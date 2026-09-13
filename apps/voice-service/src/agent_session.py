"""Voice agent orchestration: bounded tool loop, bounded context, honest wording.

The tool results — not the model's prose — decide what the user is told. If any
write failed, the model's sentence is discarded, so a hallucinated "已经打开了"
can never be spoken.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from agent_client import AgentClient, AgentError, ChatResponse, ToolCall
from agent_tools import (
    WRITE_TOOLS,
    HomeToolExecutor,
    ToolResult,
    new_operation_id,
    summarize_queries,
)

DEFAULT_MAX_TOOL_ROUNDS = 4
DEFAULT_DEADLINE_SECONDS = 20.0
DEFAULT_MAX_MESSAGES = 12

SYSTEM_PROMPT = (
    "你是一个中文家庭语音助手，负责通过提供的工具控制家里的设备。"
    "只能操作工具允许的设备，不得编造设备状态，也不要声称控制列表以外的设备。"
    "如果用户表达含糊或缺少必要信息，先用一句话追问。"
    "设备操作结果以工具返回为准，不要说工具没有报告的成功。"
    "回复要口语化、简短，适合直接朗读，不要使用列表或 Markdown。"
)


def build_system_prompt(catalog: list[dict[str, Any]]) -> str:
    """Tell the model exactly which devices exist, from the live catalog."""
    controllable = [device for device in catalog if device.get("controllable")]
    if not controllable:
        return SYSTEM_PROMPT
    described = "、".join(
        f"{device.get('name') or device['id']}（{device['id']}，位于{device.get('room_name') or device.get('room_id')}）"
        for device in controllable
    )
    return SYSTEM_PROMPT + f" 你目前可以控制：{described}。"

ERROR_TEXT = {
    "agent_auth_failed": "语音助手鉴权失败，请检查本地密钥配置。",
    "agent_unavailable": "语音助手暂时无法连接，请稍后再试。",
    "agent_rejected": "语音助手拒绝了这次请求。",
    "agent_invalid_response": "语音助手返回了无法识别的结果。",
    "agent_timeout": "这次请求处理时间过长，已停止。",
    "tool_loop_exceeded": "操作步骤过多，已停止，请说得更具体一些。",
    "backend_unavailable": "家居服务当前不可用。",
    "empty_transcript": "我没有听清，请再说一次。",
}


def _canonical(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True)


@dataclass
class AgentReply:
    text: str
    ok: bool
    error_code: str | None = None
    tool_results: list[ToolResult] = field(default_factory=list)

    @property
    def wrote_device(self) -> bool:
        return any(result.name in WRITE_TOOLS for result in self.tool_results)


class AgentSession:
    """One conversation. `reset()` is called when the loop leaves active state."""

    def __init__(
        self,
        client: AgentClient,
        executor: HomeToolExecutor,
        *,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        clock=time.monotonic,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        self.client = client
        self.executor = executor
        self.max_tool_rounds = int(max_tool_rounds)
        self.deadline_seconds = float(deadline_seconds)
        self.max_messages = int(max_messages)
        self.clock = clock
        self.system_prompt = system_prompt
        self.history: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # ------------------------------------------------------------------ public
    def reset(self) -> None:
        """End the conversation: drop context and any pending target."""
        self.history = [{"role": "system", "content": self.system_prompt}]

    def handle(self, transcript: str) -> AgentReply:
        if not isinstance(transcript, str) or not transcript.strip():
            return AgentReply(text=ERROR_TEXT["empty_transcript"], ok=False, error_code="empty_transcript")

        self.history.append({"role": "user", "content": transcript.strip()})
        deadline = self.clock() + self.deadline_seconds
        collected: list[ToolResult] = []
        write_operations: dict[str, str] = {}

        # One extra iteration beyond the tool budget so the model always gets a
        # chance to answer in words after its last tool result.
        for round_index in range(self.max_tool_rounds + 1):
            if self.clock() >= deadline:
                return self._fail("agent_timeout", collected)

            try:
                response = self.client.chat(self._messages(), self.executor.schemas())
            except AgentError as exc:
                return self._fail(exc.code, collected)

            if not response.wants_tools:
                text = self._final_text(response, collected)
                self.history.append({"role": "assistant", "content": text})
                self._trim()
                # `ok` reports whether the house actually changed, not merely that
                # a reply was produced, so a partial scene failure shows up in the
                # logs instead of only in the spoken sentence.
                writes = [result for result in collected if result.name in WRITE_TOOLS]
                return AgentReply(
                    text=text, ok=all(result.ok for result in writes), tool_results=collected
                )

            if round_index >= self.max_tool_rounds:
                # The tool budget is spent and the model still wants more.
                break

            # The assistant turn that requested the tools must be echoed back
            # before any tool result: OpenAI-compatible APIs reject a `tool`
            # message that has no preceding assistant `tool_calls`.
            self.history.append(self._assistant_tool_message(response))

            for call in response.tool_calls:
                result = self._run_tool(call, write_operations)
                collected.append(result)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result.payload(), ensure_ascii=False),
                    }
                )

        return self._fail("tool_loop_exceeded", collected)

    # ----------------------------------------------------------------- internal
    @staticmethod
    def _assistant_tool_message(response: ChatResponse) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in response.tool_calls
            ],
        }

    def _run_tool(self, call: ToolCall, write_operations: dict[str, str]) -> ToolResult:
        # A repeated identical write inside one request must replay the first
        # operation instead of commanding the device a second time.
        key = call.name + ":" + _canonical(call.arguments)
        operation_id = None
        if call.name in WRITE_TOOLS:
            operation_id = write_operations.get(key)
            if operation_id is None:
                operation_id = new_operation_id()
                write_operations[key] = operation_id
        return self.executor.execute(call.name, call.arguments, operation_id)

    def _final_text(self, response: ChatResponse, collected: list[ToolResult]) -> str:
        writes = [result for result in collected if result.name in WRITE_TOOLS]
        failed = [result for result in writes if not result.ok]
        if failed:
            # Model prose is discarded entirely: it cannot be trusted to admit a
            # failure, and a false success claim is the worst possible outcome.
            return self._failure_text(failed)
        content = (response.content or "").strip()
        if content:
            return content
        if writes:
            return "；".join(result.phrase or result.message or "已完成" for result in writes)
        summary = summarize_queries(collected)
        return summary or "没有查询到结果。"

    @staticmethod
    def _failure_text(failed: list[ToolResult]) -> str:
        parts = []
        for result in failed:
            message = result.message or "操作失败"
            if result.error_code == "confirmation_timeout":
                message = "请求已提交，但没有确认到设备状态"
            elif result.error_code == "offline":
                message = message or "设备当前离线"
            parts.append(message)
        return "；".join(dict.fromkeys(parts))

    def _messages(self) -> list[dict[str, Any]]:
        return list(self.history)

    def _trim(self) -> None:
        """Keep the system prompt plus a bounded tail, never starting on a tool."""
        if len(self.history) <= self.max_messages + 1:
            return
        head, tail = self.history[0], self.history[-(self.max_messages):]
        while tail and tail[0].get("role") == "tool":
            tail.pop(0)
        self.history = [head, *tail]

    def _fail(self, code: str, collected: list[ToolResult]) -> AgentReply:
        # A failure reply still carries the tool results so the caller can log
        # what was attempted, but the spoken text never claims success.
        return AgentReply(
            text=ERROR_TEXT.get(code, "请求失败。"), ok=False, error_code=code, tool_results=collected
        )


def create_agent_session(
    api_key: str,
    service_url: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 20.0,
    **session_options: Any,
) -> AgentSession:
    """Build the production session: DeepSeek client over the local tool executor."""
    import config

    client = AgentClient(
        api_key,
        base_url=base_url or config.agent_base_url(),
        model=model or config.agent_model(),
        timeout=timeout,
    )
    executor = HomeToolExecutor(service_url)
    # The prompt names the devices the catalog actually exposes, so the model
    # knows the real scope instead of guessing.
    session_options.setdefault("system_prompt", build_system_prompt(executor.catalog()))
    return AgentSession(client, executor, **session_options)

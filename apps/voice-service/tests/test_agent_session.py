from __future__ import annotations

import json

import pytest

from agent_client import AgentError, ChatResponse, ToolCall
from agent_session import AgentSession, SYSTEM_PROMPT
from agent_tools import ToolResult


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages_seen = []

    def chat(self, messages, tools):
        self.messages_seen.append([dict(message) for message in messages])
        outcome = self.responses.pop(0) if self.responses else ChatResponse(content="没有更多回复")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeExecutor:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def execute(self, name, arguments, operation_id=None):
        self.calls.append({"name": name, "arguments": arguments, "operation_id": operation_id})
        if self.results:
            return self.results.pop(0)
        return ToolResult(name=name, ok=True, phrase="已完成", operation_id=operation_id)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def write_call(call_id="c1", name="set_light", **arguments):
    payload = {"device_id": "living_room_light"}
    payload.update(arguments)
    return ToolCall(id=call_id, name=name, arguments=payload)


def session(client, executor, **kwargs):
    clock = kwargs.pop("clock", FakeClock())
    return AgentSession(client, executor, clock=clock, **kwargs), clock


def test_assistant_tool_calls_are_echoed_before_any_tool_result():
    """Regression: OpenAI-compatible APIs reject a `tool` message that has no
    preceding assistant `tool_calls`, which broke every real DeepSeek call."""
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(on=True)]),
        ChatResponse(content="已打开。"),
    ])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    agent.handle("打开客厅灯")

    second_call = client.messages_seen[1]
    assistant_index = next(
        index for index, message in enumerate(second_call) if message.get("role") == "assistant"
    )
    tool_index = next(
        index for index, message in enumerate(second_call) if message.get("role") == "tool"
    )
    assert assistant_index < tool_index
    echoed = second_call[assistant_index]["tool_calls"][0]
    assert echoed["function"]["name"] == "set_light"
    assert json.loads(echoed["function"]["arguments"]) == {"device_id": "living_room_light", "on": True}
    assert echoed["id"] == "c1"


def test_single_tool_call_then_spoken_reply():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(on=True)]),
        ChatResponse(content="已经为你打开客厅灯。"),
    ])
    executor = FakeExecutor([ToolResult(name="set_light", ok=True, phrase="已打开客厅灯", operation_id="op-1")])
    agent, _ = session(client, executor)

    reply = agent.handle("打开客厅灯")

    assert reply.ok
    assert reply.text == "已经为你打开客厅灯。"
    assert len(executor.calls) == 1
    # The session generates the operation id locally; the model never supplies one.
    assert executor.calls[0]["operation_id"].startswith("voice-")


def test_plain_chat_does_not_touch_any_device():
    client = FakeClient([ChatResponse(content="今天天气不错。")])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    reply = agent.handle("你好呀")

    assert reply.ok
    assert reply.text == "今天天气不错。"
    assert executor.calls == []


def test_model_prose_is_discarded_when_a_write_failed():
    """The worst possible outcome is speaking a success the device never had."""
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(on=True)]),
        ChatResponse(content="好的，客厅灯已经打开了！"),
    ])
    executor = FakeExecutor([
        ToolResult(name="set_light", ok=False, error_code="offline", message="客厅灯现在离线")
    ])
    agent, _ = session(client, executor)

    reply = agent.handle("打开客厅灯")

    assert reply.text == "客厅灯现在离线"
    assert "已经打开" not in reply.text


def test_timeout_wording_never_claims_success_or_failure():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(brightness=50)]),
        ChatResponse(content="灯已经调到 50 了。"),
    ])
    executor = FakeExecutor([
        ToolResult(name="set_light", ok=False, error_code="confirmation_timeout", message="已提交请求，但未观察到目标状态")
    ])
    agent, _ = session(client, executor)

    reply = agent.handle("把客厅灯调到 50")

    assert "没有确认到设备状态" in reply.text
    assert "失败" not in reply.text
    assert "已经" not in reply.text


def test_repeated_identical_write_in_one_turn_reuses_the_operation_id():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call("c1", on=True), write_call("c2", on=True)]),
        ChatResponse(content="已打开。"),
    ])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    agent.handle("打开客厅灯，再打开客厅灯")

    assert len(executor.calls) == 2
    assert executor.calls[0]["operation_id"] == executor.calls[1]["operation_id"]


def test_distinct_writes_get_distinct_operation_ids():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call("c1", on=True), write_call("c2", brightness=30)]),
        ChatResponse(content="已处理。"),
    ])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    agent.handle("开灯并调到 30")

    assert executor.calls[0]["operation_id"] != executor.calls[1]["operation_id"]


def test_tool_loop_is_bounded_and_reports_honestly():
    endless = lambda: ChatResponse(content=None, tool_calls=[write_call(on=True)])  # noqa: E731
    client = FakeClient([endless() for _ in range(10)])
    executor = FakeExecutor()
    agent, _ = session(client, executor, max_tool_rounds=2)

    reply = agent.handle("打开客厅灯")

    assert reply.ok is False
    assert reply.error_code == "tool_loop_exceeded"
    assert len(executor.calls) == 2
    # 2 tool rounds plus the one final chance to answer in words.
    assert len(client.messages_seen) == 3


def test_deadline_stops_the_turn_before_any_further_tool_runs():
    clock = FakeClock()
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(on=True)]),
        ChatResponse(content=None, tool_calls=[write_call(brightness=10)]),
    ])
    executor = FakeExecutor()
    agent, _ = session(client, executor, clock=clock, deadline_seconds=5.0)

    def advance(messages, tools):
        clock.now += 10.0
        return FakeClient.chat(agent.client, messages, tools)

    agent.client.chat = advance

    reply = agent.handle("打开客厅灯")

    assert reply.ok is False
    assert reply.error_code == "agent_timeout"
    # The first round already ran; the second tool call must never be reached.
    assert len(executor.calls) == 1


@pytest.mark.parametrize(
    "code",
    ["agent_auth_failed", "agent_unavailable", "agent_rejected", "agent_invalid_response"],
)
def test_llm_failures_produce_honest_text(code):
    client = FakeClient([AgentError(code)])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    reply = agent.handle("打开客厅灯")

    assert reply.ok is False
    assert reply.error_code == code
    assert reply.text
    assert executor.calls == []


def test_query_only_turn_falls_back_to_a_structured_summary():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[ToolCall(id="q1", name="query_room_status", arguments={"room": "客厅"})]),
        ChatResponse(content=""),
    ])
    executor = FakeExecutor([
        ToolResult(
            name="query_room_status",
            ok=True,
            data={"devices": [{"name": "客厅灯", "type": "light", "state": {"on": True, "brightness": 50}}]},
        )
    ])
    agent, _ = session(client, executor)

    reply = agent.handle("客厅怎么样")

    assert reply.ok
    assert "客厅灯" in reply.text
    assert "50" in reply.text


def test_empty_transcript_is_rejected_without_calling_the_model():
    client = FakeClient([ChatResponse(content="不该被调用")])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    reply = agent.handle("   ")

    assert reply.ok is False
    assert reply.error_code == "empty_transcript"
    assert client.messages_seen == []


def test_reset_clears_context_and_pending_target():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(on=True)]),
        ChatResponse(content="已打开。"),
        ChatResponse(content="再说一次吧。"),
    ])
    executor = FakeExecutor()
    agent, _ = session(client, executor)

    agent.handle("打开客厅灯")
    assert len(agent.history) > 1

    agent.reset()

    assert agent.history == [{"role": "system", "content": SYSTEM_PROMPT}]
    agent.handle("好的")
    # The second turn must not carry the first turn's messages.
    assert not any(message.get("content") == "打开客厅灯" for message in client.messages_seen[-1])


def test_history_stays_bounded_across_many_turns():
    responses = [ChatResponse(content=f"回复 {index}") for index in range(20)]
    client = FakeClient(responses)
    executor = FakeExecutor()
    agent, _ = session(client, executor, max_messages=4)

    for index in range(20):
        agent.handle(f"第 {index} 句")

    assert len(agent.history) <= 5
    assert agent.history[0]["role"] == "system"


def test_trimming_never_leaves_a_dangling_tool_message():
    client = FakeClient([
        ChatResponse(content=None, tool_calls=[write_call(on=True)]),
        ChatResponse(content="已打开。"),
    ] + [ChatResponse(content="好的。") for _ in range(6)])
    executor = FakeExecutor()
    agent, _ = session(client, executor, max_messages=2)

    agent.handle("打开客厅灯")
    for index in range(6):
        agent.handle(f"闲聊 {index}")

    assert agent.history[0]["role"] == "system"
    assert agent.history[1].get("role") != "tool"

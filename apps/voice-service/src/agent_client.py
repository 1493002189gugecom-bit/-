"""DeepSeek (OpenAI-compatible) chat completions transport for the voice agent.

Failures are reported as a small closed set of codes. Neither the API key nor any
response body is ever attached to an exception or written to a log.
"""
from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass, field
from typing import Any
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

# Closed set of failure codes the session knows how to speak about honestly.
ERROR_CODES = (
    "agent_auth_failed",
    "agent_unavailable",
    "agent_rejected",
    "agent_invalid_response",
)


class AgentError(Exception):
    def __init__(self, code: str):
        self.code = code
        # Only the fixed code enters args/repr: never the key, the URL, or a body.
        super().__init__(code)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102 - see base class
        return None


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise AgentError("agent_invalid_response")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise AgentError("agent_invalid_response") from None
    if not isinstance(parsed, dict):
        raise AgentError("agent_invalid_response")
    return parsed


class AgentClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 20.0,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("DeepSeek API key required")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.base_url + "/chat/completions",
            method="POST",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AgentError("agent_auth_failed") from None
            if exc.code >= 500:
                raise AgentError("agent_unavailable") from None
            raise AgentError("agent_rejected") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise AgentError("agent_unavailable") from None
        except ValueError:
            raise AgentError("agent_invalid_response") from None

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            # Deterministic tool choice makes the loop reproducible and testable.
            "temperature": 0,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        body = self._post(payload)
        try:
            choices = body["choices"]
            message = choices[0]["message"]
        except (KeyError, IndexError, TypeError):
            raise AgentError("agent_invalid_response") from None

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise AgentError("agent_invalid_response")

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            try:
                function = raw["function"]
                calls.append(
                    ToolCall(
                        id=str(raw.get("id") or f"call_{len(calls)}"),
                        name=str(function["name"]),
                        arguments=_parse_arguments(function.get("arguments")),
                    )
                )
            except (KeyError, TypeError):
                raise AgentError("agent_invalid_response") from None
        return ChatResponse(content=content, tool_calls=calls)

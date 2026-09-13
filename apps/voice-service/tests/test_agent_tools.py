from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from agent_client import AgentClient, AgentError
from agent_tools import (
    AC_DEVICE_IDS,
    LIGHT_DEVICE_IDS,
    TOOL_SCHEMAS,
    HomeToolExecutor,
    ToolArgumentError,
    normalize_arguments,
)

SECRET = "sk-super-secret-key-value"


class ScriptedOpener:
    """Returns one queued outcome per open() call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else {}
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()

    def __iter__(self):
        return iter([])


def chat_response(content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


# --------------------------------------------------------------------- client
def test_client_parses_content_and_tool_calls():
    client = AgentClient(SECRET, base_url="http://localhost:9")
    client.opener = ScriptedOpener([JsonResponse(chat_response(None, [tool_call("c1", "set_light", {"device_id": "living_room_light", "on": True})]))])

    response = client.chat([{"role": "user", "content": "开灯"}], list(TOOL_SCHEMAS))

    assert response.wants_tools
    assert response.tool_calls[0].name == "set_light"
    assert response.tool_calls[0].arguments == {"device_id": "living_room_light", "on": True}


def test_client_requires_an_api_key():
    with pytest.raises(ValueError, match="API key"):
        AgentClient("   ")


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (HTTPError("u", 401, "nope", {}, None), "agent_auth_failed"),
        (HTTPError("u", 403, "nope", {}, None), "agent_auth_failed"),
        (HTTPError("u", 400, "bad", {}, None), "agent_rejected"),
        (HTTPError("u", 503, "down", {}, None), "agent_unavailable"),
        (URLError("offline"), "agent_unavailable"),
        (TimeoutError(), "agent_unavailable"),
    ],
)
def test_client_maps_transport_failures_to_closed_codes(outcome, expected):
    client = AgentClient(SECRET, base_url="http://localhost:9")
    client.opener = ScriptedOpener([outcome])

    with pytest.raises(AgentError) as caught:
        client.chat([{"role": "user", "content": "hi"}], list(TOOL_SCHEMAS))

    assert caught.value.code == expected
    assert SECRET not in repr(caught.value)
    assert "Authorization" not in repr(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": 5}}]},
        {"choices": [{"message": {"content": None, "tool_calls": [{"id": "c", "function": {"name": "set_light", "arguments": "{not json"}}]}}]},
    ],
)
def test_client_rejects_malformed_bodies(payload):
    client = AgentClient(SECRET, base_url="http://localhost:9")
    client.opener = ScriptedOpener([JsonResponse(payload)])

    with pytest.raises(AgentError) as caught:
        client.chat([{"role": "user", "content": "hi"}], list(TOOL_SCHEMAS))

    assert caught.value.code == "agent_invalid_response"


def test_client_sends_bearer_token_but_never_logs_it():
    client = AgentClient(SECRET, base_url="http://localhost:9")
    opener = ScriptedOpener([JsonResponse(chat_response("好的"))])
    client.opener = opener

    client.chat([{"role": "user", "content": "hi"}], list(TOOL_SCHEMAS))

    headers = {key.lower(): value for key, value in opener.requests[0].header_items()}
    assert headers["authorization"] == "Bearer " + SECRET
    assert opener.requests[0].full_url == "http://localhost:9/chat/completions"


# ---------------------------------------------------------------------- tools
def test_narrow_device_enums_prevent_inventing_devices():
    light = next(schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "set_light")
    ac = next(schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "set_ac")

    assert light["function"]["parameters"]["properties"]["device_id"]["enum"] == list(LIGHT_DEVICE_IDS)
    assert ac["function"]["parameters"]["properties"]["device_id"]["enum"] == list(AC_DEVICE_IDS)
    with pytest.raises(ToolArgumentError):
        normalize_arguments("set_light", {"device_id": "garage_door", "on": True})


@pytest.mark.parametrize(
    "arguments",
    [
        {"device_id": "living_room_light", "brightness": 101},
        {"device_id": "living_room_light", "brightness": True},
        {"device_id": "living_room_light", "brightness": 50.5},
        {"device_id": "living_room_light", "on": "true"},
        {"device_id": "living_room_light"},
        {"device_id": "living_room_light", "on": True, "turbo": 1},
    ],
)
def test_light_arguments_are_validated_locally(arguments):
    with pytest.raises(ToolArgumentError):
        normalize_arguments("set_light", arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"device_id": "bedroom_ac", "target_temp": 15.5},
        {"device_id": "bedroom_ac", "target_temp": float("inf")},
        {"device_id": "bedroom_ac", "mode": "heat"},
        {"device_id": "bedroom_ac"},
    ],
)
def test_ac_arguments_are_validated_locally(arguments):
    with pytest.raises(ToolArgumentError):
        normalize_arguments("set_ac", arguments)


def test_invalid_arguments_never_reach_the_backend():
    executor = HomeToolExecutor("http://127.0.0.1:9")
    calls = []
    executor._request = lambda *args, **kwargs: calls.append(args) or (200, {"ok": True})

    result = executor.execute("set_light", {"device_id": "garage_door", "on": True})

    assert result.ok is False
    assert result.error_code == "unknown_tool" or result.error_code == "invalid_arguments"
    assert calls == []


def test_write_sends_the_supplied_operation_id_for_idempotency():
    executor = HomeToolExecutor("http://127.0.0.1:9")
    sent = {}

    def fake_request(method, path, query, body):
        sent.update({"method": method, "path": path, "query": query, "body": body})
        return 200, {"ok": True, "data": {"state": {"on": True}}, "phrase": "已打开客厅灯", "operation_id": "op-1"}

    executor._request = fake_request
    result = executor.execute("set_light", {"device_id": "living_room_light", "on": True}, "op-1")

    assert sent["path"] == "/tool/set_light"
    assert sent["body"]["operation_id"] == "op-1"
    assert sent["body"]["device_id"] == "living_room_light"
    assert result.ok and result.phrase == "已打开客厅灯"


def test_backend_unavailable_is_reported_without_claiming_success():
    executor = HomeToolExecutor("http://127.0.0.1:9")
    executor._request = lambda *args, **kwargs: (0, {})

    result = executor.execute("query_device_status", {"device_id": "living_room_light"})

    assert result.ok is False
    assert result.error_code == "backend_unavailable"


def test_query_reads_the_room_endpoint_without_a_body():
    executor = HomeToolExecutor("http://127.0.0.1:9")
    captured = {}

    def fake_request(method, path, query, body):
        captured.update({"method": method, "path": path, "query": query, "body": body})
        return 200, {"ok": True, "data": {"devices": []}}

    executor._request = fake_request
    executor.execute("query_room_status", {"room": "客厅"})

    assert captured["method"] == "GET"
    assert captured["path"] == "/tool/room_status"
    assert captured["query"] == {"room": "客厅"}
    assert captured["body"] is None

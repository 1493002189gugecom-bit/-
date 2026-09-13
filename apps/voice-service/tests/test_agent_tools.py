from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from agent_client import AgentClient, AgentError
from agent_tools import (
    HOME_TOOL_NAMES,
    HomeToolExecutor,
    ToolArgumentError,
    build_tool_schemas,
    normalize_arguments,
)

SECRET = "sk-super-secret-key-value"

CATALOG = [
    {"id": "living_room_light", "type": "light", "name": "客厅灯", "room_name": "客厅", "controllable": True},
    {"id": "bedroom_ac", "type": "ac", "name": "卧室空调", "room_name": "卧室", "controllable": True},
    {"id": "desk_plug", "type": "switch", "name": "智能插座", "room_name": "客厅", "controllable": True},
    {"id": "indoor_temperature", "type": "sensor", "name": "室内温度", "room_name": "客厅", "controllable": False},
]


class ScriptedOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else {}
        if isinstance(outcome, BaseException):
            raise outcome
        return JsonResponse(outcome)


class JsonResponse:
    status = 200

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
    client.opener = ScriptedOpener(
        [chat_response(None, [tool_call("c1", "set_light", {"device_id": "living_room_light", "on": True})])]
    )

    response = client.chat([{"role": "user", "content": "开灯"}], [])

    assert response.wants_tools
    assert response.tool_calls[0].name == "set_light"


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
        client.chat([{"role": "user", "content": "hi"}], [])

    assert caught.value.code == expected
    assert SECRET not in repr(caught.value)


# ---------------------------------------------------- catalog-derived surface
def test_tool_surface_is_derived_from_the_catalog():
    schemas, by_kind = build_tool_schemas(CATALOG)
    names = [schema["function"]["name"] for schema in schemas]

    assert names == ["query_room_status", "query_device_status", "set_light", "set_ac", "set_switch"]
    assert by_kind == {
        "set_light": ["living_room_light"],
        "set_ac": ["bedroom_ac"],
        "set_switch": ["desk_plug"],
    }
    # The read-only sensor is queryable but never controllable.
    assert "indoor_temperature" not in [item for ids in by_kind.values() for item in ids]


def test_a_new_device_in_the_catalog_becomes_controllable_without_code_changes():
    """This is the property that made per-device work unnecessary."""
    extended = CATALOG + [
        {"id": "kitchen_light", "type": "light", "name": "厨房灯", "room_name": "厨房", "controllable": True}
    ]

    _, by_kind = build_tool_schemas(extended)

    assert sorted(by_kind["set_light"]) == ["kitchen_light", "living_room_light"]


def test_control_tools_are_omitted_when_no_such_device_exists():
    sensor_only = [device for device in CATALOG if device["type"] == "sensor"]

    _, by_kind = build_tool_schemas(sensor_only)

    assert by_kind == {}


def test_every_control_kind_maps_to_a_declared_tool_name():
    assert set(HOME_TOOL_NAMES) == {
        "query_room_status",
        "query_device_status",
        "set_light",
        "set_ac",
        "set_switch",
        "run_scene",
    }


# ---------------------------------------------------------------- validation
def test_device_must_come_from_the_catalog():
    _, by_kind = build_tool_schemas(CATALOG)

    with pytest.raises(ToolArgumentError):
        normalize_arguments("set_light", {"device_id": "garage_door", "on": True}, by_kind)
    with pytest.raises(ToolArgumentError):
        # A real device, but the wrong tool for its type.
        normalize_arguments("set_switch", {"device_id": "living_room_light", "on": True}, by_kind)


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
    _, by_kind = build_tool_schemas(CATALOG)

    with pytest.raises(ToolArgumentError):
        normalize_arguments("set_light", arguments, by_kind)


def test_switch_requires_an_explicit_on():
    _, by_kind = build_tool_schemas(CATALOG)

    normalized = normalize_arguments("set_switch", {"device_id": "desk_plug", "on": True}, by_kind)
    assert normalized == {"device_id": "desk_plug", "on": True}

    with pytest.raises(ToolArgumentError):
        normalize_arguments("set_switch", {"device_id": "desk_plug"}, by_kind)


# ------------------------------------------------------------------ executor
def test_query_by_device_sends_the_parameter_name_the_backend_expects():
    """Regression: sending `device_id` made the backend return every device, so
    callers silently read the first one (the light) instead of the target."""
    executor = HomeToolExecutor("http://127.0.0.1:9", catalog=CATALOG)
    captured = {}

    def fake_request(method, path, query, body):
        captured.update({"method": method, "path": path, "query": query})
        return 200, {"ok": True, "data": {"devices": [{"id": "desk_plug", "state": {"on": False}}]}}

    executor._request = fake_request
    result = executor.execute("query_device_status", {"device_id": "desk_plug"})

    assert captured["query"] == {"device": "desk_plug"}
    assert result.data["devices"][0]["id"] == "desk_plug"


def test_executor_fetches_the_catalog_when_not_supplied():
    executor = HomeToolExecutor("http://127.0.0.1:9")
    executor.opener = ScriptedOpener([{"ok": True, "data": {"devices": CATALOG}}])

    names = [schema["function"]["name"] for schema in executor.schemas()]

    assert "set_switch" in names
    assert executor.device_name("desk_plug") == "智能插座"


def test_invalid_arguments_never_reach_the_backend():
    executor = HomeToolExecutor("http://127.0.0.1:9", catalog=CATALOG)
    calls = []
    executor._request = lambda *args, **kwargs: calls.append(args) or (200, {"ok": True})

    result = executor.execute("set_light", {"device_id": "garage_door", "on": True})

    assert result.ok is False
    assert calls == []


def test_switch_posts_to_its_own_endpoint_with_the_operation_id():
    executor = HomeToolExecutor("http://127.0.0.1:9", catalog=CATALOG)
    sent = {}

    def fake_request(method, path, query, body):
        sent.update({"method": method, "path": path, "body": body})
        return 200, {"ok": True, "data": {"state": {"on": True}}, "phrase": "已打开智能插座", "operation_id": "op-1"}

    executor._request = fake_request
    result = executor.execute("set_switch", {"device_id": "desk_plug", "on": True}, "op-1")

    assert sent["path"] == "/tool/set_switch"
    assert sent["body"] == {"device_id": "desk_plug", "on": True, "operation_id": "op-1"}
    assert result.ok and result.phrase == "已打开智能插座"


def test_backend_unavailable_is_reported_without_claiming_success():
    executor = HomeToolExecutor("http://127.0.0.1:9", catalog=CATALOG)
    executor._request = lambda *args, **kwargs: (0, {})

    result = executor.execute("set_switch", {"device_id": "desk_plug", "on": True})

    assert result.ok is False
    assert result.error_code == "backend_unavailable"

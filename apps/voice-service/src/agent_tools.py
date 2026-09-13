"""The voice agent's tool surface, derived from the live device catalog.

Nothing here hardcodes a device list: the executor asks home-service for its
catalog and builds one tool per controllable device type. Adding a device to
`ha_entities.json` therefore makes it voice-controllable with no code change —
which is the whole point of a whole-home voice interface.

The model still never sees a path, a URL, or a free-form device name: every
device is an enum member of a closed set taken from that catalog.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

# Device type -> the tool that acts on it.
TOOL_KIND_BY_TYPE = {"light": "set_light", "ac": "set_ac", "switch": "set_switch"}
CONTROL_KINDS = ("set_light", "set_ac", "set_switch")
READ_TOOLS = ("query_room_status", "query_device_status")
# Every tool this agent may ever expose. The concrete surface is a subset chosen
# by the catalog, never a different set of names.
HOME_TOOL_NAMES = READ_TOOLS + CONTROL_KINDS

# Value domains, which are not device-specific.
AC_MODES = ("off", "cool", "fan_only")
BRIGHTNESS_MIN, BRIGHTNESS_MAX = 0, 100
TEMP_MIN, TEMP_MAX = 16.0, 30.0


class ToolArgumentError(Exception):
    """The model produced arguments this contract does not accept."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ToolResult:
    name: str
    ok: bool
    error_code: str | None = None
    message: str | None = None
    phrase: str | None = None
    data: Any = None
    operation_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """What is handed back to the model. Never contains credentials."""
        return {
            "ok": self.ok,
            "error_code": self.error_code,
            "message": self.message,
            "phrase": self.phrase,
            "data": self.data,
        }


def new_operation_id() -> str:
    return "voice-" + uuid.uuid4().hex[:12]


# --------------------------------------------------------------------- schemas
def _device_enum(ids: list[str], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": sorted(ids), "description": description}


def build_tool_schemas(catalog: list[dict[str, Any]]):
    """Return ``(schemas, devices_by_kind)`` for one catalog snapshot."""
    devices_by_kind: dict[str, list[str]] = {}
    for device in catalog:
        kind = TOOL_KIND_BY_TYPE.get(device.get("type", ""))
        if kind and device.get("controllable"):
            devices_by_kind.setdefault(kind, []).append(device["id"])

    known_ids = [device["id"] for device in catalog]
    schemas: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "query_room_status",
                "description": "查询房间内的设备与室温。房间可用中文名（客厅、卧室）或稳定 id，省略则返回全部房间。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {"type": "string", "description": "房间名或稳定 id"}
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_device_status",
                "description": "查询某个设备或某个房间的当前状态。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_id": _device_enum(known_ids, "稳定设备 id"),
                        "room": {"type": "string", "description": "改用房间过滤时使用"},
                    },
                    "additionalProperties": False,
                },
            },
        },
    ]

    for kind in CONTROL_KINDS:
        ids = devices_by_kind.get(kind)
        if not ids:
            continue
        if kind == "set_light":
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": "set_light",
                        "description": "开关灯或设置亮度。亮度 0-100。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "device_id": _device_enum(ids, "要控制的灯"),
                                "on": {"type": "boolean"},
                                "brightness": {
                                    "type": "integer",
                                    "minimum": BRIGHTNESS_MIN,
                                    "maximum": BRIGHTNESS_MAX,
                                },
                            },
                            "required": ["device_id"],
                            "additionalProperties": False,
                        },
                    },
                }
            )
        elif kind == "set_ac":
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": "set_ac",
                        "description": "开关空调、设置模式或目标温度（16-30 度）。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "device_id": _device_enum(ids, "要控制的空调"),
                                "on": {"type": "boolean"},
                                "mode": {"type": "string", "enum": list(AC_MODES)},
                                "target_temp": {
                                    "type": "number",
                                    "minimum": TEMP_MIN,
                                    "maximum": TEMP_MAX,
                                },
                            },
                            "required": ["device_id"],
                            "additionalProperties": False,
                        },
                    },
                }
            )
        else:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": "set_switch",
                        "description": "开关插座等通断类设备。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "device_id": _device_enum(ids, "要控制的插座"),
                                "on": {"type": "boolean"},
                            },
                            "required": ["device_id", "on"],
                            "additionalProperties": False,
                        },
                    },
                }
            )
    return schemas, devices_by_kind


# ------------------------------------------------------------------ validation
_ALLOWED_ARGUMENTS = {
    "query_room_status": {"room"},
    "query_device_status": {"device_id", "room"},
    "set_light": {"device_id", "on", "brightness"},
    "set_ac": {"device_id", "on", "mode", "target_temp"},
    "set_switch": {"device_id", "on"},
}


def _require_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ToolArgumentError("invalid_arguments", f"{name} 必须是布尔值")
    return value


def _require_int(name: str, value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError("invalid_arguments", f"{name} 必须是整数")
    if not minimum <= value <= maximum:
        raise ToolArgumentError("invalid_arguments", f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _require_temp(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolArgumentError("invalid_arguments", "target_temp 必须是数字")
    number = float(value)
    if not TEMP_MIN <= number <= TEMP_MAX:
        raise ToolArgumentError(
            "invalid_arguments", f"target_temp 必须在 {TEMP_MIN:g} 到 {TEMP_MAX:g} 度之间"
        )
    return number


def _require_choice(name: str, value: Any, choices) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ToolArgumentError("invalid_arguments", f"{name} 的取值不合法")
    return value


def _optional_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError("invalid_arguments", f"{name} 必须是非空字符串")
    return value.strip()


def normalize_arguments(
    name: str,
    arguments: dict[str, Any],
    devices_by_kind: dict[str, list[str]] | None = None,
    known_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Validate against the catalog so no code lists devices by hand."""
    if name not in _ALLOWED_ARGUMENTS:
        raise ToolArgumentError("unknown_tool", f"未知工具：{name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolArgumentError("invalid_arguments", "参数必须是对象")
    unknown = set(arguments) - _ALLOWED_ARGUMENTS[name]
    if unknown:
        raise ToolArgumentError("invalid_arguments", f"不支持的参数：{', '.join(sorted(unknown))}")

    allowed_devices = list((devices_by_kind or {}).get(name) or [])
    known = list(known_ids or [])

    normalized: dict[str, Any] = {}
    if name == "query_room_status":
        if "room" in arguments:
            normalized["room"] = _optional_text("room", arguments["room"])
        return normalized

    if name == "query_device_status":
        if "device_id" in arguments:
            device_id = _optional_text("device_id", arguments["device_id"])
            if known and device_id not in known:
                raise ToolArgumentError("invalid_arguments", f"未知设备：{device_id}")
            normalized["device_id"] = device_id
        if "room" in arguments:
            normalized["room"] = _optional_text("room", arguments["room"])
        if not normalized:
            raise ToolArgumentError("invalid_arguments", "必须指定 device_id 或 room")
        return normalized

    device_id = _optional_text("device_id", arguments.get("device_id"))
    # An empty allow-list means the catalog has no such device at all, which is
    # a contract error rather than something to forward to the device.
    if allowed_devices and device_id not in allowed_devices:
        raise ToolArgumentError("invalid_arguments", f"不能控制该设备：{device_id}")
    if not allowed_devices:
        raise ToolArgumentError("invalid_arguments", "当前没有可控制的该类设备")
    normalized["device_id"] = device_id

    if name == "set_switch":
        if "on" not in arguments:
            raise ToolArgumentError("invalid_arguments", "必须指定 on")
        normalized["on"] = _require_bool("on", arguments["on"])
        return normalized

    if "on" in arguments:
        normalized["on"] = _require_bool("on", arguments["on"])

    if name == "set_light":
        if "brightness" in arguments:
            normalized["brightness"] = _require_int(
                "brightness", arguments["brightness"], BRIGHTNESS_MIN, BRIGHTNESS_MAX
            )
        if "on" not in normalized and "brightness" not in normalized:
            raise ToolArgumentError("invalid_arguments", "必须指定 on 或 brightness")
        return normalized

    if "mode" in arguments:
        normalized["mode"] = _require_choice("mode", arguments["mode"], AC_MODES)
    if "target_temp" in arguments:
        normalized["target_temp"] = _require_temp(arguments["target_temp"])
    if not {"on", "mode", "target_temp"} & set(normalized):
        raise ToolArgumentError("invalid_arguments", "必须指定 on、mode 或 target_temp")
    return normalized


# ------------------------------------------------------------------- executor
class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102 - see base class
        return None


class HomeToolExecutor:
    """Executes validated tool calls against the local home-service."""

    def __init__(self, base_url: str, timeout: float = 10.0, catalog: list[dict[str, Any]] | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # No system proxy and no redirects: the backend is loopback only, and a
        # redirected request must never carry data somewhere else.
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._catalog = catalog
        self._schemas: list[dict[str, Any]] | None = None
        self._devices_by_kind: dict[str, list[str]] = {}
        self._known_ids: list[str] = []

    # -------------------------------------------------------------- discovery
    def catalog(self) -> list[dict[str, Any]]:
        """Fetch the device catalog once; it defines the whole tool surface."""
        if self._catalog is None:
            status, body = self._request("GET", "/catalog", None, None)
            devices = (body.get("data") or {}).get("devices") if status == 200 else None
            self._catalog = devices or []
        return self._catalog

    def schemas(self) -> list[dict[str, Any]]:
        if self._schemas is None:
            self._schemas, self._devices_by_kind = build_tool_schemas(self.catalog())
            self._known_ids = [device["id"] for device in self.catalog()]
        return self._schemas

    def device_name(self, device_id: str) -> str:
        for device in self.catalog():
            if device["id"] == device_id:
                return device.get("name") or device_id
        return device_id

    # -------------------------------------------------------------- transport
    def _request(self, method: str, path: str, query: dict[str, str] | None, body: dict | None):
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        request = Request(
            url,
            method=method,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8", errors="replace"))
            except (ValueError, OSError):
                return exc.code, {}
        except (URLError, TimeoutError, OSError, ValueError):
            return 0, {}

    # -------------------------------------------------------------- execution
    def execute(self, name: str, arguments: dict[str, Any], operation_id: str | None = None) -> ToolResult:
        if name in CONTROL_KINDS:
            self.schemas()  # ensure the catalog-derived enums are loaded
        try:
            normalized = normalize_arguments(name, arguments, self._devices_by_kind, self._known_ids)
        except ToolArgumentError as exc:
            # The model is corrected, not the device: nothing is sent.
            return ToolResult(
                name=name, ok=False, error_code=exc.code, message=exc.message, arguments=arguments or {}
            )

        if name == "query_room_status":
            query = {"room": normalized["room"]} if "room" in normalized else None
            status, body = self._request("GET", "/tool/room_status", query, None)
        elif name == "query_device_status":
            # home-service names these query parameters `device`/`room`; sending
            # `device_id` silently returned every device instead of one.
            query = {
                {"device_id": "device", "room": "room"}[key]: str(value)
                for key, value in normalized.items()
            }
            status, body = self._request("GET", "/tool/device_status", query, None)
        else:
            operation_id = operation_id or new_operation_id()
            payload = dict(normalized)
            payload["operation_id"] = operation_id
            status, body = self._request("POST", f"/tool/{name}", None, payload)

        if status == 0:
            return ToolResult(
                name=name,
                ok=False,
                error_code="backend_unavailable",
                message="家居服务当前不可用",
                operation_id=operation_id,
                arguments=normalized,
            )

        result = ToolResult(
            name=name,
            ok=bool(body.get("ok")) and status < 400,
            error_code=body.get("error_code"),
            message=body.get("error"),
            phrase=body.get("phrase"),
            data=body.get("data"),
            operation_id=body.get("operation_id") or operation_id,
            arguments=normalized,
        )
        if not result.ok and not result.message:
            result.message = f"操作失败（HTTP {status}）"
        if not result.ok and not result.error_code:
            result.error_code = "request_failed"
        return result


def summarize_queries(results: list[ToolResult], device_name=None) -> str:
    """Deterministic fallback text when the model returns nothing usable."""
    lines: list[str] = []
    for result in results:
        if not result.ok:
            lines.append(result.message or "查询失败")
            continue
        data = result.data or {}
        devices = data.get("devices")
        if devices:
            for device in devices:
                state = device.get("state") or {}
                name = device.get("name") or device.get("id")
                if device.get("type") == "light":
                    if state.get("on"):
                        lines.append(f"{name}：已打开，亮度 {state.get('brightness')}")
                    else:
                        lines.append(f"{name}：已关闭")
                elif device.get("type") == "ac":
                    if state.get("on"):
                        lines.append(
                            f"{name}：已打开，模式 {state.get('mode')}，"
                            f"设定 {state.get('target_temp')} 度"
                        )
                    else:
                        lines.append(f"{name}：已关闭")
                elif device.get("type") == "sensor":
                    lines.append(f"{name}：{state.get('temperature')} 度")
                else:
                    lines.append(f"{name}：{'开' if state.get('on') else '关'}")
        for room in data.get("rooms") or []:
            temperature = room.get("simulated_temp")
            if temperature is not None:
                lines.append(f"{room.get('name')}室温 {temperature} 度")
    return "；".join(lines)

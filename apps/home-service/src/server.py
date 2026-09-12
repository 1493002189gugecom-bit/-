"""Local HTTP interface for the home state service.

Binds to 127.0.0.1 only: this service is never exposed to the LAN. It speaks
plain JSON over HTTP; the design forbids richer payloads because broadcast text
is data, not instructions.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from models import VisualObservation, now_ms
from notify import plan_notification
from state import HomeState, StateError, build_default_state
from tools import TOOL_NAMES, ToolService

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


class HomeServiceApp:
    """Transport-independent request handling, so it can be unit tested."""

    def __init__(self, state: HomeState):
        self.state = state
        self.tools = ToolService(state)

    # ------------------------------------------------------------- routing
    def handle(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        def first(name: str) -> str | None:
            values = query.get(name)
            return values[0] if values else None

        if method == "GET" and path == "/health":
            return 200, {"ok": True, "version": self.state.version, "tools": list(TOOL_NAMES)}

        if method == "GET" and path == "/state":
            since = first("since")
            return 200, self.state.sync(_int_or_none(since))

        if method == "GET" and path == "/snapshot":
            return 200, self.state.snapshot()

        if method == "GET" and path == "/broadcast/head":
            task = self.state.head_broadcast()
            return 200, {"task": None if task is None else _broadcast_payload(task, self.state)}

        if method == "POST" and path == "/broadcast/start":
            task_id = str(body.get("task_id", ""))
            try:
                task = self.state.start_broadcast(task_id)
            except StateError as exc:
                return 409, {"ok": False, "error": exc.message, "code": exc.code}
            return 200, {"ok": True, "task": _broadcast_payload(task, self.state)}

        if method == "POST" and path == "/broadcast/receipt":
            try:
                task = self.state.complete_broadcast(
                    str(body.get("task_id", "")),
                    str(body.get("receipt_id", "")),
                    bool(body.get("success", False)),
                    body.get("error"),
                )
            except StateError as exc:
                return 409, {"ok": False, "error": exc.message, "code": exc.code}
            return 200, {"ok": True, "task": _broadcast_payload(task, self.state), "phrase": self.state.broadcast_phrase(task.id)}

        if method == "POST" and path == "/tool/broadcast":
            result = self.tools.broadcast_to_room(
                str(body.get("room", "")),
                str(body.get("text", "")),
                body.get("person_ids"),
                body.get("operation_id"),
            )
            return (200 if result.ok else 400), result.to_dict()

        if method == "POST" and path == "/tool/notify":
            result = plan_notification(
                self.tools,
                list(body.get("targets", [])),
                str(body.get("text", "")),
                body.get("operation_id"),
            )
            return (200 if result.ok else 400), result.to_dict()

        if method == "POST" and path == "/tool/set_light":
            result = self.tools.set_light(
                room=body.get("room"),
                device_id=body.get("device_id"),
                on=body.get("on"),
                brightness=body.get("brightness"),
                precondition_version=body.get("precondition_version"),
                operation_id=body.get("operation_id"),
            )
            return (200 if result.ok else 400), result.to_dict()

        if method == "POST" and path == "/tool/set_ac":
            result = self.tools.set_ac(
                room=body.get("room"),
                device_id=body.get("device_id"),
                on=body.get("on"),
                mode=body.get("mode"),
                target_temp=body.get("target_temp"),
                precondition_version=body.get("precondition_version"),
                operation_id=body.get("operation_id"),
            )
            return (200 if result.ok else 400), result.to_dict()

        if method == "GET" and path == "/tool/room_status":
            result = self.tools.query_room_status(first("room"))
            return (200 if result.ok else 400), result.to_dict()

        if method == "GET" and path == "/tool/person_location":
            result = self.tools.query_person_location(first("person"))
            return (200 if result.ok else 400), result.to_dict()

        if method == "GET" and path == "/tool/device_status":
            result = self.tools.query_device_status(first("device"), first("room"))
            return (200 if result.ok else 400), result.to_dict()

        # Test-panel style mutations used by the dashboard and tests.
        if method == "POST" and path == "/test/move_person":
            try:
                person = self.state.move_person(
                    str(body.get("person_id", "")),
                    str(body.get("room_id", "")),
                    body.get("x"),
                    body.get("y"),
                )
            except StateError as exc:
                return 400, {"ok": False, "error": exc.message, "code": exc.code}
            return 200, {"ok": True, "person_id": person.id, "room_id": person.room_id}

        if method == "POST" and path == "/test/set_room_temp":
            try:
                room = self.state.set_room_temp(str(body.get("room_id", "")), float(body.get("temp", 0)))
            except (StateError, TypeError, ValueError) as exc:
                message = getattr(exc, "message", str(exc))
                return 400, {"ok": False, "error": message}
            return 200, {"ok": True, "room_id": room.id, "simulated_temp": room.simulated_temp}

        if method == "POST" and path == "/test/device_online":
            try:
                device = self.state.set_device_online(str(body.get("device_id", "")), bool(body.get("online", True)))
            except StateError as exc:
                return 400, {"ok": False, "error": exc.message, "code": exc.code}
            return 200, {"ok": True, "device_id": device.id, "online": device.online}

        if method == "POST" and path == "/test/observe":
            observation = VisualObservation(
                camera_id=str(body.get("camera_id", "cam0")),
                track_id=str(body.get("track_id", "")),
                bbox=tuple(body.get("bbox", (0, 0, 0, 0))),
                confidence=float(body.get("confidence", 0.5)),
                observed_at_ms=now_ms(),
            )
            self.state.observe(observation)
            return 200, {"ok": True, "track_id": observation.track_id}

        if method == "POST" and path == "/test/bind_track":
            try:
                observation = self.state.bind_track(str(body.get("track_id", "")), str(body.get("person_id", "")))
            except StateError as exc:
                return 400, {"ok": False, "error": exc.message, "code": exc.code}
            return 200, {"ok": True, "track_id": observation.track_id, "person_id": observation.bound_person_id}

        if method == "POST" and path == "/test/lose_track":
            self.state.lose_track(str(body.get("track_id", "")))
            return 200, {"ok": True}

        if method == "POST" and path == "/test/person_location_unknown":
            try:
                person = self.state.require_person(str(body.get("person_id", "")))
            except StateError as exc:
                return 400, {"ok": False, "error": exc.message, "code": exc.code}
            person.room_id = None
            person.x = None
            person.y = None
            person.version += 1
            return 200, {"ok": True, "person_id": person.id, "location_known": person.location_known}

        return 404, {"ok": False, "error": f"no route for {method} {path}"}


def _broadcast_payload(task, state: HomeState) -> dict[str, Any]:
    """Single source of truth for how a broadcast task is serialized."""
    return state._broadcast_view(task)


class _Handler(BaseHTTPRequestHandler):
    app: HomeServiceApp

    def log_message(self, fmt: str, *args) -> None:  # quiet console
        return

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        status, payload = self.app.handle("GET", parsed.path, parse_qs(parsed.query), {})
        self._respond(status, payload)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._read_body()
        except json.JSONDecodeError as exc:
            self._respond(400, {"ok": False, "error": f"invalid json: {exc}"})
            return
        status, payload = self.app.handle("POST", parsed.path, parse_qs(parsed.query), body)
        self._respond(status, payload)


def serve(state: HomeState, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    app = HomeServiceApp(state)
    handler = type("BoundHandler", (_Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"home-service listening on http://{host}:{port} (loopback only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "rooms.json",
    )
    parser.add_argument("--print-snapshot", action="store_true")
    args = parser.parse_args()

    if args.host != DEFAULT_HOST:
        print("refusing to bind anywhere except 127.0.0.1")
        return 2

    state = build_default_state(args.config if args.config.exists() else None)
    if args.print_snapshot:
        print(json.dumps(state.snapshot(), ensure_ascii=False, indent=2))
        return 0
    serve(state, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

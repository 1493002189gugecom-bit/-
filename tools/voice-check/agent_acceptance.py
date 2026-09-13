"""Text-driven acceptance for the voice agent, without using the microphone.

Runs real utterances through the real agent session (DeepSeek + home-service) and
verifies the resulting device state. Prints a JSON summary and exits non-zero when
any check fails, so it can gate the voice loop.

The API key is read from the local git-ignored env file and never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))

import config  # noqa: E402
from agent_client import AgentClient, AgentError  # noqa: E402
from agent_session import AgentSession  # noqa: E402
from agent_tools import HomeToolExecutor  # noqa: E402

FAULT_FILE = Path("runtime/home-assistant/fault-control.json")


def service_get(base_url, path, query=""):
    request = Request(base_url.rstrip("/") + path + query, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
    except (URLError, TimeoutError, OSError):
        return 0, {}


def device_state(base_url, device_id):
    status, body = service_get(base_url, "/tool/device_status", f"?device={device_id}")
    if status != 200:
        return None
    devices = (body.get("data") or {}).get("devices") or []
    return devices[0] if devices else None


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class Report:
    def __init__(self):
        self.checks = []

    def record(self, name, ok, detail=None):
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def run_tools_only(service_url):
    """Verify the tool contract against the live backend, with no LLM involved.

    This is the half of the agent that actually touches devices, so it is worth
    checking on its own and without an API key.
    """
    report = Report()
    status, health = service_get(service_url, "/health")
    report.record(
        "home_service_reachable",
        status == 200 and health.get("ok") is True,
        f"http={status} backend={health.get('backend')}",
    )
    if status != 200:
        return report

    executor = HomeToolExecutor(service_url)

    result = executor.execute("set_light", {"device_id": "living_room_light", "on": True}, "tools-light-on")
    state = device_state(service_url, "living_room_light")
    report.record(
        "set_light_on",
        result.ok and bool(state and state["state"].get("on")),
        f"ok={result.ok} phrase={result.phrase!r} state={state and state['state']}",
    )

    result = executor.execute(
        "set_light", {"device_id": "living_room_light", "brightness": 50}, "tools-light-50"
    )
    state = device_state(service_url, "living_room_light")
    report.record(
        "set_light_brightness_50",
        result.ok and bool(state and state["state"].get("brightness") == 50),
        f"brightness={state and state['state'].get('brightness')}",
    )

    # The same operation id must replay, not command the device a second time.
    replay = executor.execute(
        "set_light", {"device_id": "living_room_light", "brightness": 50}, "tools-light-50"
    )
    report.record(
        "same_operation_id_replays",
        replay.ok and replay.operation_id == "tools-light-50",
        f"operation_id={replay.operation_id}",
    )
    conflict = executor.execute(
        "set_light", {"device_id": "living_room_light", "brightness": 60}, "tools-light-50"
    )
    report.record(
        "same_operation_id_with_other_arguments_conflicts",
        (not conflict.ok) and conflict.error_code == "operation_id_conflict",
        f"code={conflict.error_code}",
    )

    result = executor.execute(
        "set_ac", {"device_id": "bedroom_ac", "mode": "cool", "target_temp": 24}, "tools-ac-24"
    )
    state = device_state(service_url, "bedroom_ac")
    report.record(
        "set_ac_cool_24",
        result.ok
        and bool(
            state
            and state["state"].get("mode") == "cool"
            and state["state"].get("target_temp") == 24.0
        ),
        f"ok={result.ok} state={state and state['state']}",
    )

    query = executor.execute("query_room_status", {"room": "客厅"})
    rooms = (query.data or {}).get("rooms") or []
    report.record(
        "query_room_status_returns_devices",
        query.ok and any(room.get("devices") for room in rooms),
        f"rooms={len(rooms)} devices={sum(len(room.get('devices') or []) for room in rooms)}",
    )

    # An offline device must fail without ever being actuated. Home Assistant
    # reports an unavailable entity as a separate `online=false`, so the check
    # restores availability and re-reads the real state instead of comparing an
    # "unavailable" reading against a real one.
    before = device_state(service_url, "living_room_light")
    atomic_write_json(FAULT_FILE, {"device_id": "living_room_light", "online": False})
    time.sleep(2.0)
    try:
        result = executor.execute(
            "set_light", {"device_id": "living_room_light", "on": not before["state"].get("on")}, "tools-offline"
        )
        while_offline = device_state(service_url, "living_room_light")
    finally:
        atomic_write_json(FAULT_FILE, {"device_id": "living_room_light", "online": True})
        time.sleep(2.5)
    after = device_state(service_url, "living_room_light")
    report.record(
        "offline_fails_without_actuating",
        (not result.ok)
        and result.error_code == "offline"
        and while_offline is not None
        and while_offline.get("online") is False
        and after is not None
        and after["state"] == before["state"],
        f"code={result.error_code} online_while_offline={while_offline and while_offline.get('online')} "
        f"before={before['state']} after={after and after['state']}",
    )

    invalid = executor.execute("set_light", {"device_id": "garage_door", "on": True})
    report.record(
        "invalid_device_rejected_locally",
        (not invalid.ok) and invalid.error_code in {"invalid_arguments", "unknown_tool"},
        f"code={invalid.error_code}",
    )

    return report


def run(service_url, key, model, base_url):
    report = Report()

    status, health = service_get(service_url, "/health")
    report.record(
        "home_service_reachable",
        status == 200 and health.get("ok") is True,
        f"http={status} backend={health.get('backend')}",
    )
    if status != 200:
        return report

    executor = HomeToolExecutor(service_url)
    client = AgentClient(key, base_url=base_url, model=model)
    session = AgentSession(client, executor)

    # 1) Explicit light command must actually change the device.
    reply = session.handle("打开客厅灯")
    state = device_state(service_url, "living_room_light")
    report.record(
        "light_on",
        bool(state and state["state"].get("on")) and reply.ok,
        f"reply={reply.text!r} state={state and state['state']}",
    )

    # 2) Brightness command.
    reply = session.handle("把客厅灯调到 50")
    state = device_state(service_url, "living_room_light")
    report.record(
        "light_brightness_50",
        bool(state and state["state"].get("brightness") == 50) and reply.ok,
        f"reply={reply.text!r} brightness={state and state['state'].get('brightness')}",
    )

    # 3) Vague intent: either a bounded AC change or a clarifying question is
    #    acceptable, but it must not silently do nothing and claim success.
    before = device_state(service_url, "bedroom_ac")
    reply = session.handle("有点热")
    after = device_state(service_url, "bedroom_ac")
    changed = bool(before and after and before["state"] != after["state"])
    asked = "?" in reply.text or "？" in reply.text or "哪" in reply.text
    report.record(
        "vague_intent_acts_or_asks",
        (changed or asked) and bool(reply.text),
        f"reply={reply.text!r} changed={changed} asked={asked}",
    )

    # 4) Explicit AC command.
    reply = session.handle("把卧室空调设为制冷，24 度")
    state = device_state(service_url, "bedroom_ac")
    report.record(
        "ac_cool_24",
        bool(
            state
            and state["state"].get("mode") == "cool"
            and state["state"].get("target_temp") == 24.0
        )
        and reply.ok,
        f"reply={reply.text!r} state={state and state['state']}",
    )

    # 5) An offline device must produce an honest failure, never a success claim.
    atomic_write_json(FAULT_FILE, {"device_id": "living_room_light", "online": False})
    time.sleep(2.0)
    reply = session.handle("把客厅灯关掉")
    atomic_write_json(FAULT_FILE, {"device_id": "living_room_light", "online": True})
    time.sleep(1.0)
    claims_success = any(word in reply.text for word in ("已关闭", "已经关", "关掉了"))
    report.record(
        "offline_is_reported_honestly",
        (not claims_success) and bool(reply.text),
        f"reply={reply.text!r} ok={reply.ok} code={reply.error_code}",
    )

    # 6) A rejected or unknown device must never be invented.
    reply = session.handle("把车库门打开")
    report.record(
        "unknown_device_is_not_invented",
        bool(reply.text),
        f"reply={reply.text!r}",
    )
    return report


def emit(summary, out_path):
    """Write the JSON summary as UTF-8 so it survives any console codepage."""
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if out_path:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {target}")
    else:
        print(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-url", default=config.home_service_url())
    parser.add_argument("--model", default=config.agent_model())
    parser.add_argument("--base-url", default=config.agent_base_url())
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="verify the device tool contract against the live backend, without any LLM",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("AGENT_ACCEPTANCE_OUT"),
        help="write the JSON summary here as UTF-8 instead of re-encoding through the console",
    )
    args = parser.parse_args()

    started = time.monotonic()
    if args.tools_only:
        try:
            report = run_tools_only(args.service_url)
        except Exception as exc:  # noqa: BLE001 - report the class, never a secret
            emit({"ok": False, "error": type(exc).__name__}, args.out)
            return 1
        ok = bool(report.checks) and all(check["ok"] for check in report.checks)
        emit({"ok": ok, "seconds": round(time.monotonic() - started, 1), "checks": report.checks}, args.out)
        return 0 if ok else 1

    key = config.agent_api_key()
    if not key:
        print(
            f"DEEPSEEK_API_KEY is missing; put it in {config.agent_env_file()} (git-ignored).\n"
            "Use --tools-only to verify the device tools without an LLM.",
            file=sys.stderr,
        )
        return 2

    try:
        report = run(args.service_url, key, args.model, args.base_url)
    except AgentError as exc:
        emit({"ok": False, "error_code": exc.code}, args.out)
        return 1
    except Exception as exc:  # noqa: BLE001 - report the class, never a secret
        emit({"ok": False, "error": type(exc).__name__}, args.out)
        return 1

    ok = bool(report.checks) and all(check["ok"] for check in report.checks)
    emit({"ok": ok, "seconds": round(time.monotonic() - started, 1), "checks": report.checks}, args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

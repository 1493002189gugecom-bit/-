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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-url", default=config.home_service_url())
    parser.add_argument("--model", default=config.agent_model())
    parser.add_argument("--base-url", default=config.agent_base_url())
    args = parser.parse_args()

    key = config.agent_api_key()
    if not key:
        print(
            f"DEEPSEEK_API_KEY is missing; put it in {config.agent_env_file()} (git-ignored).",
            file=sys.stderr,
        )
        return 2

    started = time.monotonic()
    try:
        report = run(args.service_url, key, args.model, args.base_url)
    except AgentError as exc:
        print(json.dumps({"ok": False, "error_code": exc.code}, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001 - report the class, never a secret
        print(json.dumps({"ok": False, "error": type(exc).__name__}, ensure_ascii=False))
        return 1

    ok = bool(report.checks) and all(check["ok"] for check in report.checks)
    print(
        json.dumps(
            {"ok": ok, "seconds": round(time.monotonic() - started, 1), "checks": report.checks},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

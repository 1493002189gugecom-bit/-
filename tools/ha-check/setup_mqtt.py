"""Idempotently configure the existing Home Assistant MQTT integration.

The broker now requires credentials, so an already-configured MQTT entry has to
be reconfigured rather than left alone. Credentials are read only from the local
git-ignored env file named by ``SHV_ENV_FILE`` and are never printed, returned,
or written into an error message.
"""
import json
import os
from pathlib import Path

from connection import request

ENV_KEYS = ("MQTT_HA_USERNAME", "MQTT_HA_PASSWORD", "MQTT_HOST", "MQTT_PORT")
# Non-secret control fields only; ``data_schema`` and credentials are excluded.
SAFE_FIELDS = ("type", "step_id", "errors", "reason")
MAX_FLOW_STEPS = 5
UI_HINT = (
    "Use Settings > Devices & services > MQTT > Reconfigure in the Home "
    "Assistant UI instead of deleting the entry."
)


def load_local_env(path):
    """Read only the known non-secret and secret MQTT keys from the local file."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        name = key.strip()
        if separator and name in ENV_KEYS:
            values.setdefault(name, value.strip())
    return values


def required(local, name):
    value = local.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is missing from the local MQTT env file")
    return value


def safe_fields(flow):
    return {key: flow.get(key) for key in SAFE_FIELDS}


def _submit(call, flow_id, payload):
    return call("POST", "/api/config/config_entries/flow/" + flow_id, payload)


def _schema_default(flow, name, fallback):
    """Preserve whatever broker/port Home Assistant already validates against."""
    for field in flow.get("data_schema") or []:
        if field.get("name") == name:
            return field.get("default", field.get("suggested_value", fallback))
    return fallback


def broker_payload(flow, local):
    return {
        "broker": _schema_default(flow, "broker", local.get("MQTT_HOST", "mosquitto")),
        "port": _schema_default(flow, "port", int(local.get("MQTT_PORT", "1883"))),
        "username": required(local, "MQTT_HA_USERNAME"),
        "password": required(local, "MQTT_HA_PASSWORD"),
    }


def _advance(call, flow, local):
    """Submit broker credentials for as many form steps as Home Assistant asks."""
    steps = 0
    while flow.get("type") == "form":
        if steps >= MAX_FLOW_STEPS:
            raise RuntimeError(
                f"MQTT config flow did not settle after {MAX_FLOW_STEPS} steps. {UI_HINT}"
            )
        steps += 1
        flow = _submit(call, flow["flow_id"], broker_payload(flow, local))
    return flow


def configure(call, local):
    """Return ``(action, flow)``; ``action`` is ``created`` or ``reconfigured``."""
    # Fail before touching Home Assistant at all if credentials are missing, so
    # a broken local file can never leave a half-started config flow behind.
    required(local, "MQTT_HA_USERNAME")
    required(local, "MQTT_HA_PASSWORD")

    entries = call("GET", "/api/config/config_entries/entry")
    mqtt = next((entry for entry in entries if entry.get("domain") == "mqtt"), None)

    if mqtt is None:
        flow = call(
            "POST",
            "/api/config/config_entries/flow",
            {"handler": "mqtt", "show_advanced_options": False},
        )
        flow = _advance(call, flow, local)
        if flow.get("type") != "create_entry":
            raise RuntimeError(
                "MQTT setup did not complete: "
                + json.dumps(safe_fields(flow), ensure_ascii=False)
                + f". {UI_HINT}"
            )
        return "created", flow

    flow = call(
        "POST",
        "/api/config/config_entries/flow",
        {"handler": "mqtt", "entry_id": mqtt["entry_id"]},
    )
    flow = _advance(call, flow, local)
    if flow.get("type") != "abort" or flow.get("reason") != "reconfigure_successful":
        raise RuntimeError(
            "MQTT reconfigure did not complete: "
            + json.dumps(safe_fields(flow), ensure_ascii=False)
            + f". {UI_HINT}"
        )
    return "reconfigured", flow


def main():
    path = os.environ.get("SHV_ENV_FILE")
    if not path:
        raise SystemExit("SHV_ENV_FILE must point at the local git-ignored MQTT env file")
    local = load_local_env(path)
    action, flow = configure(request, local)
    print(json.dumps({"action": action, **safe_fields(flow)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

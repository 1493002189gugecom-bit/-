from __future__ import annotations

import json
from pathlib import Path

import pytest

from setup_mqtt import configure, load_local_env, main

SECRET = "broker-password-value"


class ScriptedApi:
    """Records every call so tests can assert exactly what was sent."""

    def __init__(self, entries, responses):
        self.entries = entries
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, data=None):
        self.calls.append((method, path, data))
        if path == "/api/config/config_entries/entry":
            return self.entries
        return self.responses.pop(0)


def local_env(tmp_path, **overrides):
    values = {"MQTT_HA_USERNAME": "homeassistant", "MQTT_HA_PASSWORD": SECRET}
    values.update(overrides)
    path = tmp_path / "stack.env"
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8"
    )
    return load_local_env(path)


def broker_form(flow_id="f1", **defaults):
    return {
        "type": "form",
        "flow_id": flow_id,
        "step_id": "broker",
        "data_schema": [
            {"name": key, "default": value} for key, value in defaults.items()
        ],
    }


def test_fresh_install_creates_the_entry_with_credentials(tmp_path):
    api = ScriptedApi([], [broker_form(broker="mosquitto", port=1883), {"type": "create_entry"}])

    action, _ = configure(api, local_env(tmp_path))

    assert action == "created"
    assert api.calls[1] == (
        "POST",
        "/api/config/config_entries/flow",
        {"handler": "mqtt", "show_advanced_options": False},
    )
    submitted = api.calls[2][2]
    assert submitted["username"] == "homeassistant"
    assert submitted["password"] == SECRET
    assert (submitted["broker"], submitted["port"]) == ("mosquitto", 1883)


def test_existing_entry_is_reconfigured_with_schema_defaults(tmp_path):
    api = ScriptedApi(
        [{"domain": "mqtt", "entry_id": "01M2B58TKTFQDQ5BENS2NTCK9B"}],
        [
            broker_form(broker="mosquitto", port=1883, protocol="3.1.1"),
            {"type": "abort", "reason": "reconfigure_successful"},
        ],
    )

    action, _ = configure(api, local_env(tmp_path))

    assert action == "reconfigured"
    assert api.calls[1][2] == {
        "handler": "mqtt",
        "entry_id": "01M2B58TKTFQDQ5BENS2NTCK9B",
    }
    submitted = api.calls[2][2]
    # broker/port come from the live schema, never from the storage file.
    assert (submitted["broker"], submitted["port"]) == ("mosquitto", 1883)
    assert submitted["username"] == "homeassistant"


@pytest.mark.parametrize(
    "response",
    [
        {"type": "form", "flow_id": "f1", "step_id": "broker", "errors": {"base": "cannot_connect"}},
        {"type": "abort", "reason": "already_configured"},
        {"type": "create_entry"},
    ],
)
def test_unexpected_reconfigure_response_fails_safely_without_secrets(tmp_path, response):
    api = ScriptedApi(
        [{"domain": "mqtt", "entry_id": "e1"}],
        [broker_form() for _ in range(6)] + [response],
    )

    with pytest.raises(RuntimeError) as caught:
        configure(api, local_env(tmp_path))

    message = str(caught.value)
    assert "Settings > Devices & services > MQTT > Reconfigure" in message
    assert SECRET not in message


def test_missing_local_credentials_fail_before_any_request(tmp_path):
    api = ScriptedApi([{"domain": "mqtt", "entry_id": "e1"}], [broker_form()])

    with pytest.raises(RuntimeError, match="MQTT_HA_PASSWORD"):
        configure(api, local_env(tmp_path, MQTT_HA_PASSWORD=""))

    # Nothing may reach Home Assistant, not even the entry listing.
    assert api.calls == []


def test_main_requires_the_env_file_pointer(monkeypatch, capsys):
    monkeypatch.delenv("SHV_ENV_FILE", raising=False)

    with pytest.raises(SystemExit, match="SHV_ENV_FILE"):
        main()


def test_main_output_never_contains_the_password(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / "stack.env"
    env_file.write_text(
        f"MQTT_HA_USERNAME=homeassistant\nMQTT_HA_PASSWORD={SECRET}\n", encoding="utf-8"
    )
    monkeypatch.setenv("SHV_ENV_FILE", str(env_file))

    import setup_mqtt

    api = ScriptedApi(
        [{"domain": "mqtt", "entry_id": "e1"}],
        [broker_form(), {"type": "abort", "reason": "reconfigure_successful"}],
    )
    monkeypatch.setattr(setup_mqtt, "request", api)

    setup_mqtt.main()

    printed = capsys.readouterr().out
    assert SECRET not in printed
    assert json.loads(printed)["action"] == "reconfigured"


def test_env_file_reads_only_known_keys(tmp_path):
    path = tmp_path / "stack.env"
    path.write_text(
        "MQTT_USERNAME=simulator\nMQTT_PASSWORD=simulator-secret\n"
        f"MQTT_HA_USERNAME=homeassistant\nMQTT_HA_PASSWORD={SECRET}\n",
        encoding="utf-8",
    )

    values = load_local_env(path)

    # The simulator's own broker password is not needed by Home Assistant.
    assert set(values) == {"MQTT_HA_USERNAME", "MQTT_HA_PASSWORD"}

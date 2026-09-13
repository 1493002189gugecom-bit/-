from __future__ import annotations

import sys
from pathlib import Path

import pytest

import server
from operation_store import OperationStore
from server import build_app_from_environment

CATALOG = Path(__file__).parents[1] / "config" / "ha_entities.json"

BACKEND_VARIABLES = (
    "HOME_SERVICE_BACKEND",
    "HOME_ASSISTANT_URL",
    "HOME_ASSISTANT_TOKEN",
    "HA_ENTITY_CATALOG",
    "HA_OPERATION_DB",
    "HA_ENV_FILE",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in BACKEND_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    yield


def ha_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME_SERVICE_BACKEND", "ha")
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://127.0.0.1:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "unit-test-token")
    monkeypatch.setenv("HA_ENTITY_CATALOG", str(CATALOG))
    monkeypatch.setenv("HA_OPERATION_DB", str(tmp_path / "ops.sqlite3"))


def test_memory_is_the_default_only_when_the_variable_is_absent():
    app = build_app_from_environment()
    assert type(app).__name__ == "HomeServiceApp"


def test_unknown_backend_never_falls_back_to_memory(monkeypatch):
    monkeypatch.setenv("HOME_SERVICE_BACKEND", "typo")
    with pytest.raises(SystemExit, match="HOME_SERVICE_BACKEND"):
        build_app_from_environment()


@pytest.mark.parametrize(
    "missing",
    ["HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN", "HA_OPERATION_DB"],
)
def test_ha_backend_refuses_to_start_without_complete_configuration(
    monkeypatch, tmp_path, missing
):
    ha_environment(monkeypatch, tmp_path)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(SystemExit, match=missing):
        build_app_from_environment()


def test_ha_backend_reads_the_token_from_the_local_env_file(monkeypatch, tmp_path):
    ha_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)
    env_file = tmp_path / "ha.env"
    env_file.write_text(
        "HOME_ASSISTANT_TOKEN=token-from-file\n", encoding="utf-8"
    )
    monkeypatch.setenv("HA_ENV_FILE", str(env_file))

    app = build_app_from_environment()

    assert type(app).__name__ == "HAServiceApp"
    assert app.gateway.token == "token-from-file"


def test_ha_backend_reconciles_unfinished_operations_before_serving(
    monkeypatch, tmp_path
):
    ha_environment(monkeypatch, tmp_path)
    store = OperationStore(tmp_path / "ops.sqlite3")
    store.reserve(
        "leftover", "set_light", "living_room_light", {"on": True}, {"on": True}
    )
    store.transition("leftover", "submitted")

    # The device already reached the target, so recovery must confirm the
    # operation without sending a second command.
    def fake_read(self, entity):
        return {"state": "on", "attributes": {"brightness": 128}, "last_updated": "v"}

    calls = []
    monkeypatch.setattr(server.HAGateway, "read", fake_read)
    monkeypatch.setattr(
        server.HAGateway, "call", lambda self, *args: calls.append(args)
    )

    app = build_app_from_environment()

    assert app.store.get("leftover").status == "confirmed"
    assert calls == []


def test_print_snapshot_rejects_the_ha_backend(monkeypatch, tmp_path, capsys):
    ha_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["server.py", "--print-snapshot"])

    assert server.main() == 2
    assert "ha" in capsys.readouterr().out.lower()

from __future__ import annotations

import json

import pytest

import acceptance
from acceptance import atomic_write_json, normalize_state, wait_until, Report, CheckFailure


def test_atomic_write_json_leaves_no_temp_file(tmp_path):
    path = tmp_path / "nested" / "fault-control.json"

    atomic_write_json(path, {"device_id": "living_room_light", "online": False})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "device_id": "living_room_light",
        "online": False,
    }
    assert not list(path.parent.glob("*.tmp"))


def test_atomic_write_json_replaces_previous_content(tmp_path):
    path = tmp_path / "fault-control.json"
    atomic_write_json(path, {"delay_seconds": 6})
    atomic_write_json(path, {"delay_seconds": 0})

    assert json.loads(path.read_text(encoding="utf-8")) == {"delay_seconds": 0}


def test_normalize_state_converts_ha_brightness_to_percent():
    assert normalize_state(
        {"state": "on", "attributes": {"brightness": 128}}
    )["brightness_pct"] == 50
    assert normalize_state({"state": "on", "attributes": {}})["brightness_pct"] is None
    assert normalize_state(
        {"state": "cool", "attributes": {"temperature": 24}}
    )["hvac_mode"] == "cool"


def test_wait_until_returns_value_or_none():
    calls = {"count": 0}

    def eventually():
        calls["count"] += 1
        return "ready" if calls["count"] >= 3 else None

    assert wait_until(eventually, timeout=5.0, interval=0.0) == "ready"
    assert wait_until(lambda: None, timeout=0.0, interval=0.0) is None


def test_report_requires_and_raises_on_failure(capsys):
    report = Report()
    report.require("ok_check", True)
    with pytest.raises(CheckFailure):
        report.require("bad_check", False, "detail")
    assert [check["ok"] for check in report.checks] == [True, False]
    assert "bad_check" in capsys.readouterr().out


def test_hold_the_fault_file_name_in_one_place():
    # The simulator mounts its runtime directory and reads this exact name.
    assert acceptance.DEFAULT_FAULT_FILE.endswith("fault-control.json")


@pytest.mark.parametrize(
    "entity_id",
    [
        "light.shv_living_room_light",
        "climate.shv_bedroom_ac",
        "switch.shv_desk_plug",
        "sensor.shv_indoor_temperature",
    ],
)
def test_entity_ids_match_the_simulator_discovery_prefix(entity_id):
    assert entity_id.startswith(("light.", "climate.", "switch.", "sensor."))
    assert ".shv_" in entity_id
    assert entity_id in acceptance.ENTITY_IDS.values()

import copy
import json
import math

import pytest

from model import initial_state, transition, with_temperature, load_state, save_state


def test_light_and_plug_transitions_are_pure():
    state = initial_state()
    before = copy.deepcopy(state)
    changed = transition(state, "living_room_light", "set", '{"state":"ON","brightness":50}')
    assert state == before
    assert changed["living_room_light"] == {"state": "ON", "brightness": 50}
    assert transition(state, "desk_plug", "set", "ON")["desk_plug"] == {"state": "ON", "power": 60}
    assert transition(changed, "living_room_light", "set", '{"state":"OFF"}')["living_room_light"]["brightness"] == 50


@pytest.mark.parametrize("value", [-1, 101, True, None, "50", math.nan, math.inf])
def test_invalid_brightness_does_not_mutate(value):
    import json
    state = initial_state()
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        transition(state, "living_room_light", "set", json.dumps({"state": "ON", "brightness": value}))
    assert state == before


@pytest.mark.parametrize("payload", ['{}', '[]', '{"state":"on"}', '{"state":true}', '{"effect":"rainbow"}', '{"brightness":1.5}'])
def test_invalid_light_commands(payload):
    with pytest.raises(ValueError):
        transition(initial_state(), "living_room_light", "set", payload)


@pytest.mark.parametrize("value", [16, 30, 22.5])
def test_ac_temperature_bounds(value):
    assert transition(initial_state(), "bedroom_ac", "temperature/set", str(value))["bedroom_ac"]["target_temperature"] == value


@pytest.mark.parametrize("payload", ["15.9", "30.1", "NaN", "Infinity", "true", "false", "null", '"20"'])
def test_bad_ac_temperature(payload):
    with pytest.raises(ValueError):
        transition(initial_state(), "bedroom_ac", "temperature/set", payload)


@pytest.mark.parametrize("mode", ["off", "cool", "fan_only"])
def test_ac_modes(mode):
    assert transition(initial_state(), "bedroom_ac", "mode/set", mode)["bedroom_ac"]["mode"] == mode


@pytest.mark.parametrize("device,action,payload", [("desk_plug", "set", "true"), ("bedroom_ac", "mode/set", "heat"), ("unknown", "set", "ON"), ("indoor_temperature", "set", "20")])
def test_unsupported_commands(device, action, payload):
    with pytest.raises(ValueError):
        transition(initial_state(), device, action, payload)


@pytest.mark.parametrize("value", [-41, 86, True, None, "23", math.nan, math.inf])
def test_temperature_requires_finite_number(value):
    with pytest.raises(ValueError):
        with_temperature(initial_state(), value)


def test_temperature_updates_both_readings():
    state = with_temperature(initial_state(), 28.5)
    assert state["indoor_temperature"]["temperature"] == 28.5
    assert state["bedroom_ac"]["current_temperature"] == 28.5


def test_atomic_persistence_and_validation(tmp_path):
    path = tmp_path / "nested" / "state.json"
    state = transition(initial_state(), "desk_plug", "set", "ON")
    save_state(path, state)
    assert load_state(path) == state
    assert not list(path.parent.glob("*.tmp"))
    path.write_text('{"desk_plug":{"state":"ON","power":999}}')
    with pytest.raises(ValueError):
        load_state(path)


def test_absent_persistence_uses_defaults(tmp_path):
    assert load_state(tmp_path / "missing.json") == initial_state()


def test_load_rejects_missing_or_extra_devices(tmp_path):
    path = tmp_path / "state.json"
    missing = initial_state()
    del missing["desk_plug"]
    path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(ValueError, match="device set"):
        load_state(path)

    extra = initial_state()
    extra["garage_door"] = {"state": "CLOSED"}
    path.write_text(json.dumps(extra), encoding="utf-8")
    with pytest.raises(ValueError, match="device set"):
        load_state(path)


def test_load_rejects_boolean_numeric_fields(tmp_path):
    path = tmp_path / "state.json"
    state = initial_state()
    state["living_room_light"]["brightness"] = True
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="brightness"):
        load_state(path)


@pytest.mark.parametrize(
    "plug", [{"state": "OFF", "power": 60}, {"state": "ON", "power": 0}]
)
def test_load_rejects_inconsistent_plug_power(tmp_path, plug):
    path = tmp_path / "state.json"
    state = initial_state()
    state["desk_plug"] = plug
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="plug power"):
        load_state(path)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_load_rejects_non_finite_temperatures(tmp_path, value):
    path = tmp_path / "state.json"
    state = initial_state()
    state["indoor_temperature"]["temperature"] = value
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="temperature"):
        load_state(path)

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from reset_discovery import (
    PROJECT_UNIQUE_IDS,
    is_project_entity,
    prune_registry,
    reset,
    write_registry_atomically,
)


def registry_with(*entities):
    return {"version": 1, "data": {"entities": list(entities)}}


def entity(entity_id, unique_id, platform="mqtt", **extra):
    return {
        "entity_id": entity_id,
        "unique_id": unique_id,
        "platform": platform,
        "config_entry_id": "entry-1",
        **extra,
    }


def test_prune_removes_only_this_projects_mqtt_entities():
    registry = registry_with(
        entity("light.ke_ting_deng_ke_ting_deng", "shv_living_room_light"),
        entity("climate.wo_shi_kong_diao", "shv_bedroom_ac"),
        entity("light.probe_light", "shv_probe_light"),
        # An unrelated MQTT device: must survive.
        entity("sensor.other_thing", "other_unique_id"),
        # Same prefix from another integration: must survive.
        entity("light.some_light", "shv_lookalike", platform="hue"),
        # No unique_id at all: must survive.
        entity("light.manual", None),
    )

    pruned, updated = prune_registry(registry)

    assert [item["unique_id"] for item in pruned] == [
        "shv_living_room_light",
        "shv_bedroom_ac",
        "shv_probe_light",
    ]
    assert [item["unique_id"] for item in updated["data"]["entities"]] == [
        "other_unique_id",
        "shv_lookalike",
        None,
    ]
    # The caller's registry must not be mutated in place.
    assert len(registry["data"]["entities"]) == 6


def test_is_project_entity_requires_the_mqtt_platform_and_the_prefix():
    assert is_project_entity(entity("light.x", "shv_desk_plug"))
    assert not is_project_entity(entity("light.x", "shv_desk_plug", platform="esphome"))
    assert not is_project_entity(entity("light.x", "unrelated"))
    assert not is_project_entity(entity("light.x", None))


def test_project_unique_ids_match_the_simulator_discovery_contract():
    assert PROJECT_UNIQUE_IDS == (
        "shv_living_room_light",
        "shv_bedroom_ac",
        "shv_desk_plug",
        "shv_indoor_temperature",
    )


def test_write_registry_keeps_a_backup_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "core.entity_registry"
    path.write_text(
        json.dumps(registry_with(entity("light.a", "shv_a"))), encoding="utf-8"
    )

    backup = write_registry_atomically(path, registry_with())

    assert json.loads(backup.read_text(encoding="utf-8"))["data"]["entities"]
    assert json.loads(path.read_text(encoding="utf-8"))["data"]["entities"] == []
    assert not list(tmp_path.glob("*.tmp"))


def test_reset_stops_home_assistant_before_pruning_and_always_restarts(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / ".storage").mkdir(parents=True)
    path = config_dir / ".storage" / "core.entity_registry"
    path.write_text(
        json.dumps(registry_with(entity("light.a", "shv_living_room_light"))),
        encoding="utf-8",
    )
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[1] == "stop":
            # The registry must still be untouched while Home Assistant stops.
            assert json.loads(path.read_text(encoding="utf-8"))["data"]["entities"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    pruned = reset("homeassistant", config_dir, runner=runner)

    assert pruned == ["light.a"]
    assert [command[1] for command in commands] == ["stop", "start"]
    assert json.loads(path.read_text(encoding="utf-8"))["data"]["entities"] == []


def test_reset_restarts_home_assistant_even_when_pruning_fails(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / ".storage").mkdir(parents=True)
    # Invalid JSON makes the prune step raise.
    (config_dir / ".storage" / "core.entity_registry").write_text("{", encoding="utf-8")
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(json.JSONDecodeError):
        reset("homeassistant", config_dir, runner=runner)

    assert [command[1] for command in commands] == ["stop", "start"]


def test_reset_fails_clearly_when_the_registry_is_missing(tmp_path):
    with pytest.raises(RuntimeError, match="entity registry not found"):
        reset("homeassistant", tmp_path)

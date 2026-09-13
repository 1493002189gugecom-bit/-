import json

import pytest

from discovery import (
    command_publications_for_tests,
    command_topics,
    discovery_messages,
    parse_command_topic,
    state_messages,
)
from model import initial_state


def test_all_four_discovery_payloads_have_stable_ids_grouping_and_availability():
    messages = discovery_messages("house")
    assert len(messages) == 4
    payloads = [json.loads(item.payload) for item in messages]
    assert {payload["unique_id"] for payload in payloads} == {
        "shv_living_room_light",
        "shv_bedroom_ac",
        "shv_desk_plug",
        "shv_indoor_temperature",
    }
    by_id = {payload["unique_id"]: payload for payload in payloads}
    for unique_id, payload in by_id.items():
        assert payload["device"]["identifiers"] == [unique_id]
        assert payload["device"]["name"] == payload["name"]
        device_id = unique_id.removeprefix("shv_")
        assert payload["availability"] == [
            {"topic": "house/status", "payload_available": "online", "payload_not_available": "offline"},
            {"topic": f"house/{device_id}/availability", "payload_available": "online", "payload_not_available": "offline"},
        ]
        assert payload["availability_mode"] == "all"
    assert all(item.retain and item.qos == 1 for item in messages)


def test_discovery_topics_and_light_brightness_contract_are_stable():
    messages = discovery_messages("shv")
    assert [item.topic for item in messages] == [
        "homeassistant/light/shv_living_room_light/config",
        "homeassistant/climate/shv_bedroom_ac/config",
        "homeassistant/switch/shv_desk_plug/config",
        "homeassistant/sensor/shv_indoor_temperature/config",
    ]
    light = json.loads(messages[0].payload)
    assert light["schema"] == "json"
    assert light["brightness"] is True
    assert light["brightness_scale"] == 100


def test_all_known_command_topics_are_explicit_and_never_retained():
    assert command_topics("shv") == {
        "living_room_light": "shv/living_room_light/set",
        "bedroom_ac_mode": "shv/bedroom_ac/mode/set",
        "bedroom_ac_temperature": "shv/bedroom_ac/temperature/set",
        "desk_plug": "shv/desk_plug/set",
    }
    publications = command_publications_for_tests("shv")
    assert {item.topic for item in publications} == set(command_topics("shv").values())
    assert all(not item.retain for item in publications)


def test_state_messages_are_complete_retained_and_use_prefix():
    messages = state_messages(initial_state(), "house")
    assert [item.topic for item in messages] == [
        "house/living_room_light/state",
        "house/bedroom_ac/mode/state",
        "house/bedroom_ac/temperature/state",
        "house/desk_plug/state",
        "house/indoor_temperature/state",
    ]
    assert all(item.retain and item.qos == 1 for item in messages)
    assert json.loads(messages[0].payload) == {"state": "OFF", "brightness": 50}


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("shv/living_room_light/set", ("living_room_light", "set")),
        ("shv/bedroom_ac/mode/set", ("bedroom_ac", "mode/set")),
        ("shv/bedroom_ac/temperature/set", ("bedroom_ac", "temperature/set")),
        ("shv/desk_plug/set", ("desk_plug", "set")),
    ],
)
def test_parse_command_topic_accepts_only_known_commands(topic, expected):
    assert parse_command_topic(topic, "shv") == expected


@pytest.mark.parametrize(
    "topic",
    [
        "other/living_room_light/set",
        "shv/indoor_temperature/set",
        "shv/desk_plug/state",
        "shv/desk_plug/set/extra",
        "shv//set",
    ],
)
def test_parse_command_topic_rejects_unknown_commands(topic):
    with pytest.raises(ValueError, match="unknown command topic"):
        parse_command_topic(topic, "shv")

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Publication:
    topic: str
    payload: str
    retain: bool = True
    qos: int = 1


def command_topics(prefix="shv"):
    return {
        "living_room_light": f"{prefix}/living_room_light/set",
        "bedroom_ac_mode": f"{prefix}/bedroom_ac/mode/set",
        "bedroom_ac_temperature": f"{prefix}/bedroom_ac/temperature/set",
        "desk_plug": f"{prefix}/desk_plug/set",
    }


def command_publications_for_tests(prefix="shv"):
    """Describe inbound command publications without turning them into retained state."""
    return [
        Publication(topic, "", retain=False, qos=1)
        for topic in command_topics(prefix).values()
    ]


def _device(unique_id, name):
    return {"identifiers": [unique_id], "name": name, "manufacturer": "SHV"}


def _availability(prefix, device_id):
    return {
        "availability": [
            {
                "topic": f"{prefix}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
            },
            {
                "topic": f"{prefix}/{device_id}/availability",
                "payload_available": "online",
                "payload_not_available": "offline",
            },
        ],
        "availability_mode": "all",
    }


def discovery_messages(prefix="shv"):
    return [
        Publication(
            "homeassistant/light/shv_living_room_light/config",
            json.dumps(
                {
                    "name": "客厅灯",
                    "unique_id": "shv_living_room_light",
                    "device": _device("shv_living_room_light", "客厅灯"),
                    "command_topic": f"{prefix}/living_room_light/set",
                    "state_topic": f"{prefix}/living_room_light/state",
                    "schema": "json",
                    "brightness": True,
                    "brightness_scale": 100,
                    **_availability(prefix, "living_room_light"),
                },
                ensure_ascii=False,
            ),
        ),
        Publication(
            "homeassistant/climate/shv_bedroom_ac/config",
            json.dumps(
                {
                    "name": "卧室空调",
                    "unique_id": "shv_bedroom_ac",
                    "device": _device("shv_bedroom_ac", "卧室空调"),
                    "mode_command_topic": f"{prefix}/bedroom_ac/mode/set",
                    "mode_state_topic": f"{prefix}/bedroom_ac/mode/state",
                    "temperature_command_topic": f"{prefix}/bedroom_ac/temperature/set",
                    "temperature_state_topic": f"{prefix}/bedroom_ac/temperature/state",
                    "current_temperature_topic": f"{prefix}/indoor_temperature/state",
                    "modes": ["off", "cool", "fan_only"],
                    "min_temp": 16,
                    "max_temp": 30,
                    "temp_step": 0.5,
                    **_availability(prefix, "bedroom_ac"),
                },
                ensure_ascii=False,
            ),
        ),
        Publication(
            "homeassistant/switch/shv_desk_plug/config",
            json.dumps(
                {
                    "name": "智能插座",
                    "unique_id": "shv_desk_plug",
                    "device": _device("shv_desk_plug", "智能插座"),
                    "command_topic": f"{prefix}/desk_plug/set",
                    "state_topic": f"{prefix}/desk_plug/state",
                    **_availability(prefix, "desk_plug"),
                },
                ensure_ascii=False,
            ),
        ),
        Publication(
            "homeassistant/sensor/shv_indoor_temperature/config",
            json.dumps(
                {
                    "name": "室内温度",
                    "unique_id": "shv_indoor_temperature",
                    "device": _device("shv_indoor_temperature", "室内温度"),
                    "state_topic": f"{prefix}/indoor_temperature/state",
                    "device_class": "temperature",
                    "state_class": "measurement",
                    "unit_of_measurement": "°C",
                    **_availability(prefix, "indoor_temperature"),
                },
                ensure_ascii=False,
            ),
        ),
    ]


def state_messages(state, prefix="shv"):
    light = state["living_room_light"]
    ac = state["bedroom_ac"]
    plug = state["desk_plug"]
    sensor = state["indoor_temperature"]
    return [
        Publication(
            f"{prefix}/living_room_light/state",
            json.dumps(light, ensure_ascii=False, sort_keys=True),
        ),
        Publication(f"{prefix}/bedroom_ac/mode/state", ac["mode"]),
        Publication(
            f"{prefix}/bedroom_ac/temperature/state",
            str(ac["target_temperature"]),
        ),
        Publication(f"{prefix}/desk_plug/state", plug["state"]),
        Publication(
            f"{prefix}/indoor_temperature/state", str(sensor["temperature"])
        ),
    ]


def parse_command_topic(topic, prefix="shv"):
    known = {
        ("living_room_light", "set"),
        ("bedroom_ac", "mode/set"),
        ("bedroom_ac", "temperature/set"),
        ("desk_plug", "set"),
    }
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != prefix:
        raise ValueError("unknown command topic")
    device = parts[1]
    action = "/".join(parts[2:])
    if (device, action) not in known:
        raise ValueError("unknown command topic")
    return device, action

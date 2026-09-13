import copy
import json
import math
import time
from pathlib import Path

from discovery import Publication, discovery_messages, parse_command_topic, state_messages
from model import DEVICES, load_state, save_state, transition


_COMMAND_DEVICES = frozenset(DEVICES) - {"indoor_temperature"}


class SimulatorRuntime:
    def __init__(self, state_path, publisher, sleep=time.sleep, prefix="shv"):
        self._state_path = Path(state_path)
        self._publisher = publisher
        self._sleep = sleep
        self._prefix = prefix
        self._state = load_state(self._state_path)
        self._device_online = {device: True for device in DEVICES}
        self._delay_seconds = 0.0
        self._fail_next = set()

    @property
    def state(self):
        return copy.deepcopy(self._state)

    @property
    def online(self):
        return all(self._device_online.values())

    @property
    def delay_seconds(self):
        return self._delay_seconds

    def is_online(self, device):
        if device not in self._device_online:
            raise ValueError("unknown device")
        return self._device_online[device]

    def set_online(self, device, online):
        if device not in self._device_online:
            raise ValueError("unknown device")
        if not isinstance(online, bool):
            raise ValueError("online must be a boolean")
        self._device_online[device] = online
        self._publish_availability(device)

    def set_delay(self, seconds):
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise ValueError("delay must be a finite non-negative number")
        self._delay_seconds = float(seconds)

    def fail_next(self, device):
        if device not in _COMMAND_DEVICES:
            raise ValueError("unknown command device")
        self._fail_next.add(device)

    def on_connected(self):
        for publication in discovery_messages(self._prefix):
            self._publish(publication)
        self._publish(Publication(f"{self._prefix}/status", "online"))
        for device in DEVICES:
            self._publish_availability(device)
        self._publish_state()

    def handle(self, topic, payload):
        try:
            device, action = parse_command_topic(topic, self._prefix)
        except ValueError:
            self._publish_fault("unknown", "unknown_command_topic")
            return False

        if not self._device_online[device]:
            self._publish_fault(device, "offline")
            return False

        if device in self._fail_next:
            self._fail_next.remove(device)
            self._publish_fault(device, "injected_failure")
            return False

        if self._delay_seconds:
            self._sleep(self._delay_seconds)

        try:
            changed = transition(self._state, device, action, payload)
            save_state(self._state_path, changed)
        except (TypeError, ValueError, OSError):
            self._publish_fault(device, "invalid_command")
            return False

        self._state = changed
        self._publish_state()
        return True

    def _publish_state(self):
        for publication in state_messages(self._state, self._prefix):
            self._publish(publication)

    def _publish_availability(self, device):
        self._publish(
            Publication(
                f"{self._prefix}/{device}/availability",
                "online" if self._device_online[device] else "offline",
            )
        )

    def _publish_fault(self, device, error):
        payload = json.dumps(
            {"device_id": device, "error": error},
            ensure_ascii=False,
            sort_keys=True,
        )
        self._publish(
            Publication(
                f"{self._prefix}/events/fault",
                payload,
                retain=False,
                qos=1,
            )
        )

    def _publish(self, publication):
        self._publisher.publish(
            publication.topic,
            publication.payload,
            qos=publication.qos,
            retain=publication.retain,
        )

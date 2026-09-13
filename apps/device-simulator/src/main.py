import json
import os
import signal
import threading
from pathlib import Path

from discovery import command_topics
from runtime import SimulatorRuntime


def required(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise SystemExit(f"{name} is required")
    return value


def _read_fault_control(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) - {
        "device_id",
        "online",
        "delay_seconds",
        "fail_next",
    }:
        raise ValueError("invalid fault control")
    return payload


def apply_fault_control(runtime, control):
    if not isinstance(control, dict) or set(control) - {
        "device_id",
        "online",
        "delay_seconds",
        "fail_next",
    }:
        raise ValueError("invalid fault control")
    if "online" in control:
        if not isinstance(control.get("device_id"), str):
            raise ValueError("device_id is required for online control")
        runtime.set_online(control["device_id"], control["online"])
    if "delay_seconds" in control:
        runtime.set_delay(control["delay_seconds"])
    if "fail_next" in control:
        devices = control["fail_next"]
        if isinstance(devices, str):
            devices = [devices]
        if not isinstance(devices, list) or not all(
            isinstance(device, str) for device in devices
        ):
            raise ValueError("fail_next must name a device or device list")
        for device in devices:
            runtime.fail_next(device)


def _fault_file_watcher(runtime, path, stop_event, interval=0.25):
    signature = None
    while not stop_event.wait(interval):
        try:
            stat = path.stat()
            current = (stat.st_mtime_ns, stat.st_size)
            if current == signature:
                continue
            control = _read_fault_control(path)
            apply_fault_control(runtime, control)
            signature = current
        except FileNotFoundError:
            signature = None
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            # A malformed local control file must not terminate device emulation.
            continue


def graceful_shutdown(client, prefix, wait_timeout=1.0):
    """Publish a retained offline status, then disconnect exactly once.

    Shutdown must never raise: if the broker was never reachable, the client has
    already published its will (or never connected at all), and crashing on the
    way out would only hide the real connection error.
    """
    try:
        publication = client.publish(
            f"{prefix}/status", "offline", qos=1, retain=True
        )
        try:
            publication.wait_for_publish(timeout=wait_timeout)
        except (RuntimeError, ValueError, OSError):
            pass
    finally:
        try:
            client.disconnect()
        except (RuntimeError, ValueError, OSError):
            pass


def run():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise SystemExit("paho-mqtt is required") from exc

    prefix = os.environ.get("SHV_TOPIC_PREFIX", "shv").strip() or "shv"
    state_path = Path(os.environ.get("SHV_STATE_FILE", "/runtime/device-state.json"))
    fault_path_value = os.environ.get("SHV_FAULT_FILE")
    host = required("MQTT_HOST")
    port_text = os.environ.get("MQTT_PORT", "1883")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise SystemExit("MQTT_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("MQTT_PORT must be between 1 and 65535")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="shv-device-simulator",
    )
    client.username_pw_set(required("MQTT_USERNAME"), required("MQTT_PASSWORD"))
    client.will_set(f"{prefix}/status", "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    runtime = SimulatorRuntime(state_path, client, prefix=prefix)

    def on_connect(mqtt_client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            raise RuntimeError(f"mqtt connect failed: {reason_code}")
        for topic in command_topics(prefix).values():
            mqtt_client.subscribe(topic, qos=1)
        runtime.on_connected()

    def on_message(mqtt_client, userdata, message):
        runtime.handle(message.topic, message.payload.decode("utf-8", errors="replace"))

    client.on_connect = on_connect
    client.on_message = on_message

    stop_event = threading.Event()
    watcher = None
    if fault_path_value:
        watcher = threading.Thread(
            target=_fault_file_watcher,
            args=(runtime, Path(fault_path_value), stop_event),
            name="fault-file-watcher",
            daemon=True,
        )
        watcher.start()

    shutdown_started = threading.Event()

    def shutdown_once():
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        graceful_shutdown(client, prefix)

    def request_stop(signum, frame):
        stop_event.set()
        shutdown_once()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

    try:
        client.connect(host, port, keepalive=60)
        client.loop_forever()
    finally:
        stop_event.set()
        if watcher is not None:
            watcher.join(timeout=1)
        shutdown_once()


if __name__ == "__main__":
    run()

"""Reset this project's MQTT discovery entities so they get stable entity ids.

Home Assistant pins an entity's ``entity_id`` the first time a ``unique_id`` is
registered. Publishing an empty retained payload to the config topic retires the
retained Discovery message, but the registry record survives, so the entity keeps
its original id and a corrected ``object_id`` has no effect.

This tool therefore prunes the registry records themselves while Home Assistant is
stopped, and lets Discovery recreate them. It touches only records whose
``platform`` is ``mqtt`` and whose ``unique_id`` carries this project's prefix.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# unique_id values published by apps/device-simulator/src/discovery.py.
PROJECT_PREFIX = "shv_"
PROJECT_UNIQUE_IDS = (
    "shv_living_room_light",
    "shv_bedroom_ac",
    "shv_desk_plug",
    "shv_indoor_temperature",
)


def is_project_entity(record, prefix=PROJECT_PREFIX):
    """Only MQTT entities created by this project may be pruned."""
    unique_id = record.get("unique_id")
    return (
        record.get("platform") == "mqtt"
        and isinstance(unique_id, str)
        and unique_id.startswith(prefix)
    )


def prune_registry(registry, prefix=PROJECT_PREFIX):
    """Return ``(pruned_records, updated_registry)`` without mutating the input."""
    pruned = []
    kept = []
    for record in registry["data"]["entities"]:
        (pruned if is_project_entity(record, prefix) else kept).append(record)

    updated = json.loads(json.dumps(registry))
    updated["data"]["entities"] = kept
    return pruned, updated


def write_registry_atomically(path, registry):
    """Back up the registry first: this is the operator's undo button."""
    path = Path(path)
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)
    return backup


def docker(*arguments, runner=subprocess.run):
    result = runner(["docker", *arguments], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(f"docker {arguments[0]} failed: {detail}")
    return result.stdout


def wait_for_api(env_file, timeout=150.0, interval=3.0, sleep=time.sleep):
    """Wait until the Home Assistant REST API answers again after a restart."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from connection import request

    deadline = time.monotonic() + timeout
    while True:
        try:
            request("GET", "/api/config")
            return True
        except Exception:  # noqa: BLE001 - any transport failure means "not yet"
            if time.monotonic() >= deadline:
                return False
            sleep(interval)


def reset(container, config_dir, runner=subprocess.run):
    """Stop HA, prune this project's entity records, start HA again."""
    registry_path = Path(config_dir) / ".storage" / "core.entity_registry"
    if not registry_path.is_file():
        raise RuntimeError(f"entity registry not found: {registry_path}")

    docker("stop", container, runner=runner)
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        pruned, updated = prune_registry(registry)
        if pruned:
            write_registry_atomically(registry_path, updated)
    finally:
        # Home Assistant must always come back, even if pruning failed.
        docker("start", container, runner=runner)
    return [record["entity_id"] for record in pruned]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="homeassistant")
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("HA_CONFIG_DIR"),
        help="Host path of the Home Assistant config directory",
    )
    parser.add_argument("--env-file", default=os.environ.get("HA_ENV_FILE"))
    args = parser.parse_args()
    if not args.config_dir:
        raise SystemExit("--config-dir or HA_CONFIG_DIR is required")

    pruned = reset(args.container, args.config_dir)
    print(
        "pruned entity registry records: "
        + (", ".join(pruned) if pruned else "(none)")
    )
    if args.env_file:
        print("Waiting for Home Assistant to come back...")
        print(
            "Home Assistant API reachable again."
            if wait_for_api(args.env_file)
            else "Home Assistant did not answer in time; check its logs."
        )
    print("MQTT Discovery recreates the entities with stable entity ids.")


if __name__ == "__main__":
    main()

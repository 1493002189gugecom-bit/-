"""Assign each catalogued device to its Home Assistant area.

Home Assistant groups the dashboard by area, and an entity's area is stored on the
*entity* registry record. MQTT discovery cannot set it without also creating a
device, and a device block rewrites the entity id (``light.mosquitto_...``), which
would break the stable ids the whole control path depends on. So the assignment is
applied here instead, while Home Assistant is stopped.

Areas are never created: the tool only maps devices onto areas that already exist,
so a typo fails loudly instead of silently inventing a room.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_CATALOG = Path("apps/home-service/config/ha_entities.json")


def load_catalog(path) -> dict[str, dict]:
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("catalog must be a non-empty object")
    return catalog


def plan_assignments(catalog: dict[str, dict], entities: list[dict]) -> list[dict]:
    """Return the entity records that need a new area, without mutating input."""
    by_entity_id = {record.get("entity_id"): record for record in entities}
    changes = []
    for device_id, record in catalog.items():
        area_id = record.get("area_id")
        if not area_id:
            raise ValueError(f"{device_id} has no area_id")
        entity_id = record["entity_id"]
        current = by_entity_id.get(entity_id)
        if current is None:
            raise ValueError(f"{entity_id} is not registered in Home Assistant yet")
        if current.get("area_id") != area_id:
            changes.append({"entity_id": entity_id, "area_id": area_id, "previous": current.get("area_id")})
    return changes


def apply_assignments(entities: list[dict], changes: list[dict]) -> int:
    """Mutate the entity list in place; return how many records changed."""
    wanted = {change["entity_id"]: change["area_id"] for change in changes}
    applied = 0
    for record in entities:
        area_id = wanted.get(record.get("entity_id"))
        if area_id is not None and record.get("area_id") != area_id:
            record["area_id"] = area_id
            applied += 1
    return applied


def docker(*arguments, runner=subprocess.run):
    result = runner(["docker", *arguments], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(f"docker {arguments[0]} failed: {detail}")
    return result.stdout


def write_atomically(path: Path, payload) -> Path:
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return backup


def assign(container: str, config_dir, catalog_path, runner=subprocess.run) -> list[dict]:
    """Stop Home Assistant, apply the area mapping, start it again."""
    base = Path(config_dir) / ".storage"
    entity_path = base / "core.entity_registry"
    area_path = base / "core.area_registry"
    for required in (entity_path, area_path):
        if not required.is_file():
            raise RuntimeError(f"registry not found: {required}")

    catalog = load_catalog(catalog_path)
    known_areas = {area["id"] for area in json.loads(area_path.read_text(encoding="utf-8"))["data"]["areas"]}
    unknown = sorted({record["area_id"] for record in catalog.values()} - known_areas)
    if unknown:
        raise RuntimeError(f"areas do not exist in Home Assistant: {', '.join(unknown)}")

    docker("stop", container, runner=runner)
    try:
        registry = json.loads(entity_path.read_text(encoding="utf-8"))
        changes = plan_assignments(catalog, registry["data"]["entities"])
        if changes:
            apply_assignments(registry["data"]["entities"], changes)
            write_atomically(entity_path, registry)
    finally:
        # Home Assistant must come back even if the edit failed.
        docker("start", container, runner=runner)
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="homeassistant")
    parser.add_argument("--config-dir", default=os.environ.get("HA_CONFIG_DIR"))
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    args = parser.parse_args()
    if not args.config_dir:
        raise SystemExit("--config-dir or HA_CONFIG_DIR is required")

    changes = assign(args.container, args.config_dir, args.catalog)
    if not changes:
        print("every device already sits in its configured area")
        return 0
    for change in changes:
        print(f"{change['entity_id']}: {change['previous']} -> {change['area_id']}")
    print(f"assigned {len(changes)} entities; Home Assistant is restarting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

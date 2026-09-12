"""Validate the Unity manifest against the installed editor.

This exists because a package name was written from memory
(`com.unity.modules.unitywebrequestwebsocket`, which does not exist) and Unity
refused to resolve the project. The check below makes that class of mistake
impossible to commit unnoticed.

It only runs when the 2022.3 editor is installed; otherwise it is skipped rather
than silently passing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "apps" / "unity-house" / "Packages" / "manifest.json"
PROJECT_VERSION = REPO / "apps" / "unity-house" / "ProjectSettings" / "ProjectVersion.txt"

EDITOR_ROOTS = (Path(r"D:\unity\edition"), Path(r"C:\Program Files\Unity\Hub\Editor"))
CACHE_ROOT = Path.home() / "AppData" / "Local" / "Unity" / "cache" / "packages"


def _editor_version() -> str | None:
    if not PROJECT_VERSION.exists():
        return None
    for line in PROJECT_VERSION.read_text(encoding="utf-8").splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    return None


def _editor_dir() -> Path | None:
    version = _editor_version()
    if version is None:
        return None
    for root in EDITOR_ROOTS:
        candidate = root / version
        if (candidate / "Editor" / "Unity.exe").exists():
            return candidate
    return None


def _builtin_modules(editor: Path) -> set[str]:
    builtin = editor / "Editor" / "Data" / "Resources" / "PackageManager" / "BuiltInPackages"
    if not builtin.exists():
        return set()
    return {d.name for d in builtin.iterdir() if d.is_dir()}


def _cached_packages() -> set[str]:
    if not CACHE_ROOT.exists():
        return set()
    names = set()
    for path in CACHE_ROOT.rglob("*"):
        if path.is_dir() and path.name.startswith("com.unity."):
            names.add(path.name.split("@")[0])
    return names


def test_manifest_is_valid_json_with_dependencies():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    deps = data["dependencies"]
    assert isinstance(deps, dict)
    assert deps, "manifest has no dependencies"


def test_project_version_matches_user_choice():
    """The project must target the version the user asked for."""
    assert _editor_version() == "2022.3.47f1c1"


def test_no_module_named_as_a_websocket_package():
    """Regression: this exact name does not exist in Unity 2022.3."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "com.unity.modules.unitywebrequestwebsocket" not in data["dependencies"]


def test_every_dependency_resolves_on_this_machine():
    editor = _editor_dir()
    if editor is None:
        pytest.skip("Unity 2022.3 editor not installed at a known location")

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    available = _builtin_modules(editor) | _cached_packages()

    unresolved = [name for name in data["dependencies"] if name not in available]
    assert not unresolved, (
        "these manifest dependencies cannot be resolved from the installed editor "
        f"or its package cache: {unresolved}"
    )


def test_webrequest_module_present_for_websocket_support():
    """WebSocket ships inside unitywebrequest, not a separate module."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "com.unity.modules.unitywebrequest" in data["dependencies"]


SNAPSHOT_FIXTURE = REPO / "apps" / "unity-house" / "Assets" / "Tests" / "snapshot.json"


def test_snapshot_fixture_still_carries_the_contract_fields():
    """The Unity fixture must match the service, including derived fields.

    An earlier fixture was generated before two contract bugs were fixed, so it
    lacked `location_known` and `room_name`. That made the C# checks fail for the
    right reason; the danger is someone "fixing" the test by weakening it. This
    asserts the fixture carries the fields the view relies on.
    """
    if not SNAPSHOT_FIXTURE.exists():
        pytest.skip("Unity snapshot fixture not present")

    data = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))

    assert data["persons"], "fixture has no persons"
    for person in data["persons"]:
        assert "location_known" in person, "person is missing location_known"

    if data["broadcasts"]:
        for task in data["broadcasts"]:
            assert "room_name" in task, "broadcast is missing room_name"
            assert task["room_name"], "room_name must be resolved, not empty"

    assert data["rooms"] and data["devices"], "fixture must cover rooms and devices"


def test_snapshot_fixture_matches_live_service_output():
    """Regenerate the fixture if this fails: the service contract drifted."""
    if not SNAPSHOT_FIXTURE.exists():
        pytest.skip("Unity snapshot fixture not present")

    import sys as _sys

    _sys.path.insert(0, str(REPO / "apps" / "home-service" / "src"))
    from state import build_default_state  # noqa: PLC0415

    state = build_default_state(REPO / "apps" / "home-service" / "config" / "rooms.json")
    state.set_light("living_room_light", on=True, brightness=50)
    state.set_ac("bedroom_ac", on=True, mode="cool", target_temp=26)
    state.enqueue_broadcast("bedroom", "吃饭啦", ["dad"])
    live = state.snapshot()
    fixture = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))

    def key_set(payload):
        return {
            name: sorted(payload[name][0].keys())
            for name in ("rooms", "devices", "persons")
            if payload[name]
        }

    assert key_set(live) == key_set(fixture), "fixture field sets drifted from the service"
    assert sorted(live["broadcasts"][0].keys()) == sorted(fixture["broadcasts"][0].keys()), (
        "broadcast field set drifted from the service"
    )


def test_no_speculative_dependencies_are_pinned_to_unknown_versions():
    """Version pins for registry packages must match something in the cache."""
    editor = _editor_dir()
    if editor is None:
        pytest.skip("Unity 2022.3 editor not installed at a known location")

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    builtin = _builtin_modules(editor)
    cache = CACHE_ROOT
    if not cache.exists():
        pytest.skip("no Unity package cache present")

    cached_versions = {d.name for d in cache.rglob("*") if d.is_dir() and "@" in d.name}

    for name, version in data["dependencies"].items():
        if name in builtin:
            assert version == "1.0.0", f"built-in module {name} should be 1.0.0"
            continue
        assert f"{name}@{version}" in cached_versions, (
            f"{name}@{version} is not in the Unity package cache; "
            "it would need to be downloaded or the version is wrong"
        )

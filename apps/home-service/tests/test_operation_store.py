from __future__ import annotations

import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from operation_store import InvalidTransition, OperationConflict, OperationStore


def test_reserve_signature_and_canonical_idempotency(tmp_path):
    assert list(inspect.signature(OperationStore.reserve).parameters) == [
        "self",
        "id",
        "kind",
        "target_id",
        "params",
        "target",
    ]

    database = tmp_path / "ops.sqlite3"
    store = OperationStore(database)
    first = store.reserve(
        "op-1",
        "set_light",
        "living_room_light",
        {"label": "客厅", "nested": {"z": 1, "a": 2}, "brightness": 50},
        {"state": "on", "brightness": 50},
    )
    replay = store.reserve(
        "op-1",
        "set_light",
        "living_room_light",
        {"brightness": 50, "nested": {"a": 2, "z": 1}, "label": "客厅"},
        {"brightness": 50, "state": "on"},
    )

    assert first.created is True
    assert replay.created is False
    assert replay.operation == first.operation
    assert first.operation.params == {
        "brightness": 50,
        "label": "客厅",
        "nested": {"a": 2, "z": 1},
    }
    assert first.operation.target == {"brightness": 50, "state": "on"}

    with sqlite3.connect(database) as connection:
        params_json, target_json = connection.execute(
            "SELECT params_json, target_json FROM operations WHERE id = ?", ("op-1",)
        ).fetchone()
    assert params_json == '{"brightness":50,"label":"客厅","nested":{"a":2,"z":1}}'
    assert target_json == '{"brightness":50,"state":"on"}'


@pytest.mark.parametrize(
    ("kind", "target_id", "params"),
    [
        ("set_ac", "living_room_light", {"brightness": 50}),
        ("set_light", "bedroom_light", {"brightness": 50}),
        ("set_light", "living_room_light", {"brightness": 60}),
    ],
)
def test_reserve_rejects_operation_id_conflicts(tmp_path, kind, target_id, params):
    store = OperationStore(tmp_path / "ops.sqlite3")
    store.reserve(
        "op-1",
        "set_light",
        "living_room_light",
        {"brightness": 50},
        {"state": "on", "brightness": 50},
    )

    with pytest.raises(OperationConflict):
        store.reserve("op-1", kind, target_id, params, {"state": "on"})


def test_reserve_rejects_same_parameters_with_different_target(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite3")
    store.reserve(
        "op-1",
        "set_light",
        "living_room_light",
        {"brightness": 50},
        {"brightness": 50, "state": "on"},
    )

    with pytest.raises(OperationConflict):
        store.reserve(
            "op-1",
            "set_light",
            "living_room_light",
            {"brightness": 50},
            {"brightness": 50, "state": "off"},
        )


def test_database_uses_wal_mode(tmp_path):
    database = tmp_path / "ops.sqlite3"
    OperationStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_only_legal_status_transitions_are_allowed_and_payload_is_persisted(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite3")
    store.reserve("confirmed", "set_light", "light", {}, {"state": "on"})
    confirmed = store.transition("confirmed", "confirmed", result={"z": 1, "a": 2})
    assert confirmed.status == "confirmed"
    assert confirmed.result == {"a": 2, "z": 1}

    store.reserve("rejected", "set_light", "light", {}, {"state": "on"})
    rejected = store.transition(
        "rejected", "rejected", error_code="offline", error="device offline"
    )
    assert rejected.error_code == "offline"
    assert rejected.error == "device offline"

    store.reserve("submitted", "set_light", "light", {}, {"state": "on"})
    store.transition("submitted", "submitted")
    unconfirmed = store.transition(
        "submitted", "unconfirmed", error_code="confirmation_timeout"
    )
    assert unconfirmed.status == "unconfirmed"
    assert store.transition("submitted", "confirmed", result={"state": "on"}).status == "confirmed"

    for operation_id in ("confirmed", "rejected", "submitted"):
        with pytest.raises(InvalidTransition):
            store.transition(operation_id, "accepted")

    with pytest.raises(InvalidTransition):
        store.transition("confirmed", "submitted")
    with pytest.raises(InvalidTransition):
        store.transition("rejected", "confirmed")


def test_unfinished_returns_only_nonterminal_operations(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite3")
    for operation_id in ("accepted", "submitted", "unconfirmed", "confirmed", "rejected"):
        store.reserve(operation_id, "set_light", "light", {}, {"state": "on"})
    store.transition("submitted", "submitted")
    store.transition("unconfirmed", "submitted")
    store.transition("unconfirmed", "unconfirmed")
    store.transition("confirmed", "confirmed", result={"state": "on"})
    store.transition("rejected", "rejected", error_code="offline")

    operations = store.unfinished()

    assert {operation.id for operation in operations} == {"accepted", "submitted", "unconfirmed"}
    assert {operation.status for operation in operations} == {"accepted", "submitted", "unconfirmed"}
    assert store.get("confirmed").result == {"state": "on"}
    assert store.get("missing") is None


def test_two_threads_reserve_same_id_exactly_once(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite3")
    barrier = Barrier(2)

    def reserve():
        barrier.wait()
        return store.reserve(
            "shared",
            "set_light",
            "living_room_light",
            {"brightness": 50},
            {"state": "on", "brightness": 50},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = list(executor.map(lambda _: reserve(), range(2)))

    assert sorted(item.created for item in reservations) == [False, True]
    assert reservations[0].operation == reservations[1].operation


def test_concurrent_transitions_use_observed_old_status(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite3")
    store.reserve("op-1", "set_light", "light", {}, {"state": "on"})
    barrier = Barrier(2)

    def transition(status):
        barrier.wait()
        try:
            return store.transition("op-1", status).status
        except InvalidTransition:
            return "invalid"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(transition, ("confirmed", "rejected")))

    assert outcomes.count("invalid") == 1
    assert store.get("op-1").status in {"confirmed", "rejected"}

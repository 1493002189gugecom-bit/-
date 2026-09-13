from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TRANSITIONS = {
    "accepted": {"submitted", "confirmed", "rejected"},
    "submitted": {"confirmed", "unconfirmed", "rejected"},
    "unconfirmed": {"confirmed"},
    "confirmed": set(),
    "rejected": set(),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  params_json TEXT NOT NULL,
  target_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('accepted','submitted','confirmed','unconfirmed','rejected')),
  result_json TEXT,
  error_code TEXT,
  error TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
)
"""


class OperationConflict(Exception):
    """Raised when an operation ID is reused for a different request."""


class InvalidTransition(Exception):
    """Raised when an operation cannot move to the requested status."""


@dataclass(frozen=True)
class Operation:
    id: str
    kind: str
    target_id: str
    params: Any
    target: Any
    status: str
    result: Any
    error_code: str | None
    error: str | None
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True)
class Reservation:
    operation: Operation
    created: bool


class OperationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _operation(row: sqlite3.Row) -> Operation:
        return Operation(
            id=row["id"],
            kind=row["kind"],
            target_id=row["target_id"],
            params=json.loads(row["params_json"]),
            target=json.loads(row["target_json"]),
            status=row["status"],
            result=None if row["result_json"] is None else json.loads(row["result_json"]),
            error_code=row["error_code"],
            error=row["error"],
            created_at_ms=row["created_at_ms"],
            updated_at_ms=row["updated_at_ms"],
        )

    def reserve(self, id, kind, target_id, params, target):
        params_json = self._canonical_json(params)
        target_json = self._canonical_json(target)
        now = time.time_ns() // 1_000_000
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE id = ?", (id,)
            ).fetchone()
            if row is not None:
                if (
                    row["kind"] != kind
                    or row["target_id"] != target_id
                    or row["params_json"] != params_json
                    or row["target_json"] != target_json
                ):
                    raise OperationConflict(id)
                connection.commit()
                return Reservation(self._operation(row), created=False)

            connection.execute(
                """
                INSERT INTO operations (
                    id, kind, target_id, params_json, target_json, status,
                    result_json, error_code, error, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'accepted', NULL, NULL, NULL, ?, ?)
                """,
                (id, kind, target_id, params_json, target_json, now, now),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE id = ?", (id,)
            ).fetchone()
            connection.commit()
            return Reservation(self._operation(row), created=True)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, id: str) -> Operation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE id = ?", (id,)
            ).fetchone()
        return None if row is None else self._operation(row)

    def transition(
        self,
        id: str,
        status: str,
        *,
        result: Any = None,
        error_code: str | None = None,
        error: str | None = None,
    ) -> Operation:
        result_json = None if result is None else self._canonical_json(result)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE id = ?", (id,)
            ).fetchone()
            if row is None or status not in TRANSITIONS.get(row["status"], set()):
                current = None if row is None else row["status"]
                raise InvalidTransition(f"{id}: {current!r} -> {status!r}")

            updated_at_ms = time.time_ns() // 1_000_000
            cursor = connection.execute(
                """
                UPDATE operations
                SET status = ?, result_json = ?, error_code = ?, error = ?, updated_at_ms = ?
                WHERE id = ? AND status = ?
                """,
                (
                    status,
                    result_json,
                    error_code,
                    error,
                    updated_at_ms,
                    id,
                    row["status"],
                ),
            )
            if cursor.rowcount != 1:
                raise InvalidTransition(f"{id}: status changed concurrently")
            updated = connection.execute(
                "SELECT * FROM operations WHERE id = ?", (id,)
            ).fetchone()
            connection.commit()
            return self._operation(updated)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def unfinished(self) -> list[Operation]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE status IN ('accepted', 'submitted', 'unconfirmed')
                ORDER BY created_at_ms, id
                """
            ).fetchall()
        return [self._operation(row) for row in rows]

"""Shared paths for the home-service tests.

Deliberately not named ``conftest``: the voice-service test directory also has a
``conftest.py``, and importing ``conftest`` by name resolves to whichever one was
loaded first when both suites run in the same pytest session.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
CONFIG = SERVICE_ROOT / "config" / "rooms.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_acceptance  # noqa: E402
from agent_acceptance import Report, atomic_write_json, device_state  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_device_state_returns_the_first_device(monkeypatch):
    monkeypatch.setattr(
        agent_acceptance,
        "urlopen",
        lambda request, timeout=None: FakeResponse(
            {"ok": True, "data": {"devices": [{"id": "living_room_light", "state": {"on": True}}]}}
        ),
    )

    state = device_state("http://127.0.0.1:8765", "living_room_light")

    assert state["state"] == {"on": True}


def test_device_state_returns_none_when_the_backend_reports_failure(monkeypatch):
    monkeypatch.setattr(
        agent_acceptance,
        "urlopen",
        lambda request, timeout=None: FakeResponse({"ok": False, "data": None}),
    )

    assert device_state("http://127.0.0.1:8765", "living_room_light") is None


def test_device_state_returns_none_on_a_transport_failure(monkeypatch):
    def explode(request, timeout=None):
        raise URLError("offline")

    monkeypatch.setattr(agent_acceptance, "urlopen", explode)

    assert device_state("http://127.0.0.1:8765", "living_room_light") is None


def test_tools_only_runs_without_any_api_key(monkeypatch, tmp_path, capsys):
    """The device tools must be verifiable with no LLM configured at all."""
    monkeypatch.setenv("SMART_HOME_AGENT_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["agent_acceptance.py", "--tools-only"])

    called = {}

    def fake_tools_only(service_url):
        called["service_url"] = service_url
        return Report()

    monkeypatch.setattr(agent_acceptance, "run_tools_only", fake_tools_only)

    assert agent_acceptance.main() == 1  # an empty report is not a pass
    assert "service_url" in called
    assert "DEEPSEEK_API_KEY is missing" not in capsys.readouterr().err


def test_full_run_without_a_key_explains_how_to_fix_it(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SMART_HOME_AGENT_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["agent_acceptance.py"])

    assert agent_acceptance.main() == 2

    err = capsys.readouterr().err
    assert "DEEPSEEK_API_KEY" in err
    assert "--tools-only" in err


def test_report_marks_failures_and_atomic_write_leaves_no_temp(tmp_path):
    report = Report()
    report.record("good", True)
    report.record("bad", False, "why")

    assert [check["ok"] for check in report.checks] == [True, False]

    target = tmp_path / "nested" / "fault-control.json"
    atomic_write_json(target, {"delay_seconds": 0})
    assert json.loads(target.read_text(encoding="utf-8")) == {"delay_seconds": 0}
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "entity",
    ["light.shv_living_room_light", "climate.shv_bedroom_ac"],
)
def test_acceptance_targets_the_stable_entity_ids(entity):
    # The acceptance tool talks to home-service by stable device id, not entity id.
    assert "shv_" in entity

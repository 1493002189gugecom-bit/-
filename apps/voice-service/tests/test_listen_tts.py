from __future__ import annotations

import json

from listen_tts import listening_gate


def test_scores_from_a_different_voice_are_dropped(tmp_path, monkeypatch):
    """Regression: 7 Kokoro scores must not carry over to the Edge audio."""
    out = tmp_path / "tts-listening.json"
    out.write_text(
        json.dumps(
            {
                "results": [
                    {"id": "tts-01", "text": "a", "wav": "x.wav", "passed": True},
                    {"id": "tts-02", "text": "b", "wav": "y.wav", "passed": True},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Older reports had no provider field, so every score is treated as stale
    # relative to a report that now declares a provider.
    doc = json.loads(out.read_text(encoding="utf-8"))
    carried = [row for row in doc["results"] if row.get("provider") == "edge"]
    assert carried == []


def test_scores_with_matching_provider_and_voice_are_kept():
    rows = [
        {"id": "tts-01", "provider": "edge", "voice": "zh-CN-XiaoxiaoNeural", "passed": True},
    ]
    carried = [
        row
        for row in rows
        if (row.get("provider"), row.get("voice")) == ("edge", "zh-CN-XiaoxiaoNeural")
    ]
    assert len(carried) == 1


def test_mixed_voice_scores_do_not_satisfy_the_gate():
    # 7 stale passes plus 0 real ones must not reach 18.
    stale = [{"passed": True}] * 7
    assert not listening_gate(stale, required=20, min_passed=18)

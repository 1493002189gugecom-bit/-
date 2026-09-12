from __future__ import annotations

from check_asr import match_expected, normalize


def test_normalize_removes_punctuation_and_spaces():
    assert normalize("客厅， 灯！") == "客厅灯"


def test_itn_arabic_number_matches_chinese_expected_alternative():
    matched, missing = match_expected("已把空调调到26度。", ["空调", "二十六度|26度"])
    assert missing == []
    assert matched["二十六度|26度"] == "26度"


def test_percent_and_time_alternatives_match():
    _, missing = match_expected("亮度是50%，下午5点提醒。", ["百分之五十|50%", "下午五点|下午5点"])
    assert missing == []


def test_missing_concept_is_reported_as_group():
    _, missing = match_expected("打开客厅的灯", ["卧室|睡房", "灯"])
    assert missing == ["卧室|睡房"]

"""Report which Phase A recordings already exist, without recording anything.

Run: python tools/voice-check/recording_status.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parents[2]


def count_wavs(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".wav")


def count_tsv_wavs(tsv: Path) -> tuple[int, int]:
    if not tsv.exists():
        return 0, 0
    total = 0
    present = 0
    for line in tsv.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        total += 1
        wav = Path(parts[1].strip())
        if not wav.is_absolute():
            wav = REPO / wav
        present += int(wav.exists())
    return present, total


def main() -> int:
    asr_present, asr_total = count_tsv_wavs(REPO / "tools/voice-check/cases/asr-30.tsv")
    rows = [
        ("ASR 30 条（第 1 步）", asr_present, asr_total, "tools/voice-check/cases/audio/asr-*.wav"),
        ("唤醒词 小屋小屋（第 4 步）", count_wavs(REPO / "tools/voice-check/cases/audio/wake/xiaowu-xiaowu"), 20, "cases/audio/wake/xiaowu-xiaowu/"),
        ("唤醒词 你好小屋（第 4 步）", count_wavs(REPO / "tools/voice-check/cases/audio/wake/nihao-xiaowu"), 20, "cases/audio/wake/nihao-xiaowu/"),
    ]

    print(f"{'项目':<28}{'已录':>6}{'需要':>6}   位置")
    for label, present, total, where in rows:
        mark = "OK " if present >= total else "缺 "
        print(f"{mark}{label:<26}{present:>6}{total:>6}   {where}")

    noise = REPO / "tools/voice-check/cases/noise-30min"
    noise_files = [p for p in noise.rglob("*.wav")] if noise.exists() else []
    noise_seconds = 0.0
    try:
        import soundfile as sf

        for path in noise_files:
            info = sf.info(str(path))
            noise_seconds += info.frames / info.samplerate
    except Exception:  # noqa: BLE001
        noise_seconds = -1.0
    print(
        f"{'OK ' if noise_seconds >= 1800 else '缺 '}{'30 分钟负例（第 5 步）':<26}"
        f"{len(noise_files):>6}{6:>6}   共 {noise_seconds:.0f}s / 需 1800s"
    )

    self_trigger = REPO / "tools/voice-check/cases/self-trigger"
    st_files = [p for p in self_trigger.rglob("*.wav")] if self_trigger.exists() else []
    print(f"{'OK ' if st_files else '缺 '}{'声学回环（第 6 步）':<26}{len(st_files):>6}{3:>6}   cases/self-trigger/")

    print()
    if asr_present < asr_total:
        print("下一步：先跑第 1 步录音，再跑 check_asr.py。")
    elif noise_seconds < 1800 or not st_files:
        print("下一步：跑第 5、6 步采集，然后 check_wake.py。")
    else:
        print("语料已齐，可运行 check_asr.py 与 check_wake.py 出结论。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

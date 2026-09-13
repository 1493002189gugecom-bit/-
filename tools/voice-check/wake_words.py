"""Print the configured wake phrases, one per line.

Used by start_agent.ps1 so the prompt can never drift from the keyword file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))

import config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keywords-file",
        type=Path,
        default=Path("tools/voice-check/cases/wake-keywords.txt"),
    )
    args = parser.parse_args()
    words = config.wake_words(args.keywords_file)
    if not words:
        print(f"no wake words found in {args.keywords_file}", file=sys.stderr)
        return 1
    print("、".join(words))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

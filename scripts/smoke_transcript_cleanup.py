"""Offline smoke test: mask restoration, overlap dedupe, and line count.

No network and no video. Exits 0 when the transcript cleanup matches the
Douyin cases we saw (爆C, C主力建C, and a trailing newline so wc -l agrees).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core.finance_unmask import restore_masked_terms
from core.ocr_subtitle import dedupe_overlapping_captions
from core.subtitle import SubtitleResult, SubtitleSegment


def main() -> int:
    segments = [
        SubtitleSegment(0, 1, "你上一次爆C"),
        SubtitleSegment(1, 2, "C主力建C"),
        SubtitleSegment(2, 3, "主力建C"),
        SubtitleSegment(3, 4, "一轮N市下来"),
        SubtitleSegment(4, 5, "准备C底"),
        SubtitleSegment(5, 6, "滑点能吃掉你一半L润"),
        SubtitleSegment(6, 7, "别把Q亏当成机会"),
        SubtitleSegment(7, 8, "建C要慢"),
        SubtitleSegment(8, 9, "A股和CEO、C位都不该被改"),
    ]
    cleaned = dedupe_overlapping_captions(segments)
    restored = [
        SubtitleSegment(segment.start, segment.end, restore_masked_terms(segment.text))
        for segment in cleaned
    ]
    texts = [segment.text for segment in restored]
    expected = [
        "你上一次爆仓",
        "主力建仓",
        "一轮牛市下来",
        "准备抄底",
        "滑点能吃掉你一半利润",
        "别把全亏当成机会",
        "建仓要慢",
        "A股和CEO、C位都不该被改",
    ]
    if texts != expected:
        print("cleanup mismatch:", file=sys.stderr)
        for line in texts:
            print(f"  {line}", file=sys.stderr)
        return 1

    result = SubtitleResult(segments=restored, source="ocr")
    with tempfile.TemporaryDirectory(prefix="vidnotek_cleanup_") as tmp:
        path = Path(tmp) / "transcript.txt"
        result.save_txt(path)
        raw = path.read_bytes()
        file_lines = path.read_text(encoding="utf-8").splitlines()
        newline_count = raw.count(b"\n")
        if not raw.endswith(b"\n") or newline_count != len(file_lines) or len(file_lines) != len(restored):
            print(
                f"line count mismatch: newlines={newline_count} "
                f"splitlines={len(file_lines)} segments={len(restored)}",
                file=sys.stderr,
            )
            return 1
        print(f"{len(file_lines)} lines via ocr")
        print("\n".join(file_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

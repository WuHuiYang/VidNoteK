"""OCR burned-in subtitles from a video file.

Many short videos burn captions into the picture and play loud music, so
speech-to-text comes out garbled while the on-screen text is readable.
This sampler crops the caption band, OCRs it, and merges consecutive
identical lines into timed segments.
"""

from __future__ import annotations

import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from .config import AppConfig
from .ffmpeg_util import (
    choose_subtitle_crop,
    extract_cropped_frames,
    extract_frame_at,
    ffprobe_duration,
    ffprobe_video_size,
    has_video_stream,
)
from .subtitle import SubtitleResult, SubtitleSegment

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ENGINE = None


class OCRUnavailable(RuntimeError):
    """Raised when the Chinese OCR library is not installed."""


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def ocr_burned_subtitles(
    video_path: Path,
    config: AppConfig | None = None,
    work_dir: Path | None = None,
) -> SubtitleResult:
    """Sample frames and OCR the burned-in caption band."""
    config = config or AppConfig()
    if not has_video_stream(video_path):
        return SubtitleResult(segments=[], source="ocr")

    interval = _interval_for(video_path, config.asr.ocr_interval)
    width, height = ffprobe_video_size(video_path)
    crop = choose_subtitle_crop(width, height, config.asr.ocr_bottom_ratio)
    engine = _get_engine()

    def _run(frame_dir: Path) -> SubtitleResult:
        frames = extract_cropped_frames(video_path, frame_dir, interval, crop)
        samples = [(timestamp, _ocr_image(engine, path)) for timestamp, path in frames]
        samples = drop_watermark_lines(samples)
        duration = ffprobe_duration(video_path)
        segments = merge_ocr_samples(samples, interval, duration)
        return SubtitleResult(segments=segments, source="ocr", language="zh")

    if work_dir is None:
        with tempfile.TemporaryDirectory(prefix="noteking_ocr_") as tmp:
            return _run(Path(tmp))
    frame_dir = work_dir / "ocr_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    return _run(frame_dir)


def burned_in_subtitles_likely(
    video_path: Path,
    config: AppConfig | None = None,
    samples: int = 6,
) -> bool:
    """Return True when a few frames already show caption-like text."""
    config = config or AppConfig()
    if not ocr_available() or not has_video_stream(video_path):
        return False
    duration = ffprobe_duration(video_path)
    if duration <= 0:
        times = [0.4]
    else:
        fractions = [0.12, 0.28, 0.44, 0.58, 0.74, 0.88][:samples]
        times = [max(0.2, duration * fraction) for fraction in fractions]
    width, height = ffprobe_video_size(video_path)
    crop = choose_subtitle_crop(width, height, config.asr.ocr_bottom_ratio)
    engine = _get_engine()
    hits = 0
    with tempfile.TemporaryDirectory(prefix="noteking_ocr_probe_") as tmp:
        root = Path(tmp)
        for index, timestamp in enumerate(times):
            dest = root / f"probe_{index}.jpg"
            if not extract_frame_at(video_path, timestamp, dest, vf=f"{crop.vf},scale=960:-2"):
                continue
            if text_is_subtitle(_ocr_image(engine, dest)):
                hits += 1
    needed = 1 if len(times) < 3 else 2
    return hits >= needed


def merge_ocr_samples(
    samples: list[tuple[float, str]],
    interval: float,
    duration: float = 0.0,
) -> list[SubtitleSegment]:
    """Collapse consecutive near-duplicate OCR lines into segments.

    A single empty sample between two equal lines is treated as a miss,
    not as a new caption.
    """
    segments: list[SubtitleSegment] = []
    current = ""
    start = 0.0
    end = 0.0
    gap = 0

    def close() -> None:
        nonlocal current, gap
        if not current:
            return
        stop = end + interval
        if duration > 0:
            stop = min(stop, duration)
        if stop < start:
            stop = start
        segments.append(SubtitleSegment(start=start, end=stop, text=current))
        current = ""
        gap = 0

    for timestamp, text in samples:
        text = (text or "").strip()
        if not text:
            if current:
                gap += 1
                if gap > 1:
                    close()
                else:
                    end = timestamp
            continue
        if not current:
            current, start, end, gap = text, timestamp, timestamp, 0
            continue
        if _similar(text, current):
            if len(text) > len(current):
                current = text
            end = timestamp
            gap = 0
            continue
        close()
        current, start, end, gap = text, timestamp, timestamp, 0
    close()
    return segments


def drop_watermark_lines(
    samples: list[tuple[float, str]],
    min_count: int = 8,
    fraction: float = 0.7,
) -> list[tuple[float, str]]:
    """Drop a line that stays on screen for most of the video (a watermark)."""
    texts = [text for _, text in samples if text]
    if len(texts) < min_count:
        return samples
    counts: dict[str, int] = {}
    for text in texts:
        counts[text] = counts.get(text, 0) + 1
    banned = {text for text, count in counts.items() if count / len(texts) >= fraction}
    if not banned:
        return samples
    return [(timestamp, "" if text in banned else text) for timestamp, text in samples]


def text_is_subtitle(text: str) -> bool:
    if cjk_count(text) >= 2:
        return True
    return len(re.findall(r"[A-Za-z]", text)) >= 4


def cjk_count(text: str) -> int:
    return len(_CJK.findall(text or ""))


def _interval_for(video_path: Path, interval: float) -> float:
    interval = interval if interval and interval > 0 else 0.5
    duration = ffprobe_duration(video_path)
    max_frames = 2400
    if duration > 0 and duration / interval > max_frames:
        return duration / max_frames
    return interval


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OCRUnavailable(
                "Burned-in subtitle OCR needs rapidocr-onnxruntime. "
                "Install with: pip install 'rapidocr-onnxruntime>=1.3.24'"
            ) from exc
        _ENGINE = RapidOCR()
    return _ENGINE


def _ocr_image(engine, image_path: Path) -> str:
    try:
        output = engine(str(image_path))
    except Exception:
        return ""
    result = output[0] if isinstance(output, tuple) else output
    return pick_ocr_text(result)


def pick_ocr_text(result) -> str:
    """Choose the caption line from one RapidOCR result list."""
    if not result:
        return ""
    items: list[tuple[float, str]] = []
    for row in result:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        box, text = row[0], str(row[1])
        score = float(row[2]) if len(row) > 2 else 1.0
        if score < 0.45:
            continue
        cleaned = normalize_ocr_text(text)
        if not text_is_subtitle(cleaned):
            continue
        try:
            y_pos = sum(point[1] for point in box) / len(box)
        except Exception:
            y_pos = 0.0
        items.append((y_pos, cleaned))
    if not items:
        return ""
    items.sort(key=lambda item: item[0])
    return items[-1][1]


def normalize_ocr_text(text: str) -> str:
    text = (text or "").strip()
    if cjk_count(text) >= 2:
        text = re.sub(r"\s+", "", text)
    else:
        text = re.sub(r"\s+", " ", text).strip()
    return text.strip("|_-~·")


def _similar(left: str, right: str) -> bool:
    a = _compare_key(left)
    b = _compare_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 4 and shorter in longer and len(shorter) / len(longer) >= 0.6:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.86


def _compare_key(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?:：；;\"'“”‘’]", "", text).lower()

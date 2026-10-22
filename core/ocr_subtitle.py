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
    """True when either RapidOCR 3.x or the older onnxruntime package imports."""
    for name in ("rapidocr", "rapidocr_onnxruntime"):
        try:
            __import__(name)
            return True
        except ImportError:
            continue
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
        segments = dedupe_overlapping_captions(segments)
        segments = _restore_finance_masks(segments, config)
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
            current = _prefer_caption(current, text)
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


def dedupe_overlapping_captions(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    """Drop caption bleed copied from the neighboring line.

    A transition frame often glues the previous line's last letter onto the
    next caption (``爆C`` + ``主力建C`` becomes ``C主力建C``) or stores both
    lines in one sample. Keep the real caption and the new one, not the join.
    """
    texts = [segment.text.strip() for segment in segments if segment.text and segment.text.strip()]
    owners = [segment for segment in segments if segment.text and segment.text.strip()]
    if not texts:
        return []

    index = 0
    while index < len(texts) - 1:
        current, nxt = texts[index], texts[index + 1]
        if len(nxt) >= 2 and len(current) > len(nxt) and current.endswith(nxt):
            remain = current[: -len(nxt)].strip("，。！？、 ")
            if _keep_caption(remain):
                texts[index] = remain
            else:
                del texts[index]
                del owners[index]
                continue
        index += 1

    cleaned_text: list[str] = []
    cleaned_owners: list[SubtitleSegment] = []
    for text, owner in zip(texts, owners):
        if cleaned_text:
            prev = cleaned_text[-1]
            if text == prev:
                continue
            if len(prev) >= 2 and text.startswith(prev) and len(text) > len(prev):
                remain = text[len(prev):].strip("，。！？、 ")
                if not _keep_caption(remain):
                    continue
                text = remain
            else:
                overlap = _partial_overlap(prev, text)
                if overlap:
                    remain = text[overlap:].strip("，。！？、 ")
                    if not remain or remain == prev or not _keep_caption(remain):
                        continue
                    text = remain
            if text == prev:
                continue
        cleaned_text.append(text)
        cleaned_owners.append(owner)

    result: list[SubtitleSegment] = []
    for text, owner in zip(cleaned_text, cleaned_owners):
        result.append(SubtitleSegment(start=owner.start, end=owner.end, text=text))
    return result


def _keep_caption(text: str) -> bool:
    """A leftover is still a caption when it is a short masked word such as 爆C."""
    text = (text or "").strip()
    if text_is_subtitle(text):
        return True
    return cjk_count(text) >= 1 and len(text) >= 2


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
        _ENGINE = _load_engine()
    return _ENGINE


def _load_engine():
    """Prefer RapidOCR 3.x (Python 3.13) and fall back to rapidocr-onnxruntime."""
    errors: list[str] = []
    try:
        from rapidocr import RapidOCR
        # v3 logs model paths at INFO on first load; keep the CLI quiet.
        return RapidOCR(params={"Global.log_level": "error"})
    except ImportError as exc:
        errors.append(str(exc))
    try:
        from rapidocr_onnxruntime import RapidOCR
        return RapidOCR()
    except ImportError as exc:
        errors.append(str(exc))
    detail = "; ".join(errors) or "neither package is installed"
    raise OCRUnavailable(
        "Burned-in subtitle OCR needs rapidocr (Python 3.8–3.13). "
        "Install with: pip install 'rapidocr>=3.0' 'onnxruntime>=1.16'. "
        f"Details: {detail}"
    )


def _ocr_image(engine, image_path: Path) -> str:
    try:
        output = engine(str(image_path))
    except Exception:
        return ""
    return pick_ocr_text(rows_from_ocr_output(output))


def rows_from_ocr_output(output) -> list:
    """Normalize RapidOCR 3 objects and the older ``(rows, elapsed)`` tuple."""
    if output is None:
        return []
    if isinstance(output, tuple):
        output = output[0]
    txts = getattr(output, "txts", None)
    if txts:
        boxes = getattr(output, "boxes", None)
        scores = getattr(output, "scores", None)
        rows = []
        for index, text in enumerate(txts):
            box = boxes[index] if boxes is not None and index < len(boxes) else [[0, 0]] * 4
            score = float(scores[index]) if scores is not None and index < len(scores) else 1.0
            rows.append([box, text, score])
        return rows
    if isinstance(output, list):
        return output
    return []


def _restore_finance_masks(segments: list[SubtitleSegment], config: AppConfig) -> list[SubtitleSegment]:
    if not getattr(config.asr, "unmask_finance", True):
        return segments
    from .finance_unmask import parse_unmask_extra, restore_masked_terms

    extra = parse_unmask_extra(getattr(config.asr, "unmask_extra", "") or "")
    restored: list[SubtitleSegment] = []
    for segment in segments:
        text = restore_masked_terms(segment.text, extra)
        if not text:
            continue
        restored.append(SubtitleSegment(start=segment.start, end=segment.end, text=text))
    return restored


def _prefer_caption(current: str, new: str) -> str:
    """Keep a completed OCR line, but not a one-letter bleed from the previous caption."""
    if len(current) == len(new):
        return current
    longer, shorter = (current, new) if len(current) > len(new) else (new, current)
    if longer.endswith(shorter) and not longer.startswith(shorter):
        prefix = longer[: len(longer) - len(shorter)]
        if (
            len(prefix) == 1
            and prefix.isascii()
            and prefix.isalpha()
            and (cjk_count(current) or cjk_count(new))
        ):
            return shorter
    return longer


def _partial_overlap(prev: str, curr: str) -> int:
    """Suffix of ``prev`` copied onto the front of ``curr`` during a caption change."""
    max_n = min(len(prev), max(len(curr) - 1, 0))
    best = 0
    for size in range(1, max_n + 1):
        if curr.startswith(prev[-size:]):
            best = size
    if best >= 2:
        return best
    if (
        best == 1
        and prev[-1].isascii()
        and prev[-1].isalpha()
        and (cjk_count(prev) or cjk_count(curr))
    ):
        return 1
    return 0


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
    if len(shorter) >= 4 and shorter in longer and len(shorter) / len(longer) >= 0.75:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.86


def _compare_key(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?:：；;\"'“”‘’]", "", text).lower()

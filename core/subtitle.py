"""Subtitle extraction: captions, burned-in OCR, then speech-to-text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .config import AppConfig
from .parser import ParsedLink, Platform


@dataclass
class SubtitleSegment:
    start: float
    end: float
    text: str

    @property
    def start_ts(self) -> str:
        return _seconds_to_ts(self.start)

    @property
    def end_ts(self) -> str:
        return _seconds_to_ts(self.end)


@dataclass
class SubtitleResult:
    segments: list[SubtitleSegment]
    source: str  # "cc", "asr", "visual"
    language: str = "zh"
    raw_text: str = ""

    @property
    def full_text(self) -> str:
        if self.raw_text:
            return self.raw_text
        return "\n".join(s.text for s in self.segments)

    @property
    def duration(self) -> float:
        if not self.segments:
            return 0
        return self.segments[-1].end

    @property
    def srt_content(self) -> str:
        lines = []
        for i, seg in enumerate(self.segments, 1):
            lines.append(str(i))
            lines.append(f"{seg.start_ts} --> {seg.end_ts}")
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)

    def save_srt(self, path: Path) -> None:
        path.write_text(self.srt_content, encoding="utf-8")

    def save_txt(self, path: Path) -> None:
        text = self.full_text
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text, encoding="utf-8")


def _seconds_to_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(srt_path: Path) -> list[SubtitleSegment]:
    """Parse an SRT file into subtitle segments."""
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    content = content.replace("\ufeff", "")  # Remove BOM

    segments: list[SubtitleSegment] = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        ts_match = re.search(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            block,
        )
        if not ts_match:
            continue

        start = _ts_to_seconds(ts_match.group(1))
        end = _ts_to_seconds(ts_match.group(2))

        ts_line_idx = next(
            i for i, l in enumerate(lines)
            if "-->" in l
        )
        text = "\n".join(lines[ts_line_idx + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text)  # Strip HTML tags

        if text:
            segments.append(SubtitleSegment(start=start, end=end, text=text))

    return segments


def _ts_to_seconds(ts: str) -> float:
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


# ---------- extraction strategies ----------

def _try_youtube_transcript_api(
    parsed: ParsedLink, config: AppConfig
) -> SubtitleResult | None:
    """Try youtube-transcript-api for YouTube videos."""
    if parsed.platform != Platform.YOUTUBE:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        kwargs = {}
        proxy_dict = config.proxy.for_requests
        if proxy_dict:
            from youtube_transcript_api.proxies import GenericProxyConfig
            proxy_url = proxy_dict.get("https") or proxy_dict.get("http", "")
            if proxy_url:
                kwargs["proxy_config"] = GenericProxyConfig(proxy_url)

        vid = parsed.video_id
        ytt = YouTubeTranscriptApi()
        fetched = ytt.fetch(vid, languages=["zh-Hans", "zh-CN", "zh", "en"], **kwargs)
        segments = [
            SubtitleSegment(
                start=s.start,
                end=s.start + s.duration,
                text=s.text,
            )
            for s in fetched
        ]
        if segments:
            return SubtitleResult(segments=segments, source="cc", language="zh")
    except Exception:
        pass
    return None


def _try_ytdlp_subtitles(
    parsed: ParsedLink, work_dir: Path, config: AppConfig, timeout: int = 30
) -> SubtitleResult | None:
    """Try yt-dlp subtitle download with timeout."""
    from .downloader import download_subtitles
    import signal

    def _handler(signum, frame):
        raise TimeoutError("subtitle download timeout")

    try:
        old = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
        try:
            srt_files = download_subtitles(parsed.url, work_dir, config)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        if srt_files:
            segments = parse_srt(srt_files[0])
            if segments:
                return SubtitleResult(segments=segments, source="cc")
    except Exception:
        pass
    return None


def _try_asr(
    parsed: ParsedLink, work_dir: Path, config: AppConfig
) -> SubtitleResult | None:
    """Fall back to ASR transcription."""
    from .downloader import download_audio
    from .transcriber import transcribe

    try:
        audio_path = download_audio(parsed.url, work_dir, config)
        result = transcribe(audio_path, config)
        return result
    except Exception:
        pass
    return None


def _subtitle_mode(config: AppConfig) -> str:
    mode = (getattr(config.asr, "subtitle_mode", None) or "auto").strip().lower()
    if mode not in {"auto", "cc", "asr", "ocr"}:
        return "auto"
    return mode


def _from_local_file(
    video_path: Path,
    work_dir: Path,
    config: AppConfig,
    mode: str,
    skip_asr: bool,
) -> SubtitleResult:
    """OCR burned-in captions and/or transcribe a file that is already local."""
    from .ffmpeg_util import extract_wav, has_video_stream
    from .ocr_subtitle import (
        OCRUnavailable,
        burned_in_subtitles_likely,
        ocr_available,
        ocr_burned_subtitles,
    )

    if not video_path.exists():
        raise FileNotFoundError(str(video_path))

    use_ocr = mode == "ocr" or (
        mode == "auto" and has_video_stream(video_path) and ocr_available()
    )
    if use_ocr and mode == "auto":
        try:
            use_ocr = burned_in_subtitles_likely(video_path, config)
        except OCRUnavailable:
            use_ocr = False
    if use_ocr:
        try:
            result = ocr_burned_subtitles(video_path, config, work_dir)
            if mode == "ocr" or result.segments:
                return result
        except OCRUnavailable:
            if mode == "ocr":
                raise
        except Exception:
            if mode == "ocr":
                raise

    if mode != "ocr" and not skip_asr:
        wav_path = extract_wav(video_path, work_dir / "audio.wav")
        from .transcriber import transcribe
        return transcribe(wav_path, config)
    return SubtitleResult(segments=[], source="visual")


def extract_subtitles(
    parsed: ParsedLink,
    work_dir: Path,
    config: AppConfig,
    skip_asr: bool = True,
) -> SubtitleResult:
    """Subtitle fallback.

    Priority 1: platform captions (YouTube API or yt-dlp). Douyin is skipped
    here because yt-dlp cannot fetch it without fresh cookies.
    Priority 2: OCR of burned-in captions when ``subtitle_mode`` is ``ocr``,
    or ``auto`` and a few frames already contain caption text.
    Priority 3: speech-to-text, unless ``skip_asr`` is set.
    Priority 4: empty visual result.
    """
    mode = _subtitle_mode(config)
    work_dir.mkdir(parents=True, exist_ok=True)

    if parsed.platform == Platform.LOCAL:
        return _from_local_file(Path(parsed.url), work_dir, config, mode, skip_asr)

    if mode in {"auto", "cc"}:
        result = _try_youtube_transcript_api(parsed, config)
        if result:
            return result
        # Douyin captions are burned in; yt-dlp fails closed without cookies.
        if parsed.platform != Platform.DOUYIN:
            result = _try_ytdlp_subtitles(parsed, work_dir, config)
            if result:
                return result

    if mode == "cc":
        return SubtitleResult(segments=[], source="visual")

    if mode == "asr":
        if skip_asr:
            return SubtitleResult(segments=[], source="visual")
        result = _try_asr(parsed, work_dir, config)
        if result:
            return result
        return SubtitleResult(segments=[], source="visual")

    # auto or ocr: Douyin (and explicit OCR) need the media file first.
    if parsed.platform == Platform.DOUYIN or mode == "ocr":
        from .downloader import materialize_video
        video_path = materialize_video(parsed.url, work_dir, config)
        return _from_local_file(video_path, work_dir, config, mode, skip_asr)

    if mode == "auto" and not skip_asr:
        result = _try_asr(parsed, work_dir, config)
        if result:
            return result

    return SubtitleResult(segments=[], source="visual")

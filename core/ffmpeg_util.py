"""Small ffmpeg/ffprobe helpers shared by download and OCR."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def ffprobe_video_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    text = result.stdout.strip()
    if "x" not in text:
        return (0, 0)
    width, height = text.split("x", 1)
    try:
        return int(width), int(height)
    except ValueError:
        return (0, 0)


def has_video_stream(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return "video" in result.stdout.lower()


def extract_wav(src: Path, dest: Path) -> Path:
    """Extract 16 kHz mono WAV for speech-to-text."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-loglevel", "error",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not dest.exists():
        detail = (result.stderr or result.stdout or "ffmpeg failed")[:400]
        raise RuntimeError(f"Audio extract failed: {detail}")
    return dest


@dataclass(frozen=True)
class FrameCrop:
    """Vertical crop of a video frame, as fractions of the height."""

    y_ratio: float
    h_ratio: float

    @property
    def vf(self) -> str:
        y = min(max(self.y_ratio, 0.0), 0.95)
        h = min(max(self.h_ratio, 0.05), 0.8)
        return f"crop=iw:trunc(ih*{h:.4f}/2)*2:0:trunc(ih*{y:.4f}/2)*2"


def choose_subtitle_crop(width: int, height: int, bottom_ratio: float = 0.0) -> FrameCrop:
    """Pick the band where burned-in captions usually sit.

    Landscape Douyin videos put captions in the bottom band. Portrait videos
    put them above the app's bottom buttons, around 62–86% of the height.
    ``bottom_ratio`` forces a bottom band (for example 0.2 = bottom 20%).
    """
    if bottom_ratio and bottom_ratio > 0:
        ratio = min(max(bottom_ratio, 0.05), 0.6)
        return FrameCrop(1.0 - ratio, ratio)
    if height > width * 1.1 and width > 0:
        return FrameCrop(0.62, 0.24)
    return FrameCrop(0.82, 0.18)


def extract_frame_at(video: Path, timestamp: float, dest: Path, vf: str = "") -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{max(timestamp, 0):.3f}",
        "-i", str(video),
        "-frames:v", "1",
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-q:v", "5", "-loglevel", "error", str(dest)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return dest.exists() and dest.stat().st_size > 0


def extract_cropped_frames(
    video: Path,
    output_dir: Path,
    interval: float,
    crop: FrameCrop,
) -> list[tuple[float, Path]]:
    """Sample frames at a fixed interval and crop them to ``crop``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("f_*.jpg"):
        old.unlink()
    interval = max(interval, 0.2)
    fps = 1.0 / interval
    pattern = output_dir / "f_%05d.jpg"
    vf = f"fps={fps:.6f},{crop.vf},scale=960:-2"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", vf,
        "-q:v", "5",
        "-loglevel", "error",
        str(pattern),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        detail = (result.stderr or "ffmpeg failed")[:400]
        raise RuntimeError(f"Frame sampling failed: {detail}")
    frames = sorted(output_dir.glob("f_*.jpg"))
    return [(index * interval, path) for index, path in enumerate(frames)]

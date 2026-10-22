"""Local files go through ffmpeg, not yt-dlp."""

import subprocess

from core.config import AppConfig
from core.downloader import download_audio, get_video_info
from core.parser import parse_link
from core.subtitle import extract_subtitles


def _tone(path):
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ac", "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_local_file_metadata_and_audio(tmp_path):
    source = tmp_path / "tone.wav"
    _tone(source)
    parsed = parse_link(str(source))
    info = get_video_info(parsed.url, AppConfig())
    assert info.title == "tone"
    assert 0.5 < info.duration < 2.0

    wav = download_audio(parsed.url, tmp_path / "out", AppConfig())
    assert wav.exists()
    assert wav.suffix == ".wav"
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels",
            "-of", "csv=p=0",
            str(wav),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "16000" in probe.stdout
    assert probe.stdout.strip().endswith("1") or ",1" in probe.stdout


def test_caption_only_mode_does_not_invent_a_transcript(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not a video")
    parsed = parse_link(str(source))
    config = AppConfig()
    config.asr.subtitle_mode = "cc"
    result = extract_subtitles(parsed, tmp_path / "work", config, skip_asr=True)
    assert result.segments == []
    assert result.source == "visual"

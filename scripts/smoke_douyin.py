"""Download a public Douyin link and transcribe it. No login and no cookies.

Usage:
    python scripts/smoke_douyin.py
    python scripts/smoke_douyin.py "https://v.douyin.com/fnnhAB4lkq8/" -o /tmp/transcript.txt
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from core.config import AppConfig
from core.douyin import download_douyin_video
from core.ocr_subtitle import cjk_count, ocr_burned_subtitles
from core.parser import parse_link


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url",
        nargs="?",
        default="https://v.douyin.com/fnnhAB4lkq8/",
        help="Douyin share link or www.douyin.com/video/<id>",
    )
    parser.add_argument("-o", "--output", default="", help="Write the transcript here")
    parser.add_argument(
        "--subtitle-mode",
        default="ocr",
        choices=("ocr", "auto", "asr"),
        help="ocr is the reliable path for burned-in Chinese captions",
    )
    args = parser.parse_args()

    parsed = parse_link(args.url)
    if parsed.platform.value != "douyin":
        print(f"Not a Douyin URL: {args.url}", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="vidnotek_smoke_"))
    print(f"Downloading {args.url}", file=sys.stderr)
    video_path, media = download_douyin_video(args.url, work)
    print(f"id: {media.video_id}", file=sys.stderr)
    print(f"title: {media.title}", file=sys.stderr)
    print(f"uploader: {media.uploader}", file=sys.stderr)
    print(f"duration: {media.duration:.1f}s", file=sys.stderr)
    print(f"file: {video_path} ({video_path.stat().st_size} bytes)", file=sys.stderr)

    config = AppConfig()
    config.asr.subtitle_mode = args.subtitle_mode
    if args.subtitle_mode == "asr":
        from core.ffmpeg_util import extract_wav
        from core.transcriber import transcribe

        wav = extract_wav(video_path, work / "audio.wav")
        subtitles = transcribe(wav, config)
    else:
        subtitles = ocr_burned_subtitles(video_path, config, work)

    text = subtitles.full_text.strip()
    print(f"source: {subtitles.source}", file=sys.stderr)
    print(f"cjk chars: {cjk_count(text)}", file=sys.stderr)
    preview = "\n".join(segment.text for segment in subtitles.segments[:12])
    print(preview)

    if args.output:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subtitles.save_txt(dest)
        subtitles.save_srt(dest.with_suffix(".srt"))
        written = len(dest.read_text(encoding="utf-8").splitlines())
        print(f"{written} lines via {subtitles.source}", file=sys.stderr)
        print(f"wrote {dest}", file=sys.stderr)
        if written != len(subtitles.segments):
            print(
                f"Line count mismatch: file has {written} lines, "
                f"{len(subtitles.segments)} segments",
                file=sys.stderr,
            )
            return 1
    else:
        print(f"segments: {len(subtitles.segments)}", file=sys.stderr)

    if video_path.stat().st_size < 100_000 or cjk_count(text) < 8:
        print("Smoke check failed: video or transcript looks empty", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

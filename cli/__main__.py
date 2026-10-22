"""Link in, transcript or notes out.

Examples:
    python -m cli "https://v.douyin.com/xxxx/" --transcript-only -o transcript.txt
    python -m cli "https://www.douyin.com/video/123" -t brief -o notes.md
    python -m cli ./video.mp4 --subtitle-mode ocr --transcript-only -o transcript.txt
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import click

from core.config import AppConfig, apply_env
from core.parser import parse_link
from core.subtitle import extract_subtitles


def main() -> None:
    cli(standalone_mode=True)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("url")
@click.option("-t", "--template", default="detailed", show_default=True, help="Notes template.")
@click.option(
    "-o", "--output",
    default="",
    help="Output file or directory. Default: ./noteking_output",
)
@click.option(
    "--transcript-only",
    is_flag=True,
    help="Write the transcript and skip the LLM.",
)
@click.option(
    "--subtitle-mode",
    type=click.Choice(["auto", "cc", "asr", "ocr"], case_sensitive=False),
    default=None,
    help="auto: captions, then burned-in OCR when detected, then speech-to-text. "
         "ocr reads burned-in captions. asr is speech-to-text. cc is platform captions only.",
)
@click.option("--api-key", default=None, help="LLM API key. Overrides NOTEKING_LLM_API_KEY.")
@click.option("--base-url", default=None, help="OpenAI-compatible API base URL.")
@click.option("--model", default=None, help="LLM model name.")
@click.option(
    "--no-unmask",
    is_flag=True,
    help="Keep Douyin letter masks (爆C, L润) instead of restoring finance words.",
)
@click.option(
    "--unmask-extra",
    default=None,
    help="Extra mask pairs, for example 'Q亏=全亏,建C=建仓'. Overrides the built-in table.",
)
def cli(
    url: str,
    template: str,
    output: str,
    transcript_only: bool,
    subtitle_mode: str | None,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    no_unmask: bool,
    unmask_extra: str | None,
) -> None:
    """Turn a video link or local file into a transcript or notes."""
    config = apply_env(AppConfig())
    if subtitle_mode:
        config.asr.subtitle_mode = subtitle_mode
    if api_key:
        config.llm.api_key = api_key
    if base_url:
        config.llm.base_url = base_url
    if model:
        config.llm.model = model
    if no_unmask:
        config.asr.unmask_finance = False
    if unmask_extra is not None:
        config.asr.unmask_extra = unmask_extra

    if transcript_only:
        path = _write_transcript(url, config, output)
        click.echo(str(path))
        return

    if not config.llm.api_key:
        raise click.ClickException(
            "No LLM API key. Set NOTEKING_LLM_API_KEY, pass --api-key, "
            "or use --transcript-only."
        )

    from core import summarize

    out_dir, exact_file = _output_target(output)
    result = summarize(
        url=url,
        template=template,
        config=config,
        output_dir=out_dir,
        use_cache=False,
    )
    content = result.get("content", "")
    if exact_file is not None:
        exact_file.write_text(content, encoding="utf-8")
        click.echo(str(exact_file))
    else:
        click.echo(result.get("output_file", ""))
    source = result.get("source", "")
    if source:
        click.echo(f"subtitle source: {source}", err=True)


def _write_transcript(url: str, config: AppConfig, output: str) -> Path:
    from core.downloader import get_video_info

    click.echo("Fetching video...", err=True)
    parsed = parse_link(url)
    meta = get_video_info(parsed.url, config)
    click.echo(f"Title: {meta.title}", err=True)
    click.echo("Transcribing...", err=True)
    work_dir = Path(tempfile.mkdtemp(prefix="noteking_"))
    subtitles = extract_subtitles(parsed, work_dir, config, skip_asr=False)
    if not subtitles.full_text.strip():
        raise click.ClickException(
            "No transcript produced. For burned-in captions install "
            "rapidocr and onnxruntime, then pass --subtitle-mode ocr. "
            "For speech-to-text install faster-whisper (av<16) or set an ASR API key."
        )

    out_dir, exact_file = _output_target(output)
    stem = _safe_stem(meta.title or parsed.video_id or "transcript")
    text_path = exact_file if exact_file is not None else out_dir / f"{stem}.txt"
    if exact_file is not None and exact_file.suffix.lower() == ".srt":
        text_path = exact_file.with_suffix(".txt")
        subtitles.save_srt(exact_file)
        subtitles.save_txt(text_path)
        click.echo(_line_message(text_path, subtitles.source), err=True)
        return exact_file

    text_path.parent.mkdir(parents=True, exist_ok=True)
    subtitles.save_txt(text_path)
    subtitles.save_srt(text_path.with_suffix(".srt"))
    click.echo(_line_message(text_path, subtitles.source), err=True)
    return text_path


def _line_message(text_path: Path, source: str) -> str:
    """Count the lines actually written, including the last line without a guess."""
    count = len(text_path.read_text(encoding="utf-8").splitlines())
    return f"{count} lines via {source}"


def _output_target(output: str) -> tuple[Path, Path | None]:
    if not output:
        directory = Path.cwd() / "noteking_output"
        directory.mkdir(parents=True, exist_ok=True)
        return directory, None
    path = Path(output)
    if output.endswith(("/", "\\")) or path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
        return path, None
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.parent, path
    path.mkdir(parents=True, exist_ok=True)
    return path, None


def _safe_stem(title: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in title).strip()
    return (cleaned or "transcript")[:80]


if __name__ == "__main__":
    main()

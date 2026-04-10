"""VidNoteK Core Engine: the ultimate video/blog to notes tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AppConfig
from .parser import parse_link, ParsedLink, Platform, LinkType, is_batch
from .downloader import get_video_info, VideoMeta
from .subtitle import extract_subtitles, SubtitleResult
from .llm import chat
from .cache import Cache
from .templates import get_template, TEMPLATES, TEMPLATE_LIST, TemplateContext
from .batch import get_batch_entries, process_batch, merge_batch_notes, BatchProgress


__version__ = "0.1.0"


def summarize(
    url: str,
    template: str = "detailed",
    config: AppConfig | None = None,
    custom_prompt: str = "",
    use_cache: bool = True,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Main entry point: convert a video/blog URL into notes.

    Args:
        url: Video URL or local file path
        template: Output template name (see TEMPLATE_LIST)
        config: Configuration (loads default if None)
        custom_prompt: Custom prompt for the 'custom' template
        use_cache: Whether to use cached results
        output_dir: Directory to save output files

    Returns:
        dict with keys: title, content, template, source, meta
    """
    if config is None:
        config = AppConfig.load()

    cache = Cache(config)
    if use_cache:
        cached = cache.get(url, template)
        if cached:
            return cached

    out_dir = Path(output_dir) if output_dir else Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    parsed = parse_link(url)

    if is_batch(parsed):
        return _process_batch(parsed, template, config, custom_prompt, out_dir)

    return _process_single(
        parsed, template, config, custom_prompt, out_dir, cache, use_cache
    )


def _process_single(
    parsed: ParsedLink,
    template_name: str,
    config: AppConfig,
    custom_prompt: str,
    out_dir: Path,
    cache: Cache,
    use_cache: bool,
) -> dict[str, Any]:
    """Process a single video."""
    import tempfile

    work_dir = Path(tempfile.mkdtemp(prefix="noteking_"))

    # Step 1: Get video metadata
    if parsed.platform == Platform.LOCAL:
        meta = VideoMeta(title=Path(parsed.url).stem, webpage_url=parsed.url)
    else:
        meta = get_video_info(parsed.url, config)

    # Step 2: Extract subtitles (three-level fallback)
    subtitles = extract_subtitles(parsed, work_dir, config)

    if not subtitles.segments and subtitles.source == "visual":
        subtitles = SubtitleResult(
            segments=[],
            source="visual",
            raw_text=f"[视频无可用字幕，标题: {meta.title}，描述: {meta.description[:500]}]",
        )

    # Step 3: Generate notes using template
    tmpl = get_template(template_name, user_prompt=custom_prompt)
    ctx = TemplateContext(
        meta=meta,
        subtitles=subtitles,
        config=config,
        extra={"custom_prompt": custom_prompt},
    )
    content = tmpl.generate(ctx)

    # Step 4: Save output
    ext = tmpl.file_extension
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in meta.title)[:80]
    output_file = out_dir / f"{safe_title}_{template_name}{ext}"
    output_file.write_text(content, encoding="utf-8")

    # Save subtitle files
    if subtitles.segments:
        subtitles.save_srt(out_dir / f"{safe_title}.srt")
        subtitles.save_txt(out_dir / f"{safe_title}_transcript.txt")

    result = {
        "title": meta.title,
        "content": content,
        "template": template_name,
        "source": subtitles.source,
        "output_file": str(output_file),
        "url": parsed.url,
        "platform": parsed.platform.value,
        "duration": meta.duration,
        "uploader": meta.uploader,
    }

    if use_cache:
        cache.set(parsed.url, template_name, result)

    return result


def _process_batch(
    parsed: ParsedLink,
    template_name: str,
    config: AppConfig,
    custom_prompt: str,
    out_dir: Path,
) -> dict[str, Any]:
    """Process a batch (playlist/collection)."""
    entries = get_batch_entries(parsed, config)
    cache = Cache(config)

    all_results: list[dict] = []

    def process_one(entry_url: str, idx: int) -> dict:
        entry_parsed = parse_link(entry_url)
        r = _process_single(
            entry_parsed, template_name, config, custom_prompt,
            out_dir, cache, True,
        )
        all_results.append(r)
        return r

    progress = process_batch(entries, process_one)

    merged = merge_batch_notes(
        [{"title": r.get("title", ""), "content": r.get("content", "")}
         for r in all_results],
        title=f"{parsed.video_id} 合集笔记",
    )

    merged_file = out_dir / f"batch_merged_{template_name}.md"
    merged_file.write_text(merged, encoding="utf-8")

    return {
        "title": f"合集 ({len(all_results)} 个视频)",
        "content": merged,
        "template": template_name,
        "source": "batch",
        "output_file": str(merged_file),
        "url": parsed.url,
        "platform": parsed.platform.value,
        "total": progress.total,
        "completed": progress.completed,
        "failed": progress.failed,
        "individual_results": all_results,
    }


def get_transcript(
    url: str,
    config: AppConfig | None = None,
) -> str:
    """Get just the transcript text for a video."""
    if config is None:
        config = AppConfig.load()

    import tempfile

    parsed = parse_link(url)
    work_dir = Path(tempfile.mkdtemp(prefix="noteking_"))
    subtitles = extract_subtitles(parsed, work_dir, config)
    return subtitles.full_text

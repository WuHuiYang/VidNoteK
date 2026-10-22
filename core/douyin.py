"""No-login Douyin downloader.

Stock yt-dlp asks for fresh cookies on Douyin even for public videos. The
public web app at ``https://www.douyin.com/jingxuan?modal_id=<id>`` embeds
the direct mp4 in ``RENDER_DATA`` after the page renders, with no login.
Short share links (``v.douyin.com/...``) redirect to
``iesdouyin.com/share/video/<id>/``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

_ID_RE = re.compile(
    r"(?:modal_id=|aweme_id=|(?:share/)?video/)(\d{15,22})"
)
_CACHE: dict[str, tuple[float, "DouyinMedia"]] = {}
_FILE_CACHE: dict[str, Path] = {}
_CACHE_TTL = 600

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)


@dataclass
class DouyinMedia:
    video_id: str
    title: str
    description: str
    duration: float
    uploader: str
    play_url: str
    thumbnail: str
    webpage_url: str


def is_douyin_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return (
        host == "douyin.com"
        or host.endswith(".douyin.com")
        or host == "iesdouyin.com"
        or host.endswith(".iesdouyin.com")
    )


def extract_video_id(url: str) -> str:
    """Return a Douyin aweme id if it is already present in ``url``."""
    if not url:
        return ""
    match = _ID_RE.search(url)
    return match.group(1) if match else ""


def resolve_video_id(url: str, timeout: float = 20) -> str:
    """Resolve a share link or canonical URL to a numeric aweme id."""
    video_id = extract_video_id(url)
    if video_id:
        return video_id
    if not is_douyin_url(url):
        raise RuntimeError(f"Not a Douyin URL: {url}")
    headers = {"User-Agent": MOBILE_UA}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        response = client.get(url)
    video_id = extract_video_id(str(response.url))
    if not video_id:
        video_id = extract_video_id(response.text[:8000])
    if not video_id:
        raise RuntimeError(
            f"Could not resolve a Douyin video id from {url} "
            f"(final URL: {response.url})"
        )
    return video_id


def choose_play_url(video: dict) -> str:
    """Pick a progressive mp4. Prefer the H.264 ``playAddr`` over H.265."""
    for src in _src_list(video.get("playAddr")):
        if src:
            return src
    candidates: list[tuple[int, str]] = []
    for item in video.get("bitRateList") or []:
        if not isinstance(item, dict) or item.get("isH265"):
            continue
        urls = _src_list(item.get("playAddr"))
        if urls:
            candidates.append((int(item.get("dataSize") or 0), urls[0]))
    if candidates:
        under = [item for item in candidates if 0 < item[0] <= 40_000_000]
        pool = under or candidates
        pool.sort(key=lambda item: item[0])
        return pool[-1][1]
    for src in _src_list(video.get("playAddrH265")):
        if src:
            return src
    return ""


def parse_render_html(html: str, video_id: str) -> DouyinMedia:
    """Parse a rendered Douyin page and return the active video's media."""
    match = re.search(
        r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        title = _page_title(html)
        raise RuntimeError(
            f"Douyin page did not include RENDER_DATA for {video_id}"
            + (f" (title: {title})" if title else "")
        )
    data = _load_render_json(match.group(1))
    detail = _find_aweme(data, video_id)
    if not detail:
        app = data.get("app") if isinstance(data, dict) else None
        fallback = (app or {}).get("videoDetail") if isinstance(app, dict) else None
        if isinstance(fallback, dict) and str(fallback.get("awemeId", "")) == video_id:
            detail = fallback
    if not detail:
        raise RuntimeError(f"Douyin page has no video detail for {video_id}")
    video = detail.get("video") or {}
    play_url = choose_play_url(video)
    if not play_url:
        raise RuntimeError(f"Douyin page has no playable mp4 for {video_id}")
    author = detail.get("authorInfo") or {}
    title = (detail.get("itemTitle") or detail.get("desc") or "").strip()
    description = (detail.get("desc") or title).strip()
    return DouyinMedia(
        video_id=video_id,
        title=title or video_id,
        description=description,
        duration=_duration_seconds(video),
        uploader=(author.get("nickname") or "").strip(),
        play_url=play_url,
        thumbnail=(video.get("cover") or video.get("originCover") or ""),
        webpage_url=f"https://www.douyin.com/video/{video_id}",
    )


def fetch_douyin_media(url: str) -> DouyinMedia:
    """Open the public jingxuan page and read the direct mp4 URL."""
    known_id = extract_video_id(url)

    def work() -> DouyinMedia:
        video_id = known_id or resolve_video_id(url)
        cached = _fresh(video_id)
        if cached:
            return cached
        media = _fetch_with_browser(video_id)
        _CACHE[video_id] = (time.time(), media)
        return media

    if known_id:
        cached = _fresh(known_id)
        if cached:
            return cached
    return _run_blocking(work)


def download_douyin_video(url: str, output_dir: Path) -> tuple[Path, DouyinMedia]:
    """Download the public mp4. No cookies and no login."""
    output_dir.mkdir(parents=True, exist_ok=True)
    media = fetch_douyin_media(url)
    dest = output_dir / f"{media.video_id}.mp4"
    cached = _FILE_CACHE.get(media.video_id)
    if cached and cached.exists() and cached.stat().st_size > 50_000:
        if cached.resolve() != dest.resolve():
            shutil.copyfile(cached, dest)
        else:
            return dest, media
        _FILE_CACHE[media.video_id] = dest
        return dest, media
    if dest.exists() and dest.stat().st_size > 50_000:
        _FILE_CACHE[media.video_id] = dest
        return dest, media
    _download_play_url(media.play_url, dest)
    _FILE_CACHE[media.video_id] = dest
    return dest, media


def _fresh(video_id: str) -> DouyinMedia | None:
    hit = _CACHE.get(video_id)
    if not hit:
        return None
    saved_at, media = hit
    if time.time() - saved_at > _CACHE_TTL:
        return None
    return media


def _fetch_with_browser(video_id: str) -> DouyinMedia:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Douyin download needs Playwright and a Chromium/Chrome browser. "
            "Install with: pip install 'playwright>=1.40' && playwright install chromium"
        ) from exc

    page_url = f"https://www.douyin.com/jingxuan?modal_id={video_id}"
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                user_agent=DESKTOP_UA,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            page = context.new_page()
            page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_function(
                    """(vid) => {
                        const el = document.querySelector('script#RENDER_DATA');
                        if (!el) return false;
                        const text = el.textContent || '';
                        try { return decodeURIComponent(text).includes(vid); }
                        catch (e) { return text.includes(vid); }
                    }""",
                    arg=video_id,
                    timeout=20000,
                )
            except Exception:
                page.wait_for_timeout(4000)
            html = page.content()
        finally:
            browser.close()
    return parse_render_html(html, video_id)


def _launch_browser(playwright):
    args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ]
    configured = os.environ.get("NOTEKING_CHROME", "").strip()
    if configured:
        return playwright.chromium.launch(
            executable_path=configured, headless=True, args=args
        )

    errors: list[str] = []
    if shutil.which("google-chrome") or shutil.which("google-chrome-stable"):
        try:
            return playwright.chromium.launch(channel="chrome", headless=True, args=args)
        except Exception as exc:
            errors.append(f"google-chrome: {exc}")
    try:
        return playwright.chromium.launch(headless=True, args=args)
    except Exception as exc:
        errors.append(f"playwright-chromium: {exc}")
    for name in ("chromium", "chromium-browser"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            return playwright.chromium.launch(
                executable_path=path, headless=True, args=args
            )
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    detail = "; ".join(errors) or "no browser found"
    raise RuntimeError(
        "Could not start a headless browser for Douyin. Install Google Chrome "
        "or run `playwright install chromium`. " + detail
    )


def _download_play_url(url: str, dest: Path) -> None:
    headers = {"User-Agent": DESKTOP_UA, "Referer": "https://www.douyin.com/"}
    timeout = httpx.Timeout(180.0, connect=20.0)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type:
                    raise RuntimeError("Douyin returned HTML instead of a video file")
                expected = int(response.headers.get("content-length") or 0)
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        size = dest.stat().st_size
        if size < 50_000 or (expected and size < int(expected * 0.98)):
            raise RuntimeError(f"Douyin download was incomplete ({size} bytes)")
    except Exception:
        dest.unlink(missing_ok=True)
        raise


def _src_list(node) -> list[str]:
    if isinstance(node, str) and node.startswith("http"):
        return [node]
    if isinstance(node, dict):
        src = node.get("src") or node.get("url")
        return [src] if isinstance(src, str) and src.startswith("http") else []
    if isinstance(node, list):
        found: list[str] = []
        for item in node:
            found.extend(_src_list(item))
        return found
    return []


def _duration_seconds(video: dict) -> float:
    thumbs = video.get("bigThumbs") or []
    if thumbs and isinstance(thumbs[0], dict) and thumbs[0].get("duration"):
        try:
            return float(thumbs[0]["duration"])
        except (TypeError, ValueError):
            pass
    try:
        raw = float(video.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0
    if raw > 1000:
        return raw / 1000.0
    return raw


def _find_aweme(obj, video_id: str) -> dict | None:
    if isinstance(obj, dict):
        if str(obj.get("awemeId", "")) == video_id and isinstance(obj.get("video"), dict):
            return obj
        for value in obj.values():
            found = _find_aweme(value, video_id)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_aweme(value, video_id)
            if found:
                return found
    return None


def _load_render_json(raw: str) -> dict:
    text = raw.strip()
    candidates = [unquote(text), text] if "%" in text else [text]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise RuntimeError("Could not parse Douyin RENDER_DATA")


def _page_title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:120]


def _run_blocking(fn):
    """Playwright's sync API cannot run on a thread that has an asyncio loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result()

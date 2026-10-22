"""Global configuration management for VidNoteK."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = Path.home() / ".noteking"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CACHE_DIR = DEFAULT_CONFIG_DIR / "cache"
DEFAULT_OUTPUT_DIR = Path.cwd() / "noteking_output"


@dataclass
class ProxyConfig:
    enabled: bool = False
    http: str = ""
    https: str = ""
    socks5: str = ""

    @property
    def for_requests(self) -> dict[str, str] | None:
        if not self.enabled:
            return None
        proxies: dict[str, str] = {}
        if self.http:
            proxies["http"] = self.http
        if self.https:
            proxies["https"] = self.https
        elif self.socks5:
            proxies["http"] = self.socks5
            proxies["https"] = self.socks5
        return proxies or None

    @property
    def for_ytdlp(self) -> str | None:
        if not self.enabled:
            return None
        return self.socks5 or self.https or self.http or None


@dataclass
class ASRConfig:
    default_engine: str = "auto"
    faster_whisper_model: str = "base"
    groq_api_key: str = ""
    openai_api_key: str = ""
    volcengine_app_id: str = ""
    volcengine_token: str = ""
    deepgram_api_key: str = ""
    # auto: captions, then burned-in OCR when it looks useful, then ASR
    # cc: platform captions only; asr: speech-to-text only; ocr: burned-in text only
    subtitle_mode: str = "auto"
    ocr_interval: float = 0.5
    # 0 = choose the caption band from the aspect ratio; >0 = bottom fraction
    ocr_bottom_ratio: float = 0.0
    # Restore Douyin letter masks such as 爆C -> 爆仓. Set false to keep OCR text.
    unmask_finance: bool = True
    # Extra pairs, "Q亏=全亏,建C=建仓". These override the built-in table.
    unmask_extra: str = ""


@dataclass
class LLMConfig:
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 8000  # DeepSeek 限制是 8192，设置为 8000 安全
    language: str = "zh-CN"


@dataclass
class AppConfig:
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    cache_dir: str = str(DEFAULT_CACHE_DIR)
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    bilibili_sessdata: str = ""
    default_template: str = "detailed"
    max_concurrent_downloads: int = 3

    def save(self, path: Path | None = None) -> None:
        path = path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or DEFAULT_CONFIG_FILE
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return apply_env(cfg)
        try:
            data = json.loads(path.read_text())
            return apply_env(cls(
                proxy=ProxyConfig(**data.get("proxy", {})),
                asr=ASRConfig(**data.get("asr", {})),
                llm=LLMConfig(**data.get("llm", {})),
                cache_dir=data.get("cache_dir", str(DEFAULT_CACHE_DIR)),
                output_dir=data.get("output_dir", str(DEFAULT_OUTPUT_DIR)),
                bilibili_sessdata=data.get("bilibili_sessdata", ""),
                default_template=data.get("default_template", "detailed"),
                max_concurrent_downloads=data.get("max_concurrent_downloads", 3),
            ))
        except Exception:
            return apply_env(cls())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_env(cfg: "AppConfig") -> "AppConfig":
    """Overlay environment variables onto a config object. No secrets are written."""
    import os

    if os.environ.get("NOTEKING_LLM_API_KEY"):
        cfg.llm.api_key = os.environ["NOTEKING_LLM_API_KEY"]
    if os.environ.get("NOTEKING_LLM_BASE_URL"):
        cfg.llm.base_url = os.environ["NOTEKING_LLM_BASE_URL"]
    if os.environ.get("NOTEKING_LLM_MODEL"):
        cfg.llm.model = os.environ["NOTEKING_LLM_MODEL"]
    if os.environ.get("BILIBILI_SESSDATA"):
        cfg.bilibili_sessdata = os.environ["BILIBILI_SESSDATA"]
    if os.environ.get("NOTEKING_PROXY"):
        cfg.proxy.enabled = True
        cfg.proxy.http = os.environ["NOTEKING_PROXY"]
        cfg.proxy.https = os.environ["NOTEKING_PROXY"]
    if os.environ.get("NOTEKING_SUBTITLE_MODE"):
        cfg.asr.subtitle_mode = os.environ["NOTEKING_SUBTITLE_MODE"]
    if os.environ.get("NOTEKING_ASR_ENGINE"):
        cfg.asr.default_engine = os.environ["NOTEKING_ASR_ENGINE"]
    if os.environ.get("NOTEKING_ASR_MODEL"):
        cfg.asr.faster_whisper_model = os.environ["NOTEKING_ASR_MODEL"]
    if os.environ.get("NOTEKING_OCR_INTERVAL"):
        try:
            cfg.asr.ocr_interval = float(os.environ["NOTEKING_OCR_INTERVAL"])
        except ValueError:
            pass
    if os.environ.get("NOTEKING_OCR_BOTTOM_RATIO"):
        try:
            cfg.asr.ocr_bottom_ratio = float(os.environ["NOTEKING_OCR_BOTTOM_RATIO"])
        except ValueError:
            pass
    if os.environ.get("NOTEKING_UNMASK"):
        flag = os.environ["NOTEKING_UNMASK"].strip().lower()
        cfg.asr.unmask_finance = flag not in {"0", "false", "no", "off"}
    if os.environ.get("NOTEKING_UNMASK_EXTRA"):
        cfg.asr.unmask_extra = os.environ["NOTEKING_UNMASK_EXTRA"]
    return cfg

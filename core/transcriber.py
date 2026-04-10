"""ASR engine pool: multiple transcription engines with factory pattern."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .config import AppConfig
from .subtitle import SubtitleResult, SubtitleSegment


class ASREngine(ABC):
    """Abstract base for all ASR engines."""

    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str = "zh") -> SubtitleResult:
        ...

    @classmethod
    def is_available(cls, config: AppConfig) -> bool:
        return True


class FasterWhisperEngine(ASREngine):
    """Local faster-whisper engine (free, GPU-accelerated)."""

    name = "faster_whisper"

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size, device="auto", compute_type="auto"
            )
        return self._model

    def transcribe(self, audio_path: Path, language: str = "zh") -> SubtitleResult:
        model = self._get_model()
        segs, info = model.transcribe(
            str(audio_path), language=language, vad_filter=True
        )
        segments = []
        for seg in segs:
            segments.append(SubtitleSegment(
                start=seg.start, end=seg.end, text=seg.text.strip()
            ))
        return SubtitleResult(
            segments=segments, source="asr", language=info.language
        )

    @classmethod
    def is_available(cls, config: AppConfig) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False


class GroqWhisperEngine(ASREngine):
    """Groq cloud Whisper API (free tier available)."""

    name = "groq"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, audio_path: Path, language: str = "zh") -> SubtitleResult:
        import httpx

        with open(audio_path, "rb") as f:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (audio_path.name, f, "audio/wav")},
                data={
                    "model": "whisper-large-v3",
                    "response_format": "verbose_json",
                    "language": language,
                },
                timeout=300,
            )
        resp.raise_for_status()
        data = resp.json()
        segments = []
        for seg in data.get("segments", []):
            segments.append(SubtitleSegment(
                start=seg["start"], end=seg["end"], text=seg["text"].strip()
            ))
        if not segments and data.get("text"):
            segments.append(SubtitleSegment(start=0, end=0, text=data["text"]))
        return SubtitleResult(segments=segments, source="asr", language=language)

    @classmethod
    def is_available(cls, config: AppConfig) -> bool:
        return bool(config.asr.groq_api_key)


class OpenAIWhisperEngine(ASREngine):
    """OpenAI Whisper API."""

    name = "openai_whisper"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, audio_path: Path, language: str = "zh") -> SubtitleResult:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                language=language,
            )

        segments = []
        for seg in getattr(transcript, "segments", []) or []:
            segments.append(SubtitleSegment(
                start=seg["start"], end=seg["end"], text=seg["text"].strip()
            ))
        if not segments and transcript.text:
            segments.append(SubtitleSegment(start=0, end=0, text=transcript.text))
        return SubtitleResult(segments=segments, source="asr", language=language)

    @classmethod
    def is_available(cls, config: AppConfig) -> bool:
        return bool(config.asr.openai_api_key or config.llm.api_key)


# ---------- factory ----------

_ENGINES: list[type[ASREngine]] = [
    GroqWhisperEngine,
    OpenAIWhisperEngine,
    FasterWhisperEngine,
]


def _create_engine(config: AppConfig) -> ASREngine:
    pref = config.asr.default_engine

    if pref == "faster_whisper" and FasterWhisperEngine.is_available(config):
        return FasterWhisperEngine(config.asr.faster_whisper_model)
    if pref == "groq" and GroqWhisperEngine.is_available(config):
        return GroqWhisperEngine(config.asr.groq_api_key)
    if pref == "openai" and OpenAIWhisperEngine.is_available(config):
        key = config.asr.openai_api_key or config.llm.api_key
        return OpenAIWhisperEngine(key)

    # Auto: try in priority order
    if GroqWhisperEngine.is_available(config):
        return GroqWhisperEngine(config.asr.groq_api_key)
    if OpenAIWhisperEngine.is_available(config):
        key = config.asr.openai_api_key or config.llm.api_key
        return OpenAIWhisperEngine(key)
    if FasterWhisperEngine.is_available(config):
        return FasterWhisperEngine(config.asr.faster_whisper_model)

    raise RuntimeError(
        "No ASR engine available. Install faster-whisper or provide an API key "
        "for Groq/OpenAI in the config."
    )


def transcribe(audio_path: Path, config: AppConfig) -> SubtitleResult:
    """Transcribe audio using the best available ASR engine."""
    engine = _create_engine(config)
    return engine.transcribe(audio_path)

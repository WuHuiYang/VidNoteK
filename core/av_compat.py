"""Keep faster-whisper working across PyAV releases.

faster-whisper calls ``av.open(..., metadata_errors="ignore")``. PyAV 16
removed that keyword and raises ``TypeError: open() got an unexpected
keyword argument 'metadata_errors'``. Drop the argument only when the
installed PyAV rejects it, so older PyAV versions keep their old behavior.
"""

from __future__ import annotations


def install_av_open_compat() -> None:
    """Patch ``av.open`` once so unknown ``metadata_errors`` is ignored."""
    try:
        import av
    except ImportError:
        return

    current = av.open
    if getattr(current, "_vidnotek_compat", False):
        return
    original = getattr(current, "_vidnotek_original", current)

    def open_compat(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except TypeError as exc:
            if "metadata_errors" in kwargs and "metadata_errors" in str(exc):
                cleaned = dict(kwargs)
                cleaned.pop("metadata_errors", None)
                return original(*args, **cleaned)
            raise

    open_compat._vidnotek_compat = True  # type: ignore[attr-defined]
    open_compat._vidnotek_original = original  # type: ignore[attr-defined]
    av.open = open_compat

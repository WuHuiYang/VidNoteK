"""PyAV compatibility shim used by faster-whisper."""

import sys
import types

from core.av_compat import install_av_open_compat


def test_open_drops_metadata_errors_when_pyav_rejects_it(monkeypatch):
    calls = []

    def fake_open(*args, **kwargs):
        if "metadata_errors" in kwargs:
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
        calls.append((args, kwargs))
        return "container"

    fake_av = types.ModuleType("av")
    fake_av.open = fake_open
    monkeypatch.setitem(sys.modules, "av", fake_av)

    install_av_open_compat()
    assert fake_av.open("clip.wav", metadata_errors="ignore") == "container"
    assert calls == [(("clip.wav",), {})]


def test_open_still_passes_metadata_errors_to_older_pyav(monkeypatch):
    calls = []

    def fake_open(*args, **kwargs):
        calls.append(kwargs)
        return "container"

    fake_av = types.ModuleType("av")
    fake_av.open = fake_open
    monkeypatch.setitem(sys.modules, "av", fake_av)

    install_av_open_compat()
    assert fake_av.open("clip.wav", metadata_errors="ignore") == "container"
    assert calls == [{"metadata_errors": "ignore"}]

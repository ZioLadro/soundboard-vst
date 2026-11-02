import pytest

from soundboard_vst import eventlog


@pytest.fixture(autouse=True)
def _no_log_files(monkeypatch):
    """Nei test il registro resta in memoria: niente file nella cartella dati vera."""
    monkeypatch.setattr(eventlog.LOG, "write_files", False)
    eventlog.LOG.clear()

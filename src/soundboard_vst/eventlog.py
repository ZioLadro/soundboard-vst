"""Registro di tutto quello che succede: suoni premuti (e da chi), playlist, sintesi vocale, Discord…

Si scrive da qualsiasi thread con ``log(categoria, testo, chi)``. Gli eventi restano in memoria (gli
ultimi 5000, per la console nella finestra) e finiscono anche in un file al giorno nella cartella
dati (``logs/registro-AAAA-MM-GG.log``), tenuto per 14 giorni.

«Chi» ha fatto un'azione nella finestra si imposta con ``acting(nome)`` intorno al codice che la
esegue (nel thread dell'interfaccia); se non è impostato si usa ``DEFAULT_ACTOR`` («Tu»).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import config_dir

SOUND, VOICE, PLAYER, DISCORD, COMMAND, PERMISSION, IMPORT, ERROR = (
    "suono", "voce", "player", "discord", "comando", "permessi", "import", "errore")
CATEGORIES = {SOUND: "Suoni", VOICE: "Sintesi vocale", PLAYER: "Player", DISCORD: "Discord",
              COMMAND: "Comandi Discord", PERMISSION: "Permessi", IMPORT: "Nuovi suoni", ERROR: "Errori"}
ICONS = {SOUND: "🔊", VOICE: "💬", PLAYER: "🎵", DISCORD: "🤖", COMMAND: "⌨", PERMISSION: "⛔",
         IMPORT: "📥", ERROR: "⚠"}
DEFAULT_ACTOR = "Tu"
MAX_EVENTS = 5000
KEEP_DAYS = 14


@dataclass(frozen=True)
class Event:
    time: float
    category: str
    text: str
    who: str = ""

    def line(self) -> str:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time))
        who = f" [{self.who}]" if self.who else ""
        return f"{t} {CATEGORIES.get(self.category, self.category)}{who}: {self.text}"


class EventLog:
    def __init__(self, folder: Callable[[], Path] | None = None):
        self._events: deque[Event] = deque(maxlen=MAX_EVENTS)
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Event], None]] = []
        self._folder = folder or (lambda: config_dir() / "logs")
        self.write_files = True
        self._cleaned = False

    def add_listener(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[Event], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def log(self, category: str, text: str, who: str | None = None) -> Event:
        ev = Event(time.time(), category, " ".join(str(text).split())[:500],
                   current_actor() if who is None else who)
        with self._lock:
            self._events.append(ev)
            if self.write_files:
                self._write(ev)
        for fn in list(self._listeners):
            try:
                fn(ev)
            except Exception:
                pass
        return ev

    def folder(self) -> Path:
        return self._folder()

    def _write(self, ev: Event) -> None:
        try:
            folder = self._folder()
            folder.mkdir(parents=True, exist_ok=True)
            day = time.strftime("%Y-%m-%d", time.localtime(ev.time))
            with open(folder / f"registro-{day}.log", "a", encoding="utf-8") as f:
                f.write(ev.line() + "\n")
            if not self._cleaned:
                self._cleaned = True
                limit = time.time() - KEEP_DAYS * 86400
                for p in folder.glob("registro-*.log"):
                    if p.stat().st_mtime < limit:
                        p.unlink()
        except OSError:
            pass                       # il registro non deve mai bloccare il programma


LOG = EventLog()

_actor = threading.local()


def current_actor() -> str:
    return getattr(_actor, "name", None) or DEFAULT_ACTOR


@contextmanager
def acting(name: str | None):
    """Le azioni eseguite qui dentro (in questo thread) vengono attribuite a ``name``."""
    old = getattr(_actor, "name", None)
    _actor.name = name or old
    try:
        yield
    finally:
        _actor.name = old


def log(category: str, text: str, who: str | None = None) -> Event:
    return LOG.log(category, text, who)

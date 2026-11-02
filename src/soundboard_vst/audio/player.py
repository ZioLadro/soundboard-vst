"""Lettore musicale: coda di brani (file locali o YouTube) decodificati da ffmpeg in streaming.

ffmpeg decodifica qualunque formato (mp3, flac, m4a, opus, video…) direttamente in float32 stereo
al sample rate del motore; un thread riempie un buffer, il thread audio lo legge con ``read()``.
"""

from __future__ import annotations

import random
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .. import binaries
from .ringbuffer import RingBuffer

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aif", ".aiff",
                    ".mp4", ".mkv", ".webm", ".mov"}
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


@dataclass
class Track:
    title: str
    source: str                      # percorso del file o URL della pagina YouTube
    kind: str = "file"               # "file" | "youtube"
    duration: float | None = None

    def to_dict(self) -> dict:
        return {"title": self.title, "source": self.source, "kind": self.kind, "duration": self.duration}

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(str(d.get("title") or d.get("source")), str(d["source"]), d.get("kind", "file"),
                   d.get("duration"))

    @classmethod
    def from_file(cls, path: Path) -> "Track":
        return cls(path.stem, str(path), "file", None)


def probe_duration(source: str, headers: dict | None = None) -> float | None:
    exe = binaries.ffmpeg_exe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-hide_banner", "-nostdin", "-i", source], capture_output=True, text=True,
                           timeout=20, errors="replace", **binaries.no_window_kwargs())
    except Exception:
        return None
    m = _DURATION_RE.search(r.stderr)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# Risolve un brano in (URL/percorso da dare a ffmpeg, header HTTP). Per YouTube lo fornisce youtube.py.
Resolver = Callable[[Track], tuple[str, dict]]


def _default_resolver(track: Track) -> tuple[str, dict]:
    return track.source, {}


@dataclass
class _Job:
    generation: int
    proc: subprocess.Popen | None = None
    eof: bool = False
    error: str = ""
    stop: threading.Event = field(default_factory=threading.Event)


class Player:
    def __init__(self, sample_rate: int, on_change: Callable[[str], None] | None = None):
        self.sample_rate = sample_rate
        self.on_change = on_change or (lambda event: None)
        self.resolvers: dict[str, Resolver] = {"file": _default_resolver}
        self.tracks: list[Track] = []
        self.index = -1
        self.state = "stopped"          # stopped | loading | playing | paused
        self.repeat = "off"             # off | all | one
        self.shuffle = False
        self.error = ""
        self.load_progress: float | None = None     # avanzamento del download (YouTube)
        self._ring = RingBuffer(2, sample_rate * 4, max_latency=sample_rate * 4)
        self._lock = threading.RLock()
        self._generation = 0
        self._job: _Job | None = None
        self._frames_played = 0
        self._start_offset = 0.0
        self._ended = threading.Event()
        self._closed = False
        threading.Thread(target=self._supervise, name="player-supervisor", daemon=True).start()

    # Coda -----------------------------------------------------------------------------
    @property
    def current(self) -> Track | None:
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    def add(self, tracks: list[Track]) -> None:
        with self._lock:
            self.tracks.extend(tracks)
        self.on_change("queue")

    def remove(self, i: int) -> None:
        with self._lock:
            if not 0 <= i < len(self.tracks):
                return
            del self.tracks[i]
            if i == self.index:
                self._stop_job()
                self.index = min(i, len(self.tracks) - 1) if self.tracks else -1
                self.state = "stopped"
            elif i < self.index:
                self.index -= 1
        self.on_change("queue")

    def move(self, src: int, dst: int) -> None:
        with self._lock:
            if not (0 <= src < len(self.tracks) and 0 <= dst < len(self.tracks)):
                return
            cur = self.current
            self.tracks.insert(dst, self.tracks.pop(src))
            if cur is not None:
                self.index = next(i for i, t in enumerate(self.tracks) if t is cur)
        self.on_change("queue")

    def clear(self) -> None:
        with self._lock:
            self._stop_job()
            self.tracks.clear()
            self.index = -1
            self.state = "stopped"
        self.on_change("queue")
        self.on_change("state")

    # Trasporto -------------------------------------------------------------------------
    @property
    def position(self) -> float:
        return self._start_offset + self._frames_played / self.sample_rate

    @property
    def is_active(self) -> bool:
        return self.state in ("playing", "loading")

    def play(self, index: int | None = None, start: float = 0.0) -> None:
        with self._lock:
            if index is None:
                if self.state == "paused":
                    self.state = "playing"
                    self.on_change("state")
                    return
                index = self.index if self.index >= 0 else 0
            if not 0 <= index < len(self.tracks):
                return
            self._stop_job()
            self.index = index
            self._generation += 1
            job = _Job(self._generation)
            self._job = job
            self._ring.clear()
            self._frames_played = 0
            self._start_offset = max(0.0, start)
            self.error = ""
            self.state = "loading"
            track = self.tracks[index]
        self.on_change("track")
        self.on_change("state")
        threading.Thread(target=self._decode, args=(job, track, self._start_offset),
                         name="player-decoder", daemon=True).start()

    def pause(self) -> None:
        with self._lock:
            if self.state in ("playing", "loading"):
                self.state = "paused"
        self.on_change("state")

    def toggle(self) -> None:
        if self.state in ("playing", "loading"):
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        with self._lock:
            self._stop_job()
            self.state = "stopped"
            self._frames_played = 0
            self._start_offset = 0.0
        self.on_change("state")

    def next(self, user: bool = True) -> None:
        with self._lock:
            if not self.tracks:
                return
            if self.repeat == "one" and not user:
                nxt = self.index
            elif self.shuffle and len(self.tracks) > 1:
                nxt = random.choice([i for i in range(len(self.tracks)) if i != self.index])
            else:
                nxt = self.index + 1
                if nxt >= len(self.tracks):
                    if self.repeat == "all" or user:
                        nxt = 0
                    else:
                        self._stop_job()
                        self.state = "stopped"
                        self.on_change("state")
                        return
        self.play(nxt)

    def prev(self) -> None:
        if self.position > 3 or self.index <= 0:
            self.play(max(0, self.index))
        else:
            self.play(self.index - 1)

    def seek(self, seconds: float) -> None:
        if self.current is None:
            return
        paused = self.state == "paused"
        self.play(self.index, start=seconds)
        if paused:
            self.pause()

    def close(self) -> None:
        self._closed = True
        self._stop_job()
        self._ended.set()

    # Thread audio ----------------------------------------------------------------------
    def read(self, frames: int) -> np.ndarray:
        if self.state != "playing":
            return np.zeros((2, frames), dtype=np.float32)
        avail = len(self._ring)
        out = self._ring.read(frames)
        self._frames_played += min(avail, frames)
        job = self._job
        if job is not None and job.eof and len(self._ring) == 0:
            self._ended.set()
        return out

    # Decodifica ----------------------------------------------------------------------------
    def _set_progress(self, job: "_Job", fraction: float) -> None:
        if job is self._job:
            self.load_progress = fraction
            self.on_change("progress")

    def _stop_job(self) -> None:
        job, self._job = self._job, None
        if job is not None:
            job.stop.set()
            if job.proc is not None:
                try:
                    job.proc.kill()
                except Exception:
                    pass

    def _decode(self, job: _Job, track: Track, start: float) -> None:
        exe = binaries.ffmpeg_exe()
        try:
            if not exe:
                raise RuntimeError("ffmpeg non disponibile")
            resolver = self.resolvers.get(track.kind, _default_resolver)
            try:
                url, headers = resolver(track, progress=lambda f: self._set_progress(job, f))
            except TypeError:
                url, headers = resolver(track)
            self.load_progress = None
            if job.stop.is_set():
                return
            cmd = [exe, "-hide_banner", "-nostdin", "-loglevel", "error"]
            if url.startswith(("http://", "https://")):
                cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
                if headers:
                    cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
            if start > 0:
                cmd += ["-ss", f"{start:.2f}"]
            cmd += ["-i", url, "-vn", "-f", "f32le", "-ac", "2", "-ar", str(self.sample_rate), "pipe:1"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, **binaries.no_window_kwargs())
            job.proc = proc
            with self._lock:
                if self._job is job and self.state == "loading":
                    self.state = "playing"
            self.on_change("state")
            chunk = 4096 * 8   # 4096 frame stereo float32
            leftover = b""
            limit = self.sample_rate * 2
            while not job.stop.is_set():
                data = proc.stdout.read(chunk)
                if not data:
                    break
                data = leftover + data
                usable = len(data) - len(data) % 8
                leftover = data[usable:]
                block = np.frombuffer(data[:usable], dtype="<f4").reshape(-1, 2).T
                while len(self._ring) > limit and not job.stop.is_set():
                    job.stop.wait(0.02)
                if job.stop.is_set():
                    break
                self._ring.write(block)
            proc.wait(timeout=5) if not job.stop.is_set() else None
            if not job.stop.is_set() and proc.returncode not in (0, None):
                err = proc.stderr.read().decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(err[-1] if err else f"ffmpeg ha restituito {proc.returncode}")
        except Exception as exc:
            if not job.stop.is_set():
                job.error = str(exc)
                self.error = f"{track.title}: {exc}"
                self.on_change("error")
        finally:
            if job.proc is not None:
                try:
                    job.proc.stdout.close()
                    job.proc.stderr.close()
                except Exception:
                    pass
            job.eof = True
            if not job.stop.is_set() and (job.error or len(self._ring) == 0):
                self._ended.set()

    def _supervise(self) -> None:
        while not self._closed:
            self._ended.wait()
            self._ended.clear()
            if self._closed:
                return
            job = self._job
            if job is None or not job.eof or self.state not in ("playing", "loading"):
                continue
            if job.error and len(self.tracks) <= 1:
                self.stop()
                continue
            self.next(user=False)

    # Salvataggio --------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"tracks": [t.to_dict() for t in self.tracks], "index": self.index,
                "repeat": self.repeat, "shuffle": self.shuffle}

    def load_dict(self, d: dict) -> None:
        self.tracks = [Track.from_dict(x) for x in d.get("tracks", []) if x.get("source")]
        self.index = min(int(d.get("index", -1)), len(self.tracks) - 1)
        self.repeat = d.get("repeat", "off") if d.get("repeat") in ("off", "all", "one") else "off"
        self.shuffle = bool(d.get("shuffle", False))


def read_m3u(path: Path) -> list[Track]:
    tracks: list[Track] = []
    title = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            title = line.split(",", 1)[1].strip() if "," in line else None
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")):
            tracks.append(Track(title or line, line, "youtube"))
        else:
            p = Path(line)
            if not p.is_absolute():
                p = path.parent / p
            tracks.append(Track(title or p.stem, str(p), "file"))
        title = None
    return tracks


def write_m3u(path: Path, tracks: list[Track]) -> None:
    lines = ["#EXTM3U"]
    for t in tracks:
        dur = int(t.duration) if t.duration else -1
        lines.append(f"#EXTINF:{dur},{t.title}")
        lines.append(t.source)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

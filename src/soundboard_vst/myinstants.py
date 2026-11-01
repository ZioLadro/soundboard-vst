"""Ricerca e download di suoni da myinstants.com.

MyInstants non pubblica un'API documentata: la pagina di ricerca contiene però,
per ogni pulsante, una chiamata ``play('/media/sounds/<file>.mp3', ..., '<slug>')``
da cui si ricavano link e nome. Le richieste sono poche e solo su azione dell'utente.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

BASE = "https://www.myinstants.com"
USER_AGENT = f"SoundboardVST/{__version__} (+https://github.com/ZioLadro/soundboard-vst)"
TIMEOUT = 15
MAX_DOWNLOAD = 15 * 1024 * 1024   # i suoni di myinstants sono di pochi secondi

_PLAY_RE = re.compile(r"""play\(\s*'(/media/sounds/[^']+)'\s*,\s*'[^']*'\s*,\s*'([^']+)'\s*\)""")
_LINK_RE = re.compile(r"""<a[^>]+href="[^"]*/instant/([^"/]+)/?"[^>]*>(.*?)</a>""", re.S)
_TITLE_RE = re.compile(r"""title="(?:Play|Riproduci)\s+(.*?)(?:\s+sound|\s+suono)?\"""", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Instant:
    name: str
    slug: str
    url: str

    @property
    def page_url(self) -> str:
        return f"{BASE}/en/instant/{self.slug}/"


def _slug_to_name(slug: str) -> str:
    return re.sub(r"-\d+$", "", slug).replace("-", " ").strip().capitalize() or slug


def parse_results(page: str) -> list[Instant]:
    """Estrae i suoni da una pagina HTML di myinstants (ricerca, tendenze, categorie)."""
    titles: dict[str, str] = {}
    for slug, text in _LINK_RE.findall(page):
        t = html.unescape(_TAG_RE.sub("", text)).strip()
        if t:
            titles.setdefault(slug, t)

    out: list[Instant] = []
    seen: set[str] = set()
    for m in _PLAY_RE.finditer(page):
        path, slug = m.group(1), m.group(2)
        url = BASE + urllib.parse.quote(path, safe="/%._-")
        if url in seen:
            continue
        seen.add(url)
        name = titles.get(slug)
        if not name:
            near = _TITLE_RE.search(page, max(0, m.start() - 300), m.end() + 300)
            name = html.unescape(near.group(1)).strip() if near else _slug_to_name(slug)
        out.append(Instant(name, slug, url))
    return out


def _get(url: str, limit: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read((limit + 1) if limit else -1)
    if limit and len(data) > limit:
        raise ValueError("File troppo grande")
    return data


def search(query: str, page: int = 1) -> list[Instant]:
    params = {"name": query}
    if page > 1:
        params["page"] = str(page)
    url = f"{BASE}/en/search/?{urllib.parse.urlencode(params)}"
    return parse_results(_get(url).decode("utf-8", "replace"))


def trending(region: str = "it", page: int = 1) -> list[Instant]:
    url = f"{BASE}/en/index/{region}/" + (f"?page={page}" if page > 1 else "")
    return parse_results(_get(url).decode("utf-8", "replace"))


def safe_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:max_len].rstrip(" .") or "suono")


def download_bytes(instant: Instant) -> bytes:
    return _get(instant.url, limit=MAX_DOWNLOAD)


def save_to(folder: Path, instant: Instant, data: bytes | None = None) -> Path:
    """Salva il suono nella cartella senza sovrascrivere file esistenti."""
    data = data if data is not None else download_bytes(instant)
    ext = Path(urllib.parse.urlparse(instant.url).path).suffix.lower() or ".mp3"
    base = safe_filename(instant.name)
    dest = folder / f"{base}{ext}"
    n = 1
    while dest.exists():
        dest = folder / f"{base} ({n}){ext}"
        n += 1
    folder.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest

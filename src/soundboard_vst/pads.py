"""Disposizione dei pad: pagine di slot (righe × colonne) che puntano ai file dei suoni."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_SIZE, MAX_SIZE = 1, 12
DEFAULT_ROWS, DEFAULT_COLS = 6, 8


@dataclass
class PadPage:
    name: str
    slots: dict[int, str] = field(default_factory=dict)   # indice slot -> nome file


class PadLayout:
    def __init__(self, rows: int = DEFAULT_ROWS, cols: int = DEFAULT_COLS):
        self.rows = rows
        self.cols = cols
        self.pages: list[PadPage] = [PadPage("Pagina 1")]
        self.current = 0

    @property
    def size(self) -> int:
        return self.rows * self.cols

    @property
    def page(self) -> PadPage:
        return self.pages[self.current]

    # Pagine --------------------------------------------------------------------
    def add_page(self, name: str | None = None) -> int:
        self.pages.append(PadPage(name or f"Pagina {len(self.pages) + 1}"))
        return len(self.pages) - 1

    def remove_page(self, index: int) -> None:
        if len(self.pages) <= 1:
            self.pages[0].slots.clear()
            return
        del self.pages[index]
        self.current = min(self.current, len(self.pages) - 1)

    # Slot -------------------------------------------------------------------------
    def assign(self, page: int, index: int, key: str) -> None:
        if 0 <= index < self.size:
            self.pages[page].slots[index] = key

    def clear(self, page: int, index: int) -> None:
        self.pages[page].slots.pop(index, None)

    def move(self, page: int, src: int, dst: int) -> None:
        """Sposta un pad; se la destinazione è occupata, i due si scambiano."""
        slots = self.pages[page].slots
        a, b = slots.pop(src, None), slots.pop(dst, None)
        if a is not None:
            slots[dst] = a
        if b is not None:
            slots[src] = b

    def first_free(self, page: int) -> int | None:
        used = self.pages[page].slots
        return next((i for i in range(self.size) if i not in used), None)

    def place(self, key: str, page: int | None = None) -> tuple[int, int]:
        """Mette un suono nel primo slot libero (pagina corrente, poi le successive, poi una nuova)."""
        start = self.current if page is None else page
        order = list(range(start, len(self.pages))) + list(range(0, start))
        for p in order:
            i = self.first_free(p)
            if i is not None:
                self.pages[p].slots[i] = key
                return p, i
        p = self.add_page()
        self.pages[p].slots[0] = key
        return p, 0

    def contains(self, key: str) -> bool:
        return any(key in pg.slots.values() for pg in self.pages)

    def rename_key(self, old: str, new: str) -> None:
        for pg in self.pages:
            for i, k in pg.slots.items():
                if k == old:
                    pg.slots[i] = new

    def remove_key(self, key: str) -> None:
        for pg in self.pages:
            for i in [i for i, k in pg.slots.items() if k == key]:
                del pg.slots[i]

    def resize(self, rows: int, cols: int) -> None:
        """Cambia righe/colonne mantenendo la posizione (riga, colonna) dei pad.

        I pad che non entrano più vengono spostati negli slot liberi o in una nuova pagina.
        """
        rows = max(MIN_SIZE, min(MAX_SIZE, rows))
        cols = max(MIN_SIZE, min(MAX_SIZE, cols))
        overflow: list[tuple[int, str]] = []
        old_cols = self.cols
        for p, pg in enumerate(self.pages):
            new_slots: dict[int, str] = {}
            for i, key in sorted(pg.slots.items()):
                r, c = divmod(i, old_cols)
                if r < rows and c < cols:
                    new_slots[r * cols + c] = key
                else:
                    overflow.append((p, key))
            pg.slots = new_slots
        self.rows, self.cols = rows, cols
        for p, key in overflow:
            self.place(key, page=p)

    # Salvataggio ----------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "current": self.current,
            "pages": [{"name": pg.name, "slots": {str(i): k for i, k in pg.slots.items()}}
                      for pg in self.pages],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "PadLayout":
        layout = cls()
        if not d:
            return layout
        layout.rows = max(MIN_SIZE, min(MAX_SIZE, int(d.get("rows", DEFAULT_ROWS))))
        layout.cols = max(MIN_SIZE, min(MAX_SIZE, int(d.get("cols", DEFAULT_COLS))))
        pages = []
        for pd in d.get("pages") or []:
            slots = {}
            for i, k in (pd.get("slots") or {}).items():
                try:
                    idx = int(i)
                except ValueError:
                    continue
                if 0 <= idx < layout.size and k:
                    slots[idx] = str(k)
            pages.append(PadPage(str(pd.get("name") or f"Pagina {len(pages) + 1}"), slots))
        layout.pages = pages or [PadPage("Pagina 1")]
        layout.current = max(0, min(len(layout.pages) - 1, int(d.get("current", 0))))
        return layout

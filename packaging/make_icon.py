"""Rigenera ``packaging/icon.ico`` (icona dell'eseguibile) dal disegno in ``soundboard_vst.ui.icons``.

Uso: ``python packaging/make_icon.py`` (anche senza schermo: ``QT_QPA_PLATFORM=offscreen``).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> None:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841  serve a QPainter
    from soundboard_vst.ui.icons import app_icon_image, ico_bytes

    (ROOT / "icon.ico").write_bytes(ico_bytes())
    app_icon_image(256).save(str(ROOT / "icon.png"))
    print("scritto", ROOT / "icon.ico")


if __name__ == "__main__":
    main()

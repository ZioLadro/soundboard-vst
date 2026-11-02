"""Server web per il controllo remoto (aiohttp, già incluso con discord.py).

Gira in un thread con il suo event loop. Non tocca mai direttamente l'interfaccia o il motore:
- lo stato lo legge da ``get_state()`` (un'istantanea preparata dal thread della GUI);
- i comandi li passa a ``on_command(dict)``, che la GUI esegue sul proprio thread.

Ogni richiesta deve portare la chiave di accesso: nel link (``?k=…``), in un cookie impostato
alla prima visita o nell'intestazione ``X-Soundboard-Key``.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import secrets
import socket
import threading
from pathlib import Path
from typing import Callable

from aiohttp import web

from .page import PAGE_HTML

COOKIE = "sbkey"
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024


def new_token() -> str:
    return secrets.token_urlsafe(18)


def local_addresses() -> list[str]:
    """Indirizzi IPv4 del PC (LAN, ed eventualmente Tailscale 100.x), il principale per primo."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))      # nessun pacchetto inviato: serve solo a scegliere l'interfaccia
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if not addr.is_loopback and ip not in out:
            out.append(ip)
    return out or ["127.0.0.1"]


def is_tailscale(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


class RemoteServer:
    def __init__(self, get_state: Callable[[], dict], on_command: Callable[[dict], None],
                 get_image: Callable[[str], Path | None]):
        self.get_state = get_state
        self.on_command = on_command
        self.get_image = get_image
        self.token = ""
        self.port = DEFAULT_PORT
        self.error = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self.error

    # Avvio / arresto -------------------------------------------------------------------
    def start(self, port: int, token: str, host: str = "0.0.0.0") -> bool:
        self.stop()
        self.port, self.token, self.error = int(port), token, ""
        self._started.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, args=(host,), name="remote-web", daemon=True)
        self._thread.start()
        self._started.wait(5)
        return not self.error

    def _run(self, host: str) -> None:
        loop = self._loop
        asyncio.set_event_loop(loop)
        try:
            self._runner = web.AppRunner(self._make_app(), access_log=None)
            loop.run_until_complete(self._runner.setup())
            site = web.TCPSite(self._runner, host, self.port)
            loop.run_until_complete(site.start())
        except OSError as exc:
            self.error = f"Porta {self.port} non disponibile: {exc.strerror or exc}"
            self._started.set()
            loop.close()
            return
        self._started.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self._runner.cleanup())
            loop.close()

    def stop(self) -> None:
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        self._thread = None
        self._loop = None

    # App ----------------------------------------------------------------------------------
    def _make_app(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY, middlewares=[self._security])
        app.router.add_get("/", self._page)
        app.router.add_get("/api/state", self._state)
        app.router.add_post("/api/command", self._command)
        app.router.add_get("/api/image/{key}", self._image)
        return app

    def _authorized(self, request: web.Request) -> bool:
        if not self.token:
            return False
        given = (request.query.get("k") or request.cookies.get(COOKIE)
                 or request.headers.get("X-Soundboard-Key") or "")
        return hmac.compare_digest(given.encode(), self.token.encode())

    @web.middleware
    async def _security(self, request: web.Request, handler):
        if not self._authorized(request):
            if request.path == "/":
                return web.Response(status=401, content_type="text/html", text=(
                    "<meta name=viewport content='width=device-width'><body style='font-family:sans-serif;"
                    "background:#15171c;color:#e6e8ee;padding:24px'><h2>Soundboard VST</h2>"
                    "<p>Chiave di accesso mancante o non valida. Apri il link (o inquadra il QR code) che trovi "
                    "nella soundboard, in Impostazioni → Controllo remoto.</p>"))
            return web.json_response({"error": "non autorizzato"}, status=401)
        resp = await handler(request)
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.query.get("k"):
            resp.set_cookie(COOKIE, self.token, max_age=60 * 60 * 24 * 180, httponly=True, samesite="Strict")
        return resp

    async def _page(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("k"):
            # toglie la chiave dall'indirizzo (resta nel cookie), così non finisce nella cronologia
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, self.token, max_age=60 * 60 * 24 * 180, httponly=True, samesite="Strict")
            raise resp
        return web.Response(text=PAGE_HTML, content_type="text/html", charset="utf-8")

    async def _state(self, request: web.Request) -> web.Response:
        state = {k: v for k, v in self.get_state().items() if k != "library"}   # la pagina non la usa
        return web.json_response(state)

    async def _command(self, request: web.Request) -> web.Response:
        try:
            cmd = json.loads(await request.text())
        except (ValueError, UnicodeDecodeError):
            return web.json_response({"error": "JSON non valido"}, status=400)
        if not isinstance(cmd, dict) or not isinstance(cmd.get("cmd"), str):
            return web.json_response({"error": "comando non valido"}, status=400)
        self.on_command(cmd)
        return web.json_response({"ok": True})

    async def _image(self, request: web.Request) -> web.StreamResponse:
        path = self.get_image(request.match_info["key"])
        if path is None or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "max-age=3600"})

import json
import socket
import urllib.error
import urllib.request

import pytest

from soundboard_vst.remote.server import RemoteServer, is_tailscale, local_addresses, new_token


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG fake")
    commands = []
    srv = RemoteServer(lambda: {"ok": 1, "player": {"state": "stopped"}}, commands.append,
                       lambda key: img if key == "a.wav" else None)
    token = new_token()
    port = free_port()
    assert srv.start(port, token, host="127.0.0.1")
    yield srv, f"http://127.0.0.1:{port}", token, commands
    srv.stop()


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    return opener.open(req, timeout=5)


def test_requires_key(server):
    srv, base, token, _ = server
    for path in ("/", "/api/state", "/api/image/a.wav"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + path)
        assert e.value.code == 401
    with pytest.raises(urllib.error.HTTPError):
        get(base + "/api/state?k=sbagliata")


def test_page_redirect_sets_cookie_and_hides_key(server):
    srv, base, token, _ = server
    jar = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(jar)
    r = opener.open(f"{base}/?k={token}", timeout=5)
    assert r.geturl() == base + "/"                       # chiave tolta dall'indirizzo
    assert "Soundboard VST" in r.read().decode()
    state = json.loads(opener.open(base + "/api/state", timeout=5).read())   # basta il cookie
    assert state["ok"] == 1


def test_commands_and_images(server):
    srv, base, token, commands = server
    req = urllib.request.Request(base + "/api/command", data=json.dumps({"cmd": "pad", "page": 0, "index": 3}).encode(),
                                 headers={"X-Soundboard-Key": token, "Content-Type": "application/json"})
    assert json.loads(urllib.request.urlopen(req, timeout=5).read()) == {"ok": True}
    assert commands == [{"cmd": "pad", "page": 0, "index": 3}]
    bad = urllib.request.Request(base + "/api/command", data=b"[1,2]", headers={"X-Soundboard-Key": token})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(bad, timeout=5)
    assert e.value.code == 400
    assert get(base + "/api/image/a.wav", {"X-Soundboard-Key": token}).read().startswith(b"\x89PNG")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/image/nope.wav", {"X-Soundboard-Key": token})
    assert e.value.code == 404


def test_port_in_use_reports_error(server):
    srv, base, token, _ = server
    other = RemoteServer(lambda: {}, lambda c: None, lambda k: None)
    assert not other.start(srv.port, token, host="127.0.0.1")
    assert "non disponibile" in other.error


def test_addresses():
    assert all(a.count(".") == 3 for a in local_addresses())
    assert is_tailscale("100.101.102.103") and not is_tailscale("192.168.1.10")

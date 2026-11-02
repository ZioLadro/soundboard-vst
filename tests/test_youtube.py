from soundboard_vst import youtube
from soundboard_vst.audio.player import Track


class FakeYDL:
    calls = []
    responses = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, target, download=False):
        FakeYDL.calls.append((target, self.opts))
        return FakeYDL.responses[target]


def setup(monkeypatch, responses):
    FakeYDL.calls, FakeYDL.responses = [], responses
    monkeypatch.setattr(youtube, "_ydl_cls", FakeYDL)


def test_is_youtube_url():
    assert youtube.is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert youtube.is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert youtube.is_youtube_url("https://music.youtube.com/playlist?list=PL1")
    assert not youtube.is_youtube_url("https://notyoutube.com/watch?v=x")
    assert not youtube.is_youtube_url("bruh sound effect")


def test_resolve_video_and_playlist(monkeypatch):
    setup(monkeypatch, {
        "https://youtu.be/aaaaaaaaaaa": {"title": "Canzone", "webpage_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                                         "duration": 200},
        "https://www.youtube.com/playlist?list=PL": {"_type": "playlist", "entries": [
            {"id": "bbbbbbbbbbb", "url": "bbbbbbbbbbb", "title": "Uno", "duration": 61},
            {"id": "ccccccccccc", "url": "https://www.youtube.com/watch?v=ccccccccccc", "title": "Due"},
            {"id": "ddddddddddd", "title": "[Private video]"},
            None,
        ]},
    })
    [one] = youtube.resolve("https://youtu.be/aaaaaaaaaaa")
    assert (one.title, one.kind, one.duration) == ("Canzone", "youtube", 200.0)
    tracks = youtube.resolve("https://www.youtube.com/playlist?list=PL")
    assert [t.title for t in tracks] == ["Uno", "Due"]
    assert tracks[0].source == "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    opts = FakeYDL.calls[0][1]
    assert opts["extract_flat"] == "in_playlist" and "deno" in opts["js_runtimes"]


def test_search(monkeypatch):
    setup(monkeypatch, {"ytsearch3:lofi": {"entries": [{"id": "eeeeeeeeeee", "title": "Lofi", "duration": 3600}]}})
    [t] = youtube.search("lofi", count=3)
    assert t.source == "https://www.youtube.com/watch?v=eeeeeeeeeee"


def test_video_id():
    assert youtube.video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1") == "dQw4w9WgXcQ"
    assert youtube.video_id("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert youtube.video_id("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"


def test_download_uses_cache_and_dedupes(monkeypatch, tmp_path):
    """L'audio lo scarica yt-dlp (non ffmpeg, che riceve 403): la seconda volta arriva dalla cache."""
    monkeypatch.setattr(youtube, "cache_dir", lambda: tmp_path)
    downloads = []

    class DLYDL(FakeYDL):
        def extract_info(self, target, download=False):
            assert download and self.opts["format"] == "bestaudio/best" and self.opts["fixup"] == "never"
            downloads.append(target)
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            path = self.opts["outtmpl"].replace("%(ext)s", "webm")
            with open(path, "wb") as f:
                f.write(b"audio")
            return {"duration": 12, "requested_downloads": [{"filepath": path}]}

    monkeypatch.setattr(youtube, "_ydl_cls", DLYDL)
    t = Track("Video", "https://www.youtube.com/watch?v=fffffffffff", "youtube")
    progress = []
    src, headers = youtube.resolver(t, progress=progress.append)
    assert src.endswith("fffffffffff.webm") and headers == {} and progress == [0.5]
    assert t.duration == 12.0
    youtube.resolver(t)                          # dalla cache: nessun nuovo download
    assert downloads == [t.source]


def test_trim_cache(monkeypatch, tmp_path):
    import os
    import time
    monkeypatch.setattr(youtube, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(youtube, "CACHE_LIMIT", 250)
    for i, name in enumerate(["a.webm", "b.webm", "c.webm"]):
        p = tmp_path / name
        p.write_bytes(b"x" * 100)
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    youtube._trim_cache(keep=tmp_path / "a.webm")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.webm", "c.webm"]

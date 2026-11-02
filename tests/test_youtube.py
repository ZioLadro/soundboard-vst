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


def test_search_and_stream(monkeypatch):
    setup(monkeypatch, {
        "ytsearch3:lofi": {"entries": [{"id": "eeeeeeeeeee", "title": "Lofi", "duration": 3600}]},
        "https://www.youtube.com/watch?v=eeeeeeeeeee": {"url": "https://rr.googlevideo.com/x",
                                                        "http_headers": {"User-Agent": "UA"}, "duration": 3600},
    })
    [t] = youtube.search("lofi", count=3)
    url, headers = youtube.stream(Track("Lofi", t.source, "youtube"))
    assert url.startswith("https://rr.") and headers == {"User-Agent": "UA"}
    assert FakeYDL.calls[-1][1]["format"] == "bestaudio/best"

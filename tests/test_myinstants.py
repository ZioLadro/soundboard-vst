from soundboard_vst import myinstants
from soundboard_vst.myinstants import Instant, parse_results, safe_filename, save_to

SAMPLE = """
<div class="instant">
  <div class="circle small-button-background" style="background-color:#00FF00"></div>
  <button class="small-button" onclick="play('/media/sounds/vine-boom.mp3', 'loader-70972', 'vine-boom-sound-70972')"
          title="Play Vine Boom Sound sound" type="button"></button>
  <a href="/en/instant/vine-boom-sound-70972/" class="instant-link link-secondary">Vine Boom Sound</a>
</div>
<div class="instant">
  <button class="small-button" onclick="play('/media/sounds/bruh_&amp;_co.mp3', 'loader-1', 'bruh-1')"></button>
  <a href="/en/instant/bruh-1/" class="instant-link">Bruh &amp; co</a>
</div>
<div class="instant">
  <button class="small-button" onclick="play('/media/sounds/x y.mp3', 'loader-2', 'sad-trombone-2')"></button>
</div>
<button onclick="play('/media/sounds/vine-boom.mp3', 'loader-9', 'vine-boom-sound-70972')"></button>
"""


def test_parse_results():
    res = parse_results(SAMPLE)
    assert [r.name for r in res] == ["Vine Boom Sound", "Bruh & co", "Sad trombone"]
    assert res[0].url == "https://www.myinstants.com/media/sounds/vine-boom.mp3"
    assert res[2].url.endswith("/media/sounds/x%20y.mp3")
    assert res[0].page_url.endswith("/instant/vine-boom-sound-70972/")


def test_parse_empty_page():
    assert parse_results("<html>niente</html>") == []


def test_safe_filename():
    assert safe_filename('a/b:c*?"d<>|  ') == "a b c d"
    assert safe_filename("...") == "suono"


def test_save_does_not_overwrite(tmp_path):
    inst = Instant("Vine: Boom", "s", "https://x/media/sounds/v.mp3")
    p1 = save_to(tmp_path, inst, b"one")
    p2 = save_to(tmp_path, inst, b"two")
    assert p1.name == "Vine Boom.mp3" and p2.name == "Vine Boom (1).mp3"
    assert p1.read_bytes() == b"one"


def test_search_builds_url(monkeypatch):
    calls = []
    monkeypatch.setattr(myinstants, "_get", lambda url, limit=None: calls.append(url) or SAMPLE.encode())
    assert len(myinstants.search("vine boom", page=2)) == 3
    assert calls[0] == "https://www.myinstants.com/en/search/?name=vine+boom&page=2"

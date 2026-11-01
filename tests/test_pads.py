from soundboard_vst.pads import PadLayout


def test_place_fills_then_adds_page():
    lay = PadLayout(1, 2)
    assert lay.place("a.wav") == (0, 0)
    assert lay.place("b.wav") == (0, 1)
    assert lay.place("c.wav") == (1, 0)
    assert len(lay.pages) == 2


def test_move_swaps():
    lay = PadLayout(2, 2)
    lay.assign(0, 0, "a")
    lay.assign(0, 3, "b")
    lay.move(0, 0, 3)
    assert lay.page.slots == {3: "a", 0: "b"}
    lay.move(0, 3, 1)
    assert lay.page.slots == {1: "a", 0: "b"}


def test_resize_keeps_row_col_and_relocates_overflow():
    lay = PadLayout(2, 3)
    lay.assign(0, 0, "a")      # (0,0)
    lay.assign(0, 4, "b")      # (1,1)
    lay.assign(0, 5, "c")      # (1,2) -> non entra con 2 colonne
    lay.resize(2, 2)
    assert lay.page.slots[0] == "a"
    assert lay.page.slots[3] == "b"
    assert lay.contains("c")


def test_rename_remove_and_roundtrip():
    lay = PadLayout(2, 2)
    lay.place("a.wav")
    lay.add_page("Meme")
    lay.assign(1, 2, "a.wav")
    lay.rename_key("a.wav", "z.wav")
    assert lay.pages[1].slots[2] == "z.wav"
    lay.current = 1
    back = PadLayout.from_dict(lay.to_dict())
    assert back.pages[1].name == "Meme" and back.current == 1 and back.pages[0].slots == {0: "z.wav"}
    back.remove_key("z.wav")
    assert not back.contains("z.wav")


def test_from_dict_ignores_bad_entries():
    lay = PadLayout.from_dict({"rows": 99, "cols": 2, "pages": [{"slots": {"x": "a", "50": "b", "1": "c"}}]})
    assert lay.rows == 12 and lay.page.slots == {1: "c"}


def test_remove_last_page_only_clears():
    lay = PadLayout()
    lay.place("a")
    lay.remove_page(0)
    assert len(lay.pages) == 1 and not lay.page.slots

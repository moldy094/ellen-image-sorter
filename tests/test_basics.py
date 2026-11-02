# quick tests for the parts that dont need the internet
# run with: python -m pytest tests

import os
import importlib

import pytest
from PIL import Image, ImageDraw


@pytest.fixture
def home(tmp_path, monkeypatch):
    # point everything at a fake home folder so tests dont touch real settings
    monkeypatch.setenv("HOME", str(tmp_path))
    from ellensorter import config, library
    importlib.reload(config)
    importlib.reload(library)
    return tmp_path


def make_picture(path, colour, size=(400, 600), shape=0):
    im = Image.new("RGB", size, colour)
    d = ImageDraw.Draw(im)
    d.ellipse((50 + shape, 80, 300, 400 + shape), fill=(20, 20, 20))
    d.rectangle((10, 450, 380 - shape, 580), fill=(200, 30, 60))
    im.save(path)
    return path


def test_poses():
    from ellensorter.tagger import pick_pose
    assert pick_pose({"1girl", "solo", "upper_body"}) == "portraits"
    assert pick_pose({"1girl", "solo", "sitting", "holding_weapon"}) == "sitting"
    assert pick_pose({"2girls", "sitting"}) == "with others"
    assert pick_pose({"1girl", "solo", "comic"}) == "misc"
    assert pick_pose({"1girl", "solo", "lying", "on_back"}) == "lying down"
    assert pick_pose({"1girl", "solo", "full_body", "standing"}) == "full body"
    assert pick_pose({"1girl", "solo", "from_behind"}) == "from behind"
    assert pick_pose({"1girl", "solo", "scythe"}) == "action"


def test_goonery_modes():
    from ellensorter.tagger import is_goonery
    assert is_goonery("explicit", "lewd")
    assert is_goonery("questionable", "lewd")
    assert not is_goonery("sensitive", "lewd")
    assert is_goonery("sensitive", "suggestive")
    assert not is_goonery("explicit", "off")


def test_clean_name():
    from ellensorter.library import clean_name
    assert clean_name("freeman_(tkuh4475)") == "freeman (tkuh4475)"
    assert clean_name("a/b") == "a-b"
    assert clean_name("") == "unknown"


def test_numbering_and_moving(home):
    from ellensorter import library
    root = home / "lib"
    (root / "portraits").mkdir(parents=True)
    (root / "portraits" / "tanjwi 1.jpg").write_bytes(b"x")
    (root / "goonery" / "sitting").mkdir(parents=True)
    (root / "goonery" / "sitting" / "tanjwi 4.png").write_bytes(b"x")
    assert library.next_number(str(root), "tanjwi") == 5
    assert library.next_number(str(root), "someone else") == 1

    src = make_picture(root / "new.jpg", (240, 240, 240))
    dest = library.put_away(str(src), str(root), "", "sitting", "tanjwi", ".jpg")
    assert dest == str(root / "sitting" / "tanjwi 5.jpg")
    assert os.path.exists(dest) and not os.path.exists(src)


def test_filename_parsing():
    from ellensorter.lookup import from_filename
    r = {"artist": None, "source": None, "better": []}
    from_filename("129915854_p0_master1200.jpg", r)
    assert r["pixiv"] == ("129915854", 0)

    r = {"artist": None, "source": None, "better": []}
    from_filename("HWFxNuzaQAAWpH5.jpg", r)
    assert r["better"][0][1].startswith("https://pbs.twimg.com/media/HWFxNuzaQAAWpH5")

    r = {"artist": None, "source": None, "better": []}
    from_filename("__ellen_joe_zenless_zone_zero_drawn_by_tanjwi__0123456789abcdef0123456789abcdef.jpg", r)
    assert r["artist"] == "tanjwi" and r["md5"] == "0123456789abcdef0123456789abcdef"

    r = {"artist": None, "source": None, "better": []}
    from_filename("ellen 12.jpg", r)
    assert r["artist"] is None and not r["better"]


def test_duplicates(home):
    from ellensorter import library
    root = home / "lib"
    (root / "portraits").mkdir(parents=True)
    big = make_picture(root / "portraits" / "a 1.png", (240, 240, 240), size=(800, 1200))
    library.update_index(str(root), set())

    # exact same file
    im = library.open_picture(str(big))
    ph, dh = library.hashes_of(im)
    kind, other = library.find_duplicate(library.sha256_of(str(big)), ph, dh)
    assert kind == "exact"

    # same picture just smaller
    small = home / "small.jpg"
    Image.open(big).resize((400, 600)).save(small, quality=80)
    im = library.open_picture(str(small))
    ph, dh = library.hashes_of(im)
    kind, other = library.find_duplicate(library.sha256_of(str(small)), ph, dh)
    assert kind == "same" and other == str(big)

    # a totally different picture
    diff = home / "diff.png"
    Image.effect_noise((400, 600), 80).convert("RGB").save(diff)
    im = library.open_picture(str(diff))
    ph, dh = library.hashes_of(im)
    assert library.find_duplicate(library.sha256_of(str(diff)), ph, dh)[0] is None

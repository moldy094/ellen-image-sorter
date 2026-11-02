# figuring out who drew something
# goes through a bunch of places in order and stops at the first one that knows:
#   1. the file name (pixiv ids, danbooru "drawn by" names, md5 names)
#   2. danbooru by md5
#   3. our local danbooru catalog by image hash
#   4. saucenao (only if you put a key in)
#   5. reading the signature off the picture (only if easyocr is installed)
#   6. metadata stuck inside the file
# it also collects links to bigger versions of the picture for the quality upgrade

import os
import re
import json
import time
import hashlib

import requests
from PIL import Image

from . import catalog, config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"}
DANBOORU_UA = {"User-Agent": "ellen-image-sorter/1.0"}
ARTIST_CACHE = os.path.join(config.DATA_DIR, "artist_cache.json")

_artist_cache = None


def _load_cache():
    global _artist_cache
    if _artist_cache is None:
        try:
            with open(ARTIST_CACHE) as f:
                _artist_cache = json.load(f)
        except Exception:
            _artist_cache = {}
    return _artist_cache


def _save_cache():
    config.make_dirs()
    with open(ARTIST_CACHE, "w") as f:
        json.dump(_artist_cache, f, ensure_ascii=False)


def danbooru_artist_for(url_bit):
    # asks danbooru which artist has a link containing url_bit
    # eg "pixiv.net/users/123" or "x.com/someone". cached so we only ask once
    cache = _load_cache()
    if url_bit in cache:
        return cache[url_bit]
    name = None
    try:
        r = requests.get("https://danbooru.donmai.us/artists.json",
                         params={"search[url_matches]": f"*{url_bit}"}, headers=DANBOORU_UA, timeout=30)
        hits = [a["name"] for a in r.json() if not a.get("is_deleted")]
        if hits:
            name = hits[0]
    except Exception:
        return None  # dont cache errors
    cache[url_bit] = name
    _save_cache()
    return name


def first_artist(tag_string):
    names = [a for a in (tag_string or "").split() if a not in ("banned_artist", "artist_request")]
    return " & ".join(names) if names else None


# ---------- 1. file names ----------

def from_filename(filename, result):
    stem = os.path.splitext(filename)[0]

    # pixiv saves look like 123456789_p0.png or 123456789_p0_master1200.jpg
    m = re.match(r"^(\d{6,})_p(\d+)", stem)
    if m:
        result["pixiv"] = (m.group(1), int(m.group(2)))

    # twitter media ids are 15 characters like HWFxNuzaQAAWpH5
    if re.fullmatch(r"[A-Za-z0-9_-]{15}", stem):
        ext = "png" if filename.lower().endswith(".png") else "jpg"
        result["better"].append(("twitter", f"https://pbs.twimg.com/media/{stem}?format={ext}&name=orig"))

    # danbooru downloads: __ellen_joe_zenless_zone_zero_drawn_by_someone__<md5>.jpg
    m = re.search(r"drawn_by_(.+?)__([0-9a-f]{32})", stem)
    if m:
        result["md5"] = m.group(2)
        if not result["artist"]:
            result["artist"], result["source"] = m.group(1), "filename"

    # gelbooru / danbooru raw downloads are just the md5
    if re.fullmatch(r"[0-9a-f]{32}", stem):
        result["md5"] = stem


# ---------- pixiv ----------

def from_pixiv(result):
    illust, page = result["pixiv"]
    try:
        r = requests.get(f"https://www.pixiv.net/ajax/illust/{illust}", headers={**UA, "Referer": "https://www.pixiv.net/"}, timeout=30)
        body = r.json().get("body") or {}
    except Exception:
        return
    if not body:
        return
    if body.get("aiType") == 2:
        result["ai_hint"] = "pixiv says its ai"
    if not result["artist"] and body.get("userId"):
        name = danbooru_artist_for(f"pixiv.net/users/{body['userId']}")
        if not name:
            # pixiv names have junk like "@commissions open" on the end, cut that off
            name = re.sub(r"[@＠].*$", "", body.get("userName", "")).strip()
        if name:
            result["artist"], result["source"] = name, "pixiv"
    try:
        r = requests.get(f"https://www.pixiv.net/ajax/illust/{illust}/pages", headers={**UA, "Referer": "https://www.pixiv.net/"}, timeout=30)
        pages = r.json()["body"]
        result["better"].append(("pixiv", pages[page]["urls"]["original"]))
    except Exception:
        pass


# ---------- danbooru ----------

def use_post(post, result, source):
    result["post"] = post
    artist = first_artist(post.get("artist") or post.get("tag_string_artist"))
    if artist and not result["artist"]:
        result["artist"], result["source"] = artist, source
    if post.get("file_url") and post.get("ext", post.get("file_ext")) in ("jpg", "png", "webp", "gif"):
        result["better"].append(("danbooru", post["file_url"]))


def from_danbooru_md5(md5, result):
    post = catalog.by_md5(md5)
    if post:
        use_post(post, result, "danbooru")
        return
    try:
        r = requests.get("https://danbooru.donmai.us/posts.json", params={"tags": f"md5:{md5}"}, headers=DANBOORU_UA, timeout=30)
        posts = r.json()
    except Exception:
        return
    if posts:
        p = posts[0]
        use_post({"artist": p.get("tag_string_artist"), "rating": p.get("rating"),
                  "tags": p.get("tag_string_general", ""), "meta": p.get("tag_string_meta", ""),
                  "file_url": p.get("file_url"), "ext": p.get("file_ext")}, result, "danbooru")


# ---------- saucenao ----------

def from_saucenao(path, key, result):
    try:
        with open(path, "rb") as f:
            r = requests.post("https://saucenao.com/search.php",
                              params={"output_type": 2, "api_key": key, "numres": 8, "db": 999},
                              files={"file": f}, timeout=60)
        data = r.json()
    except Exception as e:
        result["notes"].append(f"saucenao failed: {e}")
        return
    if data.get("header", {}).get("status", 0) < 0:
        result["notes"].append("saucenao: " + str(data.get("header", {}).get("message", "error"))[:120])
        return
    for res in data.get("results") or []:
        if float(res["header"]["similarity"]) < 85:
            continue
        d = res["data"]
        name = None
        if d.get("twitter_user_handle"):
            name = danbooru_artist_for(f"x.com/{d['twitter_user_handle']}") or danbooru_artist_for(f"twitter.com/{d['twitter_user_handle']}") or d["twitter_user_handle"]
        elif d.get("pixiv_id") and d.get("member_id"):
            name = danbooru_artist_for(f"pixiv.net/users/{d['member_id']}") or d.get("member_name")
        elif d.get("creator"):
            c = d["creator"]
            name = c[0] if isinstance(c, list) else c
            if name and name.lower() in ("unknown", "artist request"):
                name = None
        if name:
            result["artist"], result["source"] = name, "saucenao"
            return


# ---------- ocr ----------

_reader = None


def ocr_available():
    try:
        import easyocr  # noqa
        return True
    except Exception:
        return False


HANDLE = re.compile(r"(?:@|patreon\.com/(?:c/)?|x\.com/|twitter\.com/|pixiv\s*:\s*|fanbox\s*:\s*)\s?([A-Za-z0-9_\-]{3,30})", re.I)


def from_signature(im, result):
    # reads text off the picture and looks for @handles or patreon links
    global _reader
    import numpy as np
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    small = im.copy()
    small.thumbnail((1600, 1600))
    pieces = [small]
    # signatures are tiny and usually in a corner, so also read each corner at full size
    w, h = im.size
    for x0, y0, x1, y1 in ((0, 0, .32, .22), (.68, 0, 1, .22), (0, .78, .32, 1), (.68, .78, 1, 1), (.3, .85, .7, 1)):
        corner = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
        grow = min(2.0, 900 / max(corner.width, 1))
        if grow > 1:
            corner = corner.resize((int(corner.width * grow), int(corner.height * grow)))
        pieces.append(corner)
    for piece in pieces:
        for _, text, conf in _reader.readtext(np.asarray(piece), min_size=6, text_threshold=0.5):
            if conf < 0.5:
                continue
            m = HANDLE.search(text)
            if not m:
                continue
            handle = m.group(1)
            if handle.lower() in ("mihoyo", "hoyoverse"):
                continue
            name = danbooru_artist_for(f"x.com/{handle}") or danbooru_artist_for(f"twitter.com/{handle}") or handle
            result["artist"], result["source"] = name, "signature"
            if re.search(r"(^|[_\-])ai([_\-]|$)|^ai|ai$", handle, re.I):
                result["ai_hint"] = f"signed as {handle}"
            return


# ---------- metadata ----------

def from_metadata(path, result):
    try:
        im = Image.open(path)
        info = dict(im.info or {})
        exif = im.getexif()
    except Exception:
        return
    text = " ".join(str(v)[:2000] for k, v in info.items() if isinstance(v, str))
    if re.search(r"(Steps: \d+|Sampler:|NovelAI|\"sampler_name\"|ComfyUI|negative_prompt|masterpiece, best quality)", text):
        result["ai_hint"] = "generator settings inside the file"
    if info.get("Software", "").lower().startswith(("novelai", "stable diffusion")):
        result["ai_hint"] = "made with " + info["Software"]
    artist = exif.get(0x013B) if exif else None
    if artist and not result["artist"]:
        result["artist"], result["source"] = str(artist).strip(), "metadata"


# ---------- putting it together ----------

def find(path, im, ph, dh, cfg, log=print):
    result = {"artist": None, "source": None, "post": None, "better": [], "ai_hint": None, "notes": []}
    src = cfg["sources"]

    from_filename(os.path.basename(path), result)
    from_metadata(path, result)

    if src["pixiv"] and result.get("pixiv"):
        from_pixiv(result)

    if not result["post"]:
        md5 = result.get("md5") or hashlib.md5(open(path, "rb").read()).hexdigest()
        from_danbooru_md5(md5, result)

    if not result["post"] and src["danbooru_catalog"]:
        post = catalog.match(ph, dh)
        if post:
            use_post(post, result, "danbooru")

    if not result["artist"] and src["saucenao_key"]:
        from_saucenao(path, src["saucenao_key"], result)
        time.sleep(1)  # saucenao gets mad if you spam it

    if not result["artist"] and src["ocr"] and ocr_available():
        try:
            from_signature(im, result)
        except Exception as e:
            result["notes"].append(f"ocr failed: {e}")

    return result

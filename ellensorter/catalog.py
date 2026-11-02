# local copy of every danbooru post for the character
# we keep the tags, artist, rating and a hash of each thumbnail so we can match
# a random image from twitter or wherever back to its danbooru post without
# having to reverse image search every single time

import io
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

from . import config
from .library import hashes_of, distance, to_db, from_db

# danbooru blocks browser looking user agents on the cdn, a plain one works fine
HEADERS = {"User-Agent": "ellen-image-sorter/1.0"}
API = "https://danbooru.donmai.us"

_cache = None  # list of (id, phash, dhash) so matching doesnt hit the disk every time


def db():
    config.make_dirs()
    con = sqlite3.connect(config.CATALOG_DB)
    con.execute("""create table if not exists posts (
        id integer primary key, md5 text, artist text, rating text, tags text, meta text,
        file_url text, ext text, width integer, height integer, phash integer, dhash integer)""")
    return con


def count():
    con = db()
    n = con.execute("select count(*) from posts").fetchone()[0]
    con.close()
    return n


def get_post(post_id):
    con = db()
    con.row_factory = sqlite3.Row
    row = con.execute("select * from posts where id = ?", (post_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def by_md5(md5):
    con = db()
    con.row_factory = sqlite3.Row
    row = con.execute("select * from posts where md5 = ?", (md5,)).fetchone()
    con.close()
    return dict(row) if row else None


def thumb_url(post):
    for v in (post.get("media_asset") or {}).get("variants") or []:
        if v["type"] == "360x360":
            return v["url"]
    return post.get("preview_file_url")


def hash_thumb(post):
    url = thumb_url(post)
    if not url:
        return post, None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            return post, hashes_of(im)
        except Exception:
            time.sleep(3)
    return post, None


def save_posts(con, posts):
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(hash_thumb, posts))
    saved = 0
    for p, h in results:
        if h is None:
            continue
        saved += 1
        con.execute("insert or replace into posts values (?,?,?,?,?,?,?,?,?,?,?,?)", (
            p["id"], p.get("md5"), p.get("tag_string_artist", ""), p.get("rating"),
            p.get("tag_string_general", ""), p.get("tag_string_meta", ""), p.get("file_url"),
            p.get("file_ext"), p.get("image_width"), p.get("image_height"), to_db(h[0]), to_db(h[1])))
    con.commit()
    return saved


def sync(tag, log=print):
    # first run grabs everything (newest to oldest), after that only new posts
    global _cache
    con = db()
    newest = con.execute("select max(id) from posts").fetchone()[0]
    added = 0
    if newest is None:
        log(f"building the {tag} catalog for the first time, this takes a few minutes")
        page = None
        while True:
            params = {"tags": tag, "limit": 200}
            if page:
                params["page"] = page
            posts = get_json(f"{API}/posts.json", params)
            if not posts:
                break
            added += save_posts(con, posts)
            log(f"catalog: {added} posts")
            page = f"b{min(p['id'] for p in posts)}"
            time.sleep(0.5)
    else:
        page = f"a{newest}"
        while True:
            posts = get_json(f"{API}/posts.json", {"tags": tag, "limit": 200, "page": page})
            if not posts:
                break
            added += save_posts(con, posts)
            page = f"a{max(p['id'] for p in posts)}"
            time.sleep(0.5)
    con.close()
    _cache = None
    return added


def get_json(url, params):
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"danbooru isnt answering ({url})")


def match(ph, dh):
    # finds the closest post. under 10 on the phash and 12 on the dhash was
    # basically always the same picture when i checked by eye
    global _cache
    if _cache is None:
        con = db()
        _cache = [(i, from_db(p), from_db(d)) for i, p, d in con.execute("select id, phash, dhash from posts")]
        con.close()
    best = None
    for pid, p2, d2 in _cache:
        pd = distance(ph, p2)
        if pd > 10:
            continue
        dd = distance(dh, d2)
        if dd > 12:
            continue
        if best is None or pd + dd < best[0]:
            best = (pd + dd, pid, pd, dd)
    if best is None:
        return None
    post = get_post(best[1])
    post["_pd"], post["_dd"] = best[2], best[3]
    return post

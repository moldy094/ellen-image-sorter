# stuff that deals with the sorted folder itself
# keeps a little sqlite index of every file so we can spot duplicates fast,
# figures out the next free "artist N" name, and moves files into place

import os
import re
import csv
import time
import shutil
import sqlite3
import hashlib
import subprocess
import tempfile

import imagehash
from PIL import Image

from . import config

POSES = ["portraits", "full body", "sitting", "lying down", "from behind", "action", "with others", "misc"]
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl")
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".m4v")


def is_image(path):
    return path.lower().endswith(IMAGE_EXTS)


def is_video(path):
    return path.lower().endswith(VIDEO_EXTS)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def video_frame(path):
    # grab a frame from the middle of the video so we can hash it and tag it
    # returns a PIL image or None if ffmpeg cant do it
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
        dur = float(out.stdout.strip() or 0)
    except Exception:
        dur = 0
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(dur / 2), "-i", path,
                        "-frames:v", "1", tmp.name], check=True, timeout=120)
        im = Image.open(tmp.name)
        im.load()
        return im.convert("RGB")
    except Exception:
        return None
    finally:
        os.remove(tmp.name)


def open_picture(path, small=False):
    # gives back an RGB PIL image for images and videos (first frame for gifs)
    # small=True is for hashing only, big jpegs decode way faster at a smaller size
    if is_video(path):
        return video_frame(path)
    im = Image.open(path)
    if small and im.format == "JPEG":
        im.draft("RGB", (1024, 1024))
    im.seek(0)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    return im.convert("RGB")


def hashes_of(im):
    # phash + dhash as plain ints so we can xor them later
    return int(str(imagehash.phash(im)), 16), int(str(imagehash.dhash(im)), 16)


def distance(a, b):
    return (a ^ b).bit_count()


# sqlite only does signed 64 bit numbers and the hashes are unsigned, so flip them
# to signed when saving and back when loading
def to_db(h):
    return h - (1 << 64) if h >= (1 << 63) else h


def from_db(h):
    return h & ((1 << 64) - 1)


# ---------- the index ----------

def db():
    config.make_dirs()
    con = sqlite3.connect(config.LIBRARY_DB)
    con.execute("""create table if not exists files (
        path text primary key, sha256 text, phash integer, dhash integer,
        width integer, height integer, size integer, mtime real)""")
    return con


def walk_sorted_files(root, ignore):
    # every file that is already sorted (so not the ones sitting in the root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            dirnames[:] = [d for d in dirnames if d not in ignore and not d.startswith(".")]
            continue
        for f in filenames:
            if f.startswith("."):
                continue
            yield os.path.join(dirpath, f)


def update_index(root, ignore, log=print):
    # adds new files, drops ones that are gone. only rehashes stuff that changed
    con = db()
    known = {row[0]: (row[1], row[2]) for row in con.execute("select path, size, mtime from files")}
    seen = set()
    added = 0
    for path in walk_sorted_files(root, ignore):
        if not (is_image(path) or is_video(path)):
            continue
        seen.add(path)
        st = os.stat(path)
        if path in known and known[path] == (st.st_size, st.st_mtime):
            continue
        try:
            if is_video(path):
                width = height = 0
            else:
                with Image.open(path) as probe:
                    width, height = probe.size
            im = open_picture(path, small=True)
            if im is None:
                continue
            width = width or im.width
            height = height or im.height
            ph, dh = hashes_of(im)
            con.execute("insert or replace into files values (?,?,?,?,?,?,?,?)",
                        (path, sha256_of(path), to_db(ph), to_db(dh), width, height, st.st_size, st.st_mtime))
            added += 1
            if added % 200 == 0:
                con.commit()
                log(f"indexed {added} files so far")
        except Exception as e:
            log(f"couldnt index {path}: {e}")
    gone = [p for p in known if p not in seen]
    for p in gone:
        con.execute("delete from files where path = ?", (p,))
    con.commit()
    con.close()
    return added, len(gone)


def add_to_index(path):
    con = db()
    im = open_picture(path)
    if im is not None:
        st = os.stat(path)
        ph, dh = hashes_of(im)
        con.execute("insert or replace into files values (?,?,?,?,?,?,?,?)",
                    (path, sha256_of(path), to_db(ph), to_db(dh), im.width, im.height, st.st_size, st.st_mtime))
        con.commit()
    con.close()


def remove_from_index(path):
    con = db()
    con.execute("delete from files where path = ?", (path,))
    con.commit()
    con.close()


def find_duplicate(sha, ph, dh):
    # returns ("exact", path) or ("same", path) or ("maybe", path) or (None, None)
    # same = same picture just a different size or jpeg quality
    # maybe = looks really close but could be an edit, like a translated version
    con = db()
    row = con.execute("select path from files where sha256 = ?", (sha,)).fetchone()
    if row:
        con.close()
        return "exact", row[0]
    best = None
    for path, p2, d2 in con.execute("select path, phash, dhash from files"):
        pd = distance(ph, from_db(p2))
        dd = distance(dh, from_db(d2))
        if pd <= 6 and dd <= 10:
            if best is None or pd + dd < best[0]:
                best = (pd + dd, pd, dd, path)
    con.close()
    if best is None:
        return None, None
    if best[1] <= 2 and best[2] <= 4:
        return "same", best[3]
    return "maybe", best[3]


# ---------- naming and moving ----------

def clean_name(name):
    # danbooru style names have underscores, swap them for spaces.
    # also get rid of characters linux or windows wont like in a file name
    name = name.replace("_", " ")
    name = re.sub(r'[/\\:*?"<>|]', "-", name)
    return name.strip(" .") or "unknown"


def next_number(root, base):
    # look through every file for "base N.ext" and return the biggest N + 1
    pattern = re.compile(r"^" + re.escape(base) + r" (\d+)\.[^.]+$")
    biggest = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            m = pattern.match(f)
            if m:
                biggest = max(biggest, int(m.group(1)))
    return biggest + 1


def put_away(src, root, tree, pose, artist, ext):
    # moves the file to root/tree/pose/"artist N.ext" and returns the new path
    base = clean_name(artist) if artist else "unknown"
    folder = os.path.join(root, tree, pose) if tree else os.path.join(root, pose)
    os.makedirs(folder, exist_ok=True)
    n = next_number(root, base)
    dest = os.path.join(folder, f"{base} {n}{ext}")
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(folder, f"{base} {n}{ext}")
    shutil.move(src, dest)
    return dest


def trash(path):
    # send to the desktop trash so its recoverable. if gio isnt around just move it
    # into a _trash folder next to it
    r = subprocess.run(["gio", "trash", path], capture_output=True)
    if r.returncode != 0:
        folder = os.path.join(os.path.dirname(path), "_trash")
        os.makedirs(folder, exist_ok=True)
        shutil.move(path, os.path.join(folder, os.path.basename(path)))


def needs_review(path, root):
    # something went wrong with this one, park it so we dont keep retrying it
    folder = os.path.join(root, "_needs_review")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, os.path.basename(path))
    if os.path.exists(dest):
        stem, ext = os.path.splitext(dest)
        dest = f"{stem} {int(time.time())}{ext}"
    shutil.move(path, dest)
    return dest


def write_manifest(root, original, action, new_path, artist, source, pose, tree):
    # same csv the first big sort made, so theres one place that says where everything went
    path = os.path.join(root, "_sort_manifest.csv")
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["original", "action", "new_path", "artist", "artist_source", "pose", "tree"])
        rel = os.path.relpath(new_path, root) if new_path else ""
        w.writerow([original, action, rel, artist or "", source or "", pose or "", tree or "main"])

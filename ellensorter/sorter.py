# the main thing. watches the root folder and sorts anything new that shows up
#
# for each new file:
#   hash it -> throw it out if we already have the exact same file
#   find the artist (see lookup.py)
#   grab a bigger version if there is one
#   check for the same picture at a different size
#   tag it -> pick a pose folder, check if its goonery or ai
#   move it to  <root>/[goonery|ai]/<pose>/<artist> <number>.<ext>

import os
import io
import json
import time
import logging
import warnings

import requests
from PIL import Image

from . import config, library, lookup, catalog, tagger, notify

log = logging.getLogger("ellen-sorter")

# stuff browsers and torrent clients leave around while still downloading
UNFINISHED = (".part", ".crdownload", ".tmp", ".download", ".!qb", ".partial")


def setup_logging():
    config.make_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler()],
    )
    # tons of images have slightly broken exif, PIL warns about every one of them
    warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
    # huggingface logs every single http request otherwise
    for noisy in ("httpx", "huggingface_hub", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def activity(entry):
    # little log the gui reads to show whats been happening
    entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(config.ACTIVITY_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def quality(im, path):
    # more pixels wins. if its a tie a png beats a jpg, then bigger file wins
    return (im.width * im.height, 1 if path.lower().endswith(".png") else 0, os.path.getsize(path))


def try_upgrade(path, im, ph, dh, candidates):
    # downloads every bigger version we found and keeps the best one, but only if
    # it really is the same picture (danbooru matches could be an edit or a variant)
    best_path, best_im, best_q = path, im, quality(im, path)
    folder = os.path.dirname(path)
    for i, (where, url) in enumerate(candidates):
        if where == "danbooru":
            headers = lookup.DANBOORU_UA
        else:
            headers = {**lookup.UA, "Referer": "https://www.pixiv.net/"} if where == "pixiv" else lookup.UA
        try:
            for attempt in range(4):
                r = requests.get(url, headers=headers, timeout=180)
                if r.status_code != 429:
                    break
                time.sleep(10 * (attempt + 1))  # rate limited, back off a bit
            r.raise_for_status()
            new_im = Image.open(io.BytesIO(r.content))
            fmt = (new_im.format or "JPEG").lower()
            new_im = new_im.convert("RGB")
        except Exception as e:
            log.info(f"  couldnt get the {where} version: {e}")
            continue
        p2, d2 = library.hashes_of(new_im)
        limit = (6, 10) if where == "danbooru" else (12, 16)
        if library.distance(ph, p2) > limit[0] or library.distance(dh, d2) > limit[1]:
            log.info(f"  {where} version looks different, skipping it")
            continue
        ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}.get(fmt, ".jpg")
        tmp = os.path.join(folder, f".ellen-sorter-download-{i}{ext}")
        with open(tmp, "wb") as f:
            f.write(r.content)
        q = quality(new_im, tmp)
        if q > best_q:
            if best_path != path:
                os.remove(best_path)
            best_path, best_im, best_q = tmp, new_im, q
            log.info(f"  got a better version from {where} ({new_im.width}x{new_im.height})")
        else:
            os.remove(tmp)
    return best_path, best_im


def sort_file(path, cfg):
    root = cfg["library"]["root"]
    sort_cfg = cfg["sorting"]
    name = os.path.basename(path)
    log.info(f"sorting {name}")

    if not (library.is_image(path) or library.is_video(path)):
        dest = library.needs_review(path, root)
        notify.problem(cfg, f"{name} isnt a picture or video i know how to sort, moved it to _needs_review")
        activity({"file": name, "error": "unknown file type", "dest": dest})
        return

    im = library.open_picture(path)
    if im is None:
        raise RuntimeError("couldnt open it, the file might be broken")
    sha = library.sha256_of(path)
    ph, dh = library.hashes_of(im)

    dupe, other = library.find_duplicate(sha, ph, dh)
    if dupe == "exact" and sort_cfg["duplicates"] == "trash":
        library.trash(path)
        library.write_manifest(root, name, "trashed-exact-duplicate-of", other, "", "", "", "")
        activity({"file": name, "note": f"exact copy of {os.path.relpath(other, root)}, sent to trash"})
        log.info("  exact duplicate, trashed")
        return

    # same picture at a different size or quality. if what we have is at least as
    # good just bin the new one, otherwise the old one goes and the new one gets sorted
    if dupe == "same" and sort_cfg["duplicates"] == "trash" and os.path.exists(other):
        other_im = library.open_picture(other)
        if other_im is not None and quality(other_im, other) >= quality(im, path):
            library.trash(path)
            library.write_manifest(root, name, "trashed-smaller-copy-of", other, "", "", "", "")
            activity({"file": name, "note": f"smaller copy of {os.path.relpath(other, root)}, sent to trash"})
            log.info("  we already have a better copy, trashed this one")
            return
        library.trash(other)
        library.remove_from_index(other)
        library.write_manifest(root, os.path.relpath(other, root), "trashed-replaced-by-bigger", name, "", "", "", "")
        log.info(f"  this is a bigger copy of {other}, trashed the old one")

    found = lookup.find(path, im, ph, dh, cfg)
    for note in found["notes"]:
        log.info("  " + note)

    original_name = name
    if library.is_image(path) and sort_cfg["upgrade_quality"] and found["better"]:
        new_path, im = try_upgrade(path, im, ph, dh, found["better"])
        if new_path != path:
            # the one you dropped in goes to the trash, the bigger download takes its place
            library.trash(path)
            path = new_path

    post = found["post"]
    if post:
        tags = set((post.get("tags") or "").split())
        meta = set((post.get("meta") or "").split())
        rating = tagger.DANBOORU_RATINGS.get(post.get("rating"), "general")
    else:
        tags, rating = tagger.tag(im, cfg["tagger"]["model"])
        meta = set()

    # dont let the weird stuff into the goonery folder, you can look at it and decide yourself
    if sort_cfg["goonery_filter"] and sort_cfg["goonery"] != "off":
        reason = tagger.too_much(tags | meta, rating)
        if reason:
            parked = library.needs_review(path, root)
            library.write_manifest(root, original_name, "parked-goonery-filter", parked, found["artist"], found["source"], "", "")
            activity({"file": original_name, "note": f"parked in _needs_review ({reason})"})
            log.info(f"  parked in _needs_review ({reason})")
            notify.sorted_ok(cfg, f"{original_name} went to _needs_review ({reason})")
            return

    is_ai = bool(found["ai_hint"]) or bool((tags | meta) & {"ai-generated", "ai-assisted"})
    if sort_cfg["separate_ai"] and is_ai:
        tree = sort_cfg["ai_folder"]
    elif tagger.is_goonery(rating, sort_cfg["goonery"]):
        tree = sort_cfg["goonery_folder"]
    else:
        tree = ""
    pose = tagger.pick_pose(tags)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jpeg":
        ext = ".jpg"

    dest = library.put_away(path, root, tree, pose, found["artist"], ext)
    library.add_to_index(dest)
    library.write_manifest(root, original_name, "auto-sorted", dest, found["artist"], found["source"], pose, tree)
    rel = os.path.relpath(dest, root)
    entry = {"file": original_name, "dest": rel, "artist": found["artist"] or "unknown", "source": found["source"]}
    if is_ai:
        entry["note"] = "looks ai generated (" + (found["ai_hint"] or "danbooru tag") + ")"
    if dupe == "maybe":
        entry["note"] = f"looks a lot like {os.path.relpath(other, root)}, kept both"
        notify.send(cfg, "possible duplicate", f"{original_name} looks a lot like {os.path.relpath(other, root)}. kept both, have a look")
    activity(entry)
    log.info(f"  -> {rel}  (artist: {found['artist'] or 'unknown'} via {found['source'] or 'nothing'})")
    notify.sorted_ok(cfg, f"{original_name} -> {rel}")


def waiting_files(root, ignore):
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return None
    files = []
    for e in entries:
        if not e.is_file() or e.name in ignore or e.name.startswith("."):
            continue
        if e.name.lower().endswith(UNFINISHED):
            continue
        files.append(e.path)
    return files


def sort_one_safely(path, cfg):
    try:
        sort_file(path, cfg)
        return True
    except Exception as e:
        log.exception(f"failed on {path}")
        root = cfg["library"]["root"]
        name = os.path.basename(path)
        if os.path.exists(path):
            try:
                library.needs_review(path, root)
            except Exception:
                pass
        activity({"file": name, "error": str(e)})
        notify.problem(cfg, f"couldnt sort {name}: {e}. its in _needs_review now")
        # clean up any half done downloads from the quality upgrade
        for leftover in os.listdir(root):
            if leftover.startswith(".ellen-sorter-download-"):
                os.remove(os.path.join(root, leftover))
        return False


def sort_everything_now(cfg):
    # one pass over the root folder, used by "ellen-sorter scan"
    root = cfg["library"]["root"]
    files = waiting_files(root, set(cfg["library"]["ignore"]))
    if files is None:
        print(f"cant find {root}")
        return
    library.update_index(root, set(cfg["library"]["ignore"]), log=log.info)
    for f in sorted(files):
        sort_one_safely(f, cfg)


def last_sync_file():
    return os.path.join(config.STATE_DIR, "last_catalog_sync")


def sync_catalog_if_due(cfg):
    if not cfg["sources"]["danbooru_catalog"]:
        return
    try:
        last = float(open(last_sync_file()).read())
    except Exception:
        last = 0
    if time.time() - last < cfg["sources"]["catalog_sync_hours"] * 3600:
        return
    try:
        added = catalog.sync(cfg["library"]["character_tag"], log=log.info)
        log.info(f"catalog sync done, {added} new posts")
        with open(last_sync_file(), "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        log.warning(f"catalog sync failed: {e}")
        notify.problem(cfg, f"couldnt update the danbooru catalog: {e}")


def run():
    setup_logging()
    cfg = config.load()
    cfg_time = os.path.getmtime(config.CONFIG_FILE) if os.path.exists(config.CONFIG_FILE) else 0
    root = cfg["library"]["root"]
    log.info(f"ellen image sorter starting, watching {root}")

    if os.path.isdir(root):
        added, gone = library.update_index(root, set(cfg["library"]["ignore"]), log=log.info)
        log.info(f"library index up to date ({added} added, {gone} removed)")
    sync_catalog_if_due(cfg)

    seen = {}  # path -> (size, mtime, when we first saw it like that)
    folder_missing = False
    while True:
        # pick up settings changes from the gui without needing a restart
        if os.path.exists(config.CONFIG_FILE) and os.path.getmtime(config.CONFIG_FILE) != cfg_time:
            cfg = config.load()
            cfg_time = os.path.getmtime(config.CONFIG_FILE)
            if cfg["library"]["root"] != root:
                root = cfg["library"]["root"]
                log.info(f"settings changed, now watching {root}")
                if os.path.isdir(root):
                    library.update_index(root, set(cfg["library"]["ignore"]), log=log.info)
            log.info("reloaded settings")

        files = waiting_files(root, set(cfg["library"]["ignore"]))
        if files is None:
            if not folder_missing:
                log.warning(f"cant find {root}")
                notify.problem(cfg, f"cant find the folder {root}. is the drive mounted?")
                folder_missing = True
            time.sleep(30)
            continue
        folder_missing = False

        now = time.time()
        for path in files:
            try:
                st = os.stat(path)
            except FileNotFoundError:
                continue
            sig = (st.st_size, st.st_mtime)
            if path not in seen or seen[path][:2] != sig:
                seen[path] = (*sig, now)
                continue
            # only grab it once its stopped changing for a bit (still downloading otherwise)
            if now - seen[path][2] >= cfg["library"]["settle_seconds"] and st.st_size > 0:
                sort_one_safely(path, cfg)
                seen.pop(path, None)

        for path in list(seen):
            if path not in files:
                seen.pop(path)

        if not files:
            if tagger.unload_if_idle(cfg["tagger"]["unload_after_minutes"]):
                log.info("unloaded the tagger to save ram")
            sync_catalog_if_due(cfg)
        time.sleep(cfg["library"]["check_every"])

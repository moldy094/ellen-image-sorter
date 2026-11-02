# settings for ellen image sorter
# everything lives in ~/.config/ellen-sorter/config.toml
# if a setting is missing from the file we just use the default from here

import os
import copy
import tomllib

import tomli_w

CONFIG_DIR = os.path.expanduser("~/.config/ellen-sorter")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")
DATA_DIR = os.path.expanduser("~/.local/share/ellen-sorter")
STATE_DIR = os.path.expanduser("~/.local/state/ellen-sorter")
LOG_FILE = os.path.join(STATE_DIR, "ellen-sorter.log")
ACTIVITY_FILE = os.path.join(STATE_DIR, "activity.jsonl")
CATALOG_DB = os.path.join(DATA_DIR, "catalog.sqlite")
LIBRARY_DB = os.path.join(DATA_DIR, "library.sqlite")

DEFAULTS = {
    "library": {
        # the folder you drop stuff into. sorted stuff goes into folders inside it
        "root": os.path.expanduser("~/Desktop/imgs/ellen sharkhive"),
        # danbooru tag for the character, used for the catalog
        "character_tag": "ellen_joe",
        # folders and files in the root we never touch
        "ignore": ["ellen 1", "_needs_review", "_sort_manifest.csv"],
        # how long a file has to stop changing before we grab it (seconds)
        "settle_seconds": 5,
        # how often we look at the folder (seconds)
        "check_every": 3,
    },
    "sorting": {
        # off = no goonery folder, lewd = questionable + explicit,
        # suggestive = also bikini/cleavage type stuff
        "goonery": "lewd",
        "goonery_folder": "goonery",
        # keep kink, sex acts and explicit stuff out of goonery (they go to _needs_review)
        "goonery_filter": True,
        "separate_ai": True,
        "ai_folder": "ai",
        # try to grab the biggest version of the image from pixiv/twitter/danbooru
        "upgrade_quality": True,
        # trash = send the worse copy to the trash, keep = keep both
        "duplicates": "trash",
    },
    "sources": {
        "danbooru_catalog": True,
        "pixiv": True,
        # get one at https://saucenao.com/user.php?page=search-api
        "saucenao_key": "",
        # reads signatures off the image, needs easyocr installed (its big)
        "ocr": True,
        # how often to pull new posts into the catalog (hours)
        "catalog_sync_hours": 12,
    },
    "tagger": {
        "model": "SmilingWolf/wd-eva02-large-tagger-v3",
        # unload the model after this many idle minutes so it doesnt sit in ram
        "unload_after_minutes": 10,
    },
    "notify": {
        "desktop": True,
        # also ping when stuff gets sorted fine, not just when something breaks
        "on_success": False,
        # discord webhook or ntfy topic url, leave blank for none
        "webhook_url": "",
    },
}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
    return cfg


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(cfg, f)


def make_dirs():
    for d in (CONFIG_DIR, DATA_DIR, STATE_DIR):
        os.makedirs(d, exist_ok=True)

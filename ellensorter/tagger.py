# tags pictures with the wd tagger (same tags danbooru uses) and turns the tags
# into a pose folder and a rating. if the picture is already on danbooru we just
# use danbooru's tags instead because people tagged those by hand

import csv
import time
import logging

import numpy as np
from PIL import Image

_model = None
_tags = None
_last_used = 0


def load(model_name):
    global _model, _tags
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        # use the copy we already downloaded if there is one, no need to ask the internet
        model_path = hf_hub_download(model_name, "model.onnx", local_files_only=True)
        tags_path = hf_hub_download(model_name, "selected_tags.csv", local_files_only=True)
    except Exception:
        model_path = hf_hub_download(model_name, "model.onnx")
        tags_path = hf_hub_download(model_name, "selected_tags.csv")
    with open(tags_path) as f:
        _tags = list(csv.DictReader(f))
    _model = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


def unload_if_idle(minutes):
    # the big model eats over a gig of ram, no point keeping it loaded all day
    global _model
    if _model is not None and time.time() - _last_used > minutes * 60:
        _model = None
        return True
    return False


def tag(im, model_name):
    # returns (set of tags, rating) where rating is general/sensitive/questionable/explicit
    global _last_used
    if _model is None:
        load(model_name)
    _last_used = time.time()
    inp = _model.get_inputs()[0]
    size = inp.shape[1]
    # the model wants a white padded square, BGR, 0-255 floats
    w, h = im.size
    side = max(w, h)
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(im, ((side - w) // 2, (side - h) // 2))
    square = square.resize((size, size), Image.BICUBIC)
    arr = np.asarray(square, dtype=np.float32)[:, :, ::-1]
    probs = _model.run(None, {inp.name: arr[None]})[0][0]
    tags = set()
    ratings = {}
    for t, p in zip(_tags, probs):
        if t["category"] == "9":
            ratings[t["name"]] = float(p)
        elif p > 0.35:
            tags.add(t["name"])
    rating = max(ratings, key=ratings.get)
    return tags, rating


# ---------- poses ----------
# checked in this order, first one that matches wins

OTHERS = {"multiple_girls", "2girls", "3girls", "4girls", "5girls", "6+girls", "1boy", "2boys", "3boys",
          "multiple_boys", "1other", "multiple_others", "yuri", "hetero"}
LYING = {"lying", "on_back", "on_stomach", "on_side", "all_fours", "on_bed"}
SITTING = {"sitting", "squatting", "kneeling", "seiza", "wariza", "indian_style", "crossed_legs",
           "knees_up", "hugging_own_legs", "butterfly_sitting", "yokozuwari"}
ACTION = {"fighting_stance", "jumping", "running", "midair", "motion_lines", "motion_blur", "attack",
          "battle", "speed_lines", "dynamic_pose", "holding_weapon", "holding_polearm", "holding_scythe",
          "scythe", "polearm", "weapon_over_shoulder", "fighting", "incoming_attack"}
MISC = {"comic", "4koma", "multiple_views", "reference_sheet", "character_sheet", "meme", "chibi",
        "sticker", "pixel_art", "text_focus", "manga"}


def pick_pose(tags):
    if tags & MISC:
        return "misc"
    if tags & OTHERS and "solo" not in tags:
        return "with others"
    if tags & LYING:
        return "lying down"
    if tags & SITTING:
        return "sitting"
    if tags & ACTION:
        return "action"
    if "from_behind" in tags:
        return "from behind"
    if "full_body" in tags:
        return "full body"
    return "portraits"


# danbooru uses single letters for ratings
DANBOORU_RATINGS = {"g": "general", "s": "sensitive", "q": "questionable", "e": "explicit"}


def is_goonery(rating, mode):
    if mode == "off":
        return False
    if mode == "suggestive":
        return rating in ("sensitive", "questionable", "explicit")
    return rating in ("questionable", "explicit")

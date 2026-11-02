# popups + optional discord/ntfy pings
# errors always go out (if you turned notifications on), the "sorted fine" ones
# only if you ask for them in the settings

import subprocess
import time

import requests

APP_NAME = "ellen image sorter"
_last_sent = {}


def send(cfg, title, message, error=False):
    n = cfg["notify"]
    # dont spam the same message over and over, once every 10 minutes is plenty
    key = (title, message)
    if time.time() - _last_sent.get(key, 0) < 600:
        return
    _last_sent[key] = time.time()

    if n["desktop"]:
        try:
            subprocess.run(["notify-send", "--app-name", APP_NAME,
                            "--urgency", "critical" if error else "normal",
                            "--icon", "dialog-error" if error else "image-x-generic",
                            title, message], timeout=10)
        except Exception:
            pass  # no notify-send, nothing we can do

    url = n.get("webhook_url", "").strip()
    if url:
        text = f"{'⚠️ ' if error else ''}{title}\n{message}"
        try:
            if "discord.com/api/webhooks" in url:
                requests.post(url, json={"content": text[:1900], "username": APP_NAME}, timeout=15)
            else:
                # ntfy and most other things just take the text as the body
                requests.post(url, data=text.encode(), headers={"Title": title}, timeout=15)
        except Exception:
            pass


def problem(cfg, message):
    send(cfg, "ellen image sorter had a problem", message, error=True)


def sorted_ok(cfg, message):
    if cfg["notify"]["on_success"]:
        send(cfg, "ellen image sorter", message)

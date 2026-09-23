"""Tiny Telegram Bot API helper."""
import json

import requests

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN


def call(method, files=None, timeout=60, **params):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    r = requests.post(url, data=params, files=files, timeout=timeout)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data["result"]


def send(text):
    for i in range(0, len(text), 4000):
        call("sendMessage", chat_id=TELEGRAM_CHAT_ID, text=text[i:i + 4000],
             disable_web_page_preview="true")


def action(kind="typing"):
    try:
        call("sendChatAction", chat_id=TELEGRAM_CHAT_ID, action=kind)
    except Exception:
        pass


def send_video(path, caption=""):
    with open(path, "rb") as f:
        msg = call("sendVideo", files={"video": f}, timeout=300, chat_id=TELEGRAM_CHAT_ID,
                   caption=caption[:1000], supports_streaming="true")
    media = msg.get("video") or msg.get("document")
    return media["file_id"]


def get_updates(offset):
    return call("getUpdates", offset=offset, timeout=0,
                allowed_updates=json.dumps(["message"]))


def download(file_id, dest):
    info = call("getFile", file_id=file_id)
    url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{info['file_path']}"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return dest

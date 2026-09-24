"""Remembers where the daily conversation is. Saved to state.json in the repo."""
import json
import os
from datetime import datetime

from config import STATE_FILE, TIMEZONE

DEFAULT = {
    "offset": 0,            # last Telegram update handled
    "stage": "idle",        # idle | choosing | awaiting_voice | rendering | awaiting_approval
    "candidates": [],       # today's suggested stories
    "choose_deadline": None,
    "topic": None,          # the story/topic being made
    "draft": None,          # script, caption, hashtags...
    "voice_file_id": None,  # your recording (stored on Telegram)
    "user_image_id": None,  # optional image you sent for the title card
    "video_file_id": None,  # preview video stored on Telegram
    "queue": [],            # approved reels waiting for their posting time
    "last_gender": "female",   # AI voice alternates male/female
    "pending_offer": False, # next story offer waiting until the current reel is done
    "history": [],          # titles already posted (avoids repeats)
}


def load():
    data = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
    return {**DEFAULT, **data}


def save(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def now():
    return datetime.now(TIMEZONE)

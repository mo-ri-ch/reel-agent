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
    "autopilot": True,         # finish reels on its own when you don't reply
    "script_deadline": None,
    "preview_deadline": None,
    "last_gender": "female",   # AI voice alternates male/female
    "pending_offer": False,
    "offer_log": {"date": None, "done": []},  # which story times were already sent today
    "pending_topic": None,
    "held": [],
    "post_log": [],            # [{at, extra}] every reel actually posted (for the 6-a-day guarantee)
    "paused": None,            # a regular reel paused while you make an extra one
    "spare": [],               # the other stories from the list, used if a story can't be verified
    "tried": [],               # stories already tried (not picked again)                # reels parked for your review (quality check flagged them)
    "next_video_id": None,     # a clip you sent before the script was ready     # a topic waiting for your "yes" button
    "undo_stack": [],          # last few steps, for the Undo button
    "posted_ids": [],          # reels already live (can't be undone) # next story offer waiting until the current reel is done
    "history": [],
    "posted_log": [],          # [{title, at}] reels scheduled/posted, for the 14-day repeat check          # titles already posted (avoids repeats)
}


BACKUP_FILE = STATE_FILE.replace(".json", ".backup.json")
CONTROL_DIR = os.path.join(os.path.dirname(os.path.abspath(STATE_FILE)), "control")
RECOVERED = None  # set when the memory file was broken and the backup was used


def load():
    """The agent's memory. If state.json is ever broken (e.g. a bad merge), the backup copy is used instead."""
    global RECOVERED
    data = {}
    for path in (STATE_FILE, BACKUP_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            if path == BACKUP_FILE:
                RECOVERED = "state.json was broken, so I restored my memory from the backup copy."
            break
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"Couldn't read {path}: {e}")
    s = {**DEFAULT, **data}
    apply_control(s)
    return s


def apply_control(s):
    """Changes Claude asks for without touching state.json (so no merge can break it): control/*.json files with
    {"set": {key: value}, "unset": [keys]}. Applied once, then deleted."""
    if not os.path.isdir(CONTROL_DIR):
        return
    for name in sorted(os.listdir(CONTROL_DIR)):
        path = os.path.join(CONTROL_DIR, name)
        if not name.endswith(".json"):
            continue
        try:
            with open(path) as f:
                c = json.load(f)
            s.update(c.get("set") or {})
            for k in c.get("unset") or []:
                s.pop(k, None)
            print(f"Applied control file {name}")
        except Exception as e:
            print(f"Control file {name} skipped: {e}")
        os.remove(path)


def save(state):
    for path in (STATE_FILE, BACKUP_FILE):
        with open(path, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def now():
    return datetime.now(TIMEZONE)

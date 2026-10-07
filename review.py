"""Saves an editor's review pack for every finished reel: a contact sheet of frames (the first 3 seconds in detail,
then one frame every 2 seconds) and technical measurements. Stored in review/ (newest 16 kept) so Claude can study
the real output like a video editor."""
import glob
import json
import os
import re
import subprocess
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review")
KEEP = 16


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=300)


def _duration(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout.strip()
    return float(out or 0)


def _frame(path, t, dst, width=200):
    _run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", dst])
    return os.path.exists(dst)


def measure(path):
    """Timing and sound measurements of the finished reel."""
    m = {"duration": round(_duration(path), 2)}
    # when does sound start (first moment above -35 dB)?
    sil = _run(["ffmpeg", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.05", "-f", "null", "-"]).stderr
    starts = re.findall(r"silence_start: ([\d.]+)", sil)
    ends = re.findall(r"silence_end: ([\d.]+)", sil)
    m["sound_starts_at"] = round(float(ends[0]), 2) if starts and float(starts[0]) < 0.05 and ends else 0.0
    # loudness (Instagram plays around -14 LUFS)
    lo = _run(["ffmpeg", "-i", path, "-af", "ebur128", "-f", "null", "-"]).stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", lo)
    m["loudness_lufs"] = float(i[-1]) if i else None
    # cuts (scene changes) → rhythm
    sc = _run(["ffmpeg", "-i", path, "-vf", "select='gt(scene,0.32)',showinfo", "-f", "null", "-"]).stderr
    cuts = [round(float(x), 2) for x in re.findall(r"pts_time:([\d.]+)", sc)]
    m["cuts"] = cuts
    m["first_cut_at"] = cuts[0] if cuts else None
    gaps = [b - a for a, b in zip([0.0] + cuts, cuts + [m["duration"]])]
    m["avg_shot_seconds"] = round(sum(gaps) / len(gaps), 2) if gaps else None
    m["longest_shot_seconds"] = round(max(gaps), 2) if gaps else None
    return m


def save(path, draft, topic, extra=None):
    """Writes review/<time>.jpg (contact sheet) and review/<time>.json. Never raises."""
    try:
        os.makedirs(FOLDER, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        dur = _duration(path)
        times = [0.0, 0.3, 0.7, 1.2, 1.8, 2.5] + [t for t in range(4, int(dur), 2)]
        tmp = os.path.join(FOLDER, "_f")
        os.makedirs(tmp, exist_ok=True)
        thumbs = []
        for k, t in enumerate(times[:24]):
            f = os.path.join(tmp, f"{k:02d}.jpg")
            if _frame(path, t, f):
                thumbs.append((t, Image.open(f).convert("RGB")))
        if thumbs:
            w, h = thumbs[0][1].size
            cols = 6
            rows = (len(thumbs) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * (w + 6), rows * (h + 26)), (20, 20, 24))
            d = ImageDraw.Draw(sheet)
            try:
                font = ImageFont.truetype(os.path.join(os.path.dirname(__file__), "fonts", "Poppins-SemiBold.ttf"), 15)
            except Exception:
                font = ImageFont.load_default()
            for k, (t, im) in enumerate(thumbs):
                x, y = (k % cols) * (w + 6), (k // cols) * (h + 26)
                sheet.paste(im, (x, y + 22))
                d.text((x + 4, y + 3), f"{t:.1f}s", fill=(235, 235, 235), font=font)
            sheet.save(os.path.join(FOLDER, f"{stamp}.jpg"), quality=72)
        for f in glob.glob(os.path.join(tmp, "*.jpg")):
            os.remove(f)
        os.rmdir(tmp)
        info = {"made": stamp, "title": (topic or {}).get("title", ""), "hook_text": draft.get("hook_text"),
                "hook_before": draft.get("hook_before"), "script": draft.get("script"),
                "words": len((draft.get("script") or "").split()),
                "beats": [{"line": b.get("line"), "visual": b.get("visual")} for b in draft.get("beats") or []],
                "voice": draft.get("voice_used"), "visuals": draft.get("visual_summary"),
                **measure(path), **(extra or {})}
        if info.get("duration"):
            info["words_per_minute"] = round(info["words"] / info["duration"] * 60)
        with open(os.path.join(FOLDER, f"{stamp}.json"), "w") as f:
            json.dump(info, f, indent=1, ensure_ascii=False)
        packs = sorted(glob.glob(os.path.join(FOLDER, "*.json")))
        for old in packs[:-KEEP]:
            for ext in (".json", ".jpg"):
                p = old[:-5] + ext
                if os.path.exists(p):
                    os.remove(p)
        print(f"Review pack saved: review/{stamp}")
    except Exception as e:
        print(f"Review pack skipped: {e}")

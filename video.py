"""Turns a voice-over + script into a 1080x1920 reel.

Style: a bold hook screen, a new shot every ~2.5 seconds that matches what's being said
(stock clips checked by Gemini, AI images, big-number cards), modern word-by-word captions,
soft background music and a progress bar.
"""
import glob
import io
import math
import os
import random
import re
import shutil
import subprocess

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import news
from config import FONT_PATH, HANDLE, PEXELS_API_KEY, WORK_DIR

W, H, FPS = 1080, 1920, 30
SHOT_SECONDS = 2.6            # a new shot about this often
ACCENT = (123, 154, 248)      # Gradient brand blue (#7B9AF8)
ACCENT_ASS = "&H00F89A7B&"    # same blue in ASS (BGR)
ACCENT_HEX = "0x7B9AF8"
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Poppins-ExtraBold.ttf")
FONT_SEMI = os.path.join(FONT_DIR, "Poppins-SemiBold.ttf")
MUSIC_DIR = "music"
MUSIC_VOLUME = float(os.environ.get("MUSIC_VOLUME") or 0.15)
UA = news.UA


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-1200:]}")
    return r.stdout


def duration(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


# ---------------------------------------------------------------- audio
def clean_audio(src, dst, trim_start=True):
    trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15"
    start = f"{trim}," if trim_start else ""
    af = (f"highpass=f=80,afftdn=nf=-25,{start}areverse,{trim},areverse,"
          "loudnorm=I=-14:TP=-1.5:LRA=11,apad=pad_dur=0.6")
    sh(["ffmpeg", "-y", "-i", src, "-af", af, "-ar", "48000", "-ac", "2", dst])


def pick_music():
    tracks = [f for ext in ("mp3", "m4a", "wav", "ogg", "aac") for f in glob.glob(os.path.join(MUSIC_DIR, f"*.{ext}"))]
    return random.choice(tracks) if tracks else None


def mix_music(voice_wav, music, total, dst):
    """Soft background music that ducks under the voice and fades out at the end."""
    fade_start = max(0.0, total - 1.5)
    graph = (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={MUSIC_VOLUME}[m];"
             "[0:a]asplit=2[v][key];"
             "[m][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=500[duck];"
             "[v][duck]amix=inputs=2:duration=first:normalize=0,"
             f"afade=t=out:st={fade_start:.2f}:d=1.5[out]")
    sh(["ffmpeg", "-y", "-i", voice_wav, "-stream_loop", "-1", "-i", music,
        "-filter_complex", graph, "-map", "[out]", "-ar", "48000", "-ac", "2", dst])


def transcribe(wav, hint=""):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER_MODEL") or "base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav, language="en", word_timestamps=True, beam_size=5,
                                   initial_prompt=hint[:800] or None)
    words = []
    for seg in segments:
        for w in seg.words or []:
            if re.search(r"\w", w.word):  # skip stray punctuation-only "words"
                words.append({"text": w.word.strip(), "start": w.start, "end": w.end})
    return words


def align_to_script(words, script):
    """Uses the script's exact spelling for captions, with the timings Whisper heard.
    (Whisper sometimes mishears names like "Rafale" or "@gradientailabs".) If the speaker
    went off-script (your own voice), Whisper's words are kept."""
    import difflib
    tokens = script.split()
    if not words or not tokens:
        return words
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    heard, wanted = [norm(w["text"]) for w in words], [norm(t) for t in tokens]
    sm = difflib.SequenceMatcher(None, heard, wanted, autojunk=False)
    if sm.ratio() < 0.6:
        return words
    out = [None] * len(tokens)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[j1 + k] = {"text": tokens[j1 + k], "start": words[i1 + k]["start"], "end": words[i1 + k]["end"]}
        elif j2 > j1:  # script words Whisper heard differently: share out the time it heard
            if i2 > i1:
                t0, t1 = words[i1]["start"], words[i2 - 1]["end"]
            else:
                t0 = words[i1 - 1]["end"] if i1 > 0 else 0.0
                t1 = words[i1]["start"] if i1 < len(words) else t0 + 0.3 * (j2 - j1)
            step = max(0.05, (t1 - t0) / (j2 - j1))
            for k in range(j2 - j1):
                out[j1 + k] = {"text": tokens[j1 + k], "start": t0 + k * step, "end": t0 + (k + 1) * step}
    return [w for w in out if w and re.search(r"\w", w["text"])]


# ---------------------------------------------------------------- captions
CAPTION_STYLE = (os.environ.get("CAPTION_STYLE") or "clean").lower()   # "clean" (default) or "bold"


def chunk_words(words, max_words=2, max_chars=13, sentence_breaks=".!?,;:"):
    chunks, cur = [], []
    for w in words:
        joined = " ".join(x["text"] for x in cur + [w])
        if cur and (len(cur) >= max_words or len(joined) > max_chars or w["start"] - cur[-1]["end"] > 0.5):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["text"] and w["text"][-1] in sentence_breaks:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_text(t, upper=True):
    t = re.sub(r"[{}\\]", "", t)
    t = re.sub(r"^[.,;:!?…\-–—]+", "", t)
    if upper:
        t = re.sub(r"[.,;:]+$", "", t)  # trailing commas/full stops look messy in big captions
        return t.upper()
    return t


def font_name():
    return "Poppins" if os.path.exists(FONT_BOLD) else "DejaVu Sans"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{caption}
Style: Handle,{font},36,&H40FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,3,0,8,60,60,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


def write_ass(words, total, path, hook_until=0.0):
    font = font_name()
    clean = CAPTION_STYLE != "bold"
    if clean:
        # Clean & minimal: sentence case, SemiBold, soft shadow, a short phrase at a time, active word in yellow
        caption = (f"Style: Caption,{font},82,&H00FFFFFF,&H00FFFFFF,&H60000000,&H70000000,0,0,0,0,100,100,0.5,0,1,"
                   f"3,2,2,100,100,600,1")
        chunks = chunk_words(words, max_words=5, max_chars=26, sentence_breaks=".!?")
    else:
        caption = (f"Style: Caption,{font},118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,"
                   f"9,4,2,70,70,640,1")
        chunks = chunk_words(words)
    out = [ASS_HEADER.format(W=W, H=H, caption=caption, font=font)]
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else total
        chunk_end = nxt if nxt - ch[-1]["end"] < 0.6 else ch[-1]["end"] + 0.35
        for wi, w in enumerate(ch):
            start = w["start"]
            end = ch[wi + 1]["start"] if wi + 1 < len(ch) else chunk_end
            end = max(end, start + 0.05)
            if end <= hook_until:
                continue  # the hook screen has its own big text
            start = max(start, hook_until)
            if clean:
                parts = [f"{{\\c{ACCENT_ASS}}}{ass_text(x['text'], False)}{{\\c&HFFFFFF&}}" if k == wi
                         else ass_text(x["text"], False) for k, x in enumerate(ch)]
                soft = "{\\blur4}" + ("{\\fad(90,0)}" if wi == 0 else "")
                out.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{soft}{' '.join(parts)}")
                continue
            parts = []
            for k, x in enumerate(ch):
                t = ass_text(x["text"])
                parts.append(f"{{\\c{ACCENT_ASS}\\fscx108\\fscy108}}{t}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
                             if k == wi else t)
            chars = sum(len(ass_text(x["text"])) for x in ch) + len(ch) - 1
            fit = min(100, int(100 * 13 / max(chars, 1))) if chars > 13 else 100  # keep long words on screen
            size = f"{{\\fscx{fit}\\fscy{fit}}}" if fit < 100 else ""
            pop = f"{{\\fscx{int(fit * .7)}\\fscy{int(fit * .7)}\\t(0,110,\\fscx{fit}\\fscy{fit})}}" if wi == 0 else size
            body = ' '.join(parts).replace("\\fscx100\\fscy100", f"\\fscx{fit}\\fscy{fit}") \
                .replace("\\fscx108\\fscy108", f"\\fscx{int(fit * 1.08)}\\fscy{int(fit * 1.08)}")
            out.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{pop}{body}")
    if HANDLE:
        handle = re.sub(r"[{}\\]", "", HANDLE.lstrip("@"))
        out.append(f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Handle,,0,0,0,,@{handle}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


# ---------------------------------------------------------------- pictures
def font(size, semi=False):
    for path in ((FONT_SEMI if semi else FONT_BOLD), FONT_PATH):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def gradient(top=(10, 8, 30), bottom=(55, 25, 95)):
    col = Image.new("RGB", (1, H))
    for y in range(H):
        a = y / (H - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * a) for i in range(3)))
    return col.resize((W, H))


def fetch_image(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img if img.width >= 300 else None
    except Exception:
        return None


def cover(img, w=W, h=H):
    s = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def wrap(draw, text, fnt, maxw):
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if draw.textlength(test, font=fnt) <= maxw or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def darken(img, top=0.35, bottom=0.75):
    """Vertical dark gradient so white text stays readable on any picture."""
    shade = Image.new("L", (1, H))
    for y in range(H):
        shade.putpixel((0, y), int(255 * (top + (bottom - top) * (y / (H - 1)))))
    shade = shade.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H)), img, shade)


def full_frame(img, center=0.42):
    """Any picture → full-screen 9:16 frame. Tall and square pictures fill the screen;
    wide photos (like news images) sit across the middle on a blurred copy of themselves."""
    if img.width / img.height <= 1.3:
        return cover(img)
    bg = cover(img).filter(ImageFilter.GaussianBlur(45))
    bg = Image.blend(bg, Image.new("RGB", (W, H)), 0.35)
    fg_h = int(H * 0.5)
    fg = cover(img, W, fg_h) if img.width / img.height < W / fg_h else img.resize(
        (W, int(img.height * W / img.width)), Image.LANCZOS)
    bg.paste(fg, (0, int(H * center) - fg.height // 2))
    return bg


def text_block(draw, text, fnt, y, fill="white", box=None, line_gap=1.12, maxw=W - 150):
    lines = wrap(draw, text, fnt, maxw)
    size = fnt.size
    for line in lines:
        tw = draw.textlength(line, font=fnt)
        if box:
            pad = int(size * 0.22)
            draw.rounded_rectangle([W / 2 - tw / 2 - pad, y - pad * 0.4, W / 2 + tw / 2 + pad, y + size * 1.02 + pad * 0.4],
                                   radius=int(size * 0.18), fill=box)
        draw.text((W / 2, y), line, font=fnt, fill=fill, anchor="ma",
                  stroke_width=0 if box else max(2, size // 22), stroke_fill="black")
        y += int(size * line_gap + (size * 0.15 if box else 0))
    return y


def draw_label(d, label, y=334):
    """A calm news label: a small brand-blue dot, then e.g. "The Verge · 25 Sep 2026"."""
    f = font(40, semi=True)
    tw = d.textlength(label, font=f)
    x = W / 2 - (tw + 40) / 2
    d.ellipse([x, y - 13, x + 26, y + 13], fill=ACCENT)
    d.text((x + 40, y), label, font=f, fill="white", anchor="lm", stroke_width=2, stroke_fill=(0, 0, 0))


def news_label(topic):
    """'The Verge · 25 Sep 2026' for news, 'Explainer' for your own topics."""
    from datetime import datetime, timezone
    from config import TIMEZONE
    if not topic or topic.get("custom"):
        return "Explainer"
    parts = [p.strip() for p in re.split(r"\s[|\-–—:]\s|\s\|\s?", str(topic.get("source") or "")) if p.strip()]
    generic = re.compile(r"(?i)^(ai|news|blog|the blog|feed|rss|ai news.*|artificial intelligence.*|latest.*|technology|tech)$")
    names = [p for p in parts if not generic.match(p) and not re.search(r"(?i)artificial intelligence|\bai news\b", p)]
    names = [n for n in names if n.lower() != "google news"]
    source = re.sub(r"(?i)\s+(blog|news|newsroom)$", "", names[-1]) if names else ""
    try:
        when = datetime.fromisoformat(topic["published"]).astimezone(TIMEZONE)
    except Exception:
        when = datetime.now(timezone.utc).astimezone(TIMEZONE)
    date = f"{when.day} {when.strftime('%b %Y')}"
    return f"{source[:28]} · {date}" if source and "google news" not in source.lower() else date


def make_hook_card(path, hook, label, image=None):
    bg = full_frame(image, center=0.68) if image else gradient()
    bg = darken(bg, 0.25, 0.6)
    d = ImageDraw.Draw(bg)
    lf = font(38, semi=True)
    draw_label(d, label)
    size = 118
    while size > 70 and len(wrap(d, hook.upper(), font(size), W - 150)) > 3:
        size -= 8
    text_block(d, hook.upper(), font(size), 420, fill="black", box=(255, 255, 255))
    bg.save(path)


def make_hook_overlay(path, hook, label):
    """The hook text on a transparent layer, to put on top of your own opening video."""
    shade = Image.new("L", (1, H))
    for y in range(H):
        shade.putpixel((0, y), int(170 * max(0.0, 1 - y / (H * 0.55))))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    img.putalpha(shade.resize((W, H)))
    d = ImageDraw.Draw(img)
    lf = font(38, semi=True)
    draw_label(d, label)
    size = 118
    while size > 70 and len(wrap(d, hook.upper(), font(size), W - 150)) > 3:
        size -= 8
    text_block(d, hook.upper(), font(size), 420, fill="black", box=(255, 255, 255))
    img.save(path)


def is_landscape(path):
    out = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation",
              "-of", "csv=p=0", path]).strip().splitlines()[0].split(",")
    w, h = int(out[0]), int(out[1])
    return w > h


def opening_video_shot(src, length, overlay_png, text_seconds, out):
    """Your own clip as the opening shot, with the hook text on top for the first seconds."""
    if is_landscape(src):  # wide clip: sharp video in the lower half, blurred copy behind
        fit = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"boxblur=30:4,eq=brightness=-0.12[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)*0.62[v]")
    else:
        fit = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[v]"
    graph = f"{fit};[v][1:v]overlay=0:0:enable='lt(t,{text_seconds:.2f})',fps={FPS}[out]"
    sh(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src, "-loop", "1", "-i", overlay_png, "-filter_complex", graph,
        "-map", "[out]", "-t", f"{length:.3f}", *encode_args(), out])


def make_stat_card(path, big, small, image=None, draw_number=True):
    bg = darken(full_frame(image).filter(ImageFilter.GaussianBlur(18)), 0.55, 0.85) if image else gradient()
    d = ImageDraw.Draw(bg)
    size = 300 if len(big) <= 4 else 240 if len(big) <= 6 else 180
    if draw_number:
        d.text((W / 2, 560), big, font=font(size), fill=ACCENT, anchor="ma", stroke_width=6, stroke_fill="black")
    text_block(d, small.upper(), font(68, semi=True), 560 + int(size * 1.15))
    bg.save(path)
    return size


# ---------------------------------------------------------------- animations
def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def save_frames(folder, frames):
    os.makedirs(folder, exist_ok=True)
    for k, fr in enumerate(frames):
        fr.save(os.path.join(folder, f"{k:03d}.png"))
    return {"dir": folder, "n": len(frames)}


def stat_animation(tmp, i, big, small):
    """The number counts up (0 → 600M) and settles. Returns shots, or None if it isn't a countable number."""
    m = re.match(r"^([^\d]*)(\d[\d,]*\.?\d*)(.*)$", big.strip())
    if not m:
        return None
    prefix, num, suffix = m.groups()
    value = float(num.replace(",", ""))
    decimals = len(num.split(".")[1]) if "." in num else 0
    bg = os.path.join(tmp, f"stat_bg_{i}.png")
    size = make_stat_card(bg, big, small, draw_number=False)
    full = os.path.join(tmp, f"stat_{i}.png")
    make_stat_card(full, big, small)
    frames, n = [], 22
    for k in range(n):
        v = value * ease_out((k + 1) / n)
        txt = f"{prefix}{v:,.{decimals}f}{suffix}" if "," in num else f"{prefix}{v:.{decimals}f}{suffix}"
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((W / 2, 560), txt if k < n - 1 else big, font=font(size), fill=ACCENT,
                                   anchor="ma", stroke_width=6, stroke_fill="black")
        frames.append(layer)
    anim = save_frames(os.path.join(tmp, f"stat_frames_{i}"), frames)
    return [("layered", {"bg": bg, **anim}), ("image", full)]


def hook_animation(tmp, hook, label, image=None):
    """The opening headline pops in line by line."""
    bg_img = darken(full_frame(image, center=0.68) if image else gradient(), 0.25, 0.6)
    bg = os.path.join(tmp, "hook_bg.png")
    bg_img.save(bg)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    size = 118
    while size > 70 and len(wrap(probe, hook.upper(), font(size), W - 150)) > 3:
        size -= 8
    fnt, lines = font(size), wrap(probe, hook.upper(), font(size), W - 150)
    lf = font(38, semi=True)

    def draw_state(t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        draw_label(d, label)
        y = 420
        for k, line in enumerate(lines):
            p = ease_out((t - 2 - k * 4) / 5)  # each line starts 4 frames after the previous
            step = int(size * 1.12 + size * 0.15)
            if p > 0:
                tile = Image.new("RGBA", (W, step + 40), (0, 0, 0, 0))
                td = ImageDraw.Draw(tile)
                lw = td.textlength(line, font=fnt)
                pad = int(size * 0.22)
                td.rounded_rectangle([W / 2 - lw / 2 - pad, 20 - pad * 0.4, W / 2 + lw / 2 + pad, 20 + size * 1.02 + pad * 0.4],
                                     radius=int(size * 0.18), fill=(255, 255, 255))
                td.text((W / 2, 20), line, font=fnt, fill="black", anchor="ma")
                sc = 0.82 + 0.18 * p
                tile = tile.resize((max(1, int(tile.width * sc)), max(1, int(tile.height * sc))), Image.LANCZOS)
                alpha = tile.getchannel("A").point(lambda a: int(a * p))
                tile.putalpha(alpha)
                layer.alpha_composite(tile, (int((W - tile.width) / 2), int(y - 20 * sc)))
            y += step
        return layer
    frames = [draw_state(t) for t in range(2 + 4 * len(lines) + 6)]
    anim = save_frames(os.path.join(tmp, "hook_frames"), frames)
    return {"bg": bg, **anim}


# ---------------------------------------------------------------- stock footage
def pexels_search(query, n=4):
    if not PEXELS_API_KEY:
        return []
    try:
        r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                         headers={"Authorization": PEXELS_API_KEY, **UA},
                         params={"query": query, "orientation": "portrait", "per_page": n + 4})
        if r.status_code != 200:
            print(f"Pexels search '{query}' failed: {r.status_code} {r.text[:120]}")
            return []
        videos = r.json().get("videos", [])
    except Exception as e:
        print(f"Pexels search '{query}' failed: {e}")
        return []
    found = []
    for v in videos:
        files = [f for f in v.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 720]
        if files and v.get("image"):
            best = min(files, key=lambda f: abs(f["height"] - 1920) + (5000 if f["height"] > 2200 else 0))
            found.append({"id": v["id"], "thumb": v["image"], "url": best["link"], "duration": v.get("duration", 10)})
    print(f"Pexels '{query}': {len(found)} usable clips")
    return found[:n]


def thumb_bytes(url):
    try:
        r = requests.get(url, timeout=20, headers=UA)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((220, 390))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue()
    except Exception as e:
        print(f"Thumbnail failed: {e}")
        return None


def download(url, path):
    with requests.get(url, stream=True, timeout=120, headers=UA) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for c in r.iter_content(1 << 16):
                f.write(c)
    return path


# ---------------------------------------------------------------- real photos (Wikimedia)
WIKI_UA = {"User-Agent": "GradientAIReelAgent/1.0 (Instagram reels bot; github.com/mo-ri-ch/reel-agent)"}
FREE_LICENSES = ("cc0", "cc by", "cc-by", "public domain", "pd", "cc by-sa", "cc-by-sa", "attribution")
LAST_CREDITS = []


def _clean_html(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()


def _commons_file_info(file_titles):
    """Looks up files on Wikimedia Commons; returns only freely licensed ones."""
    r = requests.get("https://commons.wikimedia.org/w/api.php", timeout=25, headers=WIKI_UA, params={
        "action": "query", "format": "json", "titles": "|".join(file_titles[:10]),
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "iiurlwidth": 1400})
    found = []
    pages = (r.json().get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if not info or not str(info.get("mime", "")).startswith("image/") or "svg" in info.get("mime", ""):
            continue
        meta = info.get("extmetadata") or {}
        lic = _clean_html((meta.get("LicenseShortName") or {}).get("value", ""))
        if not any(k in lic.lower() for k in FREE_LICENSES) or "non-free" in lic.lower() or "fair use" in lic.lower():
            continue
        if (info.get("width") or 0) < 700:
            continue
        artist = _clean_html((meta.get("Artist") or {}).get("value", ""))[:60] or "Wikimedia Commons"
        found.append({"url": info.get("thumburl") or info["url"], "credit": f"{artist} ({lic}), via Wikimedia Commons",
                      "title": page.get("title", "")})
    order = {t: i for i, t in enumerate(file_titles)}
    return sorted(found, key=lambda f: order.get(f["title"], 99))


def wiki_photo(entity):
    """A real, freely licensed photo of a named person, company, place or product. Returns (PIL image, credit)."""
    try:
        # 1) the main picture of the Wikipedia article (usually the best, most recognisable photo)
        r = requests.get("https://en.wikipedia.org/w/api.php", timeout=25, headers=WIKI_UA, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": entity, "gsrlimit": 1,
            "prop": "pageimages", "piprop": "name"})
        pages = list(((r.json().get("query") or {}).get("pages") or {}).values())
        titles = [f"File:{p['pageimage']}" for p in pages if p.get("pageimage")]
        # 2) more photos from Wikimedia Commons
        r = requests.get("https://commons.wikimedia.org/w/api.php", timeout=25, headers=WIKI_UA, params={
            "action": "query", "format": "json", "list": "search", "srsearch": f"{entity} filetype:bitmap",
            "srnamespace": 6, "srlimit": 6})
        titles += [x["title"] for x in (r.json().get("query") or {}).get("search", [])]
        for f in _commons_file_info(list(dict.fromkeys(titles))):
            img = fetch_image_wiki(f["url"])
            if img:
                print(f"Real photo for '{entity}': {f['title']}")
                return img, f["credit"]
    except Exception as e:
        print(f"Wikimedia photo for '{entity}' failed: {e}")
    return None, None


def fetch_image_wiki(url):
    try:
        r = requests.get(url, timeout=30, headers=WIKI_UA)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img if img.width >= 500 else None
    except Exception:
        return None


def add_credit(img, credit):
    """Small photo credit in the corner (required by the free licences)."""
    img = img.copy()
    d = ImageDraw.Draw(img)
    f = font(24, semi=True)
    text = (credit if credit.startswith(("Photo", "Image")) else
            f"Image: {credit}" if "." in credit and " " not in credit else f"Photo: {credit}")[:95]
    tw = d.textlength(text, font=f)
    # inside the "safe area": the slow zoom on images crops the outer edges
    d.rounded_rectangle([W - tw - 124, H - 262, W - 96, H - 220], radius=10, fill=(0, 0, 0))
    d.text((W - 110, H - 241), text, font=f, fill=(230, 230, 230), anchor="rm")
    return img


def make_source_card(path, outlet, headline, domain=""):
    """A clean 'where this comes from' card: publisher logo, name and the headline."""
    bg = gradient((245, 245, 248), (220, 224, 235))
    d = ImageDraw.Draw(bg)
    x0, y0, x1 = 70, 520, W - 70
    card_h = 700
    d.rounded_rectangle([x0 + 8, y0 + 12, x1 + 8, y0 + card_h + 12], radius=36, fill=(190, 194, 205))
    d.rounded_rectangle([x0, y0, x1, y0 + card_h], radius=36, fill=(255, 255, 255))
    logo = brand_logo(outlet, domain) if outlet else None
    x = x0 + 50
    if logo:
        lg = logo.convert("RGBA")
        lg.thumbnail((110, 110), Image.LANCZOS)
        bg.paste(lg, (x, y0 + 50), lg)
        x += 130
    d.text((x, y0 + 105), outlet or domain, font=font(56), fill=(15, 15, 25), anchor="lm")
    d.line([x0 + 50, y0 + 190, x1 - 50, y0 + 190], fill=(225, 225, 232), width=3)
    y = y0 + 230
    for line in wrap(d, headline, font(64, semi=True), x1 - x0 - 100)[:5]:
        d.text((x0 + 50, y), line, font=font(64, semi=True), fill=(20, 20, 30))
        y += 84
    if domain:
        d.text((x0 + 50, y0 + card_h - 70), domain, font=font(36, semi=True), fill=(120, 124, 140))
    tag = font(40, semi=True)
    tw = d.textlength("SOURCE", font=tag)
    d.rounded_rectangle([W / 2 - tw / 2 - 30, 400, W / 2 + tw / 2 + 30, 470], radius=35, fill=ACCENT)
    d.text((W / 2, 435), "SOURCE", font=tag, fill="black", anchor="mm")
    bg.save(path)


# ---------------------------------------------------------------- official & article images
SKIP_IMG = re.compile(r"logo|icon|avatar|sprite|favicon|badge|button|pixel|tracking|placeholder|author|profile|"
                      r"ads?[_/.-]|banner-ad|spinner|loading|emoji|\.svg|\.gif", re.I)


def page_images(url, limit=5):
    """Big images from a web page: its share image first, then large pictures in the page. [(PIL image, domain)]"""
    from urllib.parse import urljoin, urlparse
    import html as html_lib
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        page, final = r.text[:800000], r.url
    except Exception as e:
        print(f"Couldn't open {url[:80]}: {e}")
        return []
    domain = urlparse(final).netloc.replace("www.", "")
    if "news.google." in domain:
        return []
    cands = []
    for pat in (r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]*content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)'):
        cands += re.findall(pat, page, re.I)
    for tag in re.findall(r"<img\b[^>]*>", page, re.I)[:80]:
        srcset = re.search(r'srcset=["\']([^"\']+)', tag, re.I)
        if srcset:
            parts = [p.strip().split(" ")[0] for p in srcset.group(1).split(",") if p.strip()]
            if parts:
                cands.append(parts[-1])  # the largest version
                continue
        src = re.search(r'(?:data-src|src)=["\']([^"\']+)', tag, re.I)
        if src:
            cands.append(src.group(1))
    found, seen = [], set()
    for c in cands:
        c = urljoin(final, html_lib.unescape(c.strip()))
        key = re.sub(r"[?#].*$", "", c)
        if not c.startswith("http") or key in seen or SKIP_IMG.search(key):
            continue
        seen.add(key)
        img = fetch_image(c)
        if img and img.width >= 600 and img.height >= 300 and 0.4 <= img.width / img.height <= 3.0:
            found.append((img, domain))
            if len(found) >= limit:
                break
    print(f"{len(found)} images from {domain}")
    return found


def _name_tokens(name):
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if len(t) > 1]


def wiki_person(name):
    """A free photo from the person's OWN Wikipedia article (the title must match their name)."""
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", timeout=25, headers=WIKI_UA, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": name, "gsrlimit": 3,
            "prop": "pageimages", "piprop": "name"})
        pages = ((r.json().get("query") or {}).get("pages") or {}).values()
        want = _name_tokens(name)
        for p in pages:
            title = _name_tokens(p.get("title", ""))
            if p.get("pageimage") and want and all(t in title for t in want):
                for f in _commons_file_info([f"File:{p['pageimage']}"]):
                    img = fetch_image_wiki(f["url"])
                    if img:
                        return img, f["credit"].split(" (")[0]
    except Exception as e:
        print(f"Wikipedia photo for {name} failed: {e}")
    return None, None


def page_person_image(url, name):
    """A photo on a page whose alt text / file name mentions the person (e.g. a team page or the article)."""
    from urllib.parse import urljoin, urlparse
    import html as html_lib
    last = _name_tokens(name)[-1] if _name_tokens(name) else ""
    if not url or not last:
        return None, None
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        page, final = r.text[:800000], r.url
    except Exception:
        return None, None
    for tag in re.findall(r"<img\b[^>]*>", page, re.I):
        meta = " ".join(re.findall(r'(?:alt|title|src|data-src)=["\']([^"\']+)', tag, re.I)).lower()
        if last not in meta:
            continue
        srcset = re.search(r'srcset=["\']([^"\']+)', tag, re.I)
        src = (srcset.group(1).split(",")[-1].strip().split(" ")[0] if srcset else
               (re.search(r'(?:data-src|src)=["\']([^"\']+)', tag, re.I) or [None, None])[1])
        if not src:
            continue
        img = fetch_image(urljoin(final, html_lib.unescape(src)))
        if img and min(img.size) >= 250:
            return img, urlparse(final).netloc.replace("www.", "")
    return None, None


def person_photo(name, handle="", url="", source_urls=()):
    """The person's real photo, or (None, None). Only from places where it's clearly them."""
    img, credit = wiki_person(name)
    if img:
        return img, credit
    for u in [url, *source_urls]:
        img, credit = page_person_image(u, name)
        if img:
            return img, credit
    if handle:
        try:
            r = requests.get(f"https://unavatar.io/x/{handle}?fallback=false", headers=UA, timeout=20)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                if min(img.size) >= 200:
                    return img, f"x.com/{handle}"
        except Exception as e:
            print(f"X photo for {name} failed: {e}")
    return None, None


def portrait_square(img, size):
    """Square crop that keeps the face: for tall photos, take the top part (faces sit high)."""
    side = min(img.width, img.height)
    x = (img.width - side) // 2
    y = int((img.height - side) * 0.15) if img.height > img.width else 0
    return img.crop((x, y, x + side, y + side)).resize((size, size), Image.LANCZOS)


def make_person_card(path, name, role, img=None, credit="", animate_into=None):
    """animate_into: a folder → also saves the card without text plus frames of the name/role sliding in."""
    """The person's photo with their name and role underneath, like a TV lower third."""
    if img:
        bg = darken(cover(img).filter(ImageFilter.GaussianBlur(40)), 0.55, 0.8)
    else:
        bg = gradient((14, 16, 30), (30, 36, 70))
    d = ImageDraw.Draw(bg)
    size, top = 600, 330
    if img:
        face = portrait_square(img, size)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=60, fill=255)
        d.rounded_rectangle([W / 2 - size / 2 - 8, top - 8, W / 2 + size / 2 + 8, top + size + 8], radius=66,
                            fill=(255, 255, 255))
        bg.paste(face, (int(W / 2 - size / 2), top), mask)
    else:  # no trustworthy photo: initials, never someone else's face
        initials = "".join(t[0] for t in name.split()[:2]).upper()
        d.ellipse([W / 2 - 250, top + 50, W / 2 + 250, top + 550], fill=(123, 154, 248))
        d.text((W / 2, top + 300), initials, font=font(220), fill=(15, 20, 48), anchor="mm")
    y = top + size + 60
    if img and credit:
        bg = add_credit(bg, credit)

    def text_layer(p):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        dy = int(40 * (1 - p))
        ld.text((W / 2, y + dy), name, font=font(74), fill=(255, 255, 255, int(255 * p)), anchor="ma")
        if role:
            rf = font(44, semi=True)
            tw = ld.textlength(role, font=rf)
            q = ease_out((p - 0.3) / 0.7) if p < 1 else 1
            ld.rounded_rectangle([W / 2 - tw / 2 - 28, y + 110 + dy, W / 2 + tw / 2 + 28, y + 180 + dy], radius=35,
                                 fill=(*ACCENT, int(255 * q)))
            ld.text((W / 2, y + 145 + dy), role, font=rf, fill=(15, 15, 20, int(255 * q)), anchor="mm")
        return layer
    full = bg.convert("RGBA")
    full.alpha_composite(text_layer(1.0))
    full.convert("RGB").save(path)
    if animate_into:
        base = path.replace(".png", "_bg.png")
        bg.save(base)
        anim = save_frames(animate_into, [text_layer(ease_out((k + 1) / 14)) for k in range(14)])
        return {"bg": base, **anim}
    return None


def make_logo_card(path, name, domain=""):
    """A big, clean logo card for a company or product when no real image is available."""
    bg = gradient((14, 16, 30), (30, 36, 70))
    d = ImageDraw.Draw(bg)
    logo = brand_logo(name.split()[0], domain) or (brand_logo(name, domain) if " " in name else None)
    y = 640
    if logo:
        tile = 420
        d.rounded_rectangle([W / 2 - tile / 2, y, W / 2 + tile / 2, y + tile], radius=90, fill=(255, 255, 255))
        lg = logo.convert("RGBA")
        lg.thumbnail((tile - 110, tile - 110), Image.LANCZOS)
        bg.paste(lg, (int(W / 2 - lg.width / 2), int(y + tile / 2 - lg.height / 2)), lg)
        y += tile + 60
    text_block(d, name, font(84), y)
    bg.save(path)


# ---------------------------------------------------------------- logos & sound effects
SI = "https://cdn.jsdelivr.net/npm/simple-icons@16"
_SI_COLORS = None


def _si_color(slug):
    global _SI_COLORS
    if _SI_COLORS is None:
        try:
            data = requests.get(f"{SI}/data/simple-icons.json", timeout=30, headers=UA).json()
            items = data if isinstance(data, list) else data.get("icons", [])
            _SI_COLORS = {re.sub(r"[^a-z0-9]", "", i.get("slug") or i.get("title", "").lower()): i.get("hex") for i in items}
        except Exception:
            _SI_COLORS = {}
    return _SI_COLORS.get(slug)


def brand_logo(name, domain=""):
    """Company logo as a picture: Simple Icons first (crisp), then the website's own icon."""
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    try:
        r = requests.get(f"{SI}/icons/{slug}.svg", timeout=20, headers=UA)
        if r.status_code == 200 and "<svg" in r.text:
            import cairosvg
            color = _si_color(slug) or "111111"
            svg = r.text.replace("<svg ", f'<svg fill="#{color}" ', 1)
            png = cairosvg.svg2png(bytestring=svg.encode(), output_width=160, output_height=160)
            return Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception as e:
        print(f"Simple Icons logo for {name} failed: {e}")
    if domain:
        try:
            r = requests.get(f"https://www.google.com/s2/favicons?domain={domain}&sz=256", timeout=20, headers=UA)
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            if img.width >= 48:
                return img
        except Exception as e:
            print(f"Website icon for {name} failed: {e}")
    return None


def make_badge(path, name, logo):
    """A dark pill with the company logo on a white tile and the name next to it."""
    fnt = font(54, semi=True)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tw = int(probe.textlength(name, font=fnt))
    tile, pad, h = 104, 18, 140
    w = pad + (tile + 24 if logo else 22) + tw + 36
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(12, 12, 20, 215))
    x = pad
    if logo:
        d.rounded_rectangle([x, (h - tile) // 2, x + tile, (h + tile) // 2], radius=26, fill=(255, 255, 255, 255))
        lg = logo.copy()
        lg.thumbnail((tile - 26, tile - 26), Image.LANCZOS)
        img.alpha_composite(lg, (x + (tile - lg.width) // 2, (h - lg.height) // 2))
        x += tile + 24
    else:
        x += 22
    d.text((x, h // 2), name, font=fnt, fill="white", anchor="lm")
    img.save(path)


def badge_events(beats, times, words, hook_end, tmp):
    """When a company is named, show its badge for ~2 seconds (first mention only, max 4)."""
    events, seen, busy_until = [], set(), 0.0
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    for (start, end), b in zip(times, beats):
        for br in (b.get("brands") or [])[:2]:
            name = str(br.get("name", "")).strip()
            if not name or norm(name) in seen or len(events) >= 4:
                continue
            first = norm(name.split()[0])
            spoken = next((w["start"] for w in words if start - 0.3 <= w["start"] <= end and norm(w["text"]).startswith(first)),
                          start + 0.2)
            t = max(spoken, hook_end + 0.1, busy_until)
            if t - spoken > 2.0:  # too long after it was said: skip rather than show it late
                continue
            logo = brand_logo(name, str(br.get("domain", "")))
            path = os.path.join(tmp, f"badge_{len(events)}.png")
            make_badge(path, name, logo)
            events.append((path, t, t + 2.2))
            seen.add(norm(name))
            busy_until = t + 2.3
            print(f"Logo badge: {name} ({'logo' if logo else 'name only'}) at {t:.1f}s")
    return events


SFX_DIR = "sfx"


SYNTH = {  # built-in sounds, used unless you add your own to the sfx/ folder
    "whoosh": ("anoisesrc=d=0.55:c=pink:r=48000:a=0.7",
               "highpass=f=350,lowpass=f=5500,afade=t=in:st=0:d=0.32:curve=exp,afade=t=out:st=0.3:d=0.25,volume=1.6"),
    "pop": ("aevalsrc=0.9*exp(-28*t)*sin(2*PI*t*(520+1600*exp(-22*t))):s=48000:d=0.22", "anull"),
    "impact": ("aevalsrc=0.9*exp(-5*t)*sin(2*PI*52*t)+0.3*exp(-22*t)*sin(2*PI*110*t):s=48000:d=0.9",
               "lowpass=f=400,volume=1.8"),
    "riser": ("aevalsrc=0.4*(t/0.7)*sin(2*PI*(260*t+420*t*t)):s=48000:d=0.7", "afade=t=out:st=0.62:d=0.08"),
}
LEVELS = {"whoosh": 0.32, "pop": 0.45, "impact": 0.5, "riser": 0.22}


def sound_file(kind, tmp):
    files = [f for ext in ("mp3", "wav", "ogg", "m4a") for f in glob.glob(os.path.join(SFX_DIR, f"{kind}*.{ext}"))]
    if files:
        return random.choice(files)
    out = os.path.join(tmp, f"{kind}.wav")
    if not os.path.exists(out):
        src, af = SYNTH[kind]
        sh(["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-af", af, "-ac", "2", out])
    return out


def add_sound_effects(audio, events, total, tmp):
    """events: [(time, kind)] → mixed quietly into the audio track."""
    events = sorted((t, k) for t, k in events if 0 <= t < total - 0.3 and k in SYNTH)[:28]
    if not events:
        return audio
    kinds = sorted({k for _, k in events})
    inputs, parts = [], []
    for n, k in enumerate(kinds):
        inputs += ["-i", sound_file(k, tmp)]
        count = sum(1 for _, kk in events if kk == k)
        parts.append(f"[{n + 1}:a]volume={LEVELS[k]},asplit={count}" + "".join(f"[{k}{j}]" for j in range(count)))
    used, labels = {k: 0 for k in kinds}, []
    for n, (t, k) in enumerate(events):
        ms = int(max(0, (t - 0.18 if k == "whoosh" else t)) * 1000)
        parts.append(f"[{k}{used[k]}]adelay={ms}|{ms}[e{n}]")
        used[k] += 1
        labels.append(f"[e{n}]")
    parts.append(f"[0:a]{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:normalize=0[out]")
    out = os.path.join(tmp, "with_sfx.wav")
    sh(["ffmpeg", "-y", "-i", audio, *inputs, "-filter_complex", ";".join(parts),
        "-map", "[out]", "-ar", "48000", "-ac", "2", out])
    return out


# ---------------------------------------------------------------- planning
def beat_times(beats, words, total):
    """Start/end time of each beat, from where its words were spoken."""
    counts = [max(1, len(b["line"].split())) for b in beats]
    n_words, n_script = len(words), sum(counts)
    times, done = [], 0
    for i, c in enumerate(counts):
        idx = min(n_words - 1, round(done / n_script * n_words)) if n_words else 0
        start = 0.0 if i == 0 or not words else words[idx]["start"]
        times.append(start)
        done += c
    return [(t, times[i + 1] if i + 1 < len(times) else total) for i, t in enumerate(times)]


LAST_SUMMARY = ""


def safe_shot(b, i, tmp):
    """A visual that can't be wrong: name card, logo card, or a neutral illustration."""
    import images
    p = os.path.join(tmp, f"safe_{i}.png")
    if b["visual"] == "person":
        make_person_card(p, b["name"], b.get("role", ""))
    elif b["visual"] in ("official", "photo", "source") or b.get("brands"):
        name = b.get("entity") or b.get("outlet") or (b.get("brands") or [{}])[0].get("name", "")
        domain = b.get("domain") or (b.get("brands") or [{}])[0].get("domain", "")
        make_logo_card(p, name or "AI news", domain)
    else:
        img = images.generate(f"minimal abstract illustration about technology and AI, calm colors, no text, no people")
        if not img:
            return None
        full_frame(img).save(p)
    return ("image", p)


def plan_visuals(beats, tmp, times=None, source_urls=(), safe_beats=()):
    """Finds visuals for every beat. Returns a list (per beat) of shots: ('clip'|'image', path)."""
    global LAST_SUMMARY, LAST_CREDITS
    import images
    import writer
    options, thumbs = {}, {}
    for i, b in enumerate(beats):
        if b["visual"] == "clip":
            options[i] = pexels_search(b["query"]) or pexels_search(" ".join(b["query"].split()[:2])) \
                or pexels_search("technology")
            thumbs[i] = [thumb_bytes(o["thumb"]) for o in options[i]]

    # Gemini looks at the thumbnails and picks the clips that fit each line
    picks = {}
    asked = [i for i in options if any(thumbs.get(i) or [])]
    if asked:
        try:
            payload = []
            for i in asked:
                keep = [k for k, t in enumerate(thumbs[i]) if t]
                options[i] = [options[i][k] for k in keep]
                payload.append({"line": beats[i]["line"], "options": [thumbs[i][k] for k in keep]})
            chosen = writer.choose_clips(payload)
            picks = {asked[k]: v for k, v in chosen.items() if k < len(asked)}
            print(f"Gemini picked clips: {picks}")
        except Exception as e:
            print(f"Clip picking skipped: {e}")

    plan, used, counts = [], set(), {"official images": 0, "real photos": 0, "clips": 0, "AI images": 0, "cards": 0}
    LAST_CREDITS = []

    # real images from the official pages and the news sources, fetched once and shared by the beats
    pool, pool_used, fetched = [], set(), set()

    def fill_pool(url):
        if url and url not in fetched and len(fetched) < 6:
            fetched.add(url)
            pool.extend((img, dom, url) for img, dom in page_images(url))

    def take_from_pool(prefer_url="", prefer_domain=""):
        order = sorted(range(len(pool)), key=lambda k: (pool[k][2] != prefer_url,
                                                          prefer_domain not in pool[k][1] if prefer_domain else True))
        for k in order:
            if k not in pool_used:
                pool_used.add(k)
                return pool[k][0], pool[k][1]
        return None, None

    if any(b["visual"] in ("official", "photo") for b in beats):
        for b in beats:
            if b["visual"] == "official":
                fill_pool(b.get("url"))
        for u in source_urls:
            fill_pool(u)
    for i, b in enumerate(beats):
        length = (times[i][1] - times[i][0]) if times else 3.0
        want = 2 if length > 3.4 else 1
        shots = []
        if i in safe_beats:
            shot = safe_shot(b, i, tmp)
            plan.append([shot] if shot else [])
            counts["cards"] += 1
            continue
        if b["visual"] == "person":
            img, credit = person_photo(b["name"], b.get("x", ""), b.get("url", ""), source_urls)
            p = os.path.join(tmp, f"person_{i}.png")
            anim = make_person_card(p, b["name"], b.get("role", ""), img, credit or "",
                                    animate_into=os.path.join(tmp, f"person_frames_{i}"))
            shots += [("layered", anim), ("image", p)] if anim else [("image", p)]
            if img:
                counts["real photos"] += 1
                LAST_CREDITS.append(f"{b['name']}: {credit}")
            else:
                counts["cards"] += 1
            print(f"Person {b['name']}: {'photo from ' + str(credit) if img else 'name card (no reliable photo)'}")
        if b["visual"] == "official":
            for _ in range(want):
                img, dom = take_from_pool(b.get("url", ""), b.get("domain", ""))
                if not img:
                    break
                p = os.path.join(tmp, f"official_{i}_{len(shots)}.png")
                framed = full_frame(img)
                add_credit(framed, dom).save(p)
                shots.append(("image", p))
                counts["official images"] += 1
                LAST_CREDITS.append(f"{b['entity']}: {dom}")
            if not shots:  # nothing on the official pages: a real photo, else the logo card
                img, credit = wiki_photo(b["entity"])
                if img:
                    p = os.path.join(tmp, f"photo_{i}.png")
                    add_credit(full_frame(img), credit.split(" (")[0]).save(p)
                    shots.append(("image", p))
                    counts["real photos"] += 1
                    LAST_CREDITS.append(f"{b['entity']}: {credit}")
                else:
                    p = os.path.join(tmp, f"logo_{i}.png")
                    make_logo_card(p, b["entity"], b.get("domain", ""))
                    shots.append(("image", p))
                    counts["cards"] += 1
        if b["visual"] == "photo":
            img, credit = wiki_photo(b["entity"])
            if img:
                p = os.path.join(tmp, f"photo_{i}.png")
                add_credit(full_frame(img), credit.split(" (")[0]).save(p)
                shots.append(("image", p))
                counts["real photos"] += 1
                LAST_CREDITS.append(f"{b['entity']}: {credit}")
            else:  # no free photo: an image from the official/news pages, else a logo card
                img, dom = take_from_pool("", b.get("domain", ""))
                p = os.path.join(tmp, f"photo_{i}.png")
                if img:
                    add_credit(full_frame(img), dom).save(p)
                    counts["official images"] += 1
                    LAST_CREDITS.append(f"{b['entity']}: {dom}")
                else:
                    make_logo_card(p, b["entity"], b.get("domain", ""))
                    counts["cards"] += 1
                shots.append(("image", p))
        if b["visual"] == "source":
            p = os.path.join(tmp, f"source_{i}.png")
            make_source_card(p, b.get("outlet", ""), b.get("headline") or b["line"], b.get("domain", ""))
            shots.append(("image", p))
            counts["cards"] += 1
        if b["visual"] == "clip":
            order = [j for j in picks.get(i, []) if 0 <= j < len(options.get(i, []))]
            if i in picks and not order:  # Gemini: none of the clips fit this line
                b = {**b, "visual": "image", "prompt": f"a cinematic scene illustrating: {b['line']}"}
            else:
                order += [j for j in range(len(options.get(i, []))) if j not in order]
                for j in order:
                    o = options[i][j]
                    if o["id"] in used:
                        continue
                    try:
                        shots.append(("clip", download(o["url"], os.path.join(tmp, f"clip_{o['id']}.mp4"))))
                        used.add(o["id"])
                        counts["clips"] += 1
                    except Exception as e:
                        print(f"Clip download failed: {e}")
                        continue
                    if len(shots) >= want:
                        break
        if b["visual"] == "image" or (b["visual"] == "clip" and not shots):
            base = b.get("prompt") or f"a cinematic scene illustrating: {b['line']}"
            variants = [base, base + ", different camera angle, close-up detail shot"][:want]
            for v, prompt in enumerate(variants):
                img = images.generate(prompt)
                if img:
                    p = os.path.join(tmp, f"img_{i}_{v}.png")
                    full_frame(img).save(p)
                    shots.append(("image", p))
                    counts["AI images"] += 1
        if b["visual"] == "stat":
            anim = None
            try:
                anim = stat_animation(tmp, i, b["big"], b["small"])
            except Exception as e:
                print(f"Count-up skipped: {e}")
            if anim:
                shots += anim
            else:
                p = os.path.join(tmp, f"stat_{i}.png")
                make_stat_card(p, b["big"], b["small"])
                shots.append(("image", p))
            counts["cards"] += 1
        plan.append(shots)
    LAST_SUMMARY = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    print(f"Visuals: {LAST_SUMMARY}")
    return plan


# ---------------------------------------------------------------- assembling
def encode_args():
    return ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def image_shot(png, frames, out, style=0):
    frames = max(1, int(frames))
    zooms = ["min(zoom+0.0012,1.12)", "if(eq(on,0),1.12,max(zoom-0.0012,1))", "1.08", "1.08"]
    xs = ["iw/2-(iw/zoom/2)", "iw/2-(iw/zoom/2)", f"(iw-iw/zoom)*on/{frames}", f"(iw-iw/zoom)*(1-on/{frames})"]
    sh(["ffmpeg", "-y", "-i", png, "-vf",
        f"scale=2160:3840,zoompan=z='{zooms[style % 4]}':x='{xs[style % 4]}':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS}", "-frames:v", str(frames), *encode_args(), out])


def clip_shot(src, frames, out, offset=0.0):
    punch = f",zoompan=z='max(1,1.06-0.0065*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}"
    sh(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", f"{offset:.2f}", "-i", src,
        "-vf", f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"eq=brightness=-0.05:saturation=1.12:contrast=1.05{punch}", "-frames:v", str(int(frames)),
        *encode_args(), out])


def layered_shot(src, frames, out, style=0):
    """A slowly zooming background with an animated layer on top (text popping in, numbers counting)."""
    frames = max(1, int(frames))
    zooms = ["min(zoom+0.0008,1.06)", "if(eq(on,0),1.06,max(zoom-0.0008,1))"]
    sh(["ffmpeg", "-y", "-i", src["bg"], "-framerate", str(FPS), "-i", os.path.join(src["dir"], "%03d.png"),
        "-filter_complex",
        f"[0:v]scale=2160:3840,zoompan=z='{zooms[style % 2]}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS}[bg];[1:v]format=rgba[fg];[bg][fg]overlay=0:0:eof_action=repeat[v]",
        "-map", "[v]", "-frames:v", str(frames), *encode_args(), out])


def frame_count(path):
    out = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
              "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path]).strip()
    return int(out or 0)


def build_video_track(beats, times, plan, hook_png, hook_len, tmp, opening=None, total=None, hook_anim=None):
    """Every shot ends exactly on the frame where it should, so the picture never drifts from the voice."""
    segments, n, pos = [], 0, 0  # pos = frames already placed

    def add(kind, src, end_time, style=0, offset=0.0, overlay=None, text_seconds=0.0):
        nonlocal n, pos
        frames = int(round(end_time * FPS)) - pos
        if frames < 1:
            return
        out = os.path.join(tmp, f"seg{n:03d}.mp4")
        n += 1
        if kind == "opening":
            opening_video_shot(src, frames / FPS, overlay, text_seconds, out)
        elif kind == "layered":
            layered_shot(src, frames, out, style)
        elif kind == "clip":
            clip_shot(src, frames, out, offset)
        else:
            image_shot(src, frames, out, style)
        got = frame_count(out)
        if got != frames:
            print(f"Shot {n}: fixing {got} → {frames} frames")
            fixed = out.replace(".mp4", "_fix.mp4")
            sh(["ffmpeg", "-y", "-i", out, "-vf", f"tpad=stop_mode=clone:stop={max(0, frames - got)}",
                "-frames:v", str(frames), *encode_args(), fixed])
            out = fixed
        segments.append(out)
        pos += frames

    if opening:  # your own clip: (path, length, overlay_png)
        src, open_len, overlay = opening
        add("opening", src, open_len, overlay=overlay, text_seconds=hook_len)
        hook_end = open_len
    elif hook_anim:
        add("layered", hook_anim, hook_len, style=0)
        hook_end = hook_len
    else:
        add("image", hook_png, hook_len, style=0)
        hook_end = hook_len
    fallback = next((s for shots in plan for s in shots if s[0] != "layered"), ("image", hook_png))
    cuts = [hook_end]
    for i, ((start, end), shots) in enumerate(zip(times, plan)):
        start = max(start, hook_end)
        length = end - start
        if length < 0.05:
            continue
        if start > hook_end + 0.2:
            cuts.append(start)
        shots = shots or [fallback]
        pieces = max(1, round(length / SHOT_SECONDS))
        for k in range(pieces):
            kind, src = shots[k % len(shots)]
            add(kind, src, start + length * (k + 1) / pieces, style=i + k, offset=(k // len(shots)) * SHOT_SECONDS)
    if total and int(round(total * FPS)) > pos:  # never end short of the voice
        kind, src = fallback
        add(kind, src, total, style=1)
    listfile = os.path.join(tmp, "list.txt")
    with open(listfile, "w") as f:
        f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segments)
    return listfile, cuts


# ---------------------------------------------------------------- sync check
LAST_SYNC = ""


def sync_offset(caption_words, heard_words):
    """Median gap (seconds) between caption times and what Whisper hears, over matching words."""
    import difflib
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    a, b = [norm(w["text"]) for w in caption_words], [norm(w["text"]) for w in heard_words]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    diffs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            diffs += [caption_words[i1 + k]["start"] - heard_words[j1 + k]["start"] for k in range(i2 - i1)]
    if len(diffs) < 5:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]


# ---------------------------------------------------------------- main
LAST_CHECK = {}


def check_frames(out):
    """One small frame from the middle of each beat (after the opening), for the visual check."""
    info = LAST_CHECK
    frames = []
    for i, (start, end) in enumerate(info.get("times", [])):
        start = max(start, info.get("hook_end", 0))
        if end - start < 0.4:
            continue
        t = (start + end) / 2
        tmpf = os.path.join(WORK_DIR, "build", f"check_{i}.jpg")
        try:
            sh(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", out, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", tmpf])
            with open(tmpf, "rb") as f:
                frames.append({"beat": i, "jpeg": f.read(), **info["intents"][i]})
        except Exception as e:
            print(f"Frame {i} skipped: {e}")
    return frames


def render(voice_path, draft, topic, user_image_path=None, words=None, user_video_path=None, exact_words=None,
           safe_beats=()):
    """exact_words: word timings reported by the AI voice itself (most accurate)."""
    global LAST_SYNC
    tmp = os.path.join(WORK_DIR, "build")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    wav = os.path.join(tmp, "voice.wav")
    clean_audio(voice_path, wav, trim_start=not exact_words)  # keep the AI voice's own timeline
    total = duration(wav)
    if total > 180:
        raise RuntimeError("The recording is longer than 3 minutes. Please keep reels under 90 seconds.")
    from config import SPOKEN_NAME
    caption_script = re.sub(r"@\w[\w.]*", SPOKEN_NAME or "", draft.get("script", ""))
    LAST_SYNC = ""
    if words is None:
        heard = None
        try:
            heard = transcribe(wav, hint=caption_script)
        except Exception as e:
            print(f"Whisper failed: {e}")
        if exact_words:
            words = align_to_script(exact_words, caption_script)
            gap = sync_offset(words, heard) if heard else None
            if gap is not None and abs(gap) > 0.15 and heard:  # voice timings look off: trust what Whisper hears
                print(f"Voice timings off by {gap:+.2f}s, using Whisper instead")
                words = align_to_script(heard, caption_script)
                gap = 0.0
            LAST_SYNC = "✅ captions checked" + (f" (±{abs(gap):.2f}s)" if gap is not None else "")
        elif heard:
            words = align_to_script(heard, caption_script)
            LAST_SYNC = "✅ captions timed from the voice"
        else:
            raise RuntimeError("Couldn't time the captions (speech recognition failed).")
    words = [{**w, "start": max(0.0, w["start"] - 0.05)} for w in words]  # appear a hair early, feels in sync

    beats = draft.get("beats") or [{"line": draft.get("script", ""), "visual": "clip", "query": "technology"}]
    times = beat_times(beats, words, total)
    hook_len = min(max(times[0][1], 1.6), 2.8, total)

    # hook screen picture: your image > the article's photo > the first AI image / stat
    hook_img = None
    if user_image_path:
        try:
            hook_img = Image.open(user_image_path).convert("RGB")
        except Exception:
            hook_img = None
    if hook_img is None and topic and not topic.get("custom"):
        url = news.og_image(topic.get("link"))
        hook_img = fetch_image(url) if url else None
    sources = [topic.get("link")] if topic and topic.get("link") else []
    sources += [u for u in (draft.get("sources") or []) if isinstance(u, str) and u.startswith("http")][:4]
    plan = plan_visuals(beats, tmp, times, sources, safe_beats)
    if hook_img is None:
        # a real picture for the opening background — never a text card (stat, person, source, logo)
        picture = ("img_", "official_", "photo_")
        first = next((src for shots in plan for kind, src in shots
                      if kind == "image" and os.path.basename(src).startswith(picture)), None)
        hook_img = Image.open(first).convert("RGB") if first else None
    hook_png = os.path.join(tmp, "hook.png")
    label = news_label(topic)
    make_hook_card(hook_png, draft.get("hook_text") or draft.get("title", ""), label, hook_img)

    opening = None
    if user_video_path:
        try:
            clip_len = duration(user_video_path)
            open_len = min(clip_len, 6.0, total)
            overlay = os.path.join(tmp, "hook_overlay.png")
            make_hook_overlay(overlay, draft.get("hook_text") or draft.get("title", ""), label)
            opening = (user_video_path, max(open_len, hook_len), overlay)
        except Exception as e:
            print(f"Your video couldn't be used, using the normal opening: {e}")
            opening = None

    ass = os.path.join(tmp, "captions.ass")
    write_ass(words, total, ass, hook_until=hook_len * 0.85)
    hook_anim = None
    if not opening:
        try:
            hook_anim = hook_animation(tmp, draft.get("hook_text") or draft.get("title", ""), label, hook_img)
        except Exception as e:
            print(f"Hook animation skipped: {e}")
    listfile, cuts = build_video_track(beats, times, plan, hook_png, hook_len, tmp, opening, total, hook_anim)
    hook_end = opening[1] if opening else hook_len

    def intent(b):
        what = {"person": f"a photo of {b.get('name')} ({b.get('role')}) or an initials card",
                "official": f"real images of {b.get('entity')}", "photo": f"a real photo of {b.get('entity')}",
                "source": f"a source card for {b.get('outlet')}", "stat": f"a big number {b.get('big')}",
                "clip": f"stock video: {b.get('query')}", "image": f"illustration: {b.get('prompt', '')[:80]}"}
        return {"line": b["line"], "intent": what.get(b["visual"], b["visual"])}
    LAST_CHECK.clear()
    LAST_CHECK.update({"times": times, "hook_end": hook_end, "intents": [intent(b) for b in beats]})
    badges = []
    try:
        badges = badge_events(beats, times, words, hook_len, tmp)
    except Exception as e:
        print(f"Logo badges skipped: {e}")

    audio = wav
    music = pick_music()
    if music:
        try:
            audio = os.path.join(tmp, "mixed.wav")
            mix_music(wav, music, total, audio)
            print(f"Background music: {os.path.basename(music)}")
        except Exception as e:
            print(f"Music skipped: {e}")
            audio = wav

    try:
        sfx = [(0.06, "impact")] + [(t, "whoosh") for t in cuts]
        for i, b in enumerate(beats):
            if b["visual"] == "stat" and times[i][0] >= hook_end:
                sfx += [(times[i][0] + 0.02, "riser"), (times[i][0] + 0.72, "pop")]
        sfx += [(start, "pop") for _, start, _ in badges]
        audio = add_sound_effects(audio, sfx, total, tmp)
    except Exception as e:
        print(f"Sound effects skipped: {e}")

    out = os.path.join(WORK_DIR, "reel.mp4")
    fontsdir = FONT_DIR if os.path.isdir(FONT_DIR) else "."
    graph = [f"[0:v]subtitles={ass}:fontsdir={fontsdir}[v0]"]
    inputs, last = [], "v0"
    for k, (png, a, b) in enumerate(badges):
        inputs += ["-loop", "1", "-t", f"{total:.2f}", "-i", png]
        idx = 2 + k
        graph.append(f"[{idx}:v]format=rgba,fade=t=in:st={a:.2f}:d=0.18:alpha=1,"
                     f"fade=t=out:st={b - 0.25:.2f}:d=0.25:alpha=1[b{k}]")
        graph.append(f"[{last}][b{k}]overlay=x=(W-w)/2:y=200:enable='between(t,{a:.2f},{b:.2f})'[v{k + 1}]")
        last = f"v{k + 1}"
    graph.append(f"color=c={ACCENT_HEX}:s={W}x10:r={FPS}[bar]")
    graph.append(f"[{last}][bar]overlay=x='-w+w*t/{total:.3f}':y=H-10:shortest=1[out]")
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-i", audio, *inputs,
        "-filter_complex", ";".join(graph), "-map", "[out]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "4000k", "-bufsize", "8000k",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart", out])
    v_len, a_len = duration_of(out, "v"), duration_of(out, "a")
    if v_len and a_len and abs(v_len - a_len) > 0.12:
        LAST_SYNC += f" ⚠️ picture/sound length differ by {abs(v_len - a_len):.2f}s"
        print(LAST_SYNC)
    return out


def duration_of(path, kind):
    try:
        out = sh(["ffprobe", "-v", "error", "-select_streams", f"{kind}:0", "-show_entries", "stream=duration",
                  "-of", "csv=p=0", path]).strip()
        return float(out)
    except Exception:
        return None

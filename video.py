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
ACCENT = (255, 212, 0)        # yellow
ACCENT_ASS = "&H0000D4FF&"    # same yellow in ASS (BGR)
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
def clean_audio(src, dst):
    trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15"
    af = (f"highpass=f=80,afftdn=nf=-25,{trim},areverse,{trim},areverse,"
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
def chunk_words(words, max_words=2, max_chars=13):
    chunks, cur = [], []
    for w in words:
        joined = " ".join(x["text"] for x in cur + [w])
        if cur and (len(cur) >= max_words or len(joined) > max_chars or w["start"] - cur[-1]["end"] > 0.5):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?,;:]$", w["text"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_text(t):
    t = re.sub(r"[{}\\]", "", t)
    t = re.sub(r"^[.,;:!?…\-–—]+", "", t)
    t = re.sub(r"[.,;:]+$", "", t)  # trailing commas/full stops look messy on screen
    return t.upper()


def font_name():
    return "Poppins" if os.path.exists(FONT_BOLD) else "DejaVu Sans"


def write_ass(words, total, path, hook_until=0.0):
    out = [f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_name()},118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,9,4,2,70,70,640,1
Style: Handle,{font_name()},36,&H40FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,3,0,8,60,60,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""]
    chunks = chunk_words(words)
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else total
        chunk_end = nxt if nxt - ch[-1]["end"] < 0.5 else ch[-1]["end"] + 0.3
        for wi, w in enumerate(ch):
            start = w["start"]
            end = ch[wi + 1]["start"] if wi + 1 < len(ch) else chunk_end
            end = max(end, start + 0.05)
            if end <= hook_until:
                continue  # the hook screen has its own big text
            start = max(start, hook_until)
            parts = []
            for k, x in enumerate(ch):
                t = ass_text(x["text"])
                parts.append(f"{{\\c{ACCENT_ASS}\\fscx108\\fscy108}}{t}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
                             if k == wi else t)
            pop = "{\\fscx70\\fscy70\\t(0,110,\\fscx100\\fscy100)}" if wi == 0 else ""
            out.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{pop}{' '.join(parts)}")
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


def make_hook_card(path, hook, label, image=None):
    bg = full_frame(image, center=0.68) if image else gradient()
    bg = darken(bg, 0.25, 0.6)
    d = ImageDraw.Draw(bg)
    lf = font(38, semi=True)
    tw = d.textlength(label, font=lf)
    d.rounded_rectangle([W / 2 - tw / 2 - 28, 300, W / 2 + tw / 2 + 28, 368], radius=34, fill=ACCENT)
    d.text((W / 2, 334), label, font=lf, fill="black", anchor="mm")
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
    tw = d.textlength(label, font=lf)
    d.rounded_rectangle([W / 2 - tw / 2 - 28, 300, W / 2 + tw / 2 + 28, 368], radius=34, fill=ACCENT)
    d.text((W / 2, 334), label, font=lf, fill="black", anchor="mm")
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


def make_stat_card(path, big, small, image=None):
    bg = darken(full_frame(image).filter(ImageFilter.GaussianBlur(18)), 0.55, 0.85) if image else gradient()
    d = ImageDraw.Draw(bg)
    size = 300 if len(big) <= 4 else 240 if len(big) <= 6 else 180
    d.text((W / 2, 560), big, font=font(size), fill=ACCENT, anchor="ma", stroke_width=6, stroke_fill="black")
    text_block(d, small.upper(), font(68, semi=True), 560 + int(size * 1.15))
    bg.save(path)


# ---------------------------------------------------------------- stock footage
def pexels_search(query, n=4):
    if not PEXELS_API_KEY:
        return []
    try:
        r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                         headers={"Authorization": PEXELS_API_KEY},
                         params={"query": query, "orientation": "portrait", "per_page": n + 2, "size": "medium"})
        videos = r.json().get("videos", []) if r.status_code == 200 else []
    except Exception:
        return []
    found = []
    for v in videos:
        files = [f for f in v.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 960]
        if files and v.get("image"):
            best = min(files, key=lambda f: abs(f["height"] - 1920))
            found.append({"id": v["id"], "thumb": v["image"], "url": best["link"], "duration": v.get("duration", 10)})
    return found[:n]


def thumb_bytes(url):
    try:
        r = requests.get(url, timeout=20)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((220, 390))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue()
    except Exception:
        return None


def download(url, path):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for c in r.iter_content(1 << 16):
                f.write(c)
    return path


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


def plan_visuals(beats, tmp):
    """Finds a visual for every beat. Returns a list of lists of ('clip'|'image'|'stat', payload)."""
    import images
    import writer
    options = {}
    for i, b in enumerate(beats):
        if b["visual"] == "clip":
            options[i] = pexels_search(b["query"]) or pexels_search("technology abstract")
    # let Gemini look at the thumbnails and choose clips that fit each line
    picks = {}
    asked = [i for i in options if options[i]]
    if asked:
        try:
            payload = []
            for i in asked:
                thumbs = [thumb_bytes(o["thumb"]) for o in options[i]]
                options[i] = [o for o, t in zip(options[i], thumbs) if t]
                payload.append({"line": beats[i]["line"], "options": [t for t in thumbs if t]})
            chosen = writer.choose_clips(payload)
            picks = {asked[k]: v for k, v in chosen.items() if k < len(asked)}
            print(f"Gemini picked clips: {picks}")
        except Exception as e:
            print(f"Clip picking skipped: {e}")
    plan, used = [], set()
    for i, b in enumerate(beats):
        shots = []
        if b["visual"] == "clip":
            order = [j for j in picks.get(i, []) if 0 <= j < len(options.get(i, []))]
            if i in picks and not order:  # Gemini said nothing fits: use an AI image instead
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
                    except Exception:
                        continue
                    if len(shots) >= 2:
                        break
        if b["visual"] == "image" or (b["visual"] == "clip" and not shots):
            img = images.generate(b.get("prompt") or f"a cinematic scene illustrating: {b['line']}")
            if img:
                p = os.path.join(tmp, f"img_{i}.png")
                full_frame(img).save(p)
                shots.append(("image", p))
        if b["visual"] == "stat":
            p = os.path.join(tmp, f"stat_{i}.png")
            make_stat_card(p, b["big"], b["small"])
            shots.append(("image", p))
        plan.append(shots)
    return plan


# ---------------------------------------------------------------- assembling
def encode_args():
    return ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def image_shot(png, length, out, style=0):
    frames = max(1, int(round(length * FPS)))
    zooms = ["min(zoom+0.0012,1.12)", "if(eq(on,0),1.12,max(zoom-0.0012,1))", "1.08", "1.08"]
    xs = ["iw/2-(iw/zoom/2)", "iw/2-(iw/zoom/2)", f"(iw-iw/zoom)*on/{frames}", f"(iw-iw/zoom)*(1-on/{frames})"]
    sh(["ffmpeg", "-y", "-i", png, "-vf",
        f"scale=2160:3840,zoompan=z='{zooms[style % 4]}':x='{xs[style % 4]}':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS}", "-frames:v", str(frames), *encode_args(), out])


def clip_shot(src, length, out, offset=0.0):
    sh(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", f"{offset:.2f}", "-i", src, "-t", f"{length:.3f}",
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               "eq=brightness=-0.05:saturation=1.12:contrast=1.05", *encode_args(), out])


def build_video_track(beats, times, plan, hook_png, hook_len, tmp, opening=None):
    segments, n = [], 0

    def add(kind, src, length, style=0, offset=0.0):
        nonlocal n
        if length < 0.05:
            return
        out = os.path.join(tmp, f"seg{n:03d}.mp4")
        n += 1
        if kind == "clip":
            clip_shot(src, length, out, offset)
        else:
            image_shot(src, length, out, style)
        segments.append(out)

    if opening:  # your own clip: (path, length, overlay_png)
        src, open_len, overlay = opening
        out = os.path.join(tmp, f"seg{n:03d}.mp4")
        n += 1
        opening_video_shot(src, open_len, overlay, hook_len, out)
        segments.append(out)
        hook_end = open_len
    else:
        add("image", hook_png, hook_len, style=0)
        hook_end = hook_len
    fallback = next((s for shots in plan for s in shots), ("image", hook_png))
    for i, ((start, end), shots) in enumerate(zip(times, plan)):
        start = max(start, hook_end)
        length = end - start
        if length < 0.05:
            continue
        shots = shots or [fallback]
        pieces = max(1, round(length / SHOT_SECONDS))
        for k in range(pieces):
            kind, src = shots[k % len(shots)]
            add(kind, src, length / pieces, style=i + k, offset=(k // len(shots)) * SHOT_SECONDS)
    listfile = os.path.join(tmp, "list.txt")
    with open(listfile, "w") as f:
        f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segments)
    return listfile


# ---------------------------------------------------------------- main
def render(voice_path, draft, topic, user_image_path=None, words=None, user_video_path=None):
    tmp = os.path.join(WORK_DIR, "build")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    wav = os.path.join(tmp, "voice.wav")
    clean_audio(voice_path, wav)
    total = duration(wav)
    if total > 180:
        raise RuntimeError("The recording is longer than 3 minutes. Please keep reels under 90 seconds.")
    if words is None:
        words = align_to_script(transcribe(wav, hint=draft.get("script", "")), draft.get("script", ""))

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
    plan = plan_visuals(beats, tmp)
    if hook_img is None:
        first = next((src for shots in plan for kind, src in shots if kind == "image"), None)
        hook_img = Image.open(first).convert("RGB") if first else None
    hook_png = os.path.join(tmp, "hook.png")
    label = "AI EXPLAINED" if (topic or {}).get("custom") else "AI NEWS"
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
    listfile = build_video_track(beats, times, plan, hook_png, hook_len, tmp, opening)

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

    out = os.path.join(WORK_DIR, "reel.mp4")
    fontsdir = FONT_DIR if os.path.isdir(FONT_DIR) else "."
    graph = (f"[0:v]subtitles={ass}:fontsdir={fontsdir}[v];"
             f"color=c=0xFFD400:s={W}x10:r={FPS}[bar];"
             f"[v][bar]overlay=x='-w+w*t/{total:.3f}':y=H-10:shortest=1[out]")
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-i", audio,
        "-filter_complex", graph, "-map", "[out]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "4000k", "-bufsize", "8000k",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart", out])
    return out

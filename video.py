"""Turns your voice note + script into a 1080x1920 reel with word-by-word captions."""
import glob
import io
import math
import random
import os
import re
import shutil
import subprocess

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import news
from config import FONT_NAME, FONT_PATH, HANDLE, PEXELS_API_KEY, WORK_DIR

W, H, FPS = 1080, 1920, 30
HIGHLIGHT = "&H00E5FF&"  # yellow, in ASS's BGR format
CLIP_SECONDS = 4.0
MUSIC_DIR = "music"
MUSIC_VOLUME = float(os.environ.get("MUSIC_VOLUME") or 0.15)  # 0.1 = quieter, 0.25 = louder


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-1200:]}")
    return r.stdout


def duration(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", path]).strip())


# ---------- audio ----------
def clean_audio(src, dst):
    trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15"
    af = (f"highpass=f=80,afftdn=nf=-25,{trim},areverse,{trim},areverse,"
          "loudnorm=I=-14:TP=-1.5:LRA=11,apad=pad_dur=0.6")
    sh(["ffmpeg", "-y", "-i", src, "-af", af, "-ar", "48000", "-ac", "2", dst])


def pick_music():
    tracks = [f for ext in ("mp3", "m4a", "wav", "ogg", "aac")
              for f in glob.glob(os.path.join(MUSIC_DIR, f"*.{ext}"))]
    return random.choice(tracks) if tracks else None


def mix_music(voice_wav, music, total, dst):
    """Soft background music that ducks under your voice and fades out at the end."""
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
            if w.word.strip():
                words.append({"text": w.word.strip(), "start": w.start, "end": w.end})
    return words


# ---------- captions ----------
def chunk_words(words, max_words=3, max_chars=14):
    chunks, cur = [], []
    for w in words:
        joined = " ".join(x["text"] for x in cur + [w])
        if cur and (len(cur) >= max_words or len(joined) > max_chars or w["start"] - cur[-1]["end"] > 0.6):
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
    return re.sub(r"[{}\\]", "", t).upper()


def write_ass(words, total, path):
    out = [f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT_NAME},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,500,1
Style: Handle,{FONT_NAME},38,&H50FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,60,60,150,1

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
            parts = [f"{{\\c{HIGHLIGHT}}}{ass_text(x['text'])}{{\\c&HFFFFFF&}}" if k == wi
                     else ass_text(x["text"]) for k, x in enumerate(ch)]
            pop = "{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
            out.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{pop}{' '.join(parts)}")
    if HANDLE:
        handle = re.sub(r"[{}\\]", "", HANDLE.lstrip("@"))
        out.append(f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Handle,,0,0,0,,@{handle}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


# ---------- images ----------
def font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default(size)


def gradient(top=(12, 10, 40), bottom=(70, 30, 120)):
    col = Image.new("RGB", (1, H))
    for y in range(H):
        a = y / (H - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * a) for i in range(3)))
    return col.resize((W, H))


def fetch_image(url):
    try:
        r = requests.get(url, headers=news.UA, timeout=15)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img if img.width >= 300 else None
    except Exception:
        return None


def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)))
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


def make_card(path, headline, label, image=None):
    if image:
        bg = cover(image, W, H).filter(ImageFilter.GaussianBlur(40))
        bg = Image.blend(bg, Image.new("RGB", (W, H)), 0.55)
    else:
        bg = gradient()
    d = ImageDraw.Draw(bg)
    lf = font(42)
    tw = d.textlength(label, font=lf)
    x0 = (W - tw) / 2 - 32
    d.rounded_rectangle([x0, 230, x0 + tw + 64, 312], radius=41, fill=(255, 229, 0))
    d.text((W / 2, 271), label, font=lf, fill=(0, 0, 0), anchor="mm")
    size = 78
    while True:
        hf = font(size)
        lines = wrap(d, headline, hf, W - 140)
        if len(lines) <= 4 or size <= 46:
            break
        size -= 6
    y = 370
    for line in lines[:4]:
        d.text((W / 2, y), line, font=hf, fill="white", anchor="ma", stroke_width=3, stroke_fill="black")
        y += int(size * 1.22)
    if image:
        max_h = 1230 - (y + 50)
        if max_h > 220:
            im = image.copy()
            im.thumbnail((W - 120, max_h))
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=28, fill=255)
            bg.paste(im, ((W - im.width) // 2, y + 50), mask)
    bg.save(path)


def make_scene(image, path):
    """Full-screen for tall images, 'poster' style (blurred background) for wide ones."""
    if image.height / image.width >= 1.5:
        cover(image, W, H).save(path)
        return
    bg = cover(image, W, H).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H)), 0.35)
    im = image.copy()
    im.thumbnail((W - 80, 1000))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=28, fill=255)
    bg.paste(im, ((W - im.width) // 2, 220), mask)
    bg.save(path)


# ---------- stock footage ----------
def pexels_clips(keywords, dest, want=8):
    if not PEXELS_API_KEY:
        return []
    paths, used = [], set()
    terms = list(keywords) + ["artificial intelligence", "technology abstract", "futuristic"]
    for term in terms:
        if len(paths) >= want:
            break
        try:
            r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                             headers={"Authorization": PEXELS_API_KEY},
                             params={"query": term, "orientation": "portrait", "per_page": 8})
            videos = r.json().get("videos", []) if r.status_code == 200 else []
        except Exception:
            continue
        taken = 0
        for v in videos:
            if v["id"] in used or taken >= 2 or len(paths) >= want:
                continue
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 960]
            if not files:
                continue
            best = min(files, key=lambda f: abs(f["height"] - 1920))
            path = os.path.join(dest, f"clip{len(paths)}.mp4")
            try:
                with requests.get(best["link"], stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as f:
                        for c in resp.iter_content(1 << 16):
                            f.write(c)
            except Exception:
                continue
            used.add(v["id"])
            paths.append(path)
            taken += 1
    return paths


def encode_args():
    return ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def image_segment(png, length, out, zoom_in=True):
    frames = max(1, int(length * FPS))
    z = "min(zoom+0.0006,1.08)" if zoom_in else "if(eq(on,0),1.08,max(zoom-0.0006,1))"
    sh(["ffmpeg", "-y", "-i", png, "-vf",
        f"scale=2160:3840,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS}", "-frames:v", str(frames), *encode_args(), out])


def build_background(total, card_png, keywords, tmp, scenes=()):
    card_len = min(3.5, total)
    segments = [os.path.join(tmp, "seg000.mp4")]
    image_segment(card_png, card_len, segments[0])

    remaining = total - card_len
    if remaining > 0.05:
        sources = [("clip", c) for c in pexels_clips(keywords, tmp)]
        for pos, scene in zip((1, 3), scenes):  # mix AI images between stock clips
            sources.insert(min(pos, len(sources)), ("image", scene))
        if not sources:
            plain = os.path.join(tmp, "plain.png")
            gradient().save(plain)
            sources = [("plain", plain)]
        n = math.ceil(remaining / CLIP_SECONDS)
        for i in range(n):
            length = min(CLIP_SECONDS, remaining - i * CLIP_SECONDS)
            if length < 0.05:
                break
            kind, src = sources[i % len(sources)]
            seg = os.path.join(tmp, f"seg{i + 1:03d}.mp4")
            if kind == "clip":
                offset = (i // len(sources)) * CLIP_SECONDS
                sh(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(offset), "-i", src, "-t", f"{length:.3f}",
                    "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                           "eq=brightness=-0.07:saturation=1.1", *encode_args(), seg])
            elif kind == "image":
                image_segment(src, length, seg, zoom_in=(i % 2 == 0))
            else:
                sh(["ffmpeg", "-y", "-loop", "1", "-i", src, "-t", f"{length:.3f}", *encode_args(), seg])
            segments.append(seg)

    listfile = os.path.join(tmp, "list.txt")
    with open(listfile, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in segments)
    return listfile


# ---------- main ----------
def render(voice_path, draft, topic, user_image_path=None, words=None):
    import images
    tmp = os.path.join(WORK_DIR, "build")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    wav = os.path.join(tmp, "voice.wav")
    clean_audio(voice_path, wav)
    total = duration(wav)
    if total > 180:
        raise RuntimeError("The recording is longer than 3 minutes. Please keep reels under 90 seconds.")

    if words is None:
        words = transcribe(wav, hint=draft.get("script", ""))
    ass = os.path.join(tmp, "captions.ass")
    write_ass(words, total, ass)

    # AI images for the story
    ai = [img for img in (images.generate(p) for p in draft.get("image_prompts", [])[:3]) if img]

    # Title card image: your image > the article's photo > an AI image
    card_image = None
    if user_image_path:
        try:
            card_image = Image.open(user_image_path).convert("RGB")
        except Exception:
            card_image = None
    if card_image is None and topic and not topic.get("custom"):
        url = news.og_image(topic.get("link"))
        card_image = fetch_image(url) if url else None
    if card_image is None and ai:
        card_image = ai.pop(0)

    card = os.path.join(tmp, "card.png")
    label = "AI EXPLAINED" if (topic or {}).get("custom") else "AI NEWS TODAY"
    make_card(card, draft.get("title", ""), label, card_image)

    scenes = []
    for i, img in enumerate(ai[:2]):
        path = os.path.join(tmp, f"scene{i}.png")
        make_scene(img, path)
        scenes.append(path)

    listfile = build_background(total, card, draft.get("keywords", []), tmp, scenes)

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
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-i", audio,
        "-vf", f"subtitles={ass}", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-maxrate", "3500k", "-bufsize", "7000k",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart", out])
    return out

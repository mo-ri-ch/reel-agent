"""Free AI voice-over. Tries Microsoft Edge voices (Indian English), falls back to Kokoro (open source)."""
import asyncio
import os
import re

import requests

import random

from config import KOKORO_FEMALE, KOKORO_MALE, TTS_RATE, VOICES_FEMALE, VOICES_MALE

KOKORO_DIR = os.path.expanduser("~/.cache/kokoro")
KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]


def _speakable(text):
    text = re.sub(r"@(\w[\w.]*)", lambda m: m.group(1).replace(".", " dot "), text)  # "@gradientailabs" → "gradientailabs"
    return re.sub(r"[ \t]+", " ", text).strip()


def _edge(text, out_base, voice):
    import edge_tts
    out = out_base + ".mp3"

    async def run():
        await edge_tts.Communicate(text, voice, rate=TTS_RATE).save(out)

    asyncio.run(run())
    if not os.path.exists(out) or os.path.getsize(out) < 2000:
        raise RuntimeError("no audio returned")
    return out


def _kokoro(text, out_base, voice):
    os.makedirs(KOKORO_DIR, exist_ok=True)
    for name in KOKORO_FILES:
        path = os.path.join(KOKORO_DIR, name)
        if not os.path.exists(path):
            print(f"Downloading {name}...")
            with requests.get(KOKORO_BASE + name, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(path + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(path + ".part", path)
    import soundfile as sf
    from kokoro_onnx import Kokoro
    k = Kokoro(os.path.join(KOKORO_DIR, KOKORO_FILES[0]), os.path.join(KOKORO_DIR, KOKORO_FILES[1]))
    lang = "en-gb" if voice.startswith("b") else "en-us"
    samples, rate = k.create(text, voice=voice, speed=1.05, lang=lang)
    out = out_base + ".wav"
    sf.write(out, samples, rate)
    return out


def voice_label(voice):
    """en-IN-NeerjaExpressiveNeural → 'Neerja Expressive (IN)'"""
    parts = voice.split("-")
    if len(parts) >= 3:
        name = re.sub(r"Neural$", "", parts[2])
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
        return f"{name} ({parts[1]})"
    return voice


def synthesize(text, out_base, gender="male"):
    """Returns (audio_path, description). Picks a random voice of the given gender."""
    text = _speakable(text)
    pool = [v.strip() for v in (VOICES_FEMALE if gender == "female" else VOICES_MALE) if v.strip()]
    random.shuffle(pool)
    for voice in pool[:2]:
        try:
            return _edge(text, out_base, voice), f"{voice_label(voice)}, {gender}"
        except Exception as e:
            print(f"Edge voice {voice} failed: {e}")
    backup = KOKORO_FEMALE if gender == "female" else KOKORO_MALE
    return _kokoro(text, out_base, backup), f"backup voice {backup}, {gender}"

"""Free AI voice-over. Tries Microsoft Edge voices (Indian English), falls back to Kokoro (open source)."""
import asyncio
import os
import re

import requests

import random

from config import GEMINI_API_KEY, GEMINI_TTS_MODEL, GOOGLE_VOICES_FEMALE, GOOGLE_VOICES_MALE, SPOKEN_NAME, KOKORO_FEMALE, KOKORO_MALE, TTS_RATE, VOICES_FEMALE, VOICES_MALE

KOKORO_DIR = os.path.expanduser("~/.cache/kokoro")
KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]


def _speakable(text):
    text = re.sub(r"@(\w[\w.]*)", lambda m: SPOKEN_NAME or m.group(1).replace(".", " dot "), text)  # "@gradientailabs" → "Gradient AI Labs"
    return re.sub(r"[ \t]+", " ", text).strip()


LAST_WORDS = None  # exact word timings from the Edge voice, when available


def _edge(text, out_base, voice):
    global LAST_WORDS
    import edge_tts
    out = out_base + ".mp3"
    words = []

    async def run():
        try:
            comm = edge_tts.Communicate(text, voice, rate=TTS_RATE, boundary="WordBoundary")
        except TypeError:  # older edge-tts
            comm = edge_tts.Communicate(text, voice, rate=TTS_RATE)
        with open(out, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 10_000_000
                    words.append({"text": chunk["text"], "start": start,
                                  "end": start + chunk["duration"] / 10_000_000})

    asyncio.run(run())
    if not os.path.exists(out) or os.path.getsize(out) < 2000:
        raise RuntimeError("no audio returned")
    LAST_WORDS = words if len(words) >= 3 else None
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


LAST_ENGINE = ""  # "google" / "microsoft" / "backup": which one made the last voice-over
_TTS_MODELS = None


def _tts_models():
    """Google's text-to-speech models available to this key, newest first."""
    global _TTS_MODELS
    if _TTS_MODELS is None:
        _TTS_MODELS = [GEMINI_TTS_MODEL] if GEMINI_TTS_MODEL else []
        try:
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", timeout=20,
                             params={"pageSize": 200}, headers={"x-goog-api-key": GEMINI_API_KEY})
            names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                     if "tts" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", [])]
            def rank(n):  # newest version first, "flash" before "pro" (faster, bigger free quota)
                v = re.findall(r"(\d+(?:\.\d+)?)", n)
                return (-float(v[0]) if v else 0, "pro" in n, "preview" in n)
            _TTS_MODELS += sorted(names, key=rank)
        except Exception as e:
            print(f"Couldn't list Google TTS models: {e}")
        _TTS_MODELS = _TTS_MODELS or ["gemini-2.5-flash-preview-tts"]
    return _TTS_MODELS


def _google(text, out_base, voice):
    """A Google (Gemini) voice. Returns a .wav path."""
    import base64
    import wave
    prompt = text  # ONLY the script: any instruction here can end up being read aloud
    last = ""
    for model in _tts_models()[:2]:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=180, json={
                              "contents": [{"parts": [{"text": prompt}]}],
                              "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                                  "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})
        if r.status_code != 200:
            last = f"{model}: HTTP {r.status_code} {r.text[:150]}"
            continue
        parts = r.json()["candidates"][0]["content"]["parts"]
        audio = next((p["inlineData"] for p in parts if "inlineData" in p), None)
        if not audio:
            last = f"{model}: no audio in reply"
            continue
        pcm = base64.b64decode(audio["data"])
        rate = int((re.search(r"rate=(\d+)", audio.get("mimeType", "")) or [None, 24000])[1])
        out = out_base + ".wav"
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        if len(pcm) < rate:  # under half a second: something went wrong
            last = f"{model}: audio too short"
            continue
        return out
    raise RuntimeError(last or "no Google TTS model worked")


def synthesize(text, out_base, gender="male", engine="microsoft"):
    """Returns (audio_path, description). engine: "google" or "microsoft" (the other is the automatic backup)."""
    global LAST_WORDS, LAST_ENGINE
    LAST_WORDS = None
    text = _speakable(text)
    engines = ["google", "microsoft"] if engine == "google" else ["microsoft", "google"]
    for eng in engines:
        if eng == "google":
            pool = [v.strip() for v in (GOOGLE_VOICES_FEMALE if gender == "female" else GOOGLE_VOICES_MALE) if v.strip()]
            voice = random.choice(pool)
            try:
                path = _google(text, out_base + "_g", voice)
                LAST_ENGINE = "google"
                return path, f"{voice} (Google), {gender}"
            except Exception as e:
                print(f"Google voice {voice} failed: {e}")
        else:
            pool = [v.strip() for v in (VOICES_FEMALE if gender == "female" else VOICES_MALE) if v.strip()]
            random.shuffle(pool)
            for voice in pool[:2]:
                try:
                    path = _edge(text, out_base, voice)
                    LAST_ENGINE = "microsoft"
                    return path, f"{voice_label(voice)} (Microsoft), {gender}"
                except Exception as e:
                    print(f"Edge voice {voice} failed: {e}")
    backup = KOKORO_FEMALE if gender == "female" else KOKORO_MALE
    LAST_ENGINE = "backup"
    return _kokoro(text, out_base, backup), f"backup voice {backup}, {gender}"


def speech_matches(heard_words, script, max_extra_chars=14):
    """True if the voice-over says the script and nothing else.
    Extra words heard before/after the script only count when they are NOT script words: speech recognition sometimes
    'hears' an echo of script phrases in the silence at the end, which isn't a real problem; an instruction read aloud
    ("read this like a news presenter") is made of words that aren't in the script, and is caught."""
    import difflib
    norm = lambda t: re.sub(r"[^a-z0-9]", "", str(t).lower())
    words = [norm(w["text"] if isinstance(w, dict) else w) for w in heard_words]
    words = [w for w in words if w]
    want = norm(_speakable(script))
    script_words = {norm(w) for w in _speakable(script).split()} - {""}
    if not words or not want:
        return False, "no speech found"
    heard = "".join(words)
    starts, pos = [], 0
    for w in words:
        starts.append(pos)
        pos += len(w)
    sm = difflib.SequenceMatcher(None, heard, want, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 3]
    if not blocks:
        return False, "the audio doesn't match the script"
    covered = sum(b.size for b in blocks) / len(want)
    first, last = blocks[0].a, blocks[-1].a + blocks[-1].size
    lead = [w for w, p in zip(words, starts) if p + len(w) <= first]
    trail = [w for w, p in zip(words, starts) if p >= last]

    def foreign(extra):  # extra words that aren't from the script at all
        return [w for w in extra if w not in script_words and not any(w in sw or sw in w for sw in script_words if len(sw) > 3)]
    if len("".join(foreign(lead))) > max_extra_chars:
        return False, f"extra words at the start: “{' '.join(foreign(lead))[:60]}”"
    if len("".join(foreign(trail))) > max_extra_chars:
        return False, f"extra words at the end: “{' '.join(foreign(trail))[:60]}”"
    if covered < 0.85:
        return False, f"parts of the script are missing ({int(covered * 100)}% spoken)"
    return True, ""

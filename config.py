"""All settings come from environment variables (GitHub Secrets / Variables)."""
import os
from zoneinfo import ZoneInfo


def env(name, default=None):
    value = os.environ.get(name, "").strip()
    return value or default


TELEGRAM_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
# Optional "doorbell" (Cloudflare Worker) for fast replies. Leave empty to use normal polling.
DOORBELL_URL = (env("DOORBELL_URL") or "").rstrip("/")
DOORBELL_KEY = env("DOORBELL_KEY")

GEMINI_API_KEY = env("GEMINI_API_KEY")
# Claude (paid, optional): writes the scripts and does the editor-in-chief review when a key is set; Gemini otherwise
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-sonnet-5-5")
# Owner, 2026-10-10: "Sonnet is costly. Stay free" -> Claude is off; only free Gemini is used.
# Set USE_CLAUDE=1 in the workflow env to turn it back on (ask the owner first: it costs money).
USE_CLAUDE = env("USE_CLAUDE", "") == "1"
# Fish Audio: the owner's cloned voice (paid per use). Without a key, or when credits run out, the regular voices are used.
FISH_API_KEY = env("FISH_API_KEY")
FISH_VOICE_ID = env("FISH_VOICE_ID", "")  # optional; normally set with /myvoice in Telegram
FISH_MODEL = env("FISH_MODEL", "s2-pro")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.6-flash")
# Used only when the main model is overloaded (503)
GEMINI_FALLBACK_MODEL = env("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")

PEXELS_API_KEY = env("PEXELS_API_KEY")

# Free AI images: Cloudflare Workers AI (recommended), falls back to Pollinations.ai (no key)
CF_ACCOUNT_ID = env("CF_ACCOUNT_ID")
CF_API_TOKEN = env("CF_API_TOKEN")

IG_USER_ID = env("IG_USER_ID")
IG_ACCESS_TOKEN = env("IG_ACCESS_TOKEN")
IG_GRAPH_BASE = env("IG_GRAPH_BASE", "https://graph.facebook.com/v26.0").rstrip("/")

# Optional WhatsApp alerts (free, via callmebot.com)
WHATSAPP_PHONE = env("WHATSAPP_PHONE")          # with country code, e.g. +919876543210
CALLMEBOT_API_KEY = env("CALLMEBOT_API_KEY")

# AI voice-over (used when you reply "ok" instead of sending a voice note)
VOICES_MALE = env("VOICES_MALE", "en-US-AndrewMultilingualNeural,en-US-BrianMultilingualNeural").split(",")
VOICES_FEMALE = env("VOICES_FEMALE", "en-US-AvaMultilingualNeural,en-US-EmmaMultilingualNeural").split(",")
TTS_RATE = env("TTS_RATE", "+6%")
# Google (Gemini) voices, used alternately with the Microsoft ones
GOOGLE_VOICES_MALE = env("GOOGLE_VOICES_MALE", "Charon,Puck,Orus").split(",")
GOOGLE_VOICES_FEMALE = env("GOOGLE_VOICES_FEMALE", "Kore,Aoede,Zephyr").split(",")
GEMINI_TTS_MODEL = env("GEMINI_TTS_MODEL", "")  # empty = pick the newest available TTS model automatically                      # speaking speed
KOKORO_MALE = env("KOKORO_MALE", "am_michael")         # backup voices if Edge voices fail
KOKORO_FEMALE = env("KOKORO_FEMALE", "af_heart")
AI_VOICE_NOTE = env("AI_VOICE_NOTE", "")  # optional line added to captions of AI-voiced reels (off)

TIMEZONE = ZoneInfo(env("TIMEZONE", "Asia/Kolkata"))
AUTO_PICK_HOURS = float(env("AUTO_PICK_HOURS", "0.5"))
# When the bot sends you fresh stories (your local time) — one reel per time
OFFER_TIMES = [t.strip() for t in env("OFFER_TIMES", "07:00,09:30,12:00,14:30,17:00,19:30").split(",") if t.strip()]
# Autopilot: if you don't reply, use the AI voice / schedule the reel after this many hours
AUTO_APPROVE_HOURS = float(env("AUTO_APPROVE_HOURS", "0.5"))
# Times (your local time) when finished reels get posted
POST_TIMES = [t.strip() for t in env("POST_TIMES", "09:00,11:30,14:00,16:30,19:00,21:30").split(",") if t.strip()]
HANDLE = env("INSTAGRAM_HANDLE", "")
SPOKEN_NAME = env("SPOKEN_NAME", "Gradient Daily")  # how the voice-over says your @handle
NICHE = env("CHANNEL_NICHE", "daily AI news, trends and advancements, for a global audience (US, Europe, India)")

FONT_PATH = env("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_NAME = env("FONT_NAME", "DejaVu Sans")

WORK_DIR = "work"
STATE_FILE = "state.json"

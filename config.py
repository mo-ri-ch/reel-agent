"""All settings come from environment variables (GitHub Secrets / Variables)."""
import os
from zoneinfo import ZoneInfo


def env(name, default=None):
    value = os.environ.get(name, "").strip()
    return value or default


TELEGRAM_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")

GEMINI_API_KEY = env("GEMINI_API_KEY")
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
VOICES_MALE = env("VOICES_MALE", "en-IN-PrabhatNeural,en-GB-RyanNeural,en-US-GuyNeural").split(",")
VOICES_FEMALE = env("VOICES_FEMALE", "en-IN-NeerjaNeural,en-IN-NeerjaExpressiveNeural,en-GB-SoniaNeural").split(",")
TTS_RATE = env("TTS_RATE", "+8%")                      # speaking speed
KOKORO_MALE = env("KOKORO_MALE", "am_michael")         # backup voices if Edge voices fail
KOKORO_FEMALE = env("KOKORO_FEMALE", "af_heart")
AI_VOICE_NOTE = env("AI_VOICE_NOTE", "🎙️ Voiceover generated with AI")  # added to captions of AI-voiced reels

TIMEZONE = ZoneInfo(env("TIMEZONE", "Asia/Kolkata"))
AUTO_PICK_HOURS = float(env("AUTO_PICK_HOURS", "2"))
# Times (your local time) when finished reels get posted
POST_TIMES = [t.strip() for t in env("POST_TIMES", "13:00,19:30").split(",") if t.strip()]
HANDLE = env("INSTAGRAM_HANDLE", "")
NICHE = env("CHANNEL_NICHE", "daily AI news, trends and advancements")

FONT_PATH = env("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_NAME = env("FONT_NAME", "DejaVu Sans")

WORK_DIR = "work"
STATE_FILE = "state.json"

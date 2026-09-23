"""Optional WhatsApp alerts via the free CallMeBot service. Never breaks the agent if it fails."""
import urllib.parse

import requests

from config import CALLMEBOT_API_KEY, WHATSAPP_PHONE


def enabled():
    return bool(WHATSAPP_PHONE and CALLMEBOT_API_KEY)


def alert(text, raise_errors=False):
    if not enabled():
        return False
    try:
        url = ("https://api.callmebot.com/whatsapp.php?phone=" + urllib.parse.quote(WHATSAPP_PHONE) +
               "&text=" + urllib.parse.quote(text[:900]) + "&apikey=" + urllib.parse.quote(CALLMEBOT_API_KEY))
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or "error" in r.text.lower()[:300]:
            raise RuntimeError(r.text[:200])
        return True
    except Exception as e:
        print(f"WhatsApp alert failed: {e}")
        if raise_errors:
            raise
        return False

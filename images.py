"""Free AI image generation. Tries Cloudflare Workers AI first, then Pollinations.ai."""
import base64
import io
import urllib.parse

import requests
from PIL import Image

from config import CF_ACCOUNT_ID, CF_API_TOKEN

STYLE = ", cinematic lighting, highly detailed, vibrant colors, vertical composition, no text, no watermark"


def _cloudflare(prompt):
    if not (CF_ACCOUNT_ID and CF_API_TOKEN):
        return None
    url = (f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
           "/ai/run/@cf/black-forest-labs/flux-1-schnell")
    r = requests.post(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
                      json={"prompt": prompt[:2000], "steps": 6}, timeout=120)
    r.raise_for_status()
    return base64.b64decode(r.json()["result"]["image"])


def _pollinations(prompt):
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900]) +
           "?width=1080&height=1920&nologo=true&model=flux")
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError("no image returned")
    return r.content


def generate(prompt):
    """Returns a PIL image, or None if every free service failed."""
    for service in (_cloudflare, _pollinations):
        try:
            data = service(prompt + STYLE)
            if data:
                return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            print(f"{service.__name__} image failed: {e}")
    return None

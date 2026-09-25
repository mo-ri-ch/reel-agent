"""Collects fresh AI headlines from free RSS feeds."""
import html
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.artificialintelligence-news.com/feed/",
    "https://huggingface.co/blog/feed.xml",
    "https://blog.google/technology/ai/rss/",
    "https://openai.com/news/rss.xml",
    "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-IN&gl=IN&ceid=IN:en",
]


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_headlines(max_age_hours=36, limit=40):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items, seen = [], set()
    for url in FEEDS:
        try:
            resp = requests.get(url, headers=UA, timeout=20)
            feed = feedparser.parse(resp.content)
        except Exception as e:
            print(f"Feed failed: {url} ({e})")
            continue
        source = _clean(feed.feed.get("title", "")) or url.split("/")[2]
        for e in feed.entries[:25]:
            t = e.get("published_parsed") or e.get("updated_parsed")
            published = datetime(*t[:6], tzinfo=timezone.utc) if t else None
            if published and published < cutoff:
                continue
            title = _clean(e.get("title"))
            src = source
            if "news.google.com" in url and " - " in title:
                title, src = title.rsplit(" - ", 1)  # Google News puts the publisher at the end
            key = re.sub(r"[^a-z0-9]", "", title.lower())[:50]
            if not title or key in seen:
                continue
            seen.add(key)
            items.append({
                "title": title,
                "link": e.get("link", ""),
                "summary": _clean(e.get("summary"))[:400],
                "source": src,
                "published": published.isoformat() if published else "",
            })
    items.sort(key=lambda x: x["published"], reverse=True)
    return items[:limit]


def og_image(link):
    """Finds the article's main image (used on the reel's title card)."""
    if not link or "news.google.com" in link:
        return None
    try:
        page = requests.get(link, headers=UA, timeout=15).text[:400000]
    except Exception:
        return None
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)',
    ]
    for pat in patterns:
        m = re.search(pat, page, re.I)
        if m:
            return html.unescape(m.group(1))
    return None


# ---------------------------------------------------------------- repeat detection
STOP = set("""a an the and or but of to in on for with at by from as is are was were be been it its this that these
those how why what when who new just now will can could would may might says said say after over into about than more
most your you our their his her they them we us not no yes vs via amid ai artificial intelligence first launches launch
launched announces announced unveils unveiled update updates report reports gets get big latest hits crosses reaches
tops passes surpasses""".split())


def keywords(title):
    t = title.lower().replace("$", " ").replace("₹", " ")
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(million|mn)\b", r"\1m", t)       # "600 million" → "600m"
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(billion|bn)\b", r"\1b", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(trillion)\b", r"\1t", t)
    words = re.findall(r"[a-z0-9][a-z0-9.\-]*", t)
    return {w.strip(".-") for w in words if len(w.strip(".-")) > 2 and w.strip(".-") not in STOP}


def same_story(a, b):
    """True when two headlines are clearly about the same news."""
    import difflib
    ka, kb = keywords(a), keywords(b)
    if not ka or not kb:
        return False
    shared = ka & kb
    if len(shared) >= 3 or (len(shared) >= 2 and len(shared) / min(len(ka), len(kb)) >= 0.5):
        return True
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.72


def recent_match(title, past):
    """The first recent headline that's the same story, or None."""
    return next((p for p in past if same_story(title, p)), None)


def dedupe(headlines, past):
    """Drops headlines already covered recently, and repeats of the same story within the list."""
    kept = []
    for h in headlines:
        if recent_match(h["title"], past) or recent_match(h["title"], [k["title"] for k in kept]):
            continue
        kept.append(h)
    return kept

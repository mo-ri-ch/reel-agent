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
            key = re.sub(r"[^a-z0-9]", "", title.lower())[:50]
            if not title or key in seen:
                continue
            seen.add(key)
            items.append({
                "title": title,
                "link": e.get("link", ""),
                "summary": _clean(e.get("summary"))[:400],
                "source": source,
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

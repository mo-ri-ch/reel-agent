"""Collects fresh AI headlines from free RSS feeds."""
import html
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

FEEDS = [
    # tech news
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/ai/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    # official company / lab announcements
    "https://openai.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://blogs.nvidia.com/feed/",
    # India
    "https://inc42.com/feed/",
    # broad coverage (many outlets)
    "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-IN&gl=IN&ceid=IN:en",
    # sites that block direct access, reached through Google News instead
    "https://news.google.com/rss/search?q=(site:venturebeat.com+OR+site:analyticsindiamag.com+OR+site:artificialintelligence-news.com)+AI+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
    # new AI products of the day
    "https://www.producthunt.com/feed?category=artificial-intelligence",
]
AI_WORDS = re.compile(r"(?i)\b(ai|a\.i\.|llm|llms|gpt|chatgpt|openai|anthropic|claude|gemini|deepmind|llama|mistral|"
                      r"grok|copilot|nvidia|model|models|agent|agents|agi|neural|diffusion|transformer|sarvam|"
                      r"perplexity|hugging ?face|deepseek|qwen|robot|robotics|machine learning|chatbot)\b")
REDDIT_SUBS = ["LocalLLaMA", "OpenAI", "singularity", "artificial", "MachineLearning", "ClaudeAI", "Bard"]
LAST_REPORT = {}  # headlines found per source on the last fetch (for checking the feeds)


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _hacker_news(cutoff):
    """AI stories on Hacker News' front page, with their points (a strong "this is trending" signal)."""
    out = []
    try:
        r = requests.get("https://hn.algolia.com/api/v1/search", timeout=20,
                         params={"tags": "front_page", "hitsPerPage": 60})
        for h in r.json().get("hits", []):
            title, url = h.get("title") or "", h.get("url") or ""
            when = datetime.fromtimestamp(h.get("created_at_i", 0), tz=timezone.utc)
            if url and when >= cutoff and AI_WORDS.search(title):
                out.append({"title": title, "link": url, "summary": "", "source": url.split("/")[2].replace("www.", ""),
                            "published": when.isoformat(), "buzz": f"Hacker News {h.get('points', 0)} points"})
    except Exception as e:
        print(f"Hacker News failed: {e}")
    return out


def _reddit(cutoff):
    """Top posts of the day in AI communities (first place many releases and leaks show up), with upvotes."""
    out = []
    for sub in REDDIT_SUBS:
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "day", "limit": 12}, timeout=20,
                             headers={"User-Agent": "GradientDailyNewsBot/1.0 (news digest; contact via github mo-ri-ch)"})
            if r.status_code != 200:
                rss = requests.get(f"https://www.reddit.com/r/{sub}/top/.rss", params={"t": "day"}, timeout=20,
                                   headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GradientDailyNewsBot/1.0"})
                if rss.status_code != 200:
                    LAST_REPORT["Reddit"] = f"blocked (HTTP {r.status_code}/{rss.status_code})"
                    continue
                for e in feedparser.parse(rss.content).entries[:5]:  # RSS has no upvotes: top 5 of the day only
                    t = e.get("updated_parsed") or e.get("published_parsed")
                    when = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
                    if when >= cutoff:
                        out.append({"title": _clean(e.get("title", "")), "link": e.get("link", ""), "summary": "",
                                    "source": f"r/{sub}", "published": when.isoformat(), "buzz": f"top of r/{sub} today"})
                continue
            for c in r.json().get("data", {}).get("children", []):
                p = c.get("data", {})
                when = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
                score = p.get("score", 0)
                if when < cutoff or score < 150 or p.get("stickied") or p.get("over_18"):
                    continue
                link = p.get("url_overridden_by_dest") or ""
                if not link or "reddit.com" in link or "redd.it" in link or link.endswith((".jpg", ".png", ".gif")):
                    link = "https://www.reddit.com" + p.get("permalink", "")  # a text post: link to the discussion
                out.append({"title": _clean(p.get("title", "")), "link": link,
                            "summary": _clean(p.get("selftext", ""))[:400], "source": f"r/{sub}",
                            "published": when.isoformat(), "buzz": f"r/{sub} {score} upvotes"})
        except Exception as e:
            print(f"Reddit r/{sub} failed: {e}")
    return out


def fetch_headlines(max_age_hours=36, limit=60):
    """Fresh AI headlines from news sites, official blogs, Google News, Product Hunt, Hacker News and Reddit."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items, seen = [], set()
    LAST_REPORT.clear()

    def add(item, label):
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:50]
        if item["title"] and key not in seen:
            seen.add(key)
            items.append(item)
            prev = LAST_REPORT.get(label, 0)
            LAST_REPORT[label] = (prev if isinstance(prev, int) else 0) + 1

    for url in FEEDS:
        label = "Google News (VentureBeat, AIM, AI News)" if "site:" in url else url.split("/")[2].replace("www.", "")
        LAST_REPORT.setdefault(label, 0)
        try:
            resp = requests.get(url, headers=UA, timeout=20)
            if resp.status_code != 200:
                LAST_REPORT[label] = f"blocked (HTTP {resp.status_code})"
                continue
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                LAST_REPORT[label] = "empty feed"
                continue
        except Exception as e:
            print(f"Feed failed: {url} ({e})")
            LAST_REPORT[label] = f"failed ({type(e).__name__})"
            continue
        source = _clean(feed.feed.get("title", "")) or label
        broad = any(k in url for k in ("nvidia", "microsoft", "inc42", "producthunt", "technologyreview"))
        for e in feed.entries[:25]:
            t = e.get("published_parsed") or e.get("updated_parsed")
            published = datetime(*t[:6], tzinfo=timezone.utc) if t else None
            if published and published < cutoff:
                continue
            title = _clean(e.get("title"))
            src = source
            if "news.google.com" in url and " - " in title:
                title, src = title.rsplit(" - ", 1)  # Google News puts the publisher at the end
            summary = _clean(e.get("summary"))[:400]
            if broad and not AI_WORDS.search(f"{title} {summary}"):
                continue  # general feeds: keep only AI stories
            add({"title": title, "link": e.get("link", ""), "summary": summary, "source": src,
                 "published": published.isoformat() if published else "",
                 **({"buzz": "Product Hunt launch"} if "producthunt" in url else {})}, label)
    for item in _hacker_news(cutoff):
        add(item, "Hacker News")
    for item in _reddit(cutoff):
        add(item, "Reddit")
    items.sort(key=lambda x: x["published"], reverse=True)
    print("Headlines per source:", LAST_REPORT)
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


def topic_from_url(url):
    """Title, summary, outlet and date of an article link you send, so it can become a reel."""
    from urllib.parse import urlparse
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        page, final = r.text[:600000], r.url
    except Exception as e:
        raise RuntimeError(f"couldn't open that link ({e})")

    def meta(*names):
        for n in names:
            for pat in (rf'<meta[^>]+(?:property|name)=["\']{n}["\'][^>]*content=["\']([^"\']+)',
                        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{n}["\']'):
                m = re.search(pat, page, re.I)
                if m:
                    return html.unescape(m.group(1)).strip()
        return ""
    title = meta("og:title", "twitter:title") or _clean((re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
                                                          or [None, ""])[1])
    if not title:
        raise RuntimeError("couldn't read a headline from that link")
    domain = urlparse(final).netloc.replace("www.", "")
    return {"title": title[:200], "link": final, "summary": meta("og:description", "description", "twitter:description")[:400],
            "source": meta("og:site_name") or domain, "published": meta("article:published_time", "og:updated_time")}

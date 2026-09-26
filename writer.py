"""Uses the free Gemini API to pick stories and write scripts."""
import json
import re
import time

import requests

from config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, HANDLE, NICHE
from state import now


SEARCH_USED = False  # did the last ask() really use Google Search?


def ask(prompt, search=False, temperature=0.8, json_mode=False, light=False):
    """light=True: small jobs (picking stories/clips) go to the lighter model first, saving the main model's quota."""
    global SEARCH_USED
    SEARCH_USED = False
    models = [GEMINI_MODEL] + ([GEMINI_FALLBACK_MODEL] if GEMINI_FALLBACK_MODEL != GEMINI_MODEL else [])
    if light:
        models.reverse()
    last = ""
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        parts = prompt if isinstance(prompt, list) else [{"text": prompt}]
        body = {"contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": temperature}}
        if search:
            body["tools"] = [{"google_search": {}}]
        elif json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        overloaded = 0
        for attempt in range(5):
            r = requests.post(url, headers={"x-goog-api-key": GEMINI_API_KEY}, json=body, timeout=180)
            if r.status_code in (400, 403, 429) and "tools" in body:
                # Google Search isn't available (or its free quota is used up): continue without it
                print(f"Search unavailable ({r.status_code}), writing without it")
                body.pop("tools")
                if json_mode:
                    body["generationConfig"]["responseMimeType"] = "application/json"
                continue
            if r.status_code in (500, 503):
                overloaded += 1
                last = f"{model} is overloaded right now"
                if overloaded >= 2:
                    break  # try the backup model
                time.sleep(15)
                continue
            if r.status_code == 429:
                last = f"{model}: free quota used up for now"
                if attempt >= 1 or "PerDay" in r.text or "per day" in r.text.lower():
                    break  # daily limit won't reset in minutes: try the other model instead of waiting
                time.sleep(12)
                continue
            if r.status_code == 404 and model != GEMINI_MODEL:
                break  # backup model name not available
            if r.status_code != 200:
                raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if text.strip():
                if model != GEMINI_MODEL:
                    print(f"Used backup model {model}")
                SEARCH_USED = "tools" in body
                return text
            last = f"empty reply (finishReason={cand.get('finishReason')})"
            print("Gemini " + last)
            if "tools" in body:  # search sometimes returns nothing: retry without it
                body.pop("tools")
                if json_mode:
                    body["generationConfig"]["responseMimeType"] = "application/json"
        print(f"Moving on from {model}: {last}")
    raise RuntimeError(f"Gemini didn't give a usable reply, please try again in a few minutes. {last}")


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start == -1 or end == -1:
        raise ValueError(f"No JSON in model reply: {text[:200]}")
    return json.loads(text[start:end + 1])


def pick_top(headlines, history, count=3):
    listing = "\n".join(f"{i}. [{h['source']}] {h['title']}" + (f" ({h['buzz']})" if h.get("buzz") else "") +
                        f" — {h['summary'][:200]}" for i, h in enumerate(headlines, 1))
    recent = "\n- ".join([""] + list(dict.fromkeys(history))[-40:]) or "none"
    prompt = f"""You run an Instagram Reels page about {NICHE} for a general audience.
From the headlines below, pick the {count} stories that would make the most engaging 40-second reels today:
big launches, surprising capabilities, tools people can actually use, major industry moves.
Favour BREAKING stories that are clearly blowing up (high Hacker News points / Reddit upvotes in brackets) — but a Reddit
post is only a lead: prefer stories that are also confirmed by a news site or an official announcement.
Skip minor funding news, opinion pieces and duplicates of each other.
NEVER pick a story we already covered, even if the headline is worded differently, comes from another outlet, or
names a person instead of their company (e.g. "Mustafa Suleyman" = Microsoft's AI chief). Recently covered:{recent}

Headlines:
{listing}

Return ONLY JSON: {{"picks": [{{"n": <headline number>, "angle": "<one short line: why viewers will care>"}}]}}"""
    try:
        picks = parse_json(ask(prompt, temperature=0.4, json_mode=True, light=True))["picks"]
        chosen = []
        for p in picks:
            n = int(p["n"])
            if 1 <= n <= len(headlines):
                chosen.append({**headlines[n - 1], "angle": p.get("angle", "")})
        if chosen:
            return chosen[:count]
    except Exception as e:
        print(f"Picking failed, using newest headlines: {e}")
    return [{**h, "angle": ""} for h in headlines[:count]]


RULES = """Write a 25-40 second Instagram Reel about AI, read aloud by a voice-over.

SCRIPT
- 70 to 100 words. Conversational, like explaining to a smart friend. Short punchy sentences (max ~15 words), contractions, one idea per sentence.
- Line 1 is the HOOK (under 12 words). Stop the scroll with ONE of: a surprising fact or number, a bold claim,
  "you" framing about the viewer's life, or a question they can't ignore.
  Good hooks: "Your next coworker might not be human." / "Google just made search ten times faster."
  Never start with: "Hey guys", "Did you know", "In today's video", "Breaking news", "Imagine".
- Then: what happened → why it's surprising or matters → what it means for the viewer.
- BE SPECIFIC. Every script must name the concrete details: WHO (the company, lab, university or research team),
  WHAT exactly (the product or model name, the journal or paper, what it actually does), WHERE (country or city)
  and, when known, a real number or date from the source. Use Google Search to find the original source first.
  Never write vague filler like "recent research", "a new study", "experts say", "scientists", "tech giants",
  "a major company" or "this technology" without naming who or what it is. NEVER say "a developer", "a startup",
  "a team" or "an engineer": say who — e.g. not "a developer from Kerala" but "Kochi developer <full name>".
  Every named person must get a "person" beat (their name + role) so their photo is shown. If a detail can't be verified, leave it
  out rather than inventing it.
- End with one short question to spark comments. Do NOT add a "follow us" line or mention any @handle.
- Banned words: game-changer, revolutionize, revolutionary, cutting-edge, unleash, delve, landscape, buckle up,
  "the future is here", "in today's world", "stay tuned", "mind-blowing".
- No emojis, hashtags, stage directions or brackets in the lines. Write numbers the way they're said ("ten times", "two billion").

VISUALS — split the script into 5 to 8 beats (one or two sentences each). Every beat gets ONE visual.
Prefer REAL and SPECIFIC visuals over generic ones:
- a line about a named PRODUCT, APP, AI MODEL, DEVICE or COMPANY ANNOUNCEMENT → "official" (the real product images);
- a line that names or quotes a PERSON ("Sam Altman says…", "Lovable co-founder Fabian Hedin…") → ALWAYS "person";
- a named university, lab, building or place → "photo";
- where the news comes from (a journal, paper or announcement) → "source".
NEVER use a product or company name as a stock "query" or image "prompt": names are not literal ("Horizon Studio" is
Meta software, not a horizon; "Gemini" is a Google AI, not a star sign; "Apple" is a company, not fruit).
- "clip": real stock video. Use for things footage shows well: people using phones or laptops, offices, city streets,
  data centers, robots, coding screens, doctors, students. "query" = 2-4 concrete words ("woman talking to phone", not "AI innovation").
- "image": AI-generated picture for specific or futuristic ideas stock can't show. "prompt" = vivid cinematic vertical scene,
  no text, no logos, no real people's faces.
- "official": the real images of a named product or company, taken from its official page and the news article.
  "entity" = exact name ("Meta Horizon Studio"), "url" = the official product/announcement page if you know it,
  "domain" = the company's website ("meta.com").
- "person": the person's real photo with their name and role underneath. "name" = full name exactly as written in
  the source, "role" = short designation ("CEO, OpenAI", "Co-founder, Lovable"), "x" = their X/Twitter handle
  without @ if you know it (else ""), "url" = a page that shows them (company team page, profile) if you know one.
- "photo": a real photo from Wikipedia/Wikimedia Commons. "entity" = the exact thing to show, as its Wikipedia title
  would be: "Stanford University", "Jensen Huang", "Nvidia headquarters", "Dassault Rafale", "CERN". Use it often.
- "source": a card showing the source. "outlet" = journal, publisher or company ("Nature Medicine", "Google DeepMind"),
  "domain" = its website ("nature.com"), "headline" = the paper or announcement title in under 12 words.
- "stat": a big number on screen, ONLY for a number stated in the news story or your search results (at most 2).
  Never invent, round up or estimate a number. If unsure, use "clip" or "image" instead. "big" = "600M", "small" = "weekly users".
Mix the types; don't use the same type more than twice in a row.
For every beat, list in "brands" the companies or AI products NAMED in that line (e.g. OpenAI, Google, Meta, Nvidia,
ChatGPT, Gemini, Claude), with their main website domain. Use [] when none are named. Never add brands that aren't said.

Return ONLY JSON:
{{"title": "on-screen headline, max 60 characters",
 "hook_text": "3 to 6 punchy words shown big on the first screen",
 "beats": [{{"line": "spoken sentence(s)", "visual": "clip", "query": "..."}},
           {{"line": "...", "visual": "image", "prompt": "..."}},
           {{"line": "...", "visual": "person", "name": "Sam Altman", "role": "CEO, OpenAI", "x": "sama", "url": ""}},
           {{"line": "...", "visual": "photo", "entity": "Stanford University"}},
           {{"line": "...", "visual": "official", "entity": "Meta Horizon Studio", "url": "https://...", "domain": "meta.com"}},
           {{"line": "...", "visual": "source", "outlet": "Nature Medicine", "domain": "nature.com", "headline": "..."}},
           {{"line": "...", "visual": "stat", "big": "...", "small": "...",
             "brands": [{{"name": "OpenAI", "domain": "openai.com"}}]}}],
 "caption": "2-3 sentence Instagram caption ending with a question",
 "hashtags": ["10 to 12 relevant hashtags without #"],
 "sources": ["URLs you used"]}}"""


def normalize_draft(draft, topic):
    """Makes sure the draft has clean beats, script and all the fields the rest of the agent needs."""
    if isinstance(draft, list):
        draft = draft[0] if draft else {}
    beats = []
    for b in draft.get("beats") or []:
        if not isinstance(b, dict) or not str(b.get("line", "")).strip():
            continue
        kind = b.get("visual") if b.get("visual") in ("clip", "image", "stat", "photo", "source", "official",
                                                       "person") else "clip"
        beats.append({"line": str(b["line"]).strip(), "visual": kind,
                      "query": str(b.get("query") or "technology"), "prompt": str(b.get("prompt") or ""),
                      "big": str(b.get("big") or "")[:10], "small": str(b.get("small") or "")[:40],
                      "entity": str(b.get("entity") or "")[:80], "outlet": str(b.get("outlet") or "")[:60],
                      "domain": str(b.get("domain") or "")[:60], "headline": str(b.get("headline") or "")[:120],
                      "url": str(b.get("url") or "")[:300],
                      "name": str(b.get("name") or "")[:60], "role": str(b.get("role") or "")[:60],
                      "x": re.sub(r"[^A-Za-z0-9_]", "", str(b.get("x") or ""))[:30],
                      "brands": [{"name": str(x.get("name", ""))[:30], "domain": str(x.get("domain", ""))[:60]}
                                 for x in (b.get("brands") or []) if isinstance(x, dict) and x.get("name")][:2]})
    if not beats:  # older-style reply: build beats from the script lines
        script = draft.get("script", "")
        lines = script if isinstance(script, list) else str(script).splitlines()
        keywords = draft.get("keywords") or ["artificial intelligence", "technology", "data center"]
        beats = [{"line": l.strip(), "visual": "clip", "query": keywords[i % len(keywords)], "prompt": "",
                  "big": "", "small": ""} for i, l in enumerate(lines) if l.strip()]
    for b in beats:
        if b["visual"] == "stat" and not b["big"]:
            b["visual"] = "clip"
        if b["visual"] in ("photo", "official") and not b["entity"]:
            b["visual"] = "clip"
        if b["visual"] == "person" and not b["name"]:
            b["visual"] = "clip"
        if b["visual"] == "source" and not (b["outlet"] or b["headline"]):
            b["visual"] = "clip"
        if b["visual"] == "image" and not b["prompt"]:
            b["prompt"] = f"a cinematic illustration of: {b['line']}"
    draft["beats"] = beats
    draft["script"] = "\n".join(b["line"] for b in beats).strip()
    draft["title"] = str(draft.get("title") or topic["title"])[:70]
    draft["hook_text"] = str(draft.get("hook_text") or draft["title"])[:60]
    draft["caption"] = str(draft.get("caption", ""))
    draft["hashtags"] = [str(h).lstrip("#").replace(" ", "") for h in draft.get("hashtags", [])][:15]
    draft["keywords"] = [b["query"] for b in beats if b["visual"] == "clip"][:6] or ["technology"]
    draft["image_prompts"] = [b["prompt"] for b in beats if b["visual"] == "image"][:3]
    draft["sources"] = draft.get("sources", [])
    if not draft["script"]:
        raise RuntimeError("The script came back empty, please try again.")
    return draft


def choose_clips(beats_with_options):
    """Shows Gemini thumbnails of candidate stock clips and lets it pick the ones that fit each line.
    beats_with_options: [{"line": str, "options": [jpeg_bytes, ...]}]  →  {beat_index: [option_index, ...]}"""
    import base64
    parts = [{"text": "You are editing an Instagram Reel. For each spoken line below, look at the numbered stock "
                      "video thumbnails and pick the ones that visually fit the line. Prefer clips that match the "
                      "meaning; avoid generic office meetings unless the line is about one. A loosely related but "
                      "good-looking clip is fine; only reject all options if every one would look wrong or misleading."}]
    for bi, b in enumerate(beats_with_options):
        parts.append({"text": f"\nLINE {bi + 1}: \"{b['line']}\""})
        for ci, img in enumerate(b["options"]):
            parts.append({"text": f"Option {bi + 1}.{ci + 1}:"})
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
    parts.append({"text": '\nReturn ONLY JSON like {"1": [2, 1], "2": [3], "3": []} — for each line, the option '
                          "numbers that fit, best first. Use [] if none fit."})
    raw = parse_json(ask(parts, temperature=0.2, json_mode=True, light=True))
    return {int(k) - 1: [int(x) - 1 for x in v if str(x).lstrip("-").isdigit()] for k, v in raw.items()
            if str(k).isdigit() and isinstance(v, list)}


def write_script(topic, previous=None, instruction=None):
    rules = RULES.format(handle=f" (@{HANDLE.lstrip('@')})" if HANDLE else "")
    today = now().strftime("%d %B %Y")
    if topic.get("custom"):
        about = (f'The creator chose this topic: "{topic["title"]}".\n'
                 "Use Google Search to get accurate, up-to-date facts about it.")
    else:
        about = (f"Today's news story:\nTitle: {topic['title']}\nSource: {topic.get('source', '')}\n"
                 f"Link: {topic.get('link', '')}\nSummary: {topic.get('summary', '')}\n"
                 "Use Google Search to verify the details and find the latest facts.")
    prompt = f"Today is {today}.\n{about}\n\n{rules}"
    if previous and instruction:
        prompt += (f"\n\nHere is the current version:\n{json.dumps(previous, ensure_ascii=False)}\n"
                   f'Revise it based on the creator\'s feedback: "{instruction}". Keep all the rules above.')
    try:
        draft = parse_json(ask(prompt, search=True, json_mode=True))
    except ValueError:
        # the search-grounded reply wasn't clean JSON: ask again in strict JSON mode
        draft = parse_json(ask(prompt, json_mode=True))
    return normalize_draft(draft, topic)


def draft_from_own_script(text, topic=None):
    """Builds a draft from a script you wrote yourself (no Gemini needed)."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    title = (topic or {}).get("title") or lines[0]
    queries = ["person using smartphone", "data center servers", "coding on laptop", "robot arm", "city at night"]
    beats = [{"line": l, "visual": "image" if i % 3 == 1 else "clip", "query": queries[i % len(queries)],
              "prompt": f"a cinematic futuristic scene illustrating: {l}"} for i, l in enumerate(lines)]
    return normalize_draft({
        "title": title[:70], "hook_text": lines[0][:60], "beats": beats,
        "caption": " ".join(lines[:2])[:300] + "\n\nWhat do you think? Tell me in the comments 👇",
        "hashtags": ["ai", "artificialintelligence", "ainews", "tech", "technology", "chatgpt",
                     "openai", "futuretech", "machinelearning", "techindia"],
    }, {"title": title})


# ---------------------------------------------------------------- quality checks
def article_text(url, limit=5000):
    """Readable text of the source article (so its reporting counts as a source)."""
    import html as html_lib
    if url and "news.google." in url:
        import news
        url = news.real_url(url)
    if not url or "news.google." in url:
        return ""
    try:
        page = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                                                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}).text
    except Exception:
        return ""
    page = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", page)
    paras = [html_lib.unescape(re.sub(r"<[^>]+>", " ", p)) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", page)]
    text = " ".join(re.sub(r"\s+", " ", p).strip() for p in paras if len(p) > 60)
    return text[:limit]


def _norm(t):
    t = (t or "").lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9$%.' -]", " ", re.sub(r"\s+", " ", t)).strip()


def evidence_found(quote, text):
    """True if the quote really appears in the text (small differences in punctuation are allowed)."""
    q, t = _norm(quote), _norm(text)
    if len(q) < 12 or not t:
        return False
    if q in t:
        return True
    words = q.split()
    windows = [" ".join(words[i:i + 7]) for i in range(0, max(1, len(words) - 6), 3)]
    hits = sum(1 for w in windows if w in t)
    return len(words) >= 7 and hits >= max(1, len(windows) * 0.6)


def fact_check(draft, topic):
    """Evidence-based fact check. Every factual claim must come with an exact quote from a source, and the
    agent itself confirms the quote is really on that page. Returns (draft, status, notes).
    status: "ok" (every claim proven), "unsure" (something wrong or unproven), "skipped" (couldn't run)."""
    corpus = {}
    for u in [topic.get("link", ""), *(topic.get("research_sources") or [])][:3]:
        txt = article_text(u, 30000) if u else ""
        if txt:
            corpus[u] = txt
    beats = [{"beat": i + 1, "line": b["line"], **({"person": b.get("name"), "role": b.get("role")}
                                                   if b.get("visual") == "person" else {}),
              **({"number": b.get("big"), "label": b.get("small")} if b.get("visual") == "stat" else {})}
             for i, b in enumerate(draft.get("beats", []))]
    sources_txt = "\n\n".join(f"SOURCE {u}:\n{t[:12000]}" for u, t in corpus.items()) or "(no source text available)"
    prompt = f"""Today is {now().strftime("%d %B %Y")}. You are a strict fact-checker for a news page.
Story: {topic.get("title", "")}

{sources_txt}

Script beats:
{json.dumps(beats, ensure_ascii=False)}

List EVERY factual claim in the beats (names, roles, companies, product names, numbers, dates, places, who said or
did what, what a product does). Questions and opinions are not claims.
For each claim give EVIDENCE: a sentence copied WORD FOR WORD from one of the SOURCE texts above, or from a web page
you found with Google Search (then give that page's URL). Never paraphrase the evidence. If you can't find exact
evidence, mark the claim "unsupported". If a source says something different, mark it "contradicted".
Return ONLY JSON:
{{"claims": [{{"beat": <number>, "claim": "...", "status": "supported" | "unsupported" | "contradicted",
  "evidence": "exact quote (max 40 words)", "url": "the source URL the quote is from", "correct": "the right fact, if contradicted"}}]}}"""
    try:
        res = parse_json(ask(prompt, search=True, temperature=0.0, json_mode=True))
    except Exception as e:
        print(f"Fact check skipped: {e}")
        return draft, "skipped", ["the fact check couldn't run (Gemini unavailable)"]
    claims = [c for c in (res.get("claims") or []) if isinstance(c, dict) and c.get("claim")]
    if not claims:
        return draft, "unsure", ["the fact check didn't return any claims to verify"]
    notes = []
    for c in claims:
        status = str(c.get("status", "")).lower()
        tag = f"Beat {c.get('beat', '?')}: “{str(c['claim'])[:90]}”"
        if status == "contradicted":
            notes.append(f"{tag} is wrong" + (f" → {c['correct']}" if c.get("correct") else ""))
            continue
        if status != "supported":
            notes.append(f"{tag} — no source found for this")
            continue
        url = resolve_url(str(c.get("url") or ""))
        text = corpus.get(url) or next((t for u, t in corpus.items() if evidence_found(c.get("evidence", ""), t)), "")
        if not text and url:
            text = article_text(url, 30000)
            if text:
                corpus[url] = text
        if not evidence_found(c.get("evidence", ""), text):
            notes.append(f"{tag} — the quoted evidence isn't actually on the source page")
    if notes:
        return draft, "unsure", notes[:8]
    draft["evidence"] = [{"claim": c["claim"], "url": c.get("url", "")} for c in claims][:12]
    return draft, "ok", []


def visual_check(shots):
    """shots: [{"line", "intent", "jpeg"}] → [{"beat": i, "problem": str}] for clear mismatches."""
    import base64
    parts = [{"text": "You review an AI-news Instagram Reel before it's posted. For each numbered shot you get the "
                      "spoken line, what the shot is supposed to show, and a frame. Flag ONLY clear problems: the "
                      "picture is unrelated or misleading for the line (e.g. a real landscape for a software product "
                      "called 'Horizon', fruit for Apple the company), shows a different product or company than "
                      "named, is broken, blank or unreadable, or contains garbled text. Do not try to identify who "
                      "a person is from their face; for person cards only check it looks like a normal photo of a "
                      "person or an initials card. Generic but fitting visuals are fine."}]
    for i, s in enumerate(shots):
        parts.append({"text": f"\nSHOT {i + 1} · line: \"{s['line']}\" · should show: {s['intent']}"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(s["jpeg"]).decode()}})
    parts.append({"text": '\nReturn ONLY JSON: {"problems": [{"shot": <number>, "problem": "short reason"}]} '
                          '(empty list if everything is fine).'})
    res = parse_json(ask(parts, temperature=0.1, json_mode=True, light=True))
    out = []
    for p in res.get("problems") or []:
        try:
            out.append({"beat": int(p["shot"]) - 1, "problem": str(p.get("problem", ""))[:120]})
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- research (for news you send)
def resolve_url(u):
    """Follows Gemini's search redirect links (and Google News links) to the real article address."""
    if not isinstance(u, str) or not u.startswith("http"):
        return ""
    if "news.google.com" in u:
        import news
        return news.real_url(u)
    if "grounding-api-redirect" in u or "vertexaisearch" in u:
        try:
            return requests.get(u, timeout=10, allow_redirects=True, stream=True,
                                headers={"User-Agent": "Mozilla/5.0"}).url
        except Exception:
            return ""
    return u


def google_news_search(request, limit=8):
    """Backup search: asks Google News directly (free, no quota). Returns [{title, link, source, published, summary}]."""
    import feedparser
    import urllib.parse
    try:
        q = parse_json(ask(f'Turn this request into 1-3 short Google News search queries (the key names/topics, with '
                           f'"AI" if helpful). Request: "{request[:500]}". Return ONLY JSON: {{"queries": ["..."]}}',
                           temperature=0.2, json_mode=True, light=True)).get("queries") or []
    except Exception:
        q = []
    q = q or [re.sub(r"(?i)\b(give|make|tell|show|me|the|news|about|a|reel|please|on)\b", " ", request).strip()]
    found, seen = [], set()
    for query in q[:3]:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{query} when:14d") +
               "&hl=en-IN&gl=IN&ceid=IN:en")
        try:
            feed = feedparser.parse(requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).content)
        except Exception as e:
            print(f"Google News search failed: {e}")
            continue
        for e in feed.entries[:6]:
            title = re.sub(r"\s+", " ", e.get("title", "")).strip()
            if not title or title in seen:
                continue
            seen.add(title)
            src = title.rsplit(" - ", 1)[1] if " - " in title else ""
            found.append({"title": title.rsplit(" - ", 1)[0], "link": e.get("link", ""), "source": src,
                          "published": e.get("published", ""), "query": query})
    print(f"Google News search: {len(found)} results for {q}")
    return found[:limit]


def research(text):
    """Researches news you pasted: finds the original article and official announcement and the full facts.
    Returns a story dict (title, link, source, published, summary, official_url, sources) or None.
    Uses Gemini's Google Search; if that isn't available, searches Google News directly."""
    prompt = f"""Today is {now().strftime("%d %B %Y")}. Someone sent this AI news or request (maybe short, informal or forwarded, possibly with misspelled names):
\"\"\"{text[:2000]}\"\"\"

If it names SEVERAL things (e.g. "news about model X, model Y and other trending models"), make ONE roundup story covering
the most newsworthy recent ones (max 3). If a name is misspelled, work out what it most likely refers to from recent
news, and mention that interpretation in "corrections".
Research it with Google Search like a journalist:
1. Find the ORIGINAL reporting (a real news article) and, if one exists, the company's OFFICIAL announcement page.
2. Collect the verified facts: who (companies, people with their roles), what exactly (product/model names), numbers,
   dates, places, and any notable quote. Note anything in the message that is wrong or unconfirmed.
Return ONLY JSON:
{{"headline": "clear factual headline, max 100 characters",
 "summary": "the full story in 4-6 factual sentences, only verified facts",
 "published": "YYYY-MM-DD of the original announcement or article",
 "outlet": "name of the main news outlet (e.g. TechCrunch)",
 "article_url": "URL of the best original article",
 "official_url": "URL of the official announcement/product page, or empty",
 "corrections": ["anything in the message that was wrong or unconfirmed"],
 "sources": ["other URLs you used"]}}
If some names can't be found, still cover the parts of the request you CAN find (e.g. "recent trending models"),
list the names you couldn't identify in "unknown_names", and continue. Only if nothing at all can be found, return
{{"headline": "", "summary": "", "not_found": true, "unknown_names": [...]}}."""
    via = "Google Search"
    try:
        res = parse_json(ask(prompt, search=True, temperature=0.2, json_mode=True))
        searched = SEARCH_USED
    except Exception as e:
        print(f"Research failed: {e}")
        res, searched = {}, False
    if not searched or res.get("not_found") or not res.get("headline"):
        results = google_news_search(text)  # backup: real, current results from Google News
        if results:
            via = "Google News"
            import news as _news
            for r in results[:3]:
                r["link"] = _news.real_url(r["link"])
            texts = "\n\n".join(f"ARTICLE ({r['source']}): {article_text(r['link'], 2500)}" for r in results[:2]
                                  if "news.google." not in r["link"])
            listing = "\n".join(f"- {r['title']} ({r['source']}, {r['published'][:16]}) {r['link']}" for r in results)
            listing += ("\n\n" + texts) if texts.strip() else ""
            try:
                res = parse_json(ask(prompt + "\n\nUse ONLY these current Google News results as your sources "
                                              "(they are real and recent):\n" + listing,
                                     temperature=0.2, json_mode=True))
            except Exception as e:
                print(f"Research from Google News failed: {e}")
                return None if not res else {"not_found": True, "unknown_names": []}
        elif not searched:
            return None  # no search worked at all: don't claim "not found"
    unknown = [str(n)[:40] for n in (res.get("unknown_names") or [])][:5]
    if res.get("not_found") or not res.get("headline"):
        return {"not_found": True, "unknown_names": unknown}
    link = resolve_url(res.get("article_url", ""))
    if link and via == "Google Search":  # double-check the story against the article's actual text
        body = article_text(link, 4000)
        if body:
            try:
                res2 = parse_json(ask(prompt + "\n\nHere is the text of that article — make every fact match it, and "
                                               "name every person it mentions with their role:\n" + body,
                                      temperature=0.2, json_mode=True))
                if res2.get("headline"):
                    res = {**res, **{k: v for k, v in res2.items() if v}}
            except Exception as e:
                print(f"Article re-check skipped: {e}")
    official = resolve_url(res.get("official_url", ""))
    sources = [u for u in (resolve_url(x) for x in (res.get("sources") or [])[:4]) if u]
    published = ""
    try:
        from datetime import datetime
        published = datetime.strptime(str(res.get("published", ""))[:10], "%Y-%m-%d").isoformat() + "+00:00"
    except Exception:
        pass
    return {"title": str(res["headline"])[:140], "summary": str(res.get("summary", ""))[:1500],
            "source": str(res.get("outlet", ""))[:40], "link": link, "published": published,
            "official_url": official, "research_sources": [u for u in [link, official, *sources] if u],
            "corrections": [str(c)[:200] for c in (res.get("corrections") or [])][:4], "researched": True,
            "unknown_names": unknown, "via": via}


VAGUE = re.compile(
    r"(?i)\b(a|an|one|some|two|three)\s+(\w+\s+)?(developer|developers|startup|company|firm|team|researcher|researchers|"
    r"engineer|engineers|student|students|scientist|scientists|founder|founders|entrepreneur|lab|group|coder|"
    r"programmer|creator|creators|youngster|teenager|techie|professor|executive|ceo)\b"
    r"|\b(experts|researchers|scientists|developers|officials|analysts)\s+(say|said|found|have|believe|warn|built)\b"
    r"|\bsomeone\b|\b(a|one)\s+(major|big|leading|popular|well-known)\s+(\w+\s+)?(company|firm|lab|brand)\b")


def vague_phrases(script):
    """Vague references like "a developer from Kerala" that should name someone."""
    return list(dict.fromkeys(m.group(0) for m in VAGUE.finditer(script or "")))[:6]


def find_names(topic, phrases, script):
    """Searches for the actual names behind vague references. Returns [{"phrase", "name", "role", "found"}]."""
    prompt = f"""Story: {topic.get("title", "")}
Details: {topic.get("summary", "")[:800]}
Source: {topic.get("link", "")}
Script: {script}

These phrases in the script are vague: {json.dumps(phrases)}
Use Google Search (and the source article) to find exactly WHO each one is: the person's full name and role/company,
or the organisation's exact name. Return ONLY JSON:
{{"names": [{{"phrase": "...", "name": "full name", "role": "role, organisation", "found": true}}]}}
Set "found": false (and leave name empty) if you truly can't find it. Never guess a name."""
    try:
        res = parse_json(ask(prompt, search=True, temperature=0.1, json_mode=True))
        return [n for n in (res.get("names") or []) if isinstance(n, dict)]
    except Exception as e:
        print(f"Name search failed: {e}")
        return []

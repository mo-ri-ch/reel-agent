"""Uses the free Gemini API to pick stories and write scripts."""
import json
import re
import time

import requests

from config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, HANDLE, NICHE
from state import now


def ask(prompt, search=False, temperature=0.8, json_mode=False, light=False):
    """light=True: small jobs (picking stories/clips) go to the lighter model first, saving the main model's quota."""
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
    listing = "\n".join(f"{i}. [{h['source']}] {h['title']} — {h['summary'][:200]}"
                        for i, h in enumerate(headlines, 1))
    recent = "\n- ".join([""] + list(dict.fromkeys(history))[-40:]) or "none"
    prompt = f"""You run an Instagram Reels page about {NICHE} for a general audience.
From the headlines below, pick the {count} stories that would make the most engaging 40-second reels today:
big launches, surprising capabilities, tools people can actually use, major industry moves.
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
  "a major company" or "this technology" without naming who or what it is. If a detail can't be verified, leave it
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


def fact_check(draft, topic):
    """Checks every claim in the script with Google Search. Returns (draft, status, notes).
    status: "ok" (all verified), "fixed" (small errors corrected), "unsure" (needs a human), "skipped"."""
    beats = [{k: v for k, v in b.items() if v not in ("", [], None)} for b in draft.get("beats", [])]
    article = article_text(topic.get("link", ""))
    prompt = f"""Today is {now().strftime("%d %B %Y")}. You are the fact-checker of an AI-news Instagram page.
Story: {topic.get("title", "")}
Source: {topic.get("source", "")} {topic.get("link", "")}
Summary: {topic.get("summary", "")}
SOURCE ARTICLE TEXT (the reporting this story is based on):
{article or "(not available — rely on the title, summary and Google Search)"}

Script beats (JSON):
{json.dumps(beats, ensure_ascii=False)}

Use Google Search to check EVERY factual claim: names and spellings, people's roles and titles, companies,
product and model names, numbers, dates, places, and who said what. Also check each "person" beat's "role" and
each "stat" beat's number.
Return ONLY JSON:
{{"verdict": "ok" | "fixed" | "unsure",
 "issues": [{{"beat": <1-based number>, "problem": "what was wrong or unverifiable", "fix": "the correction"}}],
 "beats": [ONLY when verdict is "fixed": the full corrected beats list, same keys, minimal wording changes]}}
How to judge: this is breaking news, so brand-new products may have little coverage yet. Claims stated in the
source article, title or summary COUNT AS VERIFIED (that is the reporting). Search for everything else.
"ok" = everything checks out. "fixed" = you corrected small errors and are confident in the corrections.
"unsure" = ONLY when a claim contradicts reliable sources, or appears in no source at all and can't be verified
(likely invented by the script writer). Not being able to find extra coverage of new news is NOT a reason for "unsure"."""
    try:
        res = parse_json(ask(prompt, search=True, temperature=0.1, json_mode=True))
    except Exception as e:
        print(f"Fact check skipped: {e}")
        return draft, "skipped", []
    verdict = str(res.get("verdict", "")).lower()
    issues = [i for i in (res.get("issues") or []) if isinstance(i, dict)]
    notes = [f"Beat {i.get('beat', '?')}: {i.get('problem', '')}" + (f" → {i['fix']}" if i.get("fix") else "")
             for i in issues][:6]
    if verdict == "fixed" and isinstance(res.get("beats"), list) and res["beats"]:
        try:
            fixed = normalize_draft({**draft, "beats": res["beats"]}, topic)
            return fixed, "fixed", notes
        except Exception as e:
            print(f"Couldn't apply fact fixes: {e}")
            return draft, "unsure", notes
    if verdict == "ok" and not issues:
        return draft, "ok", []
    return draft, ("ok" if verdict == "ok" else "unsure"), notes


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

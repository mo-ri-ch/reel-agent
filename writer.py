"""Uses the free Gemini API to pick stories and write scripts."""
import json
import re
import time

import requests

from config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, HANDLE, NICHE
from state import now


SEARCH_USED = False  # did the last ask() really use Google Search?


ERRORS = []   # Gemini failures in this run (saved to state.json so Claude can see quota problems)
CLAUDE_CALLS = [0]
CLAUDE_OFF = [False]  # set when the key is refused or out of credit, so the run falls back to Gemini at once


def ask_claude(parts, temperature=0.5, max_tokens=4000):
    """Claude (Anthropic API). parts: text, or a list of {"text"} / {"inline_data": {"mime_type", "data"}} like ask().
    Raises on any problem; callers fall back to Gemini."""
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    if not ANTHROPIC_API_KEY or CLAUDE_OFF[0]:
        raise RuntimeError("Claude not available")
    content = []
    for p in (parts if isinstance(parts, list) else [{"text": parts}]):
        if "inline_data" in p:
            content.append({"type": "image", "source": {"type": "base64", "media_type": p["inline_data"]["mime_type"],
                                                        "data": p["inline_data"]["data"]}})
        elif p.get("text"):
            content.append({"type": "text", "text": p["text"]})
    CLAUDE_CALLS[0] += 1
    for attempt in range(3):
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
            "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": max_tokens,  # Sonnet 5.5 refuses "temperature"
                  "messages": [{"role": "user", "content": content}]})
        if r.status_code in (429, 500, 529) and attempt < 2:
            time.sleep(10)
            continue
        if r.status_code in (401, 402, 403) or "credit" in r.text.lower():
            CLAUDE_OFF[0] = True
            ERRORS.append({"at": time.strftime("%H:%M"), "error": f"Claude refused ({r.status_code}): {r.text[:150]}"})
        if r.status_code != 200:
            raise RuntimeError(f"Claude error {r.status_code}: {r.text[:200]}")
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        if text.strip():
            return text
    raise RuntimeError("Claude gave no reply")
CALLS = [0]   # Gemini requests made in this run
BACKUP_CALLS = [0]   # jobs Claude did because Gemini's free quota was used up (this run)
BACKUP_LEFT = [0]    # how many more of those today (set by main.py from state.json; caps the cost)


def claude_backup(prompt, search, json_mode, last):
    """Gemini's free quota is used up: let Claude do the job, so slots don't go empty for hours.
    Claude has no Google Search here, so it may only use the text it is given (stricter, never looser)."""
    if BACKUP_LEFT[0] <= 0:
        raise RuntimeError(last)
    parts = list(prompt) if isinstance(prompt, list) else [{"text": prompt}]
    extra = ""
    if search:
        extra += ("\n\n(You can't search the web now: use ONLY the source text given above; anything not in it is "
                  "\"unsupported\". Never invent quotes or URLs.)")
    if json_mode:
        extra += "\n\nReply with ONLY the JSON, no other text."
    if extra:
        parts.append({"text": extra})
    BACKUP_LEFT[0] -= 1
    BACKUP_CALLS[0] += 1
    text = ask_claude(parts, temperature=0.2 if search else 0.5)
    print("Gemini quota used up: Claude did this job")
    return text


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
            CALLS[0] += 1
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
    ERRORS.append({"at": time.strftime("%H:%M"), "error": last[:200]})
    if "quota" in last or "overloaded" in last:
        try:
            return claude_backup(prompt, search, json_mode, last)
        except Exception as e:
            print(f"Claude backup failed: {e}")
            if BACKUP_LEFT[0] > 0 or BACKUP_CALLS[0]:
                ERRORS.append({"at": time.strftime("%H:%M"), "error": f"Claude backup failed: {str(e)[:170]}"})
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
From the headlines below, pick the {count} stories that would make the most engaging 30-40 second reels today:
big launches, surprising capabilities, tools people can actually use, major industry moves.
SHAREABILITY decides reach on Instagram (DM sends count far more than likes): prefer stories a viewer would
send to a friend: surprising or weird, useful right now, affects their job, money or privacy, or sparks debate.
A dry corporate update (partnership, minor feature, earnings) loses to a surprising story from a known name.
Favour BREAKING stories that are clearly blowing up (high Hacker News points / Reddit upvotes in brackets) — but a Reddit
post is only a lead: prefer stories that are also confirmed by a news site or an official announcement.
The audience is GLOBAL (US, Europe, India): favour stories people everywhere care about (big AI companies, new
models and tools anyone can use, major policy and research). Regional stories (India, Europe, US politics) are fine
when they are big news, but keep the mix global.
OUR DATA: stories about well-known companies and products (OpenAI/ChatGPT, Google/Gemini, Apple, Microsoft, Meta,
Nvidia, Anthropic/Claude, Amazon, Tesla, big game studios…) get about 50% more views than niche ones. Strongly prefer
them. Local pilots, regional regulations and small-company news only when they are genuinely big.
Skip minor funding news, opinion pieces and duplicates of each other.
Also SKIP: company press releases and self-announcements by small or unknown firms, local/regional events
(bootcamps, workshops, trainings, seminars, hackathons), government MoUs and "policy targets" without a concrete
launch, stock/market-size reports, and anything an AI-curious viewer wouldn't tell a friend about.
It's better to return fewer picks than weak ones: only pick stories a big tech-news outlet would also cover.
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


RULES = """Write a 30-40 second Instagram Reel about AI, read aloud by a voice-over.

SCRIPT
- 75 to 105 words. Conversational, like a sharp tech journalist explaining it to a smart friend: short sentences (max
  ~16 words), contractions, one idea per sentence. Say "AI", never "artificial intelligence".
- SUBSTANCE: every sentence must add a NEW concrete fact from the sources: what exactly it is, how it works, the key
  number, who is involved, what came before, what happens next. Never write empty lines like "X reported on it",
  "the publication discussed reactions", "the code is available online" or "this raises questions". If the sources
  don't give enough real detail for a full reel, say so in "thin": true instead of padding.
- Line 1 is the HOOK: 9 words or fewer, the big name or number first. Viewers decide in under 2 seconds, so make it
  create curiosity or stakes, not just state the news. Use ONE of: a surprising fact or number, a bold (true) claim,
  "you" framing about the viewer's life, or a question they can't ignore.
  Weak: "Utah is launching a pilot program to use artificial intelligence for patient exams."
  Strong: "An AI just started examining patients in Utah."
- Line 2 gives the viewer a reason to stay (what's at stake for them, or the surprising detail), within 3 seconds.
  Good hooks: "Your next coworker might not be human." / "Google just made search ten times faster."
  Never start with: "Hey guys", "Did you know", "In today's video", "Breaking news", "Imagine".
- Then: what happened (the specifics) → how it works or the key detail → context (numbers, comparison, competitors,
  what came before) → why it matters to the viewer → what happens next.
- BE STRICTLY SPECIFIC (the owner's top rule). Name the company AND the product/model in the first two lines, every
  person with their role, and give at least one real number or date. Never generalise ("the company", "a new AI
  model", "tech giants", "experts"). Every script must name the concrete details: WHO (the company, lab, university or research team),
  WHAT exactly (the product or model name, the journal or paper, what it actually does), WHERE (country or city)
  and, when known, a real number or date from the source. Use Google Search to find the original source first.
  Never write vague filler like "recent research", "a new study", "experts say", "scientists", "tech giants",
  "a major company" or "this technology" without naming who or what it is. NEVER say "a developer", "a startup",
  "a team" or "an engineer": say who — e.g. not "a developer from Kerala" but "Kochi developer <full name>".
  Every named person must get a "person" beat (their name + role) so their photo is shown. If a detail can't be verified, leave it
  out rather than inventing it.
- Keep one surprising detail for the second-to-last line so viewers stay to the end.
- End with one short, specific question viewers can answer in a word or two ("Would you let it drive your car?"),
  never a generic "What do you think?". Do NOT add a "follow us" line or mention any @handle.
- Never say "according to <outlet>", "<outlet> reported" or "as reported by": just state the facts (the source is
  shown on screen and in the caption).
- Banned words: game-changer, revolutionize, revolutionary, cutting-edge, unleash, delve, landscape, buckle up,
  "the future is here", "in today's world", "stay tuned", "mind-blowing".
- No emojis, hashtags, stage directions or brackets in the lines. Write numbers the way they're said ("ten times", "two billion").

VISUALS — split the script into 6 to 9 beats (one or two sentences each). Every beat gets ONE visual.
Prefer REAL and SPECIFIC visuals over generic ones:
- a line about a named PRODUCT, APP, AI MODEL, DEVICE or COMPANY ANNOUNCEMENT → "official" (the real product images);
- a line that names or quotes a PERSON ("Sam Altman says…", "Lovable co-founder Fabian Hedin…") → ALWAYS "person";
- a named university, lab, building or place → "photo";
- where the news comes from (a journal, paper or announcement) → "source".
NEVER use a product or company name as a stock "query" or image "prompt": names are not literal ("Horizon Studio" is
Meta software, not a horizon; "Gemini" is a Google AI, not a star sign; "Apple" is a company, not fruit).
- "clip": real stock video. Use for things footage shows well: people using phones or laptops, offices, city streets,
  data centers, robots, coding screens, doctors, students. "query" = 2-4 concrete words ("woman talking to phone", not "AI innovation").
- "image": AVOID. AI pictures look fake in news and viewers swipe away. Use only when nothing real (official, photo,
  person, clip, source) can show the line; a real news photo is used instead whenever one exists. "prompt" = vivid
  cinematic vertical scene, no text, no logos, no real people's faces.
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
Mix the types; don't use the same type more than twice in a row. Use "clip" for at most 2 beats: stock video is
generic and rarely matches the words. When a line names a company, product or model, use "official" (its real
images); a person → "person"; a place, lab or university → "photo"; a number → "stat"; the outlet → "source".
For every beat, also give "tag": a 2-5 word on-screen phrase with that line's KEY FACT, always containing a name or a
number from the line ("Claude scanned 30M genes", "$600M a year", "Banned in 3 states"). Never an abstract label
("Expert Debate", "Traditional Methods", "Biosecurity Questions"). It is shown big when no picture fits.
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
 "delivery": "one line for the voice actor: the feeling of THIS story and where it turns (e.g. 'amused disbelief, then serious about what it means for jobs'); no script words",
 "thin": false,
 "caption": "2-3 sentence Instagram caption ending with a question",
 "hashtags": ["10 to 12 relevant hashtags without #"],
 "sources": ["URLs you used"]}}"""


def clean_spoken(line):
    """Removes things a voice must never read: [stage directions], (pause), *emphasis*, labels like 'Narrator:'."""
    line = re.sub(r"\[[^\]]*\]", " ", str(line))
    line = re.sub(r"\((?:pause|beat|music|sfx|sound|laughs?|whoosh|b-roll|cut to|on screen|voice ?over)[^)]*\)", " ",
                  line, flags=re.I)
    line = re.sub(r"(?i)^\s*(narrator|voice ?over|vo|host|speaker|line \d+)\s*:\s*", "", line)
    line = line.replace("*", "").replace("#", "").replace("_", " ")
    return re.sub(r"\s+", " ", line).strip()


ATTRIBUTION = re.compile(r"(?i)^\s*(according to|as reported by|per)\s+[^,:]{2,60}[,:]\s*")


def drop_attribution(line):
    """Owner: never say 'According to <source>' in the voice-over (the source is shown on screen and in the caption)."""
    out = ATTRIBUTION.sub("", line).strip()
    return out[:1].upper() + out[1:] if out else line


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
        beats.append({"line": drop_attribution(str(b["line"]).strip()), "visual": kind,
                      "query": str(b.get("query") or "technology"), "prompt": str(b.get("prompt") or ""),
                      "big": str(b.get("big") or "")[:10], "small": str(b.get("small") or "")[:40],
                      "entity": str(b.get("entity") or "")[:80], "outlet": str(b.get("outlet") or "")[:60],
                      "domain": str(b.get("domain") or "")[:60], "headline": str(b.get("headline") or "")[:120],
                      "url": str(b.get("url") or "")[:300], "tag": str(b.get("tag") or "")[:40],
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
    for b in draft.get("beats", []):  # no stage directions / formatting in anything that gets spoken
        b["line"] = clean_spoken(b["line"])
    draft["beats"] = [b for b in draft.get("beats", []) if b["line"]]
    draft["script"] = "\n".join(b["line"] for b in draft["beats"])
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
    if isinstance(raw, list):
        raw = {str(i + 1): v for i, v in enumerate(raw)}
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
    draft, model = None, "gemini"
    source = "" if topic.get("custom") else article_text(topic.get("link", ""), limit=9000)
    if len(source) > 600:  # Claude writes from the article itself (it has no Google Search here)
        try:
            cprompt = (prompt.replace("Use Google Search to verify the details and find the latest facts.",
                                      "Use ONLY facts stated in the SOURCE ARTICLE below.")
                       .replace("Use Google Search to find the original source first.",
                                "Use the SOURCE ARTICLE below as the original source.")
                       + f"\n\nSOURCE ARTICLE (the only facts you may use):\n{source}\n\nThe script must be 75-105 "
                       "words in total (count them): pick the best facts, don't use them all. Return ONLY the JSON.")
            draft, model = parse_json(ask_claude(cprompt, temperature=0.6)), "claude"
        except Exception as e:
            print(f"Claude writing skipped, using Gemini: {e}")
            draft = None
    if draft is None:
        try:
            draft = parse_json(ask(prompt, search=True, json_mode=True))
        except ValueError:
            # the search-grounded reply wasn't clean JSON: ask again in strict JSON mode
            draft = parse_json(ask(prompt, json_mode=True))
    draft = normalize_draft(draft, topic)
    draft["writer_model"] = model
    if not instruction:
        draft = sharpen_hook(draft, topic)
    return draft


def sharpen_hook(draft, topic):
    """Rewrites only the first spoken line into a stronger hook (facts unchanged). Falls back silently."""
    beats = draft.get("beats") or []
    if not beats:
        return draft
    first = beats[0]["line"]
    prompt = f"""News story: {topic.get('title', '')}
First line of an Instagram Reel voice-over: "{first}"
Next line: "{beats[1]['line'] if len(beats) > 1 else ''}"

Viewers swipe away within 2 seconds unless the first line grabs them. Rewrite ONLY the first line:
- a hook of 9 words or fewer, with the company/product name or the key number early, creating curiosity or stakes;
- then, if the hook drops a fact the original line had, add one short plain sentence with that fact (max 14 words);
- keep every fact true and unchanged: no new claims, numbers or names; no exaggeration; no question marks if the
  original had a fact; no "Did you know", "Imagine", "Breaking", "Hey guys"; numbers written as spoken words.
Return ONLY JSON: {{"line": "the new first line"}}"""
    try:
        res = parse_json(ask(prompt, temperature=0.7, json_mode=True, light=True))
        new = clean_spoken(str((res[0] if isinstance(res, list) and res else res).get("line", "")))
    except Exception as e:
        print(f"Hook pass skipped: {e}")
        return draft
    words = len(new.split())
    if 4 <= words <= 26 and new.lower() != first.lower():
        print(f"Hook: {first!r} → {new!r}")
        beats[0]["line"] = new
        draft["script"] = "\n".join(b["line"] for b in beats)
        draft["hook_before"] = first
    return draft


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
                     "openai", "futuretech", "machinelearning", "technews"],
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
    if len(text) < 400:  # fallback: JSON-LD articleBody, used by many news sites
        m = re.search(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.){200,})"', page)
        if m:
            try:
                text = json.loads(f'"{m.group(1)}"')
            except Exception:
                text = m.group(1)
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
        if len(txt) > 400:
            corpus[u] = txt
    if len(corpus) < 2:  # paywalled or blocked source: read other outlets' coverage of the same story
        import news as _news
        for r in google_news_search(topic.get("title", ""))[:6]:
            if len(corpus) >= 3:
                break
            u = _news.real_url(r["link"])
            if u in corpus or "news.google." in u:
                continue
            txt = article_text(u, 30000)
            if len(txt) > 400:
                corpus[u] = txt
    print(f"Fact check sources: {list(corpus)}")
    beats = [{"beat": i + 1, "line": b["line"], **({"person": b.get("name"), "role": b.get("role")}
                                                   if b.get("visual") == "person" else {}),
              **({"number": b.get("big"), "label": b.get("small")} if b.get("visual") == "stat" else {})}
             for i, b in enumerate(draft.get("beats", []))]
    if draft.get("hook_text"):  # the big opening headline / cover is checked too
        beats.insert(0, {"beat": 0, "line": f"(opening headline shown on screen and on the cover) {draft['hook_text']}"})
    sources_txt = "\n\n".join(f"SOURCE {u}:\n{t[:12000]}" for u, t in corpus.items()) or "(no source text available)"
    prompt = f"""Today is {now().strftime("%d %B %Y")}. You are a strict fact-checker for a news page.
Story: {topic.get("title", "")}

{sources_txt}

Script beats:
{json.dumps(beats, ensure_ascii=False)}

List EVERY factual claim in the beats (names, roles, companies, product names, numbers, dates, places, who said or
did what, what a product does). Questions and opinions are not claims. Beat 0 is the opening headline: it must not
exaggerate or say more than the sources do (e.g. "paused ALL training" when only some was paused is "contradicted").
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
    claims = res if isinstance(res, list) else (res.get("claims") or [])
    claims = [c for c in claims if isinstance(c, dict) and c.get("claim")]
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
    for p in (res if isinstance(res, list) else res.get("problems") or []):
        if not isinstance(p, dict):
            continue
        try:
            out.append({"beat": int(p["shot"]) - 1, "problem": str(p.get("problem", ""))[:120]})
        except Exception:
            continue
    return out


EDITOR_CRITERIA = ["hook", "specific", "substance", "accuracy", "visuals", "flow"]

EDITOR_BRIEF = """You are the editor-in-chief of @gradientai.news, a premium AI-news Instagram account for a global
audience. Be strict: only top-notch reels get posted. Judge this finished reel before it goes live.

SOURCE HEADLINE: {title}
SOURCE SUMMARY: {summary}
SCRIPT (spoken, in order):
{lines}

Score each 1-10:
- hook: do the first 2 seconds (title screen + line 1) make a viewer stop? Big name or number first?
- specific: real company, product/model and people names, real numbers/dates. Any generic phrase ("the company",
  "experts", "a new AI model", "raises questions") costs points.
- substance: every line adds a new concrete fact; no filler, no repetition, no "X reported on it".
- accuracy: every claim matches the source; no exaggeration or misleading framing (a projection is not a target, a
  report is not a confirmation). Wrong or misleading = 4 or less.
- visuals: each frame fits the words being spoken at that moment (named company -> its logo/product, person -> their
  photo, number -> number card); no unrelated, repeated, blank or broken pictures; text readable.
- flow: natural spoken English, clear story, strong specific ending question.
Then list what must change to reach 9/10."""

EDITOR_FORMAT = """
Return ONLY JSON: {"scores": {"hook": n, "specific": n, "substance": n, "accuracy": n, "visuals": n, "flow": n},
"one_line": "your verdict in under 15 words",
"script_fixes": ["concrete change to a line, e.g. 'LINE 3: name the model (GPT-5.5) instead of the new model'"],
"visual_problems": [{"line": LINE number, "problem": "short reason"}]}"""


def editor_review(draft, topic, frames, beat_times):
    """The editor-in-chief watches the finished reel (frames + script + source) and scores it like a strict news
    editor. Returns {"overall", "scores", "one_line", "script_fixes", "visual_beats", "visual_notes"}."""
    import base64
    beats = draft.get("beats") or []

    def beat_at(t):
        for i, (a, b) in enumerate(beat_times or []):
            if a <= t < b:
                return i
        return None
    lines = "\n".join(f"LINE {i + 1}: {b.get('line', '')}" for i, b in enumerate(beats))
    parts = [{"text": EDITOR_BRIEF.format(title=topic.get("title", ""), summary=str(topic.get("summary", ""))[:600],
                                          lines=lines)}]
    for i, f in enumerate(frames):
        b = beat_at(f["t"])
        said = f"LINE {b + 1}" if b is not None else "title screen"
        parts.append({"text": f"\nFRAME {i + 1} at {f['t']}s (while {said} is spoken)"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(f["jpeg"]).decode()}})
    parts.append({"text": EDITOR_FORMAT})
    try:
        res = parse_json(ask_claude(parts, temperature=0.1, max_tokens=1500))
        reviewer = "claude"
    except Exception as e:
        print(f"Claude editor skipped, using Gemini: {e}")
        res = parse_json(ask(parts, temperature=0.1, json_mode=True))
        reviewer = "gemini"
    out = score_review(res, len(beats))
    out["reviewer"] = reviewer
    return out


def score_review(res, n_beats):
    """Turns the editor's JSON into the overall score (inaccurate or generic reels can't pass on other strengths)."""
    if isinstance(res, list):
        res = res[0] if res else {}
    raw = res.get("scores") or {}
    scores = {}
    for k in EDITOR_CRITERIA:
        try:
            scores[k] = max(1, min(10, int(float(raw.get(k, 7)))))
        except Exception:
            scores[k] = 7
    overall = round(sum(scores.values()) / len(scores), 1)
    if min(scores["accuracy"], scores["specific"]) < 7:
        overall = min(overall, 6.5)
    vb, notes = [], []
    for p in res.get("visual_problems") or []:
        try:
            i = int(p.get("line")) - 1
        except Exception:
            continue
        if 0 <= i < n_beats:
            vb.append(i)
            notes.append(f"line {i + 1}: {str(p.get('problem', ''))[:90]}")
    return {"overall": overall, "scores": scores, "one_line": str(res.get("one_line", ""))[:120],
            "script_fixes": [str(x)[:200] for x in (res.get("script_fixes") or [])][:6],
            "visual_beats": sorted(set(vb)), "visual_notes": notes[:6]}


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
    if isinstance(res, list):
        res = next((x for x in res if isinstance(x, dict)), {})
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
    if isinstance(res, list):
        res = next((x for x in res if isinstance(x, dict)), {})
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
                if isinstance(res2, list):
                    res2 = next((x for x in res2 if isinstance(x, dict)), {})
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
    r"|\b(experts|researchers|scientists|developers|officials|analysts|critics|insiders)\s+(say|said|found|have|"
    r"believe|warn|warned|built|argue|argued|suggest|claim|think|predict|agree|note|fear)\b"
    r"|\bsomeone\b|\b(a|one)\s+(major|big|leading|popular|well-known)\s+(\w+\s+)?(company|firm|lab|brand)\b"
    r"|\b(tech giants?|big tech|a tech company|an ai company|an ai lab|an ai startup|ai companies|some companies)\b"
    r"|\ba\s+new\s+(ai\s+)?(model|tool|app|chatbot|platform|system|feature|product)\b(?!\s+(called|named))"
    r"|(?:^|[.!?]\s+)(independent\s+|some\s+|many\s+|other\s+)?(experts|researchers|scientists|biologists|critics|"
    r"analysts|observers|developers|engineers|insiders|officials)\b(?!\s+(at|from|of|in|with|led|behind|on)\s+[A-Z])"
    r"(?!\s+[A-Z])"
    r"|\b(independent|outside|leading)\s+experts\b"
    r"|\braises?\s+(\w+\s+){0,2}(questions|concerns)\b"
    r"|\b(sparks?|fuels?)\s+(a\s+)?(debate|concerns?|questions)\b")

NUMBER_WORDS = re.compile(r"(?i)\b(\d[\d,.]*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
                          r"thirty|forty|fifty|hundred|thousand|million|billion|trillion|percent|half|double|triple|"
                          r"january|february|march|april|may|june|july|august|september|october|november|december|"
                          r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|yesterday|last week|this week)\b")
COMMON_CAPS = {"AI", "I", "The", "This", "That", "It", "Its", "And", "But", "So", "Now", "Would", "Could", "Can", "Will",
               "What", "Why", "How", "Who", "When", "Where", "Your", "You", "We", "They", "He", "She", "If", "Just",
               "Here", "There", "Do", "Does", "Is", "Are", "Should", "Meanwhile", "Still", "Plus", "Then", "A", "An"}


def specificity(script):
    """(names, has_number): proper names mentioned (company, product, person, place) and whether a number/date is
    given. A reel must name who and what, with at least one concrete number or date."""
    names = set()
    for sentence in re.split(r"(?<=[.!?])\s+", script or ""):
        words = sentence.split()
        for i, w in enumerate(words):
            t = re.sub(r"[^\w'’.-]", "", w).strip(".'’")
            if t[:1].isupper() and t not in COMMON_CAPS and (i > 0 or len(t) > 2) and not t.isdigit():
                names.add(t)
    return names, bool(NUMBER_WORDS.search(script or ""))


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
        return [n for n in (res if isinstance(res, list) else res.get("names") or []) if isinstance(n, dict)]
    except Exception as e:
        print(f"Name search failed: {e}")
        return []


def same_event(topic, covered):
    """Is this one story the SAME news event as something we already covered? Returns that covered item or None.
    Covered items may include what our reel said, which catches renamed launches ("1T model" = "Le Chonk")."""
    if not covered:
        return None
    recent = "\n".join(f"{i}. {t}" for i, t in enumerate(list(dict.fromkeys(covered))[-60:], 1))
    res = parse_json(ask(f"""NEW STORY: {topic.get("title", "")} — {str(topic.get("summary", ""))[:300]}

ALREADY COVERED in the last 14 days (title, and what our reel said):
{recent}

Is the NEW STORY about the SAME news event as one already covered: the same announcement, launch, model, results
release, report, policy, lawsuit, deal or person's move, even if worded differently, from another outlet, a follow-up
analysis or an opinion piece about it? A genuinely NEW development (e.g. a price cut a week after a launch) is NOT a
repeat; a different story about the same company is NOT a repeat.
Return ONLY JSON: {{"repeat": true/false, "covered": <number of the covered item or 0>, "why": "short"}}""",
                         temperature=0, json_mode=True))
    if isinstance(res, list):
        res = res[0] if res else {}
    if not res.get("repeat"):
        return None
    items = list(dict.fromkeys(covered))[-60:]
    try:
        hit = items[int(res.get("covered")) - 1]
    except Exception:
        return None
    import news as _news
    # guard against false alarms: they must share at least one distinctive word (a company, product or topic name)
    if not _news.keywords(topic.get("title", "") + " " + str(topic.get("summary", ""))[:300]) & _news.keywords(hit):
        return None
    return hit.split(" — said: ")[0]


def drop_same_events(picks, covered):
    """Asks Gemini whether any picked story is the SAME news event as one already covered, even when the
    headlines share no words (e.g. a first-person essay and a news report about the same resignation)."""
    if not picks or not covered:
        return picks
    listing = "\n".join(f"{i}. {p['title']} — {p.get('summary', '')[:160]}" for i, p in enumerate(picks, 1))
    recent = "\n".join(f"- {t}" for t in list(dict.fromkeys(covered))[-40:])
    try:
        res = parse_json(ask(f"""New stories:
{listing}

Already covered recently:
{recent}

Which NEW stories are about the SAME news event as something already covered (same announcement, same person
leaving, same launch, same report, same lawsuit) — even if worded differently or from another outlet?
Only the very same event counts: two different stories about the same company or topic are NOT repeats.
Return ONLY JSON: {{"repeats": [{{"new": <number>, "covered": "the exact already-covered title it repeats"}}]}}""", temperature=0, json_mode=True,
                             light=True))
        rep = res if isinstance(res, list) else res.get("repeats") or []
        import news as _news
        bad = set()
        for r in rep:  # trust it only when the two headlines also share at least 2 key words
            if not isinstance(r, dict) or not str(r.get("new", "")).isdigit():
                continue
            i = int(r["new"])
            if 0 < i <= len(picks) and len(_news.keywords(picks[i - 1]["title"] + " " + picks[i - 1].get("summary", "")[:200])
                                           & _news.keywords(str(r.get("covered", "")))) >= 2:
                bad.add(i)
    except Exception as e:
        print(f"Same-event check skipped: {e}")
        return picks
    if bad:
        print("Dropped repeats:", [picks[i - 1]["title"] for i in bad if 0 < i <= len(picks)])
    return [p for i, p in enumerate(picks, 1) if i not in bad]

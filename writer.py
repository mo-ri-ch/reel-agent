"""Uses the free Gemini API to pick stories and write scripts."""
import json
import re
import time

import requests

from config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, HANDLE, NICHE
from state import now


def ask(prompt, search=False, temperature=0.8, json_mode=False):
    models = [GEMINI_MODEL] + ([GEMINI_FALLBACK_MODEL] if GEMINI_FALLBACK_MODEL != GEMINI_MODEL else [])
    last = ""
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
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
                last = r.text[:300]
                time.sleep(20 * (attempt + 1))
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
    recent = "; ".join(history[-15:]) or "none"
    prompt = f"""You run an Instagram Reels page about {NICHE} for a general audience.
From the headlines below, pick the {count} stories that would make the most engaging 40-second reels today:
big launches, surprising capabilities, tools people can actually use, major industry moves.
Skip minor funding news, opinion pieces, duplicates of each other, and anything similar to recently covered topics: {recent}

Headlines:
{listing}

Return ONLY JSON: {{"picks": [{{"n": <headline number>, "angle": "<one short line: why viewers will care>"}}]}}"""
    try:
        picks = parse_json(ask(prompt, temperature=0.4, json_mode=True))["picks"]
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


RULES = """Write a script for a 35-45 second Instagram Reel. The creator will read it aloud in their own voice.
- 85 to 110 words, simple spoken English. Explain any jargon in a few words.
- Line 1 is the hook: under 12 words, creates curiosity or surprise. Never start with "Hey guys" or "In today's video".
- Then 2-3 short, concrete points: what happened, why it matters, what it means for the viewer.
  Only use names, numbers and dates you are confident are accurate.
- Last line: a short ask to follow for daily AI news{handle}.
- Short sentences that are easy to say. No emojis, hashtags, stage directions or brackets in the script.

Return ONLY JSON with these keys:
{{"title": "on-screen headline, max 60 characters",
 "script": "the full script, one sentence per line",
 "caption": "2-3 sentence Instagram caption ending with a question to get comments",
 "hashtags": ["10 to 12 relevant hashtags without the # sign"],
 "keywords": ["5 short stock-footage search terms that visually match the story, e.g. robot arm, coding laptop, data center"],
 "image_prompts": ["3 prompts for AI-generated images that illustrate the story: vivid, cinematic, vertical composition. No text, no logos, no real people"],
 "sources": ["URLs you used"]}}"""


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
    if isinstance(draft, list):
        draft = draft[0] if draft else {}
    script = draft.get("script", "")
    draft["script"] = ("\n".join(script) if isinstance(script, list) else str(script)).strip()
    draft["title"] = str(draft.get("title") or topic["title"])[:70]
    draft["caption"] = str(draft.get("caption", ""))
    draft["hashtags"] = [str(h).lstrip("#").replace(" ", "") for h in draft.get("hashtags", [])][:15]
    draft["keywords"] = [str(k) for k in draft.get("keywords", [])][:6]
    draft["image_prompts"] = [str(p) for p in draft.get("image_prompts", [])][:3]
    draft["sources"] = draft.get("sources", [])
    if not draft["script"]:
        raise RuntimeError("The script came back empty, please try again.")
    return draft


def draft_from_own_script(text, topic=None):
    """Builds a draft from a script you wrote yourself (no Gemini needed)."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    title = (topic or {}).get("title") or lines[0]
    return {
        "title": title[:70],
        "script": "\n".join(lines),
        "caption": " ".join(lines[:2])[:300] + "\n\nWhat do you think? Tell me in the comments 👇",
        "hashtags": ["ai", "artificialintelligence", "ainews", "tech", "technology", "chatgpt",
                     "openai", "futuretech", "machinelearning", "techindia"],
        "keywords": ["artificial intelligence", "technology", "data center", "robot", "coding laptop"],
        "image_prompts": [f"an illustration representing: {title}",
                          "a futuristic glowing AI brain made of circuits, purple and blue neon"],
        "sources": [],
    }

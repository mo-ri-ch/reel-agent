"""Reel agent: talks to you on Telegram, then makes, schedules and posts reels.

Modes:  python main.py offer | poll | render | check
"""
import copy
import hashlib
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta

import news
import state as st
import telegram_api as tg
import whatsapp
import writer
from config import FISH_API_KEY, FISH_VOICE_ID, HANDLE, AI_VOICE_NOTE, AUTO_APPROVE_HOURS, AUTO_PICK_HOURS, OFFER_TIMES, POST_TIMES, TELEGRAM_CHAT_ID, WORK_DIR

POST_WORDS = {"post", "yes", "approve", "ok", "okay", "publish", "schedule", "👍", "✅"}
POST_NOW_WORDS = {"post now", "publish now", "now"}
REDO_WORDS = {"redo", "re-record", "rerecord", "again", "retry"}
AI_VOICE_WORDS = {"ok", "okay", "yes", "go", "approve", "approved", "good", "looks good", "done", "👍", "✅"}
MALE_WORDS = {"male", "man", "boy", "m", "guy"}
FEMALE_WORDS = {"female", "woman", "girl", "f", "lady"}


def voice_request(low):
    """'ok' → alternate, 'ok female' / 'female' → female, 'ok male' / 'male' → male. None if not a voice request."""
    words = low.replace(",", " ").split()
    if not words:
        return None
    if low in AI_VOICE_WORDS:
        return "alternate"
    if all(w in AI_VOICE_WORDS | MALE_WORDS | FEMALE_WORDS | {"voice"} for w in words):
        if any(w in FEMALE_WORDS for w in words):
            return "female"
        if any(w in MALE_WORDS for w in words):
            return "male"
    return None

HELP = f"""🤖 Reel Agent

{len(OFFER_TIMES)} times a day ({', '.join(OFFER_TIMES)}) I send you the top AI stories.
Tap the buttons under my messages, or type — both work.
• Tap a story (or type any topic you like)
• No reply? I pick #1 automatically
• I send a script. Reply with changes ("shorter", "funnier hook"…)
• Happy with it? Reply "ok" and an AI voice reads it 🤖 (alternating male/female),
  "ok male" / "ok female" to choose, or send a voice note to use your own voice 🎤
• I send a preview. Reply "post" to schedule it for the next posting time ({', '.join(POST_TIMES)}), or "post now"
• Optional: send a picture or a short video clip (e.g. from Gemini) for the opening shot

Commands:
/reel <news or request> – research it and make an extra reel now (e.g. /reel latest trending AI models)
/topic <anything> – an explainer reel on a topic (or just send a news link / paste news text)
/myscript <your script> – use a script you wrote yourself (skips Gemini)
/news – get fresh stories now (e.g. to record the next reel straight away)
/autopilot on|off – finish reels on my own when you don't reply
/queue – see scheduled reels
/stats – this week's numbers (followers, views, best reels)
/held – review reels the quality check parked
/nextstory – drop this story and make the next one
/script – show the current script again
/status – what I'm waiting for
/undo – go back one step (tap ↩️ Undo)
/skip – cancel the current reel"""


def github_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def fmt_time(dt):
    today = st.now().date()
    day = "today" if dt.date() == today else "tomorrow" if dt.date() == today + timedelta(days=1) else dt.strftime("%d %b")
    return f"{dt.strftime('%I:%M %p').lstrip('0')} {day}"


def script_message(draft, note="Tap a voice below 🤖 (or send a voice note to use your own 🎤)"):
    words = len(draft["script"].split())
    return (f"🎙 Script ({words} words, about {round(words / 2.6)} sec)\n\n{draft['script']}\n\n—\n{note}\n"
            "Want changes? Just type them, e.g. \"shorter\", \"stronger hook\".")


def deadline(hours=AUTO_APPROVE_HOURS):
    return (st.now() + timedelta(hours=hours)).isoformat()


def passed(iso):
    return bool(iso) and st.now() >= datetime.fromisoformat(iso)


def autopilot_note(kind):
    when = (st.now() + timedelta(hours=AUTO_APPROVE_HOURS)).strftime("%I:%M %p").lstrip("0")
    return {"script": f"\n🤖 Autopilot: no reply by {when}? I'll use the AI voice.",
            "preview": f"\n🤖 Autopilot: no reply by {when}? I'll schedule it."}[kind]


# ---------- buttons & undo ----------
REEL_KEYS = ["stage", "candidates", "choose_deadline", "topic", "draft", "video_file_id", "voice_file_id",
             "voice_mode", "voice_gender", "user_image_id", "user_video_id", "script_deadline", "preview_deadline",
             "pending_topic"]


def tok(s):
    """Short fingerprint of what's on screen now, so old buttons can't act on a newer reel."""
    stage = s["stage"]
    item = {"choosing": [c.get("title") for c in s.get("candidates") or []],
            "awaiting_voice": (s.get("draft") or {}).get("script"),
            "awaiting_approval": s.get("video_file_id"),
            "idle": [s.get("pending_topic"), (s.get("queue") or [{}])[0].get("video_file_id")]}.get(stage, stage)
    return hashlib.md5(json.dumps(item).encode()).hexdigest()[:6]


def btn(s, label, action, any_stage=False):
    return (label, f"any||{action}" if any_stage else f"{s['stage']}|{tok(s)}|{action}")


def story_buttons(s):
    n = len(s.get("candidates") or [])
    return [[btn(s, f"{i} 📰", str(i)) for i in range(1, n + 1)],
            [btn(s, "🔄 New stories", "/news", True), btn(s, "⏭ Skip", "/skip", True)]]


def script_buttons(s):
    return [[btn(s, "🤖 AI voice", "ok"), btn(s, "👨 Male", "ok male"), btn(s, "👩 Female", "ok female")],
            [btn(s, "↩️ Undo", "/undo", True), btn(s, "⏭ Skip", "/skip", True)]]


def preview_buttons(s):
    if (s.get("topic") or {}).get("extra"):  # your own story: posting it now doesn't touch the regular slots
        return [[btn(s, "🚀 Post now (extra)", "post now"), btn(s, f"🗓 Use a slot ({fmt_time(next_post_time(s))})", "post")],
                [btn(s, "🔁 New voice", "redo"), btn(s, "↩️ Undo", "/undo", True), btn(s, "⏭ Skip", "/skip", True)]]
    return [[btn(s, f"✅ Schedule ({fmt_time(next_post_time(s))})", "post"), btn(s, "🚀 Post now", "post now")],
            [btn(s, "🔁 New voice", "redo"), btn(s, "↩️ Undo", "/undo", True), btn(s, "⏭ Skip", "/skip", True)]]


def after_schedule_buttons(s):
    return [[btn(s, "↩️ Undo", "/undo", True), btn(s, "📰 Next reel", "/news", True)]]


def push_undo(s, label):
    snap = {"label": label[:80], "data": copy.deepcopy({k: s.get(k) for k in REEL_KEYS})}
    s["undo_stack"] = (s.get("undo_stack") or [])[-4:] + [snap]


def mark_undo(s, **info):
    if s.get("undo_stack"):
        s["undo_stack"][-1].update(info)


def stories_text(s):
    lines = ["📰 Top AI stories right now:\n"]
    for i, p in enumerate(s["candidates"], 1):
        lines.append(f"{i}) {p['title']}\n   {p['source']}" + (f" · {p['angle']}" if p.get("angle") else "") +
                     (f"\n   🔗 {p['link']}" if p.get("link") else ""))
    when = (datetime.fromisoformat(s["choose_deadline"]).strftime("%I:%M %p").lstrip("0")
            if s.get("choose_deadline") else "")
    lines.append("\nTap a story, or type your own topic." + (f"\nNo reply by {when}? I'll go with #1." if when else ""))
    return "\n".join(lines)


def show_current(s):
    """Re-sends whatever you need to act on now (used after Undo)."""
    stage = s["stage"]
    if stage == "choosing" and s.get("candidates"):
        tg.send(stories_text(s), buttons=story_buttons(s))
    elif stage == "awaiting_voice" and s.get("draft"):
        tg.send(script_message(s["draft"]), buttons=script_buttons(s))
    elif stage == "awaiting_approval":
        tg.send("Your preview is back (scroll up to watch it). What would you like to do?", buttons=preview_buttons(s))
    else:
        tg.send("Nothing in progress now. Send a topic, or tap below for fresh stories.",
                buttons=[[btn(s, "📰 Get stories", "/news", True)]])


def undo(s):
    stack = s.get("undo_stack") or []
    if not stack:
        tg.send("Nothing to undo right now.")
        return
    snap = stack.pop()
    live = snap.get("irreversible") or (snap.get("remove_from_queue") in (s.get("posted_ids") or []))
    if live:
        tg.send("🚫 That reel is already live on Instagram, so I can't undo it. "
                "You can delete it from the Instagram app if you need to.")
        return
    if snap.get("remove_from_queue"):
        s["queue"] = [q for q in s["queue"] if q["video_file_id"] != snap["remove_from_queue"]]
        if snap.get("history_title") and s["history"] and s["history"][-1] == snap["history_title"]:
            s["history"].pop()
    s.update(snap["data"])
    if s["stage"] == "rendering":
        s["stage"] = "awaiting_voice"
    auto = s.get("autopilot")
    s["script_deadline"] = deadline() if auto and s["stage"] == "awaiting_voice" else None
    s["preview_deadline"] = deadline() if auto and s["stage"] == "awaiting_approval" else None
    if s["stage"] == "choosing":
        s["choose_deadline"] = (st.now() + timedelta(hours=AUTO_PICK_HOURS)).isoformat()
    tg.send(f"↩️ Undone: {snap['label']}")
    show_current(s)


def ask_post_now(s, title):
    tg.send(f"🚀 Post \"{title}\" to Instagram right now?\nThis can't be undone once it's live.",
            buttons=[[btn(s, "🚀 Yes, post now", "postnow_yes"), btn(s, "✖️ Cancel", "cancel", True)]])


def post_next_now(s):
    if not s["queue"]:
        tg.send("There's nothing scheduled to post.")
        return
    item = s["queue"].pop(0)
    tg.send(f"📤 Posting \"{item['title']}\" now... (1-3 minutes)")
    try:
        link = publish_item(item)
        s["posted_ids"] = ((s.get("posted_ids") or []) + [item["video_file_id"]])[-30:]
        record_post(s, item.get("extra"))
        mark_undo(s, irreversible=True)
        tg.send(f"✅ Posted! {link}")
    except Exception as e:
        s["queue"].insert(0, item)
        tg.send(f"⚠️ Couldn't post it: {e}\nIt's still scheduled, so I'll try again at its posting time.")


def use_ai_voice(s, req="alternate", auto=False):
    gender = req if req in ("male", "female") else ("male" if s.get("last_gender") == "female" else "female")
    s.update(voice_mode="ai", voice_gender=gender, voice_file_id=None, stage="rendering", script_deadline=None)
    prefix = "⏰ No reply, so autopilot is taking over. " if auto else ""
    tg.send(f"{prefix}🤖 Making the reel with a {gender} AI voice. Preview coming in a few minutes.")


def reset_reel(s):
    s.update(stage="idle", draft=None, topic=None, video_file_id=None, voice_file_id=None,
             voice_mode=None, user_image_id=None, user_video_id=None, candidates=[], choose_deadline=None,
             script_deadline=None, preview_deadline=None)


def next_offer_if_waiting(s):
    if s.get("pending_offer"):
        s["pending_offer"] = False
        offer_news(s)


def park_reel(s):
    """A flagged reel is set aside for your review so it doesn't block the next reels."""
    now_iso = st.now().isoformat()
    s["held"] = [h for h in (s.get("held") or []) if st.now() - datetime.fromisoformat(h["held_at"]) < timedelta(hours=24)]
    s["held"].append({"topic": s["topic"], "draft": s["draft"], "video_file_id": s["video_file_id"],
                      "voice_mode": s.get("voice_mode"), "held_at": now_iso})
    title = s["topic"]["title"]
    reasons = (s["draft"].get("fact_notes") or []) + (s["draft"].get("visual_notes") or [])
    links = sources_block(s)
    reset_reel(s)
    tg.send(esc(f"⏸ Parked for your review: “{title}”.\nWhy:\n• " + "\n• ".join(reasons or ["quality check"])) +
            links + esc("\nAutopilot won't post it — "
            "but the next reels carry on as normal. Review it anytime (parked reels are kept for 24 hours)."), html=True,
            buttons=[[btn(s, f"👀 Review parked reels ({len(s['held'])})", "/held", True)]])
    whatsapp.alert(f"⏸ A reel is parked for your review: {title}. Open Telegram → /held")
    next_offer_if_waiting(s)


def review_held(s):
    held = [h for h in (s.get("held") or []) if st.now() - datetime.fromisoformat(h["held_at"]) < timedelta(hours=24)]
    s["held"] = held
    if not held:
        tg.send("No parked reels right now 👍")
        return
    if s["stage"] not in ("idle", "choosing"):
        tg.send("Finish or ⏭ Skip the current reel first, then send /held to review the parked one.")
        return
    h = held.pop(0)
    push_undo(s, "reviewing a parked reel")
    reset_reel(s)
    s.update(topic=h["topic"], draft=h["draft"], video_file_id=h["video_file_id"], voice_mode=h.get("voice_mode"),
             stage="awaiting_approval", preview_deadline=None)
    s["draft"]["fact_status"] = "reviewed" if s["draft"].get("fact_status") == "unsure" else s["draft"].get("fact_status")
    s["draft"]["visual_status"] = "reviewed" if s["draft"].get("visual_status") == "issues" else s["draft"].get("visual_status")
    notes = (h["draft"].get("fact_notes") or []) + (h["draft"].get("visual_notes") or [])
    tg.send_video_id(h["video_file_id"], caption=f"👀 Parked reel: {h['topic']['title']}")
    tg.send(esc("What the quality check flagged:\n• " + "\n• ".join(notes or ["(no details)"])) + sources_block(s) +
            esc("\n\nIf it's fine, tap ✅ Schedule. You can also type changes to the script, or ⏭ Skip it." +
                (f"\n\n{len(held)} more parked." if held else "")), buttons=preview_buttons(s), html=True)


def fact_check_step(draft, topic):
    """Checkpoint 1: every claim verified with Google Search before anything is voiced or rendered."""
    tg.action("typing")
    draft, status, notes = writer.fact_check(draft, topic)
    draft["fact_status"], draft["fact_notes"] = status, notes
    return draft


def resolve_links(urls, limit=4):
    """Readable source links: follows redirect links (like Gemini's search links) to the real page."""
    import requests
    out = []
    for u in urls:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        final = news.real_url(u)
        if "grounding-api-redirect" in u or "vertexaisearch" in u:
            try:
                final = requests.get(u, timeout=8, allow_redirects=True, stream=True,
                                     headers={"User-Agent": "Mozilla/5.0"}).url
            except Exception:
                pass
        if final not in out:
            out.append(final)
        if len(out) >= limit:
            break
    return out


def esc(text):
    import html
    return html.escape(text or "", quote=False)


def link_label(url, topic):
    from urllib.parse import urlparse
    if topic and url == topic.get("link"):
        who = topic.get("source") or urlparse(url).netloc.replace("www.", "")
        return f"{who}: {topic.get('title', '')[:60]}"
    host = urlparse(url).netloc.replace("www.", "")
    return "Google News article" if "news.google." in host else host


def sources_block(s):
    """Short, tappable source names (the long addresses stay hidden behind the names)."""
    import html
    links = (s.get("draft") or {}).get("source_links") or []
    if not links:
        return ""
    rows = [f'{k}. <a href="{html.escape(u, quote=True)}">{html.escape(link_label(u, s.get("topic")))}</a>'
            for k, u in enumerate(links, 1)]
    return "\n\n🔗 Sources (tap to open):\n" + "\n".join(rows)


def fact_line(draft):
    status, notes = draft.get("fact_status"), draft.get("fact_notes") or []
    if status == "ok":
        n = len(draft.get("evidence") or [])
        return f"🔎 Fact check: ✅ all {n} claims proven with quotes from the sources" if n else "🔎 Fact check: ✅ verified"
    if status == "fixed":
        return "🔎 Fact check: ✏️ corrected before writing this:\n• " + "\n• ".join(notes)
    if status == "unsure":
        return ("🔎 Fact check: ⚠️ these couldn't be verified:\n• " + "\n• ".join(notes or ["unverified claims"]))
    if status == "kept":
        return "🔎 Fact check: ⚠️ you chose to keep unverified claims"
    return "🔎 Fact check: couldn't run (Gemini unavailable) — autopilot won't post this until it's verified"


def qa_hold(draft):
    """The final gate: autopilot only posts reels whose every claim was proven and that name who they're about."""
    return (draft.get("fact_status") not in ("ok", "kept", "reviewed") or draft.get("visual_status") == "issues"
            or bool(draft.get("vague_notes")))


MAX_FIX_ROUNDS = 2


def checked_script(topic, previous=None, instruction=None):
    """Writes the script, fact-checks it, and if something is wrong rewrites it to fix the problem and checks
    again (up to MAX_FIX_ROUNDS times). Returns the draft; draft['fact_status'] says how it ended."""
    draft = writer.write_script(topic, previous=previous, instruction=instruction)
    draft = fact_check_step(draft, topic)
    rounds = 0
    while draft.get("fact_status") == "unsure" and rounds < MAX_FIX_ROUNDS:
        rounds += 1
        problems = draft.get("fact_notes") or ["some claims couldn't be verified"]
        tg.send(f"🔎 Fact check found a problem (attempt {rounds}/{MAX_FIX_ROUNDS}), fixing it:\n• " + "\n• ".join(problems))
        fix = ("Fix these fact-check problems: " + " | ".join(problems) +
               ". Correct wrong claims to exactly what the source says. REMOVE every claim that has no source, and "
               "replace it with another fact the source article DOES state, so the script stays 75-105 words. "
               "Only keep facts stated in the source article.")
        draft = writer.write_script(topic, previous=draft, instruction=fix)
        draft = fact_check_step(draft, topic)
    draft["fix_rounds"] = rounds
    draft = make_specific(draft, topic)
    return specific_facts_step(substance_step(draft, topic), topic)


def specific_facts_step(draft, topic):
    """Owner (2026-10-09): "Always strictly mention the company, name, facts, do not generalise". A script must name
    at least two real names (company, product, person, place) and give a number or date. One rewrite, else skipped."""
    if draft.get("fact_status") == "unsure":
        return draft
    names, has_num = writer.specificity(draft.get("script", ""))
    vague = writer.vague_phrases(draft.get("script", ""))
    if len(names) >= 2 and has_num and not vague:
        return draft
    missing = ([] if len(names) >= 2 else ["the exact company/product/person names"]) + \
              ([] if has_num else ["the key number or date"]) + ([f"vague: {', '.join(vague)}"] if vague else [])
    tg.send("🎯 The script is too general (" + "; ".join(missing) + "). Rewriting with the exact names and facts...")
    fix = ("Be strictly specific. Name the exact company, product or model, and the people involved with their roles; "
           "give the key numbers and dates from the source. Replace every general phrase (" + "; ".join(missing) +
           ") with the real name or fact. Never generalise. Keep every fact true and sourced.")
    try:
        better = fact_check_step(writer.write_script(topic, previous=draft, instruction=fix), topic)
    except Exception as e:  # Gemini busy: never crash the run
        print(f"Specificity rewrite failed: {e}")
        better = {"fact_status": "unsure"}
    names2, num2 = writer.specificity(better.get("script", ""))
    # names and no vague phrases are a must; a number is asked for, but some true stories simply have none
    if better.get("fact_status") != "unsure" and len(names2) >= 2 and \
            len((better.get("script") or "").split()) >= FLOOR_WORDS and not writer.vague_phrases(better.get("script", "")):
        return better
    if len(names) >= 2 and not vague and draft.get("fact_status") != "unsure":  # rewrite failed, original was fine
        return draft
    draft["fact_status"] = "unsure"
    draft["fact_notes"] = ["too general: " + "; ".join(missing)]
    return draft


MIN_WORDS = 65   # below this a reel feels empty (owner, 2026-10-09: "scripts are getting so bad, not very short")
FLOOR_WORDS = 50  # after one expansion attempt, anything shorter isn't worth a reel: the story is skipped


def substance_step(draft, topic):
    """A reel must say something: too-thin scripts get one rewrite with more verified detail; if the sources still
    don't have enough, the story is skipped (autopilot moves to the next one)."""
    if draft.get("fact_status") == "unsure":
        return draft
    n = len((draft.get("script") or "").split())
    if n >= MIN_WORDS:  # the writer's own "thin" flag is too cautious; the word count and fact check decide
        return draft
    tg.send(f"📝 The script is too thin ({n} words). Adding verified detail from the sources...")
    fix = ("The script is too thin. Expand it to 75-105 words using ONLY facts from the source article and your search "
           "results: what exactly it is, how it works, the key numbers, who is involved, what came before, and why it "
           "matters to the viewer. Every sentence must add a new concrete fact. Never write lines like 'X reported on "
           "it' or 'the publication discussed'. Keep every fact true.")
    try:
        better = fact_check_step(writer.write_script(topic, previous=draft, instruction=fix), topic)
    except Exception as e:  # Gemini busy: never crash the run; this story is skipped instead
        print(f"Expansion failed: {e}")
        better = {"fact_status": "unsure"}
    m = len((better.get("script") or "").split())
    if better.get("fact_status") != "unsure" and m >= FLOOR_WORDS:
        better["fix_rounds"] = draft.get("fix_rounds", 0)
        return make_specific(better, topic)
    draft["fact_status"] = "unsure"
    draft["fact_notes"] = [f"not enough verified detail for a full reel ({max(n, m)} words)"]
    return draft


def make_specific(draft, topic):
    """No vague 'a developer' / 'a startup': find the real names and rewrite with them (and their photo cards)."""
    phrases = writer.vague_phrases(draft.get("script", ""))
    if not phrases:
        return draft
    tg.send("🧐 The script is too general (" + ", ".join(f"“{p}”" for p in phrases) + ") — finding the actual names...")
    names = writer.find_names(topic, phrases, draft["script"])
    found = [n for n in names if n.get("found") and n.get("name")]
    missing = [n.get("phrase", "") for n in names if not (n.get("found") and n.get("name"))] or \
              [p for p in phrases if not any(p == n.get("phrase") for n in found)]
    if found:
        fix = ("Replace the vague references with these exact names and roles: " +
               "; ".join(f"“{n['phrase']}” → {n['name']} ({n.get('role', '')})" for n in found) +
               ". Give each named person a 'person' beat with their name and role. Keep everything else.")
        draft = writer.write_script(topic, previous=draft, instruction=fix)
        draft = fact_check_step(draft, topic)
        tg.send("✅ Named: " + "; ".join(f"{n['name']} ({n.get('role', '')})" for n in found))
    still = writer.vague_phrases(draft.get("script", ""))
    if still or (missing and not found):
        draft["vague_notes"] = still or missing
        tg.send("⚠️ I couldn't find who these are: " + ", ".join(f"“{p}”" for p in (still or missing)) +
                ". If you know, just reply with the name (e.g. “the developer is <name>, founder of <company>”).")
    return draft


def next_story(s, reason=""):
    """Moves on to another story when this one can't be verified, so the posting slot still gets a reel."""
    tried = set(s.get("tried") or []) | {(s.get("topic") or {}).get("title", "")}
    s["tried"] = list(tried)[-30:]
    spare = [c for c in (s.get("spare") or []) if not news.recent_match(c.get("title", ""), list(tried) + recent_titles(s))]
    if not spare:
        heads = news.dedupe(news.fetch_headlines(), recent_titles(s) + list(tried))
        spare = writer.pick_top(heads, s["history"]) if heads else []
    if not spare:
        tg.send("⚠️ I couldn't find another story to switch to. Send /news or a topic.")
        reset_reel(s)
        return
    pick, s["spare"] = spare[0], spare[1:]
    tg.send(f"➡️ Switching to another story{(' — ' + reason) if reason else ''}:\n{pick['title']}")
    start_script(s, pick, auto=True)


def recent_events(s):
    """What we covered in the last 14 days: titles plus what each reel actually said (more precise than titles)."""
    cutoff = st.now() - timedelta(days=14)
    out = []
    for h in s.get("posted_log") or []:
        if datetime.fromisoformat(h["at"]) > cutoff:
            out.append(h["title"] + (f" — said: {h['event']}" if h.get("event") else ""))
    out += [q["title"] for q in s.get("queue") or []] + [h["topic"]["title"] for h in s.get("held") or []]
    return out


def is_repeat(s, topic):
    """The last check before a story is written: is it the same news event as anything posted, queued or parked in
    the last 14 days? Word match first (works offline), then the same-event check on titles + what we said."""
    past = recent_events(s)
    hit = news.recent_match(topic.get("title", ""), [p.split(" — said: ")[0] for p in past])
    if hit:
        return hit
    try:
        return writer.same_event(topic, past)
    except Exception as e:
        print(f"Same-event gate skipped: {e}")
        return None


def start_script(s, topic, instruction=None, auto=False):
    if not instruction and not topic.get("extra") and not topic.get("custom") and not topic.get("digest"):
        repeat = is_repeat(s, topic)
        if repeat:
            tg.send(f"🔁 Skipping a repeat: “{topic['title'][:80]}” is the same news as “{repeat[:80]}”.")
            s["tried"] = ((s.get("tried") or []) + [topic.get("title", "")])[-60:]
            if auto or s.get("autopilot"):
                next_story(s, "the last one was a repeat")
            return
    tg.action("typing")
    tg.send("✍️ Revising the script..." if instruction else f"✍️ Writing a script about: {topic['title']}")
    draft = checked_script(topic, previous=s.get("draft") if instruction else None, instruction=instruction)
    if topic.get("research_sources"):  # official page + articles found by research → images & credits
        draft["sources"] = list(dict.fromkeys(topic["research_sources"] + list(draft.get("sources") or [])))
    draft["source_links"] = resolve_links([topic.get("link", "")] + list(draft.get("sources") or []))
    image = s.get("user_image_id") if instruction else None
    clip = s.get("user_video_id") if instruction else s.pop("next_video_id", None)
    reset_reel(s)
    s.update(topic=topic, draft=draft, stage="awaiting_voice", user_image_id=image, user_video_id=clip,
             script_deadline=deadline())
    if clip and not instruction:
        tg.send("🎥 Using the clip you sent as the opening shot.")
    if draft.get("fact_status") == "unsure":
        tg.send(esc(script_message(draft) + "\n\n" + fact_line(draft)) + sources_block(s) +
                esc("\n\nI couldn't fix this after checking twice." +
                    (" Autopilot will switch to another story." if s.get("autopilot") else "")), html=True,
                buttons=[[btn(s, "➡️ Next story", "/nextstory"), btn(s, "Keep anyway", "/keepscript")],
                         [btn(s, "⏭ Skip", "/skip", True)]])
        if auto and s.get("autopilot"):
            next_story(s, "the facts couldn't be verified")
        return
    tg.send(esc(script_message(draft) + "\n\n" + fact_line(draft)) + sources_block(s) +
            esc(autopilot_note("script") if s.get("autopilot") else ""), buttons=script_buttons(s), html=True)


def recent_titles(s):
    """Stories posted, queued, parked or already tried in the last 14 days."""
    cutoff = st.now() - timedelta(days=14)
    log = [h for h in (s.get("posted_log") or []) if datetime.fromisoformat(h["at"]) > cutoff]
    s["posted_log"] = log
    return ([h["title"] for h in log] + list(s.get("history") or []) + [q["title"] for q in s.get("queue") or []]
            + [h["topic"]["title"] for h in s.get("held") or []] + list(s.get("tried") or []))


def offer_news(s):
    tg.action("typing")
    headlines = news.dedupe(news.fetch_headlines(), recent_titles(s))
    s["feed_report"] = {"at": st.now().isoformat(timespec="minutes"), **news.LAST_REPORT}
    used = recent_titles(s)
    if len(headlines) < 3:  # with many reels a day the last 36 hours can run dry: look back 4 days
        older = news.dedupe(news.fetch_headlines(max_age_hours=96, limit=120), used)
        headlines = news.dedupe(headlines + older, [])
    if not headlines:
        reset_reel(s)
        tg.send("I couldn't find fresh AI news right now. Send me any topic and I'll write a script.")
        return
    picks = writer.drop_same_events(news.dedupe(writer.pick_top(headlines, used), []), used)
    for p in picks:
        p["link"] = news.real_url(p.get("link", ""))
    reset_reel(s)
    s.update(candidates=picks, stage="choosing",
             choose_deadline=(st.now() + timedelta(hours=AUTO_PICK_HOURS)).isoformat())
    tg.send(stories_text(s), buttons=story_buttons(s))
    whatsapp.alert("📰 New AI stories are ready! Open Telegram to pick one for your next reel.")


PASTE_MIN = 180  # a message this long (a paragraph or more) is treated as pasted news


def pasted_news(text):
    """A story from news text you pasted (e.g. copied from WhatsApp): first line = headline, the rest = details."""
    text = re.sub(r"[*_~]", "", text).strip()  # WhatsApp formatting marks
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    first = lines[0] if lines else text
    headline = re.split(r"(?<=[.!?])\s", first)[0][:140]
    headline = re.sub(r"(?i)^(big news|breaking|update|news)\s*[:\-–]\s*", "", headline)
    src = re.search(r"(?im)^\s*(?:via|source|from|—|-)\s*[:\-]?\s*([A-Za-z][\w .&'’-]{1,38})\s*$", text)
    return {"title": headline, "summary": text[:1500], "source": src.group(1).strip() if src else "", "link": "",
            "published": "", "pasted": True}


REQUEST_WORDS = re.compile(r"(?i)^\s*(please\s+)?(give|make|tell|show|create|do|post|write|explain|cover|share|find|"
                           r"what|news about|latest|recent|trending)\b|\bnews (about|on)\b|\breel (about|on)\b")


def researched_story(text):
    """Researches news or a request before making the reel. Returns the story, or None if there's nothing to make."""
    tg.send("🔎 Researching this story — finding the original article, the official announcement and the full facts...")
    tg.action("typing")
    found = writer.research(text)
    if found and found.get("not_found") and REQUEST_WORDS.search(text):
        names = found.get("unknown_names") or []
        tg.send("⚠️ I couldn't find news for that request" + (f" — I couldn't identify: {', '.join(names)}" if names else "") +
                ".\n\nSend it again with the exact names (and the company, if you know it), e.g.\n"
                "/reel news about the Laya model by <company>\n\nOr make a roundup of this week's trending models instead:",
                buttons=[[("📰 Trending models roundup", "any||/reel the biggest new AI model releases this week")]])
        return None
    if found and found.get("not_found"):
        tg.send("⚠️ I couldn't find any real coverage of this news online, so it may be unconfirmed. "
                "I'll still make the reel from your text, and the fact check will flag anything it can't verify.")
        return pasted_news(text)
    if not found:
        if REQUEST_WORDS.search(text):
            tg.send("⚠️ Search isn't available right now (Google's free search limit), so I can't research this yet. "
                    "Try /reel again in a little while.")
            return None
        tg.send("Search isn't available right now, so I'll use your text (the fact check still runs).")
        return pasted_news(text)
    msg = f"📰 Found it ({found.get('via', 'Google Search')}): {found['title']}"
    if found.get("unknown_names"):
        msg += f"\n❓ Couldn't identify: {', '.join(found['unknown_names'])} (send the exact name to include it)"
    if found.get("source"):
        msg += f"\nMain source: {found['source']}"
    if found.get("corrections"):
        msg += "\n\n✏️ Corrected from your message:\n• " + "\n• ".join(found["corrections"])
    if found.get("research_sources"):
        msg += "\n\n🔗 " + "\n🔗 ".join(found["research_sources"][:3])
    tg.send(msg)
    return found


def custom(text):
    return {"title": text.strip(), "custom": True}


def caption_for(draft, ai_voice=False):
    note = f"\n\n{AI_VOICE_NOTE}" if ai_voice and AI_VOICE_NOTE else ""
    credits = list(dict.fromkeys(draft.get("credits") or []))  # no duplicates
    credit_text = ("\n\n📷 " + " · ".join(credits))[:600] if credits else ""
    follow = f"\n\nFollow @{HANDLE.lstrip('@')} for daily AI news ⚡" if HANDLE else ""
    return (draft["caption"] + follow + note + credit_text + "\n\n" +
            " ".join(f"#{h}" for h in draft["hashtags"]))


# ---------- scheduling & posting ----------
# ---------- the 6-a-day guarantee ----------
def slots_on(day):
    now = st.now()
    return [datetime(day.year, day.month, day.day, *map(int, t.split(":")), tzinfo=now.tzinfo) for t in sorted(POST_TIMES)]


def posted_today(s):
    """Scheduled reels that are really on Instagram today. Counted on Instagram itself (checked at most every
    10 minutes), so a reel that was deleted or failed counts as missing and gets replaced."""
    now = st.now()
    today = now.date().isoformat()
    mine = [p for p in (s.get("post_log") or []) if p["at"][:10] == today]
    extras = sum(1 for p in mine if p.get("extra"))
    cache = s.get("ig_count") or {}
    fresh = cache.get("day") == today and now - datetime.fromisoformat(cache["at"]) < timedelta(minutes=10)
    if not fresh and IG_READY():
        import instagram
        n = instagram.reels_posted_on(now.date(), now.tzinfo)
        if n is not None:
            cache = {"day": today, "at": now.isoformat(), "count": n}
            s["ig_count"] = cache
    if (cache.get("day") == today and "count" in cache
            and now - datetime.fromisoformat(cache["at"]) < timedelta(minutes=30)):  # never trust a stale count
        # reels posted since the last Instagram check are added on top
        since = datetime.fromisoformat(cache["at"])
        recent = sum(1 for p in mine if datetime.fromisoformat(p["at"]) > since)
        return max(0, cache["count"] + recent - extras)
    return len(mine) - extras


def IG_READY():
    from config import IG_ACCESS_TOKEN, IG_USER_ID
    return bool(IG_ACCESS_TOKEN and IG_USER_ID)


def record_post(s, extra=False):
    s["post_log"] = ((s.get("post_log") or []) + [{"at": st.now().isoformat(), "extra": bool(extra)}])[-60:]


def behind_today(s):
    """How many of today's past slots went without a reel (not counting reels already queued to catch up)."""
    now = st.now()
    start = datetime.fromisoformat(s.setdefault("guarantee_since", now.isoformat()))
    passed_slots = sum(1 for t in slots_on(now.date()) if start < t <= now)
    queued_now = sum(1 for q in s["queue"] if datetime.fromisoformat(q["post_at"]) <= now and not q.get("extra"))
    return max(0, passed_slots - posted_today(s) - queued_now)


def next_unfilled(s):
    """The next moment a reel is needed: now (if behind) or the next slot today that has nothing queued."""
    now = st.now()
    if behind_today(s):
        return now
    taken = {q["post_at"][:16] for q in s["queue"]}
    return next((t for t in slots_on(now.date()) if t > now and t.isoformat()[:16] not in taken), None)


def next_post_time(s):
    now = st.now()
    if behind_today(s):  # a slot was missed today: post as soon as this reel is ready
        return now + timedelta(minutes=1)
    taken = {q["post_at"][:16] for q in s["queue"]}
    for day in range(0, 7):
        date = (now + timedelta(days=day)).date()
        for t in sorted(POST_TIMES):
            h, m = map(int, t.split(":"))
            dt = datetime(date.year, date.month, date.day, h, m, tzinfo=now.tzinfo)
            if dt > now and dt.isoformat()[:16] not in taken:
                return dt
    return now


def publish_item(item):
    import instagram
    os.makedirs(WORK_DIR, exist_ok=True)
    path = tg.download(item["video_file_id"], os.path.join(WORK_DIR, "final.mp4"))
    link = instagram.publish_reel(path, item["caption"])
    try:
        import insights
        insights.remember_reel(link, {**(item.get("meta") or {}), "posted": st.now().isoformat(timespec="minutes")})
    except Exception as e:
        print(f"Couldn't save reel details: {e}")
    return link


MAJOR_OUTLETS = re.compile(r"(?i)verge|techcrunch|wired|reuters|bloomberg|ars ?technica|venturebeat|cnbc|axios|"
                           r"engadget|technology review|financial times|wall street|wsj|new york times|bbc|guardian|"
                           r"the information|zdnet|cbs|nbc|associated press|ap news|openai|anthropic|google|deepmind|nvidia|microsoft|meta|hacker news")


def clean_headline(title):
    """'Big news | Newswise' → 'Big news' (the outlet is credited separately)."""
    return re.sub(r"\s+[|–—]\s+[^|–—]{2,40}$", "", title or "").strip() or title


def digest_rank(heads):
    """Backup reels show the strongest stories: clearly about AI, from a major outlet or the company itself."""
    def score(h):
        return ((2 if news.AI_WORDS.search(h["title"]) else 0)
                + (3 if MAJOR_OUTLETS.search(h.get("source", "")) else 0))
    return sorted(heads, key=score, reverse=True)  # stable: newest first among equals


def digest_draft(heads):
    """Three headlines read as they are (accurate by construction); each shows its outlet's card on screen."""
    beats = [{"line": "Here are today's top AI headlines.", "visual": "image", "tag": "3 AI stories today",
              "prompt": "abstract futuristic news studio with glowing screens, blue light"}]
    for h in heads[:3]:
        src = re.sub(r"\s*[|:–-].*$", "", h.get("source") or "").strip() or "the news"
        title = clean_headline(h["title"]).rstrip(".")
        beats.append({"line": f"{title}.",
                      "visual": "source", "outlet": src, "headline": title[:120], "domain": ""})
    beats.append({"line": "Which of these matters most to you?", "visual": "image", "tag": "Which matters most?",
                  "prompt": "abstract glowing network of connected nodes, blue and purple"})
    def outlet(h):
        return re.sub(r"\s*[|:–-].*$", "", h.get("source") or "").strip() or "news"
    listing = "\n".join("• " + clean_headline(h["title"]) + " (" + outlet(h) + ")" for h in heads[:3])
    draft = writer.normalize_draft({"title": "Today's top AI headlines", "hook_text": "Today's top AI headlines",
                                    "beats": beats, "caption": f"Today's top AI headlines:\n{listing}\n\n"
                                    "Which one matters most to you? 👇",
                                    "hashtags": ["ai", "ainews", "artificialintelligence", "technews", "tech"],
                                    "sources": [h.get("link", "") for h in heads[:3]]},
                                   {"title": "Today's top AI headlines"})
    draft.update(fact_status="ok", fact_notes=[], evidence=[{"claim": b["line"], "url": ""} for b in beats[1:4]])
    return draft


def emergency_reel(s):
    """Nothing ready and a slot is close: make an attributed-headlines reel right away."""
    fresh = news.fetch_headlines(max_age_hours=96, limit=120)
    heads = digest_rank(news.dedupe(fresh, recent_titles(s)))[:3]
    if len(heads) < 2:  # few "new" stories: any headline not used word-for-word before will do
        used = set(recent_titles(s))
        heads = digest_rank([h for h in fresh if h["title"] not in used])[:3]
    if len(heads) < 2:
        return False
    if s["stage"] not in ("idle", "choosing") and not s.get("paused"):
        s["paused"] = copy.deepcopy({k: s.get(k) for k in REEL_KEYS})
    reset_reel(s)
    topic = {"title": f"Top AI headlines · {fmt_time(st.now())}", "custom": False, "digest": True,
             "source": "", "published": st.now().isoformat()}
    s["tried"] = ((s.get("tried") or []) + [h["title"] for h in heads])[-60:]  # never the same headlines twice
    s.update(topic=topic, draft=digest_draft(heads), stage="rendering", voice_mode="ai",
             voice_gender="male" if s.get("last_gender") == "female" else "female")
    tg.send("⏱ A post time is close and no reel is ready, so I'm making a quick “top AI headlines” reel "
            "(every line credits its source) to keep the schedule. The reel I was working on continues after.")
    return True


def extra_reel(s, topic):
    """Your own story or link, made right away. A regular reel in progress is paused and resumes afterwards."""
    topic = {**topic, "extra": True}
    if s["stage"] == "rendering":
        tg.send("I'm in the middle of making a video — send it again in a few minutes and I'll start your reel.")
        return
    if s["stage"] != "idle" and not s.get("paused"):
        s["paused"] = copy.deepcopy({k: s.get(k) for k in REEL_KEYS})
        tg.send(f"⏸ Pausing the current reel (“{(s.get('topic') or {}).get('title', 'story list')[:60]}”) — "
                "it'll continue right after yours. The regular schedule isn't affected.")
    reset_reel(s)
    start_script(s, topic)


def resume_paused(s):
    paused = s.pop("paused", None)
    if not paused:
        return False
    s.update(paused)
    auto = s.get("autopilot")
    if s["stage"] == "rendering":
        s["stage"] = "awaiting_voice"
    s["script_deadline"] = deadline() if auto and s["stage"] == "awaiting_voice" else None
    s["preview_deadline"] = deadline() if auto and s["stage"] == "awaiting_approval" else None
    if s["stage"] == "choosing":
        s["choose_deadline"] = (st.now() + timedelta(hours=AUTO_PICK_HOURS)).isoformat()
    tg.send("▶️ Back to the reel that was paused:")
    show_current(s)
    return True


def reel_meta(s):
    """What we know about this reel, so its views can later be compared by these features."""
    t, d = s.get("topic") or {}, s.get("draft") or {}
    beats = d.get("beats") or []
    kind = "headlines" if t.get("digest") else "extra" if t.get("extra") else "explainer" if t.get("custom") else "news"
    return {"title": t.get("title", "")[:120], "kind": kind, "source": t.get("source", "")[:40],
            "engine": (s.get("engine_used") or s.get("last_engine")) if s.get("voice_mode") == "ai" else "own voice",
            "voice": d.get("voice_used", "")[:60], "person": any(b.get("visual") == "person" for b in beats),
            "words": len(d.get("script", "").split()), "visuals": d.get("visual_summary", "")[:80],
            "editor": (d.get("editor") or {}).get("overall"), "writer": d.get("writer_model", ""),
            "made": st.now().isoformat(timespec="minutes")}


def approve(s, now_please=False):
    item = {"title": s["topic"]["title"], "video_file_id": s["video_file_id"],
            "caption": caption_for(s["draft"], s.get("voice_mode") == "ai"),
            "extra": bool((s.get("topic") or {}).get("extra")), "meta": reel_meta(s)}
    s["history"] = (s["history"] + [item["title"]])[-100:]
    said = " ".join((s["draft"].get("script") or "").split())[:240]
    s["posted_log"] = (s.get("posted_log") or []) + [{"title": item["title"], "at": st.now().isoformat(),
                                                      "event": said}]
    if now_please:
        tg.send("📤 Posting to Instagram now... (1-3 minutes)")
        link = publish_item(item)
        s["posted_ids"] = ((s.get("posted_ids") or []) + [item["video_file_id"]])[-30:]
        record_post(s, (s.get("topic") or {}).get("extra"))
        mark_undo(s, irreversible=True)
        reset_reel(s)
        tg.send(f"✅ Posted! {link}")
    else:
        when = next_post_time(s)
        item["post_at"] = when.isoformat()
        s["queue"].append(item)
        mark_undo(s, remove_from_queue=item["video_file_id"], history_title=item["title"])
        reset_reel(s)
        tg.send(f"🗓 Scheduled for {fmt_time(when)}.", buttons=after_schedule_buttons(s))
    if not resume_paused(s):
        next_offer_if_waiting(s)


def post_due(s):
    now = st.now()
    for item in list(s["queue"]):
        if datetime.fromisoformat(item["post_at"]) > now:
            continue
        try:
            link = publish_item(item)
            s["queue"].remove(item)
            s["posted_ids"] = ((s.get("posted_ids") or []) + [item["video_file_id"]])[-30:]
            record_post(s, item.get("extra"))
            tg.send(f"✅ Posted: {item['title']}\n{link}")
            whatsapp.alert(f"✅ Your reel is live on Instagram: {item['title']}\n{link}")
        except Exception as e:
            traceback.print_exc()
            item["tries"] = item.get("tries", 0) + 1
            s["last_post_error"] = {"at": st.now().isoformat(timespec="minutes"), "title": item["title"][:80],
                                    "error": f"{type(e).__name__}: {e}"[:500]}  # for Claude's checks
            if item["tries"] >= 3:
                s["queue"].remove(item)
                tg.send(f"❌ Couldn't post \"{item['title']}\" after 3 tries: {e}\n"
                        "The video is still above in this chat, so you can post it by hand.")
                whatsapp.alert("❌ A scheduled reel couldn't be posted. Check Telegram for details.")
            else:
                item["post_at"] = (now + timedelta(minutes=30)).isoformat()
                tg.send(f"⚠️ Posting failed ({e}). I'll retry in 30 minutes.")


# ---------- messages ----------
def clone_voice(s, audio):
    """Turns the owner's recording into their Fish Audio voice, used for every reel from then on."""
    import tts
    if not FISH_API_KEY:
        tg.send("🎙 Add the FISH_API_KEY secret in GitHub first, then send /myvoice again.")
        return None
    if (audio.get("duration") or 60) < 20:
        s["awaiting_voice_sample"] = True
        tg.send("🎙 That's a bit short. Please send at least 1 minute of clear speech.")
        return None
    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        name = audio.get("file_name") or "sample.ogg"
        path = tg.download(audio["file_id"], os.path.join(WORK_DIR, "voice_sample" + os.path.splitext(name)[1]))
        s["fish_voice_id"] = tts.fish_clone(path)
        s.pop("fish_disabled", None)
        s.pop("fish_off_day", None)
        tg.send("✅ Your voice is ready. From the next reel on, reels speak in your voice. If Fish Audio ever runs "
                "out of credits, the regular voices take over automatically.\n/myvoice off switches it off.")
    except Exception as e:
        tg.send(f"⚠️ Couldn't make your voice: {str(e)[:200]}. Try sending the recording again.")
        s["awaiting_voice_sample"] = True
    return None


def fish_pool_command(s, arg):
    """/fishvoice <Fish Audio voice link> adds a library voice; /fishvoice list; /fishvoice clear."""
    import tts
    pool = s.setdefault("fish_pool", [])
    found = re.search(r"[0-9a-f]{32}", arg.lower())
    if arg.lower() == "clear":
        s["fish_pool"] = []
        tg.send("🎙 Removed all Fish library voices.")
    elif found and FISH_API_KEY:
        vid = found.group(0)
        if any(v["id"] == vid for v in pool):
            tg.send("🎙 That voice is already in the list.")
            return
        try:
            name = tts.fish_voice_name(vid)
        except Exception as e:
            tg.send(f"⚠️ Couldn't use that voice: {str(e)[:150]}")
            return
        pool.append({"id": vid, "name": name})
        tg.send(f"✅ Added “{name}”. Backup Fish voices: {len(pool)}. They're used when your own voice is off or a "
                "take fails the voice check.")
    elif found:
        tg.send("🎙 Add the FISH_API_KEY secret in GitHub first.")
    else:
        names = ", ".join(v.get("name", "?") for v in pool) or "none yet"
        tg.send(f"🎙 Fish library voices: {names}.\nTo add one, open a voice on fish.audio (Discovery), copy its link "
                "and send: /fishvoice <link>. Pick clear US-English narrator voices, never a celebrity's voice.\n"
                "/fishvoice clear removes them all.")


def handle(s, m, from_button=False):
    """Handles one Telegram message (or tapped button). Returns 'render' when the reel needs (re)making."""
    text = (m.get("text") or m.get("caption") or "").strip()
    doc = m.get("document") or {}
    mime = str(doc.get("mime_type", ""))
    audio = m.get("voice") or m.get("audio") or (doc if mime.startswith("audio/") else None)
    photo = (m["photo"][-1] if m.get("photo") else None) or (doc if mime.startswith("image/") else None)
    stage = s["stage"]

    if audio and (s.pop("awaiting_voice_sample", False) or text.lower().startswith("/myvoice")):
        return clone_voice(s, audio)
    if audio:
        if not s.get("draft"):
            tg.send("I don't have a script yet. Send me a topic or /news first.")
            return None
        push_undo(s, "your voice note")
        s.update(voice_file_id=audio["file_id"], voice_mode="own", stage="rendering",
                 script_deadline=None, preview_deadline=None)
        tg.send("🎬 Got your recording! Making the reel now. Preview coming in a few minutes.")
        return "render"

    video = m.get("video") or m.get("animation") or (doc if mime.startswith("video/") else None)
    if video:
        if (video.get("file_size") or 0) > 19_000_000:
            tg.send("That video is too big for Telegram bots (max 20 MB). Please send a shorter or smaller clip.")
            return None
        if not s.get("draft") or stage == "choosing":
            s["next_video_id"] = video["file_id"]
            tg.send("🎥 Got it! I'll use this clip as the opening shot of the next reel you make.")
            return None
        push_undo(s, "adding an opening video")
        s["user_video_id"] = video["file_id"]
        if stage == "awaiting_approval" and (s.get("voice_file_id") or s.get("voice_mode") == "ai"):
            s["stage"] = "rendering"
            tg.send("🎥 Got it! Remaking the reel with your clip as the opening shot.")
            return "render"
        tg.send("🎥 Got it! I'll use this clip as the opening shot, with the hook text on top.")
        return None

    if photo:
        if not s.get("draft"):
            tg.send("Send me a topic first. Then you can add a picture for the title card.")
            return None
        push_undo(s, "adding a picture")
        s["user_image_id"] = photo["file_id"]
        if stage == "awaiting_approval" and (s.get("voice_file_id") or s.get("voice_mode") == "ai"):
            s["stage"] = "rendering"
            tg.send("🖼 Got it! Remaking the reel with your picture on the title card.")
            return "render"
        tg.send("🖼 Got it! I'll put this on the title card.")
        return None

    if not text:
        return None
    low = text.lower().strip(" !.")

    link = re.search(r"https?://\S+", text)
    if not link and len(text) >= PASTE_MIN and not low.startswith("/"):
        s["pending_topic"] = text
        preview = text[:220] + ("…" if len(text) > 220 else "")
        tg.send(f"📰 Make an extra reel from this news?\n\n“{preview}”\n\nIt'll be made now and posted as an extra — "
                "the regular schedule carries on as usual.",
                buttons=[[btn(s, "✅ Yes, make it", "confirm_topic"), btn(s, "✖️ No", "cancel", True)]])
        return None
    if link and not low.startswith("/"):
        s["pending_topic"] = link.group(0)
        tg.send(f"📰 Make an extra reel from this news?\n{link.group(0)}\n\nIt'll be made now and posted as an extra — "
                "the regular schedule carries on as usual.",
                buttons=[[btn(s, "✅ Yes, make it", "confirm_topic"), btn(s, "✖️ No", "cancel", True)]])
        return None
    if low.startswith("/undo"):
        undo(s)
    elif low.startswith("/myvoice"):
        arg = low[len("/myvoice"):].strip()
        if arg == "off":
            s["fish_disabled"] = True
            tg.send("🎙 Your voice is off. Reels use your Fish library voices (/fishvoice) if you've added any, else "
                    "the regular voices. Send /myvoice on to switch back.")
        elif arg == "on":
            s.pop("fish_disabled", None)
            s.pop("fish_off_day", None)
            tg.send("🎙 Your voice is on again." if fish_voices(s) else
                    "🎙 Switched on, but there's no voice yet: send /myvoice and then a recording.")
        elif not FISH_API_KEY:
            tg.send("🎙 Add the FISH_API_KEY secret in GitHub first, then send /myvoice again.")
        else:
            s["awaiting_voice_sample"] = True
            tg.send("🎙 Send me a voice recording now (1–3 minutes). Read any news text clearly, at your normal "
                    "pace, in a quiet room, phone close to your mouth. I'll make your voice from it.")
    elif low.startswith("/fishvoice"):
        fish_pool_command(s, text[len("/fishvoice"):].strip())
    elif low.startswith("/stats"):
        import insights
        try:
            insights.collect(st.now().tzinfo)
        except Exception as e:
            print(f"Stats refresh failed: {e}")
        tg.send(insights.weekly_report(st.now().tzinfo))
    elif low.startswith("/held"):
        review_held(s)
    elif low.startswith("/nextstory"):
        push_undo(s, "switching story")
        next_story(s, "as you asked")
    elif low.startswith("/keepscript"):
        if s.get("draft"):
            s["draft"]["fact_status"] = "kept"
            tg.send(script_message(s["draft"]) + "\n\n" + fact_line(s["draft"]), buttons=script_buttons(s))
    elif low.startswith(("/start", "/help")):
        tg.send(HELP)
    elif low.startswith("/reel"):
        request = text[5:].strip()
        if not request:
            tg.send("Tell me what the reel should be about, like:\n/reel give the news about the latest trending AI models")
        else:
            story = researched_story(request)
            if story:
                push_undo(s, f"extra reel \"{request[:40]}\"")
                extra_reel(s, story)
    elif low.startswith("/topic"):
        topic = text[6:].strip()
        similar = news.recent_match(topic, recent_titles(s)) if topic else None
        if similar:
            s["pending_topic"] = topic
            tg.send(f"Heads-up: this looks like a story you already covered recently:\n“{similar}”\n\nMake it anyway?",
                    buttons=[[btn(s, "✅ Make it anyway", "confirm_topic"), btn(s, "✖️ No", "cancel", True)]])
        elif topic:
            push_undo(s, f"new topic \"{topic[:40]}\"")
            extra_reel(s, custom(topic))
        else:
            tg.send("Tell me the topic like this:\n/topic What are AI agents?")
    elif low.startswith("/myscript"):
        own = text[9:].strip()
        if not own:
            tg.send("Paste your script after the command, like:\n/myscript OpenAI just changed everything...")
        else:
            push_undo(s, "using your own script")
            topic = s.get("topic") or (s["candidates"][0] if s["stage"] == "choosing" and s["candidates"] else None)
            topic = topic or custom(own.splitlines()[0][:60])
            draft = writer.draft_from_own_script(own, topic)
            reset_reel(s)
            s.update(topic=topic, draft=draft, stage="awaiting_voice", script_deadline=deadline())
            tg.send(script_message(draft, note="Got your script ✅ Tap a voice below 🤖 or send a voice note 🎤") +
                    (autopilot_note("script") if s.get("autopilot") else ""), buttons=script_buttons(s))
    elif low.startswith("/autopilot"):
        arg = low[10:].strip()
        if arg in ("on", "off"):
            s["autopilot"] = arg == "on"
            if not s["autopilot"]:
                s.update(script_deadline=None, preview_deadline=None)
            elif s["stage"] == "awaiting_voice":
                s["script_deadline"] = deadline()
            elif s["stage"] == "awaiting_approval":
                s["preview_deadline"] = deadline()
        on = s.get("autopilot")
        tg.send(("🤖 Autopilot is ON: if you don't reply within "
                 f"{AUTO_APPROVE_HOURS:g} hours, I'll use the AI voice and schedule the reel myself."
                 if on else "✋ Autopilot is OFF: I'll always wait for your reply."),
                buttons=[[btn(s, "Turn autopilot OFF" if on else "Turn autopilot ON",
                              "/autopilot off" if on else "/autopilot on", True)]])
    elif low.startswith("/news"):
        push_undo(s, "getting new stories")
        offer_news(s)
    elif low.startswith("/skip"):
        push_undo(s, "skipping")
        reset_reel(s)
        tg.send("👍 Skipped.", buttons=[[btn(s, "↩️ Undo", "/undo", True), btn(s, "📰 Get stories", "/news", True)]])
        if not resume_paused(s):
            next_offer_if_waiting(s)
    elif low.startswith("/queue"):
        if s["queue"]:
            tg.send("🗓 Scheduled reels:\n\n" + "\n".join(
                f"• {fmt_time(datetime.fromisoformat(q['post_at']))}: {q['title']}" for q in s["queue"]) +
                "\n\nSend /clearqueue to cancel all of them.")
        else:
            tg.send("Nothing scheduled.")
    elif low.startswith("/clearqueue"):
        tg.send(f"🗑 Cancel all {len(s['queue'])} scheduled reels?",
                buttons=[[btn(s, "🗑 Yes, cancel them", "clearqueue_yes", True), btn(s, "✖️ No", "cancel", True)]])
    elif low.startswith("/script"):
        if s.get("draft"):
            tg.send(script_message(s["draft"]), buttons=script_buttons(s) if stage == "awaiting_voice" else None)
        else:
            tg.send("No script right now.")
    elif low.startswith("/status"):
        tg.send({"idle": "💤 Nothing in progress. Send a topic or /news.",
                 "choosing": "Waiting for you to pick a story.",
                 "awaiting_voice": "Waiting for you to choose a voice 🤖 or send a voice note 🎤",
                 "rendering": "Making the reel 🎬",
                 "awaiting_approval": "Waiting for you to schedule or post the preview."}.get(stage, stage)
                + f"\nScheduled reels: {len(s['queue'])} · Autopilot: {'on' if s.get('autopilot') else 'off'}")
    elif stage == "choosing":
        cands = s["candidates"]
        push_undo(s, f"choosing \"{text[:40]}\"")
        if low.isdigit() and 1 <= int(low) <= len(cands):
            s["spare"] = [c for k, c in enumerate(cands) if k != int(low) - 1]
            start_script(s, cands[int(low) - 1])
        else:
            start_script(s, custom(text))
    elif stage == "awaiting_voice":
        req = voice_request(low)
        if req:
            push_undo(s, "choosing the AI voice")
            use_ai_voice(s, req)
            return "render"
        push_undo(s, f"script change \"{text[:40]}\"")
        start_script(s, s["topic"], instruction=text)
    elif stage == "awaiting_approval":
        if low in POST_NOW_WORDS:
            ask_post_now(s, s["topic"]["title"])
        elif low in POST_WORDS:
            push_undo(s, "scheduling the reel")
            approve(s)
        elif low in REDO_WORDS:
            push_undo(s, "asking for a new voice")
            s.update(stage="awaiting_voice", preview_deadline=None,
                     script_deadline=deadline() if s.get("autopilot") else None)
            tg.send(script_message(s["draft"], note="Tap a new voice below 🤖, or send a voice note 🎤"),
                    buttons=script_buttons(s))
        else:
            push_undo(s, f"script change \"{text[:40]}\"")
            start_script(s, s["topic"], instruction=text)
    elif stage == "rendering":
        tg.send("Still making your reel, hang on 🎬")
    elif low in POST_NOW_WORDS or low in POST_WORDS:
        if low in POST_NOW_WORDS and s["queue"]:
            ask_post_now(s, s["queue"][0]["title"])
        elif s["queue"]:
            tg.send("It's already scheduled 👍", buttons=[[btn(s, "🚀 Post it now instead", "post now")]])
        else:
            tg.send("There's nothing waiting to be posted right now.")
    else:  # idle: confirm before starting a new reel, so a stray message doesn't become a topic
        s["pending_topic"] = text
        tg.send(f"Make a new reel about:\n“{text[:200]}”?",
                buttons=[[btn(s, "✅ Yes, make it", "confirm_topic"), btn(s, "✖️ No", "cancel", True)]])
    return None


def handle_button(s, cq):
    """A tapped button. Old buttons from earlier messages are ignored safely."""
    msg = cq.get("message") or {}
    stage_tag, token, action = (cq.get("data", "") + "||").split("|")[:3]
    if action == "noop":
        tg.answer_button(cq["id"])
        return None
    if stage_tag != "any" and (stage_tag != s["stage"] or token != tok(s)):
        if tg.DOORBELL_URL:  # the doorbell already answered the tap, so say it in the chat
            tg.send("ℹ️ That button was from an older message, so I ignored it. Please use the latest one 👇")
            show_current(s)
        else:
            tg.answer_button(cq["id"], "That button is from an older message 🙂 Use the latest one.")
        return None
    tg.answer_button(cq["id"])
    tg.show_choice(msg, cq.get("data", ""))
    if action == "confirm_topic":
        topic = s.get("pending_topic")
        if topic:
            push_undo(s, f"new reel \"{topic[:40]}\"")
            s["pending_topic"] = None
            if topic.startswith("http"):
                try:
                    tg.send("🔗 Reading the article...")
                    extra_reel(s, news.topic_from_url(topic))
                except Exception as e:
                    tg.send(f"⚠️ {e}. You can send the headline as text instead, or /topic <what it's about>.")
            elif len(topic) >= 60:  # a sentence or more of news → research it first
                story = researched_story(topic)
                if story:
                    extra_reel(s, story)
            else:
                extra_reel(s, custom(topic))
        return None
    if action == "cancel":
        s["pending_topic"] = None
        tg.send("👍 Cancelled, nothing changed.")
        return None
    if action == "clearqueue_yes":
        s["queue"] = []
        tg.send("🗑 Cleared all scheduled reels.")
        return None
    if action == "postnow_yes":
        push_undo(s, "posting now")
        if s["stage"] == "awaiting_approval":
            approve(s, now_please=True)
        else:
            post_next_now(s)
        return None
    return handle(s, {"chat": msg.get("chat", {}), "text": action}, from_button=True)


# ---------- modes ----------
def cmd_poll():
    s = st.load()
    backup_budget(s)
    if st.RECOVERED:
        try:
            tg.send("⚠️ " + st.RECOVERED + " Everything carries on; Claude will check it.")
        except Exception:
            pass
    before = json.dumps(s, sort_keys=True)
    render = False
    for u in tg.get_updates(s["offset"]):
        s["offset"] = u["update_id"] + 1
        cq = u.get("callback_query")
        m = u.get("message") or (cq or {}).get("message")
        if not m or str(m["chat"]["id"]) != str(TELEGRAM_CHAT_ID):
            continue
        try:
            result = handle_button(s, cq) if cq else handle(s, m)
            if result == "render":
                render = True
                break  # leave later messages for the next check
        except Exception as e:
            traceback.print_exc()
            tg.send(f"⚠️ Something went wrong: {e}")

    if not render and s["stage"] == "choosing" and s.get("choose_deadline"):
        if st.now() >= datetime.fromisoformat(s["choose_deadline"]) and s["candidates"]:
            pick = s["candidates"][0]
            tg.send(f"⏰ No reply, so I picked #1: {pick['title']}")
            push_undo(s, "autopilot picking story #1")
            try:
                s["spare"] = s["candidates"][1:]
                start_script(s, pick, auto=True)
            except Exception as e:
                traceback.print_exc()
                s["last_script_error"] = {"at": st.now().isoformat(timespec="minutes"), "error": str(e)[:400]}
                # autopilot never waits for a reply: drop this story and try the next one in 10 minutes
                s["candidates"] = s["candidates"][1:] + s["candidates"][:1]
                s["tried"] = ((s.get("tried") or []) + [pick.get("title", "")])[-60:]
                s["choose_deadline"] = (st.now() + timedelta(minutes=10)).isoformat()
                tg.send(f"⚠️ Couldn't write the script ({str(e)[:150]}). Trying the next story in 10 minutes.")

    if not render:
        try:
            if due_offer_slot(s):
                run_offer(s)
        except Exception as e:
            traceback.print_exc()
            tg.send(f"⚠️ Couldn't get the news: {e}\nSend /news to try again.")

    if not render and s.get("autopilot"):
        d_ = s.get("draft") or {}
        if (s["stage"] == "awaiting_voice" and passed(s.get("script_deadline"))
                and (d_.get("fact_status") in ("unsure", "skipped") or d_.get("vague_notes"))):
            s["script_deadline"] = None
            try:
                next_story(s, "the facts couldn't be verified")
            except Exception as e:  # writing AI busy/out of quota: never crash the run (posting must go on)
                traceback.print_exc()
                s["tried"] = ((s.get("tried") or []) + [(s.get("topic") or {}).get("title", "")])[-60:]
                if not resume_paused(s):
                    reset_reel(s)
                tg.send(f"⚠️ Couldn't switch stories right now ({str(e)[:120]}). The schedule keeper will fill "
                        "the next slot.")
        elif s["stage"] == "awaiting_voice" and passed(s.get("script_deadline")):
            push_undo(s, "autopilot choosing the AI voice")
            use_ai_voice(s, auto=True)
            render = True
        elif s["stage"] == "awaiting_approval" and passed(s.get("preview_deadline")) and qa_hold(s.get("draft") or {}):
            park_reel(s)
        elif s["stage"] == "awaiting_approval" and passed(s.get("preview_deadline")):
            s["preview_deadline"] = None
            extra = (s.get("topic") or {}).get("extra")
            tg.send("⏰ No reply, so autopilot is " + ("posting your extra reel now." if extra else "scheduling your reel."))
            push_undo(s, "autopilot posting the reel")
            try:
                approve(s, now_please=bool(extra))
            except Exception as e:
                tg.send(f"⚠️ Autopilot couldn't schedule the reel: {e}")

    if s.get("autopilot"):
        try:
            drop_queued_repeats(s)
            if not render:
                render = keep_schedule(s) or render
            else:
                keep_schedule_alarm(s)
        except Exception as e:
            traceback.print_exc()
            print(f"Schedule keeper: {e}")

    post_due(s)
    daily_report(s)
    send_outbox()
    if not render:
        stats_jobs(s)

    try:
        tg.ack_updates(s["offset"] - 1)
    except Exception as e:
        print(f"Doorbell ack failed (messages will be re-read safely next time): {e}")

    note_gemini(s)
    if json.dumps(s, sort_keys=True) != before:
        st.save(s)
    github_output("render", "true" if render else "false")


def drop_queued_repeats(s):
    """Once a day: a queued reel that turns out to repeat an already-posted story is removed (and replaced)."""
    today = st.now().date().isoformat()
    if s.get("repeat_check2_day") == today or not s["queue"]:
        return
    s["repeat_check2_day"] = today
    queued = [{"title": q["title"], "summary": ""} for q in s["queue"]]
    others = [t for t in recent_titles(s) if t not in {q["title"] for q in s["queue"]}]
    keep = {p["title"] for p in writer.drop_same_events(queued, others)}
    keep = {t for t in keep if not news.recent_match(t, others)}  # word check too (works without Gemini)
    gone = [q for q in s["queue"] if q["title"] not in keep]
    if gone:
        s["queue"] = [q for q in s["queue"] if q["title"] in keep]
        tg.send("🧹 Removed from the schedule because it repeats a story we already covered:\n• " +
                "\n• ".join(q["title"] for q in gone) + "\nA new reel will be made for that slot.")


def keep_schedule_alarm(s):
    """While a reel is being retried: if a post time has already been missed for over an hour, tell the user once."""
    now = st.now()
    if behind_today(s) and s.get("behind_since"):
        late = (now - datetime.fromisoformat(s["behind_since"])).total_seconds() / 60
        if late > 60 and s.get("late_alarm_day") != now.date().isoformat():
            s["late_alarm_day"] = now.date().isoformat()
            err = (s.get("last_render_error") or {}).get("error", "")
            tg.send("🚨 Today's reels are behind schedule. " + (f"Last error: {err}" if err else ""))


def keep_schedule(s):
    """Makes sure every post time today gets a reel: works ahead, hurries when a slot is close, and makes a
    backup reel if nothing will be ready in time. Returns True when a video needs rendering now."""
    now = st.now()
    need = next_unfilled(s)
    if not need:
        s.pop("behind_since", None)
        return False
    minutes = (need - now).total_seconds() / 60
    behind = behind_today(s) > 0
    if behind:
        s.setdefault("behind_since", now.isoformat())
    else:
        s.pop("behind_since", None)
    waited = (now - datetime.fromisoformat(s["behind_since"])).total_seconds() / 60 if behind else 0
    # 1) hurry: shorten autopilot's waiting when the slot is close
    if minutes < 90:
        cap = now + timedelta(minutes=0 if minutes < 45 else 10)
        for key in ("choose_deadline", "script_deadline", "preview_deadline"):
            if s.get(key) and datetime.fromisoformat(s[key]) > cap:
                s[key] = cap.isoformat()
    if s["stage"] == "choosing" and not s.get("choose_deadline"):
        s["choose_deadline"] = (now + timedelta(minutes=5)).isoformat()  # never wait forever for a reply
    # 2) work ahead: idle while a slot today still needs a reel → start the next one now
    if s["stage"] == "idle" and not s.get("paused"):  # around the clock: night slots are for other time zones
        last = s.get("last_auto_offer")
        if not last or abs(now - datetime.fromisoformat(last)) > timedelta(minutes=20):
            s["last_auto_offer"] = now.isoformat()
            tg.send(f"📋 A reel is missing from today's {len(POST_TIMES)} (deleted or not posted), so I'm making a "
                    "replacement now." if behind else f"📋 Getting the next reel ready for {fmt_time(need)}.")
            offer_news(s)
            if minutes < 90 and s["stage"] == "choosing":
                s["choose_deadline"] = (now + timedelta(minutes=0 if minutes < 45 else 10)).isoformat()
        return False
    # 3) no more "headlines" backup reels (owner, 2026-10-09: they made no sense and skipped every quality check).
    #    A reel that isn't ready posts as soon as it passes all checks: late and good beats on time and bad.
    key = f"{now.date()}-{posted_today(s)}"
    if behind and waited >= 10 and s.get("late_note_for") != key:
        s["late_note_for"] = key
        tg.send("⏳ This slot's reel isn't ready yet. It will post as soon as it passes every check "
                "(a late, good reel beats an on-time bad one).")
    return False


def send_outbox():
    """Messages left in outbox/ (e.g. by Claude's daily review) are sent to Telegram, then removed."""
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outbox")
    if not os.path.isdir(folder):
        return
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not name.endswith(".txt") or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                tg.send(text[:3900])
            os.remove(path)
        except Exception as e:
            print(f"Outbox message {name} not sent: {e}")


def stats_jobs(s):
    """Once a day (just after midnight, IST): collect Instagram stats. Sundays 10 AM: the weekly report."""
    if not IG_READY():
        return
    import insights
    now = st.now()
    today = now.date().isoformat()
    first_time = not s.get("stats_day")
    if s.get("stats_day") != today and (first_time or (now.hour == 0 and now.minute >= 20) or now.hour >= 1):
        s["stats_day"] = today
        try:
            status = insights.collect(now.tzinfo)
            print(f"Stats: {status}")
            data = insights.load()
            if not data.get("notes", {}).get("insights_permission", True) and not s.get("perm_told"):
                s["perm_told"] = True
                tg.send("📊 I've started saving your Instagram stats every day (followers, likes, comments). To also "
                        "track views, shares, saves and watch time, the Instagram token needs the "
                        "“instagram_manage_insights” permission. Ask Claude to walk you through adding it (5 min).")
        except Exception as e:
            print(f"Stats collection failed: {e}")
    if s.get("token_day") != today:  # once a day: warn a week before the Instagram token expires
        s["token_day"] = today
        try:
            import instagram
            valid, expires = instagram.token_expiry()
            days = (expires - now.timestamp()) / 86400 if expires else None
            if not valid or (days is not None and days < 7):
                when = "has expired" if not valid or days <= 0 else f"expires in {max(1, int(days))} day(s)"
                tg.send(f"🔑 The Instagram token {when}. Posting stops when it does. Ask Claude for the steps to make "
                        "a never-expiring page token (5 minutes).")
        except Exception as e:
            print(f"Token check failed: {e}")
    week = f"{now.isocalendar()[0]}-{now.isocalendar()[1]}"
    if now.weekday() == 6 and now.hour >= 10 and s.get("report_week") != week:
        s["report_week"] = week
        try:
            tg.send(insights.weekly_report(now.tzinfo))
        except Exception as e:
            print(f"Weekly report failed: {e}")


def daily_report(s):
    """After the day's last post time: how many of today's reels went out."""
    now = st.now()
    today = now.date().isoformat()
    last = max(slots_on(now.date()))
    if now < last + timedelta(minutes=20) or s.get("report_day") == today:
        return
    s["report_day"] = today
    done, want = posted_today(s), len(POST_TIMES)
    extras = sum(1 for p in (s.get("post_log") or []) if p["at"][:10] == today and p.get("extra"))
    msg = f"📊 Today: {done}/{want} scheduled reels posted" + (f" (+{extras} extra)" if extras else "") + \
          (" ✅" if done >= want else " ⚠️")
    if done < want and not s.get("autopilot"):
        msg += "\nAutopilot is off, so reels only go out when you approve them. Turn it on with /autopilot."
    tg.send(msg)


def due_offer_slot(s):
    """The story time that's due now and hasn't been sent today (None if nothing is due).
    Times missed by more than 2 hours are skipped rather than sent late."""
    now = st.now()
    today = now.date().isoformat()
    log = s.get("offer_log") or {}
    if log.get("date") != today:
        log = {"date": today, "done": []}
    s["offer_log"] = log
    due = None
    for t in sorted(OFFER_TIMES):
        h, m = map(int, t.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t in log["done"] or now < at:
            continue
        log["done"].append(t)
        if now - at <= timedelta(hours=2):
            due = t
    return due


def run_offer(s):
    if s["stage"] in ("idle", "choosing"):
        offer_news(s)
    else:
        s["pending_offer"] = True
        tg.send("🔔 Time for the next reel! Finish the current one (or tap ⏭ Skip) "
                "and I'll send fresh stories right after.")
        whatsapp.alert("🔔 Time for your next reel! Finish the current one on Telegram first.")


def cmd_offer():
    """Only sends stories if a story time is due and wasn't sent yet (the 5-minute checks normally do this)."""
    s = st.load()
    try:
        if due_offer_slot(s):
            run_offer(s)
        else:
            print("No story time is due right now (send /news in Telegram for stories anytime).")
    except Exception as e:
        traceback.print_exc()
        tg.send(f"⚠️ Couldn't get the news: {e}\nSend /news to try again, or send any topic.")
    st.save(s)


def fish_voices(s):
    """Fish Audio voices to try, in order: the owner's own voice (unless switched off), then the library voices the
    owner picked with /fishvoice (shuffled). Empty when there's no key or credits ran out today."""
    import random
    if not FISH_API_KEY or s.get("fish_off_day") == st.now().date().isoformat():
        return []
    own = s.get("fish_voice_id") or FISH_VOICE_ID
    out = [(own, "your voice (Fish Audio)")] if own and not s.get("fish_disabled") else []
    pool = [(v["id"], f"{v.get('name') or 'library voice'} (Fish Audio)") for v in s.get("fish_pool") or []
            if v.get("id")]
    last = s.get("last_fish_id")  # take turns (Paula, Ethan, Paula…): the one used last time goes to the back
    if last in [v[0] for v in pool]:
        k = [v[0] for v in pool].index(last)
        pool = pool[k + 1:] + pool[:k + 1]
    return out + pool


def cmd_render():
    import tts
    import video
    s = st.load()
    backup_budget(s)
    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        tg.action("upload_video")
        if s.get("voice_mode") == "ai":
            import tts
            gender = s.get("voice_gender") or "male"
            want = "microsoft" if s.get("last_engine") == "google" else "google"  # alternate Google / Microsoft
            fish = fish_voices(s)
            voice, engine = tts.synthesize(s["draft"]["script"], os.path.join(WORK_DIR, "ai_voice"), gender, want,
                                           delivery=s["draft"].get("delivery") or "", fish_voice=fish)
            if tts.LAST_ENGINE != "fish":  # the Google / Microsoft alternation only moves when one of them is used
                s["last_engine"] = tts.LAST_ENGINE or want
            if fish and tts.FISH_PROBLEM == "out":
                s["fish_off_day"] = st.now().date().isoformat()
                tg.send("🎙 Fish Audio refused (credits used up, or the key changed), so today's reels use the regular "
                        "voices. Top up at fish.audio and the Fish voices come back tomorrow.")
            # listen to the voice-over before using it: it must say the script and nothing else
            def heard_words(path):
                # Microsoft reports exactly what it spoke; otherwise transcribe WITHOUT a hint (a hint makes the
                # recogniser echo script phrases into the silence at the end)
                return tts.LAST_WORDS if tts.LAST_ENGINE == "microsoft" and tts.LAST_WORDS else video.transcribe(path)
            try:
                ok, why = tts.speech_matches(heard_words(voice), s["draft"]["script"])
            except Exception as e:
                ok, why = True, ""
                print(f"Voice check skipped: {e}")
            if not ok:
                print(f"Voice-over rejected ({why}); remaking it")
                tg.send(f"🎙 The {engine.split(',')[0]} voice-over didn't match the script ({why}), so I'm remaking it.")
                other = "microsoft" if tts.LAST_ENGINE == "google" else "google"
                rest = [v for v in fish if v[0] != tts.LAST_FISH_ID] if tts.LAST_ENGINE == "fish" else []
                voice, engine = tts.synthesize(s["draft"]["script"], os.path.join(WORK_DIR, "ai_voice2"), gender, other,
                                               fish_voice=rest)
                ok2, why2 = tts.speech_matches(heard_words(voice), s["draft"]["script"])
                if not ok2:
                    raise RuntimeError(f"the voice-over didn't match the script twice ({why2})")
            s["last_gender"] = gender
            s["engine_used"] = tts.LAST_ENGINE
            if tts.LAST_ENGINE == "fish" and tts.LAST_FISH_ID:
                s["last_fish_id"] = tts.LAST_FISH_ID
            print(f"Voice-over: {engine}")
        else:
            voice = tg.download(s["voice_file_id"], os.path.join(WORK_DIR, "voice_input"))
        image = None
        if s.get("user_image_id"):
            image = tg.download(s["user_image_id"], os.path.join(WORK_DIR, "user_image"))
        clip = None
        if s.get("user_video_id"):
            try:
                clip = tg.download(s["user_video_id"], os.path.join(WORK_DIR, "user_video.mp4"))
            except Exception as e:
                tg.send(f"⚠️ Couldn't download your video ({e}), so I'm using the normal opening.")
        exact = None
        if s.get("voice_mode") == "ai":
            import tts
            exact = tts.LAST_WORDS
        out = video.render(voice, s["draft"], s["topic"], user_image_path=image, user_video_path=clip,
                           exact_words=exact)
        # Checkpoint 2: does every shot actually fit what's being said?
        s["draft"]["visual_status"], s["draft"]["visual_notes"] = "skipped", []
        safe_done = set()
        try:
            frames = video.check_frames(out)
            problems = writer.visual_check(frames) if frames else []
            beats_bad = sorted({frames[p["beat"]]["beat"] for p in problems if 0 <= p["beat"] < len(frames)})
            if beats_bad:
                notes = [f"{frames[p['beat']]['line'][:50]}…: {p['problem']}" for p in problems
                         if 0 <= p["beat"] < len(frames)]
                tg.send("🖼 Visual check found shots that don't fit, so I'm replacing them:\n• " + "\n• ".join(notes))
                out = video.render(voice, s["draft"], s["topic"], user_image_path=image, user_video_path=clip,
                                   exact_words=exact, safe_beats=set(beats_bad))
                safe_done = set(beats_bad)
                frames = video.check_frames(out)
                again = writer.visual_check(frames) if frames else []
                if again:  # still not right: those shots become safe cards too (name/logo cards can't be wrong)
                    more = {frames[p["beat"]]["beat"] for p in again if 0 <= p["beat"] < len(frames)}
                    tg.send("🖼 Still not right, replacing these with safe cards:\n• " +
                            "\n• ".join(p["problem"] for p in again))
                    out = video.render(voice, s["draft"], s["topic"], user_image_path=image, user_video_path=clip,
                                       exact_words=exact, safe_beats=set(beats_bad) | more)
                    safe_done = set(beats_bad) | more
                s["draft"]["visual_status"] = "fixed"
                s["draft"]["visual_notes"] = notes + [p["problem"] for p in again]
            else:
                s["draft"]["visual_status"] = "ok"
        except Exception as e:
            print(f"Visual check skipped: {e}")
        # Checkpoint 3: the editor-in-chief watches the whole finished reel and scores it out of 10
        def rerender(extra):
            safe_done.update(extra)
            return video.render(voice, s["draft"], s["topic"], user_image_path=image, user_video_path=clip,
                                exact_words=exact, safe_beats=set(safe_done))
        out, action = editor_step(s, out, rerender)
        if action in ("rewrite", "switch"):
            editor_redo(s, action)
            st.save(s)
            return
        s["draft"]["credits"] = list(getattr(video, "LAST_CREDITS", []) or [])
        voice_info = f" · voice: {engine}" if s.get("voice_mode") == "ai" else ""
        s["draft"]["voice_used"] = engine if s.get("voice_mode") == "ai" else "own voice"
        s["draft"]["visual_summary"] = getattr(video, "LAST_SUMMARY", "")
        if getattr(video, "LAST_SUMMARY", ""):
            voice_info += f"\n🎞 {video.LAST_SUMMARY}"
        if getattr(video, "LAST_SYNC", ""):
            voice_info += f"\n{video.LAST_SYNC}"
        vs = s["draft"].get("visual_status")
        voice_info += {"ok": "\n🖼 Visual check: ✅ every shot fits", "fixed": "\n🖼 Visual check: ✏️ fixed mismatched shots",
                       "issues": "\n🖼 Visual check: ⚠️ some shots may not fit — please look",
                       "skipped": "\n🖼 Visual check: skipped"}.get(vs, "")
        voice_info += "\n" + fact_line(s["draft"]).split("\n")[0]
        ed = s["draft"].get("editor") or {}
        if ed.get("overall") is not None:
            voice_info += f"\n🎬 Editor: {ed['overall']}/10 — {ed.get('one_line', '')}"
        try:
            import review
            review.save(out, s["draft"], s.get("topic"))
        except Exception as e:
            print(f"Review pack skipped: {e}")
        s["video_file_id"] = tg.send_video(out, caption="👆 Preview" + voice_info)
        s["stage"] = "awaiting_approval"
        s["preview_deadline"] = deadline() if s.get("autopilot") else None
        tg.send(esc("Instagram caption:\n\n" + caption_for(s["draft"], s.get("voice_mode") == "ai")) +
                sources_block(s) + esc(
                "\n\n—\nTap below, or type changes to the script ✍️. Send a picture 🖼 or a short video 🎥 for the opening shot." +
                (("\n\n⚠️ Quality check needs you: autopilot won't post this one — watch it and tap Schedule if it's fine."
                  if qa_hold(s["draft"]) else autopilot_note("preview")) if s.get("autopilot") else "")),
                buttons=preview_buttons(s), html=True)
        whatsapp.alert("🎬 Your reel is ready for approval! Open Telegram to watch the preview and reply 'post'.")
    except Exception as e:
        traceback.print_exc()
        title = (s.get("topic") or {}).get("title", "")
        fails = s["render_fails"] = (s.get("render_fails", 0) + 1) if s.get("render_fail_topic") == title else 1
        s["render_fail_topic"] = title
        s["last_render_error"] = {"at": st.now().isoformat(), "topic": title[:80],
                                  "error": f"{type(e).__name__}: {e}"[:400],
                                  "trace": traceback.format_exc()[-1500:]}
        if s.get("autopilot") and fails >= 2:
            # this reel keeps failing: drop it and move on, so the day's schedule isn't blocked
            tg.send(f"⚠️ Couldn't make “{title[:80]}” twice ({e}). Dropping it and moving on to another story.")
            s["tried"] = ((s.get("tried") or []) + [title])[-60:]
            s["render_fails"] = 0
            if not resume_paused(s):
                reset_reel(s)
        else:
            s["stage"] = "awaiting_voice"
            s["script_deadline"] = (st.now() + timedelta(minutes=5)).isoformat() if s.get("autopilot") else None
            tg.send(f"⚠️ Couldn't make the reel: {e}\n" + ("Autopilot will try once more in a few minutes."
                    if s.get("autopilot") else "Reply \"ok\" to try the AI voice again, or send a voice note."))
    note_gemini(s)
    st.save(s)


EDITOR_PASS = 8.0   # the editor-in-chief's bar for posting
EDITOR_FLOOR = 7.0  # after one round of fixes, reels between this and the bar are posted (with the score shown)


def editor_step(s, out, rerender):
    """Scores the finished reel. Returns (video, action): "ok" (post), "rewrite" (script must change) or "switch"
    (not good enough even after fixes). Weak shots are replaced and re-scored once, right here."""
    import video
    d = s["draft"]
    if (s.get("topic") or {}).get("digest"):  # the backup headlines reel exists to keep the schedule: never blocked
        return out, "ok"
    try:
        rev = writer.editor_review(d, s.get("topic") or {}, video.editor_frames(out),
                                   video.LAST_CHECK.get("times") or [])
    except Exception as e:  # the editor must never block the schedule
        print(f"Editor review skipped: {e}")
        return out, "ok"
    d["editor"] = rev
    print(f"Editor: {rev['overall']}/10 {rev['scores']} · {rev['one_line']}")
    if rev["overall"] >= EDITOR_PASS:
        return out, "ok"
    first_round = not d.get("editor_rounds")
    if first_round and rev["visual_beats"] and not rev["script_fixes"]:
        d["editor_rounds"] = 1
        tg.send(f"🎬 Editor-in-chief: {rev['overall']}/10, {rev['one_line']}\nReplacing the weak shots:\n• " +
                "\n• ".join(rev["visual_notes"]))
        try:
            return editor_step(s, rerender(set(rev["visual_beats"])), rerender)
        except Exception as e:
            print(f"Editor re-render failed: {e}")
            return out, "ok" if rev["overall"] >= EDITOR_FLOOR else "switch"
    if first_round and rev["script_fixes"]:
        return out, "rewrite"
    return out, ("ok" if rev["overall"] >= EDITOR_FLOOR else "switch")


def editor_redo(s, action):
    """Acts on the editor's verdict: rewrite the script with its notes (then voice + render again), or switch story."""
    rev = s["draft"].get("editor") or {}
    if action == "rewrite":
        tg.send(f"🎬 Editor-in-chief: {rev.get('overall')}/10, {rev.get('one_line', '')}\nRewriting the script:\n• " +
                "\n• ".join(rev.get("script_fixes") or []))
        try:
            new = checked_script(s["topic"], previous=s["draft"],
                                 instruction="The editor-in-chief's notes, fix every one (keep every fact true and "
                                             "sourced): " + " | ".join(rev.get("script_fixes") or []))
        except Exception as e:
            print(f"Editor rewrite failed: {e}")
            new = {"fact_status": "unsure"}
        if new.get("fact_status") != "unsure" and new.get("script"):
            new["editor_rounds"] = 1
            new["source_links"] = s["draft"].get("source_links")
            s["draft"] = new
            s["stage"] = "awaiting_voice"
            s["script_deadline"] = st.now().isoformat()  # autopilot voices and renders it on the next run
            return
        tg.send("🎬 The editor's fixes couldn't be verified, so I'm switching to another story.")
    else:
        tg.send(f"🎬 Editor-in-chief: {rev.get('overall')}/10 even after fixes, {rev.get('one_line', '')}. "
                "Not good enough to post, switching to another story.")
    next_story(s, f"editor score {rev.get('overall')}/10")


def note_gemini(s):
    """Counts Gemini requests per day and keeps its last errors, so quota problems are visible."""
    day = st.now().date().isoformat()
    use = s.get("gemini_use") or {}
    if use.get("day") != day:
        use = {"day": day, "calls": 0}
    use["calls"] = use.get("calls", 0) + writer.CALLS[0]
    use["claude_calls"] = use.get("claude_calls", 0) + writer.CLAUDE_CALLS[0]
    use["claude_backup"] = use.get("claude_backup", 0) + writer.BACKUP_CALLS[0]
    writer.CALLS[0] = writer.CLAUDE_CALLS[0] = writer.BACKUP_CALLS[0] = 0
    s["gemini_use"] = use
    if writer.ERRORS:
        s["gemini_errors"] = ((s.get("gemini_errors") or []) + [{**e, "day": day} for e in writer.ERRORS])[-10:]
        writer.ERRORS.clear()
    backup_budget(s)


CLAUDE_BACKUP_PER_DAY = 150  # max jobs/day Claude takes over when Gemini's free quota is used up (~$1-2/day at most)


def backup_budget(s):
    """Tells writer how many Gemini jobs Claude may still take over today."""
    use = s.get("gemini_use") or {}
    used = use.get("claude_backup", 0) if use.get("day") == st.now().date().isoformat() else 0
    writer.BACKUP_LEFT[0] = max(0, CLAUDE_BACKUP_PER_DAY - used)


def cmd_feeds():
    """Checks every news source and saves how many stories each one gave (no messages sent)."""
    s = st.load()
    heads = news.fetch_headlines()
    s["feed_report"] = {"at": st.now().isoformat(timespec="minutes"), **news.LAST_REPORT,
                        "sample": [f"[{h['source']}] {h['title'][:70]}" + (f" ({h['buzz']})" if h.get("buzz") else "")
                                   for h in heads[:12]]}
    st.save(s)


def cmd_check():
    results = []

    def test(name, fn):
        try:
            results.append(f"✅ {name}: {fn()}")
        except Exception as e:
            results.append(f"❌ {name}: {e}")

    import requests
    import images
    import instagram
    from config import PEXELS_API_KEY

    def pexels():
        r = requests.get("https://api.pexels.com/videos/search", timeout=20,
                         headers={"Authorization": PEXELS_API_KEY or ""}, params={"query": "robot", "per_page": 1})
        if r.status_code != 200:
            raise RuntimeError("key missing or rejected (reels will use AI images/gradients instead)")
        return "OK"

    def ai_image():
        if not images.generate("a friendly robot reading a newspaper"):
            raise RuntimeError("no free image service answered (reels will still work without AI images)")
        return "OK"

    test("Telegram", lambda: "@" + tg.call("getMe")["username"])
    test("Gemini", lambda: writer.ask("Reply with just the word OK.", temperature=0).strip()[:20])
    test("Pexels", pexels)
    test("AI images", ai_image)
    test("Instagram", lambda: "@" + instagram.whoami())
    if whatsapp.enabled():
        test("WhatsApp alerts", lambda: "sent a test message" if whatsapp.alert(
            "✅ Reel Agent: WhatsApp alerts are working!", raise_errors=True) else "failed")
    else:
        results.append("➖ WhatsApp alerts: not set up (optional)")
    test("News feeds", lambda: f"{len(news.fetch_headlines())} fresh headlines")
    report = "Setup check\n\n" + "\n".join(results)
    print(report)
    try:
        tg.send(report + "\n\nSend /help to see how I work.")
    except Exception:
        pass


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "poll"
    {"poll": cmd_poll, "offer": cmd_offer, "morning": cmd_offer, "feeds": cmd_feeds,
     "render": cmd_render, "check": cmd_check}[mode]()

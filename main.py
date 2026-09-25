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
from config import AI_VOICE_NOTE, AUTO_APPROVE_HOURS, AUTO_PICK_HOURS, OFFER_TIMES, POST_TIMES, TELEGRAM_CHAT_ID, WORK_DIR

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
/topic <anything> – make an extra reel on your own topic right now (or just send a news link)
/myscript <your script> – use a script you wrote yourself (skips Gemini)
/news – get fresh stories now (e.g. to record the next reel straight away)
/autopilot on|off – finish reels on my own when you don't reply
/queue – see scheduled reels
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
    tg.send(f"⏸ Parked for your review: “{title}”.\nWhy:\n• " + "\n• ".join(reasons or ["quality check"]) +
            links + "\nAutopilot won't post it — "
            "but the next reels carry on as normal. Review it anytime (parked reels are kept for 24 hours).",
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
    tg.send("What the quality check flagged:\n• " + "\n• ".join(notes or ["(no details)"]) + sources_block(s) +
            "\n\nIf it's fine, tap ✅ Schedule. You can also type changes to the script, or ⏭ Skip it." +
            (f"\n\n{len(held)} more parked." if held else ""), buttons=preview_buttons(s))


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
        final = u
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


def sources_block(s):
    links = (s.get("draft") or {}).get("source_links") or []
    return ("\n\n🔗 Sources (tap to verify):\n" + "\n".join(f"{k}. {u}" for k, u in enumerate(links, 1))) if links else ""


def fact_line(draft):
    status, notes = draft.get("fact_status"), draft.get("fact_notes") or []
    if status == "ok":
        return "🔎 Fact check: ✅ all claims verified"
    if status == "fixed":
        return "🔎 Fact check: ✏️ corrected before writing this:\n• " + "\n• ".join(notes)
    if status == "unsure":
        return ("🔎 Fact check: ⚠️ these couldn't be verified:\n• " + "\n• ".join(notes or ["unverified claims"]))
    if status == "kept":
        return "🔎 Fact check: ⚠️ you chose to keep unverified claims"
    return "🔎 Fact check: skipped (Gemini unavailable) — please check the facts yourself"


def qa_hold(draft):
    return draft.get("fact_status") == "unsure" or draft.get("visual_status") == "issues"


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
               ". Correct each claim using the source article and search; if a claim can't be verified, remove it. "
               "Don't add new claims.")
        draft = writer.write_script(topic, previous=draft, instruction=fix)
        draft = fact_check_step(draft, topic)
    draft["fix_rounds"] = rounds
    return draft


def next_story(s, reason=""):
    """Moves on to another story when this one can't be verified, so the posting slot still gets a reel."""
    tried = set(s.get("tried") or []) | {(s.get("topic") or {}).get("title", "")}
    s["tried"] = list(tried)[-30:]
    spare = [c for c in (s.get("spare") or []) if not news.recent_match(c.get("title", ""), list(tried))]
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


def start_script(s, topic, instruction=None, auto=False):
    tg.action("typing")
    tg.send("✍️ Revising the script..." if instruction else f"✍️ Writing a script about: {topic['title']}")
    draft = checked_script(topic, previous=s.get("draft") if instruction else None, instruction=instruction)
    draft["source_links"] = resolve_links([topic.get("link", "")] + list(draft.get("sources") or []))
    image = s.get("user_image_id") if instruction else None
    clip = s.get("user_video_id") if instruction else s.pop("next_video_id", None)
    reset_reel(s)
    s.update(topic=topic, draft=draft, stage="awaiting_voice", user_image_id=image, user_video_id=clip,
             script_deadline=deadline())
    if clip and not instruction:
        tg.send("🎥 Using the clip you sent as the opening shot.")
    if draft.get("fact_status") == "unsure":
        tg.send(script_message(draft) + "\n\n" + fact_line(draft) + sources_block(s) +
                "\n\nI couldn't fix this after checking twice." +
                (" Autopilot will switch to another story." if s.get("autopilot") else ""),
                buttons=[[btn(s, "➡️ Next story", "/nextstory"), btn(s, "Keep anyway", "/keepscript")],
                         [btn(s, "⏭ Skip", "/skip", True)]])
        if auto and s.get("autopilot"):
            next_story(s, "the facts couldn't be verified")
        return
    tg.send(script_message(draft) + "\n\n" + fact_line(draft) + sources_block(s) +
            (autopilot_note("script") if s.get("autopilot") else ""), buttons=script_buttons(s))


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
    used = recent_titles(s)
    if not headlines:
        reset_reel(s)
        tg.send("I couldn't find fresh AI news right now. Send me any topic and I'll write a script.")
        return
    picks = news.dedupe(writer.pick_top(headlines, used), [])
    reset_reel(s)
    s.update(candidates=picks, stage="choosing",
             choose_deadline=(st.now() + timedelta(hours=AUTO_PICK_HOURS)).isoformat())
    tg.send(stories_text(s), buttons=story_buttons(s))
    whatsapp.alert("📰 New AI stories are ready! Open Telegram to pick one for your next reel.")


def custom(text):
    return {"title": text.strip(), "custom": True}


def caption_for(draft, ai_voice=False):
    note = f"\n\n{AI_VOICE_NOTE}" if ai_voice and AI_VOICE_NOTE else ""
    credits = list(dict.fromkeys(draft.get("credits") or []))  # no duplicates
    credit_text = ("\n\n📷 " + " · ".join(credits))[:600] if credits else ""
    return draft["caption"] + note + credit_text + "\n\n" + " ".join(f"#{h}" for h in draft["hashtags"])


# ---------- scheduling & posting ----------
def next_post_time(s):
    now = st.now()
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
    return instagram.publish_reel(path, item["caption"])


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


def approve(s, now_please=False):
    item = {"title": s["topic"]["title"], "video_file_id": s["video_file_id"],
            "caption": caption_for(s["draft"], s.get("voice_mode") == "ai")}
    s["history"] = (s["history"] + [item["title"]])[-100:]
    s["posted_log"] = (s.get("posted_log") or []) + [{"title": item["title"], "at": st.now().isoformat()}]
    if now_please:
        tg.send("📤 Posting to Instagram now... (1-3 minutes)")
        link = publish_item(item)
        s["posted_ids"] = ((s.get("posted_ids") or []) + [item["video_file_id"]])[-30:]
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
            tg.send(f"✅ Posted: {item['title']}\n{link}")
            whatsapp.alert(f"✅ Your reel is live on Instagram: {item['title']}\n{link}")
        except Exception as e:
            traceback.print_exc()
            item["tries"] = item.get("tries", 0) + 1
            if item["tries"] >= 3:
                s["queue"].remove(item)
                tg.send(f"❌ Couldn't post \"{item['title']}\" after 3 tries: {e}\n"
                        "The video is still above in this chat, so you can post it by hand.")
                whatsapp.alert("❌ A scheduled reel couldn't be posted. Check Telegram for details.")
            else:
                item["post_at"] = (now + timedelta(minutes=30)).isoformat()
                tg.send(f"⚠️ Posting failed ({e}). I'll retry in 30 minutes.")


# ---------- messages ----------
def handle(s, m, from_button=False):
    """Handles one Telegram message (or tapped button). Returns 'render' when the reel needs (re)making."""
    text = (m.get("text") or m.get("caption") or "").strip()
    doc = m.get("document") or {}
    mime = str(doc.get("mime_type", ""))
    audio = m.get("voice") or m.get("audio") or (doc if mime.startswith("audio/") else None)
    photo = (m["photo"][-1] if m.get("photo") else None) or (doc if mime.startswith("image/") else None)
    stage = s["stage"]

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
    if link and not low.startswith("/"):
        s["pending_topic"] = link.group(0)
        tg.send(f"📰 Make an extra reel from this news?\n{link.group(0)}\n\nIt'll be made now and posted as an extra — "
                "the regular schedule carries on as usual.",
                buttons=[[btn(s, "✅ Yes, make it", "confirm_topic"), btn(s, "✖️ No", "cancel", True)]])
        return None
    if low.startswith("/undo"):
        undo(s)
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
                s["choose_deadline"] = None
                tg.send(f"⚠️ Couldn't write the script: {e}\nReply 1, 2 or 3 to try again.")

    if not render:
        try:
            if due_offer_slot(s):
                run_offer(s)
        except Exception as e:
            traceback.print_exc()
            tg.send(f"⚠️ Couldn't get the news: {e}\nSend /news to try again.")

    if not render and s.get("autopilot"):
        if (s["stage"] == "awaiting_voice" and passed(s.get("script_deadline"))
                and (s.get("draft") or {}).get("fact_status") == "unsure"):
            s["script_deadline"] = None
            next_story(s, "the facts couldn't be verified")
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

    post_due(s)

    try:
        tg.ack_updates(s["offset"] - 1)
    except Exception as e:
        print(f"Doorbell ack failed (messages will be re-read safely next time): {e}")

    if json.dumps(s, sort_keys=True) != before:
        st.save(s)
    github_output("render", "true" if render else "false")


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


def cmd_render():
    import tts
    import video
    s = st.load()
    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        tg.action("upload_video")
        if s.get("voice_mode") == "ai":
            import tts
            gender = s.get("voice_gender") or "male"
            voice, engine = tts.synthesize(s["draft"]["script"], os.path.join(WORK_DIR, "ai_voice"), gender)
            s["last_gender"] = gender
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
                frames = video.check_frames(out)
                again = writer.visual_check(frames) if frames else []
                if again:  # still not right: those shots become safe cards too (name/logo cards can't be wrong)
                    more = {frames[p["beat"]]["beat"] for p in again if 0 <= p["beat"] < len(frames)}
                    tg.send("🖼 Still not right, replacing these with safe cards:\n• " +
                            "\n• ".join(p["problem"] for p in again))
                    out = video.render(voice, s["draft"], s["topic"], user_image_path=image, user_video_path=clip,
                                       exact_words=exact, safe_beats=set(beats_bad) | more)
                s["draft"]["visual_status"] = "fixed"
                s["draft"]["visual_notes"] = notes + [p["problem"] for p in again]
            else:
                s["draft"]["visual_status"] = "ok"
        except Exception as e:
            print(f"Visual check skipped: {e}")
        s["draft"]["credits"] = list(getattr(video, "LAST_CREDITS", []) or [])
        voice_info = f" · voice: {engine}" if s.get("voice_mode") == "ai" else ""
        if getattr(video, "LAST_SUMMARY", ""):
            voice_info += f"\n🎞 {video.LAST_SUMMARY}"
        if getattr(video, "LAST_SYNC", ""):
            voice_info += f"\n{video.LAST_SYNC}"
        vs = s["draft"].get("visual_status")
        voice_info += {"ok": "\n🖼 Visual check: ✅ every shot fits", "fixed": "\n🖼 Visual check: ✏️ fixed mismatched shots",
                       "issues": "\n🖼 Visual check: ⚠️ some shots may not fit — please look",
                       "skipped": "\n🖼 Visual check: skipped"}.get(vs, "")
        voice_info += "\n" + fact_line(s["draft"]).split("\n")[0]
        s["video_file_id"] = tg.send_video(out, caption="👆 Preview" + voice_info)
        s["stage"] = "awaiting_approval"
        s["preview_deadline"] = deadline() if s.get("autopilot") else None
        tg.send("Instagram caption:\n\n" + caption_for(s["draft"], s.get("voice_mode") == "ai") +
                sources_block(s) +
                "\n\n—\nTap below, or type changes to the script ✍️. Send a picture 🖼 or a short video 🎥 for the opening shot." +
                (("\n\n⚠️ Quality check needs you: autopilot won't post this one — watch it and tap Schedule if it's fine."
                  if qa_hold(s["draft"]) else autopilot_note("preview")) if s.get("autopilot") else ""),
                buttons=preview_buttons(s))
        whatsapp.alert("🎬 Your reel is ready for approval! Open Telegram to watch the preview and reply 'post'.")
    except Exception as e:
        traceback.print_exc()
        s["stage"] = "awaiting_voice"
        tg.send(f"⚠️ Couldn't make the reel: {e}\nReply \"ok\" to try the AI voice again, or send a voice note.")
        whatsapp.alert("⚠️ Your reel couldn't be made. Check Telegram and send the voice note again.")
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
    {"poll": cmd_poll, "offer": cmd_offer, "morning": cmd_offer,
     "render": cmd_render, "check": cmd_check}[mode]()

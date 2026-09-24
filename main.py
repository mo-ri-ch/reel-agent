"""Reel agent: talks to you on Telegram, then makes, schedules and posts reels.

Modes:  python main.py offer | poll | render | check
"""
import json
import os
import sys
import traceback
from datetime import datetime, timedelta

import news
import state as st
import telegram_api as tg
import whatsapp
import writer
from config import AI_VOICE_NOTE, AUTO_PICK_HOURS, POST_TIMES, TELEGRAM_CHAT_ID, WORK_DIR

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

Twice a day I send you the top AI stories.
• Reply 1, 2 or 3 to pick one, or type any topic you like
• No reply? I pick #1 automatically
• I send a script. Reply with changes ("shorter", "funnier hook"…)
• Happy with it? Reply "ok" and an AI voice reads it 🤖 (alternating male/female),
  "ok male" / "ok female" to choose, or send a voice note to use your own voice 🎤
• I send a preview. Reply "post" to schedule it for the next posting time ({', '.join(POST_TIMES)}), or "post now"
• Optional: send a picture (e.g. a screenshot) and I'll put it on the title card

Commands:
/topic <anything> – make a reel on your own topic right now
/myscript <your script> – use a script you wrote yourself (skips Gemini)
/news – get fresh stories now (e.g. to record the next reel straight away)
/queue – see scheduled reels
/script – show the current script again
/status – what I'm waiting for
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


def script_message(draft, note="Reply \"ok\" for the AI voice 🤖 (or \"ok male\" / \"ok female\"), "
                                "or send a voice note to use your own 🎤"):
    words = len(draft["script"].split())
    return (f"🎙 Script ({words} words, about {round(words / 2.6)} sec)\n\n{draft['script']}\n\n—\n{note}\n"
            "Or reply with changes, e.g. \"shorter\", \"stronger hook\", \"mention the price\".")


def reset_reel(s):
    s.update(stage="idle", draft=None, topic=None, video_file_id=None, voice_file_id=None,
             voice_mode=None, user_image_id=None, candidates=[], choose_deadline=None)


def next_offer_if_waiting(s):
    if s.get("pending_offer"):
        s["pending_offer"] = False
        offer_news(s)


def start_script(s, topic, instruction=None):
    tg.action("typing")
    tg.send("✍️ Revising the script..." if instruction else f"✍️ Writing a script about: {topic['title']}")
    draft = writer.write_script(topic, previous=s.get("draft") if instruction else None, instruction=instruction)
    image = s.get("user_image_id") if instruction else None
    reset_reel(s)
    s.update(topic=topic, draft=draft, stage="awaiting_voice", user_image_id=image)
    tg.send(script_message(draft))


def offer_news(s):
    tg.action("typing")
    headlines = news.fetch_headlines()
    used = s["history"] + [q["title"] for q in s["queue"]]
    if not headlines:
        reset_reel(s)
        tg.send("I couldn't find fresh AI news right now. Send me any topic and I'll write a script.")
        return
    picks = writer.pick_top(headlines, used)
    deadline = st.now() + timedelta(hours=AUTO_PICK_HOURS)
    reset_reel(s)
    s.update(candidates=picks, stage="choosing", choose_deadline=deadline.isoformat())
    lines = ["📰 Top AI stories right now:\n"]
    for i, p in enumerate(picks, 1):
        lines.append(f"{i}) {p['title']}\n   {p['source']}" + (f" · {p['angle']}" if p.get("angle") else ""))
    lines.append(f"\nReply with a number, or type your own topic.\n"
                 f"No reply by {deadline.strftime('%I:%M %p').lstrip('0')}? I'll go with #1.")
    tg.send("\n".join(lines))
    whatsapp.alert("📰 New AI stories are ready! Open Telegram to pick one for your next reel.")


def custom(text):
    return {"title": text.strip(), "custom": True}


def caption_for(draft, ai_voice=False):
    note = f"\n\n{AI_VOICE_NOTE}" if ai_voice and AI_VOICE_NOTE else ""
    return draft["caption"] + note + "\n\n" + " ".join(f"#{h}" for h in draft["hashtags"])


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


def approve(s, now_please=False):
    item = {"title": s["topic"]["title"], "video_file_id": s["video_file_id"],
            "caption": caption_for(s["draft"], s.get("voice_mode") == "ai")}
    s["history"] = (s["history"] + [item["title"]])[-40:]
    if now_please:
        tg.send("📤 Posting to Instagram now... (1-3 minutes)")
        link = publish_item(item)
        tg.send(f"✅ Posted! {link}")
    else:
        when = next_post_time(s)
        item["post_at"] = when.isoformat()
        s["queue"].append(item)
        tg.send(f"🗓 Scheduled for {fmt_time(when)}.\n"
                "Want to make the next one now? Send /news or /topic.")
    reset_reel(s)
    next_offer_if_waiting(s)


def post_due(s):
    now = st.now()
    for item in list(s["queue"]):
        if datetime.fromisoformat(item["post_at"]) > now:
            continue
        try:
            link = publish_item(item)
            s["queue"].remove(item)
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
def handle(s, m):
    """Handles one Telegram message. Returns 'render' when the reel needs (re)making."""
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
        s.update(voice_file_id=audio["file_id"], voice_mode="own", stage="rendering")
        tg.send("🎬 Got your recording! Making the reel now. Preview coming in a few minutes.")
        return "render"

    if photo:
        if not s.get("draft"):
            tg.send("Send me a topic first. Then you can add a picture for the title card.")
            return None
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

    if low.startswith(("/start", "/help")):
        tg.send(HELP)
    elif low.startswith("/topic"):
        topic = text[6:].strip()
        if topic:
            start_script(s, custom(topic))
        else:
            tg.send("Tell me the topic like this:\n/topic What are AI agents?")
    elif low.startswith("/myscript"):
        own = text[9:].strip()
        if not own:
            tg.send("Paste your script after the command, like:\n/myscript OpenAI just changed everything...")
        else:
            topic = s.get("topic") or (s["candidates"][0] if s["stage"] == "choosing" and s["candidates"] else None)
            topic = topic or custom(own.splitlines()[0][:60])
            draft = writer.draft_from_own_script(own, topic)
            reset_reel(s)
            s.update(topic=topic, draft=draft, stage="awaiting_voice")
            tg.send(script_message(draft, note="Got your script ✅ Record it as a voice note 🎤"))
    elif low.startswith("/news"):
        offer_news(s)
    elif low.startswith("/skip"):
        reset_reel(s)
        tg.send("👍 Skipped.")
        next_offer_if_waiting(s)
    elif low.startswith("/queue"):
        if s["queue"]:
            tg.send("🗓 Scheduled reels:\n\n" + "\n".join(
                f"• {fmt_time(datetime.fromisoformat(q['post_at']))}: {q['title']}" for q in s["queue"]) +
                "\n\nSend /clearqueue to cancel all of them.")
        else:
            tg.send("Nothing scheduled.")
    elif low.startswith("/clearqueue"):
        s["queue"] = []
        tg.send("🗑 Cleared all scheduled reels.")
    elif low.startswith("/script"):
        tg.send(script_message(s["draft"]) if s.get("draft") else "No script right now.")
    elif low.startswith("/status"):
        tg.send({"idle": "💤 Nothing in progress. Send a topic or /news.",
                 "choosing": "Waiting for you to pick a story (1, 2, 3 or your own topic).",
                 "awaiting_voice": "Waiting for your voice note 🎤",
                 "rendering": "Making the reel 🎬",
                 "awaiting_approval": "Waiting for you to reply 'post', 'post now' or 'redo'."}.get(stage, stage)
                + f"\nScheduled reels: {len(s['queue'])}")
    elif stage == "choosing":
        cands = s["candidates"]
        if low.isdigit() and 1 <= int(low) <= len(cands):
            start_script(s, cands[int(low) - 1])
        else:
            start_script(s, custom(text))
    elif stage == "awaiting_voice":
        req = voice_request(low)
        if req:
            gender = req if req != "alternate" else ("male" if s.get("last_gender") == "female" else "female")
            s.update(voice_mode="ai", voice_gender=gender, voice_file_id=None, stage="rendering")
            tg.send(f"🤖 Making the reel with a {gender} AI voice. Preview coming in a few minutes.")
            return "render"
        start_script(s, s["topic"], instruction=text)
    elif stage == "awaiting_approval":
        if low in POST_NOW_WORDS:
            approve(s, now_please=True)
        elif low in POST_WORDS:
            approve(s)
        elif low in REDO_WORDS:
            s["stage"] = "awaiting_voice"
            tg.send(script_message(s["draft"], note="Reply \"ok male\" / \"ok female\" for a new AI voice 🤖, "
                                                    "or send a voice note 🎤"))
        else:
            start_script(s, s["topic"], instruction=text)
    elif stage == "rendering":
        tg.send("Still making your reel, hang on 🎬")
    else:  # idle: any message is a new topic
        start_script(s, custom(text))
    return None


# ---------- modes ----------
def cmd_poll():
    s = st.load()
    before = json.dumps(s, sort_keys=True)
    render = False
    for u in tg.get_updates(s["offset"]):
        s["offset"] = u["update_id"] + 1
        m = u.get("message")
        if not m or str(m["chat"]["id"]) != str(TELEGRAM_CHAT_ID):
            continue
        try:
            if handle(s, m) == "render":
                render = True
                break  # leave later messages for the next check
        except Exception as e:
            traceback.print_exc()
            tg.send(f"⚠️ Something went wrong: {e}")

    if not render and s["stage"] == "choosing" and s.get("choose_deadline"):
        if st.now() >= datetime.fromisoformat(s["choose_deadline"]) and s["candidates"]:
            pick = s["candidates"][0]
            tg.send(f"⏰ No reply, so I picked #1: {pick['title']}")
            try:
                start_script(s, pick)
                whatsapp.alert("🎙 Today's script is ready. Open Telegram and record it as a voice note.")
            except Exception as e:
                s["choose_deadline"] = None
                tg.send(f"⚠️ Couldn't write the script: {e}\nReply 1, 2 or 3 to try again.")

    post_due(s)

    if json.dumps(s, sort_keys=True) != before:
        st.save(s)
    github_output("render", "true" if render else "false")


def cmd_offer():
    """Runs at each daily slot (8 AM and 4 PM by default)."""
    s = st.load()
    try:
        if s["stage"] in ("idle", "choosing"):
            offer_news(s)
        else:
            s["pending_offer"] = True
            tg.send("🔔 Time for the next reel! Finish the current one (or send /skip) "
                    "and I'll send fresh stories right after.")
            whatsapp.alert("🔔 Time for your next reel! Finish the current one on Telegram first.")
    except Exception as e:
        traceback.print_exc()
        tg.send(f"⚠️ Couldn't get the news: {e}\nSend /news to try again, or send any topic.")
    st.save(s)


def cmd_render():
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
        out = video.render(voice, s["draft"], s["topic"], user_image_path=image)
        voice_info = f" · voice: {engine}" if s.get("voice_mode") == "ai" else ""
        s["video_file_id"] = tg.send_video(out, caption="👆 Preview" + voice_info)
        s["stage"] = "awaiting_approval"
        tg.send("Instagram caption:\n\n" + caption_for(s["draft"], s.get("voice_mode") == "ai") +
                f"\n\n—\nReply \"post\" → scheduled for {fmt_time(next_post_time(s))} ✅\n"
                "\"post now\" → publish right away\n\"redo\" → new voice (AI or your own) 🎤\n"
                "Send a picture → use it on the title card 🖼\nOr send changes to the script ✍️")
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

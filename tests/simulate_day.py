"""Simulates full 24-hour days of the agent with fake news, voices, renders and Instagram, and checks that every
post time gets a reel. Run from the repo root with Python 3.11 (the version GitHub uses):

    python3.11 tests/simulate_day.py

Exit code 0 = all scenarios passed. Needs: requests feedparser Pillow numpy (no internet, no secrets)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DRIVER = r'''
import sys, random, json
from datetime import timedelta, datetime
import main, state as st, telegram_api as tg, writer, news, instagram, video, tts, whatsapp
SCENARIO = sys.argv[1]
main.TELEGRAM_CHAT_ID = "1"
log = []
clock = [datetime.fromisoformat("2026-10-08T00:00:00+05:30")]
tg.send = lambda t, buttons=None, html=False: log.append(clock[0].strftime("%H:%M ") + t.split("\n")[0][:90])
tg.action = lambda *a: None
tg.get_updates = lambda o: []
tg.ack_updates = lambda u: None
tg.send_video = lambda p, caption="", buttons=None: "VID" + clock[0].strftime("%H%M")
tg.download = lambda f, d: d
whatsapp.alert = lambda *a, **k: None
W = ("Nvidia Anthropic OpenAI Google Meta Sarvam Mistral Apple Samsung Tesla Amazon Perplexity DeepSeek Qwen Microsoft "
     "Adobe Intel Figma Notion Canva Oracle IBM Cisco Dell Sony Xiaomi Baidu Alibaba Tencent Huawei Zoom Slack Uber "
     "Spotify Netflix Shopify Stripe Airbnb Reddit Pinterest").split()
T = "chip glasses robot browser model agent phone laptop camera search watch car satellite drone headset".split()
n = [0]
def heads(**k):
    n[0] += 1
    random.seed(n[0])
    return [{"title": f"{random.choice(W)} unveils {random.choice(T)} {n[0]}{i}x", "link": f"https://x/{n[0]}{i}",
             "summary": "", "source": "TechCrunch", "published": ""} for i in range(6)]
news.fetch_headlines = heads
news.real_url = lambda u: u
writer.pick_top = lambda h, u: h[:3]
writer.drop_same_events = lambda p, c: p
calls = [0]
def write_script(t, previous=None, instruction=None):
    if SCENARIO == "gemini_down":
        raise RuntimeError("Gemini overloaded")
    body = " ".join(["Jensen Huang of Nvidia confirmed it on Tuesday with three billion dollars of orders."] * 5)
    calls[0] += 1
    if SCENARIO == "general_half" and calls[0] % 2:
        body = " ".join(["the company shared some results and people are curious about what comes next."] * 5)
    return {"title": t["title"], "script": "Here is what happened with " + t["title"] + ". " + body + " Would you use it?",
            "caption": "c " + t["title"], "hashtags": [], "beats": [], "sources": []}
writer.write_script = write_script
def fact_check(d, t):
    bad = SCENARIO == "facts_fail" and "robot" in t["title"]
    return d, ("unsure" if bad else "ok"), (["no source"] if bad else [])
writer.fact_check = fact_check
writer.visual_check = lambda f: []
main.resolve_links = lambda u, limit=4: [x for x in u if x]
def render(*a, **k):
    if SCENARIO == "render_fails" and "chip" in a[1].get("script", ""):
        raise RuntimeError("ffmpeg exploded")
    return "x.mp4"
video.render = render
video.check_frames = lambda o: []
video.editor_frames = lambda o: []
def editor_review(d, t, f, times):
    if SCENARIO == "editor_low":
        return {"overall": 5.5, "scores": {}, "one_line": "too generic", "script_fixes": ["LINE 1: name the model"],
                "visual_beats": [], "visual_notes": []}
    return {"overall": 8.5, "scores": {}, "one_line": "good", "script_fixes": [], "visual_beats": [], "visual_notes": []}
writer.editor_review = editor_review
video.transcribe = lambda wav, hint="": []
def synth(t, b, g, e="microsoft", **k):
    tts.LAST_ENGINE = "microsoft"
    tts.LAST_WORDS = [{"text": w} for w in t.split()]
    return ("v.wav", "Ava (Microsoft), female")
tts.synthesize = synth
posted = []
instagram.publish_reel = lambda p, c: posted.append(clock[0].strftime("%H:%M")) or "https://instagram.com/reel/X/"
instagram.reels_posted_on = lambda day, tz: None
main.IG_READY = lambda: False
st.now = lambda: clock[0]
main.st.now = st.now
s = st.load()
main.reset_reel(s)
for k in ("last_auto_offer", "digest_for", "report_day", "behind_since", "paused", "ig_count"):
    s.pop(k, None)
s.update(autopilot=True, queue=[], post_log=[], guarantee_since=clock[0].isoformat(), tried=[], held=[],
         pending_offer=False, history=[], posted_log=[])
st.save(s)
while clock[0] < datetime.fromisoformat("2026-10-08T23:59:00+05:30"):
    out = []
    main.github_output = lambda k, v: out.append(v)
    main.cmd_poll()
    if out and out[-1] == "true":
        main.cmd_render()
    clock[0] += timedelta(minutes=5)
print(json.dumps({"posted": posted, "slots": sorted(main.POST_TIMES)}))
'''

SCENARIOS = ["normal", "render_fails", "facts_fail", "gemini_down", "general_half", "editor_low"]


def run(scenario):
    with tempfile.TemporaryDirectory() as tmp:
        for name in os.listdir(ROOT):
            if name.endswith(".py") or name == "state.json":
                shutil.copy(os.path.join(ROOT, name), tmp)
        with open(os.path.join(tmp, "_driver.py"), "w") as f:
            f.write(DRIVER)
        env = {**os.environ, "WORK_DIR": os.path.join(tmp, "work"), "TELEGRAM_CHAT_ID": "1"}
        for k in ("IG_ACCESS_TOKEN", "IG_USER_ID"):
            env.pop(k, None)
        p = subprocess.run([sys.executable, "_driver.py", scenario], cwd=tmp, env=env, capture_output=True, text=True,
                           timeout=900)
        last = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if not last:
            return False, f"crashed:\n{p.stderr[-2000:]}"
        res = json.loads(last[-1])
        posted, slots = res["posted"], res["slots"]
        on_time = sum(1 for t in slots if any(abs(_mins(p_) - _mins(t)) <= 5 for p_ in posted))
        ok = len(posted) == len(slots) and on_time == len(slots)
        return ok, f"{len(posted)}/{len(slots)} posted, {on_time} on time: {posted}"


def _mins(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


if __name__ == "__main__":
    failed = False
    for sc in SCENARIOS:
        ok, msg = run(sc)
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'}  {sc:13} {msg}")
    sys.exit(1 if failed else 0)

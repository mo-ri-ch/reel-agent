"""Quick checks of the safety filters. Run from the repo root: python3.11 tests/test_checks.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news  # noqa: E402
import tts  # noqa: E402
import writer  # noqa: E402

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


# the voice-over must say the script and nothing else
script = ("President Donald Trump announced a new AI task force called the Super Intelligence Force. "
          "It will coordinate federal AI research. What do you think of the new initiative?")
W = script.replace(".", " ").replace("?", " ").split()
check("voice exact", tts.speech_matches(W, script)[0], True)
check("voice echo at end", tts.speech_matches(W + "Trump announced the announcement of the new initiative".split(),
                                              script)[0], True)
check("voice instruction read aloud", tts.speech_matches(
    "Read this like a clear confident tech news presenter natural pace".split() + W, script)[0], False)
check("voice stage direction", tts.speech_matches(W + "with small pauses between sentences".split(), script)[0], False)
check("voice line skipped", tts.speech_matches([w for w in W if w not in ("coordinate", "federal", "research", "It",
                                                                         "will", "AI")], script)[0], False)

# the Google voice gets director notes, and the script comes last under the transcript header, untouched
dp = tts.director_prompt("OpenAI just launched GPT-6.", "amused disbelief\n#### hack")
check("director transcript last", dp.endswith("#### TRANSCRIPT\nOpenAI just launched GPT-6."), True)
check("director one transcript header", dp.count("\n#### TRANSCRIPT"), 1)

# the owner's Fish Audio voice is tried first; out of credits or down -> the regular voices take over
_f, _g, _key = tts._fish, tts._google, tts.FISH_API_KEY
tts.FISH_API_KEY = "test"
tts._google = lambda text, out, voice, delivery=None: "google.wav"
def _out(*a, **k):
    raise tts.FishOut("HTTP 402")
tts._fish = _out
path, _ = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google", fish_voice="abc")
check("fish out -> google", (path, tts.LAST_ENGINE, tts.FISH_PROBLEM), ("google.wav", "google", "out"))
def _down(*a, **k):
    raise RuntimeError("HTTP 503")
tts._fish = _down
path, _ = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google", fish_voice="abc")
check("fish down -> google", (tts.LAST_ENGINE, tts.FISH_PROBLEM), ("google", "HTTP 503"))
tts._fish = lambda text, out, vid, **k: "fish.mp3"
path, _ = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google", fish_voice="abc")
check("fish used", (path, tts.LAST_ENGINE), ("fish.mp3", "fish"))
tts._fish = lambda text, out, vid, **k: (_ for _ in ()).throw(RuntimeError("503")) if vid == "own" else vid + ".mp3"
path, label = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google",
                             fish_voice=[("own", "your voice"), ("lib1", "Narrator (Fish Audio)")])
check("fish own down -> library voice", (path, label, tts.LAST_FISH_ID), ("lib1.mp3", "Narrator (Fish Audio)", "lib1"))
tts._fish = _out
path, _ = tts.synthesize("x y z", "/tmp/x", "male", "google", fish_voice=[("own", "a"), ("lib1", "b")])
check("fish credits out -> skip library", tts.LAST_ENGINE, "google")
tts._fish, tts._google, tts.FISH_API_KEY = _f, _g, _key

# Fish library voices take turns
import main  # noqa: E402
_k = main.FISH_API_KEY
main.FISH_API_KEY = "test"
_s = {"fish_disabled": True, "fish_pool": [{"id": "paula", "name": "Paula"}, {"id": "ethan", "name": "Ethan"}]}
check("fish first pick", main.fish_voices(_s)[0][0], "paula")
_s["last_fish_id"] = "paula"
check("fish alternates", main.fish_voices(_s)[0][0], "ethan")
_s["last_fish_id"] = "ethan"
check("fish alternates back", main.fish_voices(_s)[0][0], "paula")
_s2 = {"fish_disabled": True, "fish_pool": [{"id": "paula", "name": "Paula"}, {"id": main.ETHAN_ID, "name": "Ethan"}]}
_firsts = []
for _n in range(8):
    _s2["fish_turn"] = _n
    _firsts.append(main.fish_voices(_s2)[0][0] == main.ETHAN_ID)
check("mostly Ethan (3 of 4)", sum(_firsts), 6)
main.FISH_API_KEY = _k

# a broken memory file falls back to the backup; control files are applied once and removed
import json as _json, os as _os, tempfile as _tf  # noqa: E402
import state as _st  # noqa: E402
_d = _tf.mkdtemp()
_old = (_st.STATE_FILE, _st.BACKUP_FILE, _st.CONTROL_DIR)
_st.STATE_FILE, _st.BACKUP_FILE, _st.CONTROL_DIR = (_os.path.join(_d, "state.json"), _os.path.join(_d, "state.backup.json"),
                                                     _os.path.join(_d, "control"))
open(_st.STATE_FILE, "w").write('{"stage": "x",\n  }broken')
_json.dump({"stage": "choosing", "fish_disabled": True}, open(_st.BACKUP_FILE, "w"))
_os.makedirs(_st.CONTROL_DIR)
_json.dump({"set": {"autopilot": True}, "unset": ["fish_disabled"]}, open(_os.path.join(_st.CONTROL_DIR, "1.json"), "w"))
_s = _st.load()
check("backup used", (_s["stage"], bool(_st.RECOVERED)), ("choosing", True))
check("control applied", ("fish_disabled" in _s, _s["autopilot"], _os.listdir(_st.CONTROL_DIR)), (False, True, []))
_st.save(_s)
check("both copies saved", _json.load(open(_st.STATE_FILE))["stage"], "choosing")
_st.STATE_FILE, _st.BACKUP_FILE, _st.CONTROL_DIR = _old
_st.RECOVERED = None

# thin scripts get one expansion; if still thin, the story is skipped
_ws, _fc, _ms, _send = main.writer.write_script, main.fact_check_step, main.make_specific, main.tg.send
main.tg.send = lambda *a, **k: None
main.fact_check_step = lambda d, t: d
main.make_specific = lambda d, t: d
main.writer.write_script = lambda t, previous=None, instruction=None: {"script": "word " * 85}
check("thin script expanded", main.substance_step({"script": "too short " * 10}, {}).get("fact_status"), None)
main.writer.write_script = lambda t, previous=None, instruction=None: {"script": "word " * 30}
check("still thin -> skipped", main.substance_step({"script": "too short " * 10}, {}).get("fact_status"), "unsure")
check("model's thin flag ignored at 80 words", main.substance_step({"script": "word " * 80, "thin": True}, {})
      .get("fact_status"), None)
main.writer.write_script = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503 overloaded"))
check("gemini busy doesn't crash", main.substance_step({"script": "short " * 20}, {}).get("fact_status"), "unsure")
check("named but no number kept", main.specific_facts_step(
    {"script": "Anthropic launched Claude Security scans for GitHub projects, said Jason Clinton. " * 6}, {})
      .get("fact_status"), None)
check("full script untouched", main.substance_step({"script": "word " * 80}, {}).get("fact_status"), None)
# over-long scripts get one trim; a failed or bad trim keeps the original
main.writer.write_script = lambda t, previous=None, instruction=None: {"script": "word " * 95}
check("long script trimmed", len(main.trim_step({"script": "long " * 147}, {})["script"].split()), 95)
check("normal script not trimmed", len(main.trim_step({"script": "ok " * 100}, {})["script"].split()), 100)
main.writer.write_script = lambda t, previous=None, instruction=None: {"script": "word " * 40}
check("over-trim rejected", len(main.trim_step({"script": "long " * 140}, {})["script"].split()), 140)
main.writer.write_script = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503 overloaded"))
check("trim failure keeps draft", len(main.trim_step({"script": "long " * 140}, {})["script"].split()), 140)
main.writer.write_script, main.fact_check_step, main.make_specific, main.tg.send = _ws, _fc, _ms, _send

# strict specificity: real names + a number/date
_n, _num = writer.specificity("OpenAI's revenue is twenty billion dollars below target, TechCrunch reported on Tuesday.")
check("specific script", (len(_n) >= 2, _num), (True, True))
_n, _num = writer.specificity("The company shared new results. Experts are curious about what comes next.")
check("general script", (len(_n) >= 2, _num), (False, False))
check("vague new model", bool(writer.vague_phrases("They released a new AI model for coding.")), True)
check("named new model", bool(writer.vague_phrases("They released a new model called Codex Max.")), False)
check("vague experts debating", bool(writer.vague_phrases("Independent experts are now actively debating it.")), True)
check("filler raises questions", bool(writer.vague_phrases("This raises urgent biosecurity questions.")), True)
check("researchers at X ok", bool(writer.vague_phrases("Study done. Researchers at Stanford University found it.")), False)
check("bare researchers vague", bool(writer.vague_phrases("Study done. Researchers found it works.")), True)
check("named researchers ok", bool(writer.vague_phrases("MIT researchers led by Regina Barzilay built it.")), False)
check("vague tech giants", bool(writer.vague_phrases("Tech giants are racing to build agents.")), True)

# the editor-in-chief's score: inaccurate or generic reels can't pass on other strengths
_r = writer.score_review({"scores": {"hook": 9, "specific": 9, "substance": 9, "accuracy": 9, "visuals": 9, "flow": 9},
                          "visual_problems": [{"line": 2, "problem": "fruit for Apple"}]}, 5)
check("editor good", (_r["overall"], _r["visual_beats"]), (9.0, [1]))
_r = writer.score_review({"scores": {"hook": 10, "specific": 10, "substance": 10, "accuracy": 5, "visuals": 10,
                                     "flow": 10}}, 5)
check("editor inaccurate capped", _r["overall"], 6.5)
check("editor bad json", writer.score_review([], 3)["overall"], 7.0)

# the final repeat gate: renamed launches and follow-up pieces about the same event are caught
_ask2 = writer.ask
writer.ask = lambda *a, **k: '{"repeat": true, "covered": 1, "why": "same model"}'
check("same event caught", writer.same_event({"title": "Mistral says Le Chonk can challenge the best AI models"},
                                             ["Mistral's new 1T model aims to leapfrog rivals — said: Mistral's Le Chonk..."]),
      "Mistral's new 1T model aims to leapfrog rivals")
check("no shared word = not trusted", writer.same_event({"title": "Utah lets AI prescribe medicine"},
                                                         ["Mistral's new 1T model aims to leapfrog rivals"]), None)
writer.ask = lambda *a, **k: '{"repeat": false, "covered": 0}'
check("different story kept", writer.same_event({"title": "Mistral cuts API prices"}, ["Mistral's new 1T model"]), None)
writer.ask = _ask2

# Claude writes when a key is set; any problem falls back to Gemini; a refused key switches Claude off for the run
import config as _cfg  # noqa: E402
_post, _key, _at, _ask3 = writer.requests.post, _cfg.ANTHROPIC_API_KEY, writer.article_text, writer.ask
class _R:
    def __init__(self, code, body): self.status_code, self._b, self.text = code, body, str(body)
    def json(self): return self._b
_cfg.ANTHROPIC_API_KEY = "test"
_cfg.USE_CLAUDE = True
writer.CLAUDE_OFF[0] = False
writer.article_text = lambda url, limit=5000: "Anthropic released Claude Sonnet 5.5 on Tuesday. " * 40
writer.requests.post = lambda *a, **k: _R(200, {"content": [{"type": "text", "text":
    '{"title": "t", "beats": [{"line": "Anthropic released Claude Sonnet 5.5.", "visual": "official"}]}'}]})
writer.ask = lambda *a, **k: '{"line": "Anthropic just shipped Claude Sonnet 5.5."}'
check("claude writes", writer.write_script({"title": "Sonnet 5.5", "link": "https://x"})["writer_model"], "claude")
writer.requests.post = lambda *a, **k: _R(402, {"error": "credit balance too low"})
writer.ask = lambda *a, **k: '{"title": "t", "beats": [{"line": "Anthropic released Claude Sonnet 5.5 today.", "visual": "official"}]}'
check("no credit -> gemini", writer.write_script({"title": "Sonnet 5.5", "link": "https://x"})["writer_model"], "gemini")
check("claude switched off", writer.CLAUDE_OFF[0], True)
writer.requests.post, _cfg.ANTHROPIC_API_KEY, writer.article_text, writer.ask = _post, _key, _at, _ask3
writer.CLAUDE_OFF[0] = False

# Gemini's free quota used up: Claude takes the job (within today's budget); no budget = the error stays
_cfg.ANTHROPIC_API_KEY = "test"
_sleep = writer.time.sleep
writer.time.sleep = lambda x: None
def _fake_post(url, *a, **k):
    if "anthropic" in url and "temperature" in (k.get("json") or {}):
        return _R(400, {"error": "`temperature` is deprecated for this model."})
    if "googleapis" in url:
        return _R(429, {"error": "quota PerDay"})
    return _R(200, {"content": [{"type": "text", "text": '{"ok": 1}'}]})
writer.requests.post = _fake_post
writer.BACKUP_LEFT[0] = 1
check("quota -> claude backup", writer.parse_json(writer.ask("x", search=True, json_mode=True)), {"ok": 1})
check("backup counted", writer.BACKUP_CALLS[0], 1)
try:
    writer.ask("x")
    check("budget used up -> error", "no error", "error")
except RuntimeError:
    pass
# Claude is off: a model used up for the day is skipped next time, a missing one (404) too; others take over
_cfg.USE_CLAUDE = False
writer.EXHAUSTED.clear(); writer.MISSING.clear()
seen = []
def _chain_post(url, *a, **k):
    m = url.split("/models/")[1].split(":")[0]
    seen.append(m)
    if m == writer.GEMINI_MODEL:
        return _R(429, {"error": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"})
    if m == "gemini-3.7-flash":
        return _R(404, {"error": "not found"})
    return _R(200, {"candidates": [{"content": {"parts": [{"text": "ok from " + m}]}}]})
writer.requests.post = _chain_post
check("next free model answers", writer.ask("x"), "ok from gemini-3.5-flash")
check("used-up model remembered", writer.GEMINI_MODEL in writer.EXHAUSTED, True)
check("missing model remembered", "gemini-3.7-flash" in writer.MISSING, True)
seen.clear()
writer.ask("x")
check("skips used-up and missing", seen, ["gemini-3.5-flash"])
def _timeout_post(url, *a, **k):
    if "gemini-3.5-flash:" in url:
        raise writer.requests.exceptions.ReadTimeout("slow")
    return _R(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
writer.requests.post = _timeout_post
check("hung model -> next model", writer.ask("x"), "ok")
_pm = _R(429, {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}],
                         "message": "see PerDay docs"}})
check("per-minute limit isn't daily", writer.daily_limit_hit(_pm), False)
_pd = _R(429, {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
check("per-day limit", writer.daily_limit_hit(_pd), True)
check("light jobs start on Flash-Lite", "lite" in writer.model_order(light=True)[0], True)
check("reset is in the future", writer.quota_reset_after(writer.time.time()) > writer.time.time(), True)
writer.EXHAUSTED.clear(); writer.MISSING.clear(); writer.MODEL_USE.clear()
writer.requests.post, _cfg.ANTHROPIC_API_KEY = _post, _key
writer.time.sleep = _sleep
_cfg.USE_CLAUDE = False
writer.BACKUP_LEFT[0] = writer.BACKUP_CALLS[0] = 0
writer.ERRORS.clear()
_cfg.ANTHROPIC_API_KEY = "test"
writer.requests.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Claude must not be called"))
writer.ask = lambda *a, **k: '{"title": "t", "beats": [{"line": "Anthropic released Claude Sonnet 5.5 today.", "visual": "official"}]}'
check("claude off by default -> gemini", writer.write_script({"title": "x", "link": "https://x"})["writer_model"], "gemini")
writer.requests.post, _cfg.ANTHROPIC_API_KEY, writer.ask = _post, _key, _ask3

# hype / AI-sounding wording is caught, names that look like hype words are not; em dashes become commas
check("hype words", writer.hype_phrases("This groundbreaking model will revolutionize coding."),
      ["groundbreaking", "revolutionize"])
check("names not hype", writer.hype_phrases("Realm and Harness raised money."), [])
check("not-just shape", bool(writer.hype_phrases("It's not just a chatbot, it's an agent.")), True)
check("em dash spoken", writer.clean_spoken("OpenAI\u2014the maker of ChatGPT\u2014cut prices."),
      "OpenAI, the maker of ChatGPT, cut prices.")

_ws, _fcs = writer.write_script, main.fact_check_step
plain = " ".join(["Nvidia sold three billion dollars of chips to Microsoft this week."] * 6)
writer.write_script = lambda topic, previous=None, instruction=None: {"script": plain, "beats": []}
main.fact_check_step = lambda d, t: {**d, "fact_status": "ok"}
check("de-hype rewrites", main.de_hype({"script": "A groundbreaking deal. " + plain}, {})["script"], plain)
main.fact_check_step = lambda d, t: {**d, "fact_status": "unsure"}
check("de-hype keeps checked original", main.de_hype({"script": "A groundbreaking deal."}, {})["script"],
      "A groundbreaking deal.")
writer.write_script, main.fact_check_step = _ws, _fcs

cap = main.caption_for({"caption": "OpenAI cut prices\u2014by half.", "hashtags": [str(i) for i in range(12)]})
check("max 5 hashtags", cap.count("#"), 5)
check("caption em dash", "\u2014" in cap, False)

check("retry delay read", writer.retry_delay('"retryDelay": "34s"'), 35.0)
check("retry delay capped", writer.retry_delay('"retryDelay": "300s"'), 60)
check("drop reddit PSA", news.newsworthy({"title": "PSA: DeepSeek V4.1 Flash habitually exfiltrates API keys",
                                         "source": "r/LocalLLaMA"}), False)

# the editor waits and retries when Gemini is busy, instead of skipping the review
import video as _video  # noqa: E402
_ef, _er, _wait = _video.editor_frames, writer.editor_review, main.EDITOR_RETRY_WAIT
_video.editor_frames = lambda out: []
main.EDITOR_RETRY_WAIT = 0
tries = [0]
def _flaky_review(*a):
    tries[0] += 1
    if tries[0] < 2:
        raise RuntimeError("busy")
    return {"overall": 9.0, "scores": {}, "one_line": "great", "script_fixes": [], "visual_beats": [], "visual_notes": []}
writer.editor_review = _flaky_review
st_ = {"draft": {"beats": []}, "topic": {}}
check("editor retried", main.editor_step(st_, "v.mp4", lambda b: "v.mp4"), ("v.mp4", "ok"))
check("editor score kept", st_["draft"]["editor"]["overall"], 9.0)
writer.editor_review = lambda *a: (_ for _ in ()).throw(RuntimeError("busy"))
try:
    main.editor_step({"draft": {"beats": []}, "topic": {}}, "v.mp4", lambda b: "v.mp4")
    check("no editor -> no post", "posted", "error")
except RuntimeError:
    pass
_video.editor_frames, writer.editor_review, main.EDITOR_RETRY_WAIT = _ef, _er, _wait

# captions: frozen / wrong word timings (12 Oct Nadella reel) are caught and replaced by even timing
_scr = ("Satya Nadella says we should assume all AI models are compromised.\nThe Microsoft CEO posted this warning on X "
        "today.\nHe argues we can no longer treat AI as simple black boxes.")
_beats = [{"line": l} for l in _scr.split("\n")]
_bad = [{"text": w, "start": 0.3 + i * 0.3, "end": 0.5 + i * 0.3} for i, w in enumerate("Satya Nadella says".split())] + \
       [{"text": w, "start": 18 + i * 0.3, "end": 18.2 + i * 0.3} for i, w in enumerate("akin to the new approach".split())]
check("broken timing caught", bool(_video.sync_problem(_bad, _scr, _beats, 22.0)), True)
_ev = _video.even_words(_scr, _bad, 22.0)
check("even timing uses script words", [w["text"] for w in _ev], _scr.split())
check("even timing passes", _video.sync_problem(_ev, _scr, _beats, 22.0), "")
_good = [{"text": w, "start": i * 0.35, "end": i * 0.35 + 0.3} for i, w in enumerate(_scr.split())]
check("good timing accepted", _video.sync_problem(_good, _scr, _beats, len(_good) * 0.35 + 0.5), "")


check("one area at 6 may pass", writer.score_review({"scores": {"hook": 8, "specific": 9, "substance": 9, "accuracy": 9,
                                                            "visuals": 6, "flow": 9}}, 5)["overall"], 8.3)
check("two weak areas fail", writer.score_review({"scores": {"hook": 6, "specific": 9, "substance": 9, "accuracy": 9,
                                                          "visuals": 6, "flow": 9}}, 5)["overall"], 6.5)
check("an area at 5 fails", writer.score_review({"scores": {"hook": 9, "specific": 9, "substance": 9, "accuracy": 9,
                                                         "visuals": 5, "flow": 9}}, 5)["overall"], 6.5)
check("accuracy 6 fails", writer.score_review({"scores": {"hook": 9, "specific": 9, "substance": 9, "accuracy": 6,
                                                       "visuals": 9, "flow": 9}}, 5)["overall"], 6.5)
check("no posting below 8", main.EDITOR_FLOOR, 8.0)

check("drop opinion column", news.newsworthy({"title": "Why artificial intelligence must be stopped now",
                                             "source": "www.resilience.org"}), False)
check("keep real news", news.newsworthy({"title": "Amazon in talks to acquire AI chip startup Flexibility",
                                         "source": "Reuters"}), True)

check("drop personal essay", news.newsworthy({"title": "Learning to use local AI is exciting, overwhelming, and frustrating",
                                             "source": "The Verge"}), False)
check("drop market-research blog", news.newsworthy({"title": "U.S. High Bandwidth Memory (HBM): Solving AI Bottlenecks",
                                                  "source": "Kings Research", "link": "https://www.kingsresearch.com/blog/x"}), False)
check("keep 'Meta' news", news.newsworthy({"title": "Meta cuts 600 AI jobs", "source": "Reuters"}), True)

# all free models used up: pause quietly until the reset (one message), instead of a failure every 10 minutes
_sent, _send = [], main.tg.send
main.tg.send = lambda *a, **k: _sent.append(a[0])
writer.EXHAUSTED.clear(); writer.MISSING.clear()
check("not resting with models left", main.gemini_resting({}), None)
for _m in writer.model_order() + writer.model_order(light=True):
    writer.EXHAUSTED[_m] = writer.time.time()
_s = {}
_r1 = main.gemini_resting(_s); _r2 = main.gemini_resting(_s)
check("resting until reset", _r1 is not None and _r1 > main.st.now(), True)
check("told once", len(_sent), 1)
writer.EXHAUSTED.clear(); main.tg.send = _send

check("json trailing comma", writer.parse_json('{"a": [1, 2,], "b": {"c": 3,},}'), {"a": [1, 2], "b": {"c": 3}})

check("drop panel event", news.newsworthy({"title": "Lyceum Project Leaders Talk Corporate Funding and AI in Education",
                                          "source": "The Harvard Crimson"}), False)
check("keep company talks", news.newsworthy({"title": "OpenAI in talks to buy Windsurf for $3B", "source": "Reuters"}), True)

# real-page screenshots: no URL -> no shot (the drawn card is used); a blank page is detected
import webshot as _ws  # noqa: E402
from PIL import Image as _Im  # noqa: E402
check("no url, no page shot", _ws.capture("", "/tmp/x.png"), None)
_Im.new("RGB", (400, 900), (255, 255, 255)).save("/tmp/_blank.png")
check("blank page detected", _ws.looks_blank("/tmp/_blank.png"), True)

# Instagram music: the track is sent with the post; if Instagram refuses it, the reel still posts without it
import instagram as _ig  # noqa: E402
_calls, _igpost, _igget = [], _ig.requests.post, _ig.requests.get
def _fake_ig_post(url, data=None, **k):
    _calls.append(dict(data) if isinstance(data, dict) else {})
    if isinstance(data, dict) and "audio_configuration" in data and "media" in url and "publish" not in url:
        return _R(400, {"error": {"message": "audio not available"}})
    return _R(200, {"id": "123", "uri": "https://up"})
_ig.requests.post = _fake_ig_post
_ig.requests.get = lambda url, **k: _R(200, {"data": [], "status_code": "FINISHED", "permalink": "https://ig/p/1"})
open("/tmp/_v.mp4", "wb").write(b"0" * 10)
check("music refused -> still posts", _ig.publish_reel("/tmp/_v.mp4", "cap", audio_id="999"), "https://ig/p/1")
check("music was asked first", "audio_configuration" in _calls[0], True)
check("music error recorded", bool(_ig.AUDIO_ERROR[0]), True)
_ig.requests.get = lambda url, **k: _R(200, {"data": [{"audio_id": "a1", "title": "Song", "display_artist": "X"}]})
check("trending music parsed", _ig.search_music(), [{"id": "a1", "title": "Song", "artist": "X"}])
_ig.requests.get = lambda url, **k: _R(200, {"audio": [{"audio_id": "2188901821285578", "duration_in_ms": 221565,
                                                        "title": "End Of The Earth"}]})
check("music in Instagram's real format", _ig.search_music()[0]["id"], "2188901821285578")
_ig.requests.post, _ig.requests.get = _igpost, _igget

# the article's header photo must show the story (no joke stock photos as the opening picture)
_ask_pf = writer.ask
writer.ask = lambda *a, **k: "NO"
check("joke photo rejected", _video.picture_fits(_Im.new("RGB", (300, 200)), "Managers struggle with AI"), False)
writer.ask = lambda *a, **k: "YES"
check("fitting photo kept", _video.picture_fits(_Im.new("RGB", (300, 200)), "Meta new shares"), True)
writer.ask = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("busy"))
check("check down -> photo kept", _video.picture_fits(_Im.new("RGB", (300, 200)), "x"), True)
writer.ask = _ask_pf

# legal/consent pages are never shown as the product page or article
check("terms url skipped", bool(_video.LEGAL_URL.search("https://www.sony.com/en/terms-of-use/")), True)
check("privacy url skipped", bool(_video.LEGAL_URL.search("https://openai.com/policies/privacy-policy")), True)
check("product url kept", bool(_video.LEGAL_URL.search("https://openai.com/index/introducing-gpt-6/")), False)
check("github url kept", bool(_video.LEGAL_URL.search("https://github.com/microsoft/termsearch")), False)
import webshot as _ws
check("consent page caught", bool(_ws.LEGAL_PAGE.search("Before you continue to YouTube")), True)
check("article page kept", bool(_ws.LEGAL_PAGE.search("OpenAI working on new $30B raise at $1.25T valuation")), False)

# vague references must be caught
check("vague developer", bool(writer.vague_phrases("A developer from Kerala just dropped Laya.")), True)
check("vague experts argue", bool(writer.vague_phrases("Experts argue we must secure DNA supply chains.")), True)
check("drop newsletter roundup", news.newsworthy({"title": "Digital detox how-to; artificial intelligence in nursing; when to see your doctor about GI issues; plus other stories with Vanderbilt Health sources", "source": "Vanderbilt Health News", "link": "https://news.vumc.org/x"}), False)
check("drop how-to essay", news.newsworthy({"title": "How to Defend Against AI-Designed Viruses",
                                            "source": "War on the Rocks"}), False)
check("drop campus grants", news.newsworthy({"title": "Penn State Announces New Artificial Intelligence Grants "
                                                     "For Faculty", "source": "Onward State"}), False)
check("drop opinion section by URL", news.newsworthy({"title": "Island Businesses: Please Knock It Off With The Ai-Generated Advertisements", "source": "Nantucket Current",
      "link": "https://nantucketcurrent.com/opinion/island-businesses-please-knock-it-off"}), False)
check("keep news whose slug says opinion", news.newsworthy({"title": "OpenAI ships GPT model update", "source": "The Verge",
      "link": "https://www.theverge.com/news/123/openai-opinion-poll-feature"}), True)
check("keep university research", news.newsworthy({"title": "MIT researchers build an AI that designs new antibiotics",
                                                   "source": "MIT News"}), True)
check("drop Show HN", news.newsworthy({"title": "Show HN: Edi Life OS – self-hosted life dashboard", "source": "x"}), False)
check("drop question essay", news.newsworthy({"title": "Is this the 'mathocalypse'? Why OpenAI's results dump...",
                                              "source": "The Conversation"}), False)
check("no 'according to'", writer.drop_attribution("According to Reuters: China AI labs publish few safety tests."),
      "China AI labs publish few safety tests.")
check("named developer", bool(writer.vague_phrases("Kochi developer Arjun Menon just dropped Laya.")), False)

# repeats
past = ["Lovable's annualized revenue crosses $600M as vibe coding takes off",
        "An OpenAI safety employee has quit and is sounding the alarm"]
check("repeat number words", bool(news.recent_match("Lovable hits $600 million ARR", past)), True)
check("repeat resignation", bool(news.recent_match("I quit OpenAI because its culture is broken", past)), True)
check("not a repeat", bool(news.recent_match("Lovable launches enterprise plan", past)), False)

# weak stories are filtered
check("drop bootcamp", news.newsworthy({"title": "DIET Leh Commences Three-Day Bootcamp on AI", "source": "x"}), False)
check("keep launch", news.newsworthy({"title": "OpenAI launches GPT-6 with persistent memory",
                                      "source": "The Verge"}), True)

# the hook pass replaces only the first line, and only with a sensible length
_ask = writer.ask
d = {"beats": [{"line": "Utah is launching a pilot program to use artificial intelligence for patient exams."},
               {"line": "Doctors will review every result."}], "script": "x"}
writer.ask = lambda *a, **k: '{"line": "An AI just started examining patients in Utah."}'
out = writer.sharpen_hook(d, {"title": "Utah AI exams"})
check("hook replaced", out["beats"][0]["line"], "An AI just started examining patients in Utah.")
check("hook keeps rest", out["beats"][1]["line"], "Doctors will review every result.")
check("script rebuilt", out["script"].split("\n")[0], "An AI just started examining patients in Utah.")
writer.ask = lambda *a, **k: '{"line": "Wow."}'
d2 = {"beats": [{"line": "OpenAI just launched GPT-6."}], "script": "OpenAI just launched GPT-6."}
check("too-short hook ignored", writer.sharpen_hook(d2, {})["beats"][0]["line"], "OpenAI just launched GPT-6.")
writer.ask = lambda *a, **k: ('{"options": ["Here is some news about AI today.", '
                               '"Nvidia sold three billion dollars of chips in one week.", "So, Nvidia had a week."]}')
d3 = {"beats": [{"line": "Nvidia had a big week for chip sales."}], "script": "x"}
check("best-scoring hook picked", writer.sharpen_hook(d3, {})["beats"][0]["line"],
      "Nvidia sold three billion dollars of chips in one week.")
writer.ask = lambda *a, **k: '{"options": ["Here is some news about AI today."]}'
d4 = {"beats": [{"line": "Nvidia sold three billion dollars of chips in one week."}], "script": "x"}
check("weaker hook not used", writer.sharpen_hook(d4, {})["beats"][0]["line"],
      "Nvidia sold three billion dollars of chips in one week.")
writer.ask = _ask

# a story rejected earlier is never picked again: "tried" keeps its order (a set used to drop random titles)
import main  # noqa: E402
_send, _start = main.tg.send, main.start_script
main.tg.send = lambda *a, **k: None
picked = []
main.start_script = lambda s, pick, auto=False: picked.append(pick["title"])
_s = {"tried": [f"Old story {i}" for i in range(59)], "topic": {"title": "Qwen on a PS5"},
      "spare": [{"title": "Qwen on a PS5"}, {"title": "Fresh news"}], "history": [], "posted_log": []}
main.next_story(_s)
check("tried keeps order", _s["tried"][-2:], ["Old story 58", "Qwen on a PS5"])
check("tried keeps 60", len(_s["tried"]), 60)
check("rejected story not re-picked", picked, ["Fresh news"])
# a run that already took long doesn't start another story (the job would be cut off at 30 min and save nothing)
picked.clear()
_rs, main.RUN_START = main.RUN_START, main.RUN_START - main.RUN_BUDGET - 1
_s = {"tried": [], "topic": {"title": "Slow story"}, "stage": "rendering", "spare": [{"title": "Fresh news"}],
      "history": [], "posted_log": []}
main.next_story(_s)
main.RUN_START = _rs
check("long run: no new story", picked, [])
check("long run: reel reset", (_s["stage"], _s["tried"]), ("idle", ["Slow story"]))
main.tg.send, main.start_script = _send, _start

# a reel waiting to retry a failed upload covers its slot, so no second reel is rushed out for it
from datetime import timedelta as _td  # noqa: E402
_now, _ig = main.st.now(), main.IG_READY
main.IG_READY = lambda: False
_slot = [t for t in main.slots_on(_now.date()) if t <= _now]
if _slot:
    _s = {"guarantee_since": (_slot[0] - _td(minutes=1)).isoformat(), "post_log": [],
          "queue": [{"title": "x", "post_at": (_now + _td(minutes=30)).isoformat(), "tries": 1}]}
    check("retrying reel covers its slot", main.behind_today(_s), len(_slot) - 1)
    _s["queue"][0].pop("tries")
    check("later reel doesn't cover a missed slot", main.behind_today(_s), len(_slot))
main.IG_READY = _ig

print("\n".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)

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
writer.requests.post, _cfg.ANTHROPIC_API_KEY = _post, _key
writer.time.sleep = _sleep
writer.BACKUP_LEFT[0] = writer.BACKUP_CALLS[0] = 0
writer.ERRORS.clear()

# vague references must be caught
check("vague developer", bool(writer.vague_phrases("A developer from Kerala just dropped Laya.")), True)
check("vague experts argue", bool(writer.vague_phrases("Experts argue we must secure DNA supply chains.")), True)
check("drop how-to essay", news.newsworthy({"title": "How to Defend Against AI-Designed Viruses",
                                            "source": "War on the Rocks"}), False)
check("drop campus grants", news.newsworthy({"title": "Penn State Announces New Artificial Intelligence Grants "
                                                     "For Faculty", "source": "Onward State"}), False)
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
writer.ask = _ask

print("\n".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)

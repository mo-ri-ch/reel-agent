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
check("full script untouched", main.substance_step({"script": "word " * 80}, {}).get("fact_status"), None)
main.writer.write_script, main.fact_check_step, main.make_specific, main.tg.send = _ws, _fc, _ms, _send

# strict specificity: real names + a number/date
_n, _num = writer.specificity("OpenAI's revenue is twenty billion dollars below target, TechCrunch reported on Tuesday.")
check("specific script", (len(_n) >= 2, _num), (True, True))
_n, _num = writer.specificity("The company shared new results. Experts are curious about what comes next.")
check("general script", (len(_n) >= 2, _num), (False, False))
check("vague new model", bool(writer.vague_phrases("They released a new AI model for coding.")), True)
check("named new model", bool(writer.vague_phrases("They released a new model called Codex Max.")), False)
check("vague tech giants", bool(writer.vague_phrases("Tech giants are racing to build agents.")), True)

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

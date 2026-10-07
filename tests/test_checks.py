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
def _out(*a):
    raise tts.FishOut("HTTP 402")
tts._fish = _out
path, _ = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google", fish_voice="abc")
check("fish out -> google", (path, tts.LAST_ENGINE, tts.FISH_PROBLEM), ("google.wav", "google", "out"))
def _down(*a):
    raise RuntimeError("HTTP 503")
tts._fish = _down
path, _ = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google", fish_voice="abc")
check("fish down -> google", (tts.LAST_ENGINE, tts.FISH_PROBLEM), ("google", "HTTP 503"))
tts._fish = lambda text, out, vid: "fish.mp3"
path, _ = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google", fish_voice="abc")
check("fish used", (path, tts.LAST_ENGINE), ("fish.mp3", "fish"))
tts._fish = lambda text, out, vid: (_ for _ in ()).throw(RuntimeError("503")) if vid == "own" else vid + ".mp3"
path, label = tts.synthesize("OpenAI just launched GPT-6.", "/tmp/x", "male", "google",
                             fish_voice=[("own", "your voice"), ("lib1", "Narrator (Fish Audio)")])
check("fish own down -> library voice", (path, label, tts.LAST_FISH_ID), ("lib1.mp3", "Narrator (Fish Audio)", "lib1"))
tts._fish = _out
path, _ = tts.synthesize("x y z", "/tmp/x", "male", "google", fish_voice=[("own", "a"), ("lib1", "b")])
check("fish credits out -> skip library", tts.LAST_ENGINE, "google")
tts._fish, tts._google, tts.FISH_API_KEY = _f, _g, _key

# vague references must be caught
check("vague developer", bool(writer.vague_phrases("A developer from Kerala just dropped Laya.")), True)
check("vague experts argue", bool(writer.vague_phrases("Experts argue we must secure DNA supply chains.")), True)
check("drop how-to essay", news.newsworthy({"title": "How to Defend Against AI-Designed Viruses",
                                            "source": "War on the Rocks"}), False)
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

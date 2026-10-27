# Gradient Daily reel agent: rules for Claude

An automated Instagram account (**@gradientai.news**, "Gradient Daily · AI News", by Gradient AI Labs) that posts
**6 AI-news reels a day**: 3 for US daytime (00:30, 03:30, 06:30 IST) + 3 for India (11:30, 16:30, 21:30 IST)
(owner, 2026-10-21: night slots reached 2-4x more) on the FREE Gemini quota (owner, 2026-10-10: "stay free"). Watch `state.json` → `gemini_use` / `gemini_errors`. The owner talks to it
through a Telegram bot and reads Claude's messages there.

## Mission & goals (keep every change aimed at these)
- Build @gradientai.news into a trusted, fast-growing AI-news account for a global audience, fully on autopilot
  (the owner does nothing manually).
- Near term: 10 followers by Sun 11 Oct 2026 (from 6 on 7 Oct); then steady growth in views, watch time, shares.
- Quality bar: top-notch, editor-grade reels (studio look), specific and fact-checked, never generic.
- Long-term goals (owner, 2026-10-07: "all of them"): (1) a big audience: reach, shares, followers; (2) a credible
  brand for Gradient AI Labs; (3) leads/customers for the company; (4) income from the page (sponsors). Today the
  order is 1 → 2: grow reach with credible reels; add lead/sponsor features once there's an audience (ask first).

## How it runs
- The repo is **public** (owner, 2026-10-27): as a private repo it used up GitHub's 2,000 free Actions minutes on
  26 Oct and every run was refused ("spending limit"). Public repos have unlimited minutes. So: never commit secrets
  or personal data; they stay in GitHub secrets.
- `.github/workflows/agent.yml` runs every 5 minutes (started by cron-job.org) in **Python 3.11**. `main.py poll` does the
  work; `Make the reel` steps run when a video must be rendered.
- `state.json` is the agent's memory. **The agent commits it every 5 minutes**, so pushes often race: always
  `git pull --rebase origin main` right before `git push`, and retry.
- **NEVER edit `state.json` (or `state.backup.json`) by hand.** On 2026-10-07 a hand edit saved with different
  formatting was merged with the agent's save and broke the JSON: the agent crashed for 2 hours and missed a slot.
  To change the agent's memory, commit a file `control/<name>.json` = `{"set": {key: value}, "unset": [keys]}`; the
  agent applies it on its next run and deletes it. If state.json is ever unreadable, the agent loads
  `state.backup.json` and tells the owner.
- `stats/insights.json`: daily Instagram numbers (followers per day; per reel: views, reach, likes, comments, shares,
  saved, ig_reels_avg_watch_time in ms) and `meta` (per reel link: kind, engine, voice, person, words, slot…).
- `outbox/*.txt`: plain-text messages the agent sends to the owner's Telegram on its next run, then deletes.
- GitHub Actions logs can't be downloaded through the proxy; use `gh run list` / `gh run view <id> --json jobs`
  (step conclusions) and `state.json` → `last_render_error` for errors.

## Hard rules
1. **Test before every push**: `python3.11 -m py_compile *.py`, `python3.11 tests/test_checks.py` and
   `python3.11 tests/simulate_day.py` (needs a 3.11 venv with requests feedparser Pillow numpy). All must pass.
   Earlier outages came from untested changes (a 3.12-only f-string; an over-strict voice check).
2. Small, reversible changes. One idea per commit, with a clear message and the attribution lines.
3. **Ask the owner first** (via outbox, then wait for the next review) before: changing posting times or count,
   turning autopilot off, changing secrets/tokens/accounts, the workflow triggers, deleting posts, or anything costly.
4. Never weaken the quality gates: evidence-based fact check, voice-matches-script check, visual check, no vague
   references ("a developer" → real names), no repeats, no press releases/local events.
5. Never put secrets in code, commits, outbox messages or chat.

## Owner's preferences (learned)
- Messages: **brief**, plain language, no jargon. Lead with what happened and what (if anything) they must do.
- Be specific: real names, roles, numbers, sources. Show real photos of named people, real product images.
- Every reel is scored by the editor-in-chief (writer.editor_review) before posting: pass 8/10 overall; accuracy
  and specific at least 7; of hook, substance, visuals, flow ONE may be 6, none lower (owner, 2026-10-15: "free,
  slightly softer", after only 5 reels passed in 3 days); no exceptions after fixes; no posting if the editor
  can't run. Captions are guaranteed by code (video.sync_problem / even_words), not the
  free vision model, which misread correct captions on 12 Oct (owner, 2026-10-12: "BE very strict with the quality check"). Never lower the bar.
- Models: **free Gemini only** (owner, 2026-10-10 13:14: "Sonnet is costly. Stay free"). Claude Sonnet 5.5 code stays
  but is off (config USE_CLAUDE; the trial ran out of credit on 10 Oct). Don't turn it on without asking.
- No "Top AI headlines" backup reels (owner, 2026-10-09: made no sense). A late, fully checked reel beats an on-time bad one.
- Scripts: 30-40 s, 75-105 words, every sentence a concrete fact. Owner rejected short 45-65 word scripts
  (2026-10-09: "getting so bad"). Don't shorten scripts again without asking.
- Voice: Fish Audio library voices, mostly Ethan with Paula every 4th reel (owner, 2026-10-21: Ethan 4.5 s watch / 106 reach vs Paula 3.3 s / 42). The owner's own clone was removed on 2026-10-07 at their request — don't bring it back unless asked. Fallback US English voices only (Google + Microsoft alternating). Captions must never cover logos/faces/numbers.
- Music: Instagram's own trending music via the Audio API (owner, 2026-10-21), at volume IG_MUSIC_VOLUME (35: owner couldn't hear it at 15 and chose "clearly audible" on 2026-10-24) under
  the voice; our own background music only when Instagram's isn't available (state ig_music_off / ig_music_error).
- Brand blue (#7B9AF8), "Source · date" label, @gradientai.news handle. Look: studio style (studio.py) — clean dark/light scenes, floating picture cards, top captions with key-word highlight box (owner approved 2026-10-07).

## Daily health check (every day)
1. `gh run list -R mo-ri-ch/reel-agent -L 100`: any failures in the last 24 h? Which step (`gh run view --json jobs`)?
2. `state.json`: is the agent stuck (same stage/topic for hours), `last_render_error`, `render_fails`, `held`,
   `behind_since`; `post_log` vs `POST_TIMES` for yesterday and today.
3. `stats/insights.json` → `notes` (last_collect recent? insights_permission true?).
4. If something is broken and the fix is clear and safe: fix it, run the tests, push. Otherwise explain the problem.
5. Message the owner (one `outbox/` file) **only if** something was wrong or changed: what happened, what you did,
   anything they must do. If all is well on a weekday, send nothing.

## Weekly review (Sundays)
1. Analyse the last 7 days in `stats/insights.json` against the week before: views/reel, median, watch time,
   shares, saves, followers; by slot, kind, engine/voice, person shown, script length, source/topic, hook_score.
   Rank reels by **outlier multiple** (views ÷ the account's median views) and **shares per reach** (the strongest
   signal), not raw views. Check whether hook_score tracks watch time; if it doesn't, don't trust it.
2. Read `stats/changes.md`: for each change made ≥ 7 days ago, did its target metric improve? Revert what got worse.
3. Pick **at most 2** improvements backed by the data (e.g. hook style, script length, story selection hints,
   visuals), implement, test, push, and log them in `stats/changes.md` (date, change, why, metric + baseline).
   Until 2026-10-21 there is too little data: only make changes with a clear, large signal; otherwise just report.
4. Send one short outbox summary: the week's numbers, what you changed and why, what you'll watch next week.

## Commit attribution
End commit messages with:
```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

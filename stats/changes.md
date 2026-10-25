# Change log (for the weekly review)

Each entry: date · change · why · target metric and baseline. Review after 7+ days; revert if worse.

- 2026-10-07 · Baseline before automated reviews · 42 reels (Sep 30–Oct 7): 47 views/reel avg, median 32,
  avg watch 3.5 s, 1 share, 6 saves, 6 followers · Schedule moved from 6 to 12 reels/day (global audience) today.
- 2026-10-07 · Owner goal: 10 followers by Sun 11 Oct, no manual promotion · three changes:
  1. Hook pass: first spoken line rewritten to ≤9-word curiosity hook (facts unchanged, still fact-checked).
     Why: avg watch time 3.5 s on every reel type → viewers leave in the first seconds. Target: avg watch time (base 3.5 s).
  2. Story picks favour well-known companies/products. Why: big-name titles 58 vs 38 views/reel (20 vs 22 reels).
     Target: views/reel (base 47, median 32).
  3. Caption ends with "Follow @gradientai.news for daily AI news ⚡" (text only). Target: followers (base 6).
- 2026-10-07 · Editor pass: (a) every rendered reel saves a review pack (review/*.jpg contact sheet + *.json with
  cuts, shot lengths, sound start, loudness, words/min) so Claude can audit real output; (b) when a beat reuses
  the same photo, the repeat is a punch-in crop (new framing) instead of the same frame. Why: audit of a real reel
  found a 7.8 s static shot. Target: avg watch time (base 3.5 s), longest shot ≤ 3 s in review packs.
- 2026-10-07 · Virality research (Mosseri: watch time, sends, likes are the top signals; completion drives reach;
  under ~30 s best for non-followers) · (a) scripts 45-65 words (~20 s, was 70-100 / 25-40 s), surprise kept for
  the end, closing question must be specific; (b) story picks favour "would you send this to a friend?" stories.
  Why: avg watch 3.5 s of ~30 s, 1 share in 42 reels. Targets: avg watch time and watch % (base 3.5 s), shares
  per reel (base 0.02), views/reel (base 47).
- 2026-10-07 · Owner: AI-generated pictures don't suit news · beats that would get an AI picture (or a stock clip
  that doesn't fit) now use a real photo from the news article / official pages first; AI only as a last resort.
  Writer told to avoid "image". Target: avg watch time (base 3.5 s); visual_summary should show few "AI images".
- 2026-10-07 · Owner: voices don't sound like they understand the story · the writer adds a one-line "delivery"
  note per story; Google voices get it in Google's documented director format (profile, scene, notes, then
  #### TRANSCRIPT) so emphasis and tone follow the story. Voice check still listens to every take; a remake uses
  the bare script. Target: avg watch time (base 3.5 s); compare Google vs Microsoft reels' watch time.
- 2026-10-07 · Owner's own voice via Fish Audio (~$2-3/month, owner approved) · set up with /myvoice in Telegram;
  used for every reel; credits out / errors → regular Google/Microsoft voices automatically. Target: avg watch
  time and followers vs AI-voice reels (compare by meta.engine = "fish").
- 2026-10-07 · Fish library voices as backup (/fishvoice <link>, owner-picked): used when the owner's voice is off
  or a take fails the voice check; credits out → regular voices. Compare by meta.voice.
- 2026-10-07 · Studio style on by default (owner approved the sample): clean dark/light studio scenes, pictures as
  floating cards, captions at the top with key-word highlight, motion on every shot, article-style source card.
  Falls back to the classic style automatically if a studio render fails. Inspired by a hand-animated explainer
  reel the owner shared. Target: avg watch time (base 3.5 s), shares, followers.
- 2026-10-07 · Editor audit of the AI-viruses reel: (a) opinion essays / how-to guides dropped as stories; (b) vague
  "experts argue…" caught by the specificity check; (c) studio: scenes that would show AI pictures reuse the
  story's real photos with new crops; (d) final mix normalised to -14 LUFS (was -15.8). Target: watch time.
- 2026-10-07 · Audit of the first studio reel (Penn State faculty grants): studio worked, 0 AI pictures on screen,
  -14.6 LUFS. Fixed: (a) campus-admin stories (university grants/courses/centres) dropped; (b) every beat gets a
  2-4 word "tag"; when no real picture fits a line, the studio shows the tag in big kinetic type (like the
  reference reel) instead of looping the same photo. Target: watch time, visual variety (no picture > 2 uses).
- 2026-10-07 · Owner: smaller captions, whole sentence on screen · studio captions now show the full sentence (up to
  3 lines, 56px) with words lighting up as spoken; numbers get the highlight first. Target: watch time / completion.
- 2026-10-07 · Owner: use my voice, made energetic · own Fish clone back on with the [excited] tag, +6% pace,
  presence EQ and light compression; Paula/Ethan as backups. Compare watch time vs Paula/Ethan reels.
- 2026-10-07 · Owner: crisp, clear studio sound · every voice gets a vocal chain (high-pass, de-box EQ, presence +
  air, de-esser, gentle compression) before mixing; owner's voice adds only pace + a little bite on top.
- 2026-10-09 · REVERTED the 45-65 word limit (owner: "scripts are getting so bad, don't make it very short"). Scripts
  were thin/empty (one was 23 words: "The Conversation reported on… The publication discussed…"). Now: 30-40 s,
  75-105 words, every sentence must add a concrete fact; scripts under 65 words get one expansion with verified
  detail, else the story is skipped. Also drop Show HN posts and question/opinion headlines. Target: watch time,
  completion, follows.
- 2026-10-09 · Owner: "always strictly mention the company, name, facts" · hard gate: every script must contain ≥2
  real names (company/product/person/place) and a number or date, with no vague phrases ("a new AI model", "tech
  giants", "the company…"); one rewrite, else the story is skipped. New simulation scenario (half the scripts
  generic) still posts 12/12 on time.
- 2026-10-09 · Owner: "visuals and talks are not matching" (Anthropic gene-editing reel: 6 of 7 beats were stock
  "clip", none fitted → one DNA photo repeated 6x + abstract tags "Expert Debate"). Fixes: writer uses "clip" for at
  most 2 beats and "official"/"person"/"photo"/"stat"/"source" for named things; when nothing real fits, the studio
  shows the named company's logo card, then the line's fact in big type; a real photo is shown at most twice; tags
  must contain a name or number. Also caught vague "experts are debating…" / "raises … questions" filler.
- 2026-10-09 evening · Gates were too strict/fragile: the writer's own "thin" flag skipped good 80-word scripts; a
  required number skipped true stories with none; a Gemini error in a rewrite crashed 3 runs → the 9 PM slot got the
  backup headlines reel. Now: word count decides "thin"; names are a must, a number is asked for but optional after
  the rewrite; rewrite errors never crash (story skipped). Owner: never say "according to <source>" → removed from
  scripts and the headlines reel.
- 2026-10-09 · Editor-in-chief (owner approved): after rendering, Gemini watches ~14 frames + script + source and
  scores hook, specific, substance, accuracy, visuals, flow (1-10). Pass = 8/10 (accuracy or specific < 7 caps at
  6.5). Below: weak shots replaced and re-scored, or the script rewritten with its notes and re-made; still < 7 →
  switch story. Score shown in the Telegram preview and saved in review packs + stats meta ("editor"). Backup
  headlines reel bypasses it. Simulation: editor rejecting everything still posts 12/12 on time.
- 2026-10-09 · Owner asked about repeats. Audit found 4 repeated events in 4 days (OpenAI math results ×3, ChatGPT EU
  watermark ×2, Mistral 1T/"Le Chonk" ×2, ChatGPT Intelligent UI ×2): backup stories skipped the AI same-event check,
  and it needed 2 shared title words. Now every story passes a final same-event gate right before its script is
  written (main model; compares against titles + what each posted reel actually said, 14 days; 1 shared name is
  enough). Posted reels now store "event" (first lines of the script). Simulation with 50% repeats: 12/12 on time.
- 2026-10-09 21:20 · OUTAGE 20:50–21:25: when a story failed and the agent switched stories, a Gemini error while
  writing the new script was uncaught → every run crashed, the 9 PM reel didn't post. Fixed (switch failures are
  caught, schedule keeper fills); new simulation "gemini_flaky" covers it. Likely trigger: more Gemini calls per reel
  (editor, same-event gate, rewrites) → watch Gemini quota.
- 2026-10-09 23:55 · Owner: the "Top AI headlines" backup reel made no sense ("Very bad execution"). It read raw
  headlines (a podcast, an opinion question), bypassed every quality check incl. the editor. REMOVED as a backup:
  late-and-good beats on-time-and-bad; the owner is told when a slot is late. Also found the editor-in-chief had
  NEVER run (NameError: video not imported in editor_step → silently skipped) — fixed; simulation now proves the
  editor gates (rejecting everything → nothing posted).
- 2026-10-10 05:20 · OUTAGE 01:00–05:00 (3 slots missed, no crash): every story was rejected before rendering by
  over-strict gates I added: "Researchers at Stanford found…" counted as vague; fact-check fixes deleted lines and the
  script fell under the length floor. Fixed: researchers/experts are vague only when no name follows; fact fixes must
  replace removed lines with other sourced facts; floor 50 words.
- 2026-10-10 05:30 · Root cause of the 01:00–05:00 gap: when writing the auto-picked story's script failed (Gemini
  error), the code cleared choose_deadline and waited for the owner's reply → stuck from 02:10. Now autopilot rotates
  to the next story in 10 min, and a story list on autopilot always has a deadline. Saves last_script_error.
- 2026-10-10 05:50 · Gemini FREE quota exhausted ("free quota used up" on both models; 57 calls by 06:00) → no reel
  could be fact-checked since 23:00. Owner chose "stay free, post fewer": 6 reels/day at 01, 05, 09, 13, 17, 21 IST
  (keeps 13 & 17, our best slots). All quality checks kept. Missed morning slots aren't chased (guarantee reset).
  gemini_use/gemini_errors now saved in state. Baseline for the new schedule: views/reel and follows per day.
- 2026-10-10 08:00 · Owner: back to the earlier Indian-time slots for 6/day: 09:00, 11:30, 14:00, 16:30, 19:00, 21:30 IST (24-hour spread returns with 12/day).
- 2026-10-10 08:10 · Owner: try Claude Sonnet 5.5. Built (inactive until the ANTHROPIC_API_KEY secret exists):
  Claude writes scripts from the source article text and runs the editor-in-chief review; Gemini (free) keeps
  fact-checking with Google Search and remains the fallback (no key / no credit / errors). Est. $0.05-0.08/reel
  (Sonnet 5.5: $2 in / $10 out per MTok). meta.writer and editor.reviewer record which model did it — compare
  editor scores and views Claude vs Gemini on Sunday.
- 2026-10-10 08:20 · Owner: back to 12 reels/day (odd hours IST). Claude Sonnet 5.5 key added, so writing + editor no longer use Gemini quota; Gemini still fact-checks. Missed morning slots not chased (guarantee reset).

## 2026-10-10: Claude covers Gemini quota outages
- Change: when Gemini's free quota is used up, Claude Sonnet does that job (story picking, fact check, etc.), capped at 150 jobs/day. The fact check stays strict: Claude may only use the fetched source pages, and our code still confirms every quote is really on the page.
- Why: the quota ran out at 02:50 IST and no reels posted from 01:00 to 09:00 IST (5 slots missed).
- Metric: slots posted per day (baseline 10 Oct: 0 of the first 5); gemini_use.claude_backup (cost).

## 2026-10-10: ideas from github.com/Jakeschincariol/instagram-agent-skill (MIT)
- Hooks: 3 options on proven formulas, hookscore.py keeps the best (only if better than the original). Metric: avg watch time, 3-second hold; meta.hook_score.
- Hype/AI-sounding phrases flagged and rewritten once (checked original kept if the rewrite fails); em dashes → commas. Metric: editor "flow" score.
- Captions: max 5 hashtags (Instagram's limit), key fact in the first 125 characters. Metric: reach from search/explore, shares.
- Weekly review ranks by outlier multiple and shares per reach.
- Not taken: auto word-swapping (changes meaning in news), DM/comment bots, profile rewrite (ask owner first).

## 2026-10-10 13:14: back to free Gemini only
- Owner: "Sonnet is costly. Stay free". Claude switched off (USE_CLAUDE flag). Metric: slots posted/day on the free quota.

## 2026-10-10 13:19: 6 reels/day (owner chose, free quota)
- 09:00, 11:30, 14:00, 16:30, 19:00, 21:30 IST. Metric: slots filled on time (12/day missed 1-9 AM on 10 Oct).

## 2026-10-11: Sunday review (no code changes)
- Finding: the free Gemini quota resets at 12:30 IST (midnight US Pacific) and ran out at ~22:30 IST on 10 Oct after 5 reels.
  With Claude off, the 09:00 and 11:30 slots can't be made (both missed today). Asked the owner: 5/day after 12:30, keep 6 and
  accept late morning reels, or paid Claude for the mornings only.
- Week 4-10 Oct: 57 reels, median 83 views (prior 32), avg watch ~3 s, 4 shares, followers 6 → 7. Too little data for changes.

## 2026-10-12: more free Gemini models
- Free quota is per model (Flash ~20/day, Flash-Lite ~500/day). It covered only ~4 reels/day (12:30-17:00 IST), nothing posted 17:00 Oct 11 - 11:00 Oct 12. Added 3.7/3.5/3-preview Flash and 3.5/3.1 Flash-Lite as fallbacks; used-up models skipped until the reset; per-model use in gemini_use.models. Metric: slots filled/day (baseline: 4 on Oct 11).

## 2026-10-12: very strict quality (owner)
- No reel below 8/10 (the 7.0 floor after fixes is gone); any criterion under 7 fails; editor told to score like a top news channel and penalise vague commentary lines; visual check flags near-empty cards. Also captions criterion + caption timing guard + no posting without the editor. Metric: editor scores, watch time, shares; slots missed (expect more late/missed slots).

## 2026-10-12 evening: from rejected reels
- Photo reuse max 2 per reel by content (hook counts). Captions judged by code, not the Lite vision model (it scored correct captions 3/10). Personal essays filtered. Metric: editor visuals score (baseline 3-7 today), reels passing 8/10.

## 2026-10-13: daily check
- 12 Oct: 1 of 6 posted (strict editor rejected 10 reels, which used up the free quota by 17:40 IST); 13 Oct 09:00/11:30 missed
  while waiting for the 12:30 IST reset (expected; owner told). No failed runs. Evening fixes of 12 Oct not yet exercised.
- Change: market-research firms' sales blogs (Kings Research, Grand View, MarketsandMarkets…) filtered as press releases;
  one was in today's candidate list. Metric: share of picked stories from real newsrooms.

## 2026-10-13: visual variety
- Photo once per reel (hook counts); lines > 4 s split into card + label. Why: 5/6 reels rejected for repetition (editor visuals 3-7). Metric: editor visuals score, pass rate (baseline 13 Oct: 1 of 6 passed).

## 2026-10-13 evening: max shot 3.2 s
- Lines cut into <=3.2 s shots (card, label, real logo); letter-block logos dropped. Baseline 13 Oct: 2 of ~20 passed, visuals median 5. Metric: editor visuals, pass rate.

## 2026-10-14: daily check
- No failed runs in 24 h (17 cancelled = overlapping 5-min runs). 13 Oct: 2 of 6 posted (Intel D270, Janas, both 8.7). 14 Oct 09:00/11:30
  missed waiting for the 12:30 IST reset (expected). The 3.2 s max-shot change landed after the quota ran out, so today is its first test.
- Change: articles in a site's opinion/editorial/letters/column section (by URL) are skipped; a Nantucket Current opinion column was a
  candidate today. Metric: editor scores of picked stories, fewer quota-wasting rewrites.

## 2026-10-15: daily check
- 14 Oct: 2 of 6 posted (Saudi/OpenAI arrest 8.7, DeepMind-Singapore scams 8.5); the editor passed 2 of 20 reels (18 capped at
  6.5 for a criterion under 7, mostly visuals/hook/specific), and the free quota ran out at 17:15 IST. 15 Oct 09:00/11:30 missed
  waiting for the 12:30 IST reset (expected). Followers 8. One failed run (14 Oct 15:55 IST): Telegram unreachable from the runner.
- Fix: the rejected-stories list ("tried") lost random titles (set → list[-30:]), so the Qwen-on-PS5 story was made and rejected
  twice (~4 reels of quota). Now kept in order, 60 max. Metric: distinct stories tried/day, reels passed/day (baseline 2).
- Fix: a Telegram network error no longer crashes the run (retry once, then carry on).

## 2026-10-15: slightly softer (owner choice)
- Still 8/10 overall; accuracy and specific >= 7; one of hook/substance/visuals/flow may be 6. Why: only 5 reels passed in 3 days, many rejections from the weak free reviewer. Metric: reels/day (baseline ~1.7), views and watch time per reel (watch for a drop).

## 2026-10-18: Sunday review (no code changes)
- No failed runs in 24 h (11 cancelled = overlapping 5-min runs). 16 and 17 Oct: 6 of 6 posted (after the 15 Oct softer editor);
  18 Oct 09:00 posted at 09:13. Free Flash quota used up by ~16:00 IST; Flash-Lite 429s from ~04:00 IST, so 11:30 may wait for the 12:30 reset.
- Week 11-17 Oct: 27 reels (57 prior at 12/day), median 66 views (prior 96), mean watch 4.5 s (prior 5.7), 2 shares, 8 saves;
  followers 7 -> 9. Outliers: Intel D270 (6.6x), Liquid AI LFM2.5 (6.6x): product launches with specs, no person shown.
- Signal: Ethan beats Paula both weeks (median views 113 vs 36 this week, 132 vs 99 before; watch 5.1 s vs 3.0 s). Confound:
  alternation puts Paula on 21:30 often. Asked the owner (Ethan only vs keep both). hook_score has only 5 data points; not trusted yet.

## 2026-10-21: first data-backed changes (owner OK)
- Opening shows headline + picture from frame 0 (no blank start), slow push-in. Metric: avg watch time (baseline 14-20 Oct: 4.4 s; 7-13 Oct: 6.7 s).
- Picker ranks launches with numbers and named-person news first. Metric: median reach (baseline 14-20 Oct: 42; number-titles 99 vs 50).
- Open questions for the owner: move some slots to US hours (night slots reached 80-160 vs 10-45); Ethan vs Paula (4.5 s/106 vs 3.3 s/42).
- 21 Oct (owner OK): slots 00:30/03:30/06:30/11:30/16:30/21:30 IST (metric: median reach, baseline 42); voice mostly Ethan (metric: watch time).
- 21 Oct: real article screenshots (scrolling) for source lines. Metric: editor visuals score (baseline median 6), avg watch time.
- 21 Oct: Instagram trending music via the Audio API (replaces our own track; falls back to it). Metric: reach, avg watch time.
- 21 Oct night: product-page screenshots for official lines; company logo instead of initials; strict stock-clip picking. Metric: editor visuals (median 6).

## 2026-10-23: daily check
- No failed runs in 24 h (43 cancelled = overlapping 5-min runs). Last post 22 Oct 16:31; 21:30, 00:30, 03:30, 06:30 missed and
  11:30 will be too (free Gemini used up until the 12:30 IST reset).
- Cause: the editor passed 0 of 23 reels since 22 Oct 11:00 IST (19 Oct - 22 Oct 10:00: about 2 in 5). It began right after the
  22 Oct rubric line "unrelated picture -> visuals 5 or less" (607a946): visuals now mostly 4. Asked the owner whether to undo that
  line (the opening-photo check stays; pass mark unchanged). Not changed without his OK (hard rule 4).
- Fix: terms/privacy/consent pages are never used as product-page or article screenshots. Metric: editor visuals (median 4 since 22 Oct 11:00).

## 2026-10-25: Sunday review
- No failed runs in 24 h. 24 Oct: 5 of 6 posted (21:30 missed); 25 Oct 00:30/03:30/06:30 missed and 11:30 will be too: the free
  Gemini quota ran out at 19:33 IST on 24 Oct (resets 12:30 IST). The editor reviewed 20 reels on 24 Oct and passed ~4; visuals
  was the lowest score in 15 of 20 (11 scored 4). Owner's answer on the 22 Oct "unrelated picture" rubric line still pending.
- Week 18-24 Oct vs 11-17: 38 reels (27), median views 113.5 (71), median reach 106 (68), mean watch 4.6 s (4.5), shares 1 (2),
  saves 7 (9); followers 9 -> 11. Since the 21 Oct changes (opening from frame 0, picker ranking, US slots, Ethan, real pages):
  median reach 109 vs 42 for 14-20 Oct; median watch 4.8 s vs 4.2 s. Keep all (only 4 days old; re-check next Sunday).
- Ethan vs Paula again: 24 reels median 121 views / 5.0 s vs 14 reels 42 / 4.0 s (third week in a row). Asked the owner about Ethan only.
- Outliers: Amazon TorchNeuron (5.6x), Anthropic Claude attack-surface research (3.4x), Uber ChatGPT Work (3.2x): big-company
  launches/numbers again. hook_score: 9 data points, weak link to watch time; still not trusted.
- Change: labelled opinion pieces ("Guest commentary:", "Editorial", "Viewpoint", "Perspective:", "Column:", letters to the
  editor) are skipped by title; a Guest commentary was made and rejected (5.3) on 24 Oct, wasting quota. Metric: reels passed per day.
- 25 Oct: photo reuse back to 2 (1 made reels text-only, visuals 4); news-site domains stripped from product logos. Baseline 24 Oct: 2 of 17 passed, quota ran out 19:33, 5 slots missed.

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

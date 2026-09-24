# 🎬 Gradient AI Labs · Reel Agent

A free agent that makes **2 faceless AI-news Instagram Reels a day**.
You steer it from Telegram with a few taps; it writes the script, voices it, edits the video
and posts it to **@gradientailabs**. If you're busy, autopilot finishes the job on its own.

**Cost: ₹0 / month.**

---

## How a day looks

| Time | What happens |
|---|---|
| **8:00 AM & 4:00 PM** | The bot sends the top 3 AI stories as buttons |
| You tap a story | Gemini writes a script (≈1 min) |
| You tap a voice | The reel is made (≈5–10 min) and a preview arrives |
| You tap **✅ Schedule** | It's queued for the next posting time |
| **1:00 PM & 7:30 PM** | Scheduled reels go live on Instagram, and the bot sends you the link |

Replies usually arrive within **about a minute** (see *Doorbell* below).

### Buttons

- **Stories:** `1 📰` `2 📰` `3 📰` · `🔄 New stories` · `⏭ Skip`. You can also type any topic.
- **Script:** `🤖 AI voice` (alternates male/female) · `👨 Male` · `👩 Female` · `↩️ Undo` · `⏭ Skip`.
  You can type changes ("shorter", "stronger hook") or send a voice note to use your own voice.
- **Preview:** `✅ Schedule` · `🚀 Post now` (asks to confirm) · `🔁 New voice` · `↩️ Undo` · `⏭ Skip`.
  Send a picture to put it on the opening screen.

Tapped buttons change to **✅ You chose: …**, so you can see your choice. Buttons on old
messages are ignored safely. **↩️ Undo** goes back up to 5 steps; the only thing it can't undo
is a reel that's already live on Instagram.

### Autopilot (on by default)

If you don't reply within **2 hours**, the agent picks story #1, uses the AI voice and schedules
the reel itself. Your reply or tap at any point takes over. Toggle it with `/autopilot`.

### Commands

| Command | What it does |
|---|---|
| `/news` | Fresh stories now |
| `/topic <anything>` | A reel on your own topic |
| `/myscript <text>` | Use a script you wrote (skips Gemini) |
| `/script` · `/status` · `/queue` | Show the script, the current step, or scheduled reels |
| `/undo` · `/skip` | Go back one step or cancel the current reel |
| `/clearqueue` | Cancel all scheduled reels (asks first) |
| `/autopilot` | Turn autopilot on or off |
| `/help` | Show the full guide |

---

## How a reel is made

1. **News:** RSS feeds (TechCrunch, The Verge, Google News and more) → Gemini picks the 3 best stories.
2. **Script:** Gemini writes a 25–40 s script with a scroll-stopping hook, split into 5–8 **beats**.
   Each beat has its own visual: a stock clip, an AI image, or a big-number card.
3. **Voice:** a free Microsoft voice (Andrew, Brian, Ava, Emma, or Indian English Prabhat / Neerja), with
   Kokoro as the automatic backup. You can also send your own voice note.
4. **Visuals:** Pexels clips for each beat. **Gemini looks at the thumbnails** and picks the ones that
   match the sentence; if none fit, an AI image (Cloudflare Workers AI) is used instead.
5. **Editing (FFmpeg):** a hook screen with big text, a new shot every ~2.6 s with zooms and pans,
   Whisper-timed word-by-word captions (Poppins ExtraBold, active word in yellow), background music that
   ducks under the voice, and a progress bar.
6. **Posting:** the Instagram Graph API uploads the reel with caption and hashtags.

---

## How it runs (all free)

| Part | Job |
|---|---|
| **GitHub Actions** | Runs the agent (`.github/workflows/agent.yml`) |
| **Doorbell** (Cloudflare Worker + D1) | Telegram sends every message here instantly; it shows "⏳ Got it!", marks your tap, saves the message and starts GitHub right away |
| **cron-job.org** | Wakes the agent every 5 min (backup check + scheduled posts) and at 8 AM / 4 PM (stories) |
| **state.json** | The agent's memory between runs (current step, queue, undo history) |

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Conversation, buttons, undo, autopilot, scheduling |
| `writer.py` | Gemini: picks stories, writes scripts, chooses clips |
| `video.py` | Builds the reel (visuals, captions, music, progress bar) |
| `tts.py` | AI voices |
| `images.py` | AI images (Cloudflare, with Pollinations as backup) |
| `news.py` | RSS news feeds |
| `instagram.py` | Posting to Instagram |
| `telegram_api.py` | Telegram messages and buttons (via the doorbell) |
| `whatsapp.py` | Optional WhatsApp alerts (CallMeBot) |
| `config.py` · `state.py` | Settings and memory |
| `doorbell/` | Cloudflare Worker code and its setup guide |
| `fonts/` | Poppins font for captions and cards (OFL licence) |
| `music/` | Royalty-free background tracks, picked at random |

---

## Settings

**Secrets** (Settings → Secrets and variables → Actions → Secrets)

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, `PEXELS_API_KEY`, `CF_ACCOUNT_ID`, `CF_API_TOKEN`,
`IG_USER_ID`, `IG_ACCESS_TOKEN`, `DOORBELL_URL`, `DOORBELL_KEY`, and optionally `WHATSAPP_PHONE`, `CALLMEBOT_API_KEY`.

**Variables** (optional; defaults are shown)

| Variable | Default | What it changes |
|---|---|---|
| `INSTAGRAM_HANDLE` | — | Handle shown on reels |
| `POST_TIMES` | `13:00,19:30` | Posting times (India time) |
| `AUTO_PICK_HOURS` / `AUTO_APPROVE_HOURS` | `2` | How long autopilot waits |
| `VOICES_MALE` / `VOICES_FEMALE` | natural US voices + Indian English | Voice lists (comma-separated) |
| `TTS_RATE` | `+6%` | Speaking speed |
| `MUSIC_VOLUME` | `0.15` | Background music level |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Main model (backup: `gemini-flash-lite-latest`) |
| `WHISPER_MODEL` | `base.en` | Caption timing accuracy (`small.en` is slower but more accurate) |
| `AI_VOICE_NOTE` | off | Optional caption line for AI-voiced reels |

Story times (8 AM / 4 PM) are set in cron-job.org.

---

## Troubleshooting

- **No reply:** open **Actions** and look for a red ❌; the error is at the bottom of the failed step.
- **Gemini "quota" or "overloaded":** wait and retry; the backup model kicks in automatically when the main one is busy.
- **Instagram "session expired":** the access token ran out; create a new one and update `IG_ACCESS_TOKEN`.
- **Turn the doorbell off:** open `https://api.telegram.org/bot<TOKEN>/deleteWebhook` and delete the
  `DOORBELL_URL` secret. The agent goes back to checking every 5 minutes.
- **Always check facts in the script before approving.** AI can get news details wrong.

# 🎬 Gradient Daily · Reel Agent

A free agent that makes **6 faceless AI-news Instagram Reels a day**.
You steer it from Telegram with a few taps; it writes the script, voices it, edits the video
and posts it to **@gradient.daily** (by Gradient AI Labs). If you're busy, autopilot finishes the job on its own.

**Cost: ₹0 / month.** New here? See [Setup from scratch](#setup-from-scratch-about-2-hours-one-time).

---

## How a day looks

| Time | What happens |
|---|---|
| **7:00, 9:30, 12:00, 14:30, 17:00, 19:30** | The bot sends the top 3 AI stories as buttons (one reel per time) |
| You tap a story | Gemini writes a script (≈1 min) |
| You tap a voice | The reel is made (≈5–10 min) and a preview arrives |
| You tap **✅ Schedule** | It's queued for the next posting time |
| **9:00, 11:30, 14:00, 16:30, 19:00, 21:30** | Scheduled reels go live on Instagram, and the bot sends you the link |

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

If you don't reply within **45 minutes** at each step, the agent picks story #1, uses the AI voice and schedules
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
3. **Voice:** a free Microsoft voice (Andrew, Brian, Ava or Emma), with
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
| **cron-job.org** | Wakes the agent every 5 min: checks messages, sends stories at story times, posts scheduled reels |
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
| `POST_TIMES` | `09:00,11:30,14:00,16:30,19:00,21:30` | Posting times (India time) |
| `OFFER_TIMES` | `07:00,09:30,12:00,14:30,17:00,19:30` | When fresh stories are sent (one reel each) |
| `AUTO_PICK_HOURS` / `AUTO_APPROVE_HOURS` | `0.75` | How long autopilot waits at each step |
| `VOICES_MALE` / `VOICES_FEMALE` | natural US voices (Andrew, Brian / Ava, Emma) | Voice lists (comma-separated) |
| `TTS_RATE` | `+6%` | Speaking speed |
| `MUSIC_VOLUME` | `0.15` | Background music level |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Main model (backup: `gemini-flash-lite-latest`) |
| `WHISPER_MODEL` | `base.en` | Caption timing accuracy (`small.en` is slower but more accurate) |
| `AI_VOICE_NOTE` | off | Optional caption line for AI-voiced reels |

Story times come from `OFFER_TIMES`; the agent sends them itself during its 5-minute checks.

---

## Setup from scratch (about 2 hours, one time)

Keep a private notepad file for the keys you collect. Never share them in screenshots or chats.

### 1. Telegram bot (5 min)
1. In Telegram, open **@BotFather**, send `/newbot`, and choose a name and username. The token it gives you is `TELEGRAM_BOT_TOKEN`.
2. Send "hi" to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser.
   The number after `"chat":{"id":` is `TELEGRAM_CHAT_ID`. If the page shows `"result":[]`, send another message and refresh.

### 2. Free API keys (10 min)
- **Gemini:** aistudio.google.com → *Get API key* → *Create API key* → `GEMINI_API_KEY`.
  Check which Flash model is currently offered, and set it as the `GEMINI_MODEL` variable if it differs from the default.
- **Pexels:** pexels.com/api → sign up ("I want to download") → fill in the short form → `PEXELS_API_KEY`.
- **Cloudflare (AI images):** dash.cloudflare.com → *AI → Workers AI → Use REST API*.
  Copy the **Account ID** → `CF_ACCOUNT_ID`, then *Create a Workers AI API Token* → `CF_API_TOKEN`.
- **WhatsApp alerts (optional):** callmebot.com → *Free WhatsApp API → Send Messages*, and follow the activation steps.
  This gives you `CALLMEBOT_API_KEY`, and your number with country code is `WHATSAPP_PHONE`.

### 3. Instagram API (30–40 min)
1. Instagram app → Settings → *Account type and tools* → switch to a **Professional** (Creator or Business) account.
2. Instagram → *Edit profile → Page* → create or connect a **Facebook Page**.
3. developers.facebook.com → *My Apps → Create App* → use case **"Manage messaging & content on Instagram"**
   → connect your business portfolio → *Create app*.
4. In the app: *Customize the use case → API setup with Facebook login → Add required content permissions*.
5. *Tools → Graph API Explorer*: select the app → *Get User Access Token* → add `instagram_basic`,
   `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`
   → *Generate Access Token* → allow only your Page, Instagram account and business.
6. In the Explorer, run `me/accounts?fields=name,instagram_business_account`. The `id` inside `instagram_business_account` is `IG_USER_ID`.
7. *Tools → Access Token Debugger* → paste the token → *Debug* → **Extend Access Token** → `IG_ACCESS_TOKEN` (lasts ~60 days).

App Review isn't needed; the app works for your own account in development mode.

### 4. GitHub (15 min)
1. Create a **public** repository (Actions minutes are unlimited for public repos, and secrets stay hidden) and upload all files.
   The browser uploader skips hidden folders, so create `.github/workflows/agent.yml` with *Add file → Create new file* and paste its contents.
2. *Settings → Actions → General → Workflow permissions* → **Read and write**.
3. *Settings → Secrets and variables → Actions*: add every **secret** from the Settings section (type the names exactly),
   plus the `INSTAGRAM_HANDLE` **variable**.
4. Add royalty-free tracks (1–3 min MP3s, under ~10 MB each; the web uploader rejects files over 25 MB) to the `music/` folder,
   a few files at a time. Pixabay Music is a good free source.
5. *Actions → Reel Agent → Run workflow → mode* **check**. The bot sends you a ✅/❌ report for every service.

### 5. Reliable timing with cron-job.org (15 min)
GitHub's own scheduler is often late or skips runs, so a free cron-job.org account starts the agent instead.
1. Create a **fine-grained GitHub token**: only this repository, permission **Actions: Read and write**, longest expiry.
2. At cron-job.org, set your account timezone to **Asia/Kolkata** and create one cronjob:
   - Title: `Reel check`, schedule: **every 5 minutes**
   - URL: `https://api.github.com/repos/<you>/<repo>/actions/workflows/agent.yml/dispatches`
   - *Advanced* tab: method **POST**; headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
     `Content-Type: application/json`; body `{"ref":"main","inputs":{"mode":"poll"}}`

   The agent sends stories at the `OFFER_TIMES` by itself, so no other jobs are needed.
3. Use *Test run* on one job. **204 No Content** means it works; 401 means the token is wrong.

### 6. Doorbell for fast replies (20–30 min, optional)
Follow `doorbell/SETUP.md`: create a D1 database with the `updates` table, deploy `doorbell/worker.js` as a Worker,
bind the database as `DB`, add its **Secrets**, add `DOORBELL_URL` and `DOORBELL_KEY` on GitHub, and connect Telegram
with the `setWebhook` link **as the very last step**. Without the doorbell, the agent still works, but replies take up to 5 minutes.

### 7. First reel
Send `/news` to the bot, tap a story, tap a voice, then tap **🚀 Post now** on the preview to confirm posting works end to end.

---

## Troubleshooting

- **No reply:** open **Actions** and look for a red ❌; the error is at the bottom of the failed step.
- **Gemini "quota" or "overloaded":** wait and retry; the backup model kicks in automatically when the main one is busy.
- **Instagram "session expired":** the access token ran out; create a new one and update `IG_ACCESS_TOKEN`.
- **Turn the doorbell off:** open `https://api.telegram.org/bot<TOKEN>/deleteWebhook` and delete the
  `DOORBELL_URL` secret. The agent goes back to checking every 5 minutes.
- **Always check facts in the script before approving.** AI can get news details wrong.

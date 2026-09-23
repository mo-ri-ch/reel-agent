# 🎬 AI Reel Agent

A free agent that makes **2 faceless AI-news Instagram Reels a day in your own voice**.

**How your day looks**

1. **8:00 AM and 4:00 PM**: the bot sends you the top 3 AI stories on Telegram.
2. You reply **1, 2 or 3**, or type **your own topic**. (No reply in 2 hours means it picks #1.)
3. It sends you a script. Reply with changes ("shorter", "stronger hook") or **record it as a voice note** 🎤
4. It makes the reel and sends a preview: captions synced to your voice, a title card,
   free AI-generated images, and stock footage.
5. Reply **post** and it's scheduled for the next posting time (**1:00 PM** or **7:30 PM**).
   Reply **post now** to publish immediately, or **redo** to record again.

Want to record both reels in one sitting? After scheduling the first, send `/news` or `/topic ...` to start the next one straight away.

*Optional:* send a picture (e.g. a screenshot of the actual announcement) and it goes on the title card.
You never have to. By default, everything is automatic.

**Cost: ₹0.** It uses Telegram, Gemini (free tier), Cloudflare Workers AI (free tier), Pexels (free),
the Instagram API (free) and GitHub Actions (free).

> Replies are picked up every ~15 minutes (sometimes a bit longer when GitHub is busy), so it isn't instant chat. That's the trade-off for being free.

---

## Setup (about 1 hour, one time). Use a laptop if you can.

### Step 1: Telegram bot (5 min)
1. In Telegram, open **@BotFather**, send `/newbot`, and pick a name and username.
2. Copy the **bot token** it gives you → this is `TELEGRAM_BOT_TOKEN`.
3. Open your new bot and send it any message, like "hi".
4. In a browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   and find `"chat":{"id":123456789` → that number is `TELEGRAM_CHAT_ID`.

### Step 2: Gemini API key (2 min)
Go to **aistudio.google.com** → *Get API key* → *Create API key* → this is `GEMINI_API_KEY`.

### Step 3: Pexels API key (2 min)
Sign up at **pexels.com/api** → copy your key → this is `PEXELS_API_KEY`.
(Optional. Without it, reels use a plain gradient background.)

### Step 3b: Cloudflare (free AI images, 5 min)
1. Sign up free at **dash.cloudflare.com**.
2. Your **Account ID** is shown on the right side of the dashboard home (or under *Workers & Pages*) → this is `CF_ACCOUNT_ID`.
3. Go to **My Profile → API Tokens → Create Token** → use the **"Workers AI"** template → *Create* → this is `CF_API_TOKEN`.

(Optional. Without it, the agent tries Pollinations.ai, which needs no signup but is less reliable.)

### Step 3c: WhatsApp alerts (optional, 2 min)
Get a WhatsApp ping whenever stories are ready, a reel is waiting for approval, or a reel goes live.
You still reply on Telegram.
1. Go to **callmebot.com** → *WhatsApp API* page and follow the instructions there: save their WhatsApp
   number in your contacts and send them the activation message shown on the page.
2. They reply with your **API key** → this is `CALLMEBOT_API_KEY`.
3. Your WhatsApp number with country code (e.g. `+919876543210`) → this is `WHATSAPP_PHONE`.

(It's a free third-party service, so an alert can occasionally be late. Telegram always has everything.)

### Step 4: Instagram API (30-40 min, the fiddly part)
1. **Instagram app** → Settings → Account type → switch to **Creator** or **Business**.
2. Create a **Facebook Page** (any name) and link your Instagram to it
   (Page settings → Linked accounts → Instagram).
3. Go to **developers.facebook.com** → *My Apps* → *Create App* → choose the **Business** type
   (or the "Other" use case, then Business).
4. In the app, add the **Instagram** product (the version that uses *Facebook Login*).
5. Open **Tools → Graph API Explorer**, select your app, click *Generate Access Token* and allow these permissions:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`.
6. In the Explorer, run: `me/accounts?fields=name,instagram_business_account`
   → the `instagram_business_account` → `id` is your **`IG_USER_ID`**.
7. Make the token long-lasting: open **Access Token Debugger** (Tools menu), paste the token,
   and click **Extend Access Token** → this is `IG_ACCESS_TOKEN` (lasts ~60 days).

   *Better, never-expiring option:* business.facebook.com → Settings → **System users** → add an admin system user →
   assign it your app and Instagram account → *Generate token* with the permissions above.

You do **not** need App Review. The app works for your own account while in development mode.

### Step 5: GitHub (10 min)
1. Create a free account at **github.com** → **New repository** (name it e.g. `reel-agent`).
   - **Public is recommended.** GitHub Actions minutes are unlimited for public repos, and your keys stay hidden in Secrets.
   - For **Private**: change `*/15` to `*/30` in `.github/workflows/agent.yml` to stay within the free 2,000 minutes a month.
2. Upload all the files from this folder (*Add file → Upload files*). Make sure the
   `.github/workflows/agent.yml` file keeps that exact path. If the folder doesn't upload, use
   *Add file → Create new file*, type `.github/workflows/agent.yml` as the name, and paste the contents.
3. **Settings → Secrets and variables → Actions → New repository secret**. Add each one:

   | Secret | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | from Step 1 |
   | `TELEGRAM_CHAT_ID` | from Step 1 |
   | `GEMINI_API_KEY` | from Step 2 |
   | `PEXELS_API_KEY` | from Step 3 |
   | `CF_ACCOUNT_ID` | from Step 3b |
   | `CF_API_TOKEN` | from Step 3b |
   | `WHATSAPP_PHONE` | from Step 3c (optional) |
   | `CALLMEBOT_API_KEY` | from Step 3c (optional) |
   | `IG_USER_ID` | from Step 4 |
   | `IG_ACCESS_TOKEN` | from Step 4 |

4. In the same page, open the **Variables** tab and add `INSTAGRAM_HANDLE` = your handle (shown on every reel).
5. **Settings → Actions → General → Workflow permissions** → choose **Read and write** → Save.

### Step 6: Test it
1. **Actions** tab → *Reel Agent* → **Run workflow** → mode **check**.
   You'll get a Telegram message with ✅/❌ for each service.
2. Run it again with mode **offer** to get stories right away.
3. From now on, it runs by itself every day. 🎉

---

## Telegram commands
| Message | What happens |
|---|---|
| `1` / `2` / `3` | make a reel about that story |
| any text | use it as your own topic (or as script feedback once a script exists) |
| 🎤 voice note | make the reel from your recording |
| 🖼 picture | put it on the title card (optional) |
| `post` | schedule for the next posting time |
| `post now` | publish immediately |
| `redo` | record again |
| `/topic ...` | new reel on any topic, any time |
| `/news` | fresh stories now (start the next reel early) |
| `/queue` | see scheduled reels · `/clearqueue` cancels them |
| `/script` · `/status` · `/skip` · `/help` | as named |

## Recording tips
- Quiet room, phone about a hand's length from your mouth.
- Speak ~10% faster and with more energy than feels natural. It sounds normal on reels.
- Pause a moment before you start. The agent trims silence and levels the volume automatically.

## Changing things
- **Posting times**: add a repository variable `POST_TIMES`, e.g. `12:30,20:00` (your local time). Check your Instagram insights after 2 weeks to find your best times.
- **Story times**: edit `30 2 * * *` (8 AM IST) and `30 10 * * *` (4 PM IST) in the workflow. These are UTC; IST is UTC + 5:30.
- **Only 1 reel a day**: delete the `30 10 * * *` line and set `POST_TIMES` to one time.
- **Auto-pick delay**: add a repository variable `AUTO_PICK_HOURS` (default 2).
- **Better caption timing**: set variable `WHISPER_MODEL` to `small.en` (slower, more accurate).
- **News sources**: edit `FEEDS` in `news.py`.
- **Script style**: edit `RULES` in `writer.py`.

## Troubleshooting
- **Gemini "model not found"**: Google renames models over time. Set the variable `GEMINI_MODEL`
  to a current free model listed in AI Studio.
- **Instagram "session expired"**: your 60-day token ran out. Make a new one (or use the System User token).
- **No messages at all**: check the Actions tab for red ❌ runs and open one to read the error.
- **Replies are slow**: GitHub's timer can lag 5-20 minutes. That's normal on the free plan.
- **Always check facts in the script before recording.** AI can get news details wrong.

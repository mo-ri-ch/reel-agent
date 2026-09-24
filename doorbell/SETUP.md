# Doorbell setup (fast replies, free)

Do the parts in order. Part 4 must come last.

## Part 1: Cloudflare database
1. Cloudflare dashboard → Storage & databases → D1 SQL database → Create → name `reel-doorbell` → Create.
2. Open it → Console → run:
   CREATE TABLE updates (id INTEGER PRIMARY KEY, body TEXT);

## Part 2: Cloudflare Worker
1. Compute (Workers) → Workers & Pages → Create → "Start with Hello World" → name `reel-doorbell` → Deploy.
2. Edit code → delete everything → paste worker.js → Deploy. Note the URL (https://reel-doorbell.<you>.workers.dev).
3. Worker → Settings → Bindings → Add → D1 database → Variable name `DB` → database `reel-doorbell` → Save.
4. Worker → Settings → Variables and Secrets → Add each (type: Secret):
   BOT_TOKEN       your Telegram bot token
   GITHUB_TOKEN    your cron-job2 GitHub token (github_pat_...)
   REPO            mo-ri-ch/reel-agent
   WEBHOOK_SECRET  a random password you make up (letters, numbers, _ or -)
   AGENT_KEY       another random password you make up

## Part 3: GitHub
1. Repo secrets: DOORBELL_URL = your Worker URL, DOORBELL_KEY = same as AGENT_KEY.
2. Upload config.py, telegram_api.py, main.py (main folder) and agent.yml (.github/workflows).

## Part 4: Connect Telegram to the doorbell (last!)
Open in a browser (replace the 3 parts in < >):
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<WORKER_URL>/telegram&secret_token=<WEBHOOK_SECRET>&allowed_updates=["message","callback_query"]
You should see "Webhook was set".

## Turning it off
Open https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook and delete the DOORBELL_URL secret on GitHub.
The agent goes back to checking every 5 minutes.

// Reel Agent "doorbell" — a free Cloudflare Worker.
// Telegram sends every message/tap here instantly. The Worker saves it, shows "⏳ Got it!",
// and immediately starts your GitHub workflow, which then reads the saved messages.

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 1) Telegram → doorbell
    if (request.method === "POST" && url.pathname === "/telegram") {
      if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json();
      const cq0 = update.callback_query;
      if (cq0 && (cq0.data || "").endsWith("|noop")) {  // tapping the "✅ You chose" line: nothing to do
        ctx.waitUntil(telegram(env, "answerCallbackQuery", { callback_query_id: cq0.id }));
        return new Response("ok");
      }
      await env.DB.prepare("INSERT OR IGNORE INTO updates (id, body) VALUES (?, ?)")
        .bind(update.update_id, JSON.stringify(update)).run();

      // instant feedback so you know it was received
      if (update.callback_query) {
        const cq = update.callback_query;
        ctx.waitUntil(telegram(env, "answerCallbackQuery", {
          callback_query_id: cq.id, text: "⏳ Got it! Working on it...",
        }));
        ctx.waitUntil(showChoice(env, cq));
      } else if (update.message) {
        ctx.waitUntil(telegram(env, "sendChatAction", { chat_id: update.message.chat.id, action: "typing" }));
      }
      ctx.waitUntil(ringGitHub(env));
      return new Response("ok");
    }

    // 2) Your agent (on GitHub) → reads and clears saved messages
    if (url.pathname === "/updates" && url.searchParams.get("key") === env.AGENT_KEY) {
      if (request.method === "GET") {
        const { results } = await env.DB.prepare("SELECT body FROM updates ORDER BY id").all();
        return Response.json(results.map((r) => JSON.parse(r.body)));
      }
      if (request.method === "DELETE") {
        const upto = Number(url.searchParams.get("upto"));
        await env.DB.prepare("DELETE FROM updates WHERE id <= ?").bind(upto).run();
        return new Response("ok");
      }
    }

    return new Response("Reel Agent doorbell is running.", { status: 200 });
  },
};

// Replaces the tapped message's buttons with "✅ You chose: ..." so you can see your tap registered.
async function showChoice(env, cq) {
  const msg = cq.message;
  if (!msg) return;
  const buttons = (msg.reply_markup?.inline_keyboard || []).flat();
  const label = buttons.find((b) => b.callback_data === cq.data)?.text || "your choice";
  return telegram(env, "editMessageReplyMarkup", {
    chat_id: msg.chat.id, message_id: msg.message_id,
    reply_markup: { inline_keyboard: [[{ text: `✅ You chose: ${label}`, callback_data: "any||noop" }]] },
  });
}

async function telegram(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

async function ringGitHub(env) {
  return fetch(`https://api.github.com/repos/${env.REPO}/actions/workflows/agent.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "reel-agent-doorbell",
    },
    body: JSON.stringify({ ref: "main", inputs: { mode: "poll" } }),
  });
}

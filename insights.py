"""Collects Instagram stats every day (views, reach, shares, saves, watch time, followers) and writes the
weekly report. Everything is saved in stats/insights.json, so Claude can analyse it whenever you ask."""
import json
import os
import statistics
from datetime import datetime, timedelta

import requests

from config import IG_ACCESS_TOKEN, IG_GRAPH_BASE, IG_USER_ID

STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats", "insights.json")
REEL_METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]


def load():
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"account": {}, "reels": {}, "meta": {}, "notes": {}}


def save(data):
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)


def _get(path, **params):
    r = requests.get(f"{IG_GRAPH_BASE}/{path}", params={**params, "access_token": IG_ACCESS_TOKEN}, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"error": {"message": r.text[:200]}}
    if r.status_code != 200 or "error" in data:
        err = data.get("error", {})
        raise RuntimeError(f"{err.get('code', r.status_code)}: {err.get('message', err)}")
    return data


def remember_reel(link, meta):
    """Saves what the agent knows about a reel it just posted (voice, slot, story type…), keyed by its link,
    so its numbers can later be compared by those features."""
    if not link or not link.startswith("http"):
        return
    data = load()
    data.setdefault("meta", {})[link.rstrip("/")] = meta
    save(data)


_SUPPORTED = None  # metrics this API version accepts (found once per run)


def _reel_metrics(media_id):
    """Insights for one reel. If the full metric list is refused, each metric is tested once on its own and only
    the accepted ones are used from then on."""
    global _SUPPORTED

    def read(metrics):
        res = _get(f"{media_id}/insights", metric=",".join(metrics))
        out = {}
        for m in res.get("data", []):
            vals = m.get("values") or [{}]
            out[m["name"]] = (m.get("total_value") or {}).get("value", vals[0].get("value"))
        return out
    try:
        return read(_SUPPORTED or REEL_METRICS), None
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("10:") or "permission" in msg.lower():
            return {}, "permission"
        if _SUPPORTED is not None:
            return {}, msg[:200]
    ok = []
    for m in REEL_METRICS:
        try:
            read([m])
            ok.append(m)
        except RuntimeError:
            pass
    _SUPPORTED = ok
    if not ok:
        return {}, "no metrics available"
    try:
        return read(ok), None
    except RuntimeError as e:
        return {}, str(e)[:200]


def collect(tz, days=7):
    """Updates followers and the numbers of every reel from the last `days` days. Returns a status string."""
    data = load()
    now = datetime.now(tz)
    today = now.date().isoformat()
    try:
        acc = _get(IG_USER_ID, fields="followers_count,media_count,username")
        data["account"][today] = {"followers": acc.get("followers_count"), "posts": acc.get("media_count"),
                                  "at": now.isoformat(timespec="minutes")}
    except Exception as e:
        return f"couldn't read the account: {e}"
    since = now - timedelta(days=days)
    after, seen, problem = None, 0, None
    while True:
        params = {"fields": "id,caption,timestamp,permalink,media_product_type,like_count,comments_count",
                  "limit": 50}
        if after:
            params["after"] = after
        page = _get(f"{IG_USER_ID}/media", **params)
        items = page.get("data", [])
        for m in items:
            when = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(tz)
            if when < since:
                items = []
                break
            if m.get("media_product_type") not in (None, "REELS"):
                continue
            metrics, err = _reel_metrics(m["id"])
            problem = problem or err
            seen += 1
            data["reels"][m["id"]] = {
                "posted": when.isoformat(timespec="minutes"), "link": (m.get("permalink") or "").rstrip("/"),
                "title": (m.get("caption") or "").split("\n")[0][:120],
                "likes": m.get("like_count"), "comments": m.get("comments_count"),
                **metrics, "updated": now.isoformat(timespec="minutes")}
        after = (page.get("paging") or {}).get("cursors", {}).get("after")
        if not items or not after or not (page.get("paging") or {}).get("next"):
            break
    data["notes"]["insights_permission"] = problem != "permission"
    data["notes"]["last_collect"] = now.isoformat(timespec="minutes")
    if problem and problem != "permission":
        data["notes"]["last_problem"] = problem
    save(data)
    return f"updated {seen} reels" + (" (no insights permission)" if problem == "permission" else "")


# ---------------------------------------------------------------- the weekly report
def _views(r):
    return r.get("views") if r.get("views") is not None else r.get("reach")


def _group_avg(reels, key):
    groups = {}
    for r in reels:
        k = key(r)
        if k and _views(r) is not None:
            groups.setdefault(k, []).append(_views(r))
    return {k: (round(statistics.mean(v)), len(v)) for k, v in groups.items() if len(v) >= 3}


def weekly_report(tz):
    data = load()
    now = datetime.now(tz)
    week_ago, two_weeks = now - timedelta(days=7), now - timedelta(days=14)
    reels = [{**r, "meta": data.get("meta", {}).get(r.get("link", ""), {})} for r in data.get("reels", {}).values()]
    this = [r for r in reels if datetime.fromisoformat(r["posted"]) >= week_ago]
    last = [r for r in reels if two_weeks <= datetime.fromisoformat(r["posted"]) < week_ago]
    days = sorted(data.get("account", {}))
    f_now = data["account"][days[-1]]["followers"] if days else None
    f_then = next((data["account"][d]["followers"] for d in days if d <= week_ago.date().isoformat()), None)
    if f_then is None and days:
        f_then = data["account"][days[0]]["followers"]
    lines = ["📊 Weekly report"]
    if f_now is not None:
        lines.append(f"👥 Followers: {f_now}" + (f" ({f_now - f_then:+d} this week)"
                                                  if f_then is not None and len(days) > 1 else " (tracking started)"))
    if not data.get("notes", {}).get("insights_permission", True):
        lines.append("⚠️ Views and watch time need the insights permission on your Instagram token — ask Claude "
                     "to walk you through adding it.")
    tv = [_views(r) for r in this if _views(r) is not None]
    lv = [_views(r) for r in last if _views(r) is not None]
    if tv:
        lines.append(f"🎬 {len(this)} reels · {sum(tv):,} views · {round(statistics.mean(tv))} per reel"
                     + (f" ({round(statistics.mean(tv)) - round(statistics.mean(lv)):+d} vs last week)" if lv else ""))
        shares = sum(r.get("shares") or 0 for r in this)
        saves = sum(r.get("saved") or 0 for r in this)
        watch = [r["ig_reels_avg_watch_time"] / 1000 for r in this if r.get("ig_reels_avg_watch_time")]
        lines.append(f"🔁 {shares} shares · 💾 {saves} saves" + (f" · ⏱ {statistics.mean(watch):.1f}s avg watch"
                                                                 if watch else ""))
        ranked = sorted([r for r in this if _views(r) is not None], key=_views, reverse=True)
        lines.append("\n🏆 Best reels:")
        lines += [f"{i}. {_views(r)} views · {r['title'][:60]}\n   {r['link']}" for i, r in enumerate(ranked[:3], 1)]
        lines.append("\n📉 Weakest: " + "; ".join(f"{_views(r)} · {r['title'][:40]}" for r in ranked[-2:]))
        for label, key in [("By time slot (IST)", lambda r: r["posted"][11:13] + ":00"),
                           ("By voice", lambda r: r["meta"].get("engine")),
                           ("By reel type", lambda r: r["meta"].get("kind"))]:
            groups = _group_avg(this, key)
            if len(groups) >= 2:
                best = sorted(groups.items(), key=lambda kv: -kv[1][0])
                lines.append(f"\n{label}: " + " · ".join(f"{k} {v[0]}" for k, v in best[:4]))
        if len(tv) < 40:
            lines.append("\n(Small numbers so far — treat patterns as early hints.)")
    else:
        lines.append("No reel numbers yet this week.")
    return "\n".join(lines)

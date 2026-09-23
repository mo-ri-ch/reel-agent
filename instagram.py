"""Publishes a Reel using the official (free) Instagram Graph API."""
import os
import time

import requests

from config import IG_ACCESS_TOKEN, IG_GRAPH_BASE, IG_USER_ID


def _check(r):
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:300]}
    if r.status_code != 200 or "error" in data:
        err = data.get("error", data)
        raise RuntimeError(f"Instagram error: {err.get('message', err) if isinstance(err, dict) else err}")
    return data


def publish_reel(video_path, caption):
    size = os.path.getsize(video_path)
    # 1) create an upload container
    data = _check(requests.post(f"{IG_GRAPH_BASE}/{IG_USER_ID}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true", "access_token": IG_ACCESS_TOKEN}, timeout=60))
    container = data["id"]
    version = IG_GRAPH_BASE.split("/")[-1]
    upload_uri = data.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{version}/{container}"

    # 2) upload the video file directly (no hosting needed)
    with open(video_path, "rb") as f:
        _check(requests.post(upload_uri, data=f, timeout=600, headers={
            "Authorization": f"OAuth {IG_ACCESS_TOKEN}", "offset": "0", "file_size": str(size)}))

    # 3) wait for Instagram to process it
    for _ in range(60):
        status = _check(requests.get(f"{IG_GRAPH_BASE}/{container}", params={
            "fields": "status_code,status", "access_token": IG_ACCESS_TOKEN}, timeout=30))
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram couldn't process the video: {status.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram took too long to process the video.")

    # 4) publish
    media_id = _check(requests.post(f"{IG_GRAPH_BASE}/{IG_USER_ID}/media_publish", data={
        "creation_id": container, "access_token": IG_ACCESS_TOKEN}, timeout=60))["id"]
    try:
        return _check(requests.get(f"{IG_GRAPH_BASE}/{media_id}", params={
            "fields": "permalink", "access_token": IG_ACCESS_TOKEN}, timeout=30)).get("permalink", "")
    except Exception:
        return ""


def whoami():
    return _check(requests.get(f"{IG_GRAPH_BASE}/{IG_USER_ID}", params={
        "fields": "username", "access_token": IG_ACCESS_TOKEN}, timeout=30)).get("username")

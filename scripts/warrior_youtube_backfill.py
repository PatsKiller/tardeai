#!/usr/bin/env python3
"""Backfill Ross Cameron (@DaytradeWarrior) YouTube transcripts for 2026 YTD.

Registers the channel if missing, pages the uploads playlist until before
start_date, and ingests transcripts with publish_date metadata.

  python3 scripts/warrior_youtube_backfill.py --dry-run
  python3 scripts/warrior_youtube_backfill.py --apply --start 2026-01-01 --max 250
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CHANNEL_URL = "https://www.youtube.com/@DaytradeWarrior"
STRATEGY_FOCUS = "momentum_scalp_daytrade"
DEFAULT_START = date(2026, 1, 1)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def register_channel() -> dict:
    from youtube_transcript_ingest import extract_channel_id, get_channel_info, _get_conn

    channel_id = extract_channel_id(CHANNEL_URL)
    info = get_channel_info(channel_id)
    if info.get("error"):
        return {"error": info["error"], "channel_id": channel_id}

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO youtube_channels (channel_id, channel_name, channel_url, strategy_focus, added_by, active)
        VALUES (%s, %s, %s, %s, 'warrior_audit', TRUE)
        ON CONFLICT (channel_id) DO UPDATE SET
            channel_name = EXCLUDED.channel_name,
            channel_url = EXCLUDED.channel_url,
            strategy_focus = EXCLUDED.strategy_focus,
            active = TRUE
        """,
        (channel_id, info["channel_name"], f"https://www.youtube.com/channel/{channel_id}", STRATEGY_FOCUS),
    )
    conn.commit()
    conn.close()
    return {"channel_id": channel_id, "channel_name": info["channel_name"]}


def list_videos_since(channel_id: str, start: date, max_videos: int = 300) -> list[dict]:
    from youtube_transcript_ingest import get_channel_info, _get_youtube_api_key
    import urllib.request

    api_key = _get_youtube_api_key()
    if not api_key:
        return []

    info = get_channel_info(channel_id)
    if info.get("error"):
        return []

    playlist_id = info["uploads_playlist"]
    videos: list[dict] = []
    next_page = None

    while len(videos) < max_videos:
        url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet&playlistId={playlist_id}&maxResults=50&key={api_key}"
        )
        if next_page:
            url += f"&pageToken={next_page}"
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read())

        stop = False
        for item in data.get("items", []):
            s = item["snippet"]
            published = s.get("publishedAt", "")
            pub_date = None
            if published:
                try:
                    pub_date = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
                except Exception:
                    pub_date = None
            if pub_date and pub_date < start:
                stop = True
                break
            vid = s["resourceId"]["videoId"]
            videos.append({
                "video_id": vid,
                "title": s.get("title", ""),
                "published": published,
                "publish_date": pub_date,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
            if len(videos) >= max_videos:
                break

        next_page = data.get("nextPageToken")
        if stop or not next_page:
            break

    return [v for v in videos if not v.get("publish_date") or v["publish_date"] >= start]


def run(apply: bool, start: date, max_videos: int) -> dict:
    from youtube_transcript_ingest import ingest_video

    reg = register_channel()
    if reg.get("error"):
        print(json.dumps(reg, indent=2))
        return reg

    channel_id = reg["channel_id"]
    videos = list_videos_since(channel_id, start, max_videos=max_videos)
    in_scope = [v for v in videos if v.get("publish_date") and v["publish_date"] >= start]

    print(f"[warrior-yt] Channel: {reg['channel_name']} ({channel_id})")
    print(f"[warrior-yt] Videos since {start}: {len(in_scope)} (listed {len(videos)})")

    if not apply:
        for v in in_scope[:15]:
            print(f"  {v.get('publish_date')} | {v['title'][:70]}")
        if len(in_scope) > 15:
            print(f"  ... +{len(in_scope) - 15} more")
        return {"dry_run": True, "channel": reg, "in_scope": len(in_scope)}

    ingested = skipped = failed = 0
    for i, v in enumerate(in_scope):
        try:
            r = ingest_video(v["url"], added_by="warrior_backfill", publish_date=v.get("published"))
        except Exception as e:
            r = {"error": str(e)[:120]}
        st = r.get("status") or ("error" if r.get("error") else "?")
        if st == "ingested":
            ingested += 1
            print(f"  [{i+1}/{len(in_scope)}] INGESTED: {v['title'][:55]}")
        elif st == "already_exists":
            skipped += 1
        else:
            failed += 1
            if failed <= 5:
                print(f"  [{i+1}/{len(in_scope)}] FAIL: {v['title'][:40]} — {str(r.get('error',''))[:60]}")
        time.sleep(0.6)

    out = {
        "ok": True,
        "channel": reg,
        "in_scope": len(in_scope),
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start", default=str(DEFAULT_START))
    ap.add_argument("--max", type=int, default=250)
    args = ap.parse_args()
    apply = args.apply and not args.dry_run
    run(apply=apply, start=_parse_date(args.start), max_videos=args.max)


if __name__ == "__main__":
    main()
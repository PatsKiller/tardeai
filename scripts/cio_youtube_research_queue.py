#!/usr/bin/env python3
"""cio_youtube_research_queue.py — Material-only CIO YouTube research queue.

Pulls promoted, high-quality (quality_score >= 70) YouTube transcripts from
intelligence_whiteboard joined to youtube_transcripts. Lower-quality corpus
items stay out of the CIO desk queue.

Emits JSON under data/cio/youtube_research_queue.json for CIO/desk consumers.
Optional soft hook for hermes_research_agenda (agenda-compatible candidates).

Usage:
    python3 scripts/cio_youtube_research_queue.py --build
    python3 scripts/cio_youtube_research_queue.py --json
    python3 scripts/cio_youtube_research_queue.py --build --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

QUEUE_PATH = PROJECT_ROOT / "data" / "cio" / "youtube_research_queue.json"
MIN_QUALITY = 70
DEFAULT_LIMIT = 50

# Rough asset-class hints from strategy tags / title keywords.
_ASSET_HINTS = [
    (re.compile(r"\b(bond|treasury|agg|bnd|tlt|ief|lqd|hyg|muni)\b", re.I), "bond"),
    (re.compile(r"\b(covered.?call|jepi|qyld|put.?sell|options?\s+income)\b", re.I), "options_income"),
    (re.compile(r"\b(bitcoin|crypto|ethereum|btc|eth)\b", re.I), "crypto"),
    (re.compile(r"\b(gold|oil|commodit|silver|copper)\b", re.I), "commodity"),
    (re.compile(r"\b(etf|spy|qqq|vti|sector)\b", re.I), "etf"),
    (re.compile(r"\b(fed|fomc|macro|inflation|rates)\b", re.I), "macro"),
    (re.compile(r"\b(roth|ira|401k|retirement|medicare|rmd)\b", re.I), "retirement"),
    (re.compile(r"\b(stock|equity|earnings|growth|value)\b", re.I), "equity"),
]


def _get_conn():
    import psycopg2
    pw = ""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
                break
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai", password=pw,
        connect_timeout=10,
    )


def _parse_json_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _asset_class_hint(strategy_tags: list, title: str, summary: str) -> str:
    blob = " ".join(strategy_tags) + " " + (title or "") + " " + (summary or "")
    for rx, hint in _ASSET_HINTS:
        if rx.search(blob):
            return hint
    return "general"


def _extract_tickers(row: dict) -> list[str]:
    """Prefer whiteboard symbol / explicit tickers; never invent."""
    out: list[str] = []
    sym = (row.get("symbol") or "").strip().upper()
    if sym and re.fullmatch(r"[A-Z]{1,5}", sym):
        out.append(sym)
    for key in ("tickers_mentioned", "symbols_mentioned"):
        for t in _parse_json_list(row.get(key)):
            t = str(t).strip().upper()
            if t and re.fullmatch(r"[A-Z]{1,5}", t) and t not in out:
                out.append(t)
    return out


def fetch_material_youtube_rows(conn, *, min_quality: int = MIN_QUALITY,
                                limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Join promoted whiteboard YouTube items to transcripts; Q>=min_quality only."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Promoted = status='promoted' OR level >= 3 (tagger promotes Q>=70 at level 3)
    # OR youtube_transcripts.promoted_to_whiteboard.
    cur.execute("""
        SELECT
            wb.id AS whiteboard_id,
            wb.source_id,
            wb.symbol,
            wb.title AS wb_title,
            wb.summary AS wb_summary,
            wb.quality_score AS wb_quality,
            wb.status AS wb_status,
            wb.level AS wb_level,
            wb.promoted_at,
            yt.id AS transcript_id,
            yt.video_id,
            yt.title AS yt_title,
            yt.summary AS yt_summary,
            yt.quality_score AS yt_quality,
            yt.strategy_tags,
            yt.url,
            yt.channel_name,
            yt.ingested_at
        FROM intelligence_whiteboard wb
        JOIN youtube_transcripts yt
          ON yt.id = wb.source_id
        WHERE wb.source_type = 'youtube'
          AND GREATEST(COALESCE(wb.quality_score, 0), COALESCE(yt.quality_score, 0)) >= %s
          AND (
                wb.status = 'promoted'
             OR COALESCE(wb.level, 0) >= 3
             OR COALESCE(yt.promoted_to_whiteboard, false) = true
          )
        ORDER BY GREATEST(COALESCE(wb.quality_score, 0), COALESCE(yt.quality_score, 0)) DESC,
                 COALESCE(wb.promoted_at, yt.ingested_at) DESC NULLS LAST
        LIMIT %s
    """, (min_quality, limit * 3))  # over-fetch then dedupe
    rows = cur.fetchall() or []
    cur.close()
    return [dict(r) for r in rows]


def build_queue_items(rows: list[dict], *, min_quality: int = MIN_QUALITY,
                      limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Dedupe by video_id / whiteboard source_id; emit CIO-facing queue items."""
    seen_video: set[str] = set()
    seen_source: set[str] = set()
    items: list[dict] = []

    for r in rows:
        q = max(int(r.get("wb_quality") or 0), int(r.get("yt_quality") or 0))
        if q < min_quality:
            continue

        video_id = (r.get("video_id") or "").strip()
        source_id = str(r.get("source_id") or "")
        if video_id and video_id in seen_video:
            continue
        if source_id and source_id in seen_source:
            continue
        if video_id:
            seen_video.add(video_id)
        if source_id:
            seen_source.add(source_id)

        title = r.get("yt_title") or r.get("wb_title") or ""
        summary = r.get("yt_summary") or r.get("wb_summary") or ""
        strategy_tags = _parse_json_list(r.get("strategy_tags"))
        tickers = _extract_tickers(r)
        url = r.get("url") or (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        )

        items.append({
            "video_id": video_id or None,
            "whiteboard_source_id": source_id or None,
            "whiteboard_id": r.get("whiteboard_id"),
            "symbol": tickers[0] if tickers else (r.get("symbol") or None),
            "tickers_mentioned": tickers,
            "strategy_tags": strategy_tags,
            "title": title,
            "summary": (summary or "")[:500],
            "quality_score": q,
            "asset_class": _asset_class_hint(strategy_tags, title, summary),
            "url": url,
            "channel_name": r.get("channel_name"),
            "ingested_at": r.get("ingested_at").isoformat() if hasattr(r.get("ingested_at"), "isoformat") else r.get("ingested_at"),
        })
        if len(items) >= limit:
            break
    return items


def build_research_queue(*, min_quality: int = MIN_QUALITY, limit: int = DEFAULT_LIMIT,
                         persist: bool = True, conn=None) -> dict:
    """Build queue dict; optionally persist to data/cio/youtube_research_queue.json."""
    close = False
    if conn is None:
        conn = _get_conn()
        close = True
    try:
        rows = fetch_material_youtube_rows(conn, min_quality=min_quality, limit=limit)
        items = build_queue_items(rows, min_quality=min_quality, limit=limit)
    finally:
        if close:
            conn.close()

    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "min_quality": min_quality,
        "count": len(items),
        "items": items,
        "note": "Material-only CIO queue: promoted YouTube with quality_score>=70. "
                "Lower-tier transcripts remain in corpus only.",
    }
    if persist:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_PATH.write_text(json.dumps(payload, indent=2, default=str))
        print(f"[cio-yt-queue] Wrote {len(items)} items → {QUEUE_PATH}")
    return payload


def agenda_candidates_from_queue(limit: int = 5) -> list[dict]:
    """Soft integration for hermes_research_agenda: agenda-shaped candidates from queue file.

    Returns [] if queue missing/empty — never raises into agenda apply path.
    """
    try:
        if not QUEUE_PATH.exists():
            return []
        data = json.loads(QUEUE_PATH.read_text())
        out = []
        for it in (data.get("items") or [])[:limit]:
            label = (it.get("title") or it.get("symbol") or "YouTube research")[:80]
            tags = it.get("strategy_tags") or []
            keywords = list(tags)[:4]
            if it.get("symbol"):
                keywords.insert(0, it["symbol"])
            out.append({
                "key": f"ytq_{it.get('video_id') or it.get('whiteboard_source_id')}",
                "label": f"YouTube: {label}",
                "keywords": keywords[:8] or [label],
                "score": min(0.85, (float(it.get("quality_score") or 70) / 100.0) + 0.1),
                "source": "cio_youtube_research_queue",
                "why": f"Promoted YT Q={it.get('quality_score')} ({it.get('asset_class')})",
                "domain": it.get("asset_class") or "general",
                "provenance": {
                    "video_id": it.get("video_id"),
                    "url": it.get("url"),
                    "quality_score": it.get("quality_score"),
                },
            })
        return out
    except Exception as e:
        print(f"[cio-yt-queue] agenda_candidates soft-fail: {e}")
        return []


def load_queue() -> dict:
    if QUEUE_PATH.exists():
        return json.loads(QUEUE_PATH.read_text())
    return {"count": 0, "items": [], "note": "queue not built yet"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CIO material-only YouTube research queue")
    ap.add_argument("--build", action="store_true", help="Build and persist queue JSON")
    ap.add_argument("--json", action="store_true", help="Print queue JSON to stdout")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--min-quality", type=int, default=MIN_QUALITY)
    args = ap.parse_args(argv)

    if not args.build and not args.json:
        ap.print_help()
        return 1

    if args.build:
        payload = build_research_queue(
            min_quality=args.min_quality, limit=args.limit, persist=True)
    else:
        payload = load_queue()

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    elif args.build:
        print(f"[cio-yt-queue] {payload['count']} material items (Q>={args.min_quality})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

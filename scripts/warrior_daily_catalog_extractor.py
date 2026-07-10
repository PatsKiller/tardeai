#!/usr/bin/env python3
"""Extract Ross Cameron daily trade catalog from Warrior Trading YouTube transcripts.

Phase 1: regex/heuristic extraction (fast). Phase 2: Hermes LLM refinement (--hermes).

  python3 scripts/warrior_daily_catalog_extractor.py --since 2026-07-06 --until 2026-07-10
  python3 scripts/warrior_daily_catalog_extractor.py --apply --hermes --since 2026-01-01
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Common English words that look like tickers — exclude from symbol mining
_STOP = {
    "I", "A", "AM", "PM", "ET", "EST", "EDT", "USD", "CEO", "IPO", "SEC", "FDA", "ATH",
    "ALL", "AND", "ARE", "BUT", "CAN", "DAY", "FOR", "GET", "HAD", "HAS", "HER",
    "HIS", "HOW", "ITS", "LET", "MAY", "NEW", "NOT", "NOW", "OFF", "ONE", "OUR",
    "OUT", "RED", "RUN", "SAY", "SEE", "SET", "THE", "TOO", "TOP", "TRY", "TWO",
    "USE", "WAS", "WAY", "WHO", "WHY", "WIN", "YES", "YOU", "BIG", "LOW", "HIGH",
    "GAP", "RVOL", "LONG", "SHORT", "STOP", "OPEN", "HALT", "LIVE", "RECAP", "TRADE",
    "TRADES", "STOCK", "STOCKS", "MARKET", "GREEN", "LOSS", "GAIN", "MADE", "FROM",
    "AI", "US", "UK", "VWAP", "MACD", "EMA", "SMA", "RSI", "ATR", "OTC", "NYSE",
    "NASDAQ", "ETF", "VERY", "MOST", "BEST", "PRE", "POST", "RTH", "CHART", "LEVEL",
}

_RECAP_RE = re.compile(
    r"(recap|trades?|watchlist|green day|red day|p&l|profit|loss|made \$|trading)",
    re.I,
)
_PNL_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
_SYM_RE = re.compile(r"\b([A-Z]{1,5})\b")
_MONTH_DAY = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?",
    re.I,
)


def _get_conn():
    import psycopg2
    import psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _parse_trade_date(title: str, publish_date: date | None) -> date | None:
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    m = _MONTH_DAY.search(title or "")
    if m:
        mo = months[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else (publish_date.year if publish_date else date.today().year)
        try:
            return date(year, mo, day)
        except ValueError:
            pass
    # Recap videos often publish evening after session — use publish date as proxy
    return publish_date


def _extract_pnl(title: str, text: str) -> float | None:
    candidates = []
    for src in (title, (text or "")[:3000]):
        for m in _PNL_RE.findall(src):
            try:
                val = float(m.replace("$", "").replace(",", ""))
                if 50 <= val <= 150_000:
                    candidates.append(val)
            except ValueError:
                continue
    return max(candidates) if candidates else None


def _extract_symbols(title: str, text: str, known: set[str] | None = None) -> list[str]:
    blob = f"{title}\n{text or ''}"
    found = []
    seen = set()
    for m in _SYM_RE.findall(blob):
        if m in _STOP or m in seen:
            continue
        if len(m) == 1:
            continue
        if known and m not in known:
            continue
        seen.add(m)
        found.append(m)
    if not found and known:
        for m in _SYM_RE.findall(blob):
            if m in _STOP or m in seen or len(m) == 1:
                continue
            seen.add(m)
            found.append(m)
    return found


def _load_known_symbols(conn, since: date, until: date) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT UPPER(symbol) FROM trade_ai_scans
        WHERE run_date BETWEEN %s AND %s
        """,
        (since, until),
    )
    return {r[0] for r in cur.fetchall() if r[0]}


def fetch_warrior_transcripts(since: date, until: date) -> list[dict]:
    conn, cur = _get_conn()
    cur.execute(
        """
        SELECT id, video_id, title, channel_name, publish_date, transcript_text, cleaned_text, url
        FROM youtube_transcripts
        WHERE (
            channel_name ILIKE '%%daytrade%%warrior%%'
            OR channel_name ILIKE '%%ross%%cameron%%'
            OR title ILIKE '%%day trade warrior%%'
        )
        AND COALESCE(publish_date, ingested_at::date) BETWEEN %s AND %s
        ORDER BY publish_date DESC NULLS LAST
        """,
        (since, until),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def extract_row(row: dict, known_symbols: set[str]) -> dict | None:
    title = row.get("title") or ""
    text = row.get("cleaned_text") or row.get("transcript_text") or ""
    if not _RECAP_RE.search(title) and not _RECAP_RE.search(text[:2000]):
        return None

    pub = row.get("publish_date")
    if isinstance(pub, datetime):
        pub = pub.date()
    trade_date = _parse_trade_date(title, pub)
    if not trade_date:
        return None

    syms = _extract_symbols(title, text, known_symbols or None)
    if not syms and known_symbols:
        syms = _extract_symbols(title, text, None)
    pnl = _extract_pnl(title, text)

    conf = 0.55
    if syms:
        conf += 0.15
    if pnl is not None:
        conf += 0.1
    if _MONTH_DAY.search(title):
        conf += 0.15

    winners = [{"symbol": s, "pnl_usd": None, "note": "mentioned in recap"} for s in syms[:20]]

    return {
        "trade_date": trade_date,
        "video_id": row["video_id"],
        "video_title": title,
        "video_publish_date": pub,
        "symbols_traded": syms,
        "winners": winners,
        "losers": [],
        "net_pnl_usd": pnl,
        "extraction_method": "regex",
        "extraction_confidence": min(conf, 0.95),
        "hermes_review_json": {"source_transcript_id": row["id"], "title": title},
    }


def upsert_catalog(entries: list[dict]) -> int:
    conn, cur = _get_conn()
    n = 0
    for e in entries:
        cur.execute(
            """
            INSERT INTO ross_daily_catalog (
                trade_date, video_id, video_title, video_publish_date,
                symbols_traded, winners, losers, net_pnl_usd,
                extraction_method, extraction_confidence, hermes_review_json
            ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s::jsonb)
            ON CONFLICT (trade_date, video_id) DO UPDATE SET
                symbols_traded = EXCLUDED.symbols_traded,
                winners = EXCLUDED.winners,
                losers = EXCLUDED.losers,
                net_pnl_usd = EXCLUDED.net_pnl_usd,
                extraction_method = EXCLUDED.extraction_method,
                extraction_confidence = EXCLUDED.extraction_confidence,
                hermes_review_json = EXCLUDED.hermes_review_json,
                extracted_at = NOW()
            """,
            (
                e["trade_date"], e["video_id"], e["video_title"], e.get("video_publish_date"),
                e["symbols_traded"], json.dumps(e["winners"]), json.dumps(e["losers"]),
                e.get("net_pnl_usd"), e["extraction_method"], e["extraction_confidence"],
                json.dumps(e.get("hermes_review_json") or {}),
            ),
        )
        n += cur.rowcount
    conn.commit()
    conn.close()
    return n


def _hermes_refine(entry: dict, row: dict, known: set[str], *, skip_ollama: bool = False) -> dict:
    import sys as _sys_h
    _lib = PROJECT_ROOT / "scripts" / "lib"
    if str(_lib) not in _sys_h.path:
        _sys_h.path.insert(0, str(_lib))
    from ross_catalog_hermes import extract_with_hermes, merge_regex_and_hermes

    title = row.get("title") or entry.get("video_title") or ""
    text = row.get("cleaned_text") or row.get("transcript_text") or ""
    hermes = extract_with_hermes(
        title,
        text,
        trade_date=entry.get("trade_date"),
        known_symbols=known,
        regex_hints=entry,
        skip_ollama=skip_ollama,
    )
    if not hermes or not hermes.get("symbols_traded"):
        return entry
    return merge_regex_and_hermes(entry, hermes)


def run(since: date, until: date, apply: bool, *, use_hermes: bool = False, hermes_limit: int = 0, skip_ollama: bool = False) -> dict:
    rows = fetch_warrior_transcripts(since, until)
    conn, _ = _get_conn()
    known = _load_known_symbols(conn, since, until)
    conn.close()

    entries = []
    hermes_n = 0
    for row in rows:
        ex = extract_row(row, known)
        if not ex:
            continue
        if use_hermes and (hermes_limit <= 0 or hermes_n < hermes_limit):
            refined = _hermes_refine(ex, row, known, skip_ollama=skip_ollama)
            if refined.get("extraction_method") == "hermes":
                hermes_n += 1
                print(f"    [hermes] {ex['trade_date']} syms={','.join(refined.get('symbols_traded') or [])} pnl={refined.get('net_pnl_usd')}", flush=True)
            ex = refined
        entries.append(ex)

    print(f"[ross-catalog] transcripts={len(rows)} extracted={len(entries)} hermes={hermes_n}", flush=True)
    for e in entries:
        method = e.get("extraction_method", "regex")
        print(f"  {e['trade_date']} | [{method}] {e['video_title'][:55]} | syms={','.join(e['symbols_traded'][:8])} | pnl={e.get('net_pnl_usd')}")

    cross_n = 0
    if entries:
        import sys as _sys_cv
        _cv_lib = PROJECT_ROOT / "scripts" / "lib"
        if str(_cv_lib) not in _sys_cv.path:
            _sys_cv.path.insert(0, str(_cv_lib))
        from ross_catalog_cross_video import infer_clip_symbols

        before_empty = sum(1 for e in entries if not (e.get("symbols_traded") or []))
        entries = infer_clip_symbols(entries)
        cross_n = before_empty - sum(1 for e in entries if not (e.get("symbols_traded") or []))
        if cross_n:
            print(f"[ross-catalog] cross-video inferred {cross_n} clip rows", flush=True)

    if apply and entries:
        upsert_catalog(entries)

    return {
        "transcripts": len(rows), "extracted": len(entries),
        "hermes_refined": hermes_n, "cross_video_inferred": cross_n, "entries": entries,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hermes", action="store_true", help="Refine recap rows with Hermes LLM extraction")
    ap.add_argument("--hermes-limit", type=int, default=0, help="Max Hermes LLM calls (0=all)")
    ap.add_argument("--hermes-skip-ollama", action="store_true", help="Skip local Ollama; use OpenAI/Anthropic only")
    args = ap.parse_args()
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until) if args.until else date.today()
    out = run(since, until, apply=args.apply, use_hermes=args.hermes, hermes_limit=args.hermes_limit, skip_ollama=args.hermes_skip_ollama)
    print(json.dumps({
        "transcripts": out["transcripts"],
        "extracted": out["extracted"],
        "hermes_refined": out.get("hermes_refined", 0),
        "cross_video_inferred": out.get("cross_video_inferred", 0),
    }, indent=2))


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""alpha_vantage_owner.py — scheduled Alpha Vantage jobs through the one owner (dry run by default).

The gateway, budget and refusals live in scripts/lib/alpha_vantage_owner.py. This script runs the
two market-wide jobs the operator's gap ranking put first (2026-10-10) and publishes what they
return as files the Data Broker projections read:

  earnings_calendar      EARNINGS_CALENDAR horizon=3month, 1/day
                         -> data/runtime/alpha_vantage/earnings_calendar_latest.json (EarningsCalendar@v1)
  news_sentiment_window  NEWS_SENTIMENT time_from=<cursor> time_to=<now> sort=LATEST limit=1000, 14/day
                         -> data/runtime/alpha_vantage/news_sentiment_latest.json (NewsSentimentIndex@v1, 72 h)
                         -> data/runtime/alpha_vantage/news_sentiment_articles_YYYYMM.jsonl (append-only)

Both jobs are refused up front until the operator grants the registry scope (the owner reads
providers.alpha_vantage.supplies). Nothing schedules this script yet: a cron or n8n entry is an
operator grant (AGENTS.md §17; cron freeze 2026-10-09).

    python3 scripts/alpha_vantage_owner.py --job due                 # dry run: what is due now, 0 requests
    python3 scripts/alpha_vantage_owner.py --job all --preview-granted-scope   # dry run as if granted
    python3 scripts/alpha_vantage_owner.py --status                   # budget + key status, 0 requests
    python3 scripts/alpha_vantage_owner.py --job earnings_calendar --apply      # live (after the grants)

A dry run sends nothing and writes nothing: it swaps the HTTP transport for one that raises, and
prints the ledger hash before and after.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.alpha_vantage_owner import ET, AlphaVantageOwner, load_config  # noqa: E402

EARNINGS_SCHEMA = "EarningsCalendar@v1"
INDEX_SCHEMA = "NewsSentimentIndex@v1"
AV_TIME = "%Y%m%dT%H%M"
SCHEDULED_JOBS = ("earnings_calendar", "news_sentiment_window")


# ── parsing ──────────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def parse_earnings(rows: list[list[str]]) -> dict[str, dict[str, Any]]:
    """CSV rows (header first) -> {SYMBOL: earliest upcoming report}. Rows without a valid date drop."""
    if not rows:
        return {}
    header = [h.strip() for h in rows[0]]
    out: dict[str, dict[str, Any]] = {}
    for r in rows[1:]:
        if len(r) != len(header):
            continue
        rec = dict(zip(header, (c.strip() for c in r)))
        sym = rec.get("symbol", "").upper()
        try:
            datetime.strptime(rec.get("reportDate", ""), "%Y-%m-%d")
        except ValueError:
            continue
        if not sym:
            continue
        row = {"report_date": rec["reportDate"], "fiscal_date_ending": rec.get("fiscalDateEnding") or None,
               "estimate": _num(rec.get("estimate")), "currency": rec.get("currency") or None,
               "time_of_day": (rec.get("timeOfTheDay") or "").strip() or None, "name": rec.get("name") or None}
        prev = out.get(sym)
        if prev is None or row["report_date"] < prev["report_date"]:
            out[sym] = row
    return out


def label_for(score: float | None) -> str | None:
    """Alpha Vantage's own sentiment_score_definition bands."""
    if score is None:
        return None
    if score <= -0.35:
        return "Bearish"
    if score <= -0.15:
        return "Somewhat-Bearish"
    if score < 0.15:
        return "Neutral"
    if score < 0.35:
        return "Somewhat-Bullish"
    return "Bullish"


def _published_iso(raw: str) -> str | None:
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
        except (TypeError, ValueError):
            continue
    return None


def parse_feed(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in (payload or {}).get("feed") or []:
        url = str(a.get("url") or "").strip()
        title = str(a.get("title") or "").strip()
        if not (url or title):
            continue
        tickers = []
        for t in a.get("ticker_sentiment") or []:
            sym = str(t.get("ticker") or "").upper().strip()
            if not sym:
                continue
            tickers.append({"ticker": sym, "relevance": _num(t.get("relevance_score")),
                            "score": _num(t.get("ticker_sentiment_score")),
                            "label": t.get("ticker_sentiment_label")})
        out.append({
            "id": hashlib.sha1((url or title).encode("utf-8")).hexdigest(),
            "url": url, "title": title[:300], "source": str(a.get("source") or "")[:80],
            "time_published_raw": a.get("time_published"),
            "published_at": _published_iso(str(a.get("time_published") or "")),
            "overall_score": _num(a.get("overall_sentiment_score")),
            "overall_label": a.get("overall_sentiment_label"),
            "topics": [str(t.get("topic")) for t in (a.get("topics") or []) if t.get("topic")],
            "tickers": tickers,
        })
    return out


def build_index(articles: list[dict[str, Any]], *, now: datetime, window_hours: float,
                min_relevance: float) -> dict[str, Any]:
    """Per-ticker rollup over the window: relevance-weighted ticker sentiment, counts, top headlines."""
    cutoff = now - timedelta(hours=window_hours)
    day_cut = now - timedelta(hours=24)
    by: dict[str, dict[str, Any]] = {}
    kept = []
    for a in articles:
        try:
            pub = datetime.fromisoformat(a["published_at"]) if a.get("published_at") else None
        except ValueError:
            pub = None
        if pub is None or pub < cutoff:
            continue
        kept.append(a)
        for t in a.get("tickers") or []:
            rel, sc = t.get("relevance"), t.get("score")
            if rel is None or sc is None or rel < min_relevance:
                continue
            b = by.setdefault(t["ticker"], {"n": 0, "n_24h": 0, "w": 0.0, "ws": 0.0, "latest": None, "top": []})
            b["n"] += 1
            b["n_24h"] += 1 if pub >= day_cut else 0
            b["w"] += rel
            b["ws"] += rel * sc
            if b["latest"] is None or a["published_at"] > b["latest"]:
                b["latest"] = a["published_at"]
            b["top"].append({"title": a["title"], "url": a["url"], "source": a["source"],
                             "published_at": a["published_at"], "score": sc, "relevance": rel})
    by_ticker = {}
    for sym, b in sorted(by.items()):
        score = round(b["ws"] / b["w"], 4) if b["w"] else None
        top = sorted(b["top"], key=lambda x: (x["published_at"] or ""), reverse=True)[:5]
        by_ticker[sym] = {"articles": b["n"], "articles_24h": b["n_24h"], "weighted_score": score,
                          "label": label_for(score), "latest_published_at": b["latest"], "top": top}
    return {"articles": kept, "by_ticker": by_ticker}


# ── publishing ───────────────────────────────────────────────────────────────


def _atomic(path: Path, payload: Any) -> None:
    from lib.data_broker.atomic_json import atomic_write_json
    atomic_write_json(path, payload)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_earnings(owner: AlphaVantageOwner, now: datetime) -> dict[str, Any]:
    spec = owner.job_spec("earnings_calendar") or {}
    res = owner.request("earnings_calendar", dict(spec.get("params") or {}))
    out = {"job": "earnings_calendar", "outcome": res.outcome, "counted": res.counted, "detail": res.detail,
           "params": res.receipt.get("params") or dict(spec.get("params") or {})}
    if not res.ok or owner.dry_run:   # a dry run decides and stops: nothing parsed, nothing written
        out["published"] = False
        return out
    by_symbol = parse_earnings(res.payload)
    out["rows"] = len(by_symbol)
    if not by_symbol:
        out.update(published=False, outcome="parsed_zero_rows")
        return out
    doc = {"schema": EARNINGS_SCHEMA, "as_of": now.astimezone(timezone.utc).isoformat(),
           "source": "alpha_vantage", "function": "EARNINGS_CALENDAR", "horizon": spec.get("params", {}).get("horizon"),
           "writer": "scripts/alpha_vantage_owner.py", "rows": len(by_symbol),
           "with_time_of_day": sum(1 for r in by_symbol.values() if r.get("time_of_day")),
           "by_symbol": by_symbol}
    _atomic(owner.state / "earnings_calendar_latest.json", doc)
    out["published"] = True
    return out


def news_window(prev: dict[str, Any] | None, now: datetime, lookback_h: float) -> tuple[str, str, bool]:
    """(time_from, time_to, gap) in AV format. Contiguous with the previous pull unless older than lookback."""
    floor = now - timedelta(hours=lookback_h)
    start = floor
    gap = prev is None
    if prev and prev.get("cursor_time_to"):
        try:
            c = datetime.strptime(prev["cursor_time_to"], AV_TIME).replace(tzinfo=timezone.utc)
            start, gap = (c, False) if c >= floor else (floor, True)
        except ValueError:
            gap = True
    return start.strftime(AV_TIME), now.astimezone(timezone.utc).strftime(AV_TIME), gap


def run_news(owner: AlphaVantageOwner, now: datetime) -> dict[str, Any]:
    cfg = owner.cfg.get("news_sentiment") or {}
    spec = owner.job_spec("news_sentiment_window") or {}
    idx_path = owner.state / "news_sentiment_latest.json"
    prev = _read(idx_path)
    t_from, t_to, gap = news_window(prev, now, float(cfg.get("first_pull_lookback_hours") or 24))
    params = dict(spec.get("params") or {}, time_from=t_from, time_to=t_to)
    res = owner.request("news_sentiment_window", params)
    out = {"job": "news_sentiment_window", "outcome": res.outcome, "counted": res.counted,
           "time_from": t_from, "time_to": t_to, "cursor_gap": gap, "detail": res.detail}
    if not res.ok or owner.dry_run:
        out["published"] = False
        return out
    new = parse_feed(res.payload)
    limit = int(params.get("limit") or 1000)
    seen = {a["id"] for a in (prev or {}).get("articles") or []}
    fresh = [a for a in new if a["id"] not in seen]
    merged = list((prev or {}).get("articles") or []) + fresh
    built = build_index(merged, now=now, window_hours=float(cfg.get("index_window_hours") or 72),
                        min_relevance=float(cfg.get("min_relevance") or 0.3))
    hist = owner.state / f"news_sentiment_articles_{now.astimezone(timezone.utc).strftime('%Y%m')}.jsonl"
    owner.state.mkdir(parents=True, exist_ok=True)
    with hist.open("a", encoding="utf-8") as fh:
        for a in fresh:
            fh.write(json.dumps(a, sort_keys=True) + "\n")
    doc = {"schema": INDEX_SCHEMA, "as_of": now.astimezone(timezone.utc).isoformat(), "source": "alpha_vantage",
           "function": "NEWS_SENTIMENT", "writer": "scripts/alpha_vantage_owner.py",
           "cursor_time_to": t_to, "last_pull": {"time_from": t_from, "time_to": t_to, "returned": len(new),
                                                 "new": len(fresh), "truncated": len(new) >= limit, "cursor_gap": gap},
           "window_hours": cfg.get("index_window_hours"), "min_relevance": cfg.get("min_relevance"),
           "time_published_tz": cfg.get("time_published_tz"),
           "articles_in_window": len(built["articles"]), "tickers": len(built["by_ticker"]),
           "by_ticker": built["by_ticker"], "articles": built["articles"]}
    _atomic(idx_path, doc)
    out.update(published=True, returned=len(new), new=len(fresh), truncated=len(new) >= limit,
               tickers=len(built["by_ticker"]))
    return out


# ── schedule ─────────────────────────────────────────────────────────────────


def due_jobs(cfg: dict[str, Any], now: datetime, served: dict[str, str]) -> list[tuple[str, str]]:
    """[(job, slot)] whose latest slot today is <= now (ET) and not yet served."""
    et = now.astimezone(ET)
    out = []
    for job in SCHEDULED_JOBS:
        spec = cfg["jobs"].get(job) or {}
        past = [s for s in spec.get("slots_et") or [] if s <= et.strftime("%H:%M")]
        if not past:
            continue
        slot = f"{et.strftime('%Y-%m-%d')} {max(past)}"
        if served.get(job) != slot:
            out.append((job, slot))
    return out


def _refuse_network(params: dict[str, Any], timeout: float) -> tuple[int, str]:
    raise AssertionError("dry run: the HTTP transport is disabled")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--job", choices=("due", "all", *SCHEDULED_JOBS))
    ap.add_argument("--apply", action="store_true", help="send requests and publish (default: dry run)")
    ap.add_argument("--status", action="store_true", help="budget and key status; spends nothing")
    ap.add_argument("--preview-granted-scope", action="store_true",
                    help="dry run only: decide as if the proposed scope (news_sentiment, earnings_calendar) were granted")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.preview_granted_scope and args.apply:
        print("refused: --preview-granted-scope is a dry-run preview; a live call needs the registry grant")
        return 2
    if args.status:
        o = AlphaVantageOwner(config=cfg, dry_run=True, http=_refuse_network)
        print(json.dumps({"budget": o.budget_status(), "key": o.key_status()}, indent=2, default=str))
        return 0
    if not args.job:
        ap.error("--job or --status is required")
    dry = not args.apply
    scope = None
    if args.preview_granted_scope:
        from lib.alpha_vantage_owner import granted_domains
        scope = granted_domains() | {"news_sentiment", "earnings_calendar"}
    owner = AlphaVantageOwner(config=cfg, dry_run=dry, http=_refuse_network if dry else None, scope_override=scope)
    now = datetime.now(timezone.utc)
    sched_path = owner.state / "schedule_state.json"
    served = (_read(sched_path) or {}).get("served") or {}
    if args.job == "due":
        todo = due_jobs(cfg, now, served)
    elif args.job == "all":
        todo = [(j, "manual") for j in SCHEDULED_JOBS]
    else:
        todo = [(args.job, "manual")]
    before = owner.ledger_sha256()
    results = []
    for job, slot in todo:
        r = run_earnings(owner, now) if job == "earnings_calendar" else run_news(owner, now)
        r["slot"] = slot
        results.append(r)
        if not dry and slot != "manual":
            served[job] = slot
    if not dry and any(s != "manual" for _, s in todo):
        _atomic(sched_path, {"schema": "AlphaVantageOwnerSchedule@v1", "served": served,
                             "updated_at": now.isoformat()})
    report = {"mode": "dry_run" if dry else "apply", "at": now.isoformat(),
              "at_et": now.astimezone(ET).strftime("%Y-%m-%d %H:%M %Z"),
              "jobs": results, "requests_sent": owner.requests_sent,
              "ledger_sha256_before": before, "ledger_sha256_after": owner.ledger_sha256(),
              "budget": owner.budget_status(now)}
    print(json.dumps(report, indent=2, default=str))
    if dry and (owner.requests_sent or before != report["ledger_sha256_after"]):
        print("DRY RUN VIOLATION: a request was sent or the ledger changed", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

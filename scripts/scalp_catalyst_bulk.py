"""Bulk catalyst read for the 5-min Trade-AI scalp lane (2026-10-09).

The lane used to enrich every catalyst-cache miss with catalyst_enrichment.enrich_ticker: about two Finviz page
requests per ticker through the platform-wide Finviz throttle (one request per FINVIZ_MIN_INTERVAL across every
process). Around 60 names took longer than the lane's 295 s timeout once the afternoon cache expired, so every run
was killed (13:27 to 15:30 ET on 2026-10-09).

This reads, in the order config/trade_ai_scalp_lane.yaml `catalysts.source_order` gives:
  data_broker_news        news_articles through data_broker.catalyst_record.get_news_bulk (one SQL query)
  finviz_elite_news_bulk  Finviz Elite news export (v=3 stock news) for many tickers per request, batch_size names a
                          call, through finviz_http.finviz_get (the shared throttle)
and turns each symbol's articles into the enrich_ticker shape with catalyst_enrichment.build_enrichment, so scoring
and catalyst verification see the same fields. Symbols neither source covers are returned as `uncovered`; the caller
may still look a few of them up one at a time inside its time budget.
"""
from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def load_config(root: Optional[Path] = None) -> Dict[str, Any]:
    """`catalysts` block of config/trade_ai_scalp_lane.yaml; {} when absent or unreadable (bulk read off)."""
    try:
        import yaml

        doc = yaml.safe_load(((root or ROOT) / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8")) or {}
        return dict(doc.get("catalysts") or {})
    except Exception:
        return {}


def _utc_z(value: Any) -> str:
    """UTC 'YYYY-MM-DDTHH:MM:SSZ' — the form catalyst_enrichment._parse_iso reads. It rejects offsets other than
    +00:00 and offset+microseconds, so a DB timestamp in -04:00 would read as 9,999 h old and be dropped."""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _db_articles(symbols: List[str], cfg: Dict[str, Any], db_query: Optional[Callable]) -> Dict[str, List[Dict]]:
    try:
        from data_broker.catalyst_record import _db_query, get_news_bulk
    except Exception:
        return {}
    got = get_news_bulk(db_query or _db_query, symbols, hours=int(cfg["db_news_max_age_hours"]),
                        per_symbol=int(cfg["db_news_per_symbol"]))
    return {sym: [{"title": a.get("title") or "", "summary": "", "url": a.get("url") or "",
                   "source": a.get("source") or "news_db", "published_at": _utc_z(a.get("published_at")),
                   "provider": "news_db"} for a in arts] for sym, arts in got.items()}


def _finviz_time(text: str, tz: ZoneInfo) -> str:
    """Finviz export dates are exchange-local wall time ('2026-10-09 15:21:00'); returned as UTC ISO."""
    try:
        return _utc_z(datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz))
    except Exception:
        return ""


def _finviz_articles(symbols: List[str], cfg: Dict[str, Any], http_get: Optional[Callable],
                     stats: Dict[str, Any]) -> Dict[str, List[Dict]]:
    token = os.getenv("FINVIZ_API_TOKEN", "").strip()
    if not token or not symbols:
        return {}
    if http_get is None:
        from finviz_http import finviz_get as http_get
    tz = ZoneInfo(str(cfg["finviz_timezone"]))
    per = int(cfg["finviz_per_symbol"])
    wanted = set(symbols)
    out: Dict[str, List[Dict]] = {}
    size = max(1, int(cfg["finviz_batch_size"]))
    for i in range(0, len(symbols), size):
        chunk = symbols[i:i + size]
        url = f"{cfg['finviz_news_url']}?v={cfg['finviz_news_view']}&t={','.join(chunk)}&auth={token}"
        stats["finviz_calls"] += 1
        try:
            resp = http_get(url, headers={"User-Agent": os.getenv("FINVIZ_USER_AGENT", "Mozilla/5.0"), "Accept": "*/*"},
                            timeout=(5, 20), raise_on_429=False)
        except Exception as e:  # network error: keep what the earlier batches returned
            stats["finviz_error"] = type(e).__name__
            break
        if resp.status_code != 200:
            stats["finviz_error"] = f"HTTP {resp.status_code}"
            break                                           # 429: finviz_get already published the global cooldown
        for row in csv.DictReader(io.StringIO(resp.text)):
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            for sym in {s.strip().upper() for s in (row.get("Ticker") or "").split(",")} & wanted:
                if len(out.get(sym, [])) < per:
                    out.setdefault(sym, []).append({
                        "title": title, "summary": "", "url": row.get("Url") or "",
                        "source": row.get("Source") or "Finviz", "published_at": _finviz_time(row.get("Date") or "", tz),
                        "provider": "finviz_news"})
    return out


def enrich_bulk(symbols: List[str], cfg: Optional[Dict[str, Any]] = None, *, db_query: Optional[Callable] = None,
                http_get: Optional[Callable] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """({SYMBOL: enrich_ticker-shaped dict} for every symbol with at least one article, stats). Never raises."""
    t0 = time.monotonic()
    cfg = cfg if cfg is not None else load_config()
    syms = sorted({(s or "").upper().strip() for s in symbols if s and str(s).strip()})
    stats: Dict[str, Any] = {"symbols": len(syms), "finviz_calls": 0, "covered": {}, "uncovered": []}
    raw: Dict[str, List[Dict]] = {}
    try:
        for source in cfg.get("source_order") or []:
            todo = [s for s in syms if s not in raw] if cfg.get("fill_gaps_only") else syms
            if source == "data_broker_news":
                got = _db_articles(todo, cfg, db_query)
            elif source == "finviz_elite_news_bulk":
                got = _finviz_articles(todo, cfg, http_get, stats)
            else:
                continue
            stats["covered"][source] = len(got)
            for sym, arts in got.items():
                raw.setdefault(sym, []).extend(arts)
        from catalyst_enrichment import build_enrichment

        out = {sym: build_enrichment(sym, arts) for sym, arts in raw.items()}
    except Exception as e:
        stats["error"] = f"{type(e).__name__}: {e}"[:200]
        out = {}
    stats["uncovered"] = [s for s in syms if s not in out]
    stats["seconds"] = round(time.monotonic() - t0, 2)
    return out, stats

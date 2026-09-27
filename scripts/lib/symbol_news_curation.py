"""Gap-driven symbol-news curation, with an SLA (operator 2026-09-27).

Why: the thesis evidence gate needs at least one APPROVED news or primary item, and
the only curator (topic_curator) reviews `source LIKE 'topic_%'` rows. Company news
from RSS/SEC was never curated: 35,815 articles across 2,688 symbols in 30 days sat
at `pending`, so a symbol with no house thesis (DELL: 57 articles, all pending) could
never pass the gate however much research ran.

What: deterministic, auditable approval of a symbol's pending news when that symbol
needs evidence -- the headline names the ticker or company, the article is recent,
the publisher is not blocked, a bounded number per symbol, each with its reason.
SEC filings count as primary. The SLA report measures how long evidence-needing
symbols have waited. Rules live in portfolio_intent.yaml
options_desk_settings.symbol_news_curation. READ_ONLY_ADVISORY; MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_ROOT = Path(__file__).resolve().parents[2]

DEFAULTS: dict[str, Any] = {
    "max_age_days": 30,
    "max_per_symbol": 5,
    "max_symbols_per_run": 40,
    "blocked_sources": [],
    "primary_source_prefixes": ["sec_edgar"],
    "sla_hours_priority": 24,       # evidence-needing symbols (gap, held)
    "sla_hours_default": 72,
    "acquire_per_run": 2,           # priority symbols the monitor re-acquires per run
    "acquire_max_llm": 2,
}
_GENERIC = {"inc", "corp", "corporation", "co", "company", "ltd", "plc", "the", "group", "holdings",
            "technologies", "technology", "trust", "fund", "etf", "class", "shares", "sa", "ag", "nv"}
_TABLE_NAME_RE = re.compile(r"^(.*?)(?:\s+[—-]\s+|$)")


def settings(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if cfg is None:
        try:
            import yaml
            intent = yaml.safe_load((_ROOT / "assets" / "portfolio_intent.yaml").read_text()) or {}
            cfg = (intent.get("options_desk_settings") or {}).get("symbol_news_curation") or {}
        except Exception:  # noqa: BLE001
            cfg = {}
    return {k: (cfg or {}).get(k, v) for k, v in DEFAULTS.items()}


def name_tokens(description: Optional[str]) -> list[str]:
    """'Dell Technologies Inc — Computer Hardware.' -> ['dell']"""
    m = _TABLE_NAME_RE.match(str(description or "").strip())
    words = re.findall(r"[A-Za-z][A-Za-z&'.]+", (m.group(1) if m else "") or "")
    out = [w.lower().strip(".") for w in words if len(w) >= 3 and w.lower().strip(".") not in _GENERIC]
    return out[:1]


def names_the_company(title: str, symbol: str, tokens: Iterable[str]) -> bool:
    t = str(title or "")
    if re.search(rf"(?<![A-Za-z]){re.escape(symbol.upper())}(?![A-Za-z])", t):
        return True
    low = t.lower()
    return any(re.search(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", low) for tok in tokens)


def select(rows: list[dict[str, Any]], symbol: str, tokens: list[str], s: dict[str, Any], *,
           now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Pending rows to approve, primary first then newest, with a reason each."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=float(s["max_age_days"]))
    blocked = {str(x).lower() for x in s.get("blocked_sources") or []}
    prim = tuple(str(x).lower() for x in s.get("primary_source_prefixes") or [])
    picked = []
    for r in rows:
        src = str(r.get("source") or "").lower()
        ts = r.get("created_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts is None or ts < cutoff or src in blocked or src.startswith("topic_"):
            continue
        primary = src.startswith(prim) if prim else False
        if not primary and not names_the_company(r.get("title") or "", symbol, tokens):
            continue
        reason = ("symbol_gap_curation: primary filing" if primary else
                  f"symbol_gap_curation: headline names {symbol}; {src}; <= {s['max_age_days']}d")
        picked.append({**r, "_primary": primary, "_reason": reason, "_ts": ts})
    picked.sort(key=lambda r: (not r["_primary"], -(r["_ts"].timestamp())))
    return picked[: int(s["max_per_symbol"])]


PENDING_SQL = """SELECT id, title, source, created_at FROM news_articles
                 WHERE symbol=%s AND rag_status='pending' ORDER BY created_at DESC LIMIT 200"""
NAME_SQL = "SELECT description_1s FROM symbol_profiles WHERE symbol=%s LIMIT 1"


def curate_symbol(cur, symbol: str, s: dict[str, Any], *, apply: bool,
                  now: Optional[datetime] = None) -> dict[str, Any]:
    sym = symbol.upper()
    cur.execute(NAME_SQL, (sym,))
    row = cur.fetchone()
    desc = (row.get("description_1s") if isinstance(row, dict) else (row[0] if row else None)) if row else None
    tokens = name_tokens(desc)
    cur.execute(PENDING_SQL, (sym,))
    rows = [dict(r) if isinstance(r, dict) else dict(zip(("id", "title", "source", "created_at"), r))
            for r in cur.fetchall() or []]
    picked = select(rows, sym, tokens, s, now=now)
    approved = 0
    if apply and picked:
        try:
            from lib.writers.news_articles_writer import set_rag_status
        except ImportError:  # pragma: no cover
            from scripts.lib.writers.news_articles_writer import set_rag_status  # type: ignore
        for r in picked:
            approved += int(set_rag_status(cur, r["id"], "approved", r["_reason"]) or 0)
    return {"symbol": sym, "name_tokens": tokens, "pending_seen": len(rows), "selected": len(picked),
            "approved": approved if apply else 0,
            "titles": [str(r.get("title") or "")[:100] for r in picked]}


SLA_SQL = """SELECT symbol,
                    count(*) FILTER (WHERE rag_status='pending') AS n,
                    min(created_at) FILTER (WHERE rag_status='pending') AS oldest,
                    count(*) FILTER (WHERE rag_status='approved'
                                       AND created_at > now() - make_interval(days => %s)) AS approved_recent
             FROM news_articles
             WHERE source NOT LIKE 'topic_%%' AND symbol = ANY(%s)
             GROUP BY symbol"""
PLATFORM_SQL = """SELECT count(*) AS n, count(DISTINCT symbol) AS syms FROM news_articles
                  WHERE rag_status='pending' AND source NOT LIKE 'topic_%%'
                    AND created_at > now() - interval '30 days'"""


def sla_report(cur, priority: list[str], s: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Breach = an evidence-needing symbol with NO approved news in the window while
    news for it has waited in `pending` longer than the SLA (curation is stuck).
    Leftover pending rows that the rules correctly skip do not breach once the
    symbol has approved evidence. Platform backlog is reported alongside."""
    now = now or datetime.now(timezone.utc)
    breaches, waiting = [], []
    if priority:
        cur.execute(SLA_SQL, (int(s["max_age_days"]), list(priority)))
        for r in cur.fetchall() or []:
            r = dict(r) if isinstance(r, dict) else dict(zip(("symbol", "n", "oldest", "approved_recent"), r))
            oldest = r.get("oldest")
            if oldest is not None and oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            age_h = (now - oldest).total_seconds() / 3600 if oldest else 0.0
            item = {"symbol": r["symbol"], "pending": int(r.get("n") or 0),
                    "approved_recent": int(r.get("approved_recent") or 0), "oldest_age_hours": round(age_h, 1)}
            waiting.append(item)
            if item["approved_recent"] == 0 and item["pending"] > 0 and age_h > float(s["sla_hours_priority"]):
                breaches.append(item)
    cur.execute(PLATFORM_SQL)
    p = cur.fetchone()
    p = dict(p) if isinstance(p, dict) else ({"n": p[0], "syms": p[1]} if p else {"n": 0, "syms": 0})
    return {"schema": "SymbolNewsCurationSLA@v1", "as_of": now.isoformat(),
            "sla_hours_priority": s["sla_hours_priority"], "priority_symbols": len(priority),
            "waiting": sorted(waiting, key=lambda x: -x["oldest_age_hours"])[:50],
            "breaches": breaches, "breach_count": len(breaches),
            "platform_pending_30d": int(p.get("n") or 0), "platform_pending_symbols_30d": int(p.get("syms") or 0),
            "authority": "READ_ONLY_ADVISORY"}

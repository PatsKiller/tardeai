"""News / catalyst intelligence for Watch board (read path + async worker helpers).

Phase 0: deterministic freshness from DB + optional durable agent artifacts.
Phase 1: DeepSeek FAST worker writes artifacts under news_intelligence/.
GET/broker paths never call providers.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ET = ZoneInfo("America/New_York")

ARTIFACT_DIR = (
    PROJECT_ROOT / "data" / "runtime" / "watchlist_intelligence" / "news_intelligence"
)
# Prefer host shared runtime when present
_HOST_ART = Path(
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime/"
    "watchlist_intelligence/news_intelligence"
)
if _HOST_ART.parent.exists():
    ARTIFACT_DIR = _HOST_ART

PROCESS_ID = "watch_news_intelligence_flash"
WORKER_MODEL = "deepseek-v4-flash"
WORKER_POLICY = "FAST"

# Freshness windows
FRESH_HOURS_RTH = 6
FRESH_HOURS_OFF = 24
STALE_HOURS = 72  # beyond this → MISSING for promotion purposes if no better source


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


def _is_rth(now: datetime | None = None) -> bool:
    n = (now or _now()).astimezone(ET)
    if n.weekday() >= 5:
        return False
    mins = n.hour * 60 + n.minute
    return 9 * 60 + 30 <= mins < 16 * 60


def compute_freshness(as_of: Any, *, now: datetime | None = None) -> str:
    """Return FRESH | STALE | MISSING."""
    ts = _parse_ts(as_of)
    if not ts:
        return "MISSING"
    now = now or _now()
    age_h = (now - ts).total_seconds() / 3600.0
    if age_h < 0:
        age_h = 0
    limit = FRESH_HOURS_RTH if _is_rth(now) else FRESH_HOURS_OFF
    if age_h <= limit:
        return "FRESH"
    if age_h <= STALE_HOURS:
        return "STALE"
    return "MISSING"


def _db_query(sql: str, params=None, fetch: str = "all"):
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    if fetch == "one":
        return cur.fetchone()
    return cur.fetchall() or []


def load_db_headlines(symbol: str, *, limit: int = 8, lookback_days: int = 14) -> list[dict[str, Any]]:
    """Deterministic headlines from news_articles (no provider)."""
    sym = symbol.upper()
    out: list[dict[str, Any]] = []
    try:
        rows = _db_query(
            """
            SELECT title, source, source_url, published_at, created_at, relevance_score, sentiment
              FROM news_articles
             WHERE upper(symbol) = %s
               AND COALESCE(published_at, created_at) > now() - (%s || ' days')::interval
               AND COALESCE(hygiene_status, 'ok') NOT IN ('demoted', 'retired', 'spam')
             ORDER BY COALESCE(published_at, created_at) DESC
             LIMIT %s
            """,
            (sym, str(int(lookback_days)), int(limit)),
        )
    except Exception:
        try:
            rows = _db_query(
                """
                SELECT title, source, source_url, published_at, created_at, relevance_score, sentiment
                  FROM news_articles
                 WHERE upper(symbol) = %s
                   AND COALESCE(published_at, created_at) > now() - interval '14 days'
                 ORDER BY COALESCE(published_at, created_at) DESC
                 LIMIT %s
                """,
                (sym, int(limit)),
            )
        except Exception:
            return out
    for row in rows or []:
        if hasattr(row, "keys"):
            title = row.get("title")
            pub = row.get("published_at") or row.get("created_at")
            src = row.get("source")
            url = row.get("source_url")
        else:
            title, src, url, pub = row[0], row[1], row[2], row[3] or (row[4] if len(row) > 4 else None)
        if not title:
            continue
        out.append({
            "title": str(title)[:300],
            "source": str(src or "news")[:80],
            "published_at": pub.isoformat() if hasattr(pub, "isoformat") else pub,
            "url_hash": hashlib.sha256(str(url or title).encode()).hexdigest()[:16],
        })
    return out


def load_db_catalysts(symbol: str, *, limit: int = 5, lookback_days: int = 60) -> list[dict[str, Any]]:
    sym = symbol.upper()
    out: list[dict[str, Any]] = []
    try:
        rows = _db_query(
            """
            SELECT catalyst_type, headline, severity, impact_score, source,
                   COALESCE(published_at, created_at) AS ts, source_url
              FROM catalyst_events
             WHERE upper(symbol) = %s
               AND COALESCE(published_at, created_at) > now() - (%s || ' days')::interval
             ORDER BY COALESCE(published_at, created_at) DESC
             LIMIT %s
            """,
            (sym, str(int(lookback_days)), int(limit)),
        )
    except Exception:
        return out
    for row in rows or []:
        if hasattr(row, "keys"):
            out.append({
                "type": row.get("catalyst_type"),
                "headline": row.get("headline"),
                "severity": row.get("severity"),
                "impact": row.get("impact_score"),
                "source": row.get("source"),
                "at": row.get("ts").isoformat() if hasattr(row.get("ts"), "isoformat") else row.get("ts"),
                "url": row.get("source_url"),
            })
        else:
            out.append({
                "type": row[0], "headline": row[1], "severity": row[2], "impact": row[3],
                "source": row[4],
                "at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5],
                "url": row[6] if len(row) > 6 else None,
            })
    return out


def load_news_artifact(symbol: str) -> dict[str, Any] | None:
    path = ARTIFACT_DIR / f"{symbol.upper()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_news_artifact(payload: dict[str, Any]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    sym = (payload.get("symbol") or "UNKNOWN").upper()
    path = ARTIFACT_DIR / f"{sym}.json"
    raw = json.dumps(payload, sort_keys=True, default=str)
    payload = dict(payload)
    payload["artifact_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def project_catalyst_context(card: dict[str, Any]) -> dict[str, Any]:
    """Compose catalyst fields for a card (deterministic + optional agent artifact).

    Prefer agent artifact when COMPLETE + oversight not REJECT.
    Else fall back to DB catalyst/news; else earnings date; else MISSING.
    """
    sym = (card.get("symbol") or "").upper()
    art = load_news_artifact(sym) if sym else None

    # Agent path
    if art and art.get("status") in ("COMPLETE", "NO_MATERIAL"):
        ov = (art.get("oversight") or {}).get("status") or "SKIPPED"
        if ov != "REJECT":
            as_of = art.get("catalyst_as_of") or art.get("as_of")
            summary = art.get("catalyst_summary")
            if art.get("status") == "NO_MATERIAL":
                summary = summary or "No material catalyst in recent window"
            # Recompute freshness from age for honesty
            fresh = compute_freshness(as_of)
            if summary and fresh == "MISSING":
                fresh = "STALE"  # text exists but aged — never pretend FRESH
            if not summary:
                fresh = "MISSING"
            return {
                "catalyst_summary": summary,
                "catalyst_as_of": as_of,
                "catalyst_freshness": fresh,
                "catalyst_type": art.get("catalyst_type"),
                "catalyst_severity": art.get("severity"),
                "catalyst_source_mix": art.get("source_mix") or [],
                "latest_headlines": (art.get("headlines") or [])[:3],
                "catalyst_oversight_status": ov,
                "catalyst_worker_status": art.get("status"),
                "catalyst_vs_industry": None,
                "catalyst_vs_industry_quality": "UNAVAILABLE",
            }

    # Deterministic DB path
    cats = load_db_catalysts(sym) if sym else []
    headlines = load_db_headlines(sym) if sym else []
    summary = None
    as_of = None
    ctype = None
    severity = None
    sources: list[str] = []

    if cats:
        c0 = cats[0]
        summary = c0.get("headline")
        as_of = c0.get("at")
        ctype = c0.get("type")
        severity = c0.get("severity")
        if c0.get("source"):
            sources.append(str(c0["source"]))
    if not summary and headlines:
        h0 = headlines[0]
        summary = h0.get("title")
        as_of = h0.get("published_at")
        if h0.get("source"):
            sources.append(str(h0["source"]))
        ctype = ctype or "news"
    if not summary and card.get("catalyst_summary"):
        summary = card.get("catalyst_summary")
        # earnings-only strings: weak as_of
        if str(summary).startswith("Next earnings:"):
            ctype = "earnings"
            as_of = None  # force MISSING/STALE honesty unless we have date
            ed = card.get("next_earnings_date")
            if ed:
                as_of = str(ed)
    if not summary:
        ed = card.get("next_earnings_date")
        if ed:
            summary = f"Next earnings: {ed}"
            ctype = "earnings"
            as_of = str(ed)

    for h in headlines[:3]:
        s = h.get("source")
        if s and s not in sources:
            sources.append(str(s))

    fresh = compute_freshness(as_of) if summary else "MISSING"
    if not summary:
        fresh = "MISSING"
    elif fresh == "MISSING":
        fresh = "STALE"

    return {
        "catalyst_summary": summary,
        "catalyst_as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else as_of,
        "catalyst_freshness": fresh,
        "catalyst_type": ctype,
        "catalyst_severity": severity,
        "catalyst_source_mix": sources[:6] or (["catalyst_events"] if cats else (["news_articles"] if headlines else [])),
        "latest_headlines": headlines[:3],
        "catalyst_oversight_status": None,
        "catalyst_worker_status": None,
        "catalyst_vs_industry": None,
        "catalyst_vs_industry_quality": "UNAVAILABLE",
    }


def build_worker_prompt(symbol: str, company: str | None, headlines: list[dict], catalysts: list[dict]) -> str:
    hl = "\n".join(
        f"- [{h.get('source')}] {h.get('published_at')}: {h.get('title')}"
        for h in headlines[:8]
    ) or "- (none)"
    cl = "\n".join(
        f"- [{c.get('type')}|{c.get('severity')}] {c.get('at')}: {c.get('headline')}"
        for c in catalysts[:5]
    ) or "- (none)"
    return f"""You are the Watch News Intelligence agent. Advisory only. No trades. No orders.

Symbol: {symbol}
Company: {company or 'n/a'}

Recent headlines:
{hl}

Existing catalyst rows:
{cl}

Return JSON only with keys:
catalyst_summary (one line, max 160 chars; or null if no material news),
catalyst_type (earnings|M&A|product|macro|legal|technical|none),
severity (low|med|high),
material (true|false),
what_changed (short),
risks (array of short strings),
evidence_refs (array of short strings citing headline sources)
Do not invent tickers or prices. If nothing material, material=false and catalyst_type=none.
"""


def parse_worker_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"catalyst_summary": text[:160], "material": True, "catalyst_type": "news", "severity": "low"}


def run_oversight_stub(worker_payload: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: skip dual OAuth by default; mark SKIPPED.

    High-severity material items can be escalated later to Grok+ChatGPT dual.
    """
    sev = str(worker_payload.get("severity") or "low").lower()
    material = bool(worker_payload.get("material"))
    if not material or sev == "low":
        return {
            "status": "SKIPPED",
            "models": [],
            "notes": "low_severity_or_non_material",
            "at": _now_iso(),
        }
    # Placeholder for dual OAuth — do not call yet without explicit canary flag
    return {
        "status": "SKIPPED",
        "models": [],
        "notes": "oversight_deferred_phase2",
        "at": _now_iso(),
    }

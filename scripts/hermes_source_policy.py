"""hermes_source_policy.py — runtime source registry policy for Hermes pipelines.

Connects research_sources.active + maturity tiers to ingest, scoring, catalyst confidence,
directive promotion, and SearXNG domain filtering. UI labels (LIVE / candidate / demoted)
must match what the pipelines actually do.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
MATURITY_JSON = ROOT / "data" / "runtime" / "source_maturity_latest.json"

CONNECTOR_TYPES = frozenset({
    "social", "youtube", "sec", "rss",
    "ai_openai", "ai_anthropic", "ai_xai", "seeking_alpha",
})

# Always-on ingest pipes (infrastructure). Gated only by parent connector when applicable.
BASE_INGEST_SOURCES = frozenset({
    "yahoo_rss", "finnhub", "benzinga_rss", "benzinga_api",
})

SOURCE_TO_CONNECTOR = {
    "yahoo_rss": "rss",
    "benzinga_rss": "rss",
    "benzinga_api": "rss",
    "seeking_alpha": "seeking_alpha",
    "motley_fool": "rss",
    "morningstar": "rss",
    "barrons": "rss",
    "marketwatch": "rss",
    "finviz_news": "rss",  # finviz uses API token, not RSS connector — always allowed if not demoted
    "youtube_api": "youtube",
    "youtube": "youtube",
}

TIER_SCORE_MULT = {
    "core": 1.15,
    "trusted": 1.10,
    "probationary": 1.0,
    "candidate": 0.92,
    "demoted": 0.75,
}

TIER_QUALITY_BASE = {
    "core": 80,
    "trusted": 70,
    "probationary": 55,
    "candidate": 40,
    "demoted": 15,
}

_CACHE: dict | None = None
_CACHE_AT: float = 0.0
_CACHE_TTL = 300.0


@dataclass
class SourcePolicy:
    source: str
    source_type: str | None = None
    registry_active: bool = False
    raw_tier: str = "candidate"
    effective_tier: str = "candidate"
    promotion_tier: str = "candidate"
    operator_core_approved: bool = False
    maturity_score: float | None = None
    go_rate: float | None = None
    ingest_allowed: bool = True
    promotion_allowed: bool = False
    score_multiplier: float = 1.0
    quality_floor: int = 30
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "registry_active": self.registry_active,
            "raw_tier": self.raw_tier,
            "effective_tier": self.effective_tier,
            "promotion_tier": self.promotion_tier,
            "operator_core_approved": self.operator_core_approved,
            "maturity_score": self.maturity_score,
            "go_rate": self.go_rate,
            "ingest_allowed": self.ingest_allowed,
            "promotion_allowed": self.promotion_allowed,
            "score_multiplier": self.score_multiplier,
            "quality_floor": self.quality_floor,
            "reason": self.reason,
        }


def invalidate_cache() -> None:
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0


def _parse_notes(notes: str | None) -> dict:
    if not notes or not str(notes).strip().startswith("{"):
        return {}
    try:
        return json.loads(notes)
    except Exception:
        return {}


def _load_maturity_json() -> dict[str, dict]:
    try:
        data = json.loads(MATURITY_JSON.read_text())
        return {str(r["source"]): r for r in data.get("sources", []) if r.get("source")}
    except Exception:
        return {}


def _db_rows() -> list[dict]:
    try:
        import psycopg2.extras
        for ln in (ROOT / ".env").read_text().splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT source_name, source_type, active, credibility_score, notes "
            "FROM research_sources"
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _refresh_cache(force: bool = False) -> dict:
    global _CACHE, _CACHE_AT
    now = time.time()
    if not force and _CACHE is not None and (now - _CACHE_AT) < _CACHE_TTL:
        return _CACHE
    by_name: dict[str, dict] = {}
    connectors: dict[str, bool] = {}
    for r in _db_rows():
        name = str(r.get("source_name") or "")
        st = str(r.get("source_type") or "")
        notes = _parse_notes(r.get("notes"))
        by_name[name] = {
            "source_type": st,
            "active": bool(r.get("active")),
            "credibility": float(r.get("credibility_score") or 0),
            "notes": notes,
            "maturity_tier": notes.get("maturity_tier"),
            "maturity_score": notes.get("maturity_score"),
            "go_rate": notes.get("go_rate"),
            "operator_core_approved": bool(notes.get("operator_core_approved")),
        }
        if st in CONNECTOR_TYPES:
            connectors[st] = bool(r.get("active"))
    _CACHE = {"by_name": by_name, "connectors": connectors, "maturity_json": _load_maturity_json()}
    _CACHE_AT = now
    return _CACHE


def _web_tier_from_row(row: dict) -> str:
    cred = float(row.get("credibility") or 0)
    active = bool(row.get("active"))
    if active and cred >= 30:
        return "trusted"
    if active:
        return "probationary"
    if cred >= 25:
        return "probationary"
    return "candidate"


def _raw_tier(source: str, row: dict | None, mat_json: dict) -> str:
    if row and str(row.get("source_type")) == "web":
        return _web_tier_from_row(row)
    if row and row.get("maturity_tier"):
        return str(row["maturity_tier"])
    mj = mat_json.get(source) or {}
    return str(mj.get("tier") or "candidate")


def _effective_tier(source: str, row: dict | None, mat_json: dict) -> str:
    tier = _raw_tier(source, row, mat_json)
    active = bool(row.get("active")) if row else False
    approved = bool(row.get("operator_core_approved")) if row else False
    if tier == "demoted":
        return "demoted"
    if tier == "core":
        if active or approved:
            return "core"
        return "trusted"
    return tier


def _promotion_tier(effective: str, active: bool, approved: bool) -> str:
    if effective == "demoted":
        return "demoted"
    if effective == "core" and (active or approved):
        return "core"
    if effective in ("core", "trusted"):
        return "trusted" if (active or approved) else "probationary"
    return effective


def _connector_live(source: str, connectors: dict[str, bool]) -> bool:
    ctype = SOURCE_TO_CONNECTOR.get(source)
    if not ctype:
        return True
    if ctype == "seeking_alpha":
        return connectors.get("seeking_alpha", False)
    return connectors.get(ctype, True)


def resolve(source: str | None, *, force_refresh: bool = False) -> SourcePolicy:
    src = str(source or "").strip()
    cache = _refresh_cache(force=force_refresh)
    by_name = cache["by_name"]
    connectors = cache["connectors"]
    mat_json = cache["maturity_json"]

    if not src or src.startswith("topic_"):
        return SourcePolicy(
            source=src or "unknown",
            source_type="topic_channel",
            ingest_allowed=True,
            promotion_tier="probationary",
            effective_tier="probationary",
            score_multiplier=1.0,
            reason="topic_ingest_channel",
        )

    if src in BASE_INGEST_SOURCES:
        live = _connector_live(src, connectors)
        return SourcePolicy(
            source=src,
            source_type="base_feed",
            ingest_allowed=live,
            promotion_tier="trusted" if live else "candidate",
            effective_tier="trusted" if live else "candidate",
            score_multiplier=1.0 if live else 0.9,
            reason="rss_live" if live else "rss_connector_off",
        )

    row = by_name.get(src)
    st = (row or {}).get("source_type")
    raw = _raw_tier(src, row, mat_json)
    effective = _effective_tier(src, row, mat_json)
    active = bool((row or {}).get("active"))
    approved = bool((row or {}).get("operator_core_approved"))
    promo = _promotion_tier(effective, active, approved)
    mult = TIER_SCORE_MULT.get(effective, 0.92)
    qfloor = TIER_QUALITY_BASE.get(effective, 30)

    ingest = True
    reason = "registry_ok"
    if effective == "demoted":
        ingest = False
        reason = "demoted"
    elif st == "web":
        cred = float((row or {}).get("credibility") or 0)
        if not active and cred < 15 and effective == "candidate":
            ingest = False
            reason = "web_low_yield_inactive"
        elif active:
            reason = "web_preferred"
    elif not row:
        mj = mat_json.get(src, {})
        if mj.get("tier") == "demoted":
            ingest = False
            reason = "demoted_json_only"

    conn_live = _connector_live(src, connectors)
    if src in SOURCE_TO_CONNECTOR and not conn_live and st != "news":
        ingest = False
        reason = f"connector_off:{SOURCE_TO_CONNECTOR[src]}"

    promo_ok = promo in ("core", "trusted") and effective != "demoted"

    return SourcePolicy(
        source=src,
        source_type=st,
        registry_active=active,
        raw_tier=raw,
        effective_tier=effective,
        promotion_tier=promo,
        operator_core_approved=approved,
        maturity_score=(row or {}).get("maturity_score"),
        go_rate=(row or {}).get("go_rate"),
        ingest_allowed=ingest,
        promotion_allowed=promo_ok,
        score_multiplier=mult,
        quality_floor=qfloor,
        reason=reason,
    )


def should_ingest(source: str | None) -> tuple[bool, str]:
    pol = resolve(source)
    return pol.ingest_allowed, pol.reason


def get_source_tier(source: str | None, *, for_promotion: bool = True) -> str:
    """Tier for promotion/catalyst weighting. Respects active + operator_core_approved."""
    pol = resolve(source)
    return pol.promotion_tier if for_promotion else pol.effective_tier


def score_multiplier(source: str | None) -> float:
    return resolve(source).score_multiplier


def quality_floor(source: str | None) -> int:
    return resolve(source).quality_floor


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).netloc.replace("www.", "").lower() or None
    except Exception:
        return None


def web_domain_allowed(domain: str | None) -> tuple[bool, str]:
    if not domain:
        return True, "no_domain"
    pol = resolve(domain)
    if pol.effective_tier == "demoted":
        return False, "web_demoted"
    row = _refresh_cache()["by_name"].get(domain)
    if row and pol.source_type == "web" and not pol.registry_active and pol.effective_tier == "candidate":
        if float(row.get("credibility") or 0) < 15:
            return False, "web_candidate_noise"
    return True, pol.reason


def filter_search_results(results: list[dict]) -> list[dict]:
    """Drop SearXNG hits from demoted / noise web domains."""
    out = []
    for r in results or []:
        dom = domain_from_url(r.get("url"))
        ok, _ = web_domain_allowed(dom)
        if ok:
            out.append(r)
    return out


def apply_quality_policy(source: str, base_quality: int) -> int:
    pol = resolve(source)
    adjusted = int(round(base_quality * pol.score_multiplier))
    return min(100, max(pol.quality_floor, adjusted))
"""
directive_promotion.py — Bridge a Hermes/operator watch lead into Trade AI's
evaluation brain. Hermes supplies symbol+thesis; Trade AI decides tradeability;
operator supplies the yes. This is a REAL evaluation, never a bypass.

HARD RULES (prompt Section 0):
  * never Bucket 1 / momentum_scalp / gap_and_go  (scalp fast-path firewall)
  * advisory only; NO execution — promotion only registers + evaluates + watchpools
  * fail-closed: unresolvable symbol -> needs_review, never fabricated data
  * runs under the MAIN APP ROLE (db_adapter._get_conn), NOT a hermes_* role

Matched to real Phase-0 signatures:
  enrich:   finviz_enrichment.enrich_tickers([sym]) -> get_enriched(sym)
  classify: multi_strategy_classifier.classify_symbol(scan, strategies)  (filter output)
  bucket:   strategy yaml cfg['freshness']['bucket']  (momentum_scalp -> SAME_DAY)
  watchpool:mirror strategy_watchpool.maybe_write_watchpool INSERT (+ origin_system, directive_id)
  tier:     data/runtime/source_maturity_latest.json  sources[].tier
  diverge:  data/runtime/pro_analyst_pills_latest.json pills[].divergence
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

EXCLUDED_BUCKETS = ("SAME_DAY",)
EXCLUDED_STRATEGIES = ("momentum_scalp", "gap_and_go")

_TIER_JSON = PROJECT_ROOT / "data" / "runtime" / "source_maturity_latest.json"
_PILLS_JSON = PROJECT_ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"


# ── connection (APP ROLE — the firewall: promotion never runs as a hermes role) ──
def _conn():
    from db_adapter import _get_conn
    return _get_conn()


# ── tier + divergence reads (advisory read-models; fail-closed) ──────────────────
def get_source_tier(source_system, conn=None):
    """research_sources + operator activation -> effective promotion tier.

    Desk sources (cio/advisory/defense) default to trusted so forward curation
    is not stuck at candidate when absent from the Hermes source registry.
    """
    src = str(source_system or "").strip().lower()
    try:
        from lib.two_way_curation import DESK_PROMOTION_TIER
        if src in DESK_PROMOTION_TIER:
            return DESK_PROMOTION_TIER[src]
    except Exception:
        if src in ("cio", "advisory", "defense", "operator", "trade_ai", "hermes"):
            return "trusted" if src != "operator" else "core"
    try:
        from hermes_source_policy import get_source_tier as _policy_tier
        return _policy_tier(source_system, for_promotion=True)
    except Exception:
        pass
    try:
        d = json.loads(_TIER_JSON.read_text())
        for r in d.get("sources", []):
            if str(r.get("source", "")).lower() == src:
                tier = r.get("tier") or "candidate"
                if tier == "core":
                    return "trusted"
                return tier
    except Exception:
        pass
    return "candidate"


def get_divergence_status(symbol, conn=None):
    """Latest pro_analyst_monitor snapshot -> aligned|mixed|divergent|unavailable.
    No Street coverage / no pill -> 'unavailable' (not divergent — see governor)."""
    try:
        d = json.loads(_PILLS_JSON.read_text())
        for p in d.get("pills", []):
            if str(p.get("symbol", "")).upper() == symbol.upper():
                return p.get("divergence") or "unavailable"
    except Exception:
        pass
    return "unavailable"


def get_street_consensus(symbol):
    """Yahoo-authoritative consensus block for the provenance pill (D-3 reuse). None if uncovered."""
    try:
        d = json.loads(_PILLS_JSON.read_text())
        for p in d.get("pills", []):
            if str(p.get("symbol", "")).upper() == symbol.upper() and p.get("has_professional_coverage"):
                return {"recommendation_mean": p.get("recommendation_mean"),
                        "recommendation_key": p.get("recommendation_key"),
                        "target_mean": p.get("target_mean_price"),
                        "count": p.get("number_of_analyst_opinions")}
    except Exception:
        pass
    return None


def auto_promote_allowed(tier, divergence):
    """LOCKED GOVERNOR: auto only when source is trusted AND not fighting the Street.
    'unavailable' coverage MAY auto-promote IF tier core/trusted (absence of coverage is
    not disagreement — it lights an 'uncovered' pill). 'divergent' ALWAYS stages."""
    return (tier in ("core", "trusted")) and (divergence != "divergent")


# ── enrichment (on demand, real technicals — never a screener export) ────────────
def _latest_quote_price(symbol, conn):
    """Latest price from market_quotes (Alpaca-primary feed). The finviz enrichment cache
    carries rsi/float/rvol but NOT current price, so we backfill it here."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT price FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1",
                    (symbol.upper(),))
        row = cur.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def enrich_symbol_on_demand(symbol, conn=None):
    """enrich_tickers([sym]) populates the finviz cache (rsi/float/rvol/atr/...); get_enriched
    reads it back. Price is NOT in that cache, so backfill it from market_quotes (Alpaca feed).
    Returns the enriched dict or {} on failure (fail-closed)."""
    try:
        from finviz_enrichment import enrich_tickers, get_enriched
        try:
            enrich_tickers([symbol], project_root=str(PROJECT_ROOT))
        except Exception:
            pass  # cache may already hold it; get_enriched still tries
        rec = get_enriched(symbol, project_root=str(PROJECT_ROOT)) or {}
        if _tech_price(rec) is None:
            px = _latest_quote_price(symbol, conn or _conn())
            if px is not None:
                rec["price"] = px
        return rec
    except Exception:
        return {}


def _tech_price(tech):
    for k in ("price", "Price", "current_price", "last_price", "latest_price"):
        v = tech.get(k)
        if v not in (None, "", "-"):
            try:
                return float(str(v).replace("$", "").replace(",", ""))
            except Exception:
                continue
    return None


# ── classify (Bucket 2/3 only — scalp excluded HARD) ─────────────────────────────
def _strategy_bucket(cfg):
    return (cfg.get("freshness", {}) or {}).get("bucket") or cfg.get("bucket")


def classify_tradeable(symbol, tech):
    """Run the real classifier, then HARD-EXCLUDE Bucket-1/scalp. Returns
    [(strategy_id, cfg, bucket), ...] for qualifying Bucket 2/3 strategies only."""
    from multi_strategy_classifier import load_all_strategies, classify_symbol
    strategies = load_all_strategies()
    scan = dict(tech); scan["symbol"] = symbol.upper()
    matches = classify_symbol(scan, strategies, enrichment_cache={symbol.upper(): tech})
    out = []
    for m in matches:
        sid = m.get("strategy_id")
        if sid in EXCLUDED_STRATEGIES:
            continue
        cfg = strategies.get(sid, {})
        bucket = _strategy_bucket(cfg)
        if bucket in EXCLUDED_BUCKETS:
            continue
        out.append((sid, cfg, bucket))
    # Firewall assertion — abort rather than leak a scalp into the directive path
    assert all(b not in EXCLUDED_BUCKETS for _, _, b in out), "Bucket-1 leak — abort"
    assert all(s not in EXCLUDED_STRATEGIES for s, _, _ in out), "scalp strategy leak — abort"
    return out


# ── persistence helpers (app role) ───────────────────────────────────────────────
# Helpers NEVER commit. promote_directive_lead owns the single transaction boundary:
# it commits once at the end (or defers to the caller when a shared conn is passed).
# This keeps one promote = one transaction, so concurrent promote load holds row
# locks for the shortest possible window instead of committing ~5x per symbol.
def _upsert_watchlist_master(conn, symbol, origin_system, origin_detail, directive_id,
                             source_tier, provenance_reason):
    """UPSERT curated provenance onto watchlist_items (base table of the master VIEW).
    No unique-constraint dependency: UPDATE then INSERT-if-absent. No commit — caller owns."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE watchlist_items SET
            origin_system = COALESCE(origin_system, %s),
            origin_detail = %s::jsonb,
            -- Operator-intent precedence (fix 2026-06-19): an explicit operator ticker tag (kind='ticker')
            -- owns the item's directive_id and must NOT be clobbered by a later sector/trend auto-claim.
            -- Incoming ticker → always wins; else fill if empty; else keep an existing ticker ownership;
            -- else take the incoming (latest sector/trend wins among non-ticker, prior behavior).
            directive_id = CASE
                WHEN (SELECT kind FROM watch_directives WHERE id = %s) = 'ticker' THEN %s
                WHEN watchlist_items.directive_id IS NULL THEN %s
                WHEN (SELECT kind FROM watch_directives WHERE id = watchlist_items.directive_id) = 'ticker'
                    THEN watchlist_items.directive_id
                ELSE %s
            END,
            in_directive_watch = true,
            -- operator explicitly added this as a directive → un-remove it so it's VISIBLE on the
            -- watchlist (this was the "Maria added it but it's not showing" bug: a previously-removed
            -- symbol got in_directive_watch=true but kept status='removed', which the UI filters out).
            status = CASE WHEN status = 'removed' THEN 'active' ELSE status END,
            source_tier = %s,
            first_seen_at = COALESCE(first_seen_at, NOW()),
            last_validated_at = NOW(),
            seen_count = COALESCE(seen_count, 1) + 1,
            provenance_reason = %s,
            updated_at = NOW()
        WHERE symbol = %s
    """, (origin_system, json.dumps(origin_detail, default=str),
          directive_id, directive_id, directive_id, directive_id,
          source_tier, provenance_reason, symbol))
    if cur.rowcount == 0:
        cur.execute("""
            INSERT INTO watchlist_items
                (symbol, source, status, origin_system, origin_detail, directive_id,
                 in_directive_watch, source_tier, first_seen_at, last_validated_at,
                 seen_count, provenance_reason)
            VALUES (%s, %s, 'active', %s, %s::jsonb, %s, true, %s, NOW(), NOW(), 1, %s)
        """, (symbol, origin_system, origin_system, json.dumps(origin_detail, default=str),
              directive_id, source_tier, provenance_reason))


def _insert_watchpool_row(conn, strategy_id, symbol, snapshot, cfg, origin_system, directive_id):
    """Mirror strategy_watchpool.maybe_write_watchpool EXACTLY, plus origin_system + directive_id.
    Respects is_watchpool_active(cfg) and the ACTIVE-dedup guard. Returns row id or None."""
    from strategy_watchpool import is_watchpool_active
    if not is_watchpool_active(cfg):
        return None
    fresh = cfg.get("freshness", {})
    ttl_days = fresh.get("ttl_days", 10)
    bucket = fresh.get("bucket")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO strategy_watchpool
            (strategy_id, symbol, screener_id, entry_snapshot, expires_at, bucket,
             origin_system, directive_id)
        SELECT %s, %s, %s, %s::jsonb, NOW() + (%s || ' days')::interval, %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM strategy_watchpool
            WHERE strategy_id = %s AND symbol = %s AND current_status = 'ACTIVE'
        )
        RETURNING id;
    """, (strategy_id, symbol, "hermes_directive", json.dumps(snapshot, default=str),
          str(ttl_days), bucket, origin_system, directive_id, strategy_id, symbol))
    row = cur.fetchone()
    return row[0] if row else None


# Honest desk provenance (migration 2026-08-13_two_way_curation_p0_surfaced_by).
_SURFACED_BY_ALLOWED = frozenset({
    "trade_ai", "hermes", "operator", "cio", "advisory", "defense",
    "rotation", "reentry",
})


def _normalize_surfaced_by(surfaced_by: str | None) -> str:
    s = str(surfaced_by or "").strip().lower()
    return s if s in _SURFACED_BY_ALLOWED else "hermes"


def _record_hit(conn, directive_id, symbol, surfaced_by, tier, reason, divergence,
                promoted, promotion_status, qualified_strategies=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO watch_directive_hits
            (directive_id, symbol, surfaced_by, source_tier, hit_reason, divergence,
             promoted, promotion_status, qualified_strategies, promoted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END)
        ON CONFLICT (directive_id, symbol, surfaced_at) DO NOTHING
    """, (directive_id, symbol, _normalize_surfaced_by(surfaced_by),
          tier, reason, divergence, promoted, promotion_status,
          qualified_strategies or None, promoted))


def _mark_needs_review(conn, symbol, directive_id, why):
    cur = conn.cursor()
    cur.execute("UPDATE watchlist_items SET provenance_reason = COALESCE(provenance_reason,'')||%s WHERE symbol=%s",
                (f" [needs_review:{why}]", symbol))


def _touch_directive_serviced(conn, directive_id):
    cur = conn.cursor()
    cur.execute("UPDATE watch_directives SET last_serviced_at=NOW(), updated_at=NOW() WHERE id=%s",
                (directive_id,))


# ── the centerpiece ──────────────────────────────────────────────────────────────
def promote_directive_lead(symbol, directive_id, reason, source_system, conn=None,
                           *, auto=None, actor="system", commit=None):
    """
    Returns dict: status, registered, evaluated, qualified_strategies, watchpool_rows,
    tier, divergence.  status ∈ {PROMOTED, MONITORED_NO_QUALIFY, REGISTERED_NO_TECH,
    STAGED_FOR_REVIEW}.

    Transaction boundary: the whole promote is ONE transaction (commit at the end,
    rollback on error). ``commit`` (None → auto) means: commit once at the end when this
    function owns its connection (`conn is None`); DEFER to the caller when a shared
    `conn` is passed (the caller commits the batch once). This collapses the previous
    ~5 commits-per-symbol into one, which is the lock-hold window that caused row-lock
    contention under full promote load.
    """
    own = conn is None
    conn = conn or _conn()
    should_commit = own if commit is None else commit
    symbol = symbol.upper().strip()
    tier = get_source_tier(source_system, conn)
    divergence = get_divergence_status(symbol, conn)
    if auto is None:
        auto = auto_promote_allowed(tier, divergence)

    try:
        # Governor: non-core/trusted OR fighting the Street -> stage, do not register/evaluate.
        # (Operator one-tap passes auto=True, overriding the governor — but the scalp firewall
        #  and fail-closed checks below still apply.)
        if not auto:
            _record_hit(conn, directive_id, symbol, surfaced_by=source_system, tier=tier,
                        reason=reason, divergence=divergence, promoted=False,
                        promotion_status="STAGED_FOR_REVIEW")
            if should_commit:
                conn.commit()
            return {"status": "STAGED_FOR_REVIEW", "tier": tier, "divergence": divergence,
                    "registered": False, "evaluated": False, "actor": actor}

        # 1. Register provenance on the curated master (base table).
        _upsert_watchlist_master(conn, symbol, origin_system=source_system,
                                 origin_detail={"directive_id": directive_id, "thesis": reason},
                                 directive_id=directive_id, source_tier=tier,
                                 provenance_reason=reason)

        # 2. Inject as candidate: fetch technicals ON DEMAND (not a screener export).
        tech = enrich_symbol_on_demand(symbol, conn=conn)
        if not tech or _tech_price(tech) is None:
            # fail-closed: keep monitored, flag, no fabricated data, NO proposal.
            _record_hit(conn, directive_id, symbol, surfaced_by=source_system, tier=tier,
                        reason=reason, divergence=divergence, promoted=True,
                        promotion_status="REGISTERED_NO_TECH")
            _mark_needs_review(conn, symbol, directive_id, "enrichment_unavailable")
            if should_commit:
                conn.commit()
            return {"status": "REGISTERED_NO_TECH", "registered": True, "evaluated": False,
                    "tier": tier, "divergence": divergence, "actor": actor}

        # 3. Real strategy classifier — Bucket 2/3 only, scalp excluded HARD.
        qualified = classify_tradeable(symbol, tech)

        # 4. Qualifying names enter the watchpool exactly like a screener candidate.
        rows = []
        for sid, cfg, _bucket in qualified:
            rid = _insert_watchpool_row(conn, sid, symbol, tech, cfg,
                                        origin_system=source_system, directive_id=directive_id)
            if rid:
                rows.append(rid)

        status = "PROMOTED" if rows else "MONITORED_NO_QUALIFY"
        _record_hit(conn, directive_id, symbol, surfaced_by=source_system, tier=tier,
                    reason=reason, divergence=divergence, promoted=True,
                    promotion_status=status, qualified_strategies=[s for s, _, _ in qualified])
        _touch_directive_serviced(conn, directive_id)
        if should_commit:
            conn.commit()
        return {"status": status, "registered": True, "evaluated": True,
                "qualified_strategies": [s for s, _, _ in qualified],
                "watchpool_rows": rows, "tier": tier, "divergence": divergence, "actor": actor}
    except Exception:
        if should_commit:
            conn.rollback()
        raise


if __name__ == "__main__":
    # Smoke: tier + divergence + governor only (no writes).
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="RKLB")
    ap.add_argument("--source", default="hermes")
    a = ap.parse_args()
    t = get_source_tier(a.source); dv = get_divergence_status(a.symbol)
    print(json.dumps({"symbol": a.symbol, "source": a.source, "tier": t,
                      "divergence": dv, "auto_promote": auto_promote_allowed(t, dv)}, indent=2))

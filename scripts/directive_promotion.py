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
import os
import sys
import threading
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


#: Session guards for a connection promote_directive_lead OWNS (M5 2026-09-24).
#: watch_directives_service promotes held watchlist_items row locks "idle in
#: transaction" for ~1 min while the Finviz enrichment ran inside the open
#: transaction; that blocked the 1c migration and the GUID backfill 11 times.
#: The network fetch now runs outside any transaction, and these caps make a
#: regression fail fast instead of blocking every other writer.
DEFAULT_PROMOTE_LOCK_TIMEOUT_MS = 5000
DEFAULT_PROMOTE_IDLE_TXN_TIMEOUT_MS = 10000


def _env_ms(name, default):
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _apply_session_guards(conn):
    """lock_timeout + idle_in_transaction_session_timeout on an owned connection.

    Best-effort: a connection that cannot take SET (fake cursors in tests, an
    adapter without cursor()) is left as-is. Ends with commit so the SETs do not
    themselves leave a transaction open.
    """
    lock_ms = _env_ms("PROMOTE_LOCK_TIMEOUT_MS", DEFAULT_PROMOTE_LOCK_TIMEOUT_MS)
    idle_ms = _env_ms("PROMOTE_IDLE_TXN_TIMEOUT_MS", DEFAULT_PROMOTE_IDLE_TXN_TIMEOUT_MS)
    try:
        cur = conn.cursor()
        cur.execute("SELECT set_config('lock_timeout', %s, false)", (f"{lock_ms}ms",))
        cur.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, false)",
                    (f"{idle_ms}ms",))
        conn.commit()
    except Exception:
        pass


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
#: Price backfill window for the market_quote projection read (matches the old unbounded
#: "newest row" read closely enough: a 30-day-old price is still shown with its as_of).
QUOTE_BACKFILL_MAX_AGE_HOURS = 24 * 30


def _conn_db_query(conn):
    """Adapt a DB-API connection to the broker projections' ``db_query(sql, params, fetch)``."""
    def _q(sql, params=None, fetch="all"):
        cur = conn.cursor()
        cur.execute(sql, params or ())
        cols = [d[0] for d in (cur.description or [])]
        if fetch == "one":
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row) if hasattr(row, "keys") else dict(zip(cols, row))
        rows = cur.fetchall() or []
        return [dict(r) if hasattr(r, "keys") else dict(zip(cols, r)) for r in rows]
    return _q


def _latest_quote_price(symbol, conn):
    """Latest price through the Data Broker ``market_quote`` projection (store market_quotes,
    Alpaca-primary). The finviz enrichment cache carries rsi/float/rvol but not always a current
    price, so we backfill it here. ``skip_live=True``: this read never reaches a provider."""
    try:
        from lib.data_broker.market_quote import get_price_batch
        sym = symbol.upper()
        q = get_price_batch(_conn_db_query(conn), [sym],
                            max_age_hours=QUOTE_BACKFILL_MAX_AGE_HOURS, skip_live=True).get(sym)
        return float(q["price"]) if q and q.get("price") is not None else None
    except Exception:
        return None


#: Kill switch for the batched enrichment read (consolidation step 1). "0" restores the old
#: per-symbol fetch path exactly.
ENRICH_VIA_BROKER_ENV = "DIRECTIVE_ENRICH_VIA_BROKER"


def _broker_enabled():
    return os.environ.get(ENRICH_VIA_BROKER_ENV, "1").strip().lower() not in ("0", "false", "no")


def _fresh_enrichment_via_broker(symbol):
    """The symbol's enrichment record from the Data Broker projection when it is fresh, else None.

    Fresh = younger than the owner's own refresh window (finviz_enrichment.CACHE_TTL_HOURS), so a
    record served here is one ``enrich_tickers`` would not have refetched either.
    """
    try:
        from finviz_enrichment import CACHE_TTL_HOURS
        from lib.data_broker.finviz_enrichment_snapshot import get_enrichment
        row = get_enrichment(symbol, max_age_hours=float(CACHE_TTL_HOURS), root=PROJECT_ROOT)
        if row.get("stale") or not row.get("record"):
            return None
        return dict(row["record"])
    except Exception:
        return None


def would_enrich(symbol, source_system, auto=None, *, divergence_index=None):
    """True when promote_directive_lead would reach the enrichment step for this lead.

    Mirrors the governor at the top of promote_directive_lead: an explicit ``auto`` wins;
    otherwise auto_promote_allowed(tier, divergence). Reads only (tier policy, pills JSON).
    ``divergence_index`` ({SYMBOL: divergence}) lets a batch caller parse the pills file once.
    """
    if auto is not None:
        return bool(auto)
    sym = str(symbol or "").upper().strip()
    tier = get_source_tier(source_system)
    if divergence_index is not None:
        divergence = divergence_index.get(sym) or "unavailable"
    else:
        divergence = get_divergence_status(sym)
    return bool(auto_promote_allowed(tier, divergence))


def divergence_index():
    """{SYMBOL: divergence} from the pills snapshot, parsed once ({} when unreadable)."""
    try:
        d = json.loads(_PILLS_JSON.read_text())
    except Exception:
        return {}
    out = {}
    for p in d.get("pills", []) or []:
        sym = str(p.get("symbol", "")).upper()
        if sym and sym not in out:
            out[sym] = p.get("divergence") or "unavailable"
    return out


def prefetch_enrichment(symbols, *, dry_run=False):
    """Ask the enrichment owner to refresh a whole batch at once (consolidation step 1).

    One ``enrich_tickers(symbols)`` call fetches only the stale/missing symbols, 20 per Finviz
    export request per view, instead of one request per symbol per view. Measured before
    (watch_directives_service.log, 2026-10-09): 1,775-2,450 single-ticker fetches per run, six
    views each. ``dry_run`` reads the broker projection only and returns the plan: no Finviz
    request, no cache write.
    """
    from lib.data_broker.finviz_enrichment_snapshot import get_enrichment_batch
    syms = []
    seen = set()
    for s in symbols or []:
        u = str(s or "").upper().strip()
        if u and u not in seen:
            seen.add(u)
            syms.append(u)
    try:
        from finviz_enrichment import BATCH_SIZE, CACHE_TTL_HOURS, _default_views
        views = len(_default_views())
    except Exception:
        BATCH_SIZE, CACHE_TTL_HOURS, views = 20, 6, 6
    snap = get_enrichment_batch(syms, max_age_hours=float(CACHE_TTL_HOURS), root=PROJECT_ROOT)
    stale = snap["stale_or_missing"]
    batches = -(-len(stale) // int(BATCH_SIZE)) if stale else 0
    plan = {
        "symbols": len(syms),
        "fresh_in_broker": len(snap["fresh"]),
        "stale_or_missing": len(stale),
        "finviz_requests_batched": batches * views,
        "finviz_requests_per_symbol_path": len(stale) * views,
        "broker_as_of": snap.get("as_of"),
        "dry_run": bool(dry_run),
        "fetched": False,
    }
    if dry_run or not stale:
        return plan
    try:
        from finviz_enrichment import enrich_tickers
        enrich_tickers(stale, project_root=str(PROJECT_ROOT))
        plan["fetched"] = True
    except Exception as e:  # the per-symbol path stays the fallback
        plan["error"] = str(e)[:200]
    return plan


def enrich_symbol_on_demand(symbol, conn=None):
    """Enrichment for one symbol, read through the Data Broker first.

    1. ``finviz_enrichment_snapshot`` projection: a fresh record is used as-is (no Finviz call).
    2. Otherwise the owner refreshes it (``enrich_tickers([sym])``, unchanged legacy path) and
       ``get_enriched`` reads it back.
    Price is not always in that cache, so it is backfilled from the market_quote projection.
    Returns the enriched dict or {} on failure (fail-closed)."""
    try:
        rec = _fresh_enrichment_via_broker(symbol) if _broker_enabled() else None
        if rec is None:
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
#: watch_directives.created_by values that mean "the operator made this directive". Only these set
#: watchlist_items.in_directive_watch (operator-approved 2026-10-22: "Yes, I agree with your recommendations.").
#: Automated producers (think_tank, sector_universe, advisory, rotation_advisor, reentry, defense,
#: claude_challenger, cio) keep their membership in their own records (watch_directive_hits, directive_id,
#: origin_system) but do not set the flag. Mirrors lib.data_broker.watch_intelligence.OPERATOR_DIRECTIVE_CREATORS.
OPERATOR_DIRECTIVE_CREATORS = ("operator", "operator_audit")

#: TRUE when directive %s is ACTIVE and operator-created. Two params: (directive_id, list(creators)).
_OPERATOR_DIRECTIVE_SQL = ("EXISTS (SELECT 1 FROM watch_directives wd_op WHERE wd_op.id = %s "
                           "AND wd_op.status = 'active' AND wd_op.created_by = ANY(%s))")


def _upsert_watchlist_master(conn, symbol, origin_system, origin_detail, directive_id,
                             source_tier, provenance_reason):
    """UPSERT curated provenance onto watchlist_items (base table of the master VIEW).
    No unique-constraint dependency: UPDATE then INSERT-if-absent. No commit — caller owns.

    The flag (2026-10-22, operator-approved): ``in_directive_watch`` is set only when the directive is an ACTIVE
    operator-created one, and only such a directive un-removes a row the operator removed. An automated directive
    still records its provenance (origin_detail, directive_id, source_tier) but never sets the flag, never
    resurrects a removed row, and a row it inserts lands as 'researched', not 'active'. Nothing here clears the
    flag; ``reconcile_directive_watch_flag`` does, with a backup."""
    cur = conn.cursor()
    creators = list(OPERATOR_DIRECTIVE_CREATORS)
    cur.execute(f"""
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
            -- only an ACTIVE operator-created directive sets the flag (2026-10-22); an existing flag is kept
            -- here and cleared only by reconcile_directive_watch_flag.
            in_directive_watch = (COALESCE(in_directive_watch, false) OR {_OPERATOR_DIRECTIVE_SQL}),
            -- operator explicitly added this as a directive → un-remove it so it's VISIBLE on the
            -- watchlist (this was the "Maria added it but it's not showing" bug: a previously-removed
            -- symbol got in_directive_watch=true but kept status='removed', which the UI filters out).
            -- An automated directive never un-removes what the operator removed.
            status = CASE WHEN status = 'removed' AND {_OPERATOR_DIRECTIVE_SQL} THEN 'active' ELSE status END,
            source_tier = %s,
            first_seen_at = COALESCE(first_seen_at, NOW()),
            last_validated_at = NOW(),
            seen_count = COALESCE(seen_count, 1) + 1,
            provenance_reason = %s,
            updated_at = NOW()
        WHERE symbol = %s
    """, (origin_system, json.dumps(origin_detail, default=str),
          directive_id, directive_id, directive_id, directive_id,
          directive_id, creators, directive_id, creators,
          source_tier, provenance_reason, symbol))
    if cur.rowcount == 0:
        cur.execute(f"""
            INSERT INTO watchlist_items
                (symbol, source, status, origin_system, origin_detail, directive_id,
                 in_directive_watch, source_tier, first_seen_at, last_validated_at,
                 seen_count, provenance_reason)
            SELECT %s, %s, CASE WHEN op.flag THEN 'active' ELSE 'researched' END, %s, %s::jsonb, %s,
                   op.flag, %s, NOW(), NOW(), 1, %s
              FROM (SELECT {_OPERATOR_DIRECTIVE_SQL} AS flag) op
        """, (symbol, origin_system, origin_system, json.dumps(origin_detail, default=str),
              directive_id, source_tier, provenance_reason, directive_id, creators))


# ── in_directive_watch reconciler (operator-approved 2026-10-22) ────────────────────────────────────────────────
# The flag means "an ACTIVE operator-created directive matches this symbol". Before 2026-10-22 every directive set it
# (automated think_tank / sector_universe trend + sector directives ≈1,729 symbols) and nothing cleared it (273
# symbols from expired/archived directives), so 2,310 symbols carried it and every consumer (news_ingestion,
# hermes_top20_external_intel, pro_analyst_fetch, build_pro_analyst_read_model, external_market_data_ingest, the
# enrichment audit) treated them as operator standing instructions. This module is the flag's only writer, so the
# clearing lives here too: one writer per store (AGENTS.md §7A rule 1). It never deletes a row (§0 rule 6) and
# records every before-value in a backup before it writes (§0 rule 7: the CLI's dry run comes first).

#: A flagged row KEEPS the flag when an ACTIVE operator-created directive matches it by any of:
#:   1. ownership — watchlist_items.directive_id is that directive;
#:   2. a ticker directive whose spec symbol is this symbol;
#:   3. a promoted watch_directive_hits row of that directive (promotion is what set the flag; ownership can move to a
#:      later automated directive through the directive_id CASE above, the match does not).
#: Named params: %(creators)s.
FLAG_KEEP_SQL = """(
       wi.directive_id IN (SELECT wd_k.id FROM watch_directives wd_k
                            WHERE wd_k.status = 'active' AND wd_k.created_by = ANY(%(creators)s))
    OR UPPER(wi.symbol) IN (SELECT UPPER(TRIM(wd_t.spec->>'symbol')) FROM watch_directives wd_t
                             WHERE wd_t.kind = 'ticker' AND wd_t.status = 'active'
                               AND wd_t.created_by = ANY(%(creators)s)
                               AND COALESCE(TRIM(wd_t.spec->>'symbol'), '') <> '')
    OR UPPER(wi.symbol) IN (SELECT UPPER(h_k.symbol) FROM watch_directive_hits h_k
                              JOIN watch_directives wd_h ON wd_h.id = h_k.directive_id
                             WHERE h_k.promoted AND wd_h.status = 'active'
                               AND wd_h.created_by = ANY(%(creators)s))
)"""

FLAG_BACKUP_SCHEMA = "DirectiveWatchFlagBackup@v1"


def _rowdict(cur, row):
    if isinstance(row, dict):
        return dict(row)
    cols = [d[0] for d in (cur.description or [])]
    return dict(zip(cols, row))


def plan_directive_watch_flag_reconcile(cur, *, sample=20):
    """Read-only plan: counts before/after and every row whose flag would be cleared.

    Returns {before: {rows, symbols}, after: {rows, symbols}, clear_rows, clear_symbols, clear: [rows],
    by_directive: [{created_by, directive_status, rows}], sample: [...]}. ``symbols`` counts exactly what
    watch_universe.directive_symbols() returns (flag true, status <> 'removed', symbol not null).
    """
    p = {"creators": list(OPERATOR_DIRECTIVE_CREATORS)}
    cur.execute(f"""
        SELECT count(*) AS rows,
               count(DISTINCT wi.symbol) FILTER (WHERE wi.status <> 'removed' AND wi.symbol IS NOT NULL) AS symbols,
               count(*) FILTER (WHERE {FLAG_KEEP_SQL}) AS keep_rows,
               count(DISTINCT wi.symbol) FILTER (WHERE wi.status <> 'removed' AND wi.symbol IS NOT NULL
                                                 AND {FLAG_KEEP_SQL}) AS keep_symbols
          FROM watchlist_items wi
         WHERE wi.in_directive_watch = true
    """, p)
    c = _rowdict(cur, cur.fetchone() or (0, 0, 0, 0))
    cur.execute(f"""
        SELECT wi.id, wi.symbol, wi.status, wi.source, wi.directive_id,
               wd.created_by AS directive_created_by, wd.status AS directive_status, wd.kind AS directive_kind
          FROM watchlist_items wi
          LEFT JOIN watch_directives wd ON wd.id = wi.directive_id
         WHERE wi.in_directive_watch = true AND NOT {FLAG_KEEP_SQL}
         ORDER BY wi.symbol, wi.id
    """, p)
    clear = [_rowdict(cur, r) for r in cur.fetchall()]
    by: dict = {}
    for r in clear:
        k = (r.get("directive_created_by") or "(no directive)", r.get("directive_status") or "-")
        by[k] = by.get(k, 0) + 1
    clear_syms = {r["symbol"] for r in clear if r.get("symbol")}
    return {
        "before": {"rows": int(c.get("rows") or 0), "symbols": int(c.get("symbols") or 0)},
        "after": {"rows": int(c.get("keep_rows") or 0), "symbols": int(c.get("keep_symbols") or 0)},
        "clear_rows": len(clear), "clear_symbols": len(clear_syms), "clear": clear,
        "by_directive": [{"created_by": k[0], "directive_status": k[1], "rows": n}
                         for k, n in sorted(by.items(), key=lambda kv: -kv[1])],
        "sample": [{k: r.get(k) for k in ("symbol", "status", "directive_id", "directive_created_by",
                                          "directive_status")} for r in clear[:sample]],
        "creators": list(OPERATOR_DIRECTIVE_CREATORS),
    }


def _write_flag_backup(backup_path, rows, *, reason):
    """Append the before-values, one JSON line per row, and fsync — BEFORE any write (never a delete)."""
    from datetime import datetime, timezone
    backup_path = Path(backup_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc).isoformat()
    with open(backup_path, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({"schema": FLAG_BACKUP_SCHEMA, "at": at, "reason": reason, "id": r.get("id"),
                                 "symbol": r.get("symbol"), "status": r.get("status"),
                                 "directive_id": r.get("directive_id"),
                                 "directive_created_by": r.get("directive_created_by"),
                                 "directive_status": r.get("directive_status"),
                                 "in_directive_watch_before": True}, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return str(backup_path)


def apply_directive_watch_flag_reconcile(conn, plan, *, backup_path, max_clear=None, reason="reconcile"):
    """Clear the flag on the plan's rows: backup first, then one UPDATE that re-checks the keep rule at write time.

    ``max_clear`` bounds one call (the servicer's incremental pass). Never deletes a row; never touches any other
    column but ``updated_at``. Commits. Returns {cleared, attempted, backup}."""
    rows = list(plan.get("clear") or [])
    if max_clear is not None:
        rows = rows[:max(0, int(max_clear))]
    if not rows:
        return {"cleared": 0, "attempted": 0, "backup": None}
    backup = _write_flag_backup(backup_path, rows, reason=reason)
    cur = conn.cursor()
    cur.execute(f"""
        UPDATE watchlist_items wi SET in_directive_watch = false, updated_at = NOW()
         WHERE wi.id = ANY(%(ids)s) AND wi.in_directive_watch = true AND NOT {FLAG_KEEP_SQL}
    """, {"ids": [r["id"] for r in rows], "creators": list(OPERATOR_DIRECTIVE_CREATORS)})
    cleared = cur.rowcount
    conn.commit()
    return {"cleared": int(cleared if cleared is not None and cleared >= 0 else 0), "attempted": len(rows),
            "backup": backup}


def restore_directive_watch_flag(conn, backup_path, *, dry_run=True):
    """Rollback: set the flag back on every row id in a backup file (only rows still false). Commits unless dry."""
    ids = []
    with open(backup_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("schema") == FLAG_BACKUP_SCHEMA and d.get("in_directive_watch_before") and d.get("id") is not None:
                ids.append(int(d["id"]))
    ids = sorted(set(ids))
    if dry_run or not ids:
        return {"restore_ids": len(ids), "restored": 0, "dry_run": dry_run}
    cur = conn.cursor()
    cur.execute("""UPDATE watchlist_items SET in_directive_watch = true, updated_at = NOW()
                    WHERE id = ANY(%s) AND in_directive_watch = false""", (ids,))
    restored = cur.rowcount
    conn.commit()
    return {"restore_ids": len(ids), "restored": int(restored or 0), "dry_run": False}


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
    from lib.writers.watch_directives_writer import touch_watch_directive_serviced
    touch_watch_directive_serviced(conn.cursor(), directive_id, source="directive_promotion")


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
    if own:
        _apply_session_guards(conn)
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

        # 1. Fetch technicals ON DEMAND (not a screener export) BEFORE any write.
        #    The Finviz fetch is network I/O (several views per symbol); it used to run
        #    after the watchlist_items UPDATE below, so the row lock sat "idle in
        #    transaction" for up to a minute (M5 2026-09-24). Only reads have happened so
        #    far; when this function owns the connection, end that read transaction too,
        #    so nothing is held across the fetch. A caller-owned connection keeps its
        #    transaction boundary (the caller decides).
        if own:
            conn.rollback()
        tech = enrich_symbol_on_demand(symbol, conn=conn)

        # 2. Register provenance on the curated master (base table). Same write as before.
        _upsert_watchlist_master(conn, symbol, origin_system=source_system,
                                 origin_detail={"directive_id": directive_id, "thesis": reason},
                                 directive_id=directive_id, source_tier=tier,
                                 provenance_reason=reason)

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


#: OpenClaw's watchlist client gives up at 45s. Finviz enrichment inside
#: promote can sit on the shared throttle for minutes, so the directive row
#: exists while the client reports a timeout. Return inside this budget and
#: let the promote finish; the servicer cron is the same safety net.
DEFAULT_CREATE_PROMOTE_BUDGET_S = 20.0
_promote_inflight_lock = threading.Lock()
_promote_inflight: set[tuple] = set()


def _create_promote_budget_s(budget_s):
    if budget_s is not None:
        try:
            return max(0.0, float(budget_s))
        except (TypeError, ValueError):
            return DEFAULT_CREATE_PROMOTE_BUDGET_S
    raw = os.environ.get("DIRECTIVE_CREATE_PROMOTE_BUDGET_S", "")
    try:
        return max(0.0, float(raw)) if str(raw).strip() else DEFAULT_CREATE_PROMOTE_BUDGET_S
    except ValueError:
        return DEFAULT_CREATE_PROMOTE_BUDGET_S


def promote_directive_lead_bounded(symbol, directive_id, reason, source_system, *,
                                   budget_s=None, auto=True, actor="operator"):
    """promote_directive_lead, but the caller gets a result inside budget_s.

    A slow enrich keeps running. The directive row belongs to the caller and
    is not removed here. A second call for the same directive while the first
    is still running returns DEFERRED_TO_CRON without starting another enrich.
    """
    budget = _create_promote_budget_s(budget_s)
    key = (str(directive_id), str(symbol or "").upper())
    with _promote_inflight_lock:
        if key in _promote_inflight:
            return {
                "status": "DEFERRED_TO_CRON",
                "registered": False,
                "evaluated": False,
                "detail": "promote already running",
                "deferred": True,
            }
        _promote_inflight.add(key)

    box: dict = {}

    def _run():
        try:
            box["res"] = promote_directive_lead(
                symbol, directive_id, reason, source_system, auto=auto, actor=actor,
            )
        except Exception as exc:
            box["err"] = exc
        finally:
            with _promote_inflight_lock:
                _promote_inflight.discard(key)

    thread = threading.Thread(target=_run, name=f"promote-{directive_id}", daemon=True)
    thread.start()
    thread.join(budget)
    if thread.is_alive():
        return {
            "status": "DEFERRED_TO_CRON",
            "registered": False,
            "evaluated": False,
            "detail": "enrichment still running; directive kept for the servicer",
            "deferred": True,
        }
    if "err" in box:
        raise box["err"]
    return box.get("res") or {}


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

"""two_way_curation.py — the two-way watchlist curation loop.

Makes the watch list a closed, self-reinforcing system instead of a one-way feed.

FORWARD direction (sources -> watchlist) — the "curate in" edge:
  * CIO situations (S4_SECTOR_ROTATION, S5_CASH_DEPLOYMENT, S8_DEFENSIVE_REGIME)
  * Advisory desk verdicts (ADD / TRIM / EXIT / RE_ENTER with symbol-specific evidence)
  * Defense desk recommendation cards (get_into / short_side / income)
  each emit "curation feedback" into a per-source staging table (the same firewall
  pattern as hermes_directive_hits_staging). watch_directives_service.py drains every
  source through the one promote_directive_lead() evaluation brain — no source bypasses
  the governor, the scalp firewall, or the fail-closed enrichment checks.

REVERSE direction (outcomes -> watchlist) — the "learn back" edge:
  * realized trade/paper outcomes write back realized_outcome + thesis_win onto the
    underlying symbol's watchlist_items row
  * options paper outcomes fold an options_edge score (IV rank + prime-rubric edge)
    back onto the UNDERLYING symbol's watchlist_items conviction
  * Hermes research intelligence folds a hermes_research score back into the scorer

SAFETY INVARIANTS (mirror the existing firewall):
  * every write path takes an injectable `executor` so each edge is dry-testable in
    memory with no live database / broker / LLM
  * nothing here enables execution, touches broker/order/2FA, or flips strategy status
  * sources only ever write staging; the app role drains and evaluates (least privilege)
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

# Executor signature matches db_adapter._execute(sql, params=None, fetch=None)
Executor = Callable[..., Any]

# ── source / table taxonomy (single source of truth) ──────────────────────────
SOURCES = ("cio", "advisory", "defense")
STAGING_TABLE = {
    "cio": "cio_directive_hits_staging",
    "advisory": "advisory_directive_hits_staging",
    "defense": "defense_directive_hits_staging",
}
# Honest desk provenance (CHECK expanded in 2026-08-13_two_way_curation_p0_surfaced_by)
SURFACED_BY = {"cio": "cio", "advisory": "advisory", "defense": "defense"}
# Desk-minted directives get a default TTL so auto-minted volume is bounded.
DESK_DIRECTIVE_TTL_DAYS = 14
# Cap per-source drain rows per service pass (cost control; rest wait next cycle).
DEFAULT_DRAIN_LIMIT = 25
# Desk sources are trusted for promotion policy when not in research_sources registry.
DESK_PROMOTION_TIER = {
    "cio": "trusted",
    "advisory": "trusted",
    "defense": "trusted",
    "operator": "core",
    "trade_ai": "trusted",
    "hermes": "trusted",
}

# Advisory verdicts that justify a watchlist curation signal (the S3 taxonomy).
ACTIONABLE_ADVISORY_VERDICTS = ("ADD", "TRIM", "EXIT", "RE_ENTER")

# Defense recommendation groups that prescribe a rotate-in / hedge / income stance.
DEFENSE_ROTATE_GROUPS = ("get_into", "income", "short_side")

# CIO situation types that carry a portfolio-level stance worth curating for.
CIO_CURATION_SITUATIONS = ("S4_SECTOR_ROTATION", "S5_CASH_DEPLOYMENT", "S8_DEFENSIVE_REGIME")


# ─────────────────────────────────────────────────────────────────────────────
# Pure mapping — forward edge (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def cio_situation_to_feedback(situation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map one CIO situation to zero-or-more curation feedback records.

    Returns a list so a single situation can seed multiple watchlist edges
    (e.g. defensive regime -> rotate to defensive sectors AND watch income ETFs).
    Each record is a plain dict the emit path serializes; nothing here resolves
    symbols — the drain's directive resolution does that under the app role.
    """
    stype = str(situation.get("situation_type") or situation.get("type") or "")
    if stype not in CIO_CURATION_SITUATIONS:
        return []
    symbols = [str(s).upper() for s in (situation.get("symbols") or []) if s]
    feedback: List[Dict[str, Any]] = []
    rationale = str(situation.get("rationale") or situation.get("summary") or "")[:300]

    if stype == "S8_DEFENSIVE_REGIME":
        # risk-off: curate defensive/quality sectors + income ETFs for the watchlist
        feedback.append({
            "directive_kind": "sector",
            "directive_label": "CIO defensive regime — rotate to defensive",
            "spec": {"gics_sector": "Consumer Defensive",
                     "finviz_sector": "Consumer Defensive",
                     "etf": "XLP"},
            "rationale": rationale or "S8 defensive regime: curate defensive sectors",
            "thesis": "CIO defensive regime: curate low-beta/defensive instruments",
        })
        feedback.append({
            "directive_kind": "trend",
            "directive_label": "CIO defensive regime — income queue",
            "spec": {"keywords": ["defensive", "low volatility", "income"],
                     "seed_symbols": symbols or ["SCHD", "XLU", "XLV"]},
            "rationale": rationale or "S8 defensive regime: income/defensive queue",
            "thesis": "CIO defensive regime: curate income/defensive trend",
        })
    elif stype == "S4_SECTOR_ROTATION":
        sectors = situation.get("sectors") or situation.get("rotation_targets") or []
        if sectors:
            for sec in sectors[:3]:
                feedback.append({
                    "directive_kind": "sector",
                    "directive_label": f"CIO sector rotation — {sec}",
                    "spec": {"gics_sector": str(sec), "finviz_sector": str(sec)},
                    "rationale": rationale or f"S4 rotation target: {sec}",
                    "thesis": f"CIO rotation: overweight {sec}",
                })
        elif symbols:
            feedback.append({
                "directive_kind": "trend",
                "directive_label": "CIO sector rotation — rotate-in names",
                "spec": {"keywords": ["rotation", "rotate in"],
                         "seed_symbols": symbols[:10]},
                "rationale": rationale or "S4 rotation: curate rotate-in names",
                "thesis": "CIO rotation: curate rotate-in names",
            })
    else:  # S5_CASH_DEPLOYMENT
        seeds = situation.get("seed_symbols") or situation.get("candidates") or symbols
        feedback.append({
            "directive_kind": "trend",
            "directive_label": "CIO cash deployment — deploy queue",
            "spec": {"keywords": ["cash deployment", "deploy"],
                     "seed_symbols": [str(s).upper() for s in seeds][:10]},
            "rationale": rationale or "S5 cash deployment: curate deploy candidates",
            "thesis": "CIO cash deployment: curate deployable names",
        })
    return feedback


def advisory_verdict_to_feedback(
    verdict: str,
    symbol: str,
    *,
    row_class: str = "holding",
    conviction: Optional[float] = None,
    rationale: str = "",
    evidence_count: int = 0,
) -> Optional[Dict[str, Any]]:
    """Map an advisory desk verdict to curation feedback, or None to skip.

    Only actionable verdicts with symbol-specific evidence curate the watchlist —
    a WAIT / HOLD / INSUFFICIENT_DATA on a thin bundle must not mint a lead.
    """
    v = str(verdict or "").upper()
    sym = str(symbol or "").upper().strip()
    if not sym or v not in ACTIONABLE_ADVISORY_VERDICTS:
        return None
    if row_class == "allocation":
        return None  # allocation drift is portfolio rebalancing, never a watchlist lead
    # A2 gate: prefer symbol-specific evidence, but allow high-conviction ADD/RE_ENTER
    # with 2+ items so the two-way loop is not starved on thin-but-actionable bundles.
    min_ev = 2 if v in ("ADD", "RE_ENTER") else 3
    if evidence_count < min_ev:
        return None
    return {
        "directive_kind": "ticker",
        "directive_label": f"Advisory {v} — {sym}",
        "spec": {"symbol": sym},
        "rationale": (str(rationale or "") or f"Advisory desk verdict {v}")[:300],
        "thesis": f"Advisory {v} ({conviction or 0:.0f} conviction): {sym}",
        "conviction": conviction,
        "verdict": v,
    }


def defense_card_to_feedback(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map a defense recommendation card to curation feedback, or None.

    get_into cards prescribe a sector rotate-in; income cards prescribe a
    covered-call/income queue; short_side cards prescribe inverse-ETF hedges.
    """
    group = str(card.get("group") or "").strip().lower()
    if group not in DEFENSE_ROTATE_GROUPS:
        return None
    sym = str(card.get("symbol") or "").upper().strip()
    if group == "get_into":
        sector = str(card.get("sector") or card.get("note") or "")
        return {
            "directive_kind": "sector" if sector else "ticker",
            "directive_label": f"Defense rotate-in — {sym or sector}",
            "spec": {"gics_sector": sector, "finviz_sector": sector,
                     "symbol": sym} if sector else {"symbol": sym},
            "rationale": str(card.get("note") or "Defense desk rotate-in")[:300],
            "thesis": f"Defense rotate-in: {sym or sector}",
            "group": group,
        }
    # income / short_side carry an explicit symbol
    return {
        "directive_kind": "ticker",
        "directive_label": f"Defense {group} — {sym}",
        "spec": {"symbol": sym},
        "rationale": str(card.get("note") or f"Defense {group}")[:300],
        "thesis": f"Defense {group}: {sym}",
        "group": group,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pure mapping — reverse edge (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def options_edge_factor(iv_rank: Optional[float], edge_score: Optional[float]) -> Optional[float]:
    """Blend IV rank + prime-rubric edge score into one 0-100 options-edge factor.

    IV rank measures whether vol is attractive for premium selling; edge_score is
    the prime-rubric strategy-fit. Both missing -> None (factor is dropped, never
    fabricated). Returns a 0-100 float.
    """
    parts: List[float] = []
    if iv_rank is not None:
        # premium sellers like mid-high IV rank, but extreme IV is a warning
        iv = float(iv_rank)
        parts.append(max(0.0, min(100.0, 100 - abs(iv - 50) * 1.2)))
    if edge_score is not None:
        parts.append(max(0.0, min(100.0, float(edge_score))))
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


def iv_pct_to_rank(iv_pct: Optional[float], universe_ivs: List[float]) -> Optional[float]:
    """Map a raw IV% into a 0-100 rank vs a universe of peer IVs (percentile * 100)."""
    if iv_pct is None or not universe_ivs:
        return None
    try:
        iv = float(iv_pct)
    except (TypeError, ValueError):
        return None
    xs = sorted(float(x) for x in universe_ivs if x is not None)
    if not xs:
        return None
    below = sum(1 for x in xs if x <= iv)
    return round(100.0 * below / len(xs), 1)


def blend_options_edge_sources(
    *,
    closed_edge: Optional[float] = None,
    queue_edge: Optional[float] = None,
    iv_rank: Optional[float] = None,
) -> Optional[float]:
    """Priority blend for reverse-edge options score.

    1) Closed paper outcomes dominate when present (realized edge).
    2) Else blend approval-queue edge_score + IV-rank factor.
    3) Else queue-only or dampened IV-only (IV alone is a weaker proxy —
       mid-rank must not score a perfect 100).
    Never fabricates a neutral 50 when all missing.
    """
    if closed_edge is not None:
        return round(max(0.0, min(100.0, float(closed_edge))), 1)
    if queue_edge is not None and iv_rank is not None:
        return options_edge_factor(iv_rank, queue_edge)
    if queue_edge is not None:
        return round(max(0.0, min(100.0, float(queue_edge))), 1)
    if iv_rank is not None:
        raw = options_edge_factor(float(iv_rank), None)
        if raw is None:
            return None
        # dampen: map 0-100 → ~20-75 so IV-only never dominates ranks
        return round(20.0 + 0.55 * raw, 1)
    return None


def hermes_research_factor(signal: Optional[float]) -> Optional[float]:
    """Hermes research intelligence signal -> 0-100 factor. None drops the factor."""
    if signal is None:
        return None
    return round(max(0.0, min(100.0, float(signal))), 1)


def hermes_research_score_from_action(action: Optional[str]) -> Optional[float]:
    """Map a graded research_row 'actioned' outcome to a 0-100 research score.

    The outcome grader (grade_research_actions) resolves each Hermes research row to one
    of trade / proposal / directive_hit / none. Higher downstream action = higher research
    edge. 'none' still scores above zero (the name was researched) but carries no edge.
    None (ungraded) -> None so the scorer drops the factor rather than fabricating one.
    """
    table = {
        "trade": 90.0,
        "proposal": 75.0,
        "directive_hit": 60.0,
        "none": 15.0,
    }
    if action is None:
        return None
    return table.get(str(action).strip().lower())


def options_outcomes_to_conviction(
    outcomes: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate closed options paper outcomes per underlying symbol.

    Returns {symbol: {n, win_rate, net_pnl, options_edge, conviction_delta}}.
    conviction_delta is bounded +-20 so options edge informs but never dominates.
    """
    agg: Dict[str, Dict[str, Any]] = {}
    for o in outcomes:
        sym = str(o.get("symbol") or "").upper().strip()
        if not sym:
            continue
        a = agg.setdefault(sym, {"n": 0, "wins": 0, "losses": 0,
                                 "pnl": 0.0, "iv_rank": None, "edge": None})
        a["n"] += 1
        oc = str(o.get("outcome") or "").lower()
        if oc == "win":
            a["wins"] += 1
        elif oc == "loss":
            a["losses"] += 1
        try:
            a["pnl"] += float(o.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pass
        iv = o.get("iv_rank")
        if iv is not None and a["iv_rank"] is None:
            a["iv_rank"] = float(iv)
        e = o.get("edge_score")
        if e is not None and a["edge"] is None:
            a["edge"] = float(e)

    out: Dict[str, Dict[str, Any]] = {}
    for sym, a in agg.items():
        win_rate = round(a["wins"] / (a["wins"] + a["losses"]), 3) if (a["wins"] + a["losses"]) else None
        edge = options_edge_factor(a["iv_rank"], a["edge"])
        # bounded conviction delta: a strong (>=50% wr, positive pnl) book nudges +;
        # a losing book nudges -. Never exceeds +-20 so options never dominate the thesis.
        if win_rate is not None and a["pnl"] > 0 and win_rate >= 0.5:
            delta = min(20.0, 5.0 + (win_rate - 0.5) * 20.0)
        elif win_rate is not None and win_rate < 0.5:
            delta = max(-20.0, -(5.0 + (0.5 - win_rate) * 20.0))
        else:
            delta = 0.0
        out[sym] = {
            "n": a["n"], "win_rate": win_rate, "net_pnl": round(a["pnl"], 2),
            "options_edge": edge, "conviction_delta": round(delta, 2),
        }
    return out


def outcome_verdict_to_ledger(verdict: str) -> tuple:
    """Map an outcome-ledger verdict to (realized_outcome, thesis_win).

    hit -> (win, True); miss -> (loss, False); neutral -> (scratch, None).
    Anything else -> (None, None) = skip writeback.
    """
    v = str(verdict or "").lower()
    if v == "hit":
        return ("win", True)
    if v == "miss":
        return ("loss", False)
    if v == "neutral":
        return ("scratch", None)
    return (None, None)


def resolve_instrument_class(symbol: str) -> str:
    """Lightweight instrument classifier for coverage completeness (P3).

    Heuristic only — a real CUSIP resolver would live behind an enrichment rail.
    Returns one of: equity | etf | bond | fund | cash | unknown.
    """
    s = str(symbol or "").strip()
    if not s:
        return "unknown"
    up = s.upper()
    if up in ("CASH", "USD", "SPAXX", "SWVXX", "VMFXX"):
        return "cash"
    if len(s) == 9 and s.isdigit():
        return "bond"  # 9-digit CUSIP, checksum not validated here
    if up in ("SPY", "QQQ", "XLF", "XLK", "XLE", "XLV", "XLY", "XLP", "XLI",
              "XLU", "XLRE", "XLB", "XLC", "SCHD", "VTI", "VT", "BND", "TLT"):
        return "etf"
    return "equity"


# ─────────────────────────────────────────────────────────────────────────────
# Emit / writeback (executor-injected — dry-testable)
# ─────────────────────────────────────────────────────────────────────────────

def emit_feedback(source: str, feedback: Dict[str, Any],
                  executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Write one curation feedback record into the source's staging table.

    The app role drains this later — the source never writes production tables.
    """
    if source not in STAGING_TABLE:
        return {"ok": False, "error": f"unknown source '{source}'"}
    ex = executor or _default_executor()
    res = ex(
        f"""INSERT INTO {STAGING_TABLE[source]}
              (directive_id, symbol, thesis, source_detail)
            VALUES (%s, %s, %s, %s::jsonb)""",
        (
            feedback.get("directive_id"),
            str(feedback.get("spec", {}).get("symbol") or "").upper() or None,
            str(feedback.get("thesis") or "")[:300] or None,
            _json(feedback),
        ),
    )
    if res is None:
        return {"ok": False, "error": "db unavailable — feedback NOT staged"}
    audit(source, "staged", {"symbol": str(feedback.get("spec", {}).get("symbol") or "").upper() or None,
                             "directive_kind": feedback.get("directive_kind")}, executor=ex)
    return {"ok": True, "source": source, "staged": True}


def emit_all(source: str, feedback_list: List[Dict[str, Any]],
             executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Emit a batch of curation feedback records; returns a summary."""
    staged = skipped = failed = 0
    for fb in feedback_list or []:
        if not fb:
            skipped += 1
            continue
        res = emit_feedback(source, fb, executor)
        if res.get("ok"):
            staged += 1
        else:
            failed += 1
    return {"ok": failed == 0, "source": source, "staged": staged,
            "skipped": skipped, "failed": failed}


def undrained_staging(source: str, executor: Optional[Executor] = None,
                      directive_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read undrained staging rows for a source (and optionally one directive)."""
    if source not in STAGING_TABLE:
        return []
    ex = executor or _default_executor()
    sql = (f"SELECT id, directive_id, symbol, thesis, source_detail, proposed_at "
           f"FROM {STAGING_TABLE[source]} WHERE drained = false")
    params: tuple = ()
    if directive_id is not None:
        sql += " AND directive_id = %s"
        params = (directive_id,)
    sql += " ORDER BY proposed_at"
    rows = ex(sql, params, fetch="all")
    return [dict(r) for r in rows] if rows else []


def mark_staging_drained(source: str, row_id: int,
                         executor: Optional[Executor] = None) -> bool:
    if source not in STAGING_TABLE:
        return False
    ex = executor or _default_executor()
    res = ex(f"UPDATE {STAGING_TABLE[source]} SET drained = true, drained_at = NOW() "
             f"WHERE id = %s", (row_id,))
    return res is not None


def drain_curation_sources(cur, dry: bool, report: Dict[str, Any],
                           evaluate: Callable[..., Dict[str, Any]],
                           resolve_fn: Callable[..., List[str]],
                           *,
                           drain_limit: int = DEFAULT_DRAIN_LIMIT,
                           auto_apply: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
    """Drain CIO/advisory/defense curation feedback (forward edge) via a cursor.

    Self-contained (no psycopg2 / .env at import) so it is dry-testable with a fake
    cursor. `evaluate(symbol, directive_id, reason, source, auto)` and
    `resolve_fn(directive_dict) -> [symbol]` are supplied by the caller (the service
    wraps the real promote_directive_lead governor + directive resolver).

    ``auto_apply(source, symbol, did) -> gate dict`` is optional: when present and
    gate.auto_apply is False, evaluate is forced to stage (auto=False). When True,
    auto=None lets the governor decide. Never bypasses governor for auto=True.
    """
    report.setdefault("detail", [])
    report.setdefault("promoted", 0)
    report.setdefault("staged", 0)
    limit = max(1, int(drain_limit or DEFAULT_DRAIN_LIMIT))
    for source in ("cio", "advisory", "defense"):
        tbl = STAGING_TABLE[source]
        cur.execute(
            f"SELECT * FROM {tbl} WHERE drained=false ORDER BY proposed_at LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall() or []
        for h in rows:
            hid = h["id"]
            detail = h.get("source_detail") if isinstance(h.get("source_detail"), dict) \
                else json.loads(h.get("source_detail") or "{}")
            kind = str(detail.get("directive_kind") or "").lower()
            spec = detail.get("spec") or {}
            label = str(detail.get("directive_label") or "")[:200] or f"{source} directive"
            if kind not in ("ticker", "sector", "trend"):
                if not dry:
                    cur.execute(f"UPDATE {tbl} SET drained=true, drained_at=now() WHERE id=%s", (hid,))
                report.setdefault("curation_skipped_no_kind", 0)
                report["curation_skipped_no_kind"] += 1
                continue
            did = h.get("directive_id")
            if not did:
                cur.execute("SELECT id FROM watch_directives WHERE kind=%s AND label=%s LIMIT 1",
                            (kind, label))
                r = cur.fetchone()
                if r:
                    did = r["id"] if isinstance(r, dict) else r[0]
                elif not dry:
                    cur.execute("""INSERT INTO watch_directives
                        (kind,label,spec,rationale,created_by,status,priority,
                         trade_ai_enabled,hermes_enabled,ttl_days)
                        VALUES (%s,%s,%s::jsonb,%s,%s,'active','normal',true,true,%s)
                        RETURNING id""",
                        (kind, label, json.dumps(spec, default=str),
                         str(detail.get("rationale") or "")[:500] or None, source,
                         DESK_DIRECTIVE_TTL_DAYS))
                    row = cur.fetchone()
                    did = row["id"] if isinstance(row, dict) else row[0]
            syms = resolve_fn({"id": did, "kind": kind, "spec": spec, "label": label})
            for sym in (syms or []):
                if not dry and did:
                    auto_flag = None  # governor decides by default
                    if auto_apply is not None:
                        try:
                            gate = auto_apply(source, sym, did) or {}
                            if not gate.get("auto_apply", False):
                                auto_flag = False  # force stage_for_review path
                            report.setdefault("auto_apply_decisions", []).append({
                                "source": source, "symbol": sym,
                                "action": gate.get("action"), "auto_apply": gate.get("auto_apply"),
                            })
                        except Exception as exc:
                            auto_flag = False
                            report.setdefault("auto_apply_errors", 0)
                            report["auto_apply_errors"] = report.get("auto_apply_errors", 0) + 1
                            report["detail"].append({
                                "source": source, "symbol": sym,
                                "event": "auto_apply_error", "error": str(exc)[:120],
                            })
                    res = evaluate(
                        sym, did,
                        f"{source}:{(str(detail.get('thesis') or '')[:60])}",
                        source, auto_flag,
                    )
                    st = res.get("status")
                    report["promoted"] = report.get("promoted", 0) + (1 if st == "PROMOTED" else 0)
                    report["staged"] = report.get("staged", 0) + (1 if st == "STAGED_FOR_REVIEW" else 0)
                    report["detail"].append({"source": source, "symbol": sym, "status": st,
                                             "directive": label, "surfaced_by": SURFACED_BY.get(source, source)})
                else:
                    report["detail"].append({"source": source, "symbol": sym,
                                             "directive": label, "dry": True})
            if not dry:
                cur.execute(f"UPDATE {tbl} SET drained=true, drained_at=now() WHERE id=%s", (hid,))
                try:
                    cur.execute(
                        """INSERT INTO curation_loop_audit (source, event, payload)
                           VALUES (%s, %s, %s::jsonb)""",
                        (source, "drained",
                         json.dumps({"id": hid, "directive_id": did, "label": label}, default=str)),
                    )
                except Exception:
                    pass  # audit fail-soft — never block drain
            report.setdefault("curation_drained", 0)
            report["curation_drained"] += 1


def write_realized_outcome(symbol: str, realized_outcome: Optional[str],
                           thesis_win: Optional[bool],
                           executor: Optional[Executor] = None,
                           *,
                           overwrite: bool = True) -> Dict[str, Any]:
    """Reverse edge: realized trade outcome -> watchlist_items conviction ledger.

    Default overwrite=True so the latest graded verdict wins (avoids first-win freeze).
    Set overwrite=False to keep COALESCE first-wins semantics for back-compat tests.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol required"}
    if realized_outcome is None and thesis_win is None:
        return {"ok": False, "error": "nothing to write"}
    ex = executor or _default_executor()
    if overwrite:
        sql = """UPDATE watchlist_items SET
                 realized_outcome = COALESCE(%s, realized_outcome),
                 thesis_win = CASE WHEN %s::boolean IS NULL THEN thesis_win ELSE %s::boolean END,
                 last_validated_at = NOW(),
                 updated_at = NOW()
               WHERE symbol = %s AND status IN ('active','researched')"""
        # realized_outcome always overwrites when provided; thesis_win overwrites when not None
        params = (
            realized_outcome,
            thesis_win, thesis_win,
            sym,
        )
        if realized_outcome is not None:
            sql = """UPDATE watchlist_items SET
                     realized_outcome = %s,
                     thesis_win = CASE WHEN %s::boolean IS NULL THEN thesis_win ELSE %s::boolean END,
                     last_validated_at = NOW(),
                     updated_at = NOW()
                   WHERE symbol = %s AND status IN ('active','researched')"""
            params = (realized_outcome, thesis_win, thesis_win, sym)
    else:
        sql = """UPDATE watchlist_items SET
                 realized_outcome = COALESCE(%s, realized_outcome),
                 thesis_win = COALESCE(%s, thesis_win),
                 last_validated_at = NOW(),
                 updated_at = NOW()
               WHERE symbol = %s AND status IN ('active','researched')"""
        params = (realized_outcome, thesis_win, sym)
    res = ex(sql, params)
    if res is None:
        return {"ok": False, "error": "db unavailable — outcome NOT written"}
    audit("outcome", "folded", {"symbol": sym, "realized_outcome": realized_outcome,
                                "thesis_win": thesis_win}, executor=ex)
    return {"ok": True, "symbol": sym, "realized_outcome": realized_outcome,
            "thesis_win": thesis_win}


def write_options_edge(symbol: str, options_edge: Optional[float],
                       detail: Optional[Dict[str, Any]] = None,
                       executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Reverse edge: options paper outcomes -> underlying symbol's options_edge."""
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol required"}
    ex = executor or _default_executor()
    res = ex(
        """UPDATE watchlist_items SET
             options_edge_score = %s,
             options_edge_detail = COALESCE(%s::jsonb, options_edge_detail),
             last_validated_at = NOW(),
             updated_at = NOW()
           WHERE symbol = %s AND status IN ('active','researched')""",
        (options_edge, _json(detail or {}), sym),
    )
    if res is None:
        return {"ok": False, "error": "db unavailable — options_edge NOT written"}
    audit("options", "folded", {"symbol": sym, "options_edge": options_edge}, executor=ex)
    return {"ok": True, "symbol": sym, "options_edge": options_edge}


def write_hermes_research(symbol: str, score: Optional[float],
                          detail: Optional[Dict[str, Any]] = None,
                          executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Reverse edge: Hermes research intelligence -> watchlist_items research score."""
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol required"}
    ex = executor or _default_executor()
    res = ex(
        """UPDATE watchlist_items SET
             hermes_research_score = %s,
             hermes_research_detail = COALESCE(%s::jsonb, hermes_research_detail),
             last_validated_at = NOW(),
             updated_at = NOW()
           WHERE symbol = %s AND status IN ('active','researched')""",
        (score, _json(detail or {}), sym),
    )
    if res is None:
        return {"ok": False, "error": "db unavailable — hermes_research NOT written"}
    audit("hermes_research", "folded", {"symbol": sym, "score": score}, executor=ex)
    return {"ok": True, "symbol": sym, "hermes_research_score": score}


def ensure_directive(source: str, feedback: Dict[str, Any],
                     executor: Optional[Executor] = None) -> Optional[int]:
    """Upsert a watch_directives row from a feedback record and return its id.

    The forward edge is what makes curation *self-thinking*: a CIO/advisory/defense
    signal can mint its own standing directive (deduped by kind+label) rather than
    requiring the operator to hand-create one. created_by records the source so
    provenance is never lost. Returns None if the record has no directive_kind.
    """
    kind = str(feedback.get("directive_kind") or "").lower()
    if kind not in ("ticker", "sector", "trend"):
        return None
    label = str(feedback.get("directive_label") or "")[:200] or f"{source} {kind}"
    spec = feedback.get("spec") or {}
    rationale = str(feedback.get("rationale") or "")[:500] or None
    ex = executor or _default_executor()
    res = ex(
        """SELECT id FROM watch_directives WHERE kind = %s AND label = %s LIMIT 1""",
        (kind, label), fetch="one",
    )
    row = res[0] if res and not isinstance(res, bool) else None
    if row is not None:
        return int(row)
    ins = ex(
        """INSERT INTO watch_directives
             (kind, label, spec, rationale, created_by, status, priority,
              trade_ai_enabled, hermes_enabled, ttl_days)
           VALUES (%s, %s, %s::jsonb, %s, %s, 'active', 'normal', true, true, %s)
           RETURNING id""",
        (kind, label, _json(spec), rationale, source, DESK_DIRECTIVE_TTL_DAYS),
    )
    if not ins:
        return None
    return int(ins[0])


def audit(source: str, event: str, payload: Optional[Dict[str, Any]] = None,
          executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Append a provenance row to the curation loop audit trail."""
    ex = executor or _default_executor()
    res = ex(
        """INSERT INTO curation_loop_audit (source, event, payload)
           VALUES (%s, %s, %s::jsonb)""",
        (source, event, _json(payload or {})),
    )
    if res is None:
        return {"ok": False, "error": "db unavailable — audit NOT written"}
    return {"ok": True, "source": source, "event": event}


# ─────────────────────────────────────────────────────────────────────────────
# P4 — graduated autonomy (pure gate, no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def auto_apply_gate(source_tier: str, divergence: str, hit_rate: Optional[float],
                    *, min_hit_rate: float = 0.6) -> Dict[str, Any]:
    """Graduated auto-apply for self-learning gates.

    Auto-apply is ONLY permitted when all three hold:
      * source tier is trusted/core
      * divergence is not 'divergent'
      * the source's trailing hit-rate meets the floor (evidence the loop is working)
    Anything else stages for review. This is a policy gate, not an execution switch —
    nothing here enables a live trade.
    """
    tier_ok = str(source_tier or "").lower() in ("core", "trusted")
    div_ok = str(divergence or "") != "divergent"
    hr_ok = hit_rate is not None and float(hit_rate) >= min_hit_rate
    allowed = tier_ok and div_ok and hr_ok
    return {
        "auto_apply": allowed,
        "tier_ok": tier_ok,
        "divergence_ok": div_ok,
        "hit_rate_ok": hr_ok,
        "min_hit_rate": min_hit_rate,
        "action": "auto_apply" if allowed else "stage_for_review",
    }


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _json(obj: Any) -> str:
    import json as _json
    return _json.dumps(obj, default=str)


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute

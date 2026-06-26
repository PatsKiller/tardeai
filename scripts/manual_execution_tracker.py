#!/usr/bin/env python3
"""manual_execution_tracker.py — Automatic tagging + closed-loop tracking for manual executions.

When the operator executes a trade manually (Schwab or Fidelity) that originated from a watchlist,
watchpool, equity proposal, or options proposal, this module:

  1. Auto-matches the best origin (or accepts an explicit origin from the UI modal)
  2. Persists a manual_execution_log row with full lineage
  3. Emits lifecycle_events for journal / learning loops
  4. Marks rec_ticker_attribution.executed where applicable

Usage:
    python3 scripts/manual_execution_tracker.py --match XAR
    python3 scripts/manual_execution_tracker.py --metrics
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
AUDIT_JSONL = PROJECT_ROOT / "logs" / "manual_execution_tracker.jsonl"

log = logging.getLogger("manual_execution_tracker")

ORIGIN_PRIORITY = (
    "options_proposal",
    "proposal",
    "watchpool",
    "watchlist",
    "directive",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _audit(event: str, **fields) -> None:
    try:
        AUDIT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": _iso(), "event": event, **fields}
        with AUDIT_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def _db(sql, params=None, fetch="one"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None if fetch == "one" else []
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None if fetch == "one" else []


def _load_holdings_rows() -> List[dict]:
    try:
        data = json.loads((STATE_DIR / "holdings.json").read_text(encoding="utf-8"))
        return data.get("holdings") or []
    except Exception:
        return []


def _normalize_account_key(raw: str, holdings: Optional[List[dict]] = None) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if "_" in s and s.lower() == s:
        return s
    rows = holdings if holdings is not None else _load_holdings_rows()
    for h in rows:
        disp = (h.get("account_display") or "").strip()
        key = (h.get("account") or h.get("account_id") or "").strip()
        if s.lower() == disp.lower():
            return key
        if s.lower().replace(" ", "_") == key.lower():
            return key
    return s.lower().replace(" ", "_") if " " in s else s


def _auto_resolve_account(
    symbol: str,
    account: str = "",
    *,
    options_proposal_id: Optional[str] = None,
    proposal_id: Optional[int] = None,
) -> str:
    """Auto-select canonical account: explicit > proposal > symbol lot > Schwab default."""
    acct = _normalize_account_key(account)
    if acct:
        return acct
    if options_proposal_id:
        op = _load_options_proposal(options_proposal_id)
        if op:
            acct = _normalize_account_key(op.get("account") or "")
            if acct:
                return acct
    if proposal_id:
        row = _db(
            """SELECT COALESCE(target_account, proposed_account) AS account
               FROM paper_trade_proposals WHERE id=%s""",
            (proposal_id,),
            fetch="one",
        )
        if row and row.get("account"):
            acct = _normalize_account_key(row["account"])
            if acct:
                return acct
    holdings = _load_holdings_rows()
    sym = (symbol or "").upper()
    lots = [
        h for h in holdings
        if (h.get("symbol") or "").upper() == sym and not h.get("is_cash")
    ]
    if lots:
        lots.sort(key=lambda h: (-float(h.get("shares") or 0), -float(h.get("market_value") or 0)))
        return _normalize_account_key(lots[0].get("account") or "")
    for key in ("schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira"):
        if any((h.get("account") or "") == key for h in holdings):
            return key
    return "schwab_taxable"


def _account_broker(account: str) -> tuple:
    if not account:
        return None, None
    row = _db(
        "SELECT broker, environment FROM broker_accounts WHERE account_key=%s",
        (account,),
        fetch="one",
    )
    if row and row.get("broker"):
        return row["broker"], row.get("environment")
    a = account.lower()
    for b in ("schwab", "fidelity", "alpaca", "tos"):
        if b in a:
            return b, "live"
    return None, None


def _load_options_proposal(options_id: str) -> Optional[dict]:
    if not options_id:
        return None
    cache = STATE_DIR / "options_proposals.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        for p in data.get("proposals") or []:
            if str(p.get("id")) == str(options_id):
                return p
    except Exception:
        pass
    return None


def find_origins(symbol: str, account: Optional[str] = None) -> List[dict]:
    """Ranked origin candidates for a symbol (read-only)."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    out: List[dict] = []

    # Options proposals (cache)
    try:
        data = json.loads((STATE_DIR / "options_proposals.json").read_text(encoding="utf-8"))
        for p in data.get("proposals") or []:
            if (p.get("symbol") or "").upper() == sym:
                out.append({
                    "origin_type": "options_proposal",
                    "origin_id": str(p.get("id")),
                    "confidence": "exact",
                    "label": f"Options {p.get('strategy', '').replace('_', ' ')} ${p.get('strike')}",
                    "detail": p,
                })
    except Exception:
        pass

    # Equity proposals
    rows = _db(
        """SELECT id, symbol, strategy_id, status, origin, proposed_entry, proposed_shares,
                  COALESCE(target_account, proposed_account) AS account, created_at
           FROM paper_trade_proposals
           WHERE upper(symbol)=%s
             AND status IN ('PENDING','APPROVED_FOR_PAPER_TEST','APPROVED')
           ORDER BY created_at DESC LIMIT 5""",
        (sym,),
        fetch="all",
    ) or []
    for r in rows:
        out.append({
            "origin_type": "proposal",
            "origin_id": str(r["id"]),
            "confidence": "exact",
            "label": f"Proposal #{r['id']} · {r.get('strategy_id')}",
            "detail": dict(r),
        })

    # Watchpool
    wp = _db(
        """SELECT id, symbol, strategy_id, current_status, updated_at
           FROM strategy_watchpool
           WHERE upper(symbol)=%s AND current_status NOT IN ('expired','failed','removed')
           ORDER BY updated_at DESC NULLS LAST LIMIT 3""",
        (sym,),
        fetch="all",
    ) or []
    for r in wp:
        out.append({
            "origin_type": "watchpool",
            "origin_id": str(r["id"]),
            "confidence": "inferred",
            "label": f"Watchpool · {r.get('strategy_id')}",
            "detail": dict(r),
        })

    # Watchlist
    wl = _db(
        """SELECT symbol, source, status, hermes_rank, first_seen_at, updated_at
           FROM watchlist_items
           WHERE upper(symbol)=%s AND status <> 'removed'
           ORDER BY updated_at DESC NULLS LAST LIMIT 3""",
        (sym,),
        fetch="all",
    ) or []
    for r in wl:
        r["id"] = r.get("symbol")
    for r in wl:
        out.append({
            "origin_type": "watchlist",
            "origin_id": str(r["id"]),
            "confidence": "inferred",
            "label": f"Watchlist · {r.get('source')}",
            "detail": dict(r),
        })

    # Directives
    dr = _db(
        """SELECT id, label, kind, rationale, created_at
           FROM watch_directives
           WHERE kind='ticker'
             AND upper(COALESCE(NULLIF(spec->>'symbol',''), label))=%s
           ORDER BY created_at DESC LIMIT 2""",
        (sym,),
        fetch="all",
    ) or []
    for r in dr:
        out.append({
            "origin_type": "directive",
            "origin_id": str(r["id"]),
            "confidence": "inferred",
            "label": f"Directive · {(r.get('rationale') or '')[:60]}",
            "detail": dict(r),
        })

    # Sort by priority then confidence
    conf_rank = {"exact": 0, "inferred": 1, "manual": 2}
    prio = {t: i for i, t in enumerate(ORIGIN_PRIORITY)}

    def _key(o: dict):
        return (prio.get(o.get("origin_type"), 99), conf_rank.get(o.get("confidence"), 9))

    out.sort(key=_key)
    if account:
        acct_l = account.lower()
        for o in out:
            det = o.get("detail") or {}
            acct = (det.get("account") or det.get("target_account") or det.get("proposed_account") or "")
            if acct and acct_l in acct.lower():
                o["confidence"] = "exact"
    return out


def auto_match_origin(symbol: str, account: Optional[str] = None,
                      origin_type: Optional[str] = None,
                      origin_id: Optional[str] = None) -> dict:
    """Pick best origin — explicit wins, else highest-priority match."""
    if origin_type and origin_id:
        return {
            "origin_type": origin_type,
            "origin_id": str(origin_id),
            "origin_confidence": "exact",
        }
    candidates = find_origins(symbol, account=account)
    if not candidates:
        return {"origin_type": "manual", "origin_id": None, "origin_confidence": "manual"}
    best = candidates[0]
    return {
        "origin_type": best["origin_type"],
        "origin_id": best["origin_id"],
        "origin_confidence": best.get("confidence", "inferred"),
        "label": best.get("label"),
    }


def prepare_manual_execution(
    *,
    symbol: str,
    account: str,
    proposal_id: Optional[int] = None,
    options_proposal_id: Optional[str] = None,
    shares: Optional[int] = None,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    target: Optional[float] = None,
    strike: Optional[float] = None,
    expiration: Optional[str] = None,
    contracts: Optional[int] = None,
    risk_reward: Optional[float] = None,
) -> dict:
    """Build pre-filled manual execution payload for the adjustment modal."""
    sym = symbol.upper().strip()
    acct = _auto_resolve_account(
        sym, account or "",
        options_proposal_id=options_proposal_id,
        proposal_id=proposal_id,
    )
    broker, _ = _account_broker(acct)
    is_fidelity = broker == "fidelity" or "fidelity" in (acct or "").lower()
    is_schwab = broker == "schwab" or "schwab" in (acct or "").lower()
    prof = {
        "broker": broker or ("fidelity" if is_fidelity else "schwab" if is_schwab else "other"),
        "auto_eligible": is_schwab and not is_fidelity,
        "execution_mode": "manual" if is_fidelity else "auto_or_manual",
    }

    account_options = []
    try:
        rows = _db(
            """SELECT account_key, display_name, broker FROM broker_accounts ORDER BY account_key""",
            fetch="all",
        ) or []
        for r in rows:
            b = (r.get("broker") or "").lower()
            key = r.get("account_key") or ""
            label = r.get("display_name") or key.replace("_", " ").title()
            mode = "Manual" if "fidelity" in b or "fidelity" in key else "Auto · 2FA"
            account_options.append({"account_key": key, "label": label, "broker": b, "mode": mode})
    except Exception:
        pass

    base: Dict[str, Any] = {
        "symbol": sym,
        "account": acct,
        "account_auto_selected": not bool((account or "").strip()),
        "broker": prof["broker"],
        "execution_mode": prof["execution_mode"],
        "execution_label": "Manual · Fidelity" if is_fidelity else "Schwab · auto + 2FA",
        "auto_eligible": prof["auto_eligible"],
        "account_options": account_options,
        "origins": find_origins(sym, account=acct),
        "recommended": {},
    }

    if options_proposal_id:
        op = _load_options_proposal(options_proposal_id)
        if op:
            if not (account or "").strip() and op.get("account"):
                base["account"] = _normalize_account_key(op.get("account") or "")
                base["account_auto_selected"] = True
            base["execution_type"] = "option"
            base["recommended"] = {
                "options_proposal_id": options_proposal_id,
                "strategy": op.get("strategy"),
                "strike": strike or op.get("strike"),
                "expiration": expiration or op.get("expiration"),
                "contracts": contracts or op.get("contracts") or 1,
                "entry_price": entry or op.get("premium"),
                "option_side": op.get("side"),
                "risk_reward": risk_reward or op.get("risk_reward"),
            }
            base["origin_type"] = "options_proposal"
            base["origin_id"] = options_proposal_id
            return base

    if proposal_id:
        row = _db(
            """SELECT id, symbol, strategy_id, proposed_shares, proposed_entry, proposed_stop,
                      proposed_target1, proposed_rr
               FROM paper_trade_proposals WHERE id=%s""",
            (proposal_id,),
            fetch="one",
        )
        if row:
            base["execution_type"] = "equity"
            base["recommended"] = {
                "proposal_id": proposal_id,
                "strategy_id": row.get("strategy_id"),
                "shares": shares or row.get("proposed_shares"),
                "entry_price": entry or row.get("proposed_entry"),
                "stop_price": stop or row.get("proposed_stop"),
                "target_price": target or row.get("proposed_target1"),
                "risk_reward": risk_reward or row.get("proposed_rr"),
            }
            base["origin_type"] = "proposal"
            base["origin_id"] = str(proposal_id)
            return base

    match = auto_match_origin(sym, account=acct)
    base["execution_type"] = "option" if strike else "equity"
    base["origin_type"] = match.get("origin_type")
    base["origin_id"] = match.get("origin_id")
    base["recommended"] = {
        "shares": shares,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "strike": strike,
        "expiration": expiration,
        "contracts": contracts or 1,
        "risk_reward": risk_reward,
    }
    return base


def _emit_lifecycle(symbol: str, strategy_id: Optional[str], payload: dict,
                    origin_type: str, origin_id: Optional[str], row_id: int) -> None:
    try:
        from lifecycle_event_writer import write_event, generate_lifecycle_id
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return
        lc = generate_lifecycle_id(symbol, strategy_id or "manual", origin_id or str(row_id))
        write_event(
            conn, lc, stage="execution", event_type="manual_execution_logged",
            status="logged", symbol=symbol, strategy_id=strategy_id,
            proposal_id=payload.get("proposal_id"),
            source_script="manual_execution_tracker",
            source_table="manual_execution_log", source_pk=str(row_id),
            payload={
                "origin_type": origin_type,
                "origin_id": origin_id,
                "broker": payload.get("broker"),
                "account": payload.get("account"),
                **{k: v for k, v in payload.items() if v is not None},
            },
        )
    except Exception as e:
        log.debug("lifecycle emit skipped: %s", e)


def _sync_rec_intel(symbol: str, origin_type: str, origin_id: Optional[str], account: str) -> None:
    """Flip executed flag on matching rec_ticker_attribution rows."""
    table_map = {
        "watchlist": "watchlist_items",
        "watchpool": "strategy_watchpool",
        "proposal": "paper_trade_proposals",
        "directive": "watch_directives",
    }
    ref_table = table_map.get(origin_type)
    if not ref_table or not origin_id:
        return
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return
        _execute(
            """UPDATE rec_ticker_attribution
               SET executed=true, updated_at=now()
               WHERE upper(symbol)=%s AND source_ref_table=%s AND source_ref_id=%s""",
            (symbol.upper(), ref_table, str(origin_id)),
            fetch=None,
        )
        _execute(
            """INSERT INTO rec_ticker_attribution
               (symbol, source_type, source_ref_table, source_ref_id, source_detail,
                account, first_seen_at, last_seen_at, occurrences, executed)
               VALUES (%s,%s,%s,%s,%s,%s,now(),now(),1,true)
               ON CONFLICT (symbol, source_type, source_ref_table, source_ref_id) DO UPDATE
               SET executed=true, last_seen_at=now(), updated_at=now()""",
            (
                symbol.upper(),
                origin_type if origin_type != "options_proposal" else "proposal",
                ref_table if origin_type != "options_proposal" else "options_proposals_cache",
                str(origin_id),
                json.dumps({"manual_execution": True}),
                account,
            ),
            fetch=None,
        )
    except Exception:
        pass


def log_manual_execution(
    *,
    symbol: str,
    account: str,
    execution_type: str = "equity",
    origin_type: Optional[str] = None,
    origin_id: Optional[str] = None,
    proposal_id: Optional[int] = None,
    options_proposal_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    shares: Optional[int] = None,
    contracts: Optional[int] = None,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
    strike: Optional[float] = None,
    expiration: Optional[str] = None,
    option_side: Optional[str] = None,
    risk_reward: Optional[float] = None,
    outcome: str = "pending",
    outcome_pnl: Optional[float] = None,
    outcome_pnl_pct: Optional[float] = None,
    notes: Optional[str] = None,
    adjusted_params: Optional[dict] = None,
) -> dict:
    """Persist manual execution with automatic origin tagging."""
    sym = (symbol or "").upper().strip()
    acct = (account or "").strip()
    if not sym or not acct:
        return {"ok": False, "error": "symbol and account are required"}

    broker, _ = _account_broker(acct)
    match = auto_match_origin(sym, account=acct, origin_type=origin_type, origin_id=origin_id)
    otype = match.get("origin_type") or "manual"
    oid = match.get("origin_id")
    conf = match.get("origin_confidence") or "inferred"

    if options_proposal_id and not oid:
        otype, oid, conf = "options_proposal", str(options_proposal_id), "exact"
    if proposal_id and not oid:
        otype, oid, conf = "proposal", str(proposal_id), "exact"

    # Options-origin rows must be typed + keyed as options (not equity).
    if otype == "options_proposal" or (oid and str(oid).startswith("opt_")):
        execution_type = "option"
        if not options_proposal_id and oid:
            options_proposal_id = str(oid)
        op = _load_options_proposal(options_proposal_id or oid or "")
        if op:
            strategy_id = strategy_id or op.get("strategy")
            contracts = contracts if contracts is not None else op.get("contracts")
            strike = strike if strike is not None else op.get("strike")
            expiration = expiration or op.get("expiration")
            entry_price = entry_price if entry_price is not None else op.get("premium")
            option_side = option_side or op.get("side")
            risk_reward = risk_reward if risk_reward is not None else op.get("risk_reward")

    row = _db(
        """INSERT INTO manual_execution_log
           (symbol, account, broker, execution_type, origin_type, origin_id, origin_confidence,
            proposal_id, options_proposal_id, strategy_id, shares, contracts, entry_price,
            stop_price, target_price, strike, expiration, option_side, risk_reward,
            outcome, outcome_pnl, outcome_pnl_pct, adjusted_params, notes, executed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           RETURNING id, created_at""",
        (
            sym, acct, broker, execution_type, otype, oid, conf,
            proposal_id, options_proposal_id, strategy_id,
            shares, contracts, entry_price, stop_price, target_price,
            strike, expiration, option_side, risk_reward,
            outcome, outcome_pnl, outcome_pnl_pct,
            json.dumps(adjusted_params or {}), notes,
        ),
        fetch="one",
    )
    if not row:
        return {"ok": False, "error": "database insert failed — run migration 20260622_manual_execution_lineage.sql"}

    row_id = int(row["id"])
    payload = {
        "symbol": sym, "account": acct, "broker": broker,
        "proposal_id": proposal_id, "options_proposal_id": options_proposal_id,
        "execution_type": execution_type,
    }
    _emit_lifecycle(sym, strategy_id, payload, otype, oid, row_id)
    _sync_rec_intel(sym, otype, oid, acct)
    _audit("manual_execution_logged", id=row_id, symbol=sym, origin_type=otype, origin_id=oid, account=acct)

    return {
        "ok": True,
        "id": row_id,
        "symbol": sym,
        "account": acct,
        "broker": broker,
        "origin_type": otype,
        "origin_id": oid,
        "origin_confidence": conf,
        "origin_label": match.get("label"),
        "execution_type": execution_type,
        "message": f"Logged manual {execution_type} on {sym} → origin {otype}" + (f" #{oid}" if oid else ""),
    }


def update_outcome(execution_id: int, outcome: str,
                   outcome_pnl: Optional[float] = None,
                   outcome_pnl_pct: Optional[float] = None) -> dict:
    """Close the loop — win / loss / breakeven."""
    outcome = (outcome or "").lower().strip()
    if outcome not in ("win", "loss", "breakeven", "open", "pending"):
        return {"ok": False, "error": "outcome must be win|loss|breakeven|open|pending"}
    row = _db(
        """UPDATE manual_execution_log
           SET outcome=%s, outcome_pnl=%s, outcome_pnl_pct=%s,
               closed_at=CASE WHEN %s IN ('win','loss','breakeven') THEN now() ELSE closed_at END,
               learning_synced=false, updated_at=now()
           WHERE id=%s RETURNING symbol, origin_type, origin_id""",
        (outcome, outcome_pnl, outcome_pnl_pct, outcome, execution_id),
        fetch="one",
    )
    if not row:
        return {"ok": False, "error": "execution not found"}
    _audit("outcome_updated", id=execution_id, outcome=outcome, symbol=row.get("symbol"))
    return {"ok": True, "id": execution_id, "outcome": outcome, **dict(row)}


def _is_option_row(row: dict) -> bool:
    return (
        (row.get("execution_type") or "") == "option"
        or row.get("origin_type") == "options_proposal"
        or bool(row.get("options_proposal_id"))
        or str(row.get("origin_id") or "").startswith("opt_")
    )


def list_manual_executions(
    limit: int = 50,
    symbol: Optional[str] = None,
    execution_type: Optional[str] = None,
) -> List[dict]:
    """Recent manual execution log rows for Command Center display."""
    lim = max(1, min(int(limit), 200))
    sym = (symbol or "").upper().strip() or None
    et = (execution_type or "").lower().strip() or None
    base_sql = """SELECT id, symbol, account, broker, execution_type, origin_type, origin_id,
                         origin_confidence, proposal_id, options_proposal_id, strategy_id,
                         shares, contracts, entry_price, stop_price, target_price, strike,
                         expiration, option_side, risk_reward, outcome, outcome_pnl,
                         outcome_pnl_pct, notes, executed_at, created_at
                  FROM manual_execution_log"""
    if sym and et == "option":
        rows = _db(
            base_sql + """ WHERE upper(symbol)=%s
               AND (execution_type='option' OR origin_type='options_proposal'
                    OR options_proposal_id IS NOT NULL OR origin_id LIKE 'opt_%%')
               ORDER BY executed_at DESC LIMIT %s""",
            (sym, lim),
            fetch="all",
        ) or []
    elif sym and et == "equity":
        rows = _db(
            base_sql + """ WHERE upper(symbol)=%s
               AND execution_type='equity' AND origin_type IS DISTINCT FROM 'options_proposal'
               AND options_proposal_id IS NULL
               AND (origin_id IS NULL OR origin_id NOT LIKE 'opt_%%')
               ORDER BY executed_at DESC LIMIT %s""",
            (sym, lim),
            fetch="all",
        ) or []
    elif sym:
        rows = _db(
            base_sql + " WHERE upper(symbol)=%s ORDER BY executed_at DESC LIMIT %s",
            (sym, lim),
            fetch="all",
        ) or []
    elif et == "option":
        rows = _db(
            base_sql + """ WHERE execution_type='option' OR origin_type='options_proposal'
               OR options_proposal_id IS NOT NULL OR origin_id LIKE 'opt_%%'
               ORDER BY executed_at DESC LIMIT %s""",
            (lim,),
            fetch="all",
        ) or []
    elif et == "equity":
        rows = _db(
            base_sql + """ WHERE execution_type='equity' AND origin_type IS DISTINCT FROM 'options_proposal'
               AND options_proposal_id IS NULL
               AND (origin_id IS NULL OR origin_id NOT LIKE 'opt_%%')
               ORDER BY executed_at DESC LIMIT %s""",
            (lim,),
            fetch="all",
        ) or []
    else:
        rows = _db(
            base_sql + f" ORDER BY executed_at DESC LIMIT {lim}",
            fetch="all",
        ) or []
    return [dict(r) for r in rows]


def get_tracking_metrics(days: int = 14) -> dict:
    """Metrics for Health Agent — conversion + untagged manual trades."""
    window = max(1, int(days))
    total = int((_db(
        f"""SELECT COUNT(*) AS c FROM manual_execution_log
            WHERE executed_at > NOW() - INTERVAL '{window} days'""",
        fetch="one",
    ) or {}).get("c", 0))

    untagged = int((_db(
        f"""SELECT COUNT(*) AS c FROM manual_execution_log
            WHERE executed_at > NOW() - INTERVAL '{window} days'
              AND origin_confidence='manual'""",
        fetch="one",
    ) or {}).get("c", 0))

    pending_proposals = int((_db(
        """SELECT COUNT(*) AS c FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
             AND (lower(COALESCE(intended_broker,target_account,proposed_account,'')) LIKE 'schwab%%'
                  OR lower(COALESCE(intended_broker,target_account,proposed_account,'')) LIKE 'fidelity%%')
             AND created_at > NOW() - INTERVAL '7 days'""",
        fetch="one",
    ) or {}).get("c", 0))

    logged_from_proposals = int((_db(
        f"""SELECT COUNT(DISTINCT proposal_id) AS c FROM manual_execution_log
            WHERE executed_at > NOW() - INTERVAL '{window} days' AND proposal_id IS NOT NULL""",
        fetch="one",
    ) or {}).get("c", 0))

    options_cache = 0
    try:
        data = json.loads((STATE_DIR / "options_proposals.json").read_text(encoding="utf-8"))
        options_cache = int(data.get("count") or 0)
    except Exception:
        pass

    options_logged = int((_db(
        f"""SELECT COUNT(*) AS c FROM manual_execution_log
            WHERE executed_at > NOW() - INTERVAL '{window} days'
              AND (execution_type='option' OR origin_type='options_proposal'
                   OR options_proposal_id IS NOT NULL OR origin_id LIKE 'opt_%%')""",
        fetch="one",
    ) or {}).get("c", 0))

    conversion_pct = round(100.0 * logged_from_proposals / max(pending_proposals, 1), 1)
    tagging_pct = round(100.0 * (total - untagged) / max(total, 1), 1)

    return {
        "window_days": window,
        "manual_executions": total,
        "untagged_manual": untagged,
        "tagging_rate_pct": tagging_pct,
        "broker_proposals_pending_7d": pending_proposals,
        "proposal_executions_logged": logged_from_proposals,
        "proposal_conversion_pct": conversion_pct,
        "options_proposals_active": options_cache,
        "options_executions_logged": options_logged,
        "options_conversion_pct": round(100.0 * options_logged / max(options_cache, 1), 1),
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--match", help="Find origins for symbol")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()
    if args.match:
        print(json.dumps(find_origins(args.match.upper()), indent=2, default=str))
    elif args.metrics:
        print(json.dumps(get_tracking_metrics(), indent=2))
    else:
        p.print_help()
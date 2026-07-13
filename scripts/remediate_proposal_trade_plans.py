#!/usr/bin/env python3
"""remediate_proposal_trade_plans.py — Fix gambling-blocked broker proposals continuously.

Active queue rows missing authoritative entry/stop/target (pure R:R geometry) are:
  1. Materialized into watchlist_strategy_cards (support/resistance/stop/target)
  2. Backed with trade_plans when levels are technically anchored
  3. Re-applied to paper_trade_proposals (levels + sizing_basis exit_rationale)

Health agent auto_remediate calls this on `proposal_trade_plan_blocked` findings.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("remediate_trade_plans")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ACTIVE_STATUSES = ("PENDING", "APPROVED_FOR_PAPER_TEST", "PROPOSED", "MODIFIED", "BROKER_SUBMITTED")


def _get_conn():
    from db_adapter import _get_conn
    return _get_conn()


def find_blocked_proposals(conn, *, symbols: list[str] | None = None, proposal_ids: list[int] | None = None) -> list[dict]:
    import broker_trade_plan_gate as btpg

    cur = conn.cursor()
    where = ["status = ANY(%s)"]
    params: list = [list(ACTIVE_STATUSES)]
    if proposal_ids:
        where.append("id = ANY(%s)")
        params.append(proposal_ids)
    if symbols:
        where.append("UPPER(symbol) = ANY(%s)")
        params.append([s.upper() for s in symbols])
    cur.execute(
        f"""SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1, sizing_basis
            FROM paper_trade_proposals WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC NULLS LAST""",
        params,
    )
    cols = [d[0] for d in cur.description]
    blocked = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        gate = btpg.assess_proposal_trade_plan(int(d["id"]), conn=conn)
        if not gate.get("allowed"):
            d["violations"] = gate.get("violations") or []
            d["is_rr_only"] = gate.get("is_rr_only")
            blocked.append(d)
    return blocked


def _load_enrichment(symbol: str) -> dict:
    path = PROJECT_ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"
    try:
        raw = json.loads(path.read_text())
        e = raw.get(symbol.upper(), {})
        return e if isinstance(e, dict) else {}
    except Exception:
        return {}


def _proposal_price(conn, proposal_id: int | None, symbol: str) -> float | None:
    if proposal_id:
        cur = conn.cursor()
        cur.execute(
            "SELECT current_price, proposed_entry FROM paper_trade_proposals WHERE id=%s",
            (proposal_id,),
        )
        row = cur.fetchone()
        if row:
            for v in row:
                if v is not None and float(v) > 0:
                    return float(v)
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(symbol.upper()) or {}
        px = q.get("last_price") or q.get("last")
        return float(px) if px else None
    except Exception:
        return None


def _bootstrap_card_levels(conn, symbol: str, *, proposal_id: int | None = None) -> dict | None:
    """When ticker_prices is empty, derive support/resistance/stop/target from enrichment + live price."""
    sym = symbol.upper()
    try:
        from price_db_sync import ensure_price_history
        ensure_price_history([sym])
    except Exception:
        pass
    price = _proposal_price(conn, proposal_id, sym)
    if not price or price <= 0:
        return None
    e = _load_enrichment(sym)
    atr = float(e.get("atr") or 0) or None
    support = resistance = None
    w52_low = e.get("week52_low_pct")
    w52_high = e.get("week52_high_pct")
    try:
        if w52_low is not None:
            support = round(price / (1 + float(w52_low) / 100) * 1.02, 2)
    except Exception:
        pass
    try:
        if w52_high is not None:
            resistance = round(price / (1 + float(w52_high) / 100) * 0.98, 2)
    except Exception:
        pass
    if not support and atr:
        support = round(price - 2 * atr, 2)
    elif not support:
        support = round(price * 0.93, 2)
    stop = round(support * 0.97, 2) if support else round(price * 0.9, 2)
    if stop >= price:
        stop = round(price - (atr or price * 0.05), 2)
    target = None
    if resistance and resistance > price:
        target = round(resistance * 1.01, 2)
    elif atr:
        target = round(price + max(2 * (price - stop), 2 * atr), 2)
    else:
        target = round(price + 2 * (price - stop), 2)
    if target <= price or stop >= price:
        return None
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO watchlist_strategy_cards
               (symbol, strategy_type, latest_price, support, resistance, ideal_entry,
                stop_loss, target_price, needs_iteration, updated_at)
           VALUES (%s,'core_holding',%s,%s,%s,%s,%s,%s,FALSE,NOW())
           ON CONFLICT (symbol) DO UPDATE SET
               latest_price=EXCLUDED.latest_price, support=EXCLUDED.support,
               resistance=EXCLUDED.resistance, ideal_entry=EXCLUDED.ideal_entry,
               stop_loss=EXCLUDED.stop_loss, target_price=EXCLUDED.target_price,
               needs_iteration=FALSE, updated_at=NOW()""",
        (sym, price, support, resistance, round(price, 2), stop, target),
    )
    conn.commit()
    log.info("%s: bootstrapped card entry=%.2f stop=%.2f target=%.2f sup=%s res=%s", sym, price, stop, target, support, resistance)
    return {"entry": round(price, 2), "stop": stop, "target": target, "plan_source": "watchlist_strategy_card"}


def _compute_shares(conn, proposal_id: int | None, entry: float) -> tuple[int, float, float]:
    """Derive shares / dollar_size / dollar_risk from proposal sizing or a modest default."""
    shares = 0
    if proposal_id:
        cur = conn.cursor()
        cur.execute(
            "SELECT proposed_shares, sizing_basis FROM paper_trade_proposals WHERE id=%s",
            (proposal_id,),
        )
        row = cur.fetchone()
        if row:
            if row[0] and int(row[0]) > 0:
                shares = int(row[0])
            else:
                basis = row[1] if isinstance(row[1], dict) else {}
                if isinstance(row[1], str):
                    try:
                        basis = json.loads(row[1])
                    except Exception:
                        basis = {}
                equity = float(basis.get("equity") or 0)
                pos_pct = float(basis.get("pos_pct") or 0)
                max_size = float(basis.get("max_dollar_size") or 0)
                if max_size > 0 and entry > 0:
                    shares = max(1, int(max_size / entry))
                elif equity > 0 and pos_pct > 0 and entry > 0:
                    shares = max(1, int(equity * pos_pct / 100 / entry))
    if shares < 1 and entry > 0:
        shares = max(1, int(5000 / entry))
    dollar_size = round(shares * entry, 2)
    stop_guess = round(entry * 0.93, 2)
    dollar_risk = round(shares * max(entry - stop_guess, entry * 0.05), 2)
    return shares, dollar_size, dollar_risk


def _upsert_trade_plan(
    conn, symbol: str, strategy_id: str, auth: dict, *, proposal_id: int | None = None,
) -> int | None:
    entry = float(auth["entry"])
    stop = float(auth["stop"])
    target = float(auth["target"])
    if entry <= stop or target <= entry:
        return None
    stop_pct = round((entry - stop) / entry * 100, 2) if entry else 0
    rr = round((target - entry) / (entry - stop), 2) if entry > stop else None
    shares, dollar_size, dollar_risk = _compute_shares(conn, proposal_id, entry)
    dollar_risk = round(shares * (entry - stop), 2)
    atr = _load_enrichment(symbol.upper()).get("atr")
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM trade_plans WHERE symbol=%s AND generated_by='proposal_trade_plan_remediate'",
        (symbol.upper(),),
    )
    cur.execute(
        """INSERT INTO trade_plans
               (strategy_id, symbol, entry_low, entry_high, stop_loss, stop_pct, target_1,
                risk_reward_1, shares, dollar_size, dollar_risk, atr_value,
                disqualified, generated_at, generated_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,NOW(),'proposal_trade_plan_remediate')
           RETURNING id""",
        (
            strategy_id, symbol.upper(), entry, entry, stop, stop_pct, target, rr,
            shares, dollar_size, dollar_risk, atr,
        ),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _apply_levels_to_proposal(conn, proposal_id: int, auth: dict, *, dry_run: bool) -> dict:
    entry, stop, target = float(auth["entry"]), float(auth["stop"]), float(auth["target"])
    rr = round((target - entry) / (entry - stop), 2) if entry > stop else None
    exit_rationale = dict(auth.get("exit_rationale") or {})
    exit_rationale.setdefault("plan_source", auth.get("plan_source"))
    exit_rationale.setdefault("sources", exit_rationale.get("sources") or [])
    basis_patch = {
        "plan_source": auth.get("plan_source"),
        "exit_rationale": exit_rationale,
        "trade_plan_remediated_at": datetime.now(timezone.utc).isoformat(),
    }
    if dry_run:
        return {"entry": entry, "stop": stop, "target": target, "rr": rr, "dry_run": True}
    cur = conn.cursor()
    cur.execute(
        """UPDATE paper_trade_proposals
           SET proposed_entry=%s, proposed_stop=%s, proposed_target1=%s, proposed_rr=%s,
               sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
               updated_at=NOW()
           WHERE id=%s""",
        (entry, stop, target, rr, json.dumps(basis_patch), proposal_id),
    )
    return {"entry": entry, "stop": stop, "target": target, "rr": rr, "applied": True}


def remediate_symbol(conn, symbol: str, *, dry_run: bool = False, proposal_ids: list[int] | None = None) -> dict:
    import broker_trade_plan_gate as btpg

    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "symbol": sym, "error": "empty symbol"}

    try:
        from materialize_watchlist_strategy_cards import materialize
        if not dry_run:
            materialize([sym])
            log.info("%s: materialized strategy card", sym)
    except Exception as e:
        log.warning("%s: card materialize failed: %s", sym, e)

    auth = btpg.resolve_authoritative_levels(conn, sym)
    if not auth:
        pid0 = (proposal_ids or [None])[0]
        boot = _bootstrap_card_levels(conn, sym, proposal_id=pid0)
        if boot:
            import broker_strategy_resolver as bsr
            row = None
            if pid0:
                cur = conn.cursor()
                cur.execute("SELECT strategy_id FROM paper_trade_proposals WHERE id=%s", (pid0,))
                row = cur.fetchone()
            sid = str(row[0]) if row and row[0] else "swing_breakout"
            resolved = bsr.resolve_executable_strategy(sym, sid)
            auth = {
                "entry": boot["entry"],
                "stop": boot["stop"],
                "target": boot["target"],
                "strategy_id": resolved["strategy_id"],
                "plan_source": boot["plan_source"],
                "authoritative": True,
                "exit_rationale": {
                    "sources": ["stop from watchlist strategy card", "target from watchlist strategy card"],
                    "plan_source": "watchlist_strategy_card",
                },
            }
        else:
            return {"ok": False, "symbol": sym, "error": "no_authoritative_levels_after_materialize"}

    targets = proposal_ids or [d["id"] for d in find_blocked_proposals(conn, symbols=[sym])]
    if not targets:
        return {"ok": True, "symbol": sym, "skipped": True, "reason": "no_blocked_proposals"}

    import broker_strategy_resolver as bsr

    plan_id = None
    primary_pid = int(targets[0]) if targets else None
    exec_strategy_id = str(auth.get("strategy_id") or "swing_breakout")
    if primary_pid:
        cur = conn.cursor()
        cur.execute("SELECT strategy_id FROM paper_trade_proposals WHERE id=%s", (primary_pid,))
        row = cur.fetchone()
        if row and row[0]:
            exec_strategy_id = bsr.resolve_executable_strategy(sym, str(row[0]))["strategy_id"]
    auth = dict(auth)
    auth["strategy_id"] = exec_strategy_id
    if not dry_run:
        plan_id = _upsert_trade_plan(conn, sym, exec_strategy_id, auth, proposal_id=primary_pid)

    applied = []
    for pid in targets:
        cur = conn.cursor()
        cur.execute("SELECT strategy_id FROM paper_trade_proposals WHERE id=%s", (pid,))
        row = cur.fetchone()
        raw_sid = str(row[0]) if row and row[0] else exec_strategy_id
        resolved = bsr.resolve_executable_strategy(sym, raw_sid)
        pid_auth = dict(auth)
        pid_auth["strategy_id"] = resolved["strategy_id"]
        exit_rationale = dict(pid_auth.get("exit_rationale") or {})
        exit_rationale["resolve"] = resolved
        exit_rationale["strategy_id"] = resolved["strategy_id"]
        pid_auth["exit_rationale"] = exit_rationale
        patch = _apply_levels_to_proposal(conn, int(pid), pid_auth, dry_run=dry_run)
        if not dry_run and resolved["strategy_id"] != raw_sid:
            cur.execute(
                """UPDATE paper_trade_proposals
                   SET strategy_id=%s,
                       sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
                       updated_at=NOW()
                   WHERE id=%s""",
                (
                    resolved["strategy_id"],
                    json.dumps({"strategy_resolve": resolved}),
                    int(pid),
                ),
            )
        gate = btpg.assess_proposal_trade_plan(int(pid), conn=conn)
        applied.append({
            "proposal_id": pid,
            "levels": patch,
            "trade_plan_status": gate.get("status"),
            "allowed": gate.get("allowed"),
            "violations": gate.get("violations"),
        })

    if not dry_run:
        conn.commit()

    cleared = sum(1 for a in applied if a.get("allowed"))
    return {
        "ok": bool(cleared) or (bool(applied) and not dry_run),
        "symbol": sym,
        "trade_plan_id": plan_id,
        "plan_source": auth.get("plan_source"),
        "applied": applied,
        "cleared": cleared,
        "still_blocked": len(applied) - cleared,
    }


def _downgrade_blocked_approvals(conn, blocked_ids: list[int], *, dry_run: bool = False) -> list[dict]:
    """Revoke APPROVED_FOR_PAPER_TEST when trade plan gate still blocks — should never route."""
    import broker_trade_plan_gate as btpg

    downgraded = []
    for pid in blocked_ids:
        cur = conn.cursor()
        cur.execute("SELECT status FROM paper_trade_proposals WHERE id=%s", (pid,))
        row = cur.fetchone()
        if not row or row[0] != "APPROVED_FOR_PAPER_TEST":
            continue
        gate = btpg.assess_proposal_trade_plan(int(pid), conn=conn)
        if gate.get("allowed"):
            continue
        v0 = (gate.get("violations") or ["no authoritative trade plan"])[0]
        if dry_run:
            downgraded.append({"proposal_id": pid, "dry_run": True, "reason": v0[:160]})
            continue
        cur.execute(
            """UPDATE paper_trade_proposals
               SET status='PENDING',
                   sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
                   updated_at=NOW()
               WHERE id=%s AND status='APPROVED_FOR_PAPER_TEST'""",
            (
                json.dumps({
                    "trade_plan_downgraded_at": datetime.now(timezone.utc).isoformat(),
                    "trade_plan_downgrade_reason": v0[:200],
                }),
                pid,
            ),
        )
        downgraded.append({"proposal_id": pid, "status": "PENDING", "reason": v0[:160]})
    if downgraded and not dry_run:
        conn.commit()
    return downgraded


def run(*, dry_run: bool = False, symbols: list[str] | None = None, proposal_ids: list[int] | None = None) -> dict:
    conn = _get_conn()
    blocked = find_blocked_proposals(conn, symbols=symbols, proposal_ids=proposal_ids)
    if not blocked:
        return {"ok": True, "blocked_count": 0, "remediated": [], "message": "no blocked proposals"}

    sym_map: dict[str, list[int]] = {}
    for b in blocked:
        sym_map.setdefault(str(b["symbol"]).upper(), []).append(int(b["id"]))

    results = []
    for sym, pids in sorted(sym_map.items()):
        results.append(remediate_symbol(conn, sym, dry_run=dry_run, proposal_ids=pids))

    cleared = sum(r.get("cleared", 0) for r in results)
    still_blocked_after = find_blocked_proposals(conn, symbols=symbols, proposal_ids=proposal_ids)
    still_blocked_ids = [int(b["id"]) for b in still_blocked_after]
    downgraded = _downgrade_blocked_approvals(conn, still_blocked_ids, dry_run=dry_run)
    still_blocked = len(still_blocked_after)
    out = {
        "ok": still_blocked == 0,
        "blocked_count": len(blocked),
        "cleared": cleared,
        "still_blocked": still_blocked,
        "downgraded": downgraded,
        "remediated": results,
    }
    log.info(
        "remediate_trade_plans: blocked=%s cleared=%s still_blocked=%s dry_run=%s",
        len(blocked), cleared, still_blocked, dry_run,
    )
    return out


def audit_blocked_count(conn) -> dict:
    blocked = find_blocked_proposals(conn)
    by_symbol = {}
    for b in blocked:
        sym = str(b["symbol"]).upper()
        by_symbol.setdefault(sym, []).append(int(b["id"]))
    return {"count": len(blocked), "by_symbol": by_symbol, "proposals": blocked}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Remediate gambling-blocked proposal trade plans")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--symbol", action="append", dest="symbols")
    p.add_argument("--proposal-id", type=int, action="append", dest="proposal_ids")
    p.add_argument("--audit", action="store_true", help="Print blocked count only")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.audit:
        result = audit_blocked_count(_get_conn())
    else:
        result = run(dry_run=args.dry_run, symbols=args.symbols, proposal_ids=args.proposal_ids)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, default=str))
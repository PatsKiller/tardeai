#!/usr/bin/env python3
"""positions_sync.py — the ONLY writer of the positions store (phase 1, shadow) — operator 2026-10-06.

Plan of record: docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md. Operator, 2026-10-06:
"yes start phase 1 and fix all of it". Phase 1 builds the store alongside holdings.json; nothing reads
it until the phase 3 reader batches are approved one at a time.

Why: on 2026-10-06 PL showed 1,000 shares at a $1,766 cost (+944%) because the 15-minute Schwab position
sync refreshed the share count while the cost basis only refreshed once a day; on 2026-10-05 22 of 27
rows showed stale prices. Both came from many writers sharing one file with no freshness contract.

What one run does (tables: migrations/2026_10_06_positions_store_phase1.sql):
  1. Opens a positions_sync_runs row (the heartbeat) and commits it, so a dead writer is visible.
  2. Reads every enabled live account through its broker's READ-ONLY path (Schwab trader API via
     schwab_transport; Alpaca live and moomoo via their read clients). Never places, changes or
     cancels anything. Never touches Schwab auth.
  3. Rebuilds open lots and realized lots (FIFO) from the broker transaction ledger.
  4. In ONE transaction: appends position_snapshots, rewrites position_lots / realized_lots, and — only
     when every REQUIRED account read succeeded — replaces positions_current for the accounts that
     were read. A partial run is recorded but never becomes current (plan rule 5).
Prices are never stored as truth: broker_market_value is the broker's own figure, for reconciliation.

  positions_sync.py                 # dry run: read brokers, print what would be written
  positions_sync.py --apply         # write (needs the migration applied)
  positions_sync.py --check-fresh   # exit 2 when the latest complete run is older than the contract
  positions_sync.py --diff          # shadow diff: positions_current vs holdings.json (phase 2 report)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

WRITER = "scripts/positions_sync.py"
CONFIG_PATH = ROOT / "config" / "portfolio_positions.yaml"
DIFF_OUT_REL = Path("data") / "runtime" / "positions_shadow_diff_latest.json"

_SYNC_DEFAULTS: dict = {
    # A run is promoted to positions_current only if every one of these was read successfully.
    "required_accounts": ["schwab_rollover_ira", "schwab_roth_ira", "schwab_taxable"],
    # Read when reachable; a failure is recorded and the account keeps its last rows (with their as_of).
    "optional_accounts": ["alpaca_taxable_live", "moomoo_taxable_live"],
    # Which trade_transactions rows are the broker ledger, per account prefix.
    "ledger_import_sources": {"schwab_": ["schwab_api"]},
    "stale_after_minutes_market": 30,
    "stale_after_hours_closed": 72,
    "qty_tolerance": 0.001,
    "basis_tolerance_usd": 1.0,
}

ACQUIRE_KNOWN = {"Buy", "Reinvest Shares", "Reinvested Dividend"}
ACQUIRE_UNKNOWN = {"Security Transfer", "Transfer In", "Journaled Shares", "Journal"}
DISPOSE_SELL = {"Sell"}
# Shares leaving the account without a sale. Since 2026-10-06 the Schwab ingest keeps the direction of transfers
# and share journals (`Security Transfer Out`, `Journaled Shares Out`); before that every one read as an inflow.
DISPOSE_NO_PROCEEDS = {"Transfer Out", "Security Transfer Out", "Journaled Shares Out"}
# holdings.json names the Roth `schwab_roth`; the broker registry (broker_accounts) says `schwab_roth_ira`.
HOLDINGS_ACCOUNT_ALIASES = {"schwab_roth": "schwab_roth_ira"}


# ── config ──────────────────────────────────────────────────────────────────

def load_sync_config(path: Optional[Path] = None) -> dict:
    """`positions_sync:` section of config/portfolio_positions.yaml over the documented defaults."""
    cfg = json.loads(json.dumps(_SYNC_DEFAULTS))
    try:
        import yaml
        raw = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (raw.get("positions_sync") or {}).items() if k in _SYNC_DEFAULTS})
    except Exception:  # noqa: BLE001 — unreadable config falls back to the documented defaults
        pass
    return cfg


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


# ── broker readers (READ-ONLY) ──────────────────────────────────────────────
# Each returns {"ok": True, "cash": float, "equity": float|None, "positions": [row...], "source": str}
# or {"ok": False, "error": str}. A position row: symbol, qty, cost_basis_total, avg_cost,
# broker_market_value, asset_type.

def read_schwab(account_key: str) -> dict:
    import schwab_transport as st  # type: ignore
    acct = st.get_account(account_key)
    if not isinstance(acct, dict) or acct.get("status") not in ("active", None) or "cash" not in acct:
        return {"ok": False, "error": f"account: {str(acct)[:160]}"}
    pos = st.get_positions(account_key)
    if isinstance(pos, dict):
        return {"ok": False, "error": f"positions: {str(pos)[:160]}"}
    rows = []
    for p in pos:
        qty = _f(p.get("qty")) or 0.0
        avg = _f(p.get("avg_entry_price"))
        # Schwab reports averagePrice 0 for delisted CUSIP shells: basis is unknown, not $0.
        cost = round(avg * qty, 2) if avg not in (None, 0.0) else None
        rows.append({"symbol": str(p.get("symbol") or "").upper(), "qty": qty, "avg_cost": avg or None,
                     "cost_basis_total": cost, "broker_market_value": _f(p.get("market_value")),
                     "asset_type": p.get("asset_type")})
    return {"ok": True, "cash": _f(acct.get("cash")) or 0.0, "equity": _f(acct.get("equity")),
            "positions": rows, "source": "schwab_api"}


def read_alpaca_live(account_key: str) -> dict:
    """Alpaca LIVE account (never paper — paper is training only and never counted)."""
    from lib.positions_readers import read_alpaca_live as _r  # type: ignore
    return _r(account_key)


def read_moomoo(account_key: str) -> dict:
    from lib.positions_readers import read_moomoo as _r  # type: ignore
    return _r(account_key)


READERS: dict[str, Callable[[str], dict]] = {
    "schwab": read_schwab,
    "alpaca": read_alpaca_live,
    "moomoo": read_moomoo,
}


def broker_for(account_key: str) -> str:
    return account_key.split("_", 1)[0]


def read_accounts(accounts: Iterable[str], readers: Optional[dict] = None) -> dict:
    readers = readers or READERS
    out = {}
    for ak in accounts:
        fn = readers.get(broker_for(ak))
        if fn is None:
            out[ak] = {"ok": False, "error": f"no read path for broker {broker_for(ak)!r}"}
            continue
        try:
            out[ak] = fn(ak)
        except Exception as e:  # noqa: BLE001 — one broker failing must not abort the others
            out[ak] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
        out[ak]["captured_at"] = datetime.now(timezone.utc)
    return out


# ── lots (pure) ─────────────────────────────────────────────────────────────

def build_lots(txns: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """FIFO open lots and realized lots from broker ledger rows, per account + symbol.

    txn: id, trade_date (date), account, symbol, action, quantity (>0), price, amount, fees.
    Acquisitions with no ledger price (transfers in) open a lot whose basis is UNKNOWN; a sale matched to
    such a lot gets cost/realized_pl None — never a guessed zero (plan: realized_lots).
    """
    queues: dict[tuple, deque] = defaultdict(deque)
    realized: list[dict] = []
    for t in sorted(txns, key=lambda r: (r["trade_date"], r.get("id") or 0)):
        sym = (t.get("symbol") or "").upper()
        qty = abs(_f(t.get("quantity")) or 0.0)
        if not sym or qty <= 0:
            continue
        key = (t["account"], sym)
        action = t.get("action") or ""
        if action in ACQUIRE_KNOWN or action in ACQUIRE_UNKNOWN:
            amount, price = _f(t.get("amount")), _f(t.get("price"))
            unit = None
            if action in ACQUIRE_KNOWN:
                if amount not in (None, 0.0):
                    unit = abs(amount) / qty          # amount is net of fees on Schwab buys
                elif price not in (None, 0.0):
                    unit = price + (_f(t.get("fees")) or 0.0) / qty
            queues[key].append({"account_key": key[0], "symbol": sym, "acquired_on": t["trade_date"],
                                "acquire_action": action, "qty_open": qty, "unit_cost": unit,
                                "basis_known": unit is not None, "source_txn_id": t.get("id")})
        elif action in DISPOSE_SELL or action in DISPOSE_NO_PROCEEDS:
            proceeds_total = abs(_f(t.get("amount")) or 0.0) if action in DISPOSE_SELL else 0.0
            remaining = qty
            q = queues[key]
            while remaining > 1e-9:
                if not q:
                    # Sold shares the ledger never saw acquired (pre-ledger lots): basis unknown.
                    if action in DISPOSE_SELL:
                        realized.append(_realized(t, sym, remaining, proceeds_total * remaining / qty, None, None))
                    break
                lot = q[0]
                take = min(lot["qty_open"], remaining)
                if action in DISPOSE_SELL:
                    realized.append(_realized(t, sym, take, proceeds_total * take / qty, lot, take))
                lot["qty_open"] -= take
                remaining -= take
                if lot["qty_open"] <= 1e-9:
                    q.popleft()
    open_lots = [dict(l, qty_open=round(l["qty_open"], 6)) for q in queues.values() for l in q
                 if l["qty_open"] > 1e-9]
    return open_lots, realized


def _realized(t: dict, sym: str, qty: float, proceeds: float, lot: Optional[dict], take: Optional[float]) -> dict:
    cost = None
    if lot is not None and lot["unit_cost"] is not None:
        cost = round(lot["unit_cost"] * take, 2)
    return {"account_key": t["account"], "symbol": sym, "sold_on": t["trade_date"], "qty": round(qty, 6),
            "proceeds": round(proceeds, 2), "cost": cost,
            "realized_pl": None if cost is None else round(proceeds - cost, 2),
            "acquired_on": lot["acquired_on"] if lot else None, "basis_known": cost is not None,
            "method": "fifo", "sell_txn_id": t.get("id"), "lot_txn_id": lot["source_txn_id"] if lot else None}


# ── run assembly (pure) ─────────────────────────────────────────────────────

def plan_run(reads: dict, required: Iterable[str], open_lots: list[dict]) -> dict:
    """Decide status/promotion and assemble every row the run writes."""
    required = list(required)
    ok = sorted(ak for ak, r in reads.items() if r.get("ok"))
    failed = {ak: r.get("error") for ak, r in reads.items() if not r.get("ok")}
    missing_required = [ak for ak in required if ak not in ok]
    status = "complete" if not missing_required else ("failed" if not ok else "partial")
    lots_by = defaultdict(list)
    for l in open_lots:
        lots_by[(l["account_key"], l["symbol"])].append(l)
    snaps, current = [], []
    for ak in ok:
        r = reads[ak]
        broker = broker_for(ak)
        cap = r["captured_at"]
        rows = list(r.get("positions") or [])
        rows.append({"symbol": "CASH", "qty": r.get("cash") or 0.0, "cost_basis_total": r.get("cash") or 0.0,
                     "avg_cost": 1.0, "broker_market_value": r.get("cash") or 0.0, "asset_type": "CASH",
                     "is_cash": True})
        for p in rows:
            row = {"account_key": ak, "broker": broker, "symbol": p["symbol"], "qty": p["qty"],
                   "cost_basis_total": p.get("cost_basis_total"), "avg_cost": p.get("avg_cost"),
                   "broker_market_value": p.get("broker_market_value"), "is_cash": bool(p.get("is_cash")),
                   "asset_type": p.get("asset_type"), "source": r.get("source") or broker, "captured_at": cap}
            snaps.append(row)
            lots = lots_by.get((ak, p["symbol"]), [])
            current.append(dict(row, lots_count=len(lots),
                                lots_basis_known=(all(l["basis_known"] for l in lots) if lots else None),
                                as_of=cap))
    accounts = {ak: {"cash": reads[ak].get("cash"), "equity": reads[ak].get("equity"),
                     "source": reads[ak].get("source"), "captured_at": reads[ak]["captured_at"].isoformat(),
                     "positions": len(reads[ak].get("positions") or [])} for ak in ok}
    return {"status": status, "promote": status == "complete", "accounts_ok": ok, "accounts_failed": failed,
            "accounts": accounts, "snapshots": snaps, "current": current}


def lot_checks(current: list[dict], open_lots: list[dict], qty_tol: float, basis_tol: float) -> list[dict]:
    """Where the ledger lots do not reproduce the broker position (phase 2 evidence, not an error)."""
    by = defaultdict(lambda: [0.0, 0.0, True])
    for l in open_lots:
        b = by[(l["account_key"], l["symbol"])]
        b[0] += l["qty_open"]
        if l["unit_cost"] is None:
            b[2] = False
        else:
            b[1] += l["unit_cost"] * l["qty_open"]
    out = []
    for c in current:
        if c["is_cash"] or not c["account_key"].startswith("schwab_"):
            continue
        q, cost, known = by.get((c["account_key"], c["symbol"]), [0.0, 0.0, True])
        issues = []
        if abs(q - float(c["qty"])) > qty_tol:
            issues.append(f"ledger lots qty {q:.4f} vs broker {float(c['qty']):.4f}")
        elif known and c["cost_basis_total"] is not None and abs(cost - float(c["cost_basis_total"])) > basis_tol:
            issues.append(f"ledger lots cost {cost:.2f} vs broker {float(c['cost_basis_total']):.2f}")
        if issues:
            out.append({"account_key": c["account_key"], "symbol": c["symbol"], "issues": issues})
    return out


# ── database ────────────────────────────────────────────────────────────────

def _conn():
    from db_adapter import _get_conn  # type: ignore
    return _get_conn()


def _git_sha() -> Optional[str]:
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001 — release dirs have no .git; GIT_SHA is the contract there
        return None


def load_ledger(cur, cfg: dict) -> list[dict]:
    clauses, params = [], []
    for prefix, sources in (cfg.get("ledger_import_sources") or {}).items():
        clauses.append("(account LIKE %s AND import_source = ANY(%s))")
        params += [prefix + "%", list(sources)]
    if not clauses:
        return []
    cur.execute("SELECT id, trade_date, account, symbol, action, quantity, price, amount, fees "
                "FROM trade_transactions WHERE " + " OR ".join(clauses), params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def open_run(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO positions_sync_runs (writer, git_sha) VALUES (%s, %s) RETURNING run_id",
                    (WRITER, _git_sha()))
        run_id = cur.fetchone()[0]
    conn.commit()   # the heartbeat row exists even if the run dies below
    return run_id


def write_run(conn, run_id: int, plan: dict, open_lots: list[dict], realized: list[dict], notes: str) -> None:
    """Everything for one run in ONE transaction (plan rule 5)."""
    from psycopg2.extras import Json, execute_values  # type: ignore
    try:
        with conn.cursor() as cur:
            execute_values(cur, """INSERT INTO position_snapshots (sync_run_id, account_key, broker, symbol, qty,
                cost_basis_total, avg_cost, broker_market_value, is_cash, asset_type, source, captured_at) VALUES %s""",
                [(run_id, s["account_key"], s["broker"], s["symbol"], s["qty"], s["cost_basis_total"], s["avg_cost"],
                  s["broker_market_value"], s["is_cash"], s["asset_type"], s["source"], s["captured_at"])
                 for s in plan["snapshots"]])
            cur.execute("DELETE FROM position_lots")
            execute_values(cur, """INSERT INTO position_lots (sync_run_id, account_key, symbol, acquired_on,
                acquire_action, qty_open, unit_cost, basis_known, source_txn_id) VALUES %s""",
                [(run_id, l["account_key"], l["symbol"], l["acquired_on"], l["acquire_action"], l["qty_open"],
                  l["unit_cost"], l["basis_known"], l["source_txn_id"]) for l in open_lots]) if open_lots else None
            cur.execute("DELETE FROM realized_lots")
            execute_values(cur, """INSERT INTO realized_lots (sync_run_id, account_key, symbol, sold_on, qty, proceeds,
                cost, realized_pl, acquired_on, basis_known, method, sell_txn_id, lot_txn_id) VALUES %s""",
                [(run_id, r["account_key"], r["symbol"], r["sold_on"], r["qty"], r["proceeds"], r["cost"],
                  r["realized_pl"], r["acquired_on"], r["basis_known"], r["method"], r["sell_txn_id"],
                  r["lot_txn_id"]) for r in realized]) if realized else None
            if plan["promote"]:
                cur.execute("DELETE FROM positions_current WHERE account_key = ANY(%s)", (plan["accounts_ok"],))
                execute_values(cur, """INSERT INTO positions_current (account_key, symbol, broker, qty,
                    cost_basis_total, avg_cost, broker_market_value, is_cash, asset_type, lots_count,
                    lots_basis_known, source, as_of, sync_run_id) VALUES %s""",
                    [(c["account_key"], c["symbol"], c["broker"], c["qty"], c["cost_basis_total"], c["avg_cost"],
                      c["broker_market_value"], c["is_cash"], c["asset_type"], c["lots_count"],
                      c["lots_basis_known"], c["source"], c["as_of"], run_id) for c in plan["current"]])
            cur.execute("""UPDATE positions_sync_runs SET finished_at = now(), status = %s, promoted = %s,
                accounts_ok = %s, accounts_failed = %s, accounts = %s, position_rows = %s, lot_rows = %s,
                realized_rows = %s, notes = %s WHERE run_id = %s""",
                (plan["status"], plan["promote"], plan["accounts_ok"], Json(plan["accounts_failed"]),
                 Json(plan["accounts"]), len(plan["snapshots"]), len(open_lots), len(realized), notes[:4000], run_id))
        conn.commit()
    except Exception:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE positions_sync_runs SET finished_at = now(), status = 'failed', notes = %s "
                        "WHERE run_id = %s", ("write failed — see logs/positions_sync.log", run_id))
        conn.commit()
        raise


# ── freshness + shadow diff ─────────────────────────────────────────────────

def market_open_now(now: Optional[datetime] = None) -> bool:
    from zoneinfo import ZoneInfo
    et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    return et.weekday() < 5 and (9 * 60 + 30) <= et.hour * 60 + et.minute <= 16 * 60


def freshness(last_complete: Optional[datetime], cfg: dict, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    limit_s = (cfg["stale_after_minutes_market"] * 60 if market_open_now(now)
               else cfg["stale_after_hours_closed"] * 3600)
    age = None if last_complete is None else (now - last_complete).total_seconds()
    return {"last_complete": last_complete.isoformat() if last_complete else None, "age_s": age,
            "limit_s": limit_s, "stale": age is None or age > limit_s}


def shadow_diff(current: list[dict], store: dict, qty_tol: float, basis_tol: float) -> list[dict]:
    """positions_current vs the holdings.json rows the Command Center serves today."""
    served = {}
    for h in store.get("holdings") or []:
        sym = str(h.get("symbol") or "").upper()
        acct_key = HOLDINGS_ACCOUNT_ALIASES.get(h.get("account"), h.get("account"))
        if sym and acct_key:
            served[(acct_key, "CASH" if h.get("is_cash") else sym)] = h
    out = []
    seen = set()
    for c in current:
        k = (c["account_key"], c["symbol"])
        seen.add(k)
        h = served.get(k)
        if h is None:
            if float(c["qty"] or 0) and not c["is_cash"]:
                out.append({"account_key": k[0], "symbol": k[1], "issue": "MISSING_IN_HOLDINGS_JSON"})
            continue
        issues = []
        sh = _f(h.get("shares") if not c["is_cash"] else h.get("market_value"))
        if sh is not None and abs(sh - float(c["qty"])) > qty_tol:
            issues.append(f"qty store {float(c['qty']):.4f} vs holdings.json {sh:.4f}")
        cb = _f(h.get("cost_basis"))
        if not c["is_cash"] and cb is not None and c["cost_basis_total"] is not None \
                and abs(cb - float(c["cost_basis_total"])) > basis_tol:
            issues.append(f"cost store {float(c['cost_basis_total']):.2f} vs holdings.json {cb:.2f}")
        if issues:
            out.append({"account_key": k[0], "symbol": k[1], "issue": "; ".join(issues)})
    accts = {c["account_key"] for c in current}
    for (ak, sym), h in served.items():
        if ak in accts and (ak, sym) not in seen and not h.get("is_cash") and (_f(h.get("shares")) or 0) > qty_tol:
            out.append({"account_key": ak, "symbol": sym, "issue": "PHANTOM_IN_HOLDINGS_JSON"})
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def _jsonable(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the run (default: dry run)")
    ap.add_argument("--check-fresh", action="store_true", help="exit 2 when positions are stale")
    ap.add_argument("--diff", action="store_true", help="shadow diff positions_current vs holdings.json")
    args = ap.parse_args(argv)
    cfg = load_sync_config()

    if args.check_fresh or args.diff:
        conn = _conn()
        with conn.cursor() as cur:
            cur.execute("SELECT max(finished_at) FROM positions_sync_runs WHERE status = 'complete' AND promoted")
            last = cur.fetchone()[0]
            fresh = freshness(last, cfg)
            report: dict = {"freshness": fresh}
            if args.diff:
                cur.execute("SELECT account_key, symbol, qty, cost_basis_total, is_cash FROM positions_current")
                cols = [d[0] for d in cur.description]
                current = [dict(zip(cols, r)) for r in cur.fetchall()]
                from lib import portfolio_positions as pp  # type: ignore
                diffs = shadow_diff(current, pp.load_store(), cfg["qty_tolerance"], cfg["basis_tolerance_usd"])
                report.update({"generated_at": datetime.now(timezone.utc).isoformat(), "rows": len(current),
                               "differences": diffs})
                out = ROOT / DIFF_OUT_REL
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(report, indent=1, default=_jsonable), encoding="utf-8")
        conn.rollback()
        print(json.dumps(report, indent=1, default=_jsonable))
        return 2 if fresh["stale"] else 0

    accounts = list(dict.fromkeys(list(cfg["required_accounts"]) + list(cfg["optional_accounts"])))
    reads = read_accounts(accounts)
    conn = _conn()
    with conn.cursor() as cur:
        ledger = load_ledger(cur, cfg)
    conn.rollback()
    open_lots, realized = build_lots(ledger)
    plan = plan_run(reads, cfg["required_accounts"], open_lots)
    checks = lot_checks(plan["current"], open_lots, cfg["qty_tolerance"], cfg["basis_tolerance_usd"])
    notes = json.dumps({"lot_checks": checks}, default=_jsonable)
    summary = {"mode": "APPLY" if args.apply else "DRY-RUN", "status": plan["status"], "promote": plan["promote"],
               "accounts_ok": plan["accounts_ok"], "accounts_failed": plan["accounts_failed"],
               "accounts": plan["accounts"], "position_rows": len(plan["snapshots"]), "open_lots": len(open_lots),
               "realized_lots": len(realized), "lot_checks": checks}
    if args.apply:
        run_id = open_run(conn)
        write_run(conn, run_id, plan, open_lots, realized, notes)
        summary["run_id"] = run_id
    print(json.dumps(summary, indent=1, default=_jsonable))
    return 0 if plan["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())

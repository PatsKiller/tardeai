"""Positions read model (Step 3 W0) — one read-only, run-pinned view of the book.

Source of truth: ``position_snapshots`` (immutable rows per ``sync_run_id``) plus
``positions_sync_runs`` (the durable receipt). ``positions_current`` is used ONLY as the
"which run is latest" pointer; no value is read from it.

Contract
--------
* ``rows()`` / ``totals()`` / ``clock()`` each read ONE ``REPEATABLE READ READ ONLY``
  transaction and carry ``sync_run_id`` + ``as_of`` from that same snapshot. Two run ids are
  never mixed.
* Unavailable — DB unreachable, no latest pointer, a mixed pointer, a missing or non-promoted
  receipt, a snapshot whose row count disagrees with the receipt, or an absent/empty/corrupt
  export — returns ``available: false`` with a reason. It never returns an empty book as data.
* ``ACCOUNT_LABEL_MAP`` maps a DB ``account_key`` to the holdings label
  (``schwab_roth_ira`` -> ``schwab_roth``). ``totals()`` groups by label so the Roth is never
  split; ``rows()`` carries both the label and the key.
* Read-only: only SELECT plus BEGIN/COMMIT/ROLLBACK. No writes, no broker calls.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCHEMA = "PositionsReadModel@v1"

#: One declaration, consumed by every view. The DB stores the broker account key; the
#: holdings store and the value anchors use the shorter label.
ACCOUNT_LABEL_MAP: dict[str, str] = {"schwab_roth_ira": "schwab_roth"}

#: Where a generated export would live. It does not exist today; an absent file is
#: ``available: false``, never an empty book.
DEFAULT_EXPORT = Path("data/portfolios/state/holdings_export.json")

#: Cash is a row fact, not only an ``is_cash`` flag: the sync has written cash as a symbol.
_CASH_SYMBOLS = {"CASH", "SPAXX", "FDRXX"}

_SNAPSHOT_COLS = (
    "sync_run_id", "account_key", "broker", "symbol", "qty", "cost_basis_total", "avg_cost",
    "broker_market_value", "is_cash", "asset_type", "source", "captured_at",
)
_RECEIPT_SQL = (
    "select run_id,status,promoted,position_rows,started_at,finished_at,accounts_ok,accounts_failed "
    "from positions_sync_runs where run_id=%s"
)


def label_for(account_key: Any) -> str:
    key = str(account_key or "")
    return ACCOUNT_LABEL_MAP.get(key, key)


def _default_conn():
    from db_adapter import _get_conn  # lazy: importing this module must not open a DB

    return _get_conn()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _num(value: Any) -> Optional[float]:
    """A finite float, or None. NaN is not a number a page may show."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _is_cash(row: dict) -> bool:
    return bool(row.get("is_cash")) or str(row.get("symbol") or "").upper() in _CASH_SYMBOLS


def _price_of(row: dict) -> Optional[float]:
    """A row price is broker market value over quantity; cash is 1.0. Never an invented mark."""
    if _is_cash(row):
        return 1.0
    qty, value = _num(row.get("qty")), _num(row.get("broker_market_value"))
    return round(value / qty, 6) if qty and value is not None else None


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _probe_unavailable(reason: str, **extra: Any) -> dict:
    return {"schema": SCHEMA, "available": False, "reason": reason, **extra}


def load_export(path: Path | str) -> Optional[dict]:
    """A generated export document, or None when it is absent, empty, corrupt or not an object.

    0 bytes is the 2026-11-03 failure class: a damaged file must never be read as an empty book.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _resolve_run(cur, sync_run_id: Optional[int]):
    """The run to read, plus its receipt. ``positions_current`` is only the latest pointer."""
    if sync_run_id is None:
        cur.execute("select distinct sync_run_id from positions_current where sync_run_id is not null")
        vals = [r[0] for r in (cur.fetchall() or [])]
        if not vals:
            return None, _probe_unavailable("no_latest_pointer")
        if len(vals) != 1:
            return None, _probe_unavailable("mixed_latest_pointer", pointer_runs=sorted(int(v) for v in vals))
        run = int(vals[0])
    else:
        run = int(sync_run_id)
    cur.execute(_RECEIPT_SQL, (run,))
    r = cur.fetchone()
    if not r:
        return None, _probe_unavailable("no_sync_receipt", sync_run_id=run)
    receipt = {
        "run_id": int(r[0]), "status": r[1], "promoted": bool(r[2]),
        "position_rows": int(r[3] or 0), "started_at": _iso(r[4]), "finished_at": _iso(r[5]),
        "accounts_ok": list(r[6]) if isinstance(r[6], (list, tuple)) else r[6],
        "accounts_failed": r[7],
    }
    if receipt["status"] != "complete" or not receipt["promoted"]:
        return None, _probe_unavailable(
            "run_not_promoted", sync_run_id=run, status=receipt["status"], promoted=receipt["promoted"]
        )
    if receipt["position_rows"] <= 0:
        # A promoted run with no rows is not a book. Say unavailable; never serve an empty book.
        return None, _probe_unavailable("run_has_no_positions", sync_run_id=run)
    return run, receipt


def _from_export(export_path, reason: str, **extra: Any) -> dict:
    """Serve a generated export, stamped, or say unavailable. Never an empty book."""
    path = export_path
    if path is None:
        path = _project_root() / DEFAULT_EXPORT
    doc = load_export(path)
    if doc is None:
        return _probe_unavailable(reason, export="absent_or_invalid", **extra)
    raw_rows = doc.get("holdings") or doc.get("positions") or []
    if not isinstance(raw_rows, list) or not raw_rows:
        return _probe_unavailable(reason, export="has_no_positions", **extra)
    run = doc.get("sync_run_id")
    if run is None:
        return _probe_unavailable(reason, export="no_sync_run_id", **extra)
    rows = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        key = r.get("account_key") or r.get("account")
        rows.append({
            "sync_run_id": int(run), "account_key": str(key or ""), "account": label_for(key),
            "broker": r.get("broker"), "symbol": r.get("symbol"), "qty": r.get("qty"),
            "cost_basis_total": r.get("cost_basis_total", r.get("cost_basis")),
            "avg_cost": r.get("avg_cost"), "broker_market_value": r.get("broker_market_value", r.get("market_value")),
            "is_cash": bool(r.get("is_cash")), "asset_type": r.get("asset_type"),
            "source": r.get("source") or "export", "as_of": _iso(r.get("as_of") or r.get("captured_at")),
        })
    for row in rows:
        row["is_cash"] = _is_cash(row)
        row["price"] = _price_of(row)
    if not rows:
        return _probe_unavailable(reason, export="has_no_usable_rows", **extra)
    return {
        "schema": SCHEMA, "available": True, "source": "backup", "from_backup": True, "reason": reason,
        "sync_run_id": int(run), "as_of": doc.get("as_of") or doc.get("data_as_of"),
        "rows": rows, "receipt": None, **extra,
    }


def _snapshot(sync_run_id: Optional[int] = None, *, conn_factory=None, export_path=None) -> dict:
    """One read-only transaction: resolve the run, read its receipt and its rows, verify them."""
    conn = None
    try:
        conn = (conn_factory or _default_conn)()
        cur = conn.cursor()
        cur.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            run, receipt = _resolve_run(cur, sync_run_id)
            if run is None:
                cur.execute("ROLLBACK")
                extra = {k: v for k, v in receipt.items() if k not in ("schema", "available", "reason")}
                return _from_export(export_path, receipt["reason"], **extra)
            cur.execute(
                "select " + ",".join(_SNAPSHOT_COLS) + " from position_snapshots "
                "where sync_run_id=%s order by account_key,symbol",
                (run,),
            )
            fetched = cur.fetchall() or []
            cur.execute("ROLLBACK")  # read-only; nothing to commit
        except Exception:
            try:
                cur.execute("ROLLBACK")
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
            raise
    except Exception as exc:  # noqa: BLE001 — an unreachable DB is a fallback, not a crash
        return _from_export(export_path, f"db_unreachable:{type(exc).__name__}",
                            requested_sync_run_id=sync_run_id)
    finally:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:  # noqa: BLE001
            pass

    rows = [dict(zip(_SNAPSHOT_COLS, r)) for r in fetched]
    if len(rows) != receipt["position_rows"]:
        return _probe_unavailable(
            "snapshot_rows_mismatch", sync_run_id=run,
            receipt_rows=receipt["position_rows"], snapshot_rows=len(rows),
        )
    for row in rows:
        if int(row["sync_run_id"]) != run:  # defensive: the WHERE already pins it
            return _probe_unavailable("snapshot_run_mismatch", sync_run_id=run, row_run=row["sync_run_id"])
        row["account"] = label_for(row["account_key"])
        row["as_of"] = _iso(row.pop("captured_at", None))
        row["is_cash"] = _is_cash(row)
        row["price"] = _price_of(row)
    stamps = [row["as_of"] for row in rows if row["as_of"]]
    as_of = max(stamps) if stamps else receipt["finished_at"]
    return {
        "schema": SCHEMA, "available": True, "source": "db", "from_backup": False, "reason": None,
        "sync_run_id": run, "as_of": as_of, "rows": rows, "receipt": receipt,
    }


def rows(account: Optional[str] = None, sync_run_id: Optional[int] = None, *,
         conn_factory=None, export_path=None) -> dict:
    """Run-pinned position rows. ``account`` matches either the label or the DB key."""
    snap = _snapshot(sync_run_id, conn_factory=conn_factory, export_path=export_path)
    if not snap["available"]:
        return snap
    selected = [
        r for r in snap["rows"]
        if account is None or r["account"] == account or r["account_key"] == account
    ]
    return {**snap, "rows": selected, "count": len(selected)}


def totals(sync_run_id: Optional[int] = None, *, conn_factory=None, export_path=None) -> dict:
    """Per-account and portfolio totals, grouped by holdings label (Roth never split)."""
    snap = _snapshot(sync_run_id, conn_factory=conn_factory, export_path=export_path)
    if not snap["available"]:
        return snap
    grouped: dict[str, dict] = {}
    for row in snap["rows"]:
        acct = grouped.setdefault(
            row["account"],
            {"account": row["account"], "account_keys": set(), "total_value": 0.0,
             "total_cash": 0.0, "rows": 0, "as_of": None},
        )
        acct["account_keys"].add(row["account_key"])
        value = float(row["broker_market_value"] or 0)
        acct["total_value"] += value
        if row["is_cash"]:
            acct["total_cash"] += value
        acct["rows"] += 1
        if row["as_of"] and (acct["as_of"] is None or row["as_of"] > acct["as_of"]):
            acct["as_of"] = row["as_of"]
    accounts = []
    for acct in grouped.values():
        total_value = round(acct["total_value"], 2)
        total_cash = round(acct["total_cash"], 2)
        accounts.append({
            "account": acct["account"], "account_keys": sorted(acct["account_keys"]),
            "total_value": total_value, "total_cash": total_cash,
            "invested": round(total_value - total_cash, 2), "rows": acct["rows"], "as_of": acct["as_of"],
        })
    accounts.sort(key=lambda a: a["account"])
    total_value = round(sum(a["total_value"] for a in accounts), 2)
    total_cash = round(sum(a["total_cash"] for a in accounts), 2)
    return {
        "schema": SCHEMA, "available": True, "source": snap["source"], "from_backup": snap["from_backup"],
        "reason": snap["reason"], "sync_run_id": snap["sync_run_id"], "as_of": snap["as_of"],
        "total_value": total_value, "total_cash": total_cash,
        "invested": round(total_value - total_cash, 2), "accounts": accounts, "receipt": snap["receipt"],
    }


def clock(sync_run_id: Optional[int] = None, *, conn_factory=None, export_path=None) -> dict:
    """The run clock: sync_run_id plus the snapshot's own as_of, never a file mtime."""
    snap = _snapshot(sync_run_id, conn_factory=conn_factory, export_path=export_path)
    if not snap["available"]:
        return snap
    receipt = snap.get("receipt") or {}
    return {
        "schema": SCHEMA, "available": True, "source": snap["source"], "from_backup": snap["from_backup"],
        "reason": snap["reason"], "sync_run_id": snap["sync_run_id"], "as_of": snap["as_of"],
        "started_at": receipt.get("started_at"), "finished_at": receipt.get("finished_at"),
    }


def document(sync_run_id: Optional[int] = None, *, conn_factory=None, export_path=None) -> dict:
    """The holdings-document shape consumers already expect, with its provenance.

    This is the bridge cc4's version provided for the ``cio_truth``/Home/Portfolio wiring, now
    run-pinned: the same ``{"holdings": [...], "as_of": ..., "generated_at": ...}`` shape that
    ``portfolio_positions.load_store()`` returns, plus ``source``/``from_backup``/``reason`` so a
    reader can never present one source's numbers as another's, and never invent a price.
    """
    snap = _snapshot(sync_run_id, conn_factory=conn_factory, export_path=export_path)
    if not snap["available"]:
        return snap
    holdings = []
    for r in snap["rows"]:
        holdings.append({
            "account": r["account"], "account_key": r["account_key"], "symbol": r["symbol"],
            "shares": _num(r["qty"]), "qty": _num(r["qty"]),
            "cost_basis_total": _num(r["cost_basis_total"]), "cost_basis": _num(r["cost_basis_total"]),
            "avg_cost": _num(r["avg_cost"]), "market_value": _num(r["broker_market_value"]),
            "broker_market_value": _num(r["broker_market_value"]), "price": r["price"],
            "is_cash": r["is_cash"], "asset_type": r["asset_type"], "broker": r["broker"],
            "sync_run_id": r["sync_run_id"], "updated_at": r["as_of"], "last_repriced": r["as_of"],
            "source": r["source"] or "positions_snapshots",
        })
    as_of = snap["as_of"]
    return {
        "schema": SCHEMA, "available": True, "source": snap["source"], "from_backup": snap["from_backup"],
        "reason": snap["reason"], "sync_run_id": snap["sync_run_id"], "as_of": as_of,
        "row_count": len(holdings),
        "doc": {
            "holdings": holdings, "as_of": as_of, "generated_at": as_of, "last_repriced": as_of,
            "sync_run_id": snap["sync_run_id"], "source": "positions_snapshots",
        },
    }


__all__ = [
    "SCHEMA", "ACCOUNT_LABEL_MAP", "DEFAULT_EXPORT", "label_for", "load_export",
    "rows", "totals", "clock", "document",
]

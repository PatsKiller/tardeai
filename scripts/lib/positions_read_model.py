"""Positions read model (Step 3 W0) — one read-only, run-pinned view of the book.

Source of truth: ``position_snapshots`` (immutable rows per ``sync_run_id``) plus
``positions_sync_runs`` (the durable receipt). ``positions_current`` is used ONLY as the
"which run is latest" pointer; no value is read from it.

Contract
--------
* ``rows()`` / ``totals()`` / ``clock()`` / ``document()`` each read ONE ``REPEATABLE READ
  READ ONLY`` transaction and carry ``sync_run_id`` + ``as_of`` from that same snapshot. Two run
  ids are never mixed, and an explicit ``sync_run_id`` is never satisfied by another run —
  including on the export fallback.
* Unavailable returns ``available: false`` with a reason and **no** ``rows``/``accounts`` key:
  DB unreachable, no/mixed latest pointer, a missing, non-promoted or failed-account receipt, a
  snapshot whose row count or account coverage disagrees with the receipt, a non-finite or
  missing numeric field, or an absent/empty/corrupt/mismatched export.
* The export fallback exists **only** for an unreachable DB. A reachable DB that answers invalid
  or inconsistent state is reported as unavailable; it is never hidden behind a backup file.
* ``ACCOUNT_LABEL_MAP`` maps a DB ``account_key`` to the holdings label
  (``schwab_roth_ira`` -> ``schwab_roth``). Totals group by label so the Roth is never split;
  rows carry both the label and the key.
* Read-only: only SELECT plus BEGIN/COMMIT/ROLLBACK. No writes, no broker calls.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCHEMA = "PositionsReadModel@v1"

def _load_alias_map() -> dict[str, str]:
    """Registry key -> the short label served readers use, from the ONE canonical declaration.

    Step 1's exporter (`holdings_export.account_aliases`) reads the same config, so the DB path and the
    export path label an account identically. Falls back to the Roth entry if the config is absent.
    """
    try:
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config" / "account_display_names.json")
            .read_text(encoding="utf-8")
        )
        aliases = cfg.get("aliases") or {}
        out = {str(registry): str(short) for short, registry in aliases.items() if short and registry}
        return out or {"schwab_roth_ira": "schwab_roth"}
    except (OSError, ValueError):
        return {"schwab_roth_ira": "schwab_roth"}


#: One declaration, consumed by every view. The DB stores the broker account key; the exporter and the
#: holdings store serve the short label. Derived from `config/account_display_names.json` (2026-11-03
#: review: the exporter emits all four aliases; hard-coding only the Roth split the two paths).
ACCOUNT_LABEL_MAP: dict[str, str] = _load_alias_map()

#: Step 1's exporter writes the generated backup as `holdings.json` in the served state root
#: (`scripts/holdings_export.py` STORE_REL). The DB-down fallback reads that file, stamped.
DEFAULT_EXPORT_REL = Path("data/portfolios/state/holdings.json")

#: Cash is a row fact, not only an ``is_cash`` flag: the sync has written cash as a symbol.
_CASH_SYMBOLS = {"CASH", "SPAXX", "FDRXX"}

_SNAPSHOT_COLS = (
    "sync_run_id", "account_key", "broker", "symbol", "qty", "cost_basis_total", "avg_cost",
    "broker_market_value", "is_cash", "asset_type", "source", "captured_at",
)
_RECEIPT_SQL = (
    "select run_id,status,promoted,position_rows,started_at,finished_at,accounts_ok,accounts_failed,"
    "accounts from positions_sync_runs where run_id=%s"
)


def label_for(account_key: Any) -> str:
    key = str(account_key or "")
    return ACCOUNT_LABEL_MAP.get(key, key)


def _default_conn():
    from db_adapter import _get_conn  # lazy: importing this module must not open a DB

    return _get_conn()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_export_path() -> Path:
    """Step 1's export under the persistent state root; the checkout path only if it cannot resolve."""
    try:
        from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415

        return Path(good_persistent_root()) / DEFAULT_EXPORT_REL
    except Exception:  # noqa: BLE001 — a resolution helper must not break the read model
        return _project_root() / DEFAULT_EXPORT_REL


def _num(value: Any) -> Optional[float]:
    """A finite float, or None. NaN, infinity and ints too large for a float are not numbers
    a page may show (the last raises OverflowError, not ValueError)."""
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _is_cash(row: dict) -> bool:
    return bool(row.get("is_cash")) or str(row.get("symbol") or "").upper() in _CASH_SYMBOLS


def _price_of(row: dict) -> Optional[float]:
    """A row price is broker market value over quantity; cash is 1.0. Never an invented mark."""
    if _is_cash(row):
        return 1.0
    qty, value = _num(row.get("qty")), _num(row.get("broker_market_value"))
    return round(value / qty, 6) if qty and value is not None else None


def _numeric_problems(row: dict) -> list[str]:
    """Fields that must be finite: qty and market value always; basis fields when present."""
    bad = [f for f in ("qty", "broker_market_value") if _num(row.get(f)) is None]
    bad += [f for f in ("cost_basis_total", "avg_cost") if row.get(f) is not None and _num(row.get(f)) is None]
    return bad


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
        "accounts": r[8] if len(r) > 8 and isinstance(r[8], dict) else None,
    }
    if receipt["status"] != "complete" or not receipt["promoted"]:
        return None, _probe_unavailable(
            "run_not_promoted", sync_run_id=run, status=receipt["status"], promoted=receipt["promoted"]
        )
    if receipt["position_rows"] <= 0:
        # A promoted run with no rows is not a book. Say unavailable; never serve an empty book.
        return None, _probe_unavailable("run_has_no_positions", sync_run_id=run)
    if receipt["accounts_failed"]:
        # A run with failed accounts is partial. The receipt says so; do not serve it as whole.
        return None, _probe_unavailable(
            "run_has_failed_accounts", sync_run_id=run, accounts_failed=receipt["accounts_failed"]
        )
    if not isinstance(receipt["accounts_ok"], list) or not receipt["accounts_ok"]:
        return None, _probe_unavailable("run_has_no_account_coverage", sync_run_id=run)
    detail = receipt["accounts"]
    if not isinstance(detail, dict) or not detail:
        # The per-account detail is the completeness proof. Without it a zero-position account
        # and a LOST account are indistinguishable, so a receipt that does not carry it is
        # unavailable — never treated as complete (2026-11-03 codex review).
        return None, _probe_unavailable("receipt_account_detail_missing", sync_run_id=run)
    if set(detail) != set(receipt["accounts_ok"]):
        # The two receipt views must name the same accounts. A run whose `accounts` detail and
        # `accounts_ok` list disagree is a booking defect; refuse rather than pick one.
        return None, _probe_unavailable(
            "receipt_account_views_disagree", sync_run_id=run,
            accounts_ok=sorted(receipt["accounts_ok"]), accounts_detail=sorted(detail),
        )
    return run, receipt


def _from_export(export_path, reason: str, requested_sync_run_id: Optional[int] = None) -> dict:
    """Serve a generated export for an unreachable DB, or say unavailable. Never an empty book.

    An explicit run request is honoured exactly: an export for a different run is unavailable,
    never re-labelled. Field aliases accept both this model's shape and the Step 1 export shape.
    """
    path = Path(export_path) if export_path is not None else default_export_path()
    stamp = {"export_path": str(path), "requested_sync_run_id": requested_sync_run_id}
    doc = load_export(path)
    if doc is None:
        return _probe_unavailable(reason, export="absent_or_invalid", **stamp)
    source_doc = doc.get("doc") if isinstance(doc.get("doc"), dict) else doc
    raw_rows = source_doc.get("holdings") or source_doc.get("positions") or []
    if not isinstance(raw_rows, list) or not raw_rows:
        return _probe_unavailable(reason, export="has_no_positions", **stamp)
    run = source_doc.get("sync_run_id", doc.get("sync_run_id"))
    if run is None:
        run = source_doc.get("run_id", doc.get("run_id"))
    if run is None:
        rebuild = source_doc.get("_rebuild") or doc.get("_rebuild") or {}
        if not isinstance(rebuild, dict):
            rebuild = {}
        run = rebuild.get("run") or rebuild.get("sync_run_id")
    if run is None:
        return _probe_unavailable(reason, export="no_sync_run_id", **stamp)
    if isinstance(run, bool) or not isinstance(run, (int, float)):
        return _probe_unavailable(reason, export="sync_run_id_invalid", raw_run_id=repr(run), **stamp)
    try:
        # An exact integer run id: 641.9 must not truncate to 641, and Infinity/10**400 must
        # not raise out of the reader (2026-11-03 codex review).
        if not math.isfinite(float(run)) or int(run) != run:
            return _probe_unavailable(reason, export="sync_run_id_invalid", raw_run_id=repr(run), **stamp)
    except (TypeError, ValueError, OverflowError):
        return _probe_unavailable(reason, export="sync_run_id_invalid", raw_run_id=repr(run), **stamp)
    run = int(run)
    if requested_sync_run_id is not None and run != int(requested_sync_run_id):
        return _probe_unavailable(
            "export_run_mismatch", export_sync_run_id=run, **stamp,
        )
    invalid = [i for i, r in enumerate(raw_rows) if not isinstance(r, dict)]
    if invalid:
        # A partly malformed export is not a partial book: drop nothing silently.
        return _probe_unavailable(reason, export="member_not_object", invalid_rows=invalid[:10], **stamp)
    rows = []
    for r in raw_rows:
        key = r.get("account_key") or r.get("account")
        rows.append({
            "sync_run_id": run, "account_key": str(key or ""), "account": label_for(key),
            "broker": r.get("broker"), "symbol": r.get("symbol"),
            "qty": r.get("qty", r.get("shares", r.get("quantity"))),
            "cost_basis_total": r.get("cost_basis_total", r.get("cost_basis")),
            "avg_cost": r.get("avg_cost"),
            "broker_market_value": r.get("broker_market_value", r.get("market_value")),
            "is_cash": bool(r.get("is_cash")), "asset_type": r.get("asset_type"),
            "source": r.get("source") or "export", "as_of": _iso(r.get("as_of") or r.get("captured_at")),
        })
    for row in rows:
        row["is_cash"] = _is_cash(row)
        row["price"] = _price_of(row)
    if not rows:
        return _probe_unavailable(reason, export="has_no_usable_rows", **stamp)
    bad = [{"account": x["account"], "symbol": x["symbol"], "fields": _numeric_problems(x)}
           for x in rows if _numeric_problems(x)]
    if bad:
        return _probe_unavailable(reason, export="numeric_invalid", invalid_rows=bad[:10], **stamp)
    return {
        "schema": SCHEMA, "available": True, "source": "backup", "from_backup": True, "reason": reason,
        "sync_run_id": run, "as_of": source_doc.get("as_of") or document_as_of(source_doc),
        "rows": rows, "receipt": None,
        "coverage": {"rows": len(rows), "accounts": sorted({x["account_key"] for x in rows})},
        **stamp,
    }


def document_as_of(doc: dict) -> Optional[str]:
    return _iso(doc.get("as_of") or doc.get("data_as_of") or doc.get("generated_at"))


def _snapshot(sync_run_id: Optional[int] = None, *, conn_factory=None, export_path=None) -> dict:
    """One read-only transaction: resolve the run, read its receipt and its rows, verify them.

    The export fallback is used ONLY when the DB cannot be reached. A reachable DB that answers
    an invalid or inconsistent state is reported unavailable — never masked by a backup file.
    """
    conn = None
    try:
        conn = (conn_factory or _default_conn)()
        cur = conn.cursor()
        cur.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            run, receipt = _resolve_run(cur, sync_run_id)
            if run is None:
                cur.execute("ROLLBACK")
                return receipt  # reachable DB, invalid state: unavailable, no fallback
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
    except Exception as exc:  # noqa: BLE001 — an unreachable DB is the only fallback trigger
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
    row_accounts = {str(row["account_key"]) for row in rows}
    receipt_accounts = {str(a) for a in receipt["accounts_ok"]}
    uncovered = sorted(row_accounts - receipt_accounts)
    if uncovered:
        # The receipt is the coverage contract. A row from an account it does not claim means
        # the snapshot and the receipt are not one observation; refuse rather than guess.
        return _probe_unavailable(
            "snapshot_account_not_in_receipt", sync_run_id=run,
            missing_accounts=uncovered, receipt_accounts_ok=sorted(receipt_accounts),
        )
    detail = receipt.get("accounts")
    if detail:
        # Both directions: the receipt's per-account position count must equal the snapshot's
        # non-cash rows for that account (a zero-position account is legitimate and has no rows).
        mismatched = []
        for acct, info in detail.items():
            positions = info.get("positions") if isinstance(info, dict) else None
            if (not isinstance(info, dict) or isinstance(positions, bool)
                    or not isinstance(positions, int)):
                # An UNKNOWN per-account count is not a legitimate zero-position account, and a
                # non-numeric count must not raise out of rows()/totals()/clock()/document().
                return _probe_unavailable("receipt_account_detail_invalid", sync_run_id=run,
                                          account=acct, detail=info)
            expected = positions
            actual = sum(1 for row in rows if str(row["account_key"]) == str(acct) and not row["is_cash"])
            if expected != actual:
                mismatched.append({"account": acct, "receipt_positions": expected, "snapshot_positions": actual})
        if mismatched:
            return _probe_unavailable("snapshot_account_positions_mismatch", sync_run_id=run,
                                      accounts=mismatched[:10])
    bad = [(row["account_key"], row["symbol"], _numeric_problems(row))
           for row in rows if _numeric_problems(row)]
    if bad:
        return _probe_unavailable("snapshot_row_numeric_invalid", sync_run_id=run, invalid_rows=bad[:10])
    for row in rows:
        row["account"] = label_for(row["account_key"])
        row["as_of"] = _iso(row.pop("captured_at", None))
        row["is_cash"] = _is_cash(row)
        row["price"] = _price_of(row)
    stamps = [row["as_of"] for row in rows if row["as_of"]]
    as_of = max(stamps) if stamps else receipt["finished_at"]
    return {
        "schema": SCHEMA, "available": True, "source": "db", "from_backup": False, "reason": None,
        "sync_run_id": run, "as_of": as_of, "rows": rows, "receipt": receipt,
        "coverage": {"rows": len(rows), "accounts": sorted(row_accounts),
                     "receipt_accounts_ok": sorted(receipt_accounts)},
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


def _grouped(rows_: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows_:
        acct = grouped.setdefault(
            row["account"],
            {"account": row["account"], "account_keys": set(), "total_value": 0.0,
             "total_cash": 0.0, "rows": 0, "as_of": None},
        )
        acct["account_keys"].add(row["account_key"])
        value = float(row["broker_market_value"])
        acct["total_value"] += value
        if row["is_cash"]:
            acct["total_cash"] += value
        acct["rows"] += 1
        if row["as_of"] and (acct["as_of"] is None or row["as_of"] < acct["as_of"]):
            acct["as_of"] = row["as_of"]
    out = []
    for acct in grouped.values():
        total_value = round(acct["total_value"], 2)
        total_cash = round(acct["total_cash"], 2)
        out.append({
            "account": acct["account"], "account_keys": sorted(acct["account_keys"]),
            "total_value": total_value, "total_cash": total_cash,
            "invested": round(total_value - total_cash, 2), "rows": acct["rows"], "as_of": acct["as_of"],
        })
    out.sort(key=lambda a: a["account"])
    return out


def totals(sync_run_id: Optional[int] = None, *, conn_factory=None, export_path=None) -> dict:
    """Per-account and portfolio totals, grouped by holdings label (Roth never split)."""
    snap = _snapshot(sync_run_id, conn_factory=conn_factory, export_path=export_path)
    if not snap["available"]:
        return snap
    accounts = _grouped(snap["rows"])
    total_value = round(sum(a["total_value"] for a in accounts), 2)
    total_cash = round(sum(a["total_cash"] for a in accounts), 2)
    return {
        "schema": SCHEMA, "available": True, "source": snap["source"], "from_backup": snap["from_backup"],
        "reason": snap["reason"], "sync_run_id": snap["sync_run_id"], "as_of": snap["as_of"],
        "total_value": total_value, "total_cash": total_cash,
        "invested": round(total_value - total_cash, 2), "accounts": accounts,
        "coverage": snap["coverage"], "receipt": snap["receipt"],
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

    Carries the producer shape (``holdings``, ``portfolio_totals``, ``account_summaries``,
    ``as_of``, ``generated_at``, ``last_repriced``) plus ``source``/``from_backup``/``reason`` so a
    reader can never present one source's numbers as another's, and never invent a price. The
    per-account classification fields (``account_state``) are added by ``lib.account_state`` at the
    caller, as with every other holdings document.
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
    accounts = _grouped(snap["rows"])
    total_value = round(sum(a["total_value"] for a in accounts), 2)
    total_cash = round(sum(a["total_cash"] for a in accounts), 2)
    non_cash = [r for r in snap["rows"] if not r["is_cash"]]
    unsourced = [r for r in non_cash if _num(r["cost_basis_total"]) is None]
    basis_complete = not unsourced
    cost = round(sum(float(r["cost_basis_total"]) for r in non_cash), 2) if basis_complete else None
    gain = round(total_value - total_cash - cost, 2) if basis_complete and cost is not None else None
    totals_block = {
        "as_of": as_of, "total_value": total_value, "total_cash": total_cash,
        "total_cost_basis": cost, "total_gain": gain,
        "total_gain_pct": (round(gain / cost * 100, 4) if gain is not None and cost else None),
        "basis_complete": basis_complete, "basis_unsourced_rows": len(unsourced),
        "basis_note": ("all non-cash rows have sourced basis" if basis_complete else
                       f"aggregate basis/P&L left NULL: {len(unsourced)} non-cash row(s) have no sourced "
                       "basis — partial sums are not published as totals"),
        "note": f"read model run {snap['sync_run_id']}; day change is not carried",
    }
    summaries = {
        a["account"]: {"value": a["total_value"], "cash": a["total_cash"], "positions": a["rows"],
                       "as_of": a["as_of"], "account_keys": a["account_keys"]}
        for a in accounts
    }
    return {
        "schema": SCHEMA, "available": True, "source": snap["source"], "from_backup": snap["from_backup"],
        "reason": snap["reason"], "sync_run_id": snap["sync_run_id"], "as_of": as_of,
        "row_count": len(holdings), "coverage": snap["coverage"],
        "doc": {
            "holdings": holdings, "portfolio_totals": totals_block, "account_summaries": summaries,
            "as_of": as_of, "generated_at": as_of, "last_repriced": as_of,
            "sync_run_id": snap["sync_run_id"], "source": "positions_snapshots",
        },
    }


__all__ = [
    "SCHEMA", "ACCOUNT_LABEL_MAP", "DEFAULT_EXPORT_REL", "label_for", "load_export",
    "default_export_path", "rows", "totals", "clock", "document",
]

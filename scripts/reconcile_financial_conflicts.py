#!/usr/bin/env python3
"""Build the record-level conflict ledger for the divergent financial truth stores.

Read-only end to end. It queries broker positions and order state, compares the two
copies of each store record by record, and assigns exactly one disposition per record.
It writes one evidence file and nothing else. It never touches a state store, and it
never places, changes, cancels or simulates an order.

    python3 scripts/reconcile_financial_conflicts.py \
        --authority evidence/whole_site/BROKER_AUTHORITY_SNAPSHOT.json \
        --out evidence/whole_site/CONFLICT_LEDGER.json

Capture the authority snapshot first with --capture-authority, which is the only mode
that talks to a broker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.financial_reconciliation import (  # noqa: E402
    AUTO_MIGRATABLE,
    CLOCK_DERIVED_FIELDS,
    UNRESOLVED_OPERATOR_REVIEW,
    BrokerAuthority,
    audit_store_integrity,
    is_envelope_key,
    reconcile_clock_derived,
    reconcile_derived_store,
    reconcile_envelope_key,
    reconcile_missing_side_record,
    reconcile_missing_stop_record,
    reconcile_stop_record,
    reconcile_tax_lot_record,
)

SCHEMA = "FinancialConflictLedger@v1"
CALC_VERSION = "1.0.0"

SCHWAB_ACCOUNTS = ("schwab_taxable", "schwab_rollover_ira", "schwab_roth_ira")

#: Stores this ledger governs, and how each one is reconciled.
GOVERNED = {
    "stops.json": "indexed",
    "tax_lots.json": "indexed",
    "trade_journal.json": "clock_derived",
    "performance_history.json": "derived",
    "performance_attribution.json": "derived",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture_authority(out_path: Path) -> int:
    """The only mode that talks to a broker. Read-only: positions and order state."""
    sys.path.insert(0, str(Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild") / "scripts"))
    import schwab_transport as st  # noqa: PLC0415

    snap: dict[str, Any] = {
        "schema": "BrokerAuthoritySnapshot@v1",
        "authority": "READ_ONLY_BROKER_TRUTH",
        "captured_at_utc": _now(),
        "note": "positions and order state only; no order was placed, changed, cancelled or simulated",
        "brokers": {},
    }
    for ak in SCHWAB_ACCOUNTS:
        entry: dict[str, Any] = {
            "broker": "schwab",
            "account_key": ak,
            "environment": "live",
            "observed_at_utc": _now(),
        }
        try:
            entry["positions"] = st.get_positions(ak)
            entry["positions_status"] = "OK"
        except Exception as exc:  # noqa: BLE001
            entry["positions"], entry["positions_status"] = None, f"ERROR {type(exc).__name__}: {exc}"
        try:
            entry["orders"] = st.get_orders(ak)
            entry["orders_status"] = "OK"
        except Exception as exc:  # noqa: BLE001
            entry["orders"], entry["orders_status"] = None, f"ERROR {type(exc).__name__}: {exc}"
        # An account that returned nothing is refused rather than believed. "Empty"
        # and "unreadable" look identical downstream, and only one of them is safe.
        entry["accepted"] = (
            entry["positions_status"] == "OK" and isinstance(entry["positions"], list) and len(entry["positions"]) > 0
        )
        snap["brokers"][ak] = entry

    body = json.dumps(snap, indent=1, sort_keys=True, default=str)
    snap["snapshot_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snap, indent=1, sort_keys=True, default=str) + "\n")
    ok = sum(1 for e in snap["brokers"].values() if e["accepted"])
    print(f"authority snapshot: {out_path}")
    print(f"accounts accepted: {ok}/{len(SCHWAB_ACCOUNTS)}  sha256={snap['snapshot_sha256']}")
    return 0 if ok else 2


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _records(doc: Any) -> dict[str, Any]:
    return doc if isinstance(doc, dict) else {}


def _differing_fields(a: Any, b: Any) -> list[str]:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return []
    return sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))


def reconcile_indexed(store: str, p_doc: Any, s_doc: Any, auth: BrokerAuthority) -> list[dict]:
    """Compare an indexed collection record by record."""
    p, s = _records(p_doc), _records(s_doc)
    out: list[dict] = []
    is_stops = store == "stops.json"
    for key in sorted(set(p) | set(s)):
        in_p, in_s = key in p, key in s
        if in_p and in_s and p[key] == s[key]:
            continue  # identical records are not conflicts and are not in the ledger
        if is_envelope_key(key):
            out.append(reconcile_envelope_key(store, key, p.get(key), s.get(key)))
            continue
        if in_p and in_s:
            out.append(
                reconcile_stop_record(key, p[key], s[key], auth)
                if is_stops
                else reconcile_tax_lot_record(key, p[key], s[key], auth)
            )
            continue
        # Present on one side only. A stop is an order and is decided by live order
        # state; a lot record is a holding and is decided by position quantity. Routing
        # a stop through lot arithmetic asks a question the record cannot answer, and
        # produced four false UNRESOLVED verdicts on real protective coverage.
        side = "producer" if in_p else "served"
        value = p[key] if in_p else s[key]
        out.append(
            reconcile_missing_stop_record(key, value, side, auth)
            if is_stops
            else reconcile_missing_side_record(store, key, value, side, auth)
        )
    return out


def reconcile_clock_store(store: str, p_doc: Any, s_doc: Any) -> list[dict]:
    """trade_journal: the only divergence is a clock-derived field on each open lot."""
    out: list[dict] = []
    p_lots = (p_doc or {}).get("open_lots") or []
    s_lots = (s_doc or {}).get("open_lots") or []

    def ident(lot: dict) -> tuple:
        return (lot.get("symbol"), lot.get("account"), lot.get("lot_date"), lot.get("shares"))

    s_by = {ident(x): x for x in s_lots}
    non_clock: list[str] = []
    clock_hits: set[str] = set()
    n = 0
    for lot in p_lots:
        other = s_by.get(ident(lot))
        if other is None or lot == other:
            continue
        diff = _differing_fields(lot, other)
        extra = [f for f in diff if f not in CLOCK_DERIVED_FIELDS]
        clock_hits.update(f for f in diff if f in CLOCK_DERIVED_FIELDS)
        n += 1
        if extra:
            non_clock.append(f"{ident(lot)}:{extra}")

    if n and not non_clock:
        out.append(reconcile_clock_derived(store, "open_lots[*]", None, None, sorted(clock_hits)))
    elif non_clock:
        from lib.financial_reconciliation import _verdict  # noqa: PLC0415

        out.append(
            _verdict(
                store,
                "open_lots[*]",
                UNRESOLVED_OPERATOR_REVIEW,
                f"{len(non_clock)} open lot(s) differ in fields that are not clock-derived: {non_clock[:5]}",
                authorities=["canonical:executions"],
                rule="executions are deduplicated by broker, account, execution id, instrument, side, "
                "quantity, price and time; distinct executions are never collapsed on a symbol/date match",
            )
        )
    return out


def build_ledger(producer_root: Path, served_root: Path, auth: BrokerAuthority) -> dict[str, Any]:
    entries: list[dict] = []
    store_summary: dict[str, Any] = {}

    for store, mode in GOVERNED.items():
        p_path, s_path = producer_root / store, served_root / store
        if not p_path.exists() or not s_path.exists():
            continue
        p_doc, s_doc = _load(p_path), _load(s_path)
        if mode == "indexed":
            rows = reconcile_indexed(store, p_doc, s_doc, auth)
        elif mode == "clock_derived":
            rows = reconcile_clock_store(store, p_doc, s_doc)
        else:
            rows = [
                reconcile_derived_store(
                    store,
                    p_doc,
                    s_doc,
                    "The two copies are the same calculation evaluated over different observation "
                    "windows, not two claims about one interval.",
                )
            ]
        entries.extend(rows)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
        store_summary[store] = {
            "mode": mode,
            "conflicting_records": len(rows),
            "dispositions": counts,
            "unresolved": sum(1 for r in rows if r["disposition"] == UNRESOLVED_OPERATOR_REVIEW),
            "producer_sha256": hashlib.sha256(p_path.read_bytes()).hexdigest(),
            "served_sha256": hashlib.sha256(s_path.read_bytes()).hexdigest(),
        }

    # Integrity is a separate question from reconciliation: a record can be identical
    # on both sides and still be incoherent. Those never reach a conflict ledger.
    integrity: dict[str, Any] = {}
    for store in ("tax_lots.json",):
        s_path = served_root / store
        if s_path.exists():
            integrity[store] = audit_store_integrity(store, _load(s_path), auth)

    totals: dict[str, int] = {}
    for r in entries:
        totals[r["disposition"]] = totals.get(r["disposition"], 0) + 1

    ledger = {
        "schema": SCHEMA,
        "calculation_version": CALC_VERSION,
        "authority": "READ_ONLY_RECONCILIATION",
        "generated_at_utc": _now(),
        "producer_root": str(producer_root),
        "served_root": str(served_root),
        "authority_snapshot_sha256": auth.snapshot.get("snapshot_sha256"),
        "authority_captured_at_utc": auth.captured_at,
        "accounts_accepted": sorted(auth.accepted_accounts),
        "accounts_rejected": auth.rejected_accounts,
        "rule": (
            "A value becomes canonical because an authority asserts it or because it can be rebuilt "
            "from canonical inputs. Never because its file was written later."
        ),
        "store_summary": store_summary,
        "disposition_totals": totals,
        "integrity_audit": integrity,
        "quarantined_record_count": sum(v["records_quarantined"] for v in integrity.values()),
        "conflicting_record_count": len(entries),
        "unresolved_record_count": sum(1 for r in entries if r["disposition"] == UNRESOLVED_OPERATOR_REVIEW),
        "auto_migratable_record_count": sum(1 for r in entries if r["disposition"] in AUTO_MIGRATABLE),
        "records": entries,
    }
    ledger["ledger_sha256"] = ledger_hash(ledger)
    return ledger


#: Fields recording WHEN a decision was made rather than WHAT was decided. They are
#: excluded from the ledger hash so regenerating against unchanged authority and
#: unchanged stores reproduces the same digest. A hash that moves on every run pins
#: nothing -- and the migration manifest binds this value.
LEDGER_VOLATILE_FIELDS = ("generated_at_utc", "ledger_sha256", "_operator_flags")
RECORD_VOLATILE_FIELDS = ("decided_at_utc",)


def ledger_hash(ledger: dict[str, Any]) -> str:
    """Hash the decisions, not the clock."""
    body = {k: v for k, v in ledger.items() if k not in LEDGER_VOLATILE_FIELDS}
    body["records"] = [
        {k: v for k, v in r.items() if k not in RECORD_VOLATILE_FIELDS} for r in ledger.get("records", [])
    ]
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def build_operator_review(ledger: dict[str, Any]) -> dict[str, Any]:
    """Per-lot reconciliation rows for records no authority could settle.

    This states the question and the evidence. It does not answer it: the answer is a
    cost-basis decision with tax consequences, and nothing available here can prove it.
    """
    rows: list[dict[str, Any]] = []
    for rec in ledger["records"]:
        if rec["disposition"] != UNRESOLVED_OPERATOR_REVIEW:
            continue
        obs = rec.get("observations") or {}
        broker_qty = obs.get("broker_position_qty")
        for side in ("producer", "served"):
            for lot in obs.get(f"{side}_synthetic_lots") or []:
                rows.append(
                    {
                        "store": rec["store"],
                        "record_key": rec["record_key"],
                        "side": side,
                        "lot_index": lot.get("index"),
                        "lot_date": lot.get("lot_date"),
                        "shares": lot.get("shares"),
                        "shares_remaining": lot.get("shares_remaining"),
                        "account_in_lot": lot.get("account_in_lot"),
                        "record_key_account": rec["record_key"].split(":", 1)[-1],
                        "account_matches_record_key": lot.get("account_in_lot") == rec["record_key"].split(":", 1)[-1],
                        "source": lot.get("source"),
                        "synthetic_kind": lot.get("synthetic_kind"),
                        "basis_state": lot.get("basis_state"),
                        "broker_position_qty": broker_qty,
                        "broker_exposes_lots": False,
                        "decision_required": (
                            "confirm whether this lot is real, and if so its acquisition date, share "
                            "count and adjusted cost basis"
                        ),
                    }
                )
        # Name what is odd without claiming it is the answer.
        flags = []
        p_lots = obs.get("producer_synthetic_lots") or []
        seen: dict[tuple, int] = {}
        for lot in p_lots:
            k = (lot.get("shares"), lot.get("shares_remaining"))
            seen[k] = seen.get(k, 0) + 1
        dupes = [k for k, n in seen.items() if n > 1]
        if dupes:
            flags.append(
                f"the producer copy holds {len(dupes)} share-count value(s) more than once on "
                "different dates, which is the shape a re-run duplicate leaves; it is not proof of one"
            )
        mismatched = [r for r in rows if r["record_key"] == rec["record_key"] and not r["account_matches_record_key"]]
        if mismatched:
            flags.append(
                f"{len(mismatched)} lot(s) name an account different from the one in the record key, "
                "so the record is not internally consistent in either copy"
            )
        rec_flags = {"record_key": rec["record_key"], "store": rec["store"], "observations_worth_noting": flags}
        ledger.setdefault("_operator_flags", []).append(rec_flags)

    return {
        "schema": "OperatorLotReconciliation@v1",
        "generated_at_utc": _now(),
        "authority": "OPERATOR_DECISION_REQUIRED",
        "ledger_sha256": ledger["ledger_sha256"],
        "unresolved_record_count": ledger["unresolved_record_count"],
        "lot_row_count": len(rows),
        "instruction": (
            "For each record below, name which side is authoritative or supply the correct lots from "
            "the broker statement or an external record. Until then both copies are preserved, the "
            "affected basis renders UNVERIFIED, and no disputed value is shown as truth."
        ),
        "flags": ledger.get("_operator_flags", []),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--capture-authority",
        action="store_true",
        help="query the brokers read-only and write the authority snapshot; the only mode that connects",
    )
    ap.add_argument("--authority", help="path to a previously captured authority snapshot")
    ap.add_argument(
        "--producer-root", default="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state"
    )
    ap.add_argument("--served-root", default="/home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state")
    ap.add_argument("--out", required=True)
    ap.add_argument("--operator-review", help="also write the per-lot operator reconciliation record here")
    args = ap.parse_args(argv)

    if args.capture_authority:
        return capture_authority(Path(args.out))

    if not args.authority:
        print("--authority is required unless --capture-authority is given", file=sys.stderr)
        return 2

    auth = BrokerAuthority(json.loads(Path(args.authority).read_text()))
    if not auth.accepted_accounts:
        print("refusing: no broker account produced an accepted read; nothing can be decided", file=sys.stderr)
        return 2

    ledger = build_ledger(Path(args.producer_root), Path(args.served_root), auth)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, indent=1, sort_keys=False, default=str) + "\n")

    print(f"conflict ledger: {out}")
    print(f"ledger_sha256: {ledger['ledger_sha256']}")
    print(f"conflicting records: {ledger['conflicting_record_count']}")
    for d, n in sorted(ledger["disposition_totals"].items()):
        print(f"  {d:34} {n}")
    if args.operator_review:
        review = build_operator_review(ledger)
        Path(args.operator_review).write_text(json.dumps(review, indent=1, default=str) + "\n")
        print(f"operator review: {args.operator_review} ({review['lot_row_count']} lot rows)")
        for f in review["flags"]:
            for note in f["observations_worth_noting"]:
                print(f"  note [{f['record_key']}]: {note}")
    for st, v in (ledger.get("integrity_audit") or {}).items():
        print(
            f"integrity {st}: audited={v['records_audited']} quarantined={v['records_quarantined']} {v['defect_counts']}"
        )
    print(f"unresolved (operator review): {ledger['unresolved_record_count']}")
    if auth.rejected_accounts:
        print(f"accounts refused: {auth.rejected_accounts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

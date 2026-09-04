#!/usr/bin/env python3
"""Record-level reconciliation of divergent financial truth stores against their authority.

A store-level MANUAL_CONFLICT verdict is honest but blunt: it says "these two files
disagree" when what is actually true is that *most* records agree, a few are provably
decided by the broker, and only a residue genuinely needs a person.

This module resolves each record against the authority that governs it, and never by
recency. The rule the whole file exists to enforce:

    A value becomes canonical because an authority asserts it, or because it can be
    rebuilt from canonical inputs. Never because its file was written later.

What counts as authority, in order:

  * broker positions      -- current share quantity, per account, per instrument
  * broker orders         -- protective stop state, by broker order id
  * canonical transactions -- executions and cash flows
  * derived rebuild        -- outputs that are a pure function of the above plus a clock

Everything read here is read-only. This module never places, changes, cancels or
simulates an order, and never writes a state store.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# ── dispositions ────────────────────────────────────────────────────────────────
BROKER_VERIFIED = "BROKER_VERIFIED"
CANONICAL_TRANSACTION_VERIFIED = "CANONICAL_TRANSACTION_VERIFIED"
DERIVED_REBUILT = "DERIVED_REBUILT"
SYNTHETIC_ADVISORY_ONLY = "SYNTHETIC_ADVISORY_ONLY"
DUPLICATE_WITH_PROOF = "DUPLICATE_WITH_PROOF"
STALE_SUPERSEDED_WITH_PROOF = "STALE_SUPERSEDED_WITH_PROOF"
UNRESOLVED_OPERATOR_REVIEW = "UNRESOLVED_OPERATOR_REVIEW"

DISPOSITIONS = frozenset(
    {
        BROKER_VERIFIED,
        CANONICAL_TRANSACTION_VERIFIED,
        DERIVED_REBUILT,
        SYNTHETIC_ADVISORY_ONLY,
        DUPLICATE_WITH_PROOF,
        STALE_SUPERSEDED_WITH_PROOF,
        UNRESOLVED_OPERATOR_REVIEW,
    }
)

#: Dispositions that may be migrated without a person looking first.
AUTO_MIGRATABLE = frozenset(
    {
        BROKER_VERIFIED,
        CANONICAL_TRANSACTION_VERIFIED,
        DERIVED_REBUILT,
        DUPLICATE_WITH_PROOF,
        STALE_SUPERSEDED_WITH_PROOF,
    }
)

#: Basis that could not be proven. Never rendered as a number, never zero.
BASIS_UNVERIFIED = "BASIS_UNVERIFIED"

#: Fields that are a pure function of the wall clock. A difference in these is an
#: artifact of when a snapshot was taken, not a disagreement about a fact.
CLOCK_DERIVED_FIELDS = frozenset({"days_held", "age_days", "held_days", "days_open"})

#: Broker order states that constitute live protective coverage.
LIVE_PROTECTIVE_STATES = frozenset({"pending_activation", "awaiting_stop_condition", "accepted", "new", "open"})

#: Terminal states. An order in one of these protects nothing.
TERMINAL_ORDER_STATES = frozenset({"filled", "canceled", "cancelled", "rejected", "expired", "replaced"})

#: Quantity match tolerance. Absolute floor plus a relative term, because share counts
#: run from fractions to five figures and a fixed epsilon is wrong at one end or both.
QTY_ABS_TOL = 1e-3
QTY_REL_TOL = 1e-7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_obj(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def qty_matches(a: float | None, b: float | None) -> bool:
    """Share quantities agree within a tolerance that scales with size."""
    if a is None or b is None:
        return False
    return abs(a - b) <= max(QTY_ABS_TOL, QTY_REL_TOL * max(abs(a), abs(b)))


# ── authority index ─────────────────────────────────────────────────────────────


class BrokerAuthority:
    """Read-only index over a captured broker snapshot.

    Accounts are kept strictly separate: a position is only ever looked up by the pair
    (symbol, account_key). One broker's position is never substituted for another's,
    and a symbol-only match is never treated as evidence.
    """

    def __init__(self, snapshot: dict[str, Any]):
        self.snapshot = snapshot
        self.captured_at = snapshot.get("captured_at_utc")
        self._positions: dict[tuple[str, str], dict] = {}
        self._orders_by_id: dict[str, dict] = {}
        self._orders_by_sym: dict[tuple[str, str], list[dict]] = {}
        self.accepted_accounts: set[str] = set()
        self.rejected_accounts: dict[str, str] = {}

        for account_key, entry in (snapshot.get("brokers") or {}).items():
            if not entry.get("accepted"):
                # Partial, empty-without-proof, stale or failed responses are refused
                # outright. An account we could not read is not an account with nothing
                # in it, and treating it as empty is how holdings get wiped.
                self.rejected_accounts[account_key] = (
                    f"positions_status={entry.get('positions_status')} orders_status={entry.get('orders_status')}"
                )
                continue
            self.accepted_accounts.add(account_key)
            for p in entry.get("positions") or []:
                sym = str(p.get("symbol"))
                self._positions[(sym, account_key)] = p
            for o in entry.get("orders") or []:
                oid = str(o.get("id") or o.get("broker_order_id") or "")
                if oid:
                    self._orders_by_id[oid] = {**o, "account_key": account_key}
                self._orders_by_sym.setdefault((str(o.get("symbol")), account_key), []).append(o)

    def position_qty(self, symbol: str, account_key: str) -> float | None:
        row = self._positions.get((symbol, account_key))
        if row is None:
            return None
        try:
            return float(row.get("qty"))
        except (TypeError, ValueError):
            return None

    def has_account(self, account_key: str) -> bool:
        return account_key in self.accepted_accounts

    def order(self, order_id: str | None) -> dict | None:
        if not order_id:
            return None
        return self._orders_by_id.get(str(order_id))

    def live_protective_orders(self, symbol: str, account_key: str) -> list[dict]:
        """Open sell-side stop orders only. A buy order protects nothing."""
        out = []
        for o in self._orders_by_sym.get((symbol, account_key), []):
            if str(o.get("side", "")).lower() != "sell":
                continue
            if "stop" not in str(o.get("type", "")).lower():
                continue
            if str(o.get("status", "")).lower() not in LIVE_PROTECTIVE_STATES:
                continue
            out.append(o)
        return out


# ── per-record verdicts ─────────────────────────────────────────────────────────


def _verdict(
    store: str,
    record_key: str,
    disposition: str,
    reason: str,
    *,
    producer: Any = None,
    served: Any = None,
    canonical: Any = None,
    canonical_side: str | None = None,
    authorities: list[str] | None = None,
    observations: dict | None = None,
    rule: str = "",
) -> dict[str, Any]:
    assert disposition in DISPOSITIONS, disposition
    return {
        "store": store,
        "record_key": record_key,
        "disposition": disposition,
        "reason": reason,
        "reconciliation_rule": rule,
        "authorities_queried": authorities or [],
        "observations": observations or {},
        "producer_value": producer,
        "served_value": served,
        "producer_sha256": sha256_obj(producer) if producer is not None else None,
        "served_sha256": sha256_obj(served) if served is not None else None,
        "canonical_side": canonical_side,
        "canonical_value": canonical,
        "canonical_sha256": sha256_obj(canonical) if canonical is not None else None,
        "auto_migratable": disposition in AUTO_MIGRATABLE,
        "decided_at_utc": _now(),
    }


def split_key(record_key: str) -> tuple[str, str | None]:
    """'SCHD:schwab_taxable' -> ('SCHD', 'schwab_taxable')."""
    if ":" in record_key:
        sym, acct = record_key.split(":", 1)
        return sym, acct
    return record_key, None


def reconcile_stop_record(
    record_key: str, producer: dict | None, served: dict | None, auth: BrokerAuthority
) -> dict[str, Any]:
    """A stop is decided by the live broker order it claims to be, and nothing else."""
    symbol, account = split_key(record_key)
    rule = (
        "match the claimed broker_order_id against live broker order state; the side whose "
        "stop price equals the broker's is canonical. Recency is not consulted."
    )
    auths = [f"schwab.orders[{account}]"]

    if account and not auth.has_account(account):
        return _verdict(
            "stops.json",
            record_key,
            UNRESOLVED_OPERATOR_REVIEW,
            f"account {account} could not be read from the broker; refusing to decide without authority",
            producer=producer,
            served=served,
            authorities=auths,
            rule=rule,
        )

    present = producer if producer is not None else served
    oid = str((present or {}).get("broker_order_id") or "")
    live = auth.order(oid)

    if live is None:
        # No such order at the broker. Whatever this row is, it is not broker-verified
        # coverage; it is advisory until someone says otherwise.
        others = auth.live_protective_orders(symbol, account) if account else []
        return _verdict(
            "stops.json",
            record_key,
            SYNTHETIC_ADVISORY_ONLY,
            f"broker_order_id {oid or '(none)'} is not present in live broker order state"
            + (f"; {len(others)} other live protective order(s) exist for {symbol}" if others else ""),
            producer=producer,
            served=served,
            authorities=auths,
            observations={"live_order_found": False, "other_live_protective_orders": len(others)},
            rule=rule,
        )

    status = str(live.get("status", "")).lower()
    try:
        broker_stop = float(live.get("stop_price"))
    except (TypeError, ValueError):
        broker_stop = None
    obs = {
        "broker_order_id": oid,
        "broker_status": status,
        "broker_stop_price": broker_stop,
        "broker_qty": live.get("qty"),
        "is_live_protection": status in LIVE_PROTECTIVE_STATES,
    }

    def side_stop(rec: dict | None) -> float | None:
        if not rec:
            return None
        try:
            return float(rec.get("stop"))
        except (TypeError, ValueError):
            return None

    p_stop, s_stop = side_stop(producer), side_stop(served)
    p_ok = broker_stop is not None and p_stop is not None and abs(p_stop - broker_stop) < 1e-9
    s_ok = broker_stop is not None and s_stop is not None and abs(s_stop - broker_stop) < 1e-9

    if p_ok and not s_ok:
        return _verdict(
            "stops.json",
            record_key,
            BROKER_VERIFIED,
            f"broker order {oid} carries stop {broker_stop}; the producer copy matches and the served copy ({s_stop}) does not",
            producer=producer,
            served=served,
            canonical=producer,
            canonical_side="producer",
            authorities=auths,
            observations=obs,
            rule=rule,
        )
    if s_ok and not p_ok:
        return _verdict(
            "stops.json",
            record_key,
            BROKER_VERIFIED,
            f"broker order {oid} carries stop {broker_stop}; the served copy matches and the producer copy ({p_stop}) does not",
            producer=producer,
            served=served,
            canonical=served,
            canonical_side="served",
            authorities=auths,
            observations=obs,
            rule=rule,
        )
    if p_ok and s_ok:
        return _verdict(
            "stops.json",
            record_key,
            DUPLICATE_WITH_PROOF,
            f"both copies agree with broker order {oid} at stop {broker_stop}",
            producer=producer,
            served=served,
            canonical=producer,
            canonical_side="both",
            authorities=auths,
            observations=obs,
            rule=rule,
        )
    return _verdict(
        "stops.json",
        record_key,
        UNRESOLVED_OPERATOR_REVIEW,
        f"broker order {oid} carries stop {broker_stop}, which matches neither copy "
        f"(producer {p_stop}, served {s_stop})",
        producer=producer,
        served=served,
        authorities=auths,
        observations=obs,
        rule=rule,
    )


#: Keys that carry the store's observation envelope rather than a financial record.
#: They are restamped by whichever writer ran last and assert no fact in dispute.
ENVELOPE_KEYS = frozenset({"_agent_metadata", "_freshness_note", "generated_at", "last_updated", "_meta"})


def is_envelope_key(record_key: str) -> bool:
    return record_key in ENVELOPE_KEYS or record_key.startswith("_")


def reconcile_envelope_key(store: str, record_key: str, producer: Any, served: Any) -> dict[str, Any]:
    """Observation metadata is rebuilt by its writer, never adjudicated as a financial fact."""
    return _verdict(
        store,
        record_key,
        DERIVED_REBUILT,
        f"{record_key} is the store's observation envelope (writer identity, check time, producer "
        "status), not a financial record. It is restamped by whichever writer runs and asserts no "
        "value that could be in dispute.",
        producer=producer,
        served=served,
        canonical=None,
        canonical_side="rebuild",
        authorities=["derived:writer_envelope"],
        observations={"is_envelope": True},
        rule="envelope metadata is rebuilt by its producer; it is never selected between copies",
    )


def reconcile_missing_stop_record(
    record_key: str, present: dict | None, present_side: str, auth: BrokerAuthority
) -> dict[str, Any]:
    """A stop present in one copy only is decided by whether its order is live at the broker.

    Lot arithmetic is meaningless here -- a stop is an order, not a holding -- so this
    never routes through position totals.
    """
    symbol, account = split_key(record_key)
    rule = (
        "a stop present in one copy only is broker-verified when the order it claims is live "
        "sell-side protective coverage at the broker; position quantity is not the test"
    )
    auths = [f"schwab.orders[{account}]"]
    kw = {"producer": present} if present_side == "producer" else {"served": present}

    if account and not auth.has_account(account):
        return _verdict(
            "stops.json",
            record_key,
            UNRESOLVED_OPERATOR_REVIEW,
            f"account {account} could not be read from the broker",
            authorities=auths,
            rule=rule,
            **kw,
        )

    oid = str((present or {}).get("broker_order_id") or "")
    live = auth.order(oid)
    if live is None:
        return _verdict(
            "stops.json",
            record_key,
            SYNTHETIC_ADVISORY_ONLY,
            f"only the {present_side} copy has this record and its broker_order_id "
            f"{oid or '(none)'} is not present in live broker order state; it is advisory, "
            "not broker-verified protection",
            authorities=auths,
            observations={"live_order_found": False},
            rule=rule,
            **kw,
        )

    status = str(live.get("status", "")).lower()
    try:
        broker_stop = float(live.get("stop_price"))
    except (TypeError, ValueError):
        broker_stop = None
    try:
        rec_stop = float((present or {}).get("stop"))
    except (TypeError, ValueError):
        rec_stop = None
    try:
        broker_qty = float(live.get("qty"))
        rec_qty = float((present or {}).get("qty"))
    except (TypeError, ValueError):
        broker_qty = rec_qty = None

    obs = {
        "broker_order_id": oid,
        "broker_status": status,
        "broker_stop_price": broker_stop,
        "broker_qty": broker_qty,
        "record_stop": rec_stop,
        "record_qty": rec_qty,
        "is_live_protection": status in LIVE_PROTECTIVE_STATES,
        "position_qty": auth.position_qty(symbol, account) if account else None,
    }

    if status not in LIVE_PROTECTIVE_STATES:
        return _verdict(
            "stops.json",
            record_key,
            STALE_SUPERSEDED_WITH_PROOF,
            f"broker order {oid} is in terminal state {status!r} and protects nothing; the "
            f"copy lacking this record is not losing live coverage",
            canonical=None,
            canonical_side=("served" if present_side == "producer" else "producer"),
            authorities=auths,
            observations=obs,
            rule=rule,
            **kw,
        )

    stop_ok = broker_stop is not None and rec_stop is not None and abs(rec_stop - broker_stop) < 1e-9
    qty_ok = qty_matches(rec_qty, broker_qty)
    if stop_ok and qty_ok:
        return _verdict(
            "stops.json",
            record_key,
            BROKER_VERIFIED,
            f"only the {present_side} copy has this record, and it matches live broker order "
            f"{oid} exactly (status {status}, stop {broker_stop}, qty {broker_qty}). The other "
            "copy is missing real protective coverage.",
            canonical=present,
            canonical_side=present_side,
            authorities=auths,
            observations=obs,
            rule=rule,
            **kw,
        )
    return _verdict(
        "stops.json",
        record_key,
        UNRESOLVED_OPERATOR_REVIEW,
        f"only the {present_side} copy has this record; live broker order {oid} carries "
        f"stop {broker_stop} qty {broker_qty} but the record says stop {rec_stop} qty {rec_qty}",
        authorities=auths,
        observations=obs,
        rule=rule,
        **kw,
    )


def open_lot_total(lots: Any) -> float | None:
    """Sum of remaining shares across open lots. None if the shape is not a lot list."""
    if not isinstance(lots, list):
        return None
    total = 0.0
    for lot in lots:
        if not isinstance(lot, dict) or lot.get("closed"):
            continue
        try:
            total += float(lot.get("shares_remaining") or 0)
        except (TypeError, ValueError):
            return None
    return total


def classify_synthetic_lots(lots: Any) -> list[dict[str, Any]]:
    """Name every lot that is not a broker record, and say what kind of thing it is."""
    out = []
    if not isinstance(lots, list):
        return out
    for i, lot in enumerate(lots):
        if not isinstance(lot, dict):
            continue
        source = str(lot.get("source") or "")
        status = str(lot.get("rebuild_status") or "")
        if source.startswith("trade_transactions"):
            kind = "GOVERNED_ESTIMATE"
            why = "reconstructed from recorded transactions; a governed estimate, not a broker lot"
        elif source in ("synthetic", "placeholder", ""):
            kind = "PLACEHOLDER"
            why = "no source recorded; cannot be attributed to any authority"
        elif "import" in source or "historical" in source:
            kind = "HISTORICAL_IMPORT"
            why = f"imported from {source}"
        else:
            kind = "OTHER_NON_BROKER"
            why = f"source={source!r}"
        out.append(
            {
                "index": i,
                "lot_date": lot.get("lot_date"),
                "shares": lot.get("shares"),
                "shares_remaining": lot.get("shares_remaining"),
                "account_in_lot": lot.get("account"),
                "source": source or None,
                "rebuild_status": status or None,
                "synthetic_kind": kind,
                "why": why,
                "basis_state": BASIS_UNVERIFIED if lot.get("cost_per_share") in (None, 0) else "BASIS_RECORDED",
            }
        )
    return out


def reconcile_tax_lot_record(record_key: str, producer: Any, served: Any, auth: BrokerAuthority) -> dict[str, Any]:
    """Lots are decided by whether they reconcile to the broker's position quantity.

    Schwab does not expose tax lots, so a lot's *identity* is never broker-verifiable
    here. What is verifiable is the sum: the open lots for an account and security must
    add up to the quantity the broker says is held. A copy that reconciles is evidence;
    a copy that does not is disqualified. When both reconcile, the totals agree and the
    lot composition still differs, which is exactly the case a person must settle.
    """
    symbol, account = split_key(record_key)
    rule = (
        "sum of open lot shares_remaining must equal the broker position quantity for "
        "(symbol, account). Broker lot data is unavailable, so lot identity is never "
        "auto-selected; only reconciliation to the position total is decisive."
    )
    auths = [f"schwab.positions[{account}]"]

    if account and not auth.has_account(account):
        return _verdict(
            "tax_lots.json",
            record_key,
            UNRESOLVED_OPERATOR_REVIEW,
            f"account {account} could not be read from the broker",
            producer=producer,
            served=served,
            authorities=auths,
            rule=rule,
        )

    broker_qty = auth.position_qty(symbol, account) if account else None
    p_tot, s_tot = open_lot_total(producer), open_lot_total(served)
    obs = {
        "broker_position_qty": broker_qty,
        "producer_open_lot_total": p_tot,
        "served_open_lot_total": s_tot,
        "producer_lot_count": len(producer) if isinstance(producer, list) else None,
        "served_lot_count": len(served) if isinstance(served, list) else None,
        "producer_synthetic_lots": classify_synthetic_lots(producer),
        "served_synthetic_lots": classify_synthetic_lots(served),
    }

    if broker_qty is None:
        return _verdict(
            "tax_lots.json",
            record_key,
            UNRESOLVED_OPERATOR_REVIEW,
            f"the broker reports no position in {symbol} for {account}; lots cannot be "
            "reconciled to a quantity that does not exist",
            producer=producer,
            served=served,
            authorities=auths,
            observations=obs,
            rule=rule,
        )

    p_ok = qty_matches(p_tot, broker_qty)
    s_ok = qty_matches(s_tot, broker_qty)

    if p_ok and not s_ok:
        return _verdict(
            "tax_lots.json",
            record_key,
            BROKER_VERIFIED,
            f"the producer lots sum to {p_tot} which reconciles to the broker position "
            f"{broker_qty}; the served lots sum to {s_tot} and do not",
            producer=producer,
            served=served,
            canonical=producer,
            canonical_side="producer",
            authorities=auths,
            observations=obs,
            rule=rule,
        )
    if s_ok and not p_ok:
        return _verdict(
            "tax_lots.json",
            record_key,
            BROKER_VERIFIED,
            f"the served lots sum to {s_tot} which reconciles to the broker position "
            f"{broker_qty}; the producer lots sum to {p_tot} and do not",
            producer=producer,
            served=served,
            canonical=served,
            canonical_side="served",
            authorities=auths,
            observations=obs,
            rule=rule,
        )
    if p_ok and s_ok:
        if producer == served:
            return _verdict(
                "tax_lots.json",
                record_key,
                DUPLICATE_WITH_PROOF,
                f"both copies are identical and reconcile to the broker position {broker_qty}",
                producer=producer,
                served=served,
                canonical=producer,
                canonical_side="both",
                authorities=auths,
                observations=obs,
                rule=rule,
            )
        return _verdict(
            "tax_lots.json",
            record_key,
            UNRESOLVED_OPERATOR_REVIEW,
            f"both copies reconcile to the broker position {broker_qty} but allocate it "
            f"across different lots ({obs['producer_lot_count']} vs {obs['served_lot_count']}). "
            "The broker exposes no lot data, so cost basis and holding period cannot be "
            "decided from any authority available here.",
            producer=producer,
            served=served,
            authorities=auths,
            observations=obs,
            rule=rule,
        )
    return _verdict(
        "tax_lots.json",
        record_key,
        UNRESOLVED_OPERATOR_REVIEW,
        f"neither copy reconciles to the broker position {broker_qty} (producer {p_tot}, served {s_tot})",
        producer=producer,
        served=served,
        authorities=auths,
        observations=obs,
        rule=rule,
    )


def reconcile_missing_side_record(
    store: str, record_key: str, present: Any, present_side: str, auth: BrokerAuthority
) -> dict[str, Any]:
    """One copy has the record and the other dropped it.

    Absence is not evidence. The question is whether the *broker* still holds the thing
    the record describes -- if it does, dropping the record loses real state.
    """
    symbol, account = split_key(record_key)
    rule = "a record present in one copy only is kept when the broker still holds the underlying position"
    auths = [f"schwab.positions[{account}]"]

    if account and not auth.has_account(account):
        return _verdict(
            store,
            record_key,
            UNRESOLVED_OPERATOR_REVIEW,
            f"account {account} could not be read; cannot tell whether dropping this record loses state",
            producer=present if present_side == "producer" else None,
            served=present if present_side == "served" else None,
            authorities=auths,
            rule=rule,
        )

    broker_qty = auth.position_qty(symbol, account) if account else None
    total = open_lot_total(present)
    obs = {"broker_position_qty": broker_qty, "present_side": present_side, "present_open_lot_total": total}

    kw = {"producer": present} if present_side == "producer" else {"served": present}

    if broker_qty is None:
        return _verdict(
            store,
            record_key,
            STALE_SUPERSEDED_WITH_PROOF,
            f"the broker holds no {symbol} in {account}; the record describes a position that "
            "no longer exists, and the copy lacking it is not losing live state",
            canonical=None,
            canonical_side=("served" if present_side == "producer" else "producer"),
            authorities=auths,
            observations=obs,
            rule=rule,
            **kw,
        )
    if total is not None and qty_matches(total, broker_qty):
        return _verdict(
            store,
            record_key,
            BROKER_VERIFIED,
            f"only the {present_side} copy has this record, and it reconciles exactly to the "
            f"live broker position of {broker_qty} {symbol} in {account}. Dropping it would "
            "discard lot state for a position the account actually holds.",
            canonical=present,
            canonical_side=present_side,
            authorities=auths,
            observations=obs,
            rule=rule,
            **kw,
        )
    return _verdict(
        store,
        record_key,
        UNRESOLVED_OPERATOR_REVIEW,
        f"only the {present_side} copy has this record; the broker holds {broker_qty} {symbol} "
        f"but the record totals {total}",
        authorities=auths,
        observations=obs,
        rule=rule,
        **kw,
    )


def reconcile_clock_derived(store: str, record_key: str, producer: Any, served: Any, fields: list[str]) -> dict:
    """Differences confined to clock-derived fields are not disagreements."""
    return _verdict(
        store,
        record_key,
        DERIVED_REBUILT,
        f"the copies differ only in clock-derived field(s) {sorted(fields)}, which are a function of "
        "when the snapshot was taken rather than of any fact in dispute; the value is recomputed "
        "rather than chosen",
        producer=producer,
        served=served,
        canonical=None,
        canonical_side="rebuild",
        authorities=["derived:recompute_from_lot_dates"],
        observations={"clock_derived_fields": sorted(fields)},
        rule="a field that is a pure function of the wall clock is rebuilt, never selected",
    )


def reconcile_derived_store(store: str, producer: dict, served: dict, note: str) -> dict:
    """Whole-store derived outputs are rebuilt from canonical inputs, never merged."""
    return _verdict(
        store,
        "*",
        DERIVED_REBUILT,
        f"{note} Conflicting calculated outputs are never merged and never selected by recency; "
        "the store is rebuilt from reconciled transactions, holdings observations, cash flows and "
        "valuations. Intervals whose inputs are incomplete are marked UNVERIFIED rather than zero "
        "or carried forward from either copy.",
        producer=None,
        served=None,
        canonical=None,
        canonical_side="rebuild",
        authorities=["canonical:transactions", "canonical:holdings_observations", "canonical:valuations"],
        observations={
            "producer_sha256": sha256_obj(producer),
            "served_sha256": sha256_obj(served),
            "both_originals_preserved": True,
        },
        rule="derived outputs are rebuilt with a versioned calculation; prior outputs are kept as evidence",
    )


# ── record integrity ────────────────────────────────────────────────────────────
#
# Reconciliation compares two copies. Integrity asks a different question: is this
# record coherent at all? A record can be byte-identical on both sides and still be
# unusable -- lots attributed to another account, the same lot appended a hundred
# times by a producer that never deduplicated. Those never reach a conflict ledger,
# because nothing disagrees. They still must not be treated as truth.

RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

#: Integrity defects, most severe first.
DEFECT_CROSS_ACCOUNT = "CROSS_ACCOUNT_ATTRIBUTION"
DEFECT_DUPLICATE_OPEN = "DUPLICATE_OPEN_LOTS"
DEFECT_DUPLICATE_CLOSED = "DUPLICATE_CLOSED_LOTS"
DEFECT_MALFORMED = "MALFORMED_LOT"
DEFECT_NEGATIVE = "NEGATIVE_SHARES_REMAINING"


def _lot_identity(lot: dict) -> str:
    return json.dumps(lot, sort_keys=True, default=str)


def audit_lot_record(record_key: str, lots: Any, auth: BrokerAuthority | None = None) -> dict[str, Any]:
    """Integrity of one tax-lot record, independent of any other copy.

    Reports defects; it does not repair them. Repair would mean choosing a share
    count, and a share count no authority asserts is a number this code must never
    invent.
    """
    symbol, account = split_key(record_key)
    defects: list[dict[str, Any]] = []
    if not isinstance(lots, list):
        return {
            "record_key": record_key,
            "defects": [{"defect": DEFECT_MALFORMED, "detail": f"record is {type(lots).__name__}, expected a list"}],
            "quarantine": True,
        }

    cross: list[int] = []
    malformed: list[int] = []
    negative: list[int] = []
    seen: dict[str, list[int]] = {}
    open_total = 0.0
    open_total_dedup = 0.0
    dedup_seen: set[str] = set()

    for i, lot in enumerate(lots):
        if not isinstance(lot, dict):
            malformed.append(i)
            continue
        got = lot.get("account")
        if account and got and got != account:
            cross.append(i)
        try:
            rem = float(lot.get("shares_remaining") or 0)
        except (TypeError, ValueError):
            malformed.append(i)
            continue
        if rem < 0:
            negative.append(i)
        ident = _lot_identity(lot)
        seen.setdefault(ident, []).append(i)
        if not lot.get("closed"):
            open_total += rem
            if ident not in dedup_seen:
                open_total_dedup += rem
        dedup_seen.add(ident)

    dup_open = dup_closed = 0
    for ident, idxs in seen.items():
        if len(idxs) < 2:
            continue
        extra = len(idxs) - 1
        if json.loads(ident).get("closed"):
            dup_closed += extra
        else:
            dup_open += extra

    if cross:
        by_account: dict[str, int] = {}
        for i in cross:
            by_account[str(lots[i].get("account"))] = by_account.get(str(lots[i].get("account")), 0) + 1
        defects.append(
            {
                "defect": DEFECT_CROSS_ACCOUNT,
                "detail": (
                    f"{len(cross)} lot(s) claim an account other than {account!r}: {by_account}. "
                    "A lot belongs to the account that holds it; a record keyed to one account "
                    "cannot carry another account's basis."
                ),
                "lot_indexes": cross[:20],
            }
        )
    if malformed:
        defects.append(
            {
                "defect": DEFECT_MALFORMED,
                "detail": f"{len(malformed)} lot(s) are not usable objects",
                "lot_indexes": malformed[:20],
            }
        )
    if negative:
        defects.append(
            {
                "defect": DEFECT_NEGATIVE,
                "detail": f"{len(negative)} lot(s) hold a negative remainder",
                "lot_indexes": negative[:20],
            }
        )
    if dup_open:
        broker_qty = auth.position_qty(symbol, account) if (auth and account) else None
        defects.append(
            {
                "defect": DEFECT_DUPLICATE_OPEN,
                "detail": (
                    f"{dup_open} OPEN lot(s) are exact duplicates. The open total is {round(open_total, 4)} "
                    f"as stored and {round(open_total_dedup, 4)} deduplicated"
                    + (
                        f"; the broker holds {broker_qty}"
                        if broker_qty is not None
                        else "; the broker holds no position in this security, so neither total can be confirmed"
                    )
                    + ". Removing them would change a share quantity, so they are quarantined rather than repaired."
                ),
                "open_total_as_stored": round(open_total, 4),
                "open_total_deduplicated": round(open_total_dedup, 4),
                "broker_position_qty": broker_qty,
            }
        )
    if dup_closed:
        defects.append(
            {
                "defect": DEFECT_DUPLICATE_CLOSED,
                "detail": (
                    f"{dup_closed} CLOSED lot(s) are exact duplicates with no remaining shares. They change "
                    "no quantity and no basis, but they are not records of distinct events."
                ),
            }
        )

    # Only defects that could misstate a current holding force quarantine. Duplicated
    # closed lots are noise: they carry no shares and change no computed value.
    quarantine = any(
        d["defect"] in (DEFECT_CROSS_ACCOUNT, DEFECT_DUPLICATE_OPEN, DEFECT_MALFORMED, DEFECT_NEGATIVE) for d in defects
    )
    return {
        "record_key": record_key,
        "symbol": symbol,
        "account": account,
        "lot_count": len(lots),
        "open_total_as_stored": round(open_total, 4),
        "open_total_deduplicated": round(open_total_dedup, 4),
        "defects": defects,
        "quarantine": quarantine,
        "status": RECONCILIATION_REQUIRED if quarantine else "OK",
    }


def audit_store_integrity(store: str, doc: Any, auth: BrokerAuthority | None = None) -> dict[str, Any]:
    """Integrity across every record in a store, conflicting or not."""
    rows: list[dict[str, Any]] = []
    if isinstance(doc, dict):
        for key in sorted(doc):
            if is_envelope_key(key) or ":" not in key:
                continue
            rows.append(audit_lot_record(key, doc[key], auth))
    quarantined = [r for r in rows if r["quarantine"]]
    counts: dict[str, int] = {}
    for r in rows:
        for d in r["defects"]:
            counts[d["defect"]] = counts.get(d["defect"], 0) + 1
    return {
        "store": store,
        "records_audited": len(rows),
        "records_quarantined": len(quarantined),
        "defect_counts": counts,
        "quarantined": quarantined,
        "rule": (
            "a record is quarantined when a defect could misstate a current holding: cross-account "
            "attribution, duplicated OPEN lots, malformed lots, or a negative remainder. Duplicated "
            "CLOSED lots are reported and not quarantined -- they carry no shares."
        ),
    }

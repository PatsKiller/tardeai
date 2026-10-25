"""Stored holding history with explicit source coverage and account aliases.

Financial totals come from the named closed-trip producers. Transaction and
holding observations describe account membership and holding stretches; they
are never converted into additional, guessed profitable trips.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json

from lib.data_broker import tradeinview_sources as src
from lib.data_broker.trade_calendar import one

SCHEMA = "HoldingHistory@v1"


def _file_gap(snapshot, name):
    row = (snapshot.get("files") or {}).get(name) or {}
    if row.get("status") != "ok":
        return {"source": name, "reason": row.get("reason") or "stored source not collected"}
    return None


def history_trips(snapshot):
    trips, gaps = src.normalise_closed(snapshot)
    legacy = src.file_document(snapshot, "legacy_journal")
    gap = _file_gap(snapshot, "legacy_journal")
    if gap:
        gaps.append(gap)
    rows = legacy.get("closed_trades")
    if not isinstance(rows, list):
        if not gap:
            gaps.append({"source": "legacy_journal", "reason": "closed_trades collection missing"})
        rows = []
    occurrences = defaultdict(int)
    for n, row in enumerate(rows):
        if not isinstance(row, dict):
            gaps.append({"source": "legacy_journal", "reason": "malformed closed trip", "row": n})
            continue
        sym = src.symbol(row.get("symbol"))
        if not sym:
            gaps.append({"source": "legacy_journal", "reason": "trip symbol missing", "row": n})
            continue
        # The export has no broker trade id. Equal business values do not prove
        # that two fills are the same. Preserve each source occurrence, with a
        # stable content reference and its occurrence index.
        fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
        occurrences[fingerprint] += 1
        unknown = src.number(row.get("buy_price")) is None or src.number(row.get("cost_basis")) is None
        trip = {"trade_id": f"journal:{fingerprint}:{occurrences[fingerprint]}", "symbol": sym,
                **src.account(row.get("account")), "entry_at": src.iso(row.get("open_time")),
                "exit_at": src.iso(row.get("close_time")),
                "entry_date": src.day(row.get("open_time")) or src.day(row.get("open_date")),
                "exit_date": src.day(row.get("close_time")) or src.day(row.get("close_date")),
                "entry_price": src.number(row.get("buy_price")), "exit_price": src.number(row.get("sell_price")),
                "shares": src.number(row.get("shares")),
                "realized_pl": None if unknown else src.number(row.get("pnl")),
                "return_pct": None if unknown else src.number(row.get("pnl_pct")),
                "basis_unknown": unknown, "basis_reason": "opening basis not recorded" if unknown else None,
                "classification": row.get("trade_type"), "source": "legacy_journal.closed_trades",
                "provenance": [{"source": "legacy_journal.closed_trades", "record_id": fingerprint,
                                "source_row": n, "occurrence": occurrences[fingerprint],
                                "observed_at": src.iso(legacy.get("last_updated")),
                                "writer": "stored journal export; original writer not declared"}]}
        src._hold_days(trip)
        trips.append(trip)
    # Overlapping, unlinked source windows cannot be silently counted twice.
    # Keep the source rows available, but qualify totals until exact identities
    # establish whether they are separate fills or copies.
    by_key = defaultdict(list)
    for trip in trips:
        if trip.get("exit_date"):
            by_key[(trip["symbol"], trip.get("account_id"), trip["exit_date"])].append(trip)
    for (sym, account, day), group in by_key.items():
        if any(r["source"].startswith("legacy_journal") for r in group) and any(
                not r["source"].startswith("legacy_journal") for r in group):
            gaps.append({"source": "closed trips", "symbol": sym, "account_id": account,
                         "reason": "journal and ledger overlap without an explicit trade link", "date": day})
    return trips, gaps


def _holding_rows(snapshot):
    return [r for r in src.file_document(snapshot, "holdings").get("holdings") or []
            if isinstance(r, dict) and not r.get("is_cash") and src.symbol(r.get("symbol")) not in
            ("CASH", "SPAXX", "FDRXX")]


def _accounts(snapshot, trips):
    """All observed account memberships, not a second financial ledger."""
    result = defaultdict(set)
    embedded = src.file_document(snapshot, "holdings").get("trade_journal")
    embedded = [r for r in embedded if isinstance(r, dict)] if isinstance(embedded, list) else []
    for row in [*trips, *_holding_rows(snapshot), *src.source_rows(snapshot, "trade_transactions"), *embedded]:
        sym = src.symbol(row.get("symbol"))
        acct = row.get("account_id") if "account_label" in row else src.account(row.get("account") or row.get("account_id"))["account_id"]
        if sym and acct:
            result[sym].add(acct)
    for row in src.source_rows(snapshot, "position_transfer_history"):
        sym = src.symbol(row.get("symbol"))
        for name in ("from_account", "to_account"):
            acct = src.account(row.get(name))["account_id"]
            if sym and acct:
                result[sym].add(acct)
    for lots in src.file_document(snapshot, "tax_lots").values():
        if not isinstance(lots, list):
            continue
        for row in lots:
            sym, acct = src.symbol(row.get("symbol")), src.account(row.get("account"))["account_id"]
            if sym and acct:
                result[sym].add(acct)
    return result


def _observed_segments(trips, holdings, accounts, now):
    """Show actual lot spans; never rename lot counts as distinct holdings.

    A round-trip producer matches lots, not aggregate zero-to-positive holding
    transitions. Date-only spans therefore cannot establish 'times held'.
    """
    groups = []
    for acct in sorted(accounts):
        segments = []
        for trip in trips:
            if trip.get("account_id") != acct:
                continue
            segments.append({"start_date": trip.get("entry_date"), "end_date": trip.get("exit_date"),
                             "start_at": trip.get("entry_at"), "end_at": trip.get("exit_at"),
                             "status": "closed_trip_observation", "source": trip["source"],
                             "precision": "timestamps" if trip.get("entry_at") and trip.get("exit_at") else "calendar dates only",
                             "trade_id": trip["trade_id"], "gaps": [] if trip.get("entry_date") else
                                 [{"source": trip["source"], "reason": "opening date not recorded"}]})
        held = [r for r in holdings if src.account(r.get("account") or r.get("account_id"))["account_id"] == acct]
        for row in held:
            if (src.number(row.get("shares", row.get("quantity"))) or 0) <= 0:
                continue
            observation = row.get("provider_observed_at") or row.get("broker_position_as_of") or row.get("updated_at")
            at = src.iso(observation)
            segments.append({"start_date": src.day(observation), "end_date": src.day(observation),
                             "start_at": at, "end_at": at, "status": "current_holding_observation",
                             "source": "holdings_accounts.holdings_json", "precision": "snapshot only",
                             "gaps": [{"source": "holdings_accounts", "reason": "opening date and distinct holding transition not established"}]})
        clocks = [at for segment in segments for key in ("start_at", "end_at")
                  if (at := src.instant(segment.get(key))) is not None]
        groups.append({**src.account(acct), "as_of": max(clocks).isoformat() if clocks else None,
                       "generated_at": now.isoformat(), "segments": segments})
    return groups


def _stats(trips, coverage, gaps, symbol):
    ambiguous = any(g.get("symbol") == symbol and g.get("reason") ==
                    "journal and ledger overlap without an explicit trade link" for g in gaps)
    value = src.trip_stats(trips, complete=coverage["status"] == "COMPLETE" and not ambiguous)
    value["observed_trip_rows"] = len(trips)
    if ambiguous:
        # These amounts exist, but their distinctness is not established. Their
        # sum cannot be advertised as a known realized-profit subtotal either.
        value["known_realized_pl"] = None
        value["known_trade_count"] = None
    value["coverage"] = {**coverage, "status": "PARTIAL" if ambiguous else coverage["status"],
                         "reasons": [*coverage["reasons"], *(
                             ["journal and ledger overlap without an explicit trade link"] if ambiguous else [])]}
    return value


def _history_checks(snapshot, holdings):
    """Disclose stored-source discrepancies; never repair quantities or basis."""
    gaps = []
    mapping = snapshot.get("mapping") or {}
    if mapping.get("snaptrade_accounts_present") is not True:
        gaps.append({"source": "release account mapping", "reason": "Fidelity mapping presence not established in captured release"})
    fidelity = [r for r in holdings if (src.account(r.get("account") or r.get("account_id"))["account_id"] or "").startswith("fidelity")]
    observed = [str(r.get("provider_observed_at") or r.get("broker_position_as_of") or "") for r in fidelity]
    latest = max((v for v in observed if src.day(v)), default=None)
    gaps.append({"source": "Fidelity sync", "reason": "successful sync receipt not collected; position observations are not sync-success proof",
                 "latest_position_observed_at": latest})
    lots = defaultdict(list)
    for value in src.file_document(snapshot, "tax_lots").values():
        for row in value if isinstance(value, list) else []:
            if isinstance(row, dict) and row.get("closed") is not True:
                lots[(src.symbol(row.get("symbol")), src.account(row.get("account"))["account_id"])].append(row)
    held = defaultdict(list)
    for row in holdings:
        held[(src.symbol(row.get("symbol")), src.account(row.get("account") or row.get("account_id"))["account_id"])].append(row)
    for (sym, acct), rows in held.items():
        if not lots.get((sym, acct)):
            continue
        quantities = [src.number(r.get("shares", r.get("quantity"))) for r in rows]
        remaining = [src.number(r.get("shares_remaining", r.get("shares"))) for r in lots[(sym, acct)]]
        if all(v is not None for v in [*quantities, *remaining]) and abs(sum(quantities) - sum(remaining)) > .000001:
            gaps.append({"source": "tax lots vs holdings", "symbol": sym, "account_id": acct,
                         "account_label": src.account(acct)["account_label"], "reason": "stored share quantities disagree",
                         "holdings_shares": sum(quantities), "tax_lot_shares": sum(remaining)})
        held_basis = [src.number(r.get("cost_basis")) for r in rows]
        lot_basis = [src.number(r.get("cost_per_share")) for r in lots[(sym, acct)]]
        if all(v is not None for v in [*held_basis, *lot_basis, *remaining]):
            basis = sum(p * q for p, q in zip(lot_basis, remaining))
            if abs(sum(held_basis) - basis) > .01:
                gaps.append({"source": "tax lots vs holdings", "symbol": sym, "account_id": acct,
                             "account_label": src.account(acct)["account_label"], "reason": "stored cost basis disagrees",
                             "holdings_basis": sum(held_basis), "tax_lot_basis": basis})
    # The captured embedded journal is a transaction log, not a closed-trip
    # producer. Use its account membership, never clone FIFO matching here.
    embedded = src.file_document(snapshot, "holdings").get("trade_journal")
    if isinstance(embedded, list) and embedded:
        gaps.append({"source": "holdings.trade_journal", "reason": "transaction observations retained for membership; no explicit closed-trip links",
                     "observed_rows": len(embedded)})
    return gaps


def build_history(snapshot, query, *, now=None):
    now = now or datetime.now(timezone.utc)
    range_name = one(query, "range", "all")
    start, end = one(query, "start"), one(query, "end")
    if range_name != "all" and not (start and end):
        return {"ok": False, "schema": SCHEMA, "error": "explicit_range_required"}
    if start or end:
        try:
            if not start or not end or date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError
        except (ValueError, TypeError):
            return {"ok": False, "schema": SCHEMA, "error": "invalid_date_range"}
    order = one(query, "sort", "round_trips")
    if order not in ("round_trips", "realized", "held_now"):
        return {"ok": False, "schema": SCHEMA, "error": "invalid_sort"}
    requested = src.symbol(one(query, "symbol"))
    all_trips, gaps = history_trips(snapshot)
    trips = [t for t in all_trips if not start or (t.get("exit_date") and start <= t["exit_date"] <= end)]
    accounts = _accounts(snapshot, all_trips)
    holding_rows = _holding_rows(snapshot)
    gaps += _history_checks(snapshot, holding_rows)
    for name in ("holdings", "tax_lots", "legacy_journal"):
        if gap := _file_gap(snapshot, name):
            if gap not in gaps:
                gaps.append(gap)
    for name in ("trade_transactions", "position_transfer_history"):
        if gap := src.source_gap(snapshot, name):
            gaps.append(gap)
    trip_coverage = src.coverage(snapshot, ("schwab_round_trips", "trade_closed"))
    if _file_gap(snapshot, "legacy_journal") or any(g["source"] == "legacy_journal" for g in gaps):
        trip_coverage = {"status": "PARTIAL", "missing_sources": trip_coverage["missing_sources"],
                         "reasons": [*trip_coverage["reasons"], "older journal coverage or exact linkage incomplete"]}
    symbols = []
    for sym in sorted(accounts):
        group = [r for r in trips if r["symbol"] == sym]
        ever = [r for r in all_trips if r["symbol"] == sym]
        if len(ever) < 2 and len(accounts[sym]) < 2:
            continue
        held = [r for r in holding_rows if src.symbol(r.get("symbol")) == sym]
        held_by = defaultdict(list)
        for row in held:
            held_by[src.account(row.get("account") or row.get("account_id"))["account_id"]].append(row)
        observed_accounts = []
        for acct in sorted(accounts[sym]):
            rows = held_by[acct]
            quantities = [src.number(r.get("shares", r.get("quantity"))) for r in rows]
            # Absence is not a proven zero for an unavailable/incomplete store.
            qty = sum(quantities) if rows and all(n is not None for n in quantities) else None
            observed_accounts.append({**src.account(acct), "held_quantity": qty,
                "as_of": next((src.iso(r.get("provider_observed_at") or r.get("updated_at")) for r in rows), None),
                "missing_reason": None if qty is not None else "current quantity not observed for this account"})
        stats = _stats(group, trip_coverage, gaps, sym)
        facts = (snapshot.get("company_facts") or {}).get(sym) or {}
        name = (facts.get("company") or {}).get("value") if isinstance(facts.get("company"), dict) else None
        sym_gaps = [g for g in gaps if g.get("symbol") in (None, sym)]
        symbols.append({"symbol": sym, "company_name": name,
            "company_missing_reason": None if name else "company name not recorded in CIO memory",
            "account_count": len(accounts[sym]), "accounts": observed_accounts,
            "round_trip_count": stats["round_trip_count"], "known_trip_count": stats["known_trade_count"],
            "observed_trip_rows": len(group),
            "realized_pl": stats["realized_pl"], "known_realized_pl": stats["known_realized_pl"],
            "held_now": True if any((r["held_quantity"] or 0) > 0 for r in observed_accounts) else
                (False if all(r["held_quantity"] is not None for r in observed_accounts) else None),
            "basis_unknown": any(r["basis_unknown"] for r in group), "gaps": sym_gaps})
    sort_key = {"round_trips": "known_trip_count", "realized": "known_realized_pl", "held_now": "held_now"}[order]
    symbols.sort(key=lambda r: (r[sort_key] is None, -(r[sort_key] or 0), r["symbol"]))
    detail = None
    if requested:
        row = next((r for r in symbols if r["symbol"] == requested), None)
        if row is not None:
            group = [r for r in trips if r["symbol"] == requested]
            stats = _stats(group, trip_coverage, gaps, requested)
            held = [r for r in holding_rows if src.symbol(r.get("symbol")) == requested]
            reason = "distinct holding stretches need quantity transitions with a proven opening balance; lot matches are not holding counts"
            detail = {"symbol": requested, "company_name": row["company_name"],
                "company_missing_reason": row["company_missing_reason"],
                "stats": {**stats, "times_held": None, "known_holding_stretches": None,
                          "coverage": {**stats["coverage"], "status": "PARTIAL",
                                       "reasons": [*stats["coverage"]["reasons"], reason]}},
                "account_segments": _observed_segments(group, held, accounts[requested], now),
                "trips": sorted(group, key=lambda r: (r.get("exit_date") or "", r["trade_id"]), reverse=True),
                "gaps": [*row["gaps"], {"source": "holding transitions", "reason": reason}]}
    dates = [r["entry_date"] for r in trips if r.get("entry_date")] + [r["exit_date"] for r in trips if r.get("exit_date")]
    options = {a: src.account(a)["account_label"] for group in accounts.values() for a in group}
    return {"ok": True, "schema": SCHEMA, "as_of": snapshot.get("as_of") or now.isoformat(),
        "range": {"start_date": start or min(dates, default=None), "end_date": end or max(dates, default=None),
                  "basis": "explicit dates" if start else "all available named stored sources; no lifetime coverage assertion",
                  "coverage": trip_coverage},
        "symbols": symbols, "detail": detail, "sort": order,
        "requested_symbol": requested or None,
        "missing_reason": "symbol not present in eligible stored history" if requested and detail is None else None,
        "account_options": [{"id": a, "label": label} for a, label in sorted(options.items())],
        "gaps": gaps, "provider_calls": 0, "writes": 0, "read_only": True}


def get_history(query=None):
    query = query or {}
    checked = build_history({}, query)
    if not checked.get("ok"):
        return checked
    return build_history(src.cached_snapshot(kind="history", query=query), query)

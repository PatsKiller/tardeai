"""Stored TradeInView facts. Read projections only: no providers, models or writes.

The builders consume an explicit snapshot so a production COPY and pinned fixtures
use the same code as the HTTP surface. Missing collections retain their reason;
an unavailable source is never silently converted to an empty successful source.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lib.account_display import account_label, canonical_key, looks_like_number

ET = ZoneInfo("America/New_York")


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def instant(value: Any) -> datetime | None:
    """Only a real timestamp with an offset is an instant; dates remain dates."""
    if not value:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        return None
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def day(value: Any) -> str | None:
    """ET day for an offset timestamp, original date for a date-only fact."""
    at = instant(value)
    if at is not None:
        return at.astimezone(ET).date().isoformat()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "")
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def iso(value: Any) -> str | None:
    at = instant(value)
    return at.isoformat() if at is not None else None


def symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def account(raw: Any) -> dict[str, Any]:
    """Reuse the account registry; no account number is returned for display."""
    key = canonical_key(raw)
    if not key or looks_like_number(key):
        return {"account_id": None, "account_label": "Unlabelled account",
                "account_missing_reason": "account label is not configured"}
    return {"account_id": key, "account_label": account_label(key),
            "account_missing_reason": None}


def source_rows(snapshot: dict, name: str) -> list[dict]:
    entry = (snapshot.get("sources") or {}).get(name) or {}
    rows = entry.get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def source_gap(snapshot: dict, name: str) -> dict | None:
    entry = (snapshot.get("sources") or {}).get(name) or {}
    status = entry.get("status")
    if status == "ok" and not entry.get("truncated"):
        return None
    return {"source": name, "reason": entry.get("reason") or (
        "source result is truncated" if entry.get("truncated") else "source was not collected"),
        "as_of": entry.get("as_of")}


def file_document(snapshot: dict, name: str) -> dict:
    entry = (snapshot.get("files") or {}).get(name) or {}
    return entry.get("document") if isinstance(entry.get("document"), dict) else {}


def provenance(name: str, row: dict, *, record_id: Any = None) -> dict:
    writers = {
        "schwab_round_trips": "scripts/schwab_journal_builder.py",
        "trade_closed": "trade_closed writers (schwab rows: scripts/schwab_journal_builder.py)",
        "trade_transactions": "transactions domain writers; scripts/schwab_transaction_ingest.py target",
        "holdings.trade_journal": "holdings_accounts writer/export; scripts/portfolio_loader.py",
    }
    return {"source": name, "record_id": str(record_id) if record_id is not None else None,
            "observed_at": iso(row.get("created_at") or row.get("updated_at")),
            "writer": writers.get(name)}


def normalise_closed(snapshot: dict) -> tuple[list[dict], list[dict]]:
    """Canonical closed trips, including the *explicit* trade_closed→SRT link.

    schwab_journal_builder writes trade_closed.dedupe_key='srt:'||SRT.id. That
    exact link permits deduplication. Similar prices/dates never prove identity.
    """
    out: list[dict] = []
    gaps = [g for name in ("schwab_round_trips", "trade_closed") if (g := source_gap(snapshot, name))]
    by_srt: dict[str, dict] = {}
    seen: dict[tuple[str, str], dict] = {}
    for row in source_rows(snapshot, "schwab_round_trips"):
        if row.get("canary") is True:
            continue
        sym = symbol(row.get("symbol"))
        if not sym:
            gaps.append({"source": "schwab_round_trips", "reason": "trip symbol missing"})
            continue
        identity = str(row.get("dedupe_key") or row.get("id") or "")
        if not identity:
            gaps.append({"source": "schwab_round_trips", "reason": "trip identity missing", "symbol": sym})
            continue
        key = ("schwab_round_trips", identity)
        if key in seen:
            gaps.append({"source": "schwab_round_trips", "reason": "duplicate source trip identity",
                         "symbol": sym})
            continue
        basis_unknown = row.get("basis_status") == "basis_unknown" or number(row.get("entry_price")) is None
        trip = {"trade_id": "rt:" + identity, "symbol": sym, **account(row.get("account")),
                "entry_at": iso(row.get("entry_time")), "exit_at": iso(row.get("exit_time")),
                "entry_date": day(row.get("entry_time")) or day(row.get("entry_trade_date")),
                "exit_date": day(row.get("exit_time")) or day(row.get("exit_trade_date")),
                "entry_trade_date": day(row.get("entry_trade_date")),
                "exit_trade_date": day(row.get("exit_trade_date")),
                "entry_price": number(row.get("entry_price")), "exit_price": number(row.get("exit_price")),
                "shares": number(row.get("qty")), "realized_pl": None if basis_unknown else number(row.get("net_pnl")),
                "return_pct": None if basis_unknown else number(row.get("pnl_pct")),
                "basis_unknown": basis_unknown, "basis_reason": (
                    "basis unknown — opening buy is outside the ledger window" if basis_unknown else None),
                "source": "schwab_round_trips", "classification": row.get("classification"),
                "provenance": [provenance("schwab_round_trips", row, record_id=row.get("id"))]}
        _hold_days(trip)
        seen[key] = trip
        out.append(trip)
        if row.get("id") is not None:
            by_srt[str(row["id"])] = trip
    for row in source_rows(snapshot, "trade_closed"):
        dedupe = str(row.get("dedupe_key") or "")
        if dedupe.startswith("srt:") and dedupe[4:] in by_srt:
            trip = by_srt[dedupe[4:]]
            # A copied row may have drifted since the journal rebuild. Preserve
            # the authoritative trip and expose the disagreement, not both P/Ls.
            mismatches = []
            pairs = {"symbol": symbol(row.get("symbol")), "account_id": account(row.get("account"))["account_id"],
                     "shares": number(row.get("shares")), "realized_pl": number(row.get("pnl"))}
            for field, value in pairs.items():
                if value is not None and trip.get(field) != value:
                    mismatches.append(field)
            trip["provenance"].append(provenance("trade_closed", row, record_id=row.get("id")))
            if mismatches:
                gaps.append({"source": "trade_closed", "symbol": trip["symbol"],
                             "reason": "derived SRT copy disagrees", "fields": mismatches,
                             "trade_id": trip["trade_id"]})
            continue
        sym = symbol(row.get("symbol"))
        identity = str(row.get("id") or dedupe or "")
        if not sym or not identity:
            gaps.append({"source": "trade_closed", "reason": "trip symbol or identity missing"})
            continue
        if ("trade_closed", identity) in seen:
            gaps.append({"source": "trade_closed", "reason": "duplicate source trip identity", "symbol": sym})
            continue
        basis_unknown = number(row.get("buy_price")) is None
        trip = {"trade_id": "tc:" + identity, "symbol": sym, **account(row.get("account")),
                "entry_at": None, "exit_at": None, "entry_date": day(row.get("open_date")),
                "exit_date": day(row.get("close_date")), "entry_price": number(row.get("buy_price")),
                "exit_price": number(row.get("sell_price")), "shares": number(row.get("shares")),
                "realized_pl": None if basis_unknown else number(row.get("pnl")),
                "return_pct": None if basis_unknown else number(row.get("pnl_pct")),
                "basis_unknown": basis_unknown, "basis_reason": "opening basis not recorded" if basis_unknown else None,
                "source": "trade_closed", "classification": row.get("trade_type"),
                "provenance": [provenance("trade_closed", row, record_id=row.get("id"))]}
        _hold_days(trip)
        seen[("trade_closed", identity)] = trip
        out.append(trip)
        if dedupe.startswith("srt:"):
            gaps.append({"source": "trade_closed", "symbol": sym,
                         "reason": "linked authoritative SRT row was not collected", "trade_id": trip["trade_id"]})
    return out, gaps


def _hold_days(trip: dict) -> None:
    start, end = instant(trip.get("entry_at")), instant(trip.get("exit_at"))
    if start is not None and end is not None and end >= start:
        trip["hold_days"] = (end - start).total_seconds() / 86400
        trip["hold_days_basis"] = "elapsed timestamps"
    elif trip.get("entry_date") and trip.get("exit_date"):
        delta = (date.fromisoformat(trip["exit_date"]) - date.fromisoformat(trip["entry_date"])).days
        trip["hold_days"] = delta if delta >= 0 else None
        trip["hold_days_basis"] = "calendar dates only"
    else:
        trip["hold_days"], trip["hold_days_basis"] = None, "entry or exit date not recorded"


def bounded_json(path: Path, *, max_bytes: int = 32_000_000) -> dict:
    """Read an explicitly named stored document with a bound; never create it."""
    try:
        stat = path.stat()
        if stat.st_size > max_bytes:
            return {"status": "missing", "reason": "stored document exceeds read bound", "path": str(path)}
        raw = path.read_bytes()
        doc = json.loads(raw)
        return {"status": "ok", "document": doc, "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "written_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
    except (OSError, ValueError) as exc:
        return {"status": "missing", "reason": type(exc).__name__, "path": str(path)}


READ_ROWS = 25_000
SOURCE_SQL = {
    "schwab_round_trips": """SELECT id,account,symbol,entry_time,exit_time,entry_trade_date,exit_trade_date,
        qty,entry_price,exit_price,net_pnl,pnl_pct,classification,dedupe_key,basis_status,basis_source,
        fees,hold_minutes,created_at,canary FROM schwab_round_trips ORDER BY exit_time,id LIMIT %s""",
    "trade_closed": """SELECT id,account,symbol,open_date,close_date,shares,buy_price,sell_price,
        pnl,pnl_pct,hold_days,dedupe_key,created_at,trade_type FROM trade_closed
        ORDER BY close_date,id LIMIT %s""",
    "trade_transactions": """SELECT account,symbol,action,quantity,price,amount,fees,trade_time,
        trade_date,import_source FROM trade_transactions
        ORDER BY coalesce(trade_time,trade_date::timestamptz) LIMIT %s""",
    "position_transfer_history": """SELECT id,event_id,symbol,from_account,to_account,shares_moved,
        cost_basis_total,per_share_basis,basis_source,transfer_type,status,detected_at,normalized_at,
        sync_source FROM position_transfer_history ORDER BY detected_at,id LIMIT %s""",
    "catalyst_events": "SELECT * FROM catalyst_events ORDER BY id DESC LIMIT %s",
}


def collect_snapshot(*, kind: str, query: dict | None = None, db_query=None,
                     state_root: Path | None = None, repo_root: Path | None = None,
                     now: datetime | None = None) -> dict:
    """Read stored input collections. No producer/transfer-repair function is called.

    In particular position_transfer_normalize.list_transfer_history calls
    ensure_tables(), so it is not used by this read-only projection. The table
    it owns is read through SELECT, without importing its writer.
    """
    from lib import portfolio_positions
    from lib.data_broker import trade_journey

    now = now or datetime.now(timezone.utc)
    root = Path(state_root) if state_root is not None else trade_journey._state_root()
    repo = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    database = db_query if db_query is not None else trade_journey._db_query()

    def db(sql, params=None):
        if database is None:
            raise RuntimeError("database unavailable")
        result = database(sql, params)
        # db_adapter returns None on a connection/query failure, [] on a
        # successful empty SELECT. Those states must never share a zero count.
        if result is None or isinstance(result, bool):
            raise RuntimeError("database SELECT result unavailable")
        return result
    result: dict[str, Any] = {"as_of": now.isoformat(), "sources": {}, "files": {},
                              "provider_calls": 0, "writes": 0, "read_only": True}
    names = ["schwab_round_trips", "trade_closed"]
    if kind == "history":
        names += ["trade_transactions", "position_transfer_history"]
    if kind == "calendar":
        names += ["catalyst_events"]
    for name in names:
        if database is None:
            result["sources"][name] = {"status": "missing", "reason": "database unavailable", "rows": []}
            continue
        try:
            rows = [dict(r) for r in (db(SOURCE_SQL[name], (READ_ROWS + 1,)) or [])]
            result["sources"][name] = {"status": "ok", "as_of": now.isoformat(),
                "rows": rows[:READ_ROWS], "truncated": len(rows) > READ_ROWS,
                "query_sha256": hashlib.sha256(SOURCE_SQL[name].encode()).hexdigest()}
        except Exception as exc:  # a missing source remains a gap, not a zero
            result["sources"][name] = {"status": "missing", "reason": type(exc).__name__, "rows": []}

    holdings_path = root.joinpath(*portfolio_positions.STORE_REL)
    try:
        before = holdings_path.stat()
        if before.st_size > 32_000_000:
            raise ValueError("holdings document exceeds read bound")
        holdings = portfolio_positions.load_store(holdings_path)
        if not isinstance(holdings.get("holdings"), list):
            raise ValueError("holdings rows missing or malformed")
        after = holdings_path.stat()
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError("holdings changed during read")
        result["files"]["holdings"] = {"status": "ok", "document": holdings,
            "path": str(holdings_path),
            "written_at": datetime.fromtimestamp(after.st_mtime, timezone.utc).isoformat()}
    except (OSError, ValueError) as exc:
        result["files"]["holdings"] = {"status": "missing", "reason": str(exc) if isinstance(exc, ValueError)
                                         else type(exc).__name__, "path": str(holdings_path)}

    stored_files = {
        "reentry": root / "data/runtime/reentry_decision_desk_latest.json",
        "ingest_receipt": root / "data/runtime/schwab_transaction_ingest_last.json",
        "stop_health_receipt": root / "data/runtime/stop_health_last.json",
    }
    if kind == "history":
        stored_files["tax_lots"] = root / "data/portfolios/state/tax_lots.json"
        stored_files["legacy_journal"] = root / "data/portfolios/state/trade_journal.json"
    for key, path in stored_files.items():
        result["files"][key] = bounded_json(path)
    try:
        from lib.data_broker.watch_domains import membership_operator
        membership = membership_operator(db)
        result["operator_membership"] = membership
    except Exception as exc:
        result["operator_membership"] = {"names": {}, "sources": {}, "reason": type(exc).__name__}
    result["mapping"] = {"snaptrade_accounts_present": (repo / "config/snaptrade_accounts.json").is_file(),
                         "source": "release config/snaptrade_accounts.json presence only"}

    trips, _ = normalise_closed(result)
    holdings = file_document(result, "holdings")
    syms = {r["symbol"] for r in trips} | {symbol(r.get("symbol")) for r in holdings.get("holdings") or []}
    try:
        from lib.data_broker.cio_company_facts import for_security, load_snapshot
        from scripts.lib.identity_carriage import resolve_security_identity
        facts = load_snapshot(root)
        result["company_facts"] = {s: for_security(facts, s,
            resolve_security_identity(s, root=root).get("security_guid"), now=now)["company_facts"]
            for s in sorted(syms) if s}
    except Exception as exc:
        result["company_facts"] = {}
        result["company_facts_missing_reason"] = type(exc).__name__
    return result


def coverage(snapshot: dict, required: tuple[str, ...]) -> dict:
    missing = [g for name in required if (g := source_gap(snapshot, name))]
    return {"status": "COMPLETE" if not missing else "PARTIAL", "missing_sources": [g["source"] for g in missing],
            "reasons": [g["reason"] for g in missing]}


def trip_stats(trips: list[dict], *, complete: bool) -> dict:
    """Financial aggregates over known facts. Unknown basis never becomes zero."""
    amounts = [v for r in trips if (v := number(r.get("realized_pl"))) is not None]
    holds = [v for r in trips if (v := number(r.get("hold_days"))) is not None]
    returns = [v for r in trips if (v := number(r.get("return_pct"))) is not None]
    priced = len(amounts) == len(trips)
    total = round(math.fsum(amounts), 2) if amounts else (0.0 if complete and not trips else None)
    ordered = sorted(holds)
    mid = len(ordered) // 2
    median = (ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2) if ordered else None
    return {"round_trip_count": len(trips) if complete else None, "known_trade_count": len(trips),
            "known_realized_pl": total, "realized_pl": total if complete and priced else None,
            "unpriced_trade_count": len(trips) - len(amounts),
            "win_rate_pct": round(sum(v > 0 for v in amounts) / len(amounts) * 100, 2)
                if complete and priced and amounts else None,
            "avg_hold_days": math.fsum(holds) / len(holds) if holds and len(holds) == len(trips) and complete else None,
            "median_hold_days": median if len(holds) == len(trips) and complete else None,
            "best_trip_pct": max(returns) if returns and len(returns) == len(trips) and complete else None,
            "worst_trip_pct": min(returns) if returns and len(returns) == len(trips) and complete else None}

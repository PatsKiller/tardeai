"""Read-only TradeInView projection of the canonical options journal view."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from scripts.lib.options_workflow import number, timestamp

CLOSED = ("closed", "rolled", "assigned", "exercised", "expired")


def enrich(row):
    row = dict(row)
    snap = row.get("exit_snapshot") or row.get("latest_snapshot") or {}
    price, at = number(snap.get("underlying_price")), timestamp(snap.get("quote_timestamp"))
    row["legs"] = [dict(l) for l in row.get("legs") or []]
    for leg in row["legs"]:
        strike = number(leg.get("strike"))
        right = leg.get("option_type") or ("put" if str(leg.get("role")).endswith("put") else
                                            "call" if str(leg.get("role")).endswith("call") else None)
        m = "UNKNOWN"
        if price is not None and at is not None and strike is not None and right in {"call", "put"}:
            m = "ATM" if price == strike else "ITM" if (price > strike if right == "call" else price < strike) else "OTM"
        leg.update(option_type=right, moneyness=m, moneyness_underlying_price=price,
                   moneyness_as_of=at.isoformat() if at else None)
    row["basis_status"] = "known" if row["legs"] and all(l.get("opening_price") is not None for l in row["legs"]) else "unknown"
    row["completed_trade"] = row.get("status") in CLOSED and row.get("outcome_validity") == "closed_outcome_recorded"
    row["deep_link"] = f"/v3/trading?tab=Options&otab=Lifecycle&spid={row['strategy_position_id']}"
    return row


def filters(account=None, days=365, strategy=None, status=None, symbol=None, spid=None, roll_root=None):
    days = int(days)
    if not 1 <= days <= 36500:
        raise ValueError("days must be between 1 and 36500")
    where, params = ["(v.status IN ('open','closing','unknown') OR COALESCE(v.closed_at,v.opened_at) >= NOW() - make_interval(days => %s))"], [days]
    for col, value in (("account_key", account), ("strategy_type", strategy), ("status", status),
                       ("underlying", str(symbol).upper() if symbol else None),
                       ("strategy_position_id", int(spid) if spid else None),
                       ("roll_root_id", int(roll_root) if roll_root else None)):
        if value is not None and value != "":
            where.append(f"v.{col}=%s")
            params.append(value)
    return " AND ".join(where), params


def summary(query, account=None, days=365, *, limit=25, offset=0, strategy=None, status=None,
            symbol=None, spid=None, roll_root=None, export=False):
    limit, offset = min(100, max(1, int(limit))), max(0, int(offset))
    where, params = filters(account, days, strategy, status, symbol, spid, roll_root)
    # Aggregation is deliberately a separate unpaginated query. Unknown outcomes
    # remain outside win-rate denominators and are reported alongside known P&L.
    stats = query(f"""SELECT COUNT(*) AS total_strategies,
        COUNT(*) FILTER (WHERE v.status IN ('open','closing')) AS open_strategies,
        COUNT(*) FILTER (WHERE v.status IN ('closed','rolled','assigned','exercised','expired')
            AND v.outcome_validity='closed_outcome_recorded') AS completed_trades,
        COUNT(*) FILTER (WHERE v.status IN ('closed','rolled','assigned','exercised','expired')
            AND v.realized_pnl IS NOT NULL AND v.outcome_validity='closed_outcome_recorded') AS known_outcomes,
        COUNT(*) FILTER (WHERE v.status IN ('closed','rolled','assigned','exercised','expired')
            AND (v.realized_pnl IS NULL OR v.outcome_validity<>'closed_outcome_recorded')) AS incomplete_outcomes,
        COUNT(*) FILTER (WHERE v.status IN ('closed','rolled','assigned','exercised','expired')
            AND v.realized_pnl > 0 AND v.outcome_validity='closed_outcome_recorded') AS wins,
        SUM(v.realized_pnl) FILTER (WHERE v.outcome_validity='closed_outcome_recorded') AS known_realized_pnl,
        SUM(v.unrealized_pnl) FILTER (WHERE v.status IN ('open','closing')) AS known_unrealized_pnl,
        COUNT(*) FILTER (WHERE v.status IN ('open','closing') AND v.unrealized_pnl IS NULL) AS unknown_unrealized
        FROM v_options_journal v WHERE {where}""", params, fetch="one") or {}
    suffix = "" if export else " LIMIT %s OFFSET %s"
    rows = query(f"SELECT row_to_json(v) AS entry FROM v_options_journal v WHERE {where} "
                 "ORDER BY COALESCE(v.closed_at,v.opened_at) DESC NULLS LAST, v.strategy_position_id DESC" + suffix,
                 params if export else [*params, limit, offset], fetch="all") or []
    entries = [enrich(r["entry"] if isinstance(r["entry"], dict) else json.loads(r["entry"])) for r in rows]
    warnings = []
    ids = [r["strategy_position_id"] for r in entries]
    if ids:
        for key, table in (("fill_evidence", "options_fill_evidence"), ("stock_transfers", "options_stock_basis_transfers")):
            try:
                evidence = query(f"SELECT row_to_json(e) AS entry FROM {table} e WHERE strategy_position_id=ANY(%s)", (ids,)) or []
                for row in entries:
                    row[key] = [r["entry"] for r in evidence if r["entry"]["strategy_position_id"] == row["strategy_position_id"]]
            except Exception:
                warnings.append(f"{key} unavailable; evidence is incomplete")
    known = int(stats.get("known_outcomes") or 0)
    total = int(stats.get("total_strategies") or 0)
    out = {"ok": True, "source": "v_options_journal", "as_of": datetime.now(timezone.utc).isoformat(),
           "entries": entries, "data_warnings": warnings, "summary": {**stats, "win_rate": round(100 * int(stats.get("wins") or 0) / known, 2) if known else None},
           "limit": limit, "offset": offset, "total": total, "has_more": offset + len(entries) < total,
           "aggregation_scope": "complete filtered dataset", "audit_note": "Unfilled proposals remain in the approval queue audit, outside completed trade counts"}
    if export:
        stream = io.StringIO()
        columns = ["strategy_position_id", "roll_root_id", "account_key", "underlying", "strategy_type", "status",
                   "opened_at", "closed_at", "realized_pnl", "unrealized_pnl", "basis_status", "outcome_validity",
                   "legs", "events", "entry_snapshot", "exit_snapshot", "fill_evidence", "stock_transfers"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in entries:
            values = {k: json.dumps(row.get(k), default=str) if isinstance(row.get(k), (dict, list)) else row.get(k) for k in columns}
            # CSV is intended for spreadsheets; neutralize formula-like text.
            values = {k: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for k, v in values.items()}
            writer.writerow(values)
        out.update(csv=stream.getvalue(), exported_rows=len(entries))
    return out

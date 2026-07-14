"""deploy_events_db — schema + persistence for post-sale Redeploy events (advisory only)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION = PROJECT_ROOT / "migrations" / "2026_07_14_deploy_redeploy_events.sql"

_VALID_STATUS = frozenset({"open", "settled", "dismissed", "approved"})
_VALID_SOURCE = frozenset({"live_detect", "backfill", "manual"})


def ensure_deploy_tables(cur) -> None:
    if MIGRATION.is_file():
        cur.execute(MIGRATION.read_text())


def _json(v: Any) -> str:
    return json.dumps(v if v is not None else [])


def upsert_deploy_event(cur, row: dict[str, Any]) -> dict[str, Any]:
    """Insert or update deploy_events by event_key. Returns {ok, id, created}."""
    ensure_deploy_tables(cur)
    key = str(row["event_key"])
    status = str(row.get("status") or "open")
    if status not in _VALID_STATUS:
        status = "open"
    source = str(row.get("source") or "live_detect")
    if source not in _VALID_SOURCE:
        source = "live_detect"
    cur.execute("SELECT id FROM deploy_events WHERE event_key=%s", (key,))
    existing = cur.fetchone()
    fields = (
        key,
        str(row["symbol"]).upper(),
        str(row["account"]),
        row["sold_at"],
        row.get("proceeds_usd"),
        row.get("shares_sold"),
        row.get("realized_pnl"),
        row.get("instrument_type"),
        row.get("proxy_symbol"),
        row.get("proxy_sleeve"),
        status,
        bool(row.get("proceeds_settled")),
        row.get("cash_visible_usd"),
        _json(row.get("lookthrough_delta") or []),
        _json(row.get("redeploy_plan") or []),
        source,
        row.get("txn_ref"),
        row.get("txn_id"),
        row.get("dismiss_reason"),
        _json(row.get("metadata") or {}),
    )
    if existing:
        cur.execute(
            """UPDATE deploy_events SET
               symbol=%s, account=%s, sold_at=%s, proceeds_usd=%s, shares_sold=%s,
               realized_pnl=%s, instrument_type=%s, proxy_symbol=%s, proxy_sleeve=%s,
               status=%s, proceeds_settled=%s, cash_visible_usd=%s,
               lookthrough_delta=%s::jsonb, redeploy_plan=%s::jsonb,
               source=%s, txn_ref=%s, txn_id=%s, dismiss_reason=%s, metadata=%s::jsonb,
               updated_at=NOW()
               WHERE event_key=%s RETURNING id""",
            (*fields[1:], key),
        )
        eid = cur.fetchone()[0]
        return {"ok": True, "id": eid, "created": False, "event_key": key}
    cur.execute(
        """INSERT INTO deploy_events
           (event_key, symbol, account, sold_at, proceeds_usd, shares_sold, realized_pnl,
            instrument_type, proxy_symbol, proxy_sleeve, status, proceeds_settled, cash_visible_usd,
            lookthrough_delta, redeploy_plan, source, txn_ref, txn_id, dismiss_reason, metadata)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb)
           RETURNING id""",
        fields,
    )
    eid = cur.fetchone()[0]
    return {"ok": True, "id": eid, "created": True, "event_key": key}


def list_deploy_events(cur, *, status: str | None = None, account: str | None = None,
                       source: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    ensure_deploy_tables(cur)
    clauses, params = [], []
    if status:
        clauses.append("status=%s")
        params.append(status)
    if account:
        clauses.append("account=%s")
        params.append(account)
    if source:
        clauses.append("source=%s")
        params.append(source)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    cur.execute(
        f"""SELECT id, event_key, symbol, account, sold_at, proceeds_usd, shares_sold, realized_pnl,
                   instrument_type, proxy_symbol, proxy_sleeve, status, proceeds_settled,
                   cash_visible_usd, lookthrough_delta, redeploy_plan, source, txn_ref, txn_id,
                   dismiss_reason, metadata, created_at, updated_at
            FROM deploy_events{where}
            ORDER BY sold_at DESC, id DESC LIMIT %s""",
        tuple(params),
    )
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        row = dict(zip(cols, r))
        for jf in ("lookthrough_delta", "redeploy_plan", "metadata"):
            if isinstance(row.get(jf), str):
                try:
                    row[jf] = json.loads(row[jf])
                except Exception:
                    pass
        out.append(row)
    return out


def backfill_status_for_date(sold_at: date, *, today: date | None = None,
                             dismiss_after_days: int = 90) -> tuple[str, str | None]:
    """Approved policy: auto-dismiss sells older than 90 days on backfill."""
    today = today or date.today()
    age = (today - sold_at).days
    if age > dismiss_after_days:
        return "dismissed", "historical_backfill_over_90d"
    return "open", None
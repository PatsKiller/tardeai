"""Last-known broker stops: the stop-warning fallback while Schwab is blind (ZETA incident 2026-10-15).

Since the Schwab app was deactivated (config/schwab_access_mode.yaml mode=forbidden, 2026-10-14) the live
stop read returns UNAVAILABLE, the scan holds zero Schwab stops, and stop_health could only page "DEGRADED".
A resting ZETA stop then filled with no near-trigger warning. This module keeps the warning alive:

  * ``record_snapshot`` writes every clean Schwab stop read to the durable ``stop_last_known`` table
    (stop_lifecycle is rebuilt each run, so it cannot hold a last-known level).
  * ``load_last_known`` returns the newest known level per (account, order) from that table, falling back to
    the stop_health SIEM payloads (alert_events), which carry account/order/stop/qty from the last Schwab read.
  * ``holdings_quotes`` prices them from canonical holdings.json (finviz canonical mark, repriced every 15 min);
    no broker call is made anywhere here.
  * ``evaluate`` (pure) flags NEAR_TRIGGER (within near_pct) and TRIGGERED_LIKELY (price at/below the stop).

Read-only on the broker side; the only write is the snapshot table, from data the scan already read.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "stop_last_known_watch.json"
HOLDINGS_PATH = ROOT / "data" / "portfolios" / "state" / "holdings.json"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "near_trigger_pct": 2.0,
    "lookback_days": 10,
    "near_trigger_realert_hours": 2,
    "triggered_likely_realert": "once_per_et_day",
    "degraded_page": "once_per_et_day",
    "brokers": ["schwab"],
}

NEAR_TRIGGER = "NEAR_TRIGGER"
TRIGGERED_LIKELY = "TRIGGERED_LIKELY"
#: "not_in_read": a later read of that account no longer returned the order (rows are marked, never deleted).
_DEAD_STATUS = {"filled", "canceled", "cancelled", "rejected", "expired", "replaced", "not_in_read"}


def load_config(path: Path | None = None) -> dict:
    """The watch config merged over DEFAULTS; a missing or broken file keeps the defaults (fail toward warning)."""
    cfg = dict(DEFAULTS)
    try:
        p = path or CONFIG_PATH
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001
        pass
    return cfg


def _broker(r: dict) -> str:
    """The record's own broker; a record without one belongs to the first configured watched broker."""
    return str(r.get("broker") or (load_config().get("brokers") or DEFAULTS["brokers"])[0])


def _ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None   # NaN -> None


_DDL = """CREATE TABLE IF NOT EXISTS stop_last_known (
            broker TEXT NOT NULL, account TEXT NOT NULL, symbol TEXT NOT NULL, order_id TEXT NOT NULL,
            order_type TEXT, stop_price NUMERIC, qty NUMERIC, status TEXT,
            captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), origin TEXT NOT NULL DEFAULT 'schwab_read',
            note TEXT, PRIMARY KEY (broker, account, order_id))"""


def record_snapshot(rows: Iterable[dict], *, complete: bool, conn=None) -> int:
    """Persist the stops a Schwab read just returned. ``complete`` (every account answered) supersedes the whole
    broker snapshot, so a cancelled stop drops out; a partial read supersedes only the accounts that answered.
    Superseded rows are marked status='not_in_read' (never deleted). Never raises: losing the snapshot must
    not break the scan."""
    rows = [r for r in rows if r.get("order_id") and r.get("account")]
    try:
        if conn is None:
            from db_adapter import _get_conn
            conn = _get_conn()
        cur = conn.cursor()
        cur.execute(_DDL)
        brokers = sorted({str(_broker(r)) for r in rows}) or [_broker({})]
        # A complete broker read is the truth: operator-entered levels for those accounts are superseded too.
        if complete:
            cur.execute("UPDATE stop_last_known SET status='not_in_read', captured_at=NOW() "
                        "WHERE broker = ANY(%s) AND COALESCE(status,'') <> 'not_in_read'", (brokers,))
        else:
            accts = sorted({str(r["account"]) for r in rows})
            if accts:
                cur.execute("UPDATE stop_last_known SET status='not_in_read', captured_at=NOW() "
                            "WHERE broker = ANY(%s) AND account = ANY(%s) AND COALESCE(status,'') <> 'not_in_read'",
                            (brokers, accts))
        for r in rows:
            cur.execute("""INSERT INTO stop_last_known
                             (broker, account, symbol, order_id, order_type, stop_price, qty, status, captured_at,
                              origin)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),'schwab_read')
                           ON CONFLICT (broker, account, order_id) DO UPDATE SET
                             symbol=EXCLUDED.symbol, order_type=EXCLUDED.order_type,
                             stop_price=EXCLUDED.stop_price, qty=EXCLUDED.qty, status=EXCLUDED.status,
                             captured_at=EXCLUDED.captured_at, origin='schwab_read'""",
                        (str(_broker(r)), str(r["account"]), str(r.get("symbol") or "").upper(),
                         str(r["order_id"]), r.get("order_type"), r.get("stop_price"), r.get("qty"),
                         r.get("status")))
        conn.commit()
        return len(rows)
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        return 0


def merge_sources(snapshot_rows: list[dict], alert_rows: list[dict]) -> list[dict]:
    """Newest observation per (broker, account, order_id). Pure.

    ``alert_rows`` older than that account's snapshot are dropped (the snapshot saw the full order list then,
    so an order absent from it was gone). An order whose newest observation is TRIGGERED, or whose status is
    terminal, is not a resting stop any more."""
    snap_at: dict[tuple, datetime] = {}
    op_at: dict[tuple, datetime] = {}
    for r in snapshot_rows:
        at = _ts(r.get("captured_at"))
        if not at:
            continue
        if r.get("origin") == "operator":
            # An operator-entered level replaces every OLDER observation of that position's stops.
            k = (_broker(r), r.get("account"), str(r.get("symbol") or "").upper())
            if k not in op_at or at > op_at[k]:
                op_at[k] = at
            continue
        k = (_broker(r), r.get("account"))
        if k not in snap_at or at > snap_at[k]:
            snap_at[k] = at
    best: dict[tuple, dict] = {}
    for r in list(snapshot_rows) + list(alert_rows):
        broker = _broker(r)
        at = _ts(r.get("captured_at"))
        if at is None:
            continue
        floor = snap_at.get((broker, r.get("account")))
        if r.get("source") == "alert_events" and floor and at < floor:
            continue
        op = op_at.get((broker, r.get("account"), str(r.get("symbol") or "").upper()))
        if r.get("origin") != "operator" and op and at < op:
            continue
        k = (broker, r.get("account"), str(r.get("order_id")))
        if k not in best or at > _ts(best[k]["captured_at"]):
            best[k] = {**r, "broker": broker, "captured_at": at}
    out = []
    for r in best.values():
        if str(r.get("last_condition") or "").upper() == "TRIGGERED":
            continue
        if str(r.get("status") or "").lower() in _DEAD_STATUS:
            continue
        if _num(r.get("stop_price")) is None:
            continue
        out.append(r)
    return sorted(out, key=lambda r: (r["account"], r["symbol"], r["order_id"]))


def load_last_known(*, brokers: Iterable[str] = ("schwab",), accounts: Iterable[str] | None = None,
                    lookback_days: float = 10, now: datetime | None = None, conn=None) -> list[dict]:
    """Last-known resting stops (DB read only). Each row: broker, account, symbol, order_id, order_type,
    stop_price, qty, captured_at, source ('stop_last_known' | 'alert_events')."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=float(lookback_days))
    brokers = list(brokers)
    accounts = list(accounts) if accounts is not None else None
    snap: list[dict] = []
    alerts: list[dict] = []
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT broker, account, symbol, order_id, order_type, stop_price, qty, status, captured_at,
                              origin
                       FROM stop_last_known WHERE broker = ANY(%s) AND captured_at >= %s""", (brokers, since))
        for b, a, s, o, t, sp, q, st, at, origin in cur.fetchall():
            snap.append({"broker": b, "account": a, "symbol": str(s or "").upper(), "order_id": str(o),
                         "order_type": t, "stop_price": _num(sp), "qty": _num(q), "status": st,
                         "captured_at": at, "origin": origin, "source": f"stop_last_known:{origin}"})
    except Exception:  # noqa: BLE001 — table not created yet (no clean read since deploy): fall back below
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (parsed_payload->>'account', parsed_payload->>'order_id')
                          parsed_payload->>'broker', parsed_payload->>'account', symbol,
                          parsed_payload->>'order_id', parsed_payload->>'order_type',
                          parsed_payload->>'stop_price', parsed_payload->>'qty',
                          parsed_payload->>'condition', created_at
                   FROM alert_events
                   WHERE source_script = 'stop_health' AND parsed_payload->>'broker' = ANY(%s)
                     AND parsed_payload->>'order_id' IS NOT NULL
                     AND parsed_payload->>'stop_price' IS NOT NULL AND created_at >= %s
                   ORDER BY parsed_payload->>'account', parsed_payload->>'order_id', created_at DESC""",
                (brokers, since))
    for b, a, s, o, t, sp, q, cond, at in cur.fetchall():
        alerts.append({"broker": b, "account": a, "symbol": str(s or "").upper(), "order_id": str(o),
                       "order_type": t, "stop_price": _num(sp), "qty": _num(q), "last_condition": cond,
                       "captured_at": at, "source": "alert_events"})
    rows = merge_sources(snap, alerts)
    if accounts is not None:
        rows = [r for r in rows if r["account"] in accounts]
    return rows


def record_operator_stop(*, account: str, symbol: str, stop_price: float | None, qty: float | None = None,
                         order_id: str | None = None, broker: str = "schwab", status: str = "open",
                         note: str | None = None, conn=None) -> dict:
    """Operator-entered stop level (the operator set or saw it at Schwab himself). Local table only — no broker
    call. ``status`` 'cancelled'/'filled' retires a level. Returns the row written."""
    symbol = str(symbol or "").upper().strip()
    if not account or not symbol:
        raise ValueError("account and symbol are required")
    if status == "open" and (stop_price is None or float(stop_price) <= 0):
        raise ValueError("an open stop needs a positive stop_price")
    oid = str(order_id or f"operator-{symbol}-{account}")
    row = {"broker": broker, "account": account, "symbol": symbol, "order_id": oid, "order_type": "STOP",
           "stop_price": None if stop_price is None else float(stop_price),
           "qty": None if qty is None else float(qty), "status": status, "note": note, "origin": "operator"}
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    cur = conn.cursor()
    cur.execute(_DDL)
    cur.execute("""INSERT INTO stop_last_known
                     (broker, account, symbol, order_id, order_type, stop_price, qty, status, captured_at, origin, note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),'operator',%s)
                   ON CONFLICT (broker, account, order_id) DO UPDATE SET
                     symbol=EXCLUDED.symbol, stop_price=COALESCE(EXCLUDED.stop_price, stop_last_known.stop_price),
                     qty=COALESCE(EXCLUDED.qty, stop_last_known.qty), status=EXCLUDED.status,
                     captured_at=EXCLUDED.captured_at, origin='operator', note=EXCLUDED.note""",
                (broker, account, symbol, oid, "STOP", row["stop_price"], row["qty"], status, note))
    conn.commit()
    return row


def holdings_quotes(path: Path | None = None) -> dict:
    """(holdings account label, SYMBOL) -> shares, price, price_source, price_at from canonical holdings.json.

    current_price there is the finviz canonical mark (finviz-intraday-repricer, every 15 min): no Schwab call."""
    out: dict = {}
    try:
        doc = json.loads((path or HOLDINGS_PATH).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    for r in doc.get("holdings", []) or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
        if not sym:
            continue
        out[(str(r.get("account") or ""), sym)] = {
            "shares": _num(r.get("shares", r.get("qty"))),
            "price": _num(r.get("current_price", r.get("price"))),
            "price_source": r.get("price_source") or r.get("canonical_mark_source"),
            "price_at": r.get("canonical_mark_ingested_at") or doc.get("last_repriced"),
        }
    return out


def evaluate(stops: list[dict], quotes: dict, *, near_pct: float,
             label: Callable[[str], str] = lambda a: a) -> list[dict]:
    """Pure: one finding per stop at or within ``near_pct`` of its last-known level on a held position.

    proximity_pct = (price - stop) / price * 100 (same as stop_lifecycle_monitor). <= 0 -> TRIGGERED_LIKELY."""
    found = []
    for s in stops:
        sp = _num(s.get("stop_price"))
        q = quotes.get((label(s["account"]), s["symbol"])) or quotes.get((s["account"], s["symbol"]))
        if sp is None or not q or not (q.get("shares") or 0) > 0 or not q.get("price"):
            continue
        px = float(q["price"])
        prox = round((px - sp) / px * 100, 2)
        if px <= sp:
            cond = TRIGGERED_LIKELY
        elif prox <= float(near_pct):
            cond = NEAR_TRIGGER
        else:
            continue
        found.append({**s, "condition": cond, "current_price": px, "proximity_pct": prox,
                      "held_qty": q.get("shares"), "price_source": q.get("price_source"),
                      "price_at": q.get("price_at")})
    return sorted(found, key=lambda f: (f["condition"] != TRIGGERED_LIKELY, f["proximity_pct"]))


def held_symbols(quotes: dict, *, account_prefixes: Iterable[str] = ("schwab",)) -> list[str]:
    """'SYM@account' for every held, non-cash position in the blind accounts (sorted)."""
    pref = tuple(account_prefixes)
    out = set()
    for (acct, sym), q in quotes.items():
        if acct.startswith(pref) and (q.get("shares") or 0) > 0 and sym not in ("CASH", "") and not sym.isdigit() \
                and not (len(sym) == 9 and sym[:3].isdigit()):   # CUSIP-keyed rows (bonds/funds)
            out.add(f"{sym}@{acct}")
    return sorted(out)

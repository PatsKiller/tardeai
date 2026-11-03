"""``recovery_cases``: the row, the store, the fills consumer and the case-level replay the spec requires.

One case per symbol × account × exit cluster. The case is *facts*: what was sold, at what price, what survived as a
residual, how material it was, which account can re-enter when, and what the operator decided. Piece B owns the market
triggers; this module stores their result and opens/closes/extends the row from confirmed fills.

The store speaks plain DB-API with a parameter style detected from the connection, so the same code runs on SQLite in
tests and Postgres in production. The Postgres DDL lives in ``2026_11_03_recovery_cases.sql`` at the repo root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from .policy import Eligibility, Policy, _finite, eligibility_for, materiality_tier, residual_display

SCHEMA = "RecoveryCase@v1"

STATES = ("STOPPED_OUT", "WATCHING", "RECOVERING", "RE_ENTRY_READY", "RE_ENTERED", "CLOSED", "SNOOZED")
DECISIONS = ("none", "watching", "re-entered", "closed", "snoozed")

# Portable DDL: no types the two engines disagree about beyond what is written here.
DDL = """
CREATE TABLE IF NOT EXISTS recovery_cases (
    case_key            TEXT PRIMARY KEY,
    symbol              TEXT NOT NULL,
    account             TEXT NOT NULL,
    broker              TEXT,
    cluster_key         TEXT NOT NULL,
    exits_json          TEXT NOT NULL,
    exit_first_date     TEXT,
    exit_last_date      TEXT,
    realized_pnl        REAL,
    pre_exit_shares     REAL,
    residual_shares     REAL,
    pre_exit_weight_pct REAL,
    materiality_tier    TEXT NOT NULL,
    residual_pct_of_pre_exit REAL,
    residual_note       TEXT,
    pre_exit_source     TEXT,
    residual_as_of      TEXT,
    gaps_json           TEXT,
    state               TEXT NOT NULL,
    state_since         TEXT NOT NULL,
    eligibility_json    TEXT NOT NULL,
    plan_json           TEXT,
    last_nudge_at       TEXT,
    last_p1_at          TEXT,
    operator_decision   TEXT NOT NULL DEFAULT 'none',
    operator_note       TEXT,
    opened_at           TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    as_of               TEXT,
    source              TEXT
)
"""


# Literal statements: the column list and placeholder count are fixed here, so no SQL is ever assembled from
# runtime strings (ruff S608). The two dialects differ only in placeholder style and conflict handling.
UPSERT_SQLITE = (
    "INSERT OR REPLACE INTO recovery_cases (case_key, symbol, account, broker, cluster_key, exits_json, exit_first_date, exit_last_date, realized_pnl, pre_exit_shares, residual_shares, pre_exit_weight_pct, materiality_tier, residual_pct_of_pre_exit, residual_note, pre_exit_source, residual_as_of, gaps_json, state, state_since, eligibility_json, plan_json, last_nudge_at, last_p1_at, operator_decision, operator_note, opened_at, updated_at, as_of, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
UPSERT_POSTGRES = (
    "INSERT INTO recovery_cases (case_key, symbol, account, broker, cluster_key, exits_json, exit_first_date, exit_last_date, realized_pnl, pre_exit_shares, residual_shares, pre_exit_weight_pct, materiality_tier, residual_pct_of_pre_exit, residual_note, pre_exit_source, residual_as_of, gaps_json, state, state_since, eligibility_json, plan_json, last_nudge_at, last_p1_at, operator_decision, operator_note, opened_at, updated_at, as_of, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (case_key) DO UPDATE SET symbol=EXCLUDED.symbol, account=EXCLUDED.account, broker=EXCLUDED.broker, cluster_key=EXCLUDED.cluster_key, exits_json=EXCLUDED.exits_json, exit_first_date=EXCLUDED.exit_first_date, exit_last_date=EXCLUDED.exit_last_date, realized_pnl=EXCLUDED.realized_pnl, pre_exit_shares=EXCLUDED.pre_exit_shares, residual_shares=EXCLUDED.residual_shares, pre_exit_weight_pct=EXCLUDED.pre_exit_weight_pct, materiality_tier=EXCLUDED.materiality_tier, residual_pct_of_pre_exit=EXCLUDED.residual_pct_of_pre_exit, residual_note=EXCLUDED.residual_note, pre_exit_source=EXCLUDED.pre_exit_source, residual_as_of=EXCLUDED.residual_as_of, gaps_json=EXCLUDED.gaps_json, state=EXCLUDED.state, state_since=EXCLUDED.state_since, eligibility_json=EXCLUDED.eligibility_json, plan_json=EXCLUDED.plan_json, last_nudge_at=EXCLUDED.last_nudge_at, last_p1_at=EXCLUDED.last_p1_at, operator_decision=EXCLUDED.operator_decision, operator_note=EXCLUDED.operator_note, opened_at=EXCLUDED.opened_at, updated_at=EXCLUDED.updated_at, as_of=EXCLUDED.as_of, source=EXCLUDED.source"
)


def _utc(now: Optional[datetime] = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(now: Optional[datetime] = None) -> str:
    return _utc(now).isoformat(timespec="seconds")


class _Sql:
    """Parameter-style shim: one query text, ``?`` or ``%s`` chosen from the connection's module."""

    def __init__(self, conn: Any) -> None:
        module = type(conn).__module__ or ""
        self.conn = conn
        self.qmark = "sqlite" in module

    def run(self, sql: str, params: Sequence[Any] = ()) -> Any:
        text = sql.replace("%s", "?") if self.qmark else sql.replace("?", "%s")
        cur = self.conn.cursor()   # DB-API: only a cursor executes; psycopg2 connections have no .execute
        cur.execute(text, tuple(params))
        # Return the CURSOR, never execute()'s return value: psycopg2's Cursor.execute returns None, and the old
        # `return cur.execute(...)` made every read raise "'NoneType' object has no attribute 'fetchall'" against a
        # real Postgres connection (cx-openai-2 F2) — construction succeeded, the first get() did not.
        return cur

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        return list(self.run(sql, params).fetchall())


def _json_value(value: Any, default: Any) -> Any:
    """A JSON column as a Python value on BOTH engines.

    SQLite returns the column's text; psycopg2's JSON adapter returns an already-decoded list/dict. Calling
    ``json.loads`` on the decoded value raises "the JSON object must be str, bytes or bytearray, not list"
    (cx-openai-2 F3), so decode only text and pass everything else through.
    """
    if value is None or value == "":
        return default
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def ensure_schema(conn: Any) -> None:
    _Sql(conn).run(DDL)
    conn.commit()


def case_key(symbol: str, account: str, cluster_key: str) -> str:
    return f"{str(symbol).upper()}::{account}::{cluster_key}"


@dataclass(frozen=True)
class ExitFill:
    """One confirmed exit that belongs to a case's cluster."""

    symbol: str
    account: str
    exit_date: date
    shares: Optional[float]          # None = the fill's share count is unknown; never a quiet 0
    price: float
    realized_pnl: Optional[float]    # None = the row's realized P&L is unknown; never a quiet 0
    stop_price: Optional[float] = None
    broker: str = ""
    source: str = "broker-fills"
    #: The source row's OWN stable identity, namespaced by table: ``stopped_out_watch:<id>`` or
    #: ``trade_transactions:<dedupe_key>``. None = the source carries no key for this row (a legacy or
    #: paper-scaled row), which is an UNKNOWN identity, never a licence to match on price (codex F16).
    #: The namespace matters: two providers' local ids need not denote the same economic event.
    source_id: Optional[str] = None


@dataclass
class RecoveryCase:
    case_key: str
    symbol: str
    account: str
    broker: str
    cluster_key: str
    exits: list[dict[str, Any]]
    realized_pnl: float
    pre_exit_shares: Optional[float]
    residual_shares: Optional[float]
    pre_exit_weight_pct: Optional[float]
    materiality_tier: str
    residual_pct_of_pre_exit: Optional[float]
    residual_note: str
    state: str
    state_since: str
    eligibility: list[Eligibility]
    operator_decision: str = "none"
    plan: Optional[dict[str, Any]] = None
    last_nudge_at: Optional[str] = None
    last_p1_at: Optional[str] = None
    opened_at: str = ""
    updated_at: str = ""
    as_of: str = ""
    source: str = ""
    pre_exit_source: str = ""                       # where the pre-exit denominator came from (never inferred silently)
    residual_as_of: Optional[str] = None            # the snapshot clock behind residual_shares, when the store says
    gaps: list[str] = field(default_factory=list)   # what could not be read; travels with the row, not just the pass
    operator_note: Optional[str] = None             # preserved across refreshes (cx-openai-2 F7)

    def eligibility_line(self) -> str:
        return " · ".join(e.line() for e in self.eligibility)

    def pending_operator_decision(self) -> bool:
        """Row-level pendency: an eligibility answer the operator has not given yet is still pending."""
        return any(e.pending_operator_decision for e in self.eligibility)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "case_key": self.case_key,
            "symbol": self.symbol,
            "account": self.account,
            "broker": self.broker,
            "cluster_key": self.cluster_key,
            "exits": self.exits,
            "realized_pnl": self.realized_pnl,
            "pre_exit_shares": self.pre_exit_shares,
            "pre_exit_source": self.pre_exit_source,
            "residual_shares": self.residual_shares,
            "residual_as_of": self.residual_as_of,
            "pre_exit_weight_pct": self.pre_exit_weight_pct,
            "materiality_tier": self.materiality_tier,
            "residual_pct_of_pre_exit": self.residual_pct_of_pre_exit,
            "residual_note": self.residual_note,
            "state": self.state,
            "state_since": self.state_since,
            "eligibility": [{**e.__dict__, "answered": not e.pending_operator_decision}
                            for e in self.eligibility],
            "pending_operator_decision": self.pending_operator_decision(),
            "operator_decision": self.operator_decision,
            "operator_note": self.operator_note,
            "plan": self.plan,
            "last_nudge_at": self.last_nudge_at,
            "last_p1_at": self.last_p1_at,
            "opened_at": self.opened_at,
            "updated_at": self.updated_at,
            "as_of": self.as_of,
            "source": self.source,
            "gaps": list(self.gaps),
        }


# Words that turn proposal text into an instruction. MBI_BEHAVIOR = 0: this engine never sizes, orders, stops or
# weights anything, and the plan column is the one free-form field it stores, so it is the one place the rail has to
# be enforced rather than assumed (cx-openai-2 F5).
_EXECUTION_KEYS = frozenset({
    "shares", "share_count", "qty", "quantity", "size", "sizing", "position_size", "notional", "amount",
    "stop", "stop_price", "stoploss", "stop_loss", "target", "target_price", "take_profit",
    "order", "orders", "order_type", "order_side", "side", "buy", "sell", "limit", "limit_price",
    "weight", "allocation", "allocation_pct", "broker_order",
})


def _refuse_execution_values(node: Any, path: str = "plan", depth: int = 0) -> None:
    """Raise if a plan carries any execution-shaped value. Text is fine; a share count is not."""
    if depth > 6:
        raise ValueError("plan is nested too deeply to verify; refusing to store it")
    if isinstance(node, Mapping):
        for key, value in node.items():
            lowered = str(key).strip().lower()
            if lowered in _EXECUTION_KEYS:
                raise ValueError(f"plan may not carry an execution value ({path}.{key}); the plan is proposal text "
                                 "and this engine never sizes, orders or stops (MBI_BEHAVIOR = 0)")
            _refuse_execution_values(value, f"{path}.{key}", depth + 1)
    elif isinstance(node, (list, tuple)):  # noqa: E501
        for index, item in enumerate(node):
            _refuse_execution_values(item, f"{path}[{index}]", depth + 1)


class CaseStore:
    def __init__(self, conn: Any, policy: Policy) -> None:
        self.sql = _Sql(conn)
        self.conn = conn
        self.policy = policy
        ensure_schema(conn)

    # -- writes --------------------------------------------------------------------------------------------
    COLUMNS = ("case_key", "symbol", "account", "broker", "cluster_key", "exits_json", "exit_first_date",
               "exit_last_date", "realized_pnl", "pre_exit_shares", "residual_shares", "pre_exit_weight_pct",
               "materiality_tier", "residual_pct_of_pre_exit", "residual_note", "pre_exit_source", "residual_as_of",
               "gaps_json", "state", "state_since", "eligibility_json", "plan_json", "last_nudge_at", "last_p1_at",
               "operator_decision", "operator_note", "opened_at", "updated_at", "as_of", "source")

    def upsert(self, case: RecoveryCase) -> RecoveryCase:
        if case.plan:
            _refuse_execution_values(case.plan)
        values = (
            case.case_key, case.symbol, case.account, case.broker, case.cluster_key,
            json.dumps(case.exits, sort_keys=True), case.exits[0]["date"] if case.exits else None,
            case.exits[-1]["date"] if case.exits else None,
            case.realized_pnl, case.pre_exit_shares, case.residual_shares, case.pre_exit_weight_pct,
            case.materiality_tier, case.residual_pct_of_pre_exit, case.residual_note, case.pre_exit_source or None,
            case.residual_as_of, json.dumps(list(case.gaps), sort_keys=True),
            case.state, case.state_since,
            json.dumps([e.__dict__ for e in case.eligibility], sort_keys=True),
            json.dumps(case.plan, sort_keys=True) if case.plan else None,
            case.last_nudge_at, case.last_p1_at, case.operator_decision, case.operator_note,
            case.opened_at, case.updated_at, case.as_of, case.source,
        )
        self.sql.run(UPSERT_SQLITE if self.sql.qmark else UPSERT_POSTGRES, values)
        self.conn.commit()
        return case

    def set_state(self, key: str, state: str, *, now: Optional[datetime] = None) -> None:
        if state not in STATES:
            raise ValueError(f"unknown recovery state {state!r}")
        moment = _iso(now)
        self.sql.run("UPDATE recovery_cases SET state=%s, state_since=%s, updated_at=%s WHERE case_key=%s",
                     (state, moment, moment, key))
        self.conn.commit()

    def record_nudge(self, key: str, *, p1: bool, now: Optional[datetime] = None) -> None:
        moment = _iso(now)
        if p1:
            self.sql.run("UPDATE recovery_cases SET last_nudge_at=%s, last_p1_at=%s, updated_at=%s WHERE case_key=%s",
                         (moment, moment, moment, key))
        else:
            self.sql.run("UPDATE recovery_cases SET last_nudge_at=%s, updated_at=%s WHERE case_key=%s",
                         (moment, moment, key))
        self.conn.commit()

    def set_decision(self, key: str, decision: str, *, note: Optional[str] = None) -> None:
        if decision not in DECISIONS:
            raise ValueError(f"unknown operator decision {decision!r}")
        self.sql.run("UPDATE recovery_cases SET operator_decision=%s, operator_note=%s, updated_at=%s "
                     "WHERE case_key=%s", (decision, note, _iso(), key))
        self.conn.commit()

    # -- reads ---------------------------------------------------------------------------------------------
    def get(self, key: str) -> Optional[RecoveryCase]:
        rows = self.sql.rows("SELECT * FROM recovery_cases WHERE case_key=%s", (key,))
        return self._row_to_case(rows[0]) if rows else None

    def list(self, *, state: Optional[str] = None) -> list[RecoveryCase]:
        if state:
            rows = self.sql.rows("SELECT * FROM recovery_cases WHERE state=%s ORDER BY exit_last_date DESC", (state,))
        else:
            rows = self.sql.rows("SELECT * FROM recovery_cases ORDER BY exit_last_date DESC")
        return [self._row_to_case(row) for row in rows]

    def _row_to_case(self, row: Sequence[Any]) -> RecoveryCase:
        keys = ("case_key", "symbol", "account", "broker", "cluster_key", "exits_json", "exit_first_date",
                "exit_last_date", "realized_pnl", "pre_exit_shares", "residual_shares", "pre_exit_weight_pct",
                "materiality_tier", "residual_pct_of_pre_exit", "residual_note", "pre_exit_source",
                "residual_as_of", "gaps_json", "state", "state_since", "eligibility_json",
                "plan_json", "last_nudge_at", "last_p1_at", "operator_decision", "operator_note", "opened_at",
                "updated_at", "as_of", "source")
        data = dict(zip(keys, row))
        eligibility = [Eligibility(**item) for item in _json_value(data["eligibility_json"], [])]
        plan = _json_value(data["plan_json"], None)
        return RecoveryCase(
            case_key=data["case_key"], symbol=data["symbol"], account=data["account"],
            broker=data["broker"] or "", cluster_key=data["cluster_key"],
            exits=_json_value(data["exits_json"], []),
            # realized_pnl stays None when the column is NULL: "unknown", never a quiet 0.0 loss (F4).
            realized_pnl=_finite(data["realized_pnl"]),
            pre_exit_shares=data["pre_exit_shares"],
            residual_shares=(None if data["residual_shares"] is None else float(data["residual_shares"])),
            pre_exit_weight_pct=data["pre_exit_weight_pct"],
            materiality_tier=data["materiality_tier"], residual_pct_of_pre_exit=data["residual_pct_of_pre_exit"],
            residual_note=data["residual_note"] or "", state=data["state"], state_since=data["state_since"],
            eligibility=eligibility, operator_decision=data["operator_decision"] or "none", plan=plan,
            last_nudge_at=data["last_nudge_at"], last_p1_at=data["last_p1_at"],
            opened_at=data["opened_at"], updated_at=data["updated_at"], as_of=data["as_of"] or "",
            source=data["source"] or "", pre_exit_source=data["pre_exit_source"] or "",
            residual_as_of=data["residual_as_of"],
            gaps=[str(g) for g in _json_value(data["gaps_json"], [])],
            operator_note=data["operator_note"],
        )


def build_case(
    fills: Iterable[ExitFill],
    *,
    policy: Policy,
    residual_shares: Optional[float],
    pre_exit_shares: Optional[float],
    pre_exit_weight_pct: Optional[float],
    broker: str = "",
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    cluster_key: Optional[str] = None,
    residual_as_of: Optional[str] = None,
    gaps: Optional[Sequence[str]] = None,
) -> RecoveryCase:
    """Turn a cluster of confirmed exits into one case. Pure: no IO, so the replay can drive it directly.

    Unknown facts stay unknown (cx-openai-2 F4): a fill without a share count does not become 0, a fill without a
    realized P&L does not become a zero loss, and the residual of a positions snapshot taken BEFORE the exit is not
    reported as today's residual. Every such fact is a gap on the row.
    """
    ordered = sorted(fills, key=lambda f: f.exit_date)
    if not ordered:
        raise ValueError("a recovery case needs at least one confirmed exit")
    symbol, account = ordered[0].symbol, ordered[0].account
    first, last = ordered[0], ordered[-1]
    carried = list(gaps or [])
    # A known P&L is summed; if ANY exit in the cluster lacks one, the total is unknown — summing the known ones
    # would understate the loss and quietly downgrade the tier.
    pnls = [_finite(f.realized_pnl) for f in ordered]
    realized = None if any(p is None for p in pnls) else round(sum(pnls), 2)
    if realized is None:
        carried.append("realized P&L is unknown for at least one exit in this cluster")
    exits = [
        {"date": f.exit_date.isoformat(),
         "shares": (_finite(f.shares) if f.shares is not None else None),
         "price": float(f.price),
         "realized_pnl": _finite(f.realized_pnl), "stop_price": f.stop_price, "source": f.source,
         # Persisted so a later run can recognise THIS exit after its mutable facts change (codex F16).
         "source_id": f.source_id}
        for f in ordered
    ]
    # Pre-exit size is what was held immediately before the FINAL exit of this cluster, not the sum of every exit: a
    # symbol cut down over months sells far more shares than it ever held at once, and summing them would make a real
    # residual look like a fragment of a position that never existed.
    sold = _finite(last.shares)
    residual_known = _finite(residual_shares)
    if pre_exit_shares not in (None, ""):
        pre_exit = float(pre_exit_shares)
        pre_exit_source = "pre_exit_shares supplied by the caller (estimate, not a fill)"
    elif sold is None or residual_known is None:
        pre_exit = None
        pre_exit_source = "pre-exit size unknown (the final exit's share count or the residual could not be read)"
        carried.append("pre-exit size is unknown for this cluster")
    else:
        pre_exit = round(sold + residual_known, 6)
        pre_exit_source = "pre_exit_shares from the fill ledger (final exit + residual)"
    # A positions snapshot older than the exit cannot describe what survived it. Treating it as the residual is the
    # false-zero class in the other direction: a stale 14,000-share row would read as a 53.8% residual today.
    if residual_known is not None and residual_as_of:
        try:
            snapshot_day = date.fromisoformat(str(residual_as_of)[:10])
        except ValueError:
            snapshot_day = None
        if snapshot_day is not None and snapshot_day < last.exit_date:
            carried.append(f"positions snapshot is dated {snapshot_day} — before the {last.exit_date} exit — "
                           "so the residual is unknown")
            residual_known = None
    residual_pct, residual_note = residual_display(pre_exit, residual_known, last.exit_date.isoformat(),
                                                   source=pre_exit_source)
    tier = materiality_tier(realized, pre_exit_weight_pct, policy)
    eligibility = [eligibility_for(account, last.exit_date, policy, today=today)]
    moment = _utc(now)
    cluster = cluster_key or f"{first.exit_date.isoformat()}..{last.exit_date.isoformat()}"
    return RecoveryCase(
        case_key=case_key(symbol, account, cluster), symbol=symbol.upper(), account=account, broker=broker or last.broker,
        cluster_key=cluster, exits=exits, realized_pnl=realized, pre_exit_shares=pre_exit,
        residual_shares=residual_known,
        pre_exit_weight_pct=pre_exit_weight_pct,
        materiality_tier=tier, residual_pct_of_pre_exit=residual_pct, residual_note=residual_note, state="WATCHING",
        state_since=_iso(moment), eligibility=eligibility, opened_at=_iso(moment), updated_at=_iso(moment),
        as_of=_iso(moment), source="broker-fills", pre_exit_source=pre_exit_source,
        residual_as_of=residual_as_of, gaps=carried,
    )


def consume_fills(
    store: CaseStore,
    fills: Sequence[ExitFill],
    *,
    residual_shares: Optional[float],
    pre_exit_weight_pct: Optional[float] = None,
    pre_exit_shares: Optional[float] = None,
    broker: str = "",
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    residual_as_of: Optional[str] = None,
    gaps: Optional[Sequence[str]] = None,
    cluster_key: Optional[str] = None,
) -> RecoveryCase:
    """Open or refresh the case for one symbol × account exit cluster. Idempotent for the same cluster.

    The identity is the cluster's own date range (lead ruling 2026-11-03: ids must bind the exit, so a later, separate
    exit cluster is its own case). A refresh of the SAME cluster — a late-arriving fill, a corrected P&L — keeps the
    row's identity, state, decision, nudge clocks, plan and operator note (cx-openai-2 F7).
    """
    by_cluster: dict[str, list[ExitFill]] = {}
    for fill in fills:
        by_cluster.setdefault(f"{fill.symbol.upper()}::{fill.account}", []).append(fill)
    if len(by_cluster) != 1:
        raise ValueError("consume_fills takes one symbol × account cluster per call")
    case = build_case(list(next(iter(by_cluster.values()))), policy=store.policy, residual_shares=residual_shares,
                      pre_exit_shares=pre_exit_shares, pre_exit_weight_pct=pre_exit_weight_pct, broker=broker,
                      today=today, now=now, residual_as_of=residual_as_of, gaps=gaps, cluster_key=cluster_key)
    existing = store.get(case.case_key)
    if existing is not None:
        case.opened_at = existing.opened_at
        case.state = existing.state
        case.state_since = existing.state_since
        case.operator_decision = existing.operator_decision
        case.operator_note = existing.operator_note       # an operator annotation survives every refresh
        case.plan = existing.plan                          # so does the proposal text
        case.last_nudge_at = existing.last_nudge_at
        case.last_p1_at = existing.last_p1_at
    return store.upsert(case)


# ── Case-level replay: the acceptance gate for piece A ───────────────────────────────────────────────────────
def reclaim_exit_trigger(case: RecoveryCase, close: float, policy: Policy) -> bool:
    """R1: one close at or above the last exit price plus the policy haircut."""
    if not case.exits:
        return False
    exit_price = float(case.exits[-1]["price"])
    threshold = exit_price * (1 + float(policy.triggers["r1_reclaim_exit_pct"]) / 100.0)
    return float(close) >= threshold


def next_trigger_line(case: RecoveryCase, sma20: Optional[float]) -> str:
    if sma20 in (None, ""):
        return "next: reclaims the 20-day mean (value unavailable)"
    return f"next: reclaims {float(sma20):.2f} 20-day mean"


def replay_spcx(store: CaseStore, *, fills: Sequence[ExitFill], closes: Sequence[tuple[date, float]],
                sma20: Optional[float], residual_shares: float, pre_exit_weight_pct: float,
                today: date, now: datetime) -> dict[str, Any]:
    """The spec's replay: five exits, then closes through 11-03. Returns the case and the P1 events it raised.

    Piece A owns the case and the T1 decision; the notification itself is piece C. The event carries the exact words the
    card and the page will render, and a T1 event can never carry a suppression reason.
    """
    case = consume_fills(store, fills, residual_shares=residual_shares, pre_exit_weight_pct=pre_exit_weight_pct,
                         today=today, now=now)
    events: list[dict[str, Any]] = []
    for day, close in closes:
        if case.state != "RECOVERING" and reclaim_exit_trigger(case, close, store.policy):
            store.set_state(case.case_key, "RECOVERING", now=now)
            case.state, case.state_since = "RECOVERING", _iso(now)
            if case.materiality_tier == "T1":
                pct = (close / float(case.exits[-1]["price"]) - 1) * 100
                event = {
                    "priority": "P1",
                    "case_key": case.case_key,
                    "state": "RECOVERING",
                    "as_of": day.isoformat(),
                    "text": (f"Recovery: {case.symbol} +{pct:.1f}% above your "
                             f"{case.exits[-1]['date']} exit — {next_trigger_line(case, sma20)}"),
                    "eligibility": case.eligibility_line(),
                    "suppressed": None,
                }
                store.record_nudge(case.case_key, p1=True, now=now)
                events.append(event)
                break
    return {"case": case.to_dict(), "events": events}

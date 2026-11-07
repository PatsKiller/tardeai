"""WP3 plan persistence for WP6 outcomes (LQ-20261107-369; spec SPEC_MARKET_EVENT_REENTRY_20261107 §4.3/§4.5).

WP3 (``market_event_plan.build``) computes a candidate's plan when it is *read* and never writes
``market_event_candidates.plan``. WP6 outcomes scores forward returns from the tranche stamps in that column
(:func:`lib.market_event_outcomes.ready_stamps`), so until this module existed outcomes could only ever fall back to
the ``first_seen`` basis (opus-2's LQ-366, "Known gap").

This module freezes a candidate's plan snapshot at the moment its state (or the set of tranches it has ready)
changes, and writes it back with one guarded UPDATE per candidate:

    UPDATE market_event_candidates SET plan = %s::jsonb, updated_at = now()
     WHERE episode_id = %s AND symbol = %s AND plan IS DISTINCT FROM %s::jsonb

Idempotency is by construction, twice over. :func:`build_stamp` returns ``None`` when the computed state and ready
tranche set are the same as the stored stamp's — nothing is written at all — and the UPDATE's ``IS DISTINCT FROM``
guard is a second, independent barrier for a caller that writes unconditionally. The document carries no per-run
clock except on a genuine change (``stamp_at`` and a new tranche's ``ready_at``), so two runs over unchanged inputs
produce a byte-identical document.

Privilege shape: the account *label* is the only account identifier that is ever stored. No account number, key or
id is copied in, and ``tests/test_market_event_plan_stamp_lq369_20261107.py`` asserts that on the rendered JSON.

Advisory only. ``MBI_BEHAVIOR = 0``: nothing here sizes, orders, stops, weights or reaches a broker, and nothing
here reads a credential. The plan text is the same advisory document ``/api/v2/market-event/active`` already
renders; this module only lets it survive the request that computed it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

STAMP_SCHEMA = "MarketEventPlanStamp@v1"
ADVISORY_NOTE = ("Frozen advisory snapshot of the WP3 plan at a state change. Tranches are advisory dollars per "
                 "account label; nothing here was ordered, sized against a broker, or sent anywhere.")
TRANCHE_NUMS = (1, 2, 3)


def _iso(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _prev_stamp(previous: Any) -> dict[str, Any]:
    """Only a document this module wrote is memory; anything else (NULL, a foreign jsonb) is ignored, not repaired."""
    return dict(previous) if isinstance(previous, Mapping) and previous.get("schema") == STAMP_SCHEMA else {}


def _ready_numbers(candidate: Mapping[str, Any]) -> list[int]:
    """The tranches the state machine says are ready now (``tranches_ready`` is 1..3, else 0)."""
    n = _int(candidate.get("tranches_ready")) or 0
    return [i for i in TRANCHE_NUMS if i <= n]


def _legs_by_tranche(candidate: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """Group the consumer view's per-account tranche rows into one detail row per tranche number.

    ``candidate["plan"]["tranches"]`` holds one entry per (account, tranche). The dollars stay split by account
    LABEL; pct and the entry zone are the same across accounts by construction and are taken from the first row.
    """
    block = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
    out: dict[int, dict[str, Any]] = {}
    for t in block.get("tranches") or []:
        if not isinstance(t, Mapping):
            continue
        n = _int(t.get("n"))
        if n not in TRANCHE_NUMS:
            continue
        row = out.setdefault(n, {"pct": None, "entry_low": None, "entry_high": None, "usd_by_account": {}})
        if row["pct"] is None:
            row["pct"] = _num(t.get("pct"))
        lo, hi = _num(t.get("entry_low")), _num(t.get("entry_high"))
        if lo is not None and (row["entry_low"] is None or lo < row["entry_low"]):
            row["entry_low"] = lo
        if hi is not None and (row["entry_high"] is None or hi > row["entry_high"]):
            row["entry_high"] = hi
        usd, label = _num(t.get("usd")), str(t.get("account_label") or "Unlabelled account")
        if usd is not None:
            row["usd_by_account"][label] = round(row["usd_by_account"].get(label, 0.0) + usd, 2)
    return out


def build_stamp(candidate: Mapping[str, Any], now: datetime, *, previous: Any = None,
                episode_id: Any = None) -> dict[str, Any] | None:
    """The plan snapshot for one candidate, or ``None`` when there is nothing new to persist.

    ``candidate`` is a ``market_event_api.consumer_view`` candidate (``state``, ``tranches_ready``, ``last_price``
    and the per-account ``plan`` block). ``previous`` is the ``market_event_candidates.plan`` value as it stands in
    the DB *before* this run — capture it before ``build_active`` overwrites the row's plan with the computed view.

    Returns ``None`` when
      * the state and the ready tranche set are unchanged from the stored stamp (the idempotent no-op),
      * the candidate has never been ready and carries no stored stamp (nothing to snapshot yet),
      * the candidate has no symbol (nothing to key the row by).
    """
    sym = str(candidate.get("symbol") or "").upper()
    if not sym:
        return None
    prev = _prev_stamp(previous)
    state = str(candidate.get("state") or "WATCH").upper()
    ready = _ready_numbers(candidate)
    if prev and str(prev.get("state") or "") == state and list(prev.get("ready") or []) == ready:
        return None
    if not ready and not prev.get("tranches"):
        return None

    at = _iso(now)
    same_state = bool(prev) and str(prev.get("state") or "") == state
    details = _legs_by_tranche(candidate)
    block = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
    price = _num(candidate.get("last_price"))
    previous_legs: dict[int, dict[str, Any]] = {}
    for t in prev.get("tranches") or []:
        n = _int(t.get("tranche")) if isinstance(t, Mapping) else None
        if n in TRANCHE_NUMS:
            previous_legs[n] = dict(t)

    tranches: list[dict[str, Any]] = []
    usd_by_account: dict[str, float] = {}
    for n in ready:
        detail, carried = details.get(n) or {}, previous_legs.get(n) or {}
        # Keep a tranche's clock when it was already ready and is still ready. The state label itself does not reset
        # it: READY -> ENTERED is the operator recording an entry, not a new signal, and the tranche became ready at
        # the same moment. Only a leg that a previous stamp marked inactive (the name fell back out of READY) starts
        # a new clock. Rows written before this module existed carry no ``active`` key; they are treated as active.
        keeps_clock = bool(carried) and carried.get("active", True) is not False
        frozen_price = _num(carried.get("price")) if keeps_clock else None
        leg = {
            "tranche": n,
            "active": True,
            "ready_at": (carried.get("ready_at") or at) if keeps_clock else at,
            "price": frozen_price if frozen_price is not None else price,
            "pct": detail.get("pct") if detail.get("pct") is not None else _num(carried.get("pct")),
            "entry_zone": ([detail.get("entry_low"), detail.get("entry_high")] if detail
                           else list(carried.get("entry_zone") or [None, None])),
            "usd_by_account": (dict(detail.get("usd_by_account") or {}) if detail
                               else dict(carried.get("usd_by_account") or {})),
        }
        for label, usd in leg["usd_by_account"].items():
            usd_by_account[label] = round(usd_by_account.get(label, 0.0) + float(usd), 2)
        tranches.append(leg)
    # A tranche that was ready earlier stays in the document with active=false: WP6 scores what happened after a
    # signal, and a later state does not un-happen it. A re-entry replaces its ready_at, because the outcomes table
    # keys one row per (episode, symbol, signal) and the latest signal is the one that can be stored.
    for n, leg in sorted(previous_legs.items()):
        if n not in ready:
            leg["active"] = False
            tranches.append(leg)

    invalidation = _num(block.get("invalidation"))
    if invalidation is None:
        invalidation = _num(prev.get("invalidation"))
    return {
        "schema": STAMP_SCHEMA,
        "advisory_only": True,
        "note": ADVISORY_NOTE,
        "episode_id": episode_id,
        "symbol": sym,
        "state": state,
        "state_since": (prev.get("state_since") or at) if same_state else at,
        "stamp_at": at,
        "ready": ready,
        "tranche": max(ready) if ready else None,
        "price": price,
        "entry_zone": list(tranches[0].get("entry_zone") or [None, None]) if ready and tranches else [None, None],
        "invalidation": invalidation,
        "usd_by_account": usd_by_account,
        "risk_usd": _num(block.get("risk_usd")),
        "risk_budget_usd": _num(block.get("risk_budget_usd")),
        "tranches": tranches,
    }


def build_stamps(doc: Mapping[str, Any], now: datetime, *, previous: Mapping[str, Any] | None = None
                 ) -> list[dict[str, Any]]:
    """``{"episode_id", "symbol", "plan"}`` rows to persist from one ``MarketEvent@v1`` document.

    ``previous`` maps SYMBOL -> the stored ``market_event_candidates.plan`` value, captured before the rows were
    handed to ``build_active`` (which overwrites ``candidate["plan"]`` with the computed view).
    """
    episode = doc.get("episode") if isinstance(doc.get("episode"), Mapping) else {}
    eid = episode.get("episode_id")
    prev = {str(k).upper(): v for k, v in (previous or {}).items()}
    out = []
    for c in doc.get("candidates") or []:
        if not isinstance(c, Mapping):
            continue
        sym = str(c.get("symbol") or "").upper()
        stamp = build_stamp(c, now, previous=prev.get(sym), episode_id=eid)
        if stamp is not None:
            out.append({"episode_id": eid, "symbol": sym, "plan": stamp})
    return out


# --------------------------------------------------------------------------- writers


def write_plan_stamps(conn: Any, stamps: Sequence[Mapping[str, Any]]) -> int:
    """Persist the stamps; returns the number of candidate rows actually changed.

    Guarded by ``plan IS DISTINCT FROM`` so a stamp identical to the stored one writes nothing (rowcount 0) even if
    a caller passes it. Never touches ``state``, ``gates`` or any other column: the state machine's memory is
    ``plan.invalidation``, which this document carries, and ``state`` stays set-on-insert as WP1 intends.
    """
    changed = 0
    cur = conn.cursor()
    for s in stamps:
        doc = json.dumps(s["plan"], sort_keys=True, default=str)
        cur.execute(
            "UPDATE market_event_candidates SET plan = %s::jsonb, updated_at = now() "
            "WHERE episode_id = %s AND symbol = %s AND plan IS DISTINCT FROM %s::jsonb",
            (doc, s["episode_id"], str(s["symbol"]).upper(), doc))
        changed += max(0, int(cur.rowcount or 0))
    return changed


# --------------------------------------------------------------------------- the lane step


def db_query(conn: Any) -> Any:
    """Row-dict reader over a lane connection, in the shape ``lib.market_event_api`` takes (psycopg2 ``%s``)."""
    def query(sql: str, params: Any = None) -> list[dict[str, Any]]:
        cur = conn.cursor()
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return query


def load_mre() -> dict[str, Any]:
    """The Market Risk Engine snapshot the plan's market gate reads, from the same state root as the receipts."""
    from lib import lane_last_receipt as lr  # noqa: PLC0415

    try:
        return json.loads((lr.runtime_dir() / "market_risk_latest.json").read_text())
    except (OSError, ValueError):
        return {}


def default_holdings_path() -> Path:
    """``<state root>/data/portfolios/state/holdings.json``.

    Resolved off the receipt's runtime dir, not off the repo: a worktree has no ``data/`` symlink (the canonical
    checkout's ``data/portfolios/state`` points into persistent-state), so a repo-relative path would read nothing.
    """
    from lib import lane_last_receipt as lr  # noqa: PLC0415

    return lr.runtime_dir().parent.parent / "data" / "portfolios" / "state" / "holdings.json"


def persist_for_connection(*, conn: Any, db_query: Any, snapshot: Mapping[str, Any] | None,
                           holdings_path: Path | str | None = None, policy: Mapping[str, Any] | None = None,
                           now: datetime | None = None, apply: bool = True) -> dict[str, Any]:
    """Build the WP3 plan the /active page shows and persist the stamp of every candidate that changed.

    ``apply=False`` is the dry run: the whole plan is built and every stamp is computed, and nothing is written.
    Commits nothing itself: the caller owns the transaction. Returns a small summary for the lane receipt
    (``{"candidates", "ready", "would_change", "changed", "error"}``). A build that cannot run reports the
    exception type *and* its text in ``error`` rather than writing a partial document or a plausible zero.
    """
    from lib import account_display, market_event_api, wash_sale  # noqa: PLC0415

    at = now or datetime.now(timezone.utc)
    summary: dict[str, Any] = {"candidates": 0, "ready": 0, "would_change": 0, "changed": 0, "error": None}
    try:
        episode, _ = market_event_api.read_open_episode(db_query)
        stored: dict[str, Any] = {}
        if episode:
            rows, _ = market_event_api.read_candidates(db_query, episode.get("episode_id"))
            stored = {str(r.get("symbol") or "").upper(): r.get("plan") for r in rows}
        holds: list[Any] = []
        hpath = Path(holdings_path) if holdings_path else default_holdings_path()
        try:
            holds = (json.loads(hpath.read_text()) or {}).get("holdings") or []
        except (OSError, ValueError):
            holds = []
        doc = market_event_api.build_active(
            db_query=db_query, snapshot=snapshot, holdings_rows=holds, label=account_display.account_label,
            facts=account_display.location_facts, taxable=wash_sale.account_taxable, policy=policy, now=at)
        cands = doc.get("candidates") or []
        summary["candidates"] = len(cands)
        summary["ready"] = sum(1 for c in cands if _ready_numbers(c))
        stamps = build_stamps(doc, at, previous=stored)
        summary["would_change"] = len(stamps)
        if apply:
            summary["changed"] = write_plan_stamps(conn, stamps)
    except Exception as exc:  # noqa: BLE001 - reported by type AND text below; never flattened into a count
        summary["error"] = f"{type(exc).__name__}: {exc}"
    return summary

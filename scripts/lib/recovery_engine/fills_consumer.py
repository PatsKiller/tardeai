"""Read confirmed exits from the live stores and feed them to the case builder (spec §3.1, §3.6).

Stop-out detection moves from ``risk_management.json`` status TRIGGERED to **broker-confirmed exits**. This reader uses
the stores the host already keeps, in this order:

1. ``stopped_out_watch`` — the engine's own stop-out rows: the exit price, the realized P&L and the stop level.
2. ``trade_transactions`` — the imported broker fills: the share count per exit.
3. ``stop_last_known`` — the stop level that fired, when the host did not place the stop (the 10-14 root cause).
4. ``positions_current`` — the residual share count (approved reader batch 5).
5. ``positions_sync_runs`` — the heartbeat, which dates the positions store. It is not gated, and it is how the
   residual's own clock is known without reading a column outside the approved ``qty`` scope.

Read-only. No order, no broker write, no JSON side-file. Every failure is a stated gap: a missing store, a damaged row
and a delayed fill all say so, and none of them becomes a zero (cx-openai-2 F4/F9/F10/F11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from . import cases as rc
from .policy import _finite

def _as_date(value: Any) -> date:
    """SQLite returns TEXT, Postgres returns date/datetime: one coercion, used everywhere. Garbage raises."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _identity(table: str, value: Any) -> Optional[str]:
    """A source row's own id, namespaced by table; None when the source gives nothing usable.

    Missing, blank and malformed keys all mean UNKNOWN IDENTITY — never a shared literal, and never a licence to
    fall back to a mutable attribute (codex F16: an id7 that defaults to "" would make every such row "the same
    event"). The table prefix keeps two providers' local ids apart: they need not denote the same economic exit.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    return f"{table}:{text}"


@dataclass(frozen=True)
class ExitRead:
    fills: list[rc.ExitFill]
    residual_shares: Optional[float]
    pre_exit_weight_pct: Optional[float]
    source: str
    gaps: list[str]
    residual_as_of: Optional[str] = None
    # Explicit case-coverage status, never inferred from the text of a gap (cx-openai-2 F13): True when a source was
    # unavailable or a confirmed exit could not become a case at all (no usable price, damaged row).
    incomplete: bool = False


def _query(conn: Any, sql: str, params: tuple = ()) -> tuple[list[tuple], Optional[str]]:
    """Run one read. Returns (rows, error). A missing table is a stated gap, never a silent empty result."""
    text = sql.replace("%s", "?") if "sqlite" in (type(conn).__module__ or "") else sql
    try:
        cur = conn.cursor()
        cur.execute(text, params)
        return list(cur.fetchall()), None
    except Exception as exc:  # noqa: BLE001 - reported as a gap by the caller
        return [], f"{type(exc).__name__}: {exc}"

#: Every unresolved-identity reason written by this module carries this prefix. The reason travels in the case's own
#: `gaps` column, which is already persisted, so the ambiguity survives the pass that found it and is re-emitted by
#: every later pass until the case is resolved. The prefix is what tells a durable identity ambiguity apart from an
#: ordinary "this read failed" note, which must NOT stick.
IDENTITY_UNRESOLVED_PREFIX = "IDENTITY-UNRESOLVED: "


# Literal statements only (ruff S608): every variant a caller can choose is written out in full here, so no SQL text
# is ever assembled from a runtime variable.
# The row's own id leads every SELECT (codex F16). Matching persisted exits to reads on mutable attributes
# (date F14, arrival F15, price F16) manufactured a second exit whenever an attribute was corrected; the id is
# the one column a correction to price, P&L, shares or an equivalent date form does not change.
_WATCH_SQL = ("SELECT id, stopped_out_at, exit_price, realized_pnl, stop_price, broker FROM stopped_out_watch "
              "WHERE upper(symbol)=upper(%s) AND account=%s ORDER BY stopped_out_at")
_WATCH_SQL_ASOF = ("SELECT id, stopped_out_at, exit_price, realized_pnl, stop_price, broker FROM stopped_out_watch "
                   "WHERE upper(symbol)=upper(%s) AND account=%s AND stopped_out_at < %s ORDER BY stopped_out_at")
# A trade_transactions row has NO provider identity available to this reader. The table's columns (written by both
# ingesters) are trade_date, action, symbol, quantity, price, amount, fees, description, account, import_source,
# dedupe_key, trade_time; `id` is a local row counter. The provider's own uid lives ONLY inside `dedupe_key`, whose
# format embeds the MUTABLE quantity — so the composite is not an identity, and splitting it would be a delimiter
# guess. Nothing here selects it as one: these rows stay explicitly unidentified, which the caller reports.
_TX_SQL = ("SELECT provider_uid, trade_date, quantity, price FROM trade_transactions "
           "WHERE upper(symbol)=upper(%s) AND account=%s AND upper(action) IN "
           "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') ORDER BY trade_date DESC")
_TX_SQL_ASOF = ("SELECT provider_uid, trade_date, quantity, price FROM trade_transactions "
                "WHERE upper(symbol)=upper(%s) AND account=%s AND upper(action) IN "
                "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') AND trade_date < %s ORDER BY trade_date DESC")


def read_confirmed_exits(conn: Any, symbol: str, account: str, *, as_of: Optional[date] = None) -> ExitRead:
    """Collect the exits for one symbol × account, oldest first, with the residual that decides 'held'.

    ``as_of`` is honoured: a caller replaying to a past date does not see a later exit (cx-openai-2 F11).
    """
    gaps: list[str] = []
    fills: list[rc.ExitFill] = []
    # Explicit coverage status (cx-openai-2 F13): a source failure or an excluded confirmed exit means "this pair is
    # not fully covered", never a clean pass inferred from the wording of a gap.
    incomplete = False

    if as_of is None:
        watch_sql, watch_params = _WATCH_SQL, (symbol, account)
    else:
        # Inclusive of the as_of day: an exit dated as_of belongs to that replay.
        watch_sql = _WATCH_SQL_ASOF
        watch_params = (symbol, account, (as_of + timedelta(days=1)).isoformat())
    watch, watch_err = _query(conn, watch_sql, watch_params)
    if watch_err:
        gaps.append(f"stopped_out_watch is unavailable ({watch_err})")
        incomplete = True
    for watch_id, stopped_at, exit_price, realized, stop_price, broker in watch:
        try:
            closed_on = _as_date(stopped_at)
            price = _finite(exit_price)
            if price is None:
                raise ValueError("no exit price")
            stop = _finite(stop_price)
        except (TypeError, ValueError) as exc:
            # One damaged row is excluded and reported; it never aborts the symbol and never becomes a zero fill.
            gaps.append(f"a stopped_out_watch row for {symbol}/{account} is unreadable ({exc}); it is excluded")
            incomplete = True
            continue
        source_id = _identity("stopped_out_watch", watch_id)
        pnl = _finite(realized)
        if pnl is None:
            gaps.append(f"the {closed_on} stopped_out_watch row carries no usable realized P&L; "
                        "that exit's loss is unknown")
        fills.append(rc.ExitFill(symbol=symbol, account=account, exit_date=closed_on,
                                 shares=None, price=price, realized_pnl=pnl, stop_price=stop,
                                 broker=str(broker or ""), source="stopped_out_watch",
                                 source_id=source_id))

    # An id carried by more than one row identifies no single event (codex F16): null it on EVERY occurrence and
    # say so, rather than letting the first row win and the second inherit another exit's facts.
    id_counts: dict[str, int] = {}
    for fill in fills:
        if fill.source_id is not None:
            id_counts[fill.source_id] = id_counts.get(fill.source_id, 0) + 1
    clashing = {sid for sid, n in id_counts.items() if n > 1}
    if clashing:
        for sid in sorted(clashing):
            gaps.append(f"{id_counts[sid]} exits for {symbol}/{account} share the source id {sid}; its identity is "
                        "ambiguous, so none of them is treated as an identified exit")
        fills = [rc.ExitFill(**{**f.__dict__, "source_id": None}) if f.source_id in clashing else f for f in fills]
        incomplete = True

    if as_of is None:
        tx_sql, tx_params = _TX_SQL, (symbol, account)
    else:
        tx_sql, tx_params = _TX_SQL_ASOF, (symbol, account, (as_of + timedelta(days=1)).isoformat())
    tx, tx_err = _query(conn, tx_sql, tx_params)
    if tx_err:
        gaps.append(f"trade_transactions is unavailable ({tx_err}); the exit universe is incomplete")
        incomplete = True
    tx_by_day: dict[date, list[tuple[float, Optional[float], Optional[str]]]] = {}
    #: Rows that carry the broker's own reference become their OWN observations, keyed by that reference. They are not
    #: folded into a day total: two rows with two different references are two economic events even when every visible
    #: detail matches, and a corrected row keeps its reference across price, share and date changes.
    identified: list[rc.ExitFill] = []
    for provider_uid, trade_date, quantity, price in tx:
        try:
            day = _as_date(trade_date)
        except (TypeError, ValueError) as exc:
            gaps.append(f"a trade_transactions row for {symbol}/{account} has an unreadable date ({exc}); "
                        "it is excluded")
            incomplete = True
            continue
        qty = _finite(quantity)
        if qty is None:
            gaps.append(f"a {day} trade_transactions row for {symbol}/{account} has no usable quantity; "
                        "it is excluded")
            incomplete = True
            continue
        # The broker's reference IS the identity. NULL means the provider supplied none — a fact, not a missing value —
        # and such a row stays unidentified: never the composite key (it embeds the mutable quantity), never date,
        # price or arrival order.
        source_id = _identity("trade_transactions", provider_uid)
        tx_by_day.setdefault(day, []).append((qty, _finite(price), source_id))
        if source_id is not None:
            identified.append(rc.ExitFill(symbol=symbol, account=account, exit_date=day, shares=qty,
                                          price=_finite(price), realized_pnl=None,
                                          source="trade_transactions", source_id=source_id))

    # The exit universe is every confirmed exit from BOTH sources (cx-openai-4 R3). A later broker fill used to be
    # dropped merely because it had no stopped_out_watch row, and a fill that disagreed with the watch price was
    # silently overruled. Both are now first-class: the fill becomes its own exit, and a disagreement is a stated gap.
    per_day: dict[date, int] = {}
    for fill in fills:
        per_day[fill.exit_date] = per_day.get(fill.exit_date, 0) + 1
    attributed: list[rc.ExitFill] = []
    for fill in fills:
        quantities = tx_by_day.get(fill.exit_date) or []
        if not quantities:
            gaps.append(f"no trade_transactions row for the {fill.exit_date} exit; its share count is unknown")
            attributed.append(fill)
            continue
        for qty, price, _sid in quantities:
            if price is not None and fill.price and abs(price - fill.price) > max(0.01, 0.005 * abs(fill.price)):
                # Keep the stop-out row's price (it is the recorded exit event) but never hide the disagreement.
                gaps.append(f"conflicting exit prices on {fill.exit_date}: stopped_out_watch {fill.price:g} vs "
                            f"trade_transactions {price:g}; the watch price is stored and the conflict is flagged")
                break
        if per_day[fill.exit_date] > 1:
            # Two exits on one day cannot be told apart from a day-level total, so neither is handed the whole day.
            gaps.append(f"{per_day[fill.exit_date]} exits share {fill.exit_date}; per-exit share counts cannot be "
                        "attributed from a day-level total")
            attributed.append(fill)
        else:
            attributed.append(rc.ExitFill(**{**fill.__dict__, "shares": round(sum(q for q, _, _ in quantities), 6)}))
    fills = attributed
    # Every fill dated beyond the last stop-out row is its own confirmed exit, priced from the fill itself, with the
    # realized P&L unknown. It joins the universe instead of being dropped (cx-openai-4 R3, omitted later fill).
    covered_days = {f.exit_date for f in fills}
    identified_days = {f.exit_date for f in identified}
    for day in sorted(tx_by_day):
        if day in covered_days:
            continue
        # Rows that carry the broker's reference are already their own observations. Only the UNIDENTIFIED rows of the
        # day are aggregated, and only they can be aggregated: without an identity nothing distinguishes them.
        quantities = [(q, p) for q, p, sid in tx_by_day[day] if sid is None]
        if not quantities:
            continue
        total_qty = round(sum(q for q, _ in quantities), 6)
        priced = [(q, p) for q, p in quantities if p is not None]
        if not priced:
            gaps.append(f"the {day} exit has no usable fill price; no case is opened from a sale without a price")
            incomplete = True
            continue
        price = round(sum(q * p for q, p in priced) / sum(q for q, _ in priced), 6)
        # These rows carry no provider reference, so the fill carries none: callers report the ambiguity instead of the
        # reader inventing an identity (codex I1).
        fills.append(rc.ExitFill(symbol=symbol, account=account, exit_date=day, shares=total_qty, price=price,
                                 realized_pnl=None, source="trade_transactions", source_id=None))
        gaps.append(f"the {day} exit comes from trade_transactions with no stopped_out_watch row: its price is the "
                    "fill price and its realized P&L is unknown")

    # Identified observations join the universe as themselves — one member per broker reference.
    fills.extend(identified)

    if fills and all(f.stop_price is None for f in fills):
        stops = _query(conn, "SELECT stop_price, captured_at FROM stop_last_known "
                             "WHERE upper(symbol)=upper(%s) AND account=%s ORDER BY captured_at DESC LIMIT 1",
                       (symbol, account))[0]
        if stops:
            level = _finite(stops[0][0])
            if level is not None:
                fills = [rc.ExitFill(**{**f.__dict__, "stop_price": level}) for f in fills]
            else:
                gaps.append("the last known stop level is not a usable number")
        else:
            gaps.append("no stop level known for these exits (the host may not have placed the stop)")

    residual_rows, residual_err = _query(
        conn, "SELECT qty FROM positions_current WHERE upper(symbol)=upper(%s) AND account_key=%s",
        (symbol, account))
    residual: Optional[float] = None
    if residual_err:
        # The false-zero class: an unreadable store is "unknown", never "no shares left".
        gaps.append(f"positions_current is unreadable ({residual_err}); the residual is unknown")
    else:
        quantities = [_finite(qty) for (qty,) in residual_rows]
        if any(q is None for q in quantities):
            gaps.append("a positions_current row has no usable quantity; the residual is unknown")
        else:
            residual = sum(quantities)

    # The residual must be dated by the store that produced it. positions_current.as_of is outside the approved reader
    # scope (batch 5 reads qty only), so the promotion clock comes from positions_sync_runs, which is the heartbeat and
    # is not gated. Without it, a snapshot older than the exit could pass as today's residual (cx-openai-2 F11).
    residual_as_of: Optional[str] = None
    clock_rows, clock_err = _query(
        conn, "SELECT MAX(finished_at) FROM positions_sync_runs WHERE promoted IS TRUE AND status='complete'")
    if clock_err:
        gaps.append(f"the positions store clock is unavailable ({clock_err}); the residual's age is unknown")
    elif clock_rows and clock_rows[0][0] not in (None, ""):
        residual_as_of = str(clock_rows[0][0])[:10]

    return ExitRead(fills=fills, residual_shares=residual, pre_exit_weight_pct=None,
                    source="broker-fills", gaps=gaps, residual_as_of=residual_as_of, incomplete=incomplete)


# A case in one of these states is finished; a later exit opens a NEW case rather than extending it.
TERMINAL_STATES = ("CLOSED", "RE_ENTERED")


def _as_exit_fill(symbol: str, account: str, row: dict) -> rc.ExitFill:
    # The row's own account wins: a persisted exit carries the account it happened in, and falling back to the
    # caller's would silently relabel a legacy row (FQ-099).
    return rc.ExitFill(symbol=symbol, account=str(row.get("account") or account),
                       exit_date=date.fromisoformat(str(row["date"])[:10]),
                       shares=row.get("shares"), price=float(row["price"]),
                       realized_pnl=row.get("realized_pnl"), stop_price=row.get("stop_price"),
                       source=str(row.get("source") or ""), source_id=row.get("source_id"))


def open_or_extend(store: rc.CaseStore, read: ExitRead, *, today: Optional[date] = None,
                   now: Optional[datetime] = None,
                   coverage: Optional[dict] = None) -> Optional[rc.RecoveryCase]:
    """Persist a read as the right case: refresh, extend, or a genuinely new cluster.

    ``coverage`` is an in/out dict the caller passes so that an ambiguity found HERE — which the reader could not
    see, because it needs the persisted rows — still reaches the pass-level ``complete`` flag. It carries
    ``{"incomplete": bool}``; a pair whose identity cannot be established sets it, and retains both observations
    in the case with the gap that says they are unresolved (codex F16/I5/I12)."""

    def _unresolved(why: str) -> None:
        """Record an identity we could not establish: both observations are kept, and the pass is not complete.

        The reason is written with a stable prefix so it is DURABLE: it is persisted with the case row (the gaps column
        already travels with the row) and re-emitted on every later pass until the case can be resolved. An ambiguity
        that is reported once and forgotten on the next pass is the worst shape — correct once, silently confident
        after (codex narrow BLOCK, 2026-11-04).
        """
        read.gaps.append(IDENTITY_UNRESOLVED_PREFIX + why)
        if coverage is not None:
            coverage["incomplete"] = True

    # The defect this replaces (cx-openai-4 R5): every run handed the reader's whole history to the key, so a new
    # exit re-keyed the cluster and the same historical exit lived in both the old CLOSED case and the new one.
    # Rules now:
    #   * fills already inside an existing case's range refresh THAT case, under its own id;
    #   * fills past the newest case extend it, keeping the id, when it is still open;
    #   * fills past a terminal case open a NEW case containing only the new fills — the old ones are never replayed.
    fills = list(read.fills)
    if not fills:
        return None
    symbol, account = fills[0].symbol, fills[0].account
    existing = sorted((c for c in store.list() if c.symbol == symbol.upper() and c.account == account),
                      key=lambda c: str(c.exits[-1]["date"]) if c.exits else "")
    moments = {"today": today, "now": now}
    common = {"residual_shares": read.residual_shares, "pre_exit_weight_pct": read.pre_exit_weight_pct,
              "residual_as_of": read.residual_as_of, "gaps": read.gaps, **moments}
    if not existing:
        # codex I12 at ce917: a case CREATED from an observation with no source identity used to report complete=True
        # with no identity diagnostic — the P&L and stop gaps were honest, the identity gap was silent. Unknown identity
        # must be stated, never a quiet gap-free sum: the case is still created (the observation is real) but the pass
        # is told it cannot establish which economic events these are.
        unidentified_count = sum(1 for f in fills if f.source_id is None)
        if unidentified_count:
            _unresolved(
                f"{unidentified_count} of {len(fills)} observation(s) behind the new {symbol}/{account} case carry "
                "no source identity; which economic events they are cannot be established from the source")
        return rc.consume_fills(store, fills, **common)
    # Partition by OWNERSHIP, not by "everything up to the newest row's last date" (cx-openai-2 F12). A fill belongs to
    # the existing case whose date range contains it; only fills belonging to no case are new. Without this, a third
    # unchanged pass refreshed the newest case with an OLDER case's fills and the same exit ended up in two rows.
    # MEMBERSHIP IS DECIDED BY IDENTITY, THEN BY DATE (codex class block 2026-11-03). Date used to run first in both
    # places — ownership here and per-day pairing below — so a source correction that moved a DATE (10-27 -> 10-28) on
    # the same id fell outside its member's range and became a second member carrying the same id: -200 became -400
    # with complete=True, gaps=[]. Identity now claims the member before any date is consulted; date ownership only
    # places fills that no established identity already owns.
    stored_by_id: dict[str, rc.RecoveryCase] = {}
    for case in existing:
        for row in case.exits:
            sid = row.get("source_id")
            if sid is not None and sid not in stored_by_id:
                stored_by_id[str(sid)] = case
    ranges: list[tuple[rc.RecoveryCase, date, date]] = []
    for case in existing:
        dates = sorted(date.fromisoformat(str(e["date"])[:10]) for e in case.exits)
        if not dates:
            # codex I12: a stored case with no members is not "nothing to reconcile" — it cannot be confirmed at all,
            # and passing over it silently is how "empty" comes to mean "checked".
            _unresolved(f"the case {case.case_key} is stored with no members; it cannot be confirmed by any read")
            continue
        ranges.append((case, dates[0], dates[-1]))
    assigned: dict[str, list[rc.ExitFill]] = {case.case_key: [] for case, _, _ in ranges}
    unassigned: list[rc.ExitFill] = []
    for fill in fills:
        owner = stored_by_id.get(str(fill.source_id)) if fill.source_id is not None else None
        if owner is None:
            owner = next((case for case, low, high in ranges if low <= fill.exit_date <= high), None)
        if owner is None:
            unassigned.append(fill)
        else:
            assigned[owner.case_key].append(fill)
    result: Optional[rc.RecoveryCase] = None
    for case, _low, _high in ranges:
        got = assigned[case.case_key]
        # STAY UNRESOLVED UNTIL RESOLVED. A durable identity ambiguity recorded on this row is re-stated on every pass,
        # whether or not this particular read would rediscover it. Without this the ambiguity was recomputed from each
        # read, so a third pass that happened to pair the observations reported complete=True with gaps=[] — correct
        # once, silently confident after (codex narrow BLOCK, 2026-11-04).
        for prior_gap in [g for g in (case.gaps or []) if str(g).startswith(IDENTITY_UNRESOLVED_PREFIX)]:
            if prior_gap not in read.gaps:
                read.gaps.append(prior_gap)
            if coverage is not None:
                coverage["incomplete"] = True
        if not got:
            # codex I12 at ce917: this early return bypassed reconciliation coverage entirely, so a case the read did
            # not cover passed as "nothing to do". A source that stops reporting an observation is NOT evidence the
            # exit was deleted (contract I6/I11): the member is unconfirmed, and the pass must say so.
            _unresolved(
                f"the case {case.case_key} exists but this read produced no observation for it; its "
                f"{len(case.exits)} stored member(s) are unconfirmed in this pass, and no disappearance is claimed")
            continue
        # A DATE IS NOT A FILL IDENTITY (codex F14), and a date is not a membership rule either (class block
        # 2026-11-03). Pair across the WHOLE case by identity first, so a correction that moves the date on the same id
        # updates that member instead of forming a second one. Date+price is only the fallback for rows persisted
        # before the field — there is no date-specific special case here, date is simply last.
        stored = list(case.exits)
        reads = list(got)
        used: set[int] = set()
        pairs: list[tuple[dict, Optional[rc.ExitFill]]] = []
        for row in stored:
            sid = row.get("source_id")
            hit = None
            if sid is not None:
                hit = next((j for j, f in enumerate(reads) if j not in used and f.source_id is not None
                            and str(f.source_id) == str(sid)), None)
            if hit is not None:
                used.add(hit)
            pairs.append((row, reads[hit] if hit is not None else None))
        # Legacy rows (persisted before the field): exact price on the SAME DATE, and the link names itself provisional.
        for idx, (row, fill) in enumerate(pairs):
            if fill is not None or row.get("source_id") is not None:
                continue
            day = str(row["date"])[:10]
            hit = next((j for j, f in enumerate(reads)
                        if j not in used and f.source_id is None and f.exit_date.isoformat() == day
                        and abs(float(f.price) - float(row["price"])) < 1e-9), None)
            if hit is not None:
                used.add(hit)
                pairs[idx] = (row, reads[hit])
                _unresolved(
                    f"the {day} exit was persisted before source identity existed and was paired to a read by exact "
                    "price alone; the link is provisional, not established")
        merged: list[rc.ExitFill] = []
        # A read fill paired to nobody is a DISTINCT exit this case has not persisted — a late arrival, not an
        # ambiguity to be dropped (codex F15). It is appended, so the case never reads a fill and discards it.
        extras = [f for j, f in enumerate(reads) if j not in used]
        for extra in extras:
            if extra.source_id is None:
                # With no id on the read there is nothing to prove this is a NEW exit rather than a corrected
                # one, so it is appended on date evidence alone and the reason is stated (codex F16/I12).
                _unresolved(
                    f"a {extra.exit_date} read fill for {symbol}/{account} carries no source identity; the "
                    "stored exit and this read are BOTH retained, and whether they are one corrected exit or two "
                    "events is unresolved")
        # CROSS-SOURCE AMBIGUITY (codex I7 class block). A `trade_transactions` member and a `stopped_out_watch` member
        # can describe the SAME economic exit, and NOTHING in the data declares a crosswalk: the watch writer records
        # symbol/account/stopped_out_at/exit_price/stop_price/broker, the transaction writer records
        # trade_date/action/symbol/quantity/price/dedupe_key — they share no key in either direction. So when a case
        # would end up holding observations from two sources for the same exit date, that is an UNRESOLVED identity,
        # not two confident members: both are retained and the pass is incomplete. We do not invent a mapping, and we
        # do not merge them into one number.
        def _source_of(value: Any) -> str:
            # The row's own `source` field ("stopped_out_watch" / "trade_transactions"), not its id: trade_transactions
            # rows carry no provider identity at all (see _TX_SQL), so an id-based name would be empty exactly where
            # the cross-source question matters most.
            if isinstance(value, dict):
                name = value.get("source")
            else:
                name = getattr(value, "source", None)
            if name:
                return str(name)
            sid = value.get("source_id") if isinstance(value, dict) else getattr(value, "source_id", None)
            return str(sid).split(":", 1)[0] if sid else ""

        unpaired = [row for row, fill in pairs if fill is None]
        for extra in extras:
            extra_src = _source_of(extra)
            if not extra_src:
                continue
            clash = next((row for row in unpaired if _source_of(row) and _source_of(row) != extra_src
                          and str(row["date"])[:10] == extra.exit_date.isoformat()), None)
            if clash is not None:
                _unresolved(
                    f"the {extra.exit_date} exit for {symbol}/{account} is observed by {extra_src} and by "
                    f"{_source_of(clash)}, and no declared crosswalk links the two sources; both observations are "
                    "retained and whether they are ONE economic exit or two is unresolved")
            # LEGACY -> IDENTIFIED (codex I12). A member persisted BEFORE identity existed has no source_id, so an
            # identified read of the same exit cannot be matched to it by identity — and there is no evidence to migrate
            # it with. Neither date nor price proves the link (that heuristic is what F14-F17 kept re-creating), so the
            # pair stays unresolved: both observations retained, pass incomplete, no migration invented.
            # PROVIDER-KEY (codex I1). trade_transactions.dedupe_key is date|action|symbol|QUANTITY|account|uid, so a
            # quantity correction necessarily changes the key, and the provider uid inside it is not exposed as a field
            # (there is no uid column). Splitting the composite would be a delimiter guess, which is how F17 is born, so
            # it is not done: two observations from that source with different keys on one date are retained and the
            # pair is reported unresolved — a corrected quantity and a second sale are indistinguishable here.
            if extra_src == "trade_transactions":
                same_source = next((row for row in unpaired if _source_of(row) == extra_src
                                    and str(row["date"])[:10] == extra.exit_date.isoformat()), None)
                if same_source is not None:
                    _unresolved(
                        f"the {extra.exit_date} exit for {symbol}/{account} carries two {extra_src} observations with "
                        "different composite keys; that key includes the quantity, so a corrected quantity and a second "
                        "sale cannot be told apart without a provider uid — both are retained and the pair is unresolved")
            if extra.source_id is not None:
                # A stored member with no source_id is unidentified whatever its `source` name says, so the identity
                # test here is the id itself, not the source label.
                legacy = next((row for row in unpaired if not (row.get("source_id") or "")
                               and str(row["date"])[:10] == extra.exit_date.isoformat()), None)
                if legacy is not None:
                    _unresolved(
                        f"a {extra.exit_date} member for {symbol}/{account} was persisted before source identity "
                        f"existed and an IDENTIFIED read ({extra.source_id}) now describes that same exit date; no "
                        "evidence links them, so both observations are retained and whether they are ONE economic "
                        "exit or two is unresolved")
        merged.extend(fill if fill is not None else _as_exit_fill(symbol, account, row) for row, fill in pairs)
        merged.extend(extras)
        refreshed = rc.consume_fills(store, merged, cluster_key=case.cluster_key, **common)
        result = refreshed
    if unassigned:
        # CENTRAL MEMBER COVERAGE (codex F1 at eac2895b2). The durable prefix can only retain an ambiguity that was
        # discovered on the pass that found it; an observation arriving through THIS path — which extends an open case
        # or opens a new one — never passed through the in-case pairing, so an unidentified one was stored silently and
        # the pass reported complete=true. Batching must not change completeness: exactly the same source delivered
        # all at once reported incomplete, while arriving piecemeal it did not.
        unidentified = [f for f in unassigned if f.source_id is None]
        if unidentified:
            _unresolved(
                f"{len(unidentified)} of {len(unassigned)} observation(s) extending or opening the {symbol}/{account} "
                "case carry no source identity; which economic events they are cannot be established from the source")
        newest, _low, newest_last = ranges[-1]
        if unassigned[0].exit_date > newest_last and newest.state not in TERMINAL_STATES:
            # Extend the open case without re-keying: its stored exits plus the new ones, its cluster_key unchanged.
            merged = [_as_exit_fill(symbol, account, row) for row in newest.exits] + unassigned
            result = rc.consume_fills(store, merged, cluster_key=newest.cluster_key, **common)
        else:
            # A FORK IS NEVER SILENT (cc-deepseek-2 identity BLOCK, 2026-11-04).
            #
            # A fill that predates every stored case opens a second case from that fill alone. Measured with identical
            # data and only the arrival order differing: 10-30 observed before the first pass and 10-14 arriving after
            # it produced TWO cases for ONE stop episode — two residuals, two eligibility answers, two chances at a T1
            # page — and both reported ``complete: True`` with ``gaps: []``.
            #
            # The engine cannot prove whether such a fill is an earlier arrival of the SAME episode or a genuinely
            # separate earlier one, and a date-proximity heuristic is exactly the class this module refuses to invent.
            # So the case is still created — the observation is real and dropping it would be worse — and the fork is
            # stated durably: the pass reports incomplete, and the gap names both halves.
            predating = [f for f in unassigned if ranges and f.exit_date < ranges[0][1]]
            if predating:
                earliest = ranges[0][0]
                _unresolved(
                    f"{len(predating)} exit(s) for {symbol}/{account} predate every stored case (earliest is "
                    f"{earliest.case_key}); a second case is opened from them, and whether the two are ONE stop "
                    "episode observed out of order or two separate episodes is unresolved")
            result = rc.consume_fills(store, unassigned, **common)
    return result


def consume_symbol(store: rc.CaseStore, conn: Any, symbol: str, account: str, *,
                   today: Optional[date] = None, now: Optional[datetime] = None,
                   as_of: Optional[date] = None,
                   coverage: Optional[dict] = None) -> Optional[rc.RecoveryCase]:
    """Read one symbol × account and open/refresh its case. Returns None when there is no confirmed exit.

    ``coverage`` is the same in/out dict ``open_or_extend`` takes, so a single-symbol caller can learn that an
    identity was unresolved instead of inferring it from gap text."""
    read = read_confirmed_exits(conn, symbol, account, as_of=as_of)
    return open_or_extend(store, read, today=today, now=now, coverage=coverage)


_SYMBOLS_WATCH_SQL = ("SELECT DISTINCT symbol, account FROM stopped_out_watch "
                      "WHERE stopped_out_at IS NOT NULL AND is_active IS NOT FALSE")
_SYMBOLS_WATCH_SQL_SINCE = ("SELECT DISTINCT symbol, account FROM stopped_out_watch "
                            "WHERE stopped_out_at IS NOT NULL AND is_active IS NOT FALSE AND stopped_out_at >= %s")
_SYMBOLS_TX_SQL = ("SELECT DISTINCT symbol, account FROM trade_transactions WHERE upper(action) IN "
                   "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE')")
_SYMBOLS_TX_SQL_SINCE = ("SELECT DISTINCT symbol, account FROM trade_transactions WHERE upper(action) IN "
                         "('SELL','SOLD','STOP','STOPPED','SELL_TO_CLOSE') AND trade_date >= %s")


def symbols_with_confirmed_exits(conn: Any, *, since: Optional[date] = None
                                ) -> tuple[list[tuple[str, str]], list[str], bool]:
    """The work list — and the failures that would otherwise look like an empty one.

    A failed enumeration used to return no pairs and no error, so the pass reported "nothing to do" while every
    possible case was being dropped (cx-openai-2 F9). ``since`` is now honoured. The third value is the structured
    enumeration status: False when a source failed, so completeness never depends on the wording of a gap.
    """
    gaps: list[str] = []
    if since is None:
        rows, watch_err = _query(conn, _SYMBOLS_WATCH_SQL)
        tx, tx_err = _query(conn, _SYMBOLS_TX_SQL)
    else:
        rows, watch_err = _query(conn, _SYMBOLS_WATCH_SQL_SINCE, (since.isoformat(),))
        tx, tx_err = _query(conn, _SYMBOLS_TX_SQL_SINCE, (since.isoformat(),))
    enumerated_ok = True
    if watch_err:
        gaps.append(f"stopped_out_watch is unavailable ({watch_err}); the work list is incomplete")
        enumerated_ok = False
    seen = {(str(s).upper(), str(a)) for s, a in rows if s and a}
    if tx_err:
        gaps.append(f"trade_transactions is unavailable ({tx_err}); the work list is incomplete")
        enumerated_ok = False
    seen |= {(str(s).upper(), str(a)) for s, a in tx if s and a}
    return sorted(seen), gaps, enumerated_ok


def run(store: rc.CaseStore, conn: Any, *, today: Optional[date] = None,
        now: Optional[datetime] = None, as_of: Optional[date] = None) -> dict[str, Any]:
    """One consumer pass over every symbol × account with a confirmed exit. Idempotent.

    A pass reports ``complete: false`` whenever any source failed or any single case could not be built; one damaged
    case never prevents the others, and a partial pass never reports itself as a clean one (cx-openai-2 F9/F10).
    """
    moments = {
        "today": today or (now or datetime.now(timezone.utc)).date(),
        "now": now or datetime.now(timezone.utc),
    }
    pairs, gaps, enumerated_ok = symbols_with_confirmed_exits(conn)
    opened, refreshed, failed = [], [], []
    covered = True
    for symbol, account in pairs:
        try:
            read = read_confirmed_exits(conn, symbol, account, as_of=as_of)
            gaps.extend(f"{symbol}/{account}: {gap}" for gap in read.gaps)
            if read.incomplete:
                covered = False
            if not read.fills:
                if read.incomplete:
                    # Confirmed exits existed but none could become a case: say so as a failure, not a clean skip.
                    failed.append(f"{symbol}/{account}: confirmed exits present, no case could be built")
                continue
            before = {c.case_key for c in store.list()}
            # Identity ambiguity is only discoverable against the PERSISTED rows, so coverage is collected from
            # open_or_extend rather than decided before it (codex F16). Both observations stay in the case; the pass
            # is not allowed to call itself complete around them.
            coverage = {"incomplete": read.incomplete}
            case = open_or_extend(store, read, coverage=coverage, **moments)
            gaps.extend(f"{symbol}/{account}: {gap}" for gap in read.gaps if gap not in gaps)
            if coverage["incomplete"]:
                covered = False
            if case is None:
                continue
            (refreshed if case.case_key in before else opened).append(case.case_key)
        except Exception as exc:  # noqa: BLE001 - one case's failure is isolated and reported, never hidden
            failed.append(f"{symbol}/{account}: {type(exc).__name__}: {exc}")
            gaps.append(f"{symbol}/{account}: the case could not be built ({type(exc).__name__}: {exc})")
    return {"opened": opened, "refreshed": refreshed, "failed": failed, "gaps": gaps,
            "complete": bool(enumerated_ok and covered and not failed),
            "cases": [c.to_dict() for c in store.list()]}

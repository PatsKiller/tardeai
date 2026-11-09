"""Lane ``market-event-lifecycle`` — the full-lifecycle monitor for rotation / re-entry positions.

LQ-20261107-1656 (design, cc-opus-1: ``DESIGN-LQ-20261107-1656-cc-opus-1.md``) and LQ-20261107-1674 (build).

WP3's state machine (``market_event_plan.evaluate_candidate``) runs WATCH -> STABILIZING -> READY -> ENTERED and
then goes silent: ``ENTERED`` is carried and no code writes it, so once a name is bought nothing advises about the
position that exists. :func:`market_event_plan.evaluate_position` is the pure answer for one row; this module is the
lane step around it — it gathers the position truth, the market snapshot and the calendar, evaluates every held row,
and persists the transitions.

READ-ONLY on every source it does not own. ``positions_current``, ``stop_lifecycle``, ``holding_exit_metrics``,
``market_quotes``, ``market_ohlcv_bars`` and ``market_event_candidates`` are written by other lanes; this module
reads them and writes exactly two things:

* one row per stage transition into ``market_event_lifecycle`` (append-only; unique per
  ``(episode, symbol, account label, to_stage)`` so a revisited stage cannot alert twice), and
* the current stage map in ``market_event_candidates.plan->'lifecycle'``, guarded by ``IS DISTINCT FROM``.

Idempotent: a second run over unchanged inputs inserts 0 rows and updates 0 candidate rows.

Privilege shape: an account LABEL is the only account identifier that leaves this module; the account key is used to
join the stores and is never stored on a row. Nothing here reads a credential.

Advisory only. ``MBI_BEHAVIOR = 0`` (AGENTS.md §0 rule 1): nothing sizes, orders, stops, weights or writes to a
broker; every number is the advisory proposal the brief already renders.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

try:  # imported as ``lib.market_event_lifecycle`` from a lane (scripts/ on sys.path)
    from lib import market_event_plan as mep
except ImportError:  # imported as ``scripts.lib.market_event_lifecycle`` (repo root on sys.path, tests)
    from . import market_event_plan as mep  # type: ignore[no-redef]

try:  # the look-through basis is the board's sleeve basis when it is importable
    from fund_lookthrough import effective_sector_exposure as _lookthrough
except ImportError:  # pragma: no cover - scripts/ off sys.path (tests): the direct basis is used and labelled
    _lookthrough = None

LANE = "market-event-lifecycle"
SCHEMA_ROW = "MarketEventLifecycleRow@v1"
SCHEMA_STATE = "MarketEventLifecycleState@v1"
ET = "America/New_York"

#: macro_calendar ``event`` ids -> the policy's ``lifecycle.event_kinds`` vocabulary. Only these four gate a tranche.
EVENT_KIND_ALIASES = {
    "cpi": "CPI",
    "pce": "PCE",
    "fomc": "FOMC",
    "employment_situation": "NFP",
    "nonfarm_payrolls": "NFP",
    "payrolls": "NFP",
    "nfp": "NFP",
}

#: stop_lifecycle.lifecycle values that mean the stop is still resting at the broker (stop_lifecycle_monitor.py:8).
WORKING_STOP_STATES = ("working", "near_trigger")


def _iso(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _f(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- policy and calendar


def load_policy(path: Path | str | None = None) -> dict[str, Any]:
    """The merged ``plan`` block of ``config/market_event_policy.json`` — defaults under the file's block.

    Delegates to :func:`market_event_plan.load_policy` so the lane and the state machine read one policy shape: the
    block that carries ``lifecycle``, merged over ``DEFAULT_POLICY``. Returning the raw document here would leave
    every ``lc.get(...)`` on a code default and silently ignore the operator's file.
    """
    return mep.load_policy(Path(path) if path else None)


def plan_block(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    """The policy as a plan block, whether the caller handed us the document (``{"plan": ...}``) or the block."""
    pol = dict(policy or {})
    inner = pol.get("plan")
    return dict(inner) if isinstance(inner, Mapping) else pol


def load_events(*, now: datetime, kinds: Sequence[str] | None = None, path: Path | str | None = None,
                horizon_days: int = 10) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Calendar events in the policy vocabulary, as ``{"kind", "at", "released_at"}`` (UTC ISO).

    The source is the same ``MacroCalendar@v1`` the CIO brief reads (``scripts/lib/macro_calendar.py``), so this
    module never invents a release time. A kind outside ``lifecycle.event_kinds`` is dropped: only CPI/FOMC/NFP/PCE
    gate a tranche. ``released_at`` is set only once the release time has passed — a gate that has not released is
    withheld, never passed.

    Returns ``(events, error)``. An unreadable calendar returns ``([], "<type>: <text>")``: the caller reports it,
    and every t2 gate then withholds with ``event_gate: no calendar event in scope`` (fail closed, never a pass).
    """
    try:
        from lib import macro_calendar as mcal
    except ImportError:  # pragma: no cover - scripts/ off sys.path
        from . import macro_calendar as mcal  # type: ignore[no-redef]
    wanted = {str(k).upper() for k in (kinds or ("CPI", "FOMC", "NFP", "PCE"))}
    try:
        body = mcal.load(path)
    except (OSError, ValueError, KeyError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    out: list[dict[str, Any]] = []
    for day, entry in (body.get("dates") or {}).items():
        if not isinstance(entry, Mapping):
            continue
        for ev in entry.get("events") or []:
            if not isinstance(ev, Mapping):
                continue
            kind = EVENT_KIND_ALIASES.get(str(ev.get("event") or "").strip().lower())
            if kind is None or kind not in wanted:
                continue
            at = _release_instant(str(day), str(ev.get("time_et") or "08:30"), mcal.et_date(day))
            if at is None:
                continue
            if at > now + timedelta(days=horizon_days):
                continue
            out.append({"kind": kind, "at": _iso(at), "released_at": _iso(at) if now >= at else None})
    out.sort(key=lambda e: e["at"])
    return out, None


def _release_instant(day: str, time_et: str, et_day: date) -> Optional[datetime]:
    """The UTC instant of an ET release, or None when the row's date/time cannot be read."""
    try:
        from zoneinfo import ZoneInfo

        hh, mm = (int(x) for x in time_et.split(":", 1))
        local = datetime(et_day.year, et_day.month, et_day.day, hh, mm, tzinfo=ZoneInfo(ET))
        return local.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- store readers


def read_positions(db_query: Callable[..., list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Held, non-cash positions with their basis. Written by the broker-read lanes; this lane never calls a broker."""
    return db_query(
        "SELECT account_key, symbol, qty, avg_cost, broker_market_value, as_of "
        "FROM positions_current WHERE COALESCE(is_cash, false) = false AND qty > 0") or []


def read_positions_asof(db_query: Callable[..., list[dict[str, Any]]]) -> Optional[str]:
    """The positions snapshot's own clock: ``max(as_of)`` over every row, held or not.

    A position that the snapshot no longer lists has no ``as_of`` of its own, so the row that notices it went to
    zero is judged fresh against the snapshot that omits it — never against the lane's wall clock, which would call
    an unread snapshot fresh.
    """
    rows = db_query("SELECT max(as_of) AS asof FROM positions_current") or []
    v = rows[0].get("asof") if rows else None
    return _iso(v) if v is not None else None


def read_stops(db_query: Callable[..., list[dict[str, Any]]]) -> dict[tuple[str, str], dict[str, Any]]:
    """``{(account, SYMBOL): row}`` — the newest stop_lifecycle snapshot per account and symbol."""
    rows = db_query("SELECT account, symbol, lifecycle, stop_price, order_type, snapshot_at "
                    "FROM stop_lifecycle ORDER BY snapshot_at DESC NULLS LAST") or []
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (str(r.get("account") or ""), str(r.get("symbol") or "").upper())
        out.setdefault(key, r)
    return out


def read_guardian(db_query: Callable[..., list[dict[str, Any]]]) -> tuple[dict[tuple[str, str], dict[str, Any]],
                                                                         Optional[str]]:
    """The newest ``holding_exit_metrics`` run: ``{(account, SYMBOL): row}`` and its ``run_at``.

    Read, not copied: ``holdings_gain_guardian.py`` owns the classifier and its vocabulary (``GIVEBACK_BREACH`` /
    ``GIVEBACK_WATCH``). A run older than the policy's ``guardian_max_age_minutes`` makes the giveback leg
    unmeasured — an old giveback state is not evidence about today.
    """
    try:
        rows = db_query(
            "SELECT symbol, account, giveback_state, rsi14, run_at FROM holding_exit_metrics "
            "WHERE run_at = (SELECT max(run_at) FROM holding_exit_metrics)") or []
    except Exception as exc:  # noqa: BLE001 - an unreadable store is reported, never a silent empty
        return {}, f"{type(exc).__name__}: {exc}"
    out: dict[tuple[str, str], dict[str, Any]] = {}
    run_at = None
    for r in rows:
        key = (str(r.get("account") or ""), str(r.get("symbol") or "").upper())
        out.setdefault(key, r)
        run_at = run_at or (str(r.get("run_at")) if r.get("run_at") is not None else None)
    return out, run_at


def read_quote_asof(db_query: Callable[..., list[dict[str, Any]]],
                    symbols: Sequence[str]) -> dict[str, str]:
    """``{SYMBOL: newest quote fetched_at}`` — the market snapshot's own clock, not the bar's session date."""
    if not symbols:
        return {}
    rows = db_query("SELECT symbol, max(fetched_at) AS asof FROM market_quotes "
                    "WHERE symbol = ANY(%s) AND source = ANY(%s) AND price > 0 GROUP BY symbol",
                    (list(symbols), ["finviz", "alpaca"])) or []
    return {str(r["symbol"]).upper(): _iso(r["asof"]) for r in rows if r.get("asof") is not None}


def read_sectors(db_query: Callable[..., list[dict[str, Any]]],
                 symbols: Sequence[str]) -> dict[str, str]:
    """Finviz sector per symbol, newest snapshot (the source WP3's universe group map uses)."""
    try:
        from lib import market_event_api
    except ImportError:  # pragma: no cover
        from . import market_event_api  # type: ignore[no-redef]
    return market_event_api.read_sectors(db_query, symbols)


# --------------------------------------------------------------------------- pure calculations


def rs_loss_sessions(name_bars: Sequence[Mapping[str, Any]], proxy_bars: Sequence[Mapping[str, Any]],
                     *, pct: float, lookback: int = 5, max_sessions: int = 10) -> Optional[int]:
    """Consecutive sessions ending at the latest close on which 5-session RS vs the proxy was <= ``-pct``.

    ``rs`` for a session is the name's ``lookback``-session return minus the proxy's, in percent. Counting stops at
    the first recent session that does not qualify, so the number is "how long the name has been lagging", not "how
    many sessions ever". Returns None when either series is too short to measure one session — a missing input is
    unmeasured, never zero.
    """
    closes_n = {str(b.get("date")): _f(b.get("close")) for b in name_bars or [] if isinstance(b, Mapping)}
    closes_p = {str(b.get("date")): _f(b.get("close")) for b in proxy_bars or [] if isinstance(b, Mapping)}
    days = [d for d in closes_n if d in closes_p]
    days.sort()
    if len(days) < lookback + 1:
        return None
    n = 0
    for i in range(len(days) - 1, lookback - 1, -1):
        dn, dp = days[i], days[i - lookback]
        a1, a0 = closes_n.get(dn), closes_n.get(dp)
        b1, b0 = closes_p.get(dn), closes_p.get(dp)
        if not all(x is not None and x > 0 for x in (a1, a0, b1, b0)):
            return None if n == 0 else n
        rs = ((a1 / a0 - 1.0) - (b1 / b0 - 1.0)) * 100.0
        if rs <= -abs(pct):
            n += 1
            if n >= max_sessions:
                break
        else:
            break
    return n


def proxy_group_map(proxy_groups: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """``{group_key: {label, proxy, kind}}`` from ``config/market_reference_symbols.json` proxy_groups."""
    if proxy_groups is None:
        try:
            doc = json.loads((repo_root() / "config" / "market_reference_symbols.json").read_text())
            proxy_groups = doc.get("proxy_groups") or {}
        except (OSError, ValueError):
            proxy_groups = {}
    groups = proxy_groups.get("groups") if isinstance(proxy_groups, Mapping) else None
    return {str(k): dict(v) for k, v in (groups or {}).items() if isinstance(v, Mapping)}


def proxy_for_candidate(candidate: Mapping[str, Any], groups: Mapping[str, Mapping[str, Any]],
                        benchmark: str = "SPY") -> str:
    """The RS proxy for a candidate: its MRE group's proxy, else its sector label's proxy, else the benchmark."""
    key = str(candidate.get("sector") or "").strip().lower()
    if key in groups and groups[key].get("proxy"):
        return str(groups[key]["proxy"]).upper()
    if key:
        for g in groups.values():
            if str(g.get("label") or "").strip().lower() == key and g.get("proxy"):
                return str(g["proxy"]).upper()
    return benchmark


def sleeve_pct_by_sector(positions: Sequence[Mapping[str, Any]],
                         sector_by_symbol: Mapping[str, str]) -> tuple[dict[str, float], str]:
    """``{sector: pct of the equity book}`` and the basis actually used (``lookthrough`` or ``direct``).

    The look-through basis (``scripts/fund_lookthrough.py``, direct + configured fund weights) is the board's sleeve
    basis and is used whenever it is importable; otherwise the direct basis is used and labelled so a caller can see
    which one a trim was decided on. Fund weights live in ``config/fund_lookthrough.json``; that file's absence is
    the direct basis, not an error.
    """
    try:
        from .cio_sector_opportunity import canonical_sector
    except ImportError:  # pragma: no cover
        try:
            from lib.cio_sector_opportunity import canonical_sector  # type: ignore[no-redef]
        except ImportError:
            canonical_sector = lambda s: s  # noqa: E731 - last resort; a label that does not canonicalise stays as-is
    rows = []
    for p in positions or []:
        val = _f(p.get("broker_market_value"))
        if val is None or val <= 0:
            continue
        sym = str(p.get("symbol") or "").upper()
        rows.append({"symbol": sym, "sector": sector_by_symbol.get(sym), "value": val})
    if not rows:
        return {}, "direct"
    if _lookthrough is not None:
        try:
            exp = _lookthrough(rows) or {}
            out = {canonical_sector(str(s)): _f(v.get("pct")) for s, v in exp.items()
                   if not str(s).startswith("_") and isinstance(v, Mapping) and _f(v.get("pct")) is not None}
            return {k: float(v) for k, v in out.items() if v is not None}, "lookthrough"
        except Exception:  # noqa: BLE001 - fall through to the direct basis and label it; never a wrong number
            pass
    total = sum(r["value"] for r in rows)
    agg: dict[str, float] = {}
    for r in rows:
        agg[canonical_sector(str(r["sector"] or "Other"))] = agg.get(canonical_sector(str(r["sector"] or "Other")), 0.0) + r["value"]
    return {k: round(v / total * 100.0, 2) for k, v in agg.items()} if total else {}, "direct"


def build_snapshot(*, symbol: str, bars: Sequence[Mapping[str, Any]], quote_asof: Optional[str],
                   mre: Mapping[str, Any] | None, guardian_row: Mapping[str, Any] | None,
                   guardian_run_at: Optional[str], guardian_max_age_minutes: float, now: datetime,
                   sleeve: Mapping[str, Any] | None, rs_loss: Optional[int],
                   rs_proxy: Optional[str], policy: Mapping[str, Any]) -> dict[str, Any]:
    """The per-symbol market snapshot :func:`evaluate_position` takes.

    ``tier`` is the MRE tier; ``last_close``/``low``/``sma20``/``rsi14`` are the name gate's own numbers off the same
    bars WP3 uses; ``rs5_loss_sessions`` is measured against the sector proxy; ``gain_guardian_state`` is read from
    the guardian's newest run and dropped when that run is older than its limit (an old giveback state is not
    evidence today). ``as_of`` is the market-data clock (newest quote), never the bar's session date, so a snapshot
    built at 15:00 from yesterday's bars is stale rather than fresh.
    """
    ng = mep.name_gate(bars, policy) if hasattr(mep, "name_gate") else {}
    mre = mre if isinstance(mre, Mapping) else {}
    snap: dict[str, Any] = {
        "as_of": quote_asof,
        "tier": str(mre.get("tier") or mre.get("market_tier") or "").upper() or None,
        "mre_as_of": mre.get("as_of"),
        "last_close": _f(ng.get("last_close")),
        "low": _f(ng.get("window_low")),
        "sma20": _f(ng.get("sma20")),
        "rsi14": _f(ng.get("rsi")),
        "rs5_loss_sessions": rs_loss,
        "rs_proxy": rs_proxy,
        "gain_guardian_state": None,
        "guardian_age_minutes": None,
        "sleeve": dict(sleeve or {}),
    }
    g_state = str((guardian_row or {}).get("giveback_state") or "").upper()
    g_age = _minutes_since(guardian_run_at, now)
    snap["guardian_age_minutes"] = g_age
    if g_state and g_age is not None and g_age <= float(guardian_max_age_minutes):
        snap["gain_guardian_state"] = g_state
    elif g_state:
        snap["gain_guardian_state_ignored"] = f"{g_state} from a run {g_age:g} min old" if g_age is not None \
            else f"{g_state} with no run time"
    return snap


def _minutes_since(v: Any, now: datetime) -> Optional[float]:
    dt = mep._parse_at(v)  # noqa: SLF001 - the module's own ISO parser; one implementation, not a copy
    return None if dt is None else (now - dt).total_seconds() / 60.0


# --------------------------------------------------------------------------- row building


def plan_for_holding(candidate: Mapping[str, Any], holding_qty: Optional[float]) -> dict[str, Any]:
    """The plan block :func:`evaluate_position` reads, from the stored candidate plan and the name gate.

    ``tranche_qty`` is preferred (per-tranche share counts from WP3's per-account sizing). With no share counts the
    stored percentages are used with ``planned_shares`` = the account's current size, which makes the stage a
    "how much of the plan is already held" reading rather than a share count.
    """
    stored = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
    pcts = stored.get("tranche_pcts") or stored.get("tranche_percents") or [30, 30, 40]
    out: dict[str, Any] = {
        "invalidation": _f(stored.get("invalidation")),
        "entry_price": _f(stored.get("entry_price")) or _f(candidate.get("last_price")),
        "tranche_pcts": list(pcts),
    }
    qty = [t.get("shares") for t in (stored.get("tranches") or []) if isinstance(t, Mapping)]
    if qty and all(_f(q) is not None and _f(q) > 0 for q in qty):
        out["tranche_qty"] = [int(_f(q)) for q in qty]  # type: ignore[arg-type]
    elif holding_qty is not None:
        out["planned_shares"] = float(holding_qty)
    return out


def build_rows(inputs: Mapping[str, Any], policy: Mapping[str, Any], now: datetime,
               *, guardian_max_age_minutes: float | None = None) -> list[dict[str, Any]]:
    """One row per (candidate, account LABEL) that is held now or was held when the last run recorded it.

    A label that the current positions snapshot no longer holds is still evaluated — with qty 0 and the stop state
    read from ``stop_lifecycle`` — because a position that went to zero is exactly the STOPPED_OUT this lane exists
    to notice. The snapshot's own clock (newest positions ``as_of``) is used for that row, so a disappeared position
    is judged fresh only as long as the snapshot is.
    """
    lc = policy.get("lifecycle") if isinstance(policy.get("lifecycle"), Mapping) else {}
    gmax = float(guardian_max_age_minutes if guardian_max_age_minutes is not None else lc.get("guardian_max_age_minutes", 240))
    episode = inputs.get("episode") or {}
    eid = episode.get("episode_id") or inputs.get("episode_id")
    positions: Sequence[Mapping[str, Any]] = inputs.get("positions") or []
    stops: Mapping[tuple[str, str], Mapping[str, Any]] = inputs.get("stops") or {}
    guardian: Mapping[tuple[str, str], Mapping[str, Any]] = inputs.get("guardian") or {}
    mre = inputs.get("mre") or {}
    bars: Mapping[str, Sequence[Mapping[str, Any]]] = inputs.get("bars") or {}
    quote_asof: Mapping[str, str] = inputs.get("quote_asof") or {}
    sleeve_by_sector: Mapping[str, float] = inputs.get("sleeve_pct") or {}
    targets: Mapping[str, Any] = inputs.get("sector_targets") or {}
    band = inputs.get("trim_band") or {}
    events = inputs.get("events") or []
    groups = inputs.get("proxy_groups") or {}
    benchmark = str((inputs.get("benchmark") or "SPY")).upper()

    pos_max_asof = mep._parse_at(inputs.get("positions_as_of"))  # noqa: SLF001 - the snapshot's own clock
    for p in positions:
        a = p.get("as_of")
        dt = mep._parse_at(a)  # noqa: SLF001
        if dt is not None and (pos_max_asof is None or dt > pos_max_asof):
            pos_max_asof = dt

    rows: list[dict[str, Any]] = []
    for c in inputs.get("candidates") or []:
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        state = str(c.get("state") or "").upper()
        held_now = [p for p in positions if str(p.get("symbol") or "").upper() == sym]
        stored_lc = (c.get("plan") or {}).get("lifecycle") if isinstance(c.get("plan"), Mapping) else None
        stored_lc = stored_lc if isinstance(stored_lc, Mapping) else {}
        # Operator decision 2026-11-09 14:50 ET: a held position in this episode's candidate list IS an entered
        # position — "if I bought 81 shares now it should show the 81 shares are there". ENTERED_OBSERVED is derived
        # from positions_current and labelled with its source, so it is never confused with an operator-recorded
        # ENTERED. Without this the engine's WATCH rows never become position rows and the lifecycle never starts.
        observed = bool(held_now) and state not in ("ENTERED",) and state not in mep.POSITION_STAGES
        was_observed = bool(stored_lc.get("positions"))
        if state not in ("ENTERED",) and state not in mep.POSITION_STAGES and not observed and not was_observed:
            continue
        entry_tier = stored_lc.get("entry_tier") or str(mre.get("tier") or "").upper() or None
        cand = {
            "episode_id": c.get("episode_id") or eid,
            "symbol": sym,
            "sector": c.get("sector"),
            "state": "ENTERED_OBSERVED" if (observed or was_observed) else state,
            "entry_source": "positions_snapshot" if (observed or was_observed) else "engine_state",
            "observed_state": state if (observed or was_observed) else None,
            "entry_tier": entry_tier,
            "last_price": c.get("last_price"),
            "fell_for_reason": c.get("fell_for_reason"),
            "reason_evidence": c.get("reason_evidence"),
            "plan": plan_for_holding(c, None),
        }
        held_labels = {_label(p.get("account_key")): p for p in held_now}
        prev_map = stored_lc.get("positions") if isinstance(stored_lc.get("positions"), Mapping) else {}
        labels = list(held_labels) + [k for k in prev_map if k not in held_labels]
        if not labels:
            continue  # never held in this episode: not a position row (no_held_candidate covers the whole run)
        sector = _canonical(c.get("sector"))
        sleeve = {"pct": sleeve_by_sector.get(sector), "target": targets.get(sector),
                  "band_low_frac": band.get("low_frac"), "band_high_frac": band.get("high_frac")}
        proxy = proxy_for_candidate(c, groups, benchmark)
        rs = rs_loss_sessions(bars.get(sym) or [], bars.get(proxy) or [],
                              pct=float(lc.get("rs_loss_pct", 5.0)), lookback=5,
                              max_sessions=max(10, int(lc.get("rs_loss_sessions", 3)) + 2))
        # The giveback state is per (account, symbol), so it is attached per row below, not here.
        snap = build_snapshot(
            symbol=sym, bars=bars.get(sym) or [], quote_asof=quote_asof.get(sym), mre=mre,
            guardian_row=None, guardian_run_at=None, guardian_max_age_minutes=gmax, now=now,
            sleeve=sleeve, rs_loss=rs, rs_proxy=proxy, policy=policy)
        for label in labels:
            pos = held_labels.get(label)
            prev_stage = str(((prev_map.get(label) or {}) if isinstance(prev_map.get(label), Mapping) else {})
                             .get("stage") or "")
            qty = _f(pos.get("qty")) if pos else 0.0
            acct_key = _account_of(pos) if pos else None
            stop = stops.get((acct_key or "", sym)) if acct_key else None
            stop_state = str((stop or {}).get("lifecycle") or "").upper() if stop else ""
            g_row = guardian.get((acct_key or "", sym)) if acct_key else None
            # a snapshot with the giveback state of THIS account's row, when there is one
            row_snap = dict(snap)
            if g_row is not None:
                g_state = str(g_row.get("giveback_state") or "").upper()
                g_age = _minutes_since(g_row.get("run_at") or inputs.get("guardian_run_at"), now)
                if g_state and g_age is not None and g_age <= gmax:
                    row_snap["gain_guardian_state"] = g_state
                elif g_state:
                    row_snap["gain_guardian_state_ignored"] = (
                        f"{g_state} from a run {g_age:g} min old" if g_age is not None
                        else f"{g_state} with no run time")
            holding = {
                "account_label": label,
                "qty": qty,
                "avg_cost": _f(pos.get("avg_cost")) if pos else None,
                "price": row_snap.get("last_close"),
                "stop_price": _f((stop or {}).get("stop_price")),
                "stop_state": stop_state,
                "had_working_stop": _had_working_stop(pos, stop),
                "as_of": _iso(_position_asof(pos, pos_max_asof, now)) if pos or pos_max_asof else None,
                # the account key stays inside this module: it joins the stores and is never rendered on a row
                "_account_key": acct_key,
            }
            rows.append({
                "schema": SCHEMA_ROW,
                "episode_id": cand["episode_id"],
                "symbol": sym,
                "account_label": label,
                "previous_stage": prev_stage or state,
                "previous_recorded": bool(prev_stage),
                "candidate": cand,
                "holding": holding,
                "snapshot": row_snap,
                "events": events,
                "stored_lifecycle": stored_lc,
            })
    return rows


def evaluate_rows(rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any],
                  now: datetime) -> list[dict[str, Any]]:
    """Run :func:`market_event_plan.evaluate_position` on every row, carrying the row's identity through."""
    out = []
    for r in rows:
        cand = dict(r["candidate"])
        cand["stage"] = r.get("previous_stage")
        res = mep.evaluate_position(cand, r["holding"], r.get("events") or [], r["snapshot"], policy, now=now)
        res["episode_id"] = r.get("episode_id")
        res["account_label"] = r["account_label"]
        res["entry_tier"] = cand.get("entry_tier")
        res["entry_source"] = cand.get("entry_source")
        res["schema"] = SCHEMA_ROW
        res["first_observation"] = not r.get("previous_recorded")
        # carried into the state map so the next run can tell a qty or stop CHANGE from an unchanged book
        res["qty"] = (r.get("holding") or {}).get("qty")
        res["stop_state"] = (r.get("holding") or {}).get("stop_state")
        res["tier"] = (r.get("snapshot") or {}).get("tier")
        out.append(res)
    return out


# --------------------------------------------------------------------------- triggers


def calendar_anchor_triggers(events: Sequence[Mapping[str, Any]], *, now: datetime, settle_min: float = 15.0,
                             late_slack_min: float = 10.0, window_min: float = 60.0) -> list[dict[str, Any]]:
    """The calendar anchors that are due at ``now``: released, settled, and inside the catch-up window.

    An anchor is the release instant plus the policy's ``settle_min`` — the same instant the t2 gate opens at, so the
    trigger and the gate can never disagree about when "the event has landed". A run more than ``late_slack_min``
    after its anchor is labelled ``calendar:<kind>:late`` (design SELF-HEALING: the next tick runs the anchored
    evaluation late and says so), and an anchor older than ``window_min`` has been missed outright and is not claimed
    by a routine tick — a lane that was down for an hour does not get to relabel the gap as on time.
    """
    out: list[dict[str, Any]] = []
    for e in events or []:
        if not isinstance(e, Mapping):
            continue
        rel = mep._parse_at(e.get("released_at"))  # noqa: SLF001 - the module's own ISO parser
        if rel is None:
            continue  # not released yet: a scheduled anchor is not a due one
        anchor = rel + timedelta(minutes=float(settle_min))
        if now < anchor:
            continue
        late_min = (now - anchor).total_seconds() / 60.0
        if late_min > float(window_min):
            continue
        kind = str(e.get("kind") or "").upper()
        if not kind:
            continue
        out.append({
            "kind": kind,
            "anchor_at": _iso(anchor),
            "late_minutes": round(late_min, 1),
            "trigger": f"calendar:{kind}" + (":late" if late_min > float(late_slack_min) else ""),
        })
    out.sort(key=lambda a: a["anchor_at"])
    return out


def state_triggers(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """``tier:`` / ``qty:`` / ``stop:`` triggers — what changed since the last run recorded it.

    The comparison base is the lifecycle state the previous run persisted (``last_tier``, and each label's ``qty``
    and ``stop``). A first run has no base, so it reports a ``tick``: an absence of history is not a change.
    """
    out: list[str] = []
    for r in rows or []:
        stored = r.get("stored_lifecycle") if isinstance(r.get("stored_lifecycle"), Mapping) else {}
        sym = str(r.get("symbol") or "").upper()
        prev_tier = str(stored.get("last_tier") or "").upper()
        cur_tier = str((r.get("snapshot") or {}).get("tier") or "").upper()
        if prev_tier and cur_tier and prev_tier != cur_tier:
            out.append(f"tier:{prev_tier}->{cur_tier}")
        prev_pos = (stored.get("positions") or {})
        prev_pos = prev_pos.get(r.get("account_label")) if isinstance(prev_pos, Mapping) else None
        prev_pos = prev_pos if isinstance(prev_pos, Mapping) else {}
        holding = r.get("holding") or {}
        pq, cq = _f(prev_pos.get("qty")), _f(holding.get("qty"))
        if pq is not None and cq is not None and pq != cq:
            out.append(f"qty:{sym}")
        ps = str(prev_pos.get("stop") or "").upper()
        cs = str(holding.get("stop_state") or "").upper()
        if "stop" in prev_pos and ps != cs:
            out.append(f"stop:{sym}")
    return out


def derive_trigger(*, rows: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], now: datetime,
                   policy: Mapping[str, Any]) -> dict[str, Any]:
    """The trigger label for this run, from what actually fired (design PROCESS 4).

    Every due calendar anchor and every observed state change is reported in ``triggers`` (deduplicated, calendar
    first); ``trigger`` is the first of them, or ``tick`` when nothing fired. Never a guess: each entry names the
    thing observed, so a receipt's ``trigger`` can be checked against the anchors and the stored state.
    """
    lc = policy.get("lifecycle") if isinstance(policy.get("lifecycle"), Mapping) else {}
    anchors = calendar_anchor_triggers(
        events, now=now, settle_min=float(lc.get("settle_min", 15)),
        late_slack_min=float(lc.get("anchor_late_slack_minutes", 10)),
        window_min=float(lc.get("anchor_window_minutes", 60)))
    ordered: list[str] = []
    for t in [a["trigger"] for a in anchors] + state_triggers(rows):
        if t not in ordered:
            ordered.append(t)
    return {
        "trigger": ordered[0] if ordered else "tick",
        "triggers": ordered or ["tick"],
        "calendar": anchors,
        "anchor_max_late_minutes": max((a["late_minutes"] for a in anchors), default=0.0),
    }


def _position_asof(pos: Mapping[str, Any] | None, max_asof: Optional[datetime],
                   now: datetime) -> datetime:
    """The row's own ``as_of`` when it has one, else the snapshot's newest, else ``now`` (which then fails fresh)."""
    dt = mep._parse_at((pos or {}).get("as_of"))  # noqa: SLF001
    return dt or max_asof or now


def _had_working_stop(pos: Mapping[str, Any] | None, stop: Mapping[str, Any] | None) -> bool:
    """A position that went to zero after a resting stop: the stop row is filled, orphaned, or gone entirely."""
    if pos is not None:
        return False
    lifecycle = str((stop or {}).get("lifecycle") or "").lower()
    return (not stop) or lifecycle in ("filled", "orphaned")


def _label(account_key: Any) -> str:
    try:
        from lib import account_display
    except ImportError:  # pragma: no cover
        from . import account_display  # type: ignore[no-redef]
    return account_display.account_label(account_key)


def _account_of(pos: Mapping[str, Any] | None) -> Optional[str]:
    return str(pos.get("account_key") or "") if pos else None


def _canonical(sector: Any) -> str:
    try:
        from lib.cio_sector_opportunity import canonical_sector
    except ImportError:  # pragma: no cover
        from .cio_sector_opportunity import canonical_sector  # type: ignore[no-redef]
    return canonical_sector(str(sector or ""))


# --------------------------------------------------------------------------- alerts


#: the one suggested action per Fi-text stage; the design's step 6 names exactly these four
FI_ACTIONS = {
    "ADD_T2_READY": "review the second tranche; advisory only",
    "ADD_T3_READY": "review the third tranche; advisory only",
    "EXIT_READY": "review the exit; advisory only",
    "STOPPED_OUT": "recovery_state owns re-entry; advisory only",
}


def _alert_trigger(res: Mapping[str, Any]) -> str:
    """The number/reason that fired it, for the text's ``trigger`` slot (the formatter shortens it)."""
    reasons = [str(x) for x in (res.get("reasons") or []) if str(x).strip()]
    head = f"{res.get('stage')}" + (f": {reasons[0]}" if reasons else "")
    return head[:160]


def alert_events(results: Sequence[Mapping[str, Any]], *, now: datetime) -> tuple[list[dict[str, Any]],
                                                                                 list[dict[str, Any]]]:
    """``(texts, digest)`` for the transitions this run produced.

    A transition is one row result carrying an ``alert`` (``market_event_plan._with_alert`` attaches it once per
    ``(episode, symbol, label, to_stage)``). The four Fi-text stages become a ``market_event`` critical text through
    the same primitive the brief uses; every transition, Fi-text or not, becomes a digest entry. An unchanged stage
    carries no ``alert`` at all, so it produces neither.
    """
    texts: list[dict[str, Any]] = []
    digest: list[dict[str, Any]] = []
    for r in results or []:
        a = r.get("alert")
        if not isinstance(a, Mapping) or not a.get("event_id"):
            continue
        item = {
            "event_id": a.get("event_id"),
            "episode_id": r.get("episode_id"),
            "symbol": r.get("symbol"),
            "account_label": a.get("account_label"),
            "from_stage": a.get("from_stage"),
            "to_stage": a.get("stage"),
            "class": a.get("class"),
        }
        digest.append(item)
        if str(a.get("class")) != "fi_text":
            continue
        texts.append({
            "alert_class": "market_event",
            "event_id": a["event_id"],
            "symbol": r.get("symbol"),
            "trigger": _alert_trigger(r),
            "action": FI_ACTIONS.get(str(a.get("stage")), "review the position; advisory only"),
            "_transition": item,
        })
    return texts, digest


def _default_text(event: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from lib.critical_texts import send_critical_text
    except ImportError:  # pragma: no cover - scripts/ off sys.path
        from .critical_texts import send_critical_text  # type: ignore[no-redef]
    return send_critical_text(dict(event))


def deliver_alerts(results: Sequence[Mapping[str, Any]], *, now: datetime, send: bool = False,
                   text_sender: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                   ) -> dict[str, Any]:
    """Plan (``send=False``) or deliver (``send=True``) one text per Fi-text transition.

    The cap, the allowlist and the event-id dedupe are ``critical_texts``' own — this lane passes the event and
    records what came back. ``send=False`` is the dry run: the planned texts are printed and nothing leaves.
    """
    texts, digest = alert_events(results, now=now)
    out: dict[str, Any] = {"planned": [{k: v for k, v in t.items() if k != "_transition"} for t in texts],
                           "sent": [], "refused": [], "digest": digest}
    if not send:
        return out
    sender = text_sender or _default_text
    for t in texts:
        ev = {k: v for k, v in t.items() if k != "_transition"}
        try:
            res = dict(sender(ev) or {})
        except Exception as exc:  # noqa: BLE001 - one failed text must not lose the run's transitions
            res = {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}
        rec = {**t["_transition"], "sent": bool(res.get("sent")),
               "reason": res.get("reason") or res.get("detail")}
        (out["sent"] if rec["sent"] else out["refused"]).append(rec)
    return out


def record_alerts(conn: Any, delivered: Mapping[str, Any], now: datetime) -> int:
    """Stamp ``alert_event_id``/``alerted_at`` on the row each text was sent for. Returns the rows stamped."""
    cur = conn.cursor()
    stamped = 0
    for rec in delivered.get("sent") or []:
        cur.execute(
            "UPDATE market_event_lifecycle SET alert_event_id = %s, alerted_at = %s "
            "WHERE episode_id = %s AND symbol = %s AND account_label = %s AND to_stage = %s "
            "AND alert_event_id IS NULL",
            (rec.get("event_id"), now, rec.get("episode_id"), rec.get("symbol"),
             rec.get("account_label"), rec.get("to_stage")))
        stamped += max(0, int(cur.rowcount or 0))
    return stamped


def reconcile_unalerted(conn: Any, db_query: Callable[..., list[dict[str, Any]]] | None, *, now: datetime,
                        send: bool = False, text_sender: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                        limit: int = 20, lookback_hours: int = 24) -> dict[str, Any]:
    """Re-send Fi-text transitions that were persisted without a recorded alert — **at most once each**.

    The design's self-heal: a run that wrote the row and then failed to deliver leaves a row with no event id. This
    step finds those rows (``alert_attempts = 0``, inside the lookback), builds the event back from the row itself,
    and sends it once. An attempt is recorded whatever the outcome, so a text that is refused for its own reason
    (the hourly cap, the allowlist) is not retried forever: it becomes a fix item, not a loop.
    """
    out: dict[str, Any] = {"candidates": 0, "sent": 0, "refused": 0, "rows": []}
    if db_query is None:
        return {**out, "skipped": "no reader"}
    try:
        rows = db_query(
            "SELECT id, episode_id, symbol, account_label, from_stage, to_stage, trigger, at "
            "FROM market_event_lifecycle WHERE alert_event_id IS NULL AND alert_attempts = 0 "
            "AND to_stage = ANY(%s) AND created_at > now() - make_interval(hours => %s) "
            "ORDER BY id LIMIT %s",
            (list(mep.FI_TEXT_STAGES), int(lookback_hours), int(limit))) or []
    except Exception as exc:  # noqa: BLE001 - a reconcile that cannot read is reported, never a silent zero
        return {**out, "error": f"{type(exc).__name__}: {exc}"}
    out["candidates"] = len(rows)
    if not send or not rows:
        return out
    sender = text_sender or _default_text
    cur = conn.cursor()
    for r in rows:
        stage = str(r.get("to_stage") or "")
        ev = {
            "alert_class": "market_event",
            "event_id": f"{r.get('episode_id')}:{r.get('symbol')}:{r.get('account_label')}:{stage}",
            "symbol": r.get("symbol"),
            "trigger": f"{stage} at {r.get('at')} ({r.get('trigger')})"[:160],
            "action": FI_ACTIONS.get(stage, "review the position; advisory only"),
        }
        try:
            res = dict(sender(ev) or {})
        except Exception as exc:  # noqa: BLE001
            res = {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}
        sent = bool(res.get("sent"))
        cur.execute(
            "UPDATE market_event_lifecycle SET alert_attempts = alert_attempts + 1, "
            "alert_event_id = COALESCE(alert_event_id, %s), alerted_at = CASE WHEN %s THEN %s ELSE alerted_at END "
            "WHERE id = %s AND alert_attempts = 0",
            (ev["event_id"] if sent else None, sent, now, r.get("id")))
        out["sent" if sent else "refused"] += 1
        out["rows"].append({"id": r.get("id"), "event_id": ev["event_id"], "sent": sent,
                            "reason": None if sent else res.get("reason")})
    return out


def heal_actions(*, errors: Mapping[str, Any], transitions: int, alerted: int, late_minutes: float,
                 policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What this run would have fixed, and what it may not fix (design SELF-HEALING).

    Bounded and reported, never dispatched: this lane may not dispatch another lane (the broker-read sync is
    reported, never called), and it may not write positions, stops, plans other than its own lifecycle rows, or POST
    a route. A stale input becomes one named owner per source and re-checks on the next tick; an anchored run that
    was late is labelled; a transition persisted without its alert is the reconcile step's job.
    """
    owners = {"positions": "broker-read-sync", "mre": "market-risk-engine", "bars": "market-data-bars",
              "quotes": "quote-refresh", "calendar": "macro-calendar"}
    out: list[dict[str, Any]] = []
    for src, why in (errors or {}).items():
        owner = owners.get(str(src))
        if not owner:
            continue
        out.append({"kind": "stale_input", "source": str(src), "owner": owner,
                    "action": "redispatch_owner", "dispatched": False, "reason": str(why),
                    "next": "re-check on the next tick"})
    if late_minutes > float(policy.get("anchor_late_slack_minutes", 10)):
        out.append({"kind": "late_anchor", "action": "rerun_anchored_evaluation", "dispatched": False,
                    "reason": f"the anchor was {late_minutes:g} min old at this run",
                    "next": "the next tick evaluates it again and labels it calendar:<KIND>:late"})
    if transitions and alerted < transitions:
        out.append({"kind": "persist_without_alert", "action": "reconcile_unalerted", "dispatched": False,
                    "reason": f"{transitions - alerted} of {transitions} transition(s) have no recorded alert"})
    return out


# --------------------------------------------------------------------------- persistence


def persist_results(conn: Any, results: Sequence[Mapping[str, Any]], *, trigger: str, now: datetime,
                    previous: Mapping[tuple[str, str], Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Write the stage transitions and the current stage map. Returns ``{"transitions", "plans", "rows"}``.

    Two writes, both idempotent:

    * one append-only ``market_event_lifecycle`` row per transition, ``ON CONFLICT DO NOTHING`` against the
      ``(episode, symbol, account label, to_stage)`` unique index — so a replayed run and a revisited stage both
      write nothing;
    * one guarded UPDATE per candidate that sets ``plan->'lifecycle'`` (the current stage per LABEL, plus the entry
      tier). ``IS DISTINCT FROM`` means an unchanged map writes no row.

    A row whose verdict is UNVERIFIABLE is never persisted: no stage advances on a stale input (design CONTRACT), and
    an unverifiable run must not overwrite the last good stage with the row it could not read.
    """
    cur = conn.cursor()
    inserted = 0
    plans: dict[tuple[str, str], dict[str, Any]] = {}
    for key, stored in (previous or {}).items():
        st = dict(stored) if isinstance(stored, Mapping) else {}
        st["positions"] = dict(st.get("positions") or {})
        plans[(str(key[0]), str(key[1]).upper())] = st
    for r in results:
        eid = str(r.get("episode_id") or "")
        sym = str(r.get("symbol") or "").upper()
        label = str(r.get("account_label") or "unlabelled")
        key = (eid, sym)
        st = plans.setdefault(key, {"schema": SCHEMA_STATE, "positions": {}})
        st.setdefault("schema", SCHEMA_STATE)
        st["positions"] = dict(st.get("positions") or {})
        if not st.get("entry_tier") and r.get("entry_tier"):
            st["entry_tier"] = r["entry_tier"]
        st["episode_id"] = eid
        st["symbol"] = sym
        if r.get("verdict") == "UNVERIFIABLE":
            continue
        if str(r.get("stage")) != str(r.get("previous_stage")):
            cur.execute(
                "INSERT INTO market_event_lifecycle "
                "(episode_id, symbol, account_label, from_stage, to_stage, trigger, gates, evidence, at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
                "ON CONFLICT (episode_id, symbol, account_label, to_stage) DO NOTHING",
                (eid, sym, label, str(r.get("previous_stage")), str(r.get("stage")), trigger,
                 json.dumps(r.get("gates") or {}, sort_keys=True, default=str),
                 json.dumps({"verdict": r.get("verdict"), "reasons": list(r.get("reasons") or [])[:12],
                             "alert": r.get("alert"), "entry_source": r.get("entry_source")},
                            sort_keys=True, default=str),
                 now))
            inserted += max(0, int(cur.rowcount or 0))
        prior = (st["positions"].get(label) or {}) if isinstance(st["positions"].get(label), Mapping) else {}
        st["positions"][label] = {"stage": r.get("stage"), "at": _iso(now), "trigger": trigger,
                                  "verdict": r.get("verdict"), "qty": r.get("qty"),
                                  "stop": r.get("stop_state") or None}
        if prior.get("stage") == st["positions"][label]["stage"]:
            st["positions"][label]["at"] = prior.get("at") or _iso(now)
        # the comparison base for the next run's tier trigger; only a row that could be read may set it, so an
        # unverifiable run cannot move the base and mask the transition it could not measure
        if str(r.get("tier") or "").upper():
            st["last_tier"] = str(r["tier"]).upper()
    changed = 0
    for (eid, sym), st in plans.items():
        if not eid or not sym:
            continue
        doc = json.dumps(st, sort_keys=True, default=str)
        cur.execute(
            "UPDATE market_event_candidates "
            "SET plan = jsonb_set(COALESCE(plan, '{}'::jsonb), '{lifecycle}', %s::jsonb, true), updated_at = now() "
            "WHERE episode_id = %s AND symbol = %s "
            "AND COALESCE(plan->'lifecycle', '{}'::jsonb) IS DISTINCT FROM %s::jsonb",
            (doc, eid, sym, doc))
        changed += max(0, int(cur.rowcount or 0))
    return {"transitions": inserted, "plans": changed, "rows": len(results)}


# --------------------------------------------------------------------------- the lane step


def collect_inputs(db_query: Callable[..., list[dict[str, Any]]], now: datetime, *,
                   policy: Mapping[str, Any], calendar_path: Path | str | None = None,
                   mre: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every read the run needs, with a named error per unreadable source instead of a plausible empty.

    Nothing here writes: the whole dry run is this function plus :func:`run_lane`'s evaluation.
    """
    from lib import market_event_api as api  # noqa: PLC0415

    errors: dict[str, str] = {}
    episode, ep_err = api.read_open_episode(db_query)
    if ep_err:
        errors["episode"] = ep_err
    candidates: list[dict[str, Any]] = []
    if episode:
        candidates, c_err = api.read_candidates(db_query, episode.get("episode_id"))
        if c_err:
            errors["candidates"] = c_err
    try:
        positions = read_positions(db_query)
        positions_as_of = read_positions_asof(db_query)
    except Exception as exc:  # noqa: BLE001 - an unreadable positions table is a reported failure, not an empty book
        positions, positions_as_of = [], None
        errors["positions"] = f"{type(exc).__name__}: {exc}"
    symbols = sorted({str(p.get("symbol") or "").upper() for p in positions} |
                     {str(c.get("symbol") or "").upper() for c in candidates})
    symbols = [s for s in symbols if s]
    try:
        stops = read_stops(db_query)
    except Exception as exc:  # noqa: BLE001
        stops, errors["stops"] = {}, f"{type(exc).__name__}: {exc}"
    guardian, guardian_run_at = read_guardian(db_query)
    try:
        sectors = read_sectors(db_query, symbols)
    except Exception as exc:  # noqa: BLE001
        sectors, errors["sectors"] = {}, f"{type(exc).__name__}: {exc}"
    groups = proxy_group_map()
    proxies = sorted({proxy_for_candidate(c, groups) for c in candidates})
    try:
        bars = api.read_bars(db_query, sorted(set(symbols) | set(proxies)), now.date())
    except Exception as exc:  # noqa: BLE001
        bars, errors["bars"] = {}, f"{type(exc).__name__}: {exc}"
    try:
        quote_asof = read_quote_asof(db_query, symbols)
    except Exception as exc:  # noqa: BLE001
        quote_asof, errors["quotes"] = {}, f"{type(exc).__name__}: {exc}"
    sleeve_pct, sleeve_basis = sleeve_pct_by_sector(positions, sectors)
    targets: dict[str, float] = {}
    band: dict[str, Any] = {}
    try:
        from lib.cio_sector_opportunity import load_sector_target_map  # noqa: PLC0415
        targets = dict(load_sector_target_map().get("targets") or {})
        rot = json.loads((repo_root() / "config" / "rotation_sector_targets.json").read_text())
        band = dict(rot.get("trim_band") or {})
    except Exception as exc:  # noqa: BLE001
        errors["sector_targets"] = f"{type(exc).__name__}: {exc}"
    if mre is None:
        try:
            from lib import market_event_plan_stamp as stamp  # noqa: PLC0415
            mre = stamp.load_mre()
        except Exception as exc:  # noqa: BLE001
            mre, errors["mre"] = {}, f"{type(exc).__name__}: {exc}"
    events, cal_err = load_events(now=now, path=calendar_path)
    if cal_err:
        errors["calendar"] = cal_err
    return {
        "episode": episode, "candidates": candidates, "positions": positions,
        "positions_as_of": positions_as_of, "stops": stops,
        "guardian": guardian, "guardian_run_at": guardian_run_at, "sectors": sectors, "bars": bars,
        "quote_asof": quote_asof, "sleeve_pct": sleeve_pct, "sleeve_basis": sleeve_basis,
        "sector_targets": targets, "trim_band": band, "mre": mre, "events": events,
        "proxy_groups": groups, "errors": errors,
    }


def run_lane(*, conn: Any, db_query: Callable[..., list[dict[str, Any]]], now: datetime, apply: bool,
             trigger: str | None = "tick", policy: Mapping[str, Any] | None = None,
             calendar_path: Path | str | None = None, mre: Mapping[str, Any] | None = None,
             inputs: Mapping[str, Any] | None = None,
             text_sender: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The whole step: collect, evaluate every held row, and (``apply``) persist the transitions.

    ``apply=False`` is the dry run: the same reads and the same evaluation, nothing written. The summary carries the
    four receipt fields the contract names — ``rows_evaluated``, ``transitions``, ``not_measured`` and ``trigger`` —
    plus one compact entry per row so a dry run can be quoted. Never raises: an error is reported by type and text.

    ``trigger="auto"`` derives the label from what actually fired (:func:`derive_trigger`); an explicit string is
    recorded as given, which is what a replay wants.
    """
    pol = plan_block(policy) if policy is not None else plan_block(load_policy())
    summary: dict[str, Any] = {
        "lane": LANE, "trigger": str(trigger or "tick"), "triggers": [str(trigger or "tick")],
        "calendar_anchors": [], "anchor_max_late_minutes": 0.0,
        "rows_evaluated": 0, "transitions": 0, "plans_written": 0,
        "not_measured": 0, "candidates": 0, "empty_reason": None, "error": None, "errors": {},
        "sleeve_basis": None, "calendar_events": 0, "rows": [],
        "alerts": {"planned": [], "sent": [], "refused": [], "digest": []},
        "alerted": 0, "reconcile": {}, "heal": [],
    }
    try:
        inp = dict(inputs) if inputs is not None else collect_inputs(
            db_query, now, policy=pol, calendar_path=calendar_path, mre=mre)
        summary["errors"] = dict(inp.get("errors") or {})
        summary["sleeve_basis"] = inp.get("sleeve_basis")
        summary["calendar_events"] = len(inp.get("events") or [])
        if not inp.get("episode"):
            summary["empty_reason"] = "no_open_episode"
        summary["candidates"] = len(inp.get("candidates") or [])
        rows = build_rows(inp, pol, now)
        summary["rows_evaluated"] = len(rows)
        if str(trigger or "").lower() == "auto":
            derived = derive_trigger(rows=rows, events=inp.get("events") or [], now=now, policy=pol)
            summary["trigger"] = derived["trigger"]
            summary["triggers"] = derived["triggers"]
            summary["calendar_anchors"] = derived["calendar"]
            summary["anchor_max_late_minutes"] = derived["anchor_max_late_minutes"]
        results = evaluate_rows(rows, pol, now)
        summary["not_measured"] = sum(1 for r in results if r.get("verdict") != "OK")
        summary["rows"] = [{
            "symbol": r.get("symbol"), "account_label": r.get("account_label"),
            "previous_stage": r.get("previous_stage"), "stage": r.get("stage"),
            "verdict": r.get("verdict"), "alert": (r.get("alert") or {}).get("event_id"),
            "reasons": list(r.get("reasons") or [])[:6],
        } for r in results]
        if not rows and summary["empty_reason"] is None:
            summary["empty_reason"] = "no_held_candidate"
        if apply and rows:
            previous = {}
            for r in rows:
                stored = r.get("stored_lifecycle")
                if isinstance(stored, Mapping) and stored:
                    previous[(str(r.get("episode_id") or ""), str(r.get("symbol") or "").upper())] = stored
            wrote = persist_results(conn, results, trigger=summary["trigger"], now=now, previous=previous)
            summary["transitions"] = wrote["transitions"]
            summary["plans_written"] = wrote["plans"]
            # persist first, alert second: a text that goes out before the row exists can never be reconciled
            alerts = deliver_alerts(results, now=now, send=True, text_sender=text_sender)
            summary["alerts"] = alerts
            summary["alerted"] = record_alerts(conn, alerts, now)
            if callable(db_query):
                summary["reconcile"] = reconcile_unalerted(
                    conn, db_query, now=now, send=True, text_sender=text_sender)
        else:
            summary["alerts"] = deliver_alerts(results, now=now, send=False)
        summary["heal"] = heal_actions(
            errors=summary["errors"], transitions=summary["transitions"],
            alerted=len(summary["alerts"].get("sent") or []),
            late_minutes=float(summary.get("anchor_max_late_minutes") or 0.0), policy=pol)
    except Exception as exc:  # noqa: BLE001 - reported by type AND text, never flattened into a zero
        summary["error"] = f"{type(exc).__name__}: {exc}"
    return summary


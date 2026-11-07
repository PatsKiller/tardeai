"""GET /api/v2/market-event/active and /history (MarketEvent@v1). Spec SPEC_MARKET_EVENT_REENTRY_20261107 §4.4.

Read-only. Reads:
* the WP1/WP2 tables ``market_event_episodes`` and ``market_event_candidates`` (spec §4.2);
* daily bars built from ``market_quotes`` (sources finviz and alpaca only, never yfinance: spec §2),
  one bar per ET regular session (09:30-16:15) from the quotes fetched that day;
* the Market Risk snapshot;
* settled cash per account from the holdings rows;
* sells from ``trade_transactions``, for the wash-sale annotation.

The plan itself is ``market_event_plan.build``.

Account labels only: an account key or number never leaves this module. Each account is keyed
internally while it is computed, and the key is dropped before the payload is returned.
MBI_BEHAVIOR = 0: no order, stop, broker or DB-write path. ``db_query`` is the server's read-only helper.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

try:
    from scripts.lib import market_event_plan as plan
    from scripts.lib import wash_sale
except ImportError:  # scripts/ on sys.path (the server)
    from lib import market_event_plan as plan  # type: ignore
    from lib import wash_sale  # type: ignore

SCHEMA = "MarketEvent@v1"
HISTORY_SCHEMA = "MarketEventHistory@v1"
BARS_LOOKBACK_DAYS = 120
SELLS_LOOKBACK_DAYS = 400
STALE_SNAPSHOT_HOURS = 26.0
STALE_BAR_DAYS = 4
_WASH_ORDER = {"WASH_SALE_RISK_LOSS": 3, "UNVERIFIED": 2, "HOUSE_HOLD_NO_LOSS": 1, "NONE": 0}

DbQuery = Callable[..., Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _age_hours(stamp: Any, now: datetime) -> Optional[float]:
    s = _iso(stamp)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def _rows(db_query: DbQuery, sql: str, params: Any = None) -> Optional[list[dict[str, Any]]]:
    """None = the read failed (table missing, DB down); [] = read fine, no rows."""
    r = db_query(sql, params)
    if r is None:
        return None
    return [dict(x) for x in r]


def _episode_sort_key(e: Mapping[str, Any]) -> str:
    for k in ("opened_at", "updated_at", "created_at", "baseline_date"):
        if e.get(k):
            return _iso(e[k]) or ""
    return ""


def _clean_episode(e: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (_iso(v) if isinstance(v, (datetime, date)) else v) for k, v in e.items()}


# --------------------------------------------------------------------------- readers


def read_open_episode(db_query: DbQuery) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    rows = _rows(db_query, "SELECT * FROM market_event_episodes WHERE state <> 'CLOSED'")
    if rows is None:
        return None, "market_event_episodes unreadable (table missing or DB unavailable)"
    if not rows:
        return None, None
    rows.sort(key=_episode_sort_key, reverse=True)
    return _clean_episode(rows[0]), None


def read_candidates(db_query: DbQuery, episode_id: Any) -> tuple[list[dict[str, Any]], Optional[str]]:
    rows = _rows(db_query, "SELECT * FROM market_event_candidates WHERE episode_id = %s", (episode_id,))
    if rows is None:
        return [], "market_event_candidates unreadable"
    return rows, None


BAR_SOURCES = ("finviz", "alpaca")
BARS_SQL = (
    "SELECT symbol, d AS bar_time, (array_agg(price ORDER BY fetched_at))[1] AS open, max(price) AS high, "
    "min(price) AS low, (array_agg(price ORDER BY fetched_at DESC))[1] AS close, max(volume) AS volume "
    "FROM (SELECT symbol, price, volume, fetched_at, "
    "(fetched_at AT TIME ZONE 'America/New_York')::date AS d, "
    "(fetched_at AT TIME ZONE 'America/New_York')::time AS t FROM market_quotes "
    "WHERE symbol = ANY(%s) AND source = ANY(%s) AND fetched_at >= %s AND price > 0) q "
    "WHERE extract(isodow FROM d) < 6 AND t >= '09:30' AND t <= '16:15' "
    "GROUP BY symbol, d ORDER BY symbol, d"
)


def read_bars(db_query: DbQuery, symbols: Sequence[str], today: date) -> dict[str, list[dict[str, Any]]]:
    if not symbols:
        return {}
    # market_ohlcv_bars daily is yfinance-only (cc-opus-3, 11-07), so bars come from market_quotes.
    # Quotes are sampled, so high/low are the sampled extremes, not the true session range.
    rows = _rows(db_query, BARS_SQL,
                 (list(symbols), list(BAR_SOURCES), (today - timedelta(days=BARS_LOOKBACK_DAYS)).isoformat())) or []
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r["symbol"]).upper(), []).append(
            {"date": _iso(r.get("bar_time")), **{k: r.get(k) for k in ("open", "high", "low", "close", "volume")}})
    return {sym: _after_last_split(b) for sym, b in out.items()}


SPLIT_JUMP_RATIO = 1.67  # a session-to-session close move this large (either way) is read as a split, not a price


def _after_last_split(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the bars after the last split-sized break, so a split never reads as a crash or a new low."""
    start = 0
    for i in range(1, len(bars)):
        try:
            a, b = float(bars[i - 1]["close"]), float(bars[i]["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if a > 0 and b > 0 and max(a / b, b / a) >= SPLIT_JUMP_RATIO:
            start = i
    return bars[start:]


def read_sectors(db_query: DbQuery, symbols: Sequence[str]) -> dict[str, str]:
    if not symbols:
        return {}
    rows = _rows(db_query,
                 "SELECT DISTINCT ON (symbol) symbol, data->>'sector' AS sector FROM ticker_snapshot_daily "
                 "WHERE symbol = ANY(%s) ORDER BY symbol, snapshot_date DESC", (list(symbols),)) or []
    return {str(r["symbol"]).upper(): r["sector"] for r in rows if r.get("sector")}


def read_wash(db_query: DbQuery, symbols: Sequence[str], today: date,
              taxable: Callable[[Any], bool]) -> dict[str, dict[str, Any]]:
    """Most restrictive wash-sale classification per symbol across taxable accounts (wash_sale.classify)."""
    if not symbols:
        return {}
    rows = _rows(db_query,
                 "SELECT trade_date, trade_time, action, symbol, quantity, price, amount, fees, account "
                 "FROM trade_transactions WHERE symbol = ANY(%s) AND trade_date >= %s",
                 (list(symbols), (today - timedelta(days=SELLS_LOOKBACK_DAYS)).isoformat())) or []
    series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        series.setdefault((str(r.get("symbol") or "").upper(), str(r.get("account") or "")), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for (sym, acct), rs in series.items():
        if not taxable(acct):
            continue
        sells = [r for r in rs if wash_sale.is_sale(r.get("action"))]
        if not sells:
            continue
        last = max(sells, key=lambda r: str(r.get("trade_date") or ""))
        sell_date = wash_sale.as_date(last.get("trade_date"))
        if sell_date is None or (today - sell_date).days > wash_sale.WASH_DAYS:
            continue
        fifo = wash_sale.fifo_realized_gain(rs, sell_date=sell_date)
        c = wash_sale.classify(last_taxable_sell_date=sell_date, realized_gain=fifo.get("realized_gain"),
                               evidence=str(fifo.get("evidence") or ""), today=today)
        if _WASH_ORDER.get(c.get("kind"), 0) > _WASH_ORDER.get((out.get(sym) or {}).get("kind"), -1):
            out[sym] = c
    return out


def accounts_from_holdings(holdings_rows: Sequence[Mapping[str, Any]],
                           label: Callable[[Any], str], facts: Callable[[Mapping[str, Any]], Mapping[str, Any]]
                           ) -> list[dict[str, Any]]:
    """[{account_label, account_type, cash_usd, account_value_usd, cash_as_of}] from holdings rows.
    Cash = rows with is_cash (the same rule as cio_capital_plan.account_cash_breakdown)."""
    by: dict[str, dict[str, Any]] = {}
    for h in holdings_rows or []:
        if not isinstance(h, Mapping):
            continue
        key = str(h.get("account") or h.get("account_id") or "")
        if not key:
            continue
        a = by.setdefault(key, {"cash_usd": 0.0, "account_value_usd": 0.0, "cash_as_of": None})
        mv = plan._f(h.get("market_value")) or 0.0
        a["account_value_usd"] += mv
        if h.get("is_cash"):
            a["cash_usd"] += mv
            stamp = _iso(h.get("as_of") or h.get("last_updated") or h.get("updated_at"))
            if stamp and (a["cash_as_of"] is None or stamp < a["cash_as_of"]):
                a["cash_as_of"] = stamp
    out = []
    for key in sorted(by):
        f = facts({"account": key}) or {}
        out.append({"account_label": label(key), "account_type": str(f.get("account_type") or "unknown"),
                    **by[key]})
    return out


# --------------------------------------------------------------------------- routes


def build_active(*, db_query: DbQuery, snapshot: Optional[Mapping[str, Any]],
                 holdings_rows: Sequence[Mapping[str, Any]], label: Callable[[Any], str],
                 facts: Callable[[Mapping[str, Any]], Mapping[str, Any]], taxable: Callable[[Any], bool],
                 policy: Optional[Mapping[str, Any]] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or _now()
    today = wash_sale.as_date(now) or now.date()
    pol = dict(policy) if policy is not None else plan.load_policy()
    stale: list[str] = []
    episode, err = read_open_episode(db_query)
    if err:
        stale.append(err)
    candidates: list[dict[str, Any]] = []
    if episode:
        candidates, cerr = read_candidates(db_query, episode.get("episode_id"))
        if cerr:
            stale.append(cerr)
    top = sorted(candidates, key=lambda c: (c.get("rank") is None, c.get("rank") or 0,
                                            str(c.get("symbol"))))[: int(pol.get("max_candidates", 25))]
    syms = [str(c.get("symbol") or "").upper() for c in top]
    sectors = read_sectors(db_query, [s for s, c in zip(syms, top) if not _sector_of(c)])
    for c, s in zip(top, syms):
        c["sector"] = _sector_of(c) or sectors.get(s)
    bars = read_bars(db_query, syms, today)
    wash = read_wash(db_query, syms, today, taxable) if syms else {}
    accounts = accounts_from_holdings(holdings_rows, label, facts)
    doc = plan.build(episode=episode, candidates=top, bars_by_symbol=bars, snapshot=snapshot,
                     accounts=accounts, policy=pol, wash=wash)
    # freshness
    snap_age = _age_hours((snapshot or {}).get("as_of"), now)
    if snap_age is None or snap_age > STALE_SNAPSHOT_HOURS:
        stale.append(f"market-risk snapshot age {snap_age if snap_age is None else round(snap_age, 1)} h")
    last_bar = max((b[-1]["date"] for b in bars.values() if b), default=None)
    if syms and (last_bar is None or (today - date.fromisoformat(last_bar[:10])).days > STALE_BAR_DAYS):
        stale.append(f"latest daily bar {last_bar}")
    missing_bars = [s for s in syms if not bars.get(s)]
    if missing_bars:
        stale.append(f"no daily bars for {len(missing_bars)} of {len(syms)} candidates: {', '.join(missing_bars[:10])}")
    cand_stamp = max((_iso(c.get("updated_at")) or "" for c in top), default="") or None
    cand_age = _age_hours(cand_stamp, now)
    if top and (cand_age is None or cand_age > STALE_SNAPSHOT_HOURS):
        stale.append(f"candidates last updated {cand_stamp}")
    return consumer_view({
        "schema": SCHEMA,
        "advisory_only": True,
        "note": plan.ADVISORY_NOTE,
        "episode": doc["episode"],
        "market_gate": doc["market_gate"],
        "candidates": doc["candidates"],
        "accounts": doc["accounts"],
        "policy": doc["policy"],
        "computed_at": now.isoformat(),
        "inputs_as_of": {"market_risk": (snapshot or {}).get("as_of"), "daily_bars": last_bar,
                         "candidates": cand_stamp},
        "stale": bool(stale),
        "stale_reasons": stale,
    })


_EVIDENCE_NUMBERS = {"fwd_pe": "forward_pe", "sector_median_pe": "sector_median_pe", "peg": "peg", "roic_pct": "roic_pct"}


def _gate_state(ok: Optional[bool]) -> str:
    return "unknown" if ok is None else ("pass" if ok else "fail")


def consumer_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Add the fields the two consumers read (LQ-366 fold rehearsal), without removing any.

    * the banner and sheet (apps/command-center-v3/src/lib/marketEvent.ts): episode.id/title/tier,
      market_gate.state/chips, and per candidate a gates[] chip list and plan.tranches[] across accounts;
    * the brief (scripts/market_event_brief.py): market_gate.checks, plan.tranche (the highest tranche
      ready now) and plan.accounts[] (per account, the dollars of every tranche ready now: nothing is
      recorded as entered, so all ready tranches are deployable).
    The candidate's ``gates`` is the chip LIST; the brief's dict view is ``gate_checks``.
    """
    mg = doc.get("market_gate") or {}
    evaluated = bool(mg.get("evaluated"))
    prim = mg.get("primary") or {}
    prim_ok = (bool(prim.get("score_falling") or prim.get("tier_stepped_down")) if evaluated and prim else None)
    chips = [{"id": "market_primary", "label": "Market risk easing", "state": _gate_state(prim_ok)}]
    for c in mg.get("confirmations") or []:
        ok = c.get("confirms")
        st = "unknown" if str(c.get("state") or "").upper() in ("", "UNKNOWN") else _gate_state(bool(ok))
        chips.append({"id": f"market_{c.get('category')}", "label": str(c.get("name") or c.get("category")),
                      "state": st})
    mg["state"] = "pass" if mg.get("passed") else ("fail" if evaluated else "unknown")
    mg["chips"] = chips
    mg["checks"] = {ch["id"]: ch["state"] == "pass" for ch in chips}
    ep = doc.get("episode")
    if isinstance(ep, dict):
        ep.setdefault("id", ep.get("episode_id"))
        ep.setdefault("tier", mg.get("tier"))
        kind = str(ep.get("kind") or "market event").replace("_", " ")
        scope = ep.get("scope")
        ep.setdefault("title", " · ".join(x for x in (kind.capitalize(),
                                                        None if scope in (None, "market") else str(scope),
                                                        f"baseline {ep['baseline_date']}" if ep.get("baseline_date")
                                                        else None) if x))
    rows_by_symbol: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for acct in doc.get("accounts") or []:
        for nm in acct.get("names") or []:
            rows_by_symbol.setdefault(str(nm.get("symbol")), []).append((acct, nm))
    for c in doc.get("candidates") or []:
        ev = c.get("reason_evidence") if isinstance(c.get("reason_evidence"), dict) else {}
        for out_key, ev_key in _EVIDENCE_NUMBERS.items():
            if c.get(out_key) is None and isinstance(ev.get(ev_key), (int, float)):
                c[out_key] = ev[ev_key]
        sig = ((c.get("name_gate") or {}).get("signals") or {}) if (c.get("name_gate") or {}).get("evaluated") else {}
        name_chips = [{"id": k, "label": lbl, "state": _gate_state(sig.get(k)) if sig else "unknown"}
                      for k, lbl in (("no_new_low", "No new low"), ("rsi_turning_up", "RSI turning up"),
                                     ("accumulation", "Accumulation"), ("sma20_reclaim", "Above 20-day average"))]
        c["gates"] = name_chips + chips
        c["gate_checks"] = {ch["id"]: ch["state"] == "pass" for ch in c["gates"]}
        ready_n = int(c.get("tranches_ready") or 0)
        tranches, acct_rows, notes = [], [], []
        inv = risk = budget = None
        for acct, nm in rows_by_symbol.get(str(c.get("symbol")), []):
            inv = nm.get("invalidation") if inv is None else inv
            if isinstance(nm.get("loss_at_invalidation_usd"), (int, float)):
                risk = (risk or 0.0) + nm["loss_at_invalidation_usd"]
            if isinstance(acct.get("risk_budget_per_name_usd"), (int, float)):
                budget = (budget or 0.0) + acct["risk_budget_per_name_usd"]
            notes += [f"{acct.get('account_label')}: {a}" for a in nm.get("annotations") or []]
            for t in nm.get("tranches") or []:
                zone = t.get("entry_zone") or [None, None]
                tranches.append({"n": t.get("tranche"), "pct": t.get("pct"), "account_label": acct.get("account_label"),
                                 "shares": t.get("shares"), "usd": t.get("usd"), "entry_low": zone[0],
                                 "entry_high": zone[1] if len(zone) > 1 else None, "condition": t.get("trigger"),
                                 "status": "ready" if t.get("ready") else "waiting"})
            ready = [t for t in nm.get("tranches") or [] if t.get("ready") and isinstance(t.get("usd"), (int, float))]
            if ready:
                zone = ready[0].get("entry_zone") or []
                acct_rows.append({"account_label": acct.get("account_label"), "tranches": [t.get("tranche") for t in ready],
                                  "tranche_usd": round(sum(t["usd"] for t in ready), 2),
                                  "shares": sum(int(t.get("shares") or 0) for t in ready) or None,
                                  "entry_zone": "-".join(f"{z:.2f}" for z in zone if isinstance(z, (int, float))),
                                  "invalidation": nm.get("invalidation")})
        c["plan"] = {"tranche": ready_n or None, "tranches": tranches, "accounts": acct_rows,
                     "invalidation": inv, "risk_usd": risk, "risk_budget_usd": budget, "notes": notes} \
            if tranches or notes else None
    return doc


def _sector_of(c: Mapping[str, Any]) -> Optional[str]:
    if c.get("sector"):
        return str(c["sector"])
    ev = c.get("reason_evidence")
    if isinstance(ev, Mapping) and ev.get("sector"):
        return str(ev["sector"])
    return None


def build_history(*, db_query: DbQuery, limit: int = 50, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or _now()
    rows = _rows(db_query, "SELECT * FROM market_event_episodes")
    if rows is None:
        return {"schema": HISTORY_SCHEMA, "episodes": [], "computed_at": now.isoformat(), "stale": True,
                "stale_reasons": ["market_event_episodes unreadable (table missing or DB unavailable)"]}
    rows.sort(key=_episode_sort_key, reverse=True)
    rows = rows[: max(1, min(int(limit or 50), 200))]
    counts = _rows(db_query, "SELECT episode_id, state, count(*) AS n FROM market_event_candidates "
                             "GROUP BY episode_id, state") or []
    by: dict[str, dict[str, int]] = {}
    for c in counts:
        by.setdefault(str(c.get("episode_id")), {})[str(c.get("state"))] = int(c.get("n") or 0)
    eps = []
    for e in rows:
        ce = _clean_episode(e)
        ce["candidate_states"] = by.get(str(e.get("episode_id")), {})
        eps.append(ce)
    return {"schema": HISTORY_SCHEMA, "episodes": eps, "computed_at": now.isoformat(), "stale": False,
            "stale_reasons": []}

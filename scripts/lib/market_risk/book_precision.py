"""Live-only precision for the operator's book: look-through exposure, per-position CIO stances, protection playbooks,
book clusters and the heat-map exposure column (precision PR).

Runs only in the live evaluator (``portfolio`` context present), never in backtests or fixtures. Reads the existing
read-only position, stop and profile readers (``exposure.load_inputs``), the ``etf_holdings_snapshot`` store when it
exists, and the latest inverse-hedge stoplight state. Writes nothing. Real symbols live only in the snapshot (the
persistent-state runtime file), never in the repo. Account labels are reduced to an account TYPE (ira / taxable) in
memory for the wash-sale note and dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import lookthrough as lt
from scripts.lib.market_risk import position_stances as ps
from scripts.lib.market_risk import protection_playbook as pp
from scripts.lib.market_risk import sectors as sec


def _account_type(label: Any) -> str:
    s = str(label or "").lower()
    return "ira" if ("ira" in s or "roth" in s or "rollover" in s or "401" in s) else "taxable"


def _reader_bars(reader: Any, sym: str, n: int, end: datetime) -> list[dict[str, Any]]:
    try:
        return list(reader.daily_bars([sym], sessions=n, end=end) or [])
    except Exception:  # noqa: BLE001 — missing bars are an honest unknown in the playbook
        return []


def _sma_above(reader: Any, sym: str, n: int, end: datetime) -> bool | None:
    rows = [r for r in _reader_bars(reader, sym, n + 5, end) if r.get("close") is not None]
    if len(rows) < n:
        return None
    closes = [float(r["close"]) for r in rows]
    return closes[-1] >= sum(closes[-n:]) / n


def _hedge_state(conn_factory: Any, instrument: str) -> dict[str, Any] | None:
    try:
        conn = conn_factory()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT light, new_state, created_at FROM inverse_stoplight_transitions WHERE instrument=%s "
                "ORDER BY created_at DESC LIMIT 1",
                (instrument,),
            )
            r = cur.fetchone()
        conn.close()
        return None if not r else {"symbol": instrument, "light": r[0], "state": r[1], "as_of": str(r[2])}
    except Exception as exc:  # noqa: BLE001
        return {"symbol": instrument, "state": "UNKNOWN", "reason": type(exc).__name__}


HOLDINGS_STORE_ID = "portfolio.holdings.current"  # data/portfolios/state/holdings.json — the file Home reads


def current_book(policy: dict[str, Any], *, doc: dict | None = None, path: Any = None) -> dict[str, Any]:
    """The CURRENT holdings (canonical store ``portfolio.holdings.current``, the same holdings.json Home reads), split
    into material positions and residuals, with closed_today excluded. Freshness is ``data_as_of`` /
    ``aggregate_published_at`` — the top-level ``as_of`` of that file is a stale legacy field and is never used."""
    src = None
    if doc is None:
        from scripts.lib import canonical_store_registry as reg

        res = reg.resolve_store(HOLDINGS_STORE_ID)
        src = str(res.get("path"))
        import json as _json

        doc = _json.loads(open(res["path"], encoding="utf-8").read())
    cfg = (policy.get("positions") or {}).get("materiality") or {}
    min_shares = float(cfg.get("min_shares", 1.0))
    min_mv = float(cfg.get("min_market_value", 1000.0))
    min_w = float(cfg.get("min_book_weight", 0.001))
    holdings = [
        h for h in doc.get("holdings") or [] if isinstance(h, dict) and h.get("symbol") and not h.get("is_cash")
    ]
    total = sum(float(h.get("market_value") or 0) for h in holdings) or 0.0
    closed = {
        (str(acct), str(r.get("symbol")).upper())
        for acct, rows in (doc.get("closed_today") or {}).items()
        for r in (rows or [])
        if isinstance(r, dict)
    }
    material, residuals, excluded_closed = [], [], []
    for h in holdings:
        sym = str(h["symbol"]).upper()
        sh = float(h.get("shares") or h.get("quantity") or 0)
        mv = float(h.get("market_value") or 0)
        if (str(h.get("account")), sym) in closed and sh < min_shares:
            excluded_closed.append(sym)
            continue
        if sh < min_shares or mv < min_mv or (total and mv / total < min_w):
            residuals.append(sym)
            continue
        material.append(
            {
                "symbol": sym,
                "account_type": _account_type(h.get("account")),
                "shares": sh,
                "mark": float(h.get("current_price") or h.get("price") or 0) or None,
            }
        )
    return {
        "source": src or "injected",
        "data_as_of": doc.get("data_as_of"),
        "published_at": doc.get("aggregate_published_at"),
        "material": material,
        "residuals": sorted(set(residuals)),
        "closed_today_excluded": sorted(set(excluded_closed)),
    }


def attach(
    a: Any,
    *,
    now: datetime,
    reader: Any,
    policy: dict[str, Any],
    prior: dict | None,
    loaders: dict | None = None,
    conn_factory: Any = None,
) -> dict[str, Any]:
    from scripts.lib.market_risk import exposure

    inp = exposure.load_inputs(now=now, **(loaders or {}))
    if not inp.get("available"):
        a.positions = {"_note": f"book unavailable: {inp.get('note')}"}
        return {"available": False}
    book = current_book(policy, doc=(loaders or {}).get("book_doc"))
    material = {p["symbol"] for p in book["material"]}
    pos = [p for p in inp["positions"] if not p.get("is_cash") and p["symbol"] in material]
    syms = sorted(material)
    marks = {p["symbol"]: p.get("mark") for p in book["material"]}
    types: dict[str, set[str]] = {}
    for p in book["material"]:
        types.setdefault(p["symbol"], set()).add(p["account_type"])
    for p in pos:
        marks.setdefault(p["symbol"], p.get("mark"))
    stops = {str(s.get("symbol")).upper(): s.get("level") for s in inp.get("stops") or [] if s.get("level")}
    dist = {s: (marks[s] / float(stops[s]) - 1.0) * 100.0 for s in syms if s in stops and marks.get(s)}
    holdings: dict[str, list[dict[str, Any]]] = {}
    if hasattr(reader, "etf_holdings"):
        try:
            for r in reader.etf_holdings(syms, end=now) or []:
                holdings.setdefault(str(r["etf"]).upper(), []).append(r)
        except Exception:  # noqa: BLE001
            holdings = {}
    basket = list((policy.get("ai_concentration") or {}).get("basket") or [])
    report = (
        {str(e.get("symbol")).upper() for e in (inp.get("earnings") or []) if isinstance(e, dict)}
        if isinstance(inp.get("earnings"), list)
        else set()
    )
    expo = {
        s: lt.exposure_for(
            s,
            ai_basket=basket,
            holdings=holdings,
            profiles=inp.get("profiles") or {},
            reporting_soon=report,
            themes=(policy.get("positions") or {}).get("theme_overrides") or {},
        )
        for s in syms
    }
    doc = a.to_dict()
    block = doc.get("sectors") or {}
    cfg = policy.get("positions") or {}
    prior_pos = {k: v for k, v in ((prior or {}).get("positions") or {}).items() if isinstance(v, dict)}
    hist = [{"tier": h.get("tier"), "sectors": h.get("sectors") or {}} for h in ((prior or {}).get("history") or [])]
    reentry = ps.reentry_conditions(
        flagged_groups=sorted({g for p in prior_pos.values() for g in p.get("flagged_groups") or []}),
        sectors_block=block,
        history=hist,
        index_above_50d=_sma_above(reader, str(cfg.get("reclaim_symbol") or "QQQ"), 50, now),
        vix_below_20d=(None if (v := _sma_above(reader, "^VIX", 20, now)) is None else not v),
        engine_tier=str(doc.get("tier")),
        cfg=cfg,
    )
    stances = ps.stances(
        positions=syms,
        exposures=expo,
        tier=str(doc.get("tier")),
        shock=doc.get("shock_type") or {},
        sectors_block=block,
        prior=prior_pos,
        reentry=reentry,
        stop_distance_pct=dist,
        policy=policy,
        as_of=doc.get("as_of"),
    )
    rets = {}
    for s in syms:
        b = [float(r["close"]) for r in _reader_bars(reader, s, 70, now) if r.get("close")]
        rets[s] = [b[i] / b[i - 1] - 1 for i in range(1, len(b)) if b[i - 1]]
    fg = {s: stances[s]["flagged_groups"] for s in syms}
    mcorr = float((cfg.get("playbook") or {}).get("min_cluster_corr", 0.8))
    clusters = pp.book_clusters(rets, fg, mcorr)
    hedge = _hedge_state(conn_factory, "PSQ") if conn_factory else None
    flagged = [s for s in syms if stances[s]["stance"] not in ("HOLD",)]
    playbooks = {}
    for s in flagged:
        cl = [s, *pp.moves_with(s, {k: v for k, v in rets.items() if k in flagged}, {k: fg[k] for k in flagged}, mcorr)]
        try:
            playbooks[s] = pp.build(
                symbol=s,
                tier=str(doc.get("tier")),
                stance=stances[s],
                stop_distance_pct=dist.get(s),
                bars=_reader_bars(reader, s, 520, now),
                holdings=holdings.get(s),
                after_hours_moves={},
                account_types=sorted(types.get(s, set())),
                hedge=hedge,
                cluster=cl,
                policy=policy,
                as_of=doc.get("as_of"),
            )
        except Exception as exc:  # noqa: BLE001 — a playbook failure is reported, never blocks the tier
            playbooks[s] = {"symbol": s, "error": f"{type(exc).__name__}: {exc}"}
    for s, rec in stances.items():
        rec["look_through"] = {k: expo[s].get(k) for k in ("groups", "ai_share", "reporting", "basis", "note")}
        if s in playbooks:
            rec["playbook"] = playbooks[s]
    a.positions = {
        **stances,
        "_book": {
            "source": book["source"],
            "data_as_of": book["data_as_of"],
            "published_at": book["published_at"],
            "residuals_ignored": len(book["residuals"]),
            "closed_today_excluded": book["closed_today_excluded"],
        },
    }
    a.heatmap = sec.heatmap(block, lt.book_group_exposure(list(expo.values())))
    c.assert_no_behavior_fields(a.positions)
    return {"available": True, "flagged": flagged, "clusters": clusters, "hedge": hedge}


def reentry_watch_block(
    a: Any, *, now: datetime, reader: Any, policy: dict[str, Any], prior: dict | None, conn_factory: Any
) -> dict[str, Any]:
    """RE-ENTRY WATCH for every symbol exited in the last ``lookback_days`` (trade_closed, read-only), held or not."""
    from datetime import date as _date

    from scripts.lib.market_risk import reentry_watch as rw

    cfg = policy.get("reentry_watch") or {}
    doc = a.to_dict()
    exits: dict[str, dict[str, Any]] = {}
    conn = conn_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, account, close_date, (pnl < 0) FROM trade_closed "
                "WHERE close_date >= %s::date - %s ORDER BY close_date",
                (now.date(), int(cfg.get("lookback_days", 30))),
            )
            for sym, acct, d, loss in cur.fetchall():
                e = exits.setdefault(str(sym).upper(), {"accounts": set(), "loss": False, "exit_date": str(d)})
                e["accounts"].add(_account_type(acct))
                e["loss"] = e["loss"] or bool(loss)
                e["exit_date"] = max(e["exit_date"], str(d))
            syms = sorted(exits)
            earn: dict[str, Any] = {}
            if syms:
                cur.execute(
                    "SELECT symbol, next_earnings_date, last_earnings_date FROM symbol_profiles WHERE symbol = ANY(%s)",
                    (syms,),
                )
                earn = {str(r[0]).upper(): (r[1], r[2]) for r in cur.fetchall()}
    finally:
        conn.close()
    block = doc.get("sectors") or {}
    hist = [h.get("sectors") or {} for h in ((prior or {}).get("history") or [])] + [block]
    label_of = {r.get("key"): r.get("label") for r in block.get("groups") or []}
    basket = list((policy.get("ai_concentration") or {}).get("basket") or [])
    themes = (policy.get("positions") or {}).get("theme_overrides") or {}
    flow = next((o for o in doc.get("observations") or [] if o.get("category") == "options_flow"), {})
    cards = {}
    for sym, e in exits.items():
        bars = [r for r in (reader.daily_bars([sym], sessions=400, end=now) or []) if r.get("close") is not None]
        closes = [float(r["close"]) for r in bars]
        dates = [str(r["date"])[:10] for r in bars]
        pre = None
        if e["exit_date"] in dates:
            k = dates.index(e["exit_date"])
            pre = closes[k - 1] if k > 0 else None
        elif dates:
            before = [cl for d, cl in zip(dates, closes) if d < e["exit_date"]]
            pre = before[-1] if before else None
        ex = lt.exposure_for(sym, ai_basket=basket, themes=themes)
        groups = ex.get("groups") or {}
        main = max(groups.items(), key=lambda kv: kv[1])[0] if groups else None
        gh = [next((g.get("state") for g in (h.get("groups") or []) if g.get("key") == main), "UNKNOWN") for h in hist]
        nxt, lst = earn.get(sym) or (None, None)
        to_e = since_e = None
        ed = None
        if nxt and (_date.fromisoformat(str(nxt)[:10]) - now.date()).days >= 0:
            ed = str(nxt)[:10]
            to_e = int((_date.fromisoformat(ed) - now.date()).days * 5 / 7)
        if lst:
            since_e = int((now.date() - _date.fromisoformat(str(lst)[:10])).days * 5 / 7)

        try:
            cards[sym] = rw.card(
                symbol=sym,
                exit_date=e["exit_date"],
                breakdown_close=pre,
                closes=closes,
                last_date=dates[-1] if dates else None,
                group_label=label_of.get(main) or main,
                group_history=gh,
                earnings_next=ed,
                earnings_last=str(lst)[:10] if lst else None,
                sessions_since_earnings=since_e,
                sessions_to_earnings=to_e,
                market_tier=str(doc.get("market_tier")),
                options_flow_state=str(flow.get("state") or "UNKNOWN"),
                account_types=sorted(e["accounts"]),
                loss=e["loss"],
                days_since_exit=(now.date() - _date.fromisoformat(e["exit_date"])).days,
                policy=policy,
            )
        except Exception as exc:  # noqa: BLE001 — one symbol failing is reported, the rest still render
            cards[sym] = {"symbol": sym, "error": f"{type(exc).__name__}: {exc}"}
    a.reentry_watch = cards
    return cards

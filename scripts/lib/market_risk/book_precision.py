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
    raw = (loaders or {}).get("store_loader") or exposure._default_store_loader  # noqa: SLF001
    try:
        types: dict[str, set[str]] = {}
        for h in (raw() or {}).get("holdings") or []:
            if isinstance(h, dict) and h.get("symbol"):
                types.setdefault(str(h["symbol"]).upper(), set()).add(_account_type(h.get("account")))
    except Exception:  # noqa: BLE001
        types = {}
    pos = [p for p in inp["positions"] if not p.get("is_cash")]
    syms = sorted({p["symbol"] for p in pos})
    marks = {p["symbol"]: p.get("mark") for p in pos}
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
            s, ai_basket=basket, holdings=holdings, profiles=inp.get("profiles") or {}, reporting_soon=report
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
    a.positions = stances
    a.heatmap = sec.heatmap(block, lt.book_group_exposure(list(expo.values())))
    c.assert_no_behavior_fields(a.positions)
    return {"available": True, "flagged": flagged, "clusters": clusters, "hedge": hedge}

"""The eleven categories (§2.2): each a weighted mean of normalized indicators with a coverage fraction.

A category with coverage below its ``min_coverage`` is UNKNOWN: excluded from S's numerator AND denominator,
named in the brief with the reason, and it penalizes confidence. Never a silent zero. Every indicator keeps its
audit trail — raw value, normalized signal, as_of, source, table, staleness and the refusal reason when a banned
feed would otherwise have been scored (§2.1, §4.6).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

from . import normalize as nz
from . import policy as pmod
from . import sessions_shim

ET = ZoneInfo("America/New_York")


# ── results ----------------------------------------------------------------------------------------------------
@dataclass
class IndicatorResult:
    key: str
    label: str
    type: str
    raw: Any = None
    normalized: float | None = None
    as_of: str | None = None
    source: str = ""
    table: str = ""
    weight: float = 0.0
    stale: bool = False
    refused_reason: str | None = None
    detail: str = ""
    basis: str | None = None

    @property
    def available(self) -> bool:
        return self.normalized is not None and not self.stale and self.refused_reason is None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["available"] = self.available
        return d


@dataclass
class CategoryResult:
    key: str
    title: str
    weight_prior: float
    weight_effective: float
    subscore: float | None
    coverage: float
    state: str
    indicators: list[IndicatorResult] = field(default_factory=list)
    reason_unknown: str | None = None
    basis: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "weight_prior": self.weight_prior,
            "weight_effective": self.weight_effective,
            "subscore": None if self.subscore is None else round(self.subscore, 4),
            "coverage": round(self.coverage, 4),
            "state": self.state,
            "basis": self.basis,
            "reason_unknown": self.reason_unknown,
            "note": self.note,
            "indicators": [i.to_dict() for i in self.indicators],
        }

    @property
    def measured(self) -> bool:
        return self.state != "UNKNOWN" and self.subscore is not None


# ── context passed to builders ---------------------------------------------------------------------------------
@dataclass
class BuildContext:
    bundle: Any
    policy: dict[str, Any]
    now: datetime
    tilt: float | None = None
    tilt_detail: str = ""
    surprise: float | None = None
    surprise_detail: str = ""
    vix_pct: float | None = None
    vix_value: float | None = None
    vix_source: str | None = None


# ── helpers ----------------------------------------------------------------------------------------------------
def _bars(bundle: Any, symbol: str) -> list[dict[str, Any]]:
    return list((bundle.bars or {}).get(symbol) or [])


def _closes(bundle: Any, symbol: str) -> list[float]:
    return [float(b["close"]) for b in _bars(bundle, symbol)]


def _sessions_since(d: date, now: datetime) -> int:
    """How many completed NYSE sessions after ``d`` have closed by ``now`` (0 = d is the last closed session)."""
    last = sessions_shim.last_closed_session(now)
    if d >= last:
        return 0
    n, cur = 0, d
    while cur < last:
        cur += timedelta(days=1)
        if sessions_shim.is_trading_day(cur):
            n += 1
    return n


def _parse_age_spec(spec: Any) -> tuple[str, float]:
    """``"180m"``/``"168h"`` -> ("hours", 3.0/168.0); an int is sessions."""
    if isinstance(spec, (int, float)):
        return "sessions", float(spec)
    s = str(spec).strip().lower()
    if s.endswith("m"):
        return "hours", float(s[:-1]) / 60.0
    if s.endswith("h"):
        return "hours", float(s[:-1])
    if s.endswith("d"):
        return "hours", float(s[:-1]) * 24.0
    return "sessions", float(s)


def _as_instant(as_of: str | None) -> datetime | None:
    if not as_of:
        return None
    try:
        dt = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stale(as_of: str | None, now: datetime, max_age: Any, policy: dict[str, Any]) -> tuple[bool, str]:
    """Staleness in the category's own units (§2.9): sessions for daily series, market hours for intraday."""
    kind, limit = _parse_age_spec(max_age)
    if kind == "sessions":
        try:
            d = date.fromisoformat(str(as_of)[:10])
        except (TypeError, ValueError):
            return True, "no as_of"
        behind = _sessions_since(d, now)
        return behind > int(limit), f"{behind} sessions old (max {int(limit)})"
    inst = _as_instant(as_of)
    if inst is None:
        return True, "no as_of"
    reopen = _reopen(policy)
    hours = sessions_shim.market_hours_between(inst, now, reopen=reopen)
    return hours > limit, f"{hours:.1f} market hours old (max {limit:.1f})"


def _reopen(policy: dict[str, Any]) -> time | None:
    raw = str((policy.get("freshness") or {}).get("reopen_et") or "")
    try:
        h, m = raw.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def freshness_weight(as_of: str | None, now: datetime, policy: dict[str, Any]) -> float:
    """The ladder of §2.5 on the market clock; an unreadable as_of is treated as maximally stale."""
    inst = _as_instant(as_of)
    if inst is None:
        return 0.0
    hours = sessions_shim.market_hours_between(inst, now, reopen=_reopen(policy))
    ladder = policy["freshness"]["ladder"]
    for ceiling, weight in sorted(ladder, key=lambda r: float(r[0])):
        if hours <= float(ceiling):
            return float(weight)
    return float(policy["freshness"]["after_last"])


# ── builder: one indicator -------------------------------------------------------------------------------------
Builder = Callable[[dict[str, Any], BuildContext, str], IndicatorResult]


def _result(spec: dict[str, Any], **kw: Any) -> IndicatorResult:
    return IndicatorResult(
        key=str(spec["key"]),
        label=str(spec["label"]),
        type=str(spec["type"]),
        weight=float(spec["weight"]),
        **kw,
    )


def _trend(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["trend"]
    cash = spec.get("cash_symbol")
    etf = spec.get("etf_symbol")
    if cash and _bars(ctx.bundle, str(cash)):
        sym, source, basis = str(cash), _basis_of(_bars(ctx.bundle, str(cash))), "cash"
    elif etf:
        sym, source, basis = str(etf), _basis_of(_bars(ctx.bundle, str(etf))), "etf_derived"
    else:
        return _result(spec, refused_reason="no cash level and no ETF proxy configured")
    bars = _bars(ctx.bundle, sym)
    if not bars:
        return _result(spec, source=source, table=table, basis=basis, refused_reason=f"no daily bars for {sym}")
    s, detail = nz.trend_state(bars, cfg)
    wk, wk_detail = nz.weekly_state(bars, _weekly_cfg(ctx.policy, cfg))
    blend = float(cfg.get("weekly_blend", 0.2))
    if s is not None and wk is not None:
        s = (1.0 - blend) * s + blend * wk
        detail = f"{detail}; {wk_detail}"
    elif s is None:
        return _result(
            spec, raw=bars[-1]["close"], as_of=str(bars[-1]["date"]), source=source, table=table,
            basis=basis, refused_reason=detail,
        )
    return _result(
        spec,
        raw=round(float(bars[-1]["close"]), 4),
        normalized=round(s, 4),
        as_of=str(bars[-1].get("as_of") or bars[-1]["date"]),
        source=source,
        table=table,
        detail=f"{sym}: {detail}" + (" (ETF-derived)" if basis == "etf_derived" else ""),
        basis=basis,
    )


def _basis_of(bars: Sequence[dict[str, Any]]) -> str:
    return str(bars[-1].get("source") or "") if bars else ""


def _weekly_cfg(policy: dict[str, Any], trend_cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(policy["normalization"]["weekly"])
    # the weekly leg needs only its own history; the trend leg's 210-bar floor is not a weekly precondition
    cfg["min_bars"] = max(int(cfg["min_bars"]), int(cfg["rv_sessions"]) + 2)
    return cfg


def _futures(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cat = pmod.category(ctx.policy, "futures")
    base = dict(ctx.policy["normalization"]["futures"])
    cfg = {**base, "max_age": cat.get("max_age", "180m"), "min_prints": cat.get("min_prints", 2)}
    root = str(spec["symbol"])
    rows = [
        r
        for r in (ctx.bundle.extended or [])
        if str(r.get("symbol")).upper().startswith(root)
        and str(r.get("session")) in ("futures_open", "overnight", "premarket")
    ]
    if not rows:
        return _result(spec, source="", table=table, refused_reason=f"no {root} print in the last 8 days")
    rows.sort(key=lambda r: str(r["bar_start"]))
    newest = rows[-1]
    stale, why = _stale(str(newest["bar_start"]), ctx.now, cfg["max_age"], ctx.policy)
    # The print group starts at the most recent reopen boundary: same ET date is enough for the Sunday brief.
    day = str(newest["bar_start"])[:10]
    prints = [r for r in rows if str(r["bar_start"])[:10] == day]
    if len(prints) < int(cfg["min_prints"]):
        return _result(
            spec, raw=newest.get("price"), as_of=str(newest["bar_start"]), source=str(newest.get("feed") or ""),
            table=table, stale=stale,
            refused_reason=f"{len(prints)} print(s) on {day}; the policy needs {cfg['min_prints']} before a gap is stated",
        )
    anchor = prints[0].get("reference_close")
    anchor_label = "prior settle"
    if anchor is None:
        anchor, anchor_label = prints[0].get("price"), "first print after reopen"
    if not anchor or not newest.get("price"):
        return _result(spec, raw=newest.get("price"), as_of=str(newest["bar_start"]),
                       source=str(newest.get("feed") or ""), table=table, stale=stale,
                       refused_reason="no usable anchor level")
    gap_pct = (float(newest["price"]) / float(anchor) - 1.0) * 100.0
    s = nz.clip(gap_pct / float(cfg["gap_pct_scale"]))
    return _result(
        spec, raw=round(float(newest["price"]), 4), normalized=round(s, 4), as_of=str(newest["bar_start"]),
        source=str(newest.get("feed") or ""), table=table, stale=stale,
        detail=f"{gap_pct:+.2f}% vs {anchor_label} over {len(prints)} prints" + (f" ({why})" if stale else ""),
    )


def _vol_percentile_fred(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["percentile"]
    series = str(spec["fred_series"])
    rows = list((ctx.bundle.fred or {}).get(series) or [])
    values = [float(r["value"]) for r in rows]
    s, pct, detail = nz.percentile_state(values, cfg)
    as_of = str(rows[-1]["date"]) if rows else None
    stale, why = _stale(as_of, ctx.now, pmod.category(ctx.policy, "volatility")["max_age_sessions"], ctx.policy)
    if s is None:
        return _result(spec, source="fred", table=table, as_of=as_of, stale=stale, refused_reason=detail)
    return _result(spec, raw=round(values[-1], 4), normalized=round(s, 4), as_of=as_of, source=f"fred:{series}",
                   table=table, stale=stale, detail=f"{detail}; stdev {statistics.pstdev(values[-60:]):.2f}"
                   + (f" ({why})" if stale else ""))


def _rv_percentile(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    """20-session realized vol of the bar series, percentile of that RV over the available history."""
    cfg = ctx.policy["normalization"]["percentile"]
    trend = ctx.policy["normalization"]["weekly"]
    closes = _closes(ctx.bundle, str(spec["symbol"]))
    n = int(trend["rv_sessions"])
    if len(closes) < n + 2:
        return _result(spec, source="", table=table, refused_reason=f"only {len(closes)} bars")
    daily = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    rv: list[float] = []
    for end in range(n, len(daily) + 1):
        rv.append(statistics.pstdev(daily[end - n : end]) * math.sqrt(252) * 100.0)
    s, pct, detail = nz.percentile_state(rv, cfg)
    bars = _bars(ctx.bundle, str(spec["symbol"]))
    as_of = str(bars[-1].get("as_of") or bars[-1]["date"]) if bars else None
    stale, why = _stale(as_of, ctx.now, pmod.category(ctx.policy, "volatility")["max_age_sessions"], ctx.policy)
    if s is None:
        return _result(spec, source=str(bars[-1].get("source") if bars else ""), table=table, as_of=as_of,
                       stale=stale, refused_reason=detail)
    return _result(spec, raw=round(rv[-1], 3), normalized=round(s, 4), as_of=as_of,
                   source=str(bars[-1].get("source") or ""), table=table, stale=stale,
                   detail=f"RV20 {rv[-1]:.1f} at the {pct * 100:.0f}th pct" + (f" ({why})" if stale else ""))


def _term_structure(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["vol"]
    reg = ctx.bundle.regime or {}
    banned = {str(b).lower() for b in ctx.policy["sources"]["banned_feeds"]}
    vix_row = reg.get("vix_close")
    if not vix_row or str(vix_row.get("feed", "")).lower() in banned:
        vix_row = None
    for key in ("vix9d_close", "vix3m_close"):
        row = reg.get(key)
        if row and str(row.get("feed", "")).lower() in banned:
            return _result(
                spec, source=str(row.get("feed")), table=table, as_of=row.get("as_of"),
                refused_reason=f"{key} is {row.get('feed')!r} — banned feed, never scored (§1.14)",
            )
    vix = ctx.vix_value if ctx.vix_value is not None else (vix_row.get("value") if vix_row else None)
    v9 = (reg.get("vix9d_close") or {}).get("value")
    v3 = (reg.get("vix3m_close") or {}).get("value")
    s, detail = nz.term_structure_state(
        _num(vix), _num(v9), _num(v3), None, cfg
    )
    as_of = (reg.get("vix9d_close") or {}).get("as_of") or (vix_row or {}).get("as_of")
    if s is None:
        return _result(spec, source="market_regime_indicators", table=table, as_of=as_of, refused_reason=detail)
    return _result(spec, raw=round(float(s), 4), normalized=round(s, 4), as_of=as_of,
                   source="market_regime_indicators", table=table, detail=detail)


def _mre_state(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["regimes"]
    mre = ctx.bundle.mre
    if not mre:
        return _result(spec, source="market_risk/latest.json", table=table, refused_reason="MRE snapshot unreadable")
    as_of = str(mre.get("as_of") or mre.get("evaluated_at") or "")
    if _as_instant(as_of) is not None:
        hours = sessions_shim.market_hours_between(_as_instant(as_of), ctx.now, reopen=_reopen(ctx.policy))
        if hours > float(cfg["mre_max_age_hours"]):
            return _result(spec, source="MRE", table=table, as_of=as_of,
                           refused_reason=f"MRE snapshot {hours:.1f} market hours old (max {cfg['mre_max_age_hours']})")
    obs = {str(o.get("category")): o for o in (mre.get("observations") or []) if isinstance(o, dict)}
    o = obs.get(str(spec["mre_category"]))
    if not o:
        return _result(spec, source="MRE", table=table, as_of=as_of,
                       refused_reason=f"MRE has no {spec['mre_category']!r} observation")
    mapped = (cfg["mre_state_map"] or {}).get(str(o.get("state")))
    raw = o.get("score")
    if mapped is None:
        return _result(spec, raw=raw, source=f"MRE:{o.get('category')}", table=table, as_of=o.get("observed_at"),
                       refused_reason=f"MRE state {o.get('state')!r} has no outlook mapping")
    return _result(spec, raw=raw, normalized=float(mapped), as_of=str(o.get("observed_at") or as_of),
                   source=f"MRE:{o.get('category')}", table=table,
                   detail=f"MRE {o.get('category')} {o.get('state')} score {raw}")


def _breadth_field(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["breadth"]
    snap = ctx.bundle.snapshots
    if not snap:
        return _result(spec, source="", table=table, refused_reason="no ticker_snapshot_daily row")
    field_name = str(spec["field"])
    if snap.get(field_name) is None:
        return _result(spec, source="finviz", table=table, as_of=snap.get("date"),
                       refused_reason=f"snapshot has no {field_name}")
    pct = float(snap[field_name])
    s, detail = nz.breadth_pct_state(pct, cfg)
    return _result(spec, raw=round(pct, 2), normalized=round(s, 4), as_of=str(snap.get("as_of") or snap.get("date")),
                   source="finviz", table=table, detail=f"{detail} of {snap.get('n')} symbols")


def _breadth_high_low(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["breadth"]
    m = ctx.bundle.movers
    if not m:
        return _result(spec, source="", table=table, refused_reason="no market_movers batch")
    s, detail = nz.high_low_state(int(m.get("new_high") or 0), int(m.get("new_low") or 0), cfg)
    return _result(spec, raw={"new_high": m.get("new_high"), "new_low": m.get("new_low")},
                   normalized=None if s is None else round(s, 4), as_of=str(m.get("as_of") or ""),
                   source="finviz", table=table, detail=detail,
                   refused_reason=None if s is not None else detail)


def _mcclellan(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["breadth"]
    rows = ctx.bundle.sector_states or []
    vals = [r.get("breadth_pct") for r in rows if r.get("breadth_pct") is not None and not str(r.get("etf", "")).startswith("STYLE")]
    s, detail = nz.mcclellan_state(vals, cfg)
    as_of = str(rows[0].get("as_of")) if rows else None
    if not vals and rows:
        detail = "sector_momentum_state has no sector breadth_pct readings (STYLE rows only)"
    return _result(spec, raw=round(sum(vals) / len(vals), 2) if vals else None,
                   normalized=None if s is None else round(s, 4), as_of=as_of, source="sector_momentum_state",
                   table=table, detail=detail, refused_reason=None if s is not None else detail)


def _leadership_persistence(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    rs = ctx.bundle.sector_rs or {}
    dates = list(rs.get("dates") or [])
    window = int(spec.get("window_sessions") or 20)
    if len(dates) < window + 1:
        return _result(spec, source="", table=table,
                       refused_reason=f"{len(dates)} sector-RS dates, needs {window + 1}")
    now_d, then_d = dates[-1], dates[-1 - window]
    by_date = rs.get("by_date") or {}
    now_rank = _rank(by_date.get(now_d) or {})
    then_rank = _rank(by_date.get(then_d) or {})
    top_now = {s for s, r in now_rank.items() if r <= 3}
    top_then = {s for s, r in then_rank.items() if r <= 3}
    common = top_now | top_then
    if not common:
        return _result(spec, source="", table=table, as_of=now_d, refused_reason="no sector ranks")
    kept = len(top_now & top_then) / len(common)
    s = nz.clip(2.0 * kept - 1.0)
    return _result(spec, raw=round(kept, 3), normalized=round(s, 4), as_of=now_d, source="sector_rs_daily",
                   table=table, detail=f"{len(top_now & top_then)} of the prior top-3 still lead ({kept * 100:.0f}%), 20 sessions")


def _rank(values: dict[str, float]) -> dict[str, int]:
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    return {sym: i + 1 for i, (sym, _) in enumerate(ordered)}


_STATE_MAP = {"LEADING": 1.0, "IMPROVING": 0.5, "WEAKENING": -0.5, "LAGGING": -1.0}


def _momentum_states(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    rows = list(ctx.bundle.sector_states or [])
    if rows and all(str(r.get("etf", "")).startswith("STYLE") for r in rows):
        return _result(spec, source="sector_momentum_state", table=table,
                       refused_reason="sector_momentum_state holds only STYLE rows; the 11-sector writer has not run")
    rows = [r for r in rows if not str(r.get("etf", "")).startswith("STYLE")]
    vals = [_STATE_MAP.get(str(r.get("state")).upper()) for r in rows if str(r.get("state")).upper() in _STATE_MAP]
    if not vals:
        return _result(spec, source="", table=table, refused_reason="no sector momentum states")
    s = nz.clip(sum(vals) / len(vals))
    return _result(spec, raw={"leading": sum(1 for v in vals if v > 0.75), "lagging": sum(1 for v in vals if v < -0.75)},
                   normalized=round(s, 4), as_of=str(rows[0].get("as_of")), source="sector_momentum_state",
                   table=table, detail=f"mean state {s:+.2f} over {len(vals)} sectors")


def _style_state(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    etf = str(spec["etf"])
    row = next((r for r in (ctx.bundle.sector_states or []) if str(r.get("etf")) == etf), None)
    if not row:
        return _result(spec, source="", table=table, refused_reason=f"no {etf} row in sector_momentum_state")
    state = str(row.get("state") or "").upper()
    s = _STATE_MAP.get(state)
    if s is None:
        return _result(spec, source="sector_momentum_state", table=table, as_of=row.get("as_of"),
                       refused_reason=f"{etf} state {state!r} has no mapping")
    return _result(spec, raw=state, normalized=s, as_of=str(row.get("as_of")), source="sector_momentum_state",
                   table=table, detail=f"{etf} {state}")


def _ratio_z(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["z"]
    series = str(spec["fred_series"])
    rows = list((ctx.bundle.fred or {}).get(series) or [])
    values = [float(r["value"]) for r in rows]
    s, detail = nz.z_state(values, cfg, invert=bool(spec.get("invert")))
    as_of = str(rows[-1]["date"]) if rows else None
    cat = ctx.policy["sources"]
    max_age = _category_max_age(ctx, spec)
    stale, why = _stale(as_of, ctx.now, max_age, ctx.policy)
    if s is None:
        return _result(spec, source=f"fred:{series}", table=table, as_of=as_of, stale=stale, refused_reason=detail)
    return _result(spec, raw=round(values[-1], 4), normalized=round(s, 4), as_of=as_of, source=f"fred:{series}",
                   table=table, stale=stale, detail=detail + (f" ({why})" if stale else ""))


def _category_max_age(ctx: BuildContext, spec: dict[str, Any]) -> Any:
    for cat in ctx.policy["categories"]:
        if any(i["key"] == spec["key"] for i in cat["indicators"]):
            return cat.get("max_age", cat.get("max_age_sessions", 5))
    return 5


def _ratio_bars(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["z"]
    num, den = str(spec["numerator"]), str(spec["denominator"])
    a, b = _bars(ctx.bundle, num), _bars(ctx.bundle, den)
    if not a or not b:
        return _result(spec, source="", table=table,
                       refused_reason=f"missing daily bars for {num if not a else ''}{den if not b else ''}".strip())
    bmap = {str(r["date"]): float(r["close"]) for r in b}
    ratio = [float(r["close"]) / bmap[str(r["date"])] for r in a if str(r["date"]) in bmap and bmap[str(r["date"])]]
    s, detail = nz.z_state(ratio, cfg)
    last = a[-1]
    if s is None:
        return _result(spec, source=_basis_of(a), table=table, as_of=str(last["date"]), refused_reason=detail)
    return _result(spec, raw=round(ratio[-1], 5), normalized=round(s, 4), as_of=str(last["date"]),
                   source=_basis_of(a), table=table, detail=f"{num}/{den} {detail}")


def _rates_bp(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["rates"]
    series = str(spec["fred_series"])
    rows = list((ctx.bundle.fred or {}).get(series) or [])
    values = [float(r["value"]) for r in rows]
    s, detail = nz.rates_bp_state(values, cfg)
    as_of = str(rows[-1]["date"]) if rows else None
    stale, why = _stale(as_of, ctx.now, _category_max_age(ctx, spec), ctx.policy)
    if s is None:
        return _result(spec, source=f"fred:{series}", table=table, as_of=as_of, stale=stale, refused_reason=detail)
    return _result(spec, raw=round(values[-1], 4), normalized=round(s, 4), as_of=as_of, source=f"fred:{series}",
                   table=table, stale=stale, detail=detail + (f" ({why})" if stale else ""))


def _dollar_pct(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["dollar"]
    if spec.get("fred_series"):
        rows = list((ctx.bundle.fred or {}).get(str(spec["fred_series"])) or [])
        values = [float(r["value"]) for r in rows]
        as_of = str(rows[-1]["date"]) if rows else None
        source = f"fred:{spec['fred_series']}"
    else:
        bars = _bars(ctx.bundle, str(spec["etf_symbol"]))
        values = [float(r["close"]) for r in bars]
        as_of = str(bars[-1].get("as_of") or bars[-1]["date"]) if bars else None
        source = _basis_of(bars)
    s, detail = nz.dollar_pct_state(values, cfg)
    stale, why = _stale(as_of, ctx.now, _category_max_age(ctx, spec), ctx.policy)
    if s is None:
        return _result(spec, source=source, table=table, as_of=as_of, stale=stale, refused_reason=detail)
    return _result(spec, raw=round(values[-1], 4), normalized=round(s, 4), as_of=as_of, source=source,
                   table=table, stale=stale, detail=detail + (f" ({why})" if stale else ""))


def _event_tilt(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["events"]
    if ctx.tilt is None:
        return _result(spec, source="macro calendar", table=table, refused_reason=ctx.tilt_detail or "no calendar")
    s, detail = nz.event_tilt_state(float(ctx.tilt), cfg)
    return _result(spec, raw=round(float(ctx.tilt), 3), normalized=round(s, 4), as_of=ctx.now.isoformat(),
                   source="macro_calendar", table=table, detail=f"{ctx.tilt_detail}; {detail}")


def _event_surprise(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    if ctx.surprise is None:
        return _result(spec, source="", table=table, refused_reason=ctx.surprise_detail or "no reaction proxy available")
    return _result(spec, raw=round(float(ctx.surprise), 4), normalized=round(float(ctx.surprise), 4),
                   as_of=ctx.now.isoformat(), source="market_quotes_extended", table=table,
                   detail=ctx.surprise_detail)


def _positioning_pc(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["positioning"]
    symbols = [str(s) for s in spec.get("symbols") or []]
    signals: list[float] = []
    details: list[str] = []
    contrarian = False
    as_of = None
    used: list[str] = []
    for sym in symbols:
        rows = list((ctx.bundle.options or {}).get(sym) or [])
        ratios = [r.get("pc_vol_ratio") for r in rows if r.get("pc_vol_ratio") is not None]
        if not ratios:
            continue
        s, detail, flip = nz.positioning_state(float(ratios[-1]), [float(x) for x in ratios[:-1]], ctx.vix_pct, cfg)
        if s is None:
            details.append(f"{sym}: {detail}")
            continue
        signals.append(s)
        details.append(f"{sym}: {detail}")
        contrarian = contrarian or flip
        as_of = str(rows[-1].get("as_of"))
        used.append(sym)
    if not signals:
        return _result(spec, source="option_chain_snapshots", table=table, as_of=as_of,
                       refused_reason="; ".join(details) or "no put/call rows")
    s = sum(signals) / len(signals)
    return _result(spec, raw=None, normalized=round(s, 4), as_of=as_of, source="option_chain_snapshots",
                   table=table, detail="; ".join(details) + (" [contrarian]" if contrarian else ""))


def _mover_skew(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    cfg = ctx.policy["normalization"]["positioning"]
    m = ctx.bundle.movers
    if not m:
        return _result(spec, source="", table=table, refused_reason="no market_movers batch")
    s, detail = nz.mover_skew_state(m.get("gainers_mean_change"), m.get("losers_mean_change"), cfg)
    return _result(spec, raw={"gainers": m.get("gainers_mean_change"), "losers": m.get("losers_mean_change")},
                   normalized=None if s is None else round(s, 4), as_of=str(m.get("as_of") or ""),
                   source="finviz", table=table, detail=detail, refused_reason=None if s is not None else detail)


def _unavailable(spec: dict[str, Any], ctx: BuildContext, table: str) -> IndicatorResult:
    return _result(spec, source="", table=table, refused_reason=str(spec.get("reason") or "no source"))


BUILDERS: dict[str, Builder] = {
    "trend": _trend,
    "futures": _futures,
    "vol_percentile": _vol_percentile_fred,
    "vol_percentile_bars": _rv_percentile,
    "term_structure": _term_structure,
    "mre_state": _mre_state,
    "breadth_pct": _breadth_field,
    "breadth_high_low": _breadth_high_low,
    "breadth_mcclellan": _mcclellan,
    "leadership_persistence": _leadership_persistence,
    "momentum_states": _momentum_states,
    "style_state": _style_state,
    "ratio_z": _ratio_z,
    "ratio_bars": _ratio_bars,
    "rates_bp": _rates_bp,
    "dollar_pct": _dollar_pct,
    "event_tilt": _event_tilt,
    "event_surprise": _event_surprise,
    "positioning_pc": _positioning_pc,
    "mover_skew": _mover_skew,
    "unavailable_source": _unavailable,
}

TABLE_BY_TYPE = {
    "trend": "market_ohlcv_bars",
    "futures": "market_quotes_extended",
    "vol_percentile": "fred_economic_series",
    "vol_percentile_bars": "market_ohlcv_bars",
    "term_structure": "market_regime_indicators",
    "mre_state": "market_risk/latest.json",
    "breadth_pct": "ticker_snapshot_daily",
    "breadth_high_low": "market_movers",
    "breadth_mcclellan": "sector_momentum_state",
    "leadership_persistence": "sector_rs_daily",
    "momentum_states": "sector_momentum_state",
    "style_state": "sector_momentum_state",
    "ratio_z": "fred_economic_series",
    "ratio_bars": "market_ohlcv_bars",
    "rates_bp": "fred_economic_series",
    "dollar_pct": "fred_economic_series",
    "event_tilt": "macro_calendar",
    "event_surprise": "market_quotes_extended",
    "positioning_pc": "option_chain_snapshots",
    "mover_skew": "market_movers",
    "unavailable_source": "",
}


def build_categories(ctx: BuildContext, *, weight_effective: dict[str, float] | None = None) -> list[CategoryResult]:
    """Every category of the policy, in order. ``weight_effective`` carries the regime multipliers (§2.4)."""
    out: list[CategoryResult] = []
    for cat in ctx.policy["categories"]:
        results: list[IndicatorResult] = []
        max_age = cat.get("max_age", cat.get("max_age_sessions", 5))
        for spec in cat["indicators"]:
            builder = BUILDERS.get(str(spec["type"]))
            if builder is None:
                results.append(_result(spec, refused_reason=f"unknown indicator type {spec['type']!r}"))
                continue
            r = builder(spec, ctx, TABLE_BY_TYPE.get(str(spec["type"]), ""))
            if r.normalized is not None and r.refused_reason is None:
                # daily series staleness is stated once per indicator, in the category's own units
                r.stale, why = _stale(r.as_of, ctx.now, max_age, ctx.policy)
                if r.stale:
                    r.refused_reason = f"stale: {why}"
            results.append(r)
        available = [r for r in results if r.available]
        total_w = sum(r.weight for r in results) or 1.0
        cov = sum(r.weight for r in available) / total_w
        min_cov = float(cat["min_coverage"])
        weight_eff = float((weight_effective or {}).get(cat["key"], cat["weight"]))
        if not available or cov < min_cov:
            reasons = _unknown_reasons(results, cov, min_cov)
            out.append(
                CategoryResult(
                    key=cat["key"], title=cat["title"], weight_prior=float(cat["weight"]),
                    weight_effective=weight_eff, subscore=None, coverage=cov, state="UNKNOWN",
                    indicators=results, reason_unknown=reasons,
                    basis=cat.get("basis"), note=str(cat.get("note") or ""),
                )
            )
            continue
        sub = sum(r.weight * float(r.normalized) for r in available) / sum(r.weight for r in available)
        state = "COLLECTED" if cov >= 0.999 else "PARTIAL"
        out.append(
            CategoryResult(
                key=cat["key"], title=cat["title"], weight_prior=float(cat["weight"]),
                weight_effective=weight_eff, subscore=sub, coverage=cov, state=state,
                indicators=results, basis=cat.get("basis"), note=str(cat.get("note") or ""),
            )
        )
    return out


def _unknown_reasons(results: list[IndicatorResult], cov: float, min_cov: float) -> str:
    parts = [f"coverage {cov:.2f} < {min_cov:.2f}"]
    for r in results:
        if r.available:
            continue
        why = r.refused_reason or ("stale" if r.stale else "not measured")
        parts.append(f"{r.key}: {why}")
    return "; ".join(parts)


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


__all__ = [
    "IndicatorResult",
    "CategoryResult",
    "BuildContext",
    "build_categories",
    "freshness_weight",
]

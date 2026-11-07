"""market_event_rank — universe, prices and scores for market-event re-entry candidates (LQ-20261107-332, WP2).

Spec: persistent-state/handoffs/SPEC_MARKET_EVENT_REENTRY_20261107.md §4.2. Advisory only: this module reads and
scores; it never sizes, orders or touches a broker. Deterministic: no LLM anywhere. Every threshold and weight comes
from config/market_event_policy.json (``load_policy``).

Pure functions (tested on synthetic fixtures): ``split_suspect``, ``factor_value``, ``quality_score``,
``discount_score``, ``group_for``, ``fell_for_reason``, ``rank_candidates``, ``score_candidates``.

DB readers (read-only SELECTs; the caller owns the connection): ``session_closes``, ``last_prices``,
``load_fundamentals``, ``load_universe``, ``load_catalysts``, ``build_candidates``.

Prices come from market_quotes rows of the allowed sources only (alpaca, finviz; never yfinance). The close of
session d is the prev_close on the first allowed quote of the next session; if that session has not happened, the
first allowed quote at or after 16:00 ET on d.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "market_event_policy.json"
ET = ZoneInfo("America/New_York")
SOURCES = ("holding", "stop_out", "watchlist", "sector_peer")


# ---------------------------------------------------------------------------------------------- policy + calendar
def load_policy(path: Path | str | None = None) -> dict:
    return json.loads(Path(path or POLICY_PATH).read_text())


def is_trading_day(d: date) -> bool:
    try:
        from lib.cio_market_calendar import is_us_trading_day
        return bool(is_us_trading_day(d))
    except Exception:  # calendar backend missing: weekdays only (named fallback, holidays not excluded)
        return d.weekday() < 5


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not is_trading_day(n):
        n += timedelta(days=1)
    return n


def prev_trading_day(d: date) -> date:
    p = d - timedelta(days=1)
    while not is_trading_day(p):
        p -= timedelta(days=1)
    return p


def last_completed_session(now: datetime, close_et: str = "16:00") -> date:
    """The latest session whose close is at or before ``now``."""
    local = now.astimezone(ET)
    hh, mm = (int(x) for x in close_et.split(":"))
    d = local.date()
    if is_trading_day(d) and local.time() >= time(hh, mm):
        return d
    return prev_trading_day(d)


def _et(d: date, hhmm: str) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(hh, mm), tzinfo=ET)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------------------------------- pure scoring
def split_suspect(baseline: float | None, last: float | None, guard: Mapping[str, Any]) -> bool:
    """True when the move is large and the price ratio sits near a split ratio (either direction)."""
    if not baseline or not last or baseline <= 0 or last <= 0:
        return False
    move = abs(last / baseline - 1.0) * 100.0
    if move < float(guard.get("min_abs_move_pct", 40.0)):
        return False
    ratio = max(baseline, last) / min(baseline, last)
    tol = float(guard.get("ratio_tolerance_pct", 15.0)) / 100.0
    return any(abs(ratio / float(k) - 1.0) <= tol for k in guard.get("ratios", []))


def factor_value(x: float | None, good: float, bad: float) -> float | None:
    """Linear map: bad -> 0, good -> 1, clamped. None stays None (absent is not negative)."""
    if x is None or good == bad:
        return None
    v = (x - bad) / (good - bad)
    return max(0.0, min(1.0, v))


def quality_inputs(fund: Mapping[str, Any], sector_median_fpe: float | None, orders_growth_pct: float | None) -> dict:
    """Raw factor inputs from a snapshot row. A factor that cannot be computed is None."""
    fpe = _num(fund.get("forward_pe"))
    pe = _num(fund.get("pe"))
    out: dict[str, float | None] = {
        "fpe_vs_trailing": (fpe / pe) if fpe and pe and fpe > 0 and pe > 0 else None,
        "fpe_vs_sector_median": (fpe / sector_median_fpe) if fpe and fpe > 0 and sector_median_fpe else None,
        "peg": (lambda p: p if p is not None and p > 0 else None)(_num(fund.get("peg"))),
        "roic_pct": _num(fund.get("roic_pct")),
        "oper_margin_pct": _num(fund.get("oper_margin_pct")),
        "total_debt_equity": _num(fund.get("total_debt_equity")),
        "analyst_recom": _num(fund.get("analyst_recom")),
        "inst_trans_pct": _num(fund.get("inst_trans_pct")),
        "insider_trans_pct": _num(fund.get("insider_trans_pct")),
        "orders_backlog": orders_growth_pct,
    }
    return out


def quality_score(inputs: Mapping[str, float | None], factors_cfg: Mapping[str, Any]) -> tuple[float | None, float, dict]:
    """(score 0-100 or None, coverage 0-1, per-factor detail). Absent factors drop out and weights renormalise."""
    total_w = present_w = acc = 0.0
    detail: dict[str, Any] = {}
    for name, spec in factors_cfg.items():
        if name.startswith("_"):
            continue
        w = float(spec["weight"])
        total_w += w
        v = factor_value(inputs.get(name), float(spec["good"]), float(spec["bad"]))
        detail[name] = {"input": inputs.get(name), "value": None if v is None else round(v, 4)}
        if v is not None:
            present_w += w
            acc += w * v
    coverage = present_w / total_w if total_w else 0.0
    score = round(100.0 * acc / present_w, 2) if present_w else None
    return score, round(coverage, 4), detail


def discount_score(drawdown_pct: float, beta: float | None, bench_drawdown_pct: float, cfg: Mapping[str, Any]) -> tuple[float, dict]:
    """Discount = how much further the name fell than beta x benchmark implies, scaled to 0-100."""
    b = beta if beta is not None else float(cfg.get("default_beta", 1.0))
    b = max(float(cfg.get("beta_floor", 0.3)), min(float(cfg.get("beta_cap", 3.0)), b))
    expected = b * bench_drawdown_pct
    excess = drawdown_pct - expected  # negative = fell more than expected
    full = float(cfg.get("full_scale_pct", 20.0))
    score = max(0.0, min(1.0, -excess / full)) * 100.0
    return round(score, 2), {"beta_used": round(b, 3), "expected_drawdown_pct": round(expected, 3),
                             "excess_drawdown_pct": round(excess, 3)}


def group_for(fund: Mapping[str, Any], symbol: str, group_cfg: Mapping[str, Any], mre_groups: Mapping[str, Any]) -> str | None:
    """The first configured MRE group key (most specific first) that matches the symbol's sector/industry."""
    sector = fund.get("sector")
    industry = fund.get("industry")
    for key in group_cfg.get("order", []):
        spec = group_cfg["groups"].get(key) or {}
        if spec.get("from_mre_symbols"):
            if symbol in set((mre_groups.get(key) or {}).get("symbols") or []):
                return key
            continue
        if industry and industry in spec.get("industries", []):
            return key
        if sector and sector in spec.get("sectors", []):
            return key
    return None


def fell_for_reason(symbol: str, catalysts: Iterable[Mapping[str, Any]], excess_drawdown_pct: float | None,
                    cfg: Mapping[str, Any]) -> tuple[bool, list[dict]]:
    """A name with its own negative catalyst in the window, or an earnings reaction beyond the threshold."""
    neg = set(cfg.get("negative_catalyst_types", []))
    hits = [dict(c) for c in catalysts if c.get("catalyst_type") in neg]
    er = cfg.get("earnings_reaction") or {}
    if er.get("enabled") and excess_drawdown_pct is not None:
        earn = [dict(c) for c in catalysts if str(c.get("catalyst_type") or "").startswith("earnings")]
        if earn and excess_drawdown_pct <= -float(er.get("min_excess_drawdown_pct", 8.0)):
            hits.extend({**c, "why": "earnings_reaction"} for c in earn if c not in hits)
    return bool(hits), hits


def rank_candidates(cands: list[dict], weights: Mapping[str, float]) -> list[dict]:
    """Clean names first by combined score, then fell_for_reason names; ties by symbol. Sets rank and rank_group."""
    wq, wd = float(weights.get("quality", 0.6)), float(weights.get("discount", 0.4))
    for c in cands:
        q = c.get("quality_score")
        c["combined_score"] = round(wq * (q if q is not None else 0.0) + wd * float(c.get("discount_score") or 0.0), 3)
    ordered = sorted(cands, key=lambda c: (bool(c.get("fell_for_reason")), -c["combined_score"], c["symbol"]))
    for i, c in enumerate(ordered, 1):
        c["rank"] = i
        c["reason_evidence"]["rank_group"] = "fell_for_reason" if c.get("fell_for_reason") else "clean"
    return ordered


def sector_medians(funds: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    """Median positive forward P/E per industry and per sector (keys 'industry:<x>' / 'sector:<x>')."""
    buckets: dict[str, list[float]] = {}
    for f in funds.values():
        fpe = _num(f.get("forward_pe"))
        if not fpe or fpe <= 0:
            continue
        for k in (f"industry:{f.get('industry')}", f"sector:{f.get('sector')}"):
            buckets.setdefault(k, []).append(fpe)
    return {k: statistics.median(v) for k, v in buckets.items() if len(v) >= 3}


def passes_peer_floor(fund: Mapping[str, Any], price: float | None, cfg: Mapping[str, Any]) -> bool:
    mcap = _num(fund.get("market_cap_usd"))
    fpe = _num(fund.get("forward_pe"))
    roic = _num(fund.get("roic_pct"))
    om = _num(fund.get("oper_margin_pct"))
    de = _num(fund.get("total_debt_equity"))
    vol_k = _num(fund.get("avg_vol_m"))
    if mcap is None or mcap < float(cfg.get("min_market_cap_usd", 0)):
        return False
    if cfg.get("require_forward_pe_positive") and not (fpe and fpe > 0):
        return False
    if roic is None or roic < float(cfg.get("min_roic_pct", -1e9)):
        return False
    if om is None or om < float(cfg.get("min_oper_margin_pct", -1e9)):
        return False
    if de is not None and de > float(cfg.get("max_total_debt_equity", 1e9)):
        return False
    if price is None or price < float(cfg.get("min_price_usd", 0)):
        return False
    if vol_k is None or vol_k * 1000.0 * price < float(cfg.get("min_dollar_volume_usd", 0)):
        return False
    return True


def score_candidates(*, universe: Mapping[str, set], baseline: Mapping[str, float], last: Mapping[str, float],
                     funds: Mapping[str, Mapping[str, Any]], catalysts: Mapping[str, list],
                     orders: Mapping[str, float], bench_drawdown_pct: float, mre_groups: Mapping[str, Any],
                     affected_groups: Iterable[str], policy: Mapping[str, Any]) -> tuple[list[dict], dict]:
    """Pure core: score every universe symbol that has prices; cap sector peers; rank. Returns (ranked, excluded)."""
    rk = policy["ranking"]
    guard = policy["data"]["split_guard"]
    gcfg = policy["universe"]["group_map"]
    peer_cfg = policy["universe"]["sector_peers"]
    medians = sector_medians(funds)
    affected = set(affected_groups)
    excluded: dict[str, int] = {}
    excluded_symbols: dict[str, list[str]] = {}

    def drop(sym: str, why: str) -> None:
        excluded[why] = excluded.get(why, 0) + 1
        excluded_symbols.setdefault(why, []).append(sym)

    cands: list[dict] = []
    for sym in sorted(universe):
        srcs = set(universe[sym])
        b, l = baseline.get(sym), last.get(sym)
        if not b or not l:
            drop(sym, "no_price")
            continue
        if split_suspect(b, l, guard):
            drop(sym, "split_suspect")
            continue
        dd = (l / b - 1.0) * 100.0
        fund = funds.get(sym) or {}
        group = group_for(fund, sym, gcfg, mre_groups)
        if srcs == {"sector_peer"}:
            if group not in affected or not passes_peer_floor(fund, b, peer_cfg):
                drop(sym, "peer_floor")
                continue
        if dd > -float(rk.get("min_drawdown_pct", 0.0)):
            drop(sym, "drawdown_below_min")
            continue
        med = medians.get(f"industry:{fund.get('industry')}") or medians.get(f"sector:{fund.get('sector')}")
        q, cov, qdetail = quality_score(quality_inputs(fund, med, orders.get(sym)), rk["quality_factors"])
        d, ddetail = discount_score(dd, _num(fund.get("beta")), bench_drawdown_pct, rk["discount"])
        ffr, hits = fell_for_reason(sym, catalysts.get(sym, []), ddetail["excess_drawdown_pct"], rk["fell_for_reason"])
        cands.append({
            "symbol": sym,
            "source": sorted(srcs, key=SOURCES.index),
            "baseline_price": round(b, 4),
            "last_price": round(l, 4),
            "drawdown_pct": round(dd, 3),
            "quality_score": q,
            "discount_score": d,
            "fell_for_reason": ffr,
            "reason_evidence": {
                "sector": fund.get("sector"), "industry": fund.get("industry"), "group": group,
                "quality_coverage": cov, "low_coverage": cov < float(rk.get("min_quality_coverage", 0.0)),
                "quality_factors": qdetail, "discount": ddetail, "fpe_sector_median": med,
                "unexplained_excess_drop": (not ffr and ddetail["excess_drawdown_pct"] <=
                                            -float(rk["fell_for_reason"].get("unexplained_excess_drawdown_pct", 15.0))),
                "negative_catalysts": [{k: c.get(k) for k in ("catalyst_type", "headline", "published_at", "why")}
                                       for c in hits],
            },
            "gates": {},
            "state": "WATCH",
            "plan": None,
        })
    # cap pure sector peers per group after scoring (holdings / stop-outs / watchlist are never capped)
    cap = int(peer_cfg.get("per_group_cap", 8))
    by_group: dict[str, int] = {}
    kept = []
    wq, wd = float(rk["combined_weights"]["quality"]), float(rk["combined_weights"]["discount"])
    for c in sorted(cands, key=lambda c: (-(wq * (c["quality_score"] or 0) + wd * c["discount_score"]), c["symbol"])):
        if c["source"] == ["sector_peer"]:
            g = c["reason_evidence"]["group"] or "none"
            if by_group.get(g, 0) >= cap:
                drop(c["symbol"], "peer_cap")
                continue
            by_group[g] = by_group.get(g, 0) + 1
        kept.append(c)
    ranked = rank_candidates(kept, rk["combined_weights"])
    return ranked, {"counts": excluded, "symbols": {k: v[:50] for k, v in excluded_symbols.items()}}


# ------------------------------------------------------------------------------------------------- DB readers
def _rows(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def session_closes(conn, symbols: Iterable[str], day: date, policy: Mapping[str, Any]) -> dict[str, float]:
    """{symbol: close of session ``day``} from allowed market_quotes sources (see module doc)."""
    syms = sorted(set(symbols))
    if not syms:
        return {}
    data = policy["data"]
    srcs = list(data["quote_sources_allowed"])
    out: dict[str, float] = {}
    nd = next_trading_day(day)
    if _et(nd, data.get("premarket_from_et", "04:00")) <= datetime.now(timezone.utc):
        for sym, pc in _rows(conn, """
            SELECT DISTINCT ON (symbol) symbol, prev_close FROM market_quotes
             WHERE symbol = ANY(%s) AND source = ANY(%s) AND fetched_at >= %s AND fetched_at < %s
               AND prev_close IS NOT NULL AND prev_close > 0
             ORDER BY symbol, fetched_at ASC""",
                (syms, srcs, _et(nd, data.get("premarket_from_et", "04:00")), _et(nd, "20:00"))):
            out[sym] = float(pc)
    missing = [s for s in syms if s not in out]
    if missing:
        start = _et(day, data.get("close_time_et", "16:00"))
        end = start + timedelta(minutes=int(data.get("close_window_minutes", 30)) + 30)
        for sym, px in _rows(conn, """
            SELECT DISTINCT ON (symbol) symbol, price FROM market_quotes
             WHERE symbol = ANY(%s) AND source = ANY(%s) AND fetched_at >= %s AND fetched_at < %s
               AND price IS NOT NULL AND price > 0
             ORDER BY symbol, fetched_at ASC""", (missing, srcs, start, end)):
            out[sym] = float(px)
    return out


def last_prices(conn, symbols: Iterable[str], now: datetime, policy: Mapping[str, Any]) -> tuple[dict[str, float], str]:
    """In session: latest allowed quote. Outside: the close of the last completed session. Returns (prices, as_of)."""
    data = policy["data"]
    local = now.astimezone(ET)
    d = local.date()
    if is_trading_day(d) and _et(d, data.get("session_open_time_et", "09:30")) <= local < _et(d, data.get("close_time_et", "16:00")):
        syms = sorted(set(symbols))
        out = {s: float(p) for s, p in _rows(conn, """
            SELECT DISTINCT ON (symbol) symbol, price FROM market_quotes
             WHERE symbol = ANY(%s) AND source = ANY(%s) AND fetched_at >= %s AND price > 0
             ORDER BY symbol, fetched_at DESC""", (syms, list(data["quote_sources_allowed"]), _et(d, "04:00")))}
        return out, f"intraday:{d.isoformat()}"
    last = last_completed_session(now, data.get("close_time_et", "16:00"))
    return session_closes(conn, symbols, last, policy), f"close:{last.isoformat()}"


def load_fundamentals(conn, max_age_days: int, now: datetime) -> tuple[dict[str, dict], str | None]:
    """Latest ticker_snapshot_daily date (Finviz) within max_age_days: {symbol: data + beta + analyst_recom}."""
    row = _rows(conn, "SELECT max(snapshot_date) FROM ticker_snapshot_daily WHERE snapshot_date >= %s",
                ((now - timedelta(days=max_age_days)).date(),))
    snap = row[0][0] if row else None
    if snap is None:
        return {}, None
    out: dict[str, dict] = {}
    for sym, data, beta, recom in _rows(conn, """
        SELECT DISTINCT ON (symbol) symbol, data, beta, analyst_recom FROM ticker_snapshot_daily
         WHERE snapshot_date = %s ORDER BY symbol, source""", (snap,)):
        d = dict(data or {})
        b = _num(beta) if _num(beta) is not None else _num(d.get("beta"))
        d["beta"] = b
        # analyst_recom is a 1 (strong buy) .. 5 (sell) scale; the column also carries junk such as '-98.42%'
        r = next((x for x in (_num(recom), _num(d.get("analyst_recom"))) if x is not None and 1.0 <= x <= 5.0), None)
        d["analyst_recom"] = r
        out[sym] = d
    return out, snap.isoformat()


def load_universe(conn, policy: Mapping[str, Any], mre: Mapping[str, Any], now: datetime) -> dict[str, set]:
    """{symbol: {sources}} from holdings, stop-outs and watchlists. Sector peers are added by build_candidates."""
    u = policy["universe"]
    pat = re.compile(u["holdings"].get("symbol_pattern", r"^[A-Z][A-Z.\-]{0,6}$"))
    out: dict[str, set] = {}

    def add(sym: Any, src: str) -> None:
        s = str(sym or "").strip().upper()
        if s and pat.match(s):
            out.setdefault(s, set()).add(src)

    excl = [x.upper() for x in u["holdings"].get("exclude_asset_types", [])]
    for (sym,) in _rows(conn, """SELECT DISTINCT symbol FROM positions_current
                                  WHERE NOT coalesce(is_cash, false) AND coalesce(qty, 0) > 0
                                    AND upper(coalesce(asset_type, '')) <> ALL(%s)""", (excl,)):
        add(sym, "holding")
    since = now - timedelta(days=int(u["stop_outs"].get("lookback_days", 120)))
    for (sym,) in _rows(conn, "SELECT DISTINCT symbol FROM stopped_out_watch WHERE coalesce(is_active, false)"):
        add(sym, "stop_out")
    for (sym,) in _rows(conn, "SELECT DISTINCT symbol FROM recovery_cases WHERE left(exit_last_date, 10) >= %s", (since.date().isoformat(),)):
        add(sym, "stop_out")
    if u["stop_outs"].get("include_mre_reentry_watch"):
        for sym in (mre.get("reentry_watch") or {}):
            add(sym, "stop_out")
    for (sym,) in _rows(conn, "SELECT DISTINCT symbol FROM watchlist_items WHERE status = ANY(%s)",
                        (list(u["watchlist"].get("watchlist_items_status", ["active"])),)):
        add(sym, "watchlist")
    flags = [f for f in u["watchlist"].get("symbol_master_flags", []) if re.fullmatch(r"[a-z_]+", f)]
    if flags:
        cond = " OR ".join(f"coalesce({f}, false)" for f in flags)
        for (sym,) in _rows(conn, f"SELECT symbol FROM watchlist_symbol_master WHERE {cond}"):  # noqa: S608 (whitelisted names)
            add(sym, "watchlist")
    return out


def load_catalysts(conn, symbols: Iterable[str], since: datetime, types: Iterable[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    syms = sorted(set(symbols))
    if not syms:
        return out
    for sym, ctype, headline, published in _rows(conn, """
        SELECT symbol, catalyst_type, headline, published_at FROM catalyst_events
         WHERE symbol = ANY(%s) AND published_at >= %s AND catalyst_type = ANY(%s)
         ORDER BY symbol, published_at""", (syms, since, list(types))):
        out.setdefault(sym, []).append({"catalyst_type": ctype, "headline": (headline or "")[:200],
                                        "published_at": published.isoformat() if published else None})
    return out


def rpo_growth(rows: list[tuple[date, float]], tol_days: int = 45) -> float | None:
    """YoY growth % of remaining performance obligations from [(period_end, value)] newest first; None if unmatched."""
    if not rows:
        return None
    (p0, v0) = rows[0]
    for p, v in rows[1:]:
        if abs((p0 - p).days - 365) <= tol_days and v and v > 0:
            return round((v0 / v - 1.0) * 100.0, 3)
    return None


def load_rpo_growth(conn, symbols: Iterable[str], now: datetime, cfg: Mapping[str, Any]) -> dict[str, float]:
    """{symbol: RPO YoY growth %} from sec_xbrl; only symbols whose latest filing is within max_filing_age_days."""
    syms = sorted(set(symbols))
    if not syms:
        return {}
    by: dict[str, list[tuple[date, float]]] = {}
    latest_filed: dict[str, date] = {}
    for sym, val, pend, filed in _rows(conn, """
        SELECT symbol, metric_value, period_end, filing_date FROM sec_xbrl
         WHERE metric_name = %s AND symbol = ANY(%s) AND metric_value IS NOT NULL
         ORDER BY symbol, period_end DESC, filing_date DESC""", (cfg.get("metric_name", "remaining_performance_obligation"), syms)):
        lst = by.setdefault(sym, [])
        if lst and lst[-1][0] == pend:
            continue
        lst.append((pend, float(val)))
        latest_filed.setdefault(sym, filed)
    cutoff = (now - timedelta(days=int(cfg.get("max_filing_age_days", 150)))).date()
    out = {}
    for sym, rows in by.items():
        if latest_filed.get(sym) and latest_filed[sym] >= cutoff:
            g = rpo_growth(rows, int(cfg.get("yoy_tolerance_days", 45)))
            if g is not None:
                out[sym] = g
    return out


def peer_symbols(funds: Mapping[str, Mapping[str, Any]], affected: Iterable[str], policy: Mapping[str, Any],
                 mre_groups: Mapping[str, Any]) -> set[str]:
    """Snapshot symbols in the affected groups that pass the price-free part of the peer floor."""
    gcfg = policy["universe"]["group_map"]
    cfg = policy["universe"]["sector_peers"]
    aff = set(affected)
    out = set()
    for sym, f in funds.items():
        if group_for(f, sym, gcfg, mre_groups) not in aff:
            continue
        if passes_peer_floor(f, 1e9, {**cfg, "min_price_usd": 0, "min_dollar_volume_usd": 0}):
            out.add(sym)
    return out


def build_candidates(conn, episode: Mapping[str, Any], mre: Mapping[str, Any], policy: Mapping[str, Any],
                     now: datetime) -> dict:
    """Read everything for one episode and score it. Returns {candidates, excluded, inputs}."""
    rk = policy["ranking"]
    mre_groups = {g.get("key"): g for g in ((mre.get("sectors") or {}).get("groups") or [])}
    affected = list(episode.get("affected_sectors") or [])
    funds, snap_date = load_fundamentals(conn, int(policy["data"].get("snapshot_max_age_days", 10)), now)
    universe = load_universe(conn, policy, mre, now)
    if episode.get("kind") == "single_name_shock":
        universe = {episode["scope"]: universe.get(episode["scope"], {"holding"})}
    elif policy["universe"]["sector_peers"].get("enabled"):
        for sym in peer_symbols(funds, affected, policy, mre_groups):
            universe.setdefault(sym, set()).add("sector_peer")
    bench = policy["detector"]["benchmark_symbol"]
    baseline_day = episode["baseline_date"]
    if isinstance(baseline_day, str):
        baseline_day = date.fromisoformat(baseline_day)
    syms = set(universe) | {bench}
    baseline = session_closes(conn, syms, baseline_day, policy)
    last, last_as_of = last_prices(conn, syms, now, policy)
    if not baseline.get(bench) or not last.get(bench):
        return {"candidates": [], "excluded": {"counts": {"no_benchmark_price": 1}, "symbols": {}},
                "inputs": {"benchmark": bench, "error": "benchmark price missing"}}
    bench_dd = (last[bench] / baseline[bench] - 1.0) * 100.0
    if universe.get(bench) == {"sector_peer"}:
        universe.pop(bench)
    ffr = rk["fell_for_reason"]
    cat_since = datetime.combine(baseline_day - timedelta(days=int(ffr.get("window_pre_days", 3))), time(0), tzinfo=ET)
    catalysts = load_catalysts(conn, universe, cat_since, list(ffr["negative_catalyst_types"]) +
                               ["earnings", "earnings_miss", "earnings_beat", "earnings_report"])
    orders = load_rpo_growth(conn, universe, now, rk["orders_backlog"])
    ranked, excluded = score_candidates(universe=universe, baseline=baseline, last=last, funds=funds,
                                        catalysts=catalysts, orders=orders, bench_drawdown_pct=bench_dd,
                                        mre_groups=mre_groups, affected_groups=affected, policy=policy)
    return {"candidates": ranked, "excluded": excluded,
            "inputs": {"benchmark": bench, "benchmark_drawdown_pct": round(bench_dd, 3),
                       "baseline_date": baseline_day.isoformat(), "last_as_of": last_as_of,
                       "fundamentals_snapshot_date": snap_date, "universe_size": len(universe),
                       "universe_by_source": {s: sum(1 for v in universe.values() if s in v) for s in SOURCES}}}

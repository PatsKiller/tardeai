"""Fund-aware prospectus inputs: category → sector ETF + peer funds, a fund profile, house scenario ranges and a
measured macro-sensitivity "effect" column.

Operator 2026-10-26 (XAR): "it's missing some data towards the bottom". For an ETF the vendor fields say
"Financial / Exchange Traded Fund", so the sector benchmark became XLF, the scenarios were empty (no analyst targets
for a fund) and the macro "effect" column was blank. This module fixes those gaps from house data only:

* **Category** — ``config/prospectus_etf_categories.json``: a pinned symbol, else the first category whose keyword
  appears in the fund name, the index description (``symbol_profiles.description_1s``) or the look-through asset
  class. XAR → Aerospace & Defense → sector Industrials → XLI, peer funds ITA and PPA.
* **Relative performance** is rebuilt with that sector ETF and the peer funds (house closes via ``sources.bars``).
  Facts already written for the vendor-sector ETF keep their ids; their label says they are the vendor-sector ETF.
* **Fund profile** — expense ratio, distributions and yield (``symbol_profiles``), dividend history
  (``ticker_dividends``), top holdings and weights (``fund_lookthrough.json`` / ``fund_holdings_cache.json``), the
  analyst look-through (``etf_analyst_enrich``). AUM is not in the house; it says so.
* **House scenarios** when no analyst target exists: a ±1σ 12-month lognormal band from the 1Y volatility of daily
  closes, method labelled; "Scenario analysis, not an order".
* **Macro sensitivity** for every name: OLS of the ticker's returns on changes in the 10-year yield (daily), CPI
  (monthly) and the VIX (daily) over up to two years of house history vs FRED; "not reliable" below the point or
  t-stat floor. The "effect" is the sign of beta × the series' 3-month change: headwind / tailwind.

Pure computation over the ``sources`` readers; no provider call, no write. READ_ONLY_ADVISORY (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math
import statistics
from typing import Any, Callable, Optional

from . import blocks as bk

CONFIG_REL = "config/prospectus_etf_categories.json"
SCENARIO_FOOTER = "Scenario analysis, not an order or a recommendation to trade."
MACRO_SERIES = {"DGS10": ("rates", "10-year Treasury yield", "daily", 100.0, "bp"),
                "T10Y2Y": ("curve", "10y–2y Treasury spread", "daily", 100.0, "bp"),
                "CPIAUCSL": ("inflation", "CPI (month-over-month %)", "monthly", 1.0, "pp of monthly CPI change"),
                "VIXCLS": ("volatility", "VIX", "daily", 1.0, "VIX point")}


def _f(v: Any) -> Optional[float]:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def load_categories(root=None) -> dict:
    from . import ROOT
    try:
        return json.loads(((root or ROOT) / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"categories": {}, "symbols": {}}


def _series(bars: Any) -> list[tuple[str, float]]:
    return bk._series(bars)  # NYSE sessions only (weekend / holiday quote copies dropped), one close per date


# ── reads ─────────────────────────────────────────────────────────────────────────────────────────────────────────
PROFILE_SQL = ("SELECT quote_type, instrument_type, expense_ratio, dividend_yield_pct, ttm_dividend, "
               "ttm_distribution_amount, last_distribution_date, last_distribution_amount, distribution_cadence, "
               "next_distribution_est, analyst_look_through_pct, analyst_basis, description_1s, updated_at, "
               "distributions_updated_at FROM symbol_profiles WHERE upper(symbol) = %s LIMIT 1")


def _query(sources: Any) -> Optional[Callable]:
    try:
        return sources.db()
    except Exception:  # noqa: BLE001 - a fake or offline source: the reads below become recorded gaps
        return None


def fund_row(sources: Any, sym: str) -> dict:
    q = _query(sources)
    if q is None:
        return {}
    try:
        rows = q(PROFILE_SQL, (sym,), fetch="all") or []
    except Exception:  # noqa: BLE001
        return {}
    return dict(rows[0]) if rows else {}


def dividend_history(sources: Any, sym: str, limit: int = 8) -> list[dict]:
    q = _query(sources)
    if q is None:
        return []
    try:
        rows = q("SELECT ex_date, amount FROM ticker_dividends WHERE upper(symbol) = %s ORDER BY ex_date DESC LIMIT %s",
                 (sym, int(limit)), fetch="all") or []
    except Exception:  # noqa: BLE001
        return []
    return [{"ex_date": str(r.get("ex_date"))[:10], "amount": _f(r.get("amount"))} for r in rows if _f(r.get("amount"))]


# ── classification ────────────────────────────────────────────────────────────────────────────────────────────────
def is_fund(*, rec: dict | None, fund: dict | None, holding: dict | None, cats: dict) -> bool:
    labels = {str(x).lower() for x in cats.get("vendor_fund_labels") or []}
    qtypes = {str(x).upper() for x in cats.get("fund_quote_types") or []}
    h = holding or {}
    if h.get("is_fund") or str(h.get("asset_type") or "").lower() in {"etf", "fund", "mutual_fund"}:
        return True
    f = fund or {}
    if str(f.get("quote_type") or "").upper() in qtypes or str(f.get("instrument_type") or "").lower() in {"etf", "fund", "mutual_fund"}:
        return True
    return str((rec or {}).get("industry") or "").strip().lower() in labels


def classify(sym: str, *, rec: dict | None, fund: dict | None, lookthrough: dict | None, holding: dict | None,
             cats: dict) -> dict:
    """{is_fund, category_id, label, sector, sector_etf, peers, basis} — basis names where the category came from."""
    out = {"is_fund": is_fund(rec=rec, fund=fund, holding=holding, cats=cats), "category_id": None, "label": None,
           "sector": None, "sector_etf": None, "peers": [], "basis": None}
    if not out["is_fund"]:
        return out
    catmap = cats.get("categories") or {}
    cid = (cats.get("symbols") or {}).get(sym)
    basis = "config symbol map (config/prospectus_etf_categories.json)" if cid in catmap else None
    if not basis:
        texts = [("fund name", (rec or {}).get("company")),
                 ("index description (symbol_profiles)", (fund or {}).get("description_1s")),
                 ("look-through asset class (fund_lookthrough.json)", ((lookthrough or {}).get("fund") or {}).get("asset_class"))]
        for cand, spec in catmap.items():
            hit = next((where for where, text in texts if text and any(k in str(text).lower() for k in spec.get("keywords") or [])), None)
            if hit:
                cid, basis = cand, f"keyword match on the {hit}"
                break
    if not cid or cid not in catmap:
        out["basis"] = "no category matched (name, index description, look-through asset class)"
        return out
    spec = catmap[cid]
    limit = int(cats.get("peer_limit", 2))
    out.update(category_id=cid, label=spec.get("label"), sector=spec.get("sector"), basis=basis,
               sector_etf=spec.get("sector_etf") if spec.get("sector_etf") != sym else None,
               peers=[p for p in spec.get("peers") or [] if p != sym][:limit])
    return out


# ── relative performance with the right benchmarks ────────────────────────────────────────────────────────────────
def rebuild_relative(bundle: Any, sources: Any, bars: list, cls: dict, *, cache: dict | None = None) -> Optional[dict]:
    """Recompute relative_performance with the category's sector ETF + peer funds; relabel stale vendor-sector facts."""
    from . import blocks as bk
    rel = bundle.blocks.get("relative_performance") or {}
    old_etf = rel.get("sector_etf")
    new_etf = cls.get("sector_etf")
    peers = list(cls.get("peers") or [])
    if old_etf == new_etf and not peers:
        return None
    sym = bundle.symbol
    bench: dict[str, list] = {}
    names = [n for n in (new_etf, *bk.BENCHMARKS, *peers) if n and n != sym]
    for name in dict.fromkeys(names):
        try:
            rows = sources.bars(name) or []
        except Exception:  # noqa: BLE001
            rows = []
        if rows:
            bench[name] = rows
        bundle.cover(f"benchmark_{name}", "used" if rows else "empty",
                     detail="fund category benchmark (config/prospectus_etf_categories.json)")
    if not bars or not bench:
        return None
    new = bk.relative_performance(sym, bars, bench, cache=cache or {}, industry=None)
    new["sector_etf"] = new_etf
    new["benchmarks"] = [n for n in (new_etf, *bk.BENCHMARKS) if n and n in bench]
    new["category_peers"] = [p for p in peers if p in bench]
    new["category"] = cls.get("label")
    new["category_basis"] = cls.get("basis")
    for key in ("rank_in_industry", "rs_rating_12m", "rs_basis", "sector_trend", "industry_trend"):
        new[key] = rel.get(key)
    new["gaps"] = [g for g in new.get("gaps") or [] if "industry-group series" not in g]
    if old_etf and old_etf != new_etf:
        new["gaps"].append(f"vendor sector for this fund mapped to {old_etf}; replaced by the fund's category sector ETF "
                           f"{new_etf or '(broad fund: SPY/QQQ only)'}")
        for f in bundle.facts:
            if f.get("kind") == "relative" and str(f.get("label", "")).startswith(f"{old_etf} return"):
                f["label"] = f"{f['label']} (vendor-sector ETF; not this fund's category)"
    at = bars[-1].get("price_date") if isinstance(bars[-1], dict) else None
    for r in new["returns"]:
        if r["name"] == sym or r["name"] in bk.BENCHMARKS:
            continue
        role = "sector ETF" if r["name"] == new_etf else "peer fund"
        for w in bk.WINDOWS:
            bundle.add("relative", f"{r['name']} ({role}, {cls.get('label')}) return {w} %", value=r[w], unit="%",
                       source="ticker_prices (house)", as_of=at)
    bundle.blocks["relative_performance"] = new
    return new


# ── fund profile ──────────────────────────────────────────────────────────────────────────────────────────────────
def fund_profile(bundle: Any, sources: Any, fund: dict, cls: dict, *, lookthrough: dict | None, last: Optional[float]) -> dict:
    sym = bundle.symbol
    src = "symbol_profiles (fund fields)"
    at = fund.get("distributions_updated_at") or fund.get("updated_at")
    out: dict[str, Any] = {"category": cls.get("label"), "category_basis": cls.get("basis"), "sector": cls.get("sector"),
                           "sector_etf": cls.get("sector_etf"), "peers": cls.get("peers"), "gaps": [], "facts": {}}

    def put(key: str, label: str, value: Any, unit: str, source: str, as_of: Any = None) -> None:
        fid = bundle.add("fund", label, value=value, unit=unit, source=source, as_of=as_of)
        out[key] = _f(value)
        if fid:
            out["facts"][key] = fid

    if cls.get("label"):
        fid = bundle.add("fund", "Fund category (house map)", text=f"{cls['label']}; sector exposure "
                         f"{cls.get('sector') or 'broad / multi-sector'}; sector ETF {cls.get('sector_etf') or 'none (broad fund)'}; "
                         f"peer funds {', '.join(cls.get('peers') or []) or 'none'} ({cls.get('basis')})",
                         source=f"config/prospectus_etf_categories.json ({cls.get('basis')})")
        out["facts"]["category"] = fid
        for f in bundle.facts:  # the vendor's "Financial / Exchange Traded Fund" is a wrapper label, not an exposure
            if f.get("kind") == "company" and f.get("label") in ("Sector", "Industry") and \
                    str(f.get("text") or "").lower() in {"financial", "financial services", "exchange traded fund"}:
                f["text"] = f"{f['text']} (vendor label for a fund wrapper; house category: {cls['label']})"
    er = _f(fund.get("expense_ratio"))
    if er is not None:
        put("expense_ratio_pct", "Fund expense ratio %", er * 100 if er < 0.05 else er, "%", src, fund.get("updated_at"))
    else:
        out["expense_ratio_pct"] = None
        out["gaps"].append("expense ratio: not in symbol_profiles for this fund")
    put("dividend_yield_pct", "Fund distribution yield %", fund.get("dividend_yield_pct"), "%", src, at)
    put("ttm_distribution", "Fund distributions, trailing 12 months ($/share)",
        fund.get("ttm_distribution_amount") if fund.get("ttm_distribution_amount") is not None else fund.get("ttm_dividend"),
        "$", src, at)
    put("last_distribution", "Fund last distribution ($/share)", fund.get("last_distribution_amount"), "$", src,
        fund.get("last_distribution_date"))
    out["last_distribution_date"] = str(fund.get("last_distribution_date") or "")[:10] or None
    out["distribution_cadence"] = fund.get("distribution_cadence")
    out["next_distribution_est"] = str(fund.get("next_distribution_est") or "")[:10] or None
    if out["next_distribution_est"]:
        bundle.add("fund", "Fund next distribution (house estimate)", text=f"{out['next_distribution_est']} "
                   f"({fund.get('distribution_cadence') or 'cadence n/a'})", source=src, as_of=at)
    if last and out.get("ttm_distribution") and not out.get("dividend_yield_pct"):
        put("dividend_yield_pct", "Fund distribution yield % (trailing 12m ÷ last close)",
            out["ttm_distribution"] / last * 100, "%", "derived: symbol_profiles distributions ÷ daily_bars close", at)
    hist = dividend_history(sources, sym)
    out["dividend_history"] = hist
    if hist:
        bundle.add("fund", "Fund distribution history (ex-date: $/share)",
                   text="; ".join(f"{h['ex_date']}: {h['amount']}" for h in hist[:8]), source="ticker_dividends",
                   as_of=hist[0]["ex_date"])
    else:
        out["gaps"].append("distribution history: no ticker_dividends rows for this fund")
    lt = (lookthrough or {}).get("fund") or {}
    top = lt.get("top_holdings") or (lookthrough or {}).get("holdings") or {}
    rows = lookthrough_rows(top)
    out["top_holdings"] = rows
    if rows:
        out["top_holdings_as_of"] = lt.get("fetched_date")
        if not any(str(f.get("label") or "").startswith("Fund top holding") for f in bundle.facts):
            for r in rows:
                bundle.add("lookthrough", f"Fund top holding: {r['name']} %", value=r["weight_pct"], unit="%",
                           source="fund look-through (fund_lookthrough.json / fund_holdings_cache.json)",
                           as_of=lt.get("fetched_date"))
        out["top10_weight_pct"] = round(sum(r["weight_pct"] for r in rows), 2)
        bundle.add("fund", "Fund top-10 holdings combined weight %", value=out["top10_weight_pct"], unit="%",
                   source="fund look-through (fund_lookthrough.json / fund_holdings_cache.json)", as_of=lt.get("fetched_date"))
    else:
        out["gaps"].append("top holdings and weights: no look-through entry for this fund in fund_lookthrough.json or "
                           "fund_holdings_cache.json")
    out["aum_usd"] = None
    out["gaps"].append("assets under management: not held in any house store (symbol_profiles / enrichment cache)")
    lt_up = _f(fund.get("analyst_look_through_pct"))
    if lt_up is not None:
        put("analyst_look_through_pct", f"Analyst look-through upside % ({fund.get('analyst_basis') or 'basis n/a'})",
            lt_up, "%", "symbol_profiles (etf_analyst_enrich)", fund.get("updated_at"))
        out["analyst_basis"] = fund.get("analyst_basis")
    return out


def lookthrough_rows(top: Any, limit: int = 10) -> list[dict]:
    """Top holdings as [{name, weight_pct}] from either look-through shape: {name: weight} / {name: {weight}} or a list
    of rows keyed ``symbol``/``ticker``/``name`` with ``weight``/``pct``. fund_lookthrough.json writes ticker + pct;
    reading only symbol + weight dropped every row and printed "no look-through entry" beside a look-through table
    that listed them (accuracy audit 2026-10-26)."""
    if isinstance(top, dict):
        items = list(top.items())
    else:
        items = [(str(t.get("symbol") or t.get("ticker") or t.get("name")),
                  t.get("weight") if t.get("weight") is not None else t.get("pct"))
                 for t in top or [] if isinstance(t, dict)]
    rows = []
    for name, w in items[:limit]:
        w = (w.get("weight") if w.get("weight") is not None else w.get("pct")) if isinstance(w, dict) else w
        if _f(w) is not None and name and name != "None":
            rows.append({"name": name, "weight_pct": _f(w)})
    return rows


# ── house scenarios (no analyst targets) ──────────────────────────────────────────────────────────────────────────
def house_scenarios(bundle: Any, bars: list, cats: dict) -> Optional[dict]:
    spec = cats.get("scenarios") or {}
    s = _series(bars)[-253:]
    if len(s) < int(spec.get("min_sessions", 120)):
        return None
    rets = [math.log(s[i][1] / s[i - 1][1]) for i in range(1, len(s))]
    sigma = statistics.pstdev(rets) * math.sqrt(252) * float(spec.get("sigma", 1.0))
    last, at = s[-1][1], s[-1][0]
    hi, lo = max(c for _, c in s), min(c for _, c in s)
    label = spec.get("label") or "House range: ±1σ 12-month band from 1Y volatility."
    src = "derived: house closes (ticker_prices), 1Y volatility band"
    vol_id = bundle.add("scenario", "House range basis: annualized volatility of daily log returns (1Y) %",
                        value=sigma * 100, unit="%", source=src, as_of=at)
    hi_id = bundle.add("scenario", "House range: 52-week high close", value=hi, unit="$", source="ticker_prices (house)", as_of=at)
    lo_id = bundle.add("scenario", "House range: 52-week low close", value=lo, unit="$", source="ticker_prices (house)", as_of=at)
    cases = []
    for case, z in (("bear", -1.0), ("base", 0.0), ("bull", 1.0)):
        price = last * math.exp(z * sigma)
        chg = (price / last - 1) * 100
        fid = bundle.add("scenario", f"House {case} case price (12m, {'±1σ' if z else 'no-drift'} volatility band)",
                         value=price, unit="$", source=src, as_of=at)
        bundle.add("scenario", f"House {case} case change vs last close %", value=chg, unit="%", source=src, as_of=at)
        if case == "base":
            text = (f"Last close carried forward (no drift assumed) [{fid}]; the band's ends use 1Y volatility "
                    f"{sigma * 100:.1f}% [{vol_id}].")
        elif case == "bear":
            text = (f"One standard deviation lower over 12 months, {chg:.1f}% [{fid}]; the 52-week low close was "
                    f"${lo:.2f} [{lo_id}].")
        else:
            text = (f"One standard deviation higher over 12 months, {chg:+.1f}% [{fid}]; the 52-week high close was "
                    f"${hi:.2f} [{hi_id}].")
        cases.append({"case": case, "price": round(price, 2), "price_fact": fid, "probability_pct": None,
                      "change_pct": round(chg, 2), "narrative": text})
    return {"cases": cases, "method": "house_volatility_band", "method_label": label,
            "probability_basis": "not assigned: a ±1σ band is a statistical range (about two years in three fall inside it "
                                 "under a lognormal assumption), not a probability-weighted forecast",
            "footer": SCENARIO_FOOTER,
            "gaps": ["no analyst price targets for this name; house volatility range shown instead"]}


# ── macro sensitivity (measured, not narrated) ───────────────────────────────────────────────────────────────────
def _ols(x: list[float], y: list[float]) -> Optional[dict]:
    n = len(x)
    if n < 3:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    if not sxx:
        return None
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    resid = [b - my - beta * (a - mx) for a, b in zip(x, y)]
    sse = sum(r * r for r in resid)
    syy = sum((b - my) ** 2 for b in y)
    se = math.sqrt(sse / (n - 2) / sxx) if n > 2 and sse > 0 else 0.0
    return {"beta": beta, "r2": (1 - sse / syy) if syy else 0.0, "t": (beta / se) if se else 0.0, "n": n}


def _month_end(points: list[tuple[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for d, v in sorted(points):
        out[d[:7]] = v
    return out


def macro_sensitivity(bundle: Any, sources: Any, bars: list, now: datetime, cats: dict) -> dict:
    """{FRED id: {beta, unit, n, r2, t, reliable, chg_3m, effect, method}} from house closes vs FRED."""
    spec = cats.get("macro") or {}
    q = _query(sources)
    out: dict[str, Any] = {}
    if q is None:
        return out
    since = (now - timedelta(days=int(spec.get("lookback_days", 760)))).date()
    try:
        rows = q("SELECT series_id, value, observation_date FROM fred_economic_series WHERE series_id = ANY(%s) "
                 "AND observation_date >= %s ORDER BY series_id, observation_date", (list(MACRO_SERIES), since), fetch="all") or []
    except Exception:  # noqa: BLE001
        return out
    by: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        v = _f(r.get("value"))
        if v is not None:
            by.setdefault(r["series_id"], []).append((str(r["observation_date"])[:10], v))
    s = [(d, c) for d, c in _series(bars) if d >= since.isoformat()]
    closes = dict(s)
    min_d, min_m = int(spec.get("min_daily_points", 60)), int(spec.get("min_monthly_points", 18))
    t_min = float(spec.get("t_stat_reliable", 2.0))
    for sid, (group, label, freq, scale, unit) in MACRO_SERIES.items():
        pts = by.get(sid) or []
        if not pts:
            out[sid] = {"group": group, "label": label, "reliable": False, "effect": f"not reliable: FRED {sid} is not in fred_economic_series",
                        "method": None, "n": 0}
            continue
        if freq == "daily":
            ser = dict(pts)
            x, y = [], []
            for (d0, c0), (d1, c1) in zip(s, s[1:]):
                if d0 in ser and d1 in ser:
                    x.append((ser[d1] - ser[d0]) * scale)
                    y.append((c1 / c0 - 1) * 100)
            floor = min_d
            method = f"OLS of daily % returns on daily changes in {label} (per {unit}), house closes vs FRED {sid}"
        else:
            cpi = sorted(pts)
            mom = {cpi[i][0][:7]: (cpi[i][1] / cpi[i - 1][1] - 1) * 100 for i in range(1, len(cpi)) if cpi[i - 1][1]}
            me = _month_end(s)
            months = sorted(me)
            x, y = [], []
            for m0, m1 in zip(months, months[1:]):
                if m1 in mom:
                    x.append(mom[m1])
                    y.append((me[m1] / me[m0] - 1) * 100)
            floor = min_m
            method = f"OLS of monthly % returns on the monthly % change in CPI (FRED {sid}), month-end house closes"
        fit = _ols(x, y)
        last = pts[-1]
        prior = next((p for p in reversed(pts) if p[0] <= (date.fromisoformat(last[0]) - timedelta(days=90)).isoformat()), None)
        chg = None
        if prior:
            chg = (last[1] - prior[1]) * scale if freq == "daily" else (last[1] / prior[1] - 1) * 100 / 3
        row = {"group": group, "label": label, "unit": unit, "method": method, "n": len(x), "chg_3m": None if chg is None else round(chg, 3)}
        if fit is None or len(x) < floor:
            row.update(reliable=False, beta=None, effect=f"not reliable: {len(x)} paired points (need {floor})")
            out[sid] = row
            continue
        row.update(beta=round(fit["beta"], 5), r2=round(fit["r2"], 4), t=round(fit["t"], 2))
        reliable = abs(fit["t"]) >= t_min
        row["reliable"] = reliable
        if not reliable:
            row["effect"] = f"not reliable: t {fit['t']:.1f} below {t_min:.0f} (β {fit['beta']:+.3f}% per {unit}, n {len(x)})"
        elif chg is None or chg == 0:
            row["effect"] = f"neutral: series flat over 3 months (β {fit['beta']:+.3f}% per {unit}, n {len(x)})"
        else:
            implied = fit["beta"] * chg
            word = "tailwind" if implied > 0 else "headwind"
            row["implied_3m_pct"] = round(implied, 2)
            row["effect"] = (f"{word}: β {fit['beta']:+.3f}% per {unit} × 3-month change {chg:+.2f} ≈ {implied:+.1f}% "
                             f"(n {len(x)}, t {fit['t']:.1f}, R² {fit['r2']:.2f})")
        at = last[0]
        if row.get("beta") is not None:
            bundle.add("macro", f"Measured sensitivity to {label}: % price move per {unit} ({'monthly' if freq != 'daily' else 'daily'}, "
                       f"{len(x)} points)", value=row["beta"], source=f"derived: house closes vs FRED {sid}", as_of=at)
        bundle.add("macro", f"Macro effect on this name: {label}", text=row["effect"], source=f"derived: house closes vs FRED {sid}",
                   as_of=at)
        out[sid] = row
    return out


def apply_macro(bundle: Any, sens: dict) -> None:
    """Put the measured effect on each FRED series row (the UI reads ``series[*].effect``) and keep the detail."""
    if not sens:
        return
    macro = bundle.blocks.setdefault("macro_sensitivity", {"series": {}, "gaps": []})
    macro["sensitivity"] = sens
    series = macro.setdefault("series", {})
    for sid, row in sens.items():
        if sid in series and isinstance(series[sid], dict):
            series[sid]["effect"] = row.get("effect")
    macro["sensitivity_method"] = ("measured: OLS of the name's returns on changes in each series over up to two years of "
                                   "house closes vs FRED; 'not reliable' below the point or t-stat floor "
                                   "(config/prospectus_etf_categories.json macro)")


# ── attach (called once per bundle, after full_assemble) ─────────────────────────────────────────────────────────
def attach(sources: Any, bundle: Any, *, bars: list, holding: dict | None, now: datetime, cats: dict | None = None) -> dict:
    cats = cats or load_categories()
    sym = bundle.symbol
    cache = {}
    try:
        cache = sources.enrichment_cache() or {}
    except Exception:  # noqa: BLE001
        cache = {}
    rec = cache.get(sym) if isinstance(cache.get(sym), dict) else {}
    fund = fund_row(sources, sym)
    try:
        lt = sources.lookthrough(sym) or {}
    except Exception:  # noqa: BLE001
        lt = {}
    cls = classify(sym, rec=rec, fund=fund, lookthrough=lt, holding=holding, cats=cats)
    bundle.context["fund_category"] = cls
    if cls["is_fund"]:
        if cls.get("category_id"):
            rebuild_relative(bundle, sources, bars, cls, cache=cache)
        last = _f(bars[-1].get("close")) if bars and isinstance(bars[-1], dict) else None
        bundle.blocks["fund_profile"] = fund_profile(bundle, sources, fund, cls, lookthrough=lt, last=last)
        osd = (bundle.blocks.get("options_sentiment_dividends") or {}).get("dividend")
        fp = bundle.blocks["fund_profile"]
        if isinstance(osd, dict):  # the dividends tile was built before the fund profile: give it the fund's figures
            if osd.get("yield_pct") is None and fp.get("dividend_yield_pct") is not None:
                osd["yield_pct"] = fp["dividend_yield_pct"]
                osd["yield_basis"] = "fund distribution yield (symbol_profiles)"
            if fp.get("ttm_distribution") is not None:
                osd["ttm_distribution"] = fp["ttm_distribution"]
    has_targets = any(f.get("label") in ("Analyst target low", "Analyst target mean", "Analyst target high")
                      for f in bundle.facts)
    if not has_targets:
        hs = house_scenarios(bundle, bars, cats)
        if hs:
            bundle.blocks["scenarios_house"] = hs
    try:
        apply_macro(bundle, macro_sensitivity(bundle, sources, bars, now, cats))
    except Exception as exc:  # noqa: BLE001 - a sensitivity failure is a gap, never a failed prospectus
        bundle.blocks.setdefault("macro_sensitivity", {"series": {}}).setdefault("gaps", []).append(
            f"macro sensitivity not computed: {type(exc).__name__}")
    return cls

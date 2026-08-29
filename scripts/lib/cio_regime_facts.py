"""Regime facts computed from ingested public series. Context only, never a signal.

Wave 3A.3 section B. Each fact is a historical conditional distribution with an
explicit `sample_n` and `as_of` — never a threshold that emits an action. There
is no "NDX at X therefore sell" here and there cannot be: every row is
`dimension_scope=context`, `standalone_sell=False`, and a test asserts no row
carries an imperative.

Sources are the FRED and Ken French series already on disk under
`reference/library/series/`. Nothing here touches the network.

Grade follows the same law as everything else: below `MIN_SAMPLE_N` a row is
graded D and cannot corpus_hit, however suggestive the numbers look.
"""
from __future__ import annotations

import csv
import statistics
from datetime import date
from pathlib import Path
from typing import Any, Optional

REGIME_FACTS_VERSION = "regime_facts_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

_SERIES = Path(__file__).resolve().parents[2] / "reference" / "library" / "series"

MIN_SAMPLE_N = 8          # brief: grade D if n < 8
DIMENSION_SCOPE = "context"
APPLICATION_LAW = ("historical conditional distribution — context only; "
                   "never a threshold that emits an action; "
                   "never a standalone sell; never creates TRIM")


def _fred(name: str) -> list[tuple[date, float]]:
    p = _SERIES / f"fred_{name}.csv"
    out: list[tuple[date, float]] = []
    if not p.exists():
        return out
    for row in csv.DictReader(p.open(encoding="utf-8")):
        vals = list(row.values())
        if len(vals) < 2:
            continue
        try:
            d = date.fromisoformat(str(vals[0])[:10])
            v = float(vals[1])
        except ValueError:
            continue
        out.append((d, v))
    return out


def _monthly_last(series: list[tuple[date, float]]) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    for d, v in series:
        out[(d.year, d.month)] = v       # later rows overwrite -> month end
    return out


def _stats(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"sample_n": 0, "mean": None, "median": None, "win_rate": None}
    return {
        "sample_n": len(vals),
        "mean": round(statistics.mean(vals), 4),
        "median": round(statistics.median(vals), 4),
        "win_rate": round(sum(1 for v in vals if v > 0) / len(vals), 4),
        "stdev": round(statistics.stdev(vals), 4) if len(vals) > 1 else None,
    }


def _grade(sample_n: int) -> str:
    if sample_n < MIN_SAMPLE_N:
        return "D"
    return "B" if sample_n >= 30 else "C"


def _row(fact_id: str, result: dict[str, Any], *, sources: list[str],
         note: str = "") -> dict[str, Any]:
    n = int(result.get("sample_n") or 0)
    return {
        "source_id": "regime_fact_" + fact_id,
        "fact_id": fact_id,
        "family": "macro",
        "title": fact_id.replace("_", " "),
        "result": result,
        "sample_n": n,
        "as_of": date.today().isoformat(),
        "sources": sources,
        "evidence_grade": _grade(n),
        "application_law": APPLICATION_LAW,
        "dimension_scope": DIMENSION_SCOPE,
        "refresh": "weekly",
        "max_influence_pct": 10.0,
        "standalone_sell": False,
        "creates_trim": False,
        "notes": note,
        "regime_facts_version": REGIME_FACTS_VERSION,
        "authority": AUTHORITY,
    }


def _fwd_returns(monthly: dict[tuple[int, int], float], keys: list[tuple[int, int]],
                 horizon: int) -> list[float]:
    ordered = sorted(monthly)
    idx = {k: i for i, k in enumerate(ordered)}
    out = []
    for k in keys:
        i = idx.get(k)
        if i is None or i + horizon >= len(ordered):
            continue
        a, b = monthly[ordered[i]], monthly[ordered[i + horizon]]
        if a and a > 0:
            out.append((b / a - 1.0) * 100.0)
    return out


def spx_vs_ndx_relative_strength() -> list[dict[str, Any]]:
    spx = _monthly_last(_fred("sp500"))
    ndx = _monthly_last(_fred("nasdaqcom"))
    rows = []
    for horizon, label in ((3, "3m"), (12, "12m")):
        common = sorted(set(spx) & set(ndx))
        ordered = common
        vals = []
        for i in range(horizon, len(ordered)):
            k0, k1 = ordered[i - horizon], ordered[i]
            if spx[k0] and ndx[k0] and spx[k0] > 0 and ndx[k0] > 0:
                s = spx[k1] / spx[k0] - 1.0
                n = ndx[k1] / ndx[k0] - 1.0
                vals.append((s - n) * 100.0)
        rows.append(_row(f"spx_vs_ndx_rs_{label}", _stats(vals),
                         sources=["fred_sp500", "fred_nasdaqcom"],
                         note=("SPX minus NDX total change over the window, in "
                               "percentage points; a spread, not a signal")))
    return rows


def vix_regime_next_3m() -> list[dict[str, Any]]:
    """Next-3m SPX distribution conditioned on the VIX bucket at month end."""
    vix = _monthly_last(_fred("vixcls"))
    spx = _monthly_last(_fred("sp500"))
    buckets = {"lt15": lambda v: v < 15,
               "15_to_25": lambda v: 15 <= v <= 25,
               "gt25": lambda v: v > 25}
    rows = []
    for name, test in buckets.items():
        keys = [k for k, v in vix.items() if test(v) and k in spx]
        vals = _fwd_returns(spx, keys, 3)
        rows.append(_row(f"vix_regime_{name}_next_3m_spx", _stats(vals),
                         sources=["fred_vixcls", "fred_sp500"],
                         note=("conditional distribution only; the bucket "
                               "describes history, it does not recommend")))
    return rows


def yield_curve_inversion_next_12m() -> list[dict[str, Any]]:
    t10y2y = _monthly_last(_fred("t10y2y"))
    spx = _monthly_last(_fred("sp500"))
    inv = [k for k, v in t10y2y.items() if v < 0 and k in spx]
    nrm = [k for k, v in t10y2y.items() if v >= 0 and k in spx]
    return [
        _row("yield_curve_inverted_next_12m_spx",
             _stats(_fwd_returns(spx, inv, 12)),
             sources=["fred_t10y2y", "fred_sp500"],
             note="SPX series starts 2016, so the inverted sample is short"),
        _row("yield_curve_normal_next_12m_spx",
             _stats(_fwd_returns(spx, nrm, 12)),
             sources=["fred_t10y2y", "fred_sp500"]),
    ]


def build_regime_facts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fn in (spx_vs_ndx_relative_strength, vix_regime_next_3m,
               yield_curve_inversion_next_12m):
        try:
            out.extend(fn())
        except Exception:
            continue
    return out

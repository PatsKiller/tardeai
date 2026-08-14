"""cio_seasonality_analytics.py — Phases 11–16 monthly-return reproduction.

Computes N / mean / median / win-rate / std from monthly index returns.
Prefers public price data when explicitly allowed; otherwise a deterministic
fixture CSV so tests never need the network.

Stock Almanac layer: SOURCE CLAIM (public STA alert title/URL/date + operator
summary) ≠ TRADE AI REPRODUCTION ≠ CURRENT APPLICATION.

READ_ONLY_ADVISORY. Never a standalone sell. Never full-text book extracts.
"""
from __future__ import annotations

import csv
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_research_grader import grade_evidence
from scripts.lib.cio_research_registry import STA_PUBLIC_ALERTS
from scripts.lib.cio_seasonality_engine import MONTH_NAMES, presidential_cycle_year

SEASONALITY_ANALYTICS_VERSION = "seasonality_analytics_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"
MAX_INFLUENCE_PCT = 10.0

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "us_equity_monthly_sample.csv"

OOS_START_YEAR = 2000

# Operator-structured summaries of public STA *alerts* (not book pages).
_STA_SUMMARIES: dict[str, str] = {
    "august_general": (
        "Operator-structured summary of a public STA investor alert (citation "
        "only): August is described as among the weaker modern-sample months "
        "for broad US indexes (post-1987/1988), contrasting a stronger "
        "early-20th-century profile. Not a book extract."
    ),
    "august_midterm": (
        "Operator-structured summary of a public STA investor alert (citation "
        "only): midterm-year Augusts are described as offering no seasonal "
        "reprieve — still a weak-month window inside the midterm weak spot. "
        "Not a book extract."
    ),
    "september_general": (
        "Operator-structured summary of a public STA investor alert (citation "
        "only): September is described as the worst-performing calendar month "
        "for major US indexes in long samples since 1950. Not a book extract."
    ),
    "september_midterm": (
        "Operator-structured summary of a public STA investor alert (citation "
        "only): midterm-year Septembers are described as modestly better in "
        "rank than September overall, while average results can remain weak. "
        "Not a book extract."
    ),
}

_APPLICABILITY = (
    "Context / risk modifier only. Maximum 10% conviction or sizing language "
    "adjustment. Never a standalone sell. Does not create TRIM."
)


def _cycle_label(year: int) -> str:
    return presidential_cycle_year(int(year))["cycle_label"]


def _try_public_monthly_returns() -> list[dict[str, Any]]:
    """Best-effort public monthly % from yfinance (^GSPC). Never required."""
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return []
    try:
        hist = yf.download(
            "^GSPC",
            start="1950-01-01",
            interval="1mo",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    except Exception:
        return []
    if hist is None or getattr(hist, "empty", True):
        return []
    close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
    try:
        pct = close.pct_change() * 100.0
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for idx, val in pct.dropna().items():
        try:
            dt = idx.date() if hasattr(idx, "date") else idx
            year = int(dt.year)
            month = int(dt.month)
            rows.append(
                {
                    "date": f"{year}-{month:02d}-01",
                    "year": year,
                    "month": month,
                    "return_pct": float(val),
                    "cycle_label": _cycle_label(year),
                    "source": "yfinance_GSPC",
                }
            )
        except Exception:
            continue
    return rows


def _load_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            try:
                year = int(raw["year"] if raw.get("year") else str(raw.get("date") or "")[:4])
                month = int(raw["month"] if raw.get("month") else str(raw.get("date") or "")[5:7])
                ret = float(raw["return_pct"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                {
                    "date": raw.get("date") or f"{year}-{month:02d}-01",
                    "year": year,
                    "month": month,
                    "return_pct": ret,
                    "cycle_label": raw.get("cycle_label") or _cycle_label(year),
                    "source": path.name,
                }
            )
    return rows


def load_monthly_returns(
    path: Optional[Path] = None,
    *,
    allow_network: bool = False,
) -> list[dict[str, Any]]:
    """Load monthly % returns. Network is opt-in; fixture is the dry default."""
    if path is not None:
        return _load_csv(Path(path))
    if allow_network:
        public = _try_public_monthly_returns()
        if public:
            return public
    fixture = DEFAULT_FIXTURE
    if not fixture.is_file():
        raise FileNotFoundError(f"monthly returns fixture missing: {fixture}")
    return _load_csv(fixture)


@lru_cache(maxsize=4)
def _cached_rows(allow_network: bool = False) -> tuple[dict[str, Any], ...]:
    return tuple(load_monthly_returns(allow_network=allow_network))


def _rows(path: Optional[Path] = None, allow_network: bool = False) -> list[dict[str, Any]]:
    if path is not None:
        return load_monthly_returns(path, allow_network=False)
    return list(_cached_rows(allow_network))


def _filter(
    rows: list[dict[str, Any]],
    *,
    month: Optional[int] = None,
    cycle_label: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> list[float]:
    out: list[float] = []
    for r in rows:
        if month is not None and int(r["month"]) != int(month):
            continue
        if cycle_label and r.get("cycle_label") != cycle_label:
            continue
        yr = int(r["year"])
        if year_min is not None and yr < year_min:
            continue
        if year_max is not None and yr > year_max:
            continue
        out.append(float(r["return_pct"]))
    return out


def summarize_returns(values: list[float]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "win_rate": None,
            "std": None,
        }
    mean = statistics.fmean(values)
    return {
        "n": n,
        "mean": mean,
        "median": statistics.median(values),
        "win_rate": sum(1 for v in values if v > 0) / n,
        "std": statistics.pstdev(values) if n > 1 else 0.0,
    }


def monthly_stats(
    month: int,
    *,
    cycle_label: Optional[str] = None,
    path: Optional[Path] = None,
    allow_network: bool = False,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> dict[str, Any]:
    rows = _rows(path, allow_network)
    vals = _filter(
        rows,
        month=month,
        cycle_label=cycle_label,
        year_min=year_min,
        year_max=year_max,
    )
    stats = summarize_returns(vals)
    stats.update(
        {
            "month": month,
            "month_name": MONTH_NAMES[month] if 1 <= month <= 12 else "unknown",
            "cycle_label": cycle_label,
            "year_min": year_min,
            "year_max": year_max,
        }
    )
    return stats


def all_month_stats(
    *,
    cycle_label: Optional[str] = None,
    path: Optional[Path] = None,
    allow_network: bool = False,
) -> dict[int, dict[str, Any]]:
    return {
        m: monthly_stats(m, cycle_label=cycle_label, path=path, allow_network=allow_network)
        for m in range(1, 13)
    }


def reproduced_weak_months(
    *,
    path: Optional[Path] = None,
    allow_network: bool = False,
    min_n: int = 20,
) -> set[int]:
    """Weak-month set derived from reproduction — not a hardcoded bearish list.

    A month is weak if its mean is below 0 or it ranks in the bottom three
    means (with adequate N).
    """
    stats = all_month_stats(path=path, allow_network=allow_network)
    usable = {m: s for m, s in stats.items() if (s.get("n") or 0) >= min_n and s.get("mean") is not None}
    if not usable:
        return set()
    ranked = sorted(usable, key=lambda m: float(usable[m]["mean"]))
    bottom = set(ranked[:3])
    negative = {m for m, s in usable.items() if float(s["mean"]) < 0}
    return bottom | negative


def reproduced_strong_months(
    *,
    path: Optional[Path] = None,
    allow_network: bool = False,
    min_n: int = 20,
) -> set[int]:
    stats = all_month_stats(path=path, allow_network=allow_network)
    usable = {m: s for m, s in stats.items() if (s.get("n") or 0) >= min_n and s.get("mean") is not None}
    if not usable:
        return set()
    ranked = sorted(usable, key=lambda m: float(usable[m]["mean"]), reverse=True)
    top = set(ranked[:3])
    positive = {m for m, s in usable.items() if float(s["mean"]) > 0.8}
    return top | positive


def _oos_note(is_stats: dict[str, Any], oos: dict[str, Any], fixture_used: bool) -> str:
    src = "synthetic fixture CSV (deterministic; not a vendor print)" if fixture_used else "public monthly index series"
    oos_mean = oos.get("mean")
    oos_txt = "insufficient OOS rows"
    if oos.get("n"):
        oos_txt = (
            f"OOS {OOS_START_YEAR}–end n={oos['n']} mean="
            f"{oos_mean:.3f}% win_rate={oos.get('win_rate')}"
        )
    is_mean = is_stats.get("mean")
    is_txt = "n/a"
    if is_stats.get("n"):
        is_txt = (
            f"in-sample through {OOS_START_YEAR - 1} n={is_stats['n']} "
            f"mean={is_mean:.3f}%"
        )
    return (
        f"Reproduction source: {src}. {is_txt}. {oos_txt}. "
        "Seasonality is sample-dependent and is not an execution rule."
    )


def _source_claim(key: str) -> dict[str, Any]:
    meta = STA_PUBLIC_ALERTS[key]
    return {
        "source_id": meta["source_id"],
        "title": meta["title"],
        "url": meta["url"],
        "date": meta["date"],
        "summary": _STA_SUMMARIES[key],
        "citation_only": True,
        "fulltext": False,
        "license_class": meta["license_class"],
    }


def _almanac_slice(
    key: str,
    month: int,
    *,
    cycle_label: Optional[str],
    claim_direction: str = "negative",
    path: Optional[Path] = None,
    allow_network: bool = False,
) -> dict[str, Any]:
    rows = _rows(path, allow_network)
    fixture_used = path is not None or not allow_network or not any(
        r.get("source") == "yfinance_GSPC" for r in rows
    )
    full = summarize_returns(_filter(rows, month=month, cycle_label=cycle_label))
    ins = summarize_returns(
        _filter(rows, month=month, cycle_label=cycle_label, year_max=OOS_START_YEAR - 1)
    )
    oos = summarize_returns(
        _filter(rows, month=month, cycle_label=cycle_label, year_min=OOS_START_YEAR)
    )
    graded = grade_evidence(
        reproduced=bool(full["n"]),
        n=full["n"],
        mean=full["mean"],
        win_rate=full["win_rate"],
        std=full["std"],
        oos_mean=oos.get("mean"),
        oos_win_rate=oos.get("win_rate"),
        oos_n=oos.get("n"),
        claim_direction=claim_direction,
    )
    mean = full["mean"]
    wr = full["win_rate"]
    repro = (
        f"Trade AI independent reproduction from monthly index returns "
        f"(n={full['n']}, mean={mean if mean is None else round(mean, 4)}, "
        f"median={full['median'] if full['median'] is None else round(full['median'], 4)}, "
        f"win_rate={wr if wr is None else round(wr, 4)}, "
        f"std={full['std'] if full['std'] is None else round(full['std'], 4)}"
        f"{', cycle=' + cycle_label if cycle_label else ''})."
    )
    source = _source_claim(key)
    return {
        "key": key,
        "month": month,
        "month_name": MONTH_NAMES[month],
        "cycle_label": cycle_label or "all_years",
        "source_claim": source,
        "trade_ai_reproduction": repro,
        "n": full["n"],
        "mean": mean,
        "median": full["median"],
        "win_rate": wr,
        "std": full["std"],
        "evidence_grade": graded["evidence_grade"],
        "grade_reasons": graded.get("reasons") or [],
        "oos_note": _oos_note(ins, oos, fixture_used),
        "oos": oos,
        "in_sample": ins,
        "current_applicability": _APPLICABILITY,
        "layers": {
            "source_claim": f"{source['title']} ({source['date']}) {source['url']}",
            "trade_ai_reproduction": repro,
            "current_application": _APPLICABILITY,
        },
        "authority": AUTHORITY,
        "execution_engine": False,
        "standalone_sell": False,
        "creates_trim": False,
        "max_influence_pct": MAX_INFLUENCE_PCT,
        "version": SEASONALITY_ANALYTICS_VERSION,
    }


def august_general(*, path: Optional[Path] = None, allow_network: bool = False) -> dict[str, Any]:
    return _almanac_slice("august_general", 8, cycle_label=None, path=path, allow_network=allow_network)


def august_midterm(*, path: Optional[Path] = None, allow_network: bool = False) -> dict[str, Any]:
    return _almanac_slice(
        "august_midterm", 8, cycle_label="midterm_year", path=path, allow_network=allow_network
    )


def september_general(*, path: Optional[Path] = None, allow_network: bool = False) -> dict[str, Any]:
    return _almanac_slice("september_general", 9, cycle_label=None, path=path, allow_network=allow_network)


def september_midterm(*, path: Optional[Path] = None, allow_network: bool = False) -> dict[str, Any]:
    return _almanac_slice(
        "september_midterm", 9, cycle_label="midterm_year", path=path, allow_network=allow_network
    )


def best_six_months(*, path: Optional[Path] = None, allow_network: bool = False) -> dict[str, Any]:
    """Independent Nov–Apr vs May–Oct comparison (almanac-tradition hypothesis)."""
    rows = _rows(path, allow_network)
    best = [r["return_pct"] for r in rows if int(r["month"]) in (11, 12, 1, 2, 3, 4)]
    worst = [r["return_pct"] for r in rows if int(r["month"]) in (5, 6, 7, 8, 9, 10)]
    b = summarize_returns(best)
    w = summarize_returns(worst)
    spread = None
    if b["mean"] is not None and w["mean"] is not None:
        spread = b["mean"] - w["mean"]
    graded = grade_evidence(
        reproduced=bool(b["n"] and w["n"]),
        n=min(b["n"], w["n"]),
        mean=spread,
        win_rate=b.get("win_rate"),
        std=b.get("std"),
        claim_direction="positive",
    )
    repro = (
        f"Trade AI independent six-month window reproduction: "
        f"Nov–Apr n={b['n']} mean={b['mean']} win_rate={b['win_rate']}; "
        f"May–Oct n={w['n']} mean={w['mean']} win_rate={w['win_rate']}; "
        f"spread={spread}."
    )
    return {
        "key": "best_six_months",
        "source_claim": (
            "Almanac-tradition hypothesis (operator summary, not a book extract): "
            "November–April has often been stronger than May–October for broad US equities."
        ),
        "trade_ai_reproduction": repro,
        "n": b["n"],
        "mean": b["mean"],
        "win_rate": b["win_rate"],
        "worst_window": w,
        "spread": spread,
        "evidence_grade": graded["evidence_grade"],
        "oos_note": "Window comparison on the same monthly series used for month stats.",
        "current_applicability": _APPLICABILITY,
        "layers": {
            "source_claim": "Nov–Apr stronger than May–Oct (almanac-tradition hypothesis).",
            "trade_ai_reproduction": repro,
            "current_application": _APPLICABILITY,
        },
        "authority": AUTHORITY,
        "version": SEASONALITY_ANALYTICS_VERSION,
    }


def almanac_bundle(*, path: Optional[Path] = None, allow_network: bool = False) -> dict[str, Any]:
    return {
        "august_general": august_general(path=path, allow_network=allow_network),
        "august_midterm": august_midterm(path=path, allow_network=allow_network),
        "september_general": september_general(path=path, allow_network=allow_network),
        "september_midterm": september_midterm(path=path, allow_network=allow_network),
        "best_six_months": best_six_months(path=path, allow_network=allow_network),
        "weak_months_reproduced": sorted(reproduced_weak_months(path=path, allow_network=allow_network)),
        "strong_months_reproduced": sorted(reproduced_strong_months(path=path, allow_network=allow_network)),
        "authority": AUTHORITY,
        "version": SEASONALITY_ANALYTICS_VERSION,
    }


def month_headline(rec: dict[str, Any]) -> str:
    mean = rec.get("mean")
    wr = rec.get("win_rate")
    mean_s = "n/a" if mean is None else f"{mean:+.2f}%"
    wr_s = "n/a" if wr is None else f"{wr:.1%}"
    return (
        f"{rec.get('month_name')} {rec.get('cycle_label')}: "
        f"n={rec.get('n')} mean={mean_s} win_rate={wr_s} "
        f"grade={rec.get('evidence_grade')}"
    )

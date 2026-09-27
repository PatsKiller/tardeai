"""Reported fundamentals from SEC company facts (F1/F2 of the fundamentals plan, 2026-09-27).

Why: the platform stored no fundamentals (sec_xbrl 0 rows), so every symbol thesis was
narrative-only; DELL v2 said "no quantified AI server backlog or revenue figures".
SEC company facts carry them (DELL: revenue, margins, cash flow, remaining performance
obligations $132B).

Rules:
- official source only (data.sec.gov via financial_senses.sec_companyfacts_reader);
- a quarter is a ~90-day duration fact; a fiscal year is ~365 days; year-to-date
  facts are never treated as a quarter (DELL's "latest" revenue row is 6-month YTD);
- instants (cash, debt, shares, backlog) keyed by period end;
- restatements: the latest filed value for a (metric, form, period) wins; nothing is
  deleted; year-over-year compares like-for-like quarters only (same fiscal period,
  period end about one year earlier), otherwise no comparison is made.
Config: portfolio_intent.yaml fundamentals_feed. READ_ONLY_ADVISORY; MBI_BEHAVIOR=0.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONCEPTS: dict[str, list[str]] = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
    "remaining_performance_obligation": ["RevenueRemainingPerformanceObligation"],
}
INSTANT = {"cash", "long_term_debt", "shares_outstanding", "remaining_performance_obligation"}
DEFAULTS: dict[str, Any] = {"quarters_kept": 8, "years_kept": 3, "max_symbols_per_run": 120,
                            "stale_days_after_quarter": 100, "fix_per_run": 20,
                            "concepts": DEFAULT_CONCEPTS}


def settings(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if cfg is None:
        try:
            import yaml
            cfg = (yaml.safe_load((_ROOT / "assets" / "portfolio_intent.yaml").read_text()) or {}).get(
                "fundamentals_feed") or {}
        except Exception:  # noqa: BLE001
            cfg = {}
    return {k: (cfg or {}).get(k, v) for k, v in DEFAULTS.items()}


def _d(s: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def period_kind(start: Any, end: Any) -> Optional[str]:
    """quarter | year | ytd | instant from the fact's dates."""
    e = _d(end)
    if e is None:
        return None
    s = _d(start)
    if s is None:
        return "instant"
    days = (e - s).days
    if 80 <= days <= 100:
        return "quarter"
    if 350 <= days <= 380:
        return "year"
    return "ytd"


def filing_url(cik: str, accn: Optional[str]) -> str:
    if not accn:
        return ""
    return f"https://www.sec.gov/Archives/edgar/data/{str(cik).lstrip('0')}/{accn.replace('-', '')}/{accn}-index.htm"


def extract_rows(symbol: str, cik: str, facts: dict[str, Any], s: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for sec_xbrl: the last N quarters and years (instants at those period ends)."""
    gaap = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    out: list[dict[str, Any]] = []
    for metric, tags in (s.get("concepts") or DEFAULT_CONCEPTS).items():
        # The concept with the most recent data wins, not the first one present: Visa
        # stopped filing `Revenues` in 2019 and reports a newer concept since.
        def _latest_end(t: str) -> str:
            return max((str(r.get("end") or "") for rows in (gaap[t].get("units") or {}).values()
                        for r in rows or []), default="")
        present = [t for t in tags if t in gaap]
        if not present:
            continue
        tag = max(present, key=_latest_end)
        best: dict[tuple, dict[str, Any]] = {}
        for unit, rows in (gaap[tag].get("units") or {}).items():
            for r in rows or []:
                if r.get("val") is None or r.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                    continue
                kind = "instant" if metric in INSTANT else period_kind(r.get("start"), r.get("end"))
                if kind not in ("quarter", "year", "instant"):
                    continue
                key = (kind, r.get("start") or "", r.get("end"))
                if key not in best or str(r.get("filed") or "") > str(best[key].get("filed") or ""):
                    best[key] = {**r, "_kind": kind, "_unit": unit}
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for r in best.values():
            by_kind.setdefault(r["_kind"], []).append(r)
        keep = {"quarter": int(s["quarters_kept"]), "year": int(s["years_kept"]), "instant": int(s["quarters_kept"])}
        for kind, rows in by_kind.items():
            for r in sorted(rows, key=lambda x: x.get("end") or "", reverse=True)[: keep[kind]]:
                out.append({"symbol": symbol.upper(), "form_type": r.get("form"), "metric_name": metric,
                            "metric_value": float(r["val"]), "unit": r["_unit"],
                            "period_start": r.get("start"), "period_end": r.get("end"),
                            "filing_date": r.get("filed"), "sec_url": filing_url(cik, r.get("accn")),
                            "period_kind": kind, "fp": r.get("fp"), "fy": r.get("fy"), "tag": tag})
    return out


def _q(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    return sorted([r for r in rows if r["metric_name"] == metric and r.get("period_kind", _kind_of(r)) == "quarter"],
                  key=lambda r: str(r["period_end"]), reverse=True)


def _kind_of(r: dict[str, Any]) -> Optional[str]:
    return "instant" if r["metric_name"] in INSTANT else period_kind(r.get("period_start"), r.get("period_end"))


def _yoy(cur: dict[str, Any], rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Same metric, quarter ending ~1 year earlier (like-for-like), else None."""
    ce = _d(cur["period_end"])
    for r in rows:
        re_ = _d(r["period_end"])
        if ce and re_ and 350 <= (ce - re_).days <= 380 and r["metric_value"]:
            return r
    return None


def summarize(symbol: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Latest-quarter facts with YoY, margins and the latest instants. Numbers only from rows."""
    rows = [dict(r, period_kind=r.get("period_kind") or _kind_of(r)) for r in rows]
    out: dict[str, Any] = {"symbol": symbol.upper(), "facts": [], "latest_quarter_end": None}
    rev = _q(rows, "revenue")
    if rev:
        out["latest_quarter_end"] = str(rev[0]["period_end"])
    for metric in ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
                   "operating_cash_flow", "capex"):
        qs = _q(rows, metric)
        if not qs:
            continue
        cur = qs[0]
        prev = _yoy(cur, qs[1:])
        f = {"metric": metric, "value": cur["metric_value"], "unit": cur["unit"], "period_end": str(cur["period_end"]),
             "form": cur["form_type"], "filed": str(cur["filing_date"]), "sec_url": cur["sec_url"]}
        if prev:
            f["yoy_pct"] = round(100.0 * (cur["metric_value"] - prev["metric_value"]) / abs(prev["metric_value"]), 1)
            f["prior_period_end"] = str(prev["period_end"])
        out["facts"].append(f)
    if rev:
        r0 = rev[0]
        for m, name in (("gross_profit", "gross_margin_pct"), ("operating_income", "operating_margin_pct")):
            q = next((x for x in _q(rows, m) if str(x["period_end"]) == str(r0["period_end"])), None)
            if q and r0["metric_value"]:
                out[name] = round(100.0 * q["metric_value"] / r0["metric_value"], 1)
    for m in sorted(INSTANT):
        inst = sorted([r for r in rows if r["metric_name"] == m], key=lambda r: str(r["period_end"]), reverse=True)
        if inst:
            r = inst[0]
            out["facts"].append({"metric": m, "value": r["metric_value"], "unit": r["unit"],
                                 "period_end": str(r["period_end"]), "form": r["form_type"],
                                 "filed": str(r["filing_date"]), "sec_url": r["sec_url"]})
    return out


def _fmt(v: float, unit: str) -> str:
    if unit == "USD":
        a = abs(v)
        return (f"${v / 1e9:,.2f}B" if a >= 1e9 else f"${v / 1e6:,.1f}M" if a >= 1e6 else f"${v:,.0f}")
    if unit == "USD/shares":
        return f"${v:,.2f}"
    return f"{v:,.0f}"


def evidence_lines(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """One primary-filing evidence line per fact, e.g. 'DELL revenue $45.2B for quarter ended
    2026-07-31 (+18.4% YoY), 10-Q filed 2026-09-05'."""
    sym = summary.get("symbol")
    out = []
    for f in summary.get("facts") or []:
        what = f["metric"].replace("_", " ")
        when = f"for quarter ended {f['period_end']}" if f["metric"] not in INSTANT else f"as of {f['period_end']}"
        yoy = f" ({f['yoy_pct']:+.1f}% YoY vs {f['prior_period_end']})" if f.get("yoy_pct") is not None else ""
        out.append({"fact": f"{sym} {what} {_fmt(f['value'], f['unit'])} {when}{yoy}, {f['form']} filed {f['filed']}",
                    "sec_url": f["sec_url"], "filed": f["filed"], "metric": f["metric"]})
    for key, label in (("gross_margin_pct", "gross margin"), ("operating_margin_pct", "operating margin")):
        if summary.get(key) is not None:
            out.append({"fact": f"{sym} {label} {summary[key]}% for quarter ended {summary['latest_quarter_end']}",
                        "sec_url": "", "filed": "", "metric": key})
    return out


def freshness(summary: dict[str, Any], s: dict[str, Any], *, today: Optional[date] = None) -> str:
    """FRESH | STALE | UNAVAILABLE for an operating company's reported quarter."""
    end = _d(summary.get("latest_quarter_end"))
    if end is None:
        return "UNAVAILABLE"
    today = today or datetime.now().date()
    return "FRESH" if (today - end).days <= int(s["stale_days_after_quarter"]) else "STALE"


CARD_METRICS = ("revenue", "operating_income", "eps_diluted", "remaining_performance_obligation")
CARD_SQL = """SELECT symbol, form_type, metric_name, metric_value, unit, period_start, period_end,
                     filing_date, sec_url FROM sec_xbrl WHERE symbol=%s ORDER BY period_end DESC LIMIT 400"""


def card_block(symbol: str, execute, s: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Compact fundamentals for a card (fundamentals plan F5): state, latest quarter,
    up to four reported figures with YoY, margins, and the filing link. Numbers come
    only from sec_xbrl; an ETF or a symbol with no filings says so."""
    s = s or settings()
    try:
        rows = [dict(r) for r in (execute(CARD_SQL, (symbol.upper(),), fetch="all") or [])]
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return {"state": "UNAVAILABLE", "symbol": symbol.upper(), "lines": []}
    summ = summarize(symbol, rows)
    by = {f["metric"]: f for f in summ["facts"]}
    lines = [ln["fact"] for ln in evidence_lines({**summ, "facts": [by[m] for m in CARD_METRICS if m in by]})
             if not ln["metric"].endswith("_pct")]
    top = by.get("revenue") or next(iter(by.values()), {})
    return {"state": freshness(summ, s), "symbol": symbol.upper(), "latest_quarter_end": summ["latest_quarter_end"],
            "gross_margin_pct": summ.get("gross_margin_pct"), "operating_margin_pct": summ.get("operating_margin_pct"),
            "lines": lines, "filing_url": top.get("sec_url"), "source": "sec_xbrl"}

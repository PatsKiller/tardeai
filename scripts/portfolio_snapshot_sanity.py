"""portfolio_snapshot_sanity.py — reconcile market-day P&L vs snapshot-based performance.

Header "today" uses summed holding day_change (market move). Returns 1D used snapshot
deltas that could include reconciliation corrections (e.g. wrong share counts).
This module aligns 1D with market day, flags outlier snapshot dates, and sanitizes
drawdown series.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


# Portfolio-level: implied inter-snapshot move vs recorded day_change on newer snap
_RECON_TOTAL_PCT = 2.0
_RECON_TOTAL_GAP = 2.0
_RECON_DAY_CAP = 1.5

# Per-holding: MV jump between consecutive snapshots without a trade
_HOLDING_JUMP_PCT = 10.0

# Snapshot write guard: holding MV drift vs prior day with small market move
_WRITE_MV_DRIFT_PCT = 12.0
_WRITE_DAY_CAP_PCT = 2.0


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _day_pct(change: float, end_value: float) -> float:
    base = end_value - change
    return (change / base * 100) if base else 0.0


def portfolio_market_day(portfolio: dict | None) -> dict | None:
    """Canonical 1D return from portfolio_totals or summed holding day_change."""
    if not portfolio:
        return None
    totals = portfolio.get("portfolio_totals") or {}
    current = _f(totals.get("total_value"))
    if current <= 0:
        current = sum(
            _f(h.get("market_value"))
            for h in (portfolio.get("holdings") or [])
            if not h.get("is_loan")
        )
    if current <= 0:
        return None

    change = totals.get("day_change")
    pct = totals.get("day_change_pct")
    if change is None:
        change = sum(
            _f(h.get("day_change"))
            for h in (portfolio.get("holdings") or [])
            if not h.get("is_loan")
        )
    change = round(_f(change), 2)
    if pct is None:
        pct = round(_day_pct(change, current), 4)
    else:
        pct = round(_f(pct), 4)

    return {
        "period": "1D",
        "change": change,
        "change_pct": pct,
        "end_value": round(current, 2),
        "start_value": round(current - change, 2) if change else round(current, 2),
        "source": "market_day",
        "start_date": (date.today() - timedelta(days=1)).isoformat(),
    }


def account_market_days(portfolio: dict | None) -> dict[str, dict]:
    """Per-account 1D from account_summaries or summed holdings."""
    if not portfolio:
        return {}
    summaries = portfolio.get("account_summaries") or {}
    out: dict[str, dict] = {}

    by_acct_change: dict[str, float] = {}
    by_acct_value: dict[str, float] = {}
    for h in portfolio.get("holdings") or []:
        if h.get("is_loan"):
            continue
        acct = str(h.get("account") or "unknown")
        by_acct_change[acct] = by_acct_change.get(acct, 0.0) + _f(h.get("day_change"))
        by_acct_value[acct] = by_acct_value.get(acct, 0.0) + _f(h.get("market_value"))

    accounts = set(summaries) | set(by_acct_value)
    for acct in accounts:
        summ = summaries.get(acct) or {}
        cv = _f(summ.get("total_value")) or by_acct_value.get(acct, 0.0)
        if cv <= 0:
            continue
        chg = summ.get("day_change")
        pct = summ.get("day_change_pct")
        if chg is None:
            chg = by_acct_change.get(acct, 0.0)
        chg = round(_f(chg), 2)
        if pct is None:
            pct = round(_day_pct(chg, cv), 4)
        else:
            pct = round(_f(pct), 4)
        out[acct] = {
            "period": "1D",
            "change": chg,
            "change_pct": pct,
            "end_value": round(cv, 2),
            "start_value": round(cv - chg, 2),
            "source": "market_day",
            "start_date": (date.today() - timedelta(days=1)).isoformat(),
        }
    return out


def load_snapshots_from_dir(snap_dir: Path) -> list[dict]:
    """Load full snapshot dicts sorted by date ascending."""
    if not snap_dir.exists():
        return []
    snaps: list[dict] = []
    for f in sorted(snap_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            if d.get("date"):
                snaps.append(d)
        except Exception:
            continue
    return sorted(snaps, key=lambda s: str(s.get("date", "")))


def holding_phantom_corrections(snapshots: list[dict]) -> dict[str, float]:
    """
    Dollars to subtract from each snapshot total_value when holdings were
    temporarily overstated (e.g. wrong share count) then corrected.
    """
    corrections: dict[str, float] = {}
    sorted_snaps = sorted(snapshots, key=lambda s: str(s.get("date", "")))
    if len(sorted_snaps) < 2:
        return corrections

    for i in range(len(sorted_snaps) - 1):
        prev = sorted_snaps[i]
        nxt = sorted_snaps[i + 1]
        prev_hold = prev.get("holdings") or {}
        nxt_hold = nxt.get("holdings") or {}
        if not prev_hold or not nxt_hold:
            continue

        for key in set(prev_hold) & set(nxt_hold):
            ph, nh = prev_hold.get(key), nxt_hold.get(key)
            if not isinstance(ph, dict) or not isinstance(nh, dict):
                continue
            mv0 = _f(ph.get("market_value"))
            mv1 = _f(nh.get("market_value"))
            if mv0 <= 500 or mv1 <= 0:
                continue
            if abs(mv1 - mv0) / mv0 * 100 < _HOLDING_JUMP_PCT:
                continue
            excess = mv0 - mv1
            if excess <= 500:
                continue
            for k in range(i, max(i - 45, -1), -1):
                older = sorted_snaps[k]
                oh = (older.get("holdings") or {}).get(key)
                if not isinstance(oh, dict):
                    break
                omv = _f(oh.get("market_value"))
                if omv <= 500:
                    break
                if abs(omv - mv0) / mv0 <= 0.03:
                    d = str(older.get("date", ""))[:10]
                    corrections[d] = corrections.get(d, 0.0) + excess
                else:
                    break
    return {d: round(v, 2) for d, v in corrections.items()}


def find_reconciliation_outlier_dates(snapshots: list[dict]) -> set[str]:
    """
    Dates with stale reconciliation peaks (e.g. overstated share counts).

    Primary signal: per-holding MV jump between consecutive snapshots, propagated
    backward while the holding stayed at the inflated level. Secondary: portfolio/
    account totals inconsistent with the next snapshot's recorded day_change.
    """
    outliers: set[str] = set()
    if len(snapshots) < 2:
        return outliers

    corrections = holding_phantom_corrections(snapshots)
    outliers.update(corrections.keys())

    sorted_snaps = sorted(snapshots, key=lambda s: str(s.get("date", "")))
    for i in range(len(sorted_snaps) - 1):
        prev = sorted_snaps[i]
        nxt = sorted_snaps[i + 1]
        prev_date = str(prev.get("date", ""))
        v0 = _f(prev.get("total_value"))
        v1 = _f(nxt.get("total_value"))
        if v0 <= 0 or v1 <= 0:
            continue

        # Portfolio-level: only when day_change metadata exists on newer snap
        if "day_change" in nxt:
            implied_pct = (v1 - v0) / v0 * 100
            recorded_pct = _day_pct(_f(nxt.get("day_change")), v1)
            if (
                abs(implied_pct) >= 4.0
                and abs(recorded_pct) <= _RECON_DAY_CAP
                and abs(implied_pct - recorded_pct) >= 3.0
            ):
                outliers.add(prev_date)

        # Per-account reconciliation (stricter thresholds)
        prev_accts = prev.get("accounts") or {}
        nxt_accts = nxt.get("accounts") or {}
        for ak in set(prev_accts) & set(nxt_accts):
            if not isinstance(prev_accts[ak], dict) or not isinstance(nxt_accts[ak], dict):
                continue
            if "day_change" not in nxt_accts[ak]:
                continue
            a0 = _f(prev_accts[ak].get("value", prev_accts[ak].get("total_value")))
            a1 = _f(nxt_accts[ak].get("value", nxt_accts[ak].get("total_value")))
            if a0 <= 0 or a1 <= 0:
                continue
            a_implied = (a1 - a0) / a0 * 100
            a_recorded_pct = _day_pct(_f(nxt_accts[ak].get("day_change")), a1)
            if (
                abs(a_implied) >= 4.0
                and abs(a_recorded_pct) <= _RECON_DAY_CAP
                and abs(a_implied - a_recorded_pct) >= 3.0
            ):
                outliers.add(prev_date)

    return outliers


def corrected_snapshot_value(snap: dict, next_snap: dict | None) -> float:
    """Estimate prior close from next snapshot value minus its market day_change."""
    raw = _f(snap.get("total_value"))
    if not next_snap:
        return raw
    nxt_val = _f(next_snap.get("total_value"))
    nxt_day = _f(next_snap.get("day_change"))
    if nxt_val > 0:
        return round(nxt_val - nxt_day, 2)
    return raw


def sanitize_snapshot_totals(
    snapshots: list[dict],
    outlier_dates: set[str] | None = None,
) -> list[dict]:
    """Return chronological {date, value, corrected} points for drawdown."""
    corrections = holding_phantom_corrections(snapshots)
    if outlier_dates is None:
        outlier_dates = set(corrections.keys())
    points: list[dict] = []
    for snap in sorted(snapshots, key=lambda s: str(s.get("date", ""))):
        d = str(snap.get("date", ""))[:10]
        raw = _f(snap.get("total_value"))
        if raw <= 0:
            continue
        trim = corrections.get(d, 0.0)
        val = round(raw - trim, 2)
        points.append({
            "date": d,
            "value": val,
            "raw_value": raw,
            "phantom_trim": trim,
            "corrected": trim > 0,
        })
    return points


def compute_drawdown_series(
    snapshots: list[dict],
    outlier_dates: set[str] | None = None,
) -> list[dict]:
    """Underwater % from sanitized snapshot values."""
    points = sanitize_snapshot_totals(snapshots, outlier_dates)
    peak = 0.0
    out: list[dict] = []
    for pt in points:
        v = _f(pt.get("value"))
        if v <= 0:
            continue
        if v > peak:
            peak = v
        dd = round((v - peak) / peak * 100, 2) if peak > 0 else 0.0
        out.append({
            "date": pt["date"],
            "value": round(v, 0),
            "raw_value": round(_f(pt.get("raw_value")), 0),
            "drawdown": dd,
            "corrected": bool(pt.get("corrected")),
        })
    return out


def snapshot_period_return_reliable(
    change_pct: float | None,
    period: str,
    *,
    market_day_pct: float | None = None,
) -> bool:
    """True if snapshot-based return is trustworthy vs market day for 1D."""
    if change_pct is None:
        return False
    if period != "1D":
        return True
    if market_day_pct is None:
        return abs(change_pct) <= 3.0
    return abs(change_pct - market_day_pct) <= 1.5


def apply_market_day_1d(perf: dict, portfolio: dict | None) -> dict:
    """Overlay 1D periods with market_day and annotate snapshot outliers."""
    perf = dict(perf or {})
    md = portfolio_market_day(portfolio)
    if md:
        periods = dict(perf.get("periods") or {})
        old_1d = periods.get("1D") if isinstance(periods.get("1D"), dict) else {}
        if isinstance(old_1d, dict) and old_1d.get("source") not in ("market_day",):
            md = {
                **md,
                "snapshot_1d_pct": old_1d.get("change_pct"),
                "snapshot_1d_change": old_1d.get("change"),
                "snapshot_replaced": True,
            }
        periods["1D"] = md
        perf["periods"] = periods

    acct_md = account_market_days(portfolio)
    accounts = dict(perf.get("accounts") or {})
    for acct_key, md_acct in acct_md.items():
        entry = dict(accounts.get(acct_key) or {})
        periods = dict(entry.get("periods") or {})
        old = periods.get("1D") if isinstance(periods.get("1D"), dict) else {}
        if isinstance(old, dict) and old.get("source") not in ("market_day",):
            md_acct = {
                **md_acct,
                "snapshot_1d_pct": old.get("change_pct"),
                "snapshot_replaced": True,
            }
        periods["1D"] = md_acct
        entry["periods"] = periods
        if not entry.get("current_value"):
            entry["current_value"] = md_acct.get("end_value")
        accounts[acct_key] = entry
    perf["accounts"] = accounts
    return perf


def holding_write_sanity_issues(
    snapshot: dict,
    prev_snapshot: dict | None,
) -> list[str]:
    """Reasons to reject a new snapshot write (per-holding reconciliation drift)."""
    if not prev_snapshot:
        return []
    issues: list[str] = []
    prev_hold = prev_snapshot.get("holdings") or {}
    new_hold = snapshot.get("holdings") or {}
    for key, nh in new_hold.items():
        ph = prev_hold.get(key)
        if not isinstance(ph, dict) or not isinstance(nh, dict):
            continue
        mv0 = _f(ph.get("market_value"))
        mv1 = _f(nh.get("market_value"))
        if mv0 <= 500:
            continue
        drift = abs(mv1 - mv0) / mv0 * 100
        if drift < _WRITE_MV_DRIFT_PCT:
            continue
        sym = nh.get("symbol") or key.split(":")[0]
        acct = nh.get("account") or ""
        issues.append(
            f"{sym}@{acct}: MV {mv0:,.0f}→{mv1:,.0f} ({drift:.1f}%) without trade"
        )
    return issues


def snapshot_total_write_ok(
    snapshot: dict,
    prev_snapshot: dict | None,
    *,
    max_total_drift_pct: float = 25.0,
) -> tuple[bool, str]:
    """Combined guard for save_snapshot: total drift + holding reconciliation."""
    total = _f(snapshot.get("total_value"))
    if total <= 0:
        return False, "zero total_value"
    if prev_snapshot:
        prev_total = _f(prev_snapshot.get("total_value"))
        if prev_total > 0:
            drift = abs(total - prev_total) / prev_total * 100
            if drift > max_total_drift_pct:
                return False, f"total drift {drift:.1f}% > {max_total_drift_pct:.0f}%"
        holding_issues = holding_write_sanity_issues(snapshot, prev_snapshot)
        if holding_issues:
            return False, "; ".join(holding_issues[:3])
    return True, ""
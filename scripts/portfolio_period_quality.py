"""Annotate portfolio period returns for transfer / funding false-positives.

NAV Δ on a single account can be dominated by transfers (IRA → Roth/taxable) or by
funding a near-empty account. This module estimates market P/L vs net flow using a
household residual method on statement/snapshot series, and flags quality.

Adjusted return (simple residual method, per consecutive snapshot pair):
  household_ret = (H1 - H0) / H0
  expected_A    = V0_A * (1 + household_ret)
  flow_A        = V1_A - expected_A     # + = net transfer/contribution in
  market_pl_A   = expected_A - V0_A     # household-proportional market P/L

YTD adjusted ≈ sum(market_pl) over segments; net_flow ≈ sum(flow).

Not perfect TWR — good enough to stop false "−8% IRA wipeout" when money only moved
between household accounts. Prefer lot unrealized for name-level truth.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


ACCOUNT_KEYS = (
    "schwab_rollover_ira",
    "schwab_roth",
    "schwab_taxable",
    "fidelity_401k",
    "fidelity_rollover_ira",
    "fidelity_401k_brokerage",
)

# 401k → Rollover IRA is the same economic sleeve; history lives under either key.
FIDELITY_ECONOMIC = ("fidelity_401k", "fidelity_rollover_ira")
STANDARD_PERIODS = ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y")

# Dead / worthless lots: do not surface as "largest losers"
def is_dead_lot(h: dict) -> bool:
    try:
        mv = float(h.get("market_value") or 0)
    except (TypeError, ValueError):
        mv = 0.0
    if mv <= 1.0:
        return True
    sym = str(h.get("symbol") or "").upper()
    # known worthless / delisted stubs that may retain cost basis
    if sym in {"SRNE", "SNDL"} and mv < 50:
        return True
    # CUSIP-only / numeric symbols with no price
    if sym.isdigit() and mv < 50:
        return True
    return False


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def load_account_snapshot_series(state_dir: Path, holdings: dict | None = None) -> list[dict]:
    """Chronological [{date, acct: value, ...}, ...] plus live holdings totals if provided."""
    snap_dir = Path(state_dir) / "snapshots"
    series: list[dict] = []
    if snap_dir.is_dir():
        for f in sorted(snap_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            ac = d.get("accounts") or {}
            if not ac:
                continue
            row: dict[str, Any] = {"date": str(d.get("date") or f.stem)[:10]}
            for k, v in ac.items():
                if isinstance(v, dict):
                    row[k] = _f(v.get("value", v.get("total_value")))
                else:
                    row[k] = _f(v)
            # Linked economic Fidelity sleeve (401k renamed → rollover)
            row["_fidelity_economic"] = sum(_f(row.get(k)) for k in FIDELITY_ECONOMIC)
            series.append(row)

    if holdings:
        live: dict[str, Any] = {"date": date.today().isoformat(), "live": True}
        for h in holdings.get("holdings") or []:
            a = str(h.get("account") or "unknown")
            live[a] = live.get(a, 0.0) + _f(h.get("market_value"))
        live["_fidelity_economic"] = sum(_f(live.get(k)) for k in FIDELITY_ECONOMIC)
        # only append if we have values
        if any(isinstance(v, (int, float)) and v > 0 for k, v in live.items() if k not in ("date", "live")):
            series.append(live)
    return series


def _snap_on_or_before(series: list[dict], start_date: str) -> dict | None:
    """Last non-live snapshot on or before start_date with any positive account value."""
    cands = [
        r for r in series
        if not r.get("live") and str(r.get("date", ""))[:10] <= start_date[:10]
    ]
    return cands[-1] if cands else None


def fidelity_economic_at(
    series: list[dict], start_date: str, *, allow_first_after: bool = False
) -> tuple[float | None, str | None, bool]:
    """NAV of linked Fidelity sleeve (401k + rollover) at/near start_date.

    Returns (value, snap_date, partial) where partial=True if we had to use the
    first available observation *after* start_date (history gap before sleeve
    entered snapshots — e.g. 1Y before Dec-2025 Fidelity series).
    """
    # Prefer last snap on/before start with economic > 0
    for r in reversed([x for x in series if not x.get("live") and str(x.get("date", ""))[:10] <= start_date[:10]]):
        val = _f(r.get("_fidelity_economic"))
        if val > 0:
            return val, str(r.get("date"))[:10], False
    if allow_first_after:
        for r in series:
            if r.get("live"):
                continue
            val = _f(r.get("_fidelity_economic"))
            if val > 0:
                return val, str(r.get("date"))[:10], True
    return None, None, False


def account_nav_at(
    series: list[dict], account: str, start_date: str, *, allow_partial: bool = False
) -> tuple[float | None, str | None, bool]:
    """Single-account NAV on/before start_date. Fidelity accounts use economic link.

    Returns (value, snap_date, partial_history).
    """
    if account in FIDELITY_ECONOMIC:
        return fidelity_economic_at(series, start_date, allow_first_after=allow_partial)
    for r in reversed([x for x in series if not x.get("live") and str(x.get("date", ""))[:10] <= start_date[:10]]):
        val = _f(r.get(account))
        if val > 0:
            return val, str(r.get("date"))[:10], False
    if allow_partial:
        for r in series:
            if r.get("live"):
                continue
            val = _f(r.get(account))
            if val > 0:
                return val, str(r.get("date"))[:10], True
    return None, None, False


def fill_missing_period_cells(
    accounts: dict,
    series: list[dict],
    holdings: dict | None = None,
) -> dict:
    """Fill empty 1W/1M/3M/6M/1Y (and YTD shell) from snapshots.

    Critical for Fidelity Rollover IRA: performance_history only knew fidelity_401k,
    so after the mid-year 401k→rollover rename every multi-day period was missing.
    """
    # Live current values from holdings when available
    live_cv: dict[str, float] = {}
    if holdings:
        for h in holdings.get("holdings") or []:
            a = str(h.get("account") or "")
            if a:
                live_cv[a] = live_cv.get(a, 0.0) + _f(h.get("market_value"))

    for acct, data in list(accounts.items()):
        if not isinstance(data, dict):
            continue
        cv = _f(live_cv.get(acct) if acct in live_cv else data.get("current_value"))
        if cv <= 0:
            continue
        data["current_value"] = round(cv, 2)
        periods = dict(data.get("periods") or {})

        for period in STANDARD_PERIODS:
            if period == "1D":
                continue  # market-day overlay owns 1D
            cell = periods.get(period)
            has_change = isinstance(cell, dict) and cell.get("change") is not None
            if has_change:
                continue

            start_date = _default_start(period)
            # 1Y may predate Fidelity snapshot history — allow first available obs
            allow_partial = period in ("1Y", "6M")
            hist_val, hist_date, partial = account_nav_at(
                series, acct, start_date, allow_partial=allow_partial
            )
            if hist_val is None or hist_val <= 0:
                # leave missing
                if not isinstance(cell, dict):
                    periods[period] = None
                continue

            # Guard: never use a catastrophic live end vs recent snap (partial sync / UI lag)
            # Classic false: end $472k vs $564k week-ago → fake −16% week.
            if hist_val > 50_000 and cv > 0 and cv < 0.85 * hist_val and period in (
                "1D", "1W", "1M", "3M"
            ):
                # Prefer last good snap end over suspect live
                last_good, last_d, _ = account_nav_at(series, acct, date.today().isoformat())
                if last_good and last_good > cv * 1.05:
                    cv = last_good
            change = round(cv - hist_val, 2)
            change_pct = round((change / hist_val) * 100, 2) if hist_val else None
            src = "snapshot_linked" if acct in FIDELITY_ECONOMIC else "snapshot_fill"
            if partial:
                src = f"{src}_partial"
            note = (
                "Fidelity economic sleeve (401k+rollover) NAV at period start → current"
                if acct in FIDELITY_ECONOMIC else
                "Filled from account snapshot series (missing in performance_history)"
            )
            if partial:
                note = (
                    f"Partial history: first Fidelity snapshot {hist_date} "
                    f"(no holdings series on {start_date}). NAV Δ since then, not full {period}."
                )
            periods[period] = {
                "period": period,
                "start_date": hist_date or start_date,
                "start_value": round(hist_val, 2),
                "end_value": round(cv, 2),
                "change": change,
                "change_pct": change_pct,
                "display_change": change,
                "display_change_pct": change_pct,
                "display_label": "NAV (linked)" if acct in FIDELITY_ECONOMIC else "NAV",
                "source": src,
                "partial_history": partial,
                "linked_accounts": list(FIDELITY_ECONOMIC) if acct in FIDELITY_ECONOMIC else None,
                "note": note,
            }
        data["periods"] = periods
        accounts[acct] = data
    return accounts


def _segment_market_and_flow(v0: dict[str, float], v1: dict[str, float]) -> tuple[dict[str, float], dict[str, float], float]:
    accts = set(v0) | set(v1)
    H0 = sum(v0.get(a, 0.0) for a in accts)
    H1 = sum(v1.get(a, 0.0) for a in accts)
    if H0 <= 0:
        return {}, {}, 0.0
    mret = (H1 - H0) / H0
    market_pl: dict[str, float] = {}
    flow: dict[str, float] = {}
    for a in accts:
        b, e = v0.get(a, 0.0), v1.get(a, 0.0)
        if b <= 0 and e > 0:
            market_pl[a] = 0.0
            flow[a] = e  # pure inflow / conversion
        elif b > 0:
            expected = b * (1.0 + mret)
            market_pl[a] = expected - b
            flow[a] = e - expected
        else:
            market_pl[a] = 0.0
            flow[a] = 0.0
    return market_pl, flow, mret


def _row_household_total(row: dict) -> float:
    """Sum known account sleeves (prefer explicit keys; fall back to numeric fields)."""
    total = sum(_f(row.get(k)) for k in ACCOUNT_KEYS)
    if total > 0:
        return total
    return sum(
        _f(v) for k, v in row.items()
        if k not in ("date", "live", "_fidelity_economic") and isinstance(v, (int, float))
    )


def filter_outlier_snapshots(series: list[dict], *, drop_frac: float = 0.08) -> list[dict]:
    """Drop non-live snaps that look like partial/wipe recon (big drop then recover).

    Keeps live rows. Classic case: 2026-07-14 Schwab rollover $557k→$448k while live is ~$579k.
    """
    non_live = [r for r in series if not r.get("live")]
    live = [r for r in series if r.get("live")]
    if len(non_live) < 3:
        return series

    totals = [_row_household_total(r) for r in non_live]
    drop: set[int] = set()
    for i in range(1, len(non_live)):
        prev_t, t = totals[i - 1], totals[i]
        if prev_t <= 0 or t <= 0:
            continue
        # Catastrophic one-day drop
        if t < (1.0 - drop_frac) * prev_t:
            # Confirm it's an outlier: next good point recovers toward prev, or no next
            nxt = None
            for j in range(i + 1, min(i + 4, len(non_live))):
                if totals[j] > 0:
                    nxt = totals[j]
                    break
            if nxt is None or nxt > 0.95 * prev_t or t < 0.90 * prev_t:
                drop.add(i)
        # Also drop total-only stubs (no account keys) that aren't useful
        if not any(_f(non_live[i].get(k)) > 0 for k in ACCOUNT_KEYS):
            drop.add(i)

    cleaned = [r for i, r in enumerate(non_live) if i not in drop]
    # Preserve chronological order: cleaned non-live then live
    return cleaned + live


def last_account_level_snapshot(series: list[dict], end_date: str | None = None) -> dict | None:
    """Most recent non-live snapshot that has per-account values (not total-only stubs)."""
    end_date = end_date or date.today().isoformat()
    for r in reversed(series):
        if r.get("live"):
            continue
        d = str(r.get("date", ""))[:10]
        if d > end_date[:10]:
            continue
        # Require at least one known account key with value > 0
        if any(_f(r.get(k)) > 0 for k in ACCOUNT_KEYS):
            return r
    return None


def estimate_adjusted_return(
    series: list[dict],
    account: str,
    start_date: str,
    end_date: str | None = None,
    *,
    use_live: bool = True,
) -> dict[str, Any]:
    """Sum market_pl and flow for `account` between start_date and end_date (inclusive path).

    use_live=True (default): end path at live holdings so residual reflects current portfolio.
    Outlier/partial snapshots are stripped before building the path. Daily pin freezes the
    result so live MTM does not re-jitter the UI every request.
    """
    end_date = end_date or date.today().isoformat()
    series = filter_outlier_snapshots(series)

    # Anchor: last snapshot on or before period start (YTD often uses 12-31 prior year)
    before = [r for r in series if not r.get("live") and str(r.get("date", ""))[:10] <= start_date]
    mid = [
        r for r in series
        if not r.get("live") and start_date < str(r.get("date", ""))[:10] <= end_date
    ]
    # Drop total-only stubs from mid (no per-account keys)
    mid = [r for r in mid if any(_f(r.get(k)) > 0 for k in ACCOUNT_KEYS)]
    path: list[dict] = []
    if before:
        # prefer last before with account data
        for r in reversed(before):
            if any(_f(r.get(k)) > 0 for k in ACCOUNT_KEYS) or _f(r.get(account)) > 0:
                path.append(r)
                break
        if not path:
            path.append(before[-1])
    path.extend(mid)

    live_rows = [r for r in series if r.get("live")] if use_live else []
    if live_rows:
        path.append(live_rows[-1])
    else:
        end_snap = last_account_level_snapshot(series, end_date)
        if end_snap is not None and (
            not path or str(path[-1].get("date")) != str(end_snap.get("date"))
        ):
            path.append(end_snap)

    # ensure sorted with live last
    path = sorted(path, key=lambda r: (0 if not r.get("live") else 1, str(r.get("date", ""))))

    if len(path) < 2:
        return {
            "ok": False,
            "reason": "insufficient_snapshots",
            "market_pl": None,
            "net_flow": None,
            "adjusted_change": None,
            "adjusted_change_pct": None,
        }

    # start value = first row with account > 0 or first row
    start_val = _f(path[0].get(account))
    end_val = _f(path[-1].get(account))
    mpl_sum = 0.0
    flow_sum = 0.0
    for i in range(len(path) - 1):
        v0 = {a: _f(path[i].get(a)) for a in ACCOUNT_KEYS if a in path[i] or a in path[i + 1]}
        v1 = {a: _f(path[i + 1].get(a)) for a in ACCOUNT_KEYS if a in path[i] or a in path[i + 1]}
        # include any extra keys present
        for r in (path[i], path[i + 1]):
            for k, v in r.items():
                if k in ("date", "live", "_fidelity_economic"):
                    continue
                if isinstance(v, (int, float)):
                    v0.setdefault(k, _f(path[i].get(k)))
                    v1.setdefault(k, _f(path[i + 1].get(k)))
        mpl, fl, _ = _segment_market_and_flow(v0, v1)
        mpl_sum += mpl.get(account, 0.0)
        flow_sum += fl.get(account, 0.0)

    pct = round((mpl_sum / start_val) * 100, 2) if start_val > 0 else None
    end_label = str(path[-1].get("date"))
    used_live = bool(path[-1].get("live"))
    method = "household_residual_live_end" if used_live else "household_residual_snapshot_end"
    note = (
        "Approx market P/L after removing estimated transfers/contributions (household residual). "
        "End = live holdings; path excludes outlier snapshots. Daily pin freezes this for the UI."
        if used_live else
        f"YTD ≈ market ending at snapshot {end_label} (no live row). Outlier snaps excluded."
    )
    return {
        "ok": True,
        "start_date": str(path[0].get("date")),
        "end_date": end_label + (" (live)" if used_live else ""),
        "start_value": round(start_val, 2),
        "end_value": round(end_val, 2),
        "nav_change": round(end_val - start_val, 2),
        "market_pl": round(mpl_sum, 2),
        "net_flow": round(flow_sum, 2),
        "adjusted_change": round(mpl_sum, 2),
        "adjusted_change_pct": pct,
        "method": method,
        "used_live_end": used_live,
        "note": note,
    }


# ── Daily YTD pin (stable display across API calls) ───────────────────────────

YTD_PIN_FILENAME = "ytd_daily_pin.json"


def _ytd_pin_path(state_dir: Path) -> Path:
    return Path(state_dir) / YTD_PIN_FILENAME


def ytd_pin_end_key(series: list[dict]) -> str:
    """Label for what the residual ended on (live preferred)."""
    for r in reversed(series):
        if r.get("live"):
            return f"{str(r.get('date'))[:10]}-live"
    snap = last_account_level_snapshot(filter_outlier_snapshots(series))
    return str(snap.get("date"))[:10] if snap else date.today().isoformat()


def load_ytd_pin(state_dir: Path) -> dict | None:
    p = _ytd_pin_path(state_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_ytd_pin(state_dir: Path, pin: dict) -> None:
    p = _ytd_pin_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(pin, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(p)


def apply_or_build_ytd_pin(
    state_dir: Path,
    accounts: dict,
    port_ytd: dict | None,
    *,
    end_snapshot: str,
    force: bool = False,
) -> tuple[dict, dict | None, dict]:
    """Reuse today's YTD display pin for the calendar day; else build & persist.

    First successful compute of the day freezes ≈ market YTD (per account + portfolio).
    Subsequent API calls return the same numbers until the next calendar day
    (or force=True / YTD_PIN_FORCE=1). Does not re-key on end_snapshot so a later
    bad EOD snap cannot replace a good morning pin mid-day.
    """
    import os
    force = force or os.environ.get("YTD_PIN_FORCE", "").strip() in ("1", "true", "yes")
    today = date.today().isoformat()
    existing = None if force else load_ytd_pin(state_dir)

    # Reject pins that look like bad residual (all deeply negative while live books are up)
    def _pin_plausible(pin: dict) -> bool:
        port = pin.get("portfolio_ytd") or {}
        dc = port.get("display_change")
        if dc is None:
            return False
        # Household residual should not claim multi-tens-of-k wipeout if we already
        # know individuals were positive under live-end residual historically (~+$50k).
        # Soft guard: pin with |portfolio| > $200k absolute is almost always a bad path.
        if abs(_f(dc)) > 200_000:
            return False
        return True

    # Invalidate pins from older logic (funding % rewrite)
    pin_version = "2026-07-15c"
    if (
        existing
        and existing.get("pin_date") == today
        and existing.get("pin_version") == pin_version
        and isinstance(existing.get("accounts"), dict)
        and _pin_plausible(existing)
    ):
        for acct, ycell in (existing.get("accounts") or {}).items():
            if acct not in accounts or not isinstance(accounts[acct], dict):
                continue
            if not isinstance(ycell, dict):
                continue
            periods = accounts[acct].setdefault("periods", {})
            cur = periods.get("YTD") if isinstance(periods.get("YTD"), dict) else {}
            merged = {
                **cur, **ycell,
                "ytd_pinned": True,
                "ytd_pin_date": today,
                "ytd_pin_snapshot": existing.get("end_snapshot") or end_snapshot,
            }
            # Re-apply funding % sanitizer so stale pins with +150% Roth don't stick
            sane_pct, pct_meta = funding_sane_display_pct(
                merged.get("display_change"),
                start_value=merged.get("start_value") or merged.get("linked_start_value"),
                end_value=merged.get("end_value") or (accounts[acct] or {}).get("current_value"),
                quality=merged.get("quality"),
                flags=merged.get("flags"),
                raw_pct=merged.get("display_change_pct"),
            )
            merged["display_change_pct"] = sane_pct
            if pct_meta.get("economic_start_value") is not None:
                merged["economic_start_value"] = pct_meta["economic_start_value"]
                merged["linked_start_value"] = pct_meta["economic_start_value"]
            if pct_meta.get("display_pct_note"):
                merged["display_pct_note"] = pct_meta["display_pct_note"]
            periods["YTD"] = merged
        pin_port = existing.get("portfolio_ytd")
        if isinstance(pin_port, dict) and isinstance(port_ytd, dict):
            port_ytd = {
                **port_ytd, **pin_port,
                "ytd_pinned": True,
                "ytd_pin_date": today,
                "ytd_pin_snapshot": existing.get("end_snapshot") or end_snapshot,
            }
        elif isinstance(pin_port, dict):
            port_ytd = {
                **pin_port,
                "ytd_pinned": True,
                "ytd_pin_date": today,
                "ytd_pin_snapshot": existing.get("end_snapshot") or end_snapshot,
            }
        return accounts, port_ytd, {
            "hit": True,
            "pin_date": today,
            "end_snapshot": existing.get("end_snapshot") or end_snapshot,
            "source": "ytd_daily_pin",
            "created_at": existing.get("created_at"),
            "pin_version": pin_version,
        }

    # Build pin from current computed YTD cells
    pin_accounts: dict[str, dict] = {}
    for acct, data in accounts.items():
        if not isinstance(data, dict):
            continue
        y = (data.get("periods") or {}).get("YTD")
        if not isinstance(y, dict):
            continue
        pin_accounts[acct] = {
            "period": "YTD",
            "display_change": y.get("display_change"),
            "display_change_pct": y.get("display_change_pct"),
            "display_label": y.get("display_label"),
            "adjusted_change": y.get("adjusted_change"),
            "adjusted_change_pct": y.get("adjusted_change_pct"),
            "estimated_net_flow": y.get("estimated_net_flow"),
            "adjustment_method": y.get("adjustment_method"),
            "adjustment_note": y.get("adjustment_note"),
            "start_value": y.get("start_value"),
            "linked_start_value": y.get("linked_start_value"),
            "end_value": y.get("end_value"),
            "change": y.get("change"),
            "change_pct": y.get("change_pct"),
            "quality": y.get("quality"),
            "flags": y.get("flags"),
            "is_false_positive": y.get("is_false_positive"),
            "nav_is_not_market_only": y.get("nav_is_not_market_only"),
            "provenance_note": y.get("provenance_note"),
            "transfer_notes": y.get("transfer_notes"),
            "start_date": y.get("start_date"),
            "source": y.get("source"),
            "ytd_pinned": True,
            "ytd_pin_date": today,
            "ytd_pin_snapshot": end_snapshot,
        }
        y["ytd_pinned"] = True
        y["ytd_pin_date"] = today
        y["ytd_pin_snapshot"] = end_snapshot
        data.setdefault("periods", {})["YTD"] = y

    pin_port = None
    if isinstance(port_ytd, dict):
        pin_port = {
            "period": "YTD",
            "display_change": port_ytd.get("display_change"),
            "display_change_pct": port_ytd.get("display_change_pct"),
            "display_label": port_ytd.get("display_label"),
            "change": port_ytd.get("change"),
            "change_pct": port_ytd.get("change_pct"),
            "nav_change": port_ytd.get("nav_change"),
            "nav_change_pct": port_ytd.get("nav_change_pct"),
            "quality": port_ytd.get("quality"),
            "flags": port_ytd.get("flags"),
            "nav_is_not_market_only": port_ytd.get("nav_is_not_market_only"),
            "adjustment_note": port_ytd.get("adjustment_note"),
            "ytd_pinned": True,
            "ytd_pin_date": today,
            "ytd_pin_snapshot": end_snapshot,
        }
        port_ytd = {**port_ytd, **pin_port}

    pin_doc = {
        "_description": (
            "Daily YTD ≈ market pin. First successful compute of pin_date freezes display "
            "values for the rest of the day so residual/live MTM does not wobble in the UI. "
            "Refreshes next calendar day (or YTD_PIN_FORCE=1). pin_version bumps invalidate old pins."
        ),
        "pin_date": today,
        "pin_version": "2026-07-15c",
        "end_snapshot": end_snapshot,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "accounts": pin_accounts,
        "portfolio_ytd": pin_port,
    }
    # Don't persist an implausible pin (bad residual path)
    if _pin_plausible(pin_doc):
        try:
            save_ytd_pin(state_dir, pin_doc)
        except Exception:
            pass
        src = "computed_and_pinned"
    else:
        src = "computed_not_pinned_implausible"
    return accounts, port_ytd, {
        "hit": False,
        "pin_date": today,
        "end_snapshot": end_snapshot,
        "source": src,
    }


def funding_sane_display_pct(
    display_change: float | None,
    *,
    start_value: float | None,
    end_value: float | None,
    quality: str | None = None,
    flags: list | None = None,
    raw_pct: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Rewrite misleading % when year-start capital was tiny (Roth funding / conversion).

    Uses economic base ≈ end − market P/L so +$2.7k on a ~$48k Roth is ~+5–6%, not +150%+.
    Returns (pct_or_None, meta).
    """
    flags = list(flags or [])
    funding = (
        quality == "funding_false_positive"
        or "funding_baseline" in flags
        or "conversion_or_funding" in flags
    )
    ch = display_change
    if ch is None:
        return raw_pct, {}
    sv, ev = _f(start_value), _f(end_value)
    # Also treat absurd % as funding even if classifier missed
    if raw_pct is not None and abs(_f(raw_pct)) > 80 and ev > 0 and sv < 0.15 * ev:
        funding = True
    if not funding:
        return raw_pct, {}

    # Capital that "supported" the residual market P/L
    econ = ev - _f(ch)
    if econ < max(5_000.0, 0.15 * max(ev, 1.0)):
        # Still nonsense — suppress % entirely (show $ only)
        return None, {
            "display_pct_suppressed": True,
            "display_pct_note": "Funding/conversion baseline — % suppressed; trust $ P/L only",
            "display_pct_basis": "suppressed",
        }
    pct = round(_f(ch) / econ * 100, 2)
    return pct, {
        "display_pct_suppressed": False,
        "display_pct_note": (
            f"% vs economic capital ${econ:,.0f} (end − ≈ market P/L), "
            f"not year-start NAV ${sv:,.0f}"
        ),
        "display_pct_basis": "economic_end_minus_market_pl",
        "economic_start_value": round(econ, 2),
    }


def classify_period_quality(
    period: str,
    start_value: float | None,
    end_value: float | None,
    change: float | None,
    change_pct: float | None,
    adjusted: dict | None = None,
) -> dict[str, Any]:
    """Return quality flags for a single period cell."""
    sv = _f(start_value)
    ev = _f(end_value) if end_value is not None else 0.0
    ch = change
    cp = change_pct
    flags: list[str] = []
    quality = "reliable"

    # Funding / empty-baseline false positive (classic Roth)
    if sv > 0 and ev > 0 and sv < max(2000.0, 0.10 * ev) and cp is not None and abs(cp) > 100:
        flags.append("funding_baseline")
        quality = "funding_false_positive"
    # Also: tiny start vs large end even if raw % wasn't computed yet
    if sv > 0 and ev > 0 and sv < max(2000.0, 0.10 * ev) and ch is not None and abs(_f(ch)) > 500:
        if "funding_baseline" not in flags:
            flags.append("funding_baseline")
        if quality == "reliable":
            quality = "funding_false_positive"
    # Account appeared mid-period (401k→rollover conversion, new funding)
    if sv <= 0 and ev > 5000:
        flags.append("conversion_or_funding")
        quality = "funding_false_positive"

    # Large NAV move with offsetting estimated flow
    if adjusted and adjusted.get("ok"):
        flow = abs(_f(adjusted.get("net_flow")))
        if sv > 0 and flow > 0.05 * sv:
            flags.append("includes_transfers")
            if quality == "reliable":
                quality = "includes_transfers"
        if sv <= 0 and flow > 1000:
            flags.append("includes_transfers")
        # if NAV and adjusted disagree a lot, surface it
        if ch is not None and adjusted.get("adjusted_change") is not None:
            if abs(ch - _f(adjusted["adjusted_change"])) > max(1000.0, 0.03 * max(sv, 1)):
                flags.append("nav_vs_market_gap")

    # Impossible short-period returns already guarded upstream — keep label if present
    if cp is not None and period in ("1D", "1W") and abs(cp) > 25:
        flags.append("extreme_short_period")
        quality = "suspect"

    return {
        "quality": quality,
        "flags": flags,
        "is_false_positive": quality in ("funding_false_positive", "suspect"),
        "nav_is_not_market_only": "includes_transfers" in flags or "funding_baseline" in flags,
    }


def annotate_performance_result(result: dict, state_dir: Path, holdings: dict | None = None) -> dict:
    """Mutate/enrich portfolio_performance() result with quality + adjusted YTD fields."""
    series = load_account_snapshot_series(state_dir, holdings)
    today = date.today().isoformat()
    accounts = result.get("accounts") or {}

    # Also ensure fidelity_rollover present from live holdings if missing
    if holdings:
        live_accts: dict[str, float] = defaultdict(float)
        for h in holdings.get("holdings") or []:
            live_accts[str(h.get("account") or "")] += _f(h.get("market_value"))
        for ak, cv in live_accts.items():
            if not ak or cv <= 0:
                continue
            if ak not in accounts:
                accounts[ak] = {"current_value": round(cv, 2), "periods": {}}
            else:
                # Keep current_value live (performance_history can lag)
                accounts[ak]["current_value"] = round(cv, 2)

    # Fill 1W/1M/… for accounts that only have 1D (Fidelity after 401k→rollover rename)
    accounts = fill_missing_period_cells(accounts, series, holdings)

    for acct, data in list(accounts.items()):
        if not isinstance(data, dict):
            continue
        cv = _f(data.get("current_value"))
        periods = data.get("periods") or {}
        # Synthesize YTD shell when missing (e.g. fidelity_rollover after 401k conversion)
        if "YTD" not in periods or periods.get("YTD") is None:
            periods["YTD"] = {
                "period": "YTD",
                "start_date": _default_start("YTD"),
                "change": None,
                "change_pct": None,
                "source": "synthesized",
            }
        new_periods = {}
        for period, cell in periods.items():
            if not isinstance(cell, dict):
                new_periods[period] = cell
                continue
            start_date = cell.get("start_date") or (
                f"{date.today().year}-01-01" if period == "YTD" else None
            )
            # fill start_date defaults for common periods
            if not start_date:
                start_date = _default_start(period)

            # Residual transfer adjustment is only reliable for YTD (year-start statement anchor).
            # Live end + outlier-filtered path; daily pin freezes display for the day.
            adjusted = None
            if start_date and period == "YTD":
                adjusted = estimate_adjusted_return(
                    series, acct, str(start_date)[:10], today, use_live=True
                )

            # Prefer stored start_value; else from adjusted
            sv = cell.get("start_value")
            if sv is None and adjusted and adjusted.get("start_value") is not None:
                sv = adjusted["start_value"]
            ev = cell.get("end_value")
            if period == "YTD" and adjusted and adjusted.get("end_value") is not None:
                # YTD end = pinned snapshot, not live
                ev = adjusted["end_value"]
            if ev is None:
                ev = cv
            ch = cell.get("change")
            if period == "YTD" and adjusted and adjusted.get("nav_change") is not None:
                # Align raw NAV change to pinned end as well
                ch = adjusted["nav_change"]
                if sv and _f(sv) > 0:
                    cp = round(_f(ch) / _f(sv) * 100, 2)
                else:
                    cp = cell.get("change_pct")
            else:
                cp = cell.get("change_pct")

            q = classify_period_quality(period, sv, ev, ch, cp, adjusted if period == "YTD" else None)

            enriched = {
                **cell,
                "start_value": sv,
                "end_value": ev if ev is not None else cv,
                "quality": q["quality"] if period == "YTD" else (cell.get("quality") or "reliable"),
                "flags": q["flags"] if period == "YTD" else [],
                "is_false_positive": q["is_false_positive"] if period == "YTD" else False,
                "nav_is_not_market_only": q["nav_is_not_market_only"] if period == "YTD" else False,
            }
            if period == "YTD" and adjusted and adjusted.get("ok"):
                enriched["change"] = ch
                enriched["change_pct"] = cp
                enriched["adjusted_change"] = adjusted["adjusted_change"]
                enriched["adjusted_change_pct"] = adjusted["adjusted_change_pct"]
                enriched["estimated_net_flow"] = adjusted["net_flow"]
                enriched["adjustment_method"] = adjusted["method"]
                enriched["adjustment_note"] = adjusted["note"]
                enriched["ytd_end_snapshot"] = adjusted.get("end_date")
                # Prefer adjusted as "real" when transfers/funding OR raw NAV missing
                if q["nav_is_not_market_only"] or cell.get("change") is None:
                    enriched["display_change"] = adjusted["adjusted_change"]
                    enriched["display_change_pct"] = adjusted["adjusted_change_pct"]
                    enriched["display_label"] = "≈ market (ex-transfers)"
                else:
                    enriched["display_change"] = ch
                    enriched["display_change_pct"] = cp
                    enriched["display_label"] = "NAV"
                # Roth / funding: rewrite absurd % vs economic capital (not $1.7k year-start)
                sane_pct, pct_meta = funding_sane_display_pct(
                    enriched.get("display_change"),
                    start_value=enriched.get("start_value") or sv,
                    end_value=enriched.get("end_value") or ev,
                    quality=enriched.get("quality"),
                    flags=enriched.get("flags"),
                    raw_pct=enriched.get("display_change_pct"),
                )
                enriched["display_change_pct"] = sane_pct
                if pct_meta.get("economic_start_value") is not None:
                    enriched["economic_start_value"] = pct_meta["economic_start_value"]
                    # Prefer economic base for portfolio Σ % too
                    enriched["linked_start_value"] = pct_meta["economic_start_value"]
                if pct_meta.get("display_pct_note"):
                    enriched["display_pct_note"] = pct_meta["display_pct_note"]
                if pct_meta.get("display_pct_basis"):
                    enriched["display_pct_basis"] = pct_meta["display_pct_basis"]
                if pct_meta.get("display_pct_suppressed"):
                    enriched["display_pct_suppressed"] = True
            else:
                # Non-YTD: always show period NAV (snapshot/reprice for that window)
                enriched["display_change"] = ch
                enriched["display_change_pct"] = cp
                enriched["display_label"] = "NAV"
            new_periods[period] = enriched
        data["periods"] = new_periods
        accounts[acct] = data

    # Fidelity economic IRA: 401k rolled into fidelity_rollover — combine market P/L for YTD only
    fr = accounts.get("fidelity_rollover_ira")
    if isinstance(fr, dict):
        y_fr = (fr.get("periods") or {}).get("YTD")
        y_fr = y_fr if isinstance(y_fr, dict) else {}
        adj4 = estimate_adjusted_return(
            series, "fidelity_401k", _default_start("YTD"), today, use_live=True
        )
        adj_r = estimate_adjusted_return(
            series, "fidelity_rollover_ira", _default_start("YTD"), today, use_live=True
        )
        mpl = _f(adj4.get("adjusted_change")) + _f(adj_r.get("adjusted_change"))
        start_401k = _f(adj4.get("start_value"))
        pct = round(mpl / start_401k * 100, 2) if start_401k > 0 else None
        fl = list(y_fr.get("flags") or [])
        for f in ("conversion_or_funding", "includes_transfers", "linked_401k"):
            if f not in fl:
                fl.append(f)
        end_snap = adj_r.get("end_date") or adj4.get("end_date")
        # Since rollover account first appeared (for operator audit — not YTD false positive)
        since_open_nav = None
        since_open_pct = None
        open_anchor = None
        try:
            # first non-live snap with fidelity_rollover > 0
            for r in series:
                if r.get("live"):
                    continue
                fr_v = _f(r.get("fidelity_rollover_ira"))
                if fr_v > 1000:
                    open_anchor = str(r.get("date"))[:10]
                    open_start = fr_v
                    open_end = _f(adj_r.get("end_value")) or cv
                    since_open_nav = round(open_end - open_start, 2)
                    since_open_pct = round(since_open_nav / open_start * 100, 2) if open_start > 0 else None
                    break
        except Exception:
            pass

        y_fr = {
            **y_fr,
            "quality": "includes_transfers",
            "flags": fl,
            # NOT a funding false positive: money existed all year as 401k
            "is_false_positive": False,
            "nav_is_not_market_only": True,
            "adjusted_change": round(mpl, 2),
            "adjusted_change_pct": pct,
            "display_change": round(mpl, 2),
            "display_change_pct": pct,
            "display_label": "≈ market YTD (401k continuous)",
            "adjustment_note": (
                "NOT a 2-month-only return. Fidelity Rollover IRA label opened mid-year "
                f"({open_anchor or 'mid-year'}) when 401k converted; economic sleeve was the "
                f"401k from year-start ${start_401k:,.0f}. "
                f"YTD ≈ market P/L ${mpl:,.0f} ({pct}% on that base). "
                + (
                    f"Since account-open NAV Δ ${since_open_nav:,.0f} ({since_open_pct}%) "
                    f"from {open_anchor} — separate from YTD."
                    if since_open_nav is not None else ""
                )
            ),
            "adjustment_method": adj_r.get("method") or "household_residual_live_end",
            "linked_start_value": start_401k,
            "start_value": start_401k if start_401k > 0 else y_fr.get("start_value"),
            "end_value": adj_r.get("end_value") or y_fr.get("end_value"),
            "ytd_end_snapshot": end_snap,
            "estimated_net_flow": round(_f(adj4.get("net_flow")) + _f(adj_r.get("net_flow")), 2),
            "since_account_open_date": open_anchor,
            "since_account_open_change": since_open_nav,
            "since_account_open_change_pct": since_open_pct,
            "audit": {
                "ytd_is_false_positive": False,
                "reason": (
                    "YTD links fidelity_401k (held since year-start) + fidelity_rollover_ira "
                    "after conversion. Residual splits market P/L from the conversion flow."
                ),
                "year_start_401k": start_401k,
                "combined_market_pl": round(mpl, 2),
                "since_open_nav_change": since_open_nav,
            },
        }
        fr.setdefault("periods", {})["YTD"] = y_fr
        fr["performance_note"] = y_fr["adjustment_note"]
        accounts["fidelity_rollover_ira"] = fr

    # Re-fill multi-day periods after YTD mutations so Fidelity 1W/1M never drop off the response
    accounts = fill_missing_period_cells(accounts, series, holdings)
    # Ensure filled cells have display_* for Home/Returns (fill only sets change)
    for acct, data in list(accounts.items()):
        if not isinstance(data, dict):
            continue
        periods = data.get("periods") or {}
        for period, cell in list(periods.items()):
            if not isinstance(cell, dict):
                continue
            if cell.get("display_change") is None and cell.get("change") is not None:
                cell["display_change"] = cell.get("change")
                cell["display_change_pct"] = cell.get("change_pct")
                cell.setdefault("display_label", "NAV")
            periods[period] = cell
        data["periods"] = periods
        accounts[acct] = data

    # Per-account transfer provenance notes (rollover / Roth ladder) for UI badges
    xfer_notes: dict[str, list[str]] = {}
    try:
        from lib.position_transfer_normalize import account_transfer_notes_ytd
        xfer_notes = account_transfer_notes_ytd(state_dir)
    except Exception:
        xfer_notes = {}

    for acct, data in list(accounts.items()):
        if not isinstance(data, dict):
            continue
        notes = list(xfer_notes.get(acct) or [])
        # Also pull live holding-level notes
        if holdings:
            for h in holdings.get("holdings") or []:
                if str(h.get("account") or "") != acct:
                    continue
                n = h.get("transfer_display_note")
                if n and n not in notes:
                    notes.append(str(n))
                if h.get("normalized_after_transfer") and "Position normalized after rollover/transfer" not in notes:
                    # keep short for table
                    pass
        ytd = (data.get("periods") or {}).get("YTD")
        if isinstance(ytd, dict):
            # Prefer specific provenance labels when residual already active
            if notes:
                # Pick the most specific note for display_label secondary
                preferred = None
                for cand in (
                    "includes Fidelity rollover",
                    "Roth conversion – performance carried forward",
                    "includes external rollover",
                    "ex-transfers",
                ):
                    if cand in notes:
                        preferred = cand
                        break
                if preferred is None:
                    preferred = notes[0]
                ytd["transfer_notes"] = notes
                if ytd.get("nav_is_not_market_only") or ytd.get("display_label", "").startswith("≈"):
                    # Keep ≈ market primary; append provenance
                    base = ytd.get("display_label") or "≈ market (ex-transfers)"
                    if preferred not in base:
                        ytd["display_label"] = f"{base} · {preferred}"
                elif ytd.get("quality") in ("includes_transfers", "funding_false_positive"):
                    ytd["display_label"] = preferred
                    ytd["nav_is_not_market_only"] = True
                ytd["provenance_note"] = preferred
            data.setdefault("periods", {})["YTD"] = ytd
            data["transfer_notes"] = notes
        accounts[acct] = data

    result["accounts"] = accounts
    result["transfer_season"] = {
        "notes_by_account": xfer_notes,
        "active_kinds": sorted({
            n for ns in xfer_notes.values() for n in ns
        }),
    }
    try:
        from lib.position_transfer_normalize import list_active_notifications
        result["transfer_notifications"] = list_active_notifications()
    except Exception:
        result["transfer_notifications"] = []

    # Portfolio-level periods: SUM of per-account display values so aggregate matches individuals
    port_periods = result.get("periods") or {}
    for period, cell in list(port_periods.items()):
        if not isinstance(cell, dict):
            continue

        def _acct_period(a: str) -> dict:
            p = ((accounts.get(a) or {}).get("periods") or {}).get(period)
            return p if isinstance(p, dict) else {}

        disp_sum = 0.0
        start_sum = 0.0
        n_disp = 0
        any_adj = False
        any_xfer = False
        any_fund = False
        for a in accounts:
            ap = _acct_period(a)
            if not ap:
                continue
            if "includes_transfers" in (ap.get("flags") or []) or ap.get("nav_is_not_market_only"):
                any_xfer = True
            if ap.get("quality") == "funding_false_positive" or "funding_baseline" in (ap.get("flags") or []):
                any_fund = True
            dc = ap.get("display_change")
            if dc is None:
                dc = ap.get("change")
            if dc is not None:
                disp_sum += _f(dc)
                n_disp += 1
            # start capital for % : linked_start or start_value
            sv = ap.get("linked_start_value")
            if sv is None:
                sv = ap.get("start_value")
            if sv is not None and _f(sv) > 0:
                start_sum += _f(sv)
            if ap.get("display_label", "").startswith("≈"):
                any_adj = True

        flags = list(cell.get("flags") or [])
        if any_xfer and "includes_transfers" not in flags:
            flags.append("includes_transfers")
        if any_fund and "funding_baseline" not in flags:
            flags.append("funding_baseline")

        # Always Σ accounts for every period once we have ≥1 sleeve with data
        # (Fidelity linked fills must appear in All 1W/1M, not Schwab-only NAV).
        if n_disp > 0:
            # Prefer economic_start / linked_start for % when present (Roth funding)
            start_sum = 0.0
            for a in accounts:
                ap = _acct_period(a)
                if not ap:
                    continue
                sv = ap.get("economic_start_value")
                if sv is None:
                    sv = ap.get("linked_start_value")
                if sv is None:
                    sv = ap.get("start_value")
                if sv is not None and _f(sv) > 0 and (
                    ap.get("display_change") is not None or ap.get("change") is not None
                ):
                    start_sum += _f(sv)
            disp_pct = round(disp_sum / start_sum * 100, 2) if start_sum > 0 else None
            cell = {
                **cell,
                "flags": flags,
                "nav_is_not_market_only": bool(flags) or period == "YTD",
                "quality": "includes_transfers" if any_xfer else ("funding_mixed" if any_fund else cell.get("quality", "reliable")),
                "display_change": round(disp_sum, 2),
                "display_change_pct": disp_pct,
                "display_label": (
                    "Σ account ≈ market" if any_adj or period == "YTD" else "Σ accounts"
                ),
                "nav_change": cell.get("change"),
                "nav_change_pct": cell.get("change_pct"),
                "adjustment_note": (
                    f"Sum of per-account display P/L ({n_disp} accounts). "
                    f"Raw portfolio NAV was {cell.get('change')} ({cell.get('change_pct')}%)."
                ),
            }
        else:
            cell = {
                **cell,
                "flags": flags,
                "nav_is_not_market_only": bool(flags),
                "quality": "includes_transfers" if any_xfer else cell.get("quality", "reliable"),
                "display_change": cell.get("change"),
                "display_change_pct": cell.get("change_pct"),
                "display_label": "NAV",
            }
        port_periods[period] = cell

    # Force every standard period onto portfolio from Σ accounts (includes Fidelity fills)
    for period in STANDARD_PERIODS:
        disp_sum = 0.0
        start_sum = 0.0
        n_disp = 0
        for a, data in accounts.items():
            if not isinstance(data, dict):
                continue
            ap = (data.get("periods") or {}).get(period)
            if not isinstance(ap, dict):
                continue
            dc = ap.get("display_change")
            if dc is None:
                dc = ap.get("change")
            if dc is None:
                continue
            disp_sum += _f(dc)
            n_disp += 1
            sv = ap.get("economic_start_value")
            if sv is None:
                sv = ap.get("linked_start_value")
            if sv is None:
                sv = ap.get("start_value")
            if sv is not None and _f(sv) > 0:
                start_sum += _f(sv)
        if n_disp > 0:
            disp_pct = round(disp_sum / start_sum * 100, 2) if start_sum > 0 else None
            prior = port_periods.get(period) if isinstance(port_periods.get(period), dict) else {}
            port_periods[period] = {
                **prior,
                "period": period,
                "display_change": round(disp_sum, 2),
                "display_change_pct": disp_pct,
                "display_label": prior.get("display_label") or "Σ accounts",
                "source": prior.get("source") or "sum_accounts",
                # Keep raw NAV in change if already present
                "change": prior.get("change") if prior.get("change") is not None else round(disp_sum, 2),
                "change_pct": prior.get("change_pct") if prior.get("change_pct") is not None else disp_pct,
            }
    result["periods"] = port_periods

    # Daily YTD pin: freeze ≈ market numbers to last account-level snapshot for the day
    end_key = ytd_pin_end_key(series)
    port_ytd = port_periods.get("YTD") if isinstance(port_periods.get("YTD"), dict) else None
    accounts, port_ytd, pin_meta = apply_or_build_ytd_pin(
        state_dir, accounts, port_ytd, end_snapshot=end_key
    )
    if isinstance(port_ytd, dict):
        port_periods["YTD"] = port_ytd
    result["accounts"] = accounts
    result["periods"] = port_periods
    result["ytd_pin"] = pin_meta

    result["period_quality_note"] = (
        "YTD '≈ market' is computed once per day (first request) and pinned so it does not "
        f"wobble with live prices (pin end={end_key}). Outlier snapshots excluded from residual path. "
        "All-accounts YTD = sum of account ≈ market rows. "
        "1D still uses live market day. 1W/1M/… use linked NAV (Fidelity 401k→Rollover). "
        "Transfers/rollovers: ex-transfers notes; residual strips funding false positives. "
        "Dead $0 lots excluded from name losers. Force refresh: YTD_PIN_FORCE=1."
    )
    return result


def _default_start(period: str) -> str:
    today = date.today()
    if period == "YTD":
        return date(today.year, 1, 1).isoformat()
    if period == "1Y":
        try:
            return date(today.year - 1, today.month, today.day).isoformat()
        except ValueError:
            return date(today.year - 1, today.month, 28).isoformat()
    if period == "6M":
        m = today.month - 6
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return date(y, m, min(today.day, 28)).isoformat()
    if period == "3M":
        m = today.month - 3
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return date(y, m, min(today.day, 28)).isoformat()
    if period == "1M":
        m = today.month - 1
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return date(y, m, min(today.day, 28)).isoformat()
    if period == "1W":
        from datetime import timedelta
        return (today - timedelta(days=7)).isoformat()
    return today.isoformat()

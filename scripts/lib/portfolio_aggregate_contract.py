"""PortfolioAggregate@v1 — all-accounts header total with honest observation clocks.

The Command Center header total is an ALL-ACCOUNTS aggregate. A named account is
only ever the oldest/stale contributor, never the source of the whole total.

Live acceptance (2026-09-03, candidate abbe880e) failed because overview mixed
two clocks: top-level `data_as_of` / `data_as_of_account` for "oldest", and
`account_summaries[*].as_of` for "newest" and the accounts[] rows. That produced
oldest=alpaca@2026-09-03 while accounts[] carried schwab_rollover_ira@2026-07-17
and newest=2026-07-17 (chronologically before the claimed oldest).

Rule: oldest and newest are derived ONLY from the same accounts[] observation
times that the contract publishes. Empty observation times are omitted from
min/max (they cannot date the aggregate). Top-level data_as_of may inform a
missing per-account stamp when the account name matches, but never overrides a
dated account row that is older.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


CONTRACT_VERSION = "PortfolioAggregate@v1"
SCOPE_ALL_ACCOUNTS = "ALL_ACCOUNTS"


def _parse_obs(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Date-only stamps compare as UTC midnight so ordering is stable.
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime(int(s[:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _obs_key(value: Any) -> str:
    """Sortable key: prefer full ISO, fall back to raw string for date-only."""
    dt = _parse_obs(value)
    if dt is not None:
        return dt.isoformat()
    return str(value).strip()


def build_account_observations(
    account_summaries: Any,
    *,
    data_as_of: Any = None,
    data_as_of_account: Any = None,
) -> list[dict[str, Any]]:
    """Project account_summaries into the aggregate accounts[] rows.

    When an account's own as_of is empty but it is the named data_as_of_account,
    stamp that account with data_as_of so the row is dated. Never invent stamps
    for other accounts.
    """
    summaries = account_summaries if isinstance(account_summaries, dict) else {}
    named = str(data_as_of_account or "").strip()
    fallback = str(data_as_of or "").strip()
    out: list[dict[str, Any]] = []
    for acct, row in summaries.items():
        if not isinstance(row, dict):
            continue
        obs = row.get("as_of") or row.get("reported_total_as_of") or ""
        obs = str(obs).strip() if obs is not None else ""
        if not obs and named and acct == named and fallback:
            obs = fallback
        out.append(
            {
                "account": acct,
                "custodian": row.get("source", "") or "",
                "total_value": row.get("total_value"),
                "holdings_count": row.get("holdings_count"),
                "observation_time": obs,
                "received_time": row.get("last_import", "") or "",
                "freshness": "UNKNOWN",
            }
        )
    return out


def derive_observation_bounds(
    accounts: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (oldest_time, oldest_account, newest_time) from dated account rows.

    Undated rows are excluded. If no dated rows exist, all three are None.
    """
    dated: list[tuple[str, str, str]] = []
    for row in accounts:
        obs = row.get("observation_time")
        if not obs or not str(obs).strip():
            continue
        acct = str(row.get("account") or "?")
        raw = str(obs).strip()
        dated.append((_obs_key(raw), raw, acct))
    if not dated:
        return None, None, None
    dated.sort(key=lambda t: t[0])
    oldest_raw, oldest_acct = dated[0][1], dated[0][2]
    newest_raw = dated[-1][1]
    return oldest_raw, oldest_acct, newest_raw


def build_portfolio_aggregate(
    *,
    aggregate_value: Any,
    account_summaries: Any,
    data_as_of: Any = None,
    data_as_of_account: Any = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the PortfolioAggregate@v1 envelope for /api/v2/overview."""
    accounts = build_account_observations(
        account_summaries,
        data_as_of=data_as_of,
        data_as_of_account=data_as_of_account,
    )
    oldest_obs, oldest_acct, newest_obs = derive_observation_bounds(accounts)

    # Invariant: when both bounds exist, oldest <= newest (by parsed time).
    if oldest_obs and newest_obs:
        o_dt, n_dt = _parse_obs(oldest_obs), _parse_obs(newest_obs)
        if o_dt is not None and n_dt is not None and o_dt > n_dt:
            # Fail closed: refuse to publish a reversed pair.
            oldest_obs, oldest_acct, newest_obs = None, None, None

    agg_state = "UNAVAILABLE"
    agg_reason = "no account observations"
    if accounts:
        agg_state = "COMPLETE"
        agg_reason = f"{len(accounts)} account(s) contributing"
        if oldest_obs is None:
            agg_state = "PARTIAL"
            agg_reason = f"{len(accounts)} account(s); no dated observation rows"
        else:
            now_utc = now or datetime.now(timezone.utc)
            if now_utc.tzinfo is None:
                now_utc = now_utc.replace(tzinfo=timezone.utc)
            odt = _parse_obs(oldest_obs)
            age_h = None
            if odt is not None:
                age_h = (now_utc - odt).total_seconds() / 3600.0
            if age_h is None or age_h > 48:
                agg_state = "STALE"
                agg_reason = f"oldest observation: {oldest_acct or '?'} {oldest_obs}" + (
                    f" ({age_h:.0f}h)" if age_h is not None else " (undated)"
                )

    return {
        "contract_version": CONTRACT_VERSION,
        "portfolio_scope": SCOPE_ALL_ACCOUNTS,
        # Acceptance harness / reconciliation CSV alias (same value).
        "aggregate_scope": SCOPE_ALL_ACCOUNTS,
        "aggregate_value": aggregate_value,
        "included_account_count": len(accounts),
        "oldest_observation_time": oldest_obs,
        "oldest_observation_account": oldest_acct,
        "newest_observation_time": newest_obs,
        "freshness_state": agg_state,
        "freshness_reason": agg_reason,
        "accounts": accounts,
        "read_only": True,
    }

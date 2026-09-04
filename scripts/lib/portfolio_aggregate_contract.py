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

v2 (live acceptance 2026-09-04, release a7c550d1d) — THE CLOCKS WERE ONE FIELD
-----------------------------------------------------------------------------
v1 published a single `observation_time` per account and dated the whole
aggregate by it. That field is the POSITION observation: when the share counts
were last seen. It is not when the money was valued. On the live book those are
months apart:

    schwab_rollover_ira  as_of 2026-07-17   <- share counts observed (v1 used this)
                         last_repriced 2026-09-04  <- total_value computed
                         reported_total_as_of 2026-04-30  <- broker's own total
                         total_value 1,158,374.79  (90% of the whole book)

So the header read "data_as_of 2026-09-03" (the NEWEST position observation,
alpaca) over a total whose dominant contributor had not had its shares observed
since July, priced with quotes observed 2026-09-04 13:30 ET. Three clocks, one
label, and the label named none of them. No amount of UI wording can fix that:
the producer only ever emitted one number, so the UI had nothing truthful to
render.

v2 publishes each clock under its own name and never derives one from another:

    position_observation_time  when THIS account's share counts were observed
    valuation_time             when total_value was computed for it
    reported_total_as_of       the custodian's own stated total, and its date
    received_time              when the bytes arrived from the custodian

and at the aggregate level adds `value_dated_pct` — the share of aggregate VALUE
whose position observation is within the freshness window. That is the number
that makes a fresh-looking date over a stale book impossible to state: the live
book is 3.9% by value at the newest observation, not 100%.

The v1 field names are retained as exact aliases so existing readers do not
break; they are documented as the position clock they always were.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


CONTRACT_VERSION = "PortfolioAggregate@v2"
# v1 readers key off this string; kept so they can assert lineage.
SUPERSEDES_VERSION = "PortfolioAggregate@v1"
SCOPE_ALL_ACCOUNTS = "ALL_ACCOUNTS"

# A position observation older than this no longer dates the aggregate as fresh.
STALE_AFTER_HOURS = 48.0


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


def _age_hours(value: Any, now: datetime) -> Optional[float]:
    dt = _parse_obs(value)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 3600.0, 2)


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build_account_observations(
    account_summaries: Any,
    *,
    data_as_of: Any = None,
    data_as_of_account: Any = None,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Project account_summaries into the aggregate accounts[] rows.

    Every clock the custodian row carries is published under its own name. The
    v1 name `observation_time` is retained as an exact alias of
    `position_observation_time` -- it always WAS the position clock, it was just
    never labelled as one.

    When an account's own as_of is empty but it is the named data_as_of_account,
    stamp that account with data_as_of so the row is dated. Never invent stamps
    for other accounts, and never borrow the valuation clock to date a position.
    """
    summaries = account_summaries if isinstance(account_summaries, dict) else {}
    named = str(data_as_of_account or "").strip()
    fallback = str(data_as_of or "").strip()
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    out: list[dict[str, Any]] = []
    for acct, row in summaries.items():
        if not isinstance(row, dict):
            continue
        # The POSITION clock. reported_total_as_of is a last resort and is also
        # published separately so a reader can tell which one dated the row.
        obs = row.get("as_of") or row.get("reported_total_as_of") or ""
        obs = str(obs).strip() if obs is not None else ""
        obs_source = "account.as_of" if str(row.get("as_of") or "").strip() else ""
        if not obs_source and obs:
            obs_source = "account.reported_total_as_of"
        if not obs and named and acct == named and fallback:
            obs = fallback
            obs_source = "holdings.data_as_of"

        valuation = str(row.get("last_repriced") or "").strip()
        reported_as_of = str(row.get("reported_total_as_of") or "").strip()

        out.append(
            {
                "account": acct,
                "custodian": row.get("source", "") or "",
                "total_value": row.get("total_value"),
                "holdings_count": row.get("holdings_count"),
                # ── the four clocks, each named ──────────────────────────────
                "position_observation_time": obs,
                "position_observation_source": obs_source,
                "position_observation_age_hours": _age_hours(obs, now_utc),
                "valuation_time": valuation,
                "reported_total_as_of": reported_as_of,
                "reported_total_value": row.get("reported_total_value"),
                "received_time": row.get("last_import", "") or "",
                "dated": bool(obs),
                # v1 alias -- same value, honest name above.
                "observation_time": obs,
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


def coverage_by_value(
    accounts: list[dict[str, Any]],
    *,
    newest_obs: Optional[str],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """How much of the aggregate VALUE the headline date actually speaks for.

    The defect this exists to make unstateable: 90% of the live book's value sat
    behind a 2026-07-17 position observation while the header was dated
    2026-09-03 off a $5,000 account. Both numbers were true; together they were
    a lie. A date over an aggregate means nothing without the share of value it
    covers.

    `at_newest_pct` is the share of value observed at the newest observation --
    i.e. how much of the total the headline date is entitled to describe.
    `fresh_pct` is the share observed within STALE_AFTER_HOURS.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    total = 0.0
    dated_val = 0.0
    fresh_val = 0.0
    newest_val = 0.0
    dated_n = 0
    undated: list[str] = []

    newest_key = _obs_key(newest_obs) if newest_obs else None

    for row in accounts:
        val = abs(_num(row.get("total_value")) or 0.0)
        total += val
        obs = row.get("position_observation_time") or ""
        if not obs:
            undated.append(str(row.get("account") or "?"))
            continue
        dated_n += 1
        dated_val += val
        age = row.get("position_observation_age_hours")
        if age is not None and age <= STALE_AFTER_HOURS:
            fresh_val += val
        if newest_key is not None and _obs_key(obs) == newest_key:
            newest_val += val

    def pct(part: float) -> Optional[float]:
        if total <= 0:
            return None
        return round(100.0 * part / total, 1)

    return {
        "accounts_total": len(accounts),
        "accounts_dated": dated_n,
        "accounts_undated": len(undated),
        "undated_accounts": sorted(undated),
        "aggregate_value_abs": round(total, 2),
        "value_dated_pct": pct(dated_val),
        "value_fresh_pct": pct(fresh_val),
        "at_newest_pct": pct(newest_val),
        "stale_after_hours": STALE_AFTER_HOURS,
    }


def build_portfolio_aggregate(
    *,
    aggregate_value: Any,
    account_summaries: Any,
    data_as_of: Any = None,
    data_as_of_account: Any = None,
    valuation_time: Any = None,
    quote_observation_time: Any = None,
    quote_source: Any = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the PortfolioAggregate@v2 envelope for /api/v2/overview.

    `valuation_time` (when the aggregate value was computed) and
    `quote_observation_time` (when the marks behind it were observed) are
    SEPARATE inputs and are never derived from the position observations. A
    caller that does not have them gets nulls, not a substitute clock.
    """
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    accounts = build_account_observations(
        account_summaries,
        data_as_of=data_as_of,
        data_as_of_account=data_as_of_account,
        now=now_utc,
    )
    oldest_obs, oldest_acct, newest_obs = derive_observation_bounds(accounts)

    # Invariant: when both bounds exist, oldest <= newest (by parsed time).
    if oldest_obs and newest_obs:
        o_dt, n_dt = _parse_obs(oldest_obs), _parse_obs(newest_obs)
        if o_dt is not None and n_dt is not None and o_dt > n_dt:
            # Fail closed: refuse to publish a reversed pair.
            oldest_obs, oldest_acct, newest_obs = None, None, None

    newest_acct = None
    if newest_obs:
        nk = _obs_key(newest_obs)
        for row in accounts:
            if row.get("position_observation_time") and _obs_key(row["position_observation_time"]) == nk:
                newest_acct = row.get("account")
                break

    coverage = coverage_by_value(accounts, newest_obs=newest_obs, now=now_utc)
    oldest_age = _age_hours(oldest_obs, now_utc) if oldest_obs else None

    agg_state = "UNAVAILABLE"
    agg_reason = "no account observations"
    if accounts:
        agg_state = "COMPLETE"
        agg_reason = f"{len(accounts)} account(s) contributing"
        if oldest_obs is None:
            agg_state = "PARTIAL"
            agg_reason = f"{len(accounts)} account(s); no dated observation rows"
        else:
            if oldest_age is None or oldest_age > STALE_AFTER_HOURS:
                agg_state = "STALE"
                agg_reason = f"oldest observation: {oldest_acct or '?'} {oldest_obs}" + (
                    f" ({oldest_age:.0f}h)" if oldest_age is not None else " (undated)"
                )
            elif coverage.get("accounts_undated"):
                # Every dated row is fresh, but some value carries no date at
                # all. That is PARTIAL coverage, not a complete fresh book.
                agg_state = "PARTIAL"
                agg_reason = (
                    f"{coverage['accounts_undated']} of {coverage['accounts_total']} account(s) undated"
                    f" ({coverage.get('value_dated_pct')}% of value dated)"
                )

    return {
        "contract_version": CONTRACT_VERSION,
        "supersedes_version": SUPERSEDES_VERSION,
        "portfolio_scope": SCOPE_ALL_ACCOUNTS,
        # Acceptance harness / reconciliation CSV alias (same value).
        "aggregate_scope": SCOPE_ALL_ACCOUNTS,
        "aggregate_value": aggregate_value,
        "included_account_count": len(accounts),
        # ── clock 1+2: position observation bounds (what v1 published) ────────
        "position_observation_oldest": oldest_obs,
        "position_observation_oldest_account": oldest_acct,
        "position_observation_oldest_age_hours": oldest_age,
        "position_observation_newest": newest_obs,
        "position_observation_newest_account": newest_acct,
        # ── clock 3: when the aggregate value was computed ────────────────────
        "valuation_time": str(valuation_time or "") or None,
        # ── clock 4: when the marks behind that value were observed ───────────
        "quote_observation_time": str(quote_observation_time or "") or None,
        "quote_source": str(quote_source or "") or None,
        # ── how much of the value the headline date speaks for ────────────────
        "coverage": coverage,
        "freshness_state": agg_state,
        "freshness_reason": agg_reason,
        "accounts": accounts,
        "read_only": True,
        # v1 aliases -- identical values, position-clock semantics.
        "oldest_observation_time": oldest_obs,
        "oldest_observation_account": oldest_acct,
        "newest_observation_time": newest_obs,
    }

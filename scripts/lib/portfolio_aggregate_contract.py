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


def _rows_by_account(positions: Any) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not isinstance(positions, list):
        return out
    for row in positions:
        if not isinstance(row, dict):
            continue
        acct = str(row.get("account") or "").strip()
        if not acct:
            continue
        out.setdefault(acct, []).append(row)
    return out


def _oldest_row_observation(rows: list[dict]) -> tuple[Optional[str], Optional[str]]:
    """The account's position observation is its STALEST row.

    An account's book is only as freshly observed as the least recently observed
    holding in it. Taking the newest would let one re-synced row date the rest.
    """
    stamps: list[tuple[str, str, str]] = []
    for row in rows:
        raw = row.get("broker_position_as_of") or row.get("as_of") or ""
        raw = str(raw).strip()
        if not raw:
            continue
        field = "broker_position_as_of" if row.get("broker_position_as_of") else "as_of"
        stamps.append((_obs_key(raw), raw, field))
    if not stamps:
        return None, None
    stamps.sort(key=lambda t: t[0])
    return stamps[0][1], f"holdings.{stamps[0][2]}"


def build_account_observations(
    account_summaries: Any,
    *,
    data_as_of: Any = None,
    data_as_of_account: Any = None,
    positions: Any = None,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Project account_summaries into the aggregate accounts[] rows.

    Every clock the account carries is published under its own name. The v1 name
    `observation_time` is retained as an exact alias of
    `position_observation_time` -- it always WAS the position clock, it was just
    never labelled as one.

    WHERE THE POSITION CLOCK COMES FROM (2026-09-04, second pass)
    -------------------------------------------------------------
    v2 read `account_summaries[acct]["as_of"]`. That field is not maintained.
    `portfolio_loader.build_account_summaries` rewrites total_value,
    holdings_count, last_repriced, day_change and display_name on every run and
    never touches `as_of`, so it holds whatever some earlier path last wrote:
    2026-07-17 for schwab_rollover_ira, and nothing at all for schwab_roth,
    schwab_taxable and moomoo_taxable_live.

    The position ROWS are maintained. `schwab_position_sync` rebuilds them from
    the live broker response on every sync, stamping `broker_position_as_of`,
    and those rows said 2026-09-04 while the summary said 2026-07-17. Reading
    the abandoned mirror is what produced "99.6% of the book unobserved since
    July" -- the book had been observed that morning; only the summary was old.

    So the position clock is derived from the rows, and the summary's `as_of` is
    published beside it as `summary_as_of` with an explicit
    `observation_divergence` when the two disagree. Neither copy is edited and
    neither is silently dropped: a reader can see both and which one governs.

    On the stamp's meaning: `broker_position_as_of` is set to the sync date, not
    a broker-supplied timestamp. For a pull API that returns *current* positions
    that is the honest observation instant -- what was observed is the broker's
    book at the moment of the call. It is still NOT the valuation clock, which
    is `last_repriced` and is published separately.

    When an account's own stamp is empty and it is the named data_as_of_account,
    the top-level data_as_of dates it. Never invent stamps for other accounts,
    and never borrow the valuation clock to date a position.
    """
    summaries = account_summaries if isinstance(account_summaries, dict) else {}
    named = str(data_as_of_account or "").strip()
    fallback = str(data_as_of or "").strip()
    rows_by_acct = _rows_by_account(positions)
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    out: list[dict[str, Any]] = []
    for acct, row in summaries.items():
        if not isinstance(row, dict):
            continue
        rows = rows_by_acct.get(acct, [])
        summary_as_of = str(row.get("as_of") or "").strip()

        # 1) the maintained store: the account's own position rows
        obs, obs_source = _oldest_row_observation(rows)
        # 2) the unmaintained summary field, only when there are no rows
        if not obs and summary_as_of:
            obs, obs_source = summary_as_of, "account_summaries.as_of"
        if not obs and str(row.get("reported_total_as_of") or "").strip():
            obs = str(row["reported_total_as_of"]).strip()
            obs_source = "account_summaries.reported_total_as_of"
        # 3) the named top-level stamp, for that account only
        if not obs and named and acct == named and fallback:
            obs, obs_source = fallback, "holdings.data_as_of"

        divergence = None
        if obs and summary_as_of and _obs_key(obs) != _obs_key(summary_as_of):
            divergence = f"positions say {obs} ({obs_source}); account_summaries.as_of says {summary_as_of}"

        value = _num(row.get("total_value")) or 0.0
        # An account holding nothing contributes nothing, and cannot date the
        # aggregate. fidelity_rollover_ira -- $0, no rows, as_of 2026-07-16 --
        # was being named the oldest contributor and driving the whole book to
        # STALE while contributing not one cent to it.
        contributes = bool(rows) or abs(value) > 0

        out.append(
            {
                "account": acct,
                "custodian": row.get("source", "") or "",
                "total_value": row.get("total_value"),
                "holdings_count": row.get("holdings_count"),
                # ── the clocks, each named ──────────────────────────────────
                "position_observation_time": obs or "",
                "position_observation_source": obs_source or "",
                "position_observation_age_hours": _age_hours(obs, now_utc) if obs else None,
                "position_row_count": len(rows),
                "summary_as_of": summary_as_of or None,
                "observation_divergence": divergence,
                "valuation_time": str(row.get("last_repriced") or "").strip(),
                "reported_total_as_of": str(row.get("reported_total_as_of") or "").strip(),
                "reported_total_value": row.get("reported_total_value"),
                "received_time": row.get("last_import", "") or "",
                "dated": bool(obs),
                "contributes": contributes,
                "holds_positions": bool(rows),
                # v1 alias -- same value, honest name above.
                "observation_time": obs or "",
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
        obs = row.get("position_observation_time") or row.get("observation_time")
        if not obs or not str(obs).strip():
            continue
        # An account that holds nothing and is worth nothing cannot date the
        # aggregate. A $0 closed account stamped 2026-07-16 was being published
        # as the oldest CONTRIBUTOR and pinning the book to STALE.
        if row.get("contributes") is False:
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
    non_contributing: list[str] = []

    newest_key = _obs_key(newest_obs) if newest_obs else None

    for row in accounts:
        val = abs(_num(row.get("total_value")) or 0.0)
        acct = str(row.get("account") or "?")
        # Empty accounts are named, not counted. Listing three $0 accounts as
        # "undated" made the book look 50% unobserved when they held nothing.
        if row.get("contributes") is False:
            non_contributing.append(acct)
            continue
        total += val
        obs = row.get("position_observation_time") or ""
        if not obs:
            undated.append(acct)
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

    contributing_n = len(accounts) - len(non_contributing)
    return {
        "accounts_total": len(accounts),
        "accounts_contributing": contributing_n,
        "accounts_non_contributing": len(non_contributing),
        "non_contributing_accounts": sorted(non_contributing),
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
    positions: Any = None,
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
        positions=positions,
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
        _contrib = coverage.get("accounts_contributing", len(accounts))
        _noncontrib = coverage.get("accounts_non_contributing", 0)
        # Say how many CONTRIBUTE, not how many exist -- the reason read
        # "6 account(s) contributing" beside a coverage block saying 4.
        agg_reason = f"{_contrib} of {len(accounts)} account(s) contributing" + (
            f"; {_noncontrib} hold nothing" if _noncontrib else ""
        )
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
                # counted over contributors only
                # Every dated row is fresh, but some value carries no date at
                # all. That is PARTIAL coverage, not a complete fresh book.
                agg_state = "PARTIAL"
                agg_reason = (
                    f"{coverage['accounts_undated']} of {coverage['accounts_contributing']}"
                    f" contributing account(s) undated"
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
        # Divergences between the maintained position rows and the unmaintained
        # account_summaries.as_of mirror. Reported, never auto-remediated: both
        # copies stay exactly as their writers left them.
        "observation_divergences": [
            {"account": a["account"], "detail": a["observation_divergence"]}
            for a in accounts
            if a.get("observation_divergence")
        ],
        "freshness_state": agg_state,
        "freshness_reason": agg_reason,
        "accounts": accounts,
        "read_only": True,
        # v1 aliases -- identical values, position-clock semantics.
        "oldest_observation_time": oldest_obs,
        "oldest_observation_account": oldest_acct,
        "newest_observation_time": newest_obs,
    }

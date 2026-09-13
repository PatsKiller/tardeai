"""Read-side DECAY for data_source_health: "healthy" is a claim with an expiry.

WHY
---
Measured 2026-09-13: the data_source_health table held 18 rows. `yahoo_finance`
read "healthy" with last_success_at 2026-08-24 -- twenty days old -- because the
status column is written once by report_source() and then never touched again
until the next call. `brave_search`, `fred`, `alpha_vantage` were "unknown"
forever because nothing ever called report_source() for them, although Brave
alone made 163 governed calls that month. `finnhub` sat at "error" (HTTP 401)
for seven weeks while four scheduled callers still tried it first.

The health agent (collect_data_source_health) and the API (_data_source_health)
read the raw status column, so the platform scored 75 while all of this was true.

The rule this module enforces is AGENTS.md section 7A rule 6:

    "A data_source_health row is healthy only if it succeeded inside its window;
     a row nobody touches decays to unknown. healthy on a 20-day-old success is a
     defect."

HOW
---
`effective_status(row, now, window_minutes)` is pure: it takes a row (a dict as
returned by the table), a clock value and a window, and returns one of
"healthy" | "error" | "unknown". No I/O, no database, no clock of its own.

`window_minutes_for(source_key, registry)` derives the window from
config/data_source_authority.json: the source_key maps to a provider name, and
the window is the smallest `stale_after_hours` of any domain whose
`primary_provider` is that provider. A source with no such domain, or whose
domains declare no window, gets DEFAULT_WINDOW_MINUTES (24h). The registry is
the one place that says how fresh a source must be; this module does not carry
a second copy of that number.

SOURCE_KEY -> PROVIDER -> WINDOW (as of the 2026-09-13 registry)
-----------------------------------------------------------------
| source_key     | provider      | domains where primary        | window     |
|----------------|---------------|------------------------------|------------|
| yahoo_finance  | yfinance      | symbol_identity, earnings_date, dividends (168h each) | 168h |
| finviz         | finviz        | catalyst_news 12h, industry_momentum 26h | 12h  |
| brave_search   | brave         | web_search (stale_after_hours null) | 24h default |
| fred           | fred          | none declared                | 24h default |
| alpha_vantage  | alpha_vantage | none declared                | 24h default |
| sec_edgar      | sec_edgar     | none declared                | 24h default |
| alpaca         | alpaca        | quote_price 0.25h, technicals 26h | 0.25h |
| every other key | (itself)     | none declared                | 24h default |

The alias table SOURCE_KEY_ALIASES is the only hand-maintained mapping: a key
whose name is not literally a provider name in the registry. Everything else
maps by identity. docs/implementation/sot/phase3_registry_patch.json proposes
`macro` (fred) and `fundamentals` (alpha_vantage) domains so those two stop
falling through to the default.

SCHEDULED CALLERS
-----------------
A source that is not healthy AND has a scheduled caller is a finding: something
was supposed to feed it and did not (or failed). A source with no scheduled
caller is merely idle and is reported, not alerted. SCHEDULED_CALLERS is
transcribed from config/crontab_backup.txt on 2026-09-13; each entry names the
script and the cron expression so the claim can be re-checked with grep.

CONSUMERS: scripts/health_agent.py collect_data_source_health,
scripts/api_v2.py _data_source_health and /api/v2/discovery-source-health,
scripts/check_data_source_health.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

SCHEMA = "DataSourceHealthView@v1"

DEFAULT_WINDOW_MINUTES = 24 * 60

HEALTHY = "healthy"
ERROR = "error"
UNKNOWN = "unknown"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_source_authority.json"

# source_key -> provider name in config/data_source_authority.json "providers".
# Only keys whose spelling differs from the provider's are listed; any other key
# maps to the provider of the same name (or to nothing, and gets the default).
SOURCE_KEY_ALIASES: dict[str, str] = {
    "yahoo_finance": "yfinance",
    "brave_search": "brave",
}

# source_key -> the scheduled jobs that are supposed to call report_source() for
# it. Transcribed from config/crontab_backup.txt 2026-09-13. A key absent here has
# no scheduled caller the author could find, and is not alerted on.
SCHEDULED_CALLERS: dict[str, list[dict[str, str]]] = {
    "yahoo_finance": [
        {"script": "scripts/pro_analyst_fetch.py --max 250", "cron": "10 6 * * *"},
        {"script": "scripts/external_market_data_ingest.py --quotes", "cron": "15 7 * * 1-5"},
        {"script": "scripts/external_market_data_ingest.py --quotes", "cron": "*/15 9-16 * * 1-5"},
    ],
    "fred": [
        {"script": "scripts/fred_data_ingest.py --ingest", "cron": "15 6 * * *"},
    ],
    "alpha_vantage": [
        {"script": "scripts/external_market_data_ingest.py --fundamentals", "cron": "0 8 * * 1"},
    ],
    "brave_search": [
        {"script": "scripts/aegis_transcript_discovery.py", "cron": "0 9 * * 1-5"},
        {"script": "scripts/aegis_social_sentiment.py", "cron": "0 11,15 * * 1-5"},
    ],
    "finviz": [
        {"script": "scripts/finviz_health_check.py", "cron": "25 6-18/3 * * 1-5"},
    ],
    "sec_edgar": [
        {"script": "scripts/symbol_enrichment.py --limit 50", "cron": "30 7 * * 1-5"},
    ],
    "youtube_api": [
        {"script": "scripts/symbol_enrichment.py --limit 50", "cron": "30 7 * * 1-5"},
    ],
}


def has_scheduled_caller(source_key: str) -> bool:
    return bool(SCHEDULED_CALLERS.get(str(source_key or "")))


def _cron_dow_is_weekdays_only(cron: str) -> bool:
    """True when the day-of-week field is exactly the trading week (1-5)."""
    parts = str(cron or "").split()
    if len(parts) < 5:
        return False
    dow = parts[4]
    return dow in ("1-5", "1,2,3,4,5", "MON-FRI", "mon-fri")


def weekday_only_for(source_key: str) -> bool:
    """A source is weekday-only when it has scheduled callers and every one of
    them runs Mon-Fri. Its clock then stops over the weekend: a Friday-evening
    success is not "stale" on Sunday night, because nothing was ever going to run.

    Phase 8 measurement (Sunday 2026-09-13 17:20 ET): with plain elapsed time,
    finviz, hermes_social, incubator, news_catalyst, social, social_scalp and
    yahoo_movers -- all last touched Friday -- read `unknown`, and the hourly
    audit would have interrupted the operator eight times before Monday's first
    cron. A source with no scheduled caller, or any 7-day caller, keeps the plain
    clock: decaying sooner is the safer error.
    """
    callers = SCHEDULED_CALLERS.get(str(source_key or "")) or []
    return bool(callers) and all(_cron_dow_is_weekdays_only(c.get("cron", "")) for c in callers)


def weekday_minutes_between(start: datetime, end: datetime) -> float:
    """Minutes between two instants counting Monday-Friday only (UTC calendar).
    Saturday and Sunday contribute nothing. `end <= start` yields 0."""
    if end <= start:
        return 0.0
    total = 0.0
    cur = start
    while cur < end:
        day_end = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seg_end = min(day_end, end)
        if cur.weekday() < 5:
            total += (seg_end - cur).total_seconds() / 60.0
        cur = seg_end
    return total


# ── the registry-derived window ─────────────────────────────────────────────


def load_registry(path: Optional[Path] = None) -> dict[str, Any]:
    """Read config/data_source_authority.json. Never raises: an unreadable
    registry yields an empty document, and every source then gets the default
    window -- which is the SAFER direction (decay sooner, not later)."""
    p = Path(path) if path else REGISTRY_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def provider_for(source_key: str) -> str:
    key = str(source_key or "")
    return SOURCE_KEY_ALIASES.get(key, key)


def window_minutes_for(source_key: str, registry: Optional[dict[str, Any]]) -> int:
    """Smallest stale_after_hours over domains whose primary_provider is this
    source's provider, in minutes; DEFAULT_WINDOW_MINUTES when none declares one."""
    provider = provider_for(source_key)
    hours: list[float] = []
    for d in (registry or {}).get("domains") or []:
        if str(d.get("primary_provider") or "") != provider:
            continue
        h = d.get("stale_after_hours")
        if h is None:
            continue
        try:
            hf = float(h)
        except (TypeError, ValueError):
            continue
        if hf > 0:
            hours.append(hf)
    if not hours:
        return DEFAULT_WINDOW_MINUTES
    return max(1, int(round(min(hours) * 60)))


# ── the pure decay rule ─────────────────────────────────────────────────────


def _as_utc(value: Any) -> Optional[datetime]:
    """Coerce a timestamp cell to an aware UTC datetime. None for anything unusable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def age_minutes(row: dict[str, Any], now: datetime) -> Optional[float]:
    """Minutes since last_success_at; None when the source has never succeeded."""
    last = _as_utc(row.get("last_success_at"))
    if last is None:
        return None
    now = _as_utc(now) or datetime.now(timezone.utc)
    return max(0.0, (now - last).total_seconds() / 60.0)


def effective_status(row: dict[str, Any], now: datetime, window_minutes: int, *,
                     weekday_only: bool = False) -> str:
    """What the row is allowed to claim right now.

        healthy  last_success_at is within `window_minutes` of `now` and no
                 failure has been recorded since that success
        error    a failure is newer than the last success (or there was never a
                 success and there has been a failure)
        unknown  anything else: never reported, or the last success has aged
                 out of its window with nothing newer either way

    `weekday_only` (set by view_row from the caller schedule) measures the age in
    Monday-Friday minutes, so a Friday-evening success survives the weekend.

    The raw `status` column is deliberately NOT consulted. It is what report_source
    last wrote, however long ago; trusting it is the defect.
    """
    success = _as_utc(row.get("last_success_at"))
    failure = _as_utc(row.get("last_failure_at"))
    now = _as_utc(now) or datetime.now(timezone.utc)

    if failure is not None and (success is None or failure > success):
        return ERROR
    if success is None:
        return UNKNOWN
    elapsed_min = (
        weekday_minutes_between(success, now) if weekday_only
        else (now - success).total_seconds() / 60.0
    )
    if elapsed_min <= float(window_minutes):
        return HEALTHY
    return UNKNOWN


def view_row(row: dict[str, Any], now: datetime, registry: Optional[dict[str, Any]] = None,
             window_minutes: Optional[int] = None) -> dict[str, Any]:
    """The row as every consumer must see it: raw fields preserved, `status`
    REPLACED by the effective status, plus `raw_status`, `decayed`, `age_minutes`,
    `window_minutes`, `scheduled_caller`."""
    key = str(row.get("source_key") or "")
    win = int(window_minutes) if window_minutes is not None else window_minutes_for(key, registry)
    wk = weekday_only_for(key)
    eff = effective_status(row, now, win, weekday_only=wk)
    raw = str(row.get("status") or UNKNOWN)
    age = age_minutes(row, now)
    out = dict(row)
    out.update(
        {
            "source_key": key,
            "status": eff,
            "raw_status": raw,
            # decayed == the table would have told you something better than the truth
            "decayed": raw == HEALTHY and eff != HEALTHY,
            "age_minutes": None if age is None else round(age, 1),
            "window_minutes": win,
            "weekday_clock": wk,
            "scheduled_caller": has_scheduled_caller(key),
        }
    )
    return out


def view_rows(rows: list[dict[str, Any]], now: datetime,
              registry: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    return [view_row(r, now, registry) for r in rows or []]


def not_healthy_with_scheduled_caller(viewed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The alert set: sources something is supposed to feed, that are not healthy."""
    return [r for r in viewed if r.get("status") != HEALTHY and r.get("scheduled_caller")]

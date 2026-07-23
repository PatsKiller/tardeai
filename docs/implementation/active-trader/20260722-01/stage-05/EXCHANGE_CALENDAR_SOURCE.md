# Exchange Calendar Source

Module: `scripts/active_trader/market_calendar.py` · version `nyse-checkedin-1`

## Dependency policy (controller §6.1)
No approved exchange-calendar package is installed in the isolated environment, and no new package is
installed by this transaction. A **deterministic checked-in NYSE dataset** is used, with no runtime
web query.

## Source + coverage
- Source: NYSE published holiday & early-close schedule (2026, 2027). Retrieved 2026-07-23.
- Supported years: **{2026, 2027}**. Fails CLOSED outside the range (`UnsupportedYearError`) — never
  assumes "weekday == market day."
- Timezone: America/New_York (DST-aware; open is tz-aware 09:30 local in both EST and EDT).

## Holidays (rule-generated within supported years, weekend-observed)
New Year's, MLK, Presidents, Good Friday (computus), Memorial, Juneteenth, Independence, Labor,
Thanksgiving, Christmas.

## Early closes (1:00 PM ET dataset)
- 2026: Nov 27 (day after Thanksgiving), Dec 24 (Christmas Eve).
- 2027: Nov 26 (day after Thanksgiving).
Early-close days still qualify for observation (13:00 > 10:05 required completion) and are labeled.

## Observation qualification
`SessionInfo.qualifies_for_observation()` is true iff the session opens at 09:30 ET and closes at or
after 10:05 ET. Preflight 06:55, capture start 07:00, required RTH completion 10:05.

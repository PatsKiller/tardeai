# Market Risk Engine backtest

```
Generated: 2026-11-01T00:45:16+00:00 by scripts/market_risk_backtest.py
Data:      tests/fixtures/market_risk_scenarios (public daily history; see SOURCES.json)
Status:    GENERATED — do not edit by hand; re-run the harness
```

Each session is evaluated at 09:31 ET (after the open) and at the 16:00 ET close. Session counts are distinct
dates on which the tier was reached. Lead = sessions from the first evaluation at that tier to the SPY
max-drawdown trough inside the window (positive = early); '—' = not reached or no >=5% drawdown.

Sample: thresholds come from scripts/market_risk_calibrate.py over 2016-2025 (IN); 2026 is held out (OUT).
OVERLAY marks a scenario that adds hand-entered data from the RCA (after-hours moves, option snapshots) on top
of the public bars. It is NOT out-of-sample evidence: the overlay was written knowing the outcome. Without the
overlay, October 2026 is the tail of corrections2026, which peaks at YELLOW (review of #2383).

| Scenario | Sample | Window | Max tier | First ORANGE+ | First RED | First GREEN | SPY trough | Lead ORANGE | Lead RED | Orange sessions | Red sessions | Green sessions |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| covid2020 | IN | 2020-02-19..2020-03-23 | RED | 2020-02-24 | 2020-02-24 | — | 2020-03-23 | 20 | 20 | 0 | 21 | 0 |
| bear2022_leg1 | IN | 2022-01-03..2022-03-08 | RED | 2022-01-25 | 2022-01-25 | — | 2022-03-08 | 29 | 29 | 0 | 8 | 0 |
| bear2022_leg2 | IN | 2022-03-29..2022-06-16 | RED | 2022-06-10 | 2022-06-10 | 2022-03-30 | 2022-06-16 | 4 | 4 | 0 | 5 | 1 |
| bear2022_leg3 | IN | 2022-08-16..2022-10-12 | RED | 2022-09-13 | 2022-09-13 | — | 2022-10-12 | 21 | 21 | 0 | 11 | 0 |
| bear2022_turn | IN | 2022-10-13..2022-11-30 | RED | 2022-10-13 | 2022-10-13 | — | — | — | — | 0 | 3 | 0 |
| banks2023 | IN | 2023-03-08..2023-03-17 | RED | 2023-03-13 | 2023-03-13 | — | — | — | — | 0 | 4 | 0 |
| carry2024 | IN | 2024-08-01..2024-08-05 | RED | 2024-08-05 | 2024-08-05 | — | — | — | — | 0 | 1 | 0 |
| dec2018_selloff | IN | 2018-12-03..2018-12-31 | RED | 2018-12-24 | 2018-12-24 | — | 2018-12-24 | 0 | 0 | 0 | 4 | 0 |
| jan2019_reversal | IN | 2019-01-02..2019-01-31 | YELLOW | — | — | — | — | — | — | 0 | 0 | 0 |
| aimelt2023 | IN | 2023-05-01..2023-07-31 | BLUE | — | — | — | — | — | — | 0 | 0 | 0 |
| cut2024 | IN | 2024-09-03..2024-09-30 | YELLOW | — | — | — | — | — | — | 0 | 0 | 0 |
| santa2023 | IN | 2023-12-01..2023-12-29 | BLUE | — | — | — | — | — | — | 0 | 0 | 0 |
| calm2017_h1 | IN | 2017-01-03..2017-06-30 | YELLOW | — | — | — | — | — | — | 0 | 0 | 0 |
| calm2017_h2 | IN | 2017-07-03..2017-12-29 | YELLOW | — | — | — | — | — | — | 0 | 0 | 0 |
| calm2021_h1 | IN | 2021-01-04..2021-06-30 | YELLOW | — | — | — | — | — | — | 0 | 0 | 0 |
| corrections2026 | OUT | 2026-01-02..2026-10-30 | YELLOW | — | — | 2026-04-13 | 2026-03-30 | — | — | 0 | 0 | 5 |
| oct2026 | OVERLAY | 2026-10-01..2026-10-30 | RED | 2026-10-30 | 2026-10-30 | — | — | — | — | 0 | 1 | 0 |

## Forward SPY move frequency by tier (all scenario sessions)

```
{
 "BLUE": {
  "P(down,1d)": 0.457,
  "P(down,3d)": 0.393,
  "P(down,5d)": 0.399,
  "P(|move|>=1.5%,1d)": 0.096,
  "P(|move|>=1.5%,3d)": 0.31,
  "P(|move|>=1.5%,5d)": 0.457,
  "P(|move|>=3.0%,1d)": 0.013,
  "P(|move|>=3.0%,3d)": 0.061,
  "P(|move|>=3.0%,5d)": 0.144,
  "n": 313
 },
 "GREEN": {
  "P(down,1d)": 0.333,
  "P(down,3d)": 0.167,
  "P(down,5d)": 0.167,
  "P(|move|>=1.5%,1d)": 0.167,
  "P(|move|>=1.5%,3d)": 0.5,
  "P(|move|>=1.5%,5d)": 0.667,
  "P(|move|>=3.0%,1d)": 0.0,
  "P(|move|>=3.0%,3d)": 0.0,
  "P(|move|>=3.0%,5d)": 0.167,
  "n": 6
 },
 "NONE": {
  "P(down,1d)": 0.467,
  "P(down,3d)": 0.393,
  "P(down,5d)": 0.373,
  "P(|move|>=1.5%,1d)": 0.024,
  "P(|move|>=1.5%,3d)": 0.163,
  "P(|move|>=1.5%,5d)": 0.308,
  "P(|move|>=3.0%,1d)": 0.003,
  "P(|move|>=3.0%,3d)": 0.015,
  "P(|move|>=3.0%,5d)": 0.033,
  "n": 338
 },
 "RED": {
  "P(down,1d)": 0.58,
  "P(down,3d)": 0.5,
  "P(down,5d)": 0.52,
  "P(|move|>=1.5%,1d)": 0.62,
  "P(|move|>=1.5%,3d)": 0.94,
  "P(|move|>=1.5%,5d)": 0.98,
  "P(|move|>=3.0%,1d)": 0.36,
  "P(|move|>=3.0%,3d)": 0.6,
  "P(|move|>=3.0%,5d)": 0.76,
  "n": 50
 },
 "YELLOW": {
  "P(down,1d)": 0.506,
  "P(down,3d)": 0.49,
  "P(down,5d)": 0.506,
  "P(|move|>=1.5%,1d)": 0.257,
  "P(|move|>=1.5%,3d)": 0.617,
  "P(|move|>=1.5%,5d)": 0.759,
  "P(|move|>=3.0%,1d)": 0.032,
  "P(|move|>=3.0%,3d)": 0.229,
  "P(|move|>=3.0%,5d)": 0.36,
  "n": 253
 }
}
```


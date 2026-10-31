# Market Risk Engine backtest

```
Generated: 2026-10-31T14:40:43+00:00 by scripts/market_risk_backtest.py
Data:      tests/fixtures/market_risk_scenarios (public daily history; see SOURCES.json)
Status:    GENERATED — do not edit by hand; re-run the harness
```

| Scenario | Window | Max tier | First ORANGE+ | First RED | Orange sessions | Red sessions |
|---|---|---|---|---|---|---|
| covid2020 | 2020-02-19..2020-03-23 | ORANGE | 2020-02-25 | — | 18 | 0 |
| bear2022_leg1 | 2022-01-03..2022-03-08 | ORANGE | 2022-01-21 | — | 6 | 0 |
| bear2022_leg2 | 2022-03-29..2022-06-16 | ORANGE | 2022-04-25 | — | 10 | 0 |
| bear2022_leg3 | 2022-08-16..2022-10-12 | ORANGE | 2022-09-27 | — | 6 | 0 |
| bear2022_turn | 2022-10-13..2022-11-30 | YELLOW | — | — | 0 | 0 |
| banks2023 | 2023-03-08..2023-03-17 | YELLOW | — | — | 0 | 0 |
| carry2024 | 2024-08-01..2024-08-05 | BLUE | — | — | 0 | 0 |
| dec2018_selloff | 2018-12-03..2018-12-31 | ORANGE | 2018-12-07 | — | 11 | 0 |
| jan2019_reversal | 2019-01-02..2019-01-31 | BLUE | — | — | 0 | 0 |
| aimelt2023 | 2023-05-01..2023-07-31 | BLUE | — | — | 0 | 0 |
| cut2024 | 2024-09-03..2024-09-30 | YELLOW | — | — | 0 | 0 |
| santa2023 | 2023-12-01..2023-12-29 | NONE | — | — | 0 | 0 |
| calm2017_h1 | 2017-01-03..2017-06-30 | BLUE | — | — | 0 | 0 |
| calm2017_h2 | 2017-07-03..2017-12-29 | BLUE | — | — | 0 | 0 |
| calm2021_h1 | 2021-01-04..2021-06-30 | YELLOW | — | — | 0 | 0 |
| corrections2026 | 2026-01-02..2026-10-30 | YELLOW | — | — | 0 | 0 |
| oct2026 | 2026-10-01..2026-10-30 | YELLOW | — | — | 0 | 0 |

## Forward SPY move frequency by tier (all scenario sessions)

```
{
 "BLUE": {
  "P(down,1d)": 0.506,
  "P(down,3d)": 0.45,
  "P(down,5d)": 0.482,
  "P(|move|>=1.5%,1d)": 0.167,
  "P(|move|>=1.5%,3d)": 0.409,
  "P(|move|>=1.5%,5d)": 0.576,
  "P(|move|>=3.0%,1d)": 0.02,
  "P(|move|>=3.0%,3d)": 0.126,
  "P(|move|>=3.0%,5d)": 0.208,
  "n": 342
 },
 "NONE": {
  "P(down,1d)": 0.457,
  "P(down,3d)": 0.385,
  "P(down,5d)": 0.363,
  "P(|move|>=1.5%,1d)": 0.038,
  "P(|move|>=1.5%,3d)": 0.199,
  "P(|move|>=1.5%,5d)": 0.342,
  "P(|move|>=3.0%,1d)": 0.004,
  "P(|move|>=3.0%,3d)": 0.026,
  "P(|move|>=3.0%,5d)": 0.062,
  "n": 468
 },
 "ORANGE": {
  "P(down,1d)": 0.49,
  "P(down,3d)": 0.529,
  "P(down,5d)": 0.471,
  "P(|move|>=1.5%,1d)": 0.608,
  "P(|move|>=1.5%,3d)": 0.882,
  "P(|move|>=1.5%,5d)": 0.98,
  "P(|move|>=3.0%,1d)": 0.333,
  "P(|move|>=3.0%,3d)": 0.647,
  "P(|move|>=3.0%,5d)": 0.804,
  "n": 51
 },
 "YELLOW": {
  "P(down,1d)": 0.485,
  "P(down,3d)": 0.455,
  "P(down,5d)": 0.475,
  "P(|move|>=1.5%,1d)": 0.293,
  "P(|move|>=1.5%,3d)": 0.808,
  "P(|move|>=1.5%,5d)": 0.859,
  "P(|move|>=3.0%,1d)": 0.051,
  "P(|move|>=3.0%,3d)": 0.242,
  "P(|move|>=3.0%,5d)": 0.455,
  "n": 99
 }
}
```


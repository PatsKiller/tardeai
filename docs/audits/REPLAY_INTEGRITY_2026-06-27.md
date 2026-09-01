# Replay chart integrity audit — 2026-06-27

Status:      HISTORICAL
as_of:       2026-06-27T19:27:22-04:00
Measured at: efcc51365 / not measured

**Audited:** 2026-06-27T22:37:38.459644+00:00
**Trades:** 63 · OK 44 · WARN 19 · FAIL 0
**Scale fix:** `volume_isolated_overlay_v3.4` (volume on isolated overlay scale; candle autoscale from OHLC only)

## Summary

| Status | Count | Meaning |
|--------|------:|---------|
| ok | 44 | Bars loaded; markers in range |
| warn | 19 | Finviz fallback or marker outside bar range |
| fail | 0 | No chart data / API error |

## Per-trade

| Symbol | Close | Bars | Source | Range | Status |
|--------|-------|-----:|--------|-------|--------|
| DRS | 2026-06-26 | 0 | finviz | — | fallback |
| VTAK | 2026-06-25 | 50 | alpaca | $0.92–$1.08 | ok |
| LMT | 2026-06-23 | 0 | finviz | — | fallback |
| LHX | 2026-06-23 | 0 | finviz | — | fallback |
| KTOS | 2026-06-22 | 0 | finviz | — | fallback |
| KBR | 2026-06-22 | 0 | finviz | — | fallback |
| AVAV | 2026-06-18 | 0 | finviz | — | fallback |
| IRDM | 2026-06-16 | 0 | finviz | — | fallback |
| CAST | 2026-06-15 | 53 | alpaca | $4.15–$5.2 | ok |
| RGNT | 2026-06-09 | 46 | alpaca | $2.78–$3.78 | ok |
| GOVX | 2026-05-18 | 65 | alpaca | $2.83–$4.39 | ok |
| PRSO | 2026-05-11 | 50 | alpaca | $1.1–$1.29 | ok |
| FATN | 2026-04-30 | 47 | alpaca | $3.35–$3.73 | ok |
| DFSC | 2026-04-30 | 43 | alpaca | $2.65–$3.17 | ok |
| PFE | 2026-04-21 | 46 | alpaca | $26.2–$28.745 | ok |
| V | 2026-04-21 | 223 | alpaca | $293.89–$358.62 | ok |
| V | 2026-04-06 | 0 | finviz | — | fallback |
| GERN | 2026-02-26 | 42 | alpaca | $1.26–$2.01 | ok |
| GERN | 2026-02-26 | 42 | alpaca | $1.26–$2.01 | ok |
| ADBE | 2026-02-23 | 434 | alpaca | $224.13–$587.75 | ok |
| ADBE | 2026-02-12 | 423 | alpaca | $224.13–$587.75 | ok |
| CSWC | 2026-02-12 | 25 | alpaca | $22.6–$23.84 | ok |
| PFLT | 2026-02-11 | 24 | alpaca | $8.63–$9.75 | ok |
| 73017P409 | 2026-02-11 | 0 | finviz | — | fallback |
| PHIO | 2026-02-10 | 66 | alpaca | $1.24–$1.48 | ok |
| DHX | 2026-02-05 | 59 | alpaca | $1.98–$2.2 | ok |
| FUSE | 2026-02-03 | 47 | alpaca | $2.62–$3.24 | ok |
| FUSE | 2026-02-02 | 48 | alpaca | $2.26–$3.67 | ok |
| ARKG | 2026-01-30 | 17 | alpaca | $28.455–$34.39 | ok |
| ZSL | 2026-01-30 | 70 | alpaca | $20.1–$21.3 | marker_warn |
| WRD | 2026-01-30 | 18 | alpaca | $6.88–$10.015 | ok |
| ALXO | 2026-01-30 | 85 | alpaca | $1.64–$1.93 | ok |
| TRX | 2026-01-29 | 46 | alpaca | $2.09–$2.32 | ok |
| GCTS | 2026-01-29 | 57 | alpaca | $1.47–$1.84 | ok |
| NUWE | 2026-01-27 | 48 | alpaca | $142.1–$172.9 | marker_warn |
| 44984F807 | 2026-01-27 | 0 | finviz | — | fallback |
| GXAI | 2026-01-26 | 49 | alpaca | $1.57–$2.16 | ok |
| AXTI | 2026-01-22 | 76 | alpaca | $4.81–$26.66 | ok |
| APAM | 2026-01-20 | 142 | alpaca | $39.94–$48.46 | ok |
| SHPH | 2026-01-20 | 46 | alpaca | $35.1–$44.4 | marker_warn |
| 44984F807 | 2026-01-20 | 0 | finviz | — | fallback |
| SIBN | 2026-01-15 | 7 | alpaca | $16.66–$21.28 | ok |
| AXTI | 2026-01-08 | 131 | alpaca | $1.85–$26.66 | ok |
| AXTI | 2026-01-08 | 128 | alpaca | $1.85–$26.66 | ok |
| BNAI | 2026-01-02 | 46 | alpaca | $3.81–$4.15 | ok |
| APAM | 2025-12-31 | 29 | alpaca | $39.94–$43.5999 | ok |
| EKSO | 2025-12-30 | 59 | alpaca | $7.8001–$9.1199 | ok |
| SOPAQ | 2025-12-29 | 0 | finviz | — | fallback |
| OLOX | 2025-11-13 | 46 | alpaca | $30.3–$39.8 | marker_warn |
| MSGM | 2025-11-07 | 46 | alpaca | $4.11–$5.8 | ok |
| VIVS | 2025-10-30 | 57 | alpaca | $2.63–$3.2 | ok |
| IBIO | 2025-10-23 | 47 | alpaca | $1.61–$2.05 | ok |
| AIRE | 2025-10-22 | 53 | alpaca | $25–$32.5 | marker_warn |
| NERV | 2025-10-21 | 68 | alpaca | $6.61–$12.46 | ok |
| IBIO | 2025-10-21 | 67 | alpaca | $1.03–$1.47 | ok |
| BOF | 2025-10-21 | 74 | alpaca | $2.45–$2.85 | ok |
| GSIT | 2025-10-20 | 34 | alpaca | $6.77–$17.49 | ok |
| GSIT | 2025-10-20 | 30 | alpaca | $6.77–$17.49 | ok |
| RANI | 2025-10-17 | 54 | alpaca | $1.13–$1.52 | ok |
| ACHV | 2025-10-17 | 50 | alpaca | $3.71–$4.15 | ok |
| CTXR | 2025-10-16 | 76 | alpaca | $1.39–$1.94 | ok |
| AUUD | 2025-10-16 | 66 | alpaca | $16.79–$18.71 | marker_warn |
| ZNB | 2025-10-15 | 103 | alpaca | $190–$217 | marker_warn |

## Issues

- **DRS** (2026-06-26): alpaca 403
- **LMT** (2026-06-23): alpaca 403
- **LHX** (2026-06-23): alpaca 403
- **KTOS** (2026-06-22): alpaca 403
- **KBR** (2026-06-22): alpaca 403
- **AVAV** (2026-06-18): alpaca 403
- **IRDM** (2026-06-16): alpaca 403
- **V** (2026-04-06): alpaca 403
- **73017P409** (2026-02-11): alpaca 400
- **ZSL** (2026-01-30): entry $2.06 misaligned at bar O=20.3 H=20.3 L=20.1 C=20.15; exit $2.08 misaligned at bar O=20.3 H=20.3 L=20.1 C=20.15
- **NUWE** (2026-01-27): entry $4.575 misaligned at bar O=143.5 H=148.05 L=142.1 C=146.65; exit $4.6132 misaligned at bar O=143.5 H=148.05 L=142.1 C=146.65
- **44984F807** (2026-01-27): alpaca 400
- **SHPH** (2026-01-20): entry $4.29 misaligned at bar O=39.5 H=39.5 L=35.1 C=36.4; exit $4.0301 misaligned at bar O=39.5 H=39.5 L=35.1 C=36.4
- **44984F807** (2026-01-20): alpaca 400
- **SOPAQ** (2025-12-29): no Alpaca bars for this symbol/window
- **OLOX** (2025-11-13): entry $3.47 misaligned at bar O=33.4 H=33.51 L=30.3 C=31; exit $3.3701 misaligned at bar O=33.4 H=33.51 L=30.3 C=31
- **AIRE** (2025-10-22): entry $1.29 misaligned at bar O=27.75 H=28 L=25 C=25.5; exit $1.15 misaligned at bar O=27.75 H=28 L=25 C=25.5
- **AUUD** (2025-10-16): entry $2.42 misaligned at bar O=17.21 H=17.25 L=16.79 C=16.86; exit $2.3043 misaligned at bar O=17.21 H=17.25 L=16.79 C=16.86
- **ZNB** (2025-10-15): entry $2.1349 misaligned at bar O=193 H=193 L=190 C=190; exit $2.035 misaligned at bar O=193 H=193 L=190 C=190

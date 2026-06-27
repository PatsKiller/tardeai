# Replay chart integrity audit — 2026-06-27

**Audited:** 2026-06-27T21:17:11.234472+00:00  
**Trades:** 90 · OK 62 · WARN 28 · FAIL 0  
**Scale fix:** `volume_isolated_overlay_v3.4` (volume on isolated overlay scale; candle autoscale from OHLC only)

## Summary

| Status | Count | Meaning |
|--------|------:|---------|
| ok | 62 | Bars loaded; markers in range |
| warn | 28 | Finviz fallback or marker outside bar range |
| fail | 0 | No chart data / API error |

## Per-trade

| Symbol | Close | Bars | Source | Range | Status |
|--------|-------|-----:|--------|-------|--------|
| DRS | 2026-06-26 | 0 | finviz | — | fallback |
| VTAK | 2026-06-25 | 396 | alpaca | $0.92–$1.25 | ok |
| LHX | 2026-06-23 | 0 | finviz | — | fallback |
| LMT | 2026-06-23 | 0 | finviz | — | fallback |
| KBR | 2026-06-22 | 0 | finviz | — | fallback |
| KTOS | 2026-06-22 | 0 | finviz | — | fallback |
| AVAV | 2026-06-18 | 0 | finviz | — | fallback |
| IRDM | 2026-06-16 | 0 | finviz | — | fallback |
| CAST | 2026-06-15 | 451 | alpaca | $3.26–$5.2 | ok |
| RGNT | 2026-06-09 | 424 | alpaca | $2.13–$6.55 | ok |
| GOVX | 2026-05-18 | 447 | alpaca | $1.7801–$4.39 | ok |
| PRSO | 2026-05-11 | 451 | alpaca | $1.05–$1.59 | ok |
| FATN | 2026-04-30 | 451 | alpaca | $2.82–$3.73 | ok |
| DFSC | 2026-04-30 | 178 | alpaca | $2.65–$3.17 | ok |
| V | 2026-04-21 | 223 | alpaca | $293.89–$358.62 | ok |
| PFE | 2026-04-21 | 233 | alpaca | $23.11–$28.745 | ok |
| V | 2026-04-06 | 0 | finviz | — | fallback |
| GERN | 2026-02-26 | 42 | alpaca | $1.26–$2.01 | ok |
| GERN | 2026-02-26 | 42 | alpaca | $1.26–$2.01 | ok |
| ADBE | 2026-02-23 | 435 | alpaca | $224.13–$587.75 | ok |
| ADBE | 2026-02-12 | 424 | alpaca | $224.13–$587.75 | ok |
| CSWC | 2026-02-12 | 25 | alpaca | $22.6–$23.84 | ok |
| PFLT | 2026-02-11 | 24 | alpaca | $8.63–$9.75 | ok |
| 73017P409 | 2026-02-11 | 0 | finviz | — | fallback |
| PHIO | 2026-02-10 | 451 | alpaca | $1.12–$1.58 | ok |
| DHX | 2026-02-05 | 427 | alpaca | $1.81–$2.2 | ok |
| FUSE | 2026-02-03 | 429 | alpaca | $2–$3.24 | ok |
| FUSE | 2026-02-02 | 451 | alpaca | $2.26–$3.67 | ok |
| ZSL | 2026-01-30 | 451 | alpaca | $20.1–$28 | marker_warn |
| ALXO | 2026-01-30 | 314 | alpaca | $1.63–$1.93 | ok |
| WRD | 2026-01-30 | 18 | alpaca | $6.88–$10.015 | ok |
| ARKG | 2026-01-30 | 17 | alpaca | $28.455–$34.39 | ok |
| TRX | 2026-01-29 | 451 | alpaca | $1.965–$2.8 | ok |
| GCTS | 2026-01-29 | 451 | alpaca | $1.11–$1.84 | ok |
| NUWE | 2026-01-27 | 451 | alpaca | $122.85–$172.9 | marker_warn |
| 44984F807 | 2026-01-27 | 0 | finviz | — | fallback |
| GXAI | 2026-01-26 | 451 | alpaca | $1.36–$2.18 | ok |
| AXTI | 2026-01-22 | 76 | alpaca | $4.81–$26.66 | ok |
| 44984F807 | 2026-01-20 | 0 | finviz | — | fallback |
| APAM | 2026-01-20 | 142 | alpaca | $39.94–$48.46 | ok |
| SHPH | 2026-01-20 | 451 | alpaca | $20.8–$44.4 | marker_warn |
| SIBN | 2026-01-15 | 7 | alpaca | $16.66–$21.28 | ok |
| AXTI | 2026-01-08 | 59 | alpaca | $5.4–$26.66 | ok |
| AXTI | 2026-01-08 | 63 | alpaca | $4.81–$26.66 | ok |
| BNAI | 2026-01-02 | 430 | alpaca | $2.43–$4.25 | ok |
| APAM | 2025-12-31 | 121 | alpaca | $39.94–$48.46 | ok |
| EKSO | 2025-12-30 | 447 | alpaca | $7.8001–$12.7 | ok |
| SOPAQ | 2025-12-29 | 0 | finviz | — | fallback |
| OLOX | 2025-11-13 | 450 | alpaca | $27.4–$39.8 | marker_warn |
| MSGM | 2025-11-07 | 451 | alpaca | $3.1601–$4.89 | ok |
| VIVS | 2025-10-30 | 441 | alpaca | $2.37–$3.2 | ok |
| IBIO | 2025-10-23 | 449 | alpaca | $1.18–$2.05 | ok |
| AIRE | 2025-10-22 | 447 | alpaca | $14.44–$32.5 | marker_warn |
| BOF | 2025-10-21 | 449 | alpaca | $2.44–$3.02 | ok |
| IBIO | 2025-10-21 | 451 | alpaca | $1.03–$1.47 | ok |
| NERV | 2025-10-21 | 451 | alpaca | $5.98–$12.46 | ok |
| GSIT | 2025-10-20 | 409 | alpaca | $5.15–$18.15 | ok |
| GSIT | 2025-10-20 | 409 | alpaca | $5.15–$18.15 | ok |
| RANI | 2025-10-17 | 415 | alpaca | $1.13–$2.39 | ok |
| ACHV | 2025-10-17 | 436 | alpaca | $3.71–$4.4399 | ok |
| CTXR | 2025-10-16 | 429 | alpaca | $1.39–$1.94 | ok |
| AUUD | 2025-10-16 | 446 | alpaca | $15.32–$19.4 | marker_warn |
| ZNB | 2025-10-15 | 436 | alpaca | $180.01–$215 | marker_warn |
| MNTS | 2025-10-14 | 450 | alpaca | $27.85–$34.45 | marker_warn |
| STI | 2025-10-13 | 398 | alpaca | $9.3–$27.698 | ok |
| ELBM | 2025-10-13 | 447 | alpaca | $3.22–$8.7 | marker_warn |
| GWH | 2025-10-10 | 451 | alpaca | $3.04–$5.33 | ok |
| TELO | 2025-10-09 | 446 | alpaca | $1.86–$2.091 | ok |
| AMD | 2025-09-30 | 446 | alpaca | $159.33–$162.28 | ok |
| SPRC | 2025-09-30 | 443 | alpaca | $51.3–$63.9 | marker_warn |
| RDHL | 2025-09-29 | 450 | alpaca | $2.01–$2.79 | marker_warn |
| NUAI | 2025-09-26 | 451 | alpaca | $1.63–$2.55 | ok |
| PEPG | 2025-09-25 | 451 | alpaca | $4.9–$6.34 | marker_warn |
| SHFS | 2025-09-25 | 8 | alpaca | $3.07–$9.19 | ok |
| LAC | 2025-09-25 | 451 | alpaca | $6.37–$7.53 | ok |
| SHFS | 2025-09-24 | 447 | alpaca | $6.4101–$9.74 | ok |
| SSKN | 2025-09-23 | 451 | alpaca | $2.23–$3.04 | marker_warn |
| SLNH | 2025-09-23 | 451 | alpaca | $2.21–$3.06 | ok |
| BOXL | 2025-09-22 | 451 | alpaca | $154.8–$365.4 | marker_warn |
| AGMH | 2025-09-19 | 447 | alpaca | $6.23–$18.1 | ok |
| LASE | 2025-09-18 | 451 | alpaca | $3.45–$5.88 | ok |
| SPRC | 2025-09-17 | 451 | alpaca | $32.85–$57.24 | marker_warn |
| IHT | 2025-09-15 | 448 | alpaca | $2.39–$4.24 | ok |
| MOGU | 2025-09-11 | 446 | alpaca | $4.21–$8.52 | ok |
| WLDS | 2025-09-10 | 435 | alpaca | $22.32–$98.19 | marker_warn |
| AXTI | 2025-08-20 | 368 | alpaca | $2.2–$2.6791 | ok |
| XMTR | 2025-08-19 | 17 | alpaca | $30.63–$49.5 | ok |
| SLDP | 2025-08-08 | 9 | alpaca | $2.9–$4.83 | ok |
| BRO | 2025-07-29 | 15 | alpaca | $90.55–$108.23 | ok |
| BRO | 2025-07-29 | 15 | alpaca | $90.55–$108.23 | ok |

## Issues

- **DRS** (2026-06-26): alpaca 403
- **LHX** (2026-06-23): alpaca 403
- **LMT** (2026-06-23): alpaca 403
- **KBR** (2026-06-22): alpaca 403
- **KTOS** (2026-06-22): alpaca 403
- **AVAV** (2026-06-18): alpaca 403
- **IRDM** (2026-06-16): alpaca 403
- **V** (2026-04-06): alpaca 403
- **73017P409** (2026-02-11): alpaca 400
- **ZSL** (2026-01-30): entry 2.11 below bar low 20.1; exit 2.14 below bar low 20.1
- **NUWE** (2026-01-27): entry 4.8 below bar low 122.85; exit 4.83 below bar low 122.85
- **44984F807** (2026-01-27): alpaca 400
- **44984F807** (2026-01-20): alpaca 400
- **SHPH** (2026-01-20): entry 4.29 below bar low 20.8; exit 4.0301 below bar low 20.8
- **SOPAQ** (2025-12-29): no Alpaca bars for this symbol/window
- **OLOX** (2025-11-13): entry 3.47 below bar low 27.4; exit 3.3701 below bar low 27.4
- **AIRE** (2025-10-22): entry 1.29 below bar low 14.44; exit 1.15 below bar low 14.44
- **AUUD** (2025-10-16): entry 2.42 below bar low 15.32; exit 2.3043 below bar low 15.32
- **ZNB** (2025-10-15): entry 2.1349 below bar low 180.01; exit 2.035 below bar low 180.01
- **MNTS** (2025-10-14): entry 1.66 below bar low 27.85; exit 1.8743 below bar low 27.85
- **ELBM** (2025-10-13): exit 2.9305 below bar low 3.22
- **SPRC** (2025-09-30): entry 6.38 below bar low 51.3; exit 6.1701 below bar low 51.3
- **RDHL** (2025-09-29): entry 2.97 above bar high 2.79; exit 3.3308 above bar high 2.79
- **PEPG** (2025-09-25): entry 6.91 above bar high 6.34
- **SSKN** (2025-09-23): entry 3.29 above bar high 3.04
- **BOXL** (2025-09-22): entry 5.6767 below bar low 154.8; exit 6.4713 below bar low 154.8
- **SPRC** (2025-09-17): entry 4.51 below bar low 32.85; exit 5.16 below bar low 32.85
- **WLDS** (2025-09-10): entry 5.7 below bar low 22.32; exit 6.7 below bar low 22.32

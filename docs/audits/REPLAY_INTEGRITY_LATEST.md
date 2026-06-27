# Replay chart integrity audit — 2026-06-27

**Audited:** 2026-06-27T21:50:48.191618+00:00  
**Trades:** 90 · OK 65 · WARN 25 · FAIL 0  
**Scale fix:** `volume_isolated_overlay_v3.4` (volume on isolated overlay scale; candle autoscale from OHLC only)

## Summary

| Status | Count | Meaning |
|--------|------:|---------|
| ok | 65 | Bars loaded; markers in range |
| warn | 25 | Finviz fallback or marker outside bar range |
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
| CAST | 2026-06-15 | 451 | alpaca | $3.26–$5.2 | marker_warn |
| RGNT | 2026-06-09 | 21 | alpaca | $3.05–$3.64 | ok |
| GOVX | 2026-05-18 | 65 | alpaca | $2.83–$4.39 | ok |
| PRSO | 2026-05-11 | 48 | alpaca | $1.1–$1.29 | ok |
| FATN | 2026-04-30 | 22 | alpaca | $3.41–$3.73 | ok |
| DFSC | 2026-04-30 | 23 | alpaca | $2.65–$3.09 | ok |
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
| PHIO | 2026-02-10 | 66 | alpaca | $1.24–$1.58 | ok |
| DHX | 2026-02-05 | 59 | alpaca | $1.98–$2.2 | ok |
| FUSE | 2026-02-03 | 43 | alpaca | $2.6–$3.24 | ok |
| FUSE | 2026-02-02 | 46 | alpaca | $2.26–$3.56 | ok |
| ZSL | 2026-01-30 | 26 | alpaca | $20.7–$21.6 | marker_warn |
| ALXO | 2026-01-30 | 82 | alpaca | $1.64–$1.93 | ok |
| WRD | 2026-01-30 | 18 | alpaca | $6.88–$10.015 | ok |
| ARKG | 2026-01-30 | 17 | alpaca | $28.455–$34.39 | ok |
| TRX | 2026-01-29 | 27 | alpaca | $2.06–$2.1516 | ok |
| GCTS | 2026-01-29 | 63 | alpaca | $1.11–$1.25 | ok |
| NUWE | 2026-01-27 | 23 | alpaca | $158.2–$172.9 | marker_warn |
| 44984F807 | 2026-01-27 | 0 | finviz | — | fallback |
| GXAI | 2026-01-26 | 49 | alpaca | $1.68–$2.18 | ok |
| AXTI | 2026-01-22 | 76 | alpaca | $4.81–$26.66 | ok |
| 44984F807 | 2026-01-20 | 0 | finviz | — | fallback |
| APAM | 2026-01-20 | 142 | alpaca | $39.94–$48.46 | ok |
| SHPH | 2026-01-20 | 43 | alpaca | $35.1–$44.4 | marker_warn |
| SIBN | 2026-01-15 | 7 | alpaca | $16.66–$21.28 | ok |
| AXTI | 2026-01-08 | 59 | alpaca | $5.4–$26.66 | ok |
| AXTI | 2026-01-08 | 63 | alpaca | $4.81–$26.66 | ok |
| BNAI | 2026-01-02 | 21 | alpaca | $3.88–$4.09 | ok |
| APAM | 2025-12-31 | 121 | alpaca | $39.94–$48.46 | ok |
| EKSO | 2025-12-30 | 59 | alpaca | $7.8001–$9.04 | ok |
| SOPAQ | 2025-12-29 | 0 | finviz | — | fallback |
| OLOX | 2025-11-13 | 43 | alpaca | $29.8–$37.4 | marker_warn |
| MSGM | 2025-11-07 | 25 | alpaca | $4.56–$5.46 | ok |
| VIVS | 2025-10-30 | 57 | alpaca | $2.63–$3.2 | ok |
| IBIO | 2025-10-23 | 22 | alpaca | $1.69–$2.05 | ok |
| AIRE | 2025-10-22 | 53 | alpaca | $25–$32.5 | marker_warn |
| BOF | 2025-10-21 | 74 | alpaca | $2.52–$2.85 | ok |
| IBIO | 2025-10-21 | 48 | alpaca | $1.03–$1.47 | ok |
| NERV | 2025-10-21 | 68 | alpaca | $6.61–$12.46 | ok |
| GSIT | 2025-10-20 | 45 | alpaca | $5.15–$13.43 | ok |
| GSIT | 2025-10-20 | 46 | alpaca | $5.15–$14.8 | ok |
| RANI | 2025-10-17 | 54 | alpaca | $1.2–$1.55 | ok |
| ACHV | 2025-10-17 | 30 | alpaca | $3.71–$4.15 | ok |
| CTXR | 2025-10-16 | 70 | alpaca | $1.39–$1.94 | ok |
| AUUD | 2025-10-16 | 66 | alpaca | $16.79–$19.4 | marker_warn |
| ZNB | 2025-10-15 | 109 | alpaca | $190–$219 | marker_warn |
| MNTS | 2025-10-14 | 216 | alpaca | $27.85–$38.02 | marker_warn |
| STI | 2025-10-13 | 20 | alpaca | $7.94–$13.5 | ok |
| ELBM | 2025-10-13 | 31 | alpaca | $1.95–$5.24 | ok |
| GWH | 2025-10-10 | 21 | alpaca | $3.24–$4.06 | ok |
| TELO | 2025-10-09 | 27 | alpaca | $1.91–$2.14 | ok |
| AMD | 2025-09-30 | 257 | alpaca | $159.33–$162.28 | ok |
| SPRC | 2025-09-30 | 43 | alpaca | $52.38–$60.3 | marker_warn |
| RDHL | 2025-09-29 | 20 | alpaca | $2.55–$3.3599 | ok |
| NUAI | 2025-09-26 | 249 | alpaca | $1.42–$2.55 | ok |
| PEPG | 2025-09-25 | 28 | alpaca | $6.28–$6.93 | ok |
| SHFS | 2025-09-25 | 8 | alpaca | $3.07–$9.19 | ok |
| LAC | 2025-09-25 | 33 | alpaca | $6.74–$7.53 | ok |
| SHFS | 2025-09-24 | 27 | alpaca | $8.29–$9.74 | ok |
| SSKN | 2025-09-23 | 286 | alpaca | $2.05–$4.18 | ok |
| SLNH | 2025-09-23 | 35 | alpaca | $2.6–$3.58 | ok |
| BOXL | 2025-09-22 | 106 | alpaca | $108.72–$312.12 | marker_warn |
| AGMH | 2025-09-19 | 98 | alpaca | $4.47–$8.67 | ok |
| LASE | 2025-09-18 | 333 | alpaca | $3.35–$5.88 | ok |
| SPRC | 2025-09-17 | 52 | alpaca | $32.85–$57.24 | marker_warn |
| IHT | 2025-09-15 | 24 | alpaca | $3.05–$4.24 | ok |
| MOGU | 2025-09-11 | 62 | alpaca | $5.35–$8.52 | ok |
| WLDS | 2025-09-10 | 28 | alpaca | $44.91–$65.79 | marker_warn |
| AXTI | 2025-08-20 | 112 | alpaca | $2.2–$2.65 | ok |
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
- **CAST** (2026-06-15): exit $5.1305 misaligned at bar O=4.8501 H=4.95 L=4.55 C=4.7096
- **V** (2026-04-06): alpaca 403
- **73017P409** (2026-02-11): alpaca 400
- **ZSL** (2026-01-30): entry $2.11 misaligned at bar O=20.7 H=20.9 L=20.7 C=20.8; exit $2.14 misaligned at bar O=20.7 H=20.9 L=20.7 C=20.8
- **NUWE** (2026-01-27): entry $4.8 misaligned at bar O=159.6 H=161 L=158.2 C=161; exit $4.83 misaligned at bar O=159.6 H=161 L=158.2 C=161
- **44984F807** (2026-01-27): alpaca 400
- **44984F807** (2026-01-20): alpaca 400
- **SHPH** (2026-01-20): entry $4.29 misaligned at bar O=39.5 H=39.5 L=35.1 C=36.4; exit $4.0301 misaligned at bar O=39.5 H=39.5 L=35.1 C=36.4
- **SOPAQ** (2025-12-29): no Alpaca bars for this symbol/window
- **OLOX** (2025-11-13): entry $3.47 misaligned at bar O=33.4 H=33.51 L=30.3 C=31; exit $3.3701 misaligned at bar O=33.4 H=33.51 L=30.3 C=31
- **AIRE** (2025-10-22): entry $1.29 misaligned at bar O=27.75 H=28 L=25 C=25.5; exit $1.15 misaligned at bar O=27.75 H=28 L=25 C=25.5
- **AUUD** (2025-10-16): entry $2.42 misaligned at bar O=17.21 H=17.25 L=16.79 C=16.86; exit $2.3043 misaligned at bar O=17.21 H=17.25 L=16.79 C=16.86
- **ZNB** (2025-10-15): entry $2.1349 misaligned at bar O=193 H=193 L=190 C=190; exit $2.035 misaligned at bar O=193 H=193 L=190 C=190
- **MNTS** (2025-10-14): entry $1.66 misaligned at bar O=28.74 H=28.92 L=27.85 C=27.95; exit $1.8743 misaligned at bar O=28.74 H=28.92 L=27.85 C=27.95
- **SPRC** (2025-09-30): entry $6.38 misaligned at bar O=52.92 H=54.54 L=52.47 C=53.82; exit $6.1701 misaligned at bar O=52.92 H=54.54 L=52.47 C=53.82
- **BOXL** (2025-09-22): entry $5.6767 misaligned at bar O=114.12 H=114.12 L=108.72 C=111.6; exit $6.4713 misaligned at bar O=114.12 H=114.12 L=108.72 C=111.6
- **SPRC** (2025-09-17): entry $4.51 misaligned at bar O=33.66 H=36 L=32.85 C=35.54; exit $5.16 misaligned at bar O=33.66 H=36 L=32.85 C=35.54
- **WLDS** (2025-09-10): entry $5.7 misaligned at bar O=46.17 H=47.43 L=44.91 C=47.43; exit $6.7 misaligned at bar O=46.17 H=47.43 L=44.91 C=47.43

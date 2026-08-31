# Replay chart integrity audit — 2026-07-15

Status:      ACTIVE
as_of:       2026-07-16T11:44:07-04:00
Measured at: efcc51365 / not measured

**Audited:** 2026-07-15T19:27:04.077903+00:00  
**Trades:** 103 · OK 86 · WARN 17 · FAIL 0  
**Scale fix:** `volume_isolated_overlay_v3.4` (volume on isolated overlay scale; candle autoscale from OHLC only)

## Summary

| Status | Count | Meaning |
|--------|------:|---------|
| ok | 86 | Bars loaded; markers in range |
| warn | 17 | Finviz fallback or marker outside bar range |
| fail | 0 | No chart data / API error |

## Per-trade

| Symbol | Close | Bars | Source | Range | Status |
|--------|-------|-----:|--------|-------|--------|
| XCUR | 2026-07-15 | 57 | alpaca | $1.57–$1.99 | ok |
| FCNTX | 2026-07-13 | 207 | schwab | $22.18–$27.05 | ok |
| NEE | 2026-07-13 | 40 | schwab | $83.38–$91.6 | ok |
| LGPS | 2026-07-13 | 54 | alpaca | $1.1–$1.34 | ok |
| ARKQ | 2026-07-13 | 185 | schwab | $98.35–$144.416 | ok |
| ELAB | 2026-07-10 | 55 | alpaca | $1.25–$1.56 | ok |
| PFLT | 2026-07-09 | 185 | schwab | $7.02–$9.75 | ok |
| ARKG | 2026-07-08 | 185 | schwab | $24.6–$44.465 | ok |
| BJDX | 2026-07-07 | 56 | alpaca | $1.36–$1.48 | ok |
| PEW | 2026-07-06 | 57 | alpaca | $2.62–$2.87 | ok |
| RKLB | 2026-07-02 | 145 | schwab | $52.68–$150.9999 | ok |
| TDG | 2026-07-01 | 145 | schwab | $1123.61–$1463.025 | ok |
| PETS | 2026-06-29 | 46 | alpaca | $2–$2.35 | ok |
| DRS | 2026-06-26 | 145 | schwab | $32.43–$50.59 | ok |
| VTAK | 2026-06-25 | 50 | alpaca | $0.92–$1.08 | ok |
| LMT | 2026-06-23 | 145 | schwab | $462.25–$692.0 | ok |
| LHX | 2026-06-23 | 145 | schwab | $277.57–$379.23 | ok |
| KTOS | 2026-06-22 | 145 | schwab | $46.01–$134.0 | ok |
| KBR | 2026-06-22 | 145 | schwab | $29.94–$45.365 | ok |
| AVAV | 2026-06-18 | 145 | schwab | $135.2–$408.25 | ok |
| IRDM | 2026-06-16 | 145 | schwab | $16.3–$57.18 | ok |
| CAST | 2026-06-15 | 53 | alpaca | $4.15–$5.2 | ok |
| RGNT | 2026-06-09 | 46 | alpaca | $2.78–$3.78 | ok |
| GOVX | 2026-05-18 | 65 | alpaca | $2.83–$4.39 | ok |
| PRSO | 2026-05-11 | 50 | alpaca | $1.1–$1.29 | ok |
| FATN | 2026-04-30 | 47 | alpaca | $3.35–$3.73 | ok |
| DFSC | 2026-04-30 | 43 | alpaca | $2.65–$3.17 | ok |
| V | 2026-04-21 | 12 | alpaca | $293.89–$359.66 | ok |
| PFE | 2026-04-21 | 6 | alpaca | $23.62–$28.745 | ok |
| V | 2026-04-06 | 125 | alpaca | $66.12–$375.51 | marker_warn |
| GERN | 2026-02-26 | 12 | alpaca | $1.26–$2.01 | ok |
| GERN | 2026-02-26 | 12 | alpaca | $1.26–$2.01 | ok |
| ADBE | 2026-02-23 | 20 | alpaca | $224.13–$587.75 | ok |
| ADBE | 2026-02-12 | 19 | alpaca | $233.155–$587.75 | ok |
| CSWC | 2026-02-12 | 10 | alpaca | $21.33–$23.84 | ok |
| 73017P409 | 2026-02-11 | 0 | finviz | — | fallback |
| PFLT | 2026-02-11 | 10 | alpaca | $8.16–$9.75 | ok |
| PHIO | 2026-02-10 | 66 | alpaca | $1.24–$1.48 | ok |
| DHX | 2026-02-05 | 59 | alpaca | $1.98–$2.2 | ok |
| FUSE | 2026-02-03 | 47 | alpaca | $2.62–$3.24 | ok |
| FUSE | 2026-02-02 | 48 | alpaca | $2.26–$3.67 | ok |
| ALXO | 2026-01-30 | 85 | alpaca | $1.64–$1.93 | ok |
| WRD | 2026-01-30 | 8 | alpaca | $6.88–$10.015 | ok |
| ZSL | 2026-01-30 | 46 | alpaca | $17–$21.9 | marker_warn |
| ARKG | 2026-01-30 | 8 | alpaca | $27.36–$34.39 | ok |
| TRX | 2026-01-29 | 121 | alpaca | $2–$2.8 | ok |
| GCTS | 2026-01-29 | 57 | alpaca | $1.47–$1.84 | ok |
| NUWE | 2026-01-27 | 64 | alpaca | $130.55–$172.9 | marker_warn |
| 44984F807 | 2026-01-27 | 0 | finviz | — | fallback |
| GXAI | 2026-01-26 | 49 | alpaca | $1.57–$2.16 | ok |
| AXTI | 2026-01-22 | 7 | alpaca | $2.83–$71.4899 | ok |
| APAM | 2026-01-20 | 10 | alpaca | $34.99–$48.5 | ok |
| SHPH | 2026-01-20 | 46 | alpaca | $35.1–$44.4 | marker_warn |
| 44984F807 | 2026-01-20 | 0 | finviz | — | fallback |
| SIBN | 2026-01-15 | 7 | alpaca | $16.66–$21.28 | ok |
| AXTI | 2026-01-08 | 6 | alpaca | $2.83–$41.19 | ok |
| AXTI | 2026-01-08 | 6 | alpaca | $2.83–$41.19 | ok |
| BNAI | 2026-01-02 | 46 | alpaca | $3.81–$4.15 | ok |
| APAM | 2025-12-31 | 11 | alpaca | $39.94–$45.5236 | ok |
| EKSO | 2025-12-30 | 59 | alpaca | $7.8001–$9.1199 | ok |
| SOPAQ | 2025-12-29 | 0 | finviz | — | fallback |
| OLOX | 2025-11-13 | 46 | alpaca | $30.3–$39.8 | marker_warn |
| MSGM | 2025-11-07 | 50 | alpaca | $4.11–$5.8 | ok |
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
| MNTS | 2025-10-14 | 186 | alpaca | $27.85–$38.02 | marker_warn |
| STI | 2025-10-13 | 45 | alpaca | $7.8–$13.51 | ok |
| ELBM | 2025-10-13 | 56 | alpaca | $1.95–$5.24 | ok |
| GWH | 2025-10-10 | 46 | alpaca | $3.01–$4.9 | ok |
| TELO | 2025-10-09 | 52 | alpaca | $1.8487–$2.34 | ok |
| SPRC | 2025-09-30 | 45 | alpaca | $52.47–$63.9 | marker_warn |
| AMD | 2025-09-30 | 250 | alpaca | $159.33–$162.28 | ok |
| RDHL | 2025-09-29 | 45 | alpaca | $2.5–$3.3599 | ok |
| NUAI | 2025-09-26 | 219 | alpaca | $1.42–$2.55 | ok |
| PEPG | 2025-09-25 | 58 | alpaca | $4.58–$7.7198 | ok |
| LAC | 2025-09-25 | 56 | alpaca | $6.74–$7.53 | ok |
| SHFS | 2025-09-25 | 8 | alpaca | $3.07–$9.19 | ok |
| SHFS | 2025-09-24 | 52 | alpaca | $7.9–$9.74 | ok |
| SSKN | 2025-09-23 | 256 | alpaca | $2.05–$4.18 | ok |
| SLNH | 2025-09-23 | 56 | alpaca | $2.32–$3.58 | ok |
| BOXL | 2025-09-22 | 84 | alpaca | $119.52–$312.12 | marker_warn |
| AGMH | 2025-09-19 | 123 | alpaca | $6.23–$12.8999 | ok |
| LASE | 2025-09-18 | 303 | alpaca | $3.45–$5.88 | ok |
| SPRC | 2025-09-17 | 52 | alpaca | $32.85–$57.24 | marker_warn |
| IHT | 2025-09-15 | 49 | alpaca | $3.04–$4.24 | ok |
| MOGU | 2025-09-11 | 62 | alpaca | $4.81–$8.52 | ok |
| WLDS | 2025-09-10 | 53 | alpaca | $44.91–$65.79 | marker_warn |
| AXTI | 2025-08-20 | 112 | alpaca | $2.2–$2.65 | ok |
| XMTR | 2025-08-19 | 8 | alpaca | $30.63–$51.6815 | ok |
| SLDP | 2025-08-08 | 9 | alpaca | $2.9–$4.83 | ok |
| BRO | 2025-07-29 | 8 | alpaca | $90.38–$111.1 | ok |
| BRO | 2025-07-29 | 8 | alpaca | $90.38–$111.1 | ok |

## Issues

- **V** (2026-04-06): entry $10.75 misaligned at bar O=76.06 H=76.51 L=68.76 C=74.49
- **73017P409** (2026-02-11): alpaca 400
- **ZSL** (2026-01-30): entry $2.07 misaligned at bar O=20.8 H=20.8 L=20.7 C=20.7; exit $2.0405 misaligned at bar O=20.48 H=20.48 L=17 C=20.39
- **NUWE** (2026-01-27): entry $4.37 misaligned at bar O=146.48 H=148.75 L=142.8 C=147; exit $4.3404 misaligned at bar O=150.46 H=153.65 L=148.75 C=151.9
- **44984F807** (2026-01-27): alpaca 400
- **SHPH** (2026-01-20): entry $4.29 misaligned at bar O=39.2 H=44.4 L=38.1 C=42.1; exit $4.0301 misaligned at bar O=41.7 H=42.1 L=39.2 C=40.06
- **44984F807** (2026-01-20): alpaca 400
- **SOPAQ** (2025-12-29): no Alpaca bars for this symbol/window
- **OLOX** (2025-11-13): entry $3.47 misaligned at bar O=33.4 H=33.51 L=30.3 C=31; exit $3.3701 misaligned at bar O=33.4 H=33.51 L=30.3 C=31
- **AIRE** (2025-10-22): entry $1.29 misaligned at bar O=30.75 H=31.75 L=30.25 C=31.75; exit $1.15 misaligned at bar O=30.38 H=30.5 L=28.5 C=29.25
- **AUUD** (2025-10-16): entry $2.42 misaligned at bar O=17.63 H=17.71 L=17.56 C=17.63; exit $2.3043 misaligned at bar O=18.33 H=18.4 L=17.56 C=17.79
- **ZNB** (2025-10-15): entry $2.1349 misaligned at bar O=209.92 H=210 L=209 C=210; exit $2.035 misaligned at bar O=204.5 H=204.97 L=201 C=201.5
- **MNTS** (2025-10-14): entry $1.66 misaligned at bar O=29.81 H=29.81 L=29.45 C=29.81; exit $1.8743 misaligned at bar O=32.31 H=32.49 L=32.13 C=32.13
- **SPRC** (2025-09-30): entry $6.38 misaligned at bar O=53.8 H=59.22 L=53.55 C=58.5; exit $6.1701 misaligned at bar O=56.88 H=57.51 L=54.54 C=55.7
- **BOXL** (2025-09-22): entry $5.24 misaligned at bar O=138.6 H=192.96 L=128.52 C=189; exit $6.4713 misaligned at bar O=216 H=227.52 L=211.32 C=227.16
- **SPRC** (2025-09-17): entry $4.51 misaligned at bar O=40.82 H=41.94 L=38.97 C=41.4; exit $5.16 misaligned at bar O=46.93 H=47.61 L=43.65 C=45.36
- **WLDS** (2025-09-10): entry $5.7 misaligned at bar O=48.96 H=51.93 L=48.69 C=50.58; exit $6.7 misaligned at bar O=51.93 H=60.03 L=51.84 C=57.22

# Replay chart integrity audit — 2026-07-11

Status:      HISTORICAL
as_of:       2026-07-14T07:52:59-04:00
Measured at: efcc51365 / not measured

**Audited:** 2026-07-11T20:40:03.493465+00:00
**Trades:** 98 · OK 29 · WARN 69 · FAIL 0
**Scale fix:** `volume_isolated_overlay_v3.4` (volume on isolated overlay scale; candle autoscale from OHLC only)

## Summary

| Status | Count | Meaning |
|--------|------:|---------|
| ok | 29 | Bars loaded; markers in range |
| warn | 69 | Finviz fallback or marker outside bar range |
| fail | 0 | No chart data / API error |

## Per-trade

| Symbol | Close | Bars | Source | Range | Status |
|--------|-------|-----:|--------|-------|--------|
| ELAB | 2026-07-10 | 41 | yahoo | $1.2501–$1.56 | ok |
| PFLT | 2026-07-09 | 141 | yahoo | $7.02–$9.091944 | marker_warn |
| ARKG | 2026-07-08 | 181 | yahoo | $24.6–$44.465 | ok |
| BJDX | 2026-07-07 | 35 | yahoo | $1.51–$1.8 | ok |
| PEW | 2026-07-06 | 47 | yahoo | $2.65–$2.87 | ok |
| RKLB | 2026-07-02 | 141 | yahoo | $52.68–$151.0 | ok |
| TDG | 2026-07-01 | 141 | yahoo | $1123.609985–$1463.030029 | ok |
| PETS | 2026-06-29 | 35 | yahoo | $2.0–$2.35 | ok |
| DRS | 2026-06-26 | 141 | yahoo | $32.300437–$50.59 | ok |
| VTAK | 2026-06-25 | 40 | yahoo | $0.92–$1.08 | ok |
| LHX | 2026-06-23 | 141 | yahoo | $275.490367–$376.388668 | ok |
| LMT | 2026-06-23 | 141 | yahoo | $456.83596–$687.499244 | ok |
| KTOS | 2026-06-22 | 141 | yahoo | $46.009998–$134.0 | ok |
| KBR | 2026-06-22 | 141 | yahoo | $29.802163–$44.95858 | ok |
| AVAV | 2026-06-18 | 141 | yahoo | $135.199997–$408.25 | ok |
| IRDM | 2026-06-16 | 141 | yahoo | $16.150291–$57.18 | ok |
| CAST | 2026-06-15 | 23 | yahoo | $4.15–$4.95 | marker_warn |
| RGNT | 2026-06-09 | 0 | finviz | — | fallback |
| GOVX | 2026-05-18 | 0 | finviz | — | fallback |
| PRSO | 2026-05-11 | 0 | finviz | — | fallback |
| FATN | 2026-04-30 | 0 | finviz | — | fallback |
| DFSC | 2026-04-30 | 0 | finviz | — | fallback |
| PFE | 2026-04-21 | 118 | yahoo | $24.02436–$28.283138 | ok |
| V | 2026-04-21 | 243 | yahoo | $293.282019–$357.141626 | marker_warn |
| V | 2026-04-06 | 4573 | yahoo | $9.212624–$372.56717 | marker_warn |
| GERN | 2026-02-26 | 58 | yahoo | $1.26–$2.01 | ok |
| GERN | 2026-02-26 | 58 | yahoo | $1.26–$2.01 | ok |
| ADBE | 2026-02-23 | 411 | yahoo | $227.699997–$587.75 | ok |
| ADBE | 2026-02-12 | 403 | yahoo | $233.160004–$587.75 | ok |
| CSWC | 2026-02-12 | 46 | yahoo | $20.179806–$22.741711 | marker_warn |
| PFLT | 2026-02-11 | 45 | yahoo | $7.802816–$9.091942 | marker_warn |
| 73017P409 | 2026-02-11 | 0 | finviz | — | fallback |
| PHIO | 2026-02-10 | 0 | finviz | — | fallback |
| DHX | 2026-02-05 | 0 | finviz | — | fallback |
| FUSE | 2026-02-03 | 0 | finviz | — | fallback |
| FUSE | 2026-02-02 | 0 | finviz | — | fallback |
| ZSL | 2026-01-30 | 0 | finviz | — | fallback |
| WRD | 2026-01-30 | 40 | yahoo | $6.88–$10.015 | ok |
| ARKG | 2026-01-30 | 39 | yahoo | $27.360001–$34.389999 | ok |
| ALXO | 2026-01-30 | 0 | finviz | — | fallback |
| GCTS | 2026-01-29 | 0 | finviz | — | fallback |
| TRX | 2026-01-29 | 0 | finviz | — | fallback |
| NUWE | 2026-01-27 | 0 | finviz | — | fallback |
| 44984F807 | 2026-01-27 | 0 | finviz | — | fallback |
| GXAI | 2026-01-26 | 0 | finviz | — | fallback |
| AXTI | 2026-01-22 | 139 | yahoo | $2.06–$47.029999 | ok |
| APAM | 2026-01-20 | 201 | yahoo | $35.966561–$44.172653 | marker_warn |
| SHPH | 2026-01-20 | 0 | finviz | — | fallback |
| 44984F807 | 2026-01-20 | 0 | finviz | — | fallback |
| SIBN | 2026-01-15 | 7 | yahoo | $16.66–$21.280001 | ok |
| AXTI | 2026-01-08 | 129 | yahoo | $2.06–$30.799999 | marker_warn |
| AXTI | 2026-01-08 | 129 | yahoo | $2.06–$30.799999 | marker_warn |
| BNAI | 2026-01-02 | 0 | finviz | — | fallback |
| APAM | 2025-12-31 | 51 | yahoo | $37.703953–$42.101649 | marker_warn |
| EKSO | 2025-12-30 | 0 | finviz | — | fallback |
| SOPAQ | 2025-12-29 | 0 | finviz | — | fallback |
| OLOX | 2025-11-13 | 0 | finviz | — | fallback |
| MSGM | 2025-11-07 | 0 | finviz | — | fallback |
| VIVS | 2025-10-30 | 0 | finviz | — | fallback |
| IBIO | 2025-10-23 | 0 | finviz | — | fallback |
| AIRE | 2025-10-22 | 0 | finviz | — | fallback |
| IBIO | 2025-10-21 | 0 | finviz | — | fallback |
| NERV | 2025-10-21 | 0 | finviz | — | fallback |
| BOF | 2025-10-21 | 0 | finviz | — | fallback |
| GSIT | 2025-10-20 | 0 | finviz | — | fallback |
| GSIT | 2025-10-20 | 0 | finviz | — | fallback |
| RANI | 2025-10-17 | 0 | finviz | — | fallback |
| ACHV | 2025-10-17 | 0 | finviz | — | fallback |
| CTXR | 2025-10-16 | 0 | finviz | — | fallback |
| AUUD | 2025-10-16 | 0 | finviz | — | fallback |
| ZNB | 2025-10-15 | 0 | finviz | — | fallback |
| MNTS | 2025-10-14 | 0 | finviz | — | fallback |
| ELBM | 2025-10-13 | 0 | finviz | — | fallback |
| STI | 2025-10-13 | 0 | finviz | — | fallback |
| GWH | 2025-10-10 | 0 | finviz | — | fallback |
| TELO | 2025-10-09 | 0 | finviz | — | fallback |
| SPRC | 2025-09-30 | 0 | finviz | — | fallback |
| AMD | 2025-09-30 | 0 | finviz | — | fallback |
| RDHL | 2025-09-29 | 0 | finviz | — | fallback |
| NUAI | 2025-09-26 | 0 | finviz | — | fallback |
| PEPG | 2025-09-25 | 0 | finviz | — | fallback |
| LAC | 2025-09-25 | 0 | finviz | — | fallback |
| SHFS | 2025-09-25 | 8 | yahoo | $3.07–$9.19 | ok |
| SHFS | 2025-09-24 | 0 | finviz | — | fallback |
| SSKN | 2025-09-23 | 0 | finviz | — | fallback |
| SLNH | 2025-09-23 | 0 | finviz | — | fallback |
| BOXL | 2025-09-22 | 0 | finviz | — | fallback |
| AGMH | 2025-09-19 | 0 | finviz | — | fallback |
| LASE | 2025-09-18 | 0 | finviz | — | fallback |
| SPRC | 2025-09-17 | 0 | finviz | — | fallback |
| IHT | 2025-09-15 | 0 | finviz | — | fallback |
| MOGU | 2025-09-11 | 0 | finviz | — | fallback |
| WLDS | 2025-09-10 | 0 | finviz | — | fallback |
| AXTI | 2025-08-20 | 0 | finviz | — | fallback |
| XMTR | 2025-08-19 | 40 | yahoo | $30.629999–$51.681999 | ok |
| SLDP | 2025-08-08 | 9 | yahoo | $2.9–$4.83 | ok |
| BRO | 2025-07-29 | 37 | yahoo | $89.579359–$110.115821 | ok |
| BRO | 2025-07-29 | 37 | yahoo | $89.579359–$110.115821 | ok |

## Issues

- **PFLT** (2026-07-09): entry $8.2579 misaligned at bar O=7.716966239734838 H=8.022210590180741 L=7.602499153467663 C=7.926822185516357
- **CAST** (2026-06-15): entry $5.0197 misaligned at bar O=4.849899768829346 H=4.889999866485596 L=4.5 C=4.790500164031982; exit $5.1305 misaligned at bar O=4.849899768829346 H=4.889999866485596 L=4.5 C=4.790500164031982
- **RGNT** (2026-06-09): no Alpaca keys
- **GOVX** (2026-05-18): no Alpaca keys
- **PRSO** (2026-05-11): no Alpaca keys
- **FATN** (2026-04-30): no Alpaca keys
- **DFSC** (2026-04-30): no Alpaca keys
- **V** (2026-04-21): entry $331.484 misaligned at bar O=347.18230266311 H=348.0370800581514 L=343.97196611477676 C=347.93768310546875
- **V** (2026-04-06): entry $10.75 misaligned at bar O=13.075434786028568 H=15.16310924766338 L=12.086536356833129 C=12.416169166564941
- **CSWC** (2026-02-12): entry $23.61 misaligned at bar O=22.52230594810094 H=22.741709587417176 L=22.436452033676577 C=22.589080810546875; exit $22.93 misaligned at bar O=22.302901110944976 H=22.32198016345518 L=21.845014767571616 C=22.007183074951172
- **PFLT** (2026-02-11): entry $9.53 misaligned at bar O=9.029196344878896 H=9.08574703108023 L=8.963221293346226 C=8.982070922851562; exit $9.01 misaligned at bar O=8.605068059258242 H=8.680468363704811 L=8.42599166206574 C=8.539093017578125
- **73017P409** (2026-02-11): no Alpaca keys
- **PHIO** (2026-02-10): no Alpaca keys
- **DHX** (2026-02-05): no Alpaca keys
- **FUSE** (2026-02-03): no Alpaca keys
- **FUSE** (2026-02-02): no Alpaca keys
- **ZSL** (2026-01-30): no Alpaca keys
- **ALXO** (2026-01-30): no Alpaca keys
- **GCTS** (2026-01-29): no Alpaca keys
- **TRX** (2026-01-29): no Alpaca keys
- **NUWE** (2026-01-27): no Alpaca keys
- **44984F807** (2026-01-27): no Alpaca keys
- **GXAI** (2026-01-26): no Alpaca keys
- **APAM** (2026-01-20): entry $46.9574 misaligned at bar O=42.99881160297231 H=43.590749916329194 L=42.77683297134815 C=43.489009857177734; exit $42.57 misaligned at bar O=41.04576876220218 H=41.30065322567351 L=40.13951529283603 C=40.41328048706055
- **SHPH** (2026-01-20): no Alpaca keys
- **44984F807** (2026-01-20): no Alpaca keys
- **AXTI** (2026-01-08): exit $18.99 misaligned at bar O=24.3700008392334 H=25.979999542236328 L=22.899999618530273 C=25.829999923706055
- **AXTI** (2026-01-08): exit $18.83 misaligned at bar O=24.3700008392334 H=25.979999542236328 L=22.899999618530273 C=25.829999923706055
- **BNAI** (2026-01-02): no Alpaca keys
- **APAM** (2025-12-31): entry $41.5677 misaligned at bar O=39.70526810404353 H=39.70526810404353 L=38.997256927017204 C=39.157737731933594; exit $40.8221 misaligned at bar O=38.751813629870234 H=38.883975148914885 L=38.37420980418998 C=38.459171295166016
- **EKSO** (2025-12-30): no Alpaca keys
- **SOPAQ** (2025-12-29): no Alpaca keys
- **OLOX** (2025-11-13): no Alpaca keys
- **MSGM** (2025-11-07): no Alpaca keys
- **VIVS** (2025-10-30): no Alpaca keys
- **IBIO** (2025-10-23): no Alpaca keys
- **AIRE** (2025-10-22): no Alpaca keys
- **IBIO** (2025-10-21): no Alpaca keys
- **NERV** (2025-10-21): no Alpaca keys
- **BOF** (2025-10-21): no Alpaca keys
- **GSIT** (2025-10-20): no Alpaca keys
- **GSIT** (2025-10-20): no Alpaca keys
- **RANI** (2025-10-17): no Alpaca keys
- **ACHV** (2025-10-17): no Alpaca keys
- **CTXR** (2025-10-16): no Alpaca keys
- **AUUD** (2025-10-16): no Alpaca keys
- **ZNB** (2025-10-15): no Alpaca keys
- **MNTS** (2025-10-14): no Alpaca keys
- **ELBM** (2025-10-13): no Alpaca keys
- **STI** (2025-10-13): no Alpaca keys
- **GWH** (2025-10-10): no Alpaca keys
- **TELO** (2025-10-09): no Alpaca keys
- **SPRC** (2025-09-30): no Alpaca keys
- **AMD** (2025-09-30): no Alpaca keys
- **RDHL** (2025-09-29): no Alpaca keys
- **NUAI** (2025-09-26): no Alpaca keys
- **PEPG** (2025-09-25): no Alpaca keys
- **LAC** (2025-09-25): no Alpaca keys
- **SHFS** (2025-09-24): no Alpaca keys
- **SSKN** (2025-09-23): no Alpaca keys
- **SLNH** (2025-09-23): no Alpaca keys
- **BOXL** (2025-09-22): no Alpaca keys
- **AGMH** (2025-09-19): no Alpaca keys
- **LASE** (2025-09-18): no Alpaca keys
- **SPRC** (2025-09-17): no Alpaca keys
- **IHT** (2025-09-15): no Alpaca keys
- **MOGU** (2025-09-11): no Alpaca keys
- **WLDS** (2025-09-10): no Alpaca keys
- **AXTI** (2025-08-20): no Alpaca keys

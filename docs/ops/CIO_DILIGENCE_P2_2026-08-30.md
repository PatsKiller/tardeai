# CIO Diligence Phase 2 — identity confidence + position state

Date: 2026-08-30  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0  
CURRENT pin: `852ecd47` (#681)  
**Do NOT promote** this PR — advisory evidence + read-only harness only.

## Packages

| ID | Title | Status |
|----|-------|--------|
| P2-WS4 | Identity confidence score | **DONE** |
| P2-WS5 | HELD/EXIT/WATCH/CASH/DUST matrix | **DONE** |

## Delivered

| Artifact | Path |
|----------|------|
| Census CLI (`--json`) | `scripts/cio_identity_confidence_census.py` |
| Library | `scripts/lib/cio_identity_confidence_census.py` |
| WS4 audit (live numbers) | `docs/audits/diligence/P2_WS4_IDENTITY_CONFIDENCE_2026-08-30.md` |
| WS5 matrix audit | `docs/audits/diligence/P2_WS5_POSITION_STATE_MATRIX_2026-08-30.md` |
| Tests | `tests/test_cio_identity_confidence_census.py` |
| Scoreboard | `docs/ops/CIO_DILIGENCE_SCOREBOARD.md` + `.json` |
| Gap register | `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md` (G-ID-01 updated) |

## Headline live metrics

- **Production resolvable:** **98.9%** (88/89; miss=`HEALTH`)  
- **Identity confidence (production cohort):** **0.7996**  
- **HELD nondust / active watch:** **100%** resolvable, CONFIRMED  
- **Stamped carriage:** **4.8%** product surfaces (NPI 100%; others 0%)  
- **SCHG Surface A:** **EXITED** (`residual_shares=0.2294`)  
- **Dust table:** share`<1` = 6 · MV`<$50` = 4 · CUSIP ids = 3 · CASH = $630,784.82  
- **Minted / lots deleted:** **0 / 0**

## Rails

READ_ONLY_ADVISORY · MBI=0 · no broker · no notify-on · no lot DELETE · no registry write · no auto-stamp · One PR · TRADEAI_REMOTE_PUSH_AUTHORIZED=1 for this push only · **Do NOT promote**

## Next

P1 packages remain PENDING on the scoreboard. Follow-on for G-ID-01: stamp reentry/watch/holdings (deliberate carriage PR) + register former-table `HEALTH` if still a real EXIT name.

# Observation Windows

All boundaries are timezone-aware America/New_York. Half-open [start, end); the 10:05:00 capture
endpoint is inclusive so a continuous 09:30:00->10:05:00 stream measures exactly 35:00.

| Window | Start ET | End ET | Role |
|---|---|---|---|
| P1 | 07:00:00 | 08:00:00 | early premarket |
| P2 | 08:00:00 | 09:20:00 | core momentum discovery |
| P3 | 09:20:00 | 09:30:00 | open-approach |
| R1 | 09:30:00 | 09:45:00 | opening transition |
| R2 | 09:45:00 | 10:05:00 (incl.) | post-open validation |
| OUTSIDE | — | — | anything else |

## Accounting
- **Accepted minutes:** sum of inter-event spans <= max_silence (60s); larger gaps are silence, not counted.
- **Longest continuous minutes:** longest run with every inter-event gap <= 60s.
- **Exclusions:** cached first pushes (ineligible), STALE events, gap/drop-marked events, and startup
  margin (90s) are excluded from accepted time.
- **Premarket requirement:** >= 145 accepted minutes in [07:00, 09:30) (allowing the startup margin).
- **RTH requirement:** >= 35 continuous accepted minutes after 09:30.
- **Late start:** a start after 07:10 ET cannot produce a countable Session 1 (diagnostic only).

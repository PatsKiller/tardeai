# /v3-next Screen-State Matrix — Stage 6

| State | How represented | Example |
|---|---|---|
| Loaded | panel renders fixture data | prime queue rows |
| Empty | explicit empty state | (no session → NO_SESSION strip; fixtures show authorized) |
| Unavailable | `<Unavailable/>` marker (italic, testid=unavailable) | L2, tape, marks, null rvol/float |
| Stale | STALE warning in panel warning list | capabilities expired path |
| Conflict | CONFLICT warning | accounts discrepancy |
| Blocked (Moomoo) | 3 badges OFFLINE_IMPLEMENTED / CREDENTIAL_GATE_BLOCKED / LIVE_DATA_UNAVAILABLE; broker NOT_INSTALLED | moomoo badge + brokers panel |
| Redacted | REDACTED warning + `[REDACTED]` text | rejections raw message |
| Error | (fixtures are deterministic; live client would surface the Stage 4 error envelope) | n/a in fixtures |

No state fabricates live Level 2 or tape; all Moomoo-dependent values are explicit unavailable.

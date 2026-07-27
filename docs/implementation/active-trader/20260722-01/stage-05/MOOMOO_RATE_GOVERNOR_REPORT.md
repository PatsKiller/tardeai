# Moomoo Rate Governor Report — Stage 5

`scripts/active_trader/moomoo/governor.py` — implemented and unit-tested, and (per the
data-only ruling) NOT attached to any trade API: Stage 5 has no trade surface, statically
enforced by the AST guard (0 trade methods reachable).

## Budgets (per account, per 30 s window) — owner-approved
| Class | Ceiling | Ordinary | Reserve |
|---|---:|---:|---:|
| PLACE | 15 | 12 | 3 |
| MODIFY_CANCEL | 20 | 16 | 4 |
| SNAPSHOT | 60 | 48 | 12 |

## Mechanism (tested)
Token-bucket AND exact sliding-window: both must admit; ordinary + reserve == ceiling
(constructor-enforced). Ordinary traffic can NEVER borrow the reserve; the reserve is
protection-only; the provider ceiling is absolute (refused even for protection). Sliding
window ages out at exactly the window length. **Conservative restart**: a fresh governor
assumes the ordinary window is FULL until it ages out. Thread-safe under 100 concurrent
acquirers (never exceeds ordinary/ceiling). Snapshot uses batching (≤100 symbols/request),
never polling to replace push data.

TRADE REQUESTS EMITTED: 0 (no trade API exists in Stage 5).

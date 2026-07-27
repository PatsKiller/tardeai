# Premarket Observation Harness — Security Proof

| Control | Result |
|---|---|
| Trade-API AST scan (35 active_trader modules + run-root) | **0 findings** |
| Data-only adapter Protocol | only quote/data methods; no trade context/method; no generic invoke |
| Network in harness core | 0 (no requests/socket/urllib/OpenQuoteContext in calendar/observation/selector/schedule) |
| OpenD / Moomoo login / subscribe | none started; live path refuses without owner marker |
| Scheduler invocation | none; renderer never calls systemd-run/systemctl/at/cron |
| Transient/persistent timer created | none |
| `--execute-schedule` | returns NOT_AUTHORIZED_BY_BUILD_TRANSACTION |
| Live without marker | returns BLOCKED_OWNER_AUTHORIZATION_REQUIRED |
| Authorization marker | contains no secret (rejects password/token/secret/sms/unlock/pin) |
| Production DB / DSN / port 5432 / prod checkout path | none referenced in harness |
| Tests | fakes/fixtures/virtual clocks only; no network, no OpenD, no scheduler, no production target |
| Quote-right auto-grab | N/A (no live subscribe); Stage 5 config auto_hold_quote_right=0 unchanged |

The only `subprocess` use in the harness is a local `git rev-parse HEAD` in the composition root to read
the worktree's own SHA for authorization verification — not a scheduler, network, or trade call.

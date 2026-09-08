# Operator decisions — m2-canary-20260907 Stage-2/3

Recorded: 2026-09-08T21:05Z  
Updated: 2026-09-08T21:18Z  

Source: operator replies in independent-architect chat (`1.ok, 2 approve, 3 yes, 4. ok`)

| # | Question | Decision |
|---|---|---|
| 1 | Deploy pin | **Operator deferred — architect chooses `origin/main` at prepare time** (done: `aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816`) |
| 2 | Grants | **Yes** — release-write, service, cron, telegram, DB read |
| 3 | CANARY allowlist | **Yes** |
| 4 | Human Telegram reply | **Yes** — chat `1.ok` = proceed; **still need actual Telegram free-text `OK` to canary msg** (DB has no text OK after 21:12Z SETTLED outbound) |
| 5 | Inbound apply (not dark) | **Yes** |
| 6 | Research non-none | **ORGANIC_ONLY** locked by `4. ok`; 48h clock from epoch 21:08:30Z |
| 7 | Drive sync after promote | **Yes** |
| 8 | Dirty maintree | **Yes clear** — porcelain empty at 21:15Z; branch `local/m2-canary-soak-exec` @ `aaa9115cb` |
| 9 | Success bar | **Stage-3 organic soak seal** |
| 10 | Start mutations | **Yes** |

## Epoch

- started_at: 2026-09-08T21:08:30Z
- served_pin: aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816
- organic_non_none_deadline_utc: 2026-09-10T21:08:30Z

## Closeout note (2026-09-08T22:38Z)

Stage-2 activate complete (inbound OK proven). Stage-3 ORGANIC_ONLY soak still open — see `evidence/STAGE2_STAGE3_HANDOFF.md`.
# PROPOSED — operator decision required (AGENTS.md §9.3 / §17)

```
Status: PROPOSED
Effective-Date: PENDING
as_of: 2026-09-20T12:45:00-04:00
Measured at: host systemctl --user list-timers — zero stance-organic observe units;
  unit files landed in repo at 80ca81295 (+ Unit= fix on early timer)
Canonical repo path: docs/ops/PROPOSED_INSTALL_STANCE_ORGANIC_OBSERVE_TIMERS_2026-09-20.md
Authority: propose-and-stop — installing/enabling user systemd timers is operator-only
See also: PARTIAL-telegram-CIO-stance; scripts/report_organic_stance_hold.py;
  config/systemd/user/tradeai-stance-organic-observe{,-early}.timer
  + tradeai-stance-organic-observe.service
```

## Finding

Producer crons for all three `ORGANIC_HOLD_CALLERS` are **CONFIRMED** Mon–Fri.
Organic observe itself had **no host timer** — only Cursor campaign timers and manual remasure.
Repo now carries read-only observe units (oneshot `report_organic_stance_hold.py --json`,
`SuccessExitStatus=0 2`). They are **not** installed on the host.

Cursor timers `stance-organic-observe-early` / `stance-organic-observe` remain a parallel
path; host units make Monday observe survive without the Cursor agent session.

## Exact operator decision ask

Reply with one of:

1. **APPROVE_INSTALL_STANCE_ORGANIC_OBSERVE_TIMERS** — install from CURRENT (or this tip after merge):
   ```bash
   install -m 0644 \
     config/systemd/user/tradeai-stance-organic-observe.service \
     config/systemd/user/tradeai-stance-organic-observe.timer \
     config/systemd/user/tradeai-stance-organic-observe-early.timer \
     ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now \
     tradeai-stance-organic-observe.timer \
     tradeai-stance-organic-observe-early.timer
   systemctl --user list-timers 'tradeai-stance-organic-observe*'
   ```
2. **DEFER** — keep Cursor observe timers only; host units stay in repo uninstalled.
3. **REJECT** — do not install; document reason on this file.

No agent may `enable --now` these units without the APPROVE_* token.

## Residual

Organic OBSERVED still requires a natural Mon–Fri hold
(`source=check_investment_send` + caller in ORGANIC_HOLD_CALLERS). Timers only remasure.

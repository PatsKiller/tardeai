---
id: DSN-20261022-schwab-readonly-baseline
title: Kill switch + read-only Schwab baseline
status: IN_PROGRESS
approval: approved (approval L; AGENTS 20.0.0 §28.6 LIVE); clearing switches is the operator's alone
source: AGENTS.md §28.6; docs/ops/packets/incident-spcx-resume-20261022/README.md
summary: 'Three barriers: Schwab access mode read_only, every trading lock LOCKED, kill switches (live_submit may stay engaged
  on its own).'
phases:
- id: DSN-20261022-schwab-readonly-baseline-P1
  title: 'Incident SPCX resume packet, registry truth, double-run fixes — #1933 (14 lines on, 4 held)'
  status: LIVE
- id: DSN-20261022-schwab-readonly-baseline-P2
  title: 'Kill-switch disable() TypeError + atomic state/audit — #1983'
  status: LIVE
- id: DSN-20261022-schwab-readonly-baseline-P3
  title: Read-only baseline in AGENTS 20.0.0 §28.6 (approval L)
  status: LIVE
- id: DSN-20261022-schwab-readonly-baseline-P4
  title: Clear the global kill switch (engaged since 2026-10-14)
  status: PROPOSED
  tasks:
  - id: DSN-20261022-schwab-readonly-baseline-P4-T1
    title: 'OPERATOR: clear global kill switch after #1983 live — board task T-20261023-847c24'
    status: PROPOSED
    areas:
    - scripts/brokers/kill_switches.py
    board_task: T-20261023-847c24
- id: DSN-20261022-schwab-readonly-baseline-P5
  title: Held items
  status: HELD
  tasks:
  - id: DSN-20261022-schwab-readonly-baseline-P5-T1
    title: 'OPERATOR: Grok stop review (held from the SPCX resume)'
    status: HELD
    areas:
    - operator/decisions/grok-stop-review
    owner: OPERATOR
---

Backfill 2026-10-23. #1933 LIVE f7c1e96cb (10-22); #1983 LIVE 80e93c99f. Positions without stops are the
operator's (verbatim: "I'll manage that.") and are not agent work. Broker orders, stops, 2FA and self-issued grants are
never covered by any approval.

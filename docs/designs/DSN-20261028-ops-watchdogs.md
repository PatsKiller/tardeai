---
id: DSN-20261028-ops-watchdogs
title: Ops watchdogs — arm the three designed-but-unwired guards (stoplight strip follow-on)
status: PROPOSED
approval: operator (§17 scheduler installs — arm self-heal-fixer, install pr-merge-notify.timer, wire the failure pager)
source: operator 2026-10-28 — "Why can't we have a mode in the command center that shows stoplights when these along with the alerts?"
phases:
  - id: DSN-20261028-ops-watchdogs-P1
    title: Surface the stoplights
    status: DONE
    tasks:
      - id: DSN-20261028-ops-watchdogs-P1-T1
        title: Jobs & health watchers & alerts strip (backend `watchers` projection + frontend)
        status: DONE
  - id: DSN-20261028-ops-watchdogs-P2
    title: Arm self-heal-fixer
    status: PROPOSED
    tasks:
      - id: DSN-20261028-ops-watchdogs-P2-T1
        title: Install the self-heal-fixer cron line (registry install_line, currently PAUSED)
        status: PROPOSED
  - id: DSN-20261028-ops-watchdogs-P3
    title: Install the merge-ready notifier
    status: PROPOSED
    tasks:
      - id: DSN-20261028-ops-watchdogs-P3-T1
        title: Install tradeai-pr-merge-notify.timer (per-PR green interrupt)
        status: PROPOSED
  - id: DSN-20261028-ops-watchdogs-P4
    title: Wire the failure pager
    status: PROPOSED
    tasks:
      - id: DSN-20261028-ops-watchdogs-P4-T1
        title: Register + trigger delivery_failure_alerts.py (P1 page on red CI / failed release)
        status: PROPOSED
  - id: DSN-20261028-ops-watchdogs-P5
    title: Optional action affordance — a bounded "Request fix" on the strip
    status: PROPOSED
    tasks:
      - id: DSN-20261028-ops-watchdogs-P5-T1
        title: Operator-session gated queue-self-heal endpoint + strip button (opens a PR, never merges)
        status: PROPOSED
---

# Ops watchdogs — arm the three designed-but-unwired guards

## Why

The operator asked for a command-center stoplight for the operations watchers alongside the alerts.
The stoplight strip (`DSN-20261028-ops-watchdogs-P1-T1`) is built and lands in the same PR as this design;
it renders four lights at the top of **Jobs & health** (`/ops/jobs`):

| Light | Today (measured) | Meaning |
|---|---|---|
| Missed-run watchdog | amber | independent monitor receipt stale/missing |
| Self-heal fixer | amber — `PAUSED` | designed, never armed |
| Merge notifier | amber — `NEVER_SCHEDULED` | unit not installed |
| Failure pager | red — absent | `delivery_failure_alerts.py` is not a registered job |

The strip is deliberately honest: an unwired guard renders red/amber, never silently green. This design is
the three §17 operator acts that turn the lights green.

## P2 — Arm self-heal-fixer (the resuscitator)

**Current state:** lane `self-heal-fixer`, `state: PAUSED`, `state_reason: PROPOSED, NOT INSTALLED (2026-10-16,
operator directive: self-heal code defects go to an iterative Claude Code fixer, not the governed LLM bridge).`
Its registry row already carries a validated `install_line`:

```
40 9-18 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/tradeai_self_heal_fixer.lock timeout 10800 $PY scripts/self_heal_fixer.py --cycle --apply >> logs/self_heal_fixer.log 2>&1  # TRADEAI_LANE self-heal-fixer
```

**The act (§17):** install that exact cron line. Nothing else — no code change, no new writer. The lane already
never merges, releases or edits crontab/systemd, and refuses broker / Active Trader / MBI / guard / policy /
train-self / credential scopes (§28.14 item 4).

**Gate:** a dry run of `scripts/self_heal_fixer.py --cycle --dry-run` quoted first; then the cron install under an
operator `cron` grant; then a forced run (§8.1) with its receipt.

## P3 — Install the merge-ready notifier

**Current state:** lane `pr-merge-telegram-notify`, `state: NEVER_SCHEDULED`. The unit files exist in the repo
(`config/systemd/user/tradeai-pr-merge-notify.service` + `.timer`, every 5 min, `notify_pr_merge_ready.py --apply --json`)
but are **not installed** — only `tradeai-pr-merge-digest` and `tradeai-pr-merge-reconcile` are.

**The act (§17):** install the two unit files (`install -m 0644` into `~/.config/systemd/user`,
`systemctl --user daemon-reload`, `enable --now tradeai-pr-merge-notify.timer`). This turns the batched daily
digest into a per-PR "green → one button" interrupt.

**Gate:** `check_expected_services.py` after install; the lane flips `NEVER_SCHEDULED → ACTIVE` in the registry in
the same reviewed PR.

## P4 — Wire the failure pager

**Current state:** `scripts/delivery_failure_alerts.py` exists (a P1 sender: Telegram + email + SMS via the
communications gateway) but is registered nowhere and has no caller. It is a **sender**, not a watcher: it pages
when something detects a failure and invokes it with `--kind <failure-kind> --message <...>`.

**The act (§17, two parts):**
1. Register `delivery-failure-alerts` as a host (non-n8n) lane so it appears on Jobs & health — §24.1: the P1 path
   never depends on n8n, so it is `kind: cron`/`systemd`, never a dispatcher row.
2. Wire its trigger: the self-heal-fixer escalation path (§28.14 item 6) and a host CI-watch that pages on
   red-main-after-merge / failed-release. This is the detector half; arming P2 is the linchpin that makes the pager
   reachable.

**Gate:** `delivery_failure_alerts.py --dry-run --kind manual_test` quoted (sends nothing); the registry row passes
the correlated-reasons gate; the sender goes through the host comms chokepoint, never `bypass_router`.

## P5 — Optional: a bounded "Request fix" on the strip

**What it is:** a button on the strip (or on the self-heal light) that queues one self-heal fixer cycle on demand,
so "amber, designed-not-running" is not a dead end. It is **not read-only** — it is a write/action, so it gets its
own gates.

**Bounds (these are non-negotiable):**
- The button only queues a self-heal cycle; the fixer's own scopes still bind — it opens an ordinary fix PR through
  CI and **never merges, releases or deploys**, and it refuses broker / Active Trader / MBI / guard / policy /
  train-self / credential scopes (§28.14 items 3–4).
- It needs the self-heal fixer armed (P2) to be meaningful; before that the button is disabled with that reason
  shown (never a silent gray-out).
- It is an **operator-session, CSRF-protected POST** to a host endpoint (the same auth bar as the rest of Command
  Center), never a GET and never reachable from n8n or a scheduled job.

**The act (§17):** a new host write endpoint + the button is an operator-surface change; it ships as its own
reviewed PR after P2 is live, with the endpoint behind the Command Center auth boundary.

## Honesty

- Hermetic PASS ≠ OBSERVED. The strip turning green requires an organic `succeeded` receipt on the real schedule,
  not a forced run.
- P4's pager is a sender; until a detector invokes it, "wired" does not mean "paging". Arming P2 is what makes the
  detect→fix→escalate→page loop close.

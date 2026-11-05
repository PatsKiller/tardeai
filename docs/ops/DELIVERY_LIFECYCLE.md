# Delivery Lifecycle

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 6147-6176 -->
## Moved from AGENTS.md (25.0.1 lines 6147-6176)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **No silent removal from an operator surface.** No PR removes or hides a page, nav entry, route, tab, panel or
  widget of the Command Center unless its description links an operator-approved mockup that shows the removal. A
  side effect of an approved feature is not approved (TradeInView hid Calendar P/L and Replay). The coordinator
  holds such a PR out of every batch. *Cause (§20): 20853e201 (2026-10-22), 8c14784ae (2026-09-15) and fdb99d7a8
  (2026-09-29) removed operator surfaces without approval; operator 2026-10-24, "changed without any change control".*
- **Shared infrastructure ships alone, proven on the real layout.** A change to `scripts/safe_flock.sh`, any cron or
  n8n run wrapper, the n8n run executor, deploy/release scripts or crontab templates goes in its own PR titled
  `[shared-infra]`, never inside a feature or takeover PR and never in a mixed batch, with a test that runs it through
  the real release layout (`portfolio-server/CURRENT` symlink, `CURRENT/logs` symlink to a 775 private-group
  directory). After each release the wrapper is run once under the live `CURRENT` in no-op mode. *Cause (§20):
  d5f51dbef rode in PR #1979 / batch 8 and stopped ~30 cron jobs (stop supervisor, incident notifier, repricer, market
  data …) for ~2 days, 2026-10-23 12:06 ET → batch 21.*
- **One source per fact, owned by the CIO record.** Stance and conviction, portfolio total, cash and day P/L, position
  counts, stops (broker resting before planned), regime and VIX, sector posture, pending-approval counts and account
  ids are read through their one canonical resolver; no page or endpoint recomputes its own version. A lower-level
  signal that disagrees is shown as a conflict under the CIO value, never as a competing value. *Cause (§20): site
  audit 2026-10-24 (`handoffs/site-audit-20261024/FINDINGS.md`): SPCX ADD on Watch vs TRIM on CIO Desk; three
  portfolio totals; position counts 32/12/25/9/14/20; operator, "coming from the CIO … it should be the same".*
- **Health means the job ran.** Job health is the last successful run (exit code plus its receipt or output), never a
  log file's mtime or the existence of a crontab line; a failure shows its real cause (stderr tail), not `exit_1`. A
  monitor never depends on the thing it monitors (the alert path is independent of `incident_notifier`).
  *Cause (§20): no surface showed the 2026-10-23 outage; the error line itself kept every log "fresh".*
- **A read never acts.** A GET never triggers a broker read, a job, a recalibration or a write; pages poll only the
  data they show; one poll stays under 500 KB. Agent probes of the live server outside the §28.8 window go one request
  at a time with a memory check first (stop above 1.3 GB). *Cause (§20): 2026-10-24 — an inventory burst OOM-killed
  the server at 15:50; GET `/holdings/live-stops` refreshed a live Schwab stop read; Active Trader polls 6 MB every 30 s.*
- **Every writer is a monitored n8n lane.** A writer of a store an operator surface reads runs as an n8n lane in the
  missed-run watchdog (operator directive 2026-10-15, reconfirmed 2026-10-24); a page whose writer is paused or
  retired says so in its source clock. *Cause (§20): risk_management.json written once a day while the Risk page
  presented it as live; retired writers behind blank panels (advisory opinions, regime, dividends, attribution).*

<!-- moved from AGENTS.md 25.0.1 lines 6243-6287 -->
## Moved from AGENTS.md (25.0.1 lines 6243-6287)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **1 Claim.** `scripts/agent_claim.py status`, then `next`/`take` or `claim` with the task id `DSN-<date>-<slug>-P<n>-T<m>`;
  check open PRs and branches on the same files first; keep the worklog (§28.3, §28.3a, §28.3b). *Cause (§20): §28.3 —
  two vendors built the same fix in parallel, 2026-10-22.*
- **2 Design.** Anything beyond a fix gets `docs/designs/<id>.md` and operator approval (§17). A PR that removes or hides a
  page, nav entry, route, tab, panel or widget links an operator-approved mockup (§28.9). *Cause (§20): §28.9 —
  TradeInView hid Calendar P/L and Replay without approval.*
- **3 Build.** In a worktree off fresh `origin/main` (`git worktree add -b <branch> ~/wt-<slug> origin/main`), never in
  the primary tree; `TMPDIR=$HOME/.cache/agent-tmp/<task>` and pytest `--basetemp` on disk, never `/tmp` (§28.2); no
  agent traffic to the live server 04:00–16:15 ET on a market day (§28.8); `MBI_BEHAVIOR = 0`. *Cause (§20): 2026-10-25
  04:07–04:18 ET agent test runs filled the `/tmp` tmpfs and cron lock writes failed (ENOSPC).*
- **4 Test.** Unit tests registered in a `config/ci_gates/*.json` record (§8A); senders, brokers and live stores stubbed
  (§24.6); UI changes carry tap tests at the 412 and 390 px viewports, a list opens its detail as a full-screen sheet;
  shared infrastructure carries a real-layout proof run on a temp `PROJECT_ROOT`, never the live journal (§28.9); a
  dry run is quoted for anything that writes, sends or schedules (§0 rule 7). *Cause (§20): the operator works from a
  phone; 2026-10-25 a real-layout proof run on the live root wrote to the production journal and raised a CRIT.*
- **5 PR.** Title carries the task id; shared infrastructure is titled `[shared-infra]`, ships alone and its body has a
  `Real-layout proof:` line (§28.9); `Depends-on: #N` for a stack; body via `--body-file`; push only with
  `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` inside the push budget (§0 rule 4). The PR is the agent's last remote act (§25.10).
  *Cause (§20): §28.9 — d5f51dbef rode a mixed batch and stopped ~30 cron jobs for two days.*
- **6 CI green.** `cio-hardening`, `agent-governance`, `release-readiness` and `ci-gate` are `success` on the head SHA;
  a unit whose tests all skip fails; local green is not CI green. *Cause (§20): Mergify's required checks (§25.10); 2026-09-22 a
  locally green PR failed CI.*
- **7 Queue.** Once CI is green on the exact head the agent stops; the PR appears in the operator's next Telegram
  digest. The operator's "Approve all" approves every listed PR at the head SHA shown; a held-class PR is never in it
  and waits for the operator's own merge (§25.10). Mergify then merges inside its ET windows. Agents never merge,
  never add `operator-merge` and never release. Full path: `docs/ops/AGENT_MERGIFY_HANDOFF.md`. *Cause (§20):
  operator 2026-10-26 and 2026-10-27 — not a GitHub expert; one tap is the go-signal, then automatic queue and merge.*
- **8 Release.** Mergify squash-merges to `main` in an ET window; host `deploy_on_main` promotes CURRENT under STOP +
  GlobalReleaseLock + the standing **deploy** (promote-only) delegation, with no per-SHA grant (§25.10). Emergency
  remains the operator's host CLI + `release-write` naming the SHA. Merged is not deployed and deployed is not proven. *Cause (§20): 2026-09-22 the
  desk ran three days on a stale release; 24.0.0 split merge (Mergify) from promote (poller).*
- **9 Verify after every release.** `scripts/post_release_tester.py` sees each release in the deploy receipt history and
  runs the post-promote API checks at once (health ok, `/v3/cio` 200, served `BUILD_SHA` equals the released SHA, the
  release wrapper preflight when admitted); a light browser sweep (`scripts/site_sweep.sh`, top routes at 412 and 390,
  only the "broken" detectors: console errors, uncaught exceptions, HTTP 4xx/5xx other than expected refusals, route
  crash, load over 15 s) outside the §28.8 window and under the 1.3 GB memory gate, deferred otherwise; and a nightly
  full sweep at 21:30 ET when memory allows. A release counts as verified only by its PASSED receipt (§0 rule 8).
  *Cause (§20): operator 2026-10-25, "it's deployed, tested"; no check ran after a release unless an agent remembered.*
- **10 Failures page the operator.** `scripts/delivery_failure_alerts.py` sends an immediate P1, never the digest, by
  Telegram (`send_telegram`), email and SMS (the communications gateway; SMS once its keys are configured) when: main
  CI is red after a merge; a deploy fails, rolls back or is stuck (§25.10); the STOP latch is set; a manual promote
  or rollback fails; the post-release tester fails; or the nightly sweep finds broken pages.
  One line plus a link to System → Releases & schedules, deduped per incident, rate limited. The owning agent fixes
  forward with a new PR through this same path; nobody reverts by hand or pushes `main`. *Cause (§20): operator
  2026-10-25, "Any failures I need to be emailed, notified, and texted."*

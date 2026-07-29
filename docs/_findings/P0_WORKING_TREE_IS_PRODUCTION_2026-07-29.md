# P0 — The working tree is production for ~130 execution paths

**Filed:** 2026-07-29 · **Found during:** SL-S2 · **Status:** DIAGNOSED, NOT TOUCHED
**Classification:** architectural — two deployment models running simultaneously

---

## 1. The structural fact

```
$ crontab -l | grep -c "cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
130
```

**~130 crontab lines execute directly from the working tree.** The dashboard, by contrast, is
SHA-pinned by a systemd drop-in to a frozen release checkout:

```
# ~/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf
WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/306f8179…
ExecStart=… /home/johnclaw/trade-ai-releases/portfolio-server/306f8179…/scripts/portfolio_server.py
```

So the system runs **two deployment models at once**:

| | dashboard | cron (~130 paths) |
|---|---|---|
| source | SHA-pinned release | working tree |
| to change behaviour | commit → release → restart | **save the file** |
| "uncommitted" means | not released | **already live** |
| review before live | yes | none |

Every instruction in this workstream assumed the first model. For cron, **editing a file is
deploying it.** "Deploy dark, flag OFF" is coherent for the dashboard and meaningless for anything
cron touches.

Concrete instance already observed: the alert workstream's `config/operator_alert_policy.yaml` and
sender edits were live from the moment they were written on 2026-07-28, reachable via
`send_telegram_proposal_alert.py` → `telegram_alert_router` in cron. Commit `3f2fe892` recorded that
state; it did not cause it.

**Sector Leaders is unaffected** — it is an endpoint plus a component, with no cron path. Dark
deploy remains valid for it.

---

## 2. The mid-session writes

Three tracked source files changed during this session, absent from the opening `git status`:

```
2026-07-29 12:41:28  scripts/hermes_data_access.py           +36  −?
2026-07-29 12:42:45  scripts/hermes_external_researcher.py  +121
2026-07-29 12:49:48  scripts/research_scheduler.py           +79
                                          216 insertions total
```

### What it is NOT

**Not a Hermes firewall breach.** Verified directly:

```
grantee                | table_name                     | privs
hermes_staging_writer  | hermes_alerts                  | INSERT,SELECT,UPDATE
hermes_staging_writer  | hermes_directive_hits_staging  | INSERT,SELECT
hermes_staging_writer  | hermes_embedding_queue         | INSERT,SELECT,UPDATE
hermes_staging_writer  | hermes_memory_events           | INSERT,SELECT,UPDATE
hermes_staging_writer  | hermes_promotion_audit         | SELECT
hermes_staging_writer  | hermes_research_intelligence   | INSERT,SELECT,UPDATE
hermes_staging_writer  | hermes_validation_findings     | INSERT,SELECT,UPDATE
(7 rows — nothing outside hermes_*)
```

The live Hermes processes are `hermes chat -q …` advisory research queries returning JSON under
`agent_contract: cio_agent_v2_structured_evidence`. No filesystem write path. The firewall holds.

**Not the escalation handler.** `scripts/claude_escalation_handler.py` (cron, flock-guarded, running
during the window) executes `retry_cmd` entries, but every one passes `_check_allowlist()` —
blocked-pattern deny list, environment guards, and an explicit `allowed_script_patterns` allowlist.
Its only writes are to its own queue JSON. It retries pipeline commands; it is not a coder.

**Not a historical pattern.** Across the last 400 commits the authors are `PatsKiller` (202),
`John` (197), and `trade-ai-doc-assembler` (1). Every prior commit to all three files is authored by
`John`. There is no evidence of machine-generated changes being swept into human commits.

### What it most likely IS

A **concurrent operator-driven Codex session**:

```
pid 1253869  node /usr/bin/codex   started Wed Jul 27 20:28:40   cwd=<project root>
~/.codex/logs_2.sqlite  last written 2026-07-29 13:02:27   (active now)
```

Codex is an established tool in this repo — the alert workstream committed today is documented in
its own directory as `CODEX_IMPLEMENT_TELEGRAM_NOTIFICATION_NORMALIZATION_2026_07_28.md` and
`CODEX_RUN_LAST_MESSAGE.md`. The diffs are also stylistically inconsistent with autonomous
remediation: they carry rationale comments citing specific observed defects, e.g.

> `"""Truncate on a word boundary. The old [:240] cut mid-word — 'still highly dependen',`
> `'only middling internal rankin' — which made distinct alerts look interchangeable."""`

That is directed engineering, not a bot patching itself.

**Confidence:** high that it is not Hermes and not autonomous remediation (both ruled out by direct
evidence). Moderate that Codex specifically wrote these three files — a running Codex session in the
project root, active in the window, is the only identified writer, but no Codex transcript for
2026-07-29 was found to tie it to these exact files.

---

## 3. Why it still matters even though it is not a breach

The alarming reading is wrong. The structural one is not:

1. **`git status` clean is not a stable property.** It can go false while work is in progress. The
   SL-S2.0 gate was written as a one-time check; on this system that is unsound. Any gate depending
   on tree state must be re-checked immediately before the operation it guards, not once at the top.
2. **Concurrent writers plus cron equals unreviewed production change.** It does not require an
   autonomous agent for machine-written code to reach production — a second directed session editing
   a cron-executed file achieves the same thing, with no commit and no diff anyone reads.
3. **Commit laundering is a live hazard.** Committing from a tree that mutates underneath you sweeps
   another session's in-flight work into your commit under your message. This nearly happened twice
   today: the alert workstream was avoided only by splitting `api_v2.py` by hunk, and the
   sector-leaders commit is being held for exactly this reason.

---

## 4. Recommended — not implemented

1. **Decide the cron source of truth.** Either point cron at a pinned release like the dashboard, or
   state explicitly that the working tree is production for cron and treat every save as a deploy.
   The current situation is neither, and nobody reasons about it correctly.
2. **Re-check tree state at the point of use.** Any commit/deploy gate should verify immediately
   before acting, and abort on unexpected files.
3. **Announce concurrent sessions.** Two agents editing one working tree that is also production
   needs a coordination convention — the RI desk skill already records a shared-file race on
   `research_intelligence.py`, so this has bitten before.
4. **Leave the three files alone** until their author lands them. They are someone's in-flight work.

---

## 5. Scope note

Nothing here was touched. The three files remain exactly as found, uncommitted. This document
records the diagnosis only.

Status:      ACTIVE
as_of:       2026-09-01T21:08:48-04:00
run_id:      mp-20260901-210554
prompt_version: 1.0.0
Canonical repo path: docs/implementation/maturity-program/mp-20260901-210554/STAGE_00_PREFLIGHT.md
Authority:   pre-flight measurement only. No implementation stage started.
Verdict:     **STOPPED — canonical source checkout does not equal origin/main**

# Stage 0 · Pre-flight

Program section 1 defines two conditions that stop work before any edit. **One is tripped.**

## 1 · Identity resolution  [VERIFIED]

```
repository root (canonical checkout)  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
canonical checkout branch / SHA       HEAD (detached) / 0a591048b827d57cebd5e61f39af77bde8c58274
origin/main SHA                       6d6609915171fe6a153daf71d413df88b6483864
served CURRENT target                 portfolio-server/6d6609915-main-exact-phase2-20260901-182421
served CURRENT embedded BUILD_SHA     6d6609915171fe6a153daf71d413df88b6483864   (file content)

canonical == origin/main   NO   <-- STOP
served     == origin/main   YES
```

**The served release is exact-head.** The drift is in the canonical *source checkout*, which lags
`origin/main` by **20 commits** (`8898c7fbb` … `6d6609915`), spanning #828–#840.

Program section 1: *"If the canonical source checkout does not equal origin/main, stop any code
work and report the drift. Do not fast-forward it without separate operator approval."*
No fast-forward was performed.

### Why this matters beyond bookkeeping

Many scheduled jobs run `cd $PROJ` (the canonical checkout), not the served release. A 20-commit
lag means those crons execute code 20 commits behind what CI approved and what `CURRENT` serves.
This is the same class as the two-data-plane split recorded in
`docs/ops/litmus/LITMUS_LANES_2026-09-01.md` F1. **Not remediated here** — reported.

## 2 · Policy self-test  [VERIFIED] — PASSES

```
.githooks/pre-push with TRADEAI_REMOTE_PUSH_AUTHORIZED=0  ->  exit 1  (blocks, correct)
push_authorized_by_guard()                                ->  ok=False, reason=""
tests/test_ai_work_policy_hooks.py                        ->  10 passed
```

**This is a change since earlier today.** At ~18:00 ET an operator scope grant
(`reason="CC narrative held bind PR"`) was open; the hook honours a grant by setting
`authorized=1` **and** `override=1`, so it allowed an unauthorized push and
`ai_local_acceptance.sh` exited at its self-test for every agent. **The grant has since closed**
and the gate is sound. Recorded because the earlier failure was reported as blocking and is now
resolved by expiry, not by any change of mine.

## 3 · Dirty files and owners  [VERIFIED]

| tree | dirty | file | assessment |
|---|---|---|---|
| canonical checkout | 1 | `archive/weekly/` (untracked) | 3 screener CSVs, pre-existing, not mine |
| exact-main deploy worktree | 1 | `apps/command-center-v3/build-meta.json` | deploy-generated artifact; discarded, not committed |

## 4 · Required checks  [VERIFIED]

```
branch protection: strict=True, required contexts = ["cio-hardening"]
on origin/main 6d6609915 — all 7 green:
  aif-financial-senses-integration · broader-regression · cio-hardening
  financial-senses · provider-cost · release-readiness · research-governance
```

**Only `cio-hardening` is required.** The other six run and block nothing — AGENTS.md §8,
*"a suite in a non-required workflow will run, go red, and block nothing."*

## 5 · Required reading  [VERIFIED present on origin/main]

All nine exist: AGENTS.md (1492) · AI_WORK_POLICY.md (613) · ENGINEERING_HARD_RULES.md (46) ·
CIO_ASIS_VS_SPEC (207) · CIO_FUTURE_STATE_FULL_MATURITY (268) · ARCHITECTURE_v3_3 (5487) ·
CIO_OVERNIGHT_CLOSEOUT_2026-09-01 (1589) · CIO_OVERNIGHT_AUTONOMY_SCOREBOARD_2026-09-02 (135) ·
CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1 (452).

## 6 · Stage 1 premises, checked against the live file

| program premise | measured | verdict |
|---|---|---|
| AGENTS.md is unversioned | `Policy-Version:` count **0** | **CONFIRMED** — 1.0.0 is the correct first baseline |
| duplicate §13.5 | lines **995** and **1063** | **CONFIRMED** |
| duplicate §13.6 | lines **1008** and **1107** | **CONFIRMED** |
| repeated "Where things go" | lines **1168** and **1207** | **CONFIRMED** |
| adapters point at root AGENTS.md | CLAUDE.md 3 refs · .cursor 3 · copilot 3 | **ALREADY SATISFIED** |
| `AGENTS.nd` referenced anywhere | **0 files** | **ALREADY SATISFIED** — nothing to reject |

`AGENTS.md` content sha256 on `origin/main`: `59f2c8b0b84ef3fe…` (first 16).

### Findings not in the program's premise list

1. **`agents/aegis/AGENT.md` exists.** Scoped agent card inside `agents/aegis/`, not a competing
   root constitution. Program §1.1 rejects `AGENT.md` *as canonical*; this one does not claim to
   be. **Finding, not a violation** — no action taken.
2. **`config/drive_parity_manifest.json` already exists.** A different Drive-manifest concept.
   Stage 1.6 specifies a new distinct file; §13.5 requires stating that an existing mechanism was
   searched and ruled out before building alongside it. Ruled out: different schema and scope.
   Recorded so the Stage 1 PR can state it rather than rediscover it.

## 7 · File-set declaration and serialization

Stage 1 owns: `AGENTS.md` · `CLAUDE.md` · `.cursor/rules/00-tradeai-work-policy.mdc` ·
`.github/copilot-instructions.md` · `docs/ops/AGENTS_DRIVE_MIRROR_MANIFEST.json` (new) ·
`docs/implementation/maturity-program/mp-20260901-210554/*`.

**Overlap search over 34 open PRs: one hit, cleared.**
`#150 Active Trader — Stage 0 baseline and litmus review` lists `AGENTS.md`. It is a **DRAFT**,
last updated **2026-07-27** (5+ weeks stale), and `gh pr diff --name-only` returns **0 files**
against current main. Not an active concurrent editor. **Declared and cleared** — but it is a
standing overlap claim on the Stage 1 file set and the operator may prefer it closed first.

Drive target `Trade_AI_Docs_v2/governance/agent-policy/`: **not yet searched.** Drive tools are
available and confirmed loadable. Stage 1.6 requires searching before creating; that search is
part of Stage 1, not pre-flight, and Stage 1 has not started.

## 8 · Verdict

```
STOPPED — canonical source checkout != origin/main
```

No branch was created for implementation, no file outside this pre-flight directory was edited,
no Drive object was created or read, no scheduler touched, no deploy performed.

### Required to proceed

Operator approval to fast-forward the canonical source checkout
`0a591048b` → `6d6609915`, or an instruction to proceed against a different canonical root.

Program section 0 lists cron/systemd changes as separate-approval items and section 1 forbids the
fast-forward without approval; $PROJ is the working directory for scheduled jobs, so moving it is
a runtime change, not a bookkeeping one.

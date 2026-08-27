# Health Agent Maturity Plan — from "it ran" to "it worked"

**Date:** 2026-08-27
**Status:** PLAN — nothing below is shipped
**Trigger:** a 24-hour silent synchronization failure that the Health Agent detected correctly, attempted to fix 69 times, and reported as successful every time.

---

## The incident this plan is built on

The portfolio repricer wrote `holdings.json` into the checkout it lived in. Every deployed release symlinks that path at the persistent root, so the **served** copy — the one `/api/v2/overview` reads — went 25 hours stale while 17 of 23 positions were priced a day old (NOC off $6.06/share).

The Health Agent's own record:

| | |
|---|---|
| First detection | `2026-08-26T15:08Z` — **~38 min after onset.** Detection was not the problem. |
| Remediation attempts | **69**, over 24 hours |
| Reported outcome | `ok: True` (15), `ok: False` (27), `ok: None` (27) |
| Root causes identified | **0** |
| Staleness trend across attempts | `1474m → 1484m → 1496m` — monotonically worsening |
| How it was actually found | A human verifying an unrelated deploy |

The finding text was accurate and specific the entire time: `Portfolio last_repriced stale 1474m (max 25m)`. Nobody was told in a way that produced action, and the agent never once asked *why the fix wasn't working.*

## Root cause of the failure to self-heal

`scripts/system_health_agent.py:876` —

```python
success = proc.returncode == 0
```

**Remediation success is defined as the subprocess exit code, not as the finding clearing.** The repricer exited `0` every time because it genuinely did reprice — into the copy nobody reads. The agent had no way to notice that a "successful" fix changed nothing.

This is the whole bug. Every other weakness below is downstream of it.

### The same shape, three times in one day

This is not an isolated defect. On 2026-08-27 alone:

| Component | Reported | Actually did |
|---|---|---|
| `portfolio_repricer` | `holdings.json updated.` ×69 | wrote a copy nothing reads |
| health agent remediation | `ok: True` | ran a no-op fix |
| `position_truth` gate (audit C2) | unit tests green | never called from live code |
| PR #543's own fix | CI green, merged | import raised, silently fell back |

**A component reporting success is not evidence that it did anything.** That principle, not any single check, is what this plan encodes.

---

## What already exists (build on this, do not rebuild)

The repo is further along than the incident suggests. The gap is wiring, not absence.

| Capability | Where | State |
|---|---|---|
| Finding model, severity, dedup | `system_health_agent.py` (25 checks) | **Working** |
| Auto-remediation allowlist + denylist | `health_agent_policy.json` (`remediation_map`, 70 entries; `never_auto_remediate`, 15) | **Working** |
| Single-flight via `safe_flock.sh` | `_attempt_retry` | **Working** — prevents pile-ups |
| Retry caps, timeouts, process-group kill | `_attempt_retry` | **Working** |
| Ineffectiveness circuit breaker | fired `15:40:52Z`, "ineffective 3x within 60m" | **Working but too late** |
| Root-cause memory store | `logs/health_root_cause_memory.jsonl` | **Exists, 0 causes ever written** |
| Canonical store registry — 29 stores | `scripts/lib/canonical_store_registry.py` | **Live**, 11 consumers |
| Root classifier — `GOOD_PERSISTENT_ROOT` / `SOURCE_TREE_COUPLED` / `DUPLICATE_ROOT` / `BROKEN_SYMLINK` | `scripts/lib/production_root_map.py` | **Live, and not wired to the Health Agent** |

That last row is the missed opportunity. `map_all()` returns, today, on the live box:

```
stores mapped:          29
source_tree_coupled_n:  3      <-- exactly the failure class, unmonitored
```

**The signal that would have caught this in minutes already exists and nothing consumes it.**

---

## Phase 0 — Stop the lying (highest value, smallest change)

Effort: S · Risk: low · Closes the incident class outright

**0.1 — Verify the effect, not the exit code.**
After a remediation runs, **re-run the originating check** and compare the finding before/after. Success means *the finding cleared*. `returncode == 0` becomes one input, never the verdict.

```
outcome := CLEARED           finding gone            -> log success, record what worked
         | INEFFECTIVE       ran clean, finding persists  -> diagnose (0.2), escalate on 2nd
         | FAILED            non-zero exit           -> existing path
         | WORSENED          metric moved wrong way  -> escalate immediately, stop retrying
```

`WORSENED` alone would have caught this incident on **attempt two**: staleness rising `1474 → 1484` while the fix reports success is a contradiction no healthy system produces.

**0.2 — Record a root cause on every INEFFECTIVE.**
`health_root_cause_memory.jsonl` exists and has never held a cause. Populate it with a typed diagnosis and the evidence used. Start with three causes covering most of the surface:

- `WROTE_UNREAD_COPY` — writer target ≠ reader target (this incident)
- `EFFECT_NOT_OBSERVED` — ran clean, metric unchanged, targets agree
- `UPSTREAM_UNAVAILABLE` — dependency down; remediation cannot succeed

**0.3 — Tighten the breaker and make escalation actionable.**
Trip at **2** ineffective attempts, not 3-within-60m. The alert must carry the diagnosis, the metric trend, and the exact command that failed to help — not just the finding text. An operator should be able to act from the alert alone.

**Acceptance:** replay this incident against the new logic and assert it escalates within ≤2 attempts with `WROTE_UNREAD_COPY` and never logs `ok: True`.

## Phase 1 — Consistency invariants (catch the class, not the instance)

Effort: M · Risk: low (read-only) · This is the "continuous verification" ask

A new read-only check family, `store_consistency`, over the 29 registry stores. For each: enumerate every copy (checkout, persistent root, `CURRENT` release), then assert:

1. **Agreement** — copies that should be one file are one file (content hash, and inode where a symlink is expected).
2. **Correct root class** — no store lands in `SOURCE_TREE_COUPLED` or `DUPLICATE_ROOT`; `source_tree_coupled_n` must be **0**, and it is **3** today.
3. **Reader/writer coherence** — the path a writer resolves is the path its readers resolve. Divergence is `critical` for anything on a money surface.
4. **No broken symlinks** — `BROKEN_SYMLINK` is always critical.

This is mostly assembly: `map_all()` already computes 1, 2 and 4. Wire it in and add per-store hashing.

**Deliberately not auto-remediated.** Divergence means two candidate truths; a machine picking one can destroy the other. It escalates with both paths, both timestamps, and both hashes, and a human decides. The 69-attempt loop is what auto-remediating a misdiagnosed fault looks like.

## Phase 2 — Effect assertions for scheduled work

Effort: M · Risk: low

Log-freshness checks (`_check_log_freshness`) prove a job *ran*. They cannot prove it *did* anything — the repricer's log was healthy throughout.

Add an optional `effect_assertion` per `remediation_map` entry and per monitored cron: a cheap predicate that must hold after a successful run.

```
portfolio_repricer:
  effect_assertion: served holdings.json last_repriced within max_age_minutes
```

Ran-clean-but-assertion-false is exactly `INEFFECTIVE` from 0.1, reusing that path. Roll out to the money-path jobs first (repricer, holdings reconcile, basis sync, stop sync); leave the long tail on log-freshness only.

## Phase 3 — Proactive posture

Effort: M · Risk: medium (tuning) · Do **after** 0–2 have run clean for two weeks

- **Trend-based prediction.** Alert on a metric *heading* out of bounds — freshness age climbing across consecutive cycles — before the threshold trips.
- **Post-deploy verification.** A deploy is the highest-risk moment for divergence. Run `store_consistency` automatically after every `promote` and fail the promote on a critical finding. This incident was found during a deploy by a human doing manually what this would automate.
- **Silence detection.** A check that stops reporting is currently indistinguishable from a healthy one. Assert each check's own liveness.

## Phase 4 — Keep it from regressing

Effort: S · Risk: low

- Tests asserting remediation-verification semantics: an INEFFECTIVE remediation must never log success. Test at the behaviour level — PR #543 shipped broken past a test that only read source text.
- CI guard: every `remediation_map` entry must declare a verification check or an explicit `no_verification_reason`.
- A recorded replay of this incident as a permanent regression fixture.

---

## Sequencing and honest expectations

```
Phase 0  ──> Phase 1  ──> Phase 2  ──> [soak 2 weeks] ──> Phase 3
   |            |            |                              |
 stops the   catches the  proves jobs                   predicts,
  lying        class      did something                 verifies deploys
```

Phase 0 alone converts this incident from *24 hours silent* to *~40 minutes to an actionable page*. Everything after is depth. **If only one phase ships, ship Phase 0.**

### What this plan will not do

- **It will not remediate more aggressively.** The incident was caused by an over-confident fix loop; the fix is fewer, better-verified actions.
- **It will not add alerts nobody reads.** Phase 0.3 makes existing alerts actionable before Phase 3 adds predictive ones. Alert volume should fall.
- **It will not auto-resolve state divergence.** Escalate with evidence; a human picks the survivor.
- **It cannot fix undetectable faults.** Detection worked here. Verification and diagnosis are the gap, and that is what this targets.

### Open questions for the operator

1. **Alert channel and threshold for `critical` store divergence** — Telegram immediately, or batch into the digest? Divergence on a money surface argues for immediate.
2. **Should a critical `store_consistency` finding block a deploy promote** (Phase 3), or only warn? Blocking is safer and can wedge a deploy at a bad moment.
3. **The 3 currently `SOURCE_TREE_COUPLED` stores** — fix as part of Phase 1, or triage separately first? They are a live instance of the same class.

---

**See also:** `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` (finding C5 — critical QA violations went unalerted, same observability gap) · `docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md` (65 CI jobs reported failure having never run — the inverse error, and the same lesson about trusting a status field over evidence)

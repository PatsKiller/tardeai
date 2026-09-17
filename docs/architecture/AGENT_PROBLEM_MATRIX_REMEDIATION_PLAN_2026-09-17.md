# Agent problem matrix — remediation plan and completion record

```
Schema:     AgentProblemMatrixRemediation/v1
Date:       2026-09-17
Authority:  READ_ONLY_ADVISORY — no broker, order, stop, 2FA, risk policy or
            scheduler was modified by any change below
Audit:      docs/architecture/AGENT_PROBLEM_MATRIX_DUE_DILIGENCE_2026-09-17.md
Evidence:   evidence/agent_problem_matrix_20260917/
Operator:   approved flag activation + Tavily client + hook install on 2026-09-17
```

## What this is

The due-diligence audit graded ten agent failure modes as 4 LIVE, 4 DARK, 2 GAP.
The DARK rows were controls that existed, were tested, and that **no production path
called**. This document is the plan to close them and the record of doing it.

Per `AGENTS.md` §13.5 every item was a **wiring** task, not a build task. No new
dependency was added. The one new module — a Tavily client — exists because the
registry declared a provider with no client, which §13.5 would call the opposite
failure: a declaration with nothing behind it.

## Status

| # | row | was | now | remaining |
|---|---|---|---|---|
| 1 | 04 injection boundary | DARK | **wired + enforcing** | model-level defence still open (AIF-24 PARTIAL) |
| 2 | 09 run traces | DARK | **wired + writing** | — |
| 3 | 02 tool authority | DARK (mis-graded) | **LIVE; receipts now real** | MCP gateway activation is operator-only |
| 4 | 03 Tavily slot | GAP | **wired, fail-soft** | key provisioning + status flip: operator |
| 5 | 06 memory shadow | DARK | **staged in `.env.example`** | operator uncomments two lines |
| 6 | 08 reranker | LIVE, weak | unchanged — **proposal only** | benchmark, then decide |
| 7 | push gate | unenforced here | **installed, verified blocking** | — |

Commits: `e4e79dd` (04) · `e583bc0` (09) · `97f99f1` (03) · `ee11a62` (02) · `f6f8ec4` (06).

---

## Row 04 — injection boundary · `e4e79dd`

**The live vector.** News headlines and social post bodies were interpolated straight
into agent prompt context:

```python
lines.append(f"  - [{sent}{score}] {(n['title'] or '')[:80]}")     # publisher text
lines.append(f"  - [{plat}/{sent}] {(s['text'] or '')[:100]}")     # anonymous author
```

Both are adversary-controllable, and both sat inside homegrown `=== ... ===` fences that
a post could forge to break out of.

**Wired.** `agent_untrusted_data` gained `defang()` and `untrusted_text_block()` — the
composite seam exists so a caller cannot delimit without defanging, because a correctly
labelled envelope whose contents can close it is not a boundary. The runner now wraps
news, social and AV-news ingest and flags rows matching the pre-existing
`is_adversarial_instruction` detector. `MEMORY_ADVERSARIAL_SCAN` defaults to 1, so
admission rejects instead of recording `shadow_reject` and admitting anyway.

**Proven.** Four attack strings defanged with exactly one surviving fence; a benign
earnings headline untouched; the partitioner rejecting untrusted data in an instruction
section.

**Still open, and stated plainly:** untrusted text still reaches model context. AIF-24
stays **PARTIAL, not PASS**. This closed the structural half only.

## Row 09 — run traces · `e583bc0`

`control_plane_api` served `AgentRunTrace` rows and `cio_gate_measurement_bridge`
consumed them; nothing wrote them. The runner now opens a trace per job and closes it on
the success, symbol-gate and empty-LLM paths, carrying the rule G0 grounding verdict.
Both helpers are fail-soft — tracing must never be able to fail a job.

**Second-order effect worth noting.** `langgraph_complexity_gate` scores its
`NOT_REQUIRED` verdict from `workflow_metrics` carried on these traces. That verdict was
being computed over an almost-empty corpus. It still looks correct; it now has something
to stand on.

## Row 02 — tool authority · `ee11a62`

**The audit was wrong here and this corrects it.** Row 02 graded the control DARK because
`mcp_read_only_gateway` had no production caller. True, but the wrong measurement:
`agent_runtime.contracts.ToolPolicy` already enforces per-agent authority and is strict —
deny by default, forbidden prefixes, explicit `denied_tools`, LAB/SHADOW only, per-run
budget. Measured: darwin is denied `artifact.write`; `place_order` and `kb.ratify` are
refused as not allowlisted. **The allowlist half was LIVE.**

What was genuinely broken is the receipt trail. `data/cio/agent_tool_traces.jsonl` has
**eight readers**, one of which (`autonomy_health`) alarms when it goes stale for 12h.
Its only writers were the uncalled gateway and a seed script — so eight consumers were
reading seeded data as if it were agent behaviour. `invoke_tool` now emits on all three
paths, including denials, so a refusal is recorded rather than silent.

`MCP_READ_ONLY_GATEWAY` stays 0. See *Corrections* below.

## Row 03 — Tavily slot · `97f99f1`

`providers.tavily` carried an operator approval dated 2026-09-13, a 20/day budget and a
place in `domains.web_search.backup`, with no client anywhere. Measured:
`resolve_backup("web_search")` returns `['searxng', 'tavily']`, so the chain reached slot
2 on every Brave denial and recorded `NO_ADAPTER`.

`scripts/lib/tavily_client.py` is the one shared client, written to the `searxng_client`
idiom so both slots normalize identically. Safe to leave wired unkeyed:

| condition | behaviour |
|---|---|
| no key | `NOT_CONFIGURED` error row, no socket, no raise |
| all-error | transport raises → `_spill` refunds the unit → chain moves on |
| not armed | refuses network unless `BRAVE_ROUTER_LIVE` is set |

`status` stays `configured_unused`. Provisioning a data plan is operator-only (§17).

## Row 06 — memory shadow · `f6f8ec4`

`MEMORY_PROVIDER="null"` and `MEMORY_SHADOW=0` while `config/lane_registry.json` has
`cio-memory-shadow-measure` **ACTIVE on a daily systemd timer** — a measurement lane
running against nothing.

Staged in `.env.example` rather than flipped in code. `agent_feature_flags` is built so a
release can be staged from the environment without a code change, and selecting a memory
provider is a host decision; making an in-memory test double the committed default would
be the wrong mechanism even though it would have looked like progress.

Two uncommented lines turn the shadow on. Promotion beyond shadow stays gated by
`agent_shadow_acceptance`: fail-closed at ≥0.95 measured operator-rejection recall,
treating "not measured" as failure.

---

## Corrections to the audit

Three, all worth stating because the audit is the record.

**1. Row 02 over-called DARK.** Tool authority was already enforced by `ToolPolicy`. The
audit measured importers of one module rather than the capability — the exact mistake
§13.5 warns about ("filename greps have produced three wrong conclusions here"). Corrected
to LIVE; the receipt trail was the real gap.

**2. `MCP_READ_ONLY_GATEWAY` was initially flipped to 1 in error, then reverted.** The
reasoning was that "off" meant tool calls bypassed the fail-closed allowlist. That is
backwards: the flag **opens** the read-only MCP context path rather than guarding an
existing one, so ON grants agents a capability they do not otherwise have, and its
external providers are deliberately `NOT_CONFIGURED`. Conservative there really is 0, and
activation is operator-only. The flag is back at 0 and the rationale is recorded in
`test_defaults_are_conservative`.

**3. "Conservative" was conflated with "zero".** `test_defaults_are_conservative` asserted
every flag defaulted to 0 and called that conservative. For `MEMORY_ADVERSARIAL_SCAN`, 0
was the **permissive** value — the jailbreak scan recorded `shadow_reject` and admitted
the record anyway. The blanket zero-check was guarding the wrong thing. The test now
asserts the invariant that matters: nothing may shape advice, open a capability path, or
add a second system of record.

Six tests pinned the pre-fix state and were updated, none disabled. Two asserted the
absence of a fix (`tavily not in SPILL_ADAPTERS`; `NO_ADAPTER` in the receipt); four
assumed unset env meant off. Where a test's intent was a **gate**, the gate is still
exercised — by setting `0` explicitly rather than by unsetting — and one new test covers
the enabled half that had no coverage while defaults were 0.

---

## What is left, and whose call it is

Nothing below was done, because none of it is an agent's to decide.

| item | why it stops here | the one step |
|---|---|---|
| Tavily key + `status: active` | provisioning a data plan is §17 operator-only | set `TAVILY_API_KEY`, flip status in the same change |
| memory shadow on | host decision; §27 pins influence at 0 | uncomment two lines in `.env.example` |
| `MCP_READ_ONLY_GATEWAY=1` | opens a capability path; providers need credentials | operator decision after providers exist |
| row 08 cross-encoder reranker | new dependency; provisioning a model plan is §17 | benchmark against the existing 40-query harness first |
| confirm live `.env` on ms01 | not in this tree; never read | see *Limits* |

**Row 08 stays a proposal on purpose.** `SOURCE_BOOSTS` is a static source-type prior, not
a reranker — it cannot tell a relevant `news` item from an irrelevant one. A local
cross-encoder would cost no egress and no vendor, but adopting it before measuring would
be the habit this repository is trying to break. `hybrid_rag_retrieval_pilot.py` already
has the 40-query harness to settle it.

---

## Validation

```
629 passed, 3 skipped          consolidated sweep, 2026-09-17
ruff 0.16.2                    clean on every file touched
secrets tree scan              clean (pre-commit, every commit)
pre-push gate                  installed and verified blocking
```

Two `test_agent_runtime_host_proof_wrapper` failures are **pre-existing** — reproduced on
a clean tree via `git stash`, caused by a host artifact absent from this container. Not
introduced here and not fixed here.

Evidence: `evidence/agent_problem_matrix_20260917/consolidated_dry_run.txt` and
`per_row_dry_runs.txt`.

## Limits

- **Every dry run was a dry run.** No control has been observed firing at runtime from the
  served release, which is the bar `AGENTS.md` §1 sets for finished work. These changes
  are proven correct in isolation, not proven live.
- **The live `.env` on ms01 was never read** — it is not in this tree. If a flag is already
  set there, the corresponding verdict changes. A production activation with no committed
  record would itself be a §0 rule 5 finding.
- **The runner change is the highest-risk edit here.** `process_watchlist_agent_jobs.py`
  is the live advisory path. Both new helpers are fail-soft and the ingest change is
  string-level, but it has not run against production data.
- **Row 04 is structurally, not semantically, closed.** A model can still obey plain
  language inside a correctly labelled envelope.

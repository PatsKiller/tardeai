# CIO Prompt & Input Audit — 2026-07-01

Audit of the prompts and input data submitted to the LLMs that produce the **CIO View**
(`watchlist_final_synthesis`) — for maturity and tightness, to improve output quality.
Triggered by observed cases where the CIO's own output flagged input problems (e.g. AZN:
*"the portfolio block says AZN is not owned, while Steph describes it as a concentrated 22%
position… that inconsistency is large enough to block a credible committee-grade verdict"* →
confidence 0.19).

## The CIO pipeline (how a card's "CIO View" is produced)
1. **Committee** (`process_watchlist_agent_jobs.py`, local gemma3:4b): **Maria** (bull/news),
   **Steph** (bear/income), **Risk** each analyze the symbol from `_build_portfolio_context` +
   RAG + hermes blocks → free-form narrative + recommendation + confidence.
2. **CIO synthesis** (`run_synthesis`, prompt at line ~1537): the Chief Investment Officer prompt
   combines the committee narratives + a separate portfolio/position/income packet + strategy
   weights → final `recommendation` + `synthesis_narrative`. Stamped `SYNTHESIS_PROMPT_VERSION`.
3. **Dual-consensus** (`rerun_cio_dual_consensus.py`): the committee verdict is cross-checked by
   **Grok** and **ChatGPT** as independent arbiters → `grok_recommendation`,
   `chatgpt_recommendation`, `models_agree` ("✓ 2 models" / "⚠ models split" on the card).

## What is already mature (keep)
- **The CIO synthesis prompt is well-engineered:** clear role, strategy-type decision weights,
  explicit rules (allocation-first, income-protection, RSI-override, per-position income-impact %),
  a strong **past-performance guardrail** (separates historical evidence / current facts / forward
  assumptions / recommendation), and a rich structured JSON contract (recommendation, confidence,
  action, conflicts, unresolved, what_changes_view, next_review_date).
- **Dual-consensus is grounded**, not a thin prompt — arbiters get the committee's conclusion +
  narrative as context and reconcile two independent models; the more cautious call wins on split.
- **Data-quality plumbing exists:** `_check_symbol_data_quality`, and a `DATA QUALITY WARNING`
  note is injected when issues are detected ("lower confidence but still produce a recommendation").
- **Version-stamped** (`SYNTHESIS_PROMPT_VERSION`, `synthesis_version` column) for auditability.

## Findings — tighten these

### F1 [HIGH] Two portfolio/ownership sources that can contradict
The committee agents read `_build_portfolio_context()` (per-symbol from `holdings.json`), while the
synthesis builds a *separate* `port_ctx`/`position_summary` aggregation. When these disagree (stale
cache vs live holdings), the packet carries **contradictory ownership** — the AZN case (Steph "22%
position" vs synthesis "0 shares"). The CIO correctly flagged it but confidence collapsed to 0.19.
- **Fix:** one authoritative ownership/position source shared by agents *and* synthesis, and an
  **explicit "NOT CURRENTLY HELD (0 shares)"** line always emitted (the agent context only prints a
  `Position:` line when held → silence, not ground-truth, when not held).

### F2 [MED] Committee agent output contract is thin
`full_chain`/agent prompts are "cover these 5 points" + `{base_instruction}` and return free-form
narratives, unlike the synthesis's structured contract. Loose agent outputs make the synthesis
inputs inconsistent.
- **Fix:** give each agent a tight structured output (verdict ∈ fixed vocab, confidence, 3–5
  evidence bullets tagged fact/technical/risk, and an explicit "data I doubt" field) so the
  synthesis reconciles structured claims, not prose.

### F3 [MED] `/no_think` control token leaks to cloud lanes
Prompts are prefixed `/no_think` (a gemma/qwen control token). The dual-consensus reuses the same
prompt text on **Grok/ChatGPT**, to which `/no_think` is meaningless noise.
- **Fix:** strip lane-specific control tokens before sending to a cloud lane (lane-appropriate prompts).

### F4 [LOW] Data-quality note is a count, not specifics
The DQ warning says "N issue(s) detected" but not *which* fields are stale or their age, so the LLM
can't down-weight the specific bad inputs.
- **Fix:** enumerate the stale fields + age (e.g. "RSI 9 days old; price 3 days old") in the note.

### F5 [LOW] No explicit contradiction-handling rule
The CIO handled AZN well by reasoning, not by instruction. Add a rule: *"If input sources conflict
on a material fact (ownership, size, income), state the conflict, prefer the live holdings/DB source,
and lower confidence."* — makes contradiction handling deterministic instead of luck.

## Recommendation / priority
The prompts are **more mature than expected**; the biggest quality lever is **input tightness**, not
prompt rewrites. Priority: **F1 (single ownership source)** → **F2 (structured agent output)** →
F3/F4/F5. F1 is the one with a demonstrated confidence-tanking failure (AZN) and should go first.

## Scope note
This is an audit + recommendations. No prompts were changed in this pass (CIO prompts drive
trading-decision output; changes should be staged, version-bumped via `SYNTHESIS_VERSION_NUM`, and
A/B-observed). Implementation of F1–F5 to follow on operator approval.

## Implementation status (2026-07-01, operator-approved)
**Stage 1 SHIPPED** — `cio_synth_v4_input_tightness_2026-07-01`, `SYNTHESIS_VERSION_NUM=4`:
- **F1** ✅ explicit `NOT CURRENTLY HELD (0 shares)` line in *both* the agent context (`_get_context`,
  which previously stayed silent when unheld) and the synthesis `PORTFOLIO POSITION` block. Root cause
  refined during implementation: both context builders read the same `holdings.json` — the AZN
  contradiction was **time skew** (agent narratives generated from an older snapshot, embedded verbatim
  next to a fresh position summary), which the F5 precedence rule addresses.
- **F5** ✅ (promoted to ship with F1) CIO critical instruction 8: prefer the live PORTFOLIO POSITION
  block over analyst narratives on material-fact conflict, record in `conflicts`, lower confidence
  proportionally — without letting a stale-narrative conflict alone collapse confidence below 0.4.
- **F3** ✅ `_strip_local_tokens()` strips `/no_think` before every cloud lane call (`_synthesis_llm`,
  `_synthesis_dual`); local gemma fallback keeps the original prompt.

**Stage 2 PENDING** (next, after observing v4 confidence distributions): **F2** structured agent
evidence (note: agents already return JSON — the gap is tagged evidence bullets + a "data I doubt"
field, not a new contract), **F4** enumerate stale fields + age in the DQ note (and reconcile the
G1 "skip on stale" vs DQ-note "proceed with lower confidence" policy contradiction), plus a
`max_tokens` review on `_synthesis_dual` (1000 is tight for the full JSON contract and risks
truncation → silent fallback to loose parsing).

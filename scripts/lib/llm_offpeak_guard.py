"""llm_offpeak_guard.py — a lane that runs a paid LLM job from n8n must reproduce the cron line's off-peak wrapper.

2026-11-07 (LQ-20261107-43): `hermes-usefulness-backfill` was moved onto an n8n workflow whose command was
`env LLM_GLOBAL_DAILY_USD_CAP=2.00 $PY hermes_external_feedback_loop.py --apply` — no `run_with_deepseek_offpeak.sh`,
and the script has no off-peak check of its own. Its cron line runs the same job inside
`run_with_deepseek_offpeak.sh --scheduled -- ...`, so the cron arm can never spend inside DeepSeek's billing peak while
the n8n arm could. That is an AI usage policy violation (AGENTS.md §12, operator rule 2026-09-14), not a style issue.

Two ways a command is off-peak-protected, and this module accepts exactly these two:

  1. the argv names the wrapper (``run_with_deepseek_offpeak.sh``), so the wrapper's own PEAK_SKIP applies; or
  2. the allowlist entry declares ``offpeak_gate`` — the n8n run executor reproduces the same window in-process
     (``scripts/n8n_run_executor.offpeak_verdict``: outside the window a LIVE run is skipped and the receipt records
     the verdict). A dry run is never skipped: it makes no paid call.

Measured on 2026-11-07 before wiring this in (coordination ledger, all four runs of the lane): every run of
``hermes-usefulness-backfill`` carried ``offpeak: {applies: true, gate: "scheduled", skipped: false}`` and the served
allowlist entry (version 9d983b8f..4517a87f) declares ``offpeak_gate: "scheduled"``, so protection 2 was in force
and no paid call went out at a forbidden hour. The wrapper is still absent from the argv, which is why the defect
looked real from the command text alone — and why the durable answer is a detector over the declaration (this module)
rather than trust in the argv. What this module would catch is the next entry that declares neither.

Everything else is a problem. The gate vocabulary is pinned to the executor's own three gates by a test, so this file
cannot drift into a fourth spelling the executor would not honour.

2026-11-07 (LQ-20261107-247): ``config/llm_direct_callers.json`` lists *model* callers, not *DeepSeek* payers. A lane
that reaches only Grok/ChatGPT OAuth, or a local model, has no DeepSeek billing window to honour — gating it would
skip free work rather than prevent a metered call. ``deepseek_payers()`` reads the per-lane ``billing`` evidence in
that registry, and callers ask for a gate only on the lanes that can reach the metered key. Fail-closed: no block,
no evidence, no exemption.

Pure: no filesystem, no network, no clock. Callers pass the parsed allowlist and the LLM caller lane ids.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: The wrapper whose PEAK_SKIP the cron arms rely on.
OFFPEAK_WRAPPER = "run_with_deepseek_offpeak.sh"

#: The allowlist ``offpeak_gate`` values. MUST equal ``scripts/n8n_run_executor.OFFPEAK_GATES`` keys (pinned by
#: tests/test_llm_offpeak_guard_20261107.py); a value the executor does not know is not protection, it is a typo.
OFFPEAK_GATES = frozenset({"bulk", "official", "scheduled"})

#: Where an allowlist entry's argv may live. The executor reads ``command``; the others are accepted so a bundle that
#: names the wrapper in a live/dry argv is not flagged for the wrong reason.
_ARGV_FIELDS = ("command", "live_arg", "dry_run_arg")


def _tokens(entry: Mapping[str, Any]) -> list[str]:
    """Every argv token the entry declares, across the fields the executor and a reviewer read. Pure."""
    out: list[str] = []
    for field in _ARGV_FIELDS:
        raw = entry.get(field)
        if isinstance(raw, str):
            out.append(raw)
        elif isinstance(raw, (list, tuple)):
            out.extend(str(t) for t in raw if isinstance(t, (str, int, float)))
    return out


def command_names_wrapper(entry: Mapping[str, Any]) -> bool:
    """True when any declared argv names run_with_deepseek_offpeak.sh. Pure."""
    return any(OFFPEAK_WRAPPER in tok for tok in _tokens(entry))


def entry_problem(entry: Mapping[str, Any], *, llm_lane_ids: Iterable[str]) -> dict[str, Any] | None:
    """None when the entry is fine or the lane is not an LLM payer; otherwise the problem, ready to print. Pure."""
    lane = str(entry.get("lane_id") or "")
    if lane not in set(llm_lane_ids):
        return None
    gate = entry.get("offpeak_gate")
    if gate in OFFPEAK_GATES or command_names_wrapper(entry):
        return None
    return {
        "lane_id": lane,
        "code": "LLM_LANE_WITHOUT_OFFPEAK_GATE",
        "detail": ("this lane calls a model and its allowlist entry declares neither offpeak_gate "
                   f"({'/'.join(sorted(OFFPEAK_GATES))}) nor the {OFFPEAK_WRAPPER} wrapper, so an n8n LIVE run can "
                   "spend inside DeepSeek's billing peak"),
        "offpeak_gate": gate,
        "wrapper_in_argv": False,
    }


def problems(entries: Iterable[Mapping[str, Any]], *, llm_lane_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Every LLM lane whose allowlist entry is not off-peak-protected, sorted by lane id. Pure."""
    ids = list(llm_lane_ids)
    found = [p for e in entries if (p := entry_problem(e, llm_lane_ids=ids)) is not None]
    return sorted(found, key=lambda p: p["lane_id"])


# ── who actually pays DeepSeek ───────────────────────────────────────────────────────────────────────────────────
# LQ-20261107-247: the check below listed five allowlisted lanes that never reach the metered DeepSeek key — two
# Grok/ChatGPT OAuth lanes, two Grok-or-local lanes and one local-Ollama lane — and told each of them to declare a
# DeepSeek billing window it has no reason to honour. A gate on such a lane does not protect money; it skips free
# work. So the question "does this lane pay DeepSeek" is answered from the lane's own source, and the answer is
# recorded as evidence in config/llm_direct_callers.json, not as a flag on the allowlist entry.
#
# Fail-closed, and deliberately so (the LQ-43 shape, one level up): a lane is a DeepSeek payer unless its caller
# record carries a ``billing`` block that says ``deepseek_metered: false`` AND quotes the evidence. An absent block,
# a malformed block, a block without evidence, or ``deepseek_metered`` set to anything but the boolean false all
# count as a payer: an exemption is a claim about a file, and a claim with no evidence is not one.
BILLING_KEY = "billing"


def pays_deepseek(caller: Mapping[str, Any]) -> bool:
    """True when the lane can reach the metered DeepSeek key. Pure and fail-closed; see the note above."""
    block = caller.get(BILLING_KEY)
    if not isinstance(block, Mapping):
        return True
    if block.get("deepseek_metered") is not False:
        return True
    evidence = block.get("evidence")
    return not (isinstance(evidence, str) and evidence.strip())


def deepseek_payers(callers: Iterable[Mapping[str, Any]]) -> set[str]:
    """The lane ids of a caller registry that can pay DeepSeek. Pure."""
    return {str(c.get("lane_id")) for c in callers if c.get("lane_id") and pays_deepseek(c)}

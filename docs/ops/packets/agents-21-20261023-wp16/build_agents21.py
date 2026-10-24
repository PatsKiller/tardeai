"""Build AGENTS.md 21.0.0 (PROPOSED) from a 20.1.0-ACTIVE AGENTS.md.

usage: python build_agents21.py <20.1.0-ACTIVE AGENTS.md> <out AGENTS.md>
       python build_agents21.py --norm-digest <AGENTS.md>      (sha256 of build_ratify21.normalize_20(text))
Agents never edit AGENTS.md (§20). apply21-operator.sh runs this (sha-pinned) on the operator's worktree, because the
real 20.0.0 ratification writes its own PR, SHA and date into AGENTS.md: every edit here uses an anchor that holds no
such value, and the header lines that do (Effective-Date, Last-Reviewed) are matched by pattern.
"""

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_ratify21", HERE / "build_ratify21.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def quote(clause: str) -> str:
    body = "\n".join(("  " + line) if line else "" for line in clause.rstrip("\n").split("\n"))
    return "  ```\n" + body + "\n  ```\n"


BANNER = """**21.0.0 is PROPOSED (MAJOR) — advisory size suggestions from the CIO (§29).** Operator decisions 2026-10-23,
verbatim: "No, we don't need the hard code sizes. I could just ask the question without sizes. It can suggest sizes,
or I can say sizes." and, choosing the narrow amendment, "B". It lets one "Ask the CIO" answer field,
`size_suggestion`, state an ADVISORY size computed deterministically by `scripts/lib/cio_advisory_sizing.py` from the
operator's risk budget (§29.2), with its formula, inputs and as_of shown. Awaiting the operator's `APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>` (§20); until it is ratified
and merged nothing here binds, `advisory_size_suggestion()` returns None, and the 20.1.0 text governs. **Why
MAJOR:** it narrows §0 rule 1 "the agent never sizes" for one advisory field; a change that removes a restriction is
classed by the weakest guarantee after it (precedents 5.0.0, 14.0.0, 15.0.0 and 20.0.0, each narrowing §0). It cannot
be MINOR. **What does not change:** the agent never orders, stops, arms, weights a live portfolio, or writes to a
broker; the behaviour rail (the unconditional `BehaviorWriteRefused` raise in `apply_cognition()`,
`scripts/lib/cio_instrument_record.py`) and `BEHAVIOR_FIELDS` are unchanged; the Schwab `read_only` access mode,
the trading locks and the `live_submit` kill switch of §28.6 stay the operator's alone; a proposal still needs the
operator. **Byte-identical:** §2, §2A, §7, §7A, §13, §22, §23, §24, §27 and §28; while PROPOSED §0, §17, §26 and the
four adapters are byte-identical too, and the ratifying edit makes exactly the three clause edits quoted in §29.7.
**Numbering:** after 20.1.0 (ACTIVE); `Supersedes` 20.1.0. Approval phrase as proposed:
`APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>`.

"""

S29 = """# 29 · Advisory size suggestions (21.0.0, PROPOSED)

**Status: PROPOSED (MAJOR).** Binding only once AGENTS.md 21.0.0 is ACTIVE; until then 20.1.0 governs, and
§0, §17, §26 and the four adapters stay byte-identical. §29 lets the CIO state one ADVISORY size on an "Ask the
CIO" answer and nothing more; the ratifying edit makes exactly the clause edits quoted in §29.7. Every rule binds
every agent equally, whatever its model or vendor. Test: `tests/test_agents_policy_21_0_0_advisory_sizing.py`.

## 29.1 One field may carry a size, and only an advisory one

- **Only the "Ask the CIO" answer's `size_suggestion`.** No other answer, alert, page, prospect field, proposal,
  brief or n8n lane states a size. The suggestion is labelled ADVISORY, marked `not_actionable`, and shows its
  formula, every input and its as_of; an answer without all of them states no size. *Cause (§20): operator
  2026-10-23, "It can suggest sizes, or I can say sizes." and option B.*
- **The operator may always name a size instead.** When the operator names a quantity, the CIO shows the exposure and
  the risk at the stop reference of that quantity; it does not substitute its own. *Cause (§20): the same words.*

## 29.2 Computed from facts, never from a model

- **One deterministic function.** `advisory_size_suggestion()` in `scripts/lib/cio_advisory_sizing.py` computes it,
  long only, from the portfolio value V, the operator's risk budget per idea r (default 1%, at most 5%), a reference
  price E, a stop reference S below E, the operator's position limit p and sector limit s, the current position P
  and sector exposure X: shares = floor(min(V·r / (E − S), (V·p − P) / E, (V·s − X) / E)), never below zero, and
  the binding constraint named. A missing or invalid input returns no suggestion; nothing is defaulted except r.
  *Cause (§20): a size must be reproducible from its inputs, or it cannot be checked.*
- **Models may not invent sizes.** A model's output never supplies a quantity, a size or a limit. Any
  model-originated `size_suggestion`, and any `BEHAVIOR_FIELDS` key anywhere in a model's answer, is stripped before
  the deterministic suggestion is attached, and every stripped path is recorded on the answer. *Cause (§20): a
  model-written number with no formula behind it reads as advice the operator cannot audit.*

## 29.3 Never actionable

- **No order, stop or proposal path reads it.** The module imports nothing from the broker, order, stop or
  proposal code, and only `scripts/lib/cio_ask_contract.py` may import it; the test proves both. The suggestion is
  never auto-executed, never becomes a proposal, an order ticket, a stop, a weight or a watchlist size, and a
  proposal still needs the operator. *Cause (§20): §0 rule 1 — the agent never orders, stops, arms or writes to a
  broker.*
- **The rails stay as they are.** The behaviour rail (the unconditional `BehaviorWriteRefused` raise in
  `apply_cognition()`, `scripts/lib/cio_instrument_record.py`) and `BEHAVIOR_FIELDS` are unchanged, and no key of
  the suggestion is a `BEHAVIOR_FIELDS` key. The Schwab `read_only` access mode, the trading locks and the
  `live_submit` kill switch (§28.6) stay the operator's alone. *Cause (§20): operator 2026-10-23 — orders, stops,
  arming and the broker barriers stay locked.*

## 29.4 Inert until ratified

- **The function reads the policy at call time.** It returns None unless AGENTS.md's 21.0.0 history row begins
  with ACTIVE and this section's heading is present; there is no flag or environment override. *Cause (§20): §20 —
  until ratification no agent reads a PROPOSED widening as in force.*

## 29.5 Logged to CIO memory

- **Each suggestion is kept with its answer.** The suggestion, its inputs, its formula and its as_of are written to
  CIO memory with the answer, keyed by `security_guid`, never as a prospect field. *Cause (§20): operator
  2026-10-23, "the key is the persistent memory. Across the CIO system."*

## 29.6 The risk budget is the operator's

- **A §17 setting.** The risk budget per idea and the position and sector limits are operator settings (§17); an
  agent never sets, raises or infers them. *Cause (§20): who sets the budget sets the size.*

## 29.7 Ratifying edit

- **These clause edits, and nothing else outside the header block, the banner, §29 and the 21.0.0 history row.**
  `tests/test_agents_policy_21_0_0_advisory_sizing.py` holds the anchors and digests. *Cause (§20): §20 — rules are
  replaced, not accumulated; until ratification the clauses stay byte-identical.*

  (1) In §0 rule 1, directly after its third line, and the same sentence in each of the four adapters:

@R1@
  (2) In §26.1, directly after the "`MBI_BEHAVIOR = 0` holds for the record" bullet:

@R2@
  (3) In §17, directly after the 20.0.0 "Schwab stays read-only" paragraph:

@R3@
"""
S29 = (
    S29.replace("@R1@\n", quote(R.R1_INS))
    .replace("@R2@\n", quote(R.R2_INS))
    .replace("@R3@\n", quote(R.R3_INS.lstrip("\n")))
)
assert "@R" not in S29

ROW = (
    '| 21.0.0 | 2026-10-23 | PROPOSED | MAJOR | §29 "Advisory size suggestions" added. Operator decisions '
    '2026-10-23 (verbatim in the banner; option B): one "Ask the CIO" answer field, `size_suggestion`, may state '
    "an ADVISORY size computed deterministically by `scripts/lib/cio_advisory_sizing.py` from the operator's risk "
    "budget (default 1% per idea, at most 5%), capped by the position and sector limits, with formula, inputs and "
    "as_of shown; never executed, never read by an order, stop or proposal path; model-originated quantities "
    "stripped and recorded; logged to CIO memory. The behaviour rail, `BEHAVIOR_FIELDS` and the §28.6 broker "
    "barriers are unchanged. While PROPOSED §0, §17, §26 and the four adapters are byte-identical; the ratifying "
    "edit makes exactly the three clause edits quoted in §29.7: the §0 rule 1 advisory exception, the §26.1 "
    "bullet and the §17 risk-budget entry. | **PENDING** — awaiting "
    "`APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>` (§20); per-PR word, because it is MAJOR. |\n"
)


def build(base: str) -> str:
    text = base

    def rep(old: str, new: str) -> None:
        nonlocal text
        assert text.count(old) == 1, f"anchor not unique: {old[:80]!r} ({text.count(old)})"
        text = text.replace(old, new)

    def resub(pat: str, new: str) -> None:
        nonlocal text
        head, sep, tail = text.partition("\n```\n\n")
        head, n = re.subn(pat, new, head, flags=re.M)
        assert n == 1, f"header pattern {pat!r} matched {n}"
        text = head + sep + tail

    rep("Policy-Version:      20.1.0\n", "Policy-Version:      21.0.0\n")
    resub(
        r"^Status:              ACTIVE\nEffective-Date:      \d{4}-\d{2}-\d{2}\n",
        "Status:              PROPOSED\nEffective-Date:      PENDING\n",
    )
    resub(r"^Last-Reviewed:       \S+\n", "Last-Reviewed:       2026-10-23T10:00:00-04:00\n")
    rep("Supersedes:          20.0.0\n", "Supersedes:          20.1.0\n")
    assert re.search(r"^\| 20\.1\.0 \| 2026-10-23 \| ACTIVE \| MINOR \|", text, re.M), "20.1.0 row is not ACTIVE"
    rep("**20.1.0 is ACTIVE (MINOR)", BANNER + "**20.1.0 is ACTIVE (MINOR)")
    rep("\n---\n\n# Version history\n", "\n---\n\n" + S29 + "\n---\n\n# Version history\n")
    rep("| 20.1.0 | 2026-10-23 | ACTIVE | MINOR |", ROW + "| 20.1.0 | 2026-10-23 | ACTIVE | MINOR |")
    return text


if __name__ == "__main__":
    if sys.argv[1] == "--norm-digest":
        t = Path(sys.argv[2]).read_text(encoding="utf-8")
        print(hashlib.sha256(R.normalize_20(t).encode("utf-8")).hexdigest())
        sys.exit(0)
    base_p, out_p = map(Path, sys.argv[1:3])
    out_p.write_text(build(base_p.read_text(encoding="utf-8")), encoding="utf-8")
    print("wrote", out_p)

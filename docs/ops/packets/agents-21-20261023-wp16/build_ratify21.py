"""AGENTS.md 21.0.0 ratifying edit — clause constants, the edit itself, and the 20.0.0 normaliser.

usage: python build_ratify21.py <worktree> --pr N --sha <40-hex> --comment-id ID --comment-at ISO --date YYYY-MM-DD
Applied by ratify21-operator.sh (operator-run) after the operator posts APPROVE_AGENTS_POLICY_21_0_0 <pr> <sha>.
It sets the header block, the banner, the §29 status and the 21.0.0 row to ACTIVE and makes exactly the three clause
edits quoted in §29.7 (§0 rule 1 and the four adapters, §26.1, §17). Nothing else.

`normalize_20()` masks the five places the real 20.0.0 ratification writes its PR, SHA, comment id, URL and date, so
apply21-operator.sh can pin AGENTS.md on origin/main by a digest that does not depend on them.
"""

import argparse
import re
import sys
from pathlib import Path

ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")

# (1) §0 rule 1, directly after its third line; the same sentence in each of the four adapters.
R1_ANCHOR = "   the rail is an unconditional raise in code. See `AGENTS.md` §2.)\n"
R1_INS = (
    '   One advisory exception, binding only once AGENTS.md 21.0.0 is ACTIVE: an "Ask the CIO" answer\n'
    "   may state one ADVISORY size suggestion, computed only by `scripts/lib/cio_advisory_sizing.py`\n"
    "   from the operator's risk budget, with its formula, inputs and as_of shown. It is never executed,\n"
    "   never read by an order, stop or proposal path, and never originated by a model; the agent still\n"
    "   never orders, stops, arms, weights a live portfolio, or writes to a broker (AGENTS.md §29).\n"
)

# (2) §26.1, directly after the "`MBI_BEHAVIOR = 0` holds for the record" bullet.
R2_ANCHOR = "  (§12, §23.4). *Cause (§20): §0 rule 1; the §13.4 cognition boundary.*\n"
R2_INS = (
    '- **The one size the CIO may state is advisory (21.0.0, §29).** An "Ask the CIO" answer may carry the ADVISORY\n'
    "  suggestion of §29. It is logged with the answer in CIO memory, keyed by `security_guid`, never as a prospect\n"
    "  field and never under a `BEHAVIOR_FIELDS` key, and nothing that reads the record acts on it. *Cause (§20):\n"
    "  operator 2026-10-23, option B; §0 rule 1 as amended by 21.0.0.*\n"
)

# (3) §17, directly after the 20.0.0 "Schwab stays read-only" paragraph.
R3_ANCHOR = (
    "\npasskey on Ops → Controls or at the host terminal; never by an agent, a release, the release train or n8n.\n"
)
R3_INS = (
    "\n"
    "**Advisory sizing (21.0.0, §29):** the risk budget per idea that §29's advisory size suggestion uses (default 1%\n"
    "of portfolio value, at most 5%) · the position and sector concentration limits it caps against. Each is the\n"
    "operator's setting alone; an agent never sets, raises or infers one, and a model never supplies one.\n"
)

CLAUSES = ("R1_ANCHOR", "R1_INS", "R2_ANCHOR", "R2_INS", "R3_ANCHOR", "R3_INS")

_TOKEN20 = "APPROVE_AGENTS_POLICY_20_0_0"


def normalize_20(text: str) -> str:
    """Mask the PR, SHA, comment id, URL and dates the real 20.0.0 ratification writes (token lines and the
    Effective-Date line only), so a digest of the result is the same for any genuine 20.0.0 ratification."""
    out = []
    for line in text.splitlines(keepends=True):
        if _TOKEN20 in line or line.startswith("Effective-Date:"):
            line = re.sub(r"[0-9a-f]{40}", "<SHA>", line)
            line = re.sub(r"\d+", "<N>", line)
        out.append(line)
    return "".join(out)


def clause_edits(text: str) -> str:
    """The three clause edits on AGENTS.md (not the header, banner, §29 or the row). Each anchor must be unique."""

    def rep(t, old, new):
        assert t.count(old) == 1, f"anchor not unique: {old[:90]!r} ({t.count(old)})"
        return t.replace(old, new)

    text = rep(text, R1_ANCHOR + "2. **Broker code", R1_ANCHOR + R1_INS + "2. **Broker code")
    text = rep(text, R2_ANCHOR, R2_ANCHOR + R2_INS)
    text = rep(text, R3_ANCHOR, R3_ANCHOR + R3_INS)
    return text


def adapter_edit(text: str) -> str:
    assert text.count(R1_ANCHOR) == 1, "adapter: §0 rule 1 third line not found exactly once"
    return text.replace(R1_ANCHOR, R1_ANCHOR + R1_INS)


def ratify(
    root: Path, pr: int, sha: str, comment_id: str, comment_at: str, date: str, author: str = "PatsKiller"
) -> str:
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise SystemExit("--sha must be the full 40-hex head SHA the token names")
    p = root / "AGENTS.md"
    text = p.read_text(encoding="utf-8")
    token = f"APPROVE_AGENTS_POLICY_21_0_0 {pr} {sha}"
    url = f"https://github.com/PatsKiller/tardeai/pull/{pr}#issuecomment-{comment_id}"
    who = f'PR #{pr} comment by {author} {comment_at}, {url}, verbatim: "{token}"'

    def rep(old: str, new: str) -> None:
        nonlocal text
        assert text.count(old) == 1, f"anchor not unique: {old[:90]!r} ({text.count(old)})"
        text = text.replace(old, new)

    rep(
        "Policy-Version:      21.0.0\nVersioning-Scheme:   Semantic Versioning 2.0.0\nPolicy-Schema:       "
        "TradeAI-Agent-Operating-Standard/v1\nStatus:              PROPOSED\nEffective-Date:      PENDING\n",
        "Policy-Version:      21.0.0\nVersioning-Scheme:   Semantic Versioning 2.0.0\nPolicy-Schema:       "
        f"TradeAI-Agent-Operating-Standard/v1\nStatus:              ACTIVE\nEffective-Date:      {date}\n",
    )
    rep(
        "**21.0.0 is PROPOSED (MAJOR) — advisory size suggestions",
        "**21.0.0 is ACTIVE (MAJOR) — advisory size suggestions",
    )
    rep(
        "Awaiting the operator's `APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>` (§20); until it is ratified\n"
        "and merged nothing here binds, `advisory_size_suggestion()` returns None, and the 20.1.0 text governs.",
        f"Ratified by the operator {date} (`{token}`, §20; {who}); ratified by this edit, which set the header block\n"
        "to 21.0.0 ACTIVE and made the three clause edits quoted in §29.7.",
    )
    rep("# 29 · Advisory size suggestions (21.0.0, PROPOSED)", "# 29 · Advisory size suggestions (21.0.0, ACTIVE)")
    rep(
        "**Status: PROPOSED (MAJOR).** Binding only once AGENTS.md 21.0.0 is ACTIVE; until then 20.1.0 governs, and\n"
        "§0, §17, §26 and the four adapters stay byte-identical.",
        f"**Status: ACTIVE (MAJOR).** Ratified {date} (`{token}`, §20); the clauses quoted in §29.7 are in place in\n"
        "§0, §17, §26.1 and the four adapters.",
    )
    text = clause_edits(text)
    rep("| 21.0.0 | 2026-10-23 | PROPOSED | MAJOR |", "| 21.0.0 | 2026-10-23 | ACTIVE | MAJOR |")
    rep(
        "**PENDING** — awaiting `APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>` (§20); per-PR word, because it "
        "is MAJOR. |",
        f"**ACTIVE** — ratified `{token}` (operator, {who}); ratified by this edit on #{pr}'s branch, which set the "
        "header block to 21.0.0 ACTIVE and made the three clause edits quoted in §29.7; approval phrase as proposed "
        f"`APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>`; per-PR word, because it is MAJOR. Effective {date}. |",
    )
    p.write_text(text, encoding="utf-8")
    for a in ADAPTERS:
        ap = root / a
        ap.write_text(adapter_edit(ap.read_text(encoding="utf-8")), encoding="utf-8")
    return token


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--comment-id", required=True)
    ap.add_argument("--comment-at", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--author", default="PatsKiller")
    a = ap.parse_args()
    tok = ratify(Path(a.root), a.pr, a.sha, a.comment_id, a.comment_at, a.date, a.author)
    print("ratified:", tok, file=sys.stdout)

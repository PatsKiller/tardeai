#!/usr/bin/env python3
"""Build reviewable operator-only patches; never edit the caller's policy files."""

from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[4]
# Freeze the reviewed snapshot. Later unrelated main commits do not rewrite the package while it builds.
BASE = "4acb33ada3eed278c5f7652fcdcd6cbda15e68e5"
OUT = HERE
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")
TEST = "tests/test_agents_policy_20_2_0_work_pipeline.py"
GATE = "config/ci_gates/agents_policy_20_2_0_work_pipeline.json"


def source(path: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO), "show", f"{BASE}:{path}"], text=True)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"anchor not unique: {old[:100]!r}"
    return text.replace(old, new, 1)


BANNER = """<!-- AGENTS_20_2_BANNER_START -->
**20.2.0 is PROPOSED (MINOR) — the Work pipeline is an operator surface, never an agent authority.**
The operator may make the named Tier 2 acts with a fresh passkey assertion and typed phrase through the existing
host applier once this version is ACTIVE. Agents never call the Controls endpoints. Grant-binding package approval
is not included; `approve_item_enabled` stays off. Ratification flips no runtime feature flag. Coordination
clarifications cover shared-additive paths, evidence-only closure and the five task sections. Adapter headings say
eleven; their §0 bodies stay byte-identical. The existing §28.8 smoke flag is
`TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1` and remains unchanged. **Why MINOR:** it records an operator surface for acts the
operator already owns and adds evidence requirements; it grants an agent no permission. **Byte-identical:** outside
the header, this banner, the four labelled insertions and this version's history row, policy text is unchanged;
the generated §7A table is renderer-owned and excluded from whole-document comparisons. Existing authority rails
and broker restrictions are unchanged. Awaiting `APPROVE_AGENTS_POLICY_20_2_0 <pr_number> <head_sha>` (§20).
<!-- AGENTS_20_2_BANNER_END -->

"""

CLAUSES = {
    "27.2": """- **The Work pipeline's Tier 2 acts are Controls acts (20.2.0).** Binding only once AGENTS.md 20.2.0 is
  ACTIVE. From Ops → Coordination → Work pipeline the operator may, each time with a fresh passkey assertion and
  the typed phrase, through the one host applier: approve a design, phase or packet, and mark a DRAFT n8n health
  contract reviewed. Each is an append-only record in the coordination store (`designs/approvals.jsonl`,
  `contracts/reviews.jsonl`) carrying the operator's words and the assertion. Such a record is the operator's
  approval in their own words for §28.3b and §23.19, and is not a relayed approval under §28.4. An agent that carries
  it into the design or contract file cites the record. The operator may also merge a PR whose required checks are
  all exactly `success` at the head the operator saw (`--match-head-commit`), and run the exact-main release
  (prepare + promote) under an active `release-write` grant; the existing release gates and grant binding still
  apply. Approving an approval package that binds a guard grant is issuing a grant (§17), is not covered by this
  clause, and leaves `approve_item_enabled` off. Agents never call these endpoints (§27.2). Ratification does not
  enable `merge_pr_enabled` or `release_now_enabled`; each flag change needs its own reviewed PR after ratification.
  *Cause (§20): operator 2026-10-23, "nothing is actionable on there" and "both"; Handoff v3 WP-15.*
""",
    "28.3": """- **Shared-additive paths never conflict (20.2.0).** Binding only once AGENTS.md 20.2.0 is ACTIVE.
  A path declared shared-additive by `config/agent_claim_shared_paths.json` never conflicts with another session's
  claim; its declared mechanical merge procedure still applies. Every other path is exclusive and the committer
  still needs a live claim and current worklog. A missing or invalid shared-path config means all paths are
  exclusive. *Cause (§20): operator 2026-10-23; PR #2029; `docs/ops/AGENT_CLAIM_BOARD.md` §15.*
""",
    "28.3a": """- **Evidence-only closure of shipped free tasks (20.2.0).** Binding only once AGENTS.md 20.2.0 is ACTIVE.
  A free task whose work already shipped is closed with `task done --evidence-only`, a summary and PR/release
  evidence, without claiming its files again. It never closes a taken task or overrides another session's
  ownership. *Cause (§20): operator 2026-10-23; PR #2029 and Handoff v3 WP-03/WP-15.*
""",
    "28.3b": """- **Every task carries the full work package (20.2.0).** Binding only once AGENTS.md 20.2.0 is ACTIVE.
  Every task carries problem, definition of done, agent prompt, operator commands and proof of completion; done
  requires evidence. The Work pipeline, CLI and exported handoff read the same task record; a PR-open label is not
  proof of a served change. *Cause (§20): operator 2026-10-23, "this is what should be done inside of the board
  also"; Handoff v3 WP-41.*
""",
}


def build() -> None:
    assert BASE == "4acb33ada3eed278c5f7652fcdcd6cbda15e68e5", "re-review package base before rebuilding"
    original = source("AGENTS.md")
    assert "Policy-Version:      20.1.0\n" in original
    proposed = replace_once(original, "Policy-Version:      20.1.0\n", "Policy-Version:      20.2.0\n")
    proposed = replace_once(
        proposed,
        "Status:              ACTIVE\nEffective-Date:      2026-10-23\n",
        "Status:              PROPOSED\nEffective-Date:      PENDING\n",
    )
    proposed = replace_once(
        proposed, "Last-Reviewed:       2026-10-23T12:00:00-04:00\n", "Last-Reviewed:       2026-10-23T22:00:00-04:00\n"
    )
    proposed = replace_once(proposed, "Supersedes:          20.0.0\n", "Supersedes:          20.1.0\n")
    proposed = replace_once(proposed, "**20.1.0 is ACTIVE", BANNER + "**20.1.0 is ACTIVE")
    anchors = {"27.2": "\n## 27.3 ", "28.3": "\n## 28.3a ", "28.3a": "\n## 28.3b ", "28.3b": "\n## 28.4 "}
    for section, anchor in anchors.items():
        proposed = replace_once(proposed, anchor, "\n" + CLAUSES[section] + anchor)
    row = "| 20.2.0 | 2026-10-23 | PROPOSED | MINOR | Work pipeline Tier 2 acts through the host applier count as the operator's own, with fresh passkey and typed phrase; agents never call them. Grant-binding package approval stays excluded; runtime flags unchanged. Shared-additive paths, evidence-only shipped-task closure, five-section task proof and eleven-rule adapter headings clarified; §28.8 smoke flag unchanged. | **PENDING** — awaiting `APPROVE_AGENTS_POLICY_20_2_0 <pr_number> <head_sha>` (§20). |\n"
    proposed = replace_once(proposed, "| 20.1.0 |", row + "| 20.1.0 |")
    files = {"AGENTS.md": proposed}
    for path in ADAPTERS:
        files[path] = replace_once(source(path), "## The ten rules, verbatim", "## The eleven rules, verbatim")

    masked = lambda t: __import__("re").sub(
        r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
        r"\1\n<generated>\n\2",
        t,
        flags=__import__("re").S,
    )
    constants = {
        "base_header": {
            "Policy-Version": "20.1.0",
            "Status": "ACTIVE",
            "Effective-Date": "2026-10-23",
            "Last-Reviewed": "2026-10-23T12:00:00-04:00",
            "Supersedes": "20.0.0",
        },
        "base_masked_sha256": digest(masked(original)),
        "banner": BANNER,
        "clauses": CLAUSES,
        "adapter_sha256": {p: digest(source(p)) for p in ADAPTERS},
    }
    test = (HERE / "policy_test.py.in").read_text().replace("__CONSTANTS__", repr(constants))
    formatter = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/ruff")
    test = subprocess.check_output([str(formatter), "format", "--stdin-filename", TEST, "-"], input=test, text=True)
    files[TEST] = test
    spec = importlib.util.spec_from_file_location("gate", REPO / "scripts/lib/ci_gates.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files[GATE] = module.render(
        module.make_record(
            "agents_policy_20_2_0_work_pipeline",
            [TEST],
            [
                "ANCHOR: AGENTS_POLICY_20_2_0_WORK_PIPELINE — operator-only 20.2.0 package; named Tier2 acts, unchanged authority rails, evidence and adapter parity."
            ],
        )
    )

    # Preserve historical pinning by undoing only the new package's exact additions.
    p = "tests/test_agents_policy_20_1_0_live_server_market_hours.py"
    t = source(p)
    anchor = 'AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")\n'
    inject = "from tests.test_agents_policy_20_2_0_work_pipeline import pre_20_2_0, pre_20_2_0_adapter  # noqa: E402\n"
    t = replace_once(t, anchor, inject + anchor + "AGENTS = pre_20_2_0(AGENTS)\n")
    t = t.replace(
        'h((ROOT / a).read_text(encoding="utf-8")) == ADAPTER_SHA256[a]',
        'h(pre_20_2_0_adapter((ROOT / a).read_text(encoding="utf-8"))) == ADAPTER_SHA256[a]',
    )
    files[p] = t
    p = "tests/test_agents_policy_20_0_0_agent_operations.py"
    t = source(p)
    t = replace_once(t, anchor, inject + anchor + "AGENTS = pre_20_2_0(AGENTS)\n")
    t = replace_once(
        t, "def pre_20_0_0(text: str) -> str:\n", "def pre_20_0_0(text: str) -> str:\n    text = pre_20_2_0(text)\n"
    )
    t = replace_once(
        t,
        "def pre_20_0_0_adapter(text: str) -> str:\n",
        "def pre_20_0_0_adapter(text: str) -> str:\n    text = pre_20_2_0_adapter(text)\n",
    )
    t = replace_once(
        t,
        '    text = (ROOT / adapter).read_text(encoding="utf-8")\n',
        '    text = pre_20_2_0_adapter((ROOT / adapter).read_text(encoding="utf-8"))\n',
    )
    files[p] = t
    p = "tests/test_agents_section_zero_parity.py"
    files[p] = source(p).replace("The ten rules", "The eleven rules")
    p = "tests/test_agents_policy_4_6_0_platform_rules.py"
    files[p] = replace_once(
        source(p), '(20, 1, 0): {"20.0.0"}}.get(', '(20, 1, 0): {"20.0.0"}, (20, 2, 0): {"20.1.0"}}.get('
    )

    policy_files = {k: v for k, v in files.items() if k == "AGENTS.md" or k in ADAPTERS}
    support_files = {k: v for k, v in files.items() if k not in policy_files}

    def diff(rows):
        chunks = []
        for path, text in rows.items():
            proc = subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:{path}"], capture_output=True, text=True)
            old = proc.stdout if proc.returncode == 0 else ""
            chunks.append(
                "".join(
                    difflib.unified_diff(
                        old.splitlines(True),
                        text.splitlines(True),
                        fromfile=f"a/{path}" if old else "/dev/null",
                        tofile=f"b/{path}",
                    )
                )
            )
        # Git accepts an empty context line; omit its marker space so the
        # tracked patch artifact itself also passes repository whitespace checks.
        return "".join("\n" if line == " \n" else line for line in "".join(chunks).splitlines(keepends=True))

    (OUT / "agents-20.2.0-proposed.patch").write_text(diff(policy_files))
    (OUT / "tests-20.2.0.patch").write_text(diff(support_files))
    bases = {}
    for path in files:
        proc = subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:{path}"], capture_output=True)
        bases[path] = hashlib.sha256(proc.stdout).hexdigest() if proc.returncode == 0 else "ABSENT"
    bases["config/ops_controls.json"] = digest(source("config/ops_controls.json"))
    (OUT / "BASE_SHA").write_text(BASE + "\n")
    (OUT / "base-digests.json").write_text(json.dumps(bases, indent=2) + "\n")
    metadata = {
        "schema": "AgentsPolicyOperatorPackage@v1",
        "version": "20.2.0",
        "status": "PROPOSED",
        "base_sha": BASE,
        "base_policy": "20.1.0 ACTIVE",
        "files": list(files),
        "base_digests": bases,
        "masked_base_sha256": constants["base_masked_sha256"],
        "runtime_flags_changed": False,
        "operator_only": True,
    }
    (OUT / "package.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(
        "built",
        BASE,
        "files",
        len(files),
        "policy bytes",
        len(proposed),
        "base masked digest",
        constants["base_masked_sha256"],
    )


if __name__ == "__main__":
    build()

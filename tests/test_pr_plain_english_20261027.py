"""Every PR explains itself in plain English (AGENTS.md §28.12, 26.0.0; operator 2026-10-27).

Operator, verbatim: "make sure those approvals of PR are in plain English, the who, what, when, and why of what's
changing or what's being implemented, and fallbacks, if anything ... not just tonight's, everything going forward."

Pins: the checker accepts a complete block and rejects each missing or placeholder answer, a too-short title, and a
block placed after the technical detail; drafts and bots pass; the PR template carries the block and itself fails
until filled; the workflow fires on edits and ready_for_review and runs the checker from the base commit; AGENTS.md
states the rule.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("ppe", ROOT / "scripts/check_pr_plain_english.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


GOOD = """## In plain English
**What changes:** The disk cleanup tool stops deleting files it was never allowed to delete.
**Why:** A 2026-10-27 review found it could remove files outside the reviewed rules.
**Who / what it affects:** Only the nightly disk check; nothing the operator sees changes.
**When it takes effect:** Within minutes of merge, when the server picks up the new main.
**Approval:** Digest tap.
**Risk and fallback:** If it refuses too much, disk alerts page as before; revert the PR to undo.

## Technical detail
- Files: scripts/disk_hygiene_enforcer.py
"""
TITLE = "Disk cleanup tool refuses deletions outside its reviewed rules"


def test_a_complete_block_passes():
    assert _mod().check(TITLE, GOOD) == []


def test_each_missing_answer_is_named():
    mod = _mod()
    for label in mod.LABELS:
        body = re.sub(r"\*\*" + re.escape(label) + r":\*\*[^\n]*\n", "", GOOD, count=1)
        errs = mod.check(TITLE, body)
        assert any(label in e for e in errs), (label, errs)


def test_placeholders_and_empty_answers_fail():
    mod = _mod()
    body = GOOD.replace("Digest tap.", "<Digest tap — or — Held>")
    assert any("Approval" in e for e in mod.check(TITLE, body))
    body = GOOD.replace("**Why:** A 2026-10-27 review found it could remove files outside the reviewed rules.",
                        "**Why:**")
    assert any("Why" in e for e in mod.check(TITLE, body))


def test_short_title_and_late_block_fail():
    mod = _mod()
    assert any("title" in e for e in mod.check("[held] fix stuff", GOOD))
    late = "## Technical detail\n- x\n\n" + GOOD.split("\n## Technical detail")[0] + "\n"
    assert any("before" in e for e in mod.check(TITLE, late))
    assert any("no '## In plain English'" in e for e in mod.check(TITLE, "just a description"))


def test_drafts_and_bots_pass_with_a_notice(tmp_path, capsys):
    mod = _mod()
    ev = tmp_path / "e.json"
    ev.write_text(json.dumps({"pull_request": {"title": "x", "body": "", "draft": True, "user": {"login": "a"}}}))
    assert mod.main(["--event", str(ev)]) == 0
    assert "draft PR" in capsys.readouterr().out
    ev.write_text(json.dumps({"pull_request": {"title": "x", "body": "", "draft": False,
                                               "user": {"login": "dependabot[bot]"}}}))
    assert mod.main(["--event", str(ev)]) == 0
    ev.write_text(json.dumps({"pull_request": {"title": "x", "body": "", "draft": False, "user": {"login": "a"}}}))
    assert mod.main(["--event", str(ev)]) == 1


def test_template_carries_the_block_and_fails_until_filled():
    mod = _mod()
    tpl = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    assert mod.HEADING in tpl
    for label in mod.LABELS:
        assert f"**{label}:**" in tpl, label
    assert tpl.index(mod.HEADING) < tpl.index("## Technical detail")
    assert any("placeholder" in e for e in mod.check(TITLE, tpl)), "an unfilled template must not pass"


def test_workflow_fires_on_edits_and_uses_the_base_checker():
    doc = yaml.safe_load((ROOT / ".github/workflows/pr-plain-english.yml").read_text(encoding="utf-8"))
    on = doc.get(True, doc.get("on"))
    assert {"opened", "edited", "synchronize", "reopened", "ready_for_review"} <= set(on["pull_request"]["types"])
    assert doc["permissions"] == {"contents": "read"}
    steps = doc["jobs"]["plain-english"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert any("check_pr_plain_english.py" in str(s.get("run", "")) for s in steps)


def test_agents_md_states_the_rule():
    text = re.sub(r"\s+", " ", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))
    assert "Every PR explains itself in plain English" in text
    assert "scripts/check_pr_plain_english.py" in text

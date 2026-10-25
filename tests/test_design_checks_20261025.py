"""Design checks in CI (AGENTS.md §28.13 proposed, design/README.md): design-reference line + removal guard.

Synthetic PR bodies and unified diffs; reads the committed design/ folder. Git-free and hermetic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_design_reference as cli
from scripts.lib import design_checks as dc

ROOT = Path(__file__).resolve().parents[1]
NAV = "apps/command-center-v3/src/components/NavRail.tsx"
TIV = "apps/command-center-v3/src/pages/TradeInViewPage.tsx"
AGENTS_DESK = "apps/command-center-v3/src/pages/desks/AgentsDesk.tsx"


def diff(path: str, removed=(), added=()) -> str:
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", "@@ -1,1 +1,1 @@"]
    return "\n".join(lines + [f"-{x}" for x in removed] + [f"+{x}" for x in added]) + "\n"


# ---------------------------------------------------------------- which files are UI


@pytest.mark.parametrize("path,ui", [
    ("apps/command-center-v3/src/pages/HomeHub.tsx", True),
    ("apps/command-center-v3/src/styles/tokens.css", True),
    ("apps/command-center-v3/src/lib/format.ts", True),
    ("apps/command-center-v3/src/lib/format.test.ts", False),
    ("apps/command-center-v3/src/fixtures/watchLists.fixture.ts", False),
    ("apps/command-center-v3/e2e/watch-lists.spec.ts", False),
    ("scripts/api_v2.py", False),
])
def test_ui_file_scope(path, ui):
    assert dc.is_ui_file(path) is ui


# ---------------------------------------------------------------- Design: line


def test_body_refs_are_parsed():
    body = "Summary\n\nDesign: watch/v001\n- Design: `home/v001`\nDesign: none\n"
    assert dc.design_refs(body) == ["watch/v001", "home/v001", "none"]
    assert dc.design_refs("Our design: is great") == []


def test_non_ui_pr_needs_no_reference():
    assert dc.check_reference("", ["scripts/x.py"], ROOT) == ([], [])


def test_ui_pr_without_reference_is_refused():
    errors, _ = dc.check_reference("Fixes a thing", [NAV], ROOT)
    assert errors and "Design: <page>/vNNN" in errors[0]


def test_design_none_passes_for_a_ui_pr_without_removals():
    assert dc.check_reference("Design: none", [NAV], ROOT) == ([], [])


def test_approved_version_is_accepted_and_unknown_or_unapproved_refused(tmp_path):
    assert dc.check_reference("Design: tradeinview/v001", [TIV], ROOT) == ([], ["tradeinview/v001"])
    errs, _ = dc.check_reference("Design: nosuchpage/v001", [TIV], ROOT)
    assert "not in design/registry.json" in errs[0]
    errs, _ = dc.check_reference("Design: tradeinview/v009", [TIV], ROOT)
    assert "does not exist" in errs[0]
    errs, _ = dc.check_reference("Design: none\nDesign: home/v001", [TIV], ROOT)
    assert "both" in errs[0]


def test_proposed_version_cannot_be_built(tmp_path):
    import shutil
    shutil.copytree(ROOT / "design", tmp_path / "design")
    p = tmp_path / "design/pages/home/versions/v001/status.json"
    status = json.loads(p.read_text())
    status["state"] = "PROPOSED"
    p.write_text(json.dumps(status))
    errs, cited = dc.check_reference("Design: home/v001", ["apps/command-center-v3/src/pages/HomeHub.tsx"], tmp_path)
    assert cited == [] and "only an APPROVED or IMPLEMENTING" in errs[0]


# ---------------------------------------------------------------- removal guard


def test_removed_nav_item_with_design_none_fails():
    d = diff(NAV, removed=["      { to: '/strategy', label: 'Strategy', restored: true },"])
    errs = dc.check_removals(d, [], ROOT)
    assert len(errs) == 1 and 'nav "Strategy" is removed' in errs[0] and "Design: none" in errs[0]


def test_removed_route_fails_and_moved_tab_passes():
    d = diff("apps/command-center-v3/src/App.tsx", removed=['  <Route path="rotation" element={<X/>} />'])
    assert dc.check_removals(d, [], ROOT)
    moved = diff(TIV, removed=["const a = [{ id: 'calendar', label: 'Calendar' }]"]) + \
        diff("apps/command-center-v3/src/components/tradeinview/Tabs.tsx", added=["const b = [{ id: 'calendar', label: 'Calendar' }]"])
    assert dc.check_removals(moved, [], ROOT) == []


def test_tradeinview_calendar_replay_hide_regression_fails():
    """10-24: TradeInView hid Calendar and Replay without an approved mockup. v001 keeps both tabs."""
    removed = diff(TIV, removed=["const tabs = [{ id: 'journeys', label: 'Journeys' }, { id: 'calendar', label: 'Calendar' },",
                                 "  { id: 'replay', label: 'Replay' }, { id: 'history', label: 'Holding history' }]"],
                   added=["const tabs = [{ id: 'journeys', label: 'Journeys' }, { id: 'history', label: 'Holding history' }]"])
    errs = dc.check_removals(removed, ["tradeinview/v001"], ROOT)
    assert {e.split('"')[1] for e in errs} == {"Calendar", "Replay"}
    hidden = diff(TIV, added=["  { id: 'calendar', label: 'Calendar', hidden: true },",
                              "  {false && { id: 'replay', label: 'Replay' }}"])
    errs = dc.check_removals(hidden, ["tradeinview/v001"], ROOT)
    assert len(errs) == 2 and all("is hidden" in e for e in errs)


def test_removal_listed_in_the_cited_spec_passes():
    d = diff(AGENTS_DESK, removed=["const tabs = [{ id: 'evidence', label: 'Evidence' }]"])
    assert dc.check_removals(d, ["agents/v001"], ROOT) == []
    assert dc.check_removals(d, [], ROOT)  # same removal under Design: none fails


def test_removed_panel_heading_is_detected():
    d = diff("apps/command-center-v3/src/pages/ApprovalsHub.tsx",
             removed=['<section className="panel"><h2>Decided recently</h2>', '<section aria-label="Waiting approvals">'])
    labels = {c["label"] for c in dc.surface_changes(d)}
    assert labels == {"Decided recently", "Waiting approvals"}


def test_non_ui_files_in_the_diff_are_ignored():
    d = diff("apps/command-center-v3/e2e/x.spec.ts", removed=["{ id: 'a', label: 'Gone' }"])
    assert dc.surface_changes(d) == []


# ---------------------------------------------------------------- CLI (git-free)


def _run(tmp_path, body, changed, d):
    (tmp_path / "b.md").write_text(body)
    (tmp_path / "c.txt").write_text("\n".join(changed))
    (tmp_path / "d.diff").write_text(d)
    return cli.main(["--body-file", str(tmp_path / "b.md"), "--changed-file", str(tmp_path / "c.txt"),
                     "--diff-file", str(tmp_path / "d.diff")])


def test_cli_pass_and_fail(tmp_path, capsys):
    assert _run(tmp_path, "Design: none", [NAV], diff(NAV, added=["// comment"])) == 0
    assert "PASS" in capsys.readouterr().out
    assert _run(tmp_path, "no line", [NAV], "") == 1
    assert "REFUSED" in capsys.readouterr().out


def test_cli_reads_the_event_payload(tmp_path, monkeypatch, capsys):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": "Design: none"}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    (tmp_path / "c.txt").write_text(NAV)
    (tmp_path / "d.diff").write_text("")
    assert cli.main(["--changed-file", str(tmp_path / "c.txt"), "--diff-file", str(tmp_path / "d.diff")]) == 0


def test_workflow_runs_the_blocking_checks_and_marks_visual_report_only():
    wf = (ROOT / ".github/workflows/design-checks.yml").read_text()
    for needle in ("gen_design_tokens.py --check", "check_design_registry.py", "check_design_reference.py",
                   "design-checks.fixture.mjs", "edited", "draft == false", "contents: read"):
        assert needle in wf, needle
    assert "2026-11-01" in wf and "continue-on-error" in wf
    assert "runner." not in wf.split("steps:")[0]  # no job-level runner context


def test_phone_rules_baseline_is_well_formed():
    base = json.loads((ROOT / "apps/command-center-v3/e2e/design-checks/phone_rules_baseline.json").read_text())
    assert base["schema"] == "DesignPhoneRulesBaseline@v1"
    assert set(base["rules"]) == {"fixed_chrome", "tap_target", "horizontal_overflow", "raw_iso", "empty_bullet"}
    for key in base["violations"]:
        page, width, rule = key.split("|")[:3]
        assert width in ("412", "390") and rule in base["rules"]

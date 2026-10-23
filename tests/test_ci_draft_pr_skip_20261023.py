"""Push policy v2, CI half (2026-10-23): a draft PR is a cheap continuity checkpoint.

Pins, for every workflow under .github/workflows:
  * a `pull_request` trigger also fires on `ready_for_review`, so marking a draft ready starts the full fleet;
  * every job that a draft could start (a root job, or a job whose `if` uses always()) carries the draft guard,
    so a draft runs none of them;
  * every pull_request workflow has a concurrency group that cancels a superseded PR run but keeps one group per
    SHA for pushes to main (a merged SHA is never left without CI evidence);
  * no push trigger fires on an agent branch (fix/**, feat/**, feature/**, wt/**, aif/**, hardening/**, or a push
    trigger with no branch filter at all): the PR run is the run;
  * draft-quick-check is the one job a draft runs, and it never runs on a ready PR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / ".github" / "workflows"
GUARD = "github.event_name != 'pull_request' || github.event.pull_request.draft == false"
DRAFT_QUICK = "draft-quick-check.yml"
# SOP Stage 7 always-on governance (about one runner-minute; its CONTROL7 proof pins the workflow blob): it keeps
# running on drafts too, so a draft's required `agent-governance` context is a real result, not a skip.
ALWAYS_ON = "agent-governance.yml"
AGENT_BRANCH_PATTERNS = ("fix/", "feat/", "feature/", "wt/", "aif/", "hardening/")
# Workflows whose draft guard is pending because another live session holds the file on the claim board
# (AGENTS.md rule 11; never edit a claimed file). Each entry names the holder. Remove the entry in the PR that
# adds the three hunks (types incl. ready_for_review, concurrency group, job draft guard) to that workflow.
PENDING_CLAIMED = {
    # held by claude/acctlabel (claim 20261023T171134Z-claude-877eaed7, feat/cc-account-labels-20261023)
    "cc-surface-agreement-ci.yml",
}


def _load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _on(doc: dict) -> dict:
    on = doc.get(True, doc.get("on"))
    return on if isinstance(on, dict) else {}


def _pr_workflows() -> list[Path]:
    return sorted(p for p in WF_DIR.glob("*.yml") if "pull_request" in _on(_load(p)))


def _full_fleet() -> list[Path]:
    return [p for p in _pr_workflows() if p.name not in (DRAFT_QUICK, ALWAYS_ON) and p.name not in PENDING_CLAIMED]


def test_pending_claimed_entries_are_real_and_still_pending():
    """A pending entry must name a real pull_request workflow that still lacks the guard; once it is guarded,
    the entry must be removed so the workflow is pinned like the rest."""
    for name in PENDING_CLAIMED:
        path = WF_DIR / name
        assert path in _pr_workflows(), name
        assert GUARD not in path.read_text(encoding="utf-8"), f"{name} is guarded now: remove it from PENDING_CLAIMED"


def test_always_on_governance_is_unchanged_and_runs_on_drafts():
    doc = _load(WF_DIR / ALWAYS_ON)
    assert _on(doc)["pull_request"] is None  # default types: opened, synchronize, reopened -- drafts included
    assert all("draft" not in str(j.get("if") or "") for j in doc["jobs"].values())


def test_there_are_pull_request_workflows():
    assert len(_full_fleet()) >= 15


@pytest.mark.parametrize("path", _full_fleet(), ids=lambda p: p.name)
def test_pull_request_fires_on_ready_for_review(path: Path):
    pr = _on(_load(path))["pull_request"] or {}
    types = pr.get("types")
    assert types, f"{path.name}: pull_request has no explicit types; a draft marked ready would not re-run CI"
    assert {"opened", "synchronize", "reopened", "ready_for_review"} <= set(types), (path.name, types)


def _never_on_pull_request(cond: str) -> bool:
    """A job condition that is false for every pull_request event (dispatch-only, schedule-only, push-only)."""
    c = " ".join(cond.split())
    if c.startswith("${{") and c.endswith("}}"):
        c = c[3:-2].strip()
    conjuncts = {p.strip() for p in c.split("&&")}
    return bool(
        conjuncts
        & {
            "github.event_name == 'workflow_dispatch'",
            "github.event_name == 'schedule'",
            "github.event_name != 'pull_request'",
            "github.event_name == 'push'",
        }
    )


@pytest.mark.parametrize("path", _full_fleet(), ids=lambda p: p.name)
def test_every_job_a_draft_could_start_is_guarded(path: Path):
    doc = _load(path)
    for name, job in doc["jobs"].items():
        cond = job.get("if")
        cond_s = str(cond or "")
        startable = not job.get("needs") or "always()" in cond_s
        if not startable:
            continue  # a dependent job is skipped with the job it needs
        if _never_on_pull_request(cond_s):
            continue
        assert GUARD in cond_s, f"{path.name}: job {name!r} would run on a draft PR (if: {cond!r})"


@pytest.mark.parametrize("path", _full_fleet(), ids=lambda p: p.name)
def test_pull_request_runs_are_cancelled_when_superseded(path: Path):
    conc = _load(path).get("concurrency")
    assert isinstance(conc, dict), f"{path.name}: no concurrency group; a superseded PR run keeps billing"
    group = str(conc.get("group"))
    cancel = str(conc.get("cancel-in-progress"))
    assert "github.ref" in group, (path.name, group)
    assert cancel in ("True", "${{ github.event_name == 'pull_request' }}", "${{ github.event_name != 'schedule' }}"), (
        path.name,
        cancel,
    )


@pytest.mark.parametrize("path", sorted(WF_DIR.glob("*.yml")), ids=lambda p: p.name)
def test_no_push_trigger_fires_on_agent_branches(path: Path):
    on = _on(_load(path))
    if "push" not in on:
        return
    push = on["push"] or {}
    branches = push.get("branches")
    if path.name == "watch-quality-governance-ci.yml":
        assert branches == ["agent/watch-quality-governance-v1"]  # a retired branch name; inert
        return
    assert branches, f"{path.name}: a push trigger with no branch filter fires on every agent WIP push"
    for b in branches:
        assert not b.startswith(AGENT_BRANCH_PATTERNS), f"{path.name}: push fires on agent branches {b!r}"


def test_draft_quick_check_runs_only_on_drafts_and_is_cheap():
    doc = _load(WF_DIR / DRAFT_QUICK)
    on = _on(doc)
    assert set(on) == {"pull_request"}
    assert "ready_for_review" not in on["pull_request"]["types"]
    jobs = doc["jobs"]
    assert list(jobs) == ["draft-quick"]
    job = jobs["draft-quick"]
    assert job["if"] == "github.event.pull_request.draft == true"
    assert job["timeout-minutes"] <= 5
    assert doc["permissions"] == {"contents": "read", "pull-requests": "read"}
    text = (WF_DIR / DRAFT_QUICK).read_text(encoding="utf-8")
    assert "check_no_secrets.py --tree" in text
    assert "pytest" not in text  # syntax and secrets only: behaviour is proved by the full fleet on ready


def test_required_contexts_still_run_on_ready_prs():
    """The three required contexts keep reporting on every non-draft PR: no path filter was added."""
    for name in ("agent-governance.yml", "cio-production-hardening-ci.yml", "release-readiness.yml"):
        pr = _on(_load(WF_DIR / name))["pull_request"] or {}
        assert "paths" not in pr and "paths-ignore" not in pr, name

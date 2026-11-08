"""LQ-20261107-1228: the self-heal fixer gives the agent real context, or does not call it.

The lead's dry run on the live release (8de62f79c) found three gaps:
1. Job shf-0644049006-1 (lane incident-identity-spine) was admitted with an EMPTY evidence pack: failing_run all
   null, final_exception null, script null, registry null. A job with no error text or no script is now refused
   and escalated as a FINDING (at admission and for already-queued jobs), never handed to a model.
2. The fix worktree was based on origin/main (11-06), not the served release, which holds local-only folds under
   the no-push order. The base is now the served CURRENT/GIT_SHA, and there is no silent fallback.
3. The pack omitted the lane's contracts. It now carries the lane's rows from config/n8n_health_contracts.json,
   config/lane_registry.json and config/n8n_run_allowlist.json (the n8n argv).

Hermetic: tmp git repos and tmp state only. No DB, network, model or broker.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_fixer as F  # noqa: E402 -- scripts/ must be on sys.path first
import self_heal_fixer as S  # noqa: E402 -- scripts/ must be on sys.path first
from tests import test_lq1192_self_heal_local_only_20261108 as L  # noqa: E402 -- scripts/ must be on sys.path first
from tests import test_self_heal_fixer_20261016 as B  # noqa: E402 -- scripts/ must be on sys.path first
from tests.test_self_heal_fixer_20261016 import sandbox  # noqa: E402,F401 -- pytest fixture imported by name

NOW = B.NOW

# The lead's dry receipt for shf-0644049006-1, field for field.
EMPTY_PACK = {
    "schema": F.EVIDENCE_SCHEMA,
    "job_id": "shf-0644049006-1",
    "lane": "incident-identity-spine",
    "failing_run": {"run_id": None, "state": None, "exit_code": None, "reason": None, "code_sha": None,
                    "finished_at": None, "argv": [], "stderr_tail": "", "stdout_tail": None},
    "final_exception": None,
    "script": None,
    "registry": None,
}


@pytest.fixture(autouse=True)
def _ci(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")


def _sh_out(*cmd) -> str:
    import subprocess

    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def _cfg_update(sb, **repo) -> dict:
    cfg = json.loads(sb["cfg"].read_text())
    for k, v in repo.items():
        if v is None:
            cfg["repo"].pop(k, None)
        else:
            cfg["repo"][k] = v
    sb["cfg"].write_text(json.dumps(cfg))
    return cfg


def _empty_incident(sb):
    """The producer's own defect record, with no stderr and no failing run: incident-identity-spine's shape."""
    doc = json.loads(sb["incident"].read_text())
    doc["code_defect"] = B._producer_defect(lane="buggy-lane", stderr="", run="r1")
    doc["receipt"] = {"run_id": "r1", "argv": [], "stderr_tail": ""}
    sb["incident"].write_text(json.dumps(doc))


def _receipt(sb) -> dict:
    return json.loads((sb["state"] / B.CFG["state"]["receipt_rel"]).read_text())


def _queue_job(sb, lane="queued-lane", failure_kind="code_error:incident"):
    st = sb["state"] / B.CFG["state"]["state_rel"]
    st.parent.mkdir(parents=True, exist_ok=True)
    at = (NOW - timedelta(hours=1)).isoformat()
    job = {
        "schema": F.JOB_SCHEMA, "job_id": "shf-q-1", "dedupe_key": f"{lane}|sig-q", "lane": lane,
        "signature": "sig-q", "defect_id": "cd-q", "state": F.FIX_REQUESTED, "failure_kind": failure_kind,
        "created_at": at, "updated_at": at, "history": [{"state": F.FIX_REQUESTED, "at": at}],
        "iterations": [], "cost_usd": 0.0, "escalated_at": None,
    }
    st.write_text(json.dumps({"schema": F.STATE_SCHEMA, "jobs": {"shf-q-1": job}}))


# ---------------------------------------------------------------- 1. the evidence gate (pure)


def test_the_live_empty_pack_is_a_gap():
    assert F.evidence_gap(EMPTY_PACK) == "no_error_text"


def test_error_text_without_a_script_is_a_gap():
    pack = {**EMPTY_PACK, "failing_run": {**EMPTY_PACK["failing_run"], "stderr_tail": "KeyError: 'x'"}}
    assert F.evidence_gap(pack) == "no_script"


@pytest.mark.parametrize(
    "extra",
    [
        {"final_exception": {"type": "KeyError", "message": "'x'"}},
        {"failing_run": {**EMPTY_PACK["failing_run"], "stderr_tail": "Traceback\nKeyError: 'x'\n"}},
    ],
)
def test_error_text_and_a_script_pass(extra):
    assert F.evidence_gap({**EMPTY_PACK, **extra, "script": "scripts/x.py"}) is None


@pytest.mark.parametrize(
    "stderr",
    [
        "FAILED tests/test_x.py::test_y - StopIteration",  # a main-red CI request: argv is empty, no lane script
        'Traceback (most recent call last):\n  File "/srv/repo/scripts/lane.py", line 3, in <module>\nKeyError: 1',
    ],
)
def test_error_text_that_names_a_repo_file_needs_no_script(stderr):
    pack = {**EMPTY_PACK, "failing_run": {**EMPTY_PACK["failing_run"], "stderr_tail": stderr}}
    assert F.evidence_gap(pack) is None


def test_whitespace_stderr_is_not_error_text():
    pack = {**EMPTY_PACK, "failing_run": {**EMPTY_PACK["failing_run"], "stderr_tail": " \n\t"}, "script": "s.py"}
    assert F.evidence_gap(pack) == "no_error_text"


# ---------------------------------------------------------------- 2. lane contracts in the pack


HEALTH = {"contracts": [{"id": "lane-a", "workflow_id": "wf", "stage": "live", "purpose": {"text": "p"},
                         "healthy": [{"check": "ok"}], "failed": [{"check": "run_failed"}],
                         "expected_output": {"rule": "min_produced", "min_produced": 1}, "review": "dropped"}]}
ALLOW = {"lanes": [{"lane_id": "lane-a", "command": ["$PY", "scripts/a.py"], "timeout_s": 300,
                    "dry_run_arg": ["--dry-run"], "env_names": ["DB_PASSWORD"], "source": "dropped"}]}
ROW = {"lane_id": "lane-a", "owner": "ops", "scheduler": {"kind": "n8n", "match": "scripts/a.py"},
       "output_signal": {"path": "data/runtime/a_last.json"}, "rationalization": "dropped"}


def test_lane_contracts_carries_the_three_rows_by_key_subset():
    c = F.lane_contracts("lane-a", health_doc=HEALTH, registry_row=ROW, allowlist_doc=ALLOW)
    assert c["missing"] == []
    assert c["health_contract"]["expected_output"] == {"rule": "min_produced", "min_produced": 1}
    assert c["health_contract"]["failed"] == [{"check": "run_failed"}] and "review" not in c["health_contract"]
    assert c["n8n_run"] == {"command": ["$PY", "scripts/a.py"], "timeout_s": 300, "dry_run_arg": ["--dry-run"]}
    assert "env_names" not in c["n8n_run"] and "rationalization" not in c["registry"]
    assert c["registry"]["scheduler"]["match"] == "scripts/a.py"


def test_an_unknown_lane_names_every_missing_row():
    c = F.lane_contracts("incident-identity-spine", health_doc=HEALTH, registry_row=None, allowlist_doc=ALLOW)
    assert c == {"health_contract": None, "registry": None, "n8n_run": None,
                 "missing": ["health_contract", "registry", "n8n_run"]}


def test_contract_strings_are_bounded():
    doc = {"contracts": [{"id": "lane-a", "purpose": {"text": "x" * 5000}}]}
    c = F.lane_contracts("lane-a", health_doc=doc, registry_row=None, allowlist_doc=None)
    assert len(c["health_contract"]["purpose"]["text"]) == F.CONTRACT_STR_CHARS + 1


def test_the_repo_config_yields_contracts_for_a_real_lane():
    """Against this commit's real config: some lane has all three rows, and the pack carries them."""
    health = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    run_ids = {r.get("lane_id") for r in allow["lanes"]}
    lane = next(c["id"] for c in health["contracts"] if c.get("id") in rows and c.get("id") in run_ids)
    c = F.lane_contracts(lane, health_doc=health, registry_row=rows[lane], allowlist_doc=allow)
    assert c["missing"] == [] and c["n8n_run"]["command"] and "healthy" in c["health_contract"]
    assert S.lane_contracts_for(lane, rows[lane]) == c


def test_build_evidence_and_prompt_carry_the_contracts():
    c = F.lane_contracts("lane-a", health_doc=HEALTH, registry_row=ROW, allowlist_doc=ALLOW)
    ev = F.build_evidence(
        {"job_id": "j", "lane": "lane-a"},
        incident={"script": "scripts/a.py"},
        receipt={"stderr_tail": "ZeroDivisionError: division by zero"},
        registry_row=ROW,
        base_sha="a" * 40,
        cfg=B.CFG,
        contracts=c,
    )
    assert ev["contracts"] == c and F.evidence_gap(ev) is None
    p = F.build_prompt(ev, rails=F.extract_rails(B.AGENTS_TEXT), cfg=B.CFG, iteration=1, pytest_cmd="py")
    assert "What correct means for this lane" in p and '"min_produced": 1' in p and "scripts/a.py" in p


def test_build_evidence_without_contracts_is_unchanged_shape():
    ev = F.build_evidence({"lane": "x"}, incident={}, receipt=None, registry_row=None, base_sha="", cfg=B.CFG)
    assert ev["contracts"] is None


# ---------------------------------------------------------------- 3. the gate in the cycle


def test_an_empty_incident_is_never_admitted_and_is_escalated_once(sandbox):
    L._set_local(sandbox)
    _empty_incident(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    assert L._main(sandbox, "--apply") == 0
    assert L._state(sandbox)["jobs"] == {} and L._calls(sandbox) == []
    (sk,) = _receipt(sandbox)["skipped"]
    assert sk["why"] == "no_evidence:no_error_text" and sk["deduped"] is False
    (f,) = L._findings(sandbox)
    text = f.read_text()
    assert "(no evidence)" in text and "no_evidence:no_error_text" in text and "buggy-lane" in text
    assert L._main(sandbox, "--apply") == 0  # same day: deduped
    assert _receipt(sandbox)["skipped"][0]["deduped"] is True and len(L._findings(sandbox)) == 1


def test_a_queued_empty_job_is_refused_without_spending_the_budget(sandbox):
    """shf-0644049006-1's case: admitted before the gate, no receipt in the ledger, no registry row."""
    L._set_local(sandbox, max_jobs_per_cycle=1)
    (sandbox["bin"] / "scenario").write_text("fix")
    _queue_job(sandbox)
    _empty_incident(sandbox)  # nothing new is admitted either
    assert L._main(sandbox, "--apply") == 0
    q = L._state(sandbox)["jobs"]["shf-q-1"]
    assert q["state"] == F.FIX_REFUSED and q["reason"] == "no_evidence:no_error_text"
    assert L._calls(sandbox) == []
    (att,) = _receipt(sandbox)["attempted"]
    assert att["outcome"] == "refused:no_evidence:no_error_text" and att["finding"]


def test_the_full_sandbox_incident_still_runs(sandbox):
    """The gate does not refuse a real pack: the stock incident (traceback + scripts/buggy.py) is attempted."""
    L._set_local(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    assert L._main(sandbox, "--apply") == 0
    (job,) = L._state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_READY_LOCAL and L._calls(sandbox)


# ---------------------------------------------------------------- 4. the base is the served release


def _served(sb, tmp_path, sha: str) -> Path:
    p = tmp_path / "CURRENT_GIT_SHA"
    p.write_text(sha + "\n")
    _cfg_update(sb, base_ref=None, served_sha_file=str(p))
    return p


def _local_only_commit(sb) -> str:
    """A commit on the served line that origin/main does not have (a local-only fold under the no-push order)."""
    repo = sb["repo"]
    (repo / "scripts" / "folded.py").write_text("X = 1\n")
    B._sh("git", "-C", str(repo), "add", "-A")
    B._sh("git", "-C", str(repo), "commit", "-qm", "local-only fold")
    return _sh_out("git", "-C", str(repo), "rev-parse", "HEAD")


def test_dry_run_bases_the_fix_on_the_served_sha_not_origin_main(sandbox, tmp_path):
    L._set_local(sandbox)
    origin_main = _sh_out("git", "-C", str(sandbox["repo"]), "rev-parse", "origin/main")
    served = _local_only_commit(sandbox)
    assert served != origin_main
    _served(sandbox, tmp_path, served)
    out = tmp_path / "dry"
    assert L._main(sandbox, "--dry-run", "--out", str(out)) == 0
    rcpt = json.loads((out / "receipt.json").read_text())
    assert rcpt["base_sha"] == served and rcpt["base"]["ref"] == "served" and rcpt["base"]["why"] is None
    ev = json.loads(next(out.rglob("evidence.json")).read_text())
    assert ev["base_sha"] == served and ev["contracts"] is not None


def test_apply_fix_worktree_starts_at_the_served_commit(sandbox, tmp_path):
    L._set_local(sandbox)
    served = _local_only_commit(sandbox)
    _served(sandbox, tmp_path, served)
    (sandbox["bin"] / "scenario").write_text("fix")
    assert L._main(sandbox, "--apply") == 0
    (job,) = L._state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_READY_LOCAL
    head = job["head_sha"]
    assert _sh_out("git", "-C", str(sandbox["repo"]), "rev-parse", f"{head}^") == served


@pytest.mark.parametrize(
    "content,why",
    [
        (None, "served_sha_unreadable:2"),
        ("8de62f79c", "served_sha_not_a_full_sha"),
        ("f" * 40, "served_sha_not_in_repo"),
    ],
)
def test_no_served_base_means_no_attempt_and_no_fallback(sandbox, tmp_path, content, why):
    L._set_local(sandbox)
    (sandbox["bin"] / "scenario").write_text("fix")
    p = _served(sandbox, tmp_path, content or "x")
    if content is None:
        p.unlink()
    assert L._main(sandbox, "--apply") == 0
    rcpt = _receipt(sandbox)
    assert rcpt["base_sha"] == "" and rcpt["base"]["why"] == why
    (att,) = rcpt["attempted"]
    assert att["outcome"] == f"no_base:{why}" and L._calls(sandbox) == []
    (job,) = L._state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_REQUESTED  # stays queued for the next cycle


def test_served_is_the_default_and_reads_the_lifecycle_release_file(sandbox, tmp_path):
    served = _sh_out("git", "-C", str(sandbox["repo"]), "rev-parse", "HEAD")
    cfg = _cfg_update(sandbox, base_ref=None)
    Path(cfg["lifecycle"]["release_current_sha_file"]).write_text(served)
    b = S.resolve_base(sandbox["repo"], cfg, apply=False, environ=sandbox["env"])
    assert b == {"sha": served, "ref": "served", "source": cfg["lifecycle"]["release_current_sha_file"],
                 "fetch_rc": 0, "why": None}


def test_default_served_file_is_home_relative(tmp_path):
    cfg = {"repo": {}, "lifecycle": {}}
    b = S.resolve_base(tmp_path, cfg, apply=False, environ={"HOME": str(tmp_path)})
    assert b["source"] == str(tmp_path / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA")
    assert b["sha"] == "" and b["why"].startswith("served_sha_unreadable")


def test_unknown_base_ref_is_refused(tmp_path):
    b = S.resolve_base(tmp_path, {"repo": {"base_ref": "main"}}, apply=False, environ={})
    assert b["sha"] == "" and b["why"] == "unknown_base_ref:main"

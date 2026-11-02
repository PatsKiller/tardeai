"""Synthetic exact-head merge delegation; no GitHub write, broker or live store.
ANCHOR: PR_MERGE_DELEGATION_20261102
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEAD, MAIN, MERGED = "a" * 40, "b" * 40, "c" * 40
NOW = datetime(2030, 1, 7, 23, 45, tzinfo=timezone.utc)  # Monday 18:45 ET: no Mergify window gate.
ACTOR = "coordinator-synthetic-session"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real process/network is forbidden in merge delegation tests")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    return load("pr_merge_delegation_under_test", "scripts/lib/pr_merge_delegation.py")


def snapshot(mod, *, held=False, reviews=1):
    artifact_rows, artifact_bytes = [], {}
    for index in range(reviews):
        session = f"reviewer-synthetic-{index}"
        raw = json.dumps({"reviewer": session, "head_sha": HEAD, "verdict": "MERGE"}).encode()
        name = f"inbox/codex/review-synthetic-{index}.json"
        artifact_rows.append({"reviewer_session": session, "artifact": name,
                              "artifact_sha256": hashlib.sha256(raw).hexdigest(), "head_sha": HEAD, "verdict": "MERGE"})
        artifact_bytes[name] = raw
    checks_module = load("delegation_real_checks", "scripts/lib/pr_all_checks_green.py")
    checks = checks_module.evaluate_merge_rollup([{"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
                                                for name in ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")])
    return {"authority": {"ok": True, "authority": {"policy_sha": MAIN, "policy_version": "30.0.0",
            "capability": "coordinator_merge", "requirements": {"ordinary_reviews":1,"held_reviews":2},
            "reserved_paths":["synthetic/reserved/*"], "ratification": {"pr": 9000, "reviewed_head": MAIN}}},
            "pr": {"number": 9999, "state": "OPEN", "baseRefName": "main", "isDraft": False,
                   "headRefOid": HEAD, "headRefName": "wt/synthetic-change", "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                   "files": ["scripts/synthetic_change.py"], "changedFiles": 1, "commit_shas": [HEAD]},
            "coordinators": {"schema": "CoordinatorRegistry@v1", "lead": "codex", "coordinators": [
                {"id": "codex", "vendor": "codex", "role": "lead", "territories": ["release"]}]},
            "claims": [{"schema": "AgentClaim@v1", "claim_id": "synthetic-coordinator", "session": ACTOR, "vendor": "codex", "status": "active",
                        "paths": ["persistent-state/data/coordination/coordinator/coordinators.json"]},
                       {"schema": "AgentClaim@v1", "claim_id": "synthetic-source", "session": "author-synthetic", "vendor": "claude", "status": "done",
                        "head_sha": HEAD, "paths": ["scripts/synthetic_change.py"]}],
            "evidence": {"schema": "PrMergeReviewEvidence@v1", "pr": 9999, "head_sha": HEAD,
                         "registered_by": {"actor": "codex", "session": ACTOR},
                         "identity_provenance": "manual_coordinator_claim_and_source_check", "source_commit_shas": [HEAD],
                         "authors": [{"actor": "claude", "session": "author-synthetic", "claim_id": "synthetic-source"}],
                         "reviews": artifact_rows},
            "review_artifacts": artifact_bytes, "registration_sha256": "d" * 64,
            "checks": checks, "checks_head": HEAD, "excluded_globs": ["synthetic/reserved/*"], "held": held,
            "actor_session": ACTOR}


class Fake:
    def __init__(self, data):
        self.data, self.calls, self.events = data, [], []
        self.collect_count = 0
        self.on_collect = None
        self.submitted = True
        self.merge_sha = MERGED

    def collect(self, pr, actor):
        self.collect_count += 1
        self.calls.append("read")
        if self.on_collect:
            self.on_collect(self, self.collect_count)
        return deepcopy(self.data)

    @contextmanager
    def lock(self, pr):
        self.calls.append("lock")
        yield

    def history(self, pr):
        self.calls.append("history")
        return deepcopy(self.events)

    def append(self, pr, event):
        self.calls.append("append:" + event["event"])
        self.events.append(deepcopy(event))

    def merge(self, command):
        assert self.events[-1]["event"] == "approved"
        self.calls.append(("merge", command))
        return self.submitted

    def merged(self, pr, head):
        self.calls.append("readback")
        return self.merge_sha


def test_real_strict_check_consumer_and_readonly_plan(mod):
    fake = Fake(snapshot(mod))
    result = mod.run(9999, ACTOR, adapter=fake, clock=lambda: NOW)
    assert result["ok"] and result["dry_run"] and result["would_write"]
    assert fake.calls == ["read"] and not fake.events
    assert result["would_merge"] == ["gh", "pr", "merge", "9999", "--repo", "PatsKiller/tardeai", "--squash", "--match-head-commit", HEAD]
    assert "manual" in result["identity_limit"].lower()


def test_dryrun_tripwire_no_directory_lock_append_or_merge(mod, monkeypatch, tmp_path):
    fake = Fake(snapshot(mod))
    def forbidden(*args, **kwargs):raise AssertionError("Dry run reached a mutation")
    fake.lock = fake.append = fake.merge = forbidden
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    assert mod.run(9999, ACTOR, adapter=fake, clock=lambda: NOW)["ok"]
    fake.data["pr"]["isDraft"] = True
    assert not mod.run(9999, ACTOR, adapter=fake, clock=lambda: NOW)["ok"]
    assert not list(tmp_path.iterdir())


def test_approval_durable_order_exact_command_and_merge_only(mod):
    fake = Fake(snapshot(mod))
    result = mod.run(9999, ACTOR, apply=True, adapter=fake, clock=lambda: NOW)
    assert result == {"ok": True, "reason": "merged_not_deployed", "head_sha": HEAD, "merge_sha": MERGED, "dry_run": False}
    assert [e["event"] for e in fake.events] == ["approved", "merged"]
    assert fake.calls.index("append:approved") < next(i for i,c in enumerate(fake.calls) if isinstance(c,tuple))
    assert fake.events[0]["source"] == "ratified_policy_coordinator_delegation"
    assert "telegram" not in json.dumps(fake.events).lower() and "operator-merge" not in json.dumps(fake.events)
    command = next(c[1] for c in fake.calls if isinstance(c,tuple))
    assert "--match-head-commit" in command and all(x not in command for x in ("--admin", "--rebase", "--delete-branch", "--auto"))


@pytest.mark.parametrize("held,count,expected", [(False,1,True),(True,1,False),(True,2,True)])
def test_review_count_tracks_held_class(mod,held,count,expected):
    assert mod.evaluate(snapshot(mod,held=held,reviews=count),now=NOW)["ok"] is expected


@pytest.mark.parametrize("case", ["proposed","revoked","role","actor","claim","head","draft","base","checks","check_head","files","registration","provenance","source_commits","source_release","live_holder","review_hash","review_head","review_verdict","self_review","merger_review","duplicate_review","raw_review","reserved","operator_path","decision_path"])
def test_missing_stale_ambiguous_evidence_refuses(mod,case):
    data = snapshot(mod,held=True,reviews=2)
    if case in {"proposed","revoked"}:data["authority"]={"ok":False,"reason":case,"authority":None}
    elif case=="role":data["coordinators"]["coordinators"][0]["territories"]=[]
    elif case=="actor":data["actor_session"]="unknown-actor"
    elif case=="claim":data["claims"][0]["status"]="done"
    elif case=="head":data["pr"]["headRefOid"]="short"
    elif case=="draft":data["pr"]["isDraft"]=True
    elif case=="base":data["pr"]["baseRefName"]="other"
    elif case=="checks":data["checks"]["ok"]=False
    elif case=="check_head":data["checks_head"]=MAIN
    elif case=="files":data["pr"]["changedFiles"]=2
    elif case=="registration":data["evidence"]["head_sha"]=MAIN
    elif case=="provenance":data["evidence"]["identity_provenance"]="GitHub shared login"
    elif case=="source_commits":data["evidence"]["source_commit_shas"]=[]
    elif case=="source_release":data["claims"][1]["status"]="active"
    elif case=="live_holder":data["claims"].append({"status":"active","session":"other-holder","paths":["scripts/synthetic_change.py"]})
    elif case=="review_hash":data["evidence"]["reviews"][0]["artifact_sha256"]="e"*64
    elif case=="review_head":data["evidence"]["reviews"][0]["head_sha"]=MAIN
    elif case=="review_verdict":data["evidence"]["reviews"][0]["verdict"]="BLOCK"
    elif case=="self_review":data["evidence"]["reviews"][0]["reviewer_session"]="author-synthetic"
    elif case=="merger_review":data["evidence"]["reviews"][0]["reviewer_session"]=ACTOR
    elif case=="duplicate_review":data["evidence"]["reviews"][1]=deepcopy(data["evidence"]["reviews"][0])
    elif case=="raw_review":data["review_artifacts"][data["evidence"]["reviews"][0]["artifact"]]=b"{}"
    elif case=="reserved":data["pr"]["files"]=["config/agent_standing_authority.json"]
    elif case=="operator_path":data["pr"]["files"]=["scripts/brokers/synthetic.py"]
    elif case=="decision_path":data["pr"]["files"]=["config/lane_registry.json"]
    fake=Fake(data);result=mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)
    assert not result["ok"] and not fake.events and not any(isinstance(c,tuple) for c in fake.calls)


@pytest.mark.parametrize("value", [None,[],{},"",True,7])
def test_malformed_snapshots_are_structured_refusals(mod,value):
    data=snapshot(mod);data["evidence"]["reviews"]=value
    assert not mod.evaluate(data,now=NOW)["ok"]


@pytest.mark.parametrize("hour,minute,weekday,blocked", [(14,30,7,True),(21,14,7,True),(21,15,7,False),(23,45,7,False),(5,0,6,False)])
def test_only_weekday_market_operating_freeze_not_mergify_window(mod,hour,minute,weekday,blocked):
    now=datetime(2030,1,weekday,hour,minute,tzinfo=timezone.utc)
    assert mod.freeze(now) is blocked
    assert mod.evaluate(snapshot(mod),now=now)["ok"] is not blocked


@pytest.mark.parametrize("when", [2,3])
def test_head_or_revocation_change_before_write_never_merges(mod,when):
    fake=Fake(snapshot(mod))
    def change(driver,count):
        if count==when:driver.data["authority"]={"ok":False,"reason":"revoked","authority":None}
    fake.on_collect=change
    result=mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)
    assert not result["ok"] and result["reason"]=="critical_evidence_changed"
    assert not any(isinstance(c,tuple) for c in fake.calls)
    assert [e["event"] for e in fake.events] == ([] if when==2 else ["approved","refused_changed"])


def test_failure_of_approval_receipt_prevents_actual_merge(mod):
    fake=Fake(snapshot(mod))
    def broken(*args):raise OSError("synthetic storage error")
    fake.append=broken
    with pytest.raises(OSError):mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)
    assert not any(isinstance(c,tuple) for c in fake.calls)


def test_uncertain_transport_never_blindly_retries(mod):
    fake=Fake(snapshot(mod));fake.submitted=False;fake.merge_sha=None
    first=mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)
    assert first["reason"]=="merge_uncertain_do_not_retry"
    before=sum(isinstance(c,tuple) for c in fake.calls)
    second=mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)
    assert second["reason"]=="previous_attempt_requires_reconciliation"
    assert sum(isinstance(c,tuple) for c in fake.calls)==before


def test_idempotent_confirmed_merge_does_not_write_again(mod):
    fake=Fake(snapshot(mod))
    assert mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)["ok"]
    before=deepcopy(fake.events);writes=sum(isinstance(c,tuple) for c in fake.calls)
    fake.data["pr"]["state"]="MERGED"
    result=mod.run(9999,ACTOR,apply=True,adapter=fake,clock=lambda:NOW)
    assert result["reason"]=="already_merged" and fake.events==before
    assert sum(isinstance(c,tuple) for c in fake.calls)==writes


def test_raw_full_head_line_supported_but_short_and_ambiguous_refused(mod):
    raw=f"Adversarial-review: MERGE reviewer=synthetic-reviewer head={HEAD}".encode()
    assert mod.reviewer_artifact(raw)["head_sha"]==HEAD
    for bad in [raw+ b"\n"+raw, raw.replace(HEAD.encode(),b"aaaaaaa"),b"Adversarial-review: MERGE"]:
        with pytest.raises(mod.Refused):mod.reviewer_artifact(bad)


def test_real_authority_proposed_policy_is_inert(mod):
    helper=load("delegation_real_authority",".cursor/hooks/guard_standing_policy.py")
    result=helper.authorize("Policy-Version:30.0.0\nStatus:PROPOSED\n",{},capability="coordinator_merge",policy_sha=MAIN,revoked=False)
    assert result["ok"] is False and result["authority"] is None
    data=snapshot(mod);data["authority"]=result
    assert not mod.evaluate(data,now=NOW)["ok"]


@pytest.mark.parametrize("kind",["symlink","hardlink"])
def test_real_ledger_helpers_reject_aliases_without_modifying_target(mod,tmp_path,kind):
    host=mod.Host();host.state=tmp_path
    (tmp_path/"coordinator").mkdir()
    target=tmp_path/"unrelated.jsonl";target.write_bytes(b"synthetic unrelated evidence\n")
    directory=tmp_path/"coordinator/merge-delegation";directory.mkdir()
    linked=directory/"9999.jsonl"
    if kind=="symlink":linked.symlink_to(target)
    else:os.link(target,linked)
    before=target.read_bytes(),target.stat().st_mtime_ns
    with host.lock(9999):
        with pytest.raises(mod.Refused):host.history(9999)
        with pytest.raises((mod.Refused,OSError)):host.append(9999,{"schema":mod.SCHEMA})
    assert (target.read_bytes(),target.stat().st_mtime_ns)==before


def test_coauthor_cannot_supply_independent_review(mod):
    data=snapshot(mod)
    data["claims"].append({"schema":"AgentClaim@v1","claim_id":"synthetic-coauthor","session":"reviewer-synthetic-0","status":"done","head_sha":HEAD,"paths":["scripts/synthetic_change.py"]})
    data["evidence"]["authors"].append({"actor":"codex","session":"reviewer-synthetic-0","claim_id":"synthetic-coauthor"})
    assert mod.evaluate(data,now=NOW)["reason"]=="reviewer_not_independent"


def test_ambiguous_raw_identity_fields_and_duplicate_authors_refuse(mod):
    raw=json.dumps({"reviewer":"first-reviewer","reviewer_session":"second-reviewer","head_sha":HEAD,"verdict":"MERGE"}).encode()
    with pytest.raises(mod.Refused):mod.reviewer_artifact(raw)
    raw=json.dumps({"reviewer":"first-reviewer","head_sha":HEAD,"source_commit":[],"verdict":"MERGE"}).encode()
    with pytest.raises(mod.Refused):mod.reviewer_artifact(raw)
    data=snapshot(mod);data["evidence"]["authors"].append(deepcopy(data["evidence"]["authors"][0]))
    assert mod.evaluate(data,now=NOW)["reason"]=="author_identity_duplicate"


def test_real_ledger_writes_approval_before_fake_merge_and_serializes(mod,tmp_path):
    import threading,time
    host=mod.Host();host.state=tmp_path;(tmp_path/"coordinator").mkdir()
    data=snapshot(mod);driver=Fake(data)
    driver.lock=host.lock;driver.history=host.history;driver.append=host.append
    observed=[]
    def fake_merge(command):
        rows=[json.loads(row) for row in host.ledger_path(9999).read_bytes().splitlines()]
        assert rows[-1]["event"]=="approved" and rows[-1]["head_sha"]==HEAD
        observed.append(command);return True
    driver.merge=fake_merge
    assert mod.run(9999,ACTOR,apply=True,adapter=driver,clock=lambda:NOW)["reason"]=="merged_not_deployed"
    rows=host.history(9999);assert [r["event"] for r in rows]==["approved","merged"] and len(observed)==1
    entered=[];active=[0];peak=[0];gate=threading.Lock()
    def claim():
        with host.lock(1234):
            with gate:active[0]+=1;peak[0]=max(peak[0],active[0])
            time.sleep(.02);entered.append(True)
            with gate:active[0]-=1
    threads=[threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=5)
    assert len(entered)==2 and peak[0]==1


def test_cli_default_is_actual_readonly_plan_and_apply_is_explicit(mod,monkeypatch,capsys):
    fake=Fake(snapshot(mod));original=mod.run
    monkeypatch.setattr(mod,"run",lambda pr,actor_session,**kw:original(pr,actor_session,adapter=fake,clock=lambda:NOW,**kw))
    assert mod.main(["--pr","9999","--actor-session",ACTOR])==0
    report=json.loads(capsys.readouterr().out);assert report["dry_run"] is True and not fake.events
    assert mod.main(["--pr","9999","--actor-session",ACTOR,"--apply"])==0
    report=json.loads(capsys.readouterr().out);assert report["reason"]=="merged_not_deployed"


def test_cli_has_no_authority_overrides_and_rejects_apply_with_dryrun(mod):
    for extra in [["--apply","--dry-run"],["--admin"],["--policy","forged"],["--urgent"],["--repo","other/repo"]]:
        with pytest.raises(SystemExit):mod.main(["--pr","9999","--actor-session",ACTOR,*extra])


def test_untrusted_helper_file_is_refused_before_execution(mod,tmp_path):
    host=mod.Host();host.repo=tmp_path
    p=tmp_path/"helper.py";p.write_bytes(b"raise AssertionError('synthetic untrusted helper must not execute')\n")
    host.git=lambda *args:"AUTHORIZED_MAIN_BLOB_DIFFERENT"
    with pytest.raises(mod.Refused,match="trusted_helper_dirty_or_not_main"):
        host.helper("helper.py",MAIN)


def test_native_merge_timeout_is_uncertain_without_raw_error_echo(mod,monkeypatch):
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired("synthetic",1,stderr="PRIVATE_SYNTHETIC_TEXT")
    monkeypatch.setattr(mod.subprocess,"run",timeout)
    assert mod.Host().merge(["gh","pr","merge","9999"]) is False


@pytest.mark.parametrize("prior",["AGENTS.md","config/agent_standing_authority.json","scripts/brokers/synthetic.py",".env.private"])
def test_renaming_reserved_source_to_ordinary_path_never_bypasses_boundary(mod,prior):
    data=snapshot(mod);data["pr"]["prior_paths"]=[prior]
    assert mod.evaluate(data,now=NOW)["reason"]=="operator_only_or_delegation_definition_path"


def test_active_holder_of_old_renamed_path_still_blocks(mod):
    data=snapshot(mod);data["pr"]["prior_paths"]=["scripts/old_synthetic.py"]
    data["claims"].append({"status":"active","session":"other-source-holder","paths":["scripts/old_synthetic.py"]})
    assert mod.evaluate(data,now=NOW)["reason"]=="current_source_holder_not_released"


def test_requested_pr_identity_cannot_drift_to_another_merge(mod):
    driver=Fake(snapshot(mod));driver.data["pr"]["number"]=8888
    result=mod.run(9999,ACTOR,apply=True,adapter=driver,clock=lambda:NOW)
    assert result["reason"]=="requested_pr_identity_mismatch" and not driver.events
    assert not any(isinstance(call,tuple) for call in driver.calls)


@pytest.mark.parametrize("case",["territory_string","duplicate_id","observer"])
def test_registry_role_ambiguity_never_grants_merge(mod,case):
    data=snapshot(mod);lead=data["coordinators"]["coordinators"][0]
    if case=="territory_string":lead["territories"]="release"
    elif case=="duplicate_id":data["coordinators"]["coordinators"].append({**lead,"role":"observer"})
    else:lead["role"]="observer"
    assert mod.evaluate(data,now=NOW)["reason"]=="current_release_lead_missing"

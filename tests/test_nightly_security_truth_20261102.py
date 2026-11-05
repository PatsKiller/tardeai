"""Synthetic nightly scan output/delivery and owned tiny-child timeout regressions.
ANCHOR: NIGHTLY_SECURITY_TRUTH_20261102
No real scanner, network, notification, unit, credential or broker operation.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

ROOT=Path(__file__).resolve().parents[1]
GOOD=json.dumps({"results":[{"check_id":"synthetic.rule","path":"synthetic.py","start":{"line":1},"extra":{"severity":"ERROR","message":"Synthetic finding"}}]})
CONFIG={"alert_priority":"P1","timeout_s":2,"tools":{"semgrep":{"argv":["synthetic-semgrep","scan","."],"enabled":True}}}


@pytest.fixture
def mod(monkeypatch):
    spec=importlib.util.spec_from_file_location("nightly_security_truth_under_test",ROOT/"scripts/nightly_security_scan.py")
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    def forbidden(*args,**kwargs):raise AssertionError("No network in scanner tests")
    monkeypatch.setattr(socket.socket,"connect",forbidden)
    return module


def runner(output=GOOD,rc=0):
    return lambda argv,cwd:(0,"synthetic 1.0","") if argv[1:]==["--version"] else (rc,output,"")


@pytest.mark.parametrize("output",["not-json","<html>unavailable</html>","null","[]","{}",'{"results":{}}','{"results":[],"errors":[{"type":"synthetic"}]}'])
def test_nonjson_or_invalid_semgrep_shape_is_unusable(mod,tmp_path,output):
    result=mod.run_scan(CONFIG,runner=runner(output),state_dir=tmp_path,dry_run=True)
    assert result["tools"]["semgrep"]["status"]=="error" and result["unusable"]==["semgrep"]
    assert not result["findings"] and not list(tmp_path.iterdir())


@pytest.mark.parametrize("tool,bad",[("pip-audit","not-json"),("pip-audit",'{}'),("pip-audit",'{"dependencies":{}}'),("npm-audit","not-json"),("npm-audit",'{}'),("npm-audit",'{"vulnerabilities":[]}')])
def test_other_tool_invalid_json_contracts_are_unusable(mod,tmp_path,tool,bad):
    cfg={**CONFIG,"tools":{tool:{"argv":[tool]}}}
    result=mod.run_scan(cfg,runner=runner(bad),state_dir=tmp_path,dry_run=True)
    assert result["tools"][tool]["status"]=="error" and result["unusable"]==[tool]


def test_invalid_output_alert_names_the_contract_failure_not_a_crash(mod,tmp_path):
    """The operator line must say the payload was invalid, not report a crash at rc=0."""
    sent=[]
    result=mod.run_scan(CONFIG,runner=runner("not-json"),state_dir=tmp_path,dry_run=False,
                        send=lambda text,priority="P1":(sent.append(text) or {"accepted":True,"delivered":True}))
    assert result["unusable"]==["semgrep"] and sent
    assert "NOT USABLE" in sent[0] and "output_invalid" in sent[0] and "JSONDecodeError" in sent[0]
    assert "CRASHED" not in sent[0]


@pytest.mark.parametrize("outcome",[False,None,True,{"accepted":True,"delivered":False}])
def test_unconfirmed_delivery_keeps_retry_until_actual_delivery(mod,tmp_path,outcome):
    first=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,send=lambda *a,**kw:outcome)
    assert first["alerted"] is False and first["pending_alert_ids"]
    calls=[]
    second=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,send=lambda *a,**kw:calls.append(a[0]) or {"accepted":True,"delivered":True})
    assert second["new"]==[] and second["retry"] and len(calls)==1
    assert second["alerted"] is True and second["pending_alert_ids"]==[]
    third=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,send=lambda *a,**kw:pytest.fail("Confirmed finding must dedupe"))
    assert third["new"]==[] and third["retry"]==[]


def test_sender_exception_retains_receipt_without_private_error_text(mod,tmp_path):
    def fail(*args,**kwargs):raise RuntimeError("PRIVATE_SYNTHETIC_FAILURE_TEXT")
    result=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,send=fail)
    assert result["notification"]["error_type"]=="RuntimeError" and result["pending_alert_ids"]
    assert "PRIVATE_SYNTHETIC" not in (tmp_path/"last.json").read_text()


def test_bad_output_preserves_previous_valid_findings_and_delivery_state(mod,tmp_path):
    first=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,send=lambda *a,**kw:{"delivered":True,"accepted":True})
    second=mod.run_scan(CONFIG,runner=runner("not-json"),state_dir=tmp_path,dry_run=False,send=lambda *a,**kw:{"delivered":True})
    assert second["unusable"]==["semgrep"]
    assert [f["id"] for f in second["findings"] if f.get("carried")]==first["new"]
    third=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=True)
    assert third["new"]==[] and third["pending_alert_ids"]==[]


def test_dryrun_cannot_reach_receipt_or_sender_and_changes_with_input(mod,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError("Dry run reached mutation")
    monkeypatch.setattr(Path,"mkdir",forbidden);monkeypatch.setattr(Path,"write_text",forbidden)
    first=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=True,send=forbidden)
    changed=mod.run_scan(CONFIG,runner=runner('{"results":[]}'),state_dir=tmp_path,dry_run=True,send=forbidden)
    assert first["new"] and changed["new"]==[] and not list(tmp_path.iterdir())


@pytest.mark.parametrize("value",[0,-1,True,"forever",float("nan"),float("inf")])
def test_invalid_timeout_refuses_before_any_runner(mod,tmp_path,value):
    with pytest.raises(ValueError):
        mod.run_scan({**CONFIG,"timeout_s":value},runner=lambda *a:pytest.fail("Invalid timeout reached runner"),state_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_production_runner_uses_configured_timeout_for_scan_and_bounded_version(mod,tmp_path,monkeypatch):
    values=[]
    def bounded(argv,cwd,*,timeout_s):values.append((argv,timeout_s));return runner()(argv,cwd)
    monkeypatch.setattr(mod,"_default_runner",bounded)
    result=mod.run_scan({**CONFIG,"timeout_s":25},state_dir=tmp_path,dry_run=True)
    assert not result["unusable"] and values[0][1]==25
    assert values[1][0][-1]=="--version" and 0<values[1][1]<=10


def test_owned_tiny_process_tree_timeout_is_bounded(mod,tmp_path):
    # Only an owned synthetic Python child and its descendant; no real tool/network.
    code="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);time.sleep(30)"
    start=time.monotonic()
    rc,out,err=mod._default_runner([sys.executable,"-c",code],tmp_path,timeout_s=.2)
    elapsed=time.monotonic()-start
    assert rc==124 and "timeout" in err.lower() and elapsed<3


def test_normal_owned_child_output_exit_is_preserved(mod,tmp_path):
    rc,out,err=mod._default_runner([sys.executable,"-c","import sys;print('synthetic-output');sys.exit(1)"],tmp_path,timeout_s=2)
    assert rc==1 and out.strip()=="synthetic-output" and err==""


def test_findings_outside_existing_message_cap_remain_pending(mod,tmp_path):
    findings={"results":[{"check_id":f"synthetic.rule.{i}","path":"synthetic.py","start":{"line":i+1},"extra":{"message":"Synthetic finding","severity":"ERROR"}} for i in range(17)]}
    delivered=lambda *args,**kwargs:{"accepted":True,"delivered":True}
    first=mod.run_scan(CONFIG,runner=runner(json.dumps(findings)),state_dir=tmp_path,dry_run=False,send=delivered)
    assert len(first["new"])==17 and len(first["pending_alert_ids"])==2
    second=mod.run_scan(CONFIG,runner=runner(json.dumps(findings)),state_dir=tmp_path,dry_run=False,send=delivered)
    assert second["new"]==[] and len(second["retry"])==2 and second["pending_alert_ids"]==[]


def test_a_corrupt_carried_finding_does_not_crash_the_malformed_night(mod,tmp_path):
    """B1 (cc2/cc6): a legacy receipt row with no id must be ignored, not raise KeyError before any receipt."""
    (tmp_path/"last.json").write_text(json.dumps({"findings":[{"tool":"semgrep"}],"alerted":True}))
    result=mod.run_scan(CONFIG,runner=runner("not-json"),state_dir=tmp_path,dry_run=False,
                        send=lambda *args,**kwargs:{"accepted":True,"delivered":True})
    assert result["unusable"]==["semgrep"] and result["pending_alert_ids"]==[]
    # The id-less row is IGNORED, not carried forward: an entry that cannot be identified can never be settled.
    assert result["findings"]==[]
    assert json.loads((tmp_path/"last.json").read_text())["unusable"]==["semgrep"]


def test_a_partial_delivery_keeps_the_pending_ids(mod,tmp_path):
    """B2 (cc2/cc6): delivered=true WITH partial_failure=true is not full delivery; ids must be retried."""
    first=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,
                       send=lambda *args,**kwargs:{"delivered":True,"accepted":True,"partial_failure":True})
    assert first["alerted"] is False and first["notification"]["status"]=="partial_failure"
    assert first["pending_alert_ids"]
    calls=[]
    second=mod.run_scan(CONFIG,runner=runner(),state_dir=tmp_path,dry_run=False,
                        send=lambda *args,**kwargs:(calls.append(args[0]) or {"accepted":True,"delivered":True}))
    assert second["alerted"] is True and second["pending_alert_ids"]==[] and calls


def test_semgrep_results_survive_per_file_errors(mod):
    """B3 (cc2/cc6): one unparseable file must not discard the findings a valid scan did return."""
    doc={"results":[{"check_id":"synthetic.rule","path":"synthetic.py","start":{"line":1},
                     "extra":{"severity":"ERROR","message":"Synthetic finding"}}],
         "errors":[{"type":"Syntax error","path":"unparseable.py"}]}
    findings=mod.parse_semgrep(json.dumps(doc))
    assert len(findings)==1 and findings[0]["id"].startswith("semgrep:synthetic.rule")
    with pytest.raises(ValueError):
        mod.parse_semgrep(json.dumps({"results":[],"errors":[{"type":"synthetic"}]}))


def test_a_valid_semgrep_run_with_one_file_error_reports_its_findings(mod,tmp_path):
    out=json.dumps({"results":[{"check_id":"synthetic.rule","path":"synthetic.py","start":{"line":1},
                                "extra":{"severity":"ERROR","message":"Synthetic finding"}}],
                    "errors":[{"type":"Syntax error","path":"unparseable.py"}]})
    result=mod.run_scan(CONFIG,runner=runner(out),state_dir=tmp_path,dry_run=True)
    assert result["tools"]["semgrep"]["status"]=="ran" and len(result["findings"])==1


@pytest.mark.parametrize("delivered,expected_exit",[(False,1),(True,0)])
def test_actual_cli_uses_structured_outcome_and_pending_exit(mod,tmp_path,monkeypatch,capsys,delivered,expected_exit):
    from types import ModuleType
    fake=ModuleType("telegram_alert")
    fake.send_telegram_outcome=lambda *args,**kwargs:{"accepted":delivered,"delivered":delivered}
    monkeypatch.setitem(sys.modules,"telegram_alert",fake)
    monkeypatch.setattr(mod,"_default_runner",lambda argv,cwd,**kw:runner()(argv,cwd))
    config=tmp_path/"config.json";config.write_text(json.dumps(CONFIG))
    monkeypatch.setenv("TRADEAI_STATE_ROOT",str(tmp_path/"state"))
    result=mod.main(["--apply","--config",str(config),"--json"])
    receipt=json.loads(capsys.readouterr().out)
    assert result==expected_exit and receipt["alerted"] is delivered
    assert bool(receipt["pending_alert_ids"]) is (not delivered)


def test_exited_parent_with_descendant_holding_pipe_still_times_out(mod,tmp_path):
    code="import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print('synthetic parent exited')"
    start=time.monotonic()
    rc,out,err=mod._default_runner([sys.executable,"-c",code],tmp_path,timeout_s=.2)
    assert rc==124 and "timeout" in err.lower() and time.monotonic()-start<3

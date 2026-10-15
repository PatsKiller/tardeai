"""The n8n cutover factory (scripts/n8n_cutover_wave.py), 2026-10-15. Hermetic: a scratch code root, a fake crontab
command; nothing reads the host crontab, a secret, the ledger or the network."""

from __future__ import annotations

import csv
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import n8n_cutover_wave as W  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

LINE = ("0 10 * * 1-5 cd $PROJ && flock -n /tmp/demo.lock $PY scripts/demo_lane.py --apply --max 5 "
        ">> logs/demo.log 2>&1  # lane demo")
CRONTAB = "\n".join(["SHELL=/bin/bash", "PROJ=/x", LINE,
                     "5 * * * * cd $PROJ && $PY scripts/nolock_lane.py --apply >> logs/n.log 2>&1",
                     "*/5 * * * * cd $PROJ && flock -n /tmp/s.lock $PY scripts/sender_lane.py --send >> l 2>&1",
                     ""])


def _row(lane: str, match: str, *, klass: str = "report", stage: str = "shadow", cron: str = "0 10 * * 1-5"):
    return {"lane_id": lane, "owner": "platform", "state": "ACTIVE",
            "scheduler": {"kind": "cron", "expression": cron, "match": match, "stage": stage, "wave": "W4"},
            "output_signal": {"kind": "json_key", "path": f"data/runtime/{lane}_last.json", "key": "ok_at"},
            "dispatch": {"mode": "dry_run", "cron": [cron], "tz": "America/New_York", "wave": "W4", "class": klass,
                         "priority": 5, "retry_policy": "none"}}


def _entry(lane: str, script: str, lock: str):
    return {"lane_id": lane, "command": ["$PY", script], "lock": lock, "lock_kind": "flock", "timeout_s": 300,
            "dry_run_arg": ["--dry-run"], "live_arg": None, "market_gate": False,
            "output_signal": f"data/runtime/{lane}_last.json", "env_names": ["TRADEAI_STATE_ROOT"],
            "env_allowlist_mode": "report", "env_report_reason": "test", "source": "test"}


def _contract(lane: str, script: str, lock: str, status: str = "REVIEWED"):
    return {"schema": "N8nHealthContract@v1", "id": lane, "kind": "lane", "workflow_id": "tradeai-dispatcher",
            "status": status, "stage": "shadow", "purpose": {"text": "demo"}, "owner": "platform",
            "connects_to": [{"name": f"$PY {script}", "kind": "runner"}, {"name": lock, "kind": "lock"},
                            {"name": f"data/runtime/{lane}_last.json", "kind": "receipt"}],
            "healthy": [{"check": "shadow_dry_run_done", "text": "x"}], "degraded": [{"check": "late", "text": "x"}],
            "failed": [{"check": "run_failed", "text": "x"}], "review": {"prepared_by": "t"}}


@pytest.fixture()
def code_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / W.DISPOSITION_CSV).parent.mkdir(parents=True)
    rows = [
        {"row_id": "cron:L3", "source": "crontab", "lane_id": "demo-lane", "family_id": "F50",
         "disposition": "MIGRATE_N8N"},
        {"row_id": "cron:L4", "source": "crontab", "lane_id": "nolock-lane", "family_id": "F50",
         "disposition": "MIGRATE_N8N"},
        {"row_id": "cron:L5", "source": "crontab", "lane_id": "sender-lane", "family_id": "F10",
         "disposition": "STAY_HOST"},
        {"row_id": "cron:L9", "source": "crontab", "lane_id": "daemon-lane", "family_id": "F07",
         "disposition": "STAY_HOST"},
        {"row_id": "sd:x", "source": "registry_systemd", "lane_id": "unit-lane", "family_id": "F36",
         "disposition": "MIGRATE_N8N"},
        {"row_id": "cron:L7", "source": "crontab", "lane_id": "cons-lane", "family_id": "F15",
         "disposition": "CONSOLIDATE"},
    ]
    with open(tmp_path / W.DISPOSITION_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    reg = {"schema": "x", "lanes": [_row("demo-lane", "scripts/demo_lane.py"),
                                    _row("nolock-lane", "scripts/nolock_lane.py", cron="5 * * * *"),
                                    _row("sender-lane", "scripts/sender_lane.py", cron="*/5 * * * *")]}
    al = {"schema": "x", "lanes": [_entry("demo-lane", "scripts/demo_lane.py", "/tmp/demo.lock"),
                                   _entry("nolock-lane", "scripts/nolock_lane.py", "/tmp/nolock.lock"),
                                   _entry("sender-lane", "scripts/sender_lane.py", "/tmp/s.lock")]}
    contracts = {"schema": "x", "contracts": [_contract("demo-lane", "scripts/demo_lane.py", "/tmp/demo.lock"),
                                              _contract("nolock-lane", "scripts/nolock_lane.py", "/tmp/nolock.lock"),
                                              _contract("sender-lane", "scripts/sender_lane.py", "/tmp/s.lock")]}
    fx = {"schema": "N8nEffectKeys@v1", "lanes": {}}
    for rel, doc in ((W.REGISTRY, reg), (W.ALLOWLIST, al), (W.CONTRACTS, contracts), (W.EFFECT_KEYS, fx)):
        (tmp_path / rel).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return tmp_path


def _plan(code_root: Path, lanes=None, **kw):
    return {v["lane_id"]: v for v in W.build_plan(code_root, CRONTAB, lanes, "CWT", **kw)["lanes"]}


def test_scope_excludes_f07_systemd_and_consolidate(code_root):
    ids = {r["lane_id"] for r in W.scope_rows(W.load_disposition(code_root))}
    assert ids == {"demo-lane", "nolock-lane", "sender-lane"}


def test_parse_lane_argv_takes_cron_args_after_command():
    p = W.parse_lane_argv(W.command_of(LINE), ["$PY", "scripts/demo_lane.py", "--apply"])
    assert p["problems"] == [] and p["live_arg"] == ["--max", "5"]
    p = W.parse_lane_argv("cd $PROJ && FOO=1 $PY scripts/demo_lane.py >> l 2>&1", ["$PY", "scripts/demo_lane.py"])
    assert "unmapped_wrapper:env:FOO" in p["problems"]
    p = W.parse_lane_argv("cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/demo_lane.py", ["$PY", "scripts/demo_lane.py"])
    assert p["market_gate"] is True and p["problems"] == []
    p = W.parse_lane_argv("cd $PROJ && $PY scripts/demo_lane.py --x", ["$PY", "scripts/demo_lane.py", "--y"])
    assert p["live_arg"] is None and p["problems"][0].startswith("allowlist_command_args_not_on_cron_line")


def test_plan_verdicts(code_root):
    v = _plan(code_root)
    assert v["demo-lane"]["status"] == "READY_CANARY", v["demo-lane"]["reasons"]
    assert v["demo-lane"]["live_arg"] == ["--apply", "--max", "5"] and v["demo-lane"]["lock"] == "/tmp/demo.lock"
    assert v["nolock-lane"]["status"] == "SKIP"
    assert any(r.startswith("no_cron_flock") for r in v["nolock-lane"]["reasons"])
    assert v["sender-lane"]["tier"] == W.TIER_SEND
    v2 = _plan(code_root, max_tier=W.TIER_APPEND)
    assert any("max tier" in r for r in v2["sender-lane"]["reasons"])
    assert _plan(code_root, ["daemon-lane"])["daemon-lane"]["reasons"] == ["not_in_directive_scope (disposition csv)"]


def test_draft_contract_needs_review_flag(code_root):
    p = code_root / W.CONTRACTS
    doc = json.loads(p.read_text())
    doc["contracts"][0]["status"] = "DRAFT"
    p.write_text(json.dumps(doc))
    assert _plan(code_root, ["demo-lane"])["demo-lane"]["status"] == "SKIP"
    v = _plan(code_root, ["demo-lane"], review_drafts=True)["demo-lane"]
    assert v["status"] == "READY_CANARY" and v["contract_agent_reviewed"] is True
    assert v["changes"]["contract"]["status"] == "REVIEWED" and v["changes"]["contract"]["stage"] == "canary"
    assert v["changes"]["contract"]["healthy"][0]["check"] == "canary_live_done"
    doc["contracts"][0]["purpose"] = {"text": "UNKNOWN — needs owner"}
    p.write_text(json.dumps(doc))
    v = _plan(code_root, ["demo-lane"], review_drafts=True)["demo-lane"]
    assert v["status"] == "SKIP" and any("UNKNOWN" in r for r in v["reasons"])


def test_apply_writes_canary_shape_that_the_gate_admits(code_root):
    plan = W.build_plan(code_root, CRONTAB, ["demo-lane"], "CWT")
    assert W.apply_plan(code_root, plan) == ["demo-lane"]
    row = json.loads((code_root / W.REGISTRY).read_text())["lanes"][0]
    ent = json.loads((code_root / W.ALLOWLIST).read_text())["lanes"][0]
    assert row["scheduler"]["stage"] == "canary" and row["dispatch"]["mode"] == "live"
    assert row["scheduler"]["command_text"].startswith("cd $PROJ && flock -n /tmp/demo.lock")
    assert ent["live_arg"] == ["--apply", "--max", "5"] and ent["lock"] == "/tmp/demo.lock"
    assert LD.r1_canary_lock_matches(row, ent) == (True, "canary_on_cron")
    assert LD.dispatch_eligible(row)[0]
    c = json.loads((code_root / W.CONTRACTS).read_text())["contracts"][0]
    assert c["stage"] == "shadow"   # operator-REVIEWED contract: kept byte for byte (re-review is the operator's)


def test_appender_gets_armed_effect_key(code_root):
    p = code_root / W.REGISTRY
    doc = json.loads(p.read_text())
    doc["lanes"][0]["dispatch"]["class"] = "pipeline"
    p.write_text(json.dumps(doc))
    plan = W.build_plan(code_root, CRONTAB, ["demo-lane"], "CWT")
    W.apply_plan(code_root, plan)
    fx = json.loads((code_root / W.EFFECT_KEYS).read_text())["lanes"]["demo-lane"]
    assert fx["n8n_claim"] is True and fx["cron_claim"] is True and fx["process"] == "demo-lane"
    from scripts.lib.effect_claim import load_effect_config
    assert "demo-lane" in load_effect_config(code_root / W.EFFECT_KEYS)


def test_cutover_rows_dispatcher_shape(code_root):
    W.apply_plan(code_root, W.build_plan(code_root, CRONTAB, ["demo-lane"], "CWT"))
    assert W.cutover_rows(code_root, ["demo-lane"], "CWT") == ["demo-lane"]
    row = json.loads((code_root / W.REGISTRY).read_text())["lanes"][0]
    assert row["scheduler"]["kind"] == "n8n" and row["scheduler"]["expression"] == "dispatcher"
    assert row["scheduler"]["stage"] == "cutover" and row["scheduler"]["cadence"] == "0 10 * * 1-5"
    assert row["scheduler_before_cutover"]["stage"] == "canary"
    with pytest.raises(SystemExit):
        W.cutover_rows(code_root, ["nolock-lane"], "CWT")


def _fake_crontab(tmp_path: Path, text: str) -> Path:
    store = tmp_path / "crontab.txt"
    store.write_text(text)
    exe = tmp_path / "fakecrontab"
    exe.write_text(f"#!/bin/sh\nif [ \"$1\" = \"-l\" ]; then cat {store}; else cat > {store}; fi\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def test_comment_cron_one_write_backup_and_readback(code_root, tmp_path, monkeypatch):
    exe = _fake_crontab(tmp_path, CRONTAB)
    monkeypatch.setenv("CRONTAB_CMD", str(exe))
    dry = W.comment_cron(["demo-lane"], code_root, apply=False, backup_dir=tmp_path / "bk", date="2026-10-15")
    assert dry["edits"] and not (tmp_path / "bk").exists()
    rc = W.comment_cron(["demo-lane"], code_root, apply=True, backup_dir=tmp_path / "bk", date="2026-10-15")
    assert rc["read_back_ok"] is True and Path(rc["backup"]).read_text() == CRONTAB
    now = (tmp_path / "crontab.txt").read_text().splitlines()
    assert now[2] == "# RETIRED 2026-10-15 n8n-cutover demo-lane " + LINE
    from pipelines.cutover import _cutover as C
    m = C.N8N_TAG_RE.match(now[2])
    assert m and m.group(2) == "demo-lane"      # `_cutover.py rollback --lane` finds it
    again = W.comment_cron(["demo-lane"], code_root, apply=True, backup_dir=tmp_path / "bk", date="2026-10-15")
    assert again["problems"] and again["backup"] is None   # already commented: refused, nothing written


def test_flock_line_inserts_into_the_lane_segment():
    new, why = W.flock_line("5 * * * * cd $PROJ && timeout 5m $PY scripts/x.py --a >> l 2>&1", "scripts/x.py", "/tmp/x.lock")
    assert new == "5 * * * * cd $PROJ && flock -n /tmp/x.lock timeout 5m $PY scripts/x.py --a >> l 2>&1", why
    assert W.flock_line("5 * * * * $PY scripts/x.py", "scripts/x.py", "/tmp/x.lock")[0] == \
        "5 * * * * flock -n /tmp/x.lock $PY scripts/x.py"
    assert W.flock_line('5 * * * * cd /a && bash -c "$PY scripts/x.py"', "scripts/x.py", "/l")[0] is None
    assert W.flock_line("5 * * * * cd /a && FOO=1 $PY scripts/x.py", "scripts/x.py", "/l")[0] is None
    assert W.flock_line(LINE, "scripts/demo_lane.py", "/tmp/demo.lock")[0] is None


def test_add_flock_then_plan_is_ready(code_root, tmp_path, monkeypatch):
    exe = _fake_crontab(tmp_path, CRONTAB)
    monkeypatch.setenv("CRONTAB_CMD", str(exe))
    rc = W.add_flock(["nolock-lane"], code_root, apply=True, backup_dir=tmp_path / "bk", wave="CWT")
    assert rc["read_back_ok"] is True and len(rc["edits"]) == 1
    text = (tmp_path / "crontab.txt").read_text()
    v = {x["lane_id"]: x for x in W.build_plan(code_root, text, ["nolock-lane"], "CWT")["lanes"]}["nolock-lane"]
    assert v["status"] == "READY_CANARY", v["reasons"]


def test_packet_files(code_root, tmp_path):
    plan = W.build_plan(code_root, CRONTAB, None, "CWT")
    files = {p.name for p in W.write_packet(tmp_path / "pk", plan, "CWT")}
    assert {"README.md", "lanes.json", "01_relay_live_lanes.sh", "02_effect_owners.sh", "04_comment_cron.sh",
            "09_rollback.sh"} <= files
    readme = (tmp_path / "pk" / "README.md").read_text()
    assert "demo-lane" in readme and "no_cron_flock" in readme
    relay = (tmp_path / "pk" / "01_relay_live_lanes.sh").read_text()
    assert 'ADD="demo-lane"' in relay and "--apply" in relay


# ── the committed CW1 wave on main stays the shape the gates admit ─────────────────────────────

CW1 = Path(__file__).resolve().parents[1] / "docs/ops/packets/n8n-cutover-wave-1-20261015/lanes.json"


@pytest.mark.skipif(not CW1.exists(), reason="wave 1 packet not in this tree")
def test_cw1_rows_are_admitted_canaries():
    lanes = json.loads(CW1.read_text())["ready"]
    reg = {r["lane_id"]: r for r in json.loads((ROOT / W.REGISTRY).read_text())["lanes"]}
    ent = {e["lane_id"]: e for e in json.loads((ROOT / W.ALLOWLIST).read_text())["lanes"]}
    for lid in lanes:
        row, e = reg[lid], ent[lid]
        if row["scheduler"]["kind"] == "n8n":      # flipped to cutover by a later wave PR
            assert row["scheduler"]["stage"] == "cutover"
            continue
        assert row["scheduler"]["stage"] == "canary" and row["dispatch"]["mode"] == "live", lid
        assert LD.r1_canary_lock_matches(row, e)[0], lid
        assert LD.r1_class_admission(row, e)[0], (lid, LD.r1_class_admission(row, e))

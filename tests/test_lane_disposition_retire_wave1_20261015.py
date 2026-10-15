"""Lane disposition table + RETIRE wave 1 packet (2026-10-15).

COVERS = ["scripts/n8n_lane_disposition.py", "config/lane_registry.json",
          "docs/ops/packets/lane-retire-wave1-20261015/retire_packet.py",
          "docs/ops/packets/lane-retire-wave1-20261015/apply_registry.py"]

Pins: (1) docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv has exactly one row per active job line of the
committed crontab snapshot (394) with exactly one of the four dispositions, and every RETIRE row carries evidence;
re-running the builder on the committed inputs (log ages off) reproduces every disposition. (2) The retire packet
comments exactly its lines in place (never deletes), refuses a drifted table, rolls back byte-exactly, and its
install/rollback scripts round-trip on a fake crontab. (3) The registry keeps the 10 rows ACTIVE with a
retire_pending block (truthful until the host changes); apply_registry flips only rows whose line is really retired.
Hermetic: repo files, tmp_path and a fake `crontab` command. Never the live crontab.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "docs/implementation/n8n-maturity/data/disposition_20261015"
CSV_PATH = ROOT / "docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv"
PKT = ROOT / "docs/ops/packets/lane-retire-wave1-20261015"
SNAP = DATA / "crontab_20261015.txt"
SNAP_SHA = "6a5c6768bd3ebac52595dda82ae810c0cfaa7d2dfb054fd9e64b64db2ebd4e96"
TIER_A = {
    "agent-intelligence-cron-deep",
    "agent-intelligence-cron-daily",
    "agent-intelligence-cron-intraday",
    "symbol-enrichment",
}
TIER_B = {
    "cleanup-stale-locks",
    "risk-gate",
    "backup-generated-docs",
    "goal-pilot-material-change",
    "dormant-lane-consumers",
}
# The disposition table proposed indicator-engine for R1b; the operator answered NO on 2026-10-15 (keep it and turn it
# ON, repair in train 4). Its row was dropped from the tier-B TSV and its registry retire_pending block removed.
DECLINED = {"indicator-engine"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


D = _load("n8n_lane_disposition", ROOT / "scripts/n8n_lane_disposition.py")
RP = _load("retire_packet", PKT / "retire_packet.py")
AR = _load("apply_registry", PKT / "apply_registry.py")


def _rows():
    return list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))


def test_snapshot_is_the_one_the_table_was_built_from():
    assert hashlib.sha256(SNAP.read_bytes()).hexdigest() == SNAP_SHA


def test_one_row_per_active_crontab_line_and_totals_reconcile():
    _env, jobs = D.parse_crontab(SNAP.read_text(encoding="utf-8"))
    assert len(jobs) == 394
    rows = [r for r in _rows() if r["source"] == "crontab"]
    assert sorted(int(r["line_no"]) for r in rows) == sorted(j["line_no"] for j in jobs)
    assert {r["disposition"] for r in _rows()} <= set(D.DISPOSITIONS)
    t = D.totals(_rows())
    assert sum(t["crontab"].values()) == 394
    # No line is undeclared: every active line maps to a registry row.
    assert all(r["registry_state"] != "NONE" for r in rows)


def test_retire_rows_carry_evidence_and_the_packet_lines_are_exactly_the_r1_rows():
    rows = _rows()
    for r in rows:
        if r["disposition"] == "RETIRE":
            assert len(r["evidence"]) > 40, r["row_id"]
    r1 = {r["lane_id"] for r in rows if r["source"] == "crontab" and r["wave"] == "R1"}
    r1b = {r["lane_id"] for r in rows if r["source"] == "crontab" and r["wave"] == "R1b"}
    assert r1 == TIER_A and r1b == TIER_B | DECLINED
    assert {x["lane_id"] for x in RP.rows(tier_b=False)} == TIER_A
    assert {x["lane_id"] for x in RP.rows(tier_b=True)} == TIER_A | TIER_B


def test_builder_reproduces_the_committed_dispositions():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    for r in reg[
        "lanes"
    ]:  # the table was built before the retire_pending/shadow edits; those never change a disposition
        r.pop("retire_pending", None)
    inv = list(csv.DictReader((DATA / "inventory_20261014.csv").open(encoding="utf-8")))
    fam = list(csv.DictReader((DATA / "ws2_family_decisions_20261014.csv").open(encoding="utf-8")))
    ov = json.loads((DATA / "overrides.json").read_text(encoding="utf-8"))
    ov["allowlist_blocked"] = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["blocked_reasons"]
    built = D.build(SNAP.read_text(encoding="utf-8"), reg, inv, fam, ov, measure_logs=False)
    got = {r["row_id"]: r["disposition"] for r in built if r["source"] == "crontab"}
    want = {r["row_id"]: r["disposition"] for r in _rows() if r["source"] == "crontab"}
    assert got == want


def test_classify_rules():
    reg = {
        "a": {"lane_id": "a", "state": "RETIRED", "superseded_by": "p"},
        "p": {"lane_id": "p", "state": "ACTIVE"},
        "b": {"lane_id": "b", "state": "RETIRED", "superseded_by": "p"},
    }
    fam = {"family_id": "F11", "decision": "CONSOLIDATE", "category": "CONSOLIDATE"}
    d = D.classify("a", reg["a"], None, fam, {"lanes": {}}, reg)
    assert d["disposition"] == "CONSOLIDATE" and d["duplicate_of"] == "p"
    assert D.classify("p", reg["p"], None, None, {"lanes": {}}, reg)["disposition"] == "CONSOLIDATE"
    broker = {"family_id": "F09", "decision": "STAY EXTERNAL"}
    assert D.classify("x", {"state": "ACTIVE"}, None, broker, {"lanes": {}}, {})["disposition"] == "STAY_HOST"
    inv = {"refactor_required": "N (stays on cron; not migrating)", "risk_level": "High"}
    single = {"family_id": "F45", "decision": "MIGRATE"}
    assert D.classify("y", {"state": "ACTIVE"}, inv, single, {"lanes": {}}, {})["disposition"] == "STAY_HOST"
    assert (
        D.classify("z", {"state": "ACTIVE"}, {"refactor_required": "N"}, single, {"lanes": {}}, {})["disposition"]
        == "MIGRATE_N8N"
    )
    ov = {"lanes": {"z": {"disposition": "RETIRE", "wave": "R1", "evidence": "e"}}}
    assert D.classify("z", {"state": "ACTIVE"}, None, single, ov, {})["disposition"] == "RETIRE"


def test_cutover_directive_2026_10_15():
    """Operator directive 2026-10-15 "N8N Cutover Decision": STAY_HOST only for F07 and every registry_systemd row."""
    stay = {"disposition": "STAY_HOST", "target": "host cron/systemd", "target_shape": "host", "wave": "-",
            "evidence": "inventory 2026-10-14: not eligible for n8n", "duplicate_of": ""}
    b = D.apply_cutover_directive(stay, "F09", "crontab")
    assert b["disposition"] == "MIGRATE_N8N" and b["wave"] == "CD6" and "no broker credential" in b["target"]
    assert D.apply_cutover_directive(stay, "F10", "crontab")["target"].startswith("n8n-orchestrated primary")
    assert D.apply_cutover_directive(stay, "F40", "crontab")["wave"] == "CD4"
    assert D.apply_cutover_directive(stay, "F07w", "crontab")["wave"] == "CD5"
    assert D.apply_cutover_directive(stay, "F36", "crontab")["wave"] == "CD1"
    assert D.apply_cutover_directive(dict(stay, target="host sender (comms chokepoint)"), "F36", "crontab")["wave"] == "CD3"
    for fid, src in (("F07", "crontab"), ("F41", "registry_systemd"), ("F07w", "registry_systemd")):
        d = D.apply_cutover_directive(stay, fid, src)
        assert d["disposition"] == "STAY_HOST" and d["wave"] == "DEFERRED-I2" and "2026-10-15" in d["evidence"]
    mig = dict(stay, disposition="MIGRATE_N8N", wave="M3")
    assert D.apply_cutover_directive(mig, "F09", "crontab") == mig
    # registry_systemd: "not to be migrated, refactored, or reclassified" -> every disposition is held on the host.
    for disp in ("MIGRATE_N8N", "CONSOLIDATE", "RETIRE"):
        d = D.apply_cutover_directive(dict(stay, disposition=disp, wave="M5"), "F40", "registry_systemd")
        assert d["disposition"] == "STAY_HOST" and d["wave"] == "DEFERRED-I2"
        assert d["evidence"].startswith("operator directive 2026-10-15: registry_systemd deferred this iteration (was: ")
        assert f"(was: {disp}/M5" in d["evidence"]
    # The committed table: STAY_HOST only for F07 / registry_systemd, every converted row cites the directive.
    for r in _rows():
        if r["disposition"] == "STAY_HOST":
            assert r["family_id"] == "F07" or r["source"] == "registry_systemd", r["row_id"]
            assert r["wave"] == "DEFERRED-I2", r["row_id"]
        if r["source"] == "registry_systemd":
            assert r["disposition"] == "STAY_HOST" and r["wave"] == "DEFERRED-I2", r["row_id"]
        if r["wave"] in D.DIRECTIVE_WAVES:
            assert r["disposition"] == "MIGRATE_N8N" and D.DIRECTIVE_ID in r["evidence"], r["row_id"]
    t = D.totals(_rows())
    assert t["crontab"] == {"RETIRE": 10, "CONSOLIDATE": 148, "STAY_HOST": 1, "MIGRATE_N8N": 235}
    assert t["registry_only"] == {"RETIRE": 1, "CONSOLIDATE": 5, "STAY_HOST": 102, "MIGRATE_N8N": 32}


def test_parse_crontab_skips_env_and_comments():
    env, jobs = D.parse_crontab(
        "SHELL=/bin/bash\nPY=/x\n# 1 2 * * * old\n\n*/5 * * * * cd $PROJ && x  # TRADEAI_LANE l1\n"
    )
    assert env == {"SHELL": "/bin/bash", "PY": "/x"} and len(jobs) == 1 and jobs[0]["tag"] == "l1"
    assert jobs[0]["schedule"] == "*/5 * * * *"


# ── packet ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_build_comments_in_place_and_rolls_back_exactly():
    text = SNAP.read_text(encoding="utf-8")
    for tier_b, n in ((False, 4), (True, 9)):
        cand, problems = RP.build(text, "2026-10-15", tier_b)
        assert problems == []
        before, after = text.splitlines(), cand.splitlines()
        assert len(before) == len(after)  # nothing deleted, nothing added
        changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
        assert len(changed) == n
        for i in changed:
            assert after[i].startswith("# RETIRED 2026-10-15 retire-ld-w1 ") and after[i].endswith(before[i])
        assert RP.active_count(after) == 394 - n
        assert RP.verify(cand, tier_b, expect_live=False) == []
        restored, problems, k = RP.rollback(cand, tier_b)
        assert problems == [] and k == n and restored == text


def test_build_refuses_a_drifted_or_already_retired_table():
    text = SNAP.read_text(encoding="utf-8")
    cand, _ = RP.build(text, "2026-10-15", False)
    _c, problems = RP.build(cand, "2026-10-16", False)
    assert problems == ["nothing to retire: every packet line is already retired"]
    # tier B on top of an installed tier A retires only the tier-B lines
    both, problems = RP.build(cand, "2026-10-16", True)
    assert problems == [] and RP.active_count(both.splitlines()) == 385 and RP.verify(both, True, False) == []
    dup = text + RP.rows(False)[0]["original"] + "\n"
    _c, problems = RP.build(dup, "2026-10-15", False)
    assert any("found 2 times" in p for p in problems)
    # rollback refuses a double schedule
    double = cand + RP.rows(False)[0]["original"] + "\n"
    _r, problems, _n = RP.rollback(double, False)
    assert any("double schedule" in p for p in problems)


@pytest.fixture()
def fake_crontab(tmp_path):
    table = tmp_path / "table"
    table.write_bytes(SNAP.read_bytes())
    exe = tmp_path / "fakecron"
    exe.write_text(
        f'#!/bin/bash\nT="{table}"\nif [ "$1" = "-l" ]; then cat "$T"; '
        'elif [ "$1" = "-" ]; then cat > "$T"; else exit 9; fi\n'
    )
    exe.chmod(0o755)
    return table, exe


def _sh(script: str, args: list[str], env: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    e = dict(os.environ, **env, BACKUP_DIR=str(tmp_path / "bk"))
    return subprocess.run(["bash", str(PKT / script), *args], capture_output=True, text=True, env=e, timeout=60)


def test_install_and_rollback_round_trip_on_a_fake_crontab(tmp_path, fake_crontab):
    table, exe = fake_crontab
    dry = _sh("install.sh", ["--tier-b"], {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w0")}, tmp_path)
    assert dry.returncode == 0 and "DRY RUN" in dry.stdout and table.read_bytes() == SNAP.read_bytes()
    refused = _sh(
        "install.sh",
        ["--apply"],
        {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w1"), "CRON_GRANT_ID": ""},
        tmp_path,
    )
    assert refused.returncode == 2 and table.read_bytes() == SNAP.read_bytes()
    inst = _sh(
        "install.sh",
        ["--apply"],
        {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w2"), "CRON_GRANT_ID": "rehearsal"},
        tmp_path,
    )
    assert inst.returncode == 0, inst.stdout + inst.stderr
    assert "VERIFY OK: 4 line(s) retired" in inst.stdout and RP.active_count(table.read_text().splitlines()) == 390
    rb = _sh(
        "rollback.sh",
        ["--apply"],
        {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w3"), "CRON_GRANT_ID": "rehearsal"},
        tmp_path,
    )
    assert rb.returncode == 0, rb.stdout + rb.stderr
    assert table.read_bytes() == SNAP.read_bytes()


# ── registry ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_registry_rows_are_retired_after_the_2026_10_15_install():
    """Installed 2026-10-15 under cron grant 1aa15633…: tier A + the 5 tier-B YES rows; apply_registry.py --write."""
    reg = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    assert not [r["lane_id"] for r in reg["lanes"] if r.get("retire_pending")]
    from scripts.lib import lane_registry as LR

    for lane in TIER_A | TIER_B:
        r = rows[lane]
        assert r["state"] == "RETIRED" and r["retire_batch"] == "retire-ld-w1" and "retire_pending" not in r
        assert LR.validate_row(r) == []
    for lane in DECLINED:
        r = rows[lane]
        assert r["state"] == "ACTIVE" and "retire_pending" not in r and r["retire_declined"]["decided"] == "2026-10-15"


def test_apply_registry_flips_only_rows_whose_line_is_retired():
    tsv = {x["lane_id"]: x for x in RP.rows(tier_b=True)}
    reg = {
        "lanes": [
            {"lane_id": lane, "state": "ACTIVE", "retire_pending": {"tier": "t", "reason": tsv[lane]["reason"],
                                                                    "evidence": "e"}}
            for lane in TIER_A | TIER_B
        ]
    }
    cand, _ = RP.build(SNAP.read_text(encoding="utf-8"), "2026-10-15", False)
    flip, keep = AR.plan(reg, cand)
    assert set(flip) == TIER_A and set(keep) == TIER_B
    AR.apply(reg, flip, "2026-10-15", "g-test")
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    for lane in TIER_A:
        assert rows[lane]["state"] == "RETIRED" and rows[lane]["retire_batch"] == "retire-ld-w1"
    for lane in TIER_B:
        assert rows[lane]["state"] == "ACTIVE" and rows[lane]["retire_pending"]
    flip0, _ = AR.plan(reg, SNAP.read_text())
    assert flip0 == []  # nothing flips while the lines are live

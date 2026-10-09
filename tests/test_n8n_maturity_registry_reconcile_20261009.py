"""N8N maturity B1 — lane registry reconciled: undeclared baseline 476 → 0.

ANCHOR: N8N_MATURITY_REGISTRY_RECONCILE

The registry passed CI only through a 476-entry exemption; 321 crontab lines and 45 timers had no row.
scripts/reconcile_lane_registry.py now derives a row for every live crontab line, timer and platform
service from the host (read-only) or from the committed scheduler snapshot. These tests pin:

  * the generator is deterministic and the committed registry is its fixed point;
  * every live crontab line maps to exactly one row, every live unit has a row, no ACTIVE row maps nothing;
  * no exemption is left (baseline and inherited tranches are gone; the gate's --no-exemptions passes);
  * broker / order / secret lines are tagged KEEP_ON_CRON, cross-checked against
    pipeline_manifest.FORBIDDEN_COMMAND_TOKENS and the gateway's FORBIDDEN_ROUTE_TOKENS / SECRET_KEYS;
  * output signals come from evidence (log redirect or source-verified receipt) or are flagged
    UNVERIFIED_OUTPUT — never invented; nothing added carries a host home path.

Hermetic: reads only repository files (the snapshot is committed); no crontab, no systemd, no network.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts import reconcile_lane_registry as R  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS, SECRET_KEYS  # noqa: E402
from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS  # noqa: E402

DATA = ROOT / "docs" / "implementation" / "n8n-maturity" / "data"
SNAPSHOT = DATA / "scheduler_snapshot_20261009.json"
REGISTRY = ROOT / "config" / "lane_registry.json"
GATE = ROOT / "scripts" / "check_lane_registry.py"
COVERS = ["scripts/reconcile_lane_registry.py", "scripts/lib/lane_registry.py",
          "scripts/check_lane_registry.py", "config/lane_registry.json"]


@pytest.fixture(scope="module")
def inputs():
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return {
        "snap": snap,
        "cron_text": R.snapshot_cron_text(snap),
        "units": snap["units"],
        "f_rows": R.load_rationalization(),
        "evidence": R.load_evidence(),
    }


@pytest.fixture(scope="module")
def committed():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result(inputs, committed):
    return R.reconcile(committed, cron_text=inputs["cron_text"], units=inputs["units"],
                       f_rows=inputs["f_rows"], evidence=inputs["evidence"])


def _lines(inputs):
    return [c["expression"] for c in LR.discover_cron(inputs["cron_text"])]


def _blocking(problems):
    return [p for p in problems if p["code"] != "EVIDENCE_REJECTED"]


# ── determinism ──────────────────────────────────────────────────────────────────────────────────

def test_committed_registry_is_the_generators_fixed_point(result):
    assert not _blocking(result["problems"]), result["problems"][:5]
    assert R.dump_registry(result["registry"]) == REGISTRY.read_text(encoding="utf-8"), (
        "config/lane_registry.json differs from reconcile_lane_registry.py output on the committed snapshot; "
        "re-run: python3 scripts/reconcile_lane_registry.py --snapshot-in "
        "docs/implementation/n8n-maturity/data/scheduler_snapshot_20261009.json --write")


def test_generation_is_deterministic_from_the_hand_written_rows(inputs, committed):
    """Strip every generated row and regenerate twice: byte-identical, and identical to the commit."""
    hand = dict(committed, lanes=[r for r in committed["lanes"] if r.get("generated_by") != R.GENERATOR_VERSION])
    a = R.reconcile(hand, cron_text=inputs["cron_text"], units=inputs["units"], f_rows=inputs["f_rows"],
                    evidence=inputs["evidence"])
    b = R.reconcile(hand, cron_text=inputs["cron_text"], units=inputs["units"], f_rows=inputs["f_rows"],
                    evidence=inputs["evidence"])
    assert R.dump_registry(a["registry"]) == R.dump_registry(b["registry"])
    assert R.dump_registry(a["registry"]) == REGISTRY.read_text(encoding="utf-8")
    assert len(a["added"]) == sum(1 for r in committed["lanes"] if r.get("generated_by") == R.GENERATOR_VERSION)


def test_dry_run_is_the_default_and_writes_nothing(tmp_path):
    reg = tmp_path / "lane_registry.json"
    reg.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    before = reg.read_bytes()
    rc = R.main(["--registry", str(reg), "--snapshot-in", str(SNAPSHOT)])
    assert rc == 0
    assert reg.read_bytes() == before


# ── mapping ──────────────────────────────────────────────────────────────────────────────────────

def test_every_live_crontab_line_maps_to_exactly_one_row(inputs, committed):
    lines = _lines(inputs)
    assert len(lines) == 438
    mapping = R.line_mapping(committed, lines)
    bad = {R.sanitize(ln)[:120]: ids for ln, ids in mapping.items() if len(ids) != 1}
    assert not bad, bad


def test_every_live_unit_has_a_row(inputs, committed):
    names = [t["unit"] for t in inputs["units"]["timers"]] + [s["unit"] for s in inputs["units"]["services"]]
    assert len(inputs["units"]["services"]) >= 18
    missing = [u for u, ids in R.unit_mapping(committed, names).items() if not ids]
    assert not missing, missing


def test_the_gate_sees_nothing_undeclared_on_the_snapshot(inputs, committed):
    found = {
        "cron": LR.discover_cron(inputs["cron_text"]),
        "systemd": [{"expression": t["unit"], "enabled_state": t["enabled_state"]} for t in inputs["units"]["timers"]],
        "systemd_services": [{"expression": s["unit"], "enabled_state": s["enabled_state"]}
                             for s in inputs["units"]["services"]],
    }
    assert LR.find_undeclared(committed, found, n8n_known_ids=[]) == []


def test_no_active_row_maps_nothing(inputs, committed):
    lines = _lines(inputs)
    units = {t["unit"] for t in inputs["units"]["timers"]} | {s["unit"] for s in inputs["units"]["services"]}
    empty = []
    for r in committed["lanes"]:
        if r.get("state") != "ACTIVE":
            continue
        sched = r.get("scheduler") or {}
        if sched.get("kind") == "cron":
            if not any(any(d in ln for d in R.declarations(r)) for ln in lines):
                empty.append(r["lane_id"])
        elif sched.get("kind") == "systemd":
            names = {str(sched.get("match") or ""), str(sched.get("expression") or "").split(" ")[0]}
            if not names & units:
                empty.append(r["lane_id"])
    assert not empty, empty


def test_no_exemptions_remain_and_the_gate_enforces_it(tmp_path, inputs, committed):
    assert "undeclared_baseline" not in committed and "inherited_tranches" not in committed
    disco = tmp_path / "discovery.json"
    disco.write_text(json.dumps({
        "cron": LR.discover_cron(inputs["cron_text"]), "cron_commented": [],
        "systemd": [{"expression": t["unit"], "enabled_state": t["enabled_state"]} for t in inputs["units"]["timers"]],
        "systemd_services": [{"expression": s["unit"], "enabled_state": s["enabled_state"]}
                             for s in inputs["units"]["services"]],
    }), encoding="utf-8")
    cmd = [sys.executable, str(GATE), "--fail-on-new", "--no-exemptions", "--no-n8n", "--discovery-json", str(disco)]
    ok = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert ok.returncode == 0, ok.stdout[-2000:] + ok.stderr[-2000:]
    # an exemption is now a regression
    bad = tmp_path / "with_baseline.json"
    bad.write_text(json.dumps(dict(committed, undeclared_baseline=["0 0 * * * whatever"])), encoding="utf-8")
    red = subprocess.run(cmd + ["--registry", str(bad)], cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert red.returncode == 1


# ── classification ───────────────────────────────────────────────────────────────────────────────

def _row_for_line(committed, line):
    ids = R.line_mapping(committed, [line])[line]
    assert len(ids) == 1, (line[:100], ids)
    return next(r for r in committed["lanes"] if r["lane_id"] == ids[0])


def test_broker_order_secret_lines_are_kept_on_cron(inputs, committed):
    """Cross-check against the two token lists the program already enforces elsewhere."""
    assert R.ROUTE_TOKEN_CHANNEL_EXEMPT <= FORBIDDEN_ROUTE_TOKENS
    assert R.SECRET_NAME_EXEMPT <= SECRET_KEYS
    assert R.GATE_TOKENS <= set(FORBIDDEN_COMMAND_TOKENS)
    route = FORBIDDEN_ROUTE_TOKENS - R.ROUTE_TOKEN_CHANNEL_EXEMPT
    secret = SECRET_KEYS - R.SECRET_NAME_EXEMPT
    checked = 0
    for line in _lines(inputs):
        _sched, cmd = R.split_schedule(line)
        _tok, stem = R.primary_script(cmd)
        words = set(w for w in re.split(r"[^a-z0-9]+", stem.lower()) if w)
        hit = [t for t in FORBIDDEN_COMMAND_TOKENS if t in cmd] or sorted(words & route) or sorted(words & secret)
        if not hit:
            continue
        checked += 1
        row = _row_for_line(committed, line)
        assert row.get("stay_on_cron"), (row["lane_id"], hit)
        assert row.get("recommendation") in (R.REC_KEEP, R.REC_R0), (row["lane_id"], row.get("recommendation"))
    assert checked >= 40


def test_r0_rows_stay_active_with_the_recommendation(committed):
    r0 = [r for r in committed["lanes"] if r.get("recommendation") == R.REC_R0]
    assert len(r0) >= 25
    for r in r0:
        if r.get("generated_by") == R.GENERATOR_VERSION:
            assert r["state"] == "ACTIVE", r["lane_id"]


def test_every_rationalized_line_carries_value_class_and_recommendation(inputs, committed):
    allowed = re.compile(r"^(R0_ELIMINATE|KEEP_ON_CRON|EVENT_DRIVEN_CANDIDATE|MIGRATE_N8N|MERGE_INTO:\S+|PIPELINE:P\d\d)$")
    for line in _lines(inputs):
        row = _row_for_line(committed, line)
        assert row.get("value_class"), row["lane_id"]
        assert allowed.match(str(row.get("recommendation"))), (row["lane_id"], row.get("recommendation"))


def test_recommendation_normalisation():
    n = R.normalise_recommendation
    assert n({"recommendation": "ELIMINATE (dead since 10-02)", "pipeline": "P08"}) == "R0_ELIMINATE"
    assert n({"recommendation": "KEEP on cron/systemd; n8n watches heartbeat", "pipeline": "P09"}) == "KEEP_ON_CRON"
    assert n({"recommendation": "CONSOLIDATE-into P07", "pipeline": "P07", "value_class": "Operationally Important"}) == "PIPELINE:P07"
    assert n({"recommendation": "MERGE-into P07 sweep", "pipeline": "P07", "value_class": "Duplicated"}) == "MERGE_INTO:P07"
    assert n({"recommendation": "EVENT-DRIVEN (queue drain/poller) inside P10", "pipeline": "P10"}) == "EVENT_DRIVEN_CANDIDATE"
    assert n({"recommendation": "REPLACE by registry-driven dispatcher", "pipeline": ""}) == "MIGRATE_N8N"
    assert n(None) is None


# ── output signals ───────────────────────────────────────────────────────────────────────────────

def test_generated_rows_have_evidence_or_are_flagged_unverified(committed):
    gen = [r for r in committed["lanes"] if r.get("generated_by") == R.GENERATOR_VERSION]
    assert len(gen) >= 360
    for r in gen:
        sig = r["output_signal"]
        if sig.get("kind") == "none":
            assert sig.get("reason") == R.UNVERIFIED_OUTPUT and R.UNVERIFIED_OUTPUT in r.get("flags", []), r["lane_id"]
        else:
            assert sig.get("evidence") in ("SCRIPT_RECEIPT", "CRON_LOG_REDIRECT", "SYSTEMD_STDOUT_APPEND"), r["lane_id"]
            assert sig.get("path"), r["lane_id"]
    assert not LR.validate_registry(committed)


def test_evidence_overlay_is_source_verified_and_host_neutral():
    doc = json.loads(R.EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert doc["schema"] == "LaneOutputEvidence@v1"
    for lane_id, e in doc["entries"].items():
        if "declared_state" in e:
            assert e["declared_state"]["state"] in ("PAUSED", "RETIRED", "NEVER_SCHEDULED"), lane_id
            assert e["declared_state"]["reason_evidence"], lane_id
        if "output_signal" not in e:
            continue
        src = ROOT / e["source_file"]
        assert src.is_file(), lane_id
        assert e["verified_token"] in src.read_text(encoding="utf-8", errors="replace"), lane_id
        assert not re.search(r"/home/[^/]+", json.dumps(e)), lane_id


def test_nothing_added_carries_a_home_path(committed):
    for r in committed["lanes"]:
        if r.get("generated_by") == R.GENERATOR_VERSION:
            assert not re.search(r"/home/[A-Za-z0-9._-]+", json.dumps(r, ensure_ascii=False)), r["lane_id"]
    snap = SNAPSHOT.read_text(encoding="utf-8")
    assert not re.search(r"/home/[A-Za-z0-9._-]+", snap)


# ── units of the generator ───────────────────────────────────────────────────────────────────────

def test_identical_jobs_on_two_schedules_become_one_multi_schedule_row():
    text = ("0 10 * * 1-5 cd $PROJ && flock -n /tmp/a.lock $PY /home/u/x/scripts/snap.py >> logs/snap.log 2>&1\n"
            "35 17 * * 1-5 cd $PROJ && flock -n /tmp/a.lock $PY /home/u/x/scripts/snap.py >> logs/snap.log 2>&1\n"
            "5 * * * * cd /home/u/x && $PY scripts/other.py >> logs/other.log 2>&1\n")
    reg = {"schema": "LaneRegistry@v1", "lanes": []}
    res = R.reconcile(reg, cron_text=text, units={"timers": [], "services": []}, f_rows=[], evidence={},
                      tokens=((), frozenset(), frozenset()))
    assert not _blocking(res["problems"]), res["problems"]
    by = {r["lane_id"]: r for r in res["registry"]["lanes"]}
    assert set(by) == {"snap", "other"}
    assert by["snap"]["scheduler"]["schedules"] == ["0 10 * * 1-5", "35 17 * * 1-5"]
    assert "/home/" not in by["snap"]["scheduler"]["match"]
    assert by["snap"]["output_signal"] == {"kind": "file_mtime", "path": "logs/snap.log", "evidence": "CRON_LOG_REDIRECT"}
    assert by["other"]["expected_cadence_hours"] == 1.0
    # a relative log outside CURRENT keeps its tree, host-neutrally
    assert by["other"]["output_signal"]["path"] == "~/x/logs/other.log"
    # weekday-only job: the weekend gap is the declared cadence
    assert by["snap"]["expected_cadence_hours"] == pytest.approx(64.42, abs=0.01)


def test_a_line_with_no_output_is_flagged_not_invented():
    text = "*/5 * * * * cd /home/u/x && $PY scripts/silent_job.py\n"
    res = R.reconcile({"lanes": []}, cron_text=text, units={"timers": [], "services": []}, f_rows=[], evidence={},
                      tokens=((), frozenset(), frozenset()))
    row = res["registry"]["lanes"][0]
    assert row["output_signal"]["kind"] == "none" and row["flags"] == [R.UNVERIFIED_OUTPUT]


def test_a_systemd_row_does_not_declare_a_cron_line_that_mentions_its_unit():
    reg = {"lanes": [{"lane_id": "svc", "scheduler": {"kind": "systemd", "expression": "x.service"}}]}
    found = {"cron": [{"expression": "@reboot systemctl --user start x.service"}], "systemd": [],
             "systemd_services": [{"expression": "x.service", "enabled_state": "enabled"}]}
    out = LR.find_undeclared(reg, found)
    assert [o["kind"] for o in out] == ["cron"]


def test_an_undeclared_platform_service_is_reported():
    found = {"cron": [], "systemd": [], "systemd_services": [{"expression": "y.service", "enabled_state": "enabled"}]}
    out = LR.find_undeclared({"lanes": []}, found)
    assert out == [{"kind": "systemd_service", "expression": "y.service", "enabled_state": "enabled"}]


def test_a_service_row_is_present_when_the_service_is_discovered():
    row = {"lane_id": "s", "scheduler": {"kind": "systemd", "expression": "y.service"}}
    found = {"cron": [], "systemd": [], "systemd_services": [{"expression": "y.service"}]}
    assert LR._scheduler_present(row, found) is True


def test_tilde_output_paths_resolve_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "beat").write_text("x", encoding="utf-8")
    obs = LR.observe_signal({"kind": "file_mtime", "path": "~/logs/beat"}, root=tmp_path / "elsewhere")
    assert obs["last_output_at"] is not None


def test_disabled_timer_is_declared_paused_with_review_by():
    units = {"timers": [{"unit": "z.timer", "enabled_state": "disabled", "service": "z.service", "on_calendar": [],
                         "monotonic_hours": None, "expected_cadence_hours": None, "exec_start": "", "stdout": "",
                         "working_directory": ""}], "services": []}
    res = R.reconcile({"lanes": []}, cron_text="", units=units, f_rows=[], evidence={},
                      tokens=((), frozenset(), frozenset()))
    row = res["registry"]["lanes"][0]
    assert row["state"] == "PAUSED" and row["review_by"] and row["reason_confidence"] == "UNKNOWN"
    assert not LR.validate_registry(res["registry"])

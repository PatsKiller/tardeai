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
    # 438 captured + the 3 lines of the approved registry-ops-crons install (packet ops-crons-install.md)
    assert len(lines) == 441
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
    broker = R.load_stay_tokens()
    checked = 0
    for line in _lines(inputs):
        _sched, cmd = R.split_schedule(line)
        _tok, stem = R.primary_script(cmd)
        words = set(w for w in re.split(r"[^a-z0-9]+", stem.lower()) if w)
        hit = ([t for t in FORBIDDEN_COMMAND_TOKENS if t in cmd] or sorted(words & route) or sorted(words & secret)
               or [w for w in sorted(broker) if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(w),
                                                          R.strip_shell_comment(cmd).lower())])
        if not hit:
            continue
        checked += 1
        row = _row_for_line(committed, line)
        assert row.get("stay_on_cron"), (row["lane_id"], hit)
        # PR #1597 review: KEEP_ON_CRON beats R0 too — eliminating a broker line is an operator decision.
        assert row.get("recommendation") == R.REC_KEEP, (row["lane_id"], row.get("recommendation"))
    assert checked >= 40


def test_r0_rows_stay_active_with_the_recommendation(committed):
    r0 = [r for r in committed["lanes"] if r.get("recommendation") == R.REC_R0]
    assert len(r0) >= 20
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
            # UNVERIFIED_OUTPUT, or (registry-ops-crons 2026-10-09) a written declaration that no artifact exists
            assert sig.get("reason") in (R.UNVERIFIED_OUTPUT, "NO_DURABLE_OUTPUT"), r["lane_id"]
            assert sig["reason"] in r.get("flags", []), r["lane_id"]
        else:
            assert sig.get("evidence") in ("SCRIPT_RECEIPT", "CRON_LOG_REDIRECT", "SYSTEMD_STDOUT_APPEND"), r["lane_id"]
            # db_max receipts (registry-ops-crons: stop-health-check, schwab-stream-daemon) name a table, not a path
            assert sig.get("path") or (sig.get("kind") == "db_max" and sig.get("table")), r["lane_id"]
    assert not LR.validate_registry(committed)


def test_evidence_overlay_is_source_verified_and_host_neutral():
    doc = json.loads(R.EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert doc["schema"] == "LaneOutputEvidence@v1"
    for lane_id, e in doc["entries"].items():
        assert "declared_state" not in e, lane_id      # a proposal, never a ruling (PR #1597 review)
        if "proposed_state" in e:
            assert e["proposed_state"]["state"] in ("PAUSED", "RETIRED", "NEVER_SCHEDULED"), lane_id
            assert e["proposed_state"]["reason_evidence"], lane_id
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


def _disabled_unit(name="z.timer"):
    return {"timers": [{"unit": name, "enabled_state": "disabled", "service": "z.service", "on_calendar": [],
                        "monotonic_hours": None, "expected_cadence_hours": None, "exec_start": "", "stdout": "",
                        "working_directory": ""}], "services": []}


def test_disabled_timer_is_recorded_not_ruled():
    """PR #1597 review: a disabled unit is never declared RETIRED/PAUSED/NEVER_SCHEDULED by the generator."""
    res = R.reconcile({"lanes": []}, cron_text="", units=_disabled_unit(), f_rows=[], evidence={},
                      tokens=((), frozenset(), frozenset()))
    row = res["registry"]["lanes"][0]
    assert row["state"] == "ACTIVE" and row["status"] == R.STATUS_DISABLED_UNRULED
    assert row["operator_decision_pending"] is True and "disabled" in row["disabled_evidence"]
    assert "proposed_state" not in row and "review_by" not in row and "state_reason" not in row
    assert not LR.validate_registry(res["registry"])


def test_evidence_proposal_is_carried_as_unruled_proposed_state():
    ev = {"z": {"proposed_state": {"state": "RETIRED", "state_since": "2026-09-16", "reason_confidence": "CORRELATED",
                                   "state_reason": "orphan", "reason_evidence": "doc.md"}}}
    res = R.reconcile({"lanes": []}, cron_text="", units=_disabled_unit(), f_rows=[], evidence=ev,
                      tokens=((), frozenset(), frozenset()))
    row = res["registry"]["lanes"][0]
    assert row["state"] == "ACTIVE" and row["status"] == R.STATUS_DISABLED_UNRULED
    assert row["proposed_state"]["state"] == "RETIRED" and row["proposed_state"]["ruled"] is False
    assert row["state"] not in LR.SILENCE_EXPECTED


def test_committed_disabled_units_are_all_unruled(inputs, committed):
    by_unit = {r["scheduler"]["expression"]: r for r in committed["lanes"]
               if r.get("generated_by") == R.GENERATOR_VERSION and r["scheduler"]["kind"] == "systemd"}
    disabled = [u["unit"] for u in inputs["units"]["timers"] + inputs["units"]["services"]
                if str(u.get("enabled_state") or "") not in R.ENABLED_STATES and u["unit"] in by_unit]
    assert len(disabled) >= 7
    for u in disabled:
        r = by_unit[u]
        assert r["state"] == "ACTIVE" and r["status"] == R.STATUS_DISABLED_UNRULED, u
        assert r["operator_decision_pending"] is True, u


# ── stay_on_cron over the whole command (PR #1597 review) ──────────────────────────────────────

def test_stay_tokens_come_from_config_and_route_selection_is_a_gateway_subset():
    doc = json.loads(R.STAY_TOKENS_PATH.read_text(encoding="utf-8"))
    assert set(doc["gateway_route_tokens_in_command"]) <= FORBIDDEN_ROUTE_TOKENS
    words = R.load_stay_tokens()
    for w in ("schwab", "alpaca", "opend", "ibkr", "defense_execution", "trade_executor", "stop", "broker"):
        assert w in words, w
    # moomoo is already a pipeline_manifest token; the config does not repeat it
    assert "moomoo" in FORBIDDEN_COMMAND_TOKENS and "moomoo" not in doc["broker_command_tokens"]


def test_stay_on_cron_scans_python_c_bodies_and_skips_comments():
    toks = (tuple(FORBIDDEN_COMMAND_TOKENS), frozenset(FORBIDDEN_ROUTE_TOKENS), frozenset(SECRET_KEYS),
            R.load_stay_tokens())
    cmd = ('cd $PROJ && bash -c "$PY -c \\"import sys; import defense_execution as d; d.poll_fills()\\"" '
           '>> logs/x.log 2>&1')
    assert R.stay_on_cron(cmd, "inline", tokens=toks)["token"] == "defense_execution"
    assert R.stay_on_cron("flock -n /tmp/s.lock $PY scripts/schwab_stream_daemon.py", "schwab_stream_daemon",
                          tokens=toks)["token"] == "schwab"
    assert R.stay_on_cron("$PY scripts/x.py --apply >> logs/x.log 2>&1  # holdings vs broker", "x", tokens=toks) is None
    assert R.stay_on_cron("$PY scripts/stopwatch.py", "stopwatch", tokens=toks) is None   # whole words only
    assert R.strip_shell_comment('echo "a # b" # c') == 'echo "a # b"'


def test_reviewed_broker_lines_are_keep_on_cron(committed):
    by = {r["lane_id"]: r for r in committed["lanes"]}
    for lid, tok in (("schwab-stream-daemon", "schwab"), ("defense-execution", "defense_execution")):
        assert by[lid]["recommendation"] == R.REC_KEEP and by[lid]["stay_on_cron"]["token"] == tok, lid


def test_stay_class_beats_r0_and_the_row_stays_active(committed):
    by = {r["lane_id"]: r for r in committed["lanes"]}
    for lid in ("start-trade-ai-lab-moomoo-opend", "run-protection-pipeline-at-30-20",
                "run-protection-pipeline-at-x-30-9-16", "eod-open-trade-alert"):
        r = by[lid]
        assert r["state"] == "ACTIVE" and r["recommendation"] == R.REC_KEEP and r.get("stay_on_cron"), lid
        assert r["rationalization"]["recommendation"] == R.REC_R0, lid      # the R0 stays visible
    assert R._final_recommendation(R.REC_R0, {"class": "broker_order", "token": "x"}) == R.REC_KEEP
    assert R._final_recommendation(R.REC_R0, None) == R.REC_R0


def test_scalp_shadow_logger_row_matches_the_regranted_line(inputs, committed):
    line = next(ln for ln in _lines(inputs) if "run_scalp_shadow_logger.sh" in ln)
    assert line.startswith("*/5 6-15 * * 1-5 ")
    row = _row_for_line(committed, line)
    assert row["scheduler"]["expression"] == "*/5 6-15 * * 1-5"
    assert row["rationalization"]["f_id"] == "L804"
    assert row["rationalization"]["schedule_changed_since_rationalization"]["f_sched"] == "*/5 6-11 * * 1-5"

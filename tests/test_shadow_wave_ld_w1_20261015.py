"""Shadow wave LD-W1 (lane disposition 2026-10-15, wave M1): 6 leaf lanes onto the fabric in SHADOW (dry run only).

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json",
          "scripts/incubator_rolloff_engine.py", "scripts/pattern_extractor.py", "scripts/cio_gate_measurement_bridge.py"]

Selection (docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.md): a MIGRATE_N8N leaf line with one script,
no --send/--telegram/--alert, no LLM wrapper or model call, and no send, broker module or account read anywhere in the
import closure (advisory_lane_guard.scan_entry). Shape = the 4.4.0 cron-row shadow shape (SW4): scheduler.stage
shadow, dispatch.mode dry_run, allowlist live_arg null; the cron line keeps doing the real work.

Dry-run proof: the REAL executor (scripts/n8n_run_executor.py --once, real allowlist entries with locks moved to
tmp_path, the real registry from the code root) drains a LIVE request for each hermetic lane; the stage clamp turns
it into dry_run, the child prints its offline plan, exit 0, and no receipt or state file appears.
Hermetic: tmp_path ledger/state/locks, no DB variables, repo config read only. build-symbol-profiles-at-0-19 and
drain-discovery-backlog passed the selection but stay with their refactor shard 05-08 proposals (pinned held by
tests/test_refactor_shards_05_08_locks_20261011.py); adopting them is that owner's PR.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import advisory_lane_guard as G  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

REGISTRY = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}
SNAP = (
    (ROOT / "docs/implementation/n8n-maturity/data/disposition_20261015/crontab_20261015.txt").read_text().splitlines()
)

#: lane -> (crontab line 2026-10-15, class, script, lock, lock on the cron line?)
WAVE = {
    "opening-intelligence-render": (796, "report", "scripts/opening_intelligence.py", "/tmp/opening_intel.lock", True),
    "hermes-discovery-scorecard": (
        837,
        "report",
        "scripts/hermes_discovery_scorecard.py",
        "/tmp/hermes_discovery_scorecard.lock",
        False,
    ),
    "wire-advisory-lessons": (606, "learn", "scripts/wire_advisory_lessons.py", "/tmp/wire_lessons.lock", True),
    "incubator-rolloff-engine": (
        269,
        "hygiene",
        "scripts/incubator_rolloff_engine.py",
        "/tmp/incubator_rolloff.lock",
        False,
    ),
    "pattern-extractor": (790, "learn", "scripts/pattern_extractor.py", "/tmp/pattern_extractor.lock", True),
    "goal-gate-bridge": (983, "report", "scripts/cio_gate_measurement_bridge.py", "/tmp/goal_gate_bridge.lock", False),
}
HERMETIC = list(WAVE)


def test_wave_size_and_classes():
    assert len(WAVE) == 6
    assert {v[1] for v in WAVE.values()} == {"report", "learn", "hygiene"}


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_row_is_a_shadow_cron_row_on_its_own_line(lane):
    ln, klass, script, _lock, _on = WAVE[lane]
    row = ROWS[lane]
    s = row["scheduler"]
    assert (
        row["state"] == "ACTIVE" and "generated_by" not in row and row["adopted_reason"].startswith("shadow wave LD-W1")
    )
    assert s["kind"] == "cron" and s["stage"] == "shadow" and s["wave"] == "LD-W1"
    assert s["command_text"] == SNAP[ln - 1] and SNAP[ln - 1].startswith(s["expression"] + " ")
    # scheduler.match hits exactly this one line (a cutover must never retire two lines)
    assert [
        i for i, x in enumerate(SNAP, 1) if (s.get("match") or s["expression"]) in x and not x.lstrip().startswith("#")
    ] == [ln]
    assert row["dispatch"] == {
        "mode": "dry_run",
        "cron": [s["expression"]],
        "tz": "America/New_York",
        "wave": "W4",
        "class": klass,
        "priority": 5,
        "retry_policy": "none",
    }
    assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{lane}_last.json", "key": "ok_at"}
    assert LD.validate_dispatch_block(row) == []
    assert LD.dispatch_eligible(row)[0], LD.dispatch_eligible(row)
    if klass in LD.RATIFICATION_GATED_CLASSES:
        assert LD.r1_class_admission(row) == (True, f"r1_admitted:{klass}")


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_allowlist_entry_is_shadow_only(lane):
    ln, _klass, script, lock, on_line = WAVE[lane]
    e = ALLOW[lane]
    assert e["command"] == ["$PY", script] and e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
    assert not any(t.startswith("--apply") or t in ("--persist", "--write-measurements") for t in e["command"])
    assert e["output_signal"] == ROWS[lane]["output_signal"]["path"] == LD.receipt_signal_path(ROWS[lane])
    assert e["env_allowlist_mode"] == "report" and e["env_report_reason"]
    for name in e["env_names"]:
        assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []
    assert e["market_gate"] is False and 0 < e["timeout_s"] <= 1200 and e["lock_kind"] == "flock"
    assert e["lock"] == lock and ((lock in SNAP[ln - 1]) == on_line)
    if not on_line:
        assert "PROPOSED" in e["source"]


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_contract_is_reviewed_and_import_closure_has_no_send_or_broker(lane):
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and "UNKNOWN" not in json.dumps(c)
    rep = _scan(WAVE[lane][2])
    assert not rep.sends and not rep.direct_sends and rep.problems() == [], (lane, rep.problems(), rep.sends)


def _scan(entry):
    cls = next(
        getattr(G, n) for n in dir(G) if isinstance(getattr(G, n), type) and hasattr(getattr(G, n), "scan_entry")
    )
    return cls().scan_entry(entry)


def test_the_scripts_write_the_receipt_the_rows_name():
    for lane, (_ln, _k, script, _l, _o) in WAVE.items():
        src = (ROOT / script).read_text(encoding="utf-8")
        assert lane in src and ("write_lane_receipt" in src or "write_receipt" in src), lane


# ── hermetic dry-run proof through the real executor ──────────────────────────────────────────────────────────────


def _clean_env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PG", "DATABASE"))}
    env.update(
        TRADEAI_STATE_ROOT=str(tmp_path / "state"),
        SAFE_FLOCK_LOG_DIR=str(tmp_path / "flock-logs"),
        TRADEAI_VENV_PYTHON=sys.executable,
        TRADEAI_N8N_EXECUTOR_WORKERS="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


@pytest.mark.parametrize("lane", HERMETIC)
def test_offline_dry_run_writes_nothing(tmp_path, lane):
    _ln, _k, script, _l, _o = WAVE[lane]
    (tmp_path / "state").mkdir()
    logs_before = {p.name: p.stat().st_mtime for p in (ROOT / "logs").glob("*")} if (ROOT / "logs").is_dir() else {}
    # --dry-run wins over every live switch the cron line carries
    extra = {
        "incubator-rolloff-engine": ["--apply"],
        "goal-gate-bridge": ["--write-measurements"],
        "opening-intelligence-render": ["--persist", "--render"],
    }.get(lane, [])
    r = subprocess.run(
        [sys.executable, script, *extra, "--dry-run"],
        cwd=ROOT,
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY-RUN" in r.stdout
    assert list((tmp_path / "state").rglob("*")) == []
    logs_after = {p.name: p.stat().st_mtime for p in (ROOT / "logs").glob("*")} if (ROOT / "logs").is_dir() else {}
    assert logs_after == logs_before


def test_real_executor_clamps_a_live_request_to_the_offline_dry_run(tmp_path, monkeypatch):
    state, locks = tmp_path / "state", tmp_path / "locks"
    state.mkdir()
    locks.mkdir()
    for k, v in _clean_env(tmp_path).items():
        monkeypatch.setenv(k, v)
    for k in [k for k in os.environ if k.startswith(("DB_", "PG", "DATABASE"))]:
        monkeypatch.delenv(k, raising=False)
    entries = []
    for lane in HERMETIC:
        e = dict(ALLOW[lane])
        e["lock"] = str(locks / Path(e["lock"]).name)
        entries.append(e)
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"schema": "N8nRunAllowlist@v1", "lanes": entries}))
    ledger = tmp_path / "ledger.sqlite"
    led = CoordinationLedger(ledger)
    for i, lane in enumerate(HERMETIC):
        LedgerRunStore(led).request(
            run_id=f"run-ldw1-{i:012d}",
            lane_id=lane,
            mode="live",
            requested_by="test",
            caller_id="n8n-relay",
            now=1_791_000_000.0 + i,
        )
    led.close()
    for _ in HERMETIC:
        assert (
            X.main(
                [
                    "--once",
                    "--ledger",
                    str(ledger),
                    "--allowlist",
                    str(allow),
                    "--code-root",
                    str(ROOT),
                    "--state-root",
                    str(state),
                ]
            )
            == 0
        )
    led = CoordinationLedger(ledger)
    try:
        for i, lane in enumerate(HERMETIC):
            row = LedgerRunStore(led).get(f"run-ldw1-{i:012d}")
            rec = row["receipt"]
            assert row["state"] == "RUN_DONE", (lane, row["state"], rec.get("stdout_tail"))
            assert rec["mode"] == "dry_run" and rec["requested_mode"] == "live" and rec["argv"][-1] == "--dry-run"
            assert rec["stage_clamp"]["reason"] == "stage_shadow" and rec["stage_clamp"]["clamped"] is True
            assert "DRY-RUN" in rec["stdout_tail"]
            assert not (state / "data" / "runtime" / f"{lane}_last.json").exists()
    finally:
        led.close()


# ── receipts on the real path (the three scripts this wave changed) ──────────────────────────────────────────────


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _receipt(state: Path, lane: str) -> dict:
    return json.loads((state / "data" / "runtime" / f"{lane}_last.json").read_text())


def test_incubator_apply_writes_the_receipt_ok_and_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load("incubator_rolloff_engine_ldw1", ROOT / "scripts/incubator_rolloff_engine.py")
    monkeypatch.setattr(mod, "main", lambda: {"rolled_off": 2, "still_active": 5, "checked": 7, "mode": "apply"})
    assert mod._apply_with_receipt() == 0
    r = _receipt(tmp_path, "incubator-rolloff-engine")
    assert r["status"] == "ok" and r["summary"]["rolled_off"] == 2 and r["ok_at"]

    def boom():
        raise SystemExit(1)

    monkeypatch.setattr(mod, "main", boom)
    with pytest.raises(SystemExit):
        mod._apply_with_receipt()
    r2 = _receipt(tmp_path, "incubator-rolloff-engine")
    assert r2["status"] == "failed" and r2["exit"] == 1 and r2["ok_at"] == r["ok_at"]


def test_pattern_extractor_receipt_follows_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())  # no repo logs/ write
    mod = _load("pattern_extractor_ldw1", ROOT / "scripts/pattern_extractor.py")
    monkeypatch.setattr(
        mod,
        "run",
        lambda min_trades, dry_run: {
            "patterns_found": 1,
            "proven": 1,
            "killed": 0,
            "neutral": 0,
            "upserted": 1,
            "errors": 0,
        },
    )
    monkeypatch.setattr(sys, "argv", ["pattern_extractor.py"])
    mod.main()
    assert _receipt(tmp_path, "pattern-extractor")["status"] == "ok"
    monkeypatch.setattr(
        mod,
        "run",
        lambda min_trades, dry_run: {
            "patterns_found": 0,
            "proven": 0,
            "killed": 0,
            "neutral": 0,
            "upserted": 0,
            "errors": 1,
        },
    )
    mod.main()
    assert _receipt(tmp_path, "pattern-extractor")["status"] == "failed"
    os.remove(tmp_path / "data" / "runtime" / "pattern-extractor_last.json")
    monkeypatch.setattr(sys, "argv", ["pattern_extractor.py", "--preview"])
    mod.main()  # the DB preview never writes a receipt
    assert not (tmp_path / "data" / "runtime" / "pattern-extractor_last.json").exists()


def test_goal_gate_bridge_receipt_only_on_write_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load("cio_gate_measurement_bridge_ldw1", ROOT / "scripts/cio_gate_measurement_bridge.py")
    monkeypatch.setattr(mod, "_run", lambda args: 0)
    assert mod.main([]) == 0
    assert not (tmp_path / "data" / "runtime" / "goal-gate-bridge_last.json").exists()
    assert mod.main(["--write-measurements"]) == 0
    assert _receipt(tmp_path, "goal-gate-bridge")["status"] == "ok"
    assert mod.main(["--dry-run", "--write-measurements"]) == 0  # dry run wins, no new write

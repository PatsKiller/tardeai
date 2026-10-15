"""n8n onboarding ONB-1 (operator "N8N Cutover Decision" 2026-10-15): 6 MIGRATE_N8N lanes onto the fabric in SHADOW.

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json",
          "config/n8n_effect_keys.json", "config/n8n_lane_capability_baseline.json",
          "scripts/hermes_discovery_ingestors.py", "scripts/youtube_cookie_health_check.py",
          "scripts/generate_weekly_docx.py", "scripts/strategy_weekly_review.py", "scripts/premarket_watcher.py",
          "scripts/drain_cio_stance_classification.py", "tests/support/dry_run_write_recorder.py"]

Selection (docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv): disposition MIGRATE_N8N, family != F09,
source != registry_systemd, no allowlist entry, a --dry-run flag already in source, dispatch_eligible on the exact cron
line, no in-process model call (an llm-class lane needs the cio-governed-bridge llm_route), no paper/broker execution
on the live path, no direct sender (a send goes through the telegram_alert chokepoint; capability audit new=0).

Every lane's --dry-run was read on its code path; five WROTE or reached the network/DB and were fixed here so an explicit
--dry-run is an offline plan before env, DB, log file, network, send or receipt (the old behaviour is --preview):
premarket-watcher (log file + pipeline_runs INSERT + EDGAR/StockTwits/Yahoo), strategy-weekly-review (logs mkdir + log
file + pipeline_runs + snapshot rewrite + a possible Telegram), generate-weekly-docx (3 chart PNGs), youtube-cookie-
health-check (opened the cookie jar + DB), hermes-discovery-ingestors (env + DB). cio-stance-classification-drain was
already write-free. Each lane now writes its LaneRunReceipt@v1 (with produced_count) on a real run.

Shape = the 4.4.0 cron-row shadow shape (SW4 / LD-W1): scheduler.stage shadow, dispatch.mode dry_run, allowlist
live_arg null; the cron line keeps doing the real work.

Dry-run proof: (1) each script runs under tests/support/dry_run_write_recorder.py, a CPython audit hook that records
every write-mode open, filesystem mutation, socket connect, subprocess and sqlite connect, with the cron line's live
switches added: zero events, no DB/HTTP/send module imported; (2) the REAL executor (scripts/n8n_run_executor.py
--once) drains a LIVE request per lane, the stage clamp runs it dry_run, RUN_DONE, and no receipt or state file appears.
Hermetic: tmp_path ledger/state/locks, no DB variables, fake DB/send modules for the receipt tests, repo config read only.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import audit_lane_transitive_capabilities as CAP  # noqa: E402
from scripts import check_n8n_workflow_framework as FW  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

REGISTRY = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}
EFFECTS = json.loads((ROOT / "config/n8n_effect_keys.json").read_text())["lanes"]
SNAP = (
    (ROOT / "docs/implementation/n8n-maturity/data/disposition_20261015/crontab_20261015.txt").read_text().splitlines()
)
RECORDER = ROOT / "tests/support/dry_run_write_recorder.py"

#: lane -> (crontab line 2026-10-15, class, script, lock, lock on the cron line?, effects, cron live switches)
WAVE = {
    "hermes-discovery-ingestors": (
        687,
        "ingest",
        "scripts/hermes_discovery_ingestors.py",
        "/tmp/hermes_discovery_ingest.lock",
        True,
        ["append"],
        ["--scheduled", "--json"],
    ),
    "youtube-cookie-health-check": (
        397,
        "monitor",
        "scripts/youtube_cookie_health_check.py",
        "/tmp/youtube_cookie_health_check.lock",
        True,
        ["send"],
        ["--always"],
    ),
    "generate-weekly-docx": (
        155,
        "report",
        "scripts/generate_weekly_docx.py",
        "/tmp/weekly_docx.lock",
        True,
        ["send"],
        ["--format", "all"],
    ),
    "strategy-weekly-review": (
        279,
        "learn",
        "scripts/strategy_weekly_review.py",
        "/tmp/strategy_weekly_review.lock",
        False,
        ["append", "send"],
        [],
    ),
    "premarket-watcher": (
        264,
        "ingest",
        "scripts/premarket_watcher.py",
        "/tmp/premarket_watcher.lock",
        False,
        ["append", "send"],
        [],
    ),
    "cio-stance-classification-drain": (
        987,
        "pipeline",
        "scripts/drain_cio_stance_classification.py",
        "/tmp/cio_stance_classify.lock",
        True,
        ["append"],
        ["--apply"],
    ),
}


#: Rows that adopt their refactor shard 05 proposal unchanged (tests/test_refactor_shard_05_20261011.py pins the shape):
#: scheduler.wave R2-05 and the allowlist command = the frozen cron argv (tests/fixtures/refactor_shard_05/cron_argv.json),
#: whose --apply the --dry-run wins over. The build-symbol-profiles-at-0-19 lane repair (2026-10-15) is the precedent.
SHARD05 = {"cio-stance-classification-drain": ["--apply"]}


def _sched_wave(lane: str) -> str:
    return "R2-05" if lane in SHARD05 else "ONB-1"


def test_wave_size_and_classes():
    assert len(WAVE) == 6
    assert {v[1] for v in WAVE.values()} == {"ingest", "monitor", "report", "learn", "pipeline"}


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_row_is_a_shadow_cron_row_on_its_own_line(lane):
    ln, klass, _script, _lock, _on, _fx, _live = WAVE[lane]
    row = ROWS[lane]
    s = row["scheduler"]
    assert row["state"] == "ACTIVE" and "generated_by" not in row
    assert row["adopted_reason"].startswith("n8n onboarding ONB-1") and row["adopted_on"] == "2026-10-15"
    assert s["kind"] == "cron" and s["stage"] == "shadow" and s["wave"] == _sched_wave(lane)
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
    assert LD.dispatch_eligible(row) == (True, "eligible")
    want = f"r1_admitted:{klass}" if klass in LD.RATIFICATION_GATED_CLASSES else "pre_r1_class"
    assert LD.r1_class_admission(row, ALLOW[lane]) == (True, want)


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_allowlist_entry_is_shadow_only(lane):
    ln, _klass, script, lock, on_line, _fx, live = WAVE[lane]
    e = ALLOW[lane]
    assert e["command"] == ["$PY", script, *SHARD05.get(lane, [])]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
    if lane not in SHARD05:
        assert not set(live) & set(e["command"] + e["dry_run_arg"])
    assert e["output_signal"] == ROWS[lane]["output_signal"]["path"] == LD.receipt_signal_path(ROWS[lane])
    assert e["env_allowlist_mode"] == "report" and e["env_report_reason"]
    for name in e["env_names"]:
        assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []
    assert e["market_gate"] is False and 0 < e["timeout_s"] <= 1200 and e["lock_kind"] == "flock"
    assert e["lock"] == lock and ((lock in SNAP[ln - 1]) == on_line)
    if not on_line:
        assert "PROPOSED" in e["source"]
    else:  # canary-ready on the lock: the allowlist lock equals the cron line's flock lock
        canary = json.loads(json.dumps(ROWS[lane]))
        canary["scheduler"]["stage"], canary["dispatch"]["mode"] = "canary", "live"
        assert LD.r1_canary_lock_matches(canary, dict(e, live_arg=[] if lane in SHARD05 else live))[0]


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_contract_is_reviewed_with_an_expected_output_rule(lane):
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and "UNKNOWN" not in json.dumps(c)
    assert H.validate_contract(c) == [] and H.unknown_fields(c) == []
    assert not [x for x in c["connects_to"] if x["kind"] == "inventory_text"]
    assert c["evidence"]["receipt"] == ALLOW[lane]["output_signal"]
    assert c["baseline"]["class"] == WAVE[lane][1] and c["baseline"]["timeout_s"] == ALLOW[lane]["timeout_s"]
    assert c["owner"] == ROWS[lane]["owner"]
    assert FW._check_expected_output(c)["status"] == "pass"  # FW-M6
    eo = c["expected_output"]
    assert eo["schema"] == "N8nExpectedOutput@v1" and eo["produced_field"] == "produced_count"
    # declared only: the output receipt v2 switch is never set by an onboarding wave
    assert "output_receipt" not in json.dumps(ALLOW[lane]) and "NOT YET" in c["evidence"]["expected_output_basis"]


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_effect_key_is_staged_and_arms_neither_side(lane):
    spec = EFFECTS[lane]
    assert spec["process"] == lane and spec["input_version"] == "v1" and spec["slot"] == "scheduled_minute"
    assert spec["schedule"] == ROWS[lane]["scheduler"]["expression"] and spec["slot_tz"] == "America/New_York"
    assert spec["effects"] == WAVE[lane][5] and spec["idempotent_today"]
    assert spec["cron_claim"] is False and spec["n8n_claim"] is False


@pytest.fixture(scope="module")
def caps():
    return CAP.audit()


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_no_direct_sender_and_broker_reach_is_lazy_only(lane, caps):
    """DD01 operator ruling 2026-10-15: lazy transitive broker reach is accepted (trading lock); direct_sender never."""
    got = caps[lane]["capabilities"]
    assert "direct_sender" not in got
    for c in ("broker_module", "order_placement"):
        if c in got:
            assert got[c]["at_import"] is False, (lane, c)
    assert CAP.violations({lane: caps[lane]}, CAP.load_baseline())["new"] == []


def test_the_scripts_write_the_receipt_the_rows_name():
    for lane, spec in WAVE.items():
        src = (ROOT / spec[2]).read_text(encoding="utf-8")
        assert lane in src and "write_lane_receipt" in src and "produced_count" in src, lane


# ── dry-run proof 1: the audit-hook write recorder ────────────────────────────────────────────────────────────────


def _clean_env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PG", "DATABASE", "TELEGRAM"))}
    env.update(
        TRADEAI_STATE_ROOT=str(tmp_path / "state"),
        SAFE_FLOCK_LOG_DIR=str(tmp_path / "flock-logs"),
        TRADEAI_VENV_PYTHON=sys.executable,
        TRADEAI_N8N_EXECUTOR_WORKERS="1",
        TRADEAI_YOUTUBE_COOKIE_FILE=str(tmp_path / "absent" / "youtube_cookies.txt"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def _record(tmp_path: Path, script: str, args: list[str]) -> dict:
    out = tmp_path / "record.json"
    r = subprocess.run(
        [sys.executable, str(RECORDER), str(out), script, *args],
        cwd=ROOT,
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    rec = json.loads(out.read_text())
    rec["stdout"], rec["returncode"] = r.stdout, r.returncode
    return rec


@pytest.mark.parametrize("lane", sorted(WAVE))
def test_offline_dry_run_records_zero_writes(tmp_path, lane):
    _ln, _k, script, _l, _o, _fx, live = WAVE[lane]
    (tmp_path / "state").mkdir()
    # --dry-run wins over every live switch the cron line carries
    rec = _record(tmp_path, script, [*live, "--dry-run"])
    assert rec["returncode"] == 0 and rec["exit_code"] == 0, rec
    assert f"DRY-RUN {lane}:" in rec["stdout"]
    assert rec["events"] == {"file_writes": [], "fs_mutations": [], "network": [], "subprocess": [], "sqlite": []}, rec
    assert rec["watched_modules_loaded"] == [], rec
    assert list((tmp_path / "state").rglob("*")) == []


def test_the_recorder_does_record_writes_network_and_children(tmp_path):
    """The proof's own negative control: a script that writes, mkdirs, connects and spawns is caught on each."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import os, socket, subprocess, sys\n"
        f"os.makedirs({str(tmp_path / 'd')!r}, exist_ok=True)\n"
        f"open({str(tmp_path / 'd' / 'f.txt')!r}, 'a').write('x')\n"
        "s = socket.socket()\n"
        "try:\n    s.connect(('127.0.0.1', 9))\nexcept OSError:\n    pass\n"
        "subprocess.run([sys.executable, '-c', 'pass'])\n"
    )
    rec = _record(tmp_path, str(bad), [])
    ev = rec["events"]
    assert ev["file_writes"] and ev["fs_mutations"] and ev["network"] and ev["subprocess"], ev


# ── dry-run proof 2: the real executor clamps a LIVE request to the offline dry run ───────────────────────────────


def test_real_executor_clamps_a_live_request_to_the_offline_dry_run(tmp_path, monkeypatch):
    state, locks = tmp_path / "state", tmp_path / "locks"
    state.mkdir()
    locks.mkdir()
    for k, v in _clean_env(tmp_path).items():
        monkeypatch.setenv(k, v)
    for k in [k for k in os.environ if k.startswith(("DB_", "PG", "DATABASE", "TELEGRAM"))]:
        monkeypatch.delenv(k, raising=False)
    lanes = sorted(WAVE)
    entries = []
    for lane in lanes:
        e = dict(ALLOW[lane])
        e["lock"] = str(locks / Path(e["lock"]).name)
        entries.append(e)
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"schema": "N8nRunAllowlist@v1", "lanes": entries}))
    ledger = tmp_path / "ledger.sqlite"
    led = CoordinationLedger(ledger)
    for i, lane in enumerate(lanes):
        LedgerRunStore(led).request(
            run_id=f"run-onb1-{i:012d}",
            lane_id=lane,
            mode="live",
            requested_by="test",
            caller_id="n8n-relay",
            now=1_791_000_000.0 + i,
        )
    led.close()
    argv = [
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
    for _ in lanes:
        assert X.main(argv) == 0
    led = CoordinationLedger(ledger)
    try:
        for i, lane in enumerate(lanes):
            row = LedgerRunStore(led).get(f"run-onb1-{i:012d}")
            rec = row["receipt"]
            assert row["state"] == "RUN_DONE", (lane, row["state"], rec.get("stdout_tail"))
            assert rec["mode"] == "dry_run" and rec["requested_mode"] == "live" and rec["argv"][-1] == "--dry-run"
            assert rec["stage_clamp"]["reason"] == "stage_shadow" and rec["stage_clamp"]["clamped"] is True
            assert f"DRY-RUN {lane}:" in rec["stdout_tail"]
            assert not (state / "data" / "runtime" / f"{lane}_last.json").exists()
    finally:
        led.close()


# ── receipts on the real path (the scripts this wave changed) ─────────────────────────────────────────────────────


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _receipt(state: Path, lane: str) -> dict:
    doc = json.loads((state / "data" / "runtime" / f"{lane}_last.json").read_text())
    # the count rides ADDITIVELY on the v1 document (output={...}); v1 readers match the schema exactly
    assert doc["schema"] == "LaneRunReceipt@v1" and doc["output_fields"] == "LaneRunReceipt@v2", doc
    return doc


@pytest.fixture
def fake_db_modules(monkeypatch):
    """CI shards without the DB driver / dotenv / requests: the modules import them at top level."""
    pg = types.ModuleType("psycopg2")
    pg.extras = types.ModuleType("psycopg2.extras")
    pg.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no DB in a receipt test"))
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: False
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())  # no repo logs/ write
    sent = []
    monkeypatch.setitem(
        sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=lambda *a, **k: sent.append((a, k)) or True)
    )
    return sent


def test_strategy_weekly_review_receipt_and_preview(tmp_path, monkeypatch, fake_db_modules):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load("strategy_weekly_review_onb1", ROOT / "scripts/strategy_weekly_review.py")
    seen = []
    monkeypatch.setattr(
        mod, "run", lambda dry_run, send_tg: seen.append(dry_run) or {"strategies": 4, "transitions": 1, "errors": 0}
    )
    monkeypatch.setattr(sys, "argv", ["strategy_weekly_review.py"])
    assert mod.main() == 0
    r = _receipt(tmp_path, "strategy-weekly-review")
    assert r["status"] == "ok" and r["produced_count"] == 4 and r["ok_at"]
    monkeypatch.setattr(mod, "run", lambda dry_run, send_tg: {"strategies": 0, "transitions": 0, "errors": 1})
    assert mod.main() == 1  # honest exit: a DB/review error is a failed run (was exit 0)
    r2 = _receipt(tmp_path, "strategy-weekly-review")
    assert r2["status"] == "failed" and r2["ok_at"] == r["ok_at"]
    os.remove(tmp_path / "data" / "runtime" / "strategy-weekly-review_last.json")
    monkeypatch.setattr(
        mod, "run", lambda dry_run, send_tg: seen.append(dry_run) or {"strategies": 4, "transitions": 0, "errors": 0}
    )
    monkeypatch.setattr(sys, "argv", ["strategy_weekly_review.py", "--preview"])
    assert mod.main() == 0 and seen[-1] is True  # the DB preview runs read-only and writes no receipt
    assert not (tmp_path / "data" / "runtime" / "strategy-weekly-review_last.json").exists()


def test_generate_weekly_docx_receipt_counts_exports_and_fails_honestly(tmp_path, monkeypatch, fake_db_modules):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_PORTFOLIO_REPORTS_ROOT", str(tmp_path / "reports"))
    mod = _load("generate_weekly_docx_onb1", ROOT / "scripts/generate_weekly_docx.py")
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_portfolio_reports_root", lambda: tmp_path / "reports")
    out = tmp_path / "x.docx"
    out.write_text("doc")
    results = {"docx": {"ok": True, "path": str(out), "filename": "x.docx", "size_kb": 1}}
    monkeypatch.setitem(
        sys.modules,
        "analyst_report_builder",
        types.SimpleNamespace(build_weekly_review=lambda: {"k": 1}, save_report_json=lambda report, stem: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "report_export",
        types.SimpleNamespace(
            export_report=lambda report, fmt, output_stem: results.get(fmt, {"ok": False, "error": "boom"})
        ),
    )
    monkeypatch.setattr(sys, "argv", ["generate_weekly_docx.py"])
    assert mod.main() == 0
    r = _receipt(tmp_path, "generate-weekly-docx")
    assert r["status"] == "ok" and r["produced_count"] == 1 and len(fake_db_modules) == 1
    monkeypatch.setattr(sys, "argv", ["generate_weekly_docx.py", "--format", "all"])  # pdf export fails
    assert mod.main() == 1
    r2 = _receipt(tmp_path, "generate-weekly-docx")
    assert r2["status"] == "failed" and r2["ok_at"] == r["ok_at"] and len(fake_db_modules) == 1  # no false notice


def test_premarket_watcher_receipt_counts_activity(tmp_path, monkeypatch, fake_db_modules):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load("premarket_watcher_onb1", ROOT / "scripts/premarket_watcher.py")
    monkeypatch.setitem(
        sys.modules,
        "pipeline_registry",
        types.SimpleNamespace(
            run_start=lambda name: None, run_complete=lambda rid: None, run_fail=lambda rid, err: None
        ),
    )
    monkeypatch.setattr(mod, "main", lambda: ({"symbols_checked": 12, "symbols_with_activity": 0, "alerts": []}, False))
    monkeypatch.setattr(sys, "argv", ["premarket_watcher.py"])
    assert mod._run_with_receipt() == 0
    r = _receipt(tmp_path, "premarket-watcher")
    assert r["status"] == "ok" and r["produced_count"] == 0 and r["empty_reason"] == "no_new_input"

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "main", boom)
    with pytest.raises(RuntimeError):
        mod._run_with_receipt()
    assert _receipt(tmp_path, "premarket-watcher")["status"] == "failed"


def test_youtube_live_path_writes_both_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load("youtube_cookie_health_check_onb1", ROOT / "scripts/youtube_cookie_health_check.py")

    def fake_main():
        mod._LAST.update({"status": "green", "would_send": False, "sent": False})
        return 0

    monkeypatch.setattr(mod, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["youtube_cookie_health_check.py"])
    assert mod._live_with_lane_receipt() == 0
    r = _receipt(tmp_path, "youtube-cookie-health-check")
    assert r["status"] == "ok" and r["produced_count"] == 1 and r["summary"]["status"] == "green"
    assert "cookie_path" not in r["summary"]  # status only, no jar location detail in the lane receipt
    assert (tmp_path / "data" / "runtime" / "youtube_cookie_health_check_last.json").exists()  # legacy receipt kept


def test_cio_stance_and_ingestors_receipts_carry_produced_count():
    for script, needle in (
        ("scripts/drain_cio_stance_classification.py", '"produced_count": int(res["applied"])'),
        ("scripts/hermes_discovery_ingestors.py", '"produced_count": produced'),
    ):
        assert needle in (ROOT / script).read_text(encoding="utf-8"), script

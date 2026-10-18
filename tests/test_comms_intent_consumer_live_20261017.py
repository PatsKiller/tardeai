"""comms-intent consumer LIVE on the n8n fabric at */5 (operator decision D2 2026-10-17, "Queue reader first").

Pins the config that makes lane ``n8n-comms-intent-consumer`` a dispatch-live n8n lane exactly like its precedent
heartbeat-watch (registry stage canary + dispatch live, own flock lock, allowlist live_arg ``--apply``, REVIEWED
health contract with an output verdict, staged effect key that claims nothing), proves the consumer's
LaneRunReceipt@v2 output fields give the executor a ``produced`` / ``empty_allowed`` verdict and that a rerun is
idempotent, and runs the operator packet (docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh) against
fakes. Hermetic: tmp ledgers, tmp state root, fake systemctl/docker/proc; no live ledger, service, n8n or Telegram.

COVERS = ["scripts/n8n_comms_intent_consumer.py", "config/lane_registry.json", "config/n8n_run_allowlist.json",
          "config/n8n_health_contracts.json", "config/n8n_effect_keys.json",
          "docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh"]
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_comms_intent_consumer as CLI  # noqa: E402
from scripts import n8n_workflow_templates as T  # noqa: E402
from scripts.lib import effect_claim as FX  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_fabric_store as F  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib import n8n_output_verdict as OV  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

LANE = "n8n-comms-intent-consumer"
CONFIG = ROOT / "config"
PACKET = ROOT / "docs" / "ops" / "packets" / "comms-intent-consumer-live-20261017"
SCRIPT = PACKET / "cutover.sh"
ROUTES_PATH = CONFIG / "n8n_comms_intent_routes.json"
NOW = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)  # Sat 10:00 ET


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def _registry_row() -> dict:
    return {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}[LANE]


def _allow_entry() -> dict:
    return {e["lane_id"]: e for e in _load("n8n_run_allowlist.json")["lanes"]}[LANE]


def _contract() -> dict:
    return {c["id"]: c for c in _load("n8n_health_contracts.json")["contracts"]}[LANE]


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    """The Telegram chokepoints are stubs that fail: no path in this file may reach one."""
    calls: list[tuple] = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called")

    fake_alert = types.ModuleType("telegram_alert")
    fake_alert.send_telegram = boom
    fake_alert.record_operator_message = boom
    for name in ("telegram_alert", "scripts.telegram_alert"):
        monkeypatch.setitem(sys.modules, name, fake_alert)
    yield
    assert calls == []


# ── 1. config pins (precedent: heartbeat-watch) ───────────────────────────────────────────────────────────────────


def test_registry_row_is_a_dispatch_live_n8n_lane_at_canary_like_heartbeat_watch():
    row = _registry_row()
    hb = {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}["heartbeat-watch"]
    assert row["scheduler"] == {
        "kind": "n8n",
        "expression": "dispatcher",
        "match": "scripts/n8n_comms_intent_consumer.py",
        "cadence": "*/5 * * * *",
        "stage": "canary",
        "wave": "W1",
    }
    assert set(row["scheduler"]) == set(hb["scheduler"])  # same shape as the precedent
    assert row["dispatch"] == {
        "mode": "live",
        "cron": ["*/5 * * * *"],
        "tz": "America/New_York",
        "wave": "W1",
        "class": "monitor",
        "priority": 1,
        "retry_policy": "transient-2",
    }
    assert row["state"] == "ACTIVE" and row["expected_cadence_hours"] == hb["expected_cadence_hours"]
    assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{LANE}_last.json", "key": "ok_at"}
    assert "recommendation" not in row and "stay_on_cron" not in row  # never KEEP_ON_CRON: it is not a sender
    assert LD.dispatch_eligible(row) == (True, "eligible")
    assert LD.parse_dispatch_block(row).klass == "monitor"  # a pre-R1 class: no ratification gate
    assert LD.forbidden_hits(row) == []


def test_allowlist_entry_runs_the_real_apply_flag_under_its_own_flock_lock():
    e = _allow_entry()
    assert e["command"] == ["$PY", "scripts/n8n_comms_intent_consumer.py"]
    assert e["live_arg"] == ["--apply"] and e["dry_run_arg"] == ["--dry-run"]
    assert e["lock"] == "/tmp/tradeai_n8n_comms_intent_consumer.lock" and e["lock_kind"] == "flock"
    assert e["timeout_s"] == 60 and e["market_gate"] is False
    assert e["output_receipt"] == "v2"  # opts into the executor's output verdict
    assert e["env_allowlist_mode"] == "enforce"
    assert e["output_signal"] == _registry_row()["output_signal"]["path"]
    # the flags are the consumer's real, mutually exclusive argparse options
    src = (ROOT / "scripts" / "n8n_comms_intent_consumer.py").read_text()
    assert 'g.add_argument("--apply"' in src and 'g.add_argument("--dry-run"' in src
    assert CLI.main(["--apply", "--dry-run"]) == 2


def test_the_gateway_emits_a_live_d_key_at_each_five_minute_slot_and_demotes_off_the_live_list(tmp_path, monkeypatch):
    rows = [_registry_row()]
    allow = {LANE: _allow_entry()}
    policies = RP.load_policies(CONFIG / "n8n_retry_policies.json")
    led = CoordinationLedger(tmp_path / "ledger.sqlite")
    try:
        store = LedgerRunStore(led)
        monkeypatch.setenv("TRADEAI_N8N_RELAY_LIVE_LANES", f"heartbeat-watch {LANE}")
        due = D.compute_due(rows, allow, policies, store, NOW, source="schedule")
        assert [(i["lane_id"], i["mode"], i["idempotency_key"]) for i in due["items"]] == [
            (LANE, "live", f"d:{LANE}:live:20261017T1000")
        ]
        monkeypatch.setenv("TRADEAI_N8N_RELAY_LIVE_LANES", "heartbeat-watch")
        due = D.compute_due(rows, allow, policies, store, NOW, source="schedule")
        assert [(i["mode"], i["reason"]) for i in due["items"]] == [("dry_run", "relay_live_not_enabled")]
    finally:
        led.close()


def test_the_health_contract_is_reviewed_at_canary_with_an_output_verdict_matching_the_code():
    c = _contract()
    assert c["status"] == "REVIEWED" and c["stage"] == "canary" and c["workflow_id"] == "dispatcher"
    assert H.validate_contract(c) == [] and H.unknown_fields(c) == []
    eo = c["expected_output"]
    assert OV.validate_expected_output(eo) == []
    assert eo["rule"] == "empty_allowed" and eo["produced_field"] == "produced_count"
    assert set(eo["empty_allowed_reasons"]) == {CLI.EMPTY_NO_INPUT, CLI.EMPTY_ALL_REFUSED}
    assert CLI.SKIP_DEPENDENCY in eo["fatal_skip_reasons"]
    # never PAGE: the P1 path does not depend on n8n (§24.1)
    assert c["alerting"]["failed"]["notifier_priority"] == "P2" and eo["on_violation"]["notifier_priority"] == "P2"
    assert c["baseline"]["timeout_s"] == _allow_entry()["timeout_s"]
    res = H.check(_load("n8n_health_contracts.json"), _load("lane_registry.json"), H.load_json(H.GENERIC_INDEX_PATH))
    assert not [e for e in res["errors"] if LANE in e]


def test_no_effect_key_no_owner_row_needed():
    # No cron side to fence, and every live effect is idempotent per intent (CAS); tests/support/
    # comms_intent_consumer_live.py records why the canary-effect-key audit leaves the lane unkeyed.
    assert LANE not in _load("n8n_effect_keys.json")["lanes"]
    assert LANE not in FX.load_effect_config(CONFIG / "n8n_effect_keys.json")  # the executor claims nothing for it
    from tests.support import comms_intent_consumer_live as CIL

    assert CIL.LIVE == (LANE,)


def test_no_workflow_file_changes_the_dispatcher_fires_the_lane():
    files = T.render_generic()
    out = T.GENERIC_DEFAULT_OUT
    assert all((out / rel).read_bytes() == text.encode("utf-8") for rel, text in files.items())
    assert LANE not in T.SYSTEM_FILTER_LANES  # nothing in a workflow spells the lane id
    assert all(LANE not in text for text in files.values())


def test_the_superseded_shadow_draft_stays_valid_and_names_the_same_lane():
    draft = json.loads((ROOT / "docs/ops/packets/n8n-comms-intent-consumer-20261015/health_contract_draft.json").read_text())
    draft.pop("_note")
    assert H.validate_contract(draft) == [] and draft["id"] == LANE


# ── 2. output verdict + idempotency through the real CLI ──────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    ledger = state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    led = CoordinationLedger(ledger)
    store = F.CommsIntentStore(led, routes_path=ROUTES_PATH)
    yield types.SimpleNamespace(state=state, ledger=ledger, led=led, store=store, tmp=tmp_path)
    led.close()


def _accept(env, wf: str, ex: str, at: datetime, kind: str = "workflow_error") -> dict:
    body = {
        "domain": "fabric",
        "kind": kind,
        "subject": f"workflow {wf} failed at Assert process ({ex})",
        "summary": f"{wf}: failed step(s) ({ex})",
        "workflow_id": wf,
        "execution_id": ex,
        "node": "Assert process",
    }
    return env.store.accept(body, caller_id="n8n-relay", now=at.timestamp())


def _apply(env, monkeypatch, run_id: str, now: datetime = NOW) -> tuple[int, dict]:
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    rc = CLI.main(["--apply", "--ledger", str(env.ledger), "--state-root", str(env.state), "--now", now.isoformat()])
    path = R.attempt_receipt_path(LANE, run_id, env.state)
    return rc, json.loads(path.read_text())


def _verdict(doc: dict, run_id: str) -> dict:
    return OV.evaluate(_contract()["expected_output"], doc, run_id=run_id, lane_id=LANE, mode="live")


def _q(env, sql: str) -> list[tuple]:
    conn = sqlite3.connect(env.ledger)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_a_live_run_over_queued_intents_is_produced_and_a_rerun_is_empty_allowed_and_changes_nothing(env, monkeypatch):
    t0 = NOW - timedelta(hours=20)
    for i, ex in enumerate(("35360", "36411", "40711", "41010")):
        _accept(env, "tradeai-fabric-hermes-learning", ex, t0 + timedelta(hours=i * 5))
    rid1 = f"d:{LANE}:live:20261017T1000"
    rc, doc = _apply(env, monkeypatch, rid1)
    assert rc == 0 and doc["schema"] == "LaneRunReceipt@v2" and doc["run_id"] == rid1
    assert doc["produced_count"] == 4 and doc["attempted_count"] == 4 and doc["empty_reason"] is None
    assert _verdict(doc, rid1)["verdict"] == "produced"
    last = json.loads(R.receipt_path(LANE, env.state).read_text())
    assert last["schema"] == "LaneRunReceipt@v1" and last["output_fields"] == "LaneRunReceipt@v2"  # v1 readers kept
    assert last["ok_at"] is not None
    # one incident for the workflow, all four intents DONE and pointing at it
    inc = _q(env, "SELECT incident_key, fanin_item, state, count FROM comms_intent_incidents")
    assert [(r[1], r[2], r[3]) for r in inc] == [("wferr:tradeai-fabric-hermes-learning", "OPEN", 4)]
    assert _q(env, "SELECT state, COUNT(*) FROM comms_intents GROUP BY state") == [("DONE", 4)]
    assert _q(env, "SELECT COUNT(DISTINCT incident_key) FROM comms_intent_consumption WHERE state='DONE'") == [(1,)]
    before = _q(env, "SELECT * FROM comms_intent_incidents") + _q(env, "SELECT * FROM comms_intent_consumption")
    rid2 = f"d:{LANE}:live:20261017T1005"
    rc, doc2 = _apply(env, monkeypatch, rid2, NOW + timedelta(minutes=5))
    assert rc == 0 and doc2["produced_count"] == 0 and doc2["empty_reason"] == CLI.EMPTY_NO_INPUT
    assert _verdict(doc2, rid2)["verdict"] == "empty_allowed"
    after = _q(env, "SELECT * FROM comms_intent_incidents") + _q(env, "SELECT * FROM comms_intent_consumption")
    assert after == before  # idempotent per intent: the rerun changed no row


def test_an_empty_queue_is_empty_allowed(env, monkeypatch):
    rid = f"d:{LANE}:live:20261017T1000"
    rc, doc = _apply(env, monkeypatch, rid)
    assert rc == 0 and doc["produced_count"] == 0 and doc["attempted_count"] == 0
    assert _verdict(doc, rid) == {**_verdict(doc, rid), "verdict": "empty_allowed", "empty_reason": "no_new_input"}


def test_a_run_whose_only_claims_were_refused_is_empty_allowed_not_a_p1(env, monkeypatch, tmp_path):
    routes = json.loads(ROUTES_PATH.read_text())
    _accept(env, "tradeai-fabric-error-probe", "1", NOW - timedelta(minutes=3))
    # the route is withdrawn after the intent was queued: the consumer refuses it (terminal, dead-lettered by the fan-in)
    routes["routes"] = [r for r in routes["routes"] if (r.get("domain"), r.get("kind")) != ("fabric", "workflow_error")]
    alt = tmp_path / "routes.json"
    alt.write_text(json.dumps(routes))
    monkeypatch.setenv("TRADEAI_RUN_ID", f"d:{LANE}:live:20261017T1000")
    rc = CLI.main(["--apply", "--ledger", str(env.ledger), "--state-root", str(env.state), "--now", NOW.isoformat(),
                   "--routes", str(alt)])
    doc = json.loads(R.attempt_receipt_path(LANE, f"d:{LANE}:live:20261017T1000", env.state).read_text())
    assert rc == 0 and doc["produced_count"] == 0 and doc["skipped_reasons"] == {"intent_refused": 1}
    assert doc["empty_reason"] == CLI.EMPTY_ALL_REFUSED
    assert _verdict(doc, f"d:{LANE}:live:20261017T1000")["verdict"] == "empty_allowed"


def test_a_missing_ledger_is_the_fatal_skip_and_fails_the_run(tmp_path, monkeypatch):
    state = tmp_path / "state"
    rid = f"d:{LANE}:live:20261017T1000"
    monkeypatch.setenv("TRADEAI_RUN_ID", rid)
    rc = CLI.main(["--apply", "--ledger", str(tmp_path / "absent.sqlite"), "--state-root", str(state),
                   "--now", NOW.isoformat()])
    doc = json.loads(R.attempt_receipt_path(LANE, rid, state).read_text())
    assert rc == 1 and doc["status"] == "failed" and doc["skipped_reasons"] == {CLI.SKIP_DEPENDENCY: 1}
    assert _verdict(doc, rid)["verdict"] == "empty_violation"
    assert not (tmp_path / "absent.sqlite").exists()


def test_lane_output_counts_are_consistent():
    assert CLI.lane_output({"done": 2, "refreshed": 1, "refused": 1, "claim_lost": 0, "failed_transient": 0}) == {
        "produced_count": 3, "attempted_count": 4, "skipped_reasons": {"intent_refused": 1}, "empty_reason": None}
    assert CLI.lane_output({"done": 0, "refreshed": 0, "refused": 0, "claim_lost": 0, "failed_transient": 1})[
        "empty_reason"] is None  # a transient failure is never an allowed empty run (and the run exits 1)


def test_the_dry_run_still_writes_nothing(env, capsys):
    _accept(env, "tradeai-fabric-hermes-learning", "1", NOW - timedelta(minutes=3))
    before = env.ledger.read_bytes()
    assert CLI.main(["--dry-run", "--ledger", str(env.ledger), "--state-root", str(env.state),
                     "--now", NOW.isoformat()]) == 0
    assert env.ledger.read_bytes() == before
    assert not R.receipt_path(LANE, env.state).exists()
    assert not (env.state / "data" / "runtime" / "lane_attempts").exists()
    assert "DRY-RUN " in capsys.readouterr().out


# ── 3. the operator packet against fakes ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pk(tmp_path):
    """Fake home for cutover.sh: live list, notifier receipt, systemctl, docker and /proc."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    calls = tmp_path / "systemctl.calls"
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {calls}\n'
        'case "$*" in *"show -p MainPID"*) echo 4242 ;; *is-active*) echo active ;; esac\n'
    )
    (bin_dir / "docker").write_text("#!/usr/bin/env bash\necho true\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text("# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin\n")
    live.chmod(0o600)
    notifier = tmp_path / "incident_notifier_last.json"
    notifier.write_text(json.dumps({"cap": {"day": "2026-10-17", "used": 3, "limit": 24}}))
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "PY": sys.executable,
        "SERVED": str(ROOT),
        "STATE": str(state),
        "LEDGER": str(state / "data" / "governance" / "n8n_coordination_ledger.sqlite"),
        "LIVE_LANES_ENV": str(live),
        "NOTIFIER_RECEIPT": str(notifier),
        "SYSTEMCTL_BIN": str(bin_dir / "systemctl"),
        "DOCKER_BIN": str(bin_dir / "docker"),
        "PROC_ROOT": str(proc),
        "NOW_HM": "1000",
        "RESTART_SETTLE_S": "0",
    }

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                              timeout=120, cwd=str(tmp_path))

    return types.SimpleNamespace(run=run, live=live, proc=proc, calls=calls, notifier=notifier, state=state,
                                 env=env, tmp=tmp_path)


def _env_proc(pk, carries: bool) -> None:
    text = "PATH=/usr/bin\0TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin"
    (pk.proc / "4242" / "environ").write_text(text + (f" {LANE}\0" if carries else "\0"))


def test_packet_is_dry_by_default_set_f_and_never_deletes_or_touches_cron_or_workflows():
    src = SCRIPT.read_text()
    assert src.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in src and "\nset -f\n" in src
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for bad in ("rm ", "crontab", "n8n import", "import:workflow", "update:workflow", "DELETE ", "DROP ", "--force",
                "deactivate", "UPDATE ", "INSERT "):
        assert bad not in code, bad
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_packet_passes_shellcheck():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_relay_dry_run_changes_nothing(pk):
    before = pk.live.read_bytes()
    p = pk.run("relay")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DRY RUN" in p.stdout and f"adds: {LANE}" in p.stdout
    assert pk.live.read_bytes() == before and not pk.calls.exists()


def test_relay_apply_needs_a_grant_and_a_delivery_window(pk):
    p = pk.run("relay", "--apply")
    assert p.returncode == 1 and "TRADEAI_FABRIC_GRANT not set" in p.stdout
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1", NOW_HM="2230")
    assert p.returncode == 1 and "quiet_hours:2230" in p.stdout
    pk.notifier.write_text(json.dumps({"cap": {"day": "2026-10-17", "used": 24, "limit": 24}}))
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 1 and "cap:24/24" in p.stdout
    assert LANE not in pk.live.read_text() and not pk.calls.exists()


def test_relay_apply_appends_backs_up_reads_back_and_restarts_both_units(pk):
    _env_proc(pk, carries=True)
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.live.read_text() == (
        f"# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin {LANE}\n"
    )
    assert oct(pk.live.stat().st_mode & 0o777) == "0o600"
    backups = list(pk.tmp.glob("n8n-live-lanes.env.bak-*-comms-intent-consumer-live"))
    assert len(backups) == 1 and LANE not in backups[0].read_text()
    calls = pk.calls.read_text()
    assert "restart tradeai-n8n-run-relay.service" in calls and "restart tradeai-n8n-coordination-gateway.service" in calls
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0 and "already has" in p.stdout  # idempotent


def test_relay_apply_fails_when_a_unit_did_not_pick_up_the_lane(pk):
    _env_proc(pk, carries=False)
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 1 and "env lacks" in p.stdout


def test_rollback_removes_only_the_lane_and_restarts_both_units(pk):
    pk.live.write_text(f"# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch {LANE} n8n-incident-fanin\n")
    p = pk.run("rollback")
    assert p.returncode == 0 and "DRY RUN" in p.stdout and LANE in pk.live.read_text()
    _env_proc(pk, carries=False)
    p = pk.run("rollback", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.live.read_text() == "# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin\n"
    assert len(list(pk.tmp.glob("n8n-live-lanes.env.bak-*-comms-intent-consumer-rollback"))) == 1
    assert "restart tradeai-n8n-coordination-gateway.service" in pk.calls.read_text()


def test_publish_is_read_only_and_needs_no_import(pk):
    p = pk.run("publish")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "NO IMPORT NEEDED" in p.stdout and "tradeai-dispatcher active=true" in p.stdout


def _proof_ledger(pk, monkeypatch, delivered: bool) -> None:
    ledger = Path(pk.env["LEDGER"])
    led = CoordinationLedger(ledger)
    try:
        store = F.CommsIntentStore(led, routes_path=ROUTES_PATH)
        now = datetime.now(timezone.utc)
        store.accept({"domain": "fabric", "kind": "workflow_error", "subject": "workflow wf failed at n",
                      "summary": "wf: failed", "workflow_id": "wf", "execution_id": "1", "node": "n"},
                     caller_id="n8n-relay", now=(now - timedelta(minutes=2)).timestamp())
    finally:
        led.close()
    run_id = f"d:{LANE}:live:20261017T1000"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    assert CLI.main(["--apply", "--ledger", str(ledger), "--state-root", str(pk.state)]) == 0
    doc = json.loads(R.attempt_receipt_path(LANE, run_id, pk.state).read_text())
    receipt = {"run_id": run_id, "state": "RUN_DONE", "output_verdict": _verdict(doc, run_id)}
    conn = sqlite3.connect(ledger)
    conn.execute("INSERT INTO runs (run_id, lane_id, mode, state, requested_at, receipt_json) VALUES (?,?,?,?,?,?)",
                 (run_id, LANE, "live", "RUN_DONE", datetime.now(timezone.utc).isoformat(), json.dumps(receipt)))
    conn.commit()
    key = conn.execute("SELECT incident_key FROM comms_intent_incidents").fetchone()[0]
    conn.close()
    notified = {key: {"last_notified_at": "2999-01-01T00:00:00+00:00", "identity": "incident-notifier:p2_batch:x"}}
    runtime = pk.state / "data" / "runtime"
    (runtime / "incident_notifier_state.json").write_text(json.dumps({"notified": notified if delivered else {}}))


def test_proof_passes_on_a_produced_live_run_with_a_notifier_delivery(pk, monkeypatch):
    _proof_ledger(pk, monkeypatch, delivered=True)
    p = pk.run("proof", "--since", "2000-01-01T00:00:00")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "verdict=produced" in p.stdout and "DELIVERED" in p.stdout and "queue drained: PASS" in p.stdout


def test_proof_is_pending_until_the_notifier_delivers(pk, monkeypatch):
    _proof_ledger(pk, monkeypatch, delivered=False)
    p = pk.run("proof", "--since", "2000-01-01T00:00:00")
    assert p.returncode == 1 and "NOT DELIVERED" in p.stdout and "operator delivery: PENDING/FAIL" in p.stdout

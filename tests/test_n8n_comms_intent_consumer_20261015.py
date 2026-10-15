"""n8n comms-intent consumer (2026-10-15): QUEUED comms/intent rows become incident fan-in incidents.

Operator decision: the incident fan-in route. An intent is claimed (QUEUED -> CLAIMED -> DONE | FAILED), mapped by the
closed route table to a fan-in incident at the route's tier (DIGEST -> P2), folded into the OPEN incident for the same
workflow and kind, and never sent by the consumer: the fan-in reads it and the incident notifier's P2 batch is the only
sender (AGENTS.md §24.1). Dead letters (FAILED 3x or refused; QUEUED > 2 h) are one aggregated P2 each.

Hermetic: tmp_path ledgers built by the real CoordinationLedger + CommsIntentStore, a tmp_path state root, the CLI
called in-process with a pinned clock. The Telegram chokepoints are replaced by stubs that fail the test if called.
No live ledger, gateway, n8n or Telegram.

COVERS = ["scripts/n8n_comms_intent_consumer.py", "scripts/lib/n8n_comms_intent_consumption.py",
          "scripts/n8n_incident_fanin.py"]
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402
from scripts import n8n_comms_intent_consumer as CLI  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402
from scripts.lib import n8n_fabric_store as F  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

ROUTES_PATH = ROOT / "config" / "n8n_comms_intent_routes.json"
NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
PACKET = ROOT / "docs" / "ops" / "packets" / "n8n-comms-intent-consumer-20261015"


def _body(wf: str = "tradeai-fabric-error-probe", ex: str = "25953", subject: str | None = None, **kw) -> dict:
    b = {
        "domain": "fabric",
        "kind": "workflow_error",
        "subject": subject or f"workflow {wf} failed at Fail on purpose",
        "summary": f"{wf}: deliberate failure",
        "workflow_id": wf,
        "execution_id": ex,
        "node": "Fail on purpose",
    }
    b.update(kw)
    return b


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    """The Telegram chokepoints are stubs that record and fail: the consumer path must never reach one."""
    calls: list[tuple] = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called from the comms-intent consumer path")

    fake_alert = types.ModuleType("telegram_alert")
    fake_alert.send_telegram = boom
    fake_alert.record_operator_message = boom
    fake_system = types.ModuleType("scripts.lib.autonomy_watchdog.telegram_system")
    fake_system.send_system = boom
    for name, mod in (
        ("telegram_alert", fake_alert),
        ("scripts.telegram_alert", fake_alert),
        ("scripts.lib.autonomy_watchdog.telegram_system", fake_system),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    yield calls
    assert calls == []


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    ledger = state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    monkeypatch.delenv("TRADEAI_FANIN_COMMS_INTENT", raising=False)
    monkeypatch.setattr(fanin, "HEALTH_CONTRACTS_PATH", tmp_path / "no_contracts.json")
    led = CoordinationLedger(ledger)
    store = F.CommsIntentStore(led, routes_path=ROUTES_PATH)
    return types.SimpleNamespace(state=state, ledger=ledger, led=led, store=store, tmp=tmp_path)


def _accept(env, body: dict, at: datetime) -> dict:
    return env.store.accept(body, caller_id="n8n-relay", now=at.timestamp())


def _cli(env, *args: str, now: datetime = NOW) -> int:
    return CLI.main([*args, "--ledger", str(env.ledger), "--state-root", str(env.state), "--now", now.isoformat()])


def _q(env, sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(env.ledger)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _receipt(env) -> dict:
    return json.loads((env.state / "data" / "runtime" / "n8n-comms-intent-consumer_last.json").read_text())


# ── identities the fan-in and notifier also compute ───────────────────────────────────────────────────────────────


def test_identities_match_the_fanin_and_the_notifier():
    assert C.WFERR_SOURCE == fanin.WFERR_SOURCE
    assert C.LEDGER_REL == fanin.LEDGER_REL
    assert C.notifier_incident_key("n8n_workflow_error", "wferr:x") == N.incident_key("n8n_workflow_error", "wferr:x")
    f = {"source": "n8n_workflow_error", "item": "wferr:x"}
    assert C.fanin_event_key("n8n_workflow_error", "wferr:x", "2026-10-15") == fanin.idem_key(f, "2026-10-15")
    assert C.fanin_identity("fabric", "workflow_error", "wf-a") == ("n8n_workflow_error", "wferr:wf-a")
    assert C.fanin_identity("fabric", "run_lane_dead_letter", "wf-a") == (
        "n8n_comms_intent",
        "fabric.run_lane_dead_letter:wf-a",
    )


# ── claim ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_claim_is_an_atomic_compare_and_set(env):
    _accept(env, _body(), NOW - timedelta(minutes=5))
    a, b = C.connect_rw(env.ledger), C.connect_rw(env.ledger)
    try:
        it = C.claimable(a, NOW, 10)[0]
        assert C.claim(a, it, token="A", now=NOW) is True
        assert C.claim(b, it, token="B", now=NOW) is False  # selected as QUEUED, no longer QUEUED
        assert C.claimable(b, NOW, 10) == []  # a fresh CLAIMED row is leased
    finally:
        a.close()
        b.close()
    row = _q(env, "SELECT * FROM comms_intent_consumption")[0]
    assert (row["state"], row["attempts"], row["claim_token"]) == ("CLAIMED", 1, "A")


def test_an_expired_claim_is_claimed_again(env):
    _accept(env, _body(), NOW - timedelta(minutes=30))
    conn = C.connect_rw(env.ledger)
    try:
        it = C.claimable(conn, NOW - timedelta(minutes=20), 10)[0]
        assert C.claim(conn, it, token="dead", now=NOW - timedelta(minutes=20))  # consumer died here
        assert C.claimable(conn, NOW - timedelta(minutes=15), 10) == []
    finally:
        conn.close()
    assert _cli(env, "--apply") == 0
    row = _q(env, "SELECT * FROM comms_intent_consumption")[0]
    assert (row["state"], row["attempts"]) == ("DONE", 2)


# ── apply ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_apply_turns_a_workflow_error_into_a_p2_wferr_incident_and_records_it(env):
    rec = _accept(env, _body(), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply") == 0
    intent = env.store.get(rec["intent_id"])
    assert intent["state"] == "DONE"
    c = _q(env, "SELECT * FROM comms_intent_consumption")[0]
    key = N.incident_key("n8n_workflow_error", "wferr:tradeai-fabric-error-probe")
    assert (c["outcome"], c["incident_key"], c["severity"], c["attempts"]) == ("incident", key, "P2", 1)
    assert c["fanin_event_key"] == fanin.idem_key(
        {"source": "n8n_workflow_error", "item": "wferr:tradeai-fabric-error-probe"}, "2026-10-15"
    )
    inc = _q(env, "SELECT * FROM comms_intent_incidents")[0]
    assert (inc["state"], inc["tier"], inc["severity"], inc["count"]) == ("OPEN", "DIGEST", "P2", 1)
    assert json.loads(inc["intent_ids"]) == [rec["intent_id"]]
    r = _receipt(env)
    assert r["schema"] == "LaneRunReceipt@v1" and r["lane_id"] == "n8n-comms-intent-consumer"
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["done"] == 1
    assert r["summary"]["results"][0]["incident_key"] == key


def test_a_rerun_changes_nothing(env):
    _accept(env, _body(), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply") == 0
    snap = (
        _q(env, "SELECT * FROM comms_intents"),
        _q(env, "SELECT * FROM comms_intent_consumption"),
        _q(env, "SELECT * FROM comms_intent_incidents"),
    )
    assert _cli(env, "--apply", now=NOW + timedelta(minutes=5)) == 0
    assert snap == (
        _q(env, "SELECT * FROM comms_intents"),
        _q(env, "SELECT * FROM comms_intent_consumption"),
        _q(env, "SELECT * FROM comms_intent_incidents"),
    )
    s = _receipt(env)["summary"]
    assert (s["done"], s["incidents_created"], s["incidents_updated"], s["refreshed"]) == (0, 0, 0, 0)


def test_a_second_error_of_the_same_workflow_updates_the_open_incident(env):
    _accept(env, _body(ex="1", subject="workflow probe failed at A"), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply", now=NOW - timedelta(minutes=9)) == 0
    _accept(env, _body(ex="2", subject="workflow probe failed at B"), NOW - timedelta(minutes=2))  # new dedupe key
    _accept(env, _body(wf="other-wf", ex="3"), NOW - timedelta(minutes=2))
    assert _cli(env, "--apply") == 0
    incs = {r["fanin_item"]: r for r in _q(env, "SELECT * FROM comms_intent_incidents")}
    assert set(incs) == {"wferr:tradeai-fabric-error-probe", "wferr:other-wf"}
    probe = incs["wferr:tradeai-fabric-error-probe"]
    assert (probe["count"], probe["generation"], probe["last_execution_id"]) == (2, 1, "2")
    s = _receipt(env)["summary"]
    assert (s["incidents_created"], s["incidents_updated"]) == (1, 1)


def test_a_repeat_folded_into_a_done_intent_refreshes_its_incident(env):
    _accept(env, _body(), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply", now=NOW - timedelta(minutes=9)) == 0
    dup = _accept(env, _body(), NOW - timedelta(minutes=1))  # same subject inside the window: gateway count + 1
    assert dup["duplicate"] is True and dup["count"] == 2
    assert _cli(env, "--apply") == 0
    inc = _q(env, "SELECT * FROM comms_intent_incidents")[0]
    assert inc["count"] == 2 and _receipt(env)["summary"]["refreshed"] == 1
    assert _cli(env, "--apply", now=NOW + timedelta(minutes=1)) == 0
    assert _q(env, "SELECT count FROM comms_intent_incidents")[0]["count"] == 2


def test_the_incident_closes_after_the_window_and_reopens_on_a_new_error(env):
    _accept(env, _body(ex="1"), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply") == 0
    later = NOW + timedelta(hours=2)
    assert _cli(env, "--apply", now=later) == 0
    inc = _q(env, "SELECT * FROM comms_intent_incidents")[0]
    assert inc["state"] == "CLOSED" and _receipt(env)["summary"]["closed"] == 1
    assert C.open_incident_findings(env.ledger, later)[0] == []
    _accept(env, _body(ex="2", subject="probe failed again"), later)
    assert _cli(env, "--apply", now=later + timedelta(minutes=1)) == 0
    inc = _q(env, "SELECT * FROM comms_intent_incidents")[0]
    assert (inc["state"], inc["generation"], inc["count"]) == ("OPEN", 2, 1)


# ── refusals, retries, dead letters ───────────────────────────────────────────────────────────────────────────────


def _insert_raw(env, intent_id: str, *, kind: str, at: datetime) -> None:
    """A row the gateway would refuse today (its route was removed after acceptance, or a hand-edited ledger)."""
    conn = sqlite3.connect(env.ledger)
    conn.execute(
        "INSERT INTO comms_intents (intent_id, dedupe_key, domain, kind, tier, runbook_id, subject, summary,"
        " workflow_id, execution_id, node, caller_id, state, count, first_at, last_at, routes_sha256)"
        " VALUES (?, 'cd-x', 'fabric', ?, 'DIGEST', NULL, 's', 's', 'wf', '1', 'n', 'n8n-relay', 'QUEUED', 1, ?, ?, NULL)",
        (intent_id, kind, at.isoformat(), at.isoformat()),
    )
    conn.commit()
    conn.close()


def test_an_unknown_kind_is_failed_with_a_reason_never_retried_and_never_sent(env, no_send):
    _insert_raw(env, "ci-unknown", kind="mystery_kind", at=NOW - timedelta(minutes=5))
    assert _cli(env, "--apply") == 0  # a refusal is a finding, not a failed run
    assert env.store.get("ci-unknown")["state"] == "FAILED"
    c = _q(env, "SELECT * FROM comms_intent_consumption")[0]
    assert (c["terminal"], c["last_error"], c["outcome"], c["incident_key"]) == (1, "intent_unrouted", "refused", None)
    assert _q(env, "SELECT * FROM comms_intent_incidents") == []
    assert _cli(env, "--apply", now=NOW + timedelta(minutes=5)) == 0
    assert _q(env, "SELECT attempts FROM comms_intent_consumption")[0]["attempts"] == 1
    dead, _ = C.dead_letter_findings(env.ledger, NOW)
    assert [(f["source"], f["item"], f["severity"], f["count"]) for f in dead] == [
        ("n8n_comms_intent_dlq", "dead_letter", "P2", 1)
    ]
    assert no_send == []


def test_a_page_tier_route_is_refused(env, tmp_path):
    routes = json.loads(ROUTES_PATH.read_text())
    routes["routes"][0]["tier"] = "PAGE"
    p = tmp_path / "routes.json"
    p.write_text(json.dumps(routes))
    _accept(env, _body(), NOW - timedelta(minutes=5))
    assert (
        CLI.main(
            [
                "--apply",
                "--ledger",
                str(env.ledger),
                "--state-root",
                str(env.state),
                "--now",
                NOW.isoformat(),
                "--routes",
                str(p),
            ]
        )
        == 0
    )
    c = _q(env, "SELECT * FROM comms_intent_consumption")[0]
    assert (c["state"], c["last_error"], c["terminal"]) == ("FAILED", "page_tier_never_from_n8n", 1)


def test_a_transient_failure_retries_three_times_then_dead_letters(env, monkeypatch):
    _accept(env, _body(), NOW - timedelta(minutes=5))

    def broken(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(C, "map_intent", broken)
    for i in range(3):
        assert _cli(env, "--apply", now=NOW + timedelta(minutes=i)) == 1  # honest exit
    c = _q(env, "SELECT * FROM comms_intent_consumption")[0]
    assert (c["state"], c["attempts"], c["terminal"]) == ("FAILED", 3, 0)
    assert c["last_error"].startswith("RuntimeError: synthetic")
    assert _receipt(env)["status"] == "failed"
    assert _cli(env, "--apply", now=NOW + timedelta(minutes=5)) == 0  # nothing claimable any more
    assert _q(env, "SELECT attempts FROM comms_intent_consumption")[0]["attempts"] == 3
    dead, _ = C.dead_letter_findings(env.ledger, NOW + timedelta(minutes=5))
    assert [f["item"] for f in dead] == ["dead_letter"]


def test_an_intent_queued_over_two_hours_raises_one_queued_stale_finding(env):
    _accept(env, _body(ex="1"), NOW - timedelta(hours=3))
    _accept(env, _body(ex="2", subject="other"), NOW - timedelta(hours=2, minutes=30))
    _accept(env, _body(ex="3", subject="fresh"), NOW - timedelta(minutes=30))
    found, note = C.dead_letter_findings(env.ledger, NOW)
    assert [(f["item"], f["count"], f["severity"]) for f in found] == [("queued_stale", 2, "P2")]
    assert "oldest 3.0 h" in found[0]["detail"] and note.startswith("ok:")
    assert _cli(env, "--apply") == 0
    assert C.dead_letter_findings(env.ledger, NOW)[0] == []


# ── the cap and the dry run ───────────────────────────────────────────────────────────────────────────────────────


def test_the_per_run_cap_defers_the_rest_oldest_first(env):
    for i in range(5):
        _accept(env, _body(wf=f"wf-{i}", ex=str(i)), NOW - timedelta(minutes=50 - i))
    assert _cli(env, "--apply", "--max-intents", "2") == 0
    s = _receipt(env)["summary"]
    assert (s["done"], s["deferred"]) == (2, 3)
    states = {r["workflow_id"]: r["state"] for r in _q(env, "SELECT workflow_id, state FROM comms_intents")}
    assert states == {"wf-0": "DONE", "wf-1": "DONE", "wf-2": "QUEUED", "wf-3": "QUEUED", "wf-4": "QUEUED"}
    assert _cli(env, "--apply", "--max-intents", "2", now=NOW + timedelta(minutes=5)) == 0
    assert _receipt(env)["summary"]["deferred"] == 1


def test_the_default_cap_is_the_route_table_max_per_hour(env):
    _accept(env, _body(), NOW - timedelta(minutes=5))
    assert _cli(env, "--apply") == 0
    assert _receipt(env)["summary"]["max_intents"] == json.loads(ROUTES_PATH.read_text())["max_per_hour"]


def _fingerprint(env) -> dict:
    """Every file under the state root by hash, except SQLite's reader sidecars: a mode=ro reader of a WAL database
    maps -shm (read marks) and may create an EMPTY -wal; neither holds data, and the test asserts the -wal is empty."""
    out = {}
    for p in sorted(env.state.rglob("*")):
        if p.is_file() and not p.name.endswith(("-shm", "-wal")):
            out[str(p.relative_to(env.state))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_the_dry_run_writes_nothing(env, capsys):
    _accept(env, _body(), NOW - timedelta(minutes=10))
    env.led.close()  # checkpoint the WAL so the files are quiescent
    before = _fingerprint(env)
    tables_before = {r["name"] for r in _q(env, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert _cli(env, "--dry-run") == 0
    assert _cli(env) == 0  # the default is the dry run
    out = capsys.readouterr().out
    assert out.count("DRY-RUN ") == 2
    report = json.loads(out.splitlines()[0][len("DRY-RUN ") :])
    would = report["summary"]["would"][0]
    assert (would["action"], would["fanin_item"], would["severity"], would["incident"]) == (
        "incident",
        "wferr:tradeai-fabric-error-probe",
        "P2",
        "create_or_reopen",
    )
    assert _fingerprint(env) == before
    wal = env.ledger.with_name(env.ledger.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    assert {r["name"] for r in _q(env, "SELECT name FROM sqlite_master WHERE type='table'")} == tables_before
    assert "comms_intent_consumption" not in tables_before
    assert not (env.state / "data" / "runtime").exists()


def test_the_dry_run_on_a_missing_ledger_reports_absent_and_creates_nothing(tmp_path, capsys):
    assert (
        CLI.main(
            [
                "--dry-run",
                "--ledger",
                str(tmp_path / "none.sqlite"),
                "--state-root",
                str(tmp_path),
                "--now",
                NOW.isoformat(),
            ]
        )
        == 0
    )
    assert '"ledger": "absent"' in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_apply_on_a_missing_ledger_fails_and_never_creates_one(tmp_path):
    assert (
        CLI.main(
            [
                "--apply",
                "--ledger",
                str(tmp_path / "none.sqlite"),
                "--state-root",
                str(tmp_path),
                "--now",
                NOW.isoformat(),
            ]
        )
        == 1
    )
    assert not (tmp_path / "none.sqlite").exists()
    r = json.loads((tmp_path / "data" / "runtime" / "n8n-comms-intent-consumer_last.json").read_text())
    assert r["status"] == "failed" and r["ok_at"] is None


def test_usage_errors_exit_2(tmp_path):
    assert CLI.main(["--dry-run", "--apply"]) == 2
    assert CLI.main(["--now", "not-a-time"]) == 2
    assert CLI.main(["--max-intents", "0", "--ledger", str(tmp_path / "x"), "--now", NOW.isoformat()]) == 2


# ── the fan-in ────────────────────────────────────────────────────────────────────────────────────────────────────


def _relay_event(env, wf: str, ex: str, at: datetime) -> None:
    key = f"wferr-{wf}-{ex}"
    rec = {"idempotency_key": key, "lane_id": "n8n-workflow-error", "state": "ACCEPTED", "recorded_at": at.isoformat()}
    conn = sqlite3.connect(env.ledger)
    conn.execute(
        "INSERT INTO receipts (store_key, payload_hash, receipt_json, project, lane_id, state, updated_at)"
        " VALUES (?, 'h', ?, 'trade-ai', 'n8n-workflow-error', 'ACCEPTED', ?)",
        (f"trade-ai:{key}", json.dumps(rec), at.isoformat()),
    )
    conn.commit()
    conn.close()


def test_the_fanin_merges_an_intent_into_the_relay_incident_for_the_same_workflow(env):
    _relay_event(env, "tradeai-fabric-error-probe", "25953", NOW - timedelta(minutes=10))
    _accept(env, _body(), NOW - timedelta(minutes=10))
    _accept(env, _body(wf="intent-only", ex="7"), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply") == 0
    out = fanin._workflow_error_findings(env.state, NOW)
    fanin._comms_intent_findings(env.state, NOW, out)
    by_item = {f["item"]: f for f in out}
    assert set(by_item) == {"wferr:tradeai-fabric-error-probe", "wferr:intent-only"}  # one each, no duplicate
    merged = by_item["wferr:tradeai-fabric-error-probe"]
    assert merged["count"] == 2 and "+1 intent(s)" in merged["detail"] and merged["severity"] == "P2"
    assert merged["comms_intent_incident_key"] == N.incident_key("n8n_workflow_error", merged["item"])
    solo = by_item["wferr:intent-only"]
    assert (solo["source"], solo["severity"], solo["count"]) == ("n8n_workflow_error", "P2", 1)
    assert "merged=1" in fanin.NOTES["comms_intent_source"]


def test_a_merge_keeps_the_relays_higher_severity(env):
    _relay_event(env, "tradeai-dispatcher", "1", NOW - timedelta(minutes=5))  # the fan-in's own P1 rule
    _accept(env, _body(wf="tradeai-dispatcher", ex="1"), NOW - timedelta(minutes=5))
    assert _cli(env, "--apply") == 0
    out = fanin._workflow_error_findings(env.state, NOW)
    fanin._comms_intent_findings(env.state, NOW, out)
    assert [(f["item"], f["severity"]) for f in out] == [("wferr:tradeai-dispatcher", "P1")]


def test_the_fanin_source_is_quiet_without_tables_and_can_be_switched_off(env, monkeypatch):
    out: list = []
    fanin._comms_intent_findings(env.state, NOW, out)
    assert out == [] and "incidents_table:absent" in fanin.NOTES["comms_intent_source"]
    monkeypatch.setenv("TRADEAI_FANIN_COMMS_INTENT", "0")
    fanin._comms_intent_findings(env.state, NOW, out)
    assert fanin.NOTES["comms_intent_source"].endswith("disabled_by_env")


def test_the_notifier_sees_a_comms_intent_incident_as_one_p2_batch_line(env):
    _accept(env, _body(), NOW - timedelta(minutes=10))
    assert _cli(env, "--apply") == 0
    out: list = []
    fanin._comms_intent_findings(env.state, NOW, out)
    rows = [
        {
            **{k: f[k] for k in ("source", "item", "severity", "detail")},
            "event_id": "evt-x",
            "state": "ARTIFACT_WRITTEN",
        }
        for f in out
    ]
    open_now, _ = N.open_incidents({"incidents": rows}, set())
    assert [i["severity"] for i in open_now.values()] == ["P2"]  # DIGEST: the batched path, never an immediate P1


# ── ratchets: no sender, staged lane, contract draft ──────────────────────────────────────────────────────────────

FORBIDDEN_IMPORT_PARTS = (
    "telegram",
    "notifier",
    "send_",
    "smtp",
    "requests",
    "urllib",
    "http",
    "socket",
    "subprocess",
    "notification",
    "alert",
)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            names |= {f"{mod}.{a.name}" for a in node.names}
    return names


@pytest.mark.parametrize("rel", ["scripts/n8n_comms_intent_consumer.py", "scripts/lib/n8n_comms_intent_consumption.py"])
def test_the_consumer_imports_no_sender(rel):
    for name in _imports(ROOT / rel):
        low = name.lower()
        assert not any(part in low for part in FORBIDDEN_IMPORT_PARTS), (rel, name)
    text = (ROOT / rel).read_text(encoding="utf-8")
    for needle in ("api.telegram.org", "sendMessage", "TELEGRAM_BOT_TOKEN", "send_telegram", "send_system"):
        assert needle not in text, (rel, needle)


def test_importing_and_running_the_consumer_loads_no_sender_module(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from scripts import n8n_comms_intent_consumer as c\n"
        "c.main(['--dry-run', '--ledger', %r, '--state-root', %r])\n"
        "bad = sorted(m for m in sys.modules if any(p in m.lower() for p in ('telegram', 'notifier', 'smtp',"
        " 'requests', 'urllib3', 'http.client')))\n"
        "print('LOADED=' + ','.join(bad))\n"
    ) % (str(ROOT), str(tmp_path / "none.sqlite"), str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert "LOADED=\n" in proc.stdout or proc.stdout.rstrip().endswith("LOADED="), proc.stdout


def test_the_lane_is_staged_and_not_active():
    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    row = reg["n8n-comms-intent-consumer"]
    assert row["state"] == "NEVER_SCHEDULED" and row["scheduler"] == {"kind": "none"}
    assert "dispatch" not in row and "r1_pending" not in row
    assert row["output_signal"] == {
        "kind": "json_key",
        "path": "data/runtime/n8n-comms-intent-consumer_last.json",
        "key": "ok_at",
    }
    allow = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
    e = allow["n8n-comms-intent-consumer"]
    assert e["live_arg"] is None and e["dry_run_arg"] == ["--dry-run"]  # shadow: only the dry run is runnable
    assert e["command"] == ["$PY", "scripts/n8n_comms_intent_consumer.py"]
    assert e["output_signal"] == row["output_signal"]["path"]
    assert not e["lock"].endswith(".dryrun")


def test_the_health_contract_draft_is_valid_and_not_in_the_gate_file():
    draft = json.loads((PACKET / "health_contract_draft.json").read_text())
    draft.pop("_note")
    assert H.validate_contract(draft) == []
    assert draft["status"] == "DRAFT" and draft["id"] == "n8n-comms-intent-consumer"
    assert draft["alerting"]["failed"]["notifier_priority"] == "P2"  # never PAGE from this lane
    ids = {c["id"] for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
    assert "n8n-comms-intent-consumer" not in ids

"""W4 terminal-slot disposition: fixtures only, never replay, send or migrate live state."""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from scripts import n8n_dlq as cli, n8n_incident_fanin as fanin
from scripts.lib import n8n_dlq_disposition as DD
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
EARLY = datetime(2026, 10, 23, 18, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def fixture_ledger(tmp_path, *, count=1, output="produced", effective="live", lane="n8n-incident-fanin"):
    path = tmp_path / "ledger.sqlite"
    ledger = CoordinationLedger(path)
    store = LedgerRunStore(ledger)
    for i in range(count):
        store.record_dead_letter(slot_key=f"d:{lane}:live:20261023T1{i:03d}", lane_id=lane,
            mode="live", slot_local=None, attempts=1, last_run_id=None, last_state="RUN_FAILED",
            last_reason="safe_flock: refusing symlink_component", verdict="exhausted", now=EARLY.timestamp(),
            klass="send", max_attempts=1, policy="none")
    store.request(run_id="later-success", lane_id=lane, mode="live", requested_by="fixture", caller_id="fixture", now=NOW.timestamp()-600)
    store.claim_next(now=NOW.timestamp()-590)
    receipt = {"schema": "RunReceipt@v3", "run_id": "later-success", "lane_id": lane,
        "mode": effective, "state": "RUN_DONE", "exit_code": 0,
        "finished_at": datetime.fromtimestamp(NOW.timestamp()-500, timezone.utc).isoformat(),
        "output_verdict": {"verdict": output, "contract_id": lane}}
    store.finish("later-success", state="RUN_DONE", receipt=receipt, now=NOW.timestamp()-500)
    ledger.close()
    return path


def args(path, audit, *extra):
    return ["--ledger", str(path), "acknowledge", "--lane", "n8n-incident-fanin",
            "--superseded-by", "later-success", "--by", "operator", "--note", "wrapper outage superseded",
            "--receipts", str(audit), *extra]


def test_ack_default_is_dry_run_and_changes_no_file(tmp_path, monkeypatch, capsys):
    path = fixture_ledger(tmp_path)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(cli, "datetime", Clock)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert cli.main(args(path, audit)) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["dry_run"] is True and doc["rearm"] is False
    assert not audit.exists()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_non_rearmable_ack_is_idempotent_append_only_and_never_releases(tmp_path, monkeypatch, capsys):
    path = fixture_ledger(tmp_path)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(cli, "datetime", Clock)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert cli.main(args(path, audit, "--apply")) == 0
    first = audit.read_bytes()
    assert [json.loads(line)["phase"] for line in first.splitlines()] == ["intent", "committed"]
    assert cli.main(args(path, audit, "--apply")) == 0
    assert audit.read_bytes() == first
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    ledger = CoordinationLedger(path, read_only=True)
    try:
        row, = LedgerRunStore(ledger).list_dead_letters()
        assert row["released_at"] is None
        assert DD.is_acknowledged(row, DD.acknowledgements(audit))
        changed = {**row, "dead_at": NOW.isoformat()}
        assert not DD.is_acknowledged(changed, DD.acknowledgements(audit))
    finally:
        ledger.close()


@pytest.mark.parametrize("output,effective", [("declared_not_enforced", "live"), ("produced", "dry_run"), ("unverifiable", "live")])
def test_unverified_output_or_clamped_dry_run_cannot_supersede(tmp_path, monkeypatch, output, effective):
    path = fixture_ledger(tmp_path, output=output, effective=effective)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(cli, "datetime", Clock)
    assert cli.main(args(path, audit, "--apply")) == 4
    assert not audit.exists()


def test_actor_role_and_mutually_exclusive_modes_refuse_before_io(tmp_path):
    assert cli.main(["acknowledge", "--lane", "x", "--superseded-by", "x", "--by", "worker", "--note", "x"]) == 2
    assert cli.main(args(tmp_path / "absent", tmp_path / "audit", "--dry-run", "--apply")) == 2


def test_recovered_wrapper_burst_is_one_recovery_line_with_real_run(tmp_path, monkeypatch):
    path = fixture_ledger(tmp_path, count=375)
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(path))
    monkeypatch.setenv("TRADEAI_FANIN_DLQ", "1")
    found = fanin._dlq_findings(tmp_path, NOW)
    row, = found
    assert row["recovered"] and row["count"] == 375 and row["severity"] == "P3"
    assert row["superseded_by"] == ["later-success"] and "2026-10-23" in row["detail"]
    assert len(row["slot_keys"]) == 375


def test_protected_lane_incidents_do_not_collapse_or_auto_recover(tmp_path, monkeypatch):
    path = fixture_ledger(tmp_path, count=2, lane="broker-safety")
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(path))
    found = fanin._dlq_findings(tmp_path, NOW)
    assert len(found) == 2 and all(r["severity"] == "P2" and not r.get("recovered") for r in found)


def test_committed_ack_disappears_from_fanin_without_changing_ledger(tmp_path, monkeypatch, capsys):
    path = fixture_ledger(tmp_path)
    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(path))
    audit = tmp_path / DD.RECEIPTS_REL
    assert cli.main(args(path, audit, "--apply")) == 0
    assert fanin._dlq_findings(tmp_path, NOW) == []


@pytest.mark.parametrize("change", [
    {"lane_id": "other"}, {"mode": "dry_run"}, {"dead_at": NOW.isoformat()}, {"dead_at": "unknown"},
])
def test_later_success_must_match_lane_mode_and_time(tmp_path, change):
    path = fixture_ledger(tmp_path)
    ledger = CoordinationLedger(path, read_only=True)
    try:
        store = LedgerRunStore(ledger)
        dead, = store.list_dead_letters()
        assert not DD.recovery({**dead, **change}, store.get("later-success"), now=NOW)[0]
    finally:
        ledger.close()

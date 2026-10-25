"""2026-10-25 activation: conflict-resolver admitted as an n8n lane at canary; the decision writer is activated by the
operator's approval of the conflict_ledger authority row (operator directive 2026-10-25, verbatim: "You should turn on
everything. It shouldn't need me to turn on anything. Get it working.").

Fixtures and disposable roots only: no production state, broker, model, sender or scheduler is touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts import audit_lane_transitive_capabilities as cap  # noqa: E402
from scripts.lib.conflicts import api as conflicts_api  # noqa: E402
from scripts.lib.conflicts import cio as conflicts_cio  # noqa: E402
from tests.test_conflict_api import body, ctx  # noqa: E402
from tests.test_conflict_ledger import KEY, NOW, SUBJECT, conflict, ledger  # noqa: E402

LANE = "conflict-resolver"


def _row(path, key, value):
    return next(r for r in json.loads((ROOT / path).read_text())[key] if r.get("lane_id", r.get("id")) == value)


def test_lane_is_n8n_native_canary_in_shadow_writing_mode():
    lane = _row("config/lane_registry.json", "lanes", LANE)
    run = _row("config/n8n_run_allowlist.json", "lanes", LANE)
    contract = _row("config/n8n_health_contracts.json", "contracts", LANE)
    assert lane["scheduler"]["kind"] == "n8n" and lane["scheduler"]["expression"] == "dispatcher"
    assert lane["scheduler"]["stage"] == "canary" and lane["state"] == "ACTIVE"
    assert lane["dispatch"]["mode"] == "live"
    assert lane["dispatch"]["cron"] == ["*/15 9-16 * * 1-5", "30 7 * * 1-5", "20 16 * * 1-5"]
    assert lane["scheduler"]["cadence"] == lane["dispatch"]["cron"][0]
    assert run["command"] == ["$PY", "scripts/conflict_resolver.py", "--state-root", "$STATE_ROOT"]
    assert run["dry_run_arg"] == ["--dry-run"] and run["live_arg"] == ["--shadow"]
    # Fixture replay is never scheduler-admitted (docs/ops/CONFLICT_LEDGER.md).
    assert not any("input-file" in a for a in run["command"] + run["live_arg"] + run["dry_run_arg"])
    assert run["output_signal"] == lane["output_signal"]["path"] == "data/runtime/conflict-resolver_last.json"
    assert run["lock_kind"] == "flock" and run["lock"] == "/tmp/tradeai_conflict_resolver.lock"
    assert contract["stage"] == "canary" and contract["target_reason"] == "stage:canary"
    assert contract["status"] == contract["review"]["status"] == "REVIEWED"


def test_runner_has_no_sender_and_reaches_no_direct_sender(tmp_path):
    src = (ROOT / "scripts/conflict_resolver.py").read_text()
    for bad in ("send_telegram", "telegram_alert", "incident_notifier", "place_order", "broker_access"):
        assert bad not in src, bad
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps({"lanes": [_row("config/n8n_run_allowlist.json", "lanes", LANE)]}))
    caps = cap.audit(allowlist)[LANE]["capabilities"]
    assert "direct_sender" not in caps
    # Only the reviewed lazy reach (DD01 ruling); nothing forbidden is loaded at import.
    assert set(caps).intersection(cap.FORBIDDEN) <= {"broker_module", "order_placement"}
    assert not any(caps[c]["at_import"] for c in set(caps).intersection(cap.FORBIDDEN))
    assert set(cap.load_baseline()[LANE]) == {"broker_module", "order_placement"}


def test_writer_is_activated_only_by_the_operator_approved_authority_row():
    assert conflicts_api.writer_activated() is True
    auth = json.loads((ROOT / "config/data_source_authority.json").read_text())
    row = next(r for r in auth["domains"] if r["domain"] == "conflict_ledger")
    assert row["store"]["file"] == conflicts_api.STORE_FILE and row["writer"] == conflicts_api.WRITER
    assert not any(r["domain"] == "conflict_ledger" for r in auth.get("proposed_domains") or [])
    # A proposed row, a missing approval field or another writer never activates it.
    assert conflicts_api.writer_activated({"proposed_domains": [row]}) is False
    for broken in ({**row, "approval": {**row["approval"], "approved_by": "agent"}},
                   {**row, "approval": {k: v for k, v in row["approval"].items() if k != "reference"}},
                   {**row, "writer": "scripts/other.py"},
                   {**row, "store": {"file": "data/other.jsonl"}}):
        assert conflicts_api.writer_activated({"domains": [broken]}) is False
    assert conflicts_api.writer_activated({"domains": "not-a-list"}) is False


def test_operator_decisions_row_is_granted_for_the_approvals_writer():
    from scripts.lib import operator_approvals as oa

    auth = json.loads((ROOT / "config/data_source_authority.json").read_text())
    assert oa.writes_approved(auth) is True


def test_api_v2_route_reads_activation_and_agents_stay_refused(tmp_path, monkeypatch):
    import api_v2

    monkeypatch.setattr(conflicts_api, "_root", lambda: tmp_path)
    seen = []
    real = conflicts_api.handle

    def spy(*a, **k):
        seen.append(k.get("write_enabled"))
        return real(*a, **k)

    monkeypatch.setattr(conflicts_api, "handle", spy)
    status, refused = api_v2.handle("/api/v3/conflicts/x/decision", "POST", body={"expected_revision": 1})
    assert status in (403, 503) and refused["ok"] is False and refused["error"] != "CONFLICT_WRITER_NOT_ACTIVATED"
    assert seen == [True]
    api_v2.handle("/api/v3/conflicts", "GET")
    assert seen == [True, False]


def test_default_ledger_delivers_the_decision_to_cio_memory(tmp_path, monkeypatch):
    """With no injected ledger the POST path wires the CIO-memory sink, so a recorded decision answers 200
    (without it the append succeeds and the drain wrongly answers DECISION_DURABLE_SINK_PENDING)."""
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    delivered = []
    monkeypatch.setattr(conflicts_cio, "memory_writer", lambda root: lambda event: delivered.append(event) or True)
    url = "/api/v3/conflicts/" + quote(KEY, safe="") + "/decision"
    status, result = conflicts_api.handle(url, "POST", body(), ctx=ctx(), root=tmp_path, write_enabled=True, now=NOW)
    assert status == 200 and result["ok"] is True and result["cleared"] is False
    assert delivered and delivered[-1]["event"] == "decided"


def test_backup_data_family_names_the_ledgers():
    sh = (ROOT / "scripts/backup_secrets_state.sh").read_text()
    for rel in ("data/conflicts/conflict_events.jsonl", "data/conflicts/conflict_delivery_receipts.jsonl",
                "data/conflicts/conflict_observations.jsonl", "data/governance/operator_decisions.jsonl"):
        assert rel in sh, rel
    manifest = json.loads((ROOT / "config/backup_coverage_manifest.json").read_text())
    cls = next(c for c in manifest["asset_classes"] if c["id"] == "ps_ledgers_data_offsite")
    assert cls["mechanism"] == ["data_offsite"]
    assert {"store:conflict_ledger", "store:operator_decisions", "ps:data/conflicts"} <= set(cls["covers"])


def test_next_run_label_comes_from_the_lane_schedule():
    from datetime import datetime, timezone

    from scripts.conflict_resolver import next_run_label

    # Friday 2026-10-23 15:50 ET -> next fire 16:00 ET (*/15 9-16); Friday 16:50 ET -> Monday 07:30 ET.
    assert next_run_label(datetime(2026, 10, 23, 19, 50, tzinfo=timezone.utc)) == "2026-10-23T16:00:00-04:00"
    assert next_run_label(datetime(2026, 10, 23, 20, 50, tzinfo=timezone.utc)) == "2026-10-26T07:30:00-04:00"


def test_global_halt_becomes_a_t0_safety_input_and_reads_are_select_only():
    from datetime import datetime, timezone

    from scripts.conflict_resolver import global_halt_inputs

    now = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
    seen = []

    def query(sql, params):
        seen.append(sql)
        return [{"key": "halt_all_trading", "value": "true"}, {"key": "kill_switch_engaged", "value": "false"}]

    rows = global_halt_inputs(now, query)
    assert [(r.source, r.value, r.role) for r in rows] == [("risk_gate:halt_all_trading", "HALT", "safety")]
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in seen)
    assert global_halt_inputs(now, lambda *a: (_ for _ in ()).throw(RuntimeError("db down"))) == []

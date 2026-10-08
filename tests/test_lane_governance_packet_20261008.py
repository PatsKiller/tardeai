"""Phase 2 PR-E (2026-10-08): the weekly lane governance packet is rendered from facts that already exist, and the
governed ops-summary model job reads its receipt. Hermetic: fixture registry, fixture receipts, a sqlite ledger built
with the gateway's own ledger classes, fixture model-call modes. No network, no DB, no send."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import report_lane_governance_packet as G  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerReceiptStore  # noqa: E402

NOW = dt.datetime(2026, 10, 8, 2, 0, tzinfo=dt.timezone.utc)
SHA = "b" * 40


def _registry(tmp: Path, rows: list[dict]) -> Path:
    reg = {"schema": "LaneRegistry@v1", "authority": "READ_ONLY_ADVISORY", "seeded_at": "2026-10-08", "note": "fixture",
           "undeclared_baseline": [], "inherited_tranches": [], "lanes": rows}
    p = tmp / "lane_registry.json"
    p.write_text(json.dumps(reg))
    return p


def _lane(lane_id: str, state: str, signal_path: str, cadence_h: float = 1.0) -> dict:
    return {"lane_id": lane_id, "owner": "platform", "scheduler": {"kind": "cron", "expression": f"0 * * * * {lane_id}.py", "match": f"{lane_id}.py"},
            "expected_cadence_hours": cadence_h, "state": state, "state_since": "2026-10-08",
            "state_reason": "fixture lane for the governance packet test, declared with evidence of length over sixty characters",
            "output_signal": {"kind": "file_mtime", "path": signal_path}, "reason_confidence": "ESTABLISHED",
            "reason_evidence": "fixture evidence for the governance packet test, longer than sixty characters so the registry tests pass"}


def _root(tmp: Path) -> Path:
    root = tmp / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "governance").mkdir(parents=True)
    (root / "data" / "runtime" / "live_lane_last.json").write_text("{}")   # fresh signal → LIVE
    (root / "data" / "runtime" / "n8n_incident_fanin_last.json").write_text(json.dumps({
        "as_of": NOW.isoformat(), "open": 3, "by_severity": {"P1": 1, "P2": 2},
        "incidents": [{"source": "db_hygiene", "severity": "P2"}, {"source": "db_hygiene", "severity": "P2"}, {"source": "expected_services", "severity": "P1"}],
        "recovered": []}))
    (root / "data" / "runtime" / "db_hygiene_last.json").write_text(json.dumps({
        "as_of": NOW.isoformat(), "ok": False, "db_bytes": 24_400_000_000, "by_code": {"SIZE_BUDGET": 1},
        "findings": [{"severity": "P2", "code": "SIZE_BUDGET", "item": "trade_ai", "detail": "24.4 GB > 16 GB"}]}))
    (root / "data" / "governance" / "platform_conformance_latest.json").write_text(json.dumps({"as_of": NOW.isoformat(), "verdict": "WARN", "silos_below": ["a:0.7"]}))
    return root


def _ledger(tmp: Path) -> Path:
    path = tmp / "ledger.sqlite"
    ledger = CoordinationLedger(path)
    store = LedgerReceiptStore(ledger)
    for i, (lane, state, reason) in enumerate([("incident-fanin", "ARTIFACT_WRITTEN", None), ("incident-fanin", "CONSUMED", None),
                                               ("approval-package-reminder", "REFUSED", "unknown_lane")]):
        rec = {"schema": "N8nCoordinationReceipt@v1", "state": state, "reason": reason, "event_id": f"evt-{i}", "source_project": "trade-ai",
               "lane_id": lane, "idempotency_key": f"k{i}", "origin_sha": SHA, "recorded_at": NOW.isoformat(), "durable": True,
               "artifact_ref": {"store": "data/runtime", "ref": "x.json", "sha256": "f" * 64, "as_of": NOW.isoformat()}}
        store[f"trade-ai:k{i}"] = {"payload_hash": "h", "receipt": rec}
    ledger.close()
    return path


def _deploy(tmp: Path) -> Path:
    sd = tmp / "deploy-state"; sd.mkdir()
    (sd / "deploy_receipt.json").write_text(json.dumps({"deployed_sha": SHA, "at": NOW.isoformat(), "ok": True, "source_pr": "1497", "prev_release": "x", "release_dir": "y", "rolled_back": False}))
    (sd / "post_merge_ci.json").write_text(json.dumps({"ok": True}))
    return sd


RET_LOG = """DB Retention Policy — 2026-10-06 04:10
Table   Column   Days   Deleted
  foo   created_at   30   10
  Total deleted: 10 rows
  Total pruned: 0 files
DB Retention Policy — 2026-10-07 20:42
Table   Column   Days   Deleted
  foo   created_at   30   21
  Total deleted: 1,044,725 rows; archived first: 630,480
  Total pruned: 70 files
"""


def _build(tmp: Path, **over):
    root = _root(tmp)
    reg = _registry(tmp, [_lane("live-lane", "ACTIVE", "data/runtime/live_lane_last.json"),
                          _lane("silent-lane", "ACTIVE", "data/runtime/never_written.json"),
                          _lane("off-lane", "NEVER_SCHEDULED", "data/runtime/off.json")])
    log = tmp / "db_retention.log"; log.write_text(RET_LOG)
    kw = dict(now=NOW, period="weekly", root=root, registry_path=reg, cron_text="0 * * * * live-lane.py\n0 * * * * silent-lane.py\n",
              include_systemd=False, ledger=_ledger(tmp), deploy_state_dir=_deploy(tmp), retention_log=log, served_sha=SHA)
    kw.update(over)
    return root, G.build_packet(**kw)


def test_packet_counts_come_from_the_fixtures():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root, pk = _build(Path(d))
        sm = pk["summary"]
        assert pk["period_key"] == "2026-W41" and pk["schema"] == G.SCHEMA and pk["authority"] == "READ_ONLY_ADVISORY"
        assert sm["lanes_declared"] == 3 and sm["lane_verdicts"].get("LIVE") == 1 and sm["lane_verdicts"].get("SILENT") == 1
        assert sm["ledger_by_state"] == {"ARTIFACT_WRITTEN": 1, "CONSUMED": 1, "REFUSED": 1} and sm["ledger_refusals"] == {"unknown_lane": 1}
        assert pk["sections"]["ledger"]["per_lane"]["incident-fanin"] == {"ARTIFACT_WRITTEN": 1, "CONSUMED": 1}
        assert sm["incidents_open"] == 3 and sm["incidents_by_severity"] == {"P1": 1, "P2": 2}
        assert pk["sections"]["incidents"]["by_source"] == {"db_hygiene": 2, "expected_services": 1}
        assert sm["release"] == {"sha": SHA, "at": NOW.isoformat(), "ok": True} and pk["sections"]["releases"]["conformance"]["verdict"] == "WARN"
        assert sm["retention_last_run"] == {"ran_at": "2026-10-07 20:42", "rows_deleted": 1044725, "rows_archived_first": 630480, "tables_not_enforced": 0}
        assert sm["hygiene_findings"] == 1 and pk["sections"]["retention"]["hygiene"]["items"] == ["P2 SIZE_BUDGET trade_ai"]
        md = G.render_markdown(pk)
        assert "## Retention" in md and "1044725" in md and "`silent-lane`" in md


def test_the_retention_parser_reads_only_the_last_block_and_knows_dry_runs():
    last = G.parse_retention_log(RET_LOG)
    assert last["ran_at"] == "2026-10-07 20:42" and last["rows_deleted"] == 1044725 and last["dry_run"] is False
    dry = G.parse_retention_log("DB Retention Policy — 2026-10-08 01:00\n  Total would delete: 808 rows; archived first: 0\n")
    assert dry["dry_run"] is True and dry["rows_deleted"] == 808
    assert G.parse_retention_log("")["status"] == "NO_RUN"


def test_dry_run_writes_nothing_and_write_produces_json_md_and_receipt(tmp_path):
    root, pk = _build(tmp_path)
    before = sorted(p.name for p in (root / "data" / "governance").iterdir())
    rc = G.main(["--dry-run", "--period", "weekly", "--root", str(root), "--registry", str(tmp_path / "lane_registry.json"),
                 "--ledger", str(tmp_path / "ledger.sqlite"), "--retention-log", str(tmp_path / "db_retention.log"),
                 "--deploy-state-dir", str(tmp_path / "deploy-state"), "--no-systemd", "--now", NOW.isoformat()])
    assert rc == 0 and sorted(p.name for p in (root / "data" / "governance").iterdir()) == before
    assert not (root / G.RECEIPT_REL).exists()
    paths = G.write_packet(pk, root=root)
    assert Path(paths["json"]).name == "lane_governance_packet_weekly_2026-W41.json" and Path(paths["md"]).exists()
    receipt = json.loads((root / G.RECEIPT_REL).read_text())
    assert receipt["schema"] == G.SCHEMA and receipt["summary"]["lanes_declared"] == 3 and receipt["ops_summary"] is None
    assert len(receipt["packet_sha256"]) == 64


def test_the_ops_summary_model_job_draft_and_its_typed_refusals_never_touch_the_network(tmp_path):
    root, pk = _build(tmp_path)
    G.write_packet(pk, root=root)
    ok = G.draft_ops_summary(root=root, period="weekly", key="2026-W41", now=NOW, governed_call=G.fixture_call("valid"))
    assert ok["state"] == "ARTIFACT_WRITTEN" and ok["lane"] is None and "no lane for ops summary yet" in ok["note"]
    art = json.loads(Path(ok["artifact"]).read_text())
    assert art["receipt"]["artifact_out"]["schema_id"] == G.OPS_SCHEMA_ID and art["receipt"]["artifact_out"]["body"]["recommendation"] == "NONE"
    assert json.loads((root / G.RECEIPT_REL).read_text())["ops_summary"]["state"] == "ARTIFACT_WRITTEN"
    for mode, reason in (("invalid_json", "invalid_json"), ("over_cap", "over_cap"), ("outage", "provider_outage"), ("schema_invalid", "schema_invalid")):
        r = G.draft_ops_summary(root=root, period="weekly", key="2026-W41", now=NOW, governed_call=G.fixture_call(mode))
        assert r["state"] == "REFUSED" and r["reason"] == reason, (mode, r)


def test_the_output_contract_is_registered_and_forbids_actions():
    from scripts.lib import n8n_model_job as M
    s = M.load_schemas()[G.OPS_SCHEMA_ID]
    assert set(s["required"]) == {"headline", "sections", "open_items", "sources_cited", "confidence_note"}
    assert s["properties"]["recommendation"]["enum"] == ["NONE"] and "order" in s["forbidden_keys"]


def test_the_lane_is_declared_never_scheduled_with_its_receipt_as_signal():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lane = next(l for l in reg["lanes"] if l["lane_id"] == "lane-governance-packet-weekly")
    assert lane["state"] == "NEVER_SCHEDULED" and lane["scheduler"]["kind"] == "none"
    assert lane["output_signal"]["path"] == G.RECEIPT_REL and "grant" in lane["state_reason"]

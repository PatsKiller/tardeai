"""AGENTS.md 3.0.0 §23.10 P16 — n8n activations reconciled against the guard ledger (audit C G5).

Fixture n8n evidence and a fixture guard audit jsonl under tmp_path; no docker, no real ledger.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_n8n_activation_grants as A  # noqa: E402

SINCE = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)

EVIDENCE = {
    "workflows": [
        {"id": "e18d7849b4142927", "name": "maturity-remeasure", "active": True},
        {"id": "f4553ff360e21a9f", "name": "premarket-data-pipeline-shadow", "active": True},
        {"id": "c0d4c7845e5c4fcc", "name": "crontab-snapshot-for-health-agent", "active": True},
        {"id": "078e8fcbea0c5020", "name": "n8n-pilot-dispatch", "active": True},
        {"id": "722fac0e043ea5c4", "name": "n8n-incident-fanin", "active": True},
        {"id": "s57KBllvqf6Jb5xF", "name": "n8n-monitor-trade-ai", "active": False},
    ],
    "publish_history": [
        {
            "workflow_id": "s57KBllvqf6Jb5xF",
            "version_id": "old",
            "event": "activated",
            "at": "2026-10-08 13:23:15.104+00",
        },
        {
            "workflow_id": "s57KBllvqf6Jb5xF",
            "version_id": "old",
            "event": "deactivated",
            "at": "2026-10-09 13:37:53.81+00",
        },
        {
            "workflow_id": "c0d4c7845e5c4fcc",
            "version_id": "v-snap",
            "event": "activated",
            "at": "2026-10-09 13:30:00+00",
        },
    ],
    "published_versions": [
        # granted: service grant names the id, 2 minutes earlier, 2h window
        {
            "workflow_id": "e18d7849b4142927",
            "version_id": "v-mat",
            "at": "2026-10-09 13:03:16.96+00",
            "updated_at": "2026-10-09 13:03:16.96+00",
        },
        # ungranted: only a release-write grant without the id was live
        {
            "workflow_id": "f4553ff360e21a9f",
            "version_id": "v-pre",
            "at": "2026-10-09 12:39:45.591+00",
            "updated_at": "2026-10-09 13:03:16.33+00",
        },
        # same version as the publish_history row above -> one event, two sources
        {
            "workflow_id": "c0d4c7845e5c4fcc",
            "version_id": "v-snap",
            "at": "2026-10-09 13:30:01+00",
            "updated_at": "2026-10-09 13:30:01+00",
        },
        # named only by lane name in a cron grant
        {
            "workflow_id": "078e8fcbea0c5020",
            "version_id": "v-pd",
            "at": "2026-10-09 01:58:38.087+00",
            "updated_at": "2026-10-09 13:03:16.585+00",
        },
        # published before --since: out of scope, even though updatedAt (restart) is after it
        {
            "workflow_id": "722fac0e043ea5c4",
            "version_id": "v-fan",
            "at": "2026-10-08 23:58:37+00",
            "updated_at": "2026-10-09 13:03:15.957+00",
        },
    ],
    "version_history": [
        {
            "workflow_id": "c0d4c7845e5c4fcc",
            "version_id": "v-snap",
            "authors": "import",
            "at": "2026-10-09 12:00:00+00",
        },
    ],
}

GRANTS = [
    {
        "event": "grant-issued",
        "tier": "service",
        "seconds": 7200,
        "ts": "2026-10-09T09:01:00-04:00",
        "reason": "maturity-remeasure canary: operator imports live workflow e18d7849b4142927, unpublishes shadow",
    },
    {
        "event": "grant-issued",
        "tier": "release-write",
        "seconds": 7200,
        "ts": "2026-10-09T08:38:40-04:00",
        "reason": "PR #1543 sha a9fa8b89b: prepare + promote",
    },
    {
        "event": "grant-issued",
        "tier": "release-write",
        "seconds": 1800,
        "ts": "2026-10-09T09:10:00-04:00",
        "reason": "promote; also covers c0d4c7845e5c4fcc",
    },
    {
        "event": "grant-issued",
        "tier": "cron",
        "seconds": 14400,
        "ts": "2026-10-08T21:43:29-04:00",
        "reason": "n8n N1 cutover window: cutover_lane.sh --apply for n8n-pilot-dispatch, n8n-incident-fanin",
    },
    {
        "event": "auto-accepted",
        "tier": "service",
        "ts": "2026-10-09T09:02:00-04:00",
        "command": "systemctl restart f4553ff360e21a9f",
    },
]


def _guard_log(tmp_path: Path, grants=GRANTS) -> Path:
    p = tmp_path / "audit.jsonl"
    lines = [json.dumps(g) for g in grants]
    lines.insert(1, '{"event":"grant-issued","tier":"cron","reason":"torn')  # concurrent-append torn line
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _rows(tmp_path: Path, **kw) -> dict:
    grants = A.load_grants(_guard_log(tmp_path))
    rows = A.reconcile(A.activation_events(EVIDENCE, since=SINCE), grants, **kw)
    return {r["workflow_id"]: r for r in rows}


def test_parse_ts_handles_psql_and_iso_offsets():
    assert A.parse_ts("2026-10-09 13:03:16.96+00") == datetime(2026, 10, 9, 13, 3, 16, 960000, tzinfo=timezone.utc)
    assert A.parse_ts("2026-10-09T09:01:00-04:00") == datetime(2026, 10, 9, 13, 1, tzinfo=timezone.utc)
    assert A.parse_ts("2026-10-09T00:00:00Z") == SINCE
    assert A.parse_ts("garbage") is None and A.parse_ts(None) is None


def test_only_grant_issued_entries_are_read_and_torn_lines_are_skipped(tmp_path):
    grants = A.load_grants(_guard_log(tmp_path))
    assert [g["tier"] for g in grants] == ["service", "release-write", "release-write", "cron"]


def test_events_are_one_per_version_since_t_and_restart_updates_are_not_activations():
    events = A.activation_events(EVIDENCE, since=SINCE)
    ids = [e["workflow_id"] for e in events]
    assert "722fac0e043ea5c4" not in ids  # published before since; updated_at is a restart
    assert "s57KBllvqf6Jb5xF" not in ids  # activated before since; deactivation is not an activation
    snap = next(e for e in events if e["workflow_id"] == "c0d4c7845e5c4fcc")
    assert snap["sources"] == ["publish_history:activated", "published_version"]
    assert snap["imported_at"] == datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert len(ids) == len(set(ids)) == 4


def test_verdicts(tmp_path):
    rows = _rows(tmp_path)
    assert rows["e18d7849b4142927"]["status"] == A.GRANTED
    assert rows["e18d7849b4142927"]["grants"][0]["tier"] == "service"
    assert rows["f4553ff360e21a9f"]["status"] == A.UNGRANTED_ACTIVATION
    assert rows["c0d4c7845e5c4fcc"]["status"] == A.NAMED_IN_OTHER_TIER
    assert rows["078e8fcbea0c5020"]["status"] == A.NAME_ONLY_GRANT


def test_tier_list_is_configurable(tmp_path):
    rows = _rows(tmp_path, tiers=("cron", "config-write", "service", "release-write"))
    assert rows["c0d4c7845e5c4fcc"]["status"] == A.GRANTED


def test_a_grant_issued_after_its_window_does_not_cover_an_earlier_activation(tmp_path):
    late = [dict(GRANTS[0], ts="2026-10-09T11:00:00-04:00")]
    grants = A.load_grants(_guard_log(tmp_path, late))
    rows = {r["workflow_id"]: r for r in A.reconcile(A.activation_events(EVIDENCE, since=SINCE), grants)}
    assert rows["e18d7849b4142927"]["status"] == A.UNGRANTED_ACTIVATION


def test_an_id_must_be_named_as_a_whole_token(tmp_path):
    prefix = [dict(GRANTS[0], reason="covers e18d7849b414292 and xe18d7849b4142927")]
    grants = A.load_grants(_guard_log(tmp_path, prefix))
    rows = {r["workflow_id"]: r for r in A.reconcile(A.activation_events(EVIDENCE, since=SINCE), grants)}
    assert rows["e18d7849b4142927"]["status"] == A.UNGRANTED_ACTIVATION


def test_the_import_time_can_be_the_covered_moment(tmp_path):
    early = [
        {
            "event": "grant-issued",
            "tier": "config-write",
            "seconds": 1800,
            "ts": "2026-10-09T07:55:00-04:00",
            "reason": "import c0d4c7845e5c4fcc",
        }
    ]
    grants = A.load_grants(_guard_log(tmp_path, early))
    rows = {r["workflow_id"]: r for r in A.reconcile(A.activation_events(EVIDENCE, since=SINCE), grants)}
    assert rows["c0d4c7845e5c4fcc"]["status"] == A.GRANTED


def test_main_dry_run_write_and_exit_codes(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    ev = tmp_path / "evidence.json"
    ev.write_text(json.dumps(EVIDENCE), encoding="utf-8")
    log = _guard_log(tmp_path)
    base = ["--evidence-json", str(ev), "--guard-log", str(log), "--since", "2026-10-09T00:00:00Z"]
    assert A.main([*base, "--dry-run"]) == 0
    assert not (state / A.RECEIPT_REL).exists()
    out = capsys.readouterr().out
    assert "GRANTED=1" in out and "UNGRANTED_ACTIVATION=1" in out
    assert A.main([*base, "--write"]) == 0
    rec = json.loads((state / A.RECEIPT_REL).read_text(encoding="utf-8"))
    assert rec["schema"] == "N8nActivationAttribution@v1" and rec["verdict"] == A.UNGRANTED_ACTIVATION
    assert rec["events"] == 4 and rec["fanin_wired"] is False and rec["guard_log"] == "audit.jsonl"
    ung = [f for f in rec["fanin_findings"] if f["item"].endswith(A.UNGRANTED_ACTIVATION)]
    assert ung and ung[0]["source"] == "n8n_activation_grants" and ung[0]["severity"] == "P2"
    assert A.main([*base, "--fail-on-ungranted"]) == 1
    assert A.main(["--evidence-json", str(ev), "--guard-log", str(tmp_path / "absent.jsonl")]) == 2
    assert A.main([*base[:4], "--since", "not-a-time"]) == 2


def test_default_guard_log_follows_the_guard_lib_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GUARD_AUDIT_LOG", str(tmp_path / "x.jsonl"))
    assert A.default_guard_log() == tmp_path / "x.jsonl"
    monkeypatch.delenv("GUARD_AUDIT_LOG")
    assert A.default_guard_log() == Path.home() / "logs" / "cursor-agent-audit.jsonl"

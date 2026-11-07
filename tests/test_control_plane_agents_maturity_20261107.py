"""LQ-20261107-177: the agents row and the maturity envelope must not overstate what they carry.

Measured on the live host before this change (GET-only, 2026-11-07, ``127.0.0.1:7777``):

* ``/api/v3/control-plane/agents`` -- ``data_quality AVAILABLE`` over a one-row collection whose
  row carried ``agent_id, role, last_wake, runtime_state`` (4 of the 21 keys the Agent Office detail
  panel reads). The trace store it was projected from carries ``trigger``, ``decision.current_action``,
  ``trace_id``, ``status`` and a start/end pair, all of which were thrown away.
* ``/api/v3/control-plane/maturity`` -- ``data_quality EMPTY`` (page banner: "UNAVAILABLE -- the
  backing source has no usable data") over 14 live dimensions, three of them with four-digit counts
  read from ``data/persistent_wake/state/wakes.jsonl``. ``_maturity_has_evidence()`` tested
  ``source_store.startswith(root)``, which no relative label the builder emits can satisfy, so it
  answered False at every root -- populated or empty.

Pins:
* the row keeps the fields the trace row actually carries and stays null where it carries nothing;
* the row states how much of the 21-key page contract it fills (and the marker follows the page);
* a failure survives the agent's next success, across the compaction that ``_read_jsonl`` performs;
* a relative store label is evidence about the reported root; a host/DB scope, a sibling path that
  merely shares a string prefix, and a ``..`` climb are not;
* a root holding recorded wakes answers AVAILABLE end to end, and an empty root -- with a live
  database behind it -- still answers EMPTY (the guard the prefix test was defending).

COVERS = ["scripts/control_plane_api.py"]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.control_plane_api as api  # noqa: E402

PAGE = ROOT / "apps" / "command-center-v3" / "src" / "pages" / "control-plane" / "r22" / "AgentOfficePage.tsx"

WAKE_STORE = "data/persistent_wake/state/wakes.jsonl"


def _trace(
    agent: str = "alex",
    *,
    started: str = "2026-11-07T10:00:00Z",
    ended: str = "2026-11-07T10:00:04Z",
    status: str = "completed",
    trigger: str = "material_scan",
    action: str = "WAIT",
    trace_id: str = "tr_1",
) -> dict:
    """The shape of a live ``agent_run_traces.jsonl`` row (keys confirmed against the served store)."""
    return {
        "agent": agent,
        "role": "material_scan",
        "started_at": started,
        "ended_at": ended,
        "status": status,
        "trigger": trigger,
        "trace_id": trace_id,
        "decision": {"current_action": action, "decision_id": "dec_1", "symbol": "DATA_UNAVAILABLE"},
    }


def _isolate_root(monkeypatch, root: Path) -> None:
    """Point the module at ``root`` the way production does: no state-root override, project root only.

    ``tests/conftest.py`` pins ``TRADEAI_STATE_ROOT`` at a hermetic fixture root for every test, and
    ``_state_root()`` prefers that variable over ``PROJECT_ROOT``.
    """
    for name in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api, "PROJECT_ROOT", root)


def _root(tmp_path: Path, rows: list[dict]) -> Path:
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True, exist_ok=True)
    (cio / "agent_run_traces.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return tmp_path


def _agent_row(tmp_path: Path, monkeypatch, rows: list[dict]) -> dict:
    _isolate_root(monkeypatch, _root(tmp_path, rows))
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200, body
    assert body["data_quality"] == "AVAILABLE", body["data_quality"]
    assert body["data"]["pagination"]["total"] == 1
    return body["data"]["items"][0]


# ── the agents row ────────────────────────────────────────────────────────────


def test_the_row_keeps_the_fields_the_trace_row_carries(tmp_path, monkeypatch):
    row = _agent_row(tmp_path, monkeypatch, [_trace()])
    assert row["agent_id"] == "alex"
    assert row["role"] == "material_scan"
    assert row["last_wake"] == "2026-11-07T10:00:04Z"
    # the source row said all four of these; the old projection discarded them
    assert row["wake_reason"] == "material_scan"
    assert row["current_task"] == "WAIT"
    assert row["last_artifact"] == "tr_1"
    assert row["status"] == "completed"
    assert row["evidence_class"] == "CURRENT_SMOKE"
    assert row["latency"] == 4.0
    assert row["source_sha"] == api._sha()
    assert row["last_success"] == "2026-11-07T10:00:04Z"
    assert row["last_failure"] is None


def test_the_row_states_how_much_of_the_page_contract_it_fills(tmp_path, monkeypatch):
    row = _agent_row(tmp_path, monkeypatch, [_trace()])
    present, total = row["contract_fields_present"].split("/")
    assert int(total) == 21
    assert int(present) == 21 - len(row["contract_fields_missing"])
    assert int(present) >= 10, "the trace row alone must fill the identity, wake and status fields"
    # fields the source row genuinely does not carry stay missing -- nothing is invented
    for missing in ("queue_depth", "research_route", "model_route", "cost", "next_eligible_wake"):
        assert missing in row["contract_fields_missing"]
    assert "wake_reason" not in row["contract_fields_missing"]
    assert row["data_quality"] == "PARTIAL", "a partial row must not be served as a complete one"


def test_a_failure_survives_the_next_success(tmp_path, monkeypatch):
    row = _agent_row(tmp_path, monkeypatch, [
        _trace(started="2026-11-07T09:00:00Z", ended="2026-11-07T09:00:04Z", status="failed", trace_id="tr_fail"),
        _trace(started="2026-11-07T10:00:00Z", ended="2026-11-07T10:00:04Z", status="completed", trace_id="tr_ok"),
    ])
    assert row["last_artifact"] == "tr_ok"
    assert row["last_success"] == "2026-11-07T10:00:04Z"
    assert row["last_failure"] == "2026-11-07T09:00:04Z", "a failure must not vanish when the next wake succeeds"


def test_the_detail_endpoint_carries_the_enriched_row(tmp_path, monkeypatch):
    _isolate_root(monkeypatch, _root(tmp_path, [_trace()]))
    status, body = api.handle("/api/v3/control-plane/agents/alex")
    assert status == 200
    data = body["data"]
    assert data["wake_reason"] == "material_scan"
    assert data["current_task"] == "WAIT"
    assert data["last_artifact"] == "tr_1"
    assert data["latency"] == 4.0
    assert data["contract_fields_present"].endswith("/21")
    assert data["data_quality"] == "PARTIAL"


@pytest.mark.parametrize("every", [2, 7, 5000])
def test_the_projection_is_unchanged_by_compaction_with_failures(tmp_path, monkeypatch, every):
    """``_read_jsonl`` compacts with this projection mid-file; accumulators must survive that."""
    monkeypatch.setattr(api, "_JSONL_COMPACT_EVERY", every)
    rows = [
        _trace(agent=f"a{i % 3}", started=f"2026-11-07T00:{i:02d}:00Z", ended=f"2026-11-07T00:{i:02d}:04Z",
               status="failed" if i % 4 == 0 else "completed", trace_id=f"tr_{i}")
        for i in range(40)
    ]
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    expected = api._agents_from_traces([dict(r) for r in rows])
    got, quality = api._select_rows((path,), domain="agents")
    assert quality == "AVAILABLE"
    assert got == expected


def test_the_contract_field_list_matches_the_agent_office_detail_panel():
    """The marker counts the keys the page renders; if the page changes, this list must follow."""
    src = PAGE.read_text(encoding="utf-8")
    block = re.search(r"const keys = \[(.*?)\]", src, re.S)
    assert block, "AgentOfficePage no longer declares its detail keys as `const keys = [...]`"
    page_keys = re.findall(r"'([a-z_]+)'", block.group(1))
    assert tuple(page_keys) == api.AGENT_CONTRACT_FIELDS


# ── the maturity envelope ────────────────────────────────────────────────────


def _item(**over) -> dict:
    base = {
        "dimension": "persistent_wake_attempted",
        "evidence_class": "attempted",
        "count": 4029,
        "source_store": WAKE_STORE,
    }
    base.update(over)
    return base


def test_a_relative_store_label_is_evidence_about_this_root(tmp_path, monkeypatch):
    _isolate_root(monkeypatch, tmp_path)
    assert api._maturity_has_evidence({"items": [_item()]}) is True


@pytest.mark.parametrize(
    "store",
    [
        "postgresql:communication_deliveries",
        "user crontab",
        "systemd drop-in 32-comms-gateway-mode.conf",
        "/run/user/1000/tradeai/env+systemd drop-ins",
        "/etc/passwd",
        "/proc/self/status",
        "../outside/wakes.jsonl",
        "",
    ],
)
def test_host_and_database_scopes_are_not_evidence_about_a_root(tmp_path, monkeypatch, store):
    _isolate_root(monkeypatch, tmp_path)
    assert api._maturity_has_evidence({"items": [_item(source_store=store)]}) is False


def test_a_sibling_path_sharing_a_string_prefix_is_not_under_the_root(tmp_path, monkeypatch):
    """``startswith(root)`` accepted ``<root>-other``; path components are the honest test."""
    _isolate_root(monkeypatch, tmp_path)
    assert api._maturity_has_evidence({"items": [_item(source_store=f"{tmp_path}-other/wakes.jsonl")]}) is False


def test_an_observation_with_no_count_is_not_evidence(tmp_path, monkeypatch):
    _isolate_root(monkeypatch, tmp_path)
    assert api._maturity_has_evidence({"items": [_item(count=0)]}) is False
    assert api._maturity_has_evidence({"items": [_item(evidence_class="configured")]}) is False


@pytest.fixture
def host_probes(monkeypatch, tmp_path):
    """Close the builder's non-file inputs the way ``tests/test_whole_site_truth.py`` does."""
    from scripts.lib import campaign_maturity_truth as maturity
    from scripts.lib import maturity_score_latest_reader as reader

    # The historical score body resolves through a production path helper, not through ``root``.
    monkeypatch.setattr(
        reader, "persistent_maturity_score_path",
        lambda: tmp_path / "data" / "runtime" / "maturity_score_latest.json",
    )
    monkeypatch.setattr(maturity, "_flag_sources", lambda: {
        "PERSISTENT_WAKE_ENABLED": "1",
        "PERSISTENT_WAKE_SCHEDULE_ENABLED": "1",
        "COMMS_GATEWAY_MODE": "CANARY",
    })
    monkeypatch.setattr(maturity, "_crontab_has_persistent_wake", lambda: True)
    # a live database behind an empty root must not make that root LIVE
    monkeypatch.setattr(maturity, "_db_snapshot", lambda: {
        "available": True,
        "acr_total": 3,
        "acr_usable": 3,
        "delivery_owner_gateway": 3,
        "delivery_owner_legacy": 0,
        "deliveries_with_pmid": 3,
        "inbound_with_usable_receipt": 3,
        "shadow_proposals": 3,
        "error": None,
    })


def test_an_empty_root_with_a_live_database_is_still_empty(tmp_path, monkeypatch, host_probes):
    _isolate_root(monkeypatch, tmp_path)
    status, body = api.handle("/api/v3/control-plane/maturity")
    assert status == 200
    assert body["data"]["pagination"]["total"] == 14
    assert body["data_quality"] == "EMPTY", "postgres counts are evidence about the database, not about this root"


def test_a_root_with_recorded_wakes_reports_available(tmp_path, monkeypatch, host_probes):
    wakes = tmp_path / WAKE_STORE
    wakes.parent.mkdir(parents=True)
    wakes.write_text(json.dumps({"wake_reason": "material_scan", "provenance": {"trigger": "cron"}}) + "\n",
                     encoding="utf-8")
    _isolate_root(monkeypatch, tmp_path)
    status, body = api.handle("/api/v3/control-plane/maturity")
    assert status == 200
    assert body["data_quality"] == "AVAILABLE"
    attempted = next(i for i in body["data"]["items"] if i["dimension"] == "persistent_wake_attempted")
    assert attempted["count"] == 1
    assert attempted["source_store"] == WAKE_STORE

"""Execute the served SIEM reader with isolated rows and no application imports.

Only the dashboard function is compiled from its actual source: importing the
whole API would initialize unrelated services. Its five reads use an in-memory
query double; the real classification, grouping and response logic all execute.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


@pytest.fixture
def dashboard():
    path = ROOT / "scripts" / "api_v2.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_system_siem_dashboard"
    )
    code = compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec")

    def run(**source_rows):
        sources = dict.fromkeys(
            ("alert_events", "system_health_events", "notification_log", "hermes_alerts", "open_trade_alerts")
        )
        sources.update(source_rows)
        original = deepcopy(sources)
        reads = []

        def query(sql, params):
            assert sql.lstrip().startswith("SELECT"), "the dashboard must remain read-only"
            source = re.search(r"\bFROM\s+(\w+)", sql).group(1)
            assert source in sources, f"unexpected source: {source}"
            reads.append(source)
            return sources[source] or []

        namespace = {"_db_query": query, "_json_clean": lambda value: value.isoformat()}
        exec(code, namespace)
        result = namespace["_system_siem_dashboard"]()
        assert sources == original, "grouping must not mutate the source evidence"
        assert set(reads) == set(sources)
        return result

    return run


def alert(row_id, *, symbol="XYZ", source="worker", message="PYTHON_EXCEPTION: task failed", age=0, state="active"):
    return {
        "id": row_id,
        "alert_type": "system_health",
        "symbol": symbol,
        "severity": "critical",
        "source_script": source,
        "raw_text": message,
        "created_at": NOW - timedelta(seconds=age),
        "lifecycle_state": state,
    }


@pytest.mark.parametrize("repeats", [1, 2, 4, 10])
def test_repeated_open_p1_remains_one_visible_incident(dashboard, repeats):
    rows = [alert(index, age=index) for index in range(repeats)]
    result = dashboard(alert_events=rows)

    assert result["severity"] == {"P0": 0, "P1": 1, "P2": 0, "P3": 0}
    assert result["immediate_alerts"] == 1
    assert result["unique_groups"] == 1
    assert result["total_events"] == repeats
    assert result["suppressed"] == repeats - 1
    assert result["noise_reduction_pct"] == round(100 * (repeats - 1) / repeats, 1)
    assert result["type_counts"] == [{"type": "PIPELINE_FAILURE", "count": repeats}]
    event = result["recent_events"][0]
    assert event["severity"] == "P1"
    assert event["repeat_count"] == repeats
    assert event["suppressed"] is False
    assert event["first_seen"] == rows[-1]["created_at"].isoformat()
    assert event["last_seen"] == rows[0]["created_at"].isoformat()
    assert result["correlated"][0]["events"] == repeats


def test_two_distinct_groups_remain_two_visible_p1_incidents(dashboard):
    rows = [alert(index, symbol="AAA", age=index) for index in range(5)]
    rows += [alert(index + 10, symbol="BBB", age=index) for index in range(4)]
    result = dashboard(alert_events=rows)

    assert result["severity"]["P1"] == result["immediate_alerts"] == result["unique_groups"] == 2
    assert result["total_events"] == 9
    assert result["suppressed"] == 7
    assert sorted(event["repeat_count"] for event in result["recent_events"]) == [4, 5]
    assert result["correlated"][0]["groups"] == 2
    assert result["correlated"][0]["events"] == 9


def test_group_keeps_highest_severity_when_latest_row_is_lower(dashboard):
    # These admitted source records deliberately share a dedupe key. Telegram
    # delivery echoes are P3, while the older source event is a genuine P1.
    earlier = alert(1, symbol="echo", source="telegram", age=60)
    latest = {
        "id": 2,
        "channel": "telegram",
        "notification_type": "alert",
        "subject": "PYTHON_EXCEPTION: task failed",
        "body": "Delivery echo",
        "created_at": NOW,
    }
    result = dashboard(alert_events=[earlier], notification_log=[latest])

    assert result["severity"] == {"P0": 0, "P1": 1, "P2": 0, "P3": 0}
    assert result["immediate_alerts"] == 1
    assert result["unique_groups"] == 1
    assert result["total_events"] == 2
    event = result["recent_events"][0]
    assert event["id"] == "nl-2", "the latest evidence remains the representative"
    assert event["severity"] == "P1"
    assert event["repeat_count"] == 2
    assert result["top_dedupe_groups"][0]["severity"] == "P1"
    assert result["correlated"][0]["severity"] == "P1"


def test_acknowledgment_does_not_become_recovery(dashboard):
    result = dashboard(alert_events=[alert(1, state="acknowledged")])

    assert result["immediate_alerts"] == 1
    assert result["recent_events"][0]["lifecycle_state"] == "acknowledged"


def test_p2_classification_and_raw_repeat_evidence_are_preserved(dashboard):
    rows = [alert(index, message="queued backlog", age=index) for index in range(4)]
    result = dashboard(alert_events=rows)

    assert result["severity"] == {"P0": 0, "P1": 0, "P2": 1, "P3": 0}
    assert result["immediate_alerts"] == 0
    assert result["total_events"] == 4
    assert result["type_counts"] == [{"type": "QUEUE_BACKLOG", "count": 4}]
    assert result["recent_events"][0]["repeat_count"] == 4


def stop_alert(row_id, condition, *, account="fixture_account_a", order="fixture_order_a", message="stop condition"):
    row = alert(row_id, source="stop_health", message=message)
    row["alert_type"] = "strategic_alert"
    row["severity"] = "warning" if condition == "NEAR_TRIGGER" else "urgent"
    row["parsed_payload"] = {
        "account": account,
        "order_id": order,
        "symbol": "XYZ",
        "condition": condition,
    }
    return row


@pytest.mark.parametrize(
    "condition,priority",
    [
        ("ORPHANED", "P1"),
        ("OVERSIZED", "P1"),
        ("TRIGGERED", "P1"),
        ("NEAR_TRIGGER", "P2"),
    ],
)
def test_stop_condition_controls_type_without_prose_guessing(dashboard, condition, priority):
    row = stop_alert(1, condition, message="Stop health: on trigger it could reject")
    result = dashboard(alert_events=[row])
    event = result["recent_events"][0]
    assert event["event_type"] == "STOP_" + condition
    assert event["severity"] == priority
    assert result["immediate_alerts"] == int(priority == "P1")


def test_account_order_and_condition_are_separate_stop_incidents(dashboard):
    rows = [
        stop_alert(1, "OVERSIZED"),
        stop_alert(2, "OVERSIZED", account="fixture_account_b"),
        stop_alert(3, "OVERSIZED", order="fixture_order_b"),
        stop_alert(4, "ORPHANED"),
        stop_alert(5, "OVERSIZED", message="updated price and holdings prose"),
    ]
    result = dashboard(alert_events=rows)
    assert result["immediate_alerts"] == result["unique_groups"] == 4
    assert sorted(row["repeat_count"] for row in result["recent_events"]) == [1, 1, 1, 2]
    for event in result["recent_events"]:
        assert "fixture_account" not in event["dedupe_key"]
        assert "fixture_order" not in event["dedupe_key"]


@pytest.mark.parametrize("payload", [None, "not JSON", [], {"condition": []}])
def test_malformed_stop_identity_keeps_urgent_evidence_visible(dashboard, payload):
    row = stop_alert(1, "OVERSIZED")
    row["parsed_payload"] = payload
    result = dashboard(alert_events=[row])
    assert result["immediate_alerts"] == 1
    assert result["recent_events"][0]["event_type"] == "STOP_HEALTH"


def test_null_message_keeps_structured_risk(dashboard):
    row = stop_alert(1, "OVERSIZED", message=None)
    result = dashboard(alert_events=[row])
    assert result["immediate_alerts"] == 1
    assert result["recent_events"][0]["message"] == ""


def test_long_incomplete_messages_do_not_merge_distinct_evidence(dashboard):
    prefix = "stop condition " * 30
    rows = [stop_alert(1, "OVERSIZED", message=prefix + "first"), stop_alert(2, "OVERSIZED", message=prefix + "second")]
    for row in rows:
        row["parsed_payload"] = None
    result = dashboard(alert_events=rows)
    assert result["unique_groups"] == result["immediate_alerts"] == 2
    assert all(len(row["message"]) <= 150 for row in result["recent_events"])


@pytest.mark.parametrize("severity", ["urgent", "critical"])
def test_higher_source_severity_is_preserved(dashboard, severity):
    row = stop_alert(1, "NEAR_TRIGGER")
    row["severity"] = severity
    result = dashboard(alert_events=[row])
    assert result["immediate_alerts"] == 1
    assert result["recent_events"][0]["event_type"] == "STOP_NEAR_TRIGGER"

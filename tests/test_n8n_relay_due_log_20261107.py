"""The relay's due log names the lanes, not just the count (2026-11-07).

Live finding: three lanes are allowlisted for the dispatcher and eligible in the served release
(``self-heal-fixer-shadow`` since 2026-11-03, ``defense-cash-alternatives`` and
``dividend-calendar-refresh`` since 2026-11-06 19:49 ET) and none of them has ever appeared in a relay
request. The dispatcher's own due call at 14:30 ET returned ``{"items": 21, "truncated": 0}`` on three
consecutive trading days, and that count is the only surviving record of the answer: an offline replay
of the same registry, allowlist and ledger evaluates the lane as DUE for that slot, so either the
gateway withheld it (and ``errors`` would say why) or the caller dropped it. Neither can be told from
``items: 21``.

These tests pin the evidence: the line names the lanes the gateway answered, and the per-lane codes for
whatever the gateway withheld. Synthetic payloads only — no gateway, no socket, no credential.
"""

from __future__ import annotations

import json

from scripts import n8n_run_relay as R

KEY = "k" * 48
BEARER = "b" * 48
LANE = "n8n-lab-watchdog"


def _env(tmp_path):
    return {
        "TRADEAI_N8N_RELAY_BEARER": BEARER,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": KEY,
        "TRADEAI_STATE_ROOT": str(tmp_path),
    }


def _relay(tmp_path, reply):
    r = R.Relay(environ=_env(tmp_path), allowlist=frozenset({LANE}), transport=lambda *_: (200, reply))
    return r


def _due_line(r):
    r.due(f"Bearer {BEARER}", "")
    return r.last


def _response(items, errors=None, **extra):
    body = {"schema": "DueResponse@v1", "ok": True, "items": items, "truncated": 0}
    if errors is not None:
        body["errors"] = errors
    body.update(extra)
    return body


def test_the_due_line_names_every_lane_the_gateway_answered(tmp_path):
    reply = _response([
        {"lane_id": "self-heal-fixer-shadow", "mode": "dry_run", "idempotency_key": "d:self-heal-fixer-shadow:dry_run:20261106T1430"},
        {"lane_id": "unit-run-snapshot", "mode": "dry_run", "idempotency_key": "d:unit-run-snapshot:dry_run:20261106T1430"},
    ])
    line = _due_line(_relay(tmp_path, reply))
    assert line["items"] == 2
    assert line["due_lanes"] == "self-heal-fixer-shadow,unit-run-snapshot"


def test_a_withheld_lane_is_named_with_its_code(tmp_path):
    reply = _response(
        [{"lane_id": "unit-run-snapshot", "mode": "dry_run", "idempotency_key": "d:unit-run-snapshot:dry_run:20261106T1430"}],
        errors=[
            {"lane_id": "self-heal-fixer-shadow", "code": "class_not_permitted", "detail": "class 'report' under policy X"},
            {"lane_id": "dividend-calendar-refresh", "code": "not_allowlisted", "detail": "no run allowlist entry"},
        ],
    )
    line = _due_line(_relay(tmp_path, reply))
    assert line["due_lanes"] == "unit-run-snapshot"
    assert line["due_errors"] == "self-heal-fixer-shadow:class_not_permitted,dividend-calendar-refresh:not_allowlisted"


def test_the_detail_text_of_an_error_is_never_logged(tmp_path):
    """A detail names argv, paths or policy prose; the line keeps only the code."""
    reply = _response([], errors=[{"lane_id": "x-lane", "code": "bad_cron", "detail": "/home/someone/secret/path"}])
    line = _due_line(_relay(tmp_path, reply))
    assert line["due_errors"] == "x-lane:bad_cron"
    assert "secret" not in json.dumps(line)


def test_a_wide_answer_cannot_grow_one_line_without_limit(tmp_path):
    items = [{"lane_id": f"lane-{i:03d}", "mode": "dry_run", "idempotency_key": f"d:lane-{i:03d}:dry_run:x"} for i in range(120)]
    errors = [{"lane_id": f"lane-{i:03d}", "code": "class_not_permitted", "detail": ""} for i in range(120)]
    line = _due_line(_relay(tmp_path, _response(items, errors=errors)))
    assert len(line["due_lanes"]) <= R.DUE_LOG_LANES_MAX
    assert len(line["due_errors"]) <= R.DUE_LOG_ERRORS_MAX


def test_a_malformed_item_or_error_is_ignored_not_fatal(tmp_path):
    reply = _response(
        [{"lane_id": "ok-lane"}, {"mode": "dry_run"}, "not-a-dict", {"lane_id": None}],
        errors=[{"code": "no_lane"}, "not-a-dict", {"lane_id": "y-lane", "code": "bad_cron"}],
    )
    line = _due_line(_relay(tmp_path, reply))
    assert line["due_lanes"] == "ok-lane"
    assert line["due_errors"] == "None:no_lane,y-lane:bad_cron"


def test_a_refused_answer_says_nothing_about_lanes(tmp_path):
    line = _due_line(_relay(tmp_path, {"schema": "DueResponse@v1", "ok": False, "reason": "bad_source"}))
    assert line["state"] == "REFUSED"
    assert "due_lanes" not in line and "due_errors" not in line


def test_the_default_answer_shape_is_unchanged_for_an_empty_list(tmp_path):
    line = _due_line(_relay(tmp_path, _response([])))
    assert line["items"] == 0 and line["due_lanes"] == "" and "due_errors" not in line

"""Watch row readiness and factor provenance follow the composed CIO view."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.lib.site_payload_reads import canonical_rows


def source_row(lane="actionable"):
    return {
        "symbol": "ZZQA",
        "security_guid": "synthetic-security-guid",
        "lane": lane,
        "stage": "actionable" if lane == "actionable" else "held",
        "why": "Review re-entry now",
        "summary": "The source setup has conviction 79 and awaits a review.",
        "stance": "RE_ENTER",
        "conviction": 79,
        "conviction_source": "cio_opportunity_projection",
        "conviction_as_of": "2026-10-27T20:30:00Z",
        "conviction_components": [{"key": "technical", "label": "Technical", "value": 70}],
        "conflicts": [],
        "whats_missing": [],
        "held": lane == "manage",
        "next_action": {"kind": "propose", "label": "Review proposal", "reason": "Source setup ready"},
    }


def truth(**changes):
    return {
        "stance": "BUY_SETUP",
        "conviction": 71,
        "as_of": "2026-10-27T20:30:00Z",
        "stale": False,
        "conflicts": [],
        **changes,
    }


def compose(row, canonical):
    return canonical_rows([row], resolver=lambda *a, **kw: canonical, projection={})[0]


def test_canonical_disagreement_removes_actionable_claim_and_retains_source_context():
    row = source_row()
    before = deepcopy(row)
    result = compose(row, truth())

    assert result["next_action"]["kind"] == "resolve_conflict"
    assert result["lane"] == "forming"
    assert result["stage"] == "setup_forming"
    assert "review" in result["why"].lower()
    assert result["conviction"] == 71
    assert result["source_signal"]["conviction"] == 79
    assert result["source_signal"]["lane"] == "actionable"
    assert result["source_signal"]["why"] == before["why"]
    assert result["source_signal"]["summary"] == before["summary"]
    assert result["source_signal"]["as_of"] == before["conviction_as_of"]
    assert result["conviction_components"] == before["conviction_components"]
    assert row == before


def test_missing_cio_view_cannot_leave_an_actionable_row():
    result = compose(source_row(), truth(stance=None, conviction=None, gap={"reason": "CIO view unavailable"}))
    assert result["next_action"]["kind"] == "cio_missing"
    assert result["lane"] == "forming"
    assert result["stage"] == "setup_forming"
    assert "CIO view unavailable" in result["why"]
    assert result["conflicts"] == []


@pytest.mark.parametrize("resolved", [False, True, "false"])
def test_record_conflict_resolution_changes_readiness_without_erasing_history(resolved):
    conflict = {
        "summary": "The recorded source opinions disagree",
        "source_a": {"value": "RE_ENTER", "source_label": "CIO", "as_of": "2026-10-27T20:30:00Z"},
        "source_b": {"value": "WATCH", "source_label": "Research", "as_of": "2026-10-27T20:00:00Z"},
        "resolved": resolved,
    }
    result = compose(source_row(), truth(stance="RE_ENTER", conviction=79, conflicts=[conflict]))
    assert result["cio_truth"]["conflicts"] == [conflict]
    if resolved is True:
        assert result["lane"] == "actionable"
        assert result["next_action"]["kind"] == "propose"
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["resolved"] is True
    else:
        assert result["lane"] == "forming"
        assert result["next_action"]["kind"] == "resolve_conflict"
        assert result["conflicts"][0]["summary"] == conflict["summary"]


@pytest.mark.parametrize("resolved,expected", [(True, False), (False, True), ("false", True)])
def test_blocked_filter_requires_an_explicit_resolved_boolean(resolved, expected):
    from scripts.lib.data_broker.watch_position_facts import blocked

    row = {"conflicts": [{"resolved": resolved}], "next_action": {"kind": "propose"}}
    assert blocked(row) is expected


def test_resolved_history_never_clears_a_trade_gate_or_an_open_review():
    from scripts.lib.data_broker.watch_position_facts import blocked

    row = {"conflicts": [{"resolved": True}], "next_action": {"kind": "propose"}}
    assert blocked({**row, "trade_ai_state": "AVOID"}) is True
    assert blocked({**row, "next_action": {"kind": "resolve_conflict"}}) is True


def test_agreeing_cio_view_preserves_an_actionable_source_setup():
    row = source_row()
    result = compose(row, truth(stance="RE_ENTER", conviction=79))
    assert result["lane"] == row["lane"]
    assert result["why"] == row["why"]
    assert result["next_action"] == row["next_action"]


def test_conflicted_held_name_keeps_its_held_membership():
    row = source_row(lane="manage")
    result = compose(row, truth())
    assert result["lane"] == "manage"
    assert result["stage"] == "held"
    assert result["held"] is True
    assert result["next_action"]["kind"] == "resolve_conflict"


def test_prospects_membership_counts_caps_and_paging_follow_composed_readiness():
    from scripts.lib.site_payload_reads import prospects_page

    first = {**source_row(), "mine": True}
    second = {
        **source_row(),
        "symbol": "ZZQB",
        "security_guid": "other-fixture-guid",
        "lane": "forming",
        "stage": "setup_forming",
        "stance": "BUY_SETUP",
        "conviction": 71,
        "next_action": {"kind": "set_alert", "label": "Set alert", "reason": "Wait for evidence"},
    }
    payload = {
        "counts": {"actionable": 2, "forming": 1},
        "lanes": [
            {"id": "actionable", "count": 2, "cap": 1, "items": [first], "overflow": ["ZZOLD"]},
            {"id": "forming", "count": 1, "cap": 1, "items": [second], "overflow": []},
        ],
    }
    result = prospects_page(
        payload,
        {"lane": "forming", "limit": "1"},
        stance_resolver=lambda *a, **kw: truth(),
        stance_projection={},
        section_reader=lambda *a, **kw: {},
        review_reader=lambda *a, **kw: {},
    )
    forming = next(lane for lane in result["lanes"] if lane["id"] == "forming")
    assert result["lane_membership"]["ZZQA"] == "forming"
    assert result["counts"] == {"actionable": 1, "forming": 2}
    assert forming["count"] == 2  # the operator's row does not consume the system's cap
    assert result["pagination"]["total"] == 2
    assert len(forming["items"]) == 1
    assert result["lane_membership_unverified"] == {"actionable": ["ZZOLD"]}


@pytest.mark.parametrize(
    "query,source_conv,canonical_conv,expected",
    [
        ({"conv": "80"}, 79, 85, ["ZZQA"]),
        ({"conv": "80"}, 85, 71, []),
        ({"stage": "forming"}, 79, 71, ["ZZQA"]),
        ({"stage": "actionable"}, 79, 71, []),
    ],
)
def test_personal_filters_use_canonical_values_and_preserve_full_population(
    tmp_path, monkeypatch, query, source_conv, canonical_conv, expected
):
    from scripts.lib import site_payload_reads as reads
    from scripts.lib.data_broker import watch_prospects, watch_curation

    row = {
        **source_row(),
        "conviction": source_conv,
        "mine": True,
        "starred": True,
        "membership": [],
        "position_state": "never_held",
        "conviction_missing": [],
    }
    g = {
        "now": NOW,
        "payload": {},
        "row_for": lambda symbol: deepcopy(row),
        "opps": {},
        "operator": {"ZZQA": {}},
        "held": set(),
        "proj_meta": {},
    }
    monkeypatch.setattr(watch_prospects, "gather", lambda q: g)
    monkeypatch.setattr(watch_curation, "read_dismissed", lambda **kw: ({}, "ok"))
    result = reads.read_curation(
        {**query, "view": "mine"},
        stance_resolver=lambda *a, **kw: truth(conviction=canonical_conv),
        stance_projection={},
        section_reader=lambda *a, **kw: {},
        section_root=tmp_path,
        review_reader=lambda *a, **kw: {},
    )
    mine = result["my_watchlist"]
    assert [r["symbol"] for r in mine["rows"]] == expected
    assert mine["count"] == len(expected)
    assert mine["unfiltered_count"] == 1
    assert mine["pagination"]["total"] == len(expected)


GUID = "d9be46f8-cb52-4b29-a7e6-68a55ebdc622"
OTHER_GUID = "a64fa76d-4124-42a8-b42b-0d0a52438058"
NOW = datetime(2026, 10, 27, 21, 17, tzinfo=timezone.utc)


def queued_request(monkeypatch, extra=None, identity=None, attempts=()):
    from scripts.lib import identity_carriage, symbol_thesis_priority as queue
    from scripts.lib import watch_review_publication as publication

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(publication, "datetime", Clock)
    request = {
        "symbol": "ZZQA",
        "request_id": "rr_legacy",
        "requested_at": (NOW - timedelta(days=2)).isoformat(),
        **(extra or {}),
    }
    monkeypatch.setattr(queue, "review_states", lambda *a, **kw: {"ZZQA": {"open": True, "request_id": "rr_legacy"}})
    monkeypatch.setattr(
        queue, "_rows", lambda path: [request] if str(path).endswith(queue.RELPATH[-1]) else deepcopy(list(attempts))
    )
    identity = {"identity_status": "CONFIRMED", "security_guid": GUID} if identity is None else identity
    monkeypatch.setattr(identity_carriage, "resolve_security_identity", lambda *a, **kw: deepcopy(identity))
    return request


def test_legacy_request_revalidates_current_registry_identity_without_rewriting_question(tmp_path, monkeypatch):
    from scripts.lib import watch_review_publication as publication

    original = queued_request(monkeypatch)
    before = deepcopy(original)
    pending = publication.pending_request(tmp_path, "ZZQA")
    assert publication.request_blocker(tmp_path, pending) is None
    assert pending["identity_status"] == "CONFIRMED"
    assert pending["security_guid"] == GUID
    assert pending["request_id"] == before["request_id"]
    assert pending["requested_at"] == before["requested_at"]
    assert pending["identity_binding"]["basis"] == "current_registry_readback_for_legacy_request"
    assert pending["identity_binding"]["security_guid"] == GUID
    assert pending["identity_binding"]["bound_at"] == NOW.isoformat()
    assert original == before


@pytest.mark.parametrize(
    "extra,identity,expected",
    [
        (
            {"identity_status": "UNRESOLVED"},
            {"identity_status": "CONFIRMED", "security_guid": GUID},
            "REQUEST_IDENTITY_UNCONFIRMED",
        ),
        (
            {"identity_status": "CONFIRMED"},
            {"identity_status": "CONFIRMED", "security_guid": GUID},
            "REQUEST_IDENTITY_UNCONFIRMED",
        ),
        (
            {"security_guid": GUID},
            {"identity_status": "CONFIRMED", "security_guid": GUID},
            "REQUEST_IDENTITY_UNCONFIRMED",
        ),
        (
            {"identity_status": "CONFIRMED", "security_guid": OTHER_GUID},
            {"identity_status": "CONFIRMED", "security_guid": GUID},
            "REQUEST_IDENTITY_CHANGED",
        ),
        ({}, {"identity_status": "UNRESOLVED", "security_guid": None}, "REQUEST_IDENTITY_UNCONFIRMED"),
        ({}, {"identity_status": "AMBIGUOUS", "security_guid": GUID}, "REQUEST_IDENTITY_UNCONFIRMED"),
        ({}, {"identity_status": "CONFIRMED", "security_guid": "ZZQA"}, "REQUEST_IDENTITY_UNCONFIRMED"),
    ],
)
def test_legacy_compatibility_does_not_relax_identity_refusals(tmp_path, monkeypatch, extra, identity, expected):
    from scripts.lib import watch_review_publication as publication

    queued_request(monkeypatch, extra=extra, identity=identity)
    pending = publication.pending_request(tmp_path, "ZZQA")
    assert publication.request_blocker(tmp_path, pending) == expected
    assert "identity_binding" not in pending


def test_acquisition_owner_validates_legacy_identity_and_records_binding(tmp_path, monkeypatch):
    from scripts import run_symbol_thesis_acquisition as worker
    from scripts.lib import identity_carriage

    original = queued_request(monkeypatch)
    calls = []
    identity_calls = []

    def identity(symbol, **kwargs):
        identity_calls.append(symbol)
        return {"identity_status": "CONFIRMED", "security_guid": GUID}

    def research(symbol, **kwargs):
        assert identity_calls == ["ZZQA", "ZZQA"]  # binding, then the unchanged pre-work guard
        calls.append(symbol)
        return {"symbol": symbol, "status": "BLOCKED", "block_reason": "INSUFFICIENT_STORED_EVIDENCE"}

    monkeypatch.setattr(worker, "run_one", research)
    monkeypatch.setattr(identity_carriage, "resolve_security_identity", identity)
    monkeypatch.setattr(worker, "_now", lambda: NOW.isoformat())
    result = worker.run(root=tmp_path, symbols=["ZZQA"], apply=True, max_llm=0)
    assert calls == ["ZZQA"]
    assert result["llm_calls_used"] == 0
    row = result["results"][0]
    assert row["block_reason"] == "INSUFFICIENT_STORED_EVIDENCE"
    assert row["request_id"] == original["request_id"]
    assert row["security_guid"] == GUID
    assert row["identity_binding"]["security_guid"] == GUID
    saved = json.loads((tmp_path / worker.LEDGER_REL).read_text().splitlines()[-1])
    assert saved["request_id"] == original["request_id"]
    assert saved["identity_binding"] == row["identity_binding"]


def prior_attempt(guid=GUID, **changes):
    return {
        "symbol": "ZZQA",
        "request_id": "rr_legacy",
        "as_of": (NOW - timedelta(hours=1)).isoformat(),
        "status": "BLOCKED",
        "security_guid": guid,
        "identity_binding": {
            "basis": "current_registry_readback_for_legacy_request",
            "security_guid": guid,
            "bound_at": (NOW - timedelta(hours=1)).isoformat(),
        },
        **changes,
    }


@pytest.mark.parametrize("current_guid,expected", [(GUID, None), (OTHER_GUID, "REQUEST_IDENTITY_CHANGED")])
def test_legacy_retry_preserves_first_durable_identity_and_binding(tmp_path, monkeypatch, current_guid, expected):
    from scripts.lib import watch_review_publication as publication

    prior = prior_attempt()
    original = queued_request(
        monkeypatch, attempts=[prior], identity={"identity_status": "CONFIRMED", "security_guid": current_guid}
    )
    pending = publication.pending_request(tmp_path, "ZZQA")
    assert pending["security_guid"] == GUID
    assert pending["identity_binding"] == prior["identity_binding"]
    assert pending["request_id"] == original["request_id"]
    assert pending["requested_at"] == original["requested_at"]
    assert publication.request_blocker(tmp_path, pending) == expected
    assert "security_guid" not in original


def test_legacy_history_with_a_guid_but_no_binding_still_pins_identity(tmp_path, monkeypatch):
    from scripts.lib import watch_review_publication as publication

    prior = prior_attempt()
    prior.pop("identity_binding")
    queued_request(
        monkeypatch, attempts=[prior], identity={"identity_status": "CONFIRMED", "security_guid": OTHER_GUID}
    )
    pending = publication.pending_request(tmp_path, "ZZQA")
    assert pending["security_guid"] == GUID
    assert pending["identity_binding"]["bound_at"] == prior["as_of"]
    assert publication.request_blocker(tmp_path, pending) == "REQUEST_IDENTITY_CHANGED"


def test_unbound_blocked_attempts_and_unrelated_requests_do_not_prevent_legacy_upgrade(tmp_path, monkeypatch):
    from scripts.lib import watch_review_publication as publication

    queued_request(
        monkeypatch,
        attempts=[
            {"symbol": "ZZQA", "request_id": "rr_legacy", "status": "BLOCKED", "security_guid": None},
            prior_attempt(OTHER_GUID, request_id="rr_unrelated"),
        ],
    )
    pending = publication.pending_request(tmp_path, "ZZQA")
    assert pending["security_guid"] == GUID
    assert publication.request_blocker(tmp_path, pending) is None


@pytest.mark.parametrize(
    "attempts",
    [
        [prior_attempt(), prior_attempt(OTHER_GUID)],
        [prior_attempt(identity_binding={"security_guid": OTHER_GUID})],
        [prior_attempt(security_guid="invalid-registry-guid")],
        [{"symbol": "ZZQA", "request_id": "rr_legacy", "status": "PUBLISHED"}],
    ],
)
def test_legacy_ambiguous_or_unproven_history_cannot_rebind(tmp_path, monkeypatch, attempts):
    from scripts.lib import watch_review_publication as publication

    queued_request(monkeypatch, attempts=attempts)
    pending = publication.pending_request(tmp_path, "ZZQA")
    assert publication.request_blocker(tmp_path, pending) == "REQUEST_IDENTITY_UNCONFIRMED"


def test_drifted_legacy_retry_reaches_neither_research_nor_publication_link(tmp_path, monkeypatch):
    from scripts import run_symbol_thesis_acquisition as worker
    from scripts.lib import watch_review_publication as publication

    queued_request(
        monkeypatch,
        attempts=[prior_attempt(status="PUBLISHED", cio_link={"ok": False})],
        identity={"identity_status": "CONFIRMED", "security_guid": OTHER_GUID},
    )
    monkeypatch.setattr(worker, "run_one", lambda *a, **kw: pytest.fail("identity drift reached research"))
    monkeypatch.setattr(publication, "link_publication", lambda *a, **kw: pytest.fail("identity drift reached linking"))
    result = worker.run(root=tmp_path, symbols=["ZZQA"], apply=True, max_llm=0)
    assert result["llm_calls_used"] == 0
    assert result["results"][0]["block_reason"] == "REQUEST_IDENTITY_CHANGED"
    assert result["results"][0]["security_guid"] == GUID


def test_legacy_same_identity_retries_a_published_link_without_research(tmp_path, monkeypatch):
    from scripts import run_symbol_thesis_acquisition as worker
    from scripts.lib import watch_review_publication as publication

    prior = prior_attempt(status="PUBLISHED", cio_link={"ok": False}, review={"new_version": "synthetic@v1"})
    queued_request(monkeypatch, attempts=[prior])
    monkeypatch.setattr(worker, "run_one", lambda *a, **kw: pytest.fail("link retry repurchased research"))
    monkeypatch.setattr(
        publication, "link_publication", lambda *a, **kw: {"ok": True, "publication": {"id": "synthetic"}}
    )
    result = worker.run(root=tmp_path, symbols=["ZZQA"], apply=True, max_llm=0)
    assert result["llm_calls_used"] == 0
    row = result["results"][0]
    assert row["publication_link_retry"] is True
    assert row["security_guid"] == GUID
    assert row["identity_binding"] == prior["identity_binding"]


def test_completed_publication_lookup_excludes_another_security(tmp_path, monkeypatch):
    from scripts.lib import watch_review_publication as publication

    request = queued_request(
        monkeypatch,
        extra={"identity_status": "CONFIRMED", "security_guid": GUID},
        attempts=[prior_attempt(OTHER_GUID, status="PUBLISHED")],
    )
    assert publication.published_for_request(tmp_path, request) is None
    assert publication.request_blocker(tmp_path, request) == "REQUEST_IDENTITY_CHANGED"


def test_publication_link_refuses_an_explicit_foreign_identity_before_readback(tmp_path, monkeypatch):
    from scripts.lib import watch_review_publication as publication

    request = queued_request(monkeypatch, extra={"identity_status": "CONFIRMED", "security_guid": GUID})
    result = {"status": "PUBLISHED", "security_guid": OTHER_GUID, "review": {"new_version": "synthetic@v1"}}
    assert (
        publication.link_publication(tmp_path, request, result)["reason"]
        == "publication_identity_unconfirmed_or_changed"
    )


def test_prospects_preserves_cache_control_while_deferring_filters(monkeypatch):
    from scripts import api_v3_data_broker_watch as api
    from lib.data_broker import watch_prospects
    from lib import site_payload_reads

    seen = {}

    def source(query):
        seen["source"] = query
        return {"status": "ok", "lanes": []}

    def compose(payload, query):
        seen["canonical_filters"] = query
        return payload

    monkeypatch.setattr(watch_prospects, "list_watch_prospects", source)
    monkeypatch.setattr(site_payload_reads, "prospects_page", compose)
    query = {"fresh": "1", "conviction_min": "80", "blocked": "1"}
    api.get_prospects(query)
    assert seen["source"] == {"fresh": "1"}
    assert seen["canonical_filters"] == query

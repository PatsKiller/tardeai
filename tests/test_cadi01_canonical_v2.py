"""CADI-01 contracts, compatibility, failure isolation and durable history."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from copy import deepcopy
import json
import multiprocessing
import sqlite3

import pytest

from scripts.lib.cross_asset.canonical_decision import (
    ACTION_CLASSES,
    SCHEMA,
    adapt_decision,
    build_decision,
    process_decision_batch,
    validate_decision,
)
from scripts.lib.cross_asset.decision_store import DecisionStore
from scripts.lib.cross_asset.symbol_decision_object import new_symbol_decision
from scripts.lib.cross_asset_decision import build_decision_object, build_event


def make_decision(symbol="ABC", action="BUY", ts="2026-09-29T12:00:00Z"):
    return build_decision(
        symbol=symbol,
        action=action,
        source="fixture",
        as_of=ts,
        available_at=ts,
        source_versions={"signals": "signal-v1"},
    )


def _append_worker(args):
    path, symbol = args
    return DecisionStore(path).append(make_decision(symbol=symbol))["state"]


@pytest.mark.parametrize("action", ACTION_CLASSES)
def test_all_actions_have_one_canonical_contract(action):
    obj = make_decision(action=action)
    assert obj["schema"] == SCHEMA
    assert obj["signal_state"]["action"] == action
    assert obj["financial_action"] is False
    assert obj["expression_comparison"]["decision"] == "NO_PROVEN_WINNER"
    assert obj["expression_comparison"]["winner"] is None
    assert validate_decision(obj) == []


@pytest.mark.parametrize(
    "raw,expected",
    [("Strong Buy", "STRONG_BUY"), ("add-on-pullback", "ADD_ON_PULLBACK"), (" Entry Near ", "ENTRY_NEAR")],
)
def test_documented_action_normalizations(raw, expected):
    assert make_decision(action=raw)["signal_state"]["action"] == expected


def test_both_v1_formats_are_lossless_and_do_not_promote_heuristic_winners():
    grouped = new_symbol_decision("ABC", subject_guid="subject-1", as_of="2026-09-29T12:00:00Z")
    # A retained grouped v1 record, not a regenerated current snapshot.
    grouped["schema"] = "SymbolDecisionObject@v1"
    grouped["signal_state"] = {"kind": "reentry", "lane": "watch", "signal_id": "s1"}
    grouped["audit_history"] = [{"entry": n} for n in range(100)]
    grouped["custom_field"] = {"keep": True}
    event = build_event(symbol="ABC", signal="BUY", source="watch", observed_at="2026-09-29T12:00:00Z")
    flat = build_decision_object(event=event, identity={"symbol": "ABC", "security_guid": "sec-1"})
    flat["expression_comparison"]["winner"] = "long_call"
    for original in (grouped, flat):
        before = deepcopy(original)
        adapted = adapt_decision(original)
        assert original == before
        assert adapted["schema"] == SCHEMA
        assert adapted["legacy"]["payload"] == original
        assert adapted["expression_comparison"]["winner"] is None
        assert adapted["available_at"] is None
        assert validate_decision(adapted) == []
    assert len(adapt_decision(grouped)["audit_history"]) == 100
    assert adapt_decision(flat)["identity"]["security_guid"] == "sec-1"


def test_stable_identity_changes_when_source_version_changes():
    first = make_decision()
    assert first == make_decision()
    other = build_decision(
        symbol="ABC",
        action="BUY",
        source="fixture",
        as_of=first["as_of"],
        available_at=first["available_at"],
        source_versions={"signals": "signal-v2"},
    )
    assert first["evaluation_id"] != other["evaluation_id"]


def test_missing_positions_and_availability_are_unknown():
    obj = build_decision(symbol="ABC", action="HOLD", source="fixture", as_of="2026-09-29T12:00:00Z")
    assert obj["position_state"]["held_shares"] is None
    assert obj["position_state"]["coverage_100"] is None
    assert obj["available_at"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(financial_action=True),
        lambda x: x.update(authority="LIVE"),
        lambda x: x.update(as_of="yesterday"),
        lambda x: x["signal_state"].update(action="BUY_MORE"),
        lambda x: x["expression_comparison"].update(winner="long_call"),
        lambda x: x["research_state"].update(confidence=float("nan")),
    ],
)
def test_invalid_objects_fail_closed(mutate):
    obj = make_decision()
    mutate(obj)
    assert validate_decision(obj)


def test_unknown_action_receipt_is_durable_and_batch_continues(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    rows = [
        {"symbol": "ABC", "action": "BUY", "source": "watch"},
        {"symbol": "BAD", "action": "buy something else", "source": "legacy-queue"},
        {"symbol": "XYZ", "action": "HOLD", "source": "cio"},
    ]
    receipt = process_decision_batch(rows, store=store, as_of="2026-09-29T12:00:00Z")
    assert receipt["evaluated"] == 2
    assert receipt["failed"] == 1
    assert receipt["ok"] is False
    error = receipt["errors"][0]
    assert error["symbol"] == "BAD"
    assert error["raw_action"] == "buy something else"
    assert error["source"] == "legacy-queue"
    assert error["error_code"] == "UNKNOWN_ACTION"
    reopened = DecisionStore(store.path)
    assert len(reopened.history()) == 3
    assert reopened.latest("XYZ")["signal_state"]["action"] == "HOLD"
    assert reopened.latest("BAD") is None
    assert process_decision_batch(rows, store=reopened, as_of="2026-09-29T12:00:00Z")["duplicates"] == 3


def test_store_is_idempotent_transactional_and_restart_safe(tmp_path):
    path = tmp_path / "decisions.sqlite"
    obj = make_decision()
    store = DecisionStore(path)
    assert store.append(obj)["state"] == "APPENDED"
    assert store.append(obj)["state"] == "DUPLICATE_IGNORED"
    assert DecisionStore(path).latest("ABC") == obj
    assert len(store.history()) == 1
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE cross_asset_evaluation_history SET payload = '{}' ")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM cross_asset_evaluation_history")


def test_failed_projection_write_rolls_back_history(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    store._connect().close()
    with sqlite3.connect(store.path) as db:
        db.execute(
            "CREATE TRIGGER fail_projection BEFORE INSERT ON cross_asset_decision_projection "
            "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
        store.append(make_decision())
    assert store.history() == []


def test_corrupt_history_rebuild_does_not_discard_last_good_projection(tmp_path):
    store = DecisionStore(tmp_path / "corrupt.sqlite")
    obj = make_decision()
    store.append(obj)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "INSERT INTO cross_asset_evaluation_history "
            "(evaluation_id,schema_name,symbol,as_of,payload) VALUES (?,?,?,?,?)",
            ("eval_corrupt_fixture", SCHEMA, "BAD", obj["as_of"], "{}"),
        )
    before = store.history()
    with pytest.raises(ValueError, match="INVALID_HISTORY"):
        store.rebuild_projections()
    assert store.history() == before
    assert store.latest("ABC") == obj


def test_storage_failure_is_not_misreported_as_a_durable_input_error(tmp_path, monkeypatch):
    store = DecisionStore(tmp_path / "failed.sqlite")

    def refuse_write(obj):
        raise OSError("fixture disk failure")

    monkeypatch.setattr(store, "append", refuse_write)
    with pytest.raises(OSError, match="fixture disk failure"):
        process_decision_batch([{"symbol": "ABC", "action": "BUY", "source": "test"}], store=store)
    assert not store.path.exists()


def test_concurrent_duplicates_append_only_once(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    obj = make_decision()
    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: store.append(obj)["state"], range(24)))
    assert states.count("APPENDED") == 1
    assert states.count("DUPLICATE_IGNORED") == 23


def test_separate_processes_preserve_distinct_and_duplicate_writes(tmp_path):
    path = tmp_path / "processes.sqlite"
    symbols = ["ABC"] * 8 + [f"XYZ{number}" for number in range(8)]
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
        states = list(pool.map(_append_worker, [(path, symbol) for symbol in symbols]))
    assert states.count("APPENDED") == 9
    assert states.count("DUPLICATE_IGNORED") == 7
    assert len(DecisionStore(path).history()) == 9


def test_duplicate_id_with_different_content_is_a_conflict(tmp_path):
    store = DecisionStore(tmp_path / "conflict.sqlite")
    first = make_decision()
    store.append(first)
    changed = deepcopy(first)
    changed["research_state"] = {"research_id": "different"}
    with pytest.raises(ValueError, match="CONTENT_CONFLICT"):
        store.append(changed)
    assert store.history() == [first]


def test_replacement_write_is_refused(tmp_path):
    store = DecisionStore(tmp_path / "replace.sqlite")
    obj = make_decision()
    store.append(obj)
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "INSERT OR REPLACE INTO cross_asset_evaluation_history "
                "(evaluation_id,schema_name,symbol,as_of,payload) VALUES (?,?,?,?,?)",
                (obj["evaluation_id"], SCHEMA, "ABC", obj["as_of"], "{}"),
            )


@pytest.mark.parametrize(
    "bad",
    [
        [],
        3,
        {"identity": []},
        {"symbol": "BAD", "action": float("nan")},
        {"symbol": "BAD", "action": "BUY", "source": "x", "groups": {"identity": []}},
    ],
)
def test_malformed_rows_do_not_abort_valid_rows(tmp_path, bad):
    store = DecisionStore(tmp_path / "bad.sqlite")
    good = {"symbol": "XYZ", "action": "BUY", "source": "test"}
    for rows in ([bad, good], [good, bad]):
        receipt = process_decision_batch(rows, store=store, as_of="2026-09-29T12:00:00Z")
        assert receipt["evaluated"] == 1
        assert receipt["failed"] == 1
    assert store.latest("XYZ") is not None


@pytest.mark.parametrize("kind,action", [("buy", "SELL"), ("none", "BUY"), ("BUY", "none")])
def test_conflicting_action_fields_are_refused(kind, action):
    old = new_symbol_decision("ABC", as_of="2026-09-29T12:00:00Z")
    old["signal_state"] = {"kind": kind, "action": action}
    with pytest.raises(ValueError, match="ACTION_CONFLICT"):
        adapt_decision(old)


def test_error_receipt_preserves_event_and_source_version_references():
    receipt = process_decision_batch(
        [
            {
                "symbol": "BAD",
                "action": "UNKNOWN",
                "source": "watch",
                "event_id": "event-123",
                "source_versions": {"watch": "v17"},
            }
        ],
        as_of="2026-09-29T12:00:00Z",
    )
    assert receipt["errors"][0]["source_event_id"] == "event-123"
    assert receipt["errors"][0]["source_versions"] == {"watch": "v17"}
    assert receipt["evaluated"] == 0
    assert receipt["failed"] == 1
    assert receipt["ok"] is False


def test_ambiguous_ticker_identity_is_not_silently_collapsed(tmp_path):
    store = DecisionStore(tmp_path / "identity.sqlite")
    for security in ("security-one", "security-two"):
        obj = build_decision(
            symbol="ABC",
            action="BUY",
            source="test",
            as_of="2026-09-29T12:00:00Z",
            groups={"identity": {"security_guid": security, "identity_status": "CONFIRMED"}},
        )
        store.append(obj)
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        store.latest("ABC")
    assert store.latest("ABC", security_guid="security-one")["identity"]["security_guid"] == "security-one"


def test_timezone_offsets_are_compared_as_instants(tmp_path):
    store = DecisionStore(tmp_path / "times.sqlite")
    later = make_decision(action="HOLD", ts="2026-09-29T10:00:00-04:00")
    earlier = make_decision(action="BUY", ts="2026-09-29T13:00:00Z")
    store.append(later)
    store.append(earlier)
    assert store.latest("ABC") == later


def test_rebuild_and_out_of_order_append_preserve_latest(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    later = make_decision(action="HOLD", ts="2026-09-30T12:00:00Z")
    earlier = make_decision()
    store.append(later)
    store.append(earlier)
    original_history = store.history()
    assert store.latest("ABC") == later
    assert store.rebuild_projections()["decisions"] == 2
    assert store.latest("ABC") == later
    assert store.history() == original_history


def test_legacy_import_keeps_source_bytes_and_continues_after_bad_row(tmp_path):
    path = tmp_path / "legacy.jsonl"
    old = new_symbol_decision("ABC", as_of="2026-09-29T12:00:00Z")
    old["schema"] = "SymbolDecisionObject@v1"
    old["signal_state"] = {"kind": "buy", "lane": "legacy"}
    original = (
        json.dumps(old) + "\n{broken\n" + json.dumps({**old, "identity": {**old["identity"], "symbol": "XYZ"}}) + "\n"
    )
    path.write_text(original)
    store = DecisionStore(tmp_path / "decisions.sqlite")
    result = store.import_legacy(path)
    assert result["evaluated"] == 2
    assert result["failed"] == 1
    assert path.read_text() == original
    assert store.latest("XYZ") is not None


def test_dry_run_does_not_create_a_store(tmp_path):
    store = DecisionStore(tmp_path / "does-not-exist.sqlite")
    result = process_decision_batch(
        [{"symbol": "ABC", "action": "BUY", "source": "test"}], store=store, as_of="2026-09-29T12:00:00Z", dry_run=True
    )
    assert result["evaluated"] == 1
    assert not store.path.exists()


def test_validator_is_total_for_malformed_nested_groups():
    for group in ("identity", "signal_state", "expression_comparison", "audit_history"):
        obj = make_decision()
        obj[group] = ["invalid"] if group != "audit_history" else {}
        assert validate_decision(obj)
    obj = make_decision()
    obj["identity"]["identity_status"] = []
    assert validate_decision(obj)


def test_unknown_legacy_assembly_action_survives_to_error_receipt(tmp_path):
    from scripts.lib.cross_asset.assemble import assemble_symbol_decision

    old = assemble_symbol_decision("ABC", signal={"kind": "BUY_MORE", "lane": "legacy-test"}, prefer_shared_spine=False)
    assert old["signal_state"]["kind"] == "buy_more"
    result = process_decision_batch(
        [old, {"symbol": "XYZ", "action": "BUY", "source": "test"}],
        store=DecisionStore(tmp_path / "legacy-error.sqlite"),
    )
    assert result["evaluated"] == 1
    assert result["errors"][0]["raw_action"] == "BUY_MORE"


@pytest.mark.parametrize(
    "bad",
    [
        {"symbol": "BAD", "action": "BUY", "source": "x", "authority": "LIVE"},
        {"symbol": "BAD", "action": "BUY", "source": "x", "financial_action": True},
        {"symbol": "BAD", "action": "BUY", "source": "x", "groups": {"identity": {"symbol": "OTHER"}}},
        {"symbol": "BAD", "action": "BUY", "source": "x", "groups": {"identity": {"security_guid": {"bad": 1}}}},
    ],
)
def test_authority_and_identity_failures_are_rows_not_batch_crashes(tmp_path, bad):
    store = DecisionStore(tmp_path / "authority.sqlite")
    result = process_decision_batch([bad, {"symbol": "XYZ", "action": "BUY", "source": "x"}], store=store)
    assert result["evaluated"] == 1
    assert result["failed"] == 1
    assert store.latest("XYZ") is not None


def test_submillisecond_projection_ordering_preserves_newer_decision(tmp_path):
    store = DecisionStore(tmp_path / "microseconds.sqlite")
    later = make_decision(ts="2026-09-29T12:00:00.000002Z")
    earlier = make_decision(action="HOLD", ts="2026-09-29T12:00:00.000001Z")
    store.append(later)
    store.append(earlier)
    assert store.latest("ABC") == later


def test_legacy_import_error_keeps_raw_symbol_action_and_source(tmp_path):
    old = new_symbol_decision("BAD", as_of="2026-09-29T12:00:00Z")
    old["signal_state"] = {"kind": "UNKNOWN_RAW", "lane": "queue-one"}
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps(old) + "\n")
    store = DecisionStore(tmp_path / "import.sqlite")
    assert store.import_legacy(path)["failed"] == 1
    error = store.history()[0]
    assert error["symbol"] == "BAD"
    assert error["raw_action"] == "UNKNOWN_RAW"
    assert error["source"] == "queue-one"


@pytest.mark.parametrize("raw_action", ["", 0, False, [], {}, None])
def test_falsy_legacy_actions_do_not_turn_into_missing_signal(tmp_path, raw_action):
    from scripts.lib.cross_asset.assemble import assemble_symbol_decision

    old = assemble_symbol_decision("BAD", signal={"kind": raw_action, "lane": "legacy"}, prefer_shared_spine=False)
    receipt = process_decision_batch(
        [old, {"symbol": "XYZ", "action": "HOLD", "source": "cio"}], store=DecisionStore(tmp_path / "falsy.sqlite")
    )
    assert receipt["evaluated"] == 1
    assert receipt["failed"] == 1
    assert receipt["errors"][0]["raw_action"] == raw_action


def test_store_and_schema_registry_declarations_match_single_writer():
    from pathlib import Path
    from scripts.cio_completeness_measurement import schema_definitions

    root = Path(__file__).resolve().parents[1]
    domains = json.loads((root / "config/data_source_authority.json").read_text())["domains"]
    for name in ("cross_asset_evaluation_history", "cross_asset_decision_projection"):
        row = next(item for item in domains if item["domain"] == name)
        assert row["writer"] == "scripts/lib/cross_asset/decision_store.py"
        assert row["store"]["table"] == name
    classifications = json.loads((root / "config/cio_surface_classification.json").read_text())["entries"]
    classified = {row["name"] for row in classifications}
    defined, _ = schema_definitions(root)
    for schema in (
        SCHEMA,
        "CrossAssetDecisionError@v1",
        "CrossAssetDecisionBatchReceipt@v1",
        "CrossAssetDecisionProjection@v1",
    ):
        assert "schema:" + schema in classified
        assert schema in defined


def test_operator_audit_reads_decisions_errors_and_views_without_copying(tmp_path):
    from scripts.lib.cio_operator_artifacts import list_operator_artifacts
    from scripts.lib.cross_asset.decision_store import STORE_RELATIVE

    store = DecisionStore(tmp_path / STORE_RELATIVE)
    process_decision_batch(
        [
            {"symbol": "ABC", "action": "BUY", "source": "fixture"},
            {"symbol": "BAD", "action": "UNKNOWN_RAW", "source": "queue"},
        ],
        store=store,
        as_of="2026-09-29T12:00:00Z",
    )
    before = store.path.read_bytes()
    out = list_operator_artifacts(root=tmp_path)
    assert out["cadi_records"]["status"] == "AVAILABLE"
    assert {row["original_schema"] for row in out["artifacts"]} == {
        SCHEMA,
        "CrossAssetDecisionError@v1",
        "CrossAssetDecisionProjection@v1",
    }
    error = next(row for row in out["artifacts"] if row["original_schema"] == "CrossAssetDecisionError@v1")
    assert error["payload"]["raw_action"] == "UNKNOWN_RAW"
    assert error["persisted_at"] is None  # Never label signal time as append time.
    assert store.path.read_bytes() == before
    assert not (tmp_path / "data/cio/cio_operator_artifacts.jsonl").exists()


@pytest.mark.parametrize(
    "approval,writer,enabled,status",
    [
        ({}, "scripts/lib/cross_asset/decision_store.py", "1", "SOURCE_APPROVAL_REQUIRED"),
        (
            {
                "approved_by": "fixture operator",
                "approved_on": "fixture date",
                "reference": "fixture",
                "scope": "fixture",
            },
            "scripts/lib/cross_asset/decision_store.py",
            "0",
            "NOT_ACTIVATED",
        ),
        (
            {
                "approved_by": "fixture operator",
                "approved_on": "fixture date",
                "reference": "fixture",
                "scope": "fixture",
            },
            "other-writer",
            "1",
            "SOURCE_APPROVAL_REQUIRED",
        ),
    ],
)
def test_production_audit_read_requires_source_approval_and_activation(monkeypatch, approval, writer, enabled, status):
    from pathlib import Path
    from scripts.lib.cio_operator_artifacts import _cadi_rows
    from scripts.lib import canonical_store_registry

    original_read = Path.read_text

    def fixture_registry(path, *args, **kwargs):
        if path.name == "data_source_authority.json":
            return json.dumps(
                {
                    "domains": [
                        {"domain": name, "writer": writer, "approval": approval}
                        for name in ("cross_asset_evaluation_history", "cross_asset_decision_projection")
                    ]
                }
            )
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fixture_registry)
    monkeypatch.setenv("TRADEAI_CADI_RECORDS_READ_ENABLED", enabled)
    monkeypatch.setattr(
        canonical_store_registry, "production_state_root", lambda: pytest.fail("production read refused")
    )
    assert _cadi_rows(None, 50) == ([], status)


def test_audit_read_is_bounded_and_bad_store_is_visible(tmp_path):
    from scripts.lib.cio_operator_artifacts import _cadi_rows
    from scripts.lib.cross_asset.decision_store import STORE_RELATIVE

    store = DecisionStore(tmp_path / STORE_RELATIVE)
    for symbol in ("ABC", "DEF", "XYZ"):
        store.append(make_decision(symbol=symbol))
    assert [row["identity"]["symbol"] for row in store.history(limit=2)] == ["DEF", "XYZ"]
    # Fresh corrupt fixture, never modify or truncate a user's existing store.
    bad_root = tmp_path / "bad"
    bad_path = bad_root / STORE_RELATIVE
    bad_path.parent.mkdir(parents=True)
    bad_path.write_text("invalid sqlite fixture")
    assert _cadi_rows(bad_root, 50) == ([], "STORE_READ_FAILED")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE cross_asset_decision_projection SET payload='broken' WHERE symbol='XYZ'")
    assert _cadi_rows(tmp_path, 50) == ([], "STORE_READ_FAILED")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"schema": SCHEMA, "authority": "READ_ONLY_ADVISORY"},
        {"schema": "CrossAssetDecisionError@v1", "error_code": "BAD"},
    ],
)
def test_json_shaped_history_corruption_does_not_break_legacy_artifacts(tmp_path, monkeypatch, bad):
    from scripts.lib import cio_operator_artifacts as artifacts
    from scripts.lib.cross_asset.decision_store import STORE_RELATIVE

    store = DecisionStore(tmp_path / STORE_RELATIVE)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("in-memory history mock; never opened as SQLite")
    monkeypatch.setattr(DecisionStore, "history", lambda self, **kwargs: [bad])
    monkeypatch.setenv("CIO_OPERATOR_ARTIFACTS_JSONL", str(tmp_path / "legacy.jsonl"))
    artifacts._INDEX.clear()
    artifacts.record_advisory_message({"text": "legacy retained"}, producer="fixture", artifact_id="legacy")
    result = artifacts.list_operator_artifacts(root=tmp_path)
    assert result["cadi_records"]["status"] == "STORE_READ_FAILED"
    assert result["artifacts"][0]["payload"] == {"text": "legacy retained"}


@pytest.mark.parametrize("bad", [[], {"domains": [{"domain": []}]}, {"domains": {}}, None])
def test_malformed_authority_shape_is_reported_before_production_read(monkeypatch, bad):
    from pathlib import Path
    from scripts.lib.cio_operator_artifacts import _cadi_rows

    original_read = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, *args, **kwargs: (
            json.dumps(bad) if path.name == "data_source_authority.json" else original_read(path, *args, **kwargs)
        ),
    )
    assert _cadi_rows(None, 50) == ([], "AUTHORITY_UNAVAILABLE")


@pytest.mark.parametrize("symbol", [float("nan"), object()])
def test_malformed_raw_symbol_cannot_make_the_batch_receipt_nonjson(symbol):
    from scripts.lib.cross_asset.canonical_decision import canonical_json

    result = process_decision_batch(
        [
            {"symbol": symbol, "action": "BUY", "source": "fixture"},
            {"symbol": "XYZ", "action": "HOLD", "source": "fixture"},
        ]
    )
    assert result["failed"] == 1
    assert result["evaluated"] == 1
    assert json.loads(canonical_json(result))["failed"] == 1

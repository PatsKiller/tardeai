"""WP-30 fixture-only account metadata proposals; no broker/producer imports or calls."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/moomoo-retirement-reconcile-20261023"
spec = importlib.util.spec_from_file_location("wp30_packet", PACKET / "packet.py")
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
NOW = datetime(2026, 10, 24, 2, tzinfo=timezone.utc)


@pytest.fixture
def paths(tmp_path):
    holdings = tmp_path / "state/holdings.json"
    holdings.parent.mkdir()
    holdings.write_text(
        json.dumps(
            {
                "account_summaries": {
                    p.KEY: {
                        "retired": True,
                        "retired_at": "2026-09-01",
                        "state": "LIVE",
                        "account_number": "PRIVATE_FIXTURE_IDENTIFIER",
                        "total_value": 123.4,
                    }
                },
                "holdings": [{"account": p.KEY, "symbol": "TEST", "shares": 0.1, "basis": 3}],
                "updated_at": "old-clock",
            }
        )
    )
    served = tmp_path / "served.json"
    served.symlink_to(holdings)
    registry = tmp_path / "accounts.yaml"
    registry.write_text(
        yaml.safe_dump({"accounts": {p.KEY: {"active": True, "account_id": "PRIVATE_FIXTURE_IDENTIFIER"}}})
    )
    tripwire = tmp_path / "retired/RETIRED_moomoo_taxable_live.json"
    tripwire.parent.mkdir()
    tripwire.write_text(
        json.dumps(
            {
                "schema": "RetiredAccountRow@v1",
                "account": p.KEY,
                "tripwire": "written instruction",
                "rows": [{"secret_fixture": "NEVER_PRINT"}],
            }
        )
    )
    return p.Paths(holdings, served, registry, tripwire, tmp_path / "shared.lock", tmp_path / "cache")


def ready(paths):
    observation, doc = p.snapshot(paths)
    candidate = p.proposed_document(doc, observation, decision=p.DECISION, now=NOW)
    # Fixture simulates a separately-authorized writer; production packet has no such writer.
    paths.holdings.write_text(json.dumps(candidate))
    return p.preview(paths, NOW)[0]


def test_preview_preserves_every_production_byte_and_hides_account_values(paths):
    before = {path: path.read_bytes() for path in (paths.holdings, paths.registry, paths.tripwire)}
    receipt, observation = p.preview(paths, NOW)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert observation["retired"] is True and observation["stored_state"] == "LIVE"
    assert observation["archive_ready"] is False
    text = receipt.read_text()
    assert "PRIVATE_FIXTURE_IDENTIFIER" not in text and "NEVER_PRINT" not in text and "total_value" not in text
    assert receipt.stat().st_mode & 0o077 == 0


def test_registry_missing_flag_is_not_invented_as_false(paths):
    paths.registry.write_text(yaml.safe_dump({"accounts": {p.KEY: {}}}))
    observation, _ = p.snapshot(paths)
    assert observation["registry_active"] == "NOT_MEASURED"


@pytest.mark.parametrize("decision", [None, "KEEP_RETIRED", ""])
def test_preparation_requires_explicit_operator_choice(paths, decision):
    with pytest.raises(ValueError, match="operator decision"):
        p.prepare(paths, NOW, decision=decision)
    assert not paths.cache.exists()


def test_candidate_changes_only_target_retirement_metadata_and_retains_history(paths):
    observation, doc = p.snapshot(paths)
    before = copy.deepcopy(doc)
    proposed = p.proposed_document(doc, observation, decision=p.DECISION, now=NOW)
    assert doc == before
    after = copy.deepcopy(proposed)
    resolution = after["account_summaries"][p.KEY].pop("retirement_resolution")
    after["account_summaries"][p.KEY]["retired"] = True
    assert after == before
    assert resolution["decision"] == p.DECISION
    assert proposed["account_summaries"][p.KEY]["state"] == "LIVE"
    assert proposed["updated_at"] == "old-clock"
    assert proposed["account_summaries"][p.KEY]["retired_at"] == "2026-09-01"


def test_private_candidate_preparation_never_writes_authoritative_holdings(paths):
    before = paths.holdings.read_bytes()
    proposal = p.prepare(paths, NOW, decision=p.DECISION)
    assert paths.holdings.read_bytes() == before
    assert proposal.stat().st_mode & 0o077 == 0
    assert (proposal.parent / "candidate.PRIVATE.json").stat().st_mode & 0o077 == 0
    assert json.loads(proposal.read_text())["production_changed"] is False


@pytest.mark.parametrize(
    "problem", ["registry_inactive", "missing_summary", "tripwire_account", "tripwire_schema", "divergence"]
)
def test_unexpected_source_rejects_proposal(paths, problem):
    if problem == "registry_inactive":
        paths.registry.write_text(yaml.safe_dump({"accounts": {p.KEY: {"active": False}}}))
    elif problem == "missing_summary":
        paths.holdings.write_text('{"account_summaries": {}}')
    elif problem.startswith("tripwire"):
        tripwire = json.loads(paths.tripwire.read_text())
        tripwire["account" if problem.endswith("account") else "schema"] = "WRONG"
        paths.tripwire.write_text(json.dumps(tripwire))
    else:
        divergent = paths.cache.parent / "divergent.json"
        divergent.write_text("{}")
        paths = replace(paths, served_holdings=divergent)
    with pytest.raises(ValueError):
        p.prepare(paths, NOW, decision=p.DECISION)


def test_existing_resolution_is_not_overwritten(paths):
    doc = json.loads(paths.holdings.read_text())
    doc["account_summaries"][p.KEY]["retirement_resolution"] = {"operator_note": "existing"}
    paths.holdings.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="not overwritten"):
        p.prepare(paths, NOW, decision=p.DECISION)


def test_archive_cannot_run_before_authorized_metadata_readback(paths):
    receipt, _ = p.preview(paths, NOW)
    with pytest.raises(ValueError, match="unresolved"):
        p.archive(paths, NOW, receipt, decision=p.DECISION)
    assert paths.tripwire.exists()


def test_archive_is_exact_byte_preserving_and_never_writes_holdings(paths):
    receipt = ready(paths)
    original = paths.tripwire.read_bytes()
    holdings_before = paths.holdings.read_bytes()
    result = p.archive(paths, NOW, receipt, decision=p.DECISION)
    proof = json.loads(result.read_text())
    archived = Path(proof["archived"])
    assert archived.read_bytes() == original and not paths.tripwire.exists()
    assert paths.holdings.read_bytes() == holdings_before
    assert proof["production_holdings_changed"] is False
    assert archived.stat().st_mode & 0o077 == 0
    assert (result.parent / "resolution.STARTED.json").exists()


@pytest.mark.parametrize(
    "problem",
    ["expired", "future", "holdings_drift", "tripwire_drift", "registry_drift", "public_receipt", "wrong_decision"],
)
def test_archive_refusals_preserve_original(paths, problem):
    receipt = ready(paths)
    now = NOW
    decision = p.DECISION
    if problem == "expired":
        now += timedelta(minutes=16)
    elif problem == "future":
        now -= timedelta(seconds=1)
    elif problem == "holdings_drift":
        paths.holdings.write_text(paths.holdings.read_text() + " ")
    elif problem == "tripwire_drift":
        paths.tripwire.write_text(paths.tripwire.read_text() + " ")
    elif problem == "registry_drift":
        paths.registry.write_text(paths.registry.read_text() + "\n")
    elif problem == "public_receipt":
        receipt.chmod(0o644)
    else:
        decision = "KEEP_RETIRED"
    with pytest.raises(ValueError):
        p.archive(paths, now, receipt, decision=decision)
    assert paths.tripwire.exists()


def test_packet_has_no_holdings_writer_or_producer_import():
    source = (PACKET / "packet.py").read_text()
    assert "import holdings_guard" not in source and "from holdings_guard" not in source
    assert "import moomoo" not in source and "subprocess" not in source
    assert "paths.holdings.write" not in source
    assert "NOT IMPLEMENTED: §7A" in source


def test_unknown_stored_state_stays_unmeasured(paths):
    doc = json.loads(paths.holdings.read_text())
    doc["account_summaries"][p.KEY]["state"] = {"private": "NEVER_PRINT"}
    paths.holdings.write_text(json.dumps(doc))
    observation, _ = p.snapshot(paths)
    assert observation["stored_state"] == "NOT_MEASURED"
    assert "NEVER_PRINT" not in json.dumps(observation)


def test_busy_shared_lock_refuses_archive_without_moving_original(paths):
    receipt = ready(paths)
    with p.shared_lock(paths.lock):
        with pytest.raises(BlockingIOError):
            p.archive(paths, NOW, receipt, decision=p.DECISION)
    assert paths.tripwire.exists()


def load_audit():
    spec = importlib.util.spec_from_file_location("wp30_audit", PACKET / "audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_inventory_roles_and_privacy_use_fixture_source_only(tmp_path, monkeypatch):
    audit = load_audit()
    source = tmp_path / "scripts/example.py"
    source.parent.mkdir()
    source.write_text(
        'doc = {"account_summaries": {"PRIVATE_IDENTIFIER": 1}}\nsummary = doc.get("account_summaries")\ndoc["account_summaries"] = summary\n'
    )
    monkeypatch.setattr(audit.subprocess, "check_output", lambda *a, **k: "scripts/example.py\n")
    rows, failures = audit.inventory(tmp_path)
    assert not failures
    assert {row[3] for row in rows} == {
        "summary_container_construction",
        "summary_container_read",
        "summary_container_assignment",
    }
    assert "PRIVATE_IDENTIFIER" not in str(rows)


def test_guard_call_inventory_detects_alias_without_running_import(tmp_path, monkeypatch):
    audit = load_audit()
    source = tmp_path / "scripts/example.py"
    source.parent.mkdir()
    source.write_text(
        "from holdings_guard import protected_holdings_write as guarded\ndef save(value):\n    return guarded(value)\n"
    )
    monkeypatch.setattr(audit.subprocess, "check_output", lambda *a, **k: "scripts/example.py\n")
    rows = audit.guard_sites(tmp_path)
    assert rows == [("scripts/example.py", 3, "guarded", "guard_call_site_not_runtime_proof")]


def test_inventory_parse_failure_is_reported_not_silently_dropped(tmp_path, monkeypatch):
    audit = load_audit()
    source = tmp_path / "scripts/broken.py"
    source.parent.mkdir()
    source.write_text("account_summaries = (\n")
    monkeypatch.setattr(audit.subprocess, "check_output", lambda *a, **k: "scripts/broken.py\n")
    rows, failures = audit.inventory(tmp_path)
    assert rows == [] and failures == ["scripts/broken.py"]


def test_new_test_file_has_canonical_gate():
    gate = json.loads((ROOT / "config/ci_gates/moomoo_retirement_packet_20261023.json").read_text())
    assert "tests/test_moomoo_retirement_packet_20261023.py" in gate["files"]

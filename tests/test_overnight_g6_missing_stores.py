"""WAVE G6 — missing stores: create empty only with live registry-path consumer.

Invariants:
  * registry lists cio.decisions, notifications.outbox, learning.weekly
  * cio.decisions is retired_as_canonical_current; evening packet forbids it
  * NotificationOutbox defaults to operator_notification_outbox.jsonl (sibling)
  * no create_empty_durable for any of the three (CONSUMER_ABSENT_OR_RETIRED)
  * this file is on the hardening CI allowlist

READ_ONLY_ADVISORY. MBI=0. Prefer report over inventing unread stores.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import cio_missing_stores_g6 as g6  # noqa: E402
from scripts.lib.canonical_store_registry import STORES  # noqa: E402

HARDENING = ROOT / "scripts" / "run_cio_hardening_ci.py"
AUDIT = ROOT / "docs" / "audits" / "overnight" / "G6_MISSING_STORES_2026-08-31.md"
OUTBOX_SRC = ROOT / "scripts" / "lib" / "cio_notification_outbox.py"


def test_g6_registry_lists_all_three_targets():
    for sid in g6.G6_STORE_IDS:
        assert sid in STORES, f"registry missing {sid}"
        assert STORES[sid].get("path"), f"{sid} has no path"


def test_g6_cio_decisions_retired_and_evening_forbidden():
    spec = STORES["cio.decisions"]
    assert spec.get("retired_as_canonical_current") is True
    assert spec["path"] == "data/cio/cio_decisions.jsonl"
    assert g6.evening_packet_forbids_cio_decisions(ROOT) is True
    cfg = json.loads(
        (ROOT / "config" / "aegis_evening_surveillance.json").read_text(encoding="utf-8")
    )
    assert "cio_decisions" in (cfg.get("forbidden_inputs") or [])


def test_g6_notification_outbox_live_path_is_sibling_not_registry():
    """Live consumer writes/reads operator_*, not cio_notification_outbox.jsonl."""
    assert STORES["notifications.outbox"]["path"] == "data/cio/cio_notification_outbox.jsonl"
    src = OUTBOX_SRC.read_text(encoding="utf-8")
    assert "operator_notification_outbox.jsonl" in src
    # Pin the NotificationOutbox default ctor — not an earlier helper __init__.
    marker = "class NotificationOutbox:"
    assert marker in src
    region = src[src.find(marker): src.find(marker) + 2500]
    assert "def __init__(self, event_store_path" in region
    assert "operator_notification_outbox.jsonl" in region
    # Default block must not point at the registry filename.
    init_end = region.find("self.event_store_path = Path")
    default_block = region[: init_end if init_end > 0 else 1200]
    assert "operator_notification_outbox.jsonl" in default_block
    assert "cio_notification_outbox.jsonl" not in default_block


def test_g6_learning_weekly_registry_path_has_no_jsonl_writer_in_reviewer():
    spec = STORES["learning.weekly"]
    assert spec["path"] == "data/cio/weekly_learning.jsonl"
    reviewer = (ROOT / "scripts" / "multi_tier_trade_reviewer.py").read_text(encoding="utf-8")
    assert "weekly_learning.jsonl" not in reviewer
    assert "paper_trade_multi_reviews" in reviewer
    api = (ROOT / "scripts" / "api_v3_cio.py").read_text(encoding="utf-8")
    assert "cio_weekly_learning_reviews.jsonl" in api
    assert "weekly_learning.jsonl" not in api


def test_g6_classify_all_report_none_created():
    report = g6.classify_all(root=ROOT)
    assert report["schema"] == g6.SCHEMA
    assert report["created"] == []
    assert set(report["reported"]) == set(g6.G6_STORE_IDS)
    for row in report["decisions"]:
        assert row["create_empty_durable"] is False
        assert row["disposition"] == g6.DISPOSITION_RETIRED
        assert row["registry_expects"] is True
        assert row["live_consumer_of_registry_path"] is False
        assert row["memory_behavior_influence"] == 0
        assert row["financial_action"] is False


def test_g6_audit_doc_and_allowlist_present():
    assert AUDIT.is_file(), "G6 audit note must be committed"
    text = AUDIT.read_text(encoding="utf-8")
    assert "CONSUMER_ABSENT_OR_RETIRED" in text
    assert "cio.decisions" in text
    assert "notifications.outbox" in text
    assert "learning.weekly" in text
    assert "CREATE" in text or "created" in text.lower()
    hardening = HARDENING.read_text(encoding="utf-8")
    assert "overnight_g6_missing_stores" in hardening
    assert "tests/test_overnight_g6_missing_stores.py" in hardening


def test_g6_host_roots_missing_registry_paths_when_present():
    """When persistent-state / CURRENT exist, registry paths must be absent
    (this wave creates none). Soft-skip if roots are not on the machine."""
    host = g6.verify_host_roots()
    any_present = False
    for label, info in host.items():
        if not info.get("present"):
            continue
        any_present = True
        files = info["files"]
        for sid in g6.G6_STORE_IDS:
            assert files[sid]["exists"] is False, (
                f"{label} unexpectedly has {sid} — G6 must not revive unread stores"
            )
    if not any_present:
        pytest.skip("persistent-state / CURRENT not mounted on this host")

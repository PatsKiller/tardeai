#!/usr/bin/env python3
"""Lane I — inbound → AgentConsumptionReceipt proofs."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.agent_contracts import (  # noqa: E402
    reset_agent_contracts_memory,
)
from scripts.lib.comms.client import reset_memory_store  # noqa: E402
from scripts.lib.comms.delivery import reset_memory_deliveries  # noqa: E402
from scripts.lib.comms.inbound import reset_inbound_state  # noqa: E402
from scripts.lib.comms.mode import _cache as _mode_cache  # noqa: E402
from scripts.lib.inbound_consumption import (  # noqa: E402
    counts_as_behavioral_consumption,
    consume_inbound_event,
    process_inbound_update,
)
from scripts.lib.inbound_event_normalizer import (  # noqa: E402
    normalize_inbound_update,
    reset_normalizer_memory,
)


def _update(
    *,
    update_id: int = 4001,
    chat_id: int = 42,
    message_id: int = 501,
    user_id: int = 7,
    text: str = "hold NVDA",
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Op"},
            "text": text,
        },
    }


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.inbound._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.agent_contracts._db_conn", lambda: None)
    monkeypatch.setenv("COMMS_INBOUND_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("COMMS_INBOUND_SENDER_ALLOWLIST", "7")
    _mode_cache["mode"] = None
    reset_inbound_state()
    reset_memory_store()
    reset_memory_deliveries()
    reset_agent_contracts_memory()
    reset_normalizer_memory()
    yield
    reset_inbound_state()
    reset_memory_store()
    reset_agent_contracts_memory()
    reset_normalizer_memory()


def test_end_to_end_receipt_links_exact_inbound_event():
    r = process_inbound_update(_update(), provenance_producer="test")
    assert r.ok, r.reason
    assert r.event_id
    assert r.receipt_id
    assert r.receipt["source_kind"] == "comm_event"
    assert r.receipt["source_id"] == r.event_id
    assert r.receipt["event_id"] == r.event_id
    assert r.effect_kind == "none"
    assert r.counts_as_behavioral_consumption is False
    assert r.receipt["provenance"]["producer"] == "test"


def test_effect_kind_none_never_counts_as_behavioral():
    assert counts_as_behavioral_consumption("none", None) is False
    assert counts_as_behavioral_consumption("none", "x") is False
    assert counts_as_behavioral_consumption("changed_view", None) is False
    assert counts_as_behavioral_consumption("changed_view", "wake_1") is True


def test_non_none_requires_effect_ref():
    norm = normalize_inbound_update(_update(update_id=4010))
    assert norm.ok
    bad = consume_inbound_event(norm.event, effect_kind="changed_priority", effect_ref=None)
    assert not bad.ok
    assert "effect_ref_required" in bad.reason


def test_behavioral_effect_with_ref_counts():
    norm = normalize_inbound_update(_update(update_id=4011, message_id=777))
    assert norm.ok
    good = consume_inbound_event(
        norm.event,
        effect_kind="changed_question",
        effect_ref="wake_abc",
        provenance_producer="test",
    )
    assert good.ok, good.reason
    assert good.counts_as_behavioral_consumption is True


def test_duplicate_inbound_does_not_double_consume():
    u = _update(update_id=4020, message_id=888)
    r1 = process_inbound_update(u)
    assert r1.ok
    r2 = process_inbound_update(u)
    assert not r2.ok
    assert "duplicate" in r2.reason


def test_unauthorized_never_emits_receipt():
    r = process_inbound_update(_update(user_id=12345))
    assert not r.ok
    assert "allowlist" in r.reason or "authorization" in r.reason
    assert r.receipt_id is None


def test_malformed_never_emits_receipt():
    r = process_inbound_update({"message": {"text": "x"}})  # no update_id
    assert not r.ok
    assert r.receipt_id is None


def test_no_financial_or_broker_side_effect_surface():
    """Intake path returns advisory-only result; no broker fields."""
    r = process_inbound_update(_update(update_id=4030, text="buy 100 AAPL"))
    assert r.ok
    d = r.to_dict()
    assert "order_id" not in d
    assert "broker_action" not in d
    assert r.effect_kind == "none"
    assert r.counts_as_behavioral_consumption is False


def test_feed_telegram_update_entry_creates_receipt():
    from scripts.lib.inbound_consumption import feed_telegram_update

    r = feed_telegram_update(_update(update_id=5001, message_id=601), provenance_producer="runtime_poller")
    assert r.ok, r.reason
    assert r.receipt_id
    assert r.effect_kind == "none"
    assert r.counts_as_behavioral_consumption is False
    assert r.receipt["provenance"]["producer"] == "runtime_poller"


def test_feed_refuses_broker_effect_ref():
    from scripts.lib.inbound_consumption import feed_telegram_update

    r = feed_telegram_update(
        _update(update_id=5002, message_id=602),
        effect_kind="changed_commitment",
        effect_ref="order:123",
    )
    assert not r.ok
    assert "financial_or_broker" in r.reason


def test_restart_offset_suppresses_replay(tmp_path, monkeypatch):
    """Checkpoint survives in-process memory reset — restart cannot replay."""
    from scripts.lib.inbound_consumption import feed_telegram_update, process_inbound_update
    from scripts.lib.inbound_event_normalizer import reset_normalizer_memory

    u = _update(update_id=5100, message_id=710)
    r1 = feed_telegram_update(u)
    assert r1.ok, r1.reason
    # Simulate process restart: clear in-process dedupe, keep checkpoint files.
    reset_normalizer_memory()
    r2 = feed_telegram_update(u)
    assert not r2.ok
    assert "duplicate" in r2.reason


# Accepted Lane I runtime (poller still INTEGRATION-owned / unwired in that commit).
_UNWIRED_RUNTIME_SHA = "2e66bc0a9b683f0ee72e84e3e198fd593c2cc458"
# Integration candidate after SFR-I-RUNTIME-001 applied the poller feed.
_INTEGRATED_CANDIDATE_SHA = "4911664395d34b6114176625887bbd271d05ac0f"
_POLLER_REL = "scripts/run_telegram_callback_poller.py"
_CONSUMPTION_REL = "scripts/lib/inbound_consumption.py"
_NORMALIZER_REL = "scripts/lib/inbound_event_normalizer.py"


def _git_show(commit: str, rel: str) -> str:
    import subprocess

    return subprocess.check_output(
        ["git", "show", f"{commit}:{rel}"],
        cwd=str(ROOT),
        text=True,
    )


def _materialize_production_slice(
    dest: Path,
    *,
    poller_text: str,
    consumption_text: str | None = None,
    normalizer_text: str | None = None,
) -> Path:
    """Build a minimal non-test production tree for reachability inspection."""
    (dest / "scripts" / "lib").mkdir(parents=True)
    (dest / _POLLER_REL).write_text(poller_text, encoding="utf-8")
    (dest / _CONSUMPTION_REL).write_text(
        consumption_text if consumption_text is not None else (ROOT / _CONSUMPTION_REL).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (dest / _NORMALIZER_REL).write_text(
        normalizer_text if normalizer_text is not None else (ROOT / _NORMALIZER_REL).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Reachability must never be satisfiable by a tests/ caller.
    assert not (dest / "tests").exists()
    return dest


def test_reachability_gate_requires_poller_wiring(tmp_path):
    """Gate detects an unwired poller; integrated production tree must be wired."""
    from scripts.lib.inbound_consumption import (
        InboundReachabilityError,
        assert_inbound_runtime_reachability,
        find_normalize_runtime_callers,
        poller_wires_feed,
    )

    callers = find_normalize_runtime_callers()
    assert any("inbound_consumption" in c for c in callers), callers
    assert all(not c.startswith("tests/") for c in callers), callers

    # Negative: intentionally unwired poller (pre-SFR production text).
    unwired_poller = _git_show(_UNWIRED_RUNTIME_SHA, _POLLER_REL)
    assert "feed_telegram_update" not in unwired_poller
    unwired = _materialize_production_slice(tmp_path / "unwired", poller_text=unwired_poller)
    assert poller_wires_feed(repo_root=unwired) is False
    try:
        assert_inbound_runtime_reachability(repo_root=unwired)
        raise AssertionError("expected InboundReachabilityError on unwired fixture")
    except InboundReachabilityError as exc:
        assert "SFR-I-RUNTIME-001" in str(exc) or "feed_telegram_update" in str(exc)

    # Positive: real integrated production tree after SFR-I-RUNTIME-001.
    wired = _materialize_production_slice(
        tmp_path / "integrated",
        poller_text=_git_show(_INTEGRATED_CANDIDATE_SHA, _POLLER_REL),
        consumption_text=_git_show(_INTEGRATED_CANDIDATE_SHA, _CONSUMPTION_REL),
        normalizer_text=_git_show(_INTEGRATED_CANDIDATE_SHA, _NORMALIZER_REL),
    )
    assert poller_wires_feed(repo_root=wired) is True
    report = assert_inbound_runtime_reachability(repo_root=wired)
    assert report["ok"] is True
    assert report["poller_wires_feed_telegram_update"] is True
    assert any("inbound_consumption" in c for c in report["normalize_runtime_callers"])

    # When this checkout already carries the SFR (post-integration), live must pass.
    if poller_wires_feed():
        live = assert_inbound_runtime_reachability()
        assert live["ok"] is True
        assert live["poller_wires_feed_telegram_update"] is True


def test_reachability_gate_fails_when_poller_feed_call_removed(tmp_path):
    """Negative control: removing the poller→feed call must turn the gate red."""
    from scripts.lib.inbound_consumption import (
        InboundReachabilityError,
        assert_inbound_runtime_reachability,
        poller_wires_feed,
    )

    wired_poller = _git_show(_INTEGRATED_CANDIDATE_SHA, _POLLER_REL)
    assert "feed_telegram_update" in wired_poller
    stripped = wired_poller.replace(
        "from scripts.lib import inbound_consumption\n",
        "",
    ).replace(
        "published = inbound_consumption.feed_telegram_update(update)",
        'event = inbound["build_inbound_event"](update)\n'
        '                published = inbound["publish_communication"](event)',
    )
    assert "feed_telegram_update" not in stripped
    assert "from scripts.lib import inbound_consumption" not in stripped

    broken = _materialize_production_slice(tmp_path / "stripped", poller_text=stripped)
    assert poller_wires_feed(repo_root=broken) is False
    try:
        assert_inbound_runtime_reachability(repo_root=broken)
        raise AssertionError("expected InboundReachabilityError after removing poller feed call")
    except InboundReachabilityError as exc:
        assert "SFR-I-RUNTIME-001" in str(exc) or "feed_telegram_update" in str(exc)


def test_reachability_ignores_callers_inside_tests(tmp_path):
    """A normalize caller living under tests/ must never satisfy reachability."""
    from scripts.lib.inbound_consumption import (
        InboundReachabilityError,
        assert_inbound_runtime_reachability,
        find_normalize_runtime_callers,
        poller_wires_feed,
    )

    root = tmp_path / "tests_only"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / _NORMALIZER_REL).write_text(
        "def normalize_inbound_update(update):\n    return update\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_fake_caller.py").write_text(
        "from scripts.lib.inbound_event_normalizer import normalize_inbound_update\nnormalize_inbound_update({})\n",
        encoding="utf-8",
    )
    (root / _POLLER_REL).write_text(
        "from scripts.lib import inbound_consumption\ninbound_consumption.feed_telegram_update({})\n",
        encoding="utf-8",
    )
    # Poller is wired, but the only normalize reference is inside tests/.
    assert poller_wires_feed(repo_root=root) is True
    assert find_normalize_runtime_callers(repo_root=root) == []
    try:
        assert_inbound_runtime_reachability(repo_root=root)
        raise AssertionError("expected InboundReachabilityError when only tests/ call normalize")
    except InboundReachabilityError as exc:
        assert "no non-test runtime caller" in str(exc)


def test_reachability_gate_passes_when_poller_text_wired(tmp_path):
    """Synthetic repo proves the gate turns green once the poller references the feed."""
    from scripts.lib.inbound_consumption import assert_inbound_runtime_reachability

    root = tmp_path / "repo"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "scripts" / "lib" / "inbound_consumption.py").write_text(
        "def feed_telegram_update(update):\n    from scripts.lib.inbound_event_normalizer import normalize_inbound_update\n    return normalize_inbound_update(update)\n"
    )
    (root / "scripts" / "lib" / "inbound_event_normalizer.py").write_text(
        "def normalize_inbound_update(update):\n    return update\n"
    )
    (root / "scripts" / "run_telegram_callback_poller.py").write_text(
        "from scripts.lib.inbound_consumption import feed_telegram_update\n"
        "def poll_once():\n    feed_telegram_update({})\n"
    )
    report = assert_inbound_runtime_reachability(repo_root=root)
    assert report["ok"] is True
    assert report["poller_wires_feed_telegram_update"] is True

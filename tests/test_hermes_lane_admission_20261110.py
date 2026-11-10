"""LQ-20261107-1808 r2 must-fix 1 — the ungated Anthropic lane is closed by the process registry.

The BEFORE: ``--lane`` defaulted to ``claude`` and ``_call_direct`` POSTed ``api.anthropic.com`` with no
registry read, no allowlist, no consumption row and no ``deepseek_only`` check. The reviewer measured the
door with a fake urlopen (2026-11-10, ``REVIEW-LQ1825-25152d18b.md``):

    call_external("claude","claude-sonnet-4-6","hello",return_provenance=True) -> ('x', None)
    url: https://api.anthropic.com/v1/messages

These pins make the registry the single source of truth: the bare command defaults to the route this
process declares (``deepseek``), and any lane whose name/provider/default model is not on the row's
``allowed_lanes`` is refused (``LaneNotAdmitted``, EXIT_LANE_GATED semantics) before a credential is read
or a socket opened. The refusal holds for ``call_external`` (every caller) and for ``main`` (the CLI and
the API endpoint that shells it).

Synthetic fixtures only — no network, no key, no database. The two shipped-config pins read the JSON files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.hermes_external_researcher as her

ROOT = Path(__file__).resolve().parent.parent
PROCESS_ID = "hermes_external_research"


def _shipped_row() -> dict:
    """The row production ships for this process (the gate's own input, read as data)."""
    doc = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    for row in doc.get("processes") or []:
        if row.get("id") == PROCESS_ID:
            return row
    raise AssertionError(f"no registry row for {PROCESS_ID}")


# ── the declaration: deepseek_only, and the allowlist names no Anthropic lane ─────────────────────────────


def test_the_shipped_row_declares_a_deepseek_only_process():
    row = _shipped_row()
    assert row["lane_policy"] == "deepseek_only"
    assert row["fallback_allowed"] is False


def test_the_shipped_allowlist_names_no_anthropic_lane_or_model():
    allowed = {str(x).lower() for x in _shipped_row()["allowed_lanes"]}
    assert "claude" not in allowed and "anthropic" not in allowed
    assert not any(name.startswith(("claude", "anthropic")) for name in allowed)


def test_the_shipped_row_admits_the_declared_route_and_the_oauth_lanes_it_documents():
    row = _shipped_row()
    for lane in ("deepseek", "grok", "chatgpt"):
        assert her.lane_admission(lane, row)[0] is True, lane
    # `deepseek` is admitted through its model id: the row names `deepseek-flash`, not the CLI's `deepseek`.
    assert "deepseek-flash" in {str(x).lower() for x in row["allowed_lanes"]}


def test_claude_is_refused_by_the_shipped_row():
    admitted, why = her.lane_admission("claude", _shipped_row())
    assert admitted is False
    assert "anthropic" in why and "allowed_lanes" in why


# ── the gate itself: fail closed ──────────────────────────────────────────────────────────────────────────


def test_an_unreadable_or_empty_allowlist_admits_nothing():
    """Unknown is not permission: a row we cannot read is a refusal, not a default."""
    for cfg in ({}, {"allowed_lanes": []}, {"allowed_lanes": ["", "  "]}, None):
        assert her.lane_admission("deepseek", cfg) == (False, "allowed_lanes_empty_or_unreadable")


def test_a_registry_read_failure_is_a_refusal(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("registry gone")

    monkeypatch.setattr(her, "process_lane_config", boom)
    assert her.admission_for("claude") == (False, "registry_unreadable:RuntimeError")


def test_admission_for_reads_the_row_through_the_governed_reader(monkeypatch):
    seen = {}

    def fake_config(process_id=PROCESS_ID):
        seen["process_id"] = process_id
        return _shipped_row()

    monkeypatch.setattr(her, "process_lane_config", fake_config)
    assert her.admission_for("claude")[0] is False
    assert her.admission_for("deepseek")[0] is True
    assert seen["process_id"] == PROCESS_ID


# ── the door: no provider client is reached for a refused lane ────────────────────────────────────────────


def test_call_external_refuses_claude_before_any_provider_client(monkeypatch):
    monkeypatch.setattr(her, "process_lane_config", lambda *a, **k: _shipped_row())
    monkeypatch.setattr(her, "via_bridge", lambda: False)
    monkeypatch.setattr(her, "_call_direct", lambda *a, **k: pytest.fail("a refused lane reached the provider"))
    monkeypatch.setattr(her, "_get_key", lambda *a, **k: pytest.fail("a refused lane read a credential"))

    with pytest.raises(her.LaneNotAdmitted) as ei:
        her.call_external("claude", "claude-sonnet-4-6", "hello", return_provenance=True)
    assert ei.value.exit_code == her.EXIT_LANE_GATED == 75
    assert ei.value.lane == "claude" and ei.value.process_id == PROCESS_ID
    assert "LANE_NOT_ADMITTED" in str(ei.value)


def test_call_external_admits_the_declared_route_and_still_routes_it(monkeypatch):
    """The gate admits `deepseek` and the call reaches the governed lane (not refused, not rerouted)."""
    monkeypatch.setattr(her, "process_lane_config", lambda *a, **k: _shipped_row())
    monkeypatch.setattr(her, "via_bridge", lambda: False)
    seen = {}

    def fake_governed(model, prompt, max_tokens=0, **_k):
        seen["model"] = model
        return "answer"

    monkeypatch.setattr(her, "call_governed_deepseek", fake_governed)
    assert her.call_external("deepseek", "deepseek-flash", "hello") == "answer"
    assert seen["model"] == "deepseek-flash"


# ── the CLI: the bare command is the declared route, and a refusal is EXIT_LANE_GATED ─────────────────────


def test_the_bare_command_defaults_to_the_declared_route():
    assert her.build_parser().parse_args(["--question", "q"]).lane == "deepseek"


def _main_fixture(monkeypatch):
    """Everything main() touches before the admission gate, made synthetic and observable."""
    events: list[tuple[str, str | None]] = []
    monkeypatch.setattr(her, "process_lane_config", lambda *a, **k: _shipped_row())
    monkeypatch.setattr(her, "accounting_identity", lambda **kw: ("run-test", "call-test"))

    def fake_event(event, **kw):
        events.append((event, kw.get("reason")))

    monkeypatch.setattr(her, "append_call_event", fake_event)
    return events


def test_main_refuses_a_lane_the_registry_does_not_admit(monkeypatch):
    events = _main_fixture(monkeypatch)
    monkeypatch.setattr(her, "_load_env", lambda: pytest.fail("a refused lane read .env"))
    monkeypatch.setattr(her, "_call_direct", lambda *a, **k: pytest.fail("a refused lane reached the provider"))

    rc = her.main(["--lane", "claude", "--question", "q", "--apply"])

    assert rc == her.EXIT_LANE_GATED == 75
    assert ("SKIP_GATED", "LANE_NOT_ADMITTED:lane=claude provider=anthropic not in allowed_lanes") in events
    assert all(event != "COMPLETED" for event, _ in events)


def test_main_refuses_before_the_budget_guard_and_the_env_load(monkeypatch):
    """The refusal is the first thing after accounting: no .env, no budget call, no DB, no provider."""
    events = _main_fixture(monkeypatch)
    monkeypatch.setattr(her, "_load_env", lambda: pytest.fail("refusal happened after .env"))
    monkeypatch.setattr(her, "_call_direct", lambda *a, **k: pytest.fail("refusal happened after a provider"))

    import hermes_research_budget_guard as guard

    monkeypatch.setattr(guard, "decide", lambda **kw: pytest.fail("refusal happened after the budget guard"))

    assert her.main(["--lane", "claude", "--question", "q"]) == 75
    assert [event for event, _ in events] == ["SCHEDULED", "SKIP_GATED"]

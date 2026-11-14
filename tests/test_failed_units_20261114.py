"""OPS-C1 — one failed-unit adapter shared by every surface (operator OP-020, 2026-11-14).

Hermetic: every check feeds a fake ``run`` and a fixed clock; nothing touches systemd, the host or a database.

The bug this pins: the /ops Platform showed the three failed ``tradeai*`` units, while the /ops queue showed
``hermes-deep-research-local`` in place of ``tradeai-deploy-on-main`` — two probes over two scopes, neither stating
its scope or its observation time. After this module every surface reads ONE snapshot: same units, same ``as_of``,
and a narrower surface names the units outside its scope instead of silently differing.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import failed_units as fu  # noqa: E402

NOW = datetime(2031, 3, 7, 15, 0, 0, tzinfo=timezone.utc)

# The live disagreement, as systemd would print it (descriptions invented).
LIVE_OUTPUT = """\
tradeai-backup-enforcer.service     loaded failed failed Backup enforcer
tradeai-deploy-on-main.service     loaded failed failed Deploy on main
tradeai-prospectus-deliver.service loaded failed failed Prospectus deliver
hermes-deep-research-local.service loaded failed failed Hermes deep research (local)
"""


def runner(stdout: str = LIVE_OUTPUT, rc: int = 0, stderr: str = "", calls: list | None = None):
    def run(argv, **kw):
        if calls is not None:
            calls.append((argv, kw))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

    return run


def snap(**kw):
    return fu.probe_failed_units(runner(**{k: v for k, v in kw.items() if k != "now"}), now=lambda: NOW)


# ---- 1. one call, unscoped, bounded --------------------------------------------------------------

def test_probe_asks_systemd_once_with_no_name_pattern():
    calls: list = []
    s = fu.probe_failed_units(runner(calls=calls), now=lambda: NOW)
    assert len(calls) == 1, calls
    argv = calls[0][0]
    assert argv[:3] == ["systemctl", "--user", "list-units"]
    assert "--state=failed" in argv
    # No pattern: every reader shares the whole failed set; scoping is select()'s job.
    assert not any(a.startswith("tradeai") or a.endswith("*") for a in argv), argv
    assert calls[0][1].get("timeout") == fu.DEFAULT_TIMEOUT_S
    assert s["answered"] is True


def test_probe_never_uses_a_shell():
    calls: list = []
    fu.probe_failed_units(runner(calls=calls), now=lambda: NOW)
    assert calls[0][1].get("shell") is None


# ---- 2. parsing -----------------------------------------------------------------------------------

def test_parses_units_and_keeps_the_description():
    units = fu.parse_failed_units(LIVE_OUTPUT)
    assert [u["unit"] for u in units] == [
        "hermes-deep-research-local.service",
        "tradeai-backup-enforcer.service",
        "tradeai-deploy-on-main.service",
        "tradeai-prospectus-deliver.service",
    ]  # sorted, so two readers cannot differ by order
    assert units[0]["active"] == "failed" and units[0]["sub"] == "failed"
    assert units[0]["description"] == "Hermes deep research (local)"


def test_tolerates_the_interactive_bullet_and_blank_lines():
    text = "\n  ● tradeai-a.service loaded failed failed A\n\n"
    units = fu.parse_failed_units(text)
    assert [u["unit"] for u in units] == ["tradeai-a.service"]


def test_ignores_lines_that_are_not_units():
    assert fu.parse_failed_units("garbage\n\nLEGEND: x\n") == []


# ---- 3. unanswered is UNKNOWN, never zero ---------------------------------------------------------

def test_timeout_is_unknown_with_a_reason():
    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv[0], kw.get("timeout"))

    s = fu.probe_failed_units(slow, now=lambda: NOW)
    assert s["answered"] is False and s["units"] == []
    assert "timed out" in s["reason"]
    assert s["as_of"] == NOW.isoformat()


def test_nonzero_exit_is_unknown_and_carries_stderr():
    s = fu.probe_failed_units(runner(rc=3, stderr="Failed to connect to bus"), now=lambda: NOW)
    assert s["answered"] is False
    assert "exit 3" in s["reason"] and "bus" in s["reason"]


def test_unrunnable_systemctl_is_unknown():
    def missing(argv, **kw):
        raise FileNotFoundError("systemctl")

    s = fu.probe_failed_units(missing, now=lambda: NOW)
    assert s["answered"] is False and "not runnable" in s["reason"]


def test_an_answered_empty_probe_is_really_zero():
    s = fu.probe_failed_units(runner(stdout=""), now=lambda: NOW)
    assert s["answered"] is True and s["units"] == [] and s["reason"] is None


# ---- 4. the two surfaces now agree, structurally --------------------------------------------------

def test_platform_and_queue_share_units_and_clock():
    s = snap()
    platform = fu.select(s, prefixes=("tradeai-",), scope_label="failed tradeai* units")
    queue = fu.select(s)  # the /ops queue names every failed user unit

    assert platform["scope"] == "failed tradeai* units"
    assert [u["unit"] for u in platform["units"]] == [
        "tradeai-backup-enforcer.service",
        "tradeai-deploy-on-main.service",
        "tradeai-prospectus-deliver.service",
    ]
    # The queue is a superset with the SAME observation time — the operator's mismatch cannot recur.
    assert platform["as_of"] == queue["as_of"] == NOW.isoformat()
    assert platform["source"] == queue["source"] == fu.SOURCE
    assert {u["unit"] for u in platform["units"]} | {u["unit"] for u in platform["outside"]} == {
        u["unit"] for u in queue["units"]
    }
    assert [u["unit"] for u in platform["outside"]] == ["hermes-deep-research-local.service"]


def test_a_narrower_surface_names_what_it_does_not_show():
    sel = fu.select(snap(), prefixes=("tradeai-",), scope_label="failed tradeai* units")
    text = fu.summary(sel)
    assert "3 failed units in scope" in text
    assert "hermes-deep-research-local.service" in text
    assert "outside this scope" in text
    assert "as of 2031-03-07T15:00:00+00:00" in text


def test_a_complete_scope_has_no_outside_clause():
    s = fu.probe_failed_units(runner(stdout="tradeai-a.service loaded failed failed A\n"), now=lambda: NOW)
    text = fu.summary(fu.select(s, prefixes=("tradeai-",), scope_label="failed tradeai* units"))
    assert "1 failed unit in scope" in text and "outside this scope" not in text


def test_an_unanswered_summary_never_says_zero():
    s = fu.probe_failed_units(lambda argv, **kw: (_ for _ in ()).throw(OSError("no bus")), now=lambda: NOW)
    text = fu.summary(fu.select(s))
    assert "Failed units unknown:" in text
    assert "not runnable" in text  # type name, not the raw exception text
    assert "0 failed" not in text
    assert "Nothing here is known to be OK" in text


def test_selection_without_a_snapshot_is_unknown_not_empty():
    sel = fu.select(None)
    assert sel["answered"] is False and sel["units"] == []
    assert "0 failed" not in fu.summary(sel)


# ---- 5. the adapter is the only systemctl in the readers (no second query) ------------------------

def test_module_is_importable_without_side_effects():
    # No probe at import: an import must never run systemctl (server startup, tests, tooling).
    assert fu.SCHEMA == "FailedUnits@v1"
    assert fu.ARGV[0] == "systemctl" and "--no-pager" in fu.ARGV

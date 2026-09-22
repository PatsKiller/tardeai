"""The last three conditions that re-armed every 1800s — one gate, three root causes.

MEASURED 2026-09-22 11:07 EDT, on the live queue
------------------------------------------------
Three findings, and nothing else, produced every remaining "exhausted after N
attempts — will re-arm in 1800s" line plus its Telegram page:

    health:execution_health:approved_paper_test_stuck    attempts=19
    health:data_quality:schwab_journal_ingest_stale      attempts=19
    hermes_health_inspector:staleness_escalation         attempts=68

They survived the shed at claude_escalation_handler.py because each carried
something that looked like an action, exhausted at MAX_RETRIES, logged
"Skipping ...: retries exhausted", never ran its retry_cmd again, and re-armed
forever.  Each had a DIFFERENT root cause, and raising the attempt cap would
have addressed none of them:

1. approved_paper_test_stuck — REAL, and the retry works.  The VERIFY was the
   defect: it counted every APPROVED_FOR_PAPER_TEST row while the detector
   (health_agent.py:2731) counts only rows that are old / mid-validation /
   needing revalidation.  Live: 16 rows in the lane, exactly 2 stuck.  The
   queue item recorded `_ineffective_verify: paper_stuck_still_9` — a verify
   that cannot pass while the lane is healthy.

2. schwab_journal_ingest_stale — FALSE.  health_agent runs from the release
   tree, whose logs/ resolves to persistent-state; the ingest cron runs from
   the DEV tree.  Served copy: 54 KB, mtime 2026-09-09 15:18.  DEV copy:
   3.5 MB, mtime 2026-09-22 11:03, twelve minutes before the finding fired
   claiming "282.2h old".  Its remediation also wrote neither copy, so no retry
   could ever clear it (measured retry_output: "timeout after 300s").

3. hermes_health_inspector:staleness_escalation — STALE, and unfixable by
   retry.  fixable=False, no retry_cmd, producer not scheduled anywhere (no
   cron line among 992, no systemd unit), 6 rows frozen at 2026-08-07 carrying
   a root_cause string the code no longer emits.  It escaped the shed only
   because its component began with neither "health:" nor an entry of
   _OPERATOR_COMPONENTS.

EVERY PROPERTY BELOW HAS A NEGATIVE CONTROL
-------------------------------------------
On 2026-09-21/22 this repo produced twelve checks that reported success while
exercising nothing.  So each fix here is paired with the REVERTED behaviour run
through the SAME fixture, asserting it goes red — identical output is never
evidence of discrimination.  `test_the_detector_can_fail` runs all three
reverted implementations at once.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "scripts" / "claude_escalation_handler.py"
HEALTH = ROOT / "scripts" / "health_agent.py"
POLICY = ROOT / "config" / "health_agent_policy.json"

PAPER_COMPONENT = "health:execution_health:approved_paper_test_stuck"
SCHWAB_COMPONENT = "health:data_quality:schwab_journal_ingest_stale"
HERMES_COMPONENT = "hermes_health_inspector:staleness_escalation"

#: The lane as measured after a successful sweep: rows present, none of them
#: stuck.  The old verify sees 14 and refuses forever; the new one clears.
HEALTHY_LANE = {"total": 14, "stuck": 0}
#: The lane as measured at 11:20 EDT: 16 rows, 2 genuinely stuck (MU #10864
#: VALIDATING/NEEDS_REVALIDATION, WDAY #10752 NOT_SUBMITTED).
STUCK_LANE = {"total": 16, "stuck": 2}

#: The namespaces the shed used to be restricted to (the reverted rule).
OLD_OPERATOR_COMPONENTS = (
    "unprotected_positions", "siem_p0p1", "schwab_token_revoked",
    "finviz_cookie_expired", "audit_ledger", "kill_switch",
    "release_manifest", "proposal_link_rate", "catalyst_type_quality",
    "agent::test_", "agent_staleness",
)


def _load(path: Path, name: str):
    """Load by explicit path, not by name.

    A sibling test importing a same-named module from another tree must not
    decide which copy is asserted against — that ordering dependency cost a
    green-on-the-unpatched-file result earlier in this series.
    """
    if not path.is_file():
        pytest.skip(f"{path.name} not present in this tree")
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod.__file__ == str(path), f"loaded the wrong copy: {mod.__file__}"
    return mod


@pytest.fixture(scope="module")
def esc():
    return _load(HANDLER, "_escalation_handler_under_test")


@pytest.fixture(scope="module")
def ha():
    return _load(HEALTH, "_health_agent_under_test")


def _fake_db_verify(lane: dict, captured: list):
    """A DB that answers the DETECTOR's question and the OLD question differently.

    This is the whole point of the fixture: the two predicates disagree on the
    same database.  A stub that returned one number for both could not tell the
    fix from the bug.
    """
    def _verify(sql, params=None):
        captured.append((sql, params))
        asks_for_stuck_rows = "NEEDS_REVALIDATION" in sql
        return True, (lane["stuck"] if asks_for_stuck_rows else lane["total"]), "ok"
    return _verify


def _old_paper_verify(lane: dict) -> tuple[bool, str]:
    """The reverted verify: count every row in the lane, clear only at zero."""
    n = lane["total"]
    if n == 0:
        return True, "paper_stuck_cleared"
    return False, f"paper_stuck_still_{n}"


def _old_is_review_only(item: dict) -> bool:
    """The reverted shed: namespace-gated, so anything else survived forever."""
    comp = str(item.get("component") or "")
    if not item.get("fixable") and not item.get("retry_cmd") and not item.get("needs_code_fix"):
        if any(k in comp for k in OLD_OPERATOR_COMPONENTS) or comp.startswith("health:"):
            return True
    return False


def _split_log_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The served/DEV split exactly as measured: frozen release copy, live DEV copy."""
    served_logs = tmp_path / "release" / "logs"
    dev_root = tmp_path / "dev"
    dev_logs = dev_root / "logs"
    served_logs.mkdir(parents=True)
    dev_logs.mkdir(parents=True)

    served = served_logs / "schwab_ingest.log"
    dev = dev_logs / "schwab_ingest.log"
    served.write_text("frozen copy from 2026-09-09\n")
    dev.write_text("the copy the cron actually appends to\n")

    now = time.time()
    os.utime(served, (now - 282.2 * 3600, now - 282.2 * 3600))   # 11.8 days
    os.utime(dev, (now - 0.2 * 3600, now - 0.2 * 3600))          # 12 minutes
    return served_logs, dev_root, served


# ── 1. approved_paper_test_stuck: the verify must ask the detector's question ──

def test_verify_asks_the_detectors_question(esc, monkeypatch) -> None:
    """A healthy lane with zero stuck rows verifies CLEAR, rows present or not."""
    captured: list = []
    monkeypatch.setattr(esc, "_db_verify", _fake_db_verify(HEALTHY_LANE, captured))

    cleared, note = esc._verify_remediation({"component": PAPER_COMPONENT})

    assert cleared is True, note
    assert note == "paper_stuck_cleared_0", note
    sql = captured[0][0]
    for token in ("VALIDATING", "NOT_SUBMITTED", "NEEDS_REVALIDATION", "updated_at"):
        assert token in sql, f"verify no longer asks about {token}: {sql}"


def test_the_old_verify_goes_red_on_the_same_lane() -> None:
    """NEGATIVE CONTROL. The reverted predicate can never clear a working lane.

    14 healthy EXECUTED/ELIGIBLE rows are not a defect; the old verify called
    them one, which is why the item burned 20 attempts and re-armed forever.
    """
    cleared, note = _old_paper_verify(HEALTHY_LANE)
    assert cleared is False
    assert note == "paper_stuck_still_14"


def test_a_genuinely_stuck_lane_is_not_cleared(esc, monkeypatch) -> None:
    """The fix must not become an always-true verify: 2 stuck rows stay unfixed."""
    captured: list = []
    monkeypatch.setattr(esc, "_db_verify", _fake_db_verify(STUCK_LANE, captured))

    cleared, note = esc._verify_remediation({"component": PAPER_COMPONENT})

    assert cleared is False
    assert note == "paper_stuck_still_2", note


def test_verify_fails_closed_on_a_db_error(esc, monkeypatch) -> None:
    """A broken query must not read as 'fixed' — exit-0 thrash is the old defect."""
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: (False, None, "verify_error:boom"))
    cleared, note = esc._verify_remediation({"component": PAPER_COMPONENT})
    assert cleared is False
    assert note == "verify_error:boom"


# ── 2. schwab_journal_ingest_stale: read the copy that actually ticks ─────────

def test_the_detector_reads_the_freshest_copy(ha, tmp_path, monkeypatch) -> None:
    """Freshest-of-copies: the DEV tree ticking is evidence the producer ran."""
    served_logs, dev_root, _ = _split_log_fixture(tmp_path)
    monkeypatch.setattr(ha, "LOG_DIR", served_logs)
    monkeypatch.setattr(ha, "DEV_ROOT", dev_root)

    age_h = ha._freshest_log_age_h("schwab_ingest.log")

    assert age_h is not None
    assert age_h < 0.5, f"still reading the frozen served copy: {age_h}h"


def test_the_old_read_goes_red_on_the_same_fixture(tmp_path) -> None:
    """NEGATIVE CONTROL. LOG_DIR-only reports 282h for an ingest 12 minutes old."""
    _, _, served = _split_log_fixture(tmp_path)
    old_age_h = (time.time() - served.stat().st_mtime) / 3600
    assert old_age_h > 0.5, "fixture does not reproduce the split"
    assert old_age_h > 200, old_age_h


def test_a_log_that_exists_nowhere_is_still_missing(ha, tmp_path, monkeypatch) -> None:
    """The fix must not mask a producer that genuinely never ran."""
    monkeypatch.setattr(ha, "LOG_DIR", tmp_path / "release" / "logs")
    monkeypatch.setattr(ha, "DEV_ROOT", tmp_path / "dev")
    assert ha._freshest_log_path("schwab_ingest.log") is None
    assert ha._freshest_log_age_h("schwab_ingest.log") is None


def test_the_collector_no_longer_reads_only_the_served_copy() -> None:
    """REGRESSION GUARD at the source, so the call site cannot drift back."""
    src = HEALTH.read_text(encoding="utf-8")
    assert '_freshest_log_age_h("schwab_ingest.log")' in src
    assert 'LOG_DIR / "schwab_ingest.log"' not in src, (
        "a call site went back to the served copy only"
    )


# ── 3. the reclassification: a retry that cannot clear its finding is not a retry ──

def test_schwab_ingest_is_no_longer_auto_retried() -> None:
    """Its remediation wrote neither copy of the log the detector reads.

    Removed from remediation_map on the same precedent as schwab_token_revoked:
    the producer already has its own cron, so this is monitor-only.
    """
    rmap = json.loads(POLICY.read_text(encoding="utf-8"))["remediation_map"]
    assert "schwab_journal_ingest_stale" not in rmap
    assert "_schwab_journal_ingest_stale_note" in rmap, "removed without saying why"


def test_the_remediation_map_was_not_gutted() -> None:
    """NEGATIVE CONTROL for the test above: emptying the map would also pass it."""
    rmap = json.loads(POLICY.read_text(encoding="utf-8"))["remediation_map"]
    assert "approved_paper_test_stuck" in rmap
    assert len([k for k in rmap if not k.startswith("_")]) > 50, len(rmap)


# ── 4. the shed: no action means no retries, in ANY namespace ─────────────────

def _hermes_item() -> dict:
    return {
        "component": HERMES_COMPONENT,
        "detail": "P1: DRY_RUN: Deterministic aggregation only",
        "fixable": False,
        "source": "hermes_health_inspector",
        "_attempts": 69,
        "_exhausted": True,
    }


def test_the_hermes_item_is_shed(esc) -> None:
    """No retry_cmd, not fixable, not a code fix — it cannot be auto-fixed."""
    assert esc.is_review_only(_hermes_item(), {"approved_paper_test_stuck"}) is True


def test_the_old_shed_kept_it_forever() -> None:
    """NEGATIVE CONTROL. The namespace gate is exactly what let it storm."""
    assert _old_is_review_only(_hermes_item()) is False


def test_a_health_item_with_no_command_is_still_shed(esc) -> None:
    """The behaviour that already worked must keep working."""
    item = {"component": "health:execution_health:systemd_unit_failed", "fixable": False}
    assert esc.is_review_only(item, {"approved_paper_test_stuck"}) is True
    assert _old_is_review_only(item) is True


def test_code_fix_items_are_never_shed(esc) -> None:
    """coder_dispatch owns those; shedding them would silently drop repair work."""
    item = {"component": HERMES_COMPONENT, "fixable": False, "needs_code_fix": True}
    assert esc.is_review_only(item, {"approved_paper_test_stuck"}) is False


def test_a_de_mapped_remediation_is_shed(esc) -> None:
    """The policy, not the queued snapshot, decides what is retryable.

    The live queue entry still carries the schwab retry_cmd it was enqueued with
    weeks ago.  Once the type leaves remediation_map it must stop burning
    retries instead of re-arming on a command the producer no longer issues.
    """
    item = {
        "component": SCHWAB_COMPONENT,
        "fixable": True,
        "source": "health_agent",
        "retry_cmd": "flock -n /tmp/schwab_ingest.lock bash -c '...'",
        "_attempts": 20,
    }
    types = esc.load_remediation_types()
    assert types is not None, "could not read the live policy"
    assert esc.is_review_only(item, types) is True


def test_a_mapped_remediation_is_kept(esc) -> None:
    """NEGATIVE CONTROL for the rule above: a live mapping must NOT be shed."""
    item = {
        "component": PAPER_COMPONENT,
        "fixable": True,
        "source": "health_agent",
        "retry_cmd": ".venv/bin/python scripts/cleanup_stale_proposals.py --pipeline-sweep --apply",
    }
    types = esc.load_remediation_types()
    assert esc.is_review_only(item, types) is False


def test_an_unreadable_policy_sheds_nothing(esc) -> None:
    """FAIL CLOSED. An empty type-set would otherwise drain the whole queue."""
    item = {
        "component": SCHWAB_COMPONENT,
        "fixable": True,
        "source": "health_agent",
        "retry_cmd": "anything",
    }
    assert esc.is_review_only(item, None) is False
    assert esc.is_review_only(item, set()) is False


def test_data_source_stale_is_exempt_from_the_policy_rule(esc) -> None:
    """Its command can come from data_source_remediation, keyed by source."""
    item = {
        "component": "health:data_quality:data_source_stale",
        "fixable": True,
        "source": "health_agent",
        "retry_cmd": ".venv/bin/python scripts/sec_data_ingest.py --all",
    }
    assert esc.is_review_only(item, {"something_else"}) is False


def test_another_producers_retryable_item_is_not_touched(esc) -> None:
    """The policy rule is scoped to the producer that builds cmds from the map."""
    item = {
        "component": HERMES_COMPONENT,
        "fixable": True,
        "source": "hermes_health_inspector",
        "retry_cmd": "echo hi",
    }
    assert esc.is_review_only(item, {"something_else"}) is False


def test_load_remediation_types_reads_the_live_policy(esc) -> None:
    types = esc.load_remediation_types()
    assert types is not None
    assert "approved_paper_test_stuck" in types
    assert "schwab_journal_ingest_stale" not in types
    assert not any(t.startswith("_") for t in types), "comment keys leaked into the type set"


def test_run_actually_uses_the_shed_helper() -> None:
    """A helper the loop does not call is not a fix."""
    src = HANDLER.read_text(encoding="utf-8")
    assert "remediation_types = load_remediation_types()" in src
    assert "if is_review_only(item, remediation_types):" in src


# ── 5. one page per exhaustion, not one per cycle ────────────────────────────

def test_exhaustion_pages_once(esc) -> None:
    """attempts=68 meant 68 identical Telegram pages for one stuck condition."""
    item = {"component": HERMES_COMPONENT}
    assert esc.should_page_exhausted(item) is True
    assert esc.should_page_exhausted(item) is False
    assert esc.should_page_exhausted(item) is False


def test_a_re_arm_makes_the_next_exhaustion_page_again(esc) -> None:
    """Suppression must not silence a genuinely new failure after a re-arm."""
    item = {"component": PAPER_COMPONENT}
    assert esc.should_page_exhausted(item) is True
    item.pop("_exhaust_notified", None)          # what the re-arm branch does
    assert esc.should_page_exhausted(item) is True


def test_the_exhaust_branch_and_the_re_arm_are_wired(esc) -> None:
    src = HANDLER.read_text(encoding="utf-8")
    assert "if not should_page_exhausted(item):" in src
    assert 'item.pop("_exhaust_notified", None)' in src, "re-arm does not clear the flag"


# ── 6. the suite can go red ──────────────────────────────────────────────────

def test_the_detector_can_fail(tmp_path) -> None:
    """POSITIVE CONTROL. All three reverted implementations, one fixture each.

    If this test ever passes while the three above also pass, the assertions
    are not discriminating and the gate is decorative.
    """
    # 1. the old verify never clears a healthy lane
    assert _old_paper_verify(HEALTHY_LANE)[0] is False
    # 2. the old log read calls a 12-minute-old ingest 282 hours stale
    _, _, served = _split_log_fixture(tmp_path)
    assert (time.time() - served.stat().st_mtime) / 3600 > 0.5
    # 3. the old shed keeps a no-action item queued forever
    assert _old_is_review_only(_hermes_item()) is False

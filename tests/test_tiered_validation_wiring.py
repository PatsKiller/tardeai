"""The P6 tiered-validation gate has a production caller, and it cannot spend.

`scripts/run_tiered_validation_gate.py` shipped 2026-09-16 with the rest of the P6
tranche. Three of its siblings were armed on the host that day -- `:35`
`cio_gate_measurement_bridge.py`, `:40` `run_goal_pilot_material_change.py`, `:50`
`run_dormant_lane_consumers.py` -- and this one was not. Measured 2026-09-17: zero callers
in `scripts/`, zero references in `tests/`, zero crontab lines, no row in
`config/lane_registry.json`. Built, correct, tested, and reachable from nothing.

It was not lying about that. It declared

    SCHEDULED_ENTRYPOINT = "PROPOSAL ONLY -- not installed..."

which is a true sentence, and which is exactly why nothing ever reported the problem:
`check_dark_contracts.py` skips any module carrying a `SCHEDULED_ENTRYPOINT` constant
**whatever it says**. A module with no caller at all therefore passed the gate written to
find modules with no caller. The declaration was honest and the gate it satisfied was
empty -- which is a worse failure than a missing declaration, because it reports green.

The fix is a caller, not a better declaration. These pin both halves:

  * the gate is reached from `run_dormant_lane_consumers.py`, which IS installed (crontab
    `50 * * * *`, armed 2026-09-16 under the operator's full-package APPROVE), so no new
    scheduler entry was created -- installing one is operator-only (AGENTS.md §17);
  * the bypass constant is gone, so the dark-contract gate now genuinely guards this
    module: break the lane's import and `check_dark_contracts.py --fail-on-new` reports
    it NEW. That gate matches a *token*, though -- any bare mention of the module name in
    a non-test file under `scripts/` satisfies it, a mention inside a comment included --
    so it can be held green by prose. It briefly was: the comment registering this file in
    `run_cio_hardening_ci.py` named the module, and the gate stayed green with the lane
    broken until that comment stopped naming it. The test below therefore asserts the
    *specific caller*, not the mere mention, and is deliberately the stricter of the two;
  * the lane costs nothing, including when the operator's paid-judge flag is switched on;
  * and the claim the module makes about its own caller is checked against the caller,
    so the declaration cannot rot into the next "PROPOSAL ONLY".

No COVERS: nothing in this path sends an operator alert.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts import run_dormant_lane_consumers as runner
from scripts import run_tiered_validation_gate as gate
from scripts.lib.tiered_validation import TIER2_FLAG, TierPolicy

REPO = Path(__file__).resolve().parent.parent

LANE = "tiered_validation"


def _args(**kw) -> argparse.Namespace:
    base = {"lane": None, "root": None, "state_root": None,
            "resume_run_id": None, "apply": False, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def _production_consumers() -> list[str]:
    """Modules under scripts/ that reference the gate, by the dark-contract gate's rule.

    Same corpus rule as `check_dark_contracts.audit()` -- non-test files under `scripts/`,
    self-reference discarded -- but scanning for one module instead of tokenizing all 418
    definers, which is 0.06s rather than 5.8s. A six-second unit test inside a gate that
    runs on every push is how a gate ends up switched off.

    Returns every file that *mentions* the gate, which is all the production check can see.
    The caller asserts on a specific entry in this list, because a mention is not a call:
    a comment naming the module satisfies `check_dark_contracts.py` exactly as well as an
    import does.
    """
    hits: list[str] = []
    for path in (REPO / "scripts").rglob("*.py"):
        text_path = str(path)
        if "__pycache__" in text_path or path.name.startswith("test_"):
            continue
        if path.name == "run_tiered_validation_gate.py":
            continue                      # self-reference is not a consumer
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "run_tiered_validation_gate" in source or gate.SCHEMA in source:
            hits.append(str(path.relative_to(REPO)))
    return sorted(hits)


# ── the wire itself ──────────────────────────────────────────────────────

def test_the_gate_has_a_production_consumer_outside_its_own_tests() -> None:
    """The measurement that started this: it had none. It must now have one."""
    consumers = _production_consumers()
    assert consumers, (
        "scripts/run_tiered_validation_gate.py has no non-test consumer under scripts/. "
        "It is dark again -- the exact state measured on 2026-09-17."
    )
    assert "scripts/run_dormant_lane_consumers.py" in consumers


def test_the_gate_is_a_registered_lane_on_an_installed_entrypoint() -> None:
    """A caller that is itself unscheduled would move the darkness, not remove it."""
    assert LANE in runner.LANES
    # The runner really is armed; if that ever reverts, this wire is decorative.
    assert "INSTALLED" in runner.SCHEDULED_ENTRYPOINT
    assert "PROPOSAL ONLY" not in runner.SCHEDULED_ENTRYPOINT
    assert "50 * * * *" in runner.SCHEDULED_ENTRYPOINT


def test_cron_runs_every_lane_because_it_passes_no_lane_argument() -> None:
    """`run()` selects `list(LANES)` when `--lane` is absent, which is how cron calls it.

    A lane registered but only reachable via an explicit `--lane` would never run
    unattended -- dark with extra steps.
    """
    assert _args().lane is None
    assert LANE in list(runner.LANES)


def test_the_gate_names_its_caller_and_the_name_is_true() -> None:
    """The anti-rot control: the declaration is checked against the runner, not trusted.

    "PROPOSAL ONLY -- not installed" was true when written and stayed in the file after
    the tranche was armed around it. A declaration nothing verifies decays into a lie at
    the speed of the next commit.
    """
    declared = gate.PRODUCTION_CALLER
    assert "run_dormant_lane_consumers.py" in declared
    assert LANE in declared
    # ...and the thing it names actually exists, right now, in that module.
    assert LANE in runner.LANES
    assert runner.LANES[LANE] is runner.lane_tiered_validation


def test_the_dark_contract_bypass_constant_is_gone() -> None:
    """`SCHEDULED_ENTRYPOINT` on this module re-disables the gate that guards it.

    `check_dark_contracts.audit()` does `if declared_module_string(rel,
    "SCHEDULED_ENTRYPOINT"): continue` -- it never reads the value. Re-adding the constant
    would silence the only automated check that this module still has a caller, which is
    how it stayed dark through a green CI for a day.
    """
    assert not hasattr(gate, "SCHEDULED_ENTRYPOINT"), (
        "run_tiered_validation_gate.py must not declare SCHEDULED_ENTRYPOINT: the "
        "dark-contract gate skips any module that does, whatever the string says."
    )


# ── and it costs nothing ─────────────────────────────────────────────────

def test_the_lane_reaches_the_gate_at_tier_zero_for_nothing() -> None:
    result = runner.lane_tiered_validation(_args())

    assert result["ok"] is True
    assert result["gate_schema"] == gate.SCHEMA
    assert result["wired"].startswith("scripts.run_tiered_validation_gate.run_once")

    # Tier 0 answered, so no critic was ever constructed, let alone called.
    assert result["tier_reached"] == 0
    assert result["state"] == "BLOCK_DETERMINISTIC"
    assert result["deterministic_verdict"] == "BLOCK"
    assert result["release_allowed"] is False
    assert result["critic_calls"] == 0
    assert result["provider_calls"] == 0
    assert result["cost_usd"] == 0.0
    assert result["paid_calls"] == 0
    # The proof that the paid tier was not merely declined but never reached.
    assert result["tier2_state"] == "NOT_REACHED_TIER0_BLOCK"


def test_the_operator_paid_judge_flag_cannot_make_this_lane_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`TRADEAI_TIER2_PAID_JUDGE` is set in the host environment. It must not matter.

    Funding a paid judge is the operator's decision (AGENTS.md §17). The flag being on is
    the operator permitting spend *somewhere*; it is not an instruction to spend here, and
    an hourly cron lane that quietly began billing because a flag flipped is precisely the
    accident this asserts against.
    """
    monkeypatch.setenv(TIER2_FLAG, "1")
    # Without this the test proves nothing: it must fail for the right reason.
    assert TierPolicy.from_env().tier2_enabled is True

    result = runner.lane_tiered_validation(_args())

    assert result["cost_usd"] == 0.0
    assert result["paid_calls"] == 0
    assert result["tier2_state"] == "NOT_REACHED_TIER0_BLOCK"


def test_the_lane_is_dispatchable_through_the_runner_report() -> None:
    """Through `run()`, the path cron takes -- not just by calling the function."""
    report = runner.run(_args(lane=LANE))

    assert report["lanes_run"] == 1
    assert report["lanes_failed"] == []
    row = report["results"][0]
    assert row["lane"] == LANE
    assert row["ok"] is True
    assert row["cost_usd"] == 0.0
    assert report["financial_action"] is False
    assert report["memory_behavior_influence"] == 0


def test_a_lane_that_reported_a_cost_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative control for the free-by-construction guard.

    Both structural defences (no provider, tier-0 short-circuit) would have to fail before
    this branch matters -- which is the argument for testing it rather than trusting it.
    """
    def billing_run_once(*_a, **_kw):
        return {
            "schema": gate.SCHEMA,
            "result": {"cost_usd": 0.02, "paid_calls": 1, "state": "REFLECTIVE_PASS",
                       "tier_reached": 2, "deterministic_verdict": "PASS",
                       "release_allowed": True, "tier2_state": "ESCALATED:PASS",
                       "critic_calls": 1},
        }

    monkeypatch.setattr(gate, "run_once", billing_run_once)
    with pytest.raises(AssertionError, match="free by construction"):
        runner.lane_tiered_validation(_args())

    # And through `run()`, a billing lane is a FAILED lane and a non-zero report.
    report = runner.run(_args(lane=LANE))
    assert report["lanes_failed"] == [LANE]
    assert report["results"][0]["ok"] is False


def test_the_wired_path_stays_advisory() -> None:
    assert gate.AUTHORITY == "READ_ONLY_ADVISORY"
    assert gate.MBI_BEHAVIOR == 0
    assert runner.AUTHORITY == "READ_ONLY_ADVISORY"
    assert runner.MBI_BEHAVIOR == 0
    assert runner.FINANCIAL_ACTION is False


def test_the_lane_writes_nothing() -> None:
    """`run_once` computes; only `main()` appends a receipt, and the lane never calls it.

    The hourly caller must not append a row to the gate's own receipt file as a side
    effect of reporting -- that would make the receipt a log of the monitor rather than of
    the work.
    """
    receipt = gate._receipt_path()
    before = receipt.stat().st_mtime_ns if receipt.exists() else None

    runner.lane_tiered_validation(_args())

    after = receipt.stat().st_mtime_ns if receipt.exists() else None
    assert after == before

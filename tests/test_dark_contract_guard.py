"""The gate must reach the same verdict everywhere.

The first CI run of this guard failed on commits that passed locally. Cause:
`scheduled_scripts()` shelled out to `crontab -l`, so a script scheduled on the
developer's machine was skipped locally and flagged in CI, where no crontab
exists. It also matched commented-out cron lines, counting a switched-off job
as scheduled. Inputs are now repo-only.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts/check_dark_contracts.py"


def _guard():
    spec = importlib.util.spec_from_file_location("dark_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_guard_reads_nothing_outside_the_repo():
    """No subprocess, no crontab, no $HOME -- or the verdict moves per machine."""
    src = GUARD.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.names[0].name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {n.module.split(".")[0]
                 for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "subprocess" not in imported, "shelling out makes the gate machine-dependent"

    # Check CODE, not prose: the module docstring explains the crontab history
    # on purpose, and a raw text search hits its own explanation -- the same
    # self-reference trap that made the guard report `inherited: 0`.
    code = "\n".join(
        ast.unparse(n) for n in tree.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str))
    )
    for banned in ("crontab", "Path.home", "os.environ", "getenv"):
        assert banned not in code, f"{banned} makes the verdict machine-dependent"


def test_a_scheduled_entrypoint_is_excused_by_declaration():
    g = _guard()
    assert g.declared_module_string("scripts/build_lesson_candidates.py",
                                    "SCHEDULED_ENTRYPOINT")
    assert g.declared_module_string("scripts/resolve_due_checkpoints.py",
                                    "SCHEDULED_ENTRYPOINT")


def test_a_declaration_must_name_the_real_scheduler():
    """research_lane_health is scheduled by a systemd TIMER, not by cron.

    Its cron line is commented out, and I read only that and declared the script
    "genuinely dark". It is not: tradeai-research-lane-health.timer runs it every
    15 minutes and it was actively alerting at the time. The declaration is a
    claim about reality and has to be checked against every scheduler, not the
    first one looked at -- removing the crontab probe made the gate
    deterministic, and moved the burden of being right onto whoever writes the
    declaration.
    """
    g = _guard()
    decl = g.declared_module_string("scripts/research_lane_health.py",
                                    "SCHEDULED_ENTRYPOINT")
    assert decl and "systemd" in decl and "timer" in decl
    assert g.declared_reason("scripts/research_lane_health.py") is None, (
        "a scheduled script must not also claim to have no consumer")


def test_the_gate_is_green_on_this_tree():
    assert _guard().audit()["new"] == []


def test_the_gate_still_fails_on_a_new_dark_contract(tmp_path, monkeypatch):
    """A guard that can only pass is not a guard."""
    g = _guard()
    probe = ROOT / "scripts/lib/_dark_guard_probe_tmp.py"
    probe.write_text('SCHEMA = "ProbeContract@v1"\n', encoding="utf-8")
    try:
        new = {r["module"] for r in g.audit()["new"]}
        assert "scripts/lib/_dark_guard_probe_tmp.py" in new
    finally:
        probe.unlink()
    assert g.audit()["new"] == []


# ── a declaration is a claim about reality, so READ it ──────────────────────


def test_a_declaration_that_says_not_installed_is_not_a_caller():
    """The gate discharged a module on the mere PRESENCE of the declaration.

    `declared_module_string` returns the STRING, but line 235 only tested it for
    truthiness — so a module stating the opposite of a schedule was counted as
    wired. Three in this repo do exactly that:

        check_operator_answer_quality.py  "(proposed, not installed)"
        set_goal_predicate.py             "PROPOSAL ONLY -- not installed"
        sweep_commitment_outcomes.py      "PROPOSAL ONLY -- not installed"

    "Built but not wired" is the defect this gate exists to surface, and it was
    hiding inside the gate itself.
    """
    g = _guard()
    assert g.declares_not_installed(
        "PROPOSAL ONLY — not installed, and deliberately not schedulable.")
    assert g.declares_not_installed(
        "systemd: tradeai-operator-answer-quality.timer (proposed, not installed)")

    # Scope: this gate audits only modules that DEFINE a versioned schema (419
    # of them). sweep_commitment_outcomes.py declares "PROPOSAL ONLY -- not
    # installed" and is classified correctly above, but defines no `@v` literal,
    # so it never enters the audit at all. Two of the three are in scope; the
    # number is 2 because of that scope, not because the rule misses one.
    dni = set(_guard().audit()["declared_not_installed"])
    for module in ("scripts/set_goal_predicate.py",
                   "scripts/check_operator_answer_quality.py"):
        assert module in dni, f"{module} declares it is not installed, yet is excused"
    assert g.declares_not_installed(
        "PROPOSAL ONLY -- not installed. Proposed: daily 18:20 after the "
        "outcome checkpoints resolve."), "the out-of-scope module's string must still classify"


def test_an_installed_declaration_is_still_excused():
    """Negative control. Without it, "discharge nothing" would satisfy the test
    above while making the gate useless — and it would flag the four honest
    declarations phrased ``cron: ... (wired ...)``, which name a real schedule
    without ever using the word "installed"."""
    g = _guard()
    for decl in (
        "INSTALLED, active — crontab `40 * * * *`, hourly at :40, from the rebuild tree",
        "cron: 40 6 * * * -- daily 06:40, --apply (wired 2026-08-27, Phase 2)",
        "systemd: tradeai-research-lane-health.timer -- every 15 min",
        "systemd: tradeai-gap-resolution.timer -- every 30 min (INSTALLED, active)",
    ):
        assert not g.declares_not_installed(decl), decl


def test_reclassification_lands_in_declared_not_in_new():
    """A module that says "not installed" HAS explained itself, so it must not
    trip --fail-on-new. Otherwise this fix would red the CI gate it repairs."""
    res = _guard().audit()
    assert res["new"] == [], [r["module"] for r in res["new"]]
    # Exactly the in-scope modules that declare themselves unwired. Pinned as a
    # set rather than a count: a count could be satisfied by the wrong modules,
    # and would not go RED if the rule started matching something else.
    assert set(res["declared_not_installed"]) == {
        "scripts/check_operator_answer_quality.py",
        "scripts/set_goal_predicate.py",
    }

"""llm_offpeak_guard: an n8n-run LLM lane must reproduce the cron line's off-peak wrapper (LQ-20261107-43, 2026-11-07).

The defect this pins: `hermes-usefulness-backfill`'s n8n command was
`env LLM_GLOBAL_DAILY_USD_CAP=2.00 $PY hermes_external_feedback_loop.py --apply` — no wrapper, no gate — while its
cron twin runs inside `run_with_deepseek_offpeak.sh --scheduled`. An n8n LIVE run could therefore spend inside
DeepSeek's billing peak.

Hermetic: the guard is pure; the fixtures are dicts. No env, no DB, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import llm_offpeak_guard as G  # noqa: E402

LLM = ["hermes-usefulness-backfill", "some-other-llm-lane"]


def _entry(lane, **kw):
    base = {"lane_id": lane, "command": ["$PY", "scripts/hermes_external_feedback_loop.py", "--apply"]}
    base.update(kw)
    return base


# ── the two accepted protections ────────────────────────────────────────────────────────────────────────────────

def test_the_reported_defect_is_flagged():
    """The n8n command from the finding: cap set, no wrapper, no gate."""
    e = _entry("hermes-usefulness-backfill", command=["env", "LLM_GLOBAL_DAILY_USD_CAP=2.00", "$PY",
                                                     "scripts/hermes_external_feedback_loop.py", "--apply"])
    p = G.entry_problem(e, llm_lane_ids=LLM)
    assert p is not None and p["code"] == "LLM_LANE_WITHOUT_OFFPEAK_GATE"
    assert p["offpeak_gate"] is None and p["wrapper_in_argv"] is False


def test_a_declared_gate_is_protection():
    for gate in sorted(G.OFFPEAK_GATES):
        assert G.entry_problem(_entry("hermes-usefulness-backfill", offpeak_gate=gate), llm_lane_ids=LLM) is None


def test_the_wrapper_in_the_argv_is_protection():
    e = _entry("hermes-usefulness-backfill",
               command=["bash", "scripts/run_with_deepseek_offpeak.sh", "--scheduled", "--", "$PY",
                        "scripts/hermes_external_feedback_loop.py", "--apply"])
    assert G.entry_problem(e, llm_lane_ids=LLM) is None


def test_a_lane_that_does_not_call_a_model_is_never_flagged():
    """The gate is about paid model calls; a deterministic lane with no gate is the normal case, not a defect."""
    assert G.entry_problem(_entry("crontab-snapshot-for-health-agent"), llm_lane_ids=LLM) is None


def test_an_unknown_gate_value_is_not_protection():
    """A misspelt gate is a typo, not a gate: the executor would not honour it."""
    p = G.entry_problem(_entry("hermes-usefulness-backfill", offpeak_gate="sched"), llm_lane_ids=LLM)
    assert p is not None and p["offpeak_gate"] == "sched"


def test_problems_are_sorted_and_skip_clean_entries():
    entries = [_entry("some-other-llm-lane"), _entry("hermes-usefulness-backfill", offpeak_gate="scheduled"),
               _entry("a-deterministic-lane")]
    found = G.problems(entries, llm_lane_ids=LLM)
    assert [p["lane_id"] for p in found] == ["some-other-llm-lane"]


# ── the vocabulary is the executor's, not a second spelling ─────────────────────────────────────────────────────

def test_the_gate_vocabulary_matches_the_executor():
    """The executor reproduces windows for exactly these names; a fourth value here would be decorative."""
    from scripts import n8n_run_executor as X  # noqa: PLC0415 — import cost is not worth paying for the pure tests

    assert set(X.OFFPEAK_GATES) == set(G.OFFPEAK_GATES)


# ── today's repo state, stated rather than assumed ──────────────────────────────────────────────────────────────

def test_every_allowlisted_llm_caller_in_the_repo_carries_offpeak_protection():
    """Run the guard over the repo's own allowlist, not over fixtures: this is the check that has to stay green.

    Why it is worth a test even though the two files barely overlap today: `hermes-usefulness-backfill` is on the n8n
    onboarding W5 commit (3e5058a4b, in the integration branches and in the served release as allowlist_version
    9d983b8f..4517a87f) and NOT yet on main — so the day that branch merges, this lane's entry becomes a live
    assertion here. Its entry declares ``offpeak_gate: "scheduled"``; if a later bundle drops that field, or adds
    another LLM caller without it, this fails instead of the fact going unnoticed the way the original defect did.

    Scope, stated plainly: the guard reads the repo's allowlist. It cannot see the served release, which on
    2026-11-07 held 175 entries against main's 142 (33 lanes, this one included, exist only there)."""
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    callers = json.loads((ROOT / "config" / "llm_direct_callers.json").read_text(encoding="utf-8"))["lanes"]
    found = G.problems(allow, llm_lane_ids=G.deepseek_payers(callers))
    assert found == [], [f"{p['lane_id']}: {p['detail']}" for p in found]
    if "hermes-usefulness-backfill" in {e["lane_id"] for e in allow}:
        entry = next(e for e in allow if e["lane_id"] == "hermes-usefulness-backfill")
        assert entry["offpeak_gate"] in G.OFFPEAK_GATES


def test_every_lane_this_repo_exempts_from_the_gate_states_its_evidence():
    """LQ-20261107-247: an exemption is only allowed with the provider and the quoted source lines.

    The five lanes below were flagged by this guard on the integration line. Each reaches Grok/ChatGPT OAuth, a local
    model, or the governed bridge — never the metered DeepSeek key — so a DeepSeek window on their entry would skip
    free work and protect nothing. The exemption is data with evidence, not a silence: drop the evidence and the lane
    is a payer again (see the fail-closed tests below)."""
    callers = {c["lane_id"]: c for c in
               json.loads((ROOT / "config" / "llm_direct_callers.json").read_text(encoding="utf-8"))["lanes"]}
    exempt = {"directive-keyword-enhancer", "generate-analyst-reports-autonomous-weekly",
              "journal-review-builder", "portfolio-lookthrough-themes", "proposal-llm-review-worker"}
    for lane in exempt:
        block = callers[lane]["billing"]
        assert block["deepseek_metered"] is False, lane
        assert block["provider"].strip(), lane
        assert len(block["evidence"]) > 80, (lane, "evidence must quote the source, not assert the conclusion")
        assert G.pays_deepseek(callers[lane]) is False, lane


# ── whose money: fail-closed, and only evidence buys an exemption ───────────────────────────────────────────────

def test_a_caller_with_no_billing_block_is_a_deepseek_payer():
    """The default has to be the expensive answer, or a new lane inherits the exemption it never earned."""
    assert G.pays_deepseek({"lane_id": "new-llm-lane"}) is True
    assert G.deepseek_payers([{"lane_id": "new-llm-lane"}]) == {"new-llm-lane"}


def test_an_exemption_without_evidence_is_not_an_exemption():
    for block in ({"deepseek_metered": False},
                  {"deepseek_metered": False, "evidence": ""},
                  {"deepseek_metered": False, "evidence": "   "},
                  {"deepseek_metered": "false", "evidence": "quoted lines"},  # a string is not the boolean
                  {"evidence": "quoted lines"},                              # the flag is what exempts
                  "not a mapping"):
        assert G.pays_deepseek({"lane_id": "x", "billing": block}) is True, block


def test_only_a_boolean_false_with_evidence_exempts():
    caller = {"lane_id": "x", "billing": {"deepseek_metered": False,
                                          "provider": "grok OAuth",
                                          "evidence": "scripts/x.py:1 imports llm_lane and calls lane='grok'"}}
    assert G.pays_deepseek(caller) is False
    assert G.deepseek_payers([caller, {"lane_id": "y"}]) == {"y"}


# ── the operator surface: scripts/check_llm_offpeak_gates.py ────────────────────────────────────────────────────

def _write(tmp_path, allow, callers):
    (tmp_path / "allow.json").write_text(json.dumps({"lanes": allow}), encoding="utf-8")
    (tmp_path / "callers.json").write_text(json.dumps({"lanes": [{"lane_id": c} for c in callers]}), encoding="utf-8")
    return ["--allowlist", str(tmp_path / "allow.json"), "--callers", str(tmp_path / "callers.json")]


def test_the_checker_exits_one_and_names_the_unprotected_lane(tmp_path, capsys):
    from scripts import check_llm_offpeak_gates as C  # noqa: PLC0415

    argv = _write(tmp_path, [_entry("hermes-usefulness-backfill"), _entry("deterministic")],
                  ["hermes-usefulness-backfill"])
    assert C.main(argv) == 1
    out = capsys.readouterr().out
    assert "hermes-usefulness-backfill" in out and "LLM_LANE" not in out and "1 problem" in out
    assert C.main(argv + ["--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["problems"] == 1 and doc["allowlisted_model_callers"] == 1 and doc["entries"] == 2


def test_the_checker_is_clean_when_the_gate_is_declared(tmp_path, capsys):
    from scripts import check_llm_offpeak_gates as C  # noqa: PLC0415

    argv = _write(tmp_path, [_entry("hermes-usefulness-backfill", offpeak_gate="scheduled")],
                  ["hermes-usefulness-backfill"])
    assert C.main(argv) == 0
    assert "clean" in capsys.readouterr().out


def test_the_checker_does_not_ask_a_non_payer_for_a_deepseek_gate(tmp_path, capsys):
    """A lane whose caller record proves it reaches no DeepSeek key is counted, and left alone."""
    from scripts import check_llm_offpeak_gates as C  # noqa: PLC0415

    (tmp_path / "allow.json").write_text(json.dumps({"lanes": [_entry("grok-only-lane")]}), encoding="utf-8")
    (tmp_path / "callers.json").write_text(json.dumps({"lanes": [{
        "lane_id": "grok-only-lane",
        "billing": {"deepseek_metered": False, "provider": "grok OAuth",
                    "evidence": "scripts/grok_only.py:7 calls llm_lane.generate(lane='grok')"}}]}), encoding="utf-8")
    argv = ["--allowlist", str(tmp_path / "allow.json"), "--callers", str(tmp_path / "callers.json")]
    assert C.main(argv) == 0
    assert "pay no DeepSeek" in capsys.readouterr().out
    assert C.main(argv + ["--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["allowlisted_model_callers"] == 1 and doc["allowlisted_deepseek_payers"] == 0
    assert doc["problems"] == 0


def test_the_checker_never_reports_an_unreadable_file_as_clean(tmp_path, capsys):
    from scripts import check_llm_offpeak_gates as C  # noqa: PLC0415

    assert C.main(["--allowlist", str(tmp_path / "absent.json")]) == 2
    assert "CANNOT RUN" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")  # a list, not an object with "lanes": not a silent zero
    assert C.main(["--allowlist", str(bad)]) == 2


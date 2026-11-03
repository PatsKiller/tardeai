"""The 85% pressure guard triggers the reviewed cleaner — only when the operator's switch is armed (2026-11-03).

Operator, 2026-11-03 (disk permanent fix, item 3): "Make the pressure guard ACT at 85%: it triggers the cleaner, not
just a report." The guard still deletes nothing itself: every removal is `scripts/disk_hygiene.py`'s, under its
reviewed standing rules and caps. These tests prove the four required behaviours and the arming contract:

(a) below threshold                     -> no action at all, no subprocess;
(b) at/above threshold, DISARMED        -> report only; the cleaner is never invoked;
(c) armed + eligible items              -> a dry run that writes nothing, then the apply;
(d) armed + zero eligible               -> a refusal; no apply argv exists at all;
plus: the switch ships OFF, a disabled/unapproved standing config disarms, and an unreadable rules file disarms.

Synthetic only: every test fakes `subprocess.run` and the disk reading; nothing here deletes, touches a store or
reaches the network.
"""
from __future__ import annotations
import pytest

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disk_pressure_guard as g  # noqa: E402

GB = 1024**3


class _Proc:
    def __init__(self, stdout: str = "", rc: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, rc, stderr


def _rules(tmp_path: Path, *, armed: bool, standing_enabled: bool = True, approval: str = "APPROVED") -> Path:
    doc = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    doc["pressure_act"] = {"armed": armed, "armed_by": "test fixture", "armed_at": None}
    doc["standing_apply"]["enabled"] = standing_enabled
    doc["standing_apply"]["approval"]["status"] = approval
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return p


def _dry_line(candidates: int, reclaimable: int = 0) -> str:
    doc = {"dry_run": True, "lane_id": "disk-hygiene", "would_write": [],
           "summary": {"totals": {"candidates": candidates, "reclaimable_bytes": reclaimable,
                                  "reclaimable_gb": round(reclaimable / GB, 2)}}}
    return "DRY-RUN " + json.dumps(doc)


def _apply_line(removed: int = 12, reclaimed_gb: float = 3.4, refused=None) -> str:
    return json.dumps({"refused": refused, "manifest_age_h": 0.1, "reclaimed_bytes": int(reclaimed_gb * GB),
                       "reclaimed_gb": reclaimed_gb, "ended_above_alert_pct": False, "removed": removed,
                       "skipped": 2, "passes": 1})


class Calls:
    """Records every argv the guard shells, and answers in order (an Exception is raised instead)."""

    def __init__(self, answers):
        self.argv: list[list[str]] = []
        self.envs: list[dict | None] = []
        self.answers = list(answers)

    def run(self, argv, **kw):
        self.argv.append([str(a) for a in argv])
        self.envs.append(kw.get("env"))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _guard(monkeypatch, tmp_path, calls: Calls, *, used=91.0, sent=None, notify=True):
    sent = sent if sent is not None else []
    reads = iter([(used, 40 * GB, 468 * GB), (used, 40 * GB, 468 * GB)])
    monkeypatch.setattr(g, "RECEIPT", tmp_path / "receipts.jsonl")
    monkeypatch.setattr(g, "disk_used_pct", lambda path="/": next(reads))
    monkeypatch.setattr(g.subprocess, "run", calls.run)
    monkeypatch.setattr(g, "notify", lambda text: sent.append(text) or "accepted")
    from lib import alert_condition_state as acs

    monkeypatch.setattr(acs, "observe",
                        lambda _key, state, **k: {"action": "alert", "notify": bool(notify and state == "PRESSURE")})
    return sent


def _receipts(tmp_path: Path) -> list[dict]:
    p = tmp_path / "receipts.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------- (a) below threshold


def test_below_threshold_takes_no_action(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([])  # any subprocess at all would raise IndexError
    sent = _guard(monkeypatch, tmp_path, calls, used=70.0)
    assert g.main(["--rules", str(rules)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["over_threshold"] is False and calls.argv == [] and sent == []
    assert out["removal"].startswith("none")
    assert "cleaner" not in out and "enforcer" not in out
    assert _receipts(tmp_path)[-1]["pressure_act"]["armed"] is True


# ---------------------------------------------------------------- (b) disarmed


def test_disarmed_above_threshold_reports_only(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=False)
    calls = Calls([_Proc(json.dumps({"releases_result": {"ok": True, "deleted": [
        {"path": "/x/old", "bytes": 0, "action": "would_delete"}]}}))])
    sent = _guard(monkeypatch, tmp_path, calls)
    assert g.main(["--rules", str(rules)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pressure_act"]["armed"] is False and out["pressure_act"]["active"] is False
    assert len(calls.argv) == 1, f"disarmed must not invoke anything but the enforcer plan: {calls.argv}"
    assert calls.argv[0][1].endswith("disk_hygiene_enforcer.py") and "--dry-run" in calls.argv[0]
    assert all("disk_hygiene.py" not in " ".join(a) for a in calls.argv), "the cleaner must not be invoked disarmed"
    assert out["removal"].startswith("none (AGENTS.md §24.12")
    assert "disk-hygiene lane owns reclaim" in sent[0] and "ARMED" not in sent[0]


# ---------------------------------------------------------------- (c) armed + eligible


def test_armed_with_eligible_items_dry_runs_then_applies(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([_Proc(_dry_line(12, 3_650_722_201)), _Proc(_apply_line(12, 3.4))])
    sent = _guard(monkeypatch, tmp_path, calls)
    before = dict(os.environ)
    assert g.main(["--rules", str(rules)]) == 0
    out = json.loads(capsys.readouterr().out)

    assert len(calls.argv) == 2, calls.argv
    dry, applied = calls.argv
    assert dry[1].endswith("disk_hygiene.py") and "--standing" in dry and "--dry-run" in dry
    assert "--apply" not in dry and "--report" in dry
    assert dry[dry.index("--only-if-above") + 1] == "85"
    assert applied[1].endswith("disk_hygiene.py") and "--apply" in applied and "--standing" in applied
    assert "--until-target" in applied and applied[applied.index("--until-target") + 1] == "75"
    assert applied[applied.index("--only-if-above") + 1] == "85"

    assert out["cleaner"]["decision"] == "applied"
    assert out["cleaner"]["selection"] == {"candidates": 12, "reclaimable_bytes": 3_650_722_201, "reclaimable_gb": 3.4}
    assert out["cleaner"]["reclaimed_bytes"] == int(3.4 * GB)
    assert out["cleaner"]["removed"] == 12
    assert out["removal"].startswith("disk_hygiene.py --standing")
    assert "ARMED" in sent[0] and "3.4 GB" in sent[0]

    # The run identity is minted for the CHILD only; the guard's own environment is untouched.
    env = calls.envs[1] or {}
    assert env.get(g.RUN_ID_ENV, "").startswith("disk_pressure_guard-")
    assert os.environ.get(g.RUN_ID_ENV) == before.get(g.RUN_ID_ENV)

    rec = _receipts(tmp_path)[-1]
    assert rec["cleaner"]["decision"] == "applied" and rec["pressure_act"]["active"] is True


# ---------------------------------------------------------------- (d) armed + zero eligible


def test_armed_with_zero_eligible_items_refuses_and_never_applies(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([_Proc(_dry_line(0, 0))])
    sent = _guard(monkeypatch, tmp_path, calls)
    assert g.main(["--rules", str(rules)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(calls.argv) == 1, f"a refused selection must never reach an apply: {calls.argv}"
    assert all("--apply" not in a for a in calls.argv)
    assert out["cleaner"]["decision"] == "refused_nothing_eligible"
    assert out["removal"].startswith("none: the reviewed cleaner selected nothing eligible")
    assert "NOTHING eligible" in sent[0]


# ---------------------------------------------------------------- the arming contract


def test_the_switch_ships_off_in_the_reviewed_config():
    doc = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    assert doc["pressure_act"]["armed"] is False, "this PR adds the capability; arming is the operator's"
    assert doc["pressure_act"].get("_owner", "").startswith("operator")


def test_a_disabled_or_unapproved_standing_config_disarms_the_guard(monkeypatch, tmp_path, capsys):
    for kwargs in ({"standing_enabled": False}, {"approval": "PENDING"}):
        rules = _rules(tmp_path, armed=True, **kwargs)
        calls = Calls([_Proc(json.dumps({"releases_result": {"ok": True}}))])
        _guard(monkeypatch, tmp_path, calls, used=91.0)
        assert g.main(["--rules", str(rules)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["pressure_act"]["active"] is False
        assert out["pressure_act"].get("why_not_active")
        assert all("disk_hygiene.py" not in " ".join(a) for a in calls.argv)


def test_an_unreadable_rules_file_disarms(monkeypatch, tmp_path, capsys):
    calls = Calls([_Proc(json.dumps({"releases_result": {"ok": True}}))])
    _guard(monkeypatch, tmp_path, calls, used=91.0)
    assert g.main(["--rules", str(tmp_path / "missing.json")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pressure_act"]["armed"] is False and out["pressure_act"]["active"] is False
    assert out["pressure_act"]["error"].startswith("rules_unreadable")
    assert all("disk_hygiene.py" not in " ".join(a) for a in calls.argv)


def test_the_guard_dry_run_never_acts_even_when_armed(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([_Proc(json.dumps({"releases_result": {"ok": True}}))])
    _guard(monkeypatch, tmp_path, calls, used=91.0)
    assert g.main(["--rules", str(rules), "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert all("disk_hygiene.py" not in " ".join(a) for a in calls.argv), calls.argv


def test_a_cleaner_that_cannot_run_is_a_process_failure(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([TimeoutError("cleaner hung")])
    _guard(monkeypatch, tmp_path, calls, used=91.0)
    assert g.main(["--rules", str(rules)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["cleaner"]["decision"] == "error"
    assert out["removal"].startswith("none: the cleaner did not complete")


def test_a_cleaner_that_reports_instead_of_planning_is_an_error_not_a_refusal(monkeypatch, tmp_path, capsys):
    """A dry run that fails (rules/evidence) must never be read as 'nothing eligible' — and must never apply."""
    rules = _rules(tmp_path, armed=True)
    calls = Calls([_Proc(json.dumps({"dry_run": True, "ok": False, "error": "standing_rules_shape"}))])
    _guard(monkeypatch, tmp_path, calls, used=91.0)
    assert g.main(["--rules", str(rules)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["cleaner"]["decision"] == "error" and out["cleaner"]["error"] == "standing_rules_shape"
    assert len(calls.argv) == 1 and all("--apply" not in a for a in calls.argv)


def test_every_flag_the_guard_shells_exists_in_the_cleaner():
    """The guard shells an EXISTING CLI (AGENTS.md §24.12); a rename must not turn this into a silent no-op."""
    src = (ROOT / "scripts" / "disk_hygiene.py").read_text(encoding="utf-8")
    for flag in ('"--standing"', '"--dry-run"', '"--apply"', '"--only-if-above"', '"--until-target"',
                 '"--rules"', '"--report"', '"--state-root"'):
        assert flag in src, f"disk_hygiene.py no longer accepts {flag}; the guard would silently stop working"


# ---------------------------------------------------------------- (R1) disarm during the preview
class _DisarmDuringPreview(Calls):
    """Answers the preview, then mutates one gate in the rules before the guard's next decision."""

    def __init__(self, rules: Path, answers, mutate=None):
        super().__init__(answers)
        self.rules = rules
        self.mutate = mutate or (lambda doc: doc["pressure_act"].__setitem__("armed", False))

    def run(self, argv, **kw):
        proc = super().run(argv, **kw)
        if "--dry-run" in [str(a) for a in argv]:
            doc = json.loads(self.rules.read_text(encoding="utf-8"))
            self.mutate(doc)
            self.rules.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        return proc


def test_disarming_during_the_preview_never_requests_an_apply(monkeypatch, tmp_path, capsys):
    """P1 R1: the operator flips the switch off while the preview runs; the exec boundary must refuse."""
    rules = _rules(tmp_path, armed=True)
    calls = _DisarmDuringPreview(rules, [_Proc(stdout=_dry_line(12, 3 * GB), rc=0)])
    _guard(monkeypatch, tmp_path, calls)
    rc = g.main(["--rules", str(rules)])
    out = json.loads(capsys.readouterr().out)
    applies = [argv for argv in calls.argv if "--apply" in argv]
    assert applies == [], f"an apply was constructed after a disarm: {applies}"
    assert out["cleaner"]["decision"] == "refused_disarmed"
    assert out["cleaner"]["error"] == "pressure_act_disarmed_before_apply"
    assert rc == 0  # a refusal is a completed run, and the shared cleaner unit owns the exit contract
    receipt = _receipts(tmp_path)[-1]
    assert "pressure_act_disarmed_before_apply" in json.dumps(receipt)
    assert receipt.get("cleaner", {}).get("decision") == "refused_disarmed"


# ---------------------------------------------------------------- (R2) failed preview is not a plan
def test_a_failed_preview_never_requests_an_apply(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([_Proc(stdout=_dry_line(12, 3 * GB), rc=1)])
    _guard(monkeypatch, tmp_path, calls)
    g.main(["--rules", str(rules)])
    out = json.loads(capsys.readouterr().out)
    assert [argv for argv in calls.argv if "--apply" in argv] == []
    assert out["cleaner"]["decision"] == "error"
    assert out["cleaner"]["error"] == "dry_run_failed_rc_1"


# ---------------------------------------------------------------- (R3) a failed cleaner is not "applied"
def test_a_failed_cleaner_is_not_reported_as_applied(monkeypatch, tmp_path, capsys):
    rules = _rules(tmp_path, armed=True)
    failure = json.dumps({"ok": False, "error": "rules_unreadable:JSONDecodeError"})
    calls = Calls([_Proc(stdout=_dry_line(12, 3 * GB), rc=0), _Proc(stdout=failure, rc=1)])
    _guard(monkeypatch, tmp_path, calls)
    g.main(["--rules", str(rules)])
    out = json.loads(capsys.readouterr().out)
    assert out["cleaner"]["decision"] == "error"
    assert out["cleaner"]["decision"] != "applied"
    assert out["cleaner"]["error"].startswith("apply_failed_rc_1")


@pytest.mark.parametrize("gate,mutate", [
    ("standing_apply.enabled", lambda doc: doc["standing_apply"].__setitem__("enabled", False)),
    ("standing_apply.approval.status", lambda doc: doc["standing_apply"]["approval"].__setitem__("status", "PENDING")),
])
def test_every_arming_gate_closed_mid_preview_refuses_the_apply(monkeypatch, tmp_path, capsys, gate, mutate):
    """cc4's point: the exec-boundary recheck must cover all three gates, not just `armed`."""
    rules = _rules(tmp_path, armed=True)
    calls = _DisarmDuringPreview(rules, [_Proc(stdout=_dry_line(12, 3 * GB), rc=0)], mutate=mutate)
    _guard(monkeypatch, tmp_path, calls)
    g.main(["--rules", str(rules)])
    out = json.loads(capsys.readouterr().out)
    assert [argv for argv in calls.argv if "--apply" in argv] == [], f"{gate} closed but an apply was constructed"
    assert out["cleaner"]["decision"] == "refused_disarmed"
    assert out["cleaner"]["error"] == "pressure_act_disarmed_before_apply"


# ---------------------------------------------------------------- (F6) a refused or partial preview is not a plan
@pytest.mark.parametrize("preview,why", [
    (json.dumps({"candidates": 1}), "dry_run_envelope_missing"),
    (json.dumps({"summary": {"totals": {"candidates": 1}}}), "dry_run_envelope_missing"),
    (json.dumps({"candidates": 1, "refused": "manifest_stale"}), "dry_run_refused:manifest_stale"),
    (json.dumps({"dry_run": True, "summary": {"totals": {"candidates": "1"}}}), "dry_run_candidates_invalid"),
])
def test_a_partial_or_refusing_preview_never_constructs_an_apply(monkeypatch, tmp_path, capsys, preview, why):
    rules = _rules(tmp_path, armed=True)
    calls = Calls([_Proc(stdout=preview, rc=0)])
    _guard(monkeypatch, tmp_path, calls, used=91.0)
    g.main(["--rules", str(rules)])
    out = json.loads(capsys.readouterr().out)
    assert [a for a in calls.argv if "--apply" in a] == [], "an apply was constructed from an unrecognised preview"
    assert out["cleaner"]["decision"] == "error"
    assert out["cleaner"]["error"] == why


def test_a_below_threshold_apply_result_is_not_reported_as_applied(monkeypatch, tmp_path, capsys):
    """F5: a child that returns below_threshold after the preview did not remove anything."""
    rules = _rules(tmp_path, armed=True)
    below = json.dumps({"outcome": "below_threshold", "removed": None, "reclaimed_bytes": 0})
    calls = Calls([_Proc(stdout=_dry_line(12, 3 * GB), rc=0), _Proc(stdout=below, rc=0)])
    _guard(monkeypatch, tmp_path, calls, used=91.0)
    g.main(["--rules", str(rules)])
    out = json.loads(capsys.readouterr().out)
    assert out["cleaner"]["decision"] == "below_threshold"
    assert out["cleaner"]["decision"] != "applied"


def test_the_helper_enforces_the_gate_even_when_the_caller_passes_nothing(tmp_path, monkeypatch):
    """F4: run_cleaner must not rely on its caller to supply the arming recheck."""
    rules = _rules(tmp_path, armed=False)
    calls = Calls([])
    monkeypatch.setattr(g.subprocess, "run", calls.run)   # any cleaner invocation would IndexError on the empty queue
    out = g.run_cleaner(rules_path=rules, state_root=None, trigger_pct=91.0, target_pct=None)
    assert out["decision"] == "refused_disarmed", out
    assert calls.argv == []

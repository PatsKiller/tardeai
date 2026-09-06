"""The daily sweep that would have found what took a full session by hand.

Every check here exists because the defect it detects was real on 2026-09-06 and
had been silently true for weeks or months. Run cold against origin/main, the
engine independently rediscovered all of them plus one more (db_retention
unscheduled).

It reports and does not repair — deliberately. Re-enabling taxonomy_tagger, the
"obvious" fix for one of these findings, would have foreclosed a 32,060-row
corpus. An auto-fixer would have taken that action.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deterministic_integrity as DI  # noqa: E402


# ── it must never repair ───────────────────────────────────────────────────

def test_the_engine_does_not_write_or_execute():
    """A check that acts is another thing nobody is watching."""
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    for banned in ("INSERT INTO", "UPDATE ", "DELETE FROM", "os.remove",
                   "shutil.rmtree", "crontab -", "write_text("):
        assert banned not in src, f"the engine must not repair: found {banned!r}"


def test_no_model_in_the_engine():
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    low = src.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "completion", "prompt"):
        assert banned not in low, f"deterministic engine referenced {banned}"


# ── a commented cron is not scheduled ──────────────────────────────────────

def test_a_commented_cron_is_not_scheduled():
    """taxonomy_tagger sat commented for two months and every filename grep
    reported it as present."""
    cron = "# 20 * * * * python3 scripts/taxonomy_tagger.py --all\n"
    assert DI.is_scheduled("taxonomy_tagger.py", cron=cron, timers="") is False


def test_an_active_cron_is_scheduled():
    cron = "20 * * * * python3 scripts/taxonomy_tagger.py --all\n"
    assert DI.is_scheduled("taxonomy_tagger.py", cron=cron, timers="") is True


def test_a_systemd_timer_counts():
    assert DI.is_scheduled("mint_identity_registry.py", cron="",
                           timers="mint_identity_registry.timer") is True


def test_commented_only_is_reported_distinctly(monkeypatch):
    """'Present as a comment' is more deceptive than absent, and gets its own
    check so the remediation can say so."""
    monkeypatch.setattr(DI, "_crontab",
                        lambda: "# 20 * * * * python3 scripts/taxonomy_tagger.py\n")
    out = DI.check_commented_out_crons(["taxonomy_tagger.py"])
    assert out and out[0]["check"] == "cron_commented_out"


def test_an_active_line_suppresses_the_commented_finding(monkeypatch):
    monkeypatch.setattr(
        DI, "_crontab",
        lambda: "# old\n20 * * * * python3 scripts/taxonomy_tagger.py --all\n")
    assert DI.check_commented_out_crons(["taxonomy_tagger.py"]) == []


# ── populations are aggregated, not shouted ────────────────────────────────

def test_population_checks_collapse_to_one_finding():
    """309 tree-relative .env findings emitted individually is an alert nobody
    reads. AGENTS.md: a mechanical sweep is a candidate generator, not a count."""
    many = [DI._finding("tree_relative_secret", DI.P1, f"f{i}.py", "d", "fix")
            for i in range(50)]
    out = DI._aggregate(many)
    assert len(out) == 1
    assert "50" in out[0]["detail"]
    assert out[0]["severity"] == DI.P2, "a latent population is a debt, not an outage"


def test_incident_checks_are_not_aggregated():
    one = [DI._finding("producer_unscheduled", DI.P1, "x.py", "d", "fix")]
    assert DI._aggregate(one) == one


# ── the empty-join check, which is the 30-day CIO outage ───────────────────

class _FakeCur:
    def __init__(self, n): self.n = n
    def execute(self, *a, **k): pass
    def fetchone(self): return (self.n,)


class _FakeConn:
    def __init__(self, n): self._n = n
    def cursor(self): return _FakeCur(self._n)


def test_an_empty_join_input_is_p0():
    """cio_decision_engine INNER JOINed a 0-row table and reported success on
    3,010 runs a week for 30 days."""
    out = DI.check_empty_join_inputs(_FakeConn(0),
                                     [("cio_decision_engine", "strategy_rule_evaluations")])
    assert out and out[0]["severity"] == DI.P0


def test_a_populated_join_input_is_silent():
    assert DI.check_empty_join_inputs(_FakeConn(2716),
                                      [("cio_decision_engine", "strategy_rule_evaluations")]) == []


# ── docstrings must not satisfy a check ────────────────────────────────────

def test_checks_read_code_not_prose():
    """Three guards this session passed on a comment describing the defect."""
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    assert "_code_only" in src
    stripped = DI._code_only('def f():\n    """rows_processed: int = 0 in a docstring"""\n    return 1\n')
    assert "rows_processed" not in stripped


def test_exit_status_is_not_the_alarm_channel():
    """Findings live in the report. Exit 0 = the check ran, so systemd cannot
    confuse a crashed sweep with a sweep that found something."""
    runner = (ROOT / "scripts" / "run_integrity_checks.py").read_text(encoding="utf-8")
    assert "the CHECK ran" in runner or "check ran" in runner.lower()
    assert "return 0" in runner


# ── the declared-output check: THE defect class ────────────────────────────
#
# All 31 pipelines declare `output_tables` in pipeline_stage_owner_map. Exactly
# one place read that field, and only to forward it to a display payload. So the
# declaration drifted until it was fiction: ~20 name a table that DOES NOT
# EXIST, and symbol_enrichment declares `symbol_metadata` while actually writing
# iris_taxonomy_proposals, news_articles and trade_ai_scans.
#
# A declaration nothing validates is not a contract, it is a comment. That is why
# "runs fine, produces nothing" kept recurring: success was never joined to output.


class _MapCur:
    """Cursor stub: pipeline_runs counts, table columns, and max(ts)."""

    def __init__(self, runs, last_run, columns, newest):
        self._runs, self._last, self._cols, self._newest = runs, last_run, columns, newest
        self._mode = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).lower()
        self._mode = ("runs" if "from pipeline_runs" in s
                      else "cols" if "information_schema.columns" in s
                      else "max")

    def fetchone(self):
        return (self._runs, self._last) if self._mode == "runs" else (self._newest,)

    def fetchall(self):
        return [(c,) for c in self._cols]


class _MapConn:
    def __init__(self, cur): self._cur = cur
    def cursor(self): return self._cur


def _dt(s):
    from datetime import datetime, timezone
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


OWNER = {"p": {"output_tables": ["t"]}}


def test_success_without_output_is_p0():
    """cio_decision_engine: 3,010 successful runs a week, 30 days, nothing
    written. social_ingest: 34 runs, table never written."""
    cur = _MapCur(34, _dt("2026-09-05T18:00:00"), {"created_at"}, None)
    out = DI.check_declared_output_not_produced(_MapConn(cur), OWNER)
    assert out and out[0]["check"] == "declared_output_not_produced"
    assert out[0]["severity"] == DI.P0


def test_output_newer_than_the_run_is_silent():
    cur = _MapCur(10, _dt("2026-09-05T18:00:00"), {"created_at"}, _dt("2026-09-06T10:00:00"))
    assert DI.check_declared_output_not_produced(_MapConn(cur), OWNER) == []


def test_a_declared_table_that_does_not_exist_is_its_own_finding():
    """Eight declared tables do not exist. Collapsing that into 'untimestamped'
    understated it — a pipeline cannot produce into a table that is not there."""
    cur = _MapCur(5, _dt("2026-09-05T18:00:00"), set(), None)
    out = DI.check_declared_output_not_produced(_MapConn(cur), OWNER)
    assert out and out[0]["check"] == "declared_output_missing"
    assert out[0]["severity"] == DI.P1


def test_a_table_without_a_timestamp_says_so_rather_than_guessing():
    cur = _MapCur(5, _dt("2026-09-05T18:00:00"), {"id", "symbol"}, None)
    out = DI.check_declared_output_not_produced(_MapConn(cur), OWNER)
    assert out and out[0]["check"] == "declared_output_untimestamped"


def test_the_timestamp_column_is_discovered_not_assumed():
    """Assuming created_at reported trade_ai_scans — a healthy table using
    scanned_at — as unreadable on the very first run. A false positive is how an
    alarm becomes ignorable."""
    cur = _MapCur(5, _dt("2026-09-05T18:00:00"), {"scanned_at"}, _dt("2026-09-06T10:00:00"))
    assert DI.check_declared_output_not_produced(_MapConn(cur), OWNER) == []
    assert "scanned_at" in DI._TS_COLUMNS


def test_a_pipeline_that_never_ran_is_not_this_finding():
    """Never-ran is a different defect with a different fix; conflating them
    sends the reader to the wrong place."""
    cur = _MapCur(0, None, {"created_at"}, None)
    assert DI.check_declared_output_not_produced(_MapConn(cur), OWNER) == []


def test_it_does_not_trust_self_reported_rows():
    """rows_produced defaulted to 0 for 16 of 20 callers — the field that cannot
    be relied on. This check measures the STORE."""
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    fn = src.split("def check_declared_output_not_produced", 1)[1].split("\ndef ", 1)[0]
    assert "rows_produced" not in fn.split('"""', 2)[-1]

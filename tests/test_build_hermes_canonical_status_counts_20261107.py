"""ANCHOR: BUILD_HERMES_CANONICAL_STATUS_COUNTS_20261107 — the counts are measured, or unknown.

LQ-20261107-139 (audit78 batch 2). ``data/runtime/hermes_canonical_status_latest.json`` is the single
source the portal, the matrix Markdown and the Word doc are regenerated from, and its header carried

    "timers_count": 38, "crons_count": 209, "services_count": 2, "llm_jobs_count": 6

as literals since the file was first written (baa3ac462, 2026-06-07) — never computed. Measured on the
host on 2026-11-07 with the definitions this fix records:

    crontab -l                            1,111 lines, 327 active (not blank, not a '#' comment)
    systemctl --user list-units --type=timer --all --no-legend     83

The snapshot said 209/38. A stale count is worse than no count: the auditor could not tell which of
209, 327 and 438 was "the" number (the remediation catalogue, n8n_remediation_catalogue.json:1232,
carried the same complaint), and a reader had no way to reconcile any of them.

The rule this pins: a count is either measured, with its definition written next to it, or it is
``None`` with the reason — never a remembered number and never 0 standing in for "could not ask".

Hermetic: crontab and systemctl output are injected; no subprocess, no network, no files.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_hermes_canonical_status as b  # noqa: E402

CRONTAB_TEXT = """\
# m h dom mon dow command
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

15 */2 * * * cd $PROJ && flock -n /tmp/hermes_canon_status.lock $PY scripts/build_hermes_canonical_status.py
# RETIRED 2026-11-07 n8n-cutover build-hermes-canonical-status 15 */2 * * *
   # an indented comment
*/5 * * * * $PY scripts/x.py
"""
TIMERS_TEXT = """\
hermes-deep-research-local.timer loaded active waiting daily research
backup.timer                        loaded inactive dead
"""
SYSTEM_TIMERS_TEXT = """\
snapd.snap-repair.timer            snapd.snap-repair.service
ua-timer.timer                     ua-timer.service
"""


def test_active_crontab_lines_ignore_comments_and_blanks():
    assert b.count_active_crontab_lines(CRONTAB_TEXT) == 4   # SHELL=, PATH=, the job, */5


def test_an_empty_crontab_reads_zero_not_unknown():
    assert b.count_active_crontab_lines("") == 0
    assert b.count_active_crontab_lines("# only a comment\n\n") == 0


def test_user_timers_are_counted():
    assert b.count_user_timers(TIMERS_TEXT) == 2
    assert b.count_user_timers("") == 0


def test_measure_reads_the_host(monkeypatch):
    _host(monkeypatch, crons=(0, CRONTAB_TEXT), timers=(0, TIMERS_TEXT))
    counts = b.measure_host_counts()
    assert counts["crons_count"] == 4
    assert counts["timers_count"] == 2
    assert "crontab -l" in counts["counts_provenance"]["crons_count"]["definition"]
    assert "list-timers" in counts["counts_provenance"]["timers_count"]["definition"]
    assert counts["timers_system_count"] == 2          # system scope is measured separately
    assert counts["counts_provenance"]["crons_count"]["error"] is None


def test_a_failed_crontab_is_unknown_not_zero(monkeypatch):
    """A sandbox without crontab must not report an empty crontab, and must not report 209."""
    _host(monkeypatch, crons=(127, ""), timers=(0, TIMERS_TEXT))
    counts = b.measure_host_counts()
    assert counts["crons_count"] is None
    assert counts["timers_count"] == 2
    assert "crontab" in counts["counts_provenance"]["crons_count"]["error"]


def test_a_failed_systemctl_is_unknown_not_zero(monkeypatch):
    _host(monkeypatch, crons=(0, CRONTAB_TEXT), timers=(1, ""))
    counts = b.measure_host_counts()
    assert counts["timers_count"] is None
    assert "systemctl" in counts["counts_provenance"]["timers_count"]["error"]


def test_static_counts_are_named_as_unmeasured():
    """Two header counts are still literals; the snapshot must say so rather than imply a measurement."""
    prov = b.measure_host_counts()["counts_provenance"]
    assert prov["services_count"]["measured"] is False
    assert prov["services_count"]["value"] == 2
    assert prov["llm_jobs_count"]["measured"] is False


def test_the_snapshot_carries_measured_counts_and_never_the_constants(monkeypatch):
    monkeypatch.setattr(b, "api", lambda ep: {})
    monkeypatch.setattr(b, "sysd", lambda cmd: "")
    _host(monkeypatch, crons=(0, CRONTAB_TEXT), timers=(0, TIMERS_TEXT))

    snap, _results = b.build_snapshot()

    assert snap["crons_count"] == 4
    assert snap["timers_count"] == 2
    assert snap["crons_count"] != 209 and snap["timers_count"] != 38
    assert "counts_provenance" in snap


def test_the_snapshot_says_unknown_when_the_host_cannot_be_asked(monkeypatch):
    monkeypatch.setattr(b, "api", lambda ep: {})
    monkeypatch.setattr(b, "sysd", lambda cmd: "")
    _host(monkeypatch, crons=(1, ""), timers=(1, ""))

    snap, _ = b.build_snapshot()

    assert snap["crons_count"] is None and snap["timers_count"] is None


def _host(monkeypatch, *, crons, timers, sys_timers=None):
    """Route the measurement commands to canned (returncode, stdout) pairs."""
    def fake_run(cmd, **_kw):
        text = " ".join(cmd)
        if "list-timers" in text:
            rc, out = (sys_timers or (0, SYSTEM_TIMERS_TEXT)) if "--user" not in text else timers
        else:
            rc, out = crons
        return rc, out

    monkeypatch.setattr(b, "_run", fake_run)

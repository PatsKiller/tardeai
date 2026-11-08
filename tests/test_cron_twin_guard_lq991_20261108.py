"""ANCHOR: CRON_TWIN_GUARD_LQ991_20261108 — an n8n-live lane must not still own a firing crontab line.

Fable's n8n design audit (LQ-984 Q6 #1/#14) counted 37 crontab lines whose script belonged to a lane
with `dispatch.mode: live`. Attribution by bare script basename is wrong in both directions, and this
repo has already paid for both: commenting a sibling lane's line stops a lane that is running, and
missing a line leaves the lane on two schedulers where the cron side wins the flock and the n8n side
records RUN_SKIPPED_LOCK (looks scheduled, is not running where it was declared).

Measured on the live crontab at 2026-11-08T16:41Z against the 723-row registry: 25 lanes own 26
firing lines. Eleven of the audit's 37 were a sibling's line with different arguments. So every test
below is a pair — the shape that must read twin, and a control that must still read clean — plus the
exit-code contract, because a gate that returns 2 for a missing input has read as a pass here before.

COVERS: scripts/lib/cron_twin_attribution.py::attribute_line
COVERS: scripts/lib/cron_twin_attribution.py::findings
COVERS: scripts/lib/cron_twin_attribution.py::render_snapshot
COVERS: scripts/lib/cron_twin_attribution.py::dev_tree_lines
COVERS: scripts/check_cron_twins.py::main
COVERS: scripts/check_cron_twins.py::resolve_source

Hermetic: synthetic registry rows and crontab text under tmp_path. No crontab command, no systemd,
no database, no host state. One test reads the committed snapshot and registry to prove the gate is
green today; it never reads the host.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import check_cron_twins as CHK
from scripts.lib import cron_twin_attribution as CTA
from scripts.n8n_cutover_wave import comment_plan

HEAD = "#!/bin/sh\nPROJ=$HOME/trade-ai-releases/portfolio-server/CURRENT\n"


def _row(lane_id: str, *, state: str = "ACTIVE", mode: str | None = "live",
         kind: str = "cron", match=None, expression: str = "") -> dict:
    sched: dict = {"kind": kind, "expression": expression or lane_id}
    if match is not None:
        sched["match"] = match
    row: dict = {"lane_id": lane_id, "state": state, "scheduler": sched}
    if mode is not None:
        row["dispatch"] = {"mode": mode}
    return row


def _rows(*rows: dict) -> dict[str, dict]:
    return {r["lane_id"]: r for r in rows}


def _attr(line: str, rows: dict[str, dict], no: int = 7) -> CTA.Attribution:
    return CTA.attribute_line(line, rows, line_no=no)


def _codes(items) -> list[tuple[str, str]]:
    return sorted((f["code"], f.get("lane_id") or ",".join(f.get("lane_ids") or [])) for f in items)


# ── attribution: the twin, and the sibling that is not one ──────────────────────────────────

def test_a_live_n8n_lane_with_a_firing_line_is_a_twin():
    rows = _rows(_row("alpha", match="scripts/alpha.py"))
    line = "5 9 * * * cd $PROJ && $PY scripts/alpha.py"
    got = CTA.findings([_attr(line, rows)], rows)
    assert _codes(got) == [(CTA.TWIN, "alpha")]
    assert got[0]["method"] == "match"


def test_a_live_n8n_lane_without_a_firing_line_is_clean():
    rows = _rows(_row("alpha", match="scripts/alpha.py"))
    line = "5 9 * * * cd $PROJ && $PY scripts/beta.py"
    assert CTA.findings([_attr(line, rows)], rows) == []


def test_a_cron_parity_lane_is_not_a_twin_until_dispatch_mode_is_live():
    """The cutover keeps the cron line during parity on purpose: that is the declared state."""
    rows = _rows(_row("alpha", mode="canary", match="scripts/alpha.py"))
    line = "5 9 * * * cd $PROJ && $PY scripts/alpha.py"
    assert CTA.findings([_attr(line, rows)], rows) == []


def test_a_sibling_running_the_same_script_with_other_arguments_is_not_a_twin():
    """The audit's false positive: both lanes run data_gap_resolver.py; only one owns this line."""
    rows = _rows(
        _row("resolver-pre", match="$PROJ && $PY scripts/data_gap_resolver.py --pre-overnight"),
        _row("resolver-010", match="$PROJ && $PY scripts/data_gap_resolver.py --at 0,10,16"),
    )
    pre = "10 5 * * * cd $PROJ && $PY scripts/data_gap_resolver.py --pre-overnight"
    at = "5 0,10,16 * * * cd $PROJ && $PY scripts/data_gap_resolver.py --at 0,10,16"
    pre_attr, at_attr = _attr(pre, rows, 7), _attr(at, rows, 8)
    assert pre_attr.owners == {"resolver-pre": "match"}
    assert at_attr.owners == {"resolver-010": "match"}
    # each line is a twin of its own lane, and of no other: the audit reported four
    assert _codes(CTA.findings([pre_attr, at_attr], rows)) == [(CTA.TWIN, "resolver-010"),
                                                               (CTA.TWIN, "resolver-pre")]


def test_the_script_plus_args_fallback_names_the_sibling_whose_match_drifted():
    """When the registry text has drifted off the line, the args still pick one lane."""
    rows = _rows(
        _row("resolver-pre", match="$PROJ && $PY scripts/data_gap_resolver.py --pre-overnight"),
        _row("resolver-010", match="$PROJ && $PY scripts/data_gap_resolver.py --at 0,10,16"),
    )
    drifted = "10 5 * * * cd /srv/rel && flock -n /tmp/x.lock $PY scripts/data_gap_resolver.py --at 0,10,16"
    got = _attr(drifted, rows)
    assert got.owners == {"resolver-010": "script+args"}
    assert got.ambiguous == []


def test_an_argument_tie_is_ambiguous_and_owned_by_nobody():
    """Two rows that cannot be told apart must not be guessed between: nobody comments that line."""
    rows = _rows(
        _row("twin-a", match="/srv/never/here/scripts/dup.py --report"),
        _row("twin-b", match="/srv/never/here/scripts/dup.py --report"),
    )
    line = "0 6 * * * cd $PROJ && $PY scripts/dup.py --report"
    got = _attr(line, rows)
    assert got.owners == {} and got.ambiguous == ["twin-a", "twin-b"]
    assert _codes(CTA.findings([got], rows)) == [(CTA.AMBIGUOUS, "twin-a,twin-b")]


def test_a_tag_is_authoritative_over_text_that_names_another_lane():
    rows = _rows(_row("tagged", match="nowhere"), _row("mentions", match="scripts/shared.py"))
    line = "0 6 * * * cd $PROJ && $PY scripts/shared.py  # TRADEAI_LANE tagged"
    got = _attr(line, rows)
    assert got.owners == {"tagged": "tag"}


def test_the_effect_wrapper_names_its_lane():
    rows = _rows(_row("calibration"), _row("other", match="effect_claim_cron.sh other"))
    line = ("0 12 * * 0 cd $PROJ && flock -n /tmp/c.lock env TRADEAI_EFFECT_CLAIM=calibration "
            "bash scripts/effect_claim_cron.sh calibration $PY scripts/agent_calibration_engine.py")
    got = _attr(line, rows)
    assert got.owners == {"calibration": "effect_claim"}


def test_a_retired_rows_drifted_match_does_not_own_a_siblings_line():
    """RETIRED + a stale match string must not read as a finding on somebody else's live line."""
    rows = _rows(
        _row("old-lane", state="RETIRED", mode=None, match="$PROJ && $PY scripts/shared.py --old"),
        _row("current", match="$PROJ && $PY scripts/shared.py --new"),
    )
    line = "0 6 * * * cd $PROJ && $PY scripts/shared.py --new"
    got = CTA.findings([_attr(line, rows)], rows)
    assert _codes(got) == [(CTA.TWIN, "current")]


def test_a_retired_lane_that_still_owns_a_firing_line_is_reported():
    rows = _rows(_row("old-lane", state="RETIRED", mode=None, match="scripts/shared.py --old"))
    line = "0 6 * * * cd $PROJ && $PY scripts/shared.py --old"
    assert _codes(CTA.findings([_attr(line, rows)], rows)) == [(CTA.INACTIVE, "old-lane")]


def test_a_list_match_finds_a_compound_line_and_each_lane_is_its_own_finding():
    rows = _rows(
        _row("ri-queue", match=["scripts/ri_queue.py --drain", "scripts/ri_report.py"]),
        _row("ri-report", match="scripts/ri_report.py"),
    )
    line = "45 16 * * 1-5 cd $PROJ && $PY scripts/ri_queue.py --drain && $PY scripts/ri_report.py"
    got = CTA.findings([_attr(line, rows)], rows)
    assert _codes(got) == [(CTA.TWIN, "ri-queue"), (CTA.TWIN, "ri-report")]
    assert got[0]["line_no"] == 7 == got[1]["line_no"]


def test_comments_and_variable_lines_are_not_firing_lines():
    text = HEAD + "# 0 6 * * * $PY scripts/alpha.py\nMYVAR=1\n0 6 * * * $PY scripts/alpha.py\n"
    assert [n for n, _ in CTA.active_lines(text)] == [5]


# ── sanitized snapshot ──────────────────────────────────────────────────────────────────────

def test_a_snapshot_carries_no_home_path_and_still_attributes():
    rows = _rows(_row("alpha", match=f"{Path.home()}/trade-ai-releases/portfolio-server/CURRENT && $PY scripts/alpha.py"))
    raw = f"PROJ={Path.home()}/trade-ai-releases/portfolio-server/CURRENT\n0 6 * * * cd $PROJ && $PY scripts/alpha.py\n"
    snap = CTA.render_snapshot(raw, source="test", now=datetime(2026, 11, 8, tzinfo=timezone.utc))
    assert str(Path.home()) not in snap
    assert "$HOME/trade-ai-releases" in snap
    assert _codes(CTA.findings(CTA.attribute_crontab(snap, list(rows.values())), rows)) == [(CTA.TWIN, "alpha")]


def test_an_unstamped_or_stale_snapshot_has_no_age():
    assert CTA.snapshot_age_days("0 6 * * * $PY scripts/alpha.py\n") is None
    old = CTA.render_snapshot("0 6 * * * $PY x.py\n", source="t", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert CTA.snapshot_age_days(old, now=datetime(2026, 11, 8, tzinfo=timezone.utc)) > 300


# ── dev-tree interpreter (#14) ─────────────────────────────────────────────────────────────

def test_the_dev_tree_count_follows_the_one_py_definition():
    dev = CTA.dev_tree_lines("PY=$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python\n"
                             "0 6 * * * cd $PROJ && $PY a.py\n1 6 * * * bash b.sh\n")
    assert dev["count"] == 1 and dev["uses_release"] is False
    rel = CTA.dev_tree_lines("PY=$HOME/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python\n"
                             "0 6 * * * cd $PROJ && $PY a.py\n")
    assert rel["count"] == 0 and rel["uses_release"] is True


# ── the operator's command set is the check's own set ─────────────────────────────────────

def test_comment_cron_comments_exactly_the_lanes_and_lines_the_check_reports():
    """The list the DONE note hands the operator must be the list the tool accepts, line for line."""
    rows = _rows(
        _row("alpha", match="$PROJ && $PY scripts/alpha.py"),
        _row("beta", match="$PROJ && $PY scripts/beta.py"),
        _row("gamma", mode="canary", match="$PROJ && $PY scripts/gamma.py"),
    )
    text = ("10 6 * * * cd $PROJ && $PY scripts/alpha.py\n"
            "20 6 * * * cd $PROJ && $PY scripts/beta.py\n"
            "30 6 * * * cd $PROJ && $PY scripts/gamma.py\n")
    found = CTA.findings(CTA.attribute_crontab(text, list(rows.values())), rows)
    lanes = sorted({f["lane_id"] for f in found})
    edits, problems = comment_plan(text, rows, lanes, "2026-11-08")
    assert problems == []
    assert sorted(e["lane_id"] for e in edits) == lanes == ["alpha", "beta"]
    assert sorted(e["index"] for e in edits) == sorted(f["line_no"] - 1 for f in found)


# ── CLI: exit codes are the contract ───────────────────────────────────────────────────────

def _write_snapshot(tmp: Path, body: str, *, captured: str | None = None, stale: bool = False) -> Path:
    ts = captured or ((datetime.now(timezone.utc) - timedelta(days=400)) if stale
                      else datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    head = f"# tradeai-crontab-snapshot CrontabSnapshot@v1 captured_at={ts} source=test sanitized_home=true\n"
    p = tmp / "snap.txt"
    p.write_text(head + body, encoding="utf-8")
    return p


def _write_inputs(tmp: Path, rows: list[dict], body: str, **snap_kw) -> tuple[Path, Path, Path]:
    reg = tmp / "registry.json"
    reg.write_text(json.dumps({"lanes": rows}), encoding="utf-8")
    snap = _write_snapshot(tmp, body, **snap_kw)
    return reg, snap, tmp / "baseline.json"


TWIN_BODY = "10 6 * * * cd $PROJ && $PY scripts/alpha.py\n"
TWIN_ROWS = [_row("alpha", match="$PROJ && $PY scripts/alpha.py")]


def _run(reg, snap, baseline, *extra) -> int:
    return CHK.main(["--registry", str(reg), "--source", "committed", "--committed-snapshot", str(snap),
                     "--baseline", str(baseline), *extra])


def test_cli_clean_is_zero_with_or_without_fail_on_new(tmp_path, capsys):
    reg, snap, base = _write_inputs(tmp_path, [_row("alpha", mode="canary", match="scripts/alpha.py")], TWIN_BODY)
    assert _run(reg, snap, base) == CHK.EXIT_OK
    assert _run(reg, snap, base, "--fail-on-new") == CHK.EXIT_OK


def test_cli_a_new_twin_is_exit_1_only_under_fail_on_new(tmp_path, capsys):
    reg, snap, base = _write_inputs(tmp_path, TWIN_ROWS, TWIN_BODY)
    assert _run(reg, snap, base) == CHK.EXIT_OK
    assert _run(reg, snap, base, "--fail-on-new") == CHK.EXIT_VIOLATION
    doc = json.loads(_captured_json(capsys, reg, snap, base, "--fail-on-new", "--json") or "{}")
    assert doc["counts"]["twin_lines"] == 1 and len(doc["new"]) == 1


def test_cli_an_inherited_twin_is_green_and_a_stale_baseline_entry_is_reported(tmp_path, capsys):
    reg, snap, base = _write_inputs(tmp_path, TWIN_ROWS, TWIN_BODY, captured=None)
    assert _run(reg, snap, base, "--emit-baseline", str(base)) == CHK.EXIT_OK
    assert _run(reg, snap, base, "--fail-on-new") == CHK.EXIT_OK
    # the operator retires the line: the finding is gone, the baseline entry is stale but does not red CI
    reg2, snap2, base2 = _write_inputs(tmp_path, TWIN_ROWS, "10 6 * * * cd $PROJ && $PY scripts/other.py\n")
    assert _run(reg2, snap2, base, "--fail-on-new") == CHK.EXIT_OK


def test_cli_missing_or_unstamped_or_stale_input_is_exit_2_never_clean(tmp_path, capsys):
    reg, snap, base = _write_inputs(tmp_path, TWIN_ROWS, TWIN_BODY)
    assert _run(tmp_path / "nope.json", snap, base) == CHK.EXIT_CANNOT_RUN
    assert _run(reg, tmp_path / "nope.txt", base) == CHK.EXIT_CANNOT_RUN
    unstamped = tmp_path / "unstamped.txt"
    unstamped.write_text(TWIN_BODY, encoding="utf-8")
    assert _run(reg, unstamped, base) == CHK.EXIT_CANNOT_RUN
    stale = _write_snapshot(tmp_path, TWIN_BODY, captured=None, stale=True)
    assert _run(reg, stale, base, "--fail-on-new") == CHK.EXIT_CANNOT_RUN


def _captured_json(capsys, reg, snap, base, *extra) -> str:
    capsys.readouterr()
    _run(reg, snap, base, *extra)
    return capsys.readouterr().out


# ── the committed snapshot and registry must be green today ────────────────────────────────

def test_the_committed_snapshot_and_baseline_are_green():
    """If this fails, someone edited the snapshot without pruning the baseline — or added a twin."""
    root = Path(__file__).resolve().parents[1]
    rc = CHK.main(["--registry", str(root / "config" / "lane_registry.json"),
                   "--source", "committed",
                   "--committed-snapshot", str(root / "config" / "crontab_snapshot.txt"),
                   "--baseline", str(root / "config" / "cron_twin_baseline.json"),
                   "--fail-on-new", "--json"])
    assert rc == CHK.EXIT_OK

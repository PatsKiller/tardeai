"""INC-20261014-SPCX resume packet and double-run fix (2026-10-22).

Pins the two operator scripts in docs/ops/packets/incident-spcx-resume-20261022/ (an agent prepared them and never
ran them), the registry truth for the paused lines, and the five armed effect keys. Hermetic: the scripts' line
transforms run on a synthetic crontab in tmp_path; no crontab, broker, ledger or database is touched.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKT = ROOT / "docs" / "ops" / "packets" / "incident-spcx-resume-20261022"
RESUME = PKT / "resume-operator.sh"
DOUBLE = PKT / "double-run-operator.sh"
REG = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}
KEYS = json.loads((ROOT / "config" / "n8n_effect_keys.json").read_text(encoding="utf-8"))["lanes"]

PFX = re.compile(r"^# PAUSED 2026-10-1[45] schwab-app-deactivated \(incident SPCX(, grant 0f9de907)?\) ")


def _heredoc(text: str, tag: str) -> str:
    m = re.search(r"<<'%s'\n(.*?)\n%s\n" % (tag, tag), text, re.S)
    assert m, tag
    return m.group(1)


@pytest.mark.parametrize("script", [RESUME, DOUBLE])
def test_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0


# ── resume-operator.sh ───────────────────────────────────────────────────────────────────────────────────────


def _targets():
    return [tuple(l.split("\t", 1)) for l in _heredoc(RESUME.read_text(), "TARGETS").splitlines()]


def test_resume_order_and_scope():
    t = _targets()
    steps = [s for s, _ in t]
    assert steps == ["a", "a", "a", "b", "b", "c", "d", "e", "f", "f", "g", "h", "i", "retire214"]
    text = "\n".join(line for _, line in t)
    for kept in ("defense_execution", "options_lifecycle_run", "options_lifecycle_digest", "coder_dispatch"):
        assert kept not in text, kept
    for s, line in t:
        if s != "retire214":
            assert PFX.match(line), line[:80]
    # stream daemon is last; positions trio first
    assert "schwab_stream_daemon.py" in t[-2][1]
    assert [l for s, l in t if s == "a"][0].count("schwab_position_sync.py --apply") == 1


def test_resume_preconditions_backup_confirmation_and_rollback():
    src = RESUME.read_text()
    for needle in ('EXPECT_HOST="ms01-openclaw"', 'EXPECT_USER="johnclaw"', "read_only", 'lock_state(broker="schwab")',
                   'crontab.bak-$STAMP', 'Type RESUME', 'ROLLBACK: crontab', "--days 10 --dry-run",
                   "grok_stop_review.py --plan", "cmp -s -", "grep -qxF"):
        assert needle in src, needle
    assert src.count("read -r -p") == 1  # one confirmation, after every dry run
    assert not re.search(r"(^|[;&|(]\s*|\s)rm\s", src, re.M)  # never deletes (backup kept)
    assert "crontab -r" not in src


def test_grok_resumes_by_default_only_when_the_fix_is_served():
    src = RESUME.read_text()
    assert "RESUME_GROK" not in src
    assert "GROK_MARKER='PROCESS_ID = \"grok_stop_review\"'" in src
    assert 'grep -qxF "$GROK_MARKER" "$CUR/scripts/grok_stop_review.py"' in src
    assert "--only h" in src
    # the marker the script greps for is the exact line in the repo's (fixed) script
    assert 'PROCESS_ID = "grok_stop_review"' in (ROOT / "scripts" / "grok_stop_review.py").read_text().splitlines()


def _synthetic_crontab(lines):
    pad = ["SHELL=/bin/bash", "PROJ=/x", "PY=/y", "# keep", "0 1 * * * echo other"]
    keep = [
        "# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) */10 9-16 * * 1-5 cd /x && flock -n /tmp/defense_fills.lock true",
        "# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) */20 9-16 * * 1-5 cd /x && flock -n /tmp/options_lifecycle.lock true",
        "# PAUSED 2026-10-14 WS7-02 coder-agent autolaunch (grant a67b8f21) 0 9-18/3 * * 1-5 flock -n /tmp/tradeai_coder_dispatch.lock true",
    ]
    return "\n".join(pad + lines + keep) + "\n"


def test_resume_transform_unpauses_exactly_each_line(tmp_path):
    t = _targets()
    (tmp_path / "targets.tsv").write_text("\n".join(f"{s}\t{l}" for s, l in t) + "\n")
    (tmp_path / "edit.py").write_text(_heredoc(RESUME.read_text(), "PYEOF") + "\n")
    live = tmp_path / "crontab"
    live.write_text(_synthetic_crontab([l for _, l in t]))
    cur = live
    for step in dict.fromkeys(s for s, _ in t):
        out = tmp_path / f"after.{step}"
        r = subprocess.run([sys.executable, str(tmp_path / "edit.py"), str(cur), str(tmp_path / "targets.tsv"), step,
                            str(out)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cur = out
    final = cur.read_text().splitlines()
    for s, line in t:
        if s == "retire214":
            assert any(l.startswith("# RETIRED 2026-10-22 superseded-by drive-syncs-hourly") and l.endswith(line)
                       for l in final)
        else:
            assert PFX.sub("", line) in final
            assert line not in final
    # kept lines untouched
    assert sum(1 for l in final if l.startswith("# PAUSED")) == 3


def test_resume_transform_refuses_when_the_text_differs(tmp_path):
    t = _targets()
    (tmp_path / "targets.tsv").write_text("\n".join(f"{s}\t{l}" for s, l in t) + "\n")
    (tmp_path / "edit.py").write_text(_heredoc(RESUME.read_text(), "PYEOF") + "\n")
    live = tmp_path / "crontab"
    live.write_text(_synthetic_crontab([l.replace("--apply", "--apply ") for _, l in t]))
    r = subprocess.run([sys.executable, str(tmp_path / "edit.py"), str(live), str(tmp_path / "targets.tsv"), "a",
                        str(tmp_path / "o")], capture_output=True, text=True)
    assert r.returncode != 0 and "REFUSED" in (r.stderr + r.stdout)


# ── double-run-operator.sh ───────────────────────────────────────────────────────────────────────────────────


def _plan():
    return [l.split("\t") for l in _heredoc(DOUBLE.read_text(), "PLAN").splitlines()]


PREFIX = "# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) "


def test_double_run_plan_comments_only_the_three_proven_lanes():
    plan = _plan()
    assert {lane for lane, _ in plan} == {"sync-social-to-intelligence", "materialize-watchlist-strategy-cards",
                                          "hermes-discovery-scorecard"}
    src = DOUBLE.read_text()
    assert f"PREFIX='{PREFIX}'" in src
    for lane, old in plan:
        assert not old.startswith("#")
        assert ROWS[lane]["scheduler"]["match"] in old
        assert ROWS[lane]["dispatch"]["mode"] == "live"  # n8n keeps running it once cron is off


def test_double_run_transform(tmp_path):
    (tmp_path / "plan.tsv").write_text("\n".join("\t".join(r) for r in _plan()) + "\n")
    # the second PYEOF heredoc (edit.py) is the transform; the first is the ledger check
    blocks = re.findall(r"<<'PYEOF'\n(.*?)\nPYEOF\n", DOUBLE.read_text(), re.S)
    (tmp_path / "edit.py").write_text(blocks[1] + "\n")
    live = tmp_path / "crontab"
    live.write_text("SHELL=/bin/bash\n" + "\n".join(old for _, old in _plan()) + "\n0 1 * * * true\n")
    r = subprocess.run([sys.executable, str(tmp_path / "edit.py"), str(live), str(tmp_path / "plan.tsv"), PREFIX,
                        str(tmp_path / "out")], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "3", r.stderr
    out = (tmp_path / "out").read_text().splitlines()
    for _, old in _plan():
        assert PREFIX + old in out and old not in out
    assert "0 1 * * * true" in out


def test_no_effect_keys_are_added_by_this_pr():
    """The canary effect-key process (tests/test_canary_effect_keys_20261015.py) forbids arming keys at merge and keying
    overwrite-only lanes, so the double-run fix here is crontab-only for the lanes n8n has proven."""
    for lane in ("sync-social-to-intelligence", "materialize-watchlist-strategy-cards", "hermes-discovery-scorecard",
                 "opening-intelligence-render", "job-coverage-monitor", "classify-instruments", "finviz-enrichment",
                 "finviz-sector-research"):
        assert lane not in KEYS, lane


def test_double_run_script_guards():
    src = DOUBLE.read_text()
    for needle in ("mode=ro", "PRAGMA query_only=1", "live:RUN_DONE", ">= 3", "Type APPLY", "crontab.bak-$STAMP",
                   "REFUSED: the crontab changed since the preview", "grep -qxF"):
        assert needle in src, needle
    assert src.count("read -r -p") == 1
    assert "crontab -r" not in src and not re.search(r"(^|[;&|(]\s*|\s)rm\s", src, re.M)
    assert "set-owner" not in src and "TRADEAI_EFFECT_CLAIM=" not in src.split("PLAN\n")[1]


# ── registry truth ───────────────────────────────────────────────────────────────────────────────────────────

PAUSED_ROWS = {
    "schwab-stream-daemon", "sync-basis-from-broker", "audit-position-basis", "grok-stop-review", "coder-dispatch",
    "stop-drift-alert", "options-chain-snapshot", "defense-execution", "options-lifecycle-run",
    "options-lifecycle-digest", "schwab-econfirm-reconcile", "broker-stop-reconcile", "sweep-schwab-instruments",
    "positions-shadow-diff", "positions-proof-daily",
}
#: Resumed by the operator on 2026-10-22 (resume-operator.sh, typed RESUME); kept paused: defense, options lifecycle x2,
#: coder dispatch.
RESUMED_20261022 = PAUSED_ROWS - {"coder-dispatch", "defense-execution", "options-lifecycle-run", "options-lifecycle-digest"}
#: Disabled timers stay ACTIVE + DISABLED_UNRULED + operator_decision_pending (an operator ruling turns them off;
#: tests/test_expected_services_lane_states_20261008.py). This PR does not flip them.
STALE_TIMERS = {"db-retention-timer", "systemd-tmpfiles-clean", "tradeai-agent-runtime-atlas",
                "tradeai-agent-runtime-concierge", "tradeai-agent-runtime-hermes", "tradeai-agent-runtime-pulse",
                "tradeai-iris-taxonomy"}


def test_paused_lines_are_paused_rows():
    for lid in STALE_TIMERS:
        assert ROWS[lid]["status"] == "DISABLED_UNRULED" and ROWS[lid]["operator_decision_pending"] is True, lid
    # 2026-10-22: the operator ran resume-operator.sh (typed RESUME) and approved "approve all" item D (verbatim:
    # "yes i approve 'approve all' (A–L)"), so the resumed rows are ACTIVE since 2026-10-22; the held four stay PAUSED.
    for lid in PAUSED_ROWS:
        r = ROWS[lid]
        if lid in RESUMED_20261022:
            assert r["state"] == "ACTIVE" and r["state_since"] == "2026-10-22", lid
            assert "approve all" in r["state_reason"] and "resume-operator.sh" in r["state_reason"], lid
        else:
            assert r["state"] == "PAUSED", lid
            assert r["state_since"] and r["state_reason"] and r.get("review_by") == "2026-10-29", lid
        assert "generated_by" not in r, lid  # adopted: the generator must not reset the state
    for lid in PAUSED_ROWS:
        assert ROWS[lid]["incident"] == "INC-20261014-SPCX"


def test_l214_has_a_retired_row():
    r = ROWS["sync-docs-to-drive"]
    assert r["state"] == "RETIRED" and r["superseded_by"] == "drive-syncs-hourly"
    assert r["scheduler"]["match"] == "scripts/sync-docs-to-drive.py"


def test_live_list_mismatches_are_documented():
    assert "dry_run" in ROWS["maturity-remeasure"]["live_list_note"]
    for slot in ("0000", "0600", "0800", "1800"):
        r = ROWS[f"release-train-request-{slot}"]
        assert r["state"] == "NEVER_SCHEDULED" and "H.0" in r["live_list_note"]

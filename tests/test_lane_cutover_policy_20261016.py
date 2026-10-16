"""AGENTS.md 12.0.0 §23.25 gate alignment (operator approval 2026-10-16).

"change the sender gate to direct-senders-only and lift KEEP_ON_CRON/stay_on_cron and wrapper-token refusals for
§23.25-approved families; broker/order/secret/daemon/os markers, F07 and registry_systemd stay refused; hold
defense-execution, options-lifecycle-run, coder-dispatch, n8n-workflow-drift-check; P1 lanes last with cron kept one
trading day after proof".

Pins: the committed policy (config/lane_cutover_policy.json) agrees with the disposition sheet; exactly the reviewed
49 ACTIVE lanes become eligible on the real registry; the 4 holds refuse; hard tokens, F07 and systemd still refuse;
a direct sender is an error; p1_last lanes plan last and keep cron one trading day after the first live RUN_DONE; a
sender's cron line must carry the effect-claim wrapper before canary. Hermetic: tmp_path ledgers and scripts.
"""
from __future__ import annotations

import copy
import csv
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_cutover_wave as W  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

POLICY = json.loads((ROOT / "config" / "lane_cutover_policy.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}
ARGV = {k: " ".join(v.get("command") or []) for k, v in LD.load_run_allowlist_entries().items()}

#: The reviewed list (Agent A simulation 2026-10-16, ~/n8n-maturity-verification/gate_alignment_sim_rows_20261016.json
#: minus the 4 holds). Changing it is a reviewed edit, never a side effect.
NEWLY_ELIGIBLE_ACTIVE = sorted("""
active-trader-micro-recorder active-trader-micro-recorder-premarket advice-digest cio-entry-state
cio-opportunity-curator cio-wake-dispatch claude-escalation-handler crontab-snapshot-for-health-agent
deepseek-balance-snapshot dof-rescan-tickets dof-run-pipeline drive-syncs-hourly eod-open-trade-alert event-detector
generate-max-hold-exit-proposals hermes-watchlist-scorer incident-notifier ingest-tos-watchlists
journal-annotation-reminder llm-spend-report-daily llm-spend-report-monthly llm-spend-report-weekly
morning-brief-0730 n8n-failure-diagnosis n8n-incident-fanin n8n-pilot-dispatch n8n-research-intake-consumer
n8n-siem-bridge news-ingestion news-ingestion-tail options-intent-matcher options-iv-snapshot options-tick
portfolio-server-watchdog process-reaper research-scheduler rotation-autopilot run-ensemble-worker
run-governed-symbol-thesis-acquisition run-options-monitor screener-go-alerts send-telegram-proposal-alert
sync-memory-to-drive telegram-smart-alerts tmp-scratch-cleanup topic-research-synthesizer trade-close-llm-analyzer-structured
trade-integrity-audit watchlist-proposal-bridge
""".split())
HOLDS = {"defense-execution", "options-lifecycle-run", "coder-dispatch", "n8n-workflow-drift-check"}
P1 = {"incident-notifier", "telegram-smart-alerts", "eod-open-trade-alert", "morning-brief-0730",
      "send-telegram-proposal-alert", "advice-digest", "portfolio-server-watchdog", "process-reaper",
      "rotation-autopilot", "watchlist-proposal-bridge", "options-intent-matcher", "options-tick", "run-options-monitor",
      "generate-max-hold-exit-proposals", "active-trader-micro-recorder", "active-trader-micro-recorder-premarket"}


def _elig(row, policy=None):
    return LD.dispatch_eligible(row, allowlist_argv=ARGV, cutover_policy=policy)


# ── the committed policy ──────────────────────────────────────────────────────────────────────

def test_policy_shape_holds_and_p1_are_the_approved_sets():
    assert POLICY["schema"] == "LaneCutoverPolicy@v1"
    assert set(POLICY["holds"]) == HOLDS
    assert all(v.startswith("operator_hold_20261016") for v in POLICY["holds"].values())
    assert set(POLICY["p1_last"]) == P1 and POLICY["cron_overlap_trading_days"] == 1
    assert all(lane in ROWS for lane in HOLDS | P1)
    assert "F07" not in set(POLICY["families"].values()) or all(
        not LD.cutover_directive_lane(ROWS[k]) for k, v in POLICY["families"].items() if v == "F07" and k in ROWS)


def test_families_agree_with_the_disposition_sheet():
    by: dict[str, set] = {}
    with open(ROOT / "docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["lane_id"] and r["family_id"]:
                by.setdefault(r["lane_id"], set()).add(r["family_id"])
    for lane, fam in POLICY["families"].items():
        if lane in by:
            assert by[lane] == {fam}, (lane, fam, by[lane])
        else:
            assert lane in POLICY["family_notes"], lane  # derived (family-slot runner) or assigned, with its note
    for lane, fams in by.items():
        if len(fams) > 1:
            assert lane not in POLICY["families"], lane  # ambiguous family: fail closed


def test_loader_fails_closed(tmp_path):
    for content in ("", "not json", "[]", '{"families": "x", "holds": [1]}'):
        p = tmp_path / "p.json"
        p.write_text(content, encoding="utf-8")
        LD._CUTOVER_CACHE.pop(str(p), None)
        pol = LD.load_cutover_policy(p)
        assert pol["families"] == {} and pol["holds"] == {} and pol["p1_last"] == frozenset()
    missing = tmp_path / "nope.json"
    assert LD.load_cutover_policy(missing)["families"] == {}


# ── the real registry: exactly the reviewed 49 ────────────────────────────────────────────────

def test_exactly_the_reviewed_49_active_lanes_become_eligible():
    newly = sorted(lid for lid, r in ROWS.items()
                   if r.get("state") == "ACTIVE" and not _elig(r, LD.EMPTY_CUTOVER_POLICY)[0] and _elig(r)[0])
    assert newly == NEWLY_ELIGIBLE_ACTIVE
    assert len(newly) == 49
    for lid in newly:
        assert _elig(ROWS[lid])[1].startswith("eligible:cutover_directive_23_25:"), lid


def test_no_previously_eligible_lane_is_refused_now():
    flipped = [lid for lid, r in ROWS.items()
               if _elig(r, LD.EMPTY_CUTOVER_POLICY)[0] and not _elig(r)[0]]
    assert flipped == []


@pytest.mark.parametrize("lane", sorted(HOLDS))
def test_held_lanes_refuse(lane):
    assert _elig(ROWS[lane]) == (False, "operator_hold:operator_hold_20261016")
    assert LD.dispatchable(dict(ROWS[lane], dispatch={"mode": "live"})) is False


@pytest.mark.parametrize("lane", ["positions-sync", "broker-stop-reconcile", "stop-health-check",
                                  "schwab-position-sync", "alpaca-stop-manager-rth", "paper-execution-sweep",
                                  "run-protection-pipeline-at-30-20", "sweep-schwab-instruments"])
def test_hard_token_rows_stay_refused(lane):
    ok, why = _elig(ROWS[lane])
    assert ok is False and why.startswith("forbidden_token:"), (lane, why)


def test_systemd_rows_stay_refused():
    systemd = [r for r in ROWS.values() if isinstance(r.get("scheduler"), dict) and r["scheduler"].get("kind") == "systemd"]
    assert len(systemd) > 100
    for r in systemd:
        assert not LD.cutover_directive_lane(r), r["lane_id"]


# ── synthetic rows: the rule itself ───────────────────────────────────────────────────────────

def _row(lane="x-lane", **kw):
    row = {"lane_id": lane, "state": "ACTIVE", "recommendation": "KEEP_ON_CRON",
           "stay_on_cron": {"class": "pipeline_excluded_gate", "token": "market_day_gate.sh"},
           "scheduler": {"kind": "cron", "expression": "*/5 * * * *", "match": "scripts/x_lane.py",
                         "command_text": "bash scripts/market_day_gate.sh $PY scripts/x_lane.py --send"}}
    row.update(kw)
    return row


def _pol(fam="F36", **kw):
    pol = copy.deepcopy(LD.EMPTY_CUTOVER_POLICY)
    pol["families"] = {"x-lane": fam}
    pol.update(kw)
    return pol


def test_directive_lifts_markers_and_soft_tokens_only():
    assert LD.dispatch_eligible(_row(), cutover_policy=LD.EMPTY_CUTOVER_POLICY) == (False, "stay_on_cron")
    ok, why = LD.dispatch_eligible(_row(), cutover_policy=_pol())
    assert ok and why == "eligible:cutover_directive_23_25:keep_on_cron,market_day_gate.sh,send,stay_on_cron"
    guard = _row(scheduler={"kind": "cron", "match": "x", "command_text": "bash scripts/llm_priority_guard.sh $PY x.py"})
    assert LD.dispatch_eligible(guard, cutover_policy=_pol())[0] is True


@pytest.mark.parametrize("extra", [" && $PY scripts/positions_sync.py", " && bash scripts/sm-render.sh",
                                   " --submit", " && $PY scripts/broker_stop_reconcile.py", " --daemon x secret"])
def test_directive_never_lifts_hard_tokens(extra):
    row = _row(scheduler={"kind": "cron", "match": "x", "command_text": "$PY scripts/x_lane.py" + extra})
    ok, why = LD.dispatch_eligible(row, cutover_policy=_pol())
    assert ok is False and why.startswith("forbidden_token:"), why


def test_f07_unknown_family_and_systemd_keep_the_old_rule():
    assert LD.dispatch_eligible(_row(), cutover_policy=_pol("F07")) == (False, "stay_on_cron")
    assert LD.dispatch_eligible(_row(lane="other"), cutover_policy=_pol()) == (False, "stay_on_cron")
    sysd = _row(scheduler={"kind": "systemd", "match": "x.service"})
    assert LD.dispatch_eligible(sysd, cutover_policy=_pol()) == (False, "stay_on_cron")
    assert LD.dispatch_eligible(_row(exec_start="/usr/bin/x"), cutover_policy=_pol()) == (False, "stay_on_cron")


def test_hold_beats_everything():
    pol = _pol(holds={"x-lane": "operator_hold_20261016: test"})
    assert LD.dispatch_eligible(_row(), cutover_policy=pol) == (False, "operator_hold:operator_hold_20261016")


def test_rationalization_keep_on_cron_is_lifted_too():
    row = _row(rationalization={"recommendation": "KEEP_ON_CRON"})
    row.pop("stay_on_cron")
    assert LD.dispatch_eligible(row, cutover_policy=LD.EMPTY_CUTOVER_POLICY) == (False, "keep_on_cron")
    assert LD.dispatch_eligible(row, cutover_policy=_pol())[0] is True


# ── sender gate: direct senders only ──────────────────────────────────────────────────────────

def _sender_case(tmp_path, monkeypatch, body):
    script = tmp_path / "x_lane.py"
    script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(LD, "load_cutover_policy", lambda path=None: _pol())
    row = _row()
    entry = {"lane_id": "x-lane", "command": ["$PY", str(script)]}
    return LD.cutover_direct_sender_errors(row, entry)


def test_direct_sender_is_an_error(tmp_path, monkeypatch):
    errs = _sender_case(tmp_path, monkeypatch, "import smtplib\nsmtplib.SMTP('h').sendmail('a', 'b', 'c')\n")
    assert errs and "direct sender" in errs[0]


def test_chokepoint_sender_is_clean(tmp_path, monkeypatch):
    errs = _sender_case(tmp_path, monkeypatch, "from scripts.telegram_alert import send_telegram\nsend_telegram('x')\n")
    assert errs == []


def test_no_entry_or_no_sender_token_is_not_applicable(monkeypatch):
    monkeypatch.setattr(LD, "load_cutover_policy", lambda path=None: _pol())
    assert LD.cutover_direct_sender_errors(_row(), None) == []  # no allowlist entry: onboarding audit covers it
    quiet = _row(scheduler={"kind": "cron", "match": "x", "command_text": "$PY scripts/x_lane.py"})
    assert LD.cutover_direct_sender_errors(quiet, {"command": ["$PY", "scripts/x_lane.py"]}) == []


# ── P1 ordering and the cron overlap ──────────────────────────────────────────────────────────

def _ledger(tmp_path, rows):
    p = tmp_path / "ledger.sqlite"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
              "finished_at TEXT, exit_code INT, receipt_json TEXT)")
    c.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    return p


def test_p1_cron_kept_one_trading_day_after_first_live_run_done(tmp_path):
    pol = {"p1_last": frozenset({"incident-notifier"}), "cron_overlap_trading_days": 1}
    led = _ledger(tmp_path, [("r1", "incident-notifier", "live", "RUN_DONE", "2026-10-16T14:00:00+00:00",
                              "2026-10-16T14:00:05+00:00", 0, "{}")])
    fri, sat, mon = date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 19)
    assert W.p1_overlap_problems(["incident-notifier"], pol, ledger=led, today=fri)
    assert W.p1_overlap_problems(["incident-notifier"], pol, ledger=led, today=sat)  # weekend is not a trading day
    assert W.p1_overlap_problems(["incident-notifier"], pol, ledger=led, today=mon) == []
    assert W.p1_overlap_problems(["finviz-enrichment"], pol, ledger=led, today=fri) == []  # not P1


def test_p1_without_a_live_run_done_is_refused(tmp_path):
    pol = {"p1_last": frozenset({"options-tick"}), "cron_overlap_trading_days": 1}
    led = _ledger(tmp_path, [("r1", "options-tick", "live", "RUN_FAILED", "2026-10-16T14:00:00+00:00", None, 1, "{}")])
    probs = W.p1_overlap_problems(["options-tick"], pol, ledger=led, today=date(2026, 10, 20))
    assert probs and "no live n8n RUN_DONE" in probs[0]


def test_comment_cron_refuses_a_p1_lane_before_its_overlap(tmp_path):
    row = ROWS["incident-notifier"]
    line = f"{row['scheduler']['expression']} cd $PROJ && $PY {row['scheduler']['match']} >> logs/x.log 2>&1"
    ct = tmp_path / "crontab.txt"
    ct.write_text(line + "\n", encoding="utf-8")
    led = _ledger(tmp_path, [])
    rc = W.comment_cron(["incident-notifier"], ROOT, apply=True, backup_dir=tmp_path / "bk", date="2026-10-16",
                        crontab_path=str(ct), ledger=led, today=date(2026, 10, 16))
    assert any("p1_last" in p for p in rc["problems"]) and rc["backup"] is None and rc["read_back_ok"] is None


def _plan(lane, line):
    disp = {"lane_id": lane, "family_id": POLICY["families"].get(lane, ""), "source": "crontab",
            "disposition": "MIGRATE_N8N"}
    return W.plan_lane(lane, disp, reg_rows=ROWS, entries={}, contracts={}, effect_keys={}, crontab=line + "\n",
                       wave="CWT", policy=LD.load_cutover_policy())


def test_plan_puts_p1_last_and_requires_the_effect_claim_wrapper_for_senders():
    row = ROWS["incident-notifier"]
    line = f"{row['scheduler']['expression']} cd $PROJ && flock -n /tmp/x.lock $PY {row['scheduler']['match']}"
    v = _plan("incident-notifier", line)
    assert v["cutover_tier"] == "p1_last"
    assert any(r.startswith("p1_last:") for r in v["reasons"])
    assert any(r.startswith("sender_cron_not_effect_claimed") for r in v["reasons"])
    wrapped = line.replace("flock", "TRADEAI_EFFECT_CLAIM=incident-notifier bash scripts/effect_claim_cron.sh flock")
    assert not any(r.startswith("sender_cron_not_effect_claimed") for r in _plan("incident-notifier", wrapped)["reasons"])


def test_is_sender_lane():
    row = {"lane_id": "x"}
    assert W.is_sender_lane({"family_id": "F10"}, row, {}, "")
    assert W.is_sender_lane({"family_id": "F36"}, row, {}, "$PY x.py --telegram")
    assert W.is_sender_lane({"family_id": "F36"}, row, {"x": {"effects": ["send"]}}, "")
    assert not W.is_sender_lane({"family_id": "F36"}, row, {}, "$PY x.py --apply")

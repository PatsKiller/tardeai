"""LQ-20261107-1286 — the CIO overnight brief is registered as an n8n lane.

The operator's cadence (relayed in WORK-QUEUE 2026-11-08): weekends every 6 h; trading days
06:00, 09:00, 12:00, 16:15 and 20:00 ET; plus on market_event. One fire carries one argv, so this
module pins the four config files to each other and then EMULATES both declared argvs against a
throwaway state root: --dry-run must write nothing, and the live form must write the artifact and
no lane receipt. It also pins the two honest gaps — the market_event trigger is inert at a live
stage (EVENT_MODES), and expected_output is declared but not armed because the receipt's
empty_reason is still a free-text sentence.

Every fixture is synthetic: ZZ-prefixed symbols, invented prices, no database, no provider, no
network, no model.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.cio_overnight_brief as B  # noqa: E402
from scripts.lib.lane_dispatch import parse_dispatch_block  # noqa: E402
from scripts.lib.lane_registry import validate_row  # noqa: E402
from scripts.lib.n8n_output_verdict import validate_expected_output  # noqa: E402

LID = "cio-overnight-brief"
SCRIPT = "scripts/cio_overnight_brief.py"
ARTIFACT = "data/runtime/cio_overnight_brief/latest.json"
CONTRACT_ID = "cio-overnight-brief"

#: The registration week, Monday 2026-11-09 00:00 ET through the following Monday (exclusive).
_WEEK = datetime(2026, 11, 9)


# ── config readers ──────────────────────────────────────────────────────────────────────────


def registry() -> dict:
    return json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))


def allowlist() -> dict:
    return json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))


def contracts() -> dict:
    return json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))


def row() -> dict:
    return next(r for r in registry()["lanes"] if r["lane_id"] == LID)


def entry() -> dict:
    return next(e for e in allowlist()["lanes"] if e["lane_id"] == LID)


def contract() -> dict:
    return next(c for c in contracts()["contracts"] if c["id"] == CONTRACT_ID)


def script_source() -> str:
    return (ROOT / SCRIPT).read_text(encoding="utf-8")


# ── a minimal cron expander (minute/hour/dom/month/dow, lists, ranges, */n) ─────────────────


def _match_field(spec: str, value: int) -> bool:
    for part in spec.split(","):
        if part == "*":
            return True
        if part.startswith("*/"):
            if value % int(part[2:]) == 0:
                return True
        elif "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            if lo <= value <= hi:
                return True
        elif int(part) == value:
            return True
    return False


def _match(expr: str, when: datetime) -> bool:
    minute, hour, dom, month, dow = expr.split()
    cron_dow = (when.weekday() + 1) % 7  # cron: 0=Sunday, Python: 0=Monday
    return (
        _match_field(minute, when.minute)
        and _match_field(hour, when.hour)
        and _match_field(dom, when.day)
        and _match_field(month, when.month)
        and _match_field(dow, cron_dow)
    )


def fires() -> list[datetime]:
    exprs = row()["dispatch"]["cron"]
    out = [when for when in (_WEEK + timedelta(minutes=m) for m in range(7 * 24 * 60))
           if any(_match(e, when) for e in exprs)]
    assert len(out) == len(set(out)), "two dispatch expressions fire the same minute"
    return sorted(out)


# ── the registry row ────────────────────────────────────────────────────────────────────────


def test_row_is_a_valid_dispatcher_row_at_canary():
    r = row()
    assert validate_row(r) == []
    assert r["scheduler"]["kind"] == "n8n"
    assert r["scheduler"]["expression"] == "dispatcher"
    assert r["scheduler"]["match"] == SCRIPT
    assert r["scheduler"]["stage"] == "canary"
    assert r["state"] == "ACTIVE"
    assert r["active_days"] == [0, 1, 2, 3, 4, 5, 6]
    assert parse_dispatch_block(r).mode == "live"


def test_the_cadence_is_the_operators_five_weekday_slots_and_every_six_hours_at_weekends():
    got = {when.strftime("%a %H:%M") for when in fires()}
    expected = set()
    for day in ("Mon", "Tue", "Wed", "Thu", "Fri"):
        expected |= {f"{day} 06:00", f"{day} 09:00", f"{day} 12:00", f"{day} 16:15", f"{day} 20:00"}
    for day in ("Sat", "Sun"):
        expected |= {f"{day} 00:00", f"{day} 06:00", f"{day} 12:00", f"{day} 18:00"}
    assert got == expected
    assert len(fires()) == 5 * 5 + 2 * 4 == 33


def test_expected_cadence_hours_is_the_longest_legitimate_gap():
    got = fires()
    week = [w + timedelta(days=7) for w in got]
    seq = got + week
    longest = max(b - a for a, b in zip(seq, seq[1:]))
    assert longest == timedelta(hours=12), "the Sunday 18:00 -> Monday 06:00 gap"
    assert row()["expected_cadence_hours"] * 3600 == longest.total_seconds()


def test_only_one_registry_row_fires_this_script():
    matches = [r["lane_id"] for r in registry()["lanes"]
               if ((r.get("scheduler") or {}).get("match") == SCRIPT)]
    assert matches == [LID], "a second row naming the script would double-schedule it"


def test_the_market_event_trigger_is_declared_and_pinned_inert_at_a_live_stage():
    block = parse_dispatch_block(row())
    assert len(block.triggers) == 1
    t = block.triggers[0]
    assert (t.source, t.lane_id, t.require_verdict) == ("run_done", "market-event-detect", ("produced",))
    assert block.min_interval_s == 1800
    # The operator's "plus on market_event" cannot fire yet: the dispatcher only emits event
    # slots for a dry_run block. If this constant ever changes, the row's note is stale and the
    # operator's trigger becomes live — both need a deliberate edit, so this test fails first.
    from scripts.lib import n8n_due

    assert n8n_due.EVENT_MODES == ("dry_run",)
    assert "declared, not active" in row()["note"]


# ── the allowlist entry ────────────────────────────────────────────────────────────────────


def test_allowlist_entry_is_exactly_the_declared_two_argvs():
    from scripts.n8n_run_executor import validate_entry

    e = entry()
    assert validate_entry(e) is None
    assert e["command"] == ["$PY", SCRIPT]
    assert e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] == ["--apply"]
    assert e["lock"] == "/tmp/cio_overnight_brief.lock"
    assert e["lock_kind"] == "flock"
    assert e["timeout_s"] == 900
    assert e["market_gate"] is False
    assert e["output_signal"] == ARTIFACT
    assert e["output_signal"] == row()["output_signal"]["path"]
    assert e["env_allowlist_mode"] == "report"
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "TRADEAI_STATE_ROOT"):
        assert name in e["env_names"]


def test_no_arg_the_executor_can_pass_spends_a_model_call_the_lane_did_not_register():
    e = entry()
    for argv in (e["dry_run_arg"], e["live_arg"]):
        assert "--llm" not in argv
        # --emulated is an acceptance-run flag, never a scheduled one: it skips the receipt,
        # so a scheduled use would leave the lane's ok_at unadvanced.
        assert "--emulated" not in argv
    assert "--apply" in e["live_arg"] and "--dry-run" in e["dry_run_arg"]


def test_the_lock_is_this_lane_s_alone():
    locks = [x["lock"] for x in allowlist()["lanes"] if x["lane_id"] != LID]
    assert entry()["lock"] not in locks


# ── the health contract ────────────────────────────────────────────────────────────────────


def test_contract_is_reviewed_at_the_row_s_stage_with_a_valid_output_rule():
    c, r = contract(), row()
    assert c["schema"] == "N8nHealthContract@v1"
    assert c["kind"] == "lane" and c["workflow_id"] == "tradeai-dispatcher"
    assert c["status"] == "REVIEWED"
    assert c["stage"] == r["scheduler"]["stage"] == "canary"
    assert c["owner"] == r["owner"] == "cio"
    assert c["purpose"]["business_function"] == "cio"
    assert {edge["name"].split(" (")[0] for edge in c["connects_to"]}  # non-empty
    assert validate_expected_output(c["expected_output"]) == []


def test_contract_baseline_follows_the_timeout_and_the_declared_cadence():
    c, e, r = contract(), entry(), row()
    b = c["baseline"]
    assert b["timeout_s"] == e["timeout_s"]
    assert b["duration_degraded_above_s"] == pytest.approx(0.8 * e["timeout_s"])
    assert b["freshness_degraded_after_h"] == pytest.approx(2 * r["expected_cadence_hours"])
    assert b["freshness_failed_after_h"] == pytest.approx(3 * r["expected_cadence_hours"])


def test_expected_output_is_declared_but_not_armed_while_the_empty_reason_is_free_text():
    c, e = contract(), entry()
    eo = c["expected_output"]
    assert eo["rule"] == "empty_allowed"
    assert eo["empty_allowed_reasons"] == ["no_new_input"]
    assert eo["produced_field"] == "produced_count"
    assert eo["upstream_count_field"] == "summary.held_names"
    # Not armed: arming is the single line "output_receipt": "v2" in the allowlist entry, and it
    # must wait for the script to emit the typed reason, because a sentence cannot be listed in
    # empty_allowed_reasons and an empty night would become a RUN_FAILED.
    assert "output_receipt" not in e
    sentence = "no held name moved more than 3% or carried news since the close"
    assert sentence in script_source()
    assert not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", sentence)


def test_a_research_or_model_outage_is_degradation_not_failure():
    c = contract()
    healthy = {h["check"]: h["text"] for h in c["healthy"]}
    assert "model_optional" in healthy
    flagged = {d["check"] for d in c["degraded"]}
    assert "research_degraded" in flagged
    failed = {f["check"] for f in c["failed"]}
    assert "empty_without_citation" in failed


# ── emulation: both declared argvs against a throwaway state root ──────────────────────────


class _FakeConn:
    def close(self) -> None:  # the run closes it in a finally block
        pass


def holdings_doc() -> dict:
    return {
        "holdings": [
            {"symbol": "ZRKT", "account": "acct_a", "broker_shares": 600, "market_value": 60000, "is_cash": False},
            {"symbol": "ZQUIET", "account": "acct_a", "broker_shares": 100, "market_value": 10000, "is_cash": False},
        ],
        "portfolio_totals": {"broker_market_value_total": 70000.0},
    }


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    """A temp state root and no database: every loader is a stub, so the emulation is hermetic."""
    root = tmp_path / "state"
    (root / "data" / "portfolios" / "state").mkdir(parents=True)
    (root / "data" / "portfolios" / "state" / "holdings.json").write_text(
        json.dumps(holdings_doc()), encoding="utf-8"
    )
    monkeypatch.setattr(B, "connect", lambda: _FakeConn())
    for name in (
        "load_quotes",
        "load_news",
        "load_filings",
        "load_stops",
        "load_daily_bars",
        "load_cio_decisions",
        "load_risk_tier",
        "load_positions_current",
        "load_calendar",
        "load_market_risk",
        "load_reentry",
    ):
        monkeypatch.setattr(B, name, lambda *a, **k: {})
    return root


def test_the_dry_run_argv_writes_nothing_and_calls_no_model(state_root, capsys):
    rc = B.main(["--dry-run", "--state-root", str(state_root)])
    assert rc == 0
    assert not (state_root / "data" / "runtime" / "cio_overnight_brief").exists()
    assert not (state_root / "data" / "runtime" / "cio-overnight-brief_last.json").exists()
    assert "DRY-RUN" in capsys.readouterr().out


def test_the_live_argv_emulated_writes_the_artifact_and_no_lane_receipt(state_root, tmp_path):
    out = tmp_path / "out"
    # --no-research --no-llm keep the emulation free and offline; --emulated keeps it out of the
    # scheduled lane's receipt. The scheduled argv is plain --apply (allowlist live_arg).
    rc = B.main(
        ["--apply", "--no-research", "--no-llm", "--emulated", "--state-root", str(state_root), "--out-dir", str(out)]
    )
    assert rc == 0
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(latest["as_of"]).astimezone(B.ET)
    dated = json.loads((out / f"{as_of.date().isoformat()}.json").read_text(encoding="utf-8"))
    assert latest["lane_id"] == LID and latest["advisory_only"] is True
    assert latest["generated_at"] and latest["run_id"] == dated["run_id"]
    assert latest["counts"]["held_names"] == 2
    assert list(out.glob("*.tmp")) == []
    # An acceptance run must never advance the scheduled lane: no receipt outside --out-dir.
    assert not (state_root / "data" / "runtime" / "cio-overnight-brief_last.json").exists()

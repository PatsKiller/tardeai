"""Canary wave 1b 2026-10-14 (AGENTS.md §23.11 / §23.12 / §23.18 (c)) — 3 tier-A shadow cron rows move to canary.

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "scripts/news_to_catalyst.py"]

Stacked on canary-wave-20261014 (PR #1729, 11 lanes) under the same operator ruling (2026-10-14 ~11:05 ET: cut over
once the defect is fixed, the n8n dry run passes, the lane's regression tests pass and >= 1 live n8n run lands with
the cron line still present under the shared flock lock; multi-day soaks removed; §23.14 unchanged).

* identity-sweep-stage0 — live_arg ["--apply"]: the cron line's real run (`--all --apply`); the bare command +
  `--dry-run` stays its dry run. The executor's live argv is the cron argv after $PY, under /tmp/identity_sweep.lock.
* news-to-catalyst — the 2026-10-14 13:42:07Z / 17:31:36Z live receipts that were neither cron nor n8n were the watch
  decision refresh workers' per-symbol `news_to_catalyst.py --symbol SYM` (events dimension); fixed here: a --symbol
  run writes no lane receipt. At canary its event triggers are inert (n8n_due.EVENT_MODES is dry_run only), so going
  live adds no event-triggered live run and no run_done chain to research-insight-extractor.
* hermes-research-worker-pool — held 2026-10-14 for "failing on cron (pool_incomplete)": the receipt rule failed every
  idle hour (all lanes skipped on cadence/no_runner); fixed in scripts/hermes_research_worker_pool.py
  (tests/test_research_worker_pool_fix_20261014.py).
* resolve-due-checkpoints, aegis-social-sentiment, hermes-scope-governor, hermes-score-event-feeder stay shadow here:
  their cron lines get `flock -n <lock>` only when the operator installs packet
  ~/n8n-maturity-verification/packets/cron-lock-wrappers-20261014; their canary rows ride the stacked branch
  n8nmat/canary-wave-1c-locks-20261014 (LOCK_GATED there).

Hermetic: repo files only.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_stage_clamp as SC  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
SNAPSHOT = json.loads(
    (ROOT / "docs" / "implementation" / "n8n-maturity" / "data" / "scheduler_snapshot_20261009.json").read_text()
)

#: lane -> (live cron line number on 2026-10-14, flock lock, live_arg)
CANARY_WAVE_1B = {
    "identity-sweep-stage0": (931, "/tmp/identity_sweep.lock", ["--apply"]),
    "news-to-catalyst": (408, "/tmp/news_to_catalyst.lock", []),
    "hermes-research-worker-pool": (693, "/tmp/hermes_worker_pool.lock", []),
}
#: Rows whose cron flock arrives with packet cron-lock-wrappers-20261014: none in 1b (see canary-wave-1c-locks).
LOCK_GATED: frozenset = frozenset()
#: Stay shadow (pinned so a later edit cannot slip one in).
STILL_SHADOW = {
    "hermes-pipeline-health": "cron argv carries --send (forbidden word); needs the operator cron edit dropping --send "
                              "and scheduler.command_text; no dispatcher fire since 2026-10-11",
    "catalyst-momentum-engine-overnight": "7.0.0 sender baseline until the cron line + allowlist switch to "
                                          "scripts/catalyst_momentum_overnight.py; lock_kind safe_flock",
    "resolve-due-checkpoints": "no flock on the cron line until cron-lock-wrappers-20261014 (canary-wave-1c-locks)",
    "aegis-social-sentiment": "no flock on the cron line until cron-lock-wrappers-20261014 (canary-wave-1c-locks)",
    "hermes-scope-governor": "safe_flock.sh only until cron-lock-wrappers-20261014 (canary-wave-1c-locks)",
    "hermes-score-event-feeder": "safe_flock.sh only until cron-lock-wrappers-20261014 (canary-wave-1c-locks)",
}
LANES = sorted(CANARY_WAVE_1B)


def _cron_argv(command_text: str) -> list[str]:
    toks = shlex.split(command_text.split(">>", 1)[0].split(" #", 1)[0])
    return toks[toks.index("$PY"):]


def _cron_env_prefix(command_text: str) -> list[str]:
    """Inline NAME=VALUE assignments the cron line sets before its work command."""
    toks = shlex.split(command_text.split(">>", 1)[0].split(" #", 1)[0])
    return [t for t in toks[: toks.index("$PY")] if "=" in t and t.split("=", 1)[0].isupper()]


@pytest.mark.parametrize("lane", LANES)
def test_row_is_a_canary_cron_row(lane):
    row = ROWS[lane]
    s, d = row["scheduler"], row["dispatch"]
    assert row["state"] == "ACTIVE"
    assert (s["kind"], s["stage"], d["mode"]) == ("cron", "canary", "live")
    assert d["cron"] == [s["expression"]]
    c = row["canary"]
    assert c["wave"] == "canary-wave-1b-20261014" and c["since"] == "2026-10-14"
    assert "operator ruling 2026-10-14" in c["evidence"]
    assert "RUN_DONE" in c["evidence"] and "0 RUN_FAILED" in c["evidence"]
    assert f"L{CANARY_WAVE_1B[lane][0]}" in c["lock_proof"]
    assert "live_arg null" in c["rollback"]
    assert ("MERGE ONLY AFTER the packet is installed" in c["lock_proof"]) is (lane in LOCK_GATED)


@pytest.mark.parametrize("lane", LANES)
def test_lock_is_the_cron_flock_lock_and_live_argv_is_the_cron_argv(lane):
    row, e = ROWS[lane], ALLOW[lane]
    _, lock, live = CANARY_WAVE_1B[lane]
    text = row["scheduler"]["command_text"]
    assert e["lock"] == lock and e["lock_kind"] == "flock" and not lock.endswith(".dryrun")
    assert LD.cron_flock_locks(text) == [lock]
    assert e["live_arg"] == live
    assert e["dry_run_arg"] == ["--dry-run"]
    cmd = list(e["command"])
    env = _cron_env_prefix(text)
    if env:  # the cron line's inline env rides on `env` (the executor has no per-lane env values)
        assert cmd[: 1 + len(env)] == ["env", *env], (lane, cmd, env)
        cmd = cmd[1 + len(env):]
    assert [*cmd, *e["live_arg"]] == _cron_argv(text)


@pytest.mark.parametrize("lane", LANES)
def test_gates_admit_the_canary_shape(lane):
    row, e = ROWS[lane], ALLOW[lane]
    assert LD.dispatch_eligible(row)[0] is True
    assert LD.validate_dispatch_block(row) == []
    assert row["dispatch"]["class"] in LD.R1_ADMITTED_CLASSES
    assert LD.r1_class_admission(row, e) == (True, f"r1_admitted:{row['dispatch']['class']}")
    assert LD.r1_canary_lock_matches(row, e) == (True, "canary_on_cron")
    assert LD.forbidden_text_hits(" ".join([*e["command"], *e["live_arg"]])) == []
    assert SC.clamp_mode(lane, "live", list(ROWS.values()))["effective_mode"] == "live"


def _snapshot_line(lane: str) -> str:
    match = ROWS[lane]["scheduler"]["match"]
    hits = [c["line"] for c in SNAPSHOT["cron_lines"] if match in c["line"] and not c["line"].lstrip().startswith("#")]
    assert len(hits) == 1, (lane, hits)
    return hits[0]


@pytest.mark.parametrize("lane", sorted(set(LANES) - LOCK_GATED))
def test_flocked_lanes_snapshot_line_already_carries_the_lock(lane):
    assert LD.cron_flock_locks(_snapshot_line(lane)) == [CANARY_WAVE_1B[lane][1]]


@pytest.mark.parametrize("lane", sorted(STILL_SHADOW))
def test_still_shadow_lanes_stay_shadow(lane):
    row = ROWS[lane]
    assert row["scheduler"].get("stage") == "shadow" and row["dispatch"]["mode"] == "dry_run", lane
    assert "canary" not in row and ALLOW[lane]["live_arg"] is None, lane


def test_news_to_catalyst_triggers_are_inert_at_canary():
    from scripts.lib import n8n_due as D

    row = ROWS["news-to-catalyst"]
    assert row["dispatch"]["triggers"] and row["dispatch"]["mode"] not in D.EVENT_MODES
    # research-insight-extractor's run_done trigger on news-to-catalyst is a live (cutover) row: inert too.
    rie = ROWS["research-insight-extractor"]
    assert {"source": "run_done", "lane_id": "news-to-catalyst"} in rie["dispatch"]["triggers"]
    assert rie["dispatch"]["mode"] not in D.EVENT_MODES


# ── news_to_catalyst: a per-symbol enrichment call writes no lane receipt ─────────────────────────────


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchall(self):
        if self._sql.lstrip().startswith("SELECT catalyst_type"):
            return []
        return self._rows

    def fetchone(self):
        return None

    def close(self):
        pass


class _Conn:
    def __init__(self):
        self.commits = 0

    def cursor(self):
        return _Cur([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def test_symbol_run_writes_no_lane_receipt_but_the_lane_run_does(tmp_path, monkeypatch):
    import news_to_catalyst as ntc

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(ntc, "_get_conn", lambda: _Conn())
    receipt = tmp_path / "data" / "runtime" / "news-to-catalyst_last.json"
    assert ntc.main(["--symbol", "AAA", "--json"]) == 0
    assert not receipt.exists()
    assert ntc.main([]) == 0
    doc = json.loads(receipt.read_text())
    assert doc["lane_id"] == "news-to-catalyst" and doc["status"] == "ok"


def test_watch_refresh_events_dimension_is_the_symbol_caller():
    """Evidence pin: the per-symbol caller that wrote the 2026-10-14 13:42Z / 17:31Z receipts."""
    src = (ROOT / "scripts" / "watch_decision_refresh.py").read_text(encoding="utf-8")
    assert '"news_to_catalyst.py"),\n                            "--symbol", symbol]' in src

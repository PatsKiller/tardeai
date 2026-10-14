"""catalyst-momentum-engine-overnight: the §23.20 / 7.0.0 sender-gate blocker that lives in the lane's own code.

COVERS = ["scripts/catalyst_momentum_engine.py", "scripts/catalyst_momentum_overnight.py"]

Measured 2026-10-14 (advisory_lane_guard.scan_entry("scripts/catalyst_momentum_engine.py")): the advisory send
(auto_proposal_generator.py send_advisory_alert, scalp_advisory_alert send_telegram bypass_router), the account
reads (account_policy.get_account x3) and the broker client modules (alpaca_paper_adapter, schwab_transport) all
enter the lane's reach through ONE literal: the `--generate-proposals` subprocess `scripts/auto_proposal_generator.py`.
The overnight cron line never passes --generate-proposals, but the scan is path-insensitive, so the shared entry
script stays a sender. Fix: the proposal handoff is injected by main() and the new overnight-only entry
scripts/catalyst_momentum_overnight.py (run_overnight) injects none, so its reach holds no send, account read or
broker module. Switching the lane to that entry is an allowlist + registry + cron line change (cron grant) — not
made here. Hermetic: fake modules and connections, TRADEAI_STATE_ROOT = tmp; no DB, no network, no subprocess.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - required CI has no psycopg2
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("psycopg2 stub"))
    _pg.Error = _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)

import catalyst_momentum_engine as cme  # noqa: E402
from scripts.lib import advisory_lane_guard as G  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402

OVERNIGHT = "scripts/catalyst_momentum_overnight.py"
ENGINE = "scripts/catalyst_momentum_engine.py"


# ── the static reach ────────────────────────────────────────────────────────────────────────────────


def test_overnight_entry_reach_is_market_data_only_and_sends_nothing():
    r = G.scan_entry(OVERNIGHT)
    assert r.problems() == [] and r.market_data_only()
    assert not r.is_sender and r.sends == [] and r.bypass_router == []
    assert not [s for s in r.scanned if "auto_proposal_generator" in s or "proposal_paper_submitter" in s]
    assert f"{ENGINE}:run_overnight" in r.scanned


def test_shared_engine_entry_still_reaches_the_proposal_handoff():
    """Why the lane needs its own entry: the shared script keeps feed #2 for the premarket / swing bands."""
    r = G.scan_entry(ENGINE)
    assert r.is_sender and any("auto_proposal_generator.py" in s for s in r.sends)
    assert any("account_policy.py" in a for a in r.account_reads)


def test_only_the_handoff_names_the_proposal_subprocess():
    assert "auto_proposal_generator.py" in inspect.getsource(cme._proposal_handoff)
    for fn in (cme.run_overnight, cme._guarded_run, cme._run, cme._dry_run):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not names & {"_proposal_handoff", "subprocess", "PY"}, fn.__name__
        assert not [c for c in consts if c.endswith(".py") and "proposal" in c], fn.__name__


def test_overnight_entry_has_no_generate_proposals_flag(monkeypatch):
    monkeypatch.setattr(cme, "_load_env", lambda: None)
    with pytest.raises(SystemExit):
        cme.run_overnight(["--apply", "--generate-proposals"])
    with pytest.raises(SystemExit):
        cme.run_overnight(["--band", "premarket_scalp", "--apply"])


# ── behaviour: same work as `catalyst_momentum_engine.py --band overnight --apply` ─────────────────


class _Cur:
    def execute(self, *a, **k):
        pass

    def close(self):
        pass


class _Conn:
    autocommit = False

    def cursor(self, *a, **k):
        return _Cur()

    def close(self):
        pass


class _RC:
    def __init__(self, n):
        self.rows_written = n


def _boom(*a, **k):
    raise AssertionError("reached the proposal subprocess")


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    cands = [{"symbol": "AAA", "rvol": 9.0, "gap_pct": 4}, {"symbol": "BBB", "rvol": 6.0, "gap_pct": 2}]
    monkeypatch.setitem(sys.modules, "hermes_momentum_candidate_reader",
                        types.SimpleNamespace(get_momentum_candidates=lambda **k: cands))
    sources = lambda sym, q, **k: [{"title": f"{sym} beats", "content": "e", "url": f"https://x/{sym}/{i}"}
                                   for i in range(3)]
    monkeypatch.setitem(sys.modules, "hermes_momentum_catalyst_researcher",
                        types.SimpleNamespace(search_catalyst=sources, classify_catalyst=lambda t: "earnings"))
    monkeypatch.setattr(cme, "_load_env", lambda: None)
    monkeypatch.setattr(cme, "kill_active", lambda: False)
    monkeypatch.setattr(cme, "_search_kwargs", lambda **k: {})
    monkeypatch.setattr(cme.subprocess, "run", _boom)
    import psycopg2

    import lib.writers.hermes_research_writer as hrw

    staged, marker = [], {}
    monkeypatch.setattr(psycopg2, "connect", lambda **k: _Conn())
    monkeypatch.setattr(hrw, "write_research_rows", lambda cur, rows, producer: staged.extend(rows) or _RC(len(rows)))
    monkeypatch.setattr(cme, "_write_last_run", lambda payload: marker.update(payload) or None)
    monkeypatch.setattr("lib.search_router.engine_enabled", lambda: False, raising=False)
    return staged, marker, tmp_path / "state"


def _receipt(state):
    return json.loads((state / "data" / "runtime" / "catalyst-momentum-engine-overnight_last.json").read_text())


def test_overnight_live_run_matches_the_engine_overnight_band(engine, monkeypatch):
    staged, marker, state = engine
    assert cme.run_overnight(["--band", "overnight", "--apply"]) == 0
    a = ([r["symbol"] for r in staged], marker["staged"], marker["proposals_attempted"], _receipt(state)["summary"])
    staged.clear(), marker.clear()
    monkeypatch.setattr(sys, "argv", ["catalyst_momentum_engine.py", "--band", "overnight", "--apply"])
    assert cme.main() == 0
    b = ([r["symbol"] for r in staged], marker["staged"], marker["proposals_attempted"], _receipt(state)["summary"])
    assert a == b == (["AAA", "BBB"], 2, 0, a[3])
    assert a[3]["staged"] == 2 and _receipt(state)["status"] == "ok"


def test_overnight_dry_run_writes_nothing(engine, monkeypatch, capsys):
    staged, marker, state = engine
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert cme.run_overnight(["--band", "overnight", "--apply", "--dry-run"]) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("DRY-RUN "))
    rep = json.loads(line[len("DRY-RUN "):])
    assert rep["lane_id"] == "catalyst-momentum-engine-overnight"
    assert rep["summary"]["would_attempt_proposals"] == []
    assert not any("auto_proposal_generator" in w for w in rep["would_write"])
    assert staged == [] and marker == {}


def test_main_still_hands_gated_symbols_to_the_proposal_generator(engine, monkeypatch):
    """premarket / swing behaviour unchanged: --generate-proposals reaches the handoff, capped by band."""
    calls = []

    class _R:
        returncode, stdout = 0, "ok\n"

    monkeypatch.setattr(cme.subprocess, "run", lambda argv, **k: calls.append((argv, k["env"]["ALPACA_MODE"])) or _R())
    monkeypatch.setattr(sys, "argv", ["x", "--band", "market_swing", "--apply", "--generate-proposals"])
    assert cme.main() == 0
    assert [c[0][1:4] for c in calls] == [["scripts/auto_proposal_generator.py", "--symbol", "AAA"],
                                         ["scripts/auto_proposal_generator.py", "--symbol", "BBB"]]
    assert {c[1] for c in calls} == {"paper"}

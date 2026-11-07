"""`proposal_monitor.py --apply --dry-run` must not write (LQ-20261107-22).

The n8n run executor's dry run is exactly the allowlist command plus the dry_run_arg, so for the
proposal-monitor entry (`$PY scripts/proposal_monitor.py --pending --apply`) it runs

    scripts/proposal_monitor.py --pending --apply --dry-run

Until 2026-11-07 that printed "(dry-run — no DB writes)" and wrote anyway: main() passed
`apply=args.apply` straight into monitor_proposal(), whose `if apply:` branch UPDATEd
paper_trade_proposals and wrote a lifecycle event. A lane cannot be onboarded on a dry run that
writes (AGENTS.md 6), and a reassurance printed after the write is worse than no flag at all.

Hermetic: the DB layer, the lifecycle helpers, the quote provider and dotenv are stubbed before the
module is imported; nothing opens a connection, reads a secret or touches the network.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "proposal_monitor.py"


class _Conn:
    """A connection that records everything a write would go through."""

    def __init__(self):
        self.executed: list[str] = []
        self.commits = 0

    def cursor(self):
        conn = self

        class _Cur:
            def execute(self, sql, *a, **k):
                conn.executed.append(str(sql))

            def fetchall(self):
                return []

            def close(self):
                return None

        return _Cur()

    def commit(self):
        self.commits += 1

    def close(self):
        return None


def _load(monkeypatch):
    conn = _Conn()
    stubs = {
        "dotenv": {"load_dotenv": lambda *a, **k: True},
        "session13_db": {"get_conn": lambda: conn},
        "proposal_lifecycle": {
            "evaluate_lifecycle_status": lambda *a, **k: {},
            "get_expiry_hours": lambda *a, **k: 24,
            "is_intraday": lambda *a, **k: False,
            "is_overnight": lambda *a, **k: False,
            "get_timeframe_class": lambda *a, **k: "overnight",
            "get_price_drift_threshold": lambda *a, **k: 2.0,
            "get_max_expiry_hours": lambda *a, **k: 96,
        },
        "market_quote_provider": {"get_best_quote": lambda s: {}},
    }
    saved = {}
    for name, attrs in stubs.items():
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod
    spec = importlib.util.spec_from_file_location("proposal_monitor_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, conn, saved


def _unload(saved):
    for name, prev in saved.items():
        if prev is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prev


def _run(monkeypatch, argv):
    mod, conn, saved = _load(monkeypatch)
    try:
        seen: list[bool] = []
        mod.get_pending_proposals = lambda *a, **k: [{"id": 1, "symbol": "AAA", "proposed_entry": 10.0}]
        mod.monitor_proposal = lambda c, p, apply=False: (seen.append(apply), {"proposal_id": 1})[1]
        monkeypatch.setattr(sys, "argv", ["proposal_monitor.py", *argv])
        mod.main()
        return seen, conn
    finally:
        _unload(saved)


def test_dry_run_wins_over_apply(monkeypatch):
    seen, conn = _run(monkeypatch, ["--pending", "--apply", "--dry-run"])
    assert seen == [False], "monitor_proposal must be told not to write when --dry-run is present"
    assert conn.executed == [] and conn.commits == 0


def test_apply_still_writes_without_dry_run(monkeypatch):
    seen, _conn = _run(monkeypatch, ["--pending", "--apply"])
    assert seen == [True], "the live cron line (--pending --apply) must keep writing"


def test_neither_flag_does_not_write(monkeypatch):
    seen, conn = _run(monkeypatch, ["--pending"])
    assert seen == [False]
    assert conn.executed == [] and conn.commits == 0

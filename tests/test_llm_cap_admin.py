"""The spend caps had no operator surface at all.

Audited 2026-09-06: not in the Command Center, not in api_v2, not in api_v3_cio.
The only writer was `sync_cio_process_caps.py`, run by hand — and it is scheduled
nowhere.

The consequence, the same day: a 200-request/day cap stopped a backfill, changing
it meant a hand-written UPDATE against production, and that left
`config/llm_process_registry.json` saying `200 / $0.30` while the database said
`100000 / $1.25`. Two numbers for one quantity, with nothing to catch it.

A control with no operator surface gets changed by hand, and hand changes drift.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import llm_cap_admin as A  # noqa: E402


@pytest.fixture
def reg(tmp_path, monkeypatch):
    p = tmp_path / "reg.json"
    shutil.copy(ROOT / "config" / "llm_process_registry.json", p)
    monkeypatch.setenv("LLM_PROCESS_REGISTRY", str(p))
    return p


class _Cur:
    def __init__(self): self.rowcount = 1; self.sql = []
    def execute(self, sql, params=None): self.sql.append((sql, params))
    def fetchall(self): return [("advisory_desk_opinion", 100000, 1.25)]


class _Conn:
    def __init__(self): self._c = _Cur(); self.committed = False
    def cursor(self): return self._c
    def commit(self): self.committed = True


# ── both stores, always ────────────────────────────────────────────────────

def test_setting_a_cap_writes_the_registry_AND_the_database(reg):
    conn = _Conn()
    r = A.set_caps("advisory_desk_opinion", requests=500, dollars=0.75, conn=conn)
    assert r["ok"] and conn.committed
    doc = json.loads(reg.read_text())
    procs = doc if isinstance(doc, list) else doc.get("processes", doc)
    seq = procs if isinstance(procs, list) else list(procs.values())
    e = next(p for p in seq if p.get("id") == "advisory_desk_opinion")
    assert e["daily_soft_cap"] == 500 and e["daily_cost_cap_usd"] == 0.75


def test_the_database_is_written_first(reg):
    """A registry promising a cap the bridge is not enforcing is worse than the
    reverse: the operator would believe a limit that does not exist."""
    src = (ROOT / "scripts" / "lib" / "llm_cap_admin.py").read_text(encoding="utf-8")
    fn = src.split("def set_caps", 1)[1]
    assert fn.index("llm_process_config") < fn.index("write_text")


def test_a_failed_registry_write_is_reported_not_swallowed():
    src = (ROOT / "scripts" / "lib" / "llm_cap_admin.py").read_text(encoding="utf-8")
    assert "DB UPDATED BUT REGISTRY WRITE FAILED" in src


def test_before_and_after_are_returned_so_a_revert_needs_no_guessing(reg):
    conn = _Conn()
    r = A.set_caps("advisory_desk_opinion", requests=42, dollars=0.11, conn=conn)
    assert r["before"]["requests"] is not None
    assert r["after"]["requests"] == 42


# ── bounded, even for the operator ─────────────────────────────────────────

def test_ceilings_apply_regardless_of_who_asks(reg):
    """A cap is only worth having if it holds when someone is in a hurry — and
    that is exactly when caps get raised."""
    assert A.set_caps("advisory_desk_opinion", requests=A.MAX_REQUESTS + 1)["ok"] is False
    assert A.set_caps("advisory_desk_opinion", dollars=A.MAX_DOLLARS + 1)["ok"] is False


def test_nonsense_values_are_refused(reg):
    for kw in ({"requests": 0}, {"requests": -5}, {"dollars": 0}, {"dollars": -1.0}):
        assert A.set_caps("advisory_desk_opinion", **kw)["ok"] is False


def test_an_unknown_process_is_refused(reg):
    assert A.set_caps("nosuch_process", requests=10)["ok"] is False


def test_a_noop_call_is_refused(reg):
    assert A.set_caps("advisory_desk_opinion")["ok"] is False


# ── drift is reported, never silently reconciled ───────────────────────────

def test_drift_between_registry_and_db_is_surfaced(reg, monkeypatch):
    """Picking a winner is how the wrong number becomes authoritative."""
    class _DriftCur(_Cur):
        def fetchall(self): return [("advisory_desk_opinion", 7, 0.01)]
    class _DriftConn(_Conn):
        def cursor(self): return self._drift
        def __init__(self): super().__init__(); self._drift = _DriftCur()
    rows = A.list_caps(_DriftConn())
    row = next(r for r in rows if r["process_id"] == "advisory_desk_opinion")
    assert row["drift"] is True
    assert row["registry_requests"] != row["db_requests"]


def test_list_shows_both_sides(reg):
    rows = A.list_caps(_Conn())
    row = next(r for r in rows if r["process_id"] == "advisory_desk_opinion")
    for k in ("registry_requests", "registry_dollars", "db_requests", "db_dollars"):
        assert k in row


# ── the telegram surface ───────────────────────────────────────────────────

POLLER = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")


def test_the_command_is_allowlist_gated():
    """This is the one command that can raise a spend limit. The dispatch loop
    already gates on _allowed_chats(); the handler re-checks so a future refactor
    of the loop cannot silently open it."""
    fn = POLLER.split("def _handle_llm_caps", 1)[1].split("\ndef ", 1)[0]
    assert "_allowed_chats()" in fn


def test_the_global_cap_is_explicitly_out_of_scope():
    """It lives in the bridge's environment and needs a restart — saying so in
    the reply stops an operator believing they changed it."""
    fn = POLLER.split("def _handle_llm_caps", 1)[1].split("\ndef ", 1)[0]
    assert "LLM_GLOBAL_DAILY_USD_CAP" in fn and "restart" in fn


def test_the_reply_tells_the_operator_how_to_revert():
    fn = POLLER.split("def _handle_llm_caps", 1)[1].split("\ndef ", 1)[0]
    assert "Revert with" in fn

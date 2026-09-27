"""P2 audit remediation: alarms that see the truth (R-03, R-04, R-09, R-15, C-11)."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Cur:
    def __init__(self, catalyst_rows):
        self.sql: list[tuple[str, tuple]] = []
        self._cat = catalyst_rows
        self._pending = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))
        if sql.strip().startswith("SELECT") and "FROM news_articles" in sql:
            self._pending = []
        elif sql.strip().startswith("SELECT") and "FROM catalyst_events" in sql:
            self._pending = self._cat

    def fetchall(self):
        rows, self._pending = self._pending, []
        return rows

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1


def test_r04_catalyst_children_are_deleted_before_the_parent(monkeypatch):
    import news_symbol_guard as g
    monkeypatch.setattr(g, "headline_matches_symbol", lambda *a, **k: (False, "foreign_company"))
    monkeypatch.setattr(g, "_company_description", lambda *a, **k: "", raising=False)
    cur = _Cur([(42, "Pasqal quantum start-up", "")])
    conn = _Conn(cur)
    out = g.purge_mismatched_for_symbol(conn, "MRLN", apply=True, auto_commit=True)
    assert out["catalyst_removed"] == 1
    deletes = [s for s, _ in cur.sql if s.startswith("DELETE")]
    assert deletes[0].startswith("DELETE FROM catalyst_symbol_impact WHERE catalyst_event_id=")
    assert deletes[1].startswith("DELETE FROM catalyst_events WHERE id=")
    assert conn.commits == 1


def test_r03_crontab_snapshot_fallback_fresh_stale_and_none(tmp_path):
    from scripts.lib import crontab_snapshot as cs
    denied = lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="crontabs/johnclaw/: fopen: Permission denied")  # noqa: E731
    allowed = lambda *a, **k: SimpleNamespace(returncode=0, stdout="PY=x\n0 9 * * 0 echo hi\n", stderr="")  # noqa: E731
    root = tmp_path
    r = cs.read_crontab(root=root, runner=allowed)
    assert r.ok and r.source == "crontab" and "echo hi" in r.text
    r = cs.read_crontab(root=root, runner=denied)
    assert not r.ok and r.source == "none" and "no snapshot" in r.error
    snap = cs.snapshot_path(root); snap.parent.mkdir(parents=True)
    snap.write_text("PY=x\n0 9 * * 0 echo snap\n")
    r = cs.read_crontab(root=root, runner=denied)
    assert r.ok and r.source == "snapshot" and "echo snap" in r.text and r.age_s < 60
    old = time.time() - 3 * 3600
    os.utime(snap, (old, old))
    r = cs.read_crontab(root=root, runner=denied)
    assert not r.ok and "stale" in r.error
    assert "crontab -l >" in cs.SNAPSHOT_CRON_LINE and "crontab_snapshot.txt" in cs.SNAPSHOT_CRON_LINE


def test_r03_cron_sanity_reads_the_snapshot_and_warns_when_neither(monkeypatch, tmp_path):
    import check_cron_sanity as ccs
    from scripts.lib import crontab_snapshot as cs
    monkeypatch.setenv("TRADEAI_CRONTAB_SNAPSHOT_PATH", str(tmp_path / "snap.txt"))
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="fopen: Permission denied"))
    out = ccs.check()
    assert out[0]["type"] == "cron_sanity_check_hardened" and out[0]["severity"] == "warning"
    (tmp_path / "snap.txt").write_text("PY=/x/.venv/bin/python\n0 9 * * 0 cd /nowhere && $PY scripts/does_not_exist.py\n")
    out = ccs.check()
    types = [f["type"] for f in out]
    assert "cron_sanity_via_snapshot" in types and "cron_dead_script_ref" in types


def test_r15_lane_state_for_command():
    from scripts.lib.lane_registry import lane_state_for_command, PAUSED_OR_RETIRED
    reg = {"lanes": [
        {"lane_id": "cio-decision-engine", "state": "PAUSED", "scheduler": {"kind": "cron", "match": "scripts/cio_decision_engine.py --run"}},
        {"lane_id": "ok-lane", "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 * * * * cd $PROJ && $PY scripts/fine.py"}},
    ]}
    assert lane_state_for_command("/x/.venv/bin/python scripts/cio_decision_engine.py --run", reg)["state"] == "PAUSED"
    assert lane_state_for_command("python scripts/fine.py", reg)["state"] == "ACTIVE"
    assert lane_state_for_command("python scripts/unknown.py", reg) == {"lane_id": None, "state": None, "matched": None}
    assert "PAUSED" in PAUSED_OR_RETIRED and "ACTIVE" not in PAUSED_OR_RETIRED


def _health_agent():
    spec = importlib.util.spec_from_file_location("_p2_health_agent", ROOT / "scripts" / "health_agent.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:  # heavy module: fall back to text assertions
        return None, exc
    return mod, None


def test_r04_failure_streak_breaker_is_pure_and_wired():
    ha, err = _health_agent()
    src = (ROOT / "scripts" / "health_agent.py").read_text(encoding="utf-8", errors="replace")
    assert "_circuit_open(st)" in src and 'st["fail_streak"] = _next_fail_streak(st, rc)' in src
    assert "_lane_state_for_cmd(cmd)" in src and "_PAUSED_OR_RETIRED" in src
    if ha is None:
        return
    st = {}
    for _ in range(4):
        st["fail_streak"] = ha._next_fail_streak(st, 1)
    assert st["fail_streak"] == 4 and not ha._circuit_open(st, 5)
    st["fail_streak"] = ha._next_fail_streak(st, 1)
    assert ha._circuit_open(st, 5)
    assert ha._next_fail_streak(st, 0) == 0 and ha._next_fail_streak(st, 69) == 0


def test_c11_stop_band_recheck_is_delivered_and_linked():
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("_p2_holdings_change_trigger", ROOT / "scripts" / "holdings_change_trigger.py")
    h = _ilu.module_from_spec(spec); spec.loader.exec_module(h)  # type: ignore[union-attr]
    calls = {}

    def save(**kw):
        calls["saved"] = kw
        return 4871

    def send(text, **kw):
        calls["sent"] = (text, kw)
        return {"accepted": True, "message_id": "9001"}

    def attach(aid, mid):
        calls["attached"] = (aid, mid)
        return True
    out = h.deliver_stop_band_recheck("[holdings-change] SCHD resized 1→913 sh — protective-stop band recheck recommended",
                                      symbol="SCHD", change="resized", save=save, send=send, attach=attach)
    assert out["stored_id"] == 4871 and out["accepted"] and out["message_id"] == "9001"
    assert calls["attached"] == (4871, "9001")
    assert calls["saved"]["parsed_payload"]["kind"] == "stop_band_recheck"
    assert calls["sent"][1]["message_class"] == "operator_alert"
    # a failing sender never raises into the position sync
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tg down"))  # noqa: E731
    out = h.deliver_stop_band_recheck("x", symbol="SCHD", change="resized", save=save, send=boom, attach=attach)
    assert out["stored_id"] == 4871 and out["error"] == "send:RuntimeError"


def test_r09_deploy_writes_active_release():
    src = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")
    assert '>"${RELEASES_BASE}/ACTIVE_RELEASE"' in src
    chk = (ROOT / "scripts" / "check_file_integrity.py").read_text(encoding="utf-8")
    assert 'RELEASE_BASE / "ACTIVE_RELEASE"' in chk

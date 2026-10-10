"""Refactor wave 1 (cron -> n8n, 2026-10-10): scripts/hermes_config_governor.py (cron L671).

The lane failed on every run (13/13 retained runs): config_change_proposals.diff is jsonb and the
INSERT passed the text '<current> -> <proposed>' (InvalidTextRepresentation, Token "-"). Behind it
proposal_id is NOT NULL UNIQUE with no default, so fixing the diff alone would still fail.

- dry run (no flag, --dry-run, or --dry-run with --apply) runs detectors on a READ ONLY session and
  reaches no INSERT, no commit, no alert row, no receipt;
- --apply files proposals with a JSON diff and a proposal_id, writes hermes_config_governor_last.json
  (ok_at only on success), and a failing INSERT leaves a failed receipt and a non-zero exit.
Hermetic: fake db_adapter module, tmp kill-switch path, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_config_governor as hcg  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


class FakeConn:
    def __init__(self, shed=(1000, 500), live=100, fail_insert=False):
        self.shed, self.live, self.fail_insert = shed, live, fail_insert
        self.log: list = []
        self.inserts: list = []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat[:60]))
                if flat.startswith("INSERT"):
                    if conn.fail_insert:
                        raise RuntimeError("InvalidTextRepresentation")
                    conn.inserts.append((flat, params))
                self._sql = flat

            def fetchone(self):
                if "FROM scope_governor_audit" in self._sql:
                    return conn.shed
                if "count(DISTINCT UPPER(symbol))" in self._sql:
                    return (conn.live,)
                return None  # _pending: nothing pending

            def fetchall(self):
                return []

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(hcg, "KILL_SWITCH", tmp_path / "HERMES_DISABLED")
    conn = FakeConn()
    alerts = []
    fake = types.SimpleNamespace(_get_conn=lambda: conn, _execute=lambda sql, params, fetch=None: alerts.append(params))
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    return {"conn": conn, "alerts": alerts, "state": tmp_path / "state", "fake": fake}


@pytest.mark.parametrize("argv", [[], ["--dry-run"], ["--dry-run", "--apply"]])
def test_dry_run_reaches_no_write(env, monkeypatch, capsys, argv):
    def boom(*a, **k):
        raise AssertionError("dry run reached write_receipt")

    monkeypatch.setattr(llr, "write_receipt", boom)
    assert hcg.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["apply"] is False
    assert {p["status"] for p in out["proposals"]} == {"would_propose"} and len(out["proposals"]) == 2
    assert env["conn"].inserts == [] and ("commit",) not in env["conn"].log
    assert ("set_session", {"readonly": True}) in env["conn"].log
    assert env["alerts"] == [] and not env["state"].exists()


def test_dry_run_report_tracks_state(env, capsys):
    hcg.main([])
    first = {p["target_key"] for p in json.loads(capsys.readouterr().out)["proposals"]}
    env["conn"].shed, env["conn"].live = (0, 0), 10_000  # no pressure, no underfill
    hcg.main([])
    second = json.loads(capsys.readouterr().out)["proposals"]
    assert first == {"hermes_scope_governor.total_cap", "hermes_scope_governor.total_cap_underfill"}
    assert second == []


def test_apply_inserts_jsonb_diff_and_proposal_id_then_writes_ok_receipt(env, capsys):
    assert hcg.main(["--apply"]) == 0
    assert len(env["conn"].inserts) == 2 and ("commit",) in env["conn"].log
    for sql, params in env["conn"].inserts:
        assert sql.count("%s") == len(params), "placeholder / parameter count mismatch"
        assert "proposal_id" in sql and re.fullmatch(r"HCG_\d{14}_[0-9a-f]{8}", params[0])
        cols = sql[sql.index("(") + 1 : sql.index(")")].replace(" ", "").split(",")
        vals = sql[sql.index("VALUES (") + 8 : sql.rindex(")")].replace(" ", "").split(",")
        pos = cols.index("diff")
        assert vals[pos] == "%s::jsonb"
        diff = params[sum(1 for v in vals[:pos] if v.startswith("%s"))]
        assert isinstance(json.loads(diff), dict), "diff must be JSON for the jsonb column"
        assert "->" not in diff
        assert set(json.loads(diff)) == {"added", "changed", "removed"}
    assert len(env["alerts"]) == 1
    doc = json.loads((env["state"] / "data/runtime/hermes_config_governor_last.json").read_text())
    assert doc["status"] == "ok" and doc["ok_at"] and doc["summary"]["filed"] == 2


def test_diff_shape():
    assert hcg._diff({"total_cap": 800}, {"total_cap": 900}) == {
        "added": {},
        "changed": {"total_cap": {"old": 800, "new": 900}},
        "removed": {},
    }


def test_failed_insert_is_nonzero_with_failed_receipt(env):
    env["conn"].fail_insert = True
    with pytest.raises(RuntimeError):
        hcg.main(["--apply"])
    doc = json.loads((env["state"] / "data/runtime/hermes_config_governor_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None
    # the receipt keeps the exception type only, never its message (LaneRunReceipt@v1 contract)
    assert doc["error"] == "RuntimeError" and "InvalidTextRepresentation" not in json.dumps(doc)


def test_alert_row_failure_is_reported_not_swallowed(env, capsys):
    def bad(*a, **k):
        raise RuntimeError("alert table locked")

    env["fake"]._execute = bad
    assert hcg.main(["--apply"]) == 0  # the proposals are committed; the alert row is secondary
    out = json.loads(capsys.readouterr().out)
    assert "alert table locked" in out["alert_error"]
    doc = json.loads((env["state"] / "data/runtime/hermes_config_governor_last.json").read_text())
    assert doc["summary"]["alert_error"] == "RuntimeError"  # reported, but the message stays out of the receipt
    assert "alert table locked" not in json.dumps(doc)


def test_kill_switch_is_an_idle_success(env, tmp_path):
    (tmp_path / "HERMES_DISABLED").write_text("")
    assert hcg.main(["--apply"]) == 0
    assert env["conn"].log == []
    doc = json.loads((env["state"] / "data/runtime/hermes_config_governor_last.json").read_text())
    assert doc["status"] == "ok" and "kill switch" in doc["summary"]["idle_reason"]

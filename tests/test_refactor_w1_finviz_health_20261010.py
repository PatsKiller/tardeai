"""n8n refactor wave 1 (W2), 2026-10-10 — finviz_health_check.py (cron:L703).

``--dry-run`` is ``plan()``: credentials present, the attempt order, the current data_source_health row
(READ ONLY transaction) and the UPDATE each outcome would run. No export probe (it advances the shared
finviz_throttle state and spends a Finviz request), no UPDATE, no commit, no send, no receipt. A real run
now exits 3 when the health row could not be recorded (it used to be ``except: pass``) and writes a
LaneRunReceipt@v1. Offline: secrets, probe and DB are fakes.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_health_check as fhc  # noqa: E402

COVERS = ["scripts/finviz_health_check.py"]


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = conn.rowcount

    def execute(self, sql, params=()):
        self.conn.sql.append(" ".join(str(sql).split()))
        if self.conn.raise_on_update and "UPDATE" in sql:
            raise RuntimeError("db down")

    def fetchone(self):
        return self.conn.row


class _Conn:
    def __init__(self, row=None, rowcount=1, raise_on_update=False):
        self.sql, self.commits, self.row = [], 0, row
        self.rowcount, self.raise_on_update = rowcount, raise_on_update

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    creds = {"FINVIZ_COOKIE": "ck", "FINVIZ_API_TOKEN": "tk"}
    monkeypatch.setattr(fhc, "_env", lambda key, default="": creds.get(key, default or ""))
    conn = _Conn(row=("healthy", None, None, 0, False, None))
    monkeypatch.setattr(fhc, "_get_conn", lambda: conn)
    sent = []
    fake = type(sys)("telegram_alert")
    fake.send_telegram = lambda text, **kw: sent.append(text) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    return {"root": tmp_path, "conn": conn, "creds": creds, "sent": sent}


def _main(monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["finviz_health_check.py", *argv])
    with pytest.raises(SystemExit) as e:
        fhc.main()
    return e.value.code


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_dry_run_never_probes_never_updates_never_sends(env, monkeypatch, capsys):
    monkeypatch.setattr(fhc, "_probe", lambda *a: pytest.fail("probe reached"))
    monkeypatch.setattr(fhc, "check", lambda *a, **k: pytest.fail("check reached"))
    assert _main(monkeypatch, "--dry-run", "--telegram") == 0
    out = capsys.readouterr().out
    plan = json.loads(out[: out.index("(dry run")])
    assert plan["would_probe"] == ["cookie", "token"] and plan["current_row"]["status"] == "healthy"
    assert "UPDATE data_source_health" in plan["would_update_on_healthy"]
    sqls = env["conn"].sql
    assert sqls[0] == "BEGIN READ ONLY" and not any("UPDATE" in s for s in sqls)
    assert env["conn"].commits == 0 and env["sent"] == [] and _files(env["root"]) == []


def test_dry_run_mutation_tested_report_follows_credentials_and_row(env, monkeypatch, capsys):
    _main(monkeypatch, "--dry-run")
    first = capsys.readouterr().out
    env["creds"]["FINVIZ_COOKIE"] = ""
    env["conn"].row = None
    _main(monkeypatch, "--dry-run")
    second = capsys.readouterr().out
    assert first != second
    plan = json.loads(second[: second.index("(dry run")])
    assert plan["would_probe"] == ["token"] and plan["current_row"] == {"present": False}


def test_source_order_dry_run_exits_before_check():
    src = inspect.getsource(fhc.main)
    assert src.index("if args.dry_run:") < src.index("sys.exit(0)") < src.index("result = check()")
    called = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(ast.parse(inspect.getsource(fhc.plan)))
        if isinstance(n, ast.Call)
    }
    assert not called & {"_probe", "check", "execute", "commit", "send_telegram", "write_lane_receipt"}
    row_src = inspect.getsource(fhc._read_health_row)
    assert "BEGIN READ ONLY" in row_src and "UPDATE" not in row_src and "commit" not in row_src


def test_healthy_and_recorded_exits_0_with_receipt_ok_at(env, monkeypatch):
    monkeypatch.setattr(fhc, "_probe", lambda url, headers: (1741, None))
    assert _main(monkeypatch) == 0
    rc = json.loads((env["root"] / "data/runtime/finviz_health_check_last.json").read_text())
    assert rc["status"] == "ok" and rc["ok_at"] == rc["finished_at"] and rc["summary"]["row_count"] == 1741
    assert env["conn"].commits == 1


def test_record_failure_is_no_longer_swallowed_exit_3(env, monkeypatch):
    monkeypatch.setattr(fhc, "_probe", lambda url, headers: (5, None))
    env["conn"].raise_on_update = True
    assert _main(monkeypatch) == 3
    rc = json.loads((env["root"] / "data/runtime/finviz_health_check_last.json").read_text())
    assert rc["status"] == "failed" and rc["ok_at"] is None and rc["summary"]["record_error"] == "RuntimeError"


def test_missing_finviz_row_is_not_recorded(env, monkeypatch):
    monkeypatch.setattr(fhc, "_probe", lambda url, headers: (5, None))
    env["conn"].rowcount = 0
    assert _main(monkeypatch) == 3


def test_degraded_still_exits_1_and_carries_previous_ok_at(env, monkeypatch):
    monkeypatch.setattr(fhc, "_probe", lambda url, headers: (5, None))
    assert _main(monkeypatch) == 0
    ok_at = json.loads((env["root"] / "data/runtime/finviz_health_check_last.json").read_text())["ok_at"]
    monkeypatch.setattr(fhc, "_probe", lambda url, headers: (0, "zero rows / login page"))
    assert _main(monkeypatch) == 1
    rc = json.loads((env["root"] / "data/runtime/finviz_health_check_last.json").read_text())
    assert rc["status"] == "failed" and rc["ok_at"] == ok_at


def test_proposed_allowlist_argv_is_dispatcher_eligible():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    entry = {
        "lane_id": "finviz-health-check",
        "command": ["$PY", "scripts/finviz_health_check.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": [],
    }
    assert dispatcher_eligible(entry) == (True, "ok")

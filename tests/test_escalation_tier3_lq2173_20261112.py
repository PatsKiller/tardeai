"""STOP-ESCALATION-TIER3-LQ2173: Tier 3 (LLM analysis) never self-certifies FIXED.
A gemma reply > N chars or a Claude CLI exit 0 only proves an analysis ran. Synthetic data only."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _esc():
    spec = importlib.util.spec_from_file_location("esc_lq2173", ROOT / "scripts" / "claude_escalation_handler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ITEM = {"component": "health:synthetic:unmeasured_thing", "detail": "synthetic finding"}


class FakeCur:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO claude_interventions"):
            self.conn.next_id += 1
            self.conn.rows[self.conn.next_id] = {"status": params[5], "component": params[0]}
            self._ret = (self.conn.next_id,)
        elif s.startswith("UPDATE claude_interventions"):
            self.conn.rows[params[2]].update(status=params[0], session_log=params[1])
        self.conn.sql.append(s)

    def fetchone(self):
        return getattr(self, "_ret", None)

    def fetchall(self):
        return []

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.rows, self.sql, self.next_id = {}, [], 0

    def cursor(self, *a, **k):
        return FakeCur(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class Resp:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _run_tail(monkeypatch, tmp_path, *, verify, route):
    esc = _esc()
    q = tmp_path / "q.json"
    q.write_text(json.dumps([ITEM]))
    monkeypatch.setattr(esc, "QUEUE_FILE", q)
    monkeypatch.setattr(esc, "STALENESS_QUEUE_FILE", tmp_path / "none.json")
    conn = FakeConn()
    monkeypatch.setattr(esc, "_get_conn", lambda: conn)
    sent = []
    monkeypatch.setattr(esc, "_notify", lambda m, *a, **k: sent.append(m))
    monkeypatch.setattr(esc, "_verify_remediation", verify)
    monkeypatch.setattr(esc, "is_review_only", lambda *a, **k: False)  # let the item reach Tier 3
    monkeypatch.setenv("DISABLE_GEMMA4_31B_ESCALATION", "1")  # skip 3a unless routed
    long_text = "root cause analysis " * 20
    fake = types.ModuleType("requests")
    fake.get = lambda *a, **k: Resp({"models": []})
    fake.post = lambda *a, **k: Resp(
        {"message": {"content": long_text}, "choices": [{"message": {"content": long_text}}]}
    )
    if route == "3a":
        home = tmp_path / "home"
        (home / "llama-cpp-vulkan" / "llama-b9405").mkdir(parents=True)
        (home / "llama-cpp-vulkan" / "gemma4-31b-hf.gguf").write_text("x")
        (home / "llama-cpp-vulkan" / "llama-b9405" / "llama-server").write_text("x")
        monkeypatch.setattr(esc.Path, "home", classmethod(lambda cls: home))
        monkeypatch.setattr(esc.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
        monkeypatch.setenv("DISABLE_GEMMA4_31B_ESCALATION", "0")
        import datetime as _dt

        class _Sat(_dt.datetime):  # Saturday 03:00 ET: outside the market window
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 14, 3, 0, tzinfo=tz)

        monkeypatch.setattr(esc, "datetime", _Sat)
    if route == "3b_fallback":
        import datetime as _dt

        class _Sat(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 14, 3, 0, tzinfo=tz)

        monkeypatch.setattr(esc, "datetime", _Sat)
        monkeypatch.setattr(esc.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
        fake.get = lambda *a, **k: Resp({"models": [{"name": "gemma3:12b"}]})
        calls = []

        def _post(*a, **k):
            calls.append(1)
            body = "" if len(calls) == 1 else long_text
            return Resp({"message": {"content": body}})

        fake.post = _post
    if route == "3c":
        fake.post = lambda *a, **k: Resp({"message": {"content": ""}})
        monkeypatch.setenv("ESCALATION_USE_CLAUDE_CLI", "1")
        monkeypatch.setattr(
            esc.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="all good", stderr="")
        )
    monkeypatch.setitem(sys.modules, "requests", fake)
    esc.process_queue(dry_run=False, tier1_only=False, no_llm=False)
    return conn, sent


@pytest.mark.parametrize("route", ["3a", "3b", "3b_fallback", "3c"])
def test_llm_success_without_remeasure_is_not_fixed(monkeypatch, tmp_path, route):
    conn, sent = _run_tail(monkeypatch, tmp_path, verify=lambda item: (False, "still_failing"), route=route)
    statuses = [r["status"] for r in conn.rows.values()]
    assert statuses, "an intervention row must have been written"
    assert "fixed" not in statuses, f"{route}: LLM text/exit 0 must never write fixed: {statuses}"
    assert statuses == ["investigated_unverified"]
    text = "\n".join(sent).lower()
    assert "→ fixed" not in text and "analysis complete" not in text


def test_fixed_only_when_remeasured_clear(monkeypatch, tmp_path):
    conn, _ = _run_tail(monkeypatch, tmp_path, verify=lambda item: (True, "measured_ok"), route="3b")
    assert [r["status"] for r in conn.rows.values()] == ["fixed"]
    assert "measured_ok" in next(iter(conn.rows.values()))["session_log"]


def test_verify_exception_is_unverified_not_fixed(monkeypatch, tmp_path):
    def boom(item):
        raise RuntimeError("db down")

    conn, _ = _run_tail(monkeypatch, tmp_path, verify=boom, route="3b")
    assert [r["status"] for r in conn.rows.values()] == ["investigated_unverified"]


def test_no_analysis_is_failed(monkeypatch):
    esc = _esc()
    assert esc.tier3_row_status(ITEM, False)[0] == "failed"

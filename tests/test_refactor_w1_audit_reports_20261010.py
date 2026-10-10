"""Refactor wave 1 (cron -> n8n), 2026-10-10: audit_enrichment_coverage.py,
report_agent_number_grounding.py, write_state_freshness_history.py.

--dry-run computes the real report and cannot reach the send / --out write / psql call; a real run of the
enrichment audit and the freshness writer leaves a LaneRunReceipt@v1 whose ok_at advances only on
success; gaps and SLO findings are not failures in a dry run. Hermetic: fake DB cursor, fake psql,
fake audit subprocess, tmp persistent-state root.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    return root


def _receipt(state, lane):
    p = state / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


# ── audit_enrichment_coverage ─────────────────────────────────────────────


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append(q)

    def fetchall(self):
        return []

    def fetchone(self):
        return (1,)


@pytest.fixture
def aec(tmp_path, monkeypatch):
    mod = importlib.import_module("audit_enrichment_coverage")
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)  # no holdings / pills files -> empty sets
    cur = _Cur()
    conn = types.SimpleNamespace(cursor=lambda: cur)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    wu = types.SimpleNamespace(symbols=lambda c: mod._UNI, directive_symbols=lambda c: {"AAA"})
    monkeypatch.setitem(sys.modules, "watch_universe", wu)
    mod._UNI = {"AAA", "BBB"}
    sent = []
    monkeypatch.setattr(mod, "_alert", lambda gaps: sent.append(len(gaps)))
    mod._sent, mod._cur = sent, cur
    return mod


def test_aec_dry_run_alert_previews_but_never_sends(state, aec, capsys):
    assert aec.main(["--alert", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would send alert (1 directive gaps)" in out and "AAA: missing" in out
    assert aec._sent == []
    assert _receipt(state, "audit-enrichment-coverage") is None
    assert all(q.lstrip().upper().startswith("SELECT") for q in aec._cur.sql)


def test_aec_dry_run_json_keeps_stdout_json(state, aec, capsys):
    aec.main(["--alert", "--dry-run", "--json"])
    cap = capsys.readouterr()
    assert json.loads(cap.out)["symbols_with_gaps"] == 2 and "would send alert" in cap.err


def test_aec_dry_run_source_order():
    src = (ROOT / "scripts" / "audit_enrichment_coverage.py").read_text()
    body = src[src.index("def run(") : src.index("def _table_exists")]
    assert body.index("if dry_run:") < body.index("        _alert(directive_gaps)")


def test_aec_live_alert_sends_once_and_writes_ok_receipt(state, aec):
    assert aec.main(["--alert"]) == 0
    assert aec._sent == [1]
    rec = _receipt(state, "audit-enrichment-coverage")
    assert rec["status"] == "ok" and rec["ok_at"]
    assert rec["summary"] == {"universe": 2, "symbols_with_gaps": 2, "directive_gaps": 1, "alert_requested": True}


def test_aec_gaps_are_findings_not_failure_without_alert(state, aec):
    assert aec.main([]) == 0 and aec._sent == []
    assert _receipt(state, "audit-enrichment-coverage")["status"] == "ok"


def test_aec_audit_failure_is_failed_receipt_and_raises(state, aec, monkeypatch):
    aec.main([])
    ok_at = _receipt(state, "audit-enrichment-coverage")["ok_at"]

    def boom():
        raise ConnectionError("db down")

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=boom))
    with pytest.raises(ConnectionError):
        aec.main([])
    rec = _receipt(state, "audit-enrichment-coverage")
    assert rec["status"] == "failed" and rec["ok_at"] == ok_at


# ── report_agent_number_grounding ─────────────────────────────────────────


@pytest.fixture
def rang(monkeypatch):
    mod = importlib.import_module("report_agent_number_grounding")
    monkeypatch.setattr(mod, "fetch", lambda days: [])
    return mod


def _fail_slo(report, path=None):
    return {"ok": False, "verdict": "FAIL", "breaches": ["ungrounded_share 0.2 > 0.05"]}


def test_rang_dry_run_never_writes_out_and_exits_0_on_fail(rang, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rang, "evaluate_slo", _fail_slo)
    out = tmp_path / "rt" / "slo.json"
    assert rang.main(["--days", "7", "--check-slo", "--out", str(out), "--dry-run"]) == 0
    assert not out.exists() and not out.parent.exists()
    text = capsys.readouterr().out
    assert "SLO: FAIL" in text and f"would write {out}" in text


def test_rang_dry_run_source_order():
    src = (ROOT / "scripts" / "report_agent_number_grounding.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("args.out is not None and args.dry_run") < body.index("tmp.write_text(")


def test_rang_live_out_written_and_fail_still_exits_1(rang, tmp_path, monkeypatch):
    monkeypatch.setattr(rang, "evaluate_slo", _fail_slo)
    out = tmp_path / "slo.json"
    assert rang.main(["--check-slo", "--out", str(out)]) == 1  # unchanged live semantics
    doc = json.loads(out.read_text())
    assert doc["slo"]["verdict"] == "FAIL" and doc["measured_at"]


# ── write_state_freshness_history ─────────────────────────────────────────

AUDIT = {
    "checked_at": "2026-10-10T03:00:00+00:00",
    "freshness_ok": False,
    "issues": ["STALE: a.json is 30h old, max 24h"],
    "files_checked": [
        {"file": "a.json", "exists": True, "age_hours": 30, "max_age_hours": 24, "ok": False},
        {"file": "b.json", "exists": True, "age_hours": 1, "max_age_hours": 24, "ok": True},
    ],
}


@pytest.fixture
def wsf(monkeypatch):
    mod = importlib.import_module("write_state_freshness_history")
    psql = []
    monkeypatch.setattr(mod, "get_audit", lambda: json.loads(json.dumps(AUDIT)))
    monkeypatch.setattr(mod, "run_psql", lambda sql: psql.append(sql) or "")
    monkeypatch.setattr(mod, "load_env", lambda: None)
    monkeypatch.setattr(mod, "require_db_env", lambda: None)
    mod._psql = psql
    return mod


def test_wsf_dry_run_never_calls_psql(state, wsf, capsys):
    assert wsf.main(["--dry-run"]) == 0
    assert wsf._psql == []
    out = capsys.readouterr().out
    assert "would insert state_file=a.json ok=False" in out and "INSERT 2 rows" in out
    assert _receipt(state, "write-state-freshness-history") is None


def test_wsf_dry_run_source_order():
    src = (ROOT / "scripts" / "write_state_freshness_history.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("if args.dry_run:") < body.index("ensure_schema()")
    assert body.index("return 0") < body.index("ensure_schema()")


def test_wsf_build_insert_sql_matches_live_insert(wsf):
    sql, n = wsf.build_insert_sql(AUDIT)
    assert n == 2 and sql.count("::jsonb") == 4 and "'a.json'" in sql
    assert wsf.build_insert_sql({"files_checked": []}) == (None, 0)


def test_wsf_live_writes_ok_receipt(state, wsf):
    assert wsf.main([]) == 0
    assert len(wsf._psql) == 3 and "INSERT INTO state_freshness_history" in wsf._psql[1]
    rec = _receipt(state, "write-state-freshness-history")
    assert rec["status"] == "ok" and rec["summary"]["inserted"] == 2


def test_wsf_psql_failure_failed_receipt(state, wsf, monkeypatch):
    def boom(sql):
        raise RuntimeError("psql failed")

    monkeypatch.setattr(wsf, "run_psql", boom)
    with pytest.raises(RuntimeError):
        wsf.main([])
    assert _receipt(state, "write-state-freshness-history")["status"] == "failed"


def test_wsf_audit_subprocess_uses_venv_python(monkeypatch):
    mod = importlib.import_module("write_state_freshness_history")
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(AUDIT), stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv("TRADEAI_VENV_PYTHON", sys.executable)
    assert mod.get_audit()["files_checked"][0]["file"] == "a.json"
    assert seen["argv"][0] == sys.executable and seen["argv"][0] != "python3"

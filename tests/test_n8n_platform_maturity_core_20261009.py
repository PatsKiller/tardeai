"""N8nPlatformMaturity@v1 core: read-only probe allowlist, orchestration, receipt + markdown (hermetic)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

from n8n_maturity import core  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 20, 0, tzinfo=dt.timezone.utc)


def _load_main():
    spec = importlib.util.spec_from_file_location("n8n_platform_maturity", PROJ / "scripts" / "n8n_platform_maturity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _probe(tmp_path, runner=None, config=None):
    return core.Probe(root=tmp_path / "state", proj=tmp_path / "proj", now=NOW, env={},
                      config=config if config is not None else json.loads((PROJ / "config" / "n8n_platform_maturity.json").read_text()),
                      runner=runner or (lambda argv, t: (1, "", "absent")))


@pytest.mark.parametrize("argv", [
    ["crontab", "-l"],
    ["systemctl", "--user", "list-units", "--failed"],
    ["journalctl", "--user", "-u", "x.service", "--since", "-24h"],
    ["docker", "ps", "--format", "{{.Names}}"],
    ["docker", "exec", "db", "psql", "-U", "u", "-d", "n8n", "-At", "-c", "SELECT count(*) FROM workflow_entity"],
    ["gh", "run", "list", "--branch", "main"],
    ["gh", "api", "repos/o/r/commits/main/check-runs"],
    ["git", "-C", "/x", "log", "-1"],
    ["guard", "log", "20"],
])
def test_read_only_allowlist_accepts(argv):
    assert core.is_read_only(argv)


@pytest.mark.parametrize("argv", [
    ["crontab", "-e"], ["crontab", "-"], ["crontab", "-r"],
    ["systemctl", "--user", "restart", "x"], ["systemctl", "restart", "x"],
    ["journalctl", "--user", "--vacuum-time=1d"],
    ["docker", "exec", "db", "psql", "-c", "DELETE FROM workflow_entity"],
    ["docker", "exec", "db", "psql", "-c", "SELECT 1; DROP TABLE x"],
    ["docker", "exec", "db", "psql", "-c", "WITH x AS (DELETE FROM t RETURNING *) SELECT 1"],
    ["docker", "restart", "n8n"],
    ["gh", "api", "-X", "POST", "repos/o/r/issues"], ["gh", "api", "--method=PATCH", "x"], ["gh", "pr", "merge", "1"],
    ["git", "push"], ["git", "-C", "/x", "commit"],
    ["guard", "request", "cron"], ["rm", "-rf", "/"], [],
])
def test_read_only_allowlist_refuses(argv):
    assert not core.is_read_only(argv)


def test_probe_run_refuses_and_records(tmp_path):
    calls = []
    p = _probe(tmp_path, runner=lambda argv, t: (calls.append(argv) or (0, "x", "")))
    with pytest.raises(PermissionError):
        p.run(["crontab", "-r"])
    assert calls == []
    assert p.crontab() == "x"
    assert p.commands == [{"argv": "crontab -l", "rc": 0}]


def test_rows_since_and_missing(tmp_path):
    p = _probe(tmp_path)
    assert p.rows(tmp_path / "nope.jsonl") is None
    f = tmp_path / "a.jsonl"
    f.write_text('{"ts": "2026-10-09T10:00:00Z"}\n{"ts": "2026-10-01T10:00:00+00:00"}\nnot json\n{"x": 1}\n')
    got = p.rows(f, since=p.since(24))
    assert len(got) == 2 and got[0]["ts"].startswith("2026-10-09")


def test_ratio_and_mean_scores():
    assert core.ratio_score(None, 10) == 0.0
    assert core.ratio_score(5, 10) == 4.0
    assert core.ratio_score(10, 10) == 8.0
    assert core.ratio_score(12, 10) == 10.0
    assert core.ratio_score(15, 10, top=20) == 9.0
    s, st, _ = core.mean_score([("a", 10.0), ("b", None)])
    assert (s, st) == (5.0, core.PARTIAL)
    assert core.mean_score([("a", None)])[:2] == (0.0, core.UNVERIFIED)
    assert core.mean_score([])[1] == core.UNVERIFIED


def test_unverified_is_zero_and_fails_gate():
    r = core.dim_result("x", score=9.5, gate_rule="g", gate_pass=True, metrics={}, evidence_list=[], status=core.UNVERIFIED)
    assert r["score"] == 0.0 and r["gate"]["pass"] is False


def test_score_all_missing_collectors_and_exceptions(tmp_path):
    m = _load_main()
    p = _probe(tmp_path)

    def boom(_p):
        raise RuntimeError("no evidence here")

    def good(_p):
        return core.dim_result("registry_truth", score=8.5, gate_rule="g", gate_pass=True, metrics={"a": 1},
                               evidence_list=[core.evidence("config/lane_registry.json", rows=3)])
    rec = m.score_all(p, {"registry_truth": good, "rationalization": boom})
    assert rec["schema"] == "N8nPlatformMaturity@v1"
    assert len(rec["dimensions"]) == 12
    by = {r["id"]: r for r in rec["dimensions"]}
    assert by["registry_truth"]["score"] == 8.5 and by["registry_truth"]["n"] == 1
    assert by["rationalization"]["status"] == core.UNVERIFIED and "RuntimeError" in by["rationalization"]["notes"][0]
    assert by["docs_synced"]["score"] == 0.0
    assert rec["overall"] == round(8.5 / 12, 2)
    assert rec["gates_passed"] == 1 and rec["overall_gate_pass"] is False
    assert len(rec["unverified"]) == 11


def test_score_all_deterministic_and_markdown(tmp_path):
    m = _load_main()
    a = m.score_all(_probe(tmp_path), {})
    b = m.score_all(_probe(tmp_path), {})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    md = m.render_markdown(a)
    assert "| 1 | Registry truth |" in md and "| 12 | Docs synced |" in md and "UNVERIFIED" in md


def test_write_receipt_only_touches_its_files(tmp_path):
    m = _load_main()
    rec = m.score_all(_probe(tmp_path), {})
    root = tmp_path / "state"
    latest, hist = m.write_receipt(rec, root, {})
    m.write_receipt(rec, root, {})
    assert json.loads(latest.read_text())["schema"] == "N8nPlatformMaturity@v1"
    assert len(hist.read_text().splitlines()) == 2
    files = sorted(str(f.relative_to(root)) for f in root.rglob("*") if f.is_file())
    assert files == ["data/governance/n8n_platform_maturity_history.jsonl", "data/governance/n8n_platform_maturity_latest.json"]


def test_dry_run_default_writes_nothing(tmp_path, capsys, monkeypatch):
    m = _load_main()
    monkeypatch.setattr(m, "collectors", lambda: {})
    root = tmp_path / "state"
    assert m.main(["--root", str(root)]) == 0
    assert not root.exists()
    assert '"overall": 0.0' in capsys.readouterr().out


def test_every_dimension_has_a_collector_and_config():
    m = _load_main()
    cfg = json.loads((PROJ / "config" / "n8n_platform_maturity.json").read_text())
    assert set(cfg["dimensions"]) == set(m.ORDER)
    assert set(m.collectors()) == set(m.ORDER)


_ONE_KEY = '{{range .Config.Env}}{{if eq (index (split . "=") 0) "%s"}}{{.}}{{end}}{{end}}'


@pytest.mark.parametrize("fmt,ok", [
    ('{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}', True),
    (_ONE_KEY % "DB_POSTGRESDB_USER", True),
    (_ONE_KEY % "DB_POSTGRESDB_PASSWORD", False),
    (_ONE_KEY % "N8N_ENCRYPTION_KEY", False),
    ("{{.Config.Env}}", False),
    ("{{json .}}", False),
    ("{{.}}", False),
    ('{{index .Config.Labels "com.docker.compose.project.config_files"}}', True),
])
def test_docker_inspect_never_emits_secret_values(fmt, ok):
    assert core.is_read_only(["docker", "inspect", "n8n", "--format", fmt]) is ok
    assert core.is_read_only(["docker", "inspect", "n8n"]) is False


def test_psql_combined_short_flags():
    assert core.is_read_only(["docker", "exec", "db", "psql", "-tAc", "SELECT 1"])
    assert not core.is_read_only(["docker", "exec", "db", "psql", "-tAc", "UPDATE x SET y=1"])

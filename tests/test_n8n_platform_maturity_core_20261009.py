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


_RO = "PGOPTIONS=-c default_transaction_read_only=on"
_NAMES = '{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}'


@pytest.mark.parametrize("argv", [
    ["crontab", "-l"],
    ["/usr/bin/crontab", "-l"],
    ["systemctl", "--user", "list-units", "--failed", "--no-legend", "--plain"],
    ["systemctl", "--user", "show", "x.service", "-p", "ActiveState", "-p", "ExecStart"],
    ["systemctl", "--user", "list-unit-files", "--type=timer", "--no-legend"],
    ["journalctl", "--user", "-u", "x.service", "--since", "2026-10-09 10:00:00 UTC", "--no-pager", "-o", "short-iso"],
    ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"],
    ["docker", "inspect", "m8m-n8n", "--format", _NAMES],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c",
     "SELECT count(*) FROM workflow_entity WHERE active"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c",
     "SELECT rolname, rolsuper FROM pg_roles"],
    ["psql", "-X", "-At", "-h", "localhost", "-U", "trade_ai", "-d", "trade_ai", "-c", "SELECT 1"],
    ["gh", "run", "list", "-R", "o/r", "--workflow", "ci.yml", "--branch", "main", "--json", "conclusion", "-L", "20"],
])
def test_read_only_allowlist_accepts(argv):
    assert core.is_read_only(argv)


@pytest.mark.parametrize("argv", [
    ["crontab", "-e"], ["crontab", "-"], ["crontab", "-r"], ["/tmp/crontab", "-l"], ["./crontab", "-l"],
    ["systemctl", "--user", "restart", "x"], ["systemctl", "restart", "x"], ["systemctl", "--user", "show", "x", "--now"],
    ["journalctl", "--user", "--vacuum-time=1d"], ["journalctl", "--user", "--rotate"], ["journalctl", "-u", "x"],
    ["journalctl", "--user", "-o", "export", "-u", "x"],
    # psql: pinned shape only
    ["docker", "exec", "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c", "SELECT 1"],  # no PGOPTIONS
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c", "DELETE FROM workflow_entity"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c", "SELECT 1; DROP TABLE x"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c",
     "WITH x AS (DELETE FROM t RETURNING *) SELECT 1"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c", "SELECT * INTO t2 FROM t"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c",
     "SELECT pg_terminate_backend(123)"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c",
     "SELECT data FROM credentials_entity"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c", "SELECT 1 \\! id"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-f", "x.sql"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-o", "/tmp/x", "-c", "SELECT 1"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-L", "/tmp/l", "-U", "n8n", "-d", "n8n", "-c", "SELECT 1"],
    ["docker", "exec", "-e", _RO, "db", "psql", "-X", "-At", "-U", "n8n", "-d", "n8n", "-c", "SELECT 1", "-c", "SELECT 2"],
    ["docker", "exec", "-e", _RO, "db", "sh", "-c", "psql -c 'SELECT 1'"],
    ["docker", "exec", "db", "sh", "-c", "env"],
    ["docker", "ps", "-a"], ["docker", "restart", "n8n"], ["docker", "inspect", "n8n"],
    ["psql", "-c", "SELECT 1"], ["psql", "-X", "-At", "-U", "u", "-d", "d", "-c", "UPDATE t SET a=1"],
    ["gh", "api", "repos/o/r/commits/main/check-runs"], ["gh", "api", "-X", "POST", "repos/o/r/issues"],
    ["gh", "pr", "merge", "1"], ["gh", "run", "rerun", "1"], ["gh", "run", "list", "--web"],
    ["git", "log", "-1"], ["git", "push"], ["guard", "log", "20"],
    ["rm", "-rf", "/"], [],
])
def test_read_only_allowlist_refuses(argv):
    assert not core.is_read_only(argv)


def test_psql_argv_builder_is_the_only_accepted_shape():
    d = core.psql_argv("SELECT 1", user="n8n", db="n8n", container="db")
    h = core.psql_argv("SELECT 1", user="trade_ai", db="trade_ai", host="localhost")
    assert core.is_read_only(d) and core.is_read_only(h)
    assert d[2:4] == ["-e", "PGOPTIONS=-c default_transaction_read_only=on"]


def test_default_runner_sets_read_only_pgoptions_and_trusted_path(monkeypatch):
    seen = {}

    class P:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw.get("env") or {}
        return P()
    monkeypatch.setattr(core.subprocess, "run", fake_run)
    monkeypatch.setattr(core.shutil, "which", lambda p: "/usr/bin/" + p)
    core._default_runner(["psql", "-X"], 1.0)
    assert seen["env"]["PGOPTIONS"] == "-c default_transaction_read_only=on"
    assert seen["argv"][0] == "/usr/bin/psql"
    monkeypatch.setattr(core.shutil, "which", lambda p: "/tmp/evil/" + p)
    seen.clear()
    rc, _, err = core._default_runner(["crontab", "-l"], 1.0)
    assert rc == 127 and not seen


def test_probe_redacts_secret_shaped_output(tmp_path):
    out = ("DB_POSTGRESDB_PASSWORD=hunter2hunter2\nN8N_ENCRYPTION_KEY=abcdef0123456789\nDB_POSTGRESDB_USER=n8n\n"
           "Authorization: Bearer abcdefghijklmnopqrstuvwxyz\npostgresql://u:s3cretpw@h/db\nghp_" + "a" * 36)
    p = _probe(tmp_path, runner=lambda argv, t: (0, out, ""))
    _, got, _ = p.run(["crontab", "-l"])
    for secret in ("hunter2hunter2", "abcdef0123456789", "abcdefghijklmnopqrstuvwxyz", "s3cretpw", "a" * 36):
        assert secret not in got
    assert "DB_POSTGRESDB_USER=n8n" in got


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
    cfg = m.load_config()
    latest, hist = m.write_receipt(rec, root, cfg)
    m.write_receipt(rec, root, cfg)
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
    (_ONE_KEY % "SOME_OTHER_NAME", False),
    ("{{.Config.Env}}", False),
    ("{{.Config}}", False),
    ("{{json .}}", False),
    ("{{.}}", False),
    ('{{printf "%v" .Config.Env}}', False),
    ('{{index .Config.Labels "com.docker.compose.project.config_files"}}', True),
])
def test_docker_inspect_never_emits_secret_values(fmt, ok):
    assert core.is_read_only(["docker", "inspect", "n8n", "--format", fmt]) is ok
    assert core.is_read_only(["docker", "inspect", "n8n"]) is False


def test_load_config_fails_loudly(tmp_path):
    m = _load_main()
    with pytest.raises(SystemExit, match="unreadable"):
        m.load_config(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit, match="not valid JSON"):
        m.load_config(bad)
    part = tmp_path / "part.json"
    part.write_text(json.dumps({"target_overall": 8.0, "dimensions": {}}))
    with pytest.raises(SystemExit, match="incomplete"):
        m.load_config(part)
    assert m.load_config()["gate_score"] == 8.0


def test_config_error_scores_unverified(tmp_path):
    m = _load_main()

    def needs(p):
        p.need("registry_truth", "no_such_key")
    rec = m.score_all(_probe(tmp_path), {"registry_truth": needs})
    r = rec["dimensions"][0]
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and "config" in r["notes"][0]


def test_window_hours_honours_config(tmp_path):
    p = _probe(tmp_path)
    assert p.window_hours("reliability") == float(p.config["window_hours"])
    p.config["dimensions"]["reliability"]["window_hours"] = 6
    assert p.window_hours("reliability") == 6.0


# ── round 2 (#1593 review): quoted / Unicode-escaped SQL, catalog tables, systemctl/gh pins, redaction, env ──

_FAKE_AWS_ID = "AK" + "IA" + "ABCDEFGHIJKLMNOP"  # assembled at runtime: a synthetic id, not a credential

R2_REFUSED_SQL = [
    'select "pg_read_file"(\'/etc/passwd\')',
    'select pg_catalog."pg_ls_dir"(\'.\')',
    'select "pg_terminate_backend"(1)',
    'select "pg_sleep"(9999)',
    'select "pg_advisory_lock"(1)',
    'select * from U&"!0063redentials_entity" UESCAPE \'!\'',
    'select U&"!0070g_read_file" UESCAPE \'!\' (\'/etc/passwd\')',
    'select U&"!006co_export" UESCAPE \'!\' (1,\'/tmp/x\')',
    'select U&"!0064blink_exec" UESCAPE \'!\' (\'host=x\',\'drop table t\')',
    'select U&"!0073et_config" UESCAPE \'!\' (\'transaction_read_only\',\'off\',true)',
    'select u&"\\0064elete"',
    "select x uescape '!'",
    'select * from "credentials_entity"',
    "select usename, passwd from pg_shadow",
    "select rolpassword from pg_authid",
    'select rolpassword from "pg_authid"',
    "select * from user_entity",
    "select apikey from user_api_keys",
    "select value from settings",
    'select value from public."settings"',
    "select json_agg(c) from credentials_entity c",
    "select nextval('s')",
    "select setval('s',1)",
    "select txid_current()",
    "select * from t for share",
    "select * from t for key share",
    "select * from t for no key update",
    "WITH m AS (MERGE INTO t USING s ON true WHEN MATCHED THEN DO NOTHING RETURNING *) SELECT 1",
    # r2 probe 2 (Agent A): a comment between a function name and its paren
    "select pg_read_file/**/('x')",
    "select pg_sleep/*x*/(9)",
    "select pg_terminate_backend --c\n(1)",
    "select 1 -- trailing comment",
    "select 1 /* block */",
    "select pg_sleep\n(9)",
]


@pytest.mark.parametrize("sql", R2_REFUSED_SQL)
def test_r2_quoted_unicode_and_catalog_sql_refused(sql):
    assert core.is_safe_sql(sql) is False
    assert core.is_read_only(core.psql_argv(sql, user="u", db="d", container="c")) is False


def test_r2_legit_quoted_columns_still_pass():
    sys.path.insert(0, str(PROJ / "scripts"))
    from n8n_maturity import dims_governance, dims_signal
    sql = dims_signal.n8n_error_argv("c", "u", "d", ["error"], "2026-10-09T00:00:00+00:00")[-1]
    assert '"startedAt"' in sql and core.is_safe_sql(sql)
    assert core.is_safe_sql(dims_governance.PG_ROLES_SQL)
    assert core.is_safe_sql('SELECT count(*) FROM execution_entity WHERE "workflowId" = \'x\'')


@pytest.mark.parametrize("argv,ok", [
    (["systemctl", "--user", "show", "n8n"], False),                               # bare show dumps Environment=
    (["systemctl", "--user", "show", "n8n", "-p", "Environment"], False),
    (["systemctl", "--user", "show", "n8n", "-p", "ActiveState,Environment"], False),
    (["systemctl", "--user", "show", "n8n", "-p", "ActiveState"], True),
    (["systemctl", "--user", "show", "n8n", "-p", "ActiveState,ExecStart"], True),
    (["systemctl", "--user", "show", "-p", "FragmentPath", "-p", "DropInPaths", "x.service"], True),
    (["systemctl", "--user", "list-units", "-p", "ActiveState"], False),
    (["systemctl", "--user", "list-units", "--failed", "--no-legend", "--plain"], True),
    (["gh", "run", "list", "-R", "--hostname"], False),
    (["gh", "run", "list", "-R", "-x"], False),
    (["gh", "run", "list", "--workflow", ".github/x.yml"], False),
    (["gh", "run", "list", "-R", "o/r", "--workflow", "nightly.yml", "--branch", "main"], True),
])
def test_r2_systemctl_show_properties_and_gh_values_pinned(argv, ok):
    assert core.is_read_only(argv) is ok


@pytest.mark.parametrize("raw,secret", [
    ("DB_POSTGRESDB_PASSWORD: hunter2", "hunter2"),
    ('{"password": "hunter2"}', "hunter2"),
    ('{"password":"two words"}', "two words"),
    ('"N8N_ENCRYPTION_KEY":"abcdef123456"', "abcdef123456"),
    ("'db_password': 'x y z'", "x y z"),
    ("N8N_ENCRYPTION_KEY deadbeef", "deadbeef"),
    ("password abc123", "abc123"),
    ("password abc", "abc"),
    ("PGPASSWORD='a b c'", "a b c"),
    ('SECRET = "with spaces"', "with spaces"),
    ("api_key: zzzzzz", "zzzzzz"),
    ("n8n_api_abcdef0123456789abcdef", "n8n_api_abcdef0123456789abcdef"),
    ("key " + _FAKE_AWS_ID + " here", _FAKE_AWS_ID),
    ("Authorization: Bearer abcdefghijklmn", "abcdefghijklmn"),
    ("Environment=N8N_API_KEY=xyz DB_PASS=abc", "xyz"),
])
def test_r2_redaction_colon_json_space_and_token_forms(raw, secret):
    out = core.redact(raw)
    assert secret not in out and "<redacted>" in out


def test_r2_redaction_leaves_crontab_and_journal_prose_parseable():
    for line in ("0 3 * * * cd /x && python3 scripts/refresh_schwab_token.py --apply >> logs/x.log 2>&1",
                 "token refreshed ok",
                 "Oct 09 h systemd[1]: portfolio-server.service: Main process exited, code=killed, status=9/KILL"):
        assert core.redact(line) == line


def test_r2_default_runner_drops_pg_service_env(monkeypatch):
    seen = {}

    class _P:
        returncode, stdout, stderr = 0, "1\n", ""

    def fake_run(argv, **kw):
        seen.update(kw["env"])
        return _P()

    monkeypatch.setenv("PGSERVICE", "evil")
    monkeypatch.setenv("PGSERVICEFILE", "/tmp/evil.conf")
    monkeypatch.setattr(core, "resolve_program", lambda prog: "/usr/bin/psql")
    monkeypatch.setattr(core.subprocess, "run", fake_run)
    rc, out, _ = core._default_runner(["psql", "-X", "-At", "-U", "u", "-d", "d", "-c", "select 1"], 5)
    assert rc == 0 and out == "1\n"
    assert "PGSERVICE" not in seen and "PGSERVICEFILE" not in seen
    assert seen["PGOPTIONS"] == core.PG_READ_ONLY_OPTIONS


def test_r2_cap_on_fail_is_config_driven():
    cfg = {"gate_cap": 7.9}
    assert core.cap_on_fail(cfg, 9.5, False) == 7.9 and core.cap_on_fail(cfg, 9.5, True) == 9.5
    assert core.cap_on_fail(cfg, 3.0, False) == 3.0
    with pytest.raises(core.ConfigError):
        core.cap_on_fail({}, 9.0, False)


def test_r2_every_collector_query_passes_is_safe_sql():
    """The scorer's own fixed SQL carries no comments, so refusing ``--`` and ``/*`` costs nothing."""
    import datetime as _d
    sys.path.insert(0, str(PROJ / "scripts"))
    import n8n_live_inventory as inv
    from n8n_maturity import dims_governance, dims_healing, dims_signal
    since = _d.datetime(2026, 10, 9, tzinfo=_d.timezone.utc)
    queries = [dims_signal.n8n_error_argv("c", "u", "d", ["error", "crashed"], since.isoformat())[-1],
               dims_governance.PG_ROLES_SQL,
               inv.WORKFLOW_LIST_SQL, inv.PUBLISH_HISTORY_SQL, inv.PUBLISHED_VERSION_SQL, inv.VERSION_HISTORY_SQL]
    doc = json.loads((PROJ / "config" / "self_healing_mechanisms.json").read_text(encoding="utf-8"))
    psql_srcs = [m["evidence_source"] for m in doc["mechanisms"] if m["evidence_source"].get("kind") == "psql"]
    assert psql_srcs, "inventory has psql sources to check"
    queries += [dims_healing.psql_sql(ev, since) for ev in psql_srcs]
    for q in queries:
        assert q and "--" not in q and "/*" not in q
        assert core.is_safe_sql(q), q[:80]

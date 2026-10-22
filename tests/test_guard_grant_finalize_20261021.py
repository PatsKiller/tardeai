"""Grant mechanics, operator rulings of 2026-10-21 ("approve all your recommendations on the patches").

1. A Telegram /approve (code or button) for a tier that already has an active grant is REFUSED; the
   reply names the grant (tier, id, uses left, expiry) and the exact `bin/guard grant ... --replace`
   command, and the request stays PENDING.
3. Rows closed more than 90 days ago move to the append-only grants.archive.jsonl -- never deleted,
   atomic under the ledger lock, crash-safe, idempotent; an archived id is reported as archived.
4. install-guardrails.sh installs guard-lib.sh only from the canonical file, or refuses.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".cursor" / "hooks"
LEDGER_PY = HOOKS / "guard_ledger.py"
for p in (str(HOOKS), str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import guard_ledger as gl  # noqa: E402
from scripts.lib import guard_remote_approval as gra  # noqa: E402

DAY = 86400
GID = "a" * 32


@pytest.fixture
def adir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "approvals"
    d.mkdir(mode=0o700)
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(d))
    monkeypatch.setenv("GUARD_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", raising=False)
    return d


def _rows(adir: Path) -> dict:
    return json.loads((adir / "grants.json").read_text())


def _status(rid: str) -> str:
    return next(r for r in gra._load()["requests"] if r["request_id"] == rid)["status"]


# ── 1. remote approval with an active grant: refuse, name it, give the --replace CLI ──────────


def test_button_approval_refused_while_a_grant_is_active(adir):
    g = gl.ledger_create_grant_row("git-push", expires=int(time.time()) + 3600, uses=7, reason="push wt/a", adir=adir)
    req = gra.mint_request("git-push", seconds=1800, uses=4, reason="push wt/b")
    out = gra.settle_by_request_id(req["request_id"], approve=True, chat_id="42", allowed_chats={"42"})
    assert out["ok"] is False and out["reason"] == "ACTIVE_GRANT_EXISTS"
    msg = out["message"]
    assert "active `git-push` grant already exists" in msg
    assert f"id: {g['grant_id']}" in msg and "uses left: 7" in msg
    assert "expires: " in msg and "min left" in msg
    assert (f"{gra.GUARD_BIN} grant git-push --for 1800 --uses 4 --reason "
            f"'push wt/b [remote_request_id={req['request_id']} chat=42 via=button]' --replace") in msg
    assert f"revoke git-push --grant-id {g['grant_id']}" in msg
    # Nothing settled, nothing granted: the request is still PENDING, the ledger untouched.
    assert _status(req["request_id"]) == "PENDING"
    assert gl.ledger_list(adir)["active"]["git-push"]["grant_id"] == g["grant_id"]
    assert len(_rows(adir)) == 1
    # Deny still works while a grant is active.
    assert gra.settle_by_request_id(req["request_id"], approve=False, chat_id="42", allowed_chats={"42"})["ok"]


def test_code_approval_refused_then_allowed_after_revoke(adir):
    g = gl.ledger_create_grant_row("cron", expires=int(time.time()) + 600, uses=-1, reason="x", adir=adir)
    req = gra.mint_request("cron", seconds=600, uses=2, reason="install lane")
    out = gra.verify_and_consume(req["code"], chat_id="42", allowed_chats={"42"})
    assert out["reason"] == "ACTIVE_GRANT_EXISTS" and "uses left: unlimited" in out["message"]
    assert "--replace" in out["message"] and _status(req["request_id"]) == "PENDING"
    gl.ledger_revoke("cron", adir=adir, grant_id=g["grant_id"])
    again = gra.verify_and_consume(req["code"], chat_id="42", allowed_chats={"42"})
    assert again["ok"] is True and _status(req["request_id"]) == "APPROVED"


def test_ambiguous_tier_is_refused_with_doctor_hint(adir):
    now = int(time.time())
    (adir / "grants.json").write_text(json.dumps({
        f"cron@{c * 32}": {"tier": "cron", "grant_id": c * 32, "expires": now + 600, "uses": 1, "reason": c,
                           "status": "active"} for c in "ab"}))
    req = gra.mint_request("cron", seconds=600, uses=1, reason="x")
    out = gra.settle_by_request_id(req["request_id"], approve=True, chat_id="42", allowed_chats={"42"})
    assert out["reason"] == "ACTIVE_GRANT_EXISTS" and "MORE THAN ONE active grant" in out["message"]
    assert "doctor" in out["message"] and "--replace" in out["message"]


def test_poller_replies_with_the_refusal_and_grants_nothing(adir, monkeypatch):
    import run_telegram_callback_poller as poller
    gl.ledger_create_grant_row("service", expires=int(time.time()) + 600, uses=3, reason="restart x", adir=adir)
    req = gra.mint_request("service", seconds=600, uses=1, reason="restart y")
    sent = []
    monkeypatch.setattr(poller, "_send_reply", lambda chat, reply_to, text: sent.append(text))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("bin/guard grant must not run"))
    poller._handle_guard_approval({"message_id": 9, "from": {"id": 1}}, f"/approve {req['code']}", "42")
    assert len(sent) == 1 and "active `service` grant already exists" in sent[0] and "--replace" in sent[0]
    assert _status(req["request_id"]) == "PENDING"


def test_button_handler_alerts_and_sends_the_full_refusal(adir, monkeypatch):
    import telegram_callback_handler as handler
    g = gl.ledger_create_grant_row("config-write", expires=int(time.time()) + 600, uses=2, reason="x", adir=adir)
    req = gra.mint_request("config-write", seconds=600, uses=1, reason="edit y")
    alerts, messages = [], []
    monkeypatch.setattr(handler, "answer_callback", lambda cb_id, text, show_alert=False: alerts.append(text))
    monkeypatch.setattr(handler, "send_reply", lambda chat, mid, text: messages.append(text))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("bin/guard grant must not run"))
    handler.handle_callback_query({"id": "cb1", "data": f"gapprove:{req['request_id']}",
                                   "from": {"id": 1, "username": "op"},
                                   "message": {"chat": {"id": 42}, "message_id": 77}})
    assert alerts and "active config-write grant exists" in alerts[0] and len(alerts[0]) <= 200
    assert len(messages) == 1 and f"id: {g['grant_id']}" in messages[0] and "--replace" in messages[0]
    assert _status(req["request_id"]) == "PENDING"


def test_no_active_grant_settles_as_before(adir):
    gl.ledger_create_grant("git-push", expires=int(time.time()) - 5, uses=3, reason="expired", adir=adir)
    req = gra.mint_request("git-push", seconds=600, uses=1, reason="x")
    assert gra.settle_by_request_id(req["request_id"], approve=True, chat_id="42", allowed_chats={"42"})["ok"]


# ── 3. archive rows closed > 90 days ago ──────────────────────────────────────────────────────


def _row(tier: str, gid: str, **kw) -> tuple[str, dict]:
    base = {"tier": tier, "grant_id": gid, "expires": 0, "uses": 0, "reason": "r", "created_at": 1,
            "status": "active"}
    base.update(kw)
    return f"{tier}@{gid}", base


def _seed(adir: Path, now: int) -> dict:
    rows = dict([
        _row("cron", "1" * 32, status="revoked", closed_at=now - 90 * DAY - 1, expires=now + DAY),     # due
        _row("cron", "2" * 32, status="revoked", closed_at=now - 90 * DAY, expires=now + DAY),         # boundary
        _row("git-push", "3" * 32, expires=now - 91 * DAY, uses=4),                                    # expired, due
        _row("git-push", "4" * 32, expires=now + DAY, uses=0, exhausted_at=now - 100 * DAY),           # exhausted, due
        _row("service", "5" * 32, expires=now - 10 * DAY, uses=2),                                     # expired recently
        _row("service", "6" * 32, expires=now + DAY, uses=3),                                          # ACTIVE
        _row("llm", "7" * 32, expires=now - 200 * DAY, uses=0),                                        # exhausted, no stamp
    ])
    (adir / "grants.json").write_text(json.dumps(rows))
    return rows


def test_archive_ninety_day_boundary(adir):
    now = int(time.time())
    _seed(adir, now)
    out = gl.ledger_archive_closed(adir, now=now)
    due = {k.split("@")[1][0] for k in out["due"]}
    assert due == {"1", "3", "4", "7"}  # exactly 90 days ago is NOT "more than 90 days"
    left = {r["grant_id"][0] for r in _rows(adir).values()}
    assert left == {"2", "5", "6"}
    archived, torn = gl.read_archive(adir)
    assert torn == 0 and {g[0] for g in archived} == {"1", "3", "4", "7"}
    rec = archived["1" * 32]
    assert rec["schema"] == gl.ARCHIVE_SCHEMA and rec["row"]["status"] == "revoked" and rec["archived_at"] == now
    assert (adir / gl.ARCHIVE_NAME).stat().st_mode & 0o777 == 0o600
    # One second later the boundary row is due too.
    assert [k[-32:] for k in gl.ledger_archive_closed(adir, now=now + 1)["due"]] == ["2" * 32]


def test_archive_dry_run_writes_nothing(adir):
    now = int(time.time())
    _seed(adir, now)
    before = (adir / "grants.json").read_bytes()
    out = gl.ledger_archive_closed(adir, now=now, dry_run=True)
    assert len(out["due"]) == 4 and (adir / "grants.json").read_bytes() == before
    assert not (adir / gl.ARCHIVE_NAME).exists()


def test_archive_is_idempotent(adir):
    now = int(time.time())
    _seed(adir, now)
    gl.ledger_archive_closed(adir, now=now)
    after_first = ((adir / "grants.json").read_bytes(), (adir / gl.ARCHIVE_NAME).read_bytes())
    second = gl.ledger_archive_closed(adir, now=now)
    assert second["due"] == [] and second["appended"] == 0
    assert ((adir / "grants.json").read_bytes(), (adir / gl.ARCHIVE_NAME).read_bytes()) == after_first


def test_crash_between_append_and_ledger_rewrite_recovers_without_duplicates(adir, tmp_path):
    now = int(time.time())
    _seed(adir, now)
    before = (adir / "grants.json").read_bytes()
    env = {**os.environ, "GUARD_APPROVALS_DIR": str(adir), "GUARD_AUDIT_LOG": str(tmp_path / "a.jsonl"),
           "GUARD_LEDGER_CRASH": "archive_after_append"}
    p = subprocess.run([sys.executable, str(LEDGER_PY), "archive"], env=env, capture_output=True, text=True)
    assert p.returncode == 90
    assert (adir / "grants.json").read_bytes() == before            # ledger untouched
    lines_after_crash = (adir / gl.ARCHIVE_NAME).read_text().count("\n")
    assert len(gl.read_archive(adir)[0]) == lines_after_crash >= 4   # appended before the crash
    # Rows are now in both places: doctor says so, nothing is lost, the next run finishes the move.
    assert gl.doctor(adir)["archive_pending_removal"] == lines_after_crash
    out = gl.ledger_archive_closed(adir, now=int(time.time()))
    assert out["appended"] == 0 and out["removed_from_ledger"] == lines_after_crash
    assert (adir / gl.ARCHIVE_NAME).read_text().count("\n") == lines_after_crash
    assert gl.doctor(adir)["archive_pending_removal"] == 0


def test_torn_archive_tail_is_isolated_and_the_row_reappended(adir):
    now = int(time.time())
    _seed(adir, now)
    (adir / gl.ARCHIVE_NAME).write_text('{"schema":"GuardLedgerArchive@v1","grant_id":"1111')  # crash mid-append
    gl.ledger_archive_closed(adir, now=now)
    archived, torn = gl.read_archive(adir)
    assert torn == 1 and "1" * 32 in archived and len(archived) == 4
    assert gl.doctor(adir)["archive_torn_lines"] == 1


def test_archived_id_lookup_is_archived_not_missing(adir):
    now = int(time.time())
    _seed(adir, now)
    gl.ledger_archive_closed(adir, now=now)
    hit = gl.ledger_lookup("1" * 32, adir)
    assert hit["status"] == "archived" and hit["tier"] == "cron" and hit["archived_at"] == now
    assert gl.ledger_lookup("6" * 32, adir)["status"] == "active"
    assert gl.ledger_lookup("5" * 32, adir)["status"] == "inactive"
    assert gl.ledger_lookup("f" * 32, adir)["status"] == "missing"
    r = gl.ledger_consume_grant("cron", adir=adir, grant_id="1" * 32)
    assert r["consumed"] is False and r["error"] == "grant_archived"
    with pytest.raises(gl.LedgerError) as e:
        gl.ledger_revoke("cron", adir=adir, grant_id="1" * 32)
    assert e.value.code == "grant_archived"
    rc = subprocess.run([sys.executable, str(LEDGER_PY), "lookup", "--grant-id", "1" * 32], capture_output=True,
                        text=True, env={**os.environ, "GUARD_APPROVALS_DIR": str(adir)})
    assert rc.returncode == 0 and json.loads(rc.stdout)["status"] == "archived"


def test_doctor_reports_archive_counts(adir):
    now = int(time.time())
    _seed(adir, now)
    d = gl.doctor(adir)
    # doctor reads the wall clock: the row closed exactly 90 days before `now` becomes due a second later.
    assert d["archive_count"] == 0 and d["archivable_rows"] in (4, 5) and d["ok"] is True
    gl.ledger_archive_closed(adir, now=now + 1)  # the boundary row is due too
    d = gl.doctor(adir)
    assert d["archive_count"] == 5 and d["archivable_rows"] == 0 and d["archive_path"].endswith(gl.ARCHIVE_NAME)


def test_exhaustion_is_stamped_and_cli_refuses_a_short_window(adir):
    gl.ledger_create_grant("cron", expires=int(time.time()) + 600, uses=1, reason="x", adir=adir)
    gl.ledger_consume_grant("cron", adir=adir)
    (row,) = _rows(adir).values()
    assert row["uses"] == 0 and abs(row["exhausted_at"] - time.time()) < 60
    p = subprocess.run([sys.executable, str(LEDGER_PY), "archive", "--days", "1"], capture_output=True, text=True,
                       env={**os.environ, "GUARD_APPROVALS_DIR": str(adir)})
    assert p.returncode == 1 and json.loads(p.stdout)["error"] == "invalid_days"


# ── 4. install-guardrails.sh installs guard-lib.sh only from the canonical file ───────────────


def _fake_checkout(tmp: Path, *, canonical: bool) -> Path:
    repo = tmp / "checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    shutil.copy2(ROOT / "install-guardrails.sh", repo / "install-guardrails.sh")
    if canonical:
        shutil.copytree(HOOKS, repo / ".cursor" / "hooks")
        (repo / "bin").mkdir()
        shutil.copy2(ROOT / "bin" / "guard", repo / "bin" / "guard")
    return repo


def _install(repo: Path, tmp: Path) -> subprocess.CompletedProcess:
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "GUARD_APPROVALS_DIR": str(tmp / "approvals"),
           "GUARD_AUDIT_LOG": str(tmp / "audit.jsonl"), "TMPDIR": str(tmp)}
    return subprocess.run(["bash", "install-guardrails.sh"], cwd=repo, env=env, capture_output=True, text=True,
                          timeout=300)


@pytest.mark.skipif(shutil.which("jq") is None, reason="the installer needs jq")
def test_installer_installs_the_canonical_guard_lib_inside_a_checkout(tmp_path):
    repo = _fake_checkout(tmp_path, canonical=True)
    p = _install(repo, tmp_path)
    assert "canonical guard-lib.sh" in p.stdout, p.stdout + p.stderr
    for name in ("guard-lib.sh", "guard-shell.sh", "guard-write.sh", "guard-read.sh", "guard_ledger.py"):
        assert (repo / ".cursor/hooks" / name).read_bytes() == (HOOKS / name).read_bytes(), name
    assert (repo / "bin/guard").read_bytes() == (ROOT / "bin/guard").read_bytes()


@pytest.mark.skipif(shutil.which("jq") is None, reason="the installer needs jq")
def test_installer_refuses_without_a_canonical_guard_lib(tmp_path):
    repo = _fake_checkout(tmp_path, canonical=False)
    p = _install(repo, tmp_path)
    assert p.returncode == 1 and "REFUSING: no canonical .cursor/hooks/guard-lib.sh" in p.stdout
    assert not (repo / ".cursor/hooks/guard-lib.sh").exists()


def test_installer_embeds_no_guard_lib():
    src = (ROOT / "install-guardrails.sh").read_text(encoding="utf-8")
    assert "cat > .cursor/hooks/guard-lib.sh" not in src and "LIBEOF" not in src

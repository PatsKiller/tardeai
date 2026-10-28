"""Telegram remote guard grants are retired — the CODE, end to end (2026-10-27).

Operator-ratified on PR #2185 (``APPROVE_AGENTS_POLICY_23_0_0 2185 c366dd8d165c7eedf286d18604af8b0a11fe85db``,
PR comment by PatsKiller 2026-10-26). #2185 never merged (the release train it was queued for was retired and AGENTS.md
moved on), so this carries its code onto main. The policy text travels in a separate AGENTS.md PR; these tests pin
behaviour only and never read AGENTS.md, so they hold whatever version number that text lands under.

Pinned here, against the production constant (no monkeypatching of TELEGRAM_REMOTE_GRANT_STATUS):

1. ``TELEGRAM_REMOTE_GRANT_STATUS == "RETIRED"``; mint raises, ``/approve <CODE>`` and an Approve tap refuse with
   ``TELEGRAM_GRANT_RETIRED`` and never run ``bin/guard grant``; deny still clears a leftover PENDING row.
2. ``bin/guard request`` (scripts/guard_request_approval.py) exits 2, sends nothing; ``--dry-run`` says it would refuse.
3. The PR-merge guard bridge (a ``telegram`` guard grant per tap) refuses before minting, and the per-PR CLIs default
   to the native ``prmapprove`` path, which grants nothing.
4. What stays: keyboard ``bin/guard grant`` and Ops → Controls ``grant.issue`` (which drives ``bin/guard grant``) do not
   go through guard_remote_approval, and bin/guard still lists every tier Ops → Controls offers.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import guard_remote_approval as gra  # noqa: E402

COVERS = ["scripts/lib/guard_remote_approval.py", "scripts/guard_request_approval.py",
          "scripts/telegram_callback_handler.py", "scripts/run_telegram_callback_poller.py",
          "scripts/lib/pr_merge_telegram.py", "scripts/request_pr_merge_approve.py",
          "scripts/notify_pr_merge_ready.py", "bin/guard"]

CHAT = "1000000001"  # synthetic; never a production identifier


@pytest.fixture
def adir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "approvals"
    d.mkdir(mode=0o700)
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(d))
    monkeypatch.setenv("GUARD_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.delenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", raising=False)
    return d


def _leftover_pending(monkeypatch) -> dict:
    """A PENDING row as it would exist on the host from before retirement."""
    with monkeypatch.context() as m:
        m.setattr(gra, "TELEGRAM_REMOTE_GRANT_STATUS", "LEGACY_TEST")
        return gra.mint_request("telegram", seconds=600, uses=1, reason="left over from before retirement")


def _row(rid: str) -> dict:
    return next(r for r in gra._load()["requests"] if r["request_id"] == rid)


def _no_grant(*a, **k):
    pytest.fail(f"bin/guard grant must not run for a Telegram approval: {a!r}")


# ── 1. production status and refusals ───────────────────────────────────────────────────────


def test_production_status_is_retired():
    assert gra.TELEGRAM_REMOTE_GRANT_STATUS == "RETIRED"
    assert gra.telegram_remote_grants_retired() is True
    src = (ROOT / "scripts" / "lib" / "guard_remote_approval.py").read_text(encoding="utf-8")
    assert len(re.findall(r'^TELEGRAM_REMOTE_GRANT_STATUS = "RETIRED"$', src, re.M)) == 1


def test_retired_message_names_the_paths_that_stay_and_no_retired_train():
    msg = gra.RETIRED_MSG
    assert "retired" in msg.lower() and "bin/guard grant" in msg and "Ops → Controls" in msg
    for gone in ("train", "Run now"):
        assert gone not in msg, f"retirement message points at the retired release train: {gone!r}"


def test_mint_refuses_in_production(adir):
    with pytest.raises(ValueError, match="retired"):
        gra.mint_request("git-push", seconds=600, uses=1, reason="must refuse")
    assert not gra.requests_path().exists()


def test_approve_tap_on_a_leftover_request_refuses_and_runs_no_grant(adir, monkeypatch):
    import telegram_callback_handler as handler

    req = _leftover_pending(monkeypatch)
    alerts: list[str] = []
    monkeypatch.setattr(handler, "answer_callback", lambda cb_id, text, show_alert=False: alerts.append(text))
    monkeypatch.setattr(handler, "send_reply", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", _no_grant)
    out = handler.handle_callback_query({"id": "cb1", "data": f"gapprove:{req['request_id']}",
                                         "from": {"id": int(CHAT), "username": "op"},
                                         "message": {"chat": {"id": int(CHAT)}, "message_id": 7}})
    assert out["outcome"] == "REFUSED" and out["reason"] == "TELEGRAM_GRANT_RETIRED"
    assert alerts and "TELEGRAM_GRANT_RETIRED" in alerts[-1]
    assert _row(req["request_id"])["status"] == "PENDING"


def test_approve_code_on_a_leftover_request_refuses_and_runs_no_grant(adir, monkeypatch):
    import run_telegram_callback_poller as poller

    req = _leftover_pending(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(poller, "_send_reply", lambda chat, reply_to, text: sent.append(text))
    monkeypatch.setattr(subprocess, "run", _no_grant)
    poller._handle_guard_approval({"message_id": 9, "from": {"id": int(CHAT)}}, f"/approve {req['code']}", CHAT)
    assert sent and "TELEGRAM_GRANT_RETIRED" in sent[-1]
    assert _row(req["request_id"])["status"] == "PENDING"


def test_deny_still_clears_a_leftover_request(adir, monkeypatch):
    import telegram_callback_handler as handler

    req = _leftover_pending(monkeypatch)
    monkeypatch.setattr(handler, "answer_callback", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", _no_grant)
    out = handler.handle_callback_query({"id": "cb2", "data": f"gdeny:{req['request_id']}",
                                         "from": {"id": int(CHAT)},
                                         "message": {"chat": {"id": int(CHAT)}, "message_id": 8}})
    assert out["outcome"] == "DENIED"
    assert _row(req["request_id"])["status"] == "DENIED_BY_OPERATOR"


# ── 2. bin/guard request ─────────────────────────────────────────────────────────────────────


def _run_request(monkeypatch, *argv) -> int:
    import guard_request_approval as g

    monkeypatch.setattr(g, "_send", lambda *a, **k: pytest.fail("a retired request must not reach Telegram"))
    monkeypatch.setattr(sys, "argv", ["guard_request_approval.py", *argv])
    return g.main()


def test_guard_request_exits_2_and_sends_nothing(adir, monkeypatch, capsys):
    assert _run_request(monkeypatch, "git-push", "--for", "30m", "--uses", "3", "--reason", "must refuse") == 2
    err = capsys.readouterr().err
    assert err.startswith("REFUSED:") and "bin/guard grant" in err
    assert not gra.requests_path().exists()


def test_guard_request_dry_run_says_it_would_refuse(adir, monkeypatch, capsys):
    assert _run_request(monkeypatch, "git-push", "--for", "30m", "--reason", "probe", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "WOULD REFUSE" in out and "WOULD REQUEST" not in out


def test_bin_guard_help_marks_request_retired_and_keeps_grant():
    text = (ROOT / "bin" / "guard").read_text(encoding="utf-8")
    help_block = "\n".join(text.splitlines()[1:17])  # what `bin/guard` prints for an unknown command
    assert re.search(r"guard request <tier> \[opts\]\s+RETIRED", help_block)
    assert "guard grant <tier> [opts]" in help_block
    assert "they reply /approve <CODE>" not in text


# ── 3. the PR-merge guard bridge ─────────────────────────────────────────────────────────────


@pytest.fixture
def pmt(tmp_path, monkeypatch):
    monkeypatch.setenv("PR_MERGE_TELEGRAM_DIR", str(tmp_path / "pr_merge_telegram"))
    (tmp_path / "pr_merge_telegram").mkdir()
    from scripts.lib import pr_merge_telegram as mod

    return mod


@pytest.mark.parametrize("dry_run", [False, True])
def test_guard_bridge_refuses_before_minting(adir, pmt, monkeypatch, dry_run):
    monkeypatch.setattr(pmt, "send_interrupt", lambda *a, **k: pytest.fail("must not send"))
    out = pmt.mint_and_notify_via_guard(pr_number=7, title="t", head_sha="abcdef0123", url="u", dry_run=dry_run)
    assert out["ok"] is False and out["reason"] == "GUARD_BRIDGE_RETIRED"
    assert pmt._load() == [], "a refused bridge must not leave a PENDING pr_merge row"
    assert not gra.requests_path().exists()


def test_per_pr_clis_default_to_native(pmt, monkeypatch):
    import notify_pr_merge_ready as npr
    import request_pr_merge_approve as rpa

    monkeypatch.delenv("PR_MERGE_TELEGRAM_VIA_GUARD", raising=False)
    assert pmt.guard_bridge_retired() is True
    calls: list[str] = []
    monkeypatch.setattr(pmt, "mint_and_notify", lambda **kw: calls.append("native") or {"ok": True, "pr_number": 5})
    monkeypatch.setattr(pmt, "mint_and_notify_via_guard", lambda **kw: calls.append("guard") or {"ok": False})
    monkeypatch.setattr(rpa, "_pr_view", lambda pr, repo: {"number": 5, "title": "t", "url": "u", "headRefOid": "a" * 40,
                                                           "state": "OPEN", "labels": [], "files": []})
    assert rpa.main(["--pr", "5", "--single", "--json"]) == 0
    assert calls == ["native"]

    monkeypatch.setattr(npr, "_list_prs", lambda repo: [{"number": 6, "title": "t", "url": "u", "headRefOid": "b" * 40,
                                                         "isDraft": False, "labels": []}])
    monkeypatch.setattr(pmt, "find_pending", lambda *a, **k: None)
    monkeypatch.setattr(pmt, "pr_check_rollup_green", lambda *a, **k: (True, {}))
    monkeypatch.setattr(pmt, "write_notify_receipt", lambda summary: None)
    assert npr.main(["--apply", "--legacy-per-pr", "--json"]) == 0
    assert calls == ["native", "native"]


# ── 4. what stays: keyboard bin/guard grant and Ops → Controls ───────────────────────────────


def test_keyboard_and_ops_grant_paths_do_not_import_the_retired_module():
    for rel in (".cursor/hooks/guard-lib.sh", ".cursor/hooks/guard_ledger.py",
                "scripts/lib/ops_controls_core.py", "scripts/lib/ops_controls_api.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "guard_remote_approval" not in text, rel
        assert "guard_request_approval" not in text, rel
    # bin/guard: only the retired `request` branch may reach the Telegram request script; `grant` never does.
    guard = (ROOT / "bin" / "guard").read_text(encoding="utf-8")
    grant_fn = re.search(r"^cmd_grant\(\) \{.*?^\}", guard, re.M | re.S)
    assert grant_fn, "cmd_grant() not found in bin/guard"
    code = "\n".join(ln for ln in grant_fn.group(0).splitlines() if not ln.lstrip().startswith("#"))
    for frag in ("guard_remote_approval", "guard_request_approval", "telegram_alert", "send_telegram"):
        assert frag not in code, frag
    execs = re.findall(r"^\s*exec .*guard_\w+approval\.py.*$", guard, re.M)
    assert execs == ['    exec "$_py" "$ROOT/scripts/guard_request_approval.py" "$@" ;;'], execs


def test_bin_guard_still_offers_every_tier_ops_controls_parses():
    text = (ROOT / "bin" / "guard").read_text(encoding="utf-8")
    m = re.search(r'^ALL_TIERS="([^"]+)"', text, re.M)  # ops_controls_core.Hosts.guard_tiers reads exactly this
    assert m, "Ops → Controls grant.issue reads ALL_TIERS from bin/guard"
    tiers = set(m.group(1).split())
    for t in ("git-push", "release-write", "telegram", "cron", "broker-read", "execution-ops", "config-write"):
        assert t in tiers, t


def test_ops_controls_grant_issue_still_drives_bin_guard_grant():
    src = (ROOT / "scripts" / "lib" / "ops_controls_core.py").read_text(encoding="utf-8")
    assert 'if kind == "grant.issue":' in src
    assert '"argv": ["grant", tier, "--for"' in src and '"--yes"]' in src


def test_bin_guard_grant_still_issues_at_the_keyboard(tmp_path):
    """The keyboard path, run for real against an isolated ledger (needs jq, like bin/guard itself)."""
    import shutil

    if shutil.which("jq") is None:
        pytest.skip("bin/guard needs jq")
    adir = tmp_path / "approvals"
    adir.mkdir(mode=0o700)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tmp_path), "GUARD_APPROVALS_DIR": str(adir),
           "GUARD_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    p = subprocess.run(["bash", str(ROOT / "bin" / "guard"), "grant", "cron", "--for", "10m", "--uses", "1",
                        "--reason", "keyboard path stays", "--yes"], capture_output=True, text=True, env=env,
                       timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    sys.path.insert(0, str(ROOT / ".cursor" / "hooks"))
    import guard_ledger as gl

    active = gl.ledger_list(adir)["active"]
    assert "cron" in active and active["cron"]["grant_id"]
    assert json.dumps(active)  # serialisable ledger row, not a sentinel

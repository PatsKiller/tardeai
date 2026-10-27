"""Hermetic tests: one-tap Telegram PR merge digest + Mergify hold single source (2026-10-27).

COVERS = ["scripts/lib/pr_merge_digest.py", "scripts/lib/merge_hold_paths.py", "scripts/pr_merge_digest.py"]

Synthetic PRs only (public repo: no real holdings, names or tokens). gh and Telegram are stubbed;
nothing here reaches GitHub, Telegram or production state.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/lib/pr_merge_digest.py", "scripts/lib/merge_hold_paths.py", "scripts/pr_merge_digest.py"]

from scripts.lib import merge_hold_paths as mhp  # noqa: E402
from scripts.lib import pr_merge_digest as pmd  # noqa: E402
from scripts.lib import pr_merge_telegram as pmt  # noqa: E402

GREEN = [{"__typename": "CheckRun", "name": c, "conclusion": "SUCCESS", "status": "COMPLETED"} for c in pmt.REQUIRED_CHECKS]
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _pr(n, *, head=SHA_A, files=("docs/x.md",), labels=(), draft=False, checks=GREEN, title=None, body="## Summary\nDoes a thing.\n"):
    return {
        "number": n, "title": title or f"Synthetic change {n}", "url": f"https://example.test/pull/{n}",
        "headRefOid": head, "isDraft": draft, "labels": [{"name": x} for x in labels],
        "body": body, "files": [{"path": f} for f in files], "changedFiles": len(files),
        "statusCheckRollup": list(checks), "baseRefName": "main",
    }


class FakeGH:
    def __init__(self, open_prs, merged=()):
        self.open = {p["number"]: p for p in open_prs}
        self.merged = list(merged)
        self.labels_added: list[int] = []
        self.labels_removed: list[int] = []
        self.comments: list[tuple[int, str]] = []

    def list_open(self, repo, limit):
        return list(self.open.values())

    def view(self, repo, n):
        p = self.open.get(n)
        if not p:
            return {"number": n, "state": "MERGED", "headRefOid": "", "isDraft": False, "labels": []}
        return {"number": n, "state": "OPEN", "headRefOid": p["headRefOid"], "isDraft": p["isDraft"], "labels": p["labels"]}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PR_MERGE_TELEGRAM_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    (tmp_path / "store").mkdir()
    sent: list[dict] = []

    def fake_send(message, *, priority, reply_markup=None):
        sent.append({"message": message, "priority": priority, "reply_markup": reply_markup})
        return True, [str(1000 + len(sent))], "accepted"

    monkeypatch.setattr(pmd, "_send", fake_send)

    def no_gh(*a, **k):  # any unstubbed gh call is a test bug
        raise AssertionError(f"unstubbed gh call {a}")

    monkeypatch.setattr(pmd, "_gh", no_gh)
    monkeypatch.setattr(pmt, "_gh_json", no_gh)

    def install(gh: FakeGH):
        monkeypatch.setattr(pmd, "list_open_prs", gh.list_open)
        monkeypatch.setattr(pmd, "pr_view", gh.view)
        monkeypatch.setattr(pmd, "list_merged_prs", lambda repo, limit=50: gh.merged)

        def add(pr, *, repo=pmt.DEFAULT_REPO):
            gh.labels_added.append(pr)
            gh.open[pr]["labels"].append({"name": pmt.LABEL})
            return {"ok": True}

        def rem(pr, *, repo=pmt.DEFAULT_REPO):
            gh.labels_removed.append(pr)
            gh.open[pr]["labels"] = [x for x in gh.open[pr]["labels"] if x["name"] != pmt.LABEL]
            return {"ok": True}

        monkeypatch.setattr(pmt, "add_operator_merge_label", add)
        monkeypatch.setattr(pmt, "remove_operator_merge_label", rem)
        monkeypatch.setattr(pmt, "comment_on_pr", lambda pr, body, *, repo=pmt.DEFAULT_REPO: gh.comments.append((pr, body)) or {"ok": True})
        return gh

    return {"sent": sent, "install": install, "tmp": tmp_path}


# ── classification ───────────────────────────────────────────────────────────


def test_digest_lists_ready_and_needs_operator_one_message(env):
    gh = env["install"](FakeGH([
        _pr(1),
        _pr(2, files=("scripts/lib/x.py", "config/y.json"), labels=("shared-infra",)),
        _pr(3, draft=True),
        _pr(4, checks=[dict(GREEN[0], conclusion="FAILURE")] + GREEN[1:]),
        _pr(5, files=("AGENTS.md",)),
        _pr(6, files=("scripts/brokers/z.py",)),
        _pr(7, labels=("held",)),
        _pr(8, labels=(pmt.LABEL,)),
        _pr(9, files=("migrations/001_x.sql",)),
    ]))
    out = pmd.run_digest(apply=True)
    assert out["action"] == "sent"
    assert out["ready"] == [1, 2, 9]
    assert out["needs_operator"] == [5, 6, 7]
    skipped = {s["pr"]: s["reason"] for s in out["skipped"]}
    assert skipped == {3: "draft", 4: "checks_not_green", 8: "already_approved"}
    assert len(env["sent"]) == 1
    msg = env["sent"][0]
    assert msg["priority"] == "P1"
    btn = msg["reply_markup"]["inline_keyboard"]
    assert btn[0][0]["text"] == "✅ Approve all (3)"
    assert btn[0][0]["callback_data"] == f"prdall:{out['digest_id']}"
    assert btn[0][1]["callback_data"] == f"prdhold:{out['digest_id']}"
    assert all(len(b["callback_data"].encode()) <= 64 for row in btn for b in row)
    text = msg["message"]
    assert "Needs operator merge" in text and "#5" in text and "agents\\_policy" in text
    assert "shared-infra" in text and "shared infra" in text and "migrations" in text
    assert "`aaaaaaaaa`" in text and "Does a thing." in text
    assert gh.labels_added == []


def test_empty_digest_sends_nothing(env):
    env["install"](FakeGH([_pr(3, draft=True)]))
    out = pmd.run_digest(apply=True)
    assert out["action"] == "empty_no_message"
    assert env["sent"] == []


def test_unchanged_digest_not_resent_but_now_forces(env):
    env["install"](FakeGH([_pr(1)]))
    first = pmd.run_digest(apply=True)
    again = pmd.run_digest(apply=True)
    assert again["action"] == "unchanged_pending_digest"
    forced = pmd.run_digest(apply=True, force=True)
    assert forced["action"] == "sent" and forced["digest_id"] != first["digest_id"]
    rows = {r["digest_id"]: r for r in pmd.load_digests()}
    assert rows[first["digest_id"]]["status"] == "SUPERSEDED"
    assert len(env["sent"]) == 2


def test_dry_run_writes_nothing_and_sends_nothing(env):
    env["install"](FakeGH([_pr(1)]))
    out = pmd.run_digest(apply=False)
    assert out["action"] == "would_send" and "PR merge digest" in out["message"]
    assert env["sent"] == [] and pmd.load_digests() == []


def test_summary_line_skips_headings_and_keeps_identifiers():
    body = "<!-- tmpl -->\n# Title\n\n## Summary\n- Adds `foo_bar` to **the** thing\nmore\n"
    assert pmd.summary_line(body) == "Adds foo_bar to the thing"
    assert pmd.summary_line("") == ""


def test_long_digest_fits_one_message(env):
    long_body = "## Summary\n" + "x" * 500
    env["install"](FakeGH([_pr(n, title="T" * 200, body=long_body) for n in range(1, 11)]
                          + [_pr(100 + n, files=("AGENTS.md",), title="P" * 200) for n in range(30)]))
    out = pmd.run_digest(apply=True)
    assert len(env["sent"][0]["message"]) <= pmd.MAX_MESSAGE_CHARS
    assert out["action"] == "sent"


# ── settle ───────────────────────────────────────────────────────────────────


def test_approve_all_one_record_labels_each_and_skips_moved_head(env):
    gh = env["install"](FakeGH([_pr(1), _pr(2), _pr(3), _pr(5, files=("AGENTS.md",))]))
    d = pmd.run_digest(apply=True)
    gh.open[2]["headRefOid"] = SHA_B  # pushed after the digest went out
    tg = {"from_id": "77", "from_username": "op", "message_id": 1001, "text": f"prdall:{d['digest_id']}"}
    out = pmd.settle_approve_all(d["digest_id"], chat_id="77", allowed_chats={"77"}, telegram=tg)
    assert out["ok"] is True
    assert sorted(gh.labels_added) == [1, 3]
    assert out["returned"] == [2]
    recs = pmd._read_jsonl(pmd.approvals_path())
    assert len(recs) == 1
    rec = recs[0]
    assert rec["schema"] == "PrMergeDigestApproval@v1"
    assert rec["digest_id"] == d["digest_id"] and rec["operator_chat_id"] == "77" and rec["operator_from_id"] == "77"
    assert rec["items"] == [{"pr": 1, "head_sha": SHA_A, "label_ok": True}, {"pr": 3, "head_sha": SHA_A, "label_ok": True}] or \
        [(i["pr"], i["head_sha"]) for i in rec["items"]] == [(1, SHA_A), (3, SHA_A)]
    assert 5 not in gh.labels_added  # needs-operator PRs are never approved by the digest
    # A second tap cannot settle it again.
    again = pmd.settle_approve_all(d["digest_id"], chat_id="77", allowed_chats={"77"}, telegram=tg)
    assert again["ok"] is False and again["reason"].startswith("NOT_PENDING")
    assert sorted(gh.labels_added) == [1, 3]


def test_approve_refuses_wrong_chat_and_unknown(env):
    gh = env["install"](FakeGH([_pr(1)]))
    d = pmd.run_digest(apply=True)
    out = pmd.settle_approve_all(d["digest_id"], chat_id="999", allowed_chats={"77"})
    assert out == {"ok": False, "reason": "CHAT_NOT_ALLOWLISTED"}
    assert pmd.settle_approve_all("nope", chat_id="77", allowed_chats={"77"})["reason"] == "UNKNOWN_DIGEST"
    assert gh.labels_added == []


def test_superseded_digest_cannot_be_approved(env):
    gh = env["install"](FakeGH([_pr(1)]))
    old = pmd.run_digest(apply=True)
    pmd.run_digest(apply=True, force=True)
    out = pmd.settle_approve_all(old["digest_id"], chat_id="77", allowed_chats={"77"})
    assert out["reason"] == "NOT_PENDING:SUPERSEDED" and gh.labels_added == []


def test_hold_item_button_and_text_then_approve(env):
    gh = env["install"](FakeGH([_pr(1), _pr(2), _pr(3)]))
    d = pmd.run_digest(apply=True)
    t = pmd.toggle_item(d["digest_id"], 2, chat_id="77", allowed_chats={"77"})
    assert t["ok"] and t["held"] is True and t["remaining"] == 2
    kb = pmd.keyboard(t["digest"], pmd.load_config())
    assert kb["inline_keyboard"][0][0]["text"] == "✅ Approve all (2)"
    assert any(b["text"] == "↩ Include #2" for row in kb["inline_keyboard"] for b in row)
    reply = pmd.handle_text_command("hold #3", chat_id="77", allowed_chats={"77"})
    assert "#3 held" in reply and "covers 1" in reply
    assert pmd.handle_text_command("unhold 3", chat_id="77", allowed_chats={"77"}).endswith("covers 2.")
    assert pmd.handle_text_command("hello there", chat_id="77", allowed_chats={"77"}) is None
    out = pmd.settle_approve_all(d["digest_id"], chat_id="77", allowed_chats={"77"})
    assert sorted(gh.labels_added) == [1, 3]
    assert [i["pr"] for i in pmd._read_jsonl(pmd.approvals_path())[0]["items"]] == [1, 3]
    assert {"pr": 2, "outcome": "held_by_operator"} in out["outcomes"]


def test_hold_all_labels_nothing_and_prs_return_next_digest(env):
    gh = env["install"](FakeGH([_pr(1)]))
    d = pmd.run_digest(apply=True)
    out = pmd.settle_hold_all(d["digest_id"], chat_id="77", allowed_chats={"77"})
    assert out["ok"] and out["held"] == [1] and gh.labels_added == []
    nxt = pmd.run_digest(apply=True)
    assert nxt["action"] == "sent" and nxt["ready"] == [1]


# ── reconcile: head binding + notes ──────────────────────────────────────────


def test_head_change_after_approval_removes_label_and_returns_to_digest(env):
    gh = env["install"](FakeGH([_pr(1), _pr(2)]))
    d = pmd.run_digest(apply=True)
    pmd.settle_approve_all(d["digest_id"], chat_id="77", allowed_chats={"77"})
    gh.open[1]["headRefOid"] = SHA_B
    dry = pmd.reconcile_head_binding(pmt.DEFAULT_REPO, apply=False, cfg=pmd.load_config())
    assert {r["pr"]: r["action"] for r in dry} == {1: "would_remove_label", 2: "bound_ok"}
    assert gh.labels_removed == []
    res = pmd.reconcile_head_binding(pmt.DEFAULT_REPO, apply=True, cfg=pmd.load_config())
    assert {r["pr"]: r["action"] for r in res} == {1: "label_removed", 2: "bound_ok"}
    assert gh.labels_removed == [1]
    assert any("returns to the next Telegram digest" in c for _p, c in gh.comments)
    nxt = pmd.run_digest(apply=True)
    assert nxt["ready"] == [1]


def test_unbound_label_is_reported_not_removed(env):
    gh = env["install"](FakeGH([_pr(4, labels=(pmt.LABEL,))]))
    res = pmd.reconcile_head_binding(pmt.DEFAULT_REPO, apply=True, cfg=pmd.load_config())
    assert res == [{"pr": 4, "action": "unbound_label", "policy": "report"}]
    assert gh.labels_removed == []


def _receipt(tmp, name, outcome, main_sha):
    d = tmp / "state" / "data" / "runtime" / "deploy_on_main"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"schema": "DeployOnMainReceipt@v1", "outcome": outcome,
                                      "main_sha": main_sha, "path": "poller"}))


def test_merged_then_live_notes_and_failure_is_p1(env, monkeypatch):
    gh = env["install"](FakeGH([_pr(1), _pr(2)]))
    d = pmd.run_digest(apply=True)
    pmd.settle_approve_all(d["digest_id"], chat_id="77", allowed_chats={"77"})
    _receipt(env["tmp"], "20261027T000000Z_poller_noop.json", "noop", SHA_C)
    cfg = pmd.load_config()
    monkeypatch.setattr(pmd, "commit_included", lambda repo, c, m: m == SHA_C and c == "m1" or m == "d" * 40)
    first = pmd.reconcile_notes(pmt.DEFAULT_REPO, apply=True, cfg=cfg)  # sets the receipt cursor, no replay
    assert first["merged_note"] is None and first["live_notes"] == []
    env["sent"].clear()
    gh.merged = [{"number": 1, "title": "Synthetic change 1", "mergeCommit": {"oid": "m1"}, "mergedAt": "x"},
                 {"number": 77, "title": "not ours", "mergeCommit": {"oid": "m9"}, "mergedAt": "x"}]
    out = pmd.reconcile_notes(pmt.DEFAULT_REPO, apply=True, cfg=cfg)
    assert out["merged_note"]["prs"] == [1]
    assert len(env["sent"]) == 1 and "Merged 1, deploying" in env["sent"][0]["message"]
    assert env["sent"][0]["priority"] == "P2"
    # Merged note is sent once.
    assert pmd.reconcile_notes(pmt.DEFAULT_REPO, apply=True, cfg=cfg)["merged_note"] is None
    _receipt(env["tmp"], "20261027T010000Z_poller_verified.json", "verified", SHA_C)
    env["sent"].clear()
    out = pmd.reconcile_notes(pmt.DEFAULT_REPO, apply=True, cfg=cfg)
    assert [n["prs"] for n in out["live_notes"]] == [[1]]
    assert "Live" in env["sent"][0]["message"] and "#1" in env["sent"][0]["message"] and "tester ok" in env["sent"][0]["message"]
    assert env["sent"][0]["priority"] == "P2"
    # Failure path: a second merged PR, deploy_failed receipt → P1.
    gh.merged.append({"number": 2, "title": "Synthetic change 2", "mergeCommit": {"oid": "m2"}, "mergedAt": "y"})
    pmd.reconcile_notes(pmt.DEFAULT_REPO, apply=True, cfg=cfg)
    _receipt(env["tmp"], "20261027T020000Z_poller_deploy_failed.json", "deploy_failed", "d" * 40)
    env["sent"].clear()
    out = pmd.reconcile_notes(pmt.DEFAULT_REPO, apply=True, cfg=cfg)
    assert out["live_notes"][0]["outcome"] == "deploy_failed"
    assert env["sent"][0]["priority"] == "P1" and "Deploy problem" in env["sent"][0]["message"]


def test_next_digest_at_weekday_and_weekend():
    from datetime import datetime, timezone

    # Tue 2026-10-27 13:00 UTC = 09:00 ET → next is 12:00 ET.
    assert pmd.next_digest_at(datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)) == "Tue 2026-10-27 12:00 ET"
    # Fri 2026-10-30 21:00 UTC = 17:00 ET → Sat 00:00 ET.
    assert pmd.next_digest_at(datetime(2026, 10, 30, 21, 0, tzinfo=timezone.utc)) == "Sat 2026-10-31 00:00 ET"


# ── wiring ───────────────────────────────────────────────────────────────────


def test_callback_handler_and_poller_wire_digest():
    h = (ROOT / "scripts" / "telegram_callback_handler.py").read_text(encoding="utf-8")
    assert 'action in ("prdall", "prdhold", "prdx")' in h and "pr_merge_digest" in h
    p = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    assert "_handle_digest_hold" in p and "handle_text_command" in p


def test_digest_sends_only_through_telegram_alert_chokepoint():
    src = (ROOT / "scripts" / "lib" / "pr_merge_digest.py").read_text(encoding="utf-8")
    assert "api.telegram.org" not in src and "urllib" not in src and "requests." not in src
    assert "ta.send_telegram(" in src


def test_timer_schedule_matches_config():
    timer = (ROOT / "config" / "systemd" / "user" / "tradeai-pr-merge-digest.timer").read_text(encoding="utf-8")
    cal = re.findall(r"^OnCalendar=(.+)$", timer, flags=re.M)
    assert cal == ["Mon..Fri 08:00 America/New_York", "Mon..Fri 12:00 America/New_York",
                   "Mon..Fri 16:30 America/New_York", "Sat,Sun 00/3:00 America/New_York"]
    cfg = pmd.load_config()["next_digest_times"]
    assert cfg["weekday"] == ["08:00", "12:00", "16:30"]
    assert cfg["weekend"] == [f"{h:02d}:00" for h in range(0, 24, 3)]
    svc = (ROOT / "config" / "systemd" / "user" / "tradeai-pr-merge-digest.service").read_text(encoding="utf-8")
    assert "pr_merge_digest.py --apply" in svc
    rsvc = (ROOT / "config" / "systemd" / "user" / "tradeai-pr-merge-reconcile.service").read_text(encoding="utf-8")
    assert "--reconcile --apply" in rsvc


def test_notify_per_pr_retired_and_request_defaults_to_digest(monkeypatch, capsys):
    import notify_pr_merge_ready as npr

    monkeypatch.setattr(npr, "_list_prs", lambda repo: (_ for _ in ()).throw(AssertionError("must not scan")))
    assert npr.main(["--apply"]) == 0
    assert "retired" in capsys.readouterr().out
    src = (ROOT / "scripts" / "request_pr_merge_approve.py").read_text(encoding="utf-8")
    assert "--single" in src and "added_to_next_digest" in src and "next_digest_at" in src


# ── Mergify hold: one config, CI-enforced coverage ───────────────────────────


def _mergify():
    return yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))


def _hold_rule():
    rules = _mergify()["pull_request_rules"]
    hold = [r for r in rules if r["name"].lower().startswith("hold")]
    assert len(hold) == 1, "exactly one Mergify hold rule"
    return hold[0]


def test_mergify_hold_rule_equals_config():
    rule = _hold_rule()
    ors = rule["conditions"][0]["or"]
    files = [c[len("files~="):] for c in ors if isinstance(c, str) and c.startswith("files~=")]
    labels = sorted(c[len("label="):] for c in ors if isinstance(c, str) and c.startswith("label="))
    assert files == mhp.mergify_regexes(), "regenerate: python scripts/lib/merge_hold_paths.py --print-mergify"
    assert labels == sorted(mhp.hold_labels())
    assert rule["actions"]["label"]["add"] == ["held"]


# Every path class AGENTS.md §0 (rules 1-2) and §25.10 exclusions name, plus the merge/deploy control plane
# (coordinator AGENTS review 2026-10-27). Hardcoded here on purpose: the config may not grade itself.
REQUIRED_HELD = [
    # §0 rules 1-2 / §22 / §28.6 — broker, Active Trader, MBI, orders
    "scripts/active_trader/engine.py", "scripts/brokers/x.py", "scripts/moomoo/client.py",
    "scripts/schwab_transport.py", "scripts/lib/schwab_token.py", "scripts/broker_adapter.py",
    "scripts/lib/broker_registry.py", "scripts/alpaca_trailing_stop.py", "scripts/lib/order_intent_store.py",
    # secrets (§0 rule 2, §24.7)
    ".env", ".env.local", "config/.env", "config/secret_registry.yaml",
    # AGENTS.md / AI_WORK_POLICY (§20, §25.10)
    "AGENTS.md", "AI_WORK_POLICY.md", "docs/sub/AGENTS.md",
    # hooks / guard (§25.10)
    ".githooks/pre-push", ".cursor/hooks/guard-write.sh", "scripts/hooks/pre_push.py", "bin/guard",
    "scripts/lib/guard_remote_approval.py", "scripts/lib/guard_push_auth.py",
    # merge go-signal + Mergify + promote + emergency + grant binding (§25.10, §17)
    "scripts/request_pr_merge_approve.py", "scripts/lib/pr_merge_telegram.py", "scripts/lib/pr_merge_digest.py",
    "scripts/pr_merge_digest.py", ".mergify.yml", "config/merge_hold_paths.json",
    "scripts/lib/deploy_on_main.py", "scripts/deploy_on_main_poll.py", "scripts/cio_phase2_exact_main_deploy.sh",
    "scripts/emergency_manual_promote.sh", "scripts/lib/release_grant_binding.py",
    "scripts/lib/deploy_delegation_binding.py",
]

NOT_HELD = ["docs/ops/x.md", "scripts/lib/news_feed.py", "apps/command-center-v3/src/pages/Home.tsx",
            "tests/test_x.py", "config/environment.json", "scripts/envelope.py"]


@pytest.mark.parametrize("path", REQUIRED_HELD)
def test_required_class_is_held_by_mergify_and_digest(path):
    regexes = [re.compile(r) for r in mhp.mergify_regexes()]
    assert any(r.search(path) for r in regexes), f"{path} is not covered by the .mergify.yml hold"
    assert mhp.is_held_path(path)


@pytest.mark.parametrize("path", NOT_HELD)
def test_ordinary_paths_not_held(path):
    assert not mhp.is_held_path(path)


def test_every_order_placing_module_is_held():
    assert mhp.order_scan_violations() == []


def test_agents_25_10_exclusions_still_name_these_classes():
    """If §25.10 grows a new exclusion class, this test must be extended with it."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    sec = agents.split("\n## 25.10 ", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(sec.split())
    assert "Held classes are never in \"Approve all\"." in flat
    for name in ("broker", "Active Trader", "MBI", "secrets", "`AGENTS.md`", "`AI_WORK_POLICY.md`",
                 "hooks and guard", "`bin/guard`", "`.mergify.yml`", "`config/merge_hold_paths.json`"):
        assert name in flat, name


def test_mergify_queue_rules_unchanged_for_solo_and_default():
    rules = {r["name"]: r for r in _mergify()["pull_request_rules"]}
    solo = next(r for n, r in rules.items() if "solo" in n.lower())
    assert solo["actions"]["queue"]["name"] == "solo"
    assert "label=operator-merge" in solo["conditions"]
    default = next(r for n, r in rules.items() if n.startswith("Queue default"))
    assert "label!=solo" in default["conditions"] and "label!=shared-infra" in default["conditions"]
    q = {r["name"]: r for r in _mergify()["queue_rules"]}
    assert q["solo"]["batch_size"] == 1 and q["default"]["batch_size"] == 1

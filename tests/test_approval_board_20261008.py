"""Roadmap Phase 2 PR-C (2026-10-08): the approval board and its expiry events, hermetic.

No ledger file, no guard CLI, no socket: the loaders are injected, the gateway is the in-memory
dispatch_http, and the Telegram handler's transport is stubbed. Nothing here approves, grants,
consumes a grant or sends. Why: on 2026-10-07 two approved grants expired unused because no one
had a single list of what was open and how long it had left."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import n8n_coordination_gateway as server
from scripts.lib import approval_board_projection as ab
from scripts.lib import n8n_gateway_client as gc
from scripts.lib.n8n_coordination_gateway import PILOT_LANES
from scripts.n8n_pilot_dispatch import APPROVAL_LANE, dispatch_board_events, main as dispatch_main

ROOT = Path(__file__).resolve().parents[1]
KEY = b"approval-board-test-key-not-a-live-secret!!"
SHA = "b18d8087b0000000000000000000000000000000"
NOW = datetime(2026, 10, 8, 1, 40, tzinfo=timezone.utc)


def _transport():
    nonces, store = {}, {}

    def t(url, envelope):
        return server.dispatch_http("POST", "/v1/coordination", {}, json.dumps(envelope).encode(), key=KEY,
                                    expected_origin_sha=SHA, nonce_store=nonces, idempotency_store=store,
                                    lane_allowlist=frozenset(PILOT_LANES))
    t.store = store
    return t


def _package(pid: str, state: str, expires: datetime, *, pending: int = 1) -> dict:
    return {"package_id": pid, "campaign": "n8n", "wave": "w1", "summary": f"package {pid}", "state": state,
            "created_at": (expires - timedelta(hours=24)).isoformat(), "submitted_at": (expires - timedelta(hours=23)).isoformat(),
            "expires_at": expires.isoformat(),
            "items": [{"item_no": i + 1, "state": "PENDING" if i < pending else "APPROVED"} for i in range(2)]}


def _grants(**tiers: tuple[int, int, str]) -> dict:
    g = {t: {"expires": int(exp.timestamp()) if isinstance(exp, datetime) else exp, "uses": uses, "reason": reason,
             "created_at": int((NOW - timedelta(minutes=20)).timestamp()), "grant_id": f"gid-{t}"}
         for t, (exp, uses, reason) in tiers.items()}
    return {"state": "VALID", "grants": g, "active": [t for t, r in g.items() if r["expires"] > NOW.timestamp() and r["uses"] != 0]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "runtime" / "approval_package_reminder_last.json").write_text(json.dumps({
        "schema": "ApprovalReminderReceipt@v1", "run_id": "run-0002-abcdef", "served_sha": SHA, "planner_status": "OK",
        "outcome": "NO_ACTION", "action_count": 0, "delivery_status": "DELIVERY_OBSERVED", "delivery_receipt_count": 0,
        "started_at": NOW.isoformat(), "ended_at": NOW.isoformat()}))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("TRADEAI_SERVED_SHA", SHA)
    monkeypatch.setenv("TRADEAI_N8N_GATEWAY_HMAC_KEY", KEY.decode())
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    for v in ("TRADEAI_READ_DSN", "TRADE_AI_DSN", "DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    return root


# ── the board ──────────────────────────────────────────────────────────────────────────────────

def test_board_rows_carry_state_and_time_to_expiry_and_dead_sources_are_named():
    pkgs = [_package("pkg-open", "SUBMITTED", NOW + timedelta(minutes=25)),
            _package("pkg-late", "PARTIAL", NOW - timedelta(minutes=5)),     # window passed, ledger not yet updated
            _package("pkg-done", "VALIDATED", NOW + timedelta(hours=3))]
    grants = _grants(**{"release-write": (NOW + timedelta(minutes=7), 9, "promote 51200f611"),
                        "cron": (NOW - timedelta(minutes=1), 10, "expired one"),
                        "config-write": (NOW + timedelta(minutes=25), 0, "consumed")})
    board = ab.build_board(NOW, packages_loader=lambda: pkgs, grants_loader=lambda: grants)
    by = {(r["kind"], r["id"]): r for r in board["items"]}
    assert board["status"] == "OK" and board["total"] == 6
    assert by[("package", "pkg-open")]["state"] == "OPEN" and by[("package", "pkg-open")]["ttl_min_left"] == 25
    assert by[("package", "pkg-late")]["state"] == "EXPIRED" and by[("package", "pkg-late")]["ttl_min_left"] == -5
    assert by[("package", "pkg-done")]["state"] == "VALIDATED"
    assert by[("grant", "gid-release-write")]["state"] == "ACTIVE" and by[("grant", "gid-release-write")]["uses_left"] == 9
    assert by[("grant", "gid-cron")]["state"] == "EXPIRED" and by[("grant", "gid-config-write")]["state"] == "CONSUMED"
    assert board["counts"] == {"package": {"OPEN": 1, "EXPIRED": 1, "VALIDATED": 1}, "grant": {"ACTIVE": 1, "EXPIRED": 1, "CONSUMED": 1}}
    # the soonest expiry sorts first; nothing in the board is a secret
    assert board["items"][0]["id"] == "pkg-late"
    assert "reason" in by[("grant", "gid-release-write")] and len(by[("grant", "gid-release-write")]["reason"]) <= 160

    def boom():
        raise FileNotFoundError("guard ledger CLI absent")
    partial = ab.build_board(NOW, packages_loader=lambda: pkgs, grants_loader=boom)
    assert partial["status"] == "PARTIAL" and partial["sources"]["grants"]["status"] == "UNAVAILABLE"
    assert partial["sources"]["grants"]["reason"].startswith("FileNotFoundError")


def test_expiry_windows_are_30_min_for_packages_and_10_min_for_grants():
    pkgs = [_package("pkg-31", "SUBMITTED", NOW + timedelta(minutes=31)), _package("pkg-30", "SUBMITTED", NOW + timedelta(minutes=30)),
            _package("pkg-draft", "DRAFT", NOW + timedelta(minutes=5))]
    grants = _grants(**{"a": (NOW + timedelta(minutes=11), 1, "a"), "b": (NOW + timedelta(minutes=10), 1, "b"),
                        "c": (NOW + timedelta(minutes=3), 0, "consumed, not an alarm")})
    board = ab.build_board(NOW, packages_loader=lambda: pkgs, grants_loader=lambda: grants)
    assert [(r["kind"], r["id"]) for r in board["expiring"]] == [("grant", "gid-b"), ("package", "pkg-30")]


def test_event_plan_is_stable_inside_the_expiry_bucket():
    row = {"kind": "grant", "id": "gid-x", "expires_at": "2026-10-08T02:10:00+00:00", "created_at": "2026-10-08T01:40:00+00:00", "ttl_min_left": 9}
    a = ab.event_plan(row)
    b = ab.event_plan({**row, "ttl_min_left": 2})          # minutes later, same bucket
    assert a["idempotency_key"] == b["idempotency_key"] and a["subject_key"] == b["subject_key"]
    assert a["subject_key"] == "approval:grant:gid-x:expires_at=2026-10-08T02:10" and "expires_in" not in a["subject_key"]
    c = ab.event_plan({**row, "expires_at": "2026-10-08T03:00:00+00:00"})
    assert c["idempotency_key"] != a["idempotency_key"]
    assert a["store"] == "data/runtime" and a["artifact_rel"] == "data/runtime/approval_board_last.json"


# ── the dispatcher ─────────────────────────────────────────────────────────────────────────────

def _wire_board(monkeypatch, pkgs, grants):
    monkeypatch.setattr(ab, "load_packages", lambda ledger_path=None: pkgs)
    monkeypatch.setattr(ab, "load_grants", lambda cli=None, timeout_s=10.0: grants)


def test_dispatcher_emits_one_event_per_expiring_row_and_repeats_are_duplicates(env, monkeypatch):
    pkgs = [_package("pkg-soon", "SUBMITTED", NOW + timedelta(minutes=20)), _package("pkg-far", "SUBMITTED", NOW + timedelta(hours=5))]
    grants = _grants(**{"release-write": (NOW + timedelta(minutes=7), 9, "promote")})
    _wire_board(monkeypatch, pkgs, grants)
    t = _transport()
    monkeypatch.setattr(gc.GatewayClient, "_http", lambda self, url, envelope: t(url, envelope))
    client = gc.GatewayClient()

    dry = dispatch_board_events(client=None, root=env, sha=SHA, now=NOW)
    assert [r["outcome"] for r in dry] == ["DRY_RUN", "DRY_RUN"] and not (env / "data" / "runtime" / "approval_board_last.json").exists()
    assert {r["kind"] for r in dry} == {"grant", "package"} and all(r["lane_id"] == APPROVAL_LANE for r in dry)

    rows = dispatch_board_events(client=client, root=env, sha=SHA, now=NOW)
    assert [r["outcome"] for r in rows] == ["ARTIFACT_WRITTEN", "ARTIFACT_WRITTEN"]
    assert all(r["ops"][0]["op"] == "accept_event" and not r["ops"][0]["duplicate"] for r in rows)
    receipt = json.loads((env / "data" / "runtime" / "approval_board_last.json").read_text())
    assert receipt["schema"] == "ApprovalBoard@v1" and receipt["expiring_count"] == 2
    assert all(ref.get("artifact_ref", {}).get("ref") == "data/runtime/approval_board_last.json" for ref in t.store.values()
               if isinstance(ref, dict) and ref.get("artifact_ref"))

    again = dispatch_board_events(client=client, root=env, sha=SHA, now=NOW + timedelta(minutes=4))
    assert [r["outcome"] for r in again] == ["ARTIFACT_WRITTEN", "ARTIFACT_WRITTEN"]
    assert all(r["ops"][0]["duplicate"] is True for r in again), "same bucket → duplicate, never idempotency_conflict"
    assert {r["idempotency_key"] for r in again} == {r["idempotency_key"] for r in rows}


def test_dispatcher_emits_nothing_when_nothing_is_expiring_and_the_receipt_still_names_the_board(env, monkeypatch, tmp_path, capsys):
    _wire_board(monkeypatch, [_package("pkg-far", "SUBMITTED", NOW + timedelta(hours=5))], _grants())
    assert dispatch_board_events(client=None, root=env, sha=SHA, now=NOW) == []
    monkeypatch.setenv("TRADEAI_APPROVAL_BOARD", "0")
    assert dispatch_board_events(client=None, root=env, sha=SHA, now=NOW) == []      # opt-out for hermetic callers
    monkeypatch.delenv("TRADEAI_APPROVAL_BOARD")
    assert dispatch_main(["--dry-run", "--lane", APPROVAL_LANE, "--receipt", str(tmp_path / "r.json")]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert [l[0] for l in out["lanes"]].count(APPROVAL_LANE) == 1          # only the run-receipt event, no board row


def test_main_dry_run_carries_the_board_rows_on_the_approval_lane(env, monkeypatch, tmp_path, capsys):
    _wire_board(monkeypatch, [_package("pkg-soon", "SUBMITTED", datetime.now(timezone.utc) + timedelta(minutes=9))], _grants())
    assert dispatch_main(["--dry-run", "--lane", APPROVAL_LANE, "--receipt", str(tmp_path / "r.json")]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    lanes = [l[0] for l in out["lanes"]]
    assert lanes.count(APPROVAL_LANE) == 2 and out["fired"] == 2   # the run-receipt event + one board event
    assert not (tmp_path / "r.json").exists()


# ── the route and the page ────────────────────────────────────────────────────────────────────

def test_api_route_calls_the_projection_read_only_and_the_page_has_the_panel():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('base_path == "/api/v2/coordination/approvals"')
    block = src[i:i + 500]
    assert "approval_board_projection import load_board" in block
    for forbidden in ("INSERT", "UPDATE", "send_telegram", "guard_ledger", "consume"):
        assert forbidden not in block
    page = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "CoordinationPage.tsx").read_text(encoding="utf-8")
    assert "/api/v2/coordination/approvals" in page and 'data-testid="coordination-approvals"' in page
    chain = (ROOT / "apps" / "command-center-v3" / "package.json").read_text(encoding="utf-8")
    assert "src/lib/approvalBoard.test.ts" in chain
    reg = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert '"tests/test_approval_board_20261008.py"' in reg


# ── the Telegram ack (served since Phase 1; here proven end to end against the gateway) ───────

def test_telegram_ack_callback_records_a_consumer_receipt_and_nothing_else(env, monkeypatch):
    import importlib
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    handler = importlib.import_module("telegram_callback_handler")
    t = _transport()
    monkeypatch.setattr(gc.GatewayClient, "_http", lambda self, url, envelope: t(url, envelope))
    client = gc.GatewayClient()
    idem = "apx-0123456789abcdef0123"
    event = {"event_id": f"evt-{APPROVAL_LANE}-{idem}", "source_project": "trade-ai", "lane_id": APPROVAL_LANE,
             "schema_version": "event-reference/v0", "origin_sha": SHA, "subject_key": "approval:grant:g:expires_at=x",
             "source_timestamp": NOW.isoformat(), "deadline": (NOW + timedelta(hours=1)).isoformat(),
             "artifact_ref": "data/runtime:approval_board_last.json", "authority_class": "coordination_read",
             "correlation_id": f"corr-{idem}", "idempotency_key": idem}
    assert client.accept_event(event)["state"] == "ACCEPTED"
    ops = gc.walk_to_artifact(client, idem, {"store": "data/runtime", "ref": "approval_board_last.json", "as_of": NOW.isoformat()})
    assert ops[-1]["state"] == "ARTIFACT_WRITTEN"

    answers, edits, posts = [], [], []
    monkeypatch.setattr(handler, "answer_callback", lambda cb_id, text, show_alert=False: answers.append((cb_id, text, show_alert)))
    monkeypatch.setattr(handler, "edit_message", lambda chat_id, message_id, text: edits.append(text))
    monkeypatch.setattr(handler, "_tg_post", lambda method, data: posts.append(method))
    monkeypatch.setattr(handler, "_allowed_chat_ids", lambda: {"777"})
    monkeypatch.setattr(handler, "_allowed_from_ids", lambda: {"42"})
    cb = {"id": "cbq-1", "data": f"ack:{idem}", "from": {"id": 42, "first_name": "op"},
          "message": {"chat": {"id": 777}, "message_id": 5, "text": "incident"}}
    handler.handle_callback_query(cb)
    assert client.status(idem)["state"] == "CONSUMED"
    assert answers and answers[-1][1].startswith("Acknowledged") and posts == []   # no send: only the callback answer + an edit
    assert edits and "acknowledged by op" in edits[-1]

    # an outsider's tap and an unknown key never move anything
    cb_outsider = {**cb, "id": "cbq-2", "from": {"id": 99, "first_name": "x"}}
    handler.handle_callback_query(cb_outsider)
    assert answers[-1][0] == "cbq-2" and "Not authorized" in answers[-1][1]
    handler.handle_callback_query({**cb, "id": "cbq-3", "data": "ack:apx-does-not-exist-00000000"})
    assert answers[-1][0] == "cbq-3" and answers[-1][1].startswith("Not acknowledged")

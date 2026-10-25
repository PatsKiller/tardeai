"""Approvals → Designs lifecycle (AGENTS.md §28.13 proposed; design workflow approved by the operator 2026-10-25).

One-tap operator APPROVE / REJECT of a PROPOSED design version: recorded as a DECIDED (kind DESIGN) row in the
operator decisions ledger (same hash chain and store gate as Approvals), mirrored to the private store; agents,
readers and cross-site requests refused; fingerprint drift refused; idempotent request ids; private images served
only to the operator or an authenticated reader, only when listed in status.json with a matching sha256, never HTML.
Hermetic: tmp copies of design/ and docs/designs, a tmp ledger and a tmp private store.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import design_decisions as dd
from scripts.lib import design_decisions_api as api
from scripts.lib import design_pages as dp
from scripts.lib import operator_approvals as core

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = "tailnet:operator@example.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
T0 = datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "design", root / "design")
    (root / "docs/designs").mkdir(parents=True)
    (root / "docs/designs/DSN-20261026-compact-ask-bar.md").write_text(
        "---\nid: DSN-20261026-compact-ask-bar\ntitle: Compact phone Ask bar\nstatus: PROPOSED\n---\nbody\n", encoding="utf-8")
    store = tmp_path / "store"
    files = []
    for name, data, role in (("v002/mockups/mockup-1440.png", PNG, "mockups"), ("v002/mockups/mockup-412.png", PNG + b"1", "mockups"),
                             ("v002/mockups/mockup-390.png", PNG + b"2", "mockups"), ("v002/mockups/mockup.html", b"<script>x</script>", "mockups"),
                             ("v002/evidence/note.png", PNG + b"3", "evidence")):
        p = store / "pages/trading" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "role": role})
    status = {"schema": "DesignVersionStatus@v1", "page": "trading", "version": "v002", "state": "PROPOSED",
              "title": "Trading: compact phone header", "created": "2026-10-26", "approval": None, "spec": "SPEC.md",
              "private_assets": {"root": "persistent-state/data/design/pages/trading", "files": files},
              "fingerprint": dp.version_fingerprint(files), "prs": [], "verified": None,
              "history": [{"state": "PROPOSED", "at": "2026-10-26", "by": "agent:test"}]}
    vdir = root / "design/pages/trading/versions/v002"
    vdir.mkdir(parents=True)
    (vdir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    (vdir / "SPEC.md").write_text('# t\n## Removals, hides and moves\n- hide: panel "Scanner" — behind a tap\n', encoding="utf-8")
    reg = json.loads((root / "design/registry.json").read_text(encoding="utf-8"))
    next(p for p in reg["pages"] if p["id"] == "trading")["versions"] = [
        {"version": "v002", "state": "PROPOSED", "fingerprint": status["fingerprint"]}]
    (root / "design/registry.json").write_text(json.dumps(reg), encoding="utf-8")
    assert dp.validate(root) == []
    state = {"approved": True, "principal": OPERATOR, "listener": "serve_proxy", "csrf": (True, ""), "reader": False}
    clock = Clock()
    ledger = core.DecisionLedger(tmp_path / "gov/operator_decisions.jsonl", approved=lambda: state["approved"], clock=clock)
    ctx = api.Ctx(principal=lambda: state["principal"], listener=lambda: state["listener"],
                  csrf=lambda m, p: state["csrf"], allowed_logins=frozenset({"operator@example.com"}), ledger=ledger,
                  root=root, private_root=lambda: store, clock=clock, can_read=lambda: state["reader"])
    return {"root": root, "store": store, "ledger": ledger, "ctx": ctx, "state": state, "status": status}


def _decide(env, **over):
    body = {"page": "trading", "version": "v002", "fingerprint": env["status"]["fingerprint"], "decision": "APPROVE",
            "reason": "", "request_id": "req-0000000001"} | over
    return api.handle("/api/v2/design/decide", "POST", body, ctx=env["ctx"])


def test_projection_lists_proposed_version_dsn_and_the_10_24_backfill(env):
    status, payload = api.handle("/api/v2/design/approvals", "GET", ctx=env["ctx"])
    assert status == 200 and payload["ok"]
    data = payload["data"]
    assert [c["id"] for c in data["proposed"]] == ["design-version:trading/v002"]
    card = data["proposed"][0]
    assert {i["width"] for i in card["images"]} == {1440, 412, 390}  # html mockup is not an image
    assert card["removals"] == [{"action": "hide", "kind": "panel", "label": "Scanner"}]
    assert [d["id"] for d in data["dsn_proposed"]] == ["DSN-20261026-compact-ask-bar"]
    assert data["dsn_proposed"][0]["href"] == "/approvals/design%3ADSN-20261026-compact-ask-bar"
    backfill = [r for r in data["decided_recently"] if r["recorded"] == "recorded in handoff"]
    assert {r["title"] for r in backfill} == set(dd.BACKFILL_LABELS.values())
    desks = next(r for r in backfill if r["title"].startswith("Desk"))
    assert desks["outcome"] == "Approved" and desks["at"] == "2026-10-24" and "home/v001" in desks["pages"]
    assert data["can_decide"] is True and "not a cryptographic signature" in data["signature"]


def test_operator_approve_is_recorded_in_the_ledger_and_mirrored(env):
    status, payload = _decide(env)
    assert status == 200, payload
    row = payload["data"]["row"]
    assert row["event"] == "DECIDED" and row["kind"] == "DESIGN" and row["actor"] == OPERATOR
    assert row["item_id"] == "design-version:trading/v002" and row["document_sha"] == env["status"]["fingerprint"]
    assert row["effect"] == "RECORD_ONLY" and row["hash_self"]
    rows = env["ledger"].rows()  # chain verifies on read
    assert rows[-1]["hash_self"] == row["hash_self"]
    mirror = env["store"] / "pages/trading/v002/decision.json"
    doc = json.loads(mirror.read_text())
    assert doc["state"] == "APPROVED" and doc["ledger"]["hash_self"] == row["hash_self"]
    assert mirror.stat().st_mode & 0o777 == 0o600
    data = api.handle("/api/v2/design/approvals", "GET", ctx=env["ctx"])[1]["data"]
    assert data["proposed"] == []  # decided versions leave the queue
    assert data["decided_recently"][0]["id"] == "design-version:trading/v002"
    assert data["decided_recently"][0]["outcome"] == "Approved"
    # The same row is a DECIDED event, so the Approvals queue's Decision history includes it.
    q = core.queue_projection({}, decisions=rows, now=T0)
    assert q["recent"][0]["item_id"] == "design-version:trading/v002"


def test_reject_needs_a_reason_and_is_recorded(env):
    assert _decide(env, decision="REJECT")[1]["error"] == "REASON_REQUIRED"
    status, payload = _decide(env, decision="REJECT", reason="Ask bar still covers the list")
    assert status == 200
    doc = json.loads((env["store"] / "pages/trading/v002/decision.json").read_text())
    assert doc["state"] == "REJECTED" and doc["comment"] == "Ask bar still covers the list"


@pytest.mark.parametrize("principal,listener", [
    ("service-token", "loopback"), ("loopback", "loopback"), ("agent:codex", "serve_proxy"),
    ("tailnet:someone@else.com", "serve_proxy"), (OPERATOR, "loopback"),
])
def test_agents_readers_and_wrong_listeners_are_refused(env, principal, listener):
    env["state"].update(principal=principal, listener=listener, reader=True)
    status, payload = _decide(env)
    assert (status, payload["error"]) == (403, "AGENT_CALLER_REFUSED")
    assert env["ledger"].rows() == []


def test_csrf_is_enforced(env):
    env["state"]["csrf"] = (False, "csrf: cross-site")
    assert _decide(env)[1]["error"] == "CSRF_REFUSED"
    assert env["ledger"].rows() == []


def test_fingerprint_drift_is_refused(env):
    assert _decide(env, fingerprint="0" * 64)[1]["error"] == "DOCUMENT_CHANGED"
    assert env["ledger"].rows() == []


def test_idempotent_request_id(env):
    first = _decide(env)[1]["data"]
    again = _decide(env)[1]["data"]
    assert again["replayed"] is True and again["row"]["hash_self"] == first["row"]["hash_self"]
    assert len(env["ledger"].rows()) == 1
    assert _decide(env, decision="REJECT", reason="x")[1]["error"] == "IDEMPOTENCY_CONFLICT"
    assert _decide(env, request_id="req-0000000002")[1]["error"] == "ALREADY_DECIDED"


def test_only_proposed_versions_can_be_decided(env):
    v001 = json.loads((env["root"] / "design/pages/home/versions/v001/status.json").read_text())
    status, payload = _decide(env, page="home", version="v001", fingerprint=v001["fingerprint"])
    assert payload["error"] == "VERSION_NOT_PROPOSED"
    assert _decide(env, page="../etc", version="v001")[1]["error"] == "INVALID_DESIGN_VERSION"
    assert _decide(env, page="trading", version="v009")[1]["error"] == "ITEM_UNAVAILABLE"


def test_store_approval_pending_refuses_every_write(env):
    env["state"]["approved"] = False
    assert _decide(env)[1]["error"] == "STORE_APPROVAL_PENDING"
    assert not (env["store"] / "pages/trading/v002/decision.json").exists()


def test_production_ctx_gate_is_closed_while_the_store_row_is_proposed():
    registry = json.loads((ROOT / "config/data_source_authority.json").read_text(encoding="utf-8"))
    assert core.writes_approved(registry) is False  # operator_decisions is still `proposed`: no agent grants it


def test_get_needs_operator_or_authenticated_reader(env):
    env["state"].update(principal="loopback", listener="loopback", reader=False)
    assert api.handle("/api/v2/design/approvals", "GET", ctx=env["ctx"])[1]["error"] == "AUTHENTICATED_READER_REQUIRED"
    assert api.handle("/api/v2/design/asset", "GET", query={"page": "trading"}, ctx=env["ctx"])[0] == 403
    env["state"]["reader"] = True
    status, payload = api.handle("/api/v2/design/approvals", "GET", ctx=env["ctx"])
    assert status == 200 and payload["data"]["can_decide"] is False


def _asset(env, path, version="v002", page="trading"):
    return api.handle("/api/v2/design/asset", "GET", query={"page": [page], "version": [version], "path": [path]}, ctx=env["ctx"])


def test_image_route_serves_only_listed_png_with_matching_sha(env):
    status, payload = _asset(env, "v002/mockups/mockup-1440.png")
    assert status == 200
    img = payload["data"]
    assert img["mime"] == "image/png" and img["width"] == 1440
    assert base64.b64decode(img["image"].split(",", 1)[1]) == PNG
    assert _asset(env, "v002/mockups/mockup.html")[1]["error"] == "ASSET_TYPE_REFUSED"
    assert _asset(env, "v002/evidence/note.png")[1]["error"] == "ASSET_NOT_LISTED"  # evidence is not served
    assert _asset(env, "../../../etc/passwd")[1]["error"] == "ASSET_NOT_LISTED"
    (env["store"] / "pages/trading/v002/mockups/mockup-412.png").write_bytes(PNG + b"tampered")
    assert _asset(env, "v002/mockups/mockup-412.png")[1]["error"] == "ASSET_CHANGED"


def test_image_symlink_escape_is_refused(env, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    target = env["store"] / "pages/trading/v002/mockups/mockup-390.png"
    target.unlink()
    target.symlink_to(outside)
    assert _asset(env, "v002/mockups/mockup-390.png")[1]["error"] in ("ASSET_UNAVAILABLE", "ASSET_CHANGED")


def test_non_design_paths_are_not_handled(env):
    assert api.handle("/api/v2/designer", "GET", ctx=env["ctx"]) is None
    assert api.handle("/api/v2/design/approvals", "DELETE", ctx=env["ctx"])[1]["error"] == "METHOD_NOT_ALLOWED"


def test_repo_projection_has_no_proposed_versions_yet_and_shows_the_backfill():
    data = dd.projection(ROOT, ledger_rows=[], now=T0)
    assert data["proposed"] == []
    assert len([r for r in data["decided_recently"] if r["recorded"] == "recorded in handoff"]) == 4


def test_api_v2_dispatches_the_design_prefix():
    src = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    hook = src.index('"/api/v2/design"')
    assert src.index("operator_approvals_api as _oaa") < hook < src.index('"/api/v2/scheduler-operations"')
    assert "design_decisions_api" in src[hook:hook + 800]

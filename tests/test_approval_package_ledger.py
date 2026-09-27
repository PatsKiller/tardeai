"""ApprovalPackage@v1 ledger: chain, transitions, reply parsing, rendering (13)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import approval_package as ap  # noqa: E402

ITEMS = [
    {"item_id": "O-2a", "category": "OPERATOR", "title": "lane platform-conformance-audit", "why": "05", "rule": "AGENTS §17", "rollback": "disable lane", "scopes_needed": ["cron"]},
    {"item_id": "S-2", "category": "SECURITY", "title": "roles", "why": "least privilege", "rule": "superuser", "rollback": "DROP ROLE", "scopes_needed": ["sudo"]},
    {"item_id": "I-1", "category": "INFRA", "title": "schema intelligence", "why": "02", "rule": "§17", "rollback": "down.sql", "scopes_needed": ["db-write"], "depends_on": ["S-2"]},
    {"item_id": "B-4", "category": "BUDGET", "title": "effort 14d", "why": "09", "rule": "operator", "rollback": "stop", "reversible": True},
]


def _ledger(tmp_path):
    return ap.Ledger(tmp_path / "led.jsonl")


def test_new_package_marks_remote_forbidden_scopes_needs_local():
    pkg = ap.new_package("cogx", "Wave 1 · Foundations", "summary", ITEMS, binds={"pr": 1304, "sha": "abc"}, package_id="pkg-test-w1-0001")
    assert pkg["package_id"] == "pkg-test-w1-0001" and pkg["state"] == "DRAFT"
    states = {it["item_id"]: it["state"] for it in pkg["items"]}
    assert states["S-2"] == "NEEDS_LOCAL" and states["O-2a"] == "PENDING"
    assert pkg["reviews"]["security"] == "MISSING"
    with pytest.raises(ValueError):
        ap.new_package("c", "w", "s", [{"category": "BROKER", "title": "t", "why": "w", "rule": "r", "rollback": "x"}])
    with pytest.raises(ValueError):
        ap.new_package("c", "w", "s", [{"category": "OPERATOR", "title": "t"}])


def test_parse_reply_forms():
    assert ap.parse_reply("APPROVE pkg-20260927-cogx-w1-d9e1 all")["items"] == "all"
    r = ap.parse_reply("approve pkg-x-1 1,3, 5")
    assert r["verb"] == "APPROVE" and r["items"] == [1, 3, 5]
    r = ap.parse_reply('DENY pkg-x-1 6 "not now"')
    assert r["verb"] == "DENY" and r["items"] == [6] and r["reason"] == "not now"
    r = ap.parse_reply("DEFER pkg-x-1 12h")
    assert r["verb"] == "DEFER" and r["hours"] == 12
    assert ap.parse_reply("hello") is None and ap.parse_reply("") is None


def test_ledger_chain_and_state_transitions(tmp_path):
    led = _ledger(tmp_path)
    pkg = ap.new_package("cogx", "w1", "s", ITEMS, package_id="pkg-test-w1-0002")
    led.append({"event": "PACKAGE_CREATED", "package_id": pkg["package_id"], "package": pkg})
    led.append({"event": "SUBMITTED", "package_id": pkg["package_id"], "telegram": {"message_ids": ["1"]}})
    assert led.package(pkg["package_id"])["state"] == "SUBMITTED"
    view = ap.apply_reply(led, ap.parse_reply("APPROVE pkg-test-w1-0002 1"), decided_by={"who": "operator", "from_id": "x", "via": "typed"})
    assert view["state"] == "PARTIAL" and view["items"][0]["state"] == "APPROVED"
    view = ap.apply_reply(led, ap.parse_reply("APPROVE pkg-test-w1-0002 all"), decided_by={"who": "operator", "from_id": "x", "via": "typed"})
    assert view["state"] == "APPROVED" and view["items"][1]["state"] == "NEEDS_LOCAL"  # sudo never granted remotely
    ok, n, err = led.verify_chain()
    assert ok and n >= 5 and err is None
    # tamper → chain breaks
    rows = led.path.read_text().splitlines()
    rows[1] = rows[1].replace('"SUBMITTED"', '"SUBMITTEX"')
    led.path.write_text("\n".join(rows) + "\n")
    assert led.verify_chain()[0] is False


def test_deny_and_defer(tmp_path):
    led = _ledger(tmp_path)
    pkg = ap.new_package("cogx", "w1", "s", ITEMS, package_id="pkg-test-w1-0003")
    led.append({"event": "PACKAGE_CREATED", "package_id": pkg["package_id"], "package": pkg})
    v = ap.apply_reply(led, ap.parse_reply('DENY pkg-test-w1-0003 4 "no budget"'), decided_by={"who": "op"})
    assert v["items"][3]["state"] == "DENIED" and v["items"][3]["reason"] == "no budget" and v["state"] == "PARTIAL"
    v = ap.apply_reply(led, ap.parse_reply("DEFER pkg-test-w1-0003 6h"), decided_by={"who": "op"})
    assert all(it["state"] in ("DEFERRED", "DENIED", "NEEDS_LOCAL") for it in v["items"])
    with pytest.raises(ap.LedgerError):
        ap.apply_reply(led, ap.parse_reply("APPROVE pkg-nope all"), decided_by={"who": "op"})


def test_render_message_is_markdown_safe_and_single_chunk():
    pkg = ap.new_package("cognitive-transformation-20260927", "Wave 1 · Foundations", "One paragraph.", ITEMS, binds={"pr": 1304, "sha": "8f2a178d5"}, package_id="pkg-test-w1-0004")
    text = ap.render_message(pkg)
    assert text.count("*") == 2 and "_" not in text and "NEEDS-LOCAL" in text
    assert "APPROVE pkg-test-w1-0004 all" in text and len(ap.chunks(text)) == 1
    assert "sha 8f2a178d5" in text and "PR #1304" in text

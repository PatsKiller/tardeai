"""Ticker Prospectus API (contract shapes, small reads, files from disk, operator-only refresh). Synthetic data only."""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import prospectus_api as api  # noqa: E402
from scripts.lib.prospectus import load_config, store  # noqa: E402

NOW = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)
V1, V2 = "20261025T120000Z", "20261026T160000Z"


def ctx(tmp_path, *, principal="tailnet:operator@example.test", listener="serve_proxy", csrf=(True, "")):
    return api.Ctx(principal=lambda: principal, listener=lambda: listener, csrf=lambda m, p: csrf,
                   allowed_logins=frozenset({"operator@example.test"}), state_root=tmp_path)


@pytest.fixture()
def seeded(tmp_path):
    base = store.base_dir(tmp_path, load_config())
    for ver in (V1, V2):
        doc = {"schema": "Prospectus@v1", "symbol": "ZZAA", "name": "Zeta Widgets Inc", "scope": "holding",
               "version": ver, "generated_at": ver, "model": "claude-opus-5-5", "cost_usd": 0.3,
               "verdict_line": "Synthetic verdict.", "sections": [], "charts": []}
        store.write_version(base, "ZZAA", ver, doc, {"prospectus.html": b"<html>x</html>",
                                                      "prospectus.pdf": b"%PDF-1.7 synthetic",
                                                      "prospectus.docx": b"PK synthetic"})
    store.update_index(base, "ZZAA", name="Zeta Widgets Inc", scope="holding", version=V2, generated_at=V2,
                       model="claude-opus-5-5", cost_usd=0.3, status="ready", verdict_line="Synthetic verdict.",
                       next_due="2026-11-02T16:00:00+00:00")
    store.update_index(base, "ZZDD", name="Delta Fixture", scope="watch", version=V1, generated_at=V1,
                       model="claude-opus-5-5", status="ready", next_due="2026-10-01T00:00:00+00:00")
    store.write_universe(base, [{"symbol": "ZZAA", "scope": "holding", "premium": True},
                                {"symbol": "ZZBB", "scope": "holding", "premium": False},
                                {"symbol": "ZZCC", "scope": "watch", "premium": False},
                                {"symbol": "ZZDD", "scope": "watch", "premium": False}])
    store.enqueue(base, [{"symbol": "ZZBB", "scope": "holding", "priority": 100}])
    return tmp_path, base


def test_index_shape_matches_contract(seeded):
    root, _ = seeded
    status, body = api.handle("/api/v2/prospectus/index", "GET", ctx=ctx(root))
    assert status == 200
    assert set(body) == {"items", "totals", "budget", "viewer"} and body["viewer"] == {"operator": True}
    assert set(body["budget"]) >= {"credit_remaining_usd", "today_used_usd", "daily_cap_usd"}
    rows = {r["symbol"]: r for r in body["items"]}
    keys = {"symbol", "name", "scope", "version", "generated_at", "model", "cost_usd", "status", "stale",
            "next_due", "verdict_line", "failure_reason", "partial_gaps",
            "gate_status", "gate_reasons", "gate_checked_at"}  # data-quality gate fields (2026-10-26)
    assert all(set(r) == keys for r in body["items"])
    assert rows["ZZAA"]["status"] == "ready" and rows["ZZAA"]["stale"] is False
    assert rows["ZZBB"]["status"] == "queued" and rows["ZZCC"]["status"] == "missing"
    assert rows["ZZDD"]["stale"] is True and rows["ZZDD"]["scope"] == "watch"
    assert body["totals"] == {"ready": 2, "partial": 0, "queued": 1, "running": 0, "missing": 1, "failed": 0, "blocked_data": 0}
    agent = api.handle("/api/v2/prospectus/index", "GET", ctx=ctx(root, principal="service-token"))[1]
    assert agent["viewer"] == {"operator": False}


def test_index_payload_direct(seeded):
    root, _ = seeded
    out = api.index_payload(root, now=NOW)
    assert [r["symbol"] for r in out["items"]] == ["ZZAA", "ZZBB", "ZZCC", "ZZDD"]


def test_symbol_returns_latest_with_versions_and_specific_version(seeded):
    root, _ = seeded
    status, body = api.handle("/api/v2/prospectus/zzaa", "GET", ctx=ctx(root))
    assert status == 200 and body["version"] == V2
    assert [v["version"] for v in body["versions"]] == [V2, V1]
    assert set(body["versions"][0]) == {"version", "generated_at", "model"}
    assert body["viewer"] == {"operator": True} and body["failure_reason"] is None
    status, body = api.handle("/api/v2/prospectus/ZZAA", "GET", None, {"version": V1}, ctx=ctx(root))
    assert status == 200 and body["version"] == V1
    status, body = api.handle("/api/v2/prospectus/ZZBB", "GET", ctx=ctx(root))
    assert status == 404 and body["status"] == "queued"
    status, body = api.handle("/api/v2/prospectus/ZZAA", "GET", None, {"version": "../../x"}, ctx=ctx(root))
    assert status == 400


def test_file_route_streams_from_disk_with_disposition(seeded):
    root, _ = seeded
    res = api.handle("/api/v2/prospectus/ZZAA/file/pdf", "GET", None, {"version": [V1]}, ctx=ctx(root))
    assert isinstance(res, api.FileResult)
    assert res.path.name == "prospectus.pdf" and res.path.parent.name == V1
    assert res.content_type == "application/pdf" and res.disposition == "inline"
    docx = api.handle("/api/v2/prospectus/ZZAA/file/docx", "GET", ctx=ctx(root))
    assert docx.disposition == "attachment" and docx.filename == f"ZZAA-prospectus-{V2}.docx"
    assert api.handle("/api/v2/prospectus/ZZAA/file/exe", "GET", ctx=ctx(root))[0] == 404
    assert api.handle("/api/v2/prospectus/ZZCC/file/html", "GET", ctx=ctx(root))[0] == 404

    class Handler:
        def __init__(self):
            self.headers, self.wfile, self.code = {}, io.BytesIO(), None

        def send_response(self, code):
            self.code = code

        def send_header(self, k, v):
            self.headers[k] = v

        def end_headers(self):
            pass

    h = Handler()
    api.stream_file(h, docx, chunk=4)
    assert h.code == 200 and h.wfile.getvalue() == b"PK synthetic"
    assert h.headers["Content-Disposition"].startswith("attachment; filename=")
    assert h.headers["Content-Length"] == str(len(b"PK synthetic"))


@pytest.mark.parametrize("who", [
    {"principal": "service-token"},
    {"principal": "tailnet:someone-else@example.test"},
    {"principal": "tailnet:operator@example.test", "listener": "loopback"},
    {"principal": ""},
])
def test_refresh_refuses_agents_and_non_operators(seeded, who):
    root, base = seeded
    status, body = api.handle("/api/v2/prospectus/ZZCC/refresh", "POST", {}, ctx=ctx(root, **who))
    assert status == 403 and body["error"] == "AGENT_CALLER_REFUSED"
    assert "ZZCC" not in {r["symbol"] for r in store.read_queue(base)["items"]}


def test_refresh_operator_queues_and_csrf_rechecked(seeded):
    root, base = seeded
    status, body = api.handle("/api/v2/prospectus/ZZCC/refresh", "POST", {}, ctx=ctx(root, csrf=(False, "csrf: x")))
    assert status == 403 and body["error"] == "CSRF_REFUSED"
    status, body = api.handle("/api/v2/prospectus/ZZCC/refresh", "POST", {}, ctx=ctx(root))
    assert status == 202 and body == {"ok": True, "queued": True, "symbol": "ZZCC", "position": 0}
    row = store.read_queue(base)["items"][0]
    assert row["reason"] == "operator_refresh" and row["requested_by"] == "tailnet:operator@example.test"
    assert api.handle("/api/v2/prospectus/ZZCC/refresh", "GET", ctx=ctx(root))[0] == 405
    assert api.handle("/api/v2/prospectus/index", "POST", {}, ctx=ctx(root))[0] == 405


def test_not_ours_and_bad_paths(seeded):
    root, _ = seeded
    assert api.handle("/api/v2/other", "GET", ctx=ctx(root)) is None
    assert api.handle("/api/v2/prospectus/ZZAA/file/pdf/extra", "GET", ctx=ctx(root))[0] == 404
    assert api.handle("/api/v2/prospectus/..%2F/file/pdf", "GET", ctx=ctx(root))[0] == 404


def test_server_wiring_and_csrf_hard_route():
    src = (ROOT / "scripts/portfolio_server.py").read_text()
    assert src.count("prospectus_api") >= 4 and "_pa.stream_file(self, _pa_out)" in src
    cfg = (ROOT / "config/cc_auth.yaml").read_text()
    assert "action: prospectus_command" in cfg and "pattern: /api/v2/prospectus(/.*)?" in cfg
    assert json.loads((ROOT / "config/prospectus.json").read_text())["schema"] == "ProspectusConfig@v1"


def test_failed_and_partial_items_carry_reason_and_gaps(seeded):
    root, base = seeded
    store.update_index(base, "ZZCC", status="failed", failure_reason="OUTPUT_UNGROUNDED: 3 empty sections")
    store.update_index(base, "ZZDD", status="partial", partial_gaps=["price_history: empty"])
    rows = {r["symbol"]: r for r in api.index_payload(root, now=NOW)["items"]}
    assert rows["ZZCC"]["status"] == "failed" and rows["ZZCC"]["failure_reason"].startswith("OUTPUT_UNGROUNDED")
    assert rows["ZZDD"]["status"] == "partial" and rows["ZZDD"]["partial_gaps"] == ["price_history: empty"]

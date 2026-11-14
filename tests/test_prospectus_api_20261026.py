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


def _due_in(days: int) -> str:
    """A next_due relative to the live clock, so the fixture cannot expire on a calendar date."""
    from datetime import datetime as _d, timedelta as _td, timezone as _tz

    return (_d.now(_tz.utc) + _td(days=days)).isoformat()


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
                       next_due=_due_in(days=7))
    store.update_index(base, "ZZDD", name="Delta Fixture", scope="watch", version=V1, generated_at=V1,
                       model="claude-opus-5-5", status="ready", next_due=_due_in(days=-30))
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


# --- Stored-unit normalization (OP-064): a legacy peer market cap is MILLIONS under a "$B" label --------------------
#
# Live shapes, measured on the host store 2026-11-14: 52 of 121 stored versions predate blocks.py e416d7c55
# (2026-10-26T23:29:07Z) and carry raw Finviz millions. ANET stored 218731.87; the page printed "$218731.9B". The
# small caps are why the rule cannot be a magnitude threshold: PFLT stored 696.65 (its $0.7B) and FATN 88.2.
LEGACY_V = "20261026T181337Z"    # ANET's stored version — before the producer cutover
CURRENT_V = "20261027T141256Z"   # NVDA's stored version — peer caps already in $B (5215.0)


def _peer_doc(version, caps, *, median=None, facts=None, label="ZZLG Mkt cap ($B)"):
    """A demo-tier prospectus with one peer block; caps are given in whatever unit the writer stored."""
    rows = [{"symbol": "ZZLG" if i == 0 else f"Z{i}", "market_cap_b": c, "is_subject": i == 0}
            for i, c in enumerate(caps)]
    return {"schema": "Prospectus@v1", "symbol": "ZZLG", "version": version, "generated_at": version,
            "model": "claude-opus-5-5", "verdict_line": "Synthetic verdict.", "sections": [], "charts": [],
            "blocks": {"peer_comparison": {"fields": ["market_cap_b"], "labels": {"market_cap_b": "Mkt cap ($B)"},
                                           "rows": rows,
                                           "median": {"market_cap_b": median} if median is not None else {}}},
            "facts": facts or []}


def _stored(tmp_path, doc, version=None):
    base = store.base_dir(tmp_path, load_config())
    store.write_version(base, doc["symbol"], version or doc["version"], doc, {})
    return base


def _peer_cell(millions_or_billions):
    """The client's own formatter (apps/command-center-v3/src/lib/prospectusModel.ts peerCell)."""
    return f"${millions_or_billions:.1f}B"


def test_legacy_peer_market_cap_is_millions_converted_once_at_read(tmp_path):
    """ANET-shaped: 218731.87 is $M. The reader converts once and records the rule; the page prints $218.7B."""
    doc = _peer_doc(LEGACY_V, [218731.87, 296783.39, 143620.43], median=143620.43,
                    facts=[{"id": "F8", "kind": "fundamental", "label": "Market cap ($B)", "value": 218731.87},
                           {"id": "F95", "kind": "peers", "label": "ZZLG Mkt cap ($B)", "value": 218731.87},
                           # A dollar-valued fact that is NOT a peer cap: the subject's own market cap in dollars.
                           {"id": "F172", "kind": "fundamental", "label": "MarketCap (latest)",
                            "value": 217396490000.0}])
    _stored(tmp_path, doc)
    status, body = api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))
    assert status == 200
    pc = body["blocks"]["peer_comparison"]
    assert [r["market_cap_b"] for r in pc["rows"]] == [218.73, 296.78, 143.62]
    assert pc["median"]["market_cap_b"] == 143.62
    # What the operator reads (peerCell). Before the fix this string was "$218731.9B".
    assert _peer_cell(pc["rows"][0]["market_cap_b"]) == "$218.7B"
    # The peer-cited facts carry the same stored value under a "$B" label; the dollar-valued one is untouched.
    values = {f["id"]: f["value"] for f in body["facts"]}
    assert values["F8"] == 218.73 and values["F95"] == 218.73
    assert values["F172"] == 217396490000.0
    rec = body["unit_normalization"]
    assert rec["rule"] == api.UNIT_RULE and rec["applied"] is True and rec["action"] == "divided_1000"
    assert rec["cutover_version"] == "20261026T232907Z"
    assert rec["rows"] == 3 and rec["median"] is True and rec["facts"] == 2


def test_current_peer_market_cap_is_billions_and_left_alone(tmp_path):
    """NVDA-shaped current doc: 5215.0 is already $B — dividing it again would print $5.2B for a $5.2T company."""
    doc = _peer_doc(CURRENT_V, [5215.0, 2200.99, 1600.31], median=1045.73)
    _stored(tmp_path, doc)
    status, body = api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))
    assert status == 200
    pc = body["blocks"]["peer_comparison"]
    assert [r["market_cap_b"] for r in pc["rows"]] == [5215.0, 2200.99, 1600.31]
    assert pc["median"]["market_cap_b"] == 1045.73
    assert _peer_cell(pc["rows"][0]["market_cap_b"]) == "$5215.0B"
    rec = body["unit_normalization"]
    assert rec["applied"] is False and rec["action"] == "none" and rec["version"] == CURRENT_V


def test_legacy_small_cap_is_converted_and_a_magnitude_rule_would_miss_it(tmp_path):
    """A $0.7B name stored in millions is 696.65 — under any threshold that catches the large caps."""
    doc = _peer_doc(LEGACY_V, [696.65, 88.2, 3977.25], median=696.65)
    _stored(tmp_path, doc)
    _, body = api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))
    caps = [r["market_cap_b"] for r in body["blocks"]["peer_comparison"]["rows"]]
    assert caps == [0.7, 0.09, 3.98]  # $0.7B, $88M, $3.98B
    assert body["unit_normalization"]["rows"] == 3


def test_cutover_stamp_is_treated_as_current(tmp_path):
    """The boundary belongs to the converted side: a doc stamped exactly at the cutover is already in $B."""
    doc = _peer_doc(api.PEER_MARKET_CAP_CUTOVER_VERSION, [5215.0])
    _stored(tmp_path, doc)
    _, body = api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))
    assert body["blocks"]["peer_comparison"]["rows"][0]["market_cap_b"] == 5215.0
    assert body["unit_normalization"]["applied"] is False


def test_unreadable_version_stamp_withdraws_the_figure_not_a_guess(tmp_path):
    """Unknown beats wrong: with no readable stamp the unit cannot be established, so the cell renders "—"."""
    doc = _peer_doc(LEGACY_V, [218731.87, 296783.39], median=218731.87)
    doc["version"] = ""
    _stored(tmp_path, doc, version=LEGACY_V)
    _, body = api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))
    pc = body["blocks"]["peer_comparison"]
    assert [r["market_cap_b"] for r in pc["rows"]] == [None, None]
    assert pc["median"]["market_cap_b"] is None
    assert body["unit_normalization"]["action"] == "withdrawn" and body["unit_normalization"]["applied"] is False


def test_unreadable_stamp_withdraws_the_cap_labelled_facts_too(tmp_path):
    """cc-deepseek-9 F1 (VERDICT 2026-11-14T21:23Z): the withdrawn arm nulled the cells but left the facts, so a
    footnote printed the 1000x number under a `($B)` label while the record said "market cap withdrawn".

    The facts are withdrawn by the SAME exact value-identity set the legacy arm converts — never by label alone, so a
    value this table does not hold is not guessed at.
    """
    doc = _peer_doc(LEGACY_V, [218731.87, 296783.39], median=183987.41,
                    facts=[{"id": "F8", "kind": "fundamental", "label": "Market cap ($B)", "value": 218731.87},
                           {"id": "F95", "kind": "peers", "label": "ZZLG Mkt cap ($B)", "value": 218731.87},
                           {"id": "F133", "kind": "peers", "label": "Peer median Mkt cap ($B)", "value": 183987.41},
                           # A cap-labelled fact whose value is NOT in this table: no row or median holds it.
                           {"id": "F150", "kind": "peers", "label": "ZZQX Mkt cap ($B)", "value": 999.0},
                           # A dollar-valued fact that is not a peer cap at all.
                           {"id": "F172", "kind": "fundamental", "label": "MarketCap (latest)",
                            "value": 217396490000.0}])
    doc["version"] = ""
    _stored(tmp_path, doc, version=LEGACY_V)
    _, body = api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))

    pc = body["blocks"]["peer_comparison"]
    assert [r["market_cap_b"] for r in pc["rows"]] == [None, None]
    assert pc["median"]["market_cap_b"] is None

    facts = {f["id"]: f for f in body["facts"]}
    for fid in ("F8", "F95", "F133"):           # value matched a withdrawn row/median: withdrawn too
        assert facts[fid]["value"] is None, fid
        assert facts[fid]["text"] == "not reliable (stored unit unverified)", fid
    assert facts["F150"]["value"] == 999.0       # unmatched cap label: not guessed at
    assert "text" not in facts["F150"]
    assert facts["F172"]["value"] == 217396490000.0

    rec = body["unit_normalization"]
    assert rec["action"] == "withdrawn" and rec["applied"] is False
    assert rec["rows"] == 2 and rec["median"] is True and rec["facts"] == 3

    # Idempotent in the safe direction: a second pass does not withdraw a second time or resurrect a figure.
    again = api.normalize_stored_units(body)
    assert again is body and again["unit_normalization"]["facts"] == 3


def test_no_peer_block_adds_no_key_and_normalization_is_idempotent(tmp_path):
    """A doc without a peer table is untouched (no payload growth), and a second pass never divides twice."""
    doc = {"schema": "Prospectus@v1", "symbol": "ZZLG", "version": LEGACY_V, "generated_at": LEGACY_V,
           "verdict_line": "Synthetic.", "sections": [], "charts": [], "blocks": {}, "facts": []}
    assert api.normalize_stored_units(doc) is doc and "unit_normalization" not in doc

    legacy = _peer_doc(LEGACY_V, [218731.87, 296783.39], median=143620.43)
    once = api.normalize_stored_units(legacy)
    again = api.normalize_stored_units(once)
    assert again is once
    assert [r["market_cap_b"] for r in again["blocks"]["peer_comparison"]["rows"]] == [218.73, 296.78]
    assert again["unit_normalization"]["rows"] == 2


def test_the_stored_file_is_never_rewritten(tmp_path):
    """The read converts the payload, not the archive: the file on disk still holds the writer's millions."""
    doc = _peer_doc(LEGACY_V, [218731.87], median=218731.87)
    base = _stored(tmp_path, doc)
    path = base / "ZZLG" / LEGACY_V / "prospectus.json"
    before = path.read_bytes()
    api.handle("/api/v2/prospectus/ZZLG", "GET", ctx=ctx(tmp_path))
    assert path.read_bytes() == before
    assert json.loads(before)["blocks"]["peer_comparison"]["rows"][0]["market_cap_b"] == 218731.87

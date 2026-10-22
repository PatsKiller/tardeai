"""CIO prospect data foundation P0/P1 (ANCHOR CIO_PROSPECT_FOUNDATION_20261022).

AGENTS.md §26 (18.0.0, ACTIVE); docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §7. Pins, all inert until the
operator grants the cio_prospect registry row and the P1 migration (§17):

1. migrations/2026_10_22_cio_prospect.sql — additive, idempotent, least privilege, append-only events, no delete;
   the down file archives by rename. Proven on a THROWAWAY initdb cluster under $TMPDIR (unix socket only, never
   production; skipped without PG binaries), including the InstrumentRecordStore Postgres backend's upsert/event SQL.
2. InstrumentRecord@v1 extended (never cloned): apply_prospect rail (BEHAVIOR_FIELDS refused anywhere, MBI = 0),
   conviction reproducible from components, unified edge persisted with its inputs, the dual-write inert by default.
3. The shadow builder: one prospect per security_guid, conflicts recorded never resolved, identity unresolved gets no
   prospect, no stop/target copied, writes nothing; the watchlist curation rules.
4. The n8n lane cio-prospect-shadow at SHADOW (registry, allowlist, DRAFT contract).
5. The read-only data-broker projection cio_prospect (shadow labelled, say_so on gap, per-row stale).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib import cio_prospect_builder as B  # noqa: E402
from scripts.lib import cio_prospect_watchlist_rules as W  # noqa: E402

UP = ROOT / "migrations/2026_10_22_cio_prospect.sql"
DOWN = ROOT / "migrations/2026_10_22_cio_prospect.down.sql"
NOW = datetime(2026, 10, 22, 19, 45, tzinfo=timezone.utc)   # 15:45 ET, market open
G_NVDA, I_NVDA = "5f0c6a3e-1111-5111-8111-000000000001", "5f0c6a3e-1111-5111-8111-0000000000a1"
G_ACME, I_ACME = "5f0c6a3e-1111-5111-8111-000000000002", "5f0c6a3e-1111-5111-8111-0000000000a2"
G_BETA, I_BETA = "5f0c6a3e-1111-5111-8111-000000000003", "5f0c6a3e-1111-5111-8111-0000000000a3"
IDS = {"NVDA": (G_NVDA, I_NVDA), "ACME": (G_ACME, I_ACME), "BETA": (G_BETA, I_BETA)}


def _identity(sym: str) -> dict:
    if sym in IDS:
        g, i = IDS[sym]
        return {"symbol": sym, "security_guid": g, "issuer_guid": i, "subject_guid": g, "identity_status": "CONFIRMED"}
    return {"symbol": sym, "security_guid": None, "issuer_guid": None, "identity_status": "UNRESOLVED",
            "identity_lookup_reason": "not in registry"}


# ── 1. migration ─────────────────────────────────────────────────────────────


def test_plan_tool_static_checks_pass_and_name_the_grants():
    from scripts import cio_prospect_migration_plan as plan
    doc = plan.build_plan()
    assert doc["static_checks"] == {"ok": True, "failures": []}
    assert doc["applies"] is False and doc["db_contact"] is False
    assert doc["inventory"]["tables"] == ["cio_prospect", "cio_prospect_events"]
    assert any("sha256=" + doc["files"]["up"]["sha256"] in g for g in doc["operator_grants"])
    assert doc["registry_row"]["granted"] is False and doc["registry_row"]["proposed"] is True


def test_plan_tool_catches_a_drop_and_a_delete():
    from scripts import cio_prospect_migration_plan as plan
    up, down = UP.read_text(), DOWN.read_text()
    assert plan.static_checks(up + "\nDROP TABLE cio_prospect;", down)
    assert plan.static_checks(up, down + "\nDELETE FROM cio_prospect_archived_20261022;")
    assert plan.static_checks(up.replace("GRANT SELECT, INSERT, UPDATE ON cio_prospect TO trade_ai;",
                                         "GRANT ALL ON cio_prospect TO trade_ai;"), down)


def _bin() -> Path | None:
    for major in ("18", "17", "16", "15"):
        d = Path(f"/usr/lib/postgresql/{major}/bin")
        if (d / "initdb").is_file() and (d / "pg_ctl").is_file():
            return d
    found = shutil.which("initdb")
    return Path(found).parent if found else None


BIN = _bin()
PSQL = shutil.which("psql") or (str(BIN / "psql") if BIN and (BIN / "psql").is_file() else None)
NEEDS_PG = pytest.mark.skipif(BIN is None or PSQL is None, reason="no PostgreSQL server binaries on this host")


@pytest.fixture(scope="module")
def cluster():
    base = Path(tempfile.mkdtemp(prefix="cpx-pg-", dir=os.environ.get("TMPDIR") or None))
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    env = {**os.environ, "LC_ALL": "C"}
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD", "PGSERVICE", "PGPASSFILE"):
        env.pop(k, None)
    subprocess.run([str(BIN / "initdb"), "-D", str(data), "-U", "cpx_admin", "--auth=trust", "-E", "UTF8"],
                   check=True, capture_output=True, env=env)
    opts = f"-c listen_addresses='' -c unix_socket_directories={sock} -p 55433 -c fsync=off"
    subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-o", opts, "-l", str(base / "log"), "-w", "start"],
                   check=True, capture_output=True, env=env)

    def psql(user, db, sql=None, file=None):
        argv = [PSQL, "-X", "-h", str(sock), "-p", "55433", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-tA"]
        argv += ["-f", str(file)] if file else ["-c", sql]
        p = subprocess.run(argv, capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    try:
        assert psql("cpx_admin", "postgres", "CREATE ROLE trade_ai LOGIN")[0] == 0
        assert psql("cpx_admin", "postgres", "CREATE DATABASE cpx_scratch")[0] == 0
        assert psql("cpx_admin", "cpx_scratch", "GRANT USAGE, CREATE ON SCHEMA public TO trade_ai")[0] == 0
        psql.sock = sock  # type: ignore[attr-defined]
        yield psql
    finally:
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], capture_output=True, env=env)
        shutil.rmtree(base, ignore_errors=True)  # the throwaway cluster's own temp tree only


def _prospect_record(sym="NVDA", stage="held", stance="ADD", **over) -> dict:
    g, i = IDS[sym]
    rec = ir.new_record("HELD", sym)
    rec.update({"security_guid": g, "issuer_guid": i, "subject_guid": g})
    block = {
        "security_guid": g, "issuer_guid": i, "stage": stage, "stance": stance,
        "conviction_components": {"opportunity_score": {"value": 80.0, "weight": 0.5, "source": "opp",
                                                        "evidence_at": "2026-10-22T19:30:00+00:00"},
                                  "hermes_score": {"value": 60.0, "weight": 0.5, "source": "hermes",
                                                   "evidence_at": "2026-10-22T19:30:00+00:00"}},
        "evidence_at": "2026-10-22T19:30:00+00:00", "expires_at": "2026-10-22T20:00:00+00:00",
        "conflicts": [], "whats_missing": [],
    }
    block.update(over)
    out, _ = ir.apply_prospect(rec, prospect=block)
    return out


@NEEDS_PG
def test_migration_and_backend_on_a_throwaway_cluster(cluster):
    psql = cluster
    rc, out = psql("cpx_admin", "cpx_scratch", file=UP)
    assert rc == 0, out
    assert psql("cpx_admin", "cpx_scratch", file=UP)[0] == 0          # idempotent
    rc, out = psql("cpx_admin", "cpx_scratch",
                   "SELECT table_name || ':' || string_agg(privilege_type, ',' ORDER BY privilege_type) "
                   "FROM information_schema.role_table_grants WHERE grantee = 'trade_ai' GROUP BY table_name "
                   "ORDER BY table_name")
    assert out.splitlines() == ["cio_prospect:INSERT,SELECT,UPDATE", "cio_prospect_events:INSERT,SELECT"], out

    import psycopg2

    def connect():
        return psycopg2.connect(host=str(psql.sock), port=55433, user="trade_ai", dbname="cpx_scratch")

    backend = ir.ProspectPgBackend(connect)
    assert backend.table_present() is True
    rec = _prospect_record()
    row1 = ir.prospect_row(rec)
    assert backend.write(row1, ir.prospect_event(None, row1)) == {"ok": True, "upserted": 1, "event_appended": 1}
    # same revision again: the row is not overwritten, the event is not duplicated
    assert backend.write(row1, ir.prospect_event(None, row1))["upserted"] == 0
    rec2 = _prospect_record(stage="exit", stance="EXIT_REVIEW", stage_evidence={"source": "test"})
    rec2["prospect_revision"] = 2
    row2 = ir.prospect_row(rec2)
    ev2 = ir.prospect_event(row1, row2)
    assert ev2["event_type"] == "stage_change"
    assert backend.write(row2, ev2)["upserted"] == 1
    assert psql("cpx_admin", "cpx_scratch", "SELECT stage || ':' || revision FROM cio_prospect")[1] == "exit:2"
    assert psql("cpx_admin", "cpx_scratch", "SELECT count(*) FROM cio_prospect_events")[1] == "2"
    # the writer column binds the single writer; enums and range are CHECKed
    for sql in (
        f"UPDATE cio_prospect SET writer = 'someone_else' WHERE security_guid = '{G_NVDA}'",
        f"UPDATE cio_prospect SET stance = 'BUY_100_SHARES' WHERE security_guid = '{G_NVDA}'",
        f"UPDATE cio_prospect SET conviction = 101 WHERE security_guid = '{G_NVDA}'",
    ):
        rc, out = psql("trade_ai", "cpx_scratch", sql)
        assert rc != 0 and "violates check constraint" in out, (sql, out)
    # never deleted; events append-only, even for the owner
    for user, sql in (("trade_ai", "DELETE FROM cio_prospect"), ("cpx_admin", "DELETE FROM cio_prospect"),
                      ("cpx_admin", "DELETE FROM cio_prospect_events"),
                      ("cpx_admin", "UPDATE cio_prospect_events SET writer = 'x'"),
                      ("cpx_admin", "TRUNCATE cio_prospect_events"), ("trade_ai", "DROP TABLE cio_prospect")):
        rc, out = psql(user, "cpx_scratch", sql)
        assert rc != 0, (user, sql, out)
    # down: archived, never dropped; writes withdrawn; idempotent
    assert psql("cpx_admin", "cpx_scratch", file=DOWN)[0] == 0
    assert psql("cpx_admin", "cpx_scratch", file=DOWN)[0] == 0
    assert psql("trade_ai", "cpx_scratch", "SELECT count(*) FROM cio_prospect_archived_20261022")[1] == "1"
    rc, out = psql("trade_ai", "cpx_scratch", "UPDATE cio_prospect_archived_20261022 SET stage = 'held'")
    assert rc != 0 and "permission denied" in out
    assert backend.table_present() is False


# ── 2. InstrumentRecord@v1 extended ─────────────────────────────────────────


def test_behavior_fields_unchanged_and_disjoint_from_the_prospect():
    assert ir.BEHAVIOR_FIELDS == ("recommended_delta_usd", "size_usd", "shares", "qty", "order",
                                  "stop", "limit", "target_weight_pct", "trade", "execution")
    assert not set(ir.PROSPECT_FIELDS) & set(ir.BEHAVIOR_FIELDS)
    assert ir.MBI_BEHAVIOR == 0
    assert ir.SCHEMA == "InstrumentRecord@v1"   # extended, not cloned (§13.5)


@pytest.mark.parametrize("bad", [
    {"next_trigger": {"kind": "reference_level", "stop": 100.0}},
    {"next_action": {"who": "cio", "order": {"side": "buy"}}},
    {"conviction_components": {"unified_edge": {"value": 50, "inputs": {"qty": 10}}}},
    {"watchlist": {"member": True, "size_usd": 1000}},
])
def test_apply_prospect_refuses_behavior_anywhere(bad):
    rec = _prospect_record()
    with pytest.raises(ir.BehaviorWriteRefused):
        ir.apply_prospect(rec, prospect=bad)


def test_apply_prospect_rails():
    rec = _prospect_record()
    assert rec["conviction"] == 70.0 and rec["prospect_schema"] == ir.PROSPECT_SCHEMA
    assert rec["prospect_revision"] == 1 and rec["aliases"]["subject_key"] == "HELD:NVDA"
    with pytest.raises(ir.ProspectInvalid):                       # not a prospect field
        ir.apply_prospect(rec, prospect={"rank_score": 3})
    with pytest.raises(ir.ProspectInvalid):                       # placeholder identity
        ir.apply_prospect(ir.new_record("WATCH", "ACME"), prospect={
            "security_guid": "PLACEHOLDER", "issuer_guid": "x", "stage": "watching", "stance": "WATCH",
            "conviction": 10, "evidence_at": "2026-10-22T19:00:00+00:00", "expires_at": "2026-10-22T20:00:00+00:00"})
    with pytest.raises(ir.ProspectInvalid):                       # conviction not reproducible
        ir.apply_prospect(rec, prospect={"conviction": 99.0})
    with pytest.raises(ir.ProspectInvalid):                       # stage move names no evidence
        ir.apply_prospect(rec, prospect={"stage": "exit"})
    with pytest.raises(ir.ProspectInvalid):                       # a conflict needs two sourced values
        ir.apply_prospect(rec, prospect={"conflicts": [{"field": "stance", "values": [{"value": "ADD"}]}]})
    with pytest.raises(ir.CognitionNoOp):                         # nothing moved
        ir.apply_prospect(rec, prospect={"stance": "ADD"})
    moved, changed = ir.apply_prospect(rec, prospect={"stage": "exit", "stance": "EXIT_REVIEW",
                                                      "stage_evidence": {"source": "test"}})
    assert {"stage", "stance"} <= set(changed) and moved["prospect_revision"] == 2 and moved["stage_changed_at"]


def test_unified_edge_is_persisted_with_its_inputs_and_reproducible():
    from scripts.unified_edge_score import edge_from_trade_context
    ctx = {"risk_reward": 4.9, "confidence": 0.78, "technical_score": 71.4}
    comp = ir.unified_edge_component(ctx, source="test", evidence_at="2026-10-22T19:30:00+00:00")
    assert comp["value"] == edge_from_trade_context(ctx)
    assert comp["inputs"] == ctx and comp["method"] == "unified_edge_score.edge_from_trade_context"
    with pytest.raises(ir.BehaviorWriteRefused):
        ir.unified_edge_component({**ctx, "stop": 1.0}, source="t", evidence_at=None)


def test_dual_write_is_inert_by_default_and_never_probes_an_ungranted_store(tmp_path):
    probed = []
    st = ir.prospect_store_status(env={ir.PROSPECT_DUAL_WRITE_ENV: "1"}, table_probe=lambda: probed.append(1))
    assert st["live"] is False and "registry_row_not_granted" in st["reasons"] and probed == []
    assert ir.prospect_row_granted() is False      # the repo registry: proposed, not granted

    class Backend:
        calls: list = []

        def table_present(self):
            return True

        def write(self, row, event):
            self.calls.append((row, event))
            return {"ok": True}

    store = ir.InstrumentRecordStore(tmp_path / "ir.jsonl")
    res = store.upsert_prospect(_prospect_record(), backend=Backend(), env={})
    assert res["pg"]["mode"] == "inert" and Backend.calls == []
    assert (tmp_path / "ir.jsonl").read_text().count("\n") == 1          # jsonl stays the store of record
    granted = {"domains": [{"domain": "cio_prospect", "approval": {"approved_by": "operator"}}]}
    res = store.upsert_prospect(_prospect_record(stance="HOLD"), backend=Backend(), registry=granted,
                                env={ir.PROSPECT_DUAL_WRITE_ENV: "1"})
    assert res["pg"]["mode"] == "dual_write" and len(Backend.calls) == 1
    assert Backend.calls[0][1]["event_type"] == "update" and Backend.calls[0][0]["writer"] == "InstrumentRecordStore"
    with pytest.raises(ir.ProspectInvalid):
        store.upsert_prospect(ir.new_record("WATCH", "ACME"))


# ── 3. the shadow builder ───────────────────────────────────────────────────


def _state(tmp: Path) -> Path:
    (tmp / "data/cio").mkdir(parents=True)
    (tmp / "data/runtime").mkdir(parents=True)
    rr = {"rr": 4.9, "entry_zone": [218.5, 224.5], "entry_ref": 221.8, "invalidation_level": 213.0}
    (tmp / "data/cio/cio_opportunity_projection.json").write_text(json.dumps({"as_of": "2026-10-22T19:30:00+00:00",
        "items": {
            "NVDA": {"symbol": "NVDA", "as_of": "2026-10-22T19:30:00+00:00", "conviction": 78.1, "stance": "ADD",
                     "type": "add_on", "position_status": "owned", "coverage": 1.0, "rank": 59, "risk_reward": rr,
                     "factors": {"technical": {"score": 71.4}}, "factors_missing": []},
            "ACME": {"symbol": "ACME", "as_of": "2026-10-22T19:30:00+00:00", "conviction": 82.0, "stance": "WATCH",
                     "type": "new_position", "position_status": "not_owned", "coverage": 1.0, "rank": 3,
                     "risk_reward": {"rr": 3.0, "entry_zone": [10, 11]}, "factors": {}, "factors_missing": ["analyst"]},
            "GHOST": {"symbol": "GHOST", "as_of": "2026-10-22T19:30:00+00:00", "conviction": 90.0, "stance": "ADD",
                      "type": "new_position", "position_status": "not_owned", "risk_reward": {}, "factors": {}}}}))
    (tmp / "data/cio/cio_theses_projection.json").write_text(json.dumps({"updated_ts": "2026-10-05T13:27:16+00:00",
        "current": {"symbol_nvda": {"stance": "watch", "thesis_version": "symbol_nvda@v8", "status": "active",
                                    "linked_symbols": ["NVDA"], "published_ts": "2026-10-05T13:27:16+00:00"}}}))
    (tmp / "data/cio/security_research_spine.jsonl").write_text(json.dumps(
        {"symbol": "NVDA", "as_of": "2026-10-22T19:00:00Z", "thesis": {"stance": "WATCH", "conviction": 0.62}}) + "\n")
    (tmp / "data/cio/cio_instrument_records.jsonl").write_text(json.dumps(
        {"subject_key": "WATCH:NVDA", "kind": "WATCH", "updated_ts": "2026-10-21T23:01:16+00:00",
         "next_research_question": "Is the data-center guide credible?"}) + "\n")
    (tmp / "data/runtime/reentry_decision_desk_latest.json").write_text(json.dumps({
        "computed_at": "2026-10-22T19:40:00+00:00",
        "rows": [{"symbol": "BETA", "stop": 9.0, "target": 15.0, "entry_low": 10.0,
                  "intel": {"state": "NEAR ENTRY"}, "catalyst": {"verified": True, "confidence": 0.9}}]}))
    (tmp / "data/runtime/hermes_watchlist_lifecycle.json").write_text(json.dumps({
        "updated_at": "2026-10-22T19:37:00+00:00",
        "symbols": {"NVDA": {"lifecycle_stage": "promoted", "conviction_score": 85.5}}}))
    return tmp


def _build(tmp: Path, **kw):
    return B.build(tmp, held_reader=lambda: {"symbols": {"NVDA"}, "source": "test_holdings", "as_of": NOW.isoformat()},
                   identity_resolver=_identity, now=NOW, **kw)


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}


def test_builder_assembles_one_prospect_per_guid_and_shows_the_nvda_conflicts(tmp_path):
    root = _state(tmp_path)
    before = _tree(root)
    doc = _build(root)
    assert _tree(root) == before                                    # writes nothing
    assert doc["writes"] == "none" and doc["store_status"]["mode"] == "inert"
    by = {r["symbol"]: r for r in doc["prospects"]}
    assert set(by) == {"NVDA", "ACME", "BETA"}
    assert [u["symbol"] for u in doc["identity_unresolved"]] == ["GHOST"]   # no placeholder identity
    nv = by["NVDA"]
    assert nv["security_guid"] == G_NVDA and nv["issuer_guid"] == I_NVDA
    assert nv["stage"] == "held" and nv["stance"] == "ADD"
    fields = sorted(c["field"] for c in nv["conflicts"])
    assert fields == ["stance", "subject_key_kind"]
    stance_c = next(c for c in nv["conflicts"] if c["field"] == "stance")
    assert {v["source"] for v in stance_c["values"]} == {"cio_opportunity_projection", "cio_theses symbol_nvda@v8"}
    assert stance_c["resolved"] is False
    assert nv["next_action"]["what"].startswith("resolve 2 conflict")
    comps = nv["conviction_components"]
    assert comps["unified_edge"]["method"] == "unified_edge_score.edge_from_trade_context"
    assert nv["conviction"] == ir.conviction_from_components(comps)          # reproducible
    assert comps["fused_score"]["value"] is None                            # not wired: shown, not invented
    assert nv["watchlist"]["origin"] == "held_position" and nv["watchlist"]["protected"] is True
    assert nv["next_trigger"]["note"] == "information, never an order"
    assert by["ACME"]["stage"] == "setup_forming" and by["BETA"]["stage"] == "re_entry"
    assert by["ACME"]["shadow_rank"] < by["BETA"]["shadow_rank"]     # CIO-assessed ranks before unassessed
    blob = json.dumps(doc["prospects"])
    for k in ir.BEHAVIOR_FIELDS:                                     # re-entry stop/target never copied
        assert f'"{k}":' not in blob, k
    for p in doc["prospects"]:
        ir.prospect_row(p)                                           # every row is a valid table row


def test_home_preset_matches_the_opportunity_api_rule():
    from lib.data_broker import opportunity as op
    items = {s: {"symbol": s, "conviction": c, "coverage": cov, "risk_reward": {"rr": rr}}
             for s, c, cov, rr in (("A", 91, 1.0, 2.5), ("B", 85, 0.9, 1.9), ("C", 82, 0.7, 3.0), ("D", 88, 1.0, None),
                                   ("E", 80, 0.8, 2.0), ("F", 79.9, 1.0, 5.0), ("G", 95, 1.0, 2.1), ("H", 84, 1.0, 2.2),
                                   ("I", 86, 1.0, 4.0))}
    q = op.apply_preset({"preset": "top5"})
    want = [a["symbol"] for a in op.sort_items([a for a in items.values() if op.passes(a, q)], q["sort"])][: q["limit"]]
    assert [a["symbol"] for a in B.home_best_opportunities(items)] == want == ["G", "A", "I", "H", "E"]


def test_stance_disagreement_rule():
    assert B.disagree("ADD", "watch") and B.disagree("TRIM", "hold") and B.disagree("RE_ENTER", "WATCH")
    assert not B.disagree("HOLD", "watch") and not B.disagree("ADD", "BUY") and not B.disagree("ADD", None)
    assert not B.disagree("ADD", "something_unknown")


def test_compare_against_home_watch_telegram(tmp_path):
    root = _state(tmp_path)
    doc = _build(root)
    cmp = B.compare(doc, root, watch_top_ideas=["NVDA", "ZZZ"], watch_source="test", now=NOW)
    rows = {r["symbol"]: r for r in cmp["rows"]}
    assert rows["NVDA"]["watch"]["top_idea_rank"] == 1
    assert rows["NVDA"]["telegram"]["conviction_line"].startswith("Conviction 78/100")
    assert not rows["NVDA"]["agrees"] and any(d.startswith("inputs disagree") for d in rows["NVDA"]["differences"])
    assert rows["ZZZ"]["shadow"] is None
    assert cmp["surfaces"]["telegram"]["live"] is True


def test_watchlist_curation_rules():
    rules = W.load_rules()
    assert rules["status"] == "PROPOSED" and rules["approval"] is None
    m = W.membership([{"origin": "cio_curator", "reason": ""}, {"origin": "made_up", "reason": "x"}], rules)
    assert m["member"] is False and {r["refused"] for r in m["refused"]} == {"no_reason", "unknown_origin"}
    m = W.membership([{"origin": "hermes", "reason": "promoted"}, {"origin": "operator_star", "reason": "starred"}],
                     rules)
    assert m["origin"] == "operator_star" and m["protected"] and m["support"][0]["origin"] == "hermes"

    def p(guid, conv, origin="cio_curator", stage="actionable", expires="2026-10-22T20:00:00+00:00", stance="WATCH"):
        wl = W.membership([{"origin": origin, "reason": "r"}], rules)
        return {"security_guid": guid, "stage": stage, "conviction": conv, "stance": stance, "expires_at": expires,
                "evidence_at": "2026-10-22T19:00:00+00:00", "watchlist": wl}

    cap = rules["size_cap_per_stage"]["actionable"]
    rows = [p(f"g{i}", 50 + i) for i in range(cap + 2)] + [p("star", 1, origin="operator_star")]
    rows += [p("old", 90, expires="2026-10-01T00:00:00+00:00"), p("oldstar", 90, origin="operator_add",
                                                                   expires="2026-10-01T00:00:00+00:00"),
             p("avoid", 90, stance="AVOID")]
    res = W.curate(rows, rules, now=NOW)
    d = res["decisions"]
    assert d["star"]["decision"] == "keep"                       # operator stars are never auto-dropped
    assert d["oldstar"]["decision"] == "review"                  # protected + expired -> review, not out
    assert d["old"]["decision"] == "propose_out" and d["old"]["reason"].startswith("expired")
    assert d["avoid"]["decision"] == "propose_out"
    assert {k for k, v in d.items() if v["reason"].startswith("size cap")} == {"g0", "g1", "g2"}
    assert res["writes"].startswith("none")


def test_cli_dry_run_writes_nothing_and_write_shadow_writes_the_artifact(tmp_path, monkeypatch, capsys):
    from scripts import cio_prospect_shadow_build as cli
    root = _state(tmp_path)
    monkeypatch.setattr(B, "load_held", lambda state_root, held_reader=None: {
        "symbols": {"NVDA"}, "source": "test", "as_of": NOW.isoformat(), "status": "ok"})
    real_build = B.build
    monkeypatch.setattr(B, "build", lambda *a, **k: real_build(*a, **{**k, "identity_resolver": _identity}))
    before = _tree(root)
    assert cli.main(["--dry-run", "--state-root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["wrote"] == [] and out["summary"]["counts"]["prospects"] == 3
    assert _tree(root) == before
    assert cli.main(["--write-shadow", "--state-root", str(root)]) == 0
    capsys.readouterr()
    receipt = json.loads((root / cli.RECEIPT_REL).read_text())
    assert receipt["produced_count"] == 3 and receipt["ok_at"]
    shadow = json.loads((root / cli.SHADOW_REL).read_text())
    assert shadow["schema"] == "CioProspectShadowBuild@v1" and len(shadow["prospects"]) == 3


def test_builder_never_reads_positions_current_or_reaches_a_sender():
    for path in ("scripts/lib/cio_prospect_builder.py", "scripts/cio_prospect_shadow_build.py",
                 "scripts/lib/data_broker/cio_prospect.py", "scripts/lib/cio_prospect_watchlist_rules.py"):
        src = (ROOT / path).read_text()
        for bad in ("FROM positions_current", "JOIN positions_current", "place_order", "telegram_alert",
                    "send_telegram", "incident_notifier", "broker_access"):
            assert bad not in src, (path, bad)
        assert "InstrumentRecordStore(" not in src and "upsert_prospect" not in src, path   # the shadow is not the store


# ── 4. the n8n lane ─────────────────────────────────────────────────────────


def _row(path: str, key: str, lane: str, coll: str = "lanes") -> dict:
    return next(r for r in json.loads((ROOT / path).read_text())[coll] if r.get(key) == lane)


def test_lane_is_registered_at_shadow_and_dry_run_only():
    reg = _row("config/lane_registry.json", "lane_id", "cio-prospect-shadow")
    assert reg["scheduler"]["kind"] == "n8n" and reg["scheduler"]["expression"] == "dispatcher"
    assert reg["scheduler"]["stage"] == "shadow" and reg["dispatch"]["mode"] == "dry_run"
    assert reg["dispatch"]["class"] == "report" and reg["scheduler"]["match"] == "scripts/cio_prospect_shadow_build.py"
    al = _row("config/n8n_run_allowlist.json", "lane_id", "cio-prospect-shadow")
    assert al["live_arg"] is None and al["dry_run_arg"] == ["--dry-run"]
    assert al["command"] == ["$PY", "scripts/cio_prospect_shadow_build.py", "--with-db"]
    assert not any(n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR", "TELEGRAM"))
                   for n in al["env_names"])
    c = _row("config/n8n_health_contracts.json", "id", "cio-prospect-shadow", "contracts")
    assert c["status"] == "DRAFT" and c["stage"] == "shadow" and c["workflow_id"] == "dispatcher"
    assert c["healthy"][0]["check"] == "dry_run_writes_nothing"


# ── 5. the projection ───────────────────────────────────────────────────────


def test_projection_serves_the_shadow_labelled_and_says_so_on_gap(tmp_path):
    from lib.data_broker import cio_prospect as cp
    from lib.data_broker.catalog import PROJECTIONS
    entry = next(p for p in PROJECTIONS if p["id"] == "cio_prospect")
    assert entry["read_only"] and entry["provider_calls"] == 0 and "PROPOSED" in entry["authority_domain"]

    gap = cp.get_prospects(shadow_base=tmp_path / "missing.json", now=NOW, market_closed=False)
    assert gap["count"] == 0 and gap["gap"]["kind"] == "no_coverage" and gap["gap"]["declared_behaviour"] == "say_so"
    assert gap["source"]["kind"] == "shadow"

    root = _state(tmp_path / "s")
    doc = _build(root)
    art = tmp_path / "shadow.json"
    art.write_text(json.dumps(doc))
    res = cp.get_prospect("NVDA", shadow_base=art, now=NOW, market_closed=False)
    assert res["source"]["kind"] == "shadow" and res["source"]["label"].startswith("SHADOW")
    assert "registry_row_not_granted" in res["source"]["store_not_live"]
    assert res["stale_after_hours"] == 0.5 and res["stale"] is False
    assert res["prospect"]["conflict_count"] == 2 and res["prospect"]["stale"] is False
    later = cp.get_prospects(shadow_base=art, now=NOW + timedelta(hours=3), market_closed=False)
    assert later["stale"] is True and later["stale_rows"] == later["count"]     # per-row stale after expires_at
    assert cp.get_prospect(G_ACME, shadow_base=art, now=NOW)["prospect"]["symbol"] == "ACME"
    assert cp.get_prospect("GHOST", shadow_base=art, now=NOW)["prospect"] is None


def test_projection_reads_the_store_only_when_live(tmp_path):
    from lib.data_broker import cio_prospect as cp
    rec = ir.prospect_row(_prospect_record())
    seen = []

    def db_query(sql):
        seen.append(sql)
        return [rec]

    res = cp.get_prospects(db_query=db_query, now=NOW, market_closed=False,
                           status={"live": True, "mode": "dual_write", "reasons": []})
    assert res["source"]["kind"] == "store" and res["count"] == 1 and seen[0].startswith("SELECT ")
    res = cp.get_prospects(db_query=db_query, shadow_base=tmp_path / "none.json", now=NOW)
    assert res["source"]["kind"] == "shadow" and len(seen) == 1   # ungranted: the table is never even probed


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/cio_prospect_foundation_20261022.json").read_text())
    assert doc["anchor"] == "CIO_PROSPECT_FOUNDATION_20261022"
    assert "tests/test_cio_prospect_foundation_20261022.py" in doc["files"]

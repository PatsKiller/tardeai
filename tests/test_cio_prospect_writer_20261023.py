"""CIO prospect writer — the production caller of InstrumentRecordStore.upsert_prospect (ANCHOR CIO_PROSPECT_WRITER_20261023).

docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §11 backlog item 2, §11A (this writer), §12 audit (PR #2030).
Pins (task T-20261023-e95684):

1. Flag OFF (default): build + the shadow artifact + the writer receipt only; no jsonl prospect row, no Postgres
   contact (the backend is never even constructed). A dry run writes nothing at all.
2. Flag ON: one upsert per security_guid; a second identical run writes nothing (idempotent); the jsonl stays the
   store of record and the Postgres write happens only when prospect_store_status is live.
3. Conflicts recorded, never resolved: builder conflicts pass through; one GUID under two symbols is a conflict on
   the record; a Postgres row whose revision did not advance is listed, neither copy changed.
4. Fail-soft: a build error, a backend factory error and Postgres write errors never raise; they are counted; a
   circuit stops Postgres calls after repeated failures while the jsonl writes continue.
5. MBI_BEHAVIOR = 0: a BEHAVIOR_FIELDS key anywhere in a row or its lifecycle events refuses the row.
6. The curator and the entry-state runner call the writer only under --apply, fail-soft.
7. On an isolated throwaway Postgres cluster (skipped without server binaries or psycopg2): ON upserts once per
   GUID, the rerun is a no-op, a changed input advances the revision by one.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib import cio_prospect_builder as B  # noqa: E402
from scripts.lib import cio_prospect_writer as W  # noqa: E402
from tests.test_cio_prospect_foundation_20261022 import (  # noqa: E402
    BIN, G_NVDA, HAVE_PSYCOPG2, NOW, PSQL, UP, _identity, _state, _tree)

GRANTED = {"domains": [{"domain": "cio_prospect", "approval": {"approved_by": "operator (test)"}}]}
ON = {W.FLAG_ENV: "1"}


def _build_fn(*a, **k):
    k.pop("db_query", None)
    return B.build(*a, held_reader=lambda: {"symbols": {"NVDA"}, "source": "test_holdings", "as_of": NOW.isoformat()},
                   identity_resolver=_identity, **k)


class FakeBackend:
    def __init__(self, *, present=True, fail=False, upserted=1):
        self.present, self.fail, self.upserted = present, fail, upserted
        self.writes: list = []
        self.probes = 0

    def table_present(self):
        self.probes += 1
        return self.present

    def write(self, row, event, lifecycle=()):
        if self.fail:
            raise RuntimeError("connection refused (test)")
        self.writes.append((row, event, list(lifecycle)))
        return {"ok": True, "upserted": self.upserted, "event_appended": 1 + len(list(lifecycle))}


class Exploding:
    def __getattr__(self, name):
        raise AssertionError(f"Postgres touched with the flag off ({name})")


def _run(root, **kw):
    kw.setdefault("caller", "manual")
    kw.setdefault("apply", True)
    kw.setdefault("build_fn", _build_fn)
    kw.setdefault("now", NOW)
    return W.write_prospects(root, **kw)


def _jsonl(root: Path) -> list[dict]:
    p = root / W.RECORDS_REL
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.is_file() else []


def _prospect_lines(root: Path) -> list[dict]:
    return [r for r in _jsonl(root) if ir.is_prospect_record(r)]


# ── 1. flag OFF ──────────────────────────────────────────────────────────────


def test_dry_run_writes_nothing(tmp_path):
    root = _state(tmp_path)
    before = _tree(root)
    rep = _run(root, apply=False, env=ON, backend=Exploding(), registry=GRANTED)
    assert rep["ok"] and rep["mode"] == "dry_run" and rep["counts"]["built"] == 3 and rep["wrote"] == []
    assert _tree(root) == before


def test_flag_off_writes_the_shadow_and_receipt_only_and_never_touches_postgres(tmp_path):
    root = _state(tmp_path)
    jsonl_before = (root / W.RECORDS_REL).read_text()

    def factory():
        raise AssertionError("backend constructed with the flag off")

    rep = _run(root, env={}, backend_factory=factory, registry=GRANTED, caller="cio-opportunity-curator")
    assert rep["ok"] and rep["mode"] == "shadow_only" and rep["pg"] == {"mode": "off", "reasons": ["dual_write_flag_off"]}
    assert (root / W.RECORDS_REL).read_text() == jsonl_before          # no prospect row in the store of record
    shadow = json.loads((root / W.SHADOW_REL).read_text())
    assert shadow["schema"] == "CioProspectShadowBuild@v1" and len(shadow["prospects"]) == 3
    receipt = json.loads((root / W.receipt_rel("cio-opportunity-curator")).read_text())
    assert receipt["counts"]["built"] == 3 and receipt["counts"]["jsonl_written"] == 0
    assert receipt["memory_behavior_influence"] == 0
    # explicit backend object also untouched
    rep = _run(root, env={}, backend=Exploding(), registry=GRANTED)
    assert rep["ok"] and rep["counts"]["pg_upserted"] == 0


def test_subset_scope_never_overwrites_the_full_shadow(tmp_path):
    root = _state(tmp_path)
    _run(root, env={}, caller="cio-opportunity-curator")
    full = (root / W.SHADOW_REL).read_text()
    rep = _run(root, env={}, caller="cio-entry-state", scope="subset", symbols=["acme"])
    assert rep["counts"]["built"] == 1 and "shadow_skipped" in rep
    assert (root / W.SHADOW_REL).read_text() == full
    assert (root / W.receipt_rel("cio-entry-state")).is_file()
    assert W.receipt_rel("cio-entry-state") != W.receipt_rel("cio-opportunity-curator")


# ── 2. flag ON, idempotent ───────────────────────────────────────────────────


def test_flag_on_upserts_one_row_per_guid_and_the_rerun_is_a_no_op(tmp_path):
    root = _state(tmp_path)
    be = FakeBackend()
    rep = _run(root, env=ON, backend=be, registry=GRANTED)
    assert rep["ok"] and rep["pg"]["mode"] == "dual_write", rep
    c = rep["counts"]
    assert (c["built"], c["jsonl_written"], c["pg_upserted"], c["unchanged"]) == (3, 3, 3, 0)
    assert be.probes == 1                                              # one table probe per run, not per row
    assert len({r["security_guid"] for r, _, _ in be.writes}) == 3
    assert all(r["writer"] == "InstrumentRecordStore" for r, _, _ in be.writes)
    assert len(_prospect_lines(root)) == 3
    # Run 2 converges the fixture's legacy WATCH:NVDA kind split (the HELD:NVDA prospect now exists, so the
    # builder's subject_key_kind conflict closes) — a real change, written once. From then on: no writes.
    rep2 = _run(root, env=ON, backend=be, registry=GRANTED)
    assert rep2["counts"]["unchanged"] == 2 and rep2["counts"]["jsonl_written"] == 1
    n_writes, n_lines = len(be.writes), len(_prospect_lines(root))
    for _ in range(2):
        rep3 = _run(root, env=ON, backend=be, registry=GRANTED)
        assert rep3["counts"]["unchanged"] == 3 and rep3["counts"]["jsonl_written"] == 0, rep3["counts"]
    assert len(be.writes) == n_writes and len(_prospect_lines(root)) == n_lines
    stored = W.priors_by_guid(ir.InstrumentRecordStore(root / W.RECORDS_REL))
    assert all("instrument_records" not in r["provenance"]["sources"] for r in stored.values())


def test_flag_on_without_the_grant_writes_jsonl_and_stays_inert(tmp_path):
    root = _state(tmp_path)
    be = FakeBackend()
    rep = _run(root, env=ON, backend=be, registry={"domains": []})
    assert rep["pg"]["mode"] == "inert" and "registry_row_not_granted" in rep["pg"]["reasons"]
    assert be.writes == [] and be.probes == 0 and rep["counts"]["jsonl_written"] == 3


def test_a_changed_input_advances_the_revision_once(tmp_path):
    root = _state(tmp_path)
    be = FakeBackend()
    _run(root, env=ON, backend=be, registry=GRANTED)
    p = root / "data/cio/cio_opportunity_projection.json"
    doc = json.loads(p.read_text())
    doc["items"]["ACME"]["conviction"] = 60.0
    p.write_text(json.dumps(doc))
    rep = _run(root, env=ON, backend=be, registry=GRANTED, now=NOW + timedelta(minutes=30))
    acme = [r for r, _, _ in be.writes if r["symbol"] == "ACME"]
    assert [r["revision"] for r in acme] == [1, 2] and rep["counts"]["pg_upserted"] >= 1


# ── 3. conflicts recorded, never resolved ────────────────────────────────────


def test_builder_conflicts_pass_through_untouched(tmp_path):
    root = _state(tmp_path)
    be = FakeBackend()
    _run(root, env=ON, backend=be, registry=GRANTED)
    nv = next(r for r, _, _ in be.writes if r["security_guid"] == G_NVDA)
    assert sorted(c["field"] for c in nv["conflicts"]) == ["stance", "subject_key_kind"]
    assert all(c.get("resolved") is False for c in nv["conflicts"])


def test_one_guid_under_two_symbols_is_a_recorded_conflict(tmp_path):
    root = _state(tmp_path)
    store = ir.InstrumentRecordStore(root / W.RECORDS_REL)
    rec = ir.new_record("WATCH", "NVDX")
    rec.update({"security_guid": G_NVDA, "issuer_guid": _identity("NVDA")["issuer_guid"]})
    rec, _ = ir.apply_prospect(rec, prospect={
        "security_guid": G_NVDA, "issuer_guid": _identity("NVDA")["issuer_guid"], "stage": "watching",
        "stance": "WATCH", "conviction": 50.0, "evidence_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat()})
    store.upsert(rec)
    be = FakeBackend()
    rep = _run(root, env=ON, backend=be, registry=GRANTED)
    nv = next(r for r, _, _ in be.writes if r["security_guid"] == G_NVDA)
    sym_c = [c for c in nv["conflicts"] if c["field"] == "symbol"]
    assert len(sym_c) == 1 and {v["value"] for v in sym_c[0]["values"]} == {"NVDX", "NVDA"}
    assert sym_c[0]["resolved"] is False and rep["counts"]["writer_conflicts"] == 1
    assert nv["revision"] == 2                                          # continues the GUID's revision line


def test_postgres_ahead_of_the_jsonl_is_listed_never_overwritten(tmp_path):
    root = _state(tmp_path)
    rep = _run(root, env=ON, backend=FakeBackend(upserted=0), registry=GRANTED)
    assert rep["counts"]["pg_not_advanced"] == 3 and rep["counts"]["pg_upserted"] == 0
    assert {c["kind"] for c in rep["conflicts"]} == {"pg_revision_not_advanced"}


# ── 4. fail-soft ─────────────────────────────────────────────────────────────


def test_postgres_failure_is_fail_soft_and_opens_a_circuit(tmp_path, monkeypatch, capsys):
    root = _state(tmp_path)
    be = FakeBackend(fail=True)
    monkeypatch.setattr(W, "PG_CIRCUIT_AFTER", 2)
    rep = _run(root, env=ON, backend=be, registry=GRANTED, caller="cio-opportunity-curator")
    assert rep["ok"] is False and rep["counts"]["pg_errors"] == 2 and rep["counts"]["jsonl_written"] == 3
    assert "circuit" in rep["pg"]
    assert "postgres write failed" in capsys.readouterr().err                         # logged
    receipt = json.loads((root / W.receipt_rel("cio-opportunity-curator")).read_text())
    assert receipt["counts"]["pg_errors"] == 2                                          # counted durably


def test_build_and_backend_errors_never_raise(tmp_path):
    root = _state(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("builder exploded (test)")

    rep = _run(root, env=ON, build_fn=boom)
    assert rep["ok"] is False and rep["errors"][0]["stage"] == "run"

    def bad_factory():
        raise OSError("no database (test)")

    rep = _run(root, env=ON, backend_factory=bad_factory, registry=GRANTED)
    assert rep["counts"]["jsonl_written"] == 3 and rep["pg"]["mode"] == "inert"
    assert any(e.get("stage") == "pg_backend" for e in rep["errors"])

    class ProbeFails(FakeBackend):
        def table_present(self):
            raise ConnectionError("down (test)")

    rep = _run(root, env=ON, backend=ProbeFails(), registry=GRANTED)
    assert rep["pg"]["mode"] == "inert" and any(r.startswith("table_probe_failed") for r in rep["pg"]["reasons"])


# ── 5. MBI_BEHAVIOR = 0 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("where", ["next_trigger", "lifecycle_events", "watchlist"])
@pytest.mark.parametrize("bad", ["stop", "size_usd", "order", "qty"])
def test_behavior_fields_refuse_the_row(tmp_path, where, bad):
    root = _state(tmp_path)

    def injected(*a, **k):
        doc = _build_fn(*a, **k)
        r = next(r for r in doc["prospects"] if r["security_guid"] == G_NVDA)
        if where == "lifecycle_events":
            r["lifecycle_events"] = [{"event_type": "update", "event_key": "x", "change": {bad: 1}}]
        else:
            r[where] = {**(r.get(where) or {}), bad: 1}
        return doc

    be = FakeBackend()
    rep = _run(root, env=ON, backend=be, registry=GRANTED, build_fn=injected)
    assert rep["counts"]["refused_behavior"] == 1 and rep["counts"]["jsonl_written"] == 2
    assert G_NVDA not in {r["security_guid"] for r, _, _ in be.writes}
    assert G_NVDA not in {r.get("security_guid") for r in _prospect_lines(root)}


def test_merge_refuses_behavior_directly():
    with pytest.raises(ir.BehaviorWriteRefused):
        W.merge({"symbol": "NVDA", "subject_key": "HELD:NVDA", "security_guid": G_NVDA,
                 "position_ref": {"shares": 10}}, None, now=NOW)


# ── 6. callers ───────────────────────────────────────────────────────────────


def test_curator_calls_the_writer_only_under_apply_and_fail_soft(monkeypatch):
    src = (ROOT / "scripts/cio_opportunity_curator.py").read_text()
    body = src.split("    if apply:\n", 1)[1].split("    return report", 1)[0]
    assert "write_cio_prospects(apply=True)" in body
    assert src.count("write_cio_prospects(") == 2                       # the def + the one call under apply
    import importlib
    cur = importlib.import_module("scripts.cio_opportunity_curator")
    monkeypatch.setattr(W, "write_prospects", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    out = cur.write_cio_prospects(apply=True)
    assert out["ok"] is False and "RuntimeError" in out["error"]


def test_entry_state_runner_calls_the_writer_for_changed_names_fail_soft(monkeypatch):
    src = (ROOT / "scripts/cio_entry_state_runner.py").read_text()
    apply_block = src.split("    if a.apply:\n        for sym, r in results.items():", 1)[1].split("    else:\n", 1)[0]
    assert "write_cio_prospects(changed)" in apply_block
    import importlib
    run = importlib.import_module("scripts.cio_entry_state_runner")
    assert run.write_cio_prospects([]) == {"skipped": "no entry-state change this run"}
    seen = {}

    def fake(state_root, **k):
        seen.update(k)
        return {"mode": "shadow_only", "scope": k["scope"], "ok": True, "counts": {}, "apply": True,
                "caller": k["caller"]}

    monkeypatch.setattr(W, "write_prospects", fake)
    out = run.write_cio_prospects(["ACME"])
    assert seen["scope"] == "subset" and seen["symbols"] == ["ACME"] and seen["caller"] == "cio-entry-state"
    assert out["ok"] is True
    monkeypatch.setattr(W, "write_prospects", lambda *a, **k: (_ for _ in ()).throw(ValueError("y")))
    assert run.write_cio_prospects(["ACME"])["ok"] is False


def test_writer_never_reaches_a_broker_sender_or_model():
    src = (ROOT / "scripts/lib/cio_prospect_writer.py").read_text()
    for token in ("place_order", "send_telegram", "schwab", "alpaca", "anthropic", "openai", "DELETE ", "DROP ",
                  "TRUNCATE", "positions_current"):
        assert token not in src, token


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/cio_prospect_writer_20261023.json").read_text())
    assert doc["anchor"] == "CIO_PROSPECT_WRITER_20261023"
    assert "tests/test_cio_prospect_writer_20261023.py" in doc["files"]


# ── 7. isolated Postgres ─────────────────────────────────────────────────────

PORT = 55437
NEEDS_PG = pytest.mark.skipif(BIN is None or PSQL is None or not HAVE_PSYCOPG2,
                              reason="no PostgreSQL server binaries or psycopg2 on this host")


@pytest.fixture(scope="module")
def cluster():
    base = Path(tempfile.mkdtemp(prefix="cpw-pg-", dir=os.environ.get("TMPDIR") or None))
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    env = {**os.environ, "LC_ALL": "C"}
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD", "PGSERVICE", "PGPASSFILE"):
        env.pop(k, None)
    subprocess.run([str(BIN / "initdb"), "-D", str(data), "-U", "cpw_admin", "--auth=trust", "-E", "UTF8"],
                   check=True, capture_output=True, env=env)
    opts = f"-c listen_addresses='' -c unix_socket_directories={sock} -p {PORT} -c fsync=off"
    subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-o", opts, "-l", str(base / "log"), "-w", "start"],
                   check=True, capture_output=True, env=env)

    def psql(user, db, sql=None, file=None):
        argv = [PSQL, "-X", "-h", str(sock), "-p", str(PORT), "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-tA"]
        argv += ["-f", str(file)] if file else ["-c", sql]
        p = subprocess.run(argv, capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    try:
        assert psql("cpw_admin", "postgres", "CREATE ROLE trade_ai LOGIN")[0] == 0
        assert psql("cpw_admin", "postgres", "CREATE DATABASE cpw_scratch")[0] == 0
        assert psql("cpw_admin", "cpw_scratch", "GRANT USAGE, CREATE ON SCHEMA public TO trade_ai")[0] == 0
        rc, out = psql("cpw_admin", "cpw_scratch", file=UP)
        assert rc == 0, out
        psql.sock = sock  # type: ignore[attr-defined]
        yield psql
    finally:
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], capture_output=True, env=env)
        shutil.rmtree(base, ignore_errors=True)  # the throwaway cluster's own temp tree only


@NEEDS_PG
def test_flag_on_upserts_idempotently_on_an_isolated_cluster(cluster, tmp_path):
    psql = cluster
    import psycopg2

    def factory():
        return ir.ProspectPgBackend(lambda: psycopg2.connect(host=str(psql.sock), port=PORT, user="trade_ai",
                                                             dbname="cpw_scratch"))

    root = _state(tmp_path)
    rep = _run(root, env=ON, backend_factory=factory, registry=GRANTED)
    assert rep["ok"] and rep["pg"]["mode"] == "dual_write" and rep["counts"]["pg_upserted"] == 3, rep
    q = lambda sql: psql("cpw_admin", "cpw_scratch", sql)[1]  # noqa: E731
    assert q("SELECT count(*) FROM cio_prospect") == "3"
    assert q("SELECT count(DISTINCT security_guid) FROM cio_prospect") == "3"
    assert q("SELECT count(*) FROM cio_prospect_events") == "3"
    rep2 = _run(root, env=ON, backend_factory=factory, registry=GRANTED)   # converges the legacy WATCH:NVDA split
    assert rep2["counts"]["pg_upserted"] == 1 and q("SELECT revision FROM cio_prospect WHERE symbol = 'NVDA'") == "2"
    events = q("SELECT count(*) FROM cio_prospect_events")
    for _ in range(2):                                                          # identical reruns: nothing written
        rep3 = _run(root, env=ON, backend_factory=factory, registry=GRANTED)
        assert rep3["counts"]["unchanged"] == 3 and rep3["counts"]["pg_upserted"] == 0
    assert q("SELECT count(*) FROM cio_prospect") == "3" and q("SELECT count(*) FROM cio_prospect_events") == events
    p = root / "data/cio/cio_opportunity_projection.json"
    doc = json.loads(p.read_text())
    doc["items"]["ACME"]["conviction"] = 60.0
    p.write_text(json.dumps(doc))
    rep3 = _run(root, env=ON, backend_factory=factory, registry=GRANTED, now=NOW + timedelta(minutes=30))
    assert rep3["ok"] and rep3["counts"]["pg_not_advanced"] == 0
    assert q("SELECT revision FROM cio_prospect WHERE symbol = 'ACME'") == "2"
    assert q("SELECT count(*) FROM cio_prospect") == "3"
    assert q("SELECT DISTINCT writer FROM cio_prospect") == "InstrumentRecordStore"


def test_navn_lifecycle_passes_the_rail_and_carries_its_events(tmp_path):
    """The real worked example (exited position, 14 lifecycle events) is not refused by the MBI rail."""
    from tests.test_cio_prospect_foundation_20261022 import NAVN, NAVN_NOW, _navn_state

    def navn_build(*a, **k):
        k.pop("db_query", None)
        k["now"] = NAVN_NOW
        return B.build(*a, held_reader=lambda: {"symbols": {"NAVN"}, "source": "test", "as_of": NAVN_NOW.isoformat()},
                       identity_resolver=lambda s: NAVN["identity"] if s == "NAVN" else _identity(s),
                       captured=NAVN["captured"], **k)

    be = FakeBackend()
    rep = _run(_navn_state(tmp_path), env=ON, backend=be, registry=GRANTED, build_fn=navn_build, now=NAVN_NOW)
    assert rep["counts"]["refused_behavior"] == 0 and rep["counts"]["pg_upserted"] == 1, rep
    row, event, lifecycle = be.writes[0]
    assert row["symbol"] == "NAVN" and len(lifecycle) == 14 and event["event_type"] == "mint"


def test_timestamp_only_moves_are_not_a_version_until_the_refresh_is_due(tmp_path):
    root = _state(tmp_path)
    be = FakeBackend()
    for _ in range(2):                                   # mint + converge the legacy kind split
        _run(root, env=ON, backend=be, registry=GRANTED)
    p = root / "data/cio/cio_opportunity_projection.json"
    doc = json.loads(p.read_text())
    for it in doc["items"].values():                     # the curator re-ran: same judgment, newer as_of
        it["as_of"] = "2026-10-22T19:55:00+00:00"
    doc["as_of"] = "2026-10-22T19:55:00+00:00"
    p.write_text(json.dumps(doc))
    n = len(be.writes)
    rep = _run(root, env=ON, backend=be, registry=GRANTED, now=NOW + timedelta(minutes=30))
    assert rep["counts"]["immaterial"] >= 2 and rep["counts"]["jsonl_written"] == 0 and len(be.writes) == n
    rep = _run(root, env={**ON, W.REFRESH_ENV: "0"}, backend=be, registry=GRANTED, now=NOW + timedelta(minutes=30))
    assert rep["counts"]["jsonl_written"] >= 2 and len(be.writes) > n          # refresh due: timestamps advance


def test_material_changes_rule():
    a = {"prospect_schema": ir.PROSPECT_SCHEMA, "stage": "watching", "stance": "WATCH", "conviction": 50.0,
         "conviction_components": {"opportunity_score": {"value": 50.0, "evidence_at": "t1"}},
         "evidence_at": "t1", "expires_at": "t2", "subject_key": "WATCH:X"}
    assert W.material_changes(None, a) == ["mint"]
    assert W.material_changes(a, {**a, "evidence_at": "t3", "expires_at": "t4", "conviction": 50.6}) == []
    assert W.material_changes(a, {**a, "conviction": 51.2}) == ["conviction"]
    assert W.material_changes(a, {**a, "stance": "ADD"}) == ["stance"]
    assert W.material_changes(a, {**a, "conflicts": [{"field": "stance"}]}) == ["conflicts"]

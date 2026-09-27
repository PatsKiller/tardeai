"""Options history -> CIO bitemporal memory (M2), and the CIO review reads it back.

2026-09-26: the CIO's long-term memory (memory_r10_m2) held nothing about
options; every thesis version, decision, follow-up and validation lived only in
data/cio/options_theses.jsonl. Hermetic: no database, no psycopg2 (connections
are faked or refused by monkeypatch).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import cio_memory_integration as cmi  # noqa: E402
from scripts.lib import options_cio_review as ocr  # noqa: E402
from scripts.lib import options_memory_envelope as ome  # noqa: E402
from scripts.lib import options_memory_projection as proj  # noqa: E402
from scripts.lib.options_thesis import OptionsThesisStore  # noqa: E402

GUID = "11111111-2222-3333-4444-555555555555"


def _no_issuer(_sym):
    return None


def _store(tmp_path) -> OptionsThesisStore:
    """A realistic store: thesis v1 -> decision -> follow-up -> complete -> decision 2 -> validated -> abandoned."""
    st = OptionsThesisStore(tmp_path / "options_theses.jsonl")
    st.publish(
        {
            "position_guid": GUID,
            "symbol": "DELL",
            "strategy_type": "cash_secured_put",
            "investment_thesis": {"pin": "sym@v3", "state": "SUPPORTED", "stance": "BULLISH", "summary": "AI servers"},
            "catalysts": ["Calendar: next earnings 2026-11-27"],
            "exit_criteria": ["Close below 480"],
            "missing_required": [],
            "thesis_gate_state": "SUPPORTED",
            "portfolio_impact": {"account": "IRA-1234", "max_loss": 49000, "capital_required": 49000},
            "entry_criteria": {"premium": 21.57, "strike": 490.0},
            "contracts": 1,
            "risk_factors": ["Max loss per contract $49,000"],
        }
    )
    rv = {
        "outcome": "MORE_RESEARCH",
        "confidence": "LOW",
        "reasoning": "Catalyst thin",
        "concerns": ["valuation"],
        "unknowns": ["guidance"],
        "assumptions_challenged": [],
    }
    st.append_event(
        GUID,
        "OPTIONS_THESIS_DECISION",
        decision_guid="dec_a",
        outcome="MORE_RESEARCH",
        confidence="LOW",
        review=rv,
        reviewed_pin=f"opt_{GUID}@v1",
        supersedes=None,
    )
    st.append_event(
        GUID,
        "OPTIONS_THESIS_FOLLOWUP_REQUESTED",
        research_id="r1",
        plan_id="p1",
        deliverables=[{"intent": "cio_followup_1", "text": "DELL: guidance"}],
        due_at="2026-09-27T12:00:00+00:00",
        for_decision="dec_a",
    )
    st.append_event(
        GUID,
        "OPTIONS_THESIS_FOLLOWUP_COMPLETE",
        research_id="r1",
        answers=[{"deliverable": "DELL: guidance", "answered": True, "answer": "raised"}],
    )
    st.append_event(
        GUID,
        "OPTIONS_THESIS_DECISION",
        decision_guid="dec_b",
        outcome="APPROVE",
        confidence="MEDIUM",
        review=dict(rv, outcome="APPROVE", reasoning="Guidance raised"),
        reviewed_pin=f"opt_{GUID}@v1",
        supersedes="dec_a",
    )
    st.append_event(
        GUID,
        "OPTIONS_VALIDATED",
        status="CHANGED",
        material_changes=["premium 21.57 -> 25 (+15.9%)"],
        live={"bid": 24.5, "ask": 25.5, "mid": 25.0},
        recomputed={"max_loss": 46500},
        contracts=1,
        validated_at="2026-09-27T14:00:00+00:00",
    )
    st.append_event(GUID, "OPTIONS_THESIS_ABANDONED", reason="no fill", missing=[])
    return st


def _plan(tmp_path, watermark=None):
    st = _store(tmp_path)
    return st, proj.plan(st._events(), watermark, issuer_resolver=_no_issuer)


# ── mapping ────────────────────────────────────────────────────────────────


def test_every_event_type_maps_to_its_predicate(tmp_path):
    _st, pl = _plan(tmp_path)
    assert pl["counts"] == {
        "options_thesis": 1,
        "options_cio_decision": 2,
        "options_followup": 2,
        "options_validation": 1,
        "options_thesis_outcome": 1,
    }
    by = {}
    for e in pl["envelopes"]:
        by.setdefault(e["predicate"], []).append(e)
        assert e["source_type"] == "options_thesis_store"
        assert e["trace_id"] == GUID and e["symbol"] == "DELL" and e["valid_from"]
        assert e["object"]["option_strategy_guid"] == GUID
    thesis = by["options_thesis"][0]
    assert thesis["subject_guid"] == GUID  # single-valued per strategy
    assert thesis["object"]["pin"] == f"opt_{GUID}@v1"
    assert thesis["object"]["investment_thesis"]["summary"] == "AI servers"
    assert thesis["object"]["catalysts"] and thesis["object"]["exit_criteria"]
    d1, d2 = by["options_cio_decision"]
    assert d1["subject_guid"] == str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:options_memory:{GUID}|dec_a"))
    assert d1["subject_guid"] != d2["subject_guid"]  # one identity per decision
    assert d2["object"]["outcome"] == "APPROVE" and d2["object"]["reasoning"] == "Guidance raised"
    assert d1["object"]["concerns"] == ["valuation"] and d1["object"]["unknowns"] == ["guidance"]
    f1, f2 = by["options_followup"]
    assert f1["subject_guid"] != f2["subject_guid"]
    assert f1["object"]["deliverables"] == ["DELL: guidance"] and f1["object"]["due_at"]
    assert f2["object"]["stage"] == "COMPLETE"
    v = by["options_validation"][0]["object"]
    assert v["status"] == "CHANGED" and v["material_changes"] and v["validated_at"]
    assert by["options_thesis_outcome"][0]["object"]["outcome"] == "ABANDONED"
    assert "options_cio_decision" not in cmi.SINGLE_VALUED_PREDICATES
    assert "options_thesis" in cmi.SINGLE_VALUED_PREDICATES


def test_payload_allowlist_keeps_financial_fields_out(tmp_path):
    _st, pl = _plan(tmp_path)
    blob = json.dumps([e["object"] for e in pl["envelopes"]])
    for key in (
        "account",
        "contracts",
        "max_loss",
        "capital_required",
        "premium",
        "bid",
        "ask",
        "live",
        "recomputed",
        "portfolio_impact",
        "entry_criteria",
        "risk_factors",
    ):
        assert f'"{key}"' not in blob, key
    assert "IRA-1234" not in blob and "49000" not in blob
    for e in pl["envelopes"]:
        assert not proj.forbidden_keys_deep(e["object"])
        assert not cmi.FORBIDDEN_OBJECT_KEYS & set(e["object"])


def test_untracked_event_types_are_not_projected(tmp_path):
    st = _store(tmp_path)
    st.append_event(GUID, "OPTIONS_THESIS_RESEARCH_REQUESTED", research_id="r0")
    pl = proj.plan(st._events(), None, issuer_resolver=_no_issuer)
    assert pl["not_projected"] == {"OPTIONS_THESIS_RESEARCH_REQUESTED": 1}
    assert pl["new_watermark"] == st._events()[-1]["event_hash"]


def test_issuer_guid_comes_from_the_registry_resolver(tmp_path):
    st = _store(tmp_path)
    pl = proj.plan(st._events(), None, issuer_resolver=lambda s: "iss-" + s)
    assert {e["issuer_guid"] for e in pl["envelopes"]} == {"iss-DELL"}


# ── watermark + provenance ─────────────────────────────────────────────────


def test_watermark_is_idempotent(tmp_path):
    st, pl = _plan(tmp_path)
    again = proj.plan(st._events(), pl["new_watermark"], issuer_resolver=_no_issuer)
    assert again["events_pending"] == 0 and again["envelopes"] == [] and again["watermark_found"]
    mid = st._events()[2]["event_hash"]
    part = proj.plan(st._events(), mid, issuer_resolver=_no_issuer)
    assert part["events_pending"] == len(st._events()) - 3
    lost = proj.plan(st._events(), "not-in-log", issuer_resolver=_no_issuer)
    assert lost["watermark_found"] is False and lost["events_pending"] == len(st._events())


def test_superseding_decision_plans_a_provenance_edge(tmp_path):
    st, pl = _plan(tmp_path)
    decs = [e for e in pl["envelopes"] if e["predicate"] == "options_cio_decision"]
    assert "provenance" not in decs[0]
    prov = decs[1]["provenance"]
    assert prov["relation"] == "SUPERSEDES"
    assert prov["from_source_id"] == decs[1]["source_id"]
    assert prov["to_source_id"] == decs[0]["source_id"]
    assert pl["provenance_planned"] == 1


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sql.append((sql, params))
        s = " ".join(sql.split())
        if "FROM memory_r10_m2.memory_fact_version" in s:
            self._row = (self.conn.facts[params[2]],) if params[2] in self.conn.facts else None
        elif s.startswith("SELECT 1 FROM memory_r10_m2.provenance_edge"):
            self._row = (1,) if (params[1], params[2]) in self.conn.edges else None
        elif s.startswith("INSERT INTO memory_r10_m2.provenance_edge"):
            self.conn.edges.add((params[1], params[2]))
        else:
            self._row = None

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self):
        self.facts: dict[str, str] = {}
        self.edges: set = set()
        self.sql: list = []

    def cursor(self):
        return _FakeCursor(self)


class _FakeIntegrator:
    tenant_id = "tradeai_default"

    def __init__(self):
        self.conn = _FakeConn()
        self.written: list[dict] = []

    def connect(self):
        return self.conn

    def _set_tenant(self, conn, *, local=False):
        pass

    def integrate_envelope(self, env, *, apply, dry_run):
        assert apply and "provenance" not in env
        fid = str(uuid.uuid4())
        self.conn.facts[env["source_id"]] = fid
        self.written.append(env)
        return {"memory_version_id": fid}


def test_apply_skips_existing_source_ids_and_writes_the_edge(tmp_path):
    from scripts import options_memory_projector as cli

    _st, pl = _plan(tmp_path)
    integ = _FakeIntegrator()
    first_sid = pl["envelopes"][0]["source_id"]
    integ.conn.facts[first_sid] = str(uuid.uuid4())  # already in memory
    state_path = tmp_path / "state.json"
    res = cli.apply_plan(pl, integrator=integ, state_path=state_path, state={})
    assert res["skipped_existing"] == 1 and res["written"] == len(pl["envelopes"]) - 1
    assert res["provenance_edges"] == 1 and not res["errors"]
    assert json.loads(state_path.read_text())["watermark_event_hash"] == pl["new_watermark"]
    # Re-running the same plan writes nothing new: source_id idempotency.
    res2 = cli.apply_plan(pl, integrator=integ, state_path=state_path, state={})
    assert res2["written"] == 0 and res2["provenance_edges"] == 0


def test_apply_stops_at_first_failure_and_keeps_watermark_honest(tmp_path):
    from scripts import options_memory_projector as cli

    _st, pl = _plan(tmp_path)
    integ = _FakeIntegrator()
    calls = {"n": 0}
    real = integ.integrate_envelope

    def flaky(env, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(env, **kw)

    integ.integrate_envelope = flaky
    state_path = tmp_path / "state.json"
    res = cli.apply_plan(pl, integrator=integ, state_path=state_path, state={})
    assert res["errors"] and res["written"] == 1
    assert json.loads(state_path.read_text())["watermark_event_hash"] == pl["envelopes"][0]["source_id"]


def test_dry_run_never_connects(tmp_path, monkeypatch, capsys):
    from scripts import options_memory_projector as cli

    st = _store(tmp_path)

    def refuse(*a, **k):
        raise AssertionError("dry run connected")

    monkeypatch.setattr(cmi.CIOEnvelopeIntegrator, "connect", refuse)
    monkeypatch.setitem(sys.modules, "psycopg2", None)  # any import would fail loudly
    monkeypatch.setattr(proj, "_default_issuer_resolver", _no_issuer)
    rc = cli.main(["--store", str(st.path), "--state", str(tmp_path / "s.json")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["mode"] == "dry_run" and out["counts"]["options_cio_decision"] == 2
    assert len(out["sample_envelopes"]) == 1
    assert not (tmp_path / "s.json").exists()  # dry run never advances the watermark


def test_apply_refuses_without_dsn_and_on_unauthorized_production(tmp_path, monkeypatch, capsys):
    from scripts import options_memory_projector as cli

    st = _store(tmp_path)
    monkeypatch.setattr(proj, "_default_issuer_resolver", _no_issuer)
    monkeypatch.delenv("M2_DSN", raising=False)
    assert cli.main(["--apply", "--store", str(st.path), "--state", str(tmp_path / "s.json")]) == 2
    assert "M2_DSN_REQUIRED" in capsys.readouterr().out
    monkeypatch.setenv("M2_DSN", "postgresql://u:secret@127.0.0.1:5432/db")
    monkeypatch.delenv("TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED", raising=False)
    assert cli.main(["--apply", "--store", str(st.path), "--state", str(tmp_path / "s.json")]) == 2
    out = capsys.readouterr().out
    assert "M2_DSN_PRODUCTION_PORT_FORBIDDEN" in out and "secret" not in out


# ── integrator backward compatibility ──────────────────────────────────────


def test_integrator_default_source_type_unchanged():
    integ = cmi.CIOEnvelopeIntegrator(dsn="postgresql://u:p@127.0.0.1:55432/x")
    r = integ.integrate_envelope({"predicate": "thesis", "claim": "c", "symbol": "SCHD"}, apply=False)
    assert r["source_type"] == "cio_envelope" == cmi.DEFAULT_SOURCE_TYPE
    base_issuer = r["issuer_guid"]
    r2 = integ.integrate_envelope(
        {
            "predicate": "options_thesis",
            "claim": "c",
            "symbol": "SCHD",
            "subject_guid": GUID,
            "issuer_guid": "iss-x",
            "source_type": "options_thesis_store",
        },
        apply=False,
    )
    assert r2["source_type"] == "options_thesis_store" and r2["issuer_guid"] == "iss-x"
    assert r2["subject_guid"] == GUID and r2["temporal_policy"] == "SINGLE_VALUED_CURRENT"
    r3 = integ.integrate_envelope({"predicate": "thesis", "claim": "c", "symbol": "SCHD"}, apply=False)
    assert r3["issuer_guid"] == base_issuer  # no issuer_guid given: unchanged
    with pytest.raises(RuntimeError, match="FINANCIAL_TRUTH_REFUSED"):
        integ.integrate_envelope({"predicate": "options_thesis", "object": {"qty": 1}}, apply=False)


def test_integrator_passes_source_type_to_both_writers():
    class Cur:
        def __init__(self, log):
            self.log = log

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.log.append((" ".join(sql.split()), params))

        def fetchone(self):
            return ("00000000-0000-0000-0000-000000000001",)

        def fetchall(self):
            return []

    class Conn:
        def __init__(self):
            self.log = []

        def cursor(self):
            return Cur(self.log)

    integ = cmi.CIOEnvelopeIntegrator(dsn="postgresql://u:p@127.0.0.1:55432/x")
    ids = {"subject_guid": GUID}
    for pred, fn, default in (
        ("options_cio_decision", "save_bitemporal_fact_version", False),
        ("options_thesis", "supersede_single_valued_fact", False),
        ("note", "save_bitemporal_fact_version", True),
    ):
        conn = Conn()
        env = {} if default else {"source_type": "options_thesis_store"}
        policy = "SINGLE_VALUED_CURRENT" if pred in cmi.SINGLE_VALUED_PREDICATES else "MULTI_VALUED"
        kw = {} if default else {"source_type": "options_thesis_store"}
        integ._apply_in_transaction(
            conn,
            env,
            {},
            obj={"a": 1},
            claim="c",
            subject_guid=GUID,
            ids=ids,
            predicate=pred,
            temporal_policy=policy,
            valid_period="[2026-09-26,)",
            **kw,
        )
        call = next(p for s, p in conn.log if fn in s)
        assert ("cio_envelope" if default else "options_thesis_store") in call


# ── read side: build_facts ─────────────────────────────────────────────────

P = {
    "symbol": "DELL",
    "strategy": "cash_secured_put",
    "option_strategy_guid": GUID,
    "underlying_price": 562.89,
    "strike": 490.0,
    "premium": 21.57,
    "dte": 55,
}


def test_build_facts_includes_prior_decisions_when_enabled(monkeypatch):
    monkeypatch.delenv("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS", raising=False)
    prior = [
        {
            "kind": "options_cio_decision",
            "as_of": "2026-09-20",
            "outcome": "MORE_RESEARCH",
            "reasoning": "IV rank 71 too rich",
        }
    ]
    seen = {}

    def loader(guid, sym, *, limit, lookback_days):
        seen.update(guid=guid, sym=sym, limit=limit, lookback_days=lookback_days)
        return prior

    f = ocr.build_facts(P, memory={"memory_reads": True, "limit": 4, "lookback_days": 30, "loader": loader})
    assert f["prior_decisions"] == prior
    assert seen == {"guid": GUID, "sym": "DELL", "limit": 4, "lookback_days": 30}
    # prior numbers are part of the facts, so the traceability rail accepts them
    ok, errs = ocr.validate(
        {"outcome": "MONITOR_ONLY", "confidence": "LOW", "reasoning": "Last review flagged IV rank 71"}, f
    )
    assert ok, errs


def test_build_facts_off_by_config_and_env_override(monkeypatch):
    monkeypatch.delenv("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS", raising=False)
    assert "prior_decisions" not in ocr.build_facts(P)
    assert "prior_decisions" not in ocr.build_facts(P, memory={"memory_reads": False, "loader": lambda *a, **k: [1]})
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS", "0")
    assert "prior_decisions" not in ocr.build_facts(P, memory={"memory_reads": True, "loader": lambda *a, **k: [1]})
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS", "1")
    f = ocr.build_facts(P, memory={"memory_reads": False, "loader": lambda *a, **k: [{"kind": "x"}]})
    assert f["prior_decisions"] == [{"kind": "x"}]


def test_build_facts_empty_on_read_failure(monkeypatch):
    monkeypatch.delenv("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS", raising=False)

    def boom(*a, **k):
        raise RuntimeError("db down")

    f = ocr.build_facts(P, memory={"memory_reads": True, "loader": boom})
    assert f["prior_decisions"] == []
    # the real loader with a failing connection also returns [] rather than raising
    assert ome.load_prior_options_facts(GUID, "DELL", limit=3, lookback_days=30, connect=boom) == []


def test_real_loader_query_and_compact_rows():
    class Cur:
        def __init__(self, log):
            self.log = log

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.log.append((" ".join(sql.split()), params))

        def fetchall(self):
            return [
                (
                    "options_cio_decision",
                    {
                        "option_strategy_guid": GUID,
                        "outcome": "REJECT",
                        "confidence": "HIGH",
                        "reasoning": "spread too wide",
                        "concerns": ["a", "b", "c", "d"],
                        "decision_guid": "dec_z",
                    },
                    "2026-09-25T10:00:00+00:00",
                ),
                (
                    "options_thesis",
                    json.dumps(
                        {
                            "option_strategy_guid": "other",
                            "thesis_state": "SUPPORTED",
                            "investment_thesis": {"summary": "s"},
                        }
                    ),
                    "2026-09-24T10:00:00+00:00",
                ),
            ]

    class Conn:
        def __init__(self):
            self.log = []
            self.closed = False

        def cursor(self):
            return Cur(self.log)

        def close(self):
            self.closed = True

    conn = Conn()
    rows = ome.load_prior_options_facts(GUID, "dell", limit=5, lookback_days=90, connect=lambda: conn)
    assert rows[0] == {
        "kind": "options_cio_decision",
        "as_of": "2026-09-25",
        "same_strategy": True,
        "outcome": "REJECT",
        "confidence": "HIGH",
        "reasoning": "spread too wide",
        "concerns": ["a", "b", "c"],
    }
    assert rows[1]["same_strategy"] is False and rows[1]["summary"] == "s"
    assert "dec_z" not in json.dumps(rows)  # GUIDs stay out of the review facts
    sql, params = conn.log[-1]
    assert "upper_inf(tx_period)" in sql and params[1] == "options_thesis_store"
    assert params[3] == GUID and params[4] == "DELL" and params[5] == 90 and params[6] == 5
    assert conn.closed


def test_loader_without_dsn_or_disabled_returns_empty(monkeypatch):
    monkeypatch.delenv("M2_DSN", raising=False)
    monkeypatch.setenv(ome.OUTCOME_LOADER_ENV, "1")
    assert ome.load_prior_options_facts(GUID, "DELL", limit=3, lookback_days=30) == []
    monkeypatch.setenv(ome.OUTCOME_LOADER_ENV, "0")
    monkeypatch.setenv("M2_DSN", "postgresql://u:p@127.0.0.1:55432/x")
    assert ome.load_prior_options_facts(GUID, "DELL", limit=3, lookback_days=30) == []


def test_review_dry_run_reports_prior_count(monkeypatch):
    monkeypatch.delenv("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS", raising=False)
    r = ocr.review(P, mode="dry", memory={"memory_reads": True, "loader": lambda *a, **k: [{"kind": "x"}]})
    assert r["status"] == "DRY_RUN" and r["prior_decisions_count"] == 1


def test_config_turns_memory_reads_on():
    import yaml

    from scripts.lib.options_thesis_lifecycle import memory_settings, settings

    intent = yaml.safe_load((ROOT / "assets" / "portfolio_intent.yaml").read_text())
    s = settings(intent["options_desk_settings"])
    m = memory_settings(s)
    assert m["memory_reads"] is True and m["limit"] > 0 and m["lookback_days"] > 0
    assert memory_settings(settings({}))["memory_reads"] is False  # default stays off


# ── end to end on the isolated test database, as the production writer role ──

from tests.test_memory_agent_least_privilege_20260924 import _agent_integrator, agent_role  # noqa: E402,F401


def test_projects_and_reads_back_as_the_production_writer_role(agent_role, tmp_path):  # noqa: F811
    from scripts import options_memory_projector as cli

    tenant = f"opt-{uuid.uuid4().hex[:6]}"
    _st, pl = _plan(tmp_path)
    integ = _agent_integrator(tenant)
    try:
        res = cli.apply_plan(pl, integrator=integ, state_path=tmp_path / "s.json", state={})
        assert not res["errors"], res
        assert res["written"] == len(pl["envelopes"]) and res["provenance_edges"] == 1
        again = cli.apply_plan(pl, integrator=integ, state_path=tmp_path / "s.json", state={})
        assert again["written"] == 0 and again["skipped_existing"] == len(pl["envelopes"])
        conn = integ.connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), count(DISTINCT identity_guid), min(source_type), max(source_type) "
                "FROM memory_r10_m2.memory_fact_version WHERE tenant_id=%s AND upper_inf(tx_period)",
                (tenant,),
            )
            n, idents, st_min, st_max = cur.fetchone()
            assert n == len(pl["envelopes"]) and idents == n
            assert st_min == st_max == "options_thesis_store"
            cur.execute(
                "SELECT count(*) FROM memory_r10_m2.provenance_edge WHERE tenant_id=%s AND relation='SUPERSEDES'",
                (tenant,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        integ.close()

    from scripts.lib.memory_m2_v2 import connect as m2_connect

    rows = ome.load_prior_options_facts(
        GUID, "DELL", limit=10, lookback_days=36500, connect=m2_connect, tenant_id=tenant
    )
    kinds = sorted(r["kind"] for r in rows)
    assert kinds == [
        "options_cio_decision",
        "options_cio_decision",
        "options_followup",
        "options_followup",
        "options_thesis",
    ]
    assert rows and all(r["same_strategy"] for r in rows)


def test_escalation_is_projected_as_a_followup_fact():
    """2026-09-26: web-backed answers still weak -> ChatGPT/Grok/DeepSeek; memory keeps it."""
    obj = proj._followup_object({"event_type": "OPTIONS_THESIS_ESCALATED", "reason": "only 0 of 5 fully answered",
                                 "lane": "grok", "status": "sent", "external_research_id": 7,
                                 "recommendation": "Next earnings 2026-11-24.", "confidence": "MEDIUM"})
    assert obj["stage"] == "EXTERNAL_RESEARCH" and obj["lane"] == "grok" and "2026-11-24" in obj["findings"]
    assert proj.EVENT_PREDICATES["OPTIONS_THESIS_ESCALATED"] == "options_followup"
    assert "escalated to grok" in proj._claim("options_followup", "DELL", obj)
    assert not proj.forbidden_keys_deep(obj)


def test_reopen_is_projected_as_an_outcome():
    obj = proj._outcome_object({"event_type": "OPTIONS_THESIS_REOPENED", "actor": "operator", "reason": "web live"})
    assert obj["outcome"] == "REOPENED" and obj["actor"] == "operator"
    assert proj.EVENT_PREDICATES["OPTIONS_THESIS_REOPENED"] == "options_thesis_outcome"
    assert not proj.forbidden_keys_deep(obj)

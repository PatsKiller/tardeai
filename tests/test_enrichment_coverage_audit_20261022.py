"""Enrichment-coverage audit rescope (2026-10-22, operator-approved: "Yes, I agree with your recommendations.").

Before: the daily alert audited every ``in_directive_watch`` row (2,310 symbols, 2,201 with gaps), listed the first
12 alphabetically with no total, fired P2 every weekday with no dedupe, blamed "the fetcher", and dumped the full
list into the log. These tests pin the fix:

* scope = curated Watch membership (cio_prospect store when granted; interim active + held + operator ticker
  directives) — never the directive flag;
* expectations match the funded policy (news for held/proposed, llm for T0/T1, no-articles-anywhere is not a gap);
* message = counts first, top 10 by priority, truthful cause lines from lane receipts;
* P3 digest, sent only when the count rises or a new gap appears;
* the log carries a summary, the full list goes to a capped manifest.

Hermetic: fake cursors, tmp state root, no DB, no send.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import enrichment_coverage as ec  # noqa: E402

SRC = (ROOT / "scripts" / "audit_enrichment_coverage.py").read_text()


# ── scope: never the directive flag ─────────────────────────────────────────────────────────────────────────────
def test_audit_no_longer_reads_the_directive_flag_or_watch_universe():
    """FAILS on the old script: it called watch_universe.directive_symbols() (in_directive_watch=true)."""
    code = SRC.split('"""', 2)[2]  # past the module docstring, which explains the old scope
    assert "directive_symbols" not in code
    assert "in_directive_watch" not in code
    assert "import watch_universe" not in code


def test_audit_reads_held_through_the_one_held_reader_not_holdings_json():
    assert "membership_held" in SRC
    assert "holdings.json" not in SRC
    allow = (ROOT / "tests" / "fixtures" / "holdings_json_direct_readers_allowlist_20261005.txt").read_text()
    assert "scripts/audit_enrichment_coverage.py" not in allow.splitlines()


class _ScriptedCur:
    """Answers each SELECT by a keyword in its SQL; records every statement."""

    def __init__(self, answers):
        self.answers = answers
        self.sql = []
        self._rows = []

    def execute(self, q, params=None):
        self.sql.append((" ".join(q.split()), params))
        self._rows = []
        for key, rows in self.answers.items():
            if key in " ".join(q.split()):
                self._rows = [(r,) for r in rows]
                break

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


@pytest.fixture
def aec(monkeypatch):
    return importlib.import_module("audit_enrichment_coverage")


def test_interim_membership_is_active_plus_held_plus_operator_ticker_directives(aec, monkeypatch):
    cur = _ScriptedCur({
        "WHERE status = 'active' AND symbol IS NOT NULL": ["AAA", "BBB", "not-a-ticker"],
        "FROM watch_directives": ["OPD"],
        "FROM paper_trade_proposals": ["BBB"],
        "hermes_rank": ["AAA"],
    })
    monkeypatch.setitem(sys.modules, "lib.data_broker.cio_prospect", None)  # projection absent -> interim
    import lib.data_broker.watch_domains as wd
    monkeypatch.setattr(wd, "membership_held", lambda surface=None: ({"HLD"}, "holdings_accounts.holdings_json"))
    members, info = aec.resolve_members(cur)
    assert members == {"AAA": {"active", "high_rank"}, "BBB": {"active", "proposed"},
                       "HLD": {"held"}, "OPD": {"operator_directive"}}
    assert info["source"] == "interim" and info["operator_directives"] == 1
    assert "cio_prospect" in info["preferred_status"]
    # the operator-directive read is scoped to operator-created, active ticker directives
    wd_sql = [(q, p) for q, p in cur.sql if "FROM watch_directives" in q]
    assert wd_sql and "created_by = ANY" in wd_sql[0][0] and wd_sql[0][1] == (["operator", "operator_audit"],)
    assert not any("in_directive_watch" in q for q, _ in cur.sql)


def test_cio_prospect_store_is_preferred_when_it_answers_from_the_store(aec, monkeypatch):
    fake = types.SimpleNamespace(get_prospects=lambda **k: {
        "ok": True, "source": {"kind": "store"},
        "prospects": [{"symbol": "NVDA", "stage": "held"}, {"symbol": "PLTR", "stage": "watching"},
                      {"symbol": "OLD", "stage": "exit"}]})
    import lib.data_broker as pkg
    monkeypatch.setitem(sys.modules, "lib.data_broker.cio_prospect", fake)
    monkeypatch.setattr(pkg, "cio_prospect", fake, raising=False)
    cur = _ScriptedCur({})
    members, info = aec.resolve_members(cur)
    assert members == {"NVDA": {"held"}, "PLTR": {"active"}}
    assert info["source"] == "cio_prospect"


def test_cio_prospect_shadow_is_not_authoritative_falls_back_to_interim(aec, monkeypatch):
    fake = types.SimpleNamespace(get_prospects=lambda **k: {"ok": True, "source": {"kind": "shadow"},
                                                             "prospects": [{"symbol": "ZZZ", "stage": "held"}]})
    import lib.data_broker as pkg
    import lib.data_broker.watch_domains as wd
    monkeypatch.setitem(sys.modules, "lib.data_broker.cio_prospect", fake)
    monkeypatch.setattr(pkg, "cio_prospect", fake, raising=False)
    monkeypatch.setattr(wd, "membership_held", lambda surface=None: (set(), "unavailable"))
    members, info = aec.resolve_members(_ScriptedCur({}))
    assert "ZZZ" not in members and info["source"] == "interim"
    assert "shadow" in info["preferred_status"]


# ── expectations match the funded policy ───────────────────────────────────────────────────────────────────────
def test_expected_surfaces_follow_the_budget_tiers():
    assert ec.expected_surfaces({"active"}) == ["technicals", "analyst"]
    assert ec.expected_surfaces({"operator_directive"}) == ["technicals", "analyst"]  # T2: no cloud LLM, no news bar
    assert ec.expected_surfaces({"high_rank"}) == ["technicals", "analyst", "llm_curation"]
    assert ec.expected_surfaces({"proposed"}) == ["technicals", "analyst", "news_7d", "llm_curation"]
    assert ec.expected_surfaces({"held"}) == ["technicals", "analyst", "news_7d", "llm_curation",
                                              "protection_advisory"]


def test_budget_policy_still_funds_cloud_llm_for_t0_t1_only():
    """The expectation is only honest while the policy says so; this fails if the policy moves."""
    import yaml
    pol = yaml.safe_load((ROOT / "config" / "hermes_research_budget.yaml").read_text())
    assert pol["external_cloud_tiers"] == ["T0", "T1"]
    m = pol["trigger_source_tier"]
    assert m["holdings"] == "T0" and m["open_proposal"] == "T0" and m["high_rank_watchlist"] == "T1"
    assert m["active_directive"] == "T2"


def test_no_articles_from_any_source_is_not_a_gap():
    members = {"HLD": {"held"}, "NEW": {"held"}}
    ev = {"tech_ok": {"HLD", "NEW"}, "analyst_ok": {"HLD", "NEW"}, "llm_ok": {"HLD", "NEW"},
          "prot_ok": {"HLD", "NEW"}, "news_7d_ok": set(), "news_ever": {"HLD"}}
    r = ec.evaluate(members, ev)
    assert [g["symbol"] for g in r["gaps"]] == ["HLD"] and r["gaps"][0]["missing"] == ["news_7d"]
    assert r["no_articles_any_source"] == ["NEW"]


def test_directive_only_names_are_not_held_to_news_or_llm():
    r = ec.evaluate({"OPD": {"operator_directive"}}, {"tech_ok": {"OPD"}, "analyst_ok": {"OPD"}})
    assert r["gaps"] == []


def test_priority_order_held_then_proposed_then_directive_then_rank_then_active():
    members = {"A1": {"active"}, "D1": {"operator_directive"}, "H1": {"held"}, "P1": {"proposed"},
               "R1": {"high_rank"}}
    r = ec.evaluate(members, {})
    assert [g["symbol"] for g in r["gaps"]] == ["H1", "P1", "D1", "R1", "A1"]


# ── message: counts first, top 10, truthful causes ─────────────────────────────────────────────────────────────
def _big_result(n=25):
    members = {f"S{i:02d}": {"active"} for i in range(n)}
    members["HELD"] = {"held"}
    return members, ec.evaluate(members, {"tech_ok": set(members)})


def test_message_leads_with_counts_and_lists_only_the_top_10():
    members, r = _big_result()
    d = ec.alert_decision(None, r["gaps"])
    msg = ec.message(members=members, result=r, decision=d, causes=["x"], membership_source="interim",
                     manifest_rel="data/runtime/m.json")
    lines = msg.splitlines()
    assert lines[1].startswith(f"{len(r['gaps'])} of {len(members)} members have gaps")
    bullets = [ln for ln in lines if ln.startswith("• ") and "[" in ln]
    assert len(bullets) == 10 and bullets[0].startswith("• HELD [held]")
    assert "data/runtime/m.json" in msg
    assert "fetcher skipped" not in msg  # the old false "Fix" line is gone


def test_cause_line_reports_the_hermes_top20_failure_from_its_receipt():
    rec = {"status": "failed", "error": "OperationalError", "finished_at": "2026-10-22T20:08:45+00:00",
           "ok_at": "2026-10-22T18:07:27+00:00"}
    lines = ec.cause_lines({"llm_curation": 6, "news_7d": 3}, {"hermes_top20_external_intel": rec},
                           {"news_cap": "60"})
    assert lines[0].startswith("news_7d (3): ") and "NEWS_INGEST_MAX=60" in lines[0]
    assert "hermes_top20_external_intel last run FAILED 2026-10-22 20:08 UTC (OperationalError)" in lines[1]
    assert "last ok 2026-10-22 18:07 UTC" in lines[1] and "T0/T1 only" in lines[1]


def test_cause_line_says_when_there_is_no_receipt():
    lines = ec.cause_lines({"llm_curation": 1}, {}, {})
    assert "hermes_top20_external_intel: no lane receipt found" in lines[0]


# ── dedupe: count worsens or the set changes ───────────────────────────────────────────────────────────────────
def _gaps(*pairs):
    return [{"symbol": s, "tier": "active", "missing": list(m)} for s, m in pairs]


def test_alert_decision_dedupes_unchanged_and_improved_sets():
    g1 = _gaps(("AAA", ["analyst"]), ("BBB", ["technicals"]))
    assert ec.alert_decision(None, g1)["reason"] == "first_run"
    st = ec.new_state(g1, {"reason": "first_run"}, alerted=True)
    assert ec.alert_decision(st, g1) == {**ec.alert_decision(st, g1), "send": False, "reason": "unchanged"}
    improved = ec.alert_decision(st, _gaps(("AAA", ["analyst"])))
    assert improved["send"] is False and improved["reason"] == "improved"
    worse = ec.alert_decision(st, g1 + _gaps(("CCC", ["analyst"])))
    assert worse["send"] is True and worse["reason"] == "worsened"
    swapped = ec.alert_decision(st, _gaps(("AAA", ["analyst"]), ("DDD", ["technicals"])))
    assert swapped["send"] is True and swapped["reason"] == "set_changed" and swapped["new_entries"] == 1
    assert ec.alert_decision(st, [])["send"] is False


# ── P3, digest; log summary; capped manifest ───────────────────────────────────────────────────────────────────
def test_alert_is_a_p3_intent():
    body = SRC[SRC.index("def _alert("):]
    assert 'priority="P3"' in body and 'priority="P2"' not in SRC


def test_manifest_is_capped():
    members = {f"S{i:04d}": {"active"} for i in range(ec.MANIFEST_CAP + 50)}
    r = ec.evaluate(members, {})
    m = ec.manifest(members=members, result=r, decision=ec.alert_decision(None, r["gaps"]), causes=[],
                    membership_source="interim")
    assert len(m["gaps"]) == ec.MANIFEST_CAP and m["truncated"] is True
    assert m["symbols_with_gaps"] == ec.MANIFEST_CAP + 50


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    return root


def test_live_run_logs_a_summary_and_writes_a_capped_manifest(state, aec, monkeypatch, capsys):
    members = {f"S{i:04d}": {"active"} for i in range(800)}
    conn = types.SimpleNamespace(cursor=lambda: _ScriptedCur({}))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    monkeypatch.setattr(aec, "resolve_members", lambda c: (members, {"source": "interim", "label": "t"}))
    monkeypatch.setattr(aec, "gather_evidence", lambda c, m: ({}, {}))
    monkeypatch.setattr(aec, "lane_receipts", lambda: {})
    sent = []
    monkeypatch.setattr(aec, "_alert", lambda msg, n: sent.append(msg) or True)
    assert aec.main(["--alert"]) == 0
    out = capsys.readouterr().out
    assert len(out) < 20_000, "the log gets a summary, never the full list"
    assert "S0799" not in out
    man = json.loads((state / "data" / "runtime" / "audit-enrichment-coverage_manifest.json").read_text())
    assert man["symbols_with_gaps"] == 800 and len(man["gaps"]) == ec.MANIFEST_CAP
    assert len(sent) == 1 and len(sent[0]) < 4000
    rec = json.loads((state / "data" / "runtime" / "audit-enrichment-coverage_last.json").read_text())
    assert rec["produced_count"] == 800 and rec["summary"]["alert_sent"] is True


# ── n8n lane wiring: shadow, v2 receipt, contract, inventory ───────────────────────────────────────────────────
def test_lane_is_registered_at_shadow_and_opted_into_v2_output():
    from tests.support import lane_produced_count as H
    H.assert_opted_in("audit-enrichment-coverage")
    allow = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
    e = allow["audit-enrichment-coverage"]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None  # shadow: the cron line still does the work
    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    row = reg["audit-enrichment-coverage"]
    assert row["scheduler"]["stage"] == "shadow" and row["dispatch"]["mode"] == "dry_run"


def test_contract_names_the_receipt_and_the_new_unit():
    raw = (ROOT / "config" / "n8n_health_contracts.json").read_text()
    assert "data/runtime/audit-enrichment-coverage_last.json produced_count" in raw
    c = next(x for x in json.loads(raw)["contracts"] if x["id"] == "audit-enrichment-coverage")
    assert c["expected_output"]["unit"] == "curated Watch members audited"
    assert "P3" in json.dumps(c["purpose"]) or "P3" in json.dumps(c["evidence"])


def test_cron_inventory_records_the_rescope_and_the_retirement_one_liner():
    inv = (ROOT / "docs" / "implementation" / "n8n-maturity" / "cron-inventory" / "README.md").read_text()
    assert "audit-enrichment-coverage" in inv and "enrich_coverage.lock" in inv
    assert "# RETIRED" in inv

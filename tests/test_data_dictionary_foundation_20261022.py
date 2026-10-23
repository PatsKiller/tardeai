"""Data foundation (2026-10-22): the data dictionary inside the §7A registry, and its CI enforcement.

Operator direction 2026-10-22 (verbatim): "The CIO agent is supposed to tie all of this together, and it should all
be in persistent memory. One data store with everything; use the CIO agent and n8n to accomplish this." and "...
we should also have a data dictionary that shows one source of data."

What this pins:
  * the dictionary lives in config/data_source_authority.json (no parallel registry): proposed rows in
    proposed_domains[] with status "proposed" and no approval, so UNAPPROVED_SOURCE and the §7A table are untouched;
  * every registry gap the 2026-10-22 inventory measured has exactly one proposed row, each with one store, one
    writer (or a declared UNCONSOLIDATED target), a refresh lane, a freshness SLA, readers and its copies;
  * n8n never-list families stay on the host; the CIO prospect is keyed by security_guid (subject_guid is an alias)
    and extends InstrumentRecord@v1 without any behaviour field;
  * CI: a second writer or a page/API reading a derived/retiring copy WARNS for a proposed row and FAILS once the
    row is granted (domains[].dictionary ceilings); a malformed proposal always fails;
  * docs/architecture/DATA_DICTIONARY.md is rendered from the registry and cannot drift.

Hermetic: the enforcement tests build a tmp repo; the live-repo tests only read repository files. TRADE_AI_CI=1.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_data_source_authority as gate  # noqa: E402
import render_data_dictionary as rdd  # noqa: E402
from lib import data_dictionary as DD  # noqa: E402

AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text(encoding="utf-8"))
ROWS = {r["domain"]: r for r in AUTH["proposed_domains"]}
GRANTED = {d["domain"]: d for d in AUTH["domains"] if d.get("dictionary")}
# cio_prospect left this tuple when approval E (operator 2026-10-22) was recorded 2026-10-23 (T-20261023-9c7a5c).
GAPS = ("broker_stops", "watchlist_membership", "scanner_results", "catalyst_events", "fused_signals",
        "cio_decisions", "cio_theses", "options_ideas", "paper_proposals", "paper_trades", "alert_events",
        "comms_intents", "positions_store", "security_identity", "transactions")
GRANT = {"approved_by": "operator", "approved_on": "2026-10-23", "reference": "test grant", "scope": "test"}


# ------------------------------------------------------------------------------------------- the registry


def test_one_registry_not_a_parallel_one():
    assert AUTH["schema"] == "DataSourceAuthority@v2"
    assert AUTH["data_dictionary"]["schema"] == DD.SCHEMA
    assert not list((ROOT / "config").glob("data_dictionary*.json")), "the dictionary lives in the §7A registry"


def test_every_measured_gap_has_exactly_one_proposed_row():
    assert set(GAPS) <= set(ROWS), sorted(set(GAPS) - set(ROWS))
    assert len(ROWS) == len(AUTH["proposed_domains"])


@pytest.mark.parametrize("name", GAPS)
def test_proposed_row_is_complete_and_ungranted(name):
    r = ROWS[name]
    assert r["status"] == "proposed" and r["approval"] is None
    for k in ("store", "cadence", "freshness_sla", "refresh_lane", "readers", "facts", "proposal"):
        assert r.get(k), f"{name}: {k}"
    assert r.get("writer") or (r.get("writer_status") == "UNCONSOLIDATED" and r.get("writer_target"))
    assert r["proposal"]["decision"].strip()
    assert DD.store_key(r["store"])


def test_proposed_rows_never_reach_domains_or_the_section_7a_table():
    names = {d["domain"] for d in AUTH["domains"]}
    new = set(ROWS) - {r for r in ROWS if ROWS[r].get("extends_approved")}
    assert not (new & names)
    assert gate.check_approvals(AUTH) == [], "proposed rows must not trip UNAPPROVED_SOURCE"
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    table = agents.split("<!-- SOURCE_OF_TRUTH_TABLE_START -->", 1)[1].split("<!-- SOURCE_OF_TRUTH_TABLE_END -->")[0]
    for n in new:
        assert f"**{n}**" not in table, n


def test_the_live_dictionary_validates():
    assert DD.validate(AUTH, ROOT) == []


@pytest.mark.parametrize("name", ["broker_stops", "options_ideas", "paper_proposals", "paper_trades",
                                  "positions_store", "transactions", "comms_intents"])
def test_never_list_families_stay_on_the_host(name):
    lane = ROWS[name]["refresh_lane"]
    assert lane["never_list"] is True and lane["runner"] == "host", name


def test_broker_execution_tables_are_excluded_not_managed():
    roles = {DD.store_key(c["store"]): c["role"] for c in ROWS["broker_stops"]["derived_copies"]}
    assert roles["table:broker_order_intents"] == "excluded" and roles["table:trade_approvals"] == "excluded"
    for rel in DD.BROKER_EXCLUDE_FILES:
        assert not DD._excluded("scripts/x.py") and DD._excluded(rel)


def test_positions_one_authority_and_holdings_json_becomes_an_export():
    r = ROWS["positions_store"]
    assert r["extends_approved"] is True and r["supersedes"] == ["holdings_accounts"]
    assert r["store"] == {"table": "positions_current"} and r["writer"] == "scripts/positions_sync.py"
    holdings = next(c for c in r["derived_copies"] if c["store"].get("file") == "portfolios/state/holdings.json")
    assert holdings["role"] == "derived" and "2026-10-22" in holdings["how"]


def test_cio_prospect_is_one_store_one_writer_superseding_the_opportunity_file():
    assert "cio_prospect" not in ROWS
    r = GRANTED["cio_prospect"]
    assert r["approval"]["approved_by"] == "operator" and "6bac8924" in r["approval"]["reference"]
    assert r["dictionary"]["writer_ceiling"] == 1
    assert r["store"] == {"table": "cio_prospect"}
    assert r["writer"] == "scripts/lib/cio_instrument_record.py" and (ROOT / r["writer"]).exists()
    assert r["supersedes"] == ["opportunity_assessment"]
    assert set(r["readers"]) >= {"Home", "Watch", "Trade AI", "Options", "Open Trades", "Telegram", "Proposals",
                                 "Re-entry"}
    copies = {DD.store_key(c["store"]) for c in r["derived_copies"]}
    for c in ("file:data/cio/cio_opportunity_projection.json", "file:cio/cio_instrument_records.jsonl",
              "file:cio/ticker_research_state.jsonl", "file:cio/security_research_spine.jsonl",
              "table:cio_entry_states", "table:decision_packets"):
        assert c in copies, c


def test_three_declared_stores_are_marked_missing():
    marked = {d["domain"]: d["store_presence"]["status"] for d in AUTH["domains"] if d.get("store_presence")}
    for name in ("yfinance_info_snapshot", "earnings_calendar", "news_sentiment"):
        assert marked.get(name) == "MISSING", name


# --------------------------------------------------------------------------------------------- field level


def test_prospect_is_keyed_by_security_guid_and_subject_guid_is_an_alias():
    key = AUTH["data_dictionary"]["canonical_key"]
    assert key["per_security"] == "security_guid" and key["per_company"] == "issuer_guid"
    assert "subject_guid" in key["aliases"] and "never stored as a second key" in key["aliases"]["subject_guid"]
    rec = AUTH["data_dictionary"]["records"]["CIOProspect"]
    assert rec["domain"] == "cio_prospect" and "InstrumentRecord@v1" in rec["extends"]
    fields = {f["field"]: f for f in rec["fields"]}
    for name in ("security_guid", "issuer_guid", "stage", "conviction", "conviction_components", "stance",
                 "catalyst_grade", "next_trigger", "whats_missing", "next_action", "evidence_at", "expires_at",
                 "conflicts"):
        assert name in fields, name
    assert fields["security_guid"].get("required") is True
    assert "watching" in fields["stage"]["meaning"] and "re_entry" in fields["stage"]["meaning"]
    assert "never silently resolved" in fields["conflicts"]["meaning"]
    assert "Gate 2" in fields["catalyst_grade"]["meaning"]


def test_no_prospect_field_is_a_behaviour_field():
    from lib.cio_instrument_record import BEHAVIOR_FIELDS
    names = set()
    for f in AUTH["data_dictionary"]["records"]["CIOProspect"]["fields"]:
        names.update(p.strip() for p in f["field"].replace("[]", "").split("/"))
    assert not (names & set(BEHAVIOR_FIELDS)), names & set(BEHAVIOR_FIELDS)


def test_every_key_fact_has_one_domain():
    facts = {f["fact"]: f for f in AUTH["data_dictionary"]["facts"]}
    for fact, domain in (("shares", "positions_store"), ("cash", "positions_store"), ("cost basis", "positions_store"),
                         ("mark", "quote_price"), ("stop", "broker_stops"), ("catalyst", "catalyst_events"),
                         ("fused score", "fused_signals"), ("unified edge", "cio_prospect"),
                         ("decision", "cio_decisions"), ("options idea", "options_ideas"), ("alert", "alert_events")):
        assert facts[fact]["domain"] == domain, fact
    assert len(facts) == len(AUTH["data_dictionary"]["facts"]), "one entry per fact"


# --------------------------------------------------------------------------------------------- enforcement


def _tmp_repo(tmp_path: Path, *, writers: int = 1, surface_reads: int = 0) -> tuple[Path, dict]:
    """A tiny repo: one proposed row over table ``t_store`` with a derived copy file ``copy.json``."""
    root = tmp_path
    (root / "scripts").mkdir()
    (root / "scripts" / "w0.py").write_text("cur.execute('INSERT INTO t_store VALUES (1)')\n")
    for i in range(1, writers):
        (root / "scripts" / f"w{i}.py").write_text("cur.execute('UPDATE t_store SET x=1')\n")
    api = "x = 1\n" + "".join("p = open('copy.json').read()\n" for _ in range(surface_reads))
    (root / "scripts" / "api_v2.py").write_text(api)
    auth = {
        "schema": "DataSourceAuthority@v2", "providers": {}, "domains": [],
        "data_dictionary": {"schema": DD.SCHEMA, "surface_files": ["scripts/api_v2.py"], "facts": [], "records": {}},
        "proposed_domains": [{
            "domain": "thing", "status": "proposed", "entity": "Thing", "title": "Thing", "class": "derived",
            "facts": ["thing"], "store": {"table": "t_store"}, "writer": "scripts/w0.py", "cadence": "daily",
            "stale_after_hours": 24, "freshness_sla": "24 h",
            "refresh_lane": {"runner": "n8n", "lane": "thing-lane", "never_list": False, "note": "test"},
            "projection": None, "readers": ["Home"], "no_coverage": "say_so", "approval": None,
            "proposal": {"proposed_by": "test", "proposed_on": "2026-10-22", "reference": "test",
                         "decision": "grant thing"},
            "derived_copies": [{"store": {"file": "copy.json"}, "role": "derived", "how": "export"}],
        }],
    }
    return root, auth


def test_proposed_row_with_a_second_writer_warns_and_never_fails(tmp_path):
    root, auth = _tmp_repo(tmp_path, writers=2, surface_reads=1)
    findings, warnings, _ = DD.evaluate(auth, root)
    assert findings == []
    assert {w["check"] for w in warnings} == {"DICTIONARY_SECOND_WRITER", "NON_AUTHORITATIVE_READ"}


def test_granted_row_fails_on_a_second_writer_added_after_the_grant(tmp_path):
    root, auth = _tmp_repo(tmp_path, writers=1)
    granted = DD.promote(auth, "thing", GRANT, DD.measure(auth, root))
    assert DD.evaluate(granted, root)[0] == [], "clean at grant time"
    (root / "scripts" / "rogue.py").write_text("cur.execute('INSERT INTO t_store VALUES (2)')\n")
    findings = DD.evaluate(granted, root)[0]
    assert [f["check"] for f in findings] == ["DICTIONARY_SECOND_WRITER"]
    assert "scripts/rogue.py" in findings[0]["files"]
    # the gate itself reports it (the same evaluator, wired into check_data_source_authority.main)
    assert [f["check"] for f in gate.check_dictionary(granted, root)[0]] == ["DICTIONARY_SECOND_WRITER"]


def test_granted_row_fails_when_a_page_api_reads_a_copy_above_its_ceiling(tmp_path):
    root, auth = _tmp_repo(tmp_path, writers=1, surface_reads=0)
    granted = DD.promote(auth, "thing", GRANT, DD.measure(auth, root))
    assert DD.evaluate(granted, root)[0] == []
    (root / "scripts" / "api_v2.py").write_text("p = open('copy.json').read()\n")
    findings = DD.evaluate(granted, root)[0]
    assert [f["check"] for f in findings] == ["NON_AUTHORITATIVE_READ"]
    assert findings[0]["copy"] == "file:copy.json" and findings[0]["files"] == ["scripts/api_v2.py"]


def test_granted_unconsolidated_row_keeps_its_measured_ceiling_and_may_only_fall(tmp_path):
    root, auth = _tmp_repo(tmp_path, writers=3, surface_reads=1)
    granted = DD.promote(auth, "thing", GRANT, DD.measure(auth, root))
    block = granted["domains"][0]["dictionary"]
    assert block["writer_ceiling"] == 3 and block["surface_read_ceilings"] == {"file:copy.json": 1}
    assert DD.evaluate(granted, root)[0] == [], "at the ceiling: green"
    (root / "scripts" / "w3.py").write_text("cur.execute('UPDATE t_store SET y=2')\n")
    assert [f["check"] for f in DD.evaluate(granted, root)[0]] == ["DICTIONARY_SECOND_WRITER"]


def test_promotion_needs_the_full_grant_and_records_it(tmp_path):
    root, auth = _tmp_repo(tmp_path)
    with pytest.raises(DD.DictionaryError):
        DD.promote(auth, "thing", {"approved_by": "operator"})
    granted = DD.promote(auth, "thing", GRANT, DD.measure(auth, root))
    assert granted["proposed_domains"] == [] and auth["proposed_domains"], "promote returns a new registry"
    row = granted["domains"][0]
    assert row["approval"] == GRANT and "status" not in row and row["dictionary"]["schema"] == DD.SCHEMA
    assert gate.check_approvals(granted) == []


def test_promoting_the_live_positions_row_extends_and_marks_holdings_superseded():
    granted = DD.promote(AUTH, "positions_store", GRANT, {})
    doms = {d["domain"]: d for d in granted["domains"]}
    assert doms["positions_store"]["approval"] == GRANT and "dictionary" in doms["positions_store"]
    assert doms["holdings_accounts"]["dictionary_superseded_by"] == "positions_store"
    assert len(granted["domains"]) == len(AUTH["domains"]), "superseded domains are marked, never removed"


@pytest.mark.parametrize("mutate,why", [
    (lambda r: r.update(status="approved"), "status must be"),
    (lambda r: r.update(approval=GRANT), "carries no approval"),
    (lambda r: r.pop("proposal"), "missing proposal"),
    (lambda r: r.update(writer=None), "no single writer"),
    (lambda r: r["refresh_lane"].update(never_list=True), "never-list"),
    (lambda r: r["derived_copies"].append({"store": {"table": "old"}, "role": "retiring", "how": "drop it"}),
     "archive + tripwire"),
    (lambda r: r["derived_copies"].append({"store": {"table": "t_store"}, "role": "derived", "how": "x"}),
     "both authoritative and a copy"),
])
def test_a_malformed_proposal_always_fails(tmp_path, mutate, why):
    root, auth = _tmp_repo(tmp_path)
    mutate(auth["proposed_domains"][0])
    findings = DD.evaluate(auth, root)[0]
    assert any(f["check"] == "DICTIONARY_INVALID" and why in f["why"] for f in findings), findings


def test_claiming_an_approved_store_without_superseding_it_fails(tmp_path):
    root, auth = _tmp_repo(tmp_path)
    auth["domains"].append({"domain": "old_owner", "store": {"file": "copy.json"}})
    findings = DD.validate(auth, root)
    assert any("supersedes" in f["why"] for f in findings), findings
    auth["proposed_domains"][0]["supersedes"] = ["old_owner"]
    assert DD.validate(auth, root) == []


def test_the_live_gate_is_green_with_proposed_rows_warning_only():
    findings, warnings, measured = gate.check_dictionary(AUTH)
    assert findings == [], findings
    assert warnings and all(w["state"].startswith("proposed") for w in warnings)
    assert measured["paper_proposals"]["writer_files"], "the scan sees the multi-writer hot spot"


# ------------------------------------------------------------------------------------------------- the doc


def test_rendered_dictionary_is_current():
    assert rdd.main(["--check"]) == 0, "run scripts/render_data_dictionary.py"


def test_rendered_dictionary_names_every_row_and_fact():
    text = rdd.render(AUTH)
    assert text == rdd.render(copy.deepcopy(AUTH)), "deterministic"
    for name in ROWS:
        assert f"`{name}`" in text, name
    for f in AUTH["data_dictionary"]["facts"]:
        assert f"**{f['fact']}**" in text, f["fact"]
    assert "Status:" in text and "as_of:" in text and "Measured at:" in text


def test_local_acceptance_runs_the_drift_check():
    sh = (ROOT / "scripts" / "ai_local_acceptance.sh").read_text(encoding="utf-8")
    assert "scripts/render_data_dictionary.py --check" in sh

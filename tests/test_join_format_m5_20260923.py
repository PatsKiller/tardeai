"""M5 step 5 (2026-09-23): Hermes join keyed by subject_guid + Postgres opr_ leg,
LEGEND inside finalize, numbered [n] citations that map to Sources entries.

Audit findings this pins:
  * the join matched on the ticker string only, so a row for another security
    that shares a ticker could answer for this one, and GUID-stamped rows gained
    nothing from their GUID;
  * the desk's opr_ requests filed in Postgres ``data_gap_registry`` were never
    read -- only the JSONL ledger;
  * the pill key (LEGEND) was added on some desk paths only;
  * no reply ever rendered an inline citation, although Hermes answers carry
    ``citations[]``.

Hermetic: no psycopg2, no live DB, no live registry (conftest turns both off).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib import hermes_subject_join as hj
from scripts.lib import reply_provenance as rp

GUID_S = "84601d7d-ae35-4d6c-9d0e-000000000001"
GUID_OTHER = "0bcf1ac9-0000-4000-8000-000000000002"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture()
def cio_dir(tmp_path, monkeypatch):
    d = tmp_path / "cio"
    d.mkdir()
    # the projection leg reads the live store unless redirected; keep it empty
    monkeypatch.setattr("scripts.lib.cio_hermes_research._load_projection", lambda: {}, raising=False)
    return d


# ── join keyed by subject_guid ───────────────────────────────────────────────


def test_guid_row_matches_even_when_its_ticker_string_differs(cio_dir):
    _write(
        cio_dir / "hermes_research_results.jsonl",
        [
            {
                "symbol": "SENTINELONE",
                "subject_guid": GUID_S,
                "result_id": "rr_guid1",
                "research_id": "res_guid1",
                "status": "completed",
                "summary": "real work",
                "answers": [{"summary": "x"}],
            },
        ],
    )
    j = hj.join_subject_hermes("S", subject_guid=GUID_S, cio_dir=cio_dir)
    assert j.result_ids == ["rr_guid1"]
    assert j.status == hj.STATUS_DESK_COMPLETED


def test_same_ticker_other_security_does_not_answer_for_this_one(cio_dir):
    _write(
        cio_dir / "hermes_research_results.jsonl",
        [
            {
                "symbol": "S",
                "subject_guid": GUID_OTHER,
                "result_id": "rr_other",
                "research_id": "res_other",
                "status": "completed",
                "summary": "other issuer",
            },
        ],
    )
    j = hj.join_subject_hermes("S", subject_guid=GUID_S, cio_dir=cio_dir)
    assert j.result_ids == [] and j.status == hj.STATUS_NONE


def test_legacy_row_without_guid_still_matches_by_symbol(cio_dir):
    _write(
        cio_dir / "cio_operator_gap_requests.jsonl",
        [
            {"symbol": "S", "pending_id": "opr_legacy01", "research_id": "res_legacy01"},
        ],
    )
    j = hj.join_subject_hermes("S", subject_guid=GUID_S, cio_dir=cio_dir)
    assert "opr_legacy01" in j.pending_ids and "res_legacy01" in j.research_ids


def test_multi_subject_row_with_partial_guids_keeps_the_symbol_match(cio_dir):
    _write(
        cio_dir / "cio_operator_gap_requests.jsonl",
        [
            {"symbols": ["NOC", "S"], "subject_guid": GUID_OTHER, "pending_id": "opr_multi001"},
        ],
    )
    j = hj.join_subject_hermes("S", subject_guid=GUID_S, cio_dir=cio_dir)
    assert "opr_multi001" in j.pending_ids


def test_per_gap_guid_is_honoured(cio_dir):
    _write(
        cio_dir / "cio_operator_gap_requests.jsonl",
        [
            {"pending_id": "opr_gaps0001", "gaps": [{"symbol": "S", "subject_guid": GUID_S}]},
        ],
    )
    j = hj.join_subject_hermes("S", subject_guid=GUID_S, cio_dir=cio_dir)
    assert "opr_gaps0001" in j.pending_ids


def test_guid_is_resolved_from_the_registry_when_caller_passes_only_a_symbol(cio_dir, monkeypatch):
    monkeypatch.setenv("TRADEAI_HERMES_JOIN_RESOLVE_GUID", "1")
    monkeypatch.setattr(
        "scripts.lib.cio_hermes_research._subject_identity", lambda sym: {"subject_guid": GUID_S} if sym == "S" else {}
    )
    assert hj.join_subject_hermes("S", cio_dir=cio_dir).subject_guid == GUID_S


def test_registry_resolution_off_switch(monkeypatch):
    monkeypatch.setenv("TRADEAI_HERMES_JOIN_RESOLVE_GUID", "0")
    assert hj.resolve_subject_guid("S") is None


# ── Postgres opr_ leg ────────────────────────────────────────────────────────


def _gap_db(rows):
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append((sql, params))
        if "data_gap_registry" in sql:
            return rows
        return []

    q.calls = calls
    return q


def test_open_db_gap_request_counts_as_pending_and_is_named(cio_dir):
    db = _gap_db(
        [
            {
                "id": 80,
                "symbol": "S",
                "gap_type": "stale_news",
                "status": "open",
                "gap_detail": "operator desk opr_da07dadd868f: hermes_research research",
                "resolution_data": None,
            },
            {
                "id": 76,
                "symbol": "S",
                "gap_type": "stale_news",
                "status": "abandoned",
                "gap_detail": "operator desk opr_cdffec2f75db: hermes_research research",
                "resolution_data": {"job_id": "gap_s_catalyst_a6a32e"},
            },
        ]
    )
    j = hj.join_subject_hermes("S", cio_dir=cio_dir, db_query=db)
    assert j.pending_ids == ["opr_da07dadd868f"]  # abandoned is not in flight
    assert j.status == hj.STATUS_QUEUED
    assert "data_gap_registry · opr_da07dadd868f (open)" in j.sources
    assert "data_gap_registry · opr_cdffec2f75db (abandoned)" in j.sources
    assert db.calls[0][1][0] == "S"


def test_db_failure_degrades_to_jsonl(cio_dir):
    _write(cio_dir / "cio_operator_gap_requests.jsonl", [{"symbol": "S", "pending_id": "opr_jsonl0001"}])

    def boom(*_a, **_k):
        raise ImportError("No module named 'psycopg2'")

    j = hj.join_subject_hermes("S", cio_dir=cio_dir, db_query=boom, hub_finder=hj.hub_promoted_count_finder(boom))
    assert j.pending_ids == ["opr_jsonl0001"]
    assert j.hub_count is None  # unknown, never a silent 0


def test_hub_finder_counts_promoted_rows_for_one_ticker():
    seen = {}

    def q(sql, params=None, fetch="all"):
        seen["sql"], seen["params"] = sql, params
        return [{"n": 21}]

    assert hj.hub_promoted_count_finder(q)("noc") == 21
    assert "status = 'promoted'" in seen["sql"] and seen["params"] == ("NOC",)


def test_house_db_query_is_off_under_the_test_switch(monkeypatch):
    monkeypatch.setenv("TRADEAI_HERMES_JOIN_DB", "0")
    assert hj.house_db_query() is None


# ── LEGEND inside finalize ───────────────────────────────────────────────────


def test_finalize_opens_every_reply_with_the_legend_once():
    final, prov = rp.finalize_operator_reply("S is analyzed-thin.", rp.ReplyProvenance(kind="t"))
    assert final.split("\n")[0] == rp.LEGEND and prov.legend_present
    again, _ = rp.finalize_operator_reply(final, rp.ReplyProvenance(kind="t"))
    assert again.count(rp.LEGEND.split(" · ", 1)[0]) == 1


def test_finalize_keeps_a_legend_a_path_already_placed_below_its_header():
    body = "📬 *Follow-up* `opr_x` — Hermes research landed\n" + rp.LEGEND + "\nYou asked: …"
    final, _ = rp.finalize_operator_reply(body, rp.ReplyProvenance(kind="t"))
    assert final.count(rp.LEGEND.split(" · ", 1)[0]) == 1
    assert final.split("\n")[0].startswith("📬")


# ── [n] citations ────────────────────────────────────────────────────────────


def test_a_visible_id_is_numbered_and_listed_on_sources():
    prov = rp.ReplyProvenance(
        kind="t",
        stores_read=["hermes_research_results"],
        citations=[
            {"id": "res_c3a661c21740", "label": "hermes research · res_c3a661c21740"},
        ],
    )
    final, prov = rp.finalize_operator_reply("Desk research: res_c3a661c21740 finished thin.", prov)
    assert "res_c3a661c21740 [1] finished thin." in final
    src = next(ln for ln in final.split("\n") if ln.startswith("Sources:"))
    assert "[1] hermes research · res_c3a661c21740" in src
    assert prov.cited == ["[1] hermes research · res_c3a661c21740"]


def test_evidence_the_reply_does_not_show_is_never_cited():
    prov = rp.ReplyProvenance(kind="t", citations=[{"id": "rr_notshown", "label": "hermes_research_results"}])
    final, prov = rp.finalize_operator_reply("Nothing about that id here.", prov)
    assert "[1]" not in final and prov.cited == []


def test_second_finalize_does_not_renumber_or_duplicate():
    cites = [
        {"id": "rr_aaaa", "label": "hermes_research_results · rr_aaaa"},
        {"id": "opr_bbbb", "label": "operator gap request"},
    ]
    once, _ = rp.finalize_operator_reply("rr_aaaa then opr_bbbb.", rp.ReplyProvenance(kind="t", citations=cites))
    twice, prov = rp.finalize_operator_reply(once, rp.ReplyProvenance(kind="t", citations=cites))
    body = twice.split("\n")[1]
    assert body == "rr_aaaa [1] then opr_bbbb [2]."
    src = next(ln for ln in twice.split("\n") if ln.startswith("Sources:"))
    assert src.count("[1]") == 1 and src.count("[2]") == 1
    assert "[2] operator gap request · opr_bbbb" in src
    origin = next(ln for ln in twice.split("\n") if ln.startswith("Origin:"))
    assert "no store read" in origin  # citations are not counted as stores


def test_citation_cap(monkeypatch):
    monkeypatch.setenv("TRADEAI_REPLY_MAX_CITATIONS", "2")
    ids = [f"res_{i:04d}" for i in range(5)]
    final, prov = rp.finalize_operator_reply(
        " ".join(ids), rp.ReplyProvenance(kind="t", citations=[{"id": i, "label": "hermes research"} for i in ids])
    )
    assert len(prov.cited) == 2 and "[3]" not in final


def test_join_citations_feed_finalize():
    j = hj.HermesJoinResult(symbol="S", result_ids=["rr_06fb7ccbc798"], research_ids=["res_c3a661c21740"])
    j.honesty_line = hj.honesty_line_for(hj.STATUS_ANALYZED_THIN, symbol="S", result_id="rr_06fb7ccbc798")
    final, prov = rp.finalize_operator_reply(j.honesty_line, rp.ReplyProvenance(kind="t", citations=j.citations()))
    assert "(rr_06fb7ccbc798 [1])" in final
    assert prov.cited[0] == "[1] hermes_research_results · rr_06fb7ccbc798"


def test_hermes_answer_citations_land_at_the_end_of_the_rendered_answer_line():
    from scripts.lib import cio_operator_desk_loop as dl

    result = {
        "result_id": "rr_06fb7ccbc798",
        "model": "deepseek-flash",
        "completed_ts": "2026-09-23T12:00:00Z",
        "answers": [
            {
                "summary": "The desk has no symbol-specific fundamental evidence for SentinelOne.",
                "citations": [
                    "ticker_enrichment_cache:S:2026-09-18T12:06:15",
                    "market_regime:risk_on_trend:2026-09-22",
                ],
            }
        ],
        "findings": [],
        "research_gaps_remaining": [],
        "limitations": [],
    }
    section = dl.format_hermes_section(result)
    final, prov = rp.finalize_operator_reply(
        section, rp.ReplyProvenance(kind="t", citations=dl.hermes_result_citations(result))
    )
    answer = next(ln for ln in final.split("\n") if "no symbol-specific" in ln)
    assert answer.endswith("[1] [2]")
    assert prov.cited[:2] == [
        "[1] Hermes evidence · ticker_enrichment_cache:S:2026-09-18T12:06:15",
        "[2] Hermes evidence · market_regime:risk_on_trend:2026-09-22",
    ]
    # the result id is not printed by the section, so it is not cited
    assert not any("rr_06fb7ccbc798" in c for c in prov.cited)

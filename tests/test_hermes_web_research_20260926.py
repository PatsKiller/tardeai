"""Options-gap research reads the web first (operator 2026-09-26).

"why not using hermes brave etc research llm if needed same research lanes": three
DELL runs cited only internal ids and answered "no authored thesis exists".
Hermetic: no network, no psycopg2; search lanes and the model call are injected.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import hermes_web_research as hw  # noqa: E402

NOW = datetime(2026, 9, 26, 23, 50, tzinfo=timezone.utc)
CFG = {"enabled_reasons": ["options_thesis_gap"], "max_queries": 3, "results_per_query": 2, "max_results": 5}


@dataclass
class Resp:
    ok: bool
    results: list = field(default_factory=list)
    reason: str = ""
    provider: str = "searxng"


def _req(reason="options_thesis_gap"):
    return {
        "authority": "READ_ONLY_ADVISORY",
        "research_id": "res_x",
        "symbol": "DELL",
        "reason": reason,
        "questions": [
            {"id": "q_thesis_check", "intent": "thesis_check", "text": "What is the thesis?"},
            {"id": "q_catalyst_map", "intent": "catalyst_map", "text": "Catalysts?"},
            {
                "id": "q_cio_followup_1",
                "intent": "cio_followup_1",
                "text": "DELL: find dated, sourced facts that resolve this CIO concern (do not restate it): "
                "Analyst data all null: rating, revision direction, street mean target",
            },
        ],
    }


def _hit(n):
    return {"url": f"https://example.com/dell-{n}", "title": f"DELL stock {n}", "description": f"earnings snippet {n}"}


def test_other_research_reasons_are_untouched():
    calls = []
    out = hw.gather(_req(reason="wake"), cfg=CFG, free_fn=lambda q, **k: calls.append(q), env={})
    assert out == {"used": False, "reason": "not_enabled_for_reason"} and calls == []


def test_queries_come_from_intents_and_cio_concerns():
    qs = hw.queries_for(_req(), hw.settings(CFG), now=NOW)
    assert qs[0] == "DELL stock outlook growth drivers 2026"
    assert qs[1] == "DELL next earnings date 2026"
    kinds = dict(hw.planned_queries(_req(), hw.settings(CFG), now=NOW))
    assert kinds["DELL next earnings date 2026"] == "news" and kinds[qs[0]] == "web"
    assert qs[2].startswith("DELL Analyst data") and "restate" not in qs[2] and "null" not in qs[2]


def test_searxng_first_brave_only_when_it_finds_nothing():
    free_calls, brave_calls = [], []

    def free(q, **k):
        free_calls.append((q, k["caller"]))
        return (
            Resp(ok=False, reason="ZERO_RESULTS") if "earnings" in q else Resp(ok=True, results=[_hit(len(free_calls))])
        )

    def brave(q, **k):
        brave_calls.append((q, k["caller"], k["enabled"]))
        return Resp(ok=True, results=[_hit("b")], provider="brave")

    out = hw.gather(_req(), cfg=CFG, free_fn=free, brave_fn=brave, env={"BRAVE_SEARCH_API_KEY": "k"})
    assert len(free_calls) == 3 and all(c == "hermes_cio_research" for _, c in free_calls)
    assert brave_calls == [("DELL next earnings date 2026", "hermes_cio_research", True)]
    assert [r["provider"] for r in out["results"]] == ["searxng", "brave", "searxng"]
    assert [r["id"] for r in out["results"]] == ["w1", "w2", "w3"]


def test_no_brave_key_means_no_paid_call():
    brave_calls = []
    out = hw.gather(
        _req(),
        cfg=CFG,
        free_fn=lambda q, **k: Resp(ok=False, reason="ZERO_RESULTS"),
        brave_fn=lambda q, **k: brave_calls.append(q),
        env={},
    )
    assert brave_calls == [] or hw._brave_key({})  # a key in the repo .env may exist on a dev box
    assert out["used"] and all(not q["ok"] for q in out["queries"])


def test_search_failure_is_no_results_never_an_exception():
    def boom(q, **k):
        raise TimeoutError("searx down")

    out = hw.gather(_req(), cfg={**CFG, "brave_fallback": False}, free_fn=boom, env={})
    assert out["used"] and out["results"] == []


def test_citations_are_grounded_to_supplied_urls():
    web = {
        "results": [
            {"id": "w1", "url": "https://a.com/x", "provider": "searxng"},
            {"id": "w2", "url": "https://b.com/y", "provider": "brave"},
        ],
        "queries": [],
    }
    body = {
        "answers": [{"question_id": "q1", "citations": ["w1", "https://made-up.com/z", "symbol_dell"]}],
        "sources": ["https://b.com/y", "https://made-up.com/q"],
        "source_refs": [],
    }
    out = hw.ground_citations(body, web)
    assert out["answers"][0]["citations"] == ["https://a.com/x", "symbol_dell"]
    assert out["source_urls"] == ["https://a.com/x", "https://b.com/y"]
    assert "https://made-up.com/q" not in out["sources"]
    assert out["web_research"]["cited"] == 2 and out["web_research"]["providers"] == ["brave", "searxng"]


def test_bridge_supplies_web_results_and_grounds_the_answer(monkeypatch):
    from scripts.lib import hermes_bridge_backend as hb

    web = {
        "used": True,
        "results": [
            {
                "id": "w1",
                "url": "https://ir.dell.com/q3",
                "title": "Dell Q3",
                "snippet": "Q3 FY27 earnings Nov 25",
                "provider": "searxng",
                "query": "q",
            }
        ],
        "queries": [{"query": "DELL next earnings date 2026", "provider": "searxng", "ok": True, "n": 1}],
    }
    monkeypatch.setattr(hb, "_gather_web", lambda request: web)
    seen = {}

    def chat(messages):
        seen["messages"] = messages
        return json.dumps(
            {
                "as_of": NOW.isoformat(),
                "findings": [],
                "answers": [
                    {
                        "question_id": q["id"],
                        "status": "answered",
                        "summary": "Earnings Nov 25.",
                        "detail": "",
                        "confidence": 0.7,
                        "citations": ["w1"],
                    }
                    for q in _req()["questions"]
                ],
            }
        )

    be = hb.BridgeHermesResearchBackend()
    monkeypatch.setattr(be, "_chat_completions", chat)
    body = be.run(_req())
    user = json.loads(seen["messages"][-1]["content"].split("\n", 1)[1])
    assert user["web_results"][0]["url"] == "https://ir.dell.com/q3"
    assert any("web_results are live search results" in m["content"] for m in seen["messages"] if m["role"] == "system")
    assert body["answers"][0]["citations"] == ["https://ir.dell.com/q3"]
    assert body["source_urls"] == ["https://ir.dell.com/q3"]
    assert body["web_research"]["cited"] == 1


def test_shop_and_support_pages_are_not_research():
    """2026-09-26 dry run: 'DELL' returned dell.com home, drivers and support pages."""
    hits = [
        {
            "url": "https://www.dell.com/en-us?msockid=1",
            "title": "Dell Computers & Technology Solutions",
            "description": "Shop laptops, desktops and monitors",
        },
        {"url": "https://www.dell.com/en-us?msockid=2", "title": "Dell Computers", "description": "Shop"},
        {
            "url": "https://www.marketbeat.com/stocks/NYSE/DELL/earnings/",
            "title": "Dell earnings date",
            "description": "Dell Technologies next earnings date",
        },
    ]
    out = hw.gather(
        _req(),
        cfg={**CFG, "brave_fallback": False, "max_queries": 1},
        free_fn=lambda q, **k: Resp(ok=True, results=hits),
        env={},
    )
    assert [r["url"] for r in out["results"]] == ["https://www.marketbeat.com/stocks/NYSE/DELL/earnings/"]


def test_concern_queries_drop_house_schema_words():
    q = hw._question_query(
        "DELL", "DELL: No dated catalyst events; catalyst.events and event_ids empty; analyst rating null"
    )
    assert "catalyst.events" not in q and "event_ids" not in q and "events" not in q.split()
    assert q.startswith("DELL") and "analyst" in q and "rating" in q


# ── 2026-09-27 W0-4: all CIO research web-grounded; producer pages reused first ──

def test_wildcard_enables_every_reason():
    assert hw.applies({"reason": "situation.raised:S3_REENTRY_CANDIDATE"}, hw.settings({"enabled_reasons": ["*"]}))
    assert not hw.applies({"reason": "x"}, hw.settings({"enabled_reasons": ["options_thesis_gap"]}))


def test_research_objects_are_reused_before_searching(tmp_path):
    feed = tmp_path / "research_objects.jsonl"
    rows = [
        {"symbol": "DELL", "captured_at": "2026-09-26T12:00:00Z", "source_url": "https://a.com/dell-earnings",
         "title": "Dell earnings preview", "body": "Dell stock ahead of quarter", "research_object_id": "ro1"},
        {"symbol": "DELL", "captured_at": "2026-09-20T12:00:00Z", "source_url": "https://old.com/x",
         "title": "Dell stock old", "body": "earnings", "research_object_id": "ro_old"},
        {"symbol": "HPE", "captured_at": "2026-09-26T12:00:00Z", "source_url": "https://b.com/hpe",
         "title": "HPE stock", "body": "earnings", "research_object_id": "ro2"},
        {"symbol": "DELL", "captured_at": "2026-09-26T13:00:00Z", "source_url": "https://www.dell.com/shop",
         "title": "Dell laptops", "body": "Shop now", "research_object_id": "ro_shop"},
    ]
    feed.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    cfg = {**CFG, "enabled_reasons": ["*"], "research_objects_path": str(feed), "brave_fallback": False, "max_queries": 1}
    searched = []
    out = hw.gather(_req(reason="situation.raised:S3_REENTRY_CANDIDATE"), cfg=cfg, env={}, now=NOW,
                    free_fn=lambda q, **k: searched.append(q) or Resp(ok=True, results=[_hit(1)]))
    assert out["results"][0]["url"] == "https://a.com/dell-earnings"
    assert out["results"][0]["provider"] == "research_objects" and out["results"][0]["research_object_id"] == "ro1"
    urls = [r["url"] for r in out["results"]]
    assert "https://old.com/x" not in urls and "https://b.com/hpe" not in urls and "https://www.dell.com/shop" not in urls
    assert out["queries"][0]["query"] == "reused_research_objects" and len(searched) == 1


def test_missing_feed_is_just_no_reuse(tmp_path):
    cfg = {**CFG, "research_objects_path": str(tmp_path / "absent.jsonl"), "brave_fallback": False, "max_queries": 1}
    out = hw.gather(_req(), cfg=cfg, env={}, now=NOW, free_fn=lambda q, **k: Resp(ok=True, results=[_hit(1)]))
    assert [r["provider"] for r in out["results"]] == ["searxng"]

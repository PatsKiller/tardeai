"""Ask the CIO — contract tests (AskRequest@v1 / AskAnswer@v1). Hermetic: no I/O beyond tmp AGENTS.md fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib import cio_ask_contract as C


def _prospectus(name="Tesla", guid="g-tsla", sym="TSLA"):
    sc = {s: C.Scenario(narrative=f"{s} case", price=100.0) for s in C.SCENARIOS}
    return C.SecurityProspectus(
        entity=C.EntityRef(name=name, symbol=sym, security_guid=guid),
        horizons={h: dict(sc) for h in C.HORIZONS},
        street_target=C.StreetTarget(
            low=150, median=250, high=400, n_analysts=40, as_of="2026-10-22", source="fixture"
        ),
        catalysts=[C.Catalyst(event="Q4 deliveries", date="2027-01-02", date_confidence="confirmed")],
        risks=["execution"],
        what_changes_view=["merger terms published"],
    )


def test_ask_id_is_deterministic_and_channel_scoped():
    a = C.make_ask_id(channel="cc", source_ref="r1", question="Buy  TSLA?")
    assert a == C.make_ask_id(channel="cc", source_ref="r1", question="buy tsla?")
    assert a != C.make_ask_id(channel="telegram", source_ref="r1", question="buy tsla?")
    assert C.make_thread_id(a).startswith("thr_")


def test_request_roundtrip_and_quantities_optional():
    req = C.AskRequest(question="Should I invest in Skydance?", channel="cc", source_ref="r1")
    assert C.validate_request(req) == []
    assert req.named_quantities == []
    back = C.AskRequest.from_dict(json.loads(json.dumps(req.to_dict())))
    assert back.ask_id == req.ask_id


def test_private_entity_never_carries_a_ticker():
    e = C.EntityRef(
        name="Acme Pre-IPO",
        kind="private_entity",
        entity_guid=C.private_entity_guid("Acme Pre-IPO"),
        resolution="UNRESOLVED_PRIVATE",
    )
    assert C.validate_entity(e) == []
    e.symbol = "ACME"
    assert any("never invent a ticker" in p for p in C.validate_entity(e))
    assert C.private_entity_guid("acme  pre-ipo") == C.private_entity_guid("ACME Pre IPO")


def test_prospectus_requires_all_horizons_scenarios_and_dated_catalysts():
    pr = _prospectus()
    assert C.validate_prospectus(pr) == []
    del pr.horizons["6m"]
    pr.catalysts.append(C.Catalyst(event="vague"))
    probs = C.validate_prospectus(pr)
    assert any("6m missing" in p for p in probs) and any("undated" in p for p in probs)


def test_answer_roundtrip_validates():
    ans = C.AskAnswer(
        ask_id="ask_x",
        thread_id="thr_x",
        version=1,
        depth="deep",
        status="deep",
        summary="Base case constructive.",
        prospectus=[_prospectus()],
        sources=[C.Source(title="10-Q", kind="sec", as_of="2026-10-20")],
        confidence=C.Confidence(level="medium", score=0.6),
    )
    assert C.validate_answer(ans, allow_size_suggestion=False) == []
    back = C.AskAnswer.from_dict(json.loads(json.dumps(ans.to_dict(allow_size_suggestion=False))))
    assert back.answer_id == "ask_x:v1" and back.prospectus[0].entity.symbol == "TSLA"


def test_sizing_context_has_no_behavior_field_keys():
    from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS

    keys = set(C.SizingContextRow.__dataclass_fields__)
    assert not keys & set(BEHAVIOR_FIELDS)


def test_mbi_guard_strips_quantity_and_order_advice():
    txt = (
        "TSLA's base case is constructive. I recommend buying 1,000 shares. "
        "Place a limit order at 240. Set your stop at 210.\nRisk: dilution."
    )
    clean, findings = C.mbi_guard_text(txt)
    assert len(findings) == 3
    assert "1,000 shares" not in clean and "limit order" not in clean and "stop at" not in clean
    assert "constructive" in clean and "dilution" in clean and C.MBI_STRIP_NOTE in clean


def test_mbi_guard_leaves_exposure_language_alone():
    txt = "At 100 shares the exposure is $25,000, 2.1% of the portfolio; at 1,000 shares it is 21%."
    clean, findings = C.mbi_guard_text(txt)
    assert findings == [] and clean == txt


def test_mbi_guard_payload_strips_behavior_keys():
    out, f = C.mbi_guard_payload({"view": "ok", "recommended_quantity": 500, "nested": [{"stop": 1, "x": 2}]})
    assert out == {"view": "ok", "nested": [{"x": 2}]}
    assert {x["match"] for x in f} == {"recommended_quantity", "stop"}


def test_size_suggestion_gated_until_21(tmp_path: Path):
    head = "# 0 · If you read nothing else\n\n| Version | Date | Status |\n|---|---|---|\n"
    p = tmp_path / "AGENTS.md"
    p.write_text(head + "| 19.0.0 | 2026-10-22 | ACTIVE |\n| 21.0.0 | 2026-10-24 | PROPOSED |\n")
    assert C.size_suggestion_allowed(p) is False
    p.write_text(head + "| 19.0.0 | 2026-10-22 | ACTIVE |\n| 21.0.0 | 2026-10-24 | ACTIVE |\n")
    assert C.size_suggestion_allowed(p) is True
    p.write_text(head + "| 22.1.0 | 2026-11-01 | ACTIVE |\n")
    assert C.size_suggestion_allowed(p) is True  # or_later
    assert C.size_suggestion_allowed(tmp_path / "missing.md") is False  # fail closed


def test_size_suggestion_omitted_and_flagged_while_gated():
    ans = C.AskAnswer(
        ask_id="a",
        thread_id="t",
        version=1,
        depth="quick",
        status="quick",
        summary="s",
        size_suggestion=[
            C.SizeSuggestion(
                symbol="TSLA", risk_budget_pct=0.5, reference_stop_price=200, illustrative_range=(10, 20), reasoning="r"
            )
        ],
    )
    assert "size_suggestion" not in ans.to_dict(allow_size_suggestion=False)
    assert any("21.0.0" in p for p in C.validate_answer(ans, allow_size_suggestion=False))
    assert "size_suggestion" in ans.to_dict(allow_size_suggestion=True)


def test_repo_agents_md_does_not_allow_size_suggestion_today():
    # AGENTS.md on this branch is 19.x — the gate must be closed.
    assert C.size_suggestion_allowed() is False


def test_parse_named_quantities():
    q = C.parse_named_quantities("100 or 1,000 TSLA given the SpaceX merger talk?", ["TSLA"])
    assert [(x.symbol, x.amount, x.unit) for x in q] == [("TSLA", 100.0, "shares"), ("TSLA", 1000.0, "shares")]
    assert C.parse_named_quantities("Invest in Skydance after Musk's $1B?", []) == []
    assert C.parse_named_quantities("Is TSLA a buy into 2027?", ["TSLA"]) == []
    q2 = C.parse_named_quantities("what about $5k of NVDA", ["NVDA"])
    assert [(x.amount, x.unit) for x in q2] == [(5000.0, "usd")]


def test_egress_drops_position_dollars():
    out = C.research_context_for_model({"q": "x", "sizing_context": [1], "facts": {"market_value": 9, "pe": 30}})
    assert out == {"q": "x", "facts": {"pe": 30}}

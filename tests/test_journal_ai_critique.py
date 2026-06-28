#!/usr/bin/env python3
"""AI trade critique methodology hardening (P1-4).

Deterministic-first; LLM prose may enrich but never erases deterministic facts; prompt
version + context/response hashes + deterministic-fallback flag are captured; replay
integrity failures degrade status; stale flips on tag change; search text mirrors payload.
Runs under pytest and standalone (pure functions — no DB).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")
    assert cond, f"{name} {detail}"


DET = {"summary": "Deterministic base summary with $1.23 entry", "strengths": ["good entry"],
       "improvements": ["size up"], "takeaways": ["t"], "deterministic": True}


def test_deterministic_without_llm():
    import journal_ai_critique as j
    nar, fallback = j._merge_llm_narrative(DET, None, "", "grok")
    check("no-llm keeps deterministic summary", nar.get("summary") == DET["summary"])
    check("no-llm sets deterministic_fallback", fallback is True)
    check("no-llm marks deterministic", nar.get("deterministic") is True)


def test_llm_cannot_overwrite_deterministic_facts():
    import journal_ai_critique as j
    parsed = {"summary": "LLM imagined a $9.99 entry", "strengths": ["x"],
              "improvements": [], "takeaways": []}
    nar, fallback = j._merge_llm_narrative(DET, parsed, '{"summary":"..."}', "grok")
    check("llm enhances", nar.get("llm_enhanced") is True and fallback is False)
    # Deterministic base summary is preserved verbatim alongside LLM prose.
    check("deterministic base summary preserved", nar.get("deterministic_base_summary") == DET["summary"])


def test_parse_failed_falls_back_deterministic():
    import journal_ai_critique as j
    nar, fallback = j._merge_llm_narrative(DET, None, "garbage non-json text", "grok")
    check("parse failure falls back", fallback is True and nar.get("parse_failed") is True)
    check("parse failure keeps deterministic summary", nar.get("summary") == DET["summary"])


def test_context_and_response_hash():
    import journal_ai_critique as j
    h1 = j._context_hash({"trade": {"sym": "V", "pnl": 10}})
    h2 = j._context_hash({"trade": {"sym": "V", "pnl": 10}})
    h3 = j._context_hash({"trade": {"sym": "V", "pnl": 11}})
    check("context hash stable", h1 == h2)
    check("context hash changes with input", h1 != h3)
    check("response hash None when empty", j._response_hash("") is None)
    check("response hash present when text", bool(j._response_hash("abc")))


def test_replay_integrity_degrades_status():
    import journal_ai_critique as j
    ok = j.replay_integrity_status({"replay_integrity": {"markers_resolved": True, "chart_integrity": {"ok": True}}})
    bad_markers = j.replay_integrity_status({"replay_integrity": {"markers_resolved": False, "chart_integrity": None}})
    bad_time = j.replay_integrity_status({"replay_integrity": {"markers_resolved": True, "chart_integrity": {"time_integrity": False}}})
    check("clean replay ok", ok["ok"] is True)
    check("unresolved markers not ok", bad_markers["ok"] is False)
    check("time integrity fail not ok", bad_time["ok"] is False and bad_time["time_integrity_ok"] is False)


def test_integrity_helper_variants():
    import journal_ai_critique as j
    check("None integrity ok", j._integrity_ok(None) is True)
    check("ok False blocks", j._integrity_ok({"ok": False}) is False)
    check("status fail blocks", j._integrity_ok({"status": "fail"}) is False)
    check("status pass ok", j._integrity_ok({"status": "pass"}) is True)


def test_invalid_trade_key_returns_none():
    import journal_ai_critique as j
    check("short key -> None", j.build_context("bad") is None)
    check("two-part key -> None", j.build_context("V:roth") is None)


def test_tag_fingerprint_stale_on_change():
    import journal_ai_critique as j
    a = {"setup_family": "breakout", "market_regime": "bull", "mistake_tags": ["fomo"]}
    b = {"setup_family": "breakout", "market_regime": "bull", "mistake_tags": ["fomo"]}
    c = {"setup_family": "pullback", "market_regime": "bull", "mistake_tags": ["fomo"]}
    check("same tags same fingerprint", j.tag_fingerprint(a) == j.tag_fingerprint(b))
    check("changed tag new fingerprint", j.tag_fingerprint(a) != j.tag_fingerprint(c))


def test_stale_from_tags_toggle():
    import journal_ai_critique as j
    review_now = {"setup_family": "pullback", "market_regime": "bull"}
    meta = {"tag_fingerprint": j.tag_fingerprint({"setup_family": "breakout", "market_regime": "bull"})}
    stale, _fp = j._stale_from_tags(review_now, meta, critique=None)
    check("tag change toggles stale", stale is True)
    review_same = {"setup_family": "breakout", "market_regime": "bull"}
    stale2, _ = j._stale_from_tags(review_same, meta, critique=None)
    check("matching tags not stale", stale2 is False)


def test_search_text_mirrors_payload():
    import journal_ai_critique as j
    critique = {"symbol": "NVDA", "narrative": {"summary": "clean breakout", "takeaways": ["hold winners"],
                "strengths": ["entry"], "improvements": ["trail"], "suggested_tags": ["fomo"]},
                "trade_classification": {"setup_family": "breakout", "market_regime": "bull"}}
    st = j._search_text(critique)
    check("search text mirrors symbol+summary+tags",
          "nvda" in st and "clean breakout" in st and "breakout" in st and "hold winners" in st)


ALL = [
    test_deterministic_without_llm, test_llm_cannot_overwrite_deterministic_facts,
    test_parse_failed_falls_back_deterministic, test_context_and_response_hash,
    test_replay_integrity_degrades_status, test_integrity_helper_variants,
    test_invalid_trade_key_returns_none, test_tag_fingerprint_stale_on_change,
    test_stale_from_tags_toggle, test_search_text_mirrors_payload,
]


if __name__ == "__main__":
    print("\n— AI trade critique methodology —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)

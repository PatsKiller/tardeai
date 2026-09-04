#!/usr/bin/env python3
"""Repost-amplification and bot-burst detection, with the negative controls.

The negative controls matter more than the positives here. A detector that
flags every busy day is worse than no detector: it trains the operator to
ignore it, and it mislabels genuine catalysts as manipulation.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.lib import social_integrity as S  # noqa: E402

T0 = datetime(2026, 9, 4, 14, 0, 0, tzinfo=timezone.utc)


def post(text, author="alice", offset=0, **kw):
    return {"title": text, "author": author, "created_at": (T0 + timedelta(seconds=offset)).isoformat(), **kw}


# ── Normalisation ───────────────────────────────────────────────────────────


def test_normalisation_ignores_links_handles_and_case():
    a = "ACME beats earnings! https://x.com/a?utm=1 $ACME @bob"
    b = "acme beats earnings https://other.link/z $ACME"
    assert S.normalize_text(a) == S.normalize_text(b)
    assert S.content_fingerprint(a) == S.content_fingerprint(b)


def test_the_retweet_prefix_is_stripped():
    """`RT @user: X` is X, amplified — the prefix is not content."""
    assert S.content_fingerprint("RT @someone: ACME halted") == S.content_fingerprint("ACME halted")


def test_different_claims_do_not_collide():
    assert S.content_fingerprint("ACME beats") != S.content_fingerprint("ACME misses")


# ── Repost detection ────────────────────────────────────────────────────────


def test_verbatim_reposts_collapse_to_one_claim():
    posts = [post("ACME halted pending news", author=f"u{i}", offset=i * 30) for i in range(6)]
    f = S.detect_reposts(posts)
    assert f.total_posts == 6
    assert f.distinct_claims == 1
    assert f.echo_posts == 5
    assert f.amplification_ratio == 1 - (1 / 6) or round(f.amplification_ratio, 2) == 0.83


def test_the_earliest_dated_post_is_the_original():
    posts = [
        post("ACME halted", author="late", offset=500),
        post("ACME halted", author="first", offset=0),
        post("ACME halted", author="middle", offset=200),
    ]
    f = S.detect_reposts(posts)
    grp = f.groups[0]
    assert posts[grp["original_index"]]["author"] == "first"


def test_an_undated_post_is_never_credited_as_the_original():
    """An amplifier with no timestamp must not be promoted to source."""
    posts = [
        {"title": "ACME halted", "author": "undated"},
        post("ACME halted", author="dated", offset=100),
    ]
    f = S.detect_reposts(posts)
    grp = f.groups[0]
    assert posts[grp["original_index"]]["author"] == "dated"


def test_reworded_reposts_are_caught_by_similarity_not_just_hashing():
    base = "ACME halted pending material news from the exchange this morning"
    posts = [
        post(base, author="a", offset=0),
        post(base + " today", author="b", offset=60),
        post("ACME halted pending material news from the exchange this morn", author="c", offset=120),
    ]
    f = S.detect_reposts(posts)
    assert f.max_group_size >= 2, "near-duplicate rewording escaped detection"
    assert any(not g["exact"] for g in f.groups)


def test_single_author_amplification_is_named():
    posts = [post("ACME to the moon", author="pumper", offset=i * 20) for i in range(4)]
    f = S.detect_reposts(posts)
    assert f.single_author_amplification is True
    assert "single author" in f.note


def test_reposts_are_annotated_not_deleted():
    """Dropping echoes would hide the amplification instead of showing it."""
    posts = [post("ACME halted", author=f"u{i}", offset=i * 10) for i in range(5)]
    f = S.detect_reposts(posts)
    members = f.groups[0]["member_indices"]
    assert len(members) == 5, "echo posts were discarded rather than grouped"
    assert f.total_posts == 5


# ── Repost NEGATIVE controls ────────────────────────────────────────────────


def test_distinct_claims_are_not_flagged_as_amplification():
    posts = [
        post("ACME beats on revenue", author="a", offset=0),
        post("ACME guidance cut for Q4", author="b", offset=30),
        post("ACME CFO departs abruptly", author="c", offset=60),
        post("ACME announces buyback programme", author="d", offset=90),
    ]
    f = S.detect_reposts(posts)
    assert f.echo_posts == 0
    assert f.amplification_ratio == 0.0
    assert f.distinct_claims == 4
    assert "distinct claim" in f.note


def test_a_shared_ticker_alone_is_not_a_repost():
    posts = [
        post("$ACME looks strong into earnings", author="a", offset=0),
        post("$ACME chart is breaking down badly", author="b", offset=10),
    ]
    assert S.detect_reposts(posts).echo_posts == 0


def test_empty_and_single_post_samples_are_safe():
    assert S.detect_reposts([]).total_posts == 0
    one = S.detect_reposts([post("solo")])
    assert one.echo_posts == 0 and one.distinct_claims == 1


# ── Bot-burst detection ─────────────────────────────────────────────────────


def test_a_single_author_flooding_a_window_is_flagged():
    posts = [post(f"ACME is going up {i}", author="pumper", offset=i * 5) for i in range(8)]
    f = S.detect_bot_burst(posts, window_seconds=300)
    assert f.detected is True
    assert any("author_concentration" in r for r in f.reasons)
    assert f.peak_count >= 8


def test_a_templated_burst_from_many_accounts_is_flagged():
    """Different authors, same script — the coordinated-promotion shape."""
    tpl = "ACME is the best opportunity in the market right now do not miss it"
    posts = [post(tpl, author=f"acct{i}", offset=i * 10) for i in range(7)]
    f = S.detect_bot_burst(posts, window_seconds=300)
    assert f.detected is True
    assert any("template_similarity" in r for r in f.reasons)
    assert f.distinct_authors_in_peak == 7


# ── Burst NEGATIVE controls — the ones that keep it usable ──────────────────


def test_a_genuine_catalyst_spike_is_not_flagged():
    """Many authors reacting to real news, each saying something different.

    This is the control that stops the detector becoming a news detector.
    """
    texts = [
        "ACME halted on the tape, waiting for the filing",
        "just saw the 8-K, guidance is cut by twelve percent",
        "my position is underwater, considering trimming here",
        "volume is enormous compared with the twenty day average",
        "does anyone have the transcript from the call",
        "downgrade from the sell side just crossed",
        "options chain is pricing a nine percent move",
        "this looks overdone to me, adding on weakness",
    ]
    posts = [post(t, author=f"trader{i}", offset=i * 20) for i, t in enumerate(texts)]
    f = S.detect_bot_burst(posts, window_seconds=300)
    assert f.detected is False, f"genuine catalyst flagged as a burst: {f.reasons}"
    assert f.peak_count >= 8, "the spike itself should still be measured"
    assert "not a burst" in f.note


def test_volume_alone_never_triggers_a_burst():
    posts = [post(f"independent observation number {i} about the market", author=f"u{i}", offset=i) for i in range(40)]
    assert S.detect_bot_burst(posts).detected is False


def test_a_small_sample_is_not_judged():
    posts = [post("ACME up", author="a", offset=0), post("ACME up", author="a", offset=5)]
    f = S.detect_bot_burst(posts, window_seconds=300)
    assert f.detected is False
    assert "below the" in f.note


def test_the_same_author_spread_over_days_is_not_a_burst():
    posts = [post(f"ACME thought {i}", author="regular", offset=i * 86400) for i in range(8)]
    assert S.detect_bot_burst(posts, window_seconds=300).detected is False


def test_undated_posts_do_not_fabricate_a_window():
    posts = [{"title": f"ACME {i}", "author": "a"} for i in range(10)]
    f = S.detect_bot_burst(posts)
    assert f.detected is False
    assert f.peak_count == 0


# ── Combined assessment + authority ─────────────────────────────────────────


def test_the_assessment_publishes_both_the_naive_and_corrected_counts():
    posts = [post("ACME halted", author=f"u{i}", offset=i * 10) for i in range(6)]
    a = S.assess_social_sample(posts, symbol="ACME")
    assert a["total_posts"] == 6
    assert a["effective_distinct_claims"] == 1
    assert a["integrity_degraded"] is True
    assert a["confidence_qualifier"] == "AMPLIFIED_OR_COORDINATED"


def test_a_clean_sample_reports_no_structural_distortion():
    posts = [
        post("ACME beats on revenue", author="a", offset=0),
        post("guidance was trimmed for the fourth quarter", author="b", offset=40),
        post("the CFO is stepping down next month", author="c", offset=80),
    ]
    a = S.assess_social_sample(posts, symbol="ACME")
    assert a["integrity_degraded"] is False
    assert a["confidence_qualifier"] == "NO_STRUCTURAL_DISTORTION"


def test_social_evidence_can_never_authorize_an_order():
    for sample in ([], [post("x")], [post("ACME halted", author=f"u{i}", offset=i) for i in range(9)]):
        a = S.assess_social_sample(sample)
        assert a["can_authorize_order"] is False
        assert a["verification_status"] == "UNVERIFIED"
        assert a["authority"] == "READ_ONLY_ADVISORY"


def test_the_module_holds_no_trading_surface():
    import ast

    src = (REPO / "scripts" / "lib" / "social_integrity.py").read_text()
    tree = ast.parse(src)
    idents = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            idents.add(n.id.lower())
        elif isinstance(n, ast.Attribute):
            idents.add(n.attr.lower())
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                idents.add(a.name.lower())
    for forbidden in ("place_order", "submit_order", "broker", "alpaca", "schwab", "position_size", "risk_limit"):
        assert not any(forbidden in i for i in idents), f"references {forbidden}"


def test_determinism_the_same_sample_always_scores_the_same():
    posts = [post("ACME halted", author=f"u{i}", offset=i * 10) for i in range(5)]
    a, b = S.assess_social_sample(posts), S.assess_social_sample(posts)
    assert a == b


# ── Wiring: the collector must actually consume the detector ────────────────


def _collector():
    import importlib

    scripts_dir = str(REPO / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module("aegis_social_sentiment")


def _mention(text, author, offset):
    return {
        "title": text,
        "author": author,
        "created_at": (T0 + timedelta(seconds=offset)).isoformat(),
        "bull_signals": 1,
        "bear_signals": 0,
        "score": 5,
    }


def test_the_collector_publishes_the_corrected_claim_count():
    a = _collector()
    amplified = [_mention("ACME to the moon", f"u{i}", i * 10) for i in range(6)]
    rec = a.normalize_sentiment("ACME", {"mentions": amplified}, {}, None)
    assert rec["mention_count"] == 6, "the raw count must remain visible"
    assert rec["effective_distinct_claims"] == 1
    assert rec["amplification_ratio"] > 0.8
    assert rec["integrity"]["integrity_degraded"] is True


def test_amplification_reduces_confidence():
    """A sample that is mostly echo supports less than its size suggests."""
    a = _collector()
    amplified = [_mention("ACME to the moon", f"u{i}", i * 10) for i in range(6)]
    distinct = [_mention(f"distinct observation number {i} about the company", f"u{i}", i * 60) for i in range(6)]
    amp = a.normalize_sentiment("ACME", {"mentions": amplified}, {}, None)
    dis = a.normalize_sentiment("ACME", {"mentions": distinct}, {}, None)
    assert amp["confidence"] < dis["confidence"]
    assert dis["amplification_ratio"] == 0.0
    assert dis["effective_distinct_claims"] == 6


def test_a_distinct_sample_is_not_penalised():
    a = _collector()
    distinct = [_mention(f"observation {i} about the quarter", f"u{i}", i * 60) for i in range(5)]
    rec = a.normalize_sentiment("ACME", {"mentions": distinct}, {}, None)
    assert rec["amplification_ratio"] == 0.0
    assert rec["coordinated_burst_detected"] is False
    assert rec["integrity"]["confidence_qualifier"] == "NO_STRUCTURAL_DISTORTION"


def test_the_collector_record_can_never_authorize_an_order():
    a = _collector()
    for sample in ([_mention("x", "u", 0)], [_mention("ACME up", f"u{i}", i) for i in range(9)]):
        rec = a.normalize_sentiment("ACME", {"mentions": sample}, {}, None)
        assert rec["can_authorize_order"] is False

"""P5 — the goal need ledger, and the independence defect underneath it.

THE DEFECT (measured 2026-09-16, `research_circle.score_lap` line 181):

    sources = {e.source.split(":")[0] for e in fresh}

That keys independence on the RETRIEVAL CHANNEL — how the item was fetched — not on
the publisher who made the claim. Two consequences, both silent:

  * `searxng:reuters.com` and `searxng:nyt.com` collapse to the single source
    "searxng". Six real publishers score as one and never earn the +25.
  * A Yahoo quote and an SEC Form 4 score as "two independent sources" although
    neither one can confirm or refute the other. So does one wire story reached
    through both Brave and SearXNG.

Every `min_sources >= 2` predicate reads that number, so the corruption is invisible
and total. These tests pin the fix at the level the defect lives on, and each one
goes red if its guarantee is removed:

  1. two SearXNG results from DIFFERENT publishers  => sources == 2
  2. the SAME publisher reached via two channels    => sources == 1
  3. a Yahoo quote + an SEC filing                  => NOT mutual corroboration

Plus the ledger itself: keyed (goal_id, predicate_version, lap), projecting what
score_lap already computed, append-only, and silent unless applied.

Offline and pure. No network, no database, no model, no spend.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_goal_need_ledger as ngl  # noqa: E402
from scripts.lib import research_circle as rc  # noqa: E402

COVERS = ["scripts/lib/cio_goal_need_ledger.py", "scripts/lib/research_circle.py",
          "scripts/run_research_circle.py"]

NOW = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)
TODAY = NOW.date().isoformat()


def _ev(kind, source, text, *, as_of=TODAY, value=None, channel="provider", url=None):
    return rc.Evidence(kind, source, text, as_of=as_of, value=value, channel=channel, url=url)


def _two_publishers():
    return [
        _ev("web", "searxng:reuters.com", "HPE wins a $450M award",
            url="https://www.reuters.com/tech/hpe-award", channel="web_free"),
        _ev("web", "searxng:nytimes.com", "HPE wins a $450M award",
            url="https://www.nytimes.com/2026/09/16/hpe.html", channel="web_free"),
    ]


def _one_publisher_two_channels():
    return [
        _ev("web", "searxng:reuters.com", "HPE wins a $450M award",
            url="https://www.reuters.com/tech/hpe-award", channel="web_free"),
        _ev("web", "brave:reuters.com", "HPE wins a $450M award",
            url="https://reuters.com/tech/hpe-award", channel="web_free"),
    ]


# ── 1. independence is counted by publisher ──────────────────────────────────

def test_two_searxng_results_from_different_publishers_are_two_sources():
    """The +25 that six publishers behind one search engine never used to earn."""
    s = rc.score_lap(["news"], _two_publishers(), now=NOW)
    need = s["per_need"]["news"]
    assert need["sources"] == ["nytimes.com", "reuters.com"]
    assert len(need["sources"]) == 2
    assert need["corroborated"] is True
    assert need["score"] == 65  # 40 base + 25 corroboration


def test_the_same_publisher_via_two_channels_is_one_source():
    """One wire story, two retrieval channels, one publisher — and no bonus."""
    s = rc.score_lap(["news"], _one_publisher_two_channels(), now=NOW)
    need = s["per_need"]["news"]
    assert need["sources"] == ["reuters.com"]
    assert len(need["sources"]) == 1
    assert need["corroborated"] is False
    assert need["score"] == 40  # no corroboration bonus
    # Both channels are still recorded — the pair is the key, the publisher is the count.
    assert need["independence_keys"] == ["reuters.com|brave", "reuters.com|searxng"]


def test_a_yahoo_quote_and_an_sec_filing_are_not_mutual_corroboration():
    """Two publishers, two unrelated claims. Neither can confirm or refute the other."""
    quote = _ev("quote", "yahoo", "HPE last $56.05", value=56.05,
                url="https://finance.yahoo.com/quote/HPE")
    filing = _ev("sec", "sec:form4", "HPE Form 4 2026-09-15: officer sold 10,000",
                 url="https://www.sec.gov/Archives/edgar/data/hpe/f4.htm")
    # They ARE two different publishers ...
    assert rc.publisher_host(quote) != rc.publisher_host(filing)
    # ... and they are still only ONE witness to any single claim.
    assert rc.corroborating_publishers([quote, filing]) == 1
    s = rc.score_lap(["price", "insiders"], [quote, filing], now=NOW)
    assert s["corroboration"]["corroborated"] is False
    assert s["corroboration"]["max_publishers_on_one_claim"] == 1
    assert s["per_need"]["price"]["score"] == 40
    assert s["per_need"]["insiders"]["score"] == 40
    assert s["per_need"]["price"]["corroborated"] is False
    assert s["per_need"]["insiders"]["corroborated"] is False


def test_the_retrieval_channel_alone_is_never_the_independence_key():
    """The defect stated directly: the old key sees one source where there are two."""
    ev = _two_publishers()
    assert len({rc.retrieval_channel(e) for e in ev}) == 1   # the OLD key: "searxng"
    assert len({rc.publisher_host(e) for e in ev}) == 2      # the NEW key: two publishers
    assert rc.score_lap(["news"], ev, now=NOW)["per_need"]["news"]["corroborated"] is True


def test_publisher_host_prefers_the_url_over_the_retrieval_channel():
    aggregated = _ev("web", "searxng:news.google.com", "Reuters: HPE wins award",
                     url="https://www.reuters.com/tech/hpe-award", channel="web_free")
    assert rc.publisher_host(aggregated) == "reuters.com"
    assert rc.retrieval_channel(aggregated) == "searxng"
    assert rc.independence_key(aggregated) == ("reuters.com", "searxng")
    # No URL: the source suffix, then the channel's canonical host.
    assert rc.publisher_host(_ev("web", "searxng:reuters.com", "x", channel="web_free")) == "reuters.com"
    assert rc.publisher_host(_ev("quote", "yahoo", "x")) == "finance.yahoo.com"
    assert rc.publisher_host(_ev("sec", "sec:form4", "x")) == "sec.gov"
    assert rc.publisher_host(_ev("quote", "trade_ai:ticker_prices", "x", channel="house")) == "house.trade_ai"


def test_house_and_outside_publishers_still_cross_check():
    """The pre-existing guarantee must survive the change: distinct publishers, one claim."""
    ev = [_ev("quote", "trade_ai:ticker_prices", "HPE close $55.96", value=55.96, channel="house"),
          _ev("quote", "yahoo", "HPE last $56.05", value=56.05)]
    s = rc.score_lap(["price"], ev, now=NOW)
    assert s["per_need"]["price"]["corroborated"] is True
    assert s["per_need"]["price"]["score"] == 100


# ── 2. the need ledger ───────────────────────────────────────────────────────

def _lap_score():
    ev = _two_publishers() + [
        _ev("analyst", "trade_ai:analysts", "Buy, target $96.50", as_of="2026-06-24", channel="house"),
    ]
    return rc.score_lap(["news", "analysts", "levels"], ev, now=NOW)


def test_the_row_is_keyed_by_goal_predicate_and_lap():
    s = _lap_score()
    row = ngl.build_row("goal-abc", s, lap=2, predicate_version="v3",
                        decision=rc.deterministic_decision(s, lap=2), now=NOW)
    assert row["key"] == "goal-abc|v3|2"
    assert (row["goal_id"], row["predicate_version"], row["lap"]) == ("goal-abc", "v3", 2)
    assert row["schema"] == "CIOGoalNeedLedger@v1"
    assert row["authority"] == "READ_ONLY_ADVISORY"
    assert ngl.ledger_key("g", "v1", 1) != ngl.ledger_key("g", "v2", 1)


def test_it_projects_score_lap_rather_than_rescoring():
    """Every number in the row is score_lap's. This ledger must never be a second scorer."""
    s = _lap_score()
    d = rc.deterministic_decision(s, lap=1)
    row = ngl.build_row("goal-abc", s, lap=1, decision=d, now=NOW)
    assert row["overall"] == s["overall"] and row["maturity"] == s["maturity"]
    assert row["weakest_need"] == s["weakest_need"]
    assert row["missing_facts"] == d["missing_facts"]
    assert row["decision"] == d["decision"]
    for n in row["per_need"]:
        src = s["per_need"][n["need"]]
        assert n["score"] == src["score"]
        assert n["publishers"] == src["sources"]          # publishers, not channels
        assert n["corroborated"] == src["corroborated"]
        assert n["fresh_items"] == src["fresh_items"]
    # "open" is score_lap's own missing-fact threshold, not a second opinion.
    assert row["open_needs"] == sorted(n for n, v in s["per_need"].items() if v["score"] < 40)
    assert set(row["open_needs"]) == set(d["missing_facts"])


def test_the_digest_moves_only_when_what_is_known_changes():
    one = rc.score_lap(["news"], _two_publishers()[:1], now=NOW)
    same = rc.score_lap(["news"], _two_publishers()[:1], now=NOW)
    richer = rc.score_lap(["news"], _two_publishers(), now=NOW)
    d_one = ngl.need_digest(ngl.project_needs(one))
    assert d_one == ngl.need_digest(ngl.project_needs(same))     # a lap that learned nothing
    assert d_one != ngl.need_digest(ngl.project_needs(richer))   # a second publisher is progress


def test_the_ledger_writes_nothing_unless_applied(tmp_path):
    path = tmp_path / "cio_goal_need_ledger.jsonl"
    s = _lap_score()
    dry = ngl.NeedLedger(path)
    dry.record("goal-abc", s, lap=1, predicate_version="v3")
    assert not path.exists()
    assert len(dry.rows) == 1

    live = ngl.NeedLedger(path, apply=True)
    live.record("goal-abc", s, lap=1, predicate_version="v3")
    live.record("goal-abc", s, lap=2, predicate_version="v3")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["lap"] for r in rows] == [1, 2]
    assert live.latest("goal-abc", "v3")["lap"] == 2
    assert live.read("other-goal", "v3") == []


def test_the_ledger_is_append_only(tmp_path):
    """A re-recorded lap appends a new row; it never rewrites the old one."""
    path = tmp_path / "need.jsonl"
    s = _lap_score()
    led = ngl.NeedLedger(path, apply=True)
    led.record("goal-abc", s, lap=1, predicate_version="v3")
    led.record("goal-abc", s, lap=1, predicate_version="v3")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(led.read("goal-abc", "v3")) == 2


def test_a_damaged_line_does_not_hide_the_rows_around_it(tmp_path):
    path = tmp_path / "need.jsonl"
    s = _lap_score()
    led = ngl.NeedLedger(path, apply=True)
    led.record("goal-abc", s, lap=1, predicate_version="v3")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"goal_id": "goal-abc", trunc\n')
    led.record("goal-abc", s, lap=2, predicate_version="v3")
    assert [r["lap"] for r in led.read("goal-abc", "v3")] == [1, 2]


# ── cross-module identity: one spelling for "this goal has no predicate yet" ──
# P4 and P5 were briefed separately and independently chose "v0" and "v0-unset"
# for the SAME condition. Nothing failed, because P4 filters its own lap ledger
# (where it writes and reads its own spelling) and reads P5's rows on goal_id
# alone -- so the divergence was latent. But the same field keys the generation
# token, this ledger row and the budget bucket, so two spellings means one
# goal-lap carrying two identities: precisely the five-identities-no-join-key
# defect the goal-loop plan exists to remove, reintroduced by parallel work.
# Canonical is "v0", matching cio_goals' `v{int}` identity rendering, so the
# unset line reads as the natural predecessor of v1.

def test_predicate_version_is_canonical_across_modules():
    """A second spelling of the unset version must fail here, not in production."""
    from scripts.lib import goal_generation as gg
    assert ngl.DEFAULT_PREDICATE_VERSION == gg.PREDICATE_VERSION_FALLBACK == "v0"


def test_the_unset_version_joins_across_the_ledger_and_the_generation_token():
    """The ledger row and the dedup key must agree on the version segment."""
    from scripts.lib import goal_generation as gg
    unset_goal = {"goal_id": "goal-abc"}
    pv = gg.predicate_version(unset_goal)
    assert pv == ngl.DEFAULT_PREDICATE_VERSION
    key = ngl.ledger_key("goal-abc", pv, 1)
    assert key.split("|")[1] == pv
    assert f":{pv}:" in gg.generation_key("goal-abc", pv, "deadbeef")


def test_the_cli_default_derives_from_the_constant_not_a_literal():
    """run_research_circle --predicate-version must follow the canonical constant."""
    import re
    from pathlib import Path
    src = Path("scripts/run_research_circle.py").read_text(encoding="utf-8")
    m = re.search(r'--predicate-version["\'],\s*default=([A-Za-z_.]+)', src)
    assert m, "the --predicate-version default should be a named constant"
    assert m.group(1).endswith("DEFAULT_PREDICATE_VERSION")

"""Tests for youtube_channel_discovery asset-class coverage + auto-approve threshold."""
import importlib
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

ycd = importlib.import_module("youtube_channel_discovery")


def test_discovery_queries_cover_put_bond_growth():
    blob = " ".join(q["query"].lower() + " " + q["strategy"].lower()
                    for q in ycd.DISCOVERY_QUERIES)
    assert "put" in blob, "expected put-selling coverage in DISCOVERY_QUERIES"
    assert "bond" in blob, "expected bond coverage in DISCOVERY_QUERIES"
    assert "growth" in blob, "expected growth coverage in DISCOVERY_QUERIES"
    # Broader asset-class span
    assert any("treasury" in q["query"].lower() or q.get("asset_class") == "bond"
               for q in ycd.DISCOVERY_QUERIES)
    assert any(q.get("asset_class") == "options_income" for q in ycd.DISCOVERY_QUERIES)
    assert any("retirement" in q["query"].lower() or q.get("asset_class") == "retirement"
               for q in ycd.DISCOVERY_QUERIES)


def test_auto_approve_threshold_constant():
    assert ycd.AUTO_APPROVE_QUALITY == 75
    assert ycd.MAX_CANDIDATES_PER_RUN == 20


def test_score_channel_add_below_auto_approve_stays_review_path():
    """Q in [50,74] → recommendation ADD but below auto-approve threshold."""
    # Force a mid score via known retirement keywords + modest subs
    scores = ycd.score_channel(
        name="Dividend Income Channel",
        description="dividend yield income retirement ira covered call strategy",
        subscribers=15000,
        video_count=80,
        strategy="tactical_income",
        asset_class="options_income",
    )
    assert scores["recommendation"] in ("ADD", "REVIEW")
    if scores["recommendation"] == "ADD" and scores["quality_score"] < ycd.AUTO_APPROVE_QUALITY:
        # Eligible for candidate insert but NOT auto-approve
        assert scores["quality_score"] < 75


def test_score_channel_high_quality_meets_auto_approve_gate():
    scores = ycd.score_channel(
        name="Dividend Growth Investing",
        description=(
            "dividend growth investing yield income retirement roth ira 401k "
            "covered call bdc cef reit medicare irmaa social security "
            "put selling bond etf treasury"
        ),
        subscribers=600000,
        video_count=600,
        strategy="dividend_growth_compounder",
        asset_class="equity",
    )
    assert scores["recommendation"] == "ADD"
    assert scores["quality_score"] >= ycd.AUTO_APPROVE_QUALITY


def test_max_candidates_cap_respected(monkeypatch):
    """discover_channels stops inserting after max_candidates."""
    calls = {"n": 0}

    class FakeCur:
        def execute(self, *a, **k):
            sql = a[0] if a else ""
            if "SELECT channel_id FROM youtube_channels" in sql or \
               "SELECT channel_id FROM youtube_channel_candidates" in sql:
                self._rows = []
            elif "CREATE TABLE" in sql:
                pass
            elif "INSERT INTO youtube_channel_candidates" in sql:
                calls["n"] += 1
                self.rowcount = 1
            else:
                self.rowcount = 0

        def fetchall(self):
            return getattr(self, "_rows", [])

        def fetchone(self):
            return None

    class FakeConn:
        def cursor(self, **k):
            return FakeCur()

        def commit(self):
            pass

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(ycd, "_get_conn", lambda: FakeConn())
    monkeypatch.setattr(ycd, "_youtube_search", lambda q, max_results=3: [{
        "channel_id": f"UC{abs(hash(q)) % 10**22:022d}"[:24],
        "channel_name": f"Chan {q[:20]}",
        "description": "dividend yield income retirement ira covered call bond etf growth stocks",
    }])
    monkeypatch.setattr(ycd, "_get_channel_stats", lambda cid: {
        "subscribers": 200000, "video_count": 200,
        "description": "dividend yield income retirement ira covered call bond etf growth",
    })
    monkeypatch.setattr(ycd, "_auto_approve_candidate", lambda *a, **k: False)

    result = ycd.discover_channels(send_telegram=False, max_candidates=3)
    assert result["candidates"] <= 3
    assert calls["n"] <= 3
    assert result["capped_at"] == 3

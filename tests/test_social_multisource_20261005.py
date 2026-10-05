"""Social scanner uses every social source, not StockTwits alone (operator 2026-10-05).

- Reddit uses the official Data API (app-only OAuth); unauthenticated JSON is 403. Not configured or
  failing is LOUD (printed + `reddit` source health row), never a silent 0.
- Hermes forum search and Aegis social sentiment (social_sentiment_history) are merged into the
  scanner's per-symbol aggregate as named sources.
- The catalyst researcher looks at scouts blocked only on catalyst verification first.
- Hermes social can run on today's scalp candidates.
Fakes only: no network, no database, no secrets.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def _stub(name, **attrs):
    if name in sys.modules:
        return
    try:
        __import__(name)
        return
    except Exception:  # noqa: BLE001
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub("dotenv", load_dotenv=lambda *a, **k: None)
_stub("psycopg2", connect=lambda *a, **k: None)
_stub("psycopg2.extras", RealDictCursor=object)
if "psycopg2" in sys.modules and not hasattr(sys.modules["psycopg2"], "extras"):
    sys.modules["psycopg2"].extras = sys.modules["psycopg2.extras"]
_stub("requests", get=None, post=None)

import social_ingest as si  # noqa: E402


# ── Reddit ────────────────────────────────────────────────────────────────────

def test_reddit_not_configured_is_loud_and_touches_no_db(monkeypatch, capsys):
    monkeypatch.setattr(si, "_reddit_secret", lambda n: "")
    reported = []
    monkeypatch.setattr(si, "_report_reddit", lambda ok, rows, err: reported.append((ok, rows, err)))
    monkeypatch.setattr(si, "_get_conn", lambda: pytest.fail("must not open the DB when Reddit is not configured"))
    res = si.ingest_reddit_with_discovery()
    assert res["configured"] is False and res["inserted"] == 0
    assert reported and reported[0][0] is False and "REDDIT_NOT_CONFIGURED" in reported[0][2]


def test_reddit_session_uses_official_oauth(monkeypatch):
    monkeypatch.setattr(si, "_reddit_secret", lambda n: {"REDDIT_CLIENT_ID": "cid", "REDDIT_CLIENT_SECRET": "sec"}[n])
    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return {"access_token": "tok"}
    fake = types.SimpleNamespace(post=lambda url, **kw: calls.append((url, kw)) or Resp())
    monkeypatch.setitem(sys.modules, "requests", fake)
    s = si.reddit_session()
    assert s["ok"] and s["base"] == "https://oauth.reddit.com"
    assert s["headers"]["Authorization"] == "bearer tok" and "User-Agent" in s["headers"]
    url, kw = calls[0]
    assert url == si.REDDIT_TOKEN_URL and kw["auth"] == ("cid", "sec") and kw["data"]["grant_type"] == "client_credentials"


def test_reddit_token_failure_is_reported(monkeypatch):
    monkeypatch.setattr(si, "_reddit_secret", lambda n: "x")

    class Resp:
        status_code = 401

        def json(self):
            return {}
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=lambda *a, **k: Resp()))
    s = si.reddit_session()
    assert s == {"ok": False, "reason": "REDDIT_TOKEN_HTTP_401"}


def test_momentum_subreddits_are_included():
    for sub in ("pennystocks", "smallstreetbets", "Daytrading", "wallstreetbets"):
        assert sub in si.REDDIT_MOMENTUM_SUBS
    src = (ROOT / "scripts" / "social_ingest.py").read_text()
    assert "www.reddit.com/r/" not in src                       # no unauthenticated reads left


def test_reddit_client_id_is_storable():
    import secrets_admin as sa
    assert "REDDIT_CLIENT_ID" in sa.KNOWN_CONFIG
    assert "REDDIT_CLIENT_SECRET".endswith(sa.SECRET_SUFFIXES)


# ── Scanner merge ─────────────────────────────────────────────────────────────

class _Cur:
    def __init__(self, posts, history, fail_history=False):
        self.posts, self.history, self.fail_history = posts, history, fail_history
        self._last = []

    def execute(self, sql, params=None):
        if "social_sentiment_history" in sql:
            if self.fail_history:
                raise RuntimeError("no table")
            self._last = self.history
        else:
            self._last = self.posts

    def fetchall(self):
        return list(self._last)


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def rollback(self):
        pass


def _scanner():
    import social_scalp_scanner as sss
    return sss


HISTORY = [
    {"symbol": "sdev", "source_family": "hermes", "source_name": "hermes_searxng", "mention_count": 4,
     "bullish_count": 3, "bearish_count": 0, "top_posts_summary": "SDEV forum chatter", "universe": "scalp"},
    {"symbol": "SDEV", "source_family": "social", "source_name": "reddit+stocktwits+brave", "mention_count": 6,
     "bullish_count": 4, "bearish_count": 1, "top_posts_summary": ""},
    {"symbol": "TOOLONG", "source_family": "hermes", "source_name": "x", "mention_count": 9,
     "bullish_count": 0, "bearish_count": 0, "top_posts_summary": "", "universe": "scalp"},
    {"symbol": "MSFT", "source_family": "social", "source_name": "reddit+stocktwits+brave", "mention_count": 30,
     "bullish_count": 9, "bearish_count": 2, "top_posts_summary": "", "universe": "tracked"},
]


def test_scanner_merges_hermes_and_aegis_as_named_sources():
    sss = _scanner()
    posts = [{"platform": "stocktwits", "symbols_mentioned": ["SDEV"], "sentiment": "bullish",
              "text": "SDEV up", "post_date": datetime.now(timezone.utc), "strategy_tags": []}] * 2
    cands = sss.get_social_candidates(_Conn(_Cur(posts, HISTORY)))
    sdev = next(c for c in cands if c["symbol"] == "SDEV")
    assert sdev["mention_count"] == 2                         # ranking stays on its own post mentions
    assert sdev["external_mentions"] == 4 + 6
    assert set(sdev["sources"]) == {"stocktwits", "hermes:hermes_searxng", "social:reddit+stocktwits+brave"}
    assert sdev["mentions_by_source"] == {"stocktwits": 2, "hermes:hermes_searxng": 4,
                                         "social:reddit+stocktwits+brave": 6}
    assert sdev["bull"] == 2 + 3 + 4 and sdev["bear"] == 1
    assert all(c["symbol"] not in ("TOOLONG", "MSFT") for c in cands)  # tracked universe never adds a scalp name


def test_scanner_finds_scalp_universe_candidates_with_no_stocktwits_posts():
    sss = _scanner()
    cands = sss.get_social_candidates(_Conn(_Cur([], HISTORY)))
    assert [c["symbol"] for c in cands] == ["SDEV"]          # only the scalp-universe Hermes row creates one
    assert cands[0]["mention_count"] == 4                     # scalp-universe mentions rank it
    assert cands[0]["sources"] == ["hermes:hermes_searxng", "social:reddit+stocktwits+brave"]


def test_scanner_survives_missing_history_table():
    sss = _scanner()
    posts = [{"platform": "stocktwits", "symbols_mentioned": ["ABCD"], "sentiment": "", "text": "x",
              "post_date": datetime.now(timezone.utc), "strategy_tags": []}] * 3
    cands = sss.get_social_candidates(_Conn(_Cur(posts, [], fail_history=True)))
    assert cands and cands[0]["sources"] == ["stocktwits"]


# ── Catalyst researcher + Hermes social universe ─────────────────────────────

def test_catalyst_researcher_puts_awaiting_scouts_first(monkeypatch):
    import hermes_momentum_catalyst_researcher as hm
    results = [[("SDEV",)], [("AAA",), ("SDEV",), ("BBB",)]]

    class C:
        def execute(self, sql, params=None):
            self.rows = results.pop(0)

        def fetchall(self):
            return self.rows

    class K:
        def cursor(self):
            return C()

        def close(self):
            pass
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda **k: K()))
    assert hm.get_scalp_candidates(max_tickers=3) == ["SDEV", "AAA", "BBB"]


def test_hermes_social_can_use_the_scalp_universe(monkeypatch):
    import hermes_momentum_catalyst_researcher as hm
    import hermes_social_sentiment as hs
    monkeypatch.setattr(hm, "get_scalp_candidates", lambda max_tickers=25: ["SDEV", "CRMD"])
    assert hs.resolve_scalp_universe(10) == ["SDEV", "CRMD"]

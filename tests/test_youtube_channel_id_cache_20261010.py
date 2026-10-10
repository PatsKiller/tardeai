"""YouTube lane stops paying search.list to find channels it already tracks (API overlap Q9, 2026-10-10).

Measured: ~30 active youtube_channels rows carry a slug channel_id ("ben_felix") plus a /@handle,
/c/Name or /user/Name URL. fetch_channel_videos fell back to search.list (100 units) for each of them
on every run: ~3,000 units a run, ~15.2k a week. The fix resolves the UC id once (channels.list, 1 unit)
and caches it in the durable runtime dir. Fakes only: no network, no database.
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
    import psycopg2.extras  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import youtube_transcript_ingest as yt  # noqa: E402

UC = "UCabcdefghijklmnopqrstuv"  # 24 chars


class _Cur:
    def __init__(self, row, updates):
        self.row, self.updates = row, updates

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("UPDATE"):
            self.updates.append(params)

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row, updates):
        self.row, self.updates = row, updates

    def cursor(self, cursor_factory=None):
        return _Cur(self.row, self.updates)

    def commit(self):
        pass

    def close(self):
        pass


def _wire(monkeypatch, tmp_path, row, handle_items=None):
    calls, updates = [], []
    handle_items = [{"id": UC, "snippet": {"title": "Ben Felix"}}] if handle_items is None else handle_items

    def urlopen(url, timeout=None):
        calls.append(url)
        if "/search" in url:
            body = {"items": [{"id": {"videoId": "s1"}, "snippet": {"title": "t", "channelTitle": "c",
                                                                    "publishedAt": "2026-10-09T00:00:00Z"}}]}
        elif "forHandle=" in url or "forUsername=" in url:
            body = {"items": handle_items}
        elif "/channels" in url:
            body = {"items": [{"snippet": {"title": "Ben Felix"},
                               "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}]}
        elif "/playlistItems" in url:
            body = {"items": [{"snippet": {"title": "v", "publishedAt": "2026-10-09T00:00:00Z",
                                           "resourceId": {"videoId": "p1"}}}]}
        else:
            raise AssertionError(url)
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(yt.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(yt, "_get_conn", lambda: _Conn(row, updates))
    monkeypatch.setattr(yt, "ingest_video", lambda url, **_k: {"status": "already_exists"})
    return calls, updates


ROW = {"channel_id": "ben_felix", "channel_name": "Ben Felix", "channel_url": "https://www.youtube.com/@BenFelixCSI"}


def test_slug_channel_uses_uploads_playlist_not_search(monkeypatch, tmp_path):
    calls, updates = _wire(monkeypatch, tmp_path, ROW)
    quota = yt.QuotaBudget()
    out = yt.fetch_channel_videos("ben_felix", quota=quota)
    assert not any("/search" in u for u in calls), "search.list (100 units) must not be used once a UC id resolves"
    assert out["discovery"] == "uploads_playlist"
    assert quota.spent <= 3  # forHandle 1 + channels 1 + playlistItems 1, versus 100 for search
    assert updates == [("ben_felix",)], "last_checked is keyed on the row's own channel_id"
    cache = json.loads((tmp_path / "data" / "runtime" / yt.CHANNEL_ID_CACHE_NAME).read_text())
    assert cache["ben_felix"]["channel_id"] == UC


def test_second_run_reads_the_cache(monkeypatch, tmp_path):
    calls, _ = _wire(monkeypatch, tmp_path, ROW)
    yt.fetch_channel_videos("ben_felix", quota=yt.QuotaBudget())
    calls.clear()
    quota = yt.QuotaBudget()
    yt.fetch_channel_videos("ben_felix", quota=quota)
    assert not any("forHandle=" in u or "/search" in u for u in calls)
    assert quota.spent == 2


def test_unresolvable_channel_falls_back_to_search_and_is_negative_cached(monkeypatch, tmp_path):
    calls, _ = _wire(monkeypatch, tmp_path, ROW, handle_items=[])
    out = yt.fetch_channel_videos("ben_felix", quota=yt.QuotaBudget())
    assert out["discovery"] == "search"  # unchanged fallback when no UC id resolves
    calls.clear()
    yt.fetch_channel_videos("ben_felix", quota=yt.QuotaBudget())
    assert not any("forHandle=" in u for u in calls), "a failed lookup is not repeated within the negative TTL"


def test_lookup_query_per_url_shape():
    assert yt._channel_lookup_query("https://www.youtube.com/@BenFelixCSI") == "forHandle=BenFelixCSI"
    assert yt._channel_lookup_query("https://www.youtube.com/c/YahooFinance") == "forHandle=YahooFinance"
    assert yt._channel_lookup_query("https://www.youtube.com/user/abc") == "forUsername=abc"
    assert yt._channel_lookup_query("https://example.invalid/x") is None

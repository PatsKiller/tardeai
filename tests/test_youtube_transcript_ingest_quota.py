#!/usr/bin/env python3
"""Unit tests: YouTube daily ingest prefers uploads playlist over search.list."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import youtube_transcript_ingest as yti  # noqa: E402


UC_ID = "UCabcdefghijklmnopqrstuv"  # 24 chars, starts with UC


def _db_row(**kwargs):
    return dict(kwargs)


def _fake_conn(fetchone_row=None, fetchall_rows=None):
    """Minimal psycopg2-like connection/cursor for DB lookups."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_row
    cur.fetchall.return_value = fetchall_rows or []
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setattr(yti, "_get_youtube_api_key", lambda: "test-key")


def test_is_usable_channel_id():
    assert yti._is_usable_channel_id(UC_ID) is True
    assert yti._is_usable_channel_id("UC" + "x" * 22) is True
    assert yti._is_usable_channel_id("Dividend Bull") is False
    assert yti._is_usable_channel_id("") is False
    assert yti._is_usable_channel_id(None) is False
    assert yti._is_usable_channel_id("UC_short") is False


def test_quota_budget_charge_and_exhaust():
    q = yti.QuotaBudget(limit=150)
    assert q.charge(yti.COST_SEARCH_LIST) is True
    assert q.spent == 100
    assert q.exhausted is False
    # Next search would exceed 150
    assert q.charge(yti.COST_SEARCH_LIST) is False
    assert q.exhausted is True
    assert q.spent == 100


def test_fetch_prefers_list_channel_videos_when_channel_id_present(api_key, monkeypatch):
    row = _db_row(channel_id=UC_ID, channel_name="Dividend Bull", channel_url="")
    monkeypatch.setattr(yti, "_get_conn", lambda: _fake_conn(fetchone_row=row))

    listed = [
        {
            "video_id": "abcdefghijk",
            "title": "Weekly Dividends",
            "channel": "Dividend Bull",
            "published": "2026-08-19T12:00:00Z",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
        }
    ]
    list_mock = MagicMock(return_value=listed)
    search_mock = MagicMock(return_value=[])
    ingest_mock = MagicMock(return_value={"status": "ingested", "video_id": "abcdefghijk"})

    monkeypatch.setattr(yti, "list_channel_videos", list_mock)
    monkeypatch.setattr(yti, "search_channel_videos", search_mock)
    monkeypatch.setattr(yti, "ingest_video", ingest_mock)

    result = yti.fetch_channel_videos(UC_ID, max_videos=3)

    list_mock.assert_called_once()
    assert list_mock.call_args.args[0] == UC_ID
    assert list_mock.call_args.kwargs.get("max_results") == 3 or list_mock.call_args.args[1:] == ()
    search_mock.assert_not_called()
    ingest_mock.assert_called_once()
    assert ingest_mock.call_args.kwargs.get("publish_date") == "2026-08-19T12:00:00Z"
    assert result["discovery"] == "uploads_playlist"
    assert result["found"] == 1
    assert result["ingested"] == 1
    assert result["quota_exhausted"] is False


def test_fetch_uses_search_only_as_fallback_without_channel_id(api_key, monkeypatch):
    row = _db_row(channel_id="handle-not-uc", channel_name="Some Channel", channel_url="")
    monkeypatch.setattr(yti, "_get_conn", lambda: _fake_conn(fetchone_row=row))

    list_mock = MagicMock(return_value=[])
    search_mock = MagicMock(
        return_value=[
            {
                "video_id": "xyzxyzxyzxy",
                "title": "Market Talk",
                "channel": "Some Channel",
                "published": "2026-08-18T10:00:00Z",
                "url": "https://www.youtube.com/watch?v=xyzxyzxyzxy",
            }
        ]
    )
    ingest_mock = MagicMock(return_value={"status": "already_exists", "video_id": "xyzxyzxyzxy"})

    monkeypatch.setattr(yti, "list_channel_videos", list_mock)
    monkeypatch.setattr(yti, "search_channel_videos", search_mock)
    monkeypatch.setattr(yti, "ingest_video", ingest_mock)

    result = yti.fetch_channel_videos("Some Channel", max_videos=2)

    list_mock.assert_not_called()
    search_mock.assert_called_once()
    assert result["discovery"] == "search"
    assert result["found"] == 1
    ingest_mock.assert_called_once()
    assert ingest_mock.call_args.kwargs.get("publish_date") == "2026-08-18T10:00:00Z"


def test_quota_guard_stops_further_api_calls(api_key, monkeypatch):
    """With a tiny budget, later channels must not call list/search APIs."""
    channels = [
        _db_row(channel_id=UC_ID, channel_name="Chan A"),
        _db_row(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", channel_name="Chan B"),
        _db_row(channel_id="UCcccccccccccccccccccccc", channel_name="Chan C"),
    ]
    by_id = {c["channel_id"]: c for c in channels}
    call_log: list[str] = []
    phase = {"n": 0}

    def get_conn():
        phase["n"] += 1
        # First connection: channel list for ingest_all_channels
        if phase["n"] == 1:
            return _fake_conn(fetchall_rows=channels)
        # Remaining connections serve fetchone by channel_id from the SQL args —
        # RealDictCursor mock ignores SQL; return a generic conn whose fetchone
        # uses the last-seen channel from list_channel_videos calls, or row 0.
        # Simpler approach: return rows in order for successive fetchone calls.
        conn = _fake_conn()
        cur = conn.cursor.return_value

        def execute(sql, params=None):
            cur._last_sql = sql
            cur._last_params = params or ()

        def fetchone():
            params = getattr(cur, "_last_params", ())
            if params and params[0] in by_id:
                return by_id[params[0]]
            # ILIKE / name path — match by name fragment
            for c in channels:
                if params and str(params[0]) in (c["channel_id"], c["channel_name"]):
                    return c
            return channels[0]

        cur.execute.side_effect = execute
        cur.fetchone.side_effect = fetchone
        return conn

    def fake_list(channel_id, max_results=50, *, quota=None):
        if quota is not None:
            if not quota.charge(yti.COST_CHANNELS_LIST):
                call_log.append(f"blocked-list:{channel_id}")
                return []
            if not quota.charge(yti.COST_PLAYLIST_ITEMS_PAGE):
                call_log.append(f"blocked-playlist:{channel_id}")
                return []
        call_log.append(f"list:{channel_id}")
        return [
            {
                "video_id": "vid" + channel_id[-8:],
                "title": f"Video {channel_id[-4:]}",
                "channel": channel_id,
                "published": "2026-08-19T00:00:00Z",
                "url": f"https://www.youtube.com/watch?v=vid{channel_id[-8:]}",
            }
        ]

    def fake_search(channel_name, max_results=5, *, quota=None):
        call_log.append(f"search:{channel_name}")
        if quota is not None:
            quota.charge(yti.COST_SEARCH_LIST)
        return []

    monkeypatch.setattr(yti, "_get_conn", get_conn)
    monkeypatch.setattr(yti, "list_channel_videos", fake_list)
    monkeypatch.setattr(yti, "search_channel_videos", fake_search)
    monkeypatch.setattr(
        yti,
        "ingest_video",
        MagicMock(return_value={"status": "ingested", "video_id": "x"}),
    )

    # Budget of 2 units: enough for one channel (1 channels.list + 1 playlist page)
    result = yti.ingest_all_channels(max_per_channel=1, quota_budget=2)

    list_calls = [c for c in call_log if c.startswith("list:")]
    search_calls = [c for c in call_log if c.startswith("search:")]
    assert len(list_calls) == 1, f"expected 1 successful list call, got {call_log}"
    assert search_calls == [], f"search must not run: {call_log}"
    assert result["quota_exhausted"] is True
    assert result["channels"] == 3
    # First channel succeeds; second attempt trips the guard and stops
    assert result["channels_processed"] == 2
    assert result["quota_spent"] == 2
    assert "UCcccccccccccccccccccccc" not in "".join(call_log)


def test_list_channel_videos_charges_quota_and_stops(api_key, monkeypatch):
    monkeypatch.setattr(
        yti,
        "get_channel_info",
        lambda channel_id: {
            "channel_id": channel_id,
            "channel_name": "T",
            "uploads_playlist": "UUabcdefghijklmnopqrstuv",
        },
    )

    pages_fetched = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            pages_fetched["n"] += 1
            return (
                b'{"items":[{"snippet":{"resourceId":{"videoId":"aaaaaaaaaaa"},'
                b'"title":"t","channelTitle":"T","publishedAt":"2026-01-01T00:00:00Z"}}]}'
            )

    monkeypatch.setattr(yti.urllib.request, "urlopen", lambda *a, **k: FakeResp())

    quota = yti.QuotaBudget(limit=2)  # channels.list(1) + one playlist page(1)
    videos = yti.list_channel_videos(UC_ID, max_results=50, quota=quota)

    assert pages_fetched["n"] == 1
    assert len(videos) == 1
    assert quota.spent == 2
    assert quota.exhausted is False

    # Another call should exhaust before channels.list
    videos2 = yti.list_channel_videos(UC_ID, max_results=50, quota=quota)
    assert videos2 == []
    assert quota.exhausted is True
    assert pages_fetched["n"] == 1  # no further HTTP


def test_search_channel_videos_respects_quota(api_key, monkeypatch):
    opened = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            opened["n"] += 1
            return b'{"items":[]}'

    monkeypatch.setattr(yti.urllib.request, "urlopen", lambda *a, **k: FakeResp())

    quota = yti.QuotaBudget(limit=50)  # less than COST_SEARCH_LIST
    out = yti.search_channel_videos("Foo", max_results=3, quota=quota)
    assert out == []
    assert opened["n"] == 0
    assert quota.exhausted is True


def test_ingest_all_channels_surfaces_quota_exhausted(api_key, monkeypatch):
    channels = [
        _db_row(channel_id=UC_ID, channel_name="A"),
        _db_row(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", channel_name="B"),
    ]

    state = {"phase": "list"}

    def get_conn():
        if state["phase"] == "list":
            state["phase"] = "fetch"
            return _fake_conn(fetchall_rows=channels)
        # fetch_channel_videos lookups + updates
        return _fake_conn(fetchone_row=channels[0])

    def fake_fetch(channel_id_or_name, max_videos=3, *, quota=None):
        if quota is not None and not quota.charge(2):
            return {
                "channel": channel_id_or_name,
                "channel_id": channel_id_or_name,
                "found": 0,
                "ingested": 0,
                "discovery": "skipped",
                "quota_exhausted": True,
                **quota.summary(),
            }
        return {
            "channel": channel_id_or_name,
            "channel_id": channel_id_or_name,
            "found": 1,
            "ingested": 1,
            "discovery": "uploads_playlist",
            "quota_exhausted": False,
            **(quota.summary() if quota else {}),
        }

    monkeypatch.setattr(yti, "_get_conn", get_conn)
    monkeypatch.setattr(yti, "fetch_channel_videos", fake_fetch)

    out = yti.ingest_all_channels(max_per_channel=1, quota_budget=2)
    assert out["quota_exhausted"] is True
    assert "quota_spent" in out
    assert "quota_budget" in out
    assert out["channels"] == 2
    assert out["channels_processed"] == 2  # first ok, second returns exhausted
    assert out["stopped_early"] is True

"""Stage 5 contract: directive add ≠ ranked /api/v2/watchlist membership.

Positive control: a create response shaped like Maria's S / directive #1278 failure
must carry on_ranked_watchlist=False and membership=directive_only when the ranked
probe misses — never claim watchlist membership from directive_id alone.

MBI_BEHAVIOR = 0. Offline / hermetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib.watchlist_membership_honesty import (  # noqa: E402
    RANKED_WATCHLIST_PATH,
    DIRECTIVES_PATH,
    build_directive_add_honesty,
    format_operator_copy,
    subject_identity_from_receipt,
    symbol_on_ranked_watchlist,
)
from lib.writers import watch_directives_writer as w  # noqa: E402


REQUIRED_HONESTY_KEYS = (
    "directive_id",
    "on_ranked_watchlist",
    "membership",
    "ranked_watchlist_path",
    "directives_path",
    "honesty",
    "policy",
    "subject_guid",
)


def test_directive_only_s_shaped_response_never_claims_ranked():
    """S / id=1278 class: directive real, ranked list omits symbol."""
    h = build_directive_add_honesty(
        directive_id=1278,
        kind="ticker",
        label="Watchlist",
        symbol="S",
        subject_guid="84601d7d-0000-0000-0000-000000000001",
        identity_source="registry",
        reused=False,
        serviced={"status": "STAGED_FOR_REVIEW"},
        on_ranked_watchlist=False,
    )
    for k in REQUIRED_HONESTY_KEYS:
        assert k in h, k
    assert h["on_ranked_watchlist"] is False
    assert h["membership"] == "directive_only"
    assert h["ranked_watchlist_path"] == RANKED_WATCHLIST_PATH
    assert h["directives_path"] == DIRECTIVES_PATH
    assert h["policy"] == "honest_split"
    assert "NOT on ranked" in h["honesty"]
    assert "1278" in h["honesty"]
    copy = format_operator_copy(h)
    assert "NOT on ranked" in copy
    assert "Added to watchlist" not in copy


def test_ranked_true_only_when_probed_true():
    h = build_directive_add_honesty(
        directive_id=99,
        kind="ticker",
        label="watch NVDA",
        symbol="NVDA",
        on_ranked_watchlist=True,
        ranked_via="watchlist_items",
    )
    assert h["membership"] == "ranked_watchlist"
    assert h["on_ranked_watchlist"] is True
    assert "also present on ranked" in h["honesty"]


def test_unknown_ranked_defaults_fail_closed_not_true():
    """on_ranked_watchlist=None must not become True."""
    h = build_directive_add_honesty(
        directive_id=1,
        kind="ticker",
        label="watch X",
        symbol="X",
        on_ranked_watchlist=None,
    )
    assert h["on_ranked_watchlist"] is False
    assert h["membership"] == "directive_only"


def test_symbol_on_ranked_watchlist_items_arm():
    def dbq(sql, params=None, fetch=None):
        assert "watchlist_items" in sql
        assert params == ("S",)
        return {"symbol": "S", "status": "active", "source": "operator_directive"}

    r = symbol_on_ranked_watchlist("S", db_query=dbq)
    assert r["on_ranked"] is True and r["via"] == "watchlist_items"


def test_symbol_on_ranked_watchlist_json_arm():
    r = symbol_on_ranked_watchlist("ANET", watchlist_json={"ANET": {"notes": "dc"}})
    assert r["on_ranked"] is True and r["via"] == "watchlist.json"


def test_symbol_missing_from_both_is_not_ranked():
    def dbq(sql, params=None, fetch=None):
        return None

    r = symbol_on_ranked_watchlist("S", db_query=dbq, watchlist_json={"NVDA": {}})
    assert r["on_ranked"] is False and r["via"] is None


def test_write_receipt_subject_identity_property(tmp_path, monkeypatch):
    """Writer stamps subject_guid onto receipt; API honesty reads it from there."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_iso.json"))
    from scripts.lib import identity_registry as ir

    ir._CACHE.clear()

    class Cur:
        def __init__(self):
            self._n = 900
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchone(self):
            sql, _ = self.sql[-1]
            if "RETURNING id" in sql:
                self._n += 1
                return {"id": self._n}
            return None

        def fetchall(self):
            return []

    cur = Cur()
    rc = w.write_watch_directives(
        cur,
        [{"kind": "ticker", "label": "watch RKLB", "spec": {"symbol": "RKLB"}, "created_by": "test"}],
        source="test",
        on_duplicate="insert",
    )
    assert rc.directive_id == 901
    ident = rc.subject_identity
    assert "subject_guid" in ident
    # Either registry/spine resolved a GUID, or honest None — never invent one.
    if ident["subject_guid"] is not None:
        assert isinstance(ident["subject_guid"], str) and len(ident["subject_guid"]) >= 8
        assert ident["identity_source"] in ("registry", "spine")
    from_helper = subject_identity_from_receipt(rc)
    assert from_helper.get("subject_guid") == ident.get("subject_guid")


def test_api_create_response_contract_directive_only(monkeypatch):
    """_watch_directive_create must expose Stage 5 fields; S-shaped miss stays directive_only."""
    import api_v2

    class Cur:
        def __init__(self):
            self._n = 1277
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchone(self):
            sql = self.sql[-1][0] if self.sql else ""
            if "RETURNING id" in sql and sql.lstrip().upper().startswith("INSERT"):
                self._n += 1
                return {"id": self._n}
            if "FROM watchlist_items" in sql:
                return None  # ranked miss — the S failure shape
            if "SELECT id FROM watch_directives" in sql:
                return None
            return None

        def fetchall(self):
            return []

    cur = Cur()

    def ex(sql, params=None, fetch=None):
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "none":
            return True
        return cur.fetchall()

    monkeypatch.setattr(api_v2, "_db_query", ex, raising=True)

    import directive_promotion as dp

    monkeypatch.setattr(
        dp,
        "promote_directive_lead",
        lambda *a, **k: {"status": "STAGED_FOR_REVIEW", "registered": False},
        raising=False,
    )

    monkeypatch.setattr(
        w,
        "resolve_directive_subject",
        lambda kind, spec: {
            "subject_guid": "84601d7d-test-sentinelone",
            "identity_source": "registry",
            "symbol": "S",
        },
        raising=True,
    )

    code, out = api_v2._watch_directive_create(
        {
            "kind": "ticker",
            "label": "Watchlist",
            "spec": {"symbol": "S"},
            "rationale": "parity Stage 5 positive control",
            "created_by": "test",
        }
    )
    assert code == 200 and out["ok"] is True
    assert out["directive_id"] == 1278
    assert out["on_ranked_watchlist"] is False
    assert out["membership"] == "directive_only"
    assert out["ranked_watchlist_path"] == "/api/v2/watchlist"
    assert out["subject_guid"] == "84601d7d-test-sentinelone"
    assert "NOT on ranked" in out["honesty"]
    assert out["watchlist_honesty"]["policy"] == "honest_split"
    assert "Added to watchlist" not in (out.get("honesty") or "")


def test_api_create_claims_ranked_only_when_items_row_exists(monkeypatch):
    import api_v2

    class Cur:
        def __init__(self):
            self._n = 50
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchone(self):
            sql = self.sql[-1][0] if self.sql else ""
            if "RETURNING id" in sql and sql.lstrip().upper().startswith("INSERT"):
                self._n += 1
                return {"id": self._n}
            if "FROM watchlist_items" in sql:
                return {"symbol": "NVDA", "status": "active", "source": "operator_directive"}
            if "SELECT id FROM watch_directives" in sql:
                return None
            return None

        def fetchall(self):
            return []

    cur = Cur()

    def ex(sql, params=None, fetch=None):
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "none":
            return True
        return cur.fetchall()

    monkeypatch.setattr(api_v2, "_db_query", ex, raising=True)
    import directive_promotion as dp

    monkeypatch.setattr(
        dp,
        "promote_directive_lead",
        lambda *a, **k: {"status": "PROMOTED", "registered": True},
        raising=False,
    )
    monkeypatch.setattr(
        w,
        "resolve_directive_subject",
        lambda kind, spec: {
            "subject_guid": "guid-nvda",
            "identity_source": "spine",
            "symbol": "NVDA",
        },
        raising=True,
    )

    code, out = api_v2._watch_directive_create(
        {
            "kind": "ticker",
            "label": "watch NVDA",
            "spec": {"symbol": "NVDA"},
            "created_by": "test",
        }
    )
    assert code == 200
    assert out["on_ranked_watchlist"] is True
    assert out["membership"] == "ranked_watchlist"
    assert out["subject_guid"] == "guid-nvda"

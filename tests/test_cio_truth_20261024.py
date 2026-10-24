"""W1 read-only CIO truth: strict identity, consistent facts and visible gaps."""
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)


def test_stance_is_guid_bound_and_preserves_lower_level_conflicts():
    doc = {"source": {"kind": "store"}, "prospects": [
        {"security_guid": "guid-spcx", "symbol": "SPCX", "stance": "ADD", "conviction": 73.3,
         "revision": 2, "as_of": NOW.isoformat(), "stale": False,
         "conflicts": [{"source": "decision_engine", "stance": "TRIM"}]},
        {"security_guid": "other-guid", "symbol": "SPCX", "stance": "SELL", "conviction": 10},
    ]}
    result = truth.stance_for("guid-spcx", projection=doc, now=NOW)
    assert (result["stance"], result["conviction"]) == ("ADD", 73.3)
    assert result["conflicts"] == [{"source": "decision_engine", "stance": "TRIM"}]
    result["conflicts"].clear()
    assert len(doc["prospects"][0]["conflicts"]) == 1
    missing = truth.stance_for("SPCX", projection=doc, now=NOW)
    assert missing["stance"] is None and missing["gap"]


def test_stance_uses_latest_version_and_keeps_expiry():
    doc = {"prospects": [
        {"security_guid": "g", "stance": "ADD", "conviction": 80, "revision": 1, "as_of": "2026-10-22"},
        {"security_guid": "g", "stance": "HOLD", "conviction": 60, "revision": 2, "as_of": "2026-10-23", "stale": True},
    ]}
    result = truth.stance_for("g", projection=doc, now=NOW)
    assert result["stance"] == "HOLD" and result["stale"] is True


def test_empty_guid_never_reads_a_store(monkeypatch):
    from scripts.lib.data_broker import cio_prospect
    monkeypatch.setattr(cio_prospect, "get_prospects", lambda **kw: (_ for _ in ()).throw(AssertionError("read")))
    assert truth.stance_for("", now=NOW)["gap"]

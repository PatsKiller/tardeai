"""Quote timestamp normalization + after-hours session policy (PR #33).

The ' ET' / space-separated shapes broke datetime.fromisoformat() ("Invalid isoformat string") in the
protective-stop quote gate. These tests pin the shared normalizer, the session classification, and that an
unparseable quote blocks with a human message (never a raw isoformat error), and that the first live canary
is restricted to a regular session.
"""
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brokers.quote_time import parse_quote_ts, classify_session, to_iso, quote_age_seconds  # noqa: E402

UI = ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx"
API = ROOT / "scripts/api_v2.py"
PF = ROOT / "scripts/protective_stop_2fa_preflight.py"


def test_01_parse_et_suffix_as_eastern():
    dt_v = parse_quote_ts("2026-06-30 16:15:02 ET")
    assert dt_v is not None and dt_v.tzinfo is not None
    # June -> EDT (-04:00), regardless of the literal EDT/EST text
    assert dt_v.utcoffset() == dt.timedelta(hours=-4)
    assert to_iso("2026-06-30 16:15:02 ET") == "2026-06-30T16:15:02-04:00"


def test_02_parse_iso_with_offset():
    dt_v = parse_quote_ts("2026-06-30T15:30:03-04:00")
    assert dt_v is not None and dt_v.utcoffset() == dt.timedelta(hours=-4)


def test_03_parse_z_timestamp():
    dt_v = parse_quote_ts("2026-06-30T19:30:03Z")
    assert dt_v is not None and dt_v.utcoffset() == dt.timedelta(0)
    assert classify_session("2026-06-30T19:30:03Z") == "regular"   # 19:30Z == 15:30 ET


def test_04_parse_space_separated_local_as_eastern():
    dt_v = parse_quote_ts("2026-06-30 15:30:03")
    assert dt_v is not None and dt_v.utcoffset() == dt.timedelta(hours=-4)
    assert classify_session("2026-06-30 15:30:03") == "regular"


def test_05_invalid_returns_none_never_raises():
    for bad in ("garbage", "", None, "2026-13-99 99:99 ET"):
        assert parse_quote_ts(bad) is None
        assert classify_session(bad) == "unknown"
        assert to_iso(bad) is None


def test_06_session_boundaries():
    assert classify_session("2026-06-30 09:31:00 ET") == "regular"
    assert classify_session("2026-06-30 15:59:00 ET") == "regular"
    assert classify_session("2026-06-30 16:15:02 ET") == "after_hours"
    assert classify_session("2026-06-30 08:00:00 ET") == "pre_market"
    assert classify_session("2026-06-30 21:00:00 ET") == "closed"
    assert classify_session("2026-07-04 11:00:00 ET") == "closed"  # Saturday


def test_07_api_gate_uses_normalizer_not_bare_fromisoformat():
    api = API.read_text(encoding="utf-8")
    # the protective-stop quote gate must route through the shared normalizer
    assert "from brokers.quote_time import parse_quote_ts" in api
    assert "Quote timestamp could not be parsed" in api
    # and must NOT raw-parse the quote_at with fromisoformat anymore
    assert "_dt.datetime.fromisoformat(raw_ts)" not in api


def test_08_after_hours_policy_present_and_default_off():
    api = API.read_text(encoding="utf-8")
    assert "after_hours_blocked" in api
    assert "_after_hours_stop_override" in api
    assert "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION" in api
    # override requires BOTH a policy flag AND an operator ack — never silent
    fn = api.split("def _after_hours_stop_override")[1].split("\ndef ")[0]
    assert "SCHWAB_AFTER_HOURS_STOP_OVERRIDE" in fn and "after_hours_ack" in fn
    assert "policy_on and operator_ack" in fn


def test_09_override_helper_default_blocks(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import api_v2
    monkeypatch.delenv("SCHWAB_AFTER_HOURS_STOP_OVERRIDE", raising=False)
    assert api_v2._after_hours_stop_override({"after_hours_ack": True}) is False   # no policy flag
    monkeypatch.setenv("SCHWAB_AFTER_HOURS_STOP_OVERRIDE", "1")
    assert api_v2._after_hours_stop_override({}) is False                          # no ack
    assert api_v2._after_hours_stop_override({"after_hours_ack": True}) is True    # both -> allowed


def test_10_ui_shows_session_and_no_raw_parse_error():
    src = UI.read_text(encoding="utf-8")
    assert "Session" in src and "Quote raw / normalized" in src
    assert "quote_session" in src and "quote_normalized" in src
    assert "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION" in src
    assert "Quote timestamp could not be parsed" in src
    assert "After-hours quote detected" in src
    # never surface the python parse error to the operator
    assert "Invalid isoformat string" not in src


def test_11_preflight_classifies_quote_and_fails_on_unparseable():
    pf = PF.read_text(encoding="utf-8")
    assert "from brokers.quote_time import parse_quote_ts" in pf
    assert "quote_freshness_class" in pf and "operator_readiness" in pf
    assert "after_hours_blocked" in pf and "regular_session_fresh" in pf
    assert "Quote timestamp could not be parsed" in pf


def test_12_no_broker_write_in_normalizer_or_preflight_quote_path():
    # the normalizer is pure
    qt = (ROOT / "scripts/brokers/quote_time.py").read_text(encoding="utf-8")
    for bad in ("place_order", "submit_order", "schwab_transport", "requests.", "urlopen"):
        assert bad not in qt, f"quote_time.py must be pure — found {bad!r}"
    # the preflight never submits a broker order (it reports broker_submitted=False)
    pf = PF.read_text(encoding="utf-8")
    assert '"broker_submitted": False' in pf
    for bad in ("place_order(", "schwab_transport", ".submit_order("):
        assert bad not in pf, f"preflight must not place orders — found {bad!r}"

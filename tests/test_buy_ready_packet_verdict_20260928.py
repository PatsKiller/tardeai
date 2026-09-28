"""Failed acceptance test 2026-09-28 (release 490735fba, rolled back to d3bfc9ca0): the Entry
alerts index served AXTI as OPTIONS_ALT_OK / qualified_count 1 from a packet saved at 14:20Z,
before the earnings-gate fix, because it counted the file's own ``qualified: true``.

Repair contract, valid in the COMBINED code whatever the merge order:
- the index routes every packet through lib.buy_ready_options_alternatives.packet_view (live-proof
  branch) when that build has it; a stored verdict without the current gate_version is
  STALE_PRE_FIX with qualified_count 0;
- when packet_view is absent the index fails closed to PACKET_UNVERIFIED, qualified_count 0;
- even a view that says OK counts a unit only if it is a known strategy, carries an earnings
  verdict object with in_blackout exactly False, and that verdict is gate-stamped;
- the raw claim is preserved under ``claimed`` for audit; ``desk`` stays a separate field;
- the single-symbol API handler is the live-proof hunk (never the file verbatim).
Hermetic: the served AXTI packet as a fixture, a fake packet_view that mirrors the real one's shape."""
from __future__ import annotations

import json
import sys
import types
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import buy_ready_packets_index as bri  # noqa: E402

NOW = datetime(2026, 9, 28, 20, 35, tzinfo=timezone.utc)
AXTI = json.loads((ROOT / "tests" / "fixtures" / "axti_buy_ready_packet_20260928T1420Z_served.json").read_text())
GATE = "2026-09-28"


def _fake_packet_view(*, current_gate: str = GATE):
    """Mirror of the live-proof packet_view: stale when gate_version missing/mismatched, else OK."""
    def packet_view(packet, *, now=None, **kw):
        view = deepcopy(packet)
        alts = view.get("options_alternatives") or {}
        gv = alts.get("gate_version")
        stale = None
        if not gv:
            stale = {"code": "STALE_PRE_FIX", "reason": "no gate_version on the stored verdicts (computed before the 2026-09-28 earnings-gate fix)"}
        elif gv != current_gate:
            stale = {"code": "STALE_PRE_FIX", "reason": f"stored gate_version {gv} != running {current_gate}"}
        if stale:
            original = {"status": alts.get("status"), "qualified": [a.get("strategy") for a in alts.get("alternatives") or [] if a.get("qualified")]}
            for a in alts.get("alternatives") or []:
                a["qualified"] = False
                a["disqualified_by"] = [f"{stale['code']} ({stale['reason']})"] + list(a.get("disqualified_by") or [])
            alts["status"] = stale["code"]; alts["superseded"] = True; alts["stale"] = stale; alts["original"] = original
        return {"status": stale["code"] if stale else "OK", "saved_at": view.get("saved_at"), "generated_at": alts.get("generated_at"),
                "as_of": alts.get("chain_as_of"), "gate_version": gv, "stale": stale, "packet": view}
    return packet_view


def _install_view(monkeypatch, fn):
    mod = types.ModuleType("lib.buy_ready_options_alternatives")
    mod.packet_view = fn
    monkeypatch.setitem(sys.modules, "lib.buy_ready_options_alternatives", mod)
    monkeypatch.setitem(sys.modules, "scripts.lib.buy_ready_options_alternatives", mod)


def _remove_view(monkeypatch):
    for name in ("lib.buy_ready_options_alternatives", "scripts.lib.buy_ready_options_alternatives"):
        monkeypatch.setitem(sys.modules, name, None)   # import raises ImportError


def _stamped_current(packet, *, strategy="debit_call_vertical", in_blackout=False, gate=GATE):
    p = deepcopy(packet)
    alts = p["options_alternatives"]
    alts["gate_version"] = gate; alts["generated_at"] = "2026-09-28T20:30:00+00:00"
    alts["alternatives"] = [{"strategy": strategy, "qualified": True, "rank": 1,
                             "earnings": {"in_blackout": in_blackout, "symbol": "AXTI", "strategy": strategy, "gate_version": gate}}]
    alts["status"] = "OK"; p["options_alt"] = {"status": "OPTIONS_ALT_OK", "strategy": strategy}
    return p


def test_the_exact_served_axti_packet_is_stale_pre_fix_with_zero_qualified(monkeypatch):
    _install_view(monkeypatch, _fake_packet_view())
    assert AXTI["saved_at"].startswith("2026-09-28T14:20") and "gate_version" not in json.dumps(AXTI)
    v = bri.options_verdict(AXTI, now=NOW)
    assert v["status"] == "STALE_PRE_FIX" and v["qualified_count"] == 0 and v["qualified"] == []
    assert v["claimed"] == {"status": "OPTIONS_ALT_OK", "qualified": ["debit_call_vertical"]}   # audit trail of the file's claim
    assert "before the 2026-09-28 earnings-gate fix" in v["reason"] and v["gate_version"] is None
    row = bri.index_packet(AXTI, proposals=[], dropped=[{"symbol": "AXTI", "reason": "EDGE_BELOW"}], now=NOW)
    assert row["options_alt"]["status"] == "STALE_PRE_FIX" and row["options_alt"]["qualified_count"] == 0
    assert row["desk"] == {"status": "not_built", "reason": "EDGE_BELOW", "entry_state": None, "detail": {}}  # kept distinct


def test_without_packet_view_the_index_fails_closed_to_unverified(monkeypatch):
    _remove_view(monkeypatch)
    v = bri.options_verdict(AXTI, now=NOW)
    assert v["status"] == "PACKET_UNVERIFIED" and v["qualified_count"] == 0 and v["considered"] == 4
    assert v["claimed"]["qualified"] == ["debit_call_vertical"]


def test_unstamped_clear_verdict_is_stale_even_when_it_says_qualified(monkeypatch):
    _install_view(monkeypatch, _fake_packet_view())
    p = _stamped_current(AXTI); p["options_alternatives"].pop("gate_version")
    p["options_alternatives"]["alternatives"][0]["earnings"].pop("gate_version")
    v = bri.options_verdict(p, now=NOW)
    assert v["status"] == "STALE_PRE_FIX" and v["qualified_count"] == 0


def test_stale_blocked_verdict_stays_zero_and_keeps_its_claim(monkeypatch):
    _install_view(monkeypatch, _fake_packet_view())
    p = _stamped_current(AXTI, in_blackout=True, gate="2026-09-20")
    p["options_alternatives"]["alternatives"][0]["qualified"] = False
    v = bri.options_verdict(p, now=NOW)
    assert v["status"] == "STALE_PRE_FIX" and v["qualified_count"] == 0 and "2026-09-20" in v["reason"]
    assert v["claimed"]["qualified"] == []


def test_unknown_strategy_or_missing_event_verdict_never_counts(monkeypatch):
    _install_view(monkeypatch, _fake_packet_view())
    unknown = _stamped_current(AXTI, strategy="mystery_spread")
    v = bri.options_verdict(unknown, now=NOW)
    assert v["status"] == "NONE_QUALIFIED" and v["qualified_count"] == 0
    no_event = _stamped_current(AXTI); no_event["options_alternatives"]["alternatives"][0].pop("earnings")
    assert bri.options_verdict(no_event, now=NOW)["qualified_count"] == 0
    none_event = _stamped_current(AXTI); none_event["options_alternatives"]["alternatives"][0]["earnings"]["in_blackout"] = None
    assert bri.options_verdict(none_event, now=NOW)["qualified_count"] == 0
    blocked = _stamped_current(AXTI, in_blackout=True)
    assert bri.options_verdict(blocked, now=NOW)["qualified_count"] == 0


def test_a_genuinely_current_passing_verdict_is_ok_with_one_qualified(monkeypatch):
    _install_view(monkeypatch, _fake_packet_view())
    v = bri.options_verdict(_stamped_current(AXTI), now=NOW)
    assert v["status"] == "OPTIONS_ALT_OK" and v["qualified_count"] == 1 and v["qualified"] == ["debit_call_vertical"]
    assert v["gate_version"] == GATE and v["evaluated_at"] == "2026-09-28T20:30:00+00:00" and v["stale"] is None


def test_index_rows_carry_the_verdict_not_the_claim(monkeypatch, tmp_path):
    _install_view(monkeypatch, _fake_packet_view())
    d = tmp_path / "pk"; d.mkdir()
    (d / "AXTI.json").write_text(json.dumps(AXTI))
    (d / "GOOD.json").write_text(json.dumps({**_stamped_current(AXTI), "symbol": "GOOD", "saved_at": AXTI["saved_at"]}))
    out = bri.index_packets(d, now=NOW)
    assert out["schema"] == "BuyReadyPacketIndex@v2"
    by = {r["symbol"]: r["options_alt"] for r in out["rows"]}
    assert by["AXTI"]["status"] == "STALE_PRE_FIX" and by["AXTI"]["qualified_count"] == 0
    assert by["GOOD"]["status"] == "OPTIONS_ALT_OK" and by["GOOD"]["qualified_count"] == 1
    cio = {r["symbol"]: r["cio_verdict"] for r in out["rows"]}
    assert cio["AXTI"]["token"] == AXTI["cio_verdict"]["token"] and cio["AXTI"]["verdict"] == AXTI["cio_verdict"]["verdict"]  # CIO block untouched by the options verdict


def test_single_symbol_api_handler_is_the_live_proof_hunk():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    body = src[src.index("def _buy_ready_packet("):]
    body = body[:body.index("\ndef ", 10)]
    assert "packet_view(packet)" in body and '"PACKET_UNVERIFIED"' in body
    assert '"status": "OK", "saved_at": packet.get("saved_at"), "packet": packet' not in body   # never verbatim


@pytest.mark.parametrize("path", ["tests/fixtures/axti_buy_ready_packet_20260928T1420Z_served.json"])
def test_fixture_is_the_incident_packet(path):
    p = json.loads((ROOT / path).read_text())
    assert p["symbol"] == "AXTI" and p["options_alt"]["status"] == "OPTIONS_ALT_OK"
    assert [a["strategy"] for a in p["options_alternatives"]["alternatives"] if a["qualified"]] == ["debit_call_vertical"]

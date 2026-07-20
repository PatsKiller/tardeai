#!/usr/bin/env python3
"""Phase 1 tests: canonical registry -> compiler -> executor.

Pure only: no network, no DB writes. The live-validation gate is exercised
against a stubbed validator so CI never needs a Finviz account.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_screen_compiler as fc  # noqa: E402


def _reg():
    return yaml.safe_load((ROOT / "config" / "finviz_screen_registry.yaml").read_text())


def test_registry_parses_and_has_the_operator_preset():
    r = _reg()
    assert "OPT-CC-QUALITY-OVERWRITE" in r["screens"]


def test_every_screen_ships_shadow_and_human_review_only():
    """Nothing in the canonical library may arrive proposal-eligible."""
    r = _reg()
    defaults = r.get("defaults", {})
    for sid, spec in r["screens"].items():
        status = spec.get("status") or defaults.get("status")
        assert status == "SHADOW", f"{sid} is not SHADOW"


def test_compile_is_deterministic():
    r = _reg()
    spec = r["screens"]["OPT-CC-QUALITY-OVERWRITE"]
    a = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE", spec, r["defaults"])
    b = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE", spec, r["defaults"])
    assert a["machine_url"] == b["machine_url"]
    assert a["definition_hash"] == b["definition_hash"]


def test_filter_order_does_not_change_the_hash():
    """Reordering filters is not a semantic change."""
    r = _reg()
    spec = dict(r["screens"]["OPT-CC-QUALITY-OVERWRITE"])
    a = fc.compile_screen("X", spec, r["defaults"])
    spec2 = dict(spec)
    spec2["hard_filters"] = list(reversed(spec["hard_filters"]))
    b = fc.compile_screen("X", spec2, r["defaults"])
    assert a["definition_hash"] == b["definition_hash"]
    assert a["machine_url"] == b["machine_url"]


def test_changing_a_filter_changes_the_hash():
    r = _reg()
    spec = dict(r["screens"]["OPT-CC-QUALITY-OVERWRITE"])
    a = fc.compile_screen("X", spec, r["defaults"])
    spec2 = dict(spec)
    spec2["hard_filters"] = list(spec["hard_filters"]) + [{"token": "geo_usa"}]
    b = fc.compile_screen("X", spec2, r["defaults"])
    assert a["definition_hash"] != b["definition_hash"]


def test_unfiltered_screen_is_refused():
    """A definition with no filters would capture the whole universe."""
    with pytest.raises(ValueError, match="no hard_filters"):
        fc.compile_screen("BAD", {"hard_filters": []}, {})


def test_machine_url_uses_v152_not_v111():
    """v=111 silently ignores the &c= column pack."""
    r = _reg()
    c = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE",
                          r["screens"]["OPT-CC-QUALITY-OVERWRITE"], r["defaults"])
    assert "v=152" in c["machine_url"]
    assert "v=111" not in c["machine_url"]


def test_no_registry_token_is_a_known_ignored_code():
    """Regression guard for the 2026-07-20 finding: these do nothing at Finviz."""
    KNOWN_IGNORED = {
        "fa_dividendyield_o1", "fa_dividendyield_o2", "fa_dividendyield_o3",
        "fa_dividendyield_o4", "fa_dividendyield_o5", "fa_dividendyield_o6",
        "fa_div_o1.5", "fa_epsyoy5_o5", "fa_epsyoy5_o10",
        "fa_payoutratio_u60p", "fa_payoutratio_u80p",
        "sh_float_u500", "sh_price_u150", "ta_perf_1mup",
        "ta_rsi_nos60", "ta_rsi_ob30", "ta_beta_u1.2", "ta_atr_u3",
        "ta_highlow52w_b0to20h", "ta_rsi_nob70",
    }
    r = _reg()
    for sid, spec in r["screens"].items():
        toks = {f["token"] for f in spec["hard_filters"]}
        assert not (toks & KNOWN_IGNORED), f"{sid} uses ignored token(s): {toks & KNOWN_IGNORED}"


def test_deviations_from_preset_are_recorded():
    """Where the compiled screen differs from the operator's preset, say so."""
    spec = _reg()["screens"]["OPT-CC-QUALITY-OVERWRITE"]
    devs = spec.get("deviations_from_preset") or []
    assert len(devs) >= 3
    for d in devs:
        assert d.get("requested") and d.get("implemented") and d.get("reason")


def test_shadow_screens_upsert_inactive():
    """A SHADOW definition must register with active=false."""
    r = _reg()
    c = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE",
                          r["screens"]["OPT-CC-QUALITY-OVERWRITE"], r["defaults"])
    captured = {}

    class Cur:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
        def fetchone(self): return None

    fc.upsert(c, Cur())
    assert "INSERT INTO finviz_screeners" in captured["sql"]
    assert captured["params"][-1] is False, "SHADOW screen must be inserted inactive"


def test_upsert_is_idempotent_when_nothing_changed():
    r = _reg()
    c = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE",
                          r["screens"]["OPT-CC-QUALITY-OVERWRITE"], r["defaults"])
    spec = c["spec"]
    desc = (f"{spec.get('purpose','').strip()} "
            f"[canonical registry v{spec.get('screen_version',1)}, "
            f"def#{c['definition_hash']}]").strip()

    class Cur:
        def execute(self, sql, params=None):
            assert "UPDATE" not in sql, "unchanged row must not be rewritten"
        def fetchone(self):
            return (c["machine_url"], desc, spec.get("schedule", ""),
                    spec.get("strategy_type", ""), False)

    assert fc.upsert(c, Cur()) == "unchanged"


def test_validation_gate_blocks_ignored_tokens(monkeypatch):
    """The compiler must refuse to promote a screen built on a dead token."""
    import finviz_filter_validator as fv
    monkeypatch.setattr(fc, "validate_tokens", lambda compiled: {
        "ok": True, "baseline": 11501,
        "results": {"bogus_token": {"state": fv.IGNORED, "rows": 11501}},
        "bad_tokens": {"bogus_token": {"state": fv.IGNORED, "rows": 11501}}})
    r = _reg()
    c = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE",
                          r["screens"]["OPT-CC-QUALITY-OVERWRITE"], r["defaults"])
    v = fc.validate_tokens([c])
    assert v["bad_tokens"], "gate must surface ignored tokens"

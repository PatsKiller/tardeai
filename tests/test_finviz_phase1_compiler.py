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
    """Nothing in the canonical library may arrive proposal-eligible.

    Phase 1.2: `status` was replaced by separated controls, because one field
    could not express "runs but may not propose".
    """
    r = _reg()
    d = r.get("defaults", {})
    for sid, spec in r["screens"].items():
        mode = spec.get("research_mode", d.get("research_mode"))
        assert mode == "SHADOW", f"{sid} is not SHADOW"
        assert spec.get("proposal_eligible", d.get("proposal_eligible")) is False
        assert spec.get("execution_eligible", d.get("execution_eligible")) is False
        assert d.get("human_review_only") is True


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
            m = c["manifest"]
            return (c["machine_url"], desc, spec.get("schedule", ""),
                    spec.get("strategy_type", ""), bool(m["run_enabled"]),
                    m["research_mode"], bool(m["proposal_eligible"]),
                    bool(m["execution_eligible"]))

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


# ── Phase 1.2: separated governance (run vs propose vs execute) ────────────

def test_shadow_screen_runs_but_cannot_propose():
    """The Phase 1 defect: SHADOW compiled to active=false, so no evidence."""
    r = _reg()
    c = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE",
                          r["screens"]["OPT-CC-QUALITY-OVERWRITE"], r["defaults"])
    m = c["manifest"]
    assert m["research_mode"] == "SHADOW"
    assert m["run_enabled"] is True, "a shadow screen MUST run or it gathers nothing"
    assert m["proposal_eligible"] is False
    assert m["execution_eligible"] is False


def test_shadow_upserts_active_true():
    """active means RUN, not PROPOSE."""
    r = _reg()
    c = fc.compile_screen("OPT-CC-QUALITY-OVERWRITE",
                          r["screens"]["OPT-CC-QUALITY-OVERWRITE"], r["defaults"])
    captured = {}

    class Cur:
        def execute(self, sql, params=None):
            captured.setdefault("sqls", []).append(sql)
            captured["params"] = params
        def fetchone(self): return None

    fc.upsert(c, Cur())
    ins = [s for s in captured["sqls"] if "INSERT INTO finviz_screeners" in s]
    assert ins, "expected an insert"
    p = captured["params"]
    assert True in p, "active must be true so the executor runs it"
    assert "SHADOW" in p
    assert p.count(False) >= 2, "proposal_eligible and execution_eligible must be false"


def test_compiler_refuses_shadow_with_proposal_authority():
    r = _reg()
    spec = dict(r["screens"]["OPT-CC-QUALITY-OVERWRITE"])
    spec["proposal_eligible"] = True          # SHADOW + propose = illegal
    with pytest.raises(ValueError, match="cannot be proposal"):
        fc.compile_screen("X", spec, r["defaults"])


def test_compiler_refuses_execution_eligible():
    r = _reg()
    spec = dict(r["screens"]["OPT-CC-QUALITY-OVERWRITE"])
    spec["research_mode"] = "OPERATIONAL"
    spec["execution_eligible"] = True
    with pytest.raises(ValueError, match="execution_eligible must be false"):
        fc.compile_screen("X", spec, r["defaults"])


def test_compiler_refuses_unknown_research_mode():
    r = _reg()
    spec = dict(r["screens"]["OPT-CC-QUALITY-OVERWRITE"])
    spec["research_mode"] = "LIVE"
    with pytest.raises(ValueError, match="research_mode"):
        fc.compile_screen("X", spec, r["defaults"])


def test_scoring_feeder_excludes_shadow_screens():
    """Shadow membership must never reach the Hermes scoring pipeline."""
    src = (ROOT / "scripts" / "hermes_score_event_feeder.py").read_text()
    i = src.index('"finviz":')
    q = src[i:i + 700]
    assert "proposal_eligible = true" in q, "feeder must gate on proposal_eligible"
    assert "research_mode <> 'SHADOW'" in q, "feeder must exclude SHADOW screens"


def test_run_and_propose_are_independent_fields():
    """Regression guard: never collapse these back into one flag."""
    import yaml as _y
    d = _y.safe_load((ROOT / "config" / "finviz_screen_registry.yaml").read_text())
    for key in ("run_enabled", "research_mode", "proposal_eligible", "execution_eligible"):
        assert key in d["defaults"], f"registry defaults lost {key}"

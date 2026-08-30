"""Wave 3B — schema, deterministic join, notification policy, and the four pins.

The pins are the point of this file. Wave 3B builds the machinery that *would*
notify, and the whole value of that is worthless if the machinery quietly turns
itself on. Every pin gets a test that fails loudly.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_notification_policy as policy
from scripts.lib.cio_council_synthesis import (
    AGREED, DISPUTED, NO_INPUT, SINGLE, render_lines, synthesize,
)
from scripts.lib.cio_specialist_artifact import (
    OUTCOMES, PROVIDERS, append, build, load, total_cost, validate,
)

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

WAVE3B_MODULES = [
    "scripts/lib/cio_specialist_artifact.py",
    "scripts/lib/cio_council_synthesis.py",
    "scripts/lib/cio_notification_policy.py",
]


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


# =============================================================== THE FOUR PINS

def test_pin_no_new_telegram_call_site():
    """PIN: no new Telegram/WhatsApp producer, no send() call sites."""
    offenders = []
    for rel in WAVE3B_MODULES:
        code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", _src(rel)))
        for bad in ("send_cio_message", "sendMessage", "api.telegram.org",
                    "RealTelegramAdapter", "whatsapp", "cio_telegram_transport"):
            if bad in code:
                offenders.append(f"{rel}:{bad}")
    assert not offenders, offenders


def test_pin_policy_never_flips_the_notify_env():
    """PIN: CIO_SITUATION_NOTIFY stays 0/unset; CIO_TELEGRAM_INTERDICT stays on."""
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     _src("scripts/lib/cio_notification_policy.py")))
    assert "os.environ[" not in code, "policy must never assign an env var"
    assert "setenv" not in code and "putenv" not in code
    # reading them is expected; writing them is not
    assert "environ.get" in code


def test_pin_mbi_is_not_read_to_size_or_act():
    """PIN: MBI ceiling 0 — never read to size or act."""
    for rel in WAVE3B_MODULES:
        code = _src(rel)
        assert "memory_behavior_influence" not in code, rel
        assert "MBI" not in code, rel


def test_pin_rotate_is_not_an_executable_action_enum():
    """PIN: ROTATE stays advisory text / option_id, not a worker action."""
    for rel in WAVE3B_MODULES:
        code = _src(rel)
        assert "ROTATE" not in code, rel


def test_pin_council_calls_no_model_and_mints_no_plan():
    """PIN: council does not call a model and does not mint/attach plans."""
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     _src("scripts/lib/cio_council_synthesis.py")))
    for bad in ("build_product", "hermes", "openai", "anthropic", "requests",
                "urllib", "httpx", "backend"):
        assert bad not in code.lower(), bad
    block = synthesize(artifacts=[], symbol="SCHD")
    assert block["model_called"] is False
    assert block["mints_plan"] is False
    assert block["attaches_plan"] is False


def test_pin_specialist_artifact_makes_no_http_call():
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     _src("scripts/lib/cio_specialist_artifact.py")))
    for bad in ("requests", "urllib", "httpx", "socket", "http"):
        assert bad not in code.lower(), bad


# ========================================================= SpecialistArtifact

def test_artifact_schema_and_validation():
    a = build(artifact_id="a1", provider="stub", outcome="VALID",
              plan_id="p1", workflow_id="wf_wave3b")
    assert a["schema"] == "SpecialistArtifact@v1-lite"
    assert a["workflow_id"] == "wf_wave3b"
    assert validate(a) == []
    assert a["financial_action"] is False


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_declared_provider_builds(provider):
    cost = 0.0 if provider == "stub" else 0.01
    a = build(artifact_id="x", provider=provider, outcome="VALID",
              cost_usd=cost, workflow_id="wf_wave3b")
    assert validate(a) == []


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_declared_outcome_builds(outcome):
    assert validate(build(artifact_id="x", provider="stub",
                          outcome=outcome, workflow_id="wf_wave3b")) == []


def test_unknown_provider_raises_rather_than_coercing():
    """A silently normalised provider would make a paid call look free."""
    with pytest.raises(ValueError):
        build(artifact_id="x", provider="gemini", outcome="VALID",
              workflow_id="wf_wave3b")


def test_a_stub_artifact_must_be_free():
    with pytest.raises(ValueError):
        build(artifact_id="x", provider="stub", outcome="VALID", cost_usd=1.0,
              workflow_id="wf_wave3b")


def test_negative_cost_rejected():
    with pytest.raises(ValueError):
        build(artifact_id="x", provider="flash", outcome="VALID", cost_usd=-1,
              workflow_id="wf_wave3b")


def test_append_and_load_roundtrip(tmp_path):
    a = build(artifact_id="a1", provider="stub", outcome="VALID",
              workflow_id="wf_wave3b")
    assert append(tmp_path, a)["wrote"] is True
    rows = load(tmp_path)
    assert len(rows) == 1 and rows[0]["artifact_id"] == "a1"
    assert rows[0]["workflow_id"] == "wf_wave3b"
    assert total_cost(rows) == 0.0


def test_invalid_row_is_not_written(tmp_path):
    bad = build(artifact_id="a1", provider="stub", outcome="VALID",
                workflow_id="wf_wave3b")
    bad["provider"] = "gemini"
    assert append(tmp_path, bad)["wrote"] is False
    assert load(tmp_path) == []


# ================================================================== council

def _art(i, outcome, position=None, cost=0.0):
    return {"artifact_id": i, "outcome": outcome, "position": position,
            "cost_usd": cost, "source_refs": []}


def test_disagreement_is_labelled_not_resolved():
    b = synthesize(artifacts=[_art("a", "VALID", "BULLISH"),
                              _art("b", "VALID", "BEARISH")], symbol="SCHD")
    assert b["state"] == DISPUTED
    assert set(b["positions"]) == {"BULLISH", "BEARISH"}
    assert "no winner" in b["disputed_note"].lower()
    assert "DIVERGENCE" in " ".join(render_lines(b))


def test_agreement_and_single_source_are_distinguished():
    assert synthesize(artifacts=[_art("a", "VALID", "BULLISH"),
                                 _art("b", "VALID", "BULLISH")])["state"] == AGREED
    assert synthesize(artifacts=[_art("a", "VALID", "BULLISH")])["state"] == SINGLE


def test_only_valid_artifacts_are_synthesised():
    b = synthesize(artifacts=[_art("a", "FAIL"), _art("b", "execution_language")])
    assert b["state"] == NO_INPUT
    assert b["artifacts_valid"] == 0
    assert {x["outcome"] for x in b["excluded_non_valid"]} == {
        "FAIL", "execution_language"}


def test_position_is_never_inferred_from_prose():
    """A stance must come from an explicit field, not a parsed sentence."""
    b = synthesize(artifacts=[_art("a", "VALID"), _art("b", "VALID")])
    assert b["positions"] == {}
    assert b["state"] == AGREED


def test_council_lines_carry_no_imperative():
    from scripts.lib.execution_language import find_imperative

    for arts in ([_art("a", "VALID", "BULLISH"), _art("b", "VALID", "BEARISH")],
                 [_art("a", "VALID", "BULLISH")], []):
        assert not find_imperative(" ".join(render_lines(synthesize(artifacts=arts))))


def test_cost_is_summed_over_all_considered_not_just_valid():
    b = synthesize(artifacts=[_art("a", "VALID", "X", 0.02),
                              _art("b", "FAIL", None, 0.03)])
    assert b["total_cost_usd"] == 0.05


# =========================================================== notification

def test_s1_observational_is_suppressed():
    r = policy.decide({"situation_type": "S1_POSITION_LIFECYCLE", "material": True},
                      now=NOW)
    assert r["decision"] == policy.SUPPRESSED
    assert r["reason"] == "s1_observational_default_suppressed"


def test_all_s5_cash_is_suppressed():
    r = policy.decide({"situation_type": "S5_CASH_DEPLOYMENT", "material": True},
                      now=NOW)
    assert r["decision"] == policy.SUPPRESSED


def test_duplicate_subject_is_suppressed_first():
    """36 open S5 plans are one question; notifying each says nothing new."""
    r = policy.decide({"situation_type": "S3_REENTRY_CANDIDATE", "material": True},
                      duplicate_subject=True, now=NOW)
    assert r["decision"] == policy.SUPPRESSED
    assert r["reason"] == "duplicate_subject"


def test_s6_fire_is_command_center_never_immediate():
    r = policy.decide({"situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
                       "material": True}, now=NOW)
    assert r["decision"] == policy.COMMAND_CENTER_ONLY
    assert r["decision"] != policy.IMMEDIATE


def test_not_material_is_suppressed():
    r = policy.decide({"situation_type": "S3_REENTRY_CANDIDATE", "material": False},
                      now=NOW)
    assert r["decision"] == policy.SUPPRESSED


def test_disputed_council_goes_to_the_command_center():
    r = policy.decide({"situation_type": "S3_REENTRY_CANDIDATE", "material": True},
                      synthesis={"state": "DISPUTED"}, now=NOW)
    assert r["decision"] == policy.COMMAND_CENTER_ONLY


def test_every_decision_records_would_send_false():
    for plan in ({"situation_type": "S6_X", "material": True},
                 {"situation_type": "S3_X", "material": True},
                 {"situation_type": "S1_X", "material": True}):
        r = policy.decide(plan, now=NOW)
        assert r["would_send"] is False
        assert r["delivery"] == "shadow"
        assert r["financial_action"] is False


def test_notification_id_is_stable_and_persisted(tmp_path):
    plan = {"plan_id": "p1", "situation_type": "S6_X", "material": True}
    a = policy.decide(plan, now=NOW)
    b = policy.decide(plan, now=NOW)
    assert a["notification_id"] == b["notification_id"]
    res = policy.persist(tmp_path, a)
    assert res["wrote"] is True
    assert res["notification_id"] == a["notification_id"]


def test_delivery_refuses_a_live_adapter():
    class Live:
        is_live = True

        def send(self, n):
            raise AssertionError("must never be called")

    row = policy.decide({"situation_type": "S6_X", "material": True}, now=NOW)
    with pytest.raises(RuntimeError):
        policy.deliver(row, adapter=Live())


def test_suppressed_never_reaches_an_adapter():
    class Boom:
        is_live = False

        def send(self, n):
            raise AssertionError("suppressed must not be delivered")

    row = policy.decide({"situation_type": "S5_CASH", "material": True}, now=NOW)
    assert policy.deliver(row, adapter=Boom())["delivered"] is False


def test_shadow_delivery_reports_would_send_false():
    row = policy.decide({"situation_type": "S6_X", "material": True}, now=NOW)
    out = policy.deliver(row)
    assert out["would_send"] is False
    assert out["delivery_method"] == "shadow"


# ============================================================== checkpoint

def test_new_checkpoint_must_declare_plan_id(tmp_path):
    from scripts.lib.cio_institutional_learning import persist_checkpoint

    r = persist_checkpoint(tmp_path, {"checkpoint_id": "c1"})
    assert r["wrote"] is False
    assert r["rejected"] == "missing_plan_id_field"


def test_a_bound_checkpoint_is_written(tmp_path):
    from scripts.lib.cio_institutional_learning import persist_checkpoint

    assert persist_checkpoint(tmp_path, {"checkpoint_id": "c1",
                                         "plan_id": "p1"})["wrote"] is True


def test_an_explicitly_unbound_checkpoint_is_allowed(tmp_path):
    """Cash- and dust-bound checkpoints have no plan by nature.

    Rejecting them outright would break the very rows the operator said not to
    rewrite. A declared null keeps them writable while excluding them from the
    rate's denominator.
    """
    from scripts.lib.cio_institutional_learning import persist_checkpoint

    r = persist_checkpoint(tmp_path, {"checkpoint_id": "c2", "plan_id": None,
                                      "plan_binding": "unbound_cash"})
    assert r["wrote"] is True


def test_scheduler_always_declares_a_plan_binding():
    from scripts.lib.cio_institutional_learning import schedule_outcome_checkpoint

    unbound = schedule_outcome_checkpoint("d1", "30d")
    assert "plan_id" in unbound and unbound["plan_binding"] == "unbound"
    bound = schedule_outcome_checkpoint("d1", "30d", plan_id="p1")
    assert bound["plan_id"] == "p1" and bound["plan_binding"] == "bound"


# ============================================================ ops surface

def test_eligible_surface_carries_skip_reason_and_caps():
    from scripts.lib.cio_research_gate import decide as gate_decide
    from scripts.lib.cio_research_gate import schedule_surface

    rows = [gate_decide({"material": True, "kind": "held_core_thesis"}, now=NOW)]
    rows += [gate_decide({"material": False, "kind": "held_core_thesis"}, now=NOW)
             for _ in range(20)]
    s = schedule_surface(rows, cap=10, now=NOW)
    assert len(s["next_eligible"]) <= 10
    assert len(s["skipped_sample"]) <= 10
    assert all("skip_reason" in r for r in s["skipped_sample"])


def test_ops_surface_is_never_routed_to_telegram():
    from scripts.lib.cio_research_gate import decide as gate_decide
    from scripts.lib.cio_research_gate import schedule_surface

    s = schedule_surface([gate_decide({"material": True,
                                       "kind": "held_core_thesis"}, now=NOW)],
                         now=NOW)
    assert "telegram" not in str(s).lower()
    assert s["financial_action"] is False


# ================================================================== EDGAR

def test_edgar_is_registered_entity_scoped_and_cannot_close():
    from scripts.lib.cio_corpus_index import registry

    row = next(r for r in registry()["seed"]
               if r["source_id"] == "sec_edgar_full_text")
    assert row["dimension_scope"] == "entity"
    assert row["evidence_grade"] == "C"
    assert row["can_corpus_hit"] is False
    assert row["path_or_MISSING"] == "MISSING"


def test_no_edgar_crawler_was_added():
    """Code only — the modules legitimately *say* "no crawler" in prose."""
    for rel in ("scripts/lib/cio_library_seed.py",) + tuple(WAVE3B_MODULES):
        code = re.sub(r"#.*", "",
                      re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", _src(rel))).lower()
        for bad in ("crawl(", "scrape(", "download_full_text", "requests.get",
                    "urlopen"):
            assert bad not in code, (rel, bad)

"""LLM_MODEL_SCOUT_20261107 — monthly Model Scout (LQ-20261107-197, DSN-20261107-ANTHROPIC-FIRST-ROUTING §5.2).

The diff finds new, retired and missing ids; a failed discovery is UNKNOWN, never a P1; the scout never writes the
registry, the task classes or the credit policy; no key value reaches stdout, the report or the receipt; the eval is
capped and refuses live; the fixtures are synthetic. No network: every provider answer is a fake fetch.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import llm_model_scout as scout  # noqa: E402

KEY_A = "sk-ant-synthetic-SECRET-aaaaaaaaaaaaaaaa"
KEY_D = "sk-ds-synthetic-SECRET-dddddddddddddddd"
REGISTRY = {"providers": {
    "anthropic": {"models": {
        "h": {"model_id": "m-haiku-2", "enabled": True},
        "s": {"model_id": "m-sonnet-2", "enabled": True},
        "old": {"model_id": "m-haiku-1", "enabled": False, "historical_only": True}},
        "retired_models": {"m-opus-0": "retired"}},
    "deepseek": {"models": {"f": {"model_id": "ds-flash", "enabled": True,
                                  "pricing_snapshot_usd_per_million_tokens": {"cache_miss_input": 0.15, "output": 0.6}}},
                 "legacy_model_ids_rejected": ["ds-chat"]}}}
POLICY = {"models": {"bulk": "m-haiku-2", "mid": "m-sonnet-2", "standard": "m-opus-2"}}
TASK_CLASSES = {"eval_classes": ["extract", "summarize", "score", "reason", "critique", "verdict"]}
FIXTURES = ROOT / "tests" / "fixtures" / "llm_eval"


def listing(*rows):
    return json.dumps({"data": [r if isinstance(r, dict) else {"id": r} for r in rows], "has_more": False}).encode()


def fake_fetch(answers):
    """answers: {host fragment: (status, body)}; records the headers it was given."""
    seen = []

    def fetch(url, headers):
        seen.append((url, dict(headers)))
        for frag, ans in answers.items():
            if frag in url:
                return ans
        return 404, b""
    fetch.seen = seen
    return fetch


def run(answers, providers=("anthropic", "deepseek")):
    return scout.scout(keys={"ANTHROPIC_API_KEY": KEY_A, "deepseek_tradeai": KEY_D}, registry=REGISTRY, policy=POLICY,
                       fixtures=FIXTURES, task_classes=TASK_CLASSES, fetch=fake_fetch(answers), providers=providers)


def kinds(report, provider):
    return {(f["kind"], f["model_id"]) for f in report["diff"][provider]["findings"]}


def test_diff_flags_new_ids_and_skips_registered_retired_and_rejected():
    r = run({"anthropic": (200, listing("m-haiku-2", "m-sonnet-2", "m-opus-2", "m-haiku-3", "m-opus-0")),
             "deepseek": (200, listing("ds-flash", "ds-chat", "ds-flash-2"))})
    assert ("NEW_MODEL", "m-haiku-3") in kinds(r, "anthropic")
    assert ("NEW_MODEL", "ds-flash-2") in kinds(r, "deepseek")
    new = {m for k, m in kinds(r, "anthropic") | kinds(r, "deepseek") if k == "NEW_MODEL"}
    assert new == {"m-haiku-3", "ds-flash-2"}  # m-opus-0 retired, ds-chat rejected, routed ids known
    assert r["p1"] == []


def test_a_routed_model_the_provider_no_longer_lists_is_p1_and_exits_3(tmp_path, capsys):
    r = run({"anthropic": (200, listing("m-haiku-2", "m-opus-2")), "deepseek": (200, listing("ds-flash"))})
    assert {(f["provider"], f["kind"], f["model_id"]) for f in r["p1"]} == {
        ("anthropic", "ROUTED_MODEL_NOT_LISTED", "m-sonnet-2")}
    # the tier model from the credit policy counts as routed, not only the registry's enabled rows
    r2 = run({"anthropic": (200, listing("m-haiku-2", "m-sonnet-2")), "deepseek": (200, listing("ds-flash"))})
    assert [f["model_id"] for f in r2["p1"]] == ["m-opus-2"]
    rc = _main(tmp_path, {"anthropic": (200, listing("m-haiku-2")), "deepseek": (200, listing("ds-flash"))})
    assert rc == 3 and "P1 anthropic ROUTED_MODEL_NOT_LISTED m-sonnet-2" in capsys.readouterr().out


def test_a_routed_model_marked_retired_is_p1_and_deprecation_fields_are_flagged():
    reg = json.loads(json.dumps(REGISTRY))
    reg["providers"]["anthropic"]["retired_models"]["m-sonnet-2"] = "retiring"
    known = scout.known_ids(reg, POLICY)["anthropic"]
    d = {"status": "OK", "models": [{"id": "m-haiku-2", "retires_at": "2026-12-01T00:00:00Z"},
                                    {"id": "m-sonnet-2"}, {"id": "m-opus-2"},
                                    {"id": "m-haiku-1", "deprecated_at": "2026-09-30T00:00:00Z"}]}
    out = scout.diff("anthropic", d, known)
    got = {(f["kind"], f["model_id"], f["severity"]) for f in out["findings"]}
    assert ("ROUTED_MODEL_MARKED_RETIRED", "m-sonnet-2", "P1") in got
    assert ("DEPRECATION_NOTICE", "m-haiku-2", "P2") in got   # routed and retiring
    assert ("DEPRECATION_NOTICE", "m-haiku-1", "INFO") in got  # historical only


@pytest.mark.parametrize("answer", [(401, b""), (500, b""), (200, b"not json"), (200, b'{"nope": 1}')])
def test_a_failed_discovery_is_unknown_never_a_false_p1(answer):
    r = run({"anthropic": answer, "deepseek": (200, listing("ds-flash"))})
    assert r["diff"]["anthropic"]["status"] == "UNKNOWN" and r["p1"] == []


def test_no_key_is_no_key_and_sends_nothing():
    f = fake_fetch({})
    d = scout.discover("anthropic", {}, f)
    assert d["status"] == "NO_KEY" and f.seen == []


def test_anthropic_paginates_and_keys_go_only_in_headers():
    pages = [json.dumps({"data": [{"id": "m-haiku-2"}], "has_more": True, "last_id": "m-haiku-2"}).encode(),
             json.dumps({"data": [{"id": "m-sonnet-2"}], "has_more": False}).encode()]
    seen = []

    def fetch(url, headers):
        seen.append((url, headers))
        return 200, pages[len(seen) - 1]
    d = scout.discover("anthropic", {"ANTHROPIC_API_KEY": KEY_A}, fetch)
    assert [m["id"] for m in d["models"]] == ["m-haiku-2", "m-sonnet-2"]
    assert "after_id=m-haiku-2" in seen[1][0]
    assert all(KEY_A not in u for u, _ in seen) and seen[0][1]["x-api-key"] == KEY_A


def test_price_comes_from_the_api_or_a_curated_row_never_a_guess():
    d = {"models": [{"id": "x", "max_input_tokens": 1000, "max_tokens": 100}, {"id": "ds-flash"}]}
    known = scout.known_ids(REGISTRY, POLICY)
    unpriced = scout.price_row("anthropic", "x", d, known["anthropic"])
    assert unpriced["price"] is None and unpriced["price_status"] == "PRICE_UNCONFIRMED"
    assert unpriced["context_window"] == 1000 and unpriced["max_output_tokens"] == 100
    curated = scout.price_row("deepseek", "ds-flash", d, known["deepseek"])
    assert curated["price_status"] == "CONFIRMED" and curated["price_source"] == "registry_curated"


def test_only_newer_ids_in_a_routed_family_become_eval_candidates():
    rows = [{"id": "m-haiku-2", "created_at": "2026-06-01T00:00:00Z"}, {"id": "m-sonnet-2"}, {"id": "m-opus-2"},
            {"id": "m-haiku-3", "created_at": "2026-10-01T00:00:00Z"},
            {"id": "m-haiku-0", "created_at": "2025-01-01T00:00:00Z"},
            {"id": "other-model-9", "created_at": "2026-10-01T00:00:00Z"}]
    r = run({"anthropic": (200, listing(*rows)), "deepseek": (200, listing("ds-flash"))})
    assert [c["model_id"] for c in r["eval"]["candidates"]] == ["m-haiku-3"]
    # unpriced: planned nothing, blocked with the reason; nothing ran
    assert r["eval"]["plan"]["items"] == []
    assert r["eval"]["plan"]["blocked"] == [{"model_id": "m-haiku-3", "reason": "EVAL_BLOCKED_PRICE_UNCONFIRMED"}]
    assert r["eval"]["results"] is None and r["recommendations"] == []


def test_eval_plan_never_exceeds_two_dollars():
    sets = scout.load_eval_sets(FIXTURES, TASK_CLASSES["eval_classes"])
    pricey = [{"model_id": f"big-{i}", "price_status": "CONFIRMED", "price": {"input": 15, "output": 75}}
              for i in range(3)]
    plan = scout.eval_plan(pricey, sets)
    assert Decimal(plan["planned_usd"]) <= Decimal("2.00") and plan["items"]
    assert any(b["reason"] == "EVAL_CAP_REACHED" for b in plan["blocked"])


def test_scorer_and_recommendation_with_an_injected_generator():
    case = json.loads((FIXTURES / "extract.json").read_text())["cases"][0]
    good = json.dumps(case["expected"])
    assert scout.score_case(case, good) == {"id": case["id"], "json_valid": True, "accuracy": 1.0}
    assert scout.score_case(case, "not json")["json_valid"] is False
    cases = json.loads((FIXTURES / "verdict.json").read_text())["cases"]

    def gen(model_id, c):
        exp = c["expected"]["verdict"] if model_id == "cand" else "APPROVE"
        return {"text": json.dumps({"verdict": exp, "reason": "rule"}), "usd": "0.001", "latency_ms": 5}
    res = {"verdict": {m: scout.run_eval(m, cases, gen, Decimal("2")) for m in ("inc", "cand")}}
    assert res["verdict"]["cand"]["accuracy"] == 1.0 > res["verdict"]["inc"]["accuracy"]
    recs = scout.recommend(res, {"verdict": "inc"})
    assert [(r["class"], r["candidate"]) for r in recs] == [("verdict", "cand")]
    assert recs[0]["action"].startswith("RECOMMEND_ONLY")
    # the budget stops a run
    assert scout.run_eval("cand", cases, gen, Decimal("0.0025"))["cases"] == 3


def test_live_eval_refuses():
    assert scout.main(["--eval", "--env-file", ""]) == 2


def _hash(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _main(tmp_path, answers, extra=(), monkeypatch=None):
    env_file = tmp_path / "keys.env"
    env_file.write_text(f"ANTHROPIC_API_KEY={KEY_A}\nexport deepseek_tradeai='{KEY_D}'\n", encoding="utf-8")
    reg, pol = tmp_path / "registry.json", tmp_path / "policy.json"
    reg.write_text(json.dumps(REGISTRY), encoding="utf-8")
    pol.write_text(json.dumps(POLICY), encoding="utf-8")
    return scout.main(["--env-file", str(env_file), "--providers", "anthropic,deepseek", "--registry", str(reg),
                       "--policy", str(pol), "--json", *extra], fetch=fake_fetch(answers), environ={})


def test_the_scout_never_writes_the_registry_task_classes_or_policy(tmp_path, monkeypatch, capsys):
    real = [ROOT / "config/llm_model_registry.json", ROOT / "config/llm_task_classes.json",
            ROOT / "config/anthropic_credit_policy.json"]
    before = _hash(real)
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(scout, "_db_insert", lambda report: "TABLE_ABSENT")
    answers = {"anthropic": (200, listing("m-haiku-2", "m-sonnet-2", "m-opus-2", "m-haiku-3")),
               "deepseek": (200, listing("ds-flash"))}
    reg = tmp_path / "registry.json"
    assert _main(tmp_path, answers) == 0
    assert not state.exists(), "a dry run wrote state"
    reg_before = reg.read_bytes()
    assert _main(tmp_path, answers, ["--write"]) == 0
    assert reg.read_bytes() == reg_before and _hash(real) == before
    written = sorted(p.relative_to(state).as_posix() for p in state.rglob("*") if p.is_file())
    assert any(w.startswith("data/runtime/llm_model_scout/") and w.endswith(".json") for w in written)
    assert all("registry" not in w and "task_classes" not in w and "policy" not in w for w in written)


def test_no_key_value_ever_appears_in_stdout_report_or_receipt(tmp_path, monkeypatch, capsys):
    """A hostile listing echoes the key back as a model id; the redactor still keeps it out of every output."""
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(scout, "_db_insert", lambda report: "TABLE_ABSENT")
    answers = {"anthropic": (200, listing("m-haiku-2", "m-sonnet-2", "m-opus-2", f"echo-{KEY_A}")),
               "deepseek": (200, listing("ds-flash", KEY_D))}
    _main(tmp_path, answers)
    _main(tmp_path, answers, ["--write"])
    out = capsys.readouterr()
    texts = [out.out, out.err] + [p.read_text(encoding="utf-8") for p in state.rglob("*") if p.is_file()]
    assert len(texts) >= 4
    for t in texts:
        assert KEY_A not in t and KEY_D not in t
    assert "[REDACTED]" in out.out
    report = json.loads(next(state.rglob("llm_model_scout/*.json")).read_text())
    assert report["key_names_present"] == ["ANTHROPIC_API_KEY", "deepseek_tradeai"]


def test_eval_fixtures_are_frozen_synthetic_twenty_per_class():
    for cls in TASK_CLASSES["eval_classes"]:
        doc = json.loads((FIXTURES / f"{cls}.json").read_text(encoding="utf-8"))
        assert doc["synthetic"] is True and doc["class"] == cls and len(doc["cases"]) == 20
        assert len({c["id"] for c in doc["cases"]}) == 20
        for c in doc["cases"]:
            assert c["class"] == cls and c["expected"] and c["system"]
    cases = json.dumps([json.loads((FIXTURES / f"{c}.json").read_text())["cases"] for c in TASK_CLASSES["eval_classes"]])
    assert "/" + "home/" not in cases and "account" not in cases.lower() and "portfolio" not in cases.lower()


def test_lane_proposal_is_shadow_monthly_and_pairs_the_three_rows():
    p = json.loads((ROOT / "docs/llm/llm-model-scout-lane.proposed.json").read_text(encoding="utf-8"))
    reg, allow, contract = p["lane_registry"], p["n8n_run_allowlist"], p["n8n_health_contract"]
    assert reg["lane_id"] == allow["lane_id"] == contract["id"] == scout.LANE_ID
    assert reg["scheduler"]["kind"] == "n8n" and reg["scheduler"]["stage"] == "shadow"
    assert reg["scheduler"]["cadence"] == "0 6 1 * *" and reg["dispatch"]["cron"] == ["0 6 1 * *"]
    assert reg["scheduler"]["timezone"] == "America/New_York" and reg["dispatch"]["mode"] == "dry_run"
    assert allow["live_arg"] is None and allow["dry_run_arg"] == ["--dry-run"]
    assert allow["command"] == ["$PY", "scripts/llm_model_scout.py"]
    assert contract["alerting"]["failed"]["notifier_priority"] == "P1"

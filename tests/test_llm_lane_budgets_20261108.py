"""LQ-20261107-865: config-driven per-lane cloud request budgets.

- `config/llm_lane_budgets.json` is self-deriving: every row's `budget_s` equals the value its own
  `p95_ms`/`max_ok_ms` produce under the file's `margin` and `cap_s`, so the file cannot quietly drift
  from the measurement it claims.
- The three degraded lanes named by the item are sized: topic_curator 40 s (was 30 s at the
  improve_queries site), topic_ingestion 30 s (was 25 s at the RAG-quality site),
  topic_research_synthesizer 70 s (already correct -- recorded, not changed).
- `generate_cloud(timeout=None)` waits the lane's resolved budget, an explicit timeout is passed
  through verbatim, and a lane the config does not size falls back to 90 s (the historical default).
- A malformed config raises: a budget nobody can read is not silently replaced by the fallback.
- The call sites in topic_curator / topic_ingestion / topic_research_synthesizer no longer carry a
  literal timeout (AST-checked), so re-introducing a hand-picked number fails here.

Hermetic: no DB, no network, no process spawn, no LLM call.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import topic_curator as tc  # noqa: E402
from lib import governed_cloud_generation as gcg  # noqa: E402
from lib import llm_lane_budgets as budgets  # noqa: E402

SHIPPED = ROOT / "config" / "llm_lane_budgets.json"
CALL_SITE_SCRIPTS = (
    ROOT / "scripts" / "topic_curator.py",
    ROOT / "scripts" / "topic_ingestion.py",
    ROOT / "scripts" / "topic_research_synthesizer.py",
)
DEGRADED = ("topic_curator", "topic_ingestion", "topic_research_synthesizer")


class FakeLane:
    def __init__(self, available, responses):
        self.available_lanes = set(available)
        self.responses = dict(responses)
        self.calls = []

    def available(self, lane):
        return lane in self.available_lanes

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        value = self.responses[kwargs["lane"]]
        if isinstance(value, Exception):
            raise value
        return value


def _write_config(tmp_path, *, lanes=None, **over):
    doc = {
        "schema": budgets.SCHEMA,
        "margin": 0.25,
        "cap_s": 120,
        "fallback_s": 90,
        "lanes": lanes if lanes is not None else {},
    }
    doc.update(over)
    path = tmp_path / "llm_lane_budgets.json"
    path.write_text(json.dumps(doc))
    return path


def _row(budget_s, p95_ms=1000, max_ok_ms=1000):
    return {"budget_s": budget_s, "p95_ms": p95_ms, "max_ok_ms": max_ok_ms}


# ── the shipped config is its own derivation ────────────────────────────────────────────────────────
def test_every_shipped_row_re_derives_its_own_budget():
    raw = json.loads(SHIPPED.read_text())
    assert raw["schema"] == budgets.SCHEMA
    for lane, row in raw["lanes"].items():
        derived = budgets.derive_budget_s(
            float(row["p95_ms"]), float(row["max_ok_ms"]), margin=raw["margin"], cap_s=raw["cap_s"]
        )
        assert derived == float(row["budget_s"]), f"{lane}: file says {row['budget_s']}, method says {derived}"


def test_shipped_config_sizes_the_three_degraded_lanes_from_the_measured_tail():
    shipped = budgets.load_lane_budgets(SHIPPED)
    for lane in DEGRADED:
        assert lane in shipped, lane
    assert shipped["topic_curator"] == 40.0 > 30.0
    assert shipped["topic_ingestion"] == 30.0 > 25.0
    # The synthesizer was already sized correctly; the config records the measurement and changes nothing.
    assert shipped["topic_research_synthesizer"] == 70.0


def test_report_exits_zero_on_the_shipped_config(monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_LLM_LANE_BUDGETS_PATH", str(SHIPPED))
    assert budgets._main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "topic_curator" in out and "DRIFT" not in out


def test_report_exits_nonzero_when_a_row_drifts_from_its_measurement(monkeypatch, tmp_path, capsys):
    """Mutation: change the shipped budget by 5 s, the report notices."""
    doc = json.loads(SHIPPED.read_text())
    doc["lanes"]["topic_curator"]["budget_s"] += 5
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setenv("TRADEAI_LLM_LANE_BUDGETS_PATH", str(path))
    assert budgets._main(["--report"]) == 1
    assert "DRIFT" in capsys.readouterr().out


# ── the derivation itself ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [(40.0, 40.0), (39.9, 40.0), (25.64, 30.0), (0.1, 5.0), (120.0, 120.0)],
)
def test_ceil_to_five_seconds_keeps_an_exact_step_exact(value, expected):
    assert budgets.ceil_to_5s(value) == expected


def test_ceil_rejects_a_nonpositive_budget():
    with pytest.raises(budgets.LlmLaneBudgetConfigError):
        budgets.ceil_to_5s(0)


def test_derivation_is_capped_and_uses_the_whole_successful_tail():
    # Cap binds before the margin would push it over.
    assert budgets.derive_budget_s(99_000, 99_500, margin=0.25, cap_s=120) == 120.0
    # The observed max-ok outranks a smaller p95*margin target.
    assert budgets.derive_budget_s(20_000, 39_900, margin=0.25, cap_s=120) == 40.0


# ── generate_cloud resolves the budget, and only when the caller did not name one ──────────────────
def _resolve(monkeypatch, tmp_path, lanes, **over):
    path = _write_config(tmp_path, lanes=lanes, **over)
    monkeypatch.setenv("TRADEAI_LLM_LANE_BUDGETS_PATH", str(path))
    monkeypatch.delenv(gcg.VIA_BRIDGE_ENV, raising=False)
    fake = FakeLane({"grok"}, {"grok": "ok"})
    monkeypatch.setitem(sys.modules, "llm_lane", fake)
    return fake


def test_generate_cloud_waits_the_lane_budget_when_the_caller_names_none(monkeypatch, tmp_path):
    fake = _resolve(monkeypatch, tmp_path, {"lq865_lane_a": _row(45)})
    text, lane = gcg.generate_cloud("p", process_id="lq865_lane_a", task_summary="t")
    assert (text, lane) == ("ok", "grok")
    assert fake.calls[0][1]["timeout"] == 45.0


def test_generate_cloud_keys_the_budget_to_the_process_id(monkeypatch, tmp_path):
    fake = _resolve(monkeypatch, tmp_path, {"lq865_lane_a": _row(45), "lq865_lane_b": _row(60)})
    gcg.generate_cloud("p", process_id="lq865_lane_b", task_summary="t")
    assert fake.calls[0][1]["timeout"] == 60.0


def test_generate_cloud_does_not_rewrite_an_explicit_timeout(monkeypatch, tmp_path):
    fake = _resolve(monkeypatch, tmp_path, {"lq865_lane_a": _row(45)})
    gcg.generate_cloud("p", process_id="lq865_lane_a", task_summary="t", timeout=7)
    assert fake.calls[0][1]["timeout"] == 7.0


def test_generate_cloud_falls_back_to_historical_default_for_an_unsized_lane(monkeypatch, tmp_path):
    fake = _resolve(monkeypatch, tmp_path, {"lq865_lane_a": _row(45)})
    gcg.generate_cloud("p", process_id="lq865_unlisted", task_summary="t")
    assert fake.calls[0][1]["timeout"] == budgets.DEFAULT_FALLBACK_S == 90.0


# ── a config nobody can read raises; it is never silently replaced ─────────────────────────────────
def test_absent_config_means_no_overrides_and_the_caller_fallback():
    missing = Path("/nonexistent/llm_lane_budgets.json")
    assert budgets.load_lane_budgets(missing) == {}
    assert budgets.budget_s("topic_curator", path=missing) == 90.0


@pytest.mark.parametrize(
    "text,reason",
    [
        ("{not json", "lane_budgets_unreadable"),
        (json.dumps({"schema": "Wrong@v1", "margin": 0.25, "cap_s": 120, "fallback_s": 90, "lanes": {}}),
         "lane_budgets_schema"),
        (json.dumps({"schema": budgets.SCHEMA, "margin": 0.25, "cap_s": 500, "fallback_s": 90, "lanes": {}}),
         "lane_budgets_cap_too_high"),
        (json.dumps({"schema": budgets.SCHEMA, "margin": 0.25, "cap_s": 120, "fallback_s": 90,
                     "lanes": {"x": _row(240)}}), "lane_budgets_over_cap"),
        (json.dumps({"schema": budgets.SCHEMA, "margin": 0.25, "cap_s": 120, "fallback_s": 90,
                     "lanes": {"x": {"budget_s": "40"}}}), "lane_budgets_bad_field"),
    ],
)
def test_a_malformed_config_raises_instead_of_falling_back(tmp_path, text, reason):
    path = tmp_path / "bad.json"
    path.write_text(text)
    with pytest.raises(budgets.LlmLaneBudgetConfigError, match=reason):
        budgets.load_lane_budgets(path)


# ── the call sites ─────────────────────────────────────────────────────────────────────────────────
def _generate_cloud_calls(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "generate_cloud":
            yield node


@pytest.mark.parametrize("path", CALL_SITE_SCRIPTS, ids=lambda p: p.name)
def test_no_scheduled_call_site_pins_its_own_timeout(path):
    calls = list(_generate_cloud_calls(path))
    assert calls, f"{path.name} has no generate_cloud call to check"
    for call in calls:
        assert not [kw for kw in call.keywords if kw.arg == "timeout"], f"{path.name}:{call.lineno}"


def test_curator_generator_passes_no_timeout(monkeypatch):
    """Behaviour, not just source: the helper hands the resolution to generate_cloud."""
    seen = {}

    def fake_generate(prompt, **kwargs):
        seen.update(kwargs)
        return "ok", "grok"

    import types

    monkeypatch.setitem(sys.modules, "lib.governed_cloud_generation",
                        types.SimpleNamespace(generate_cloud=fake_generate))
    assert tc._free_lane_gen("prompt") == "ok"
    assert "timeout" not in seen
    assert seen["process_id"] == "topic_curator"

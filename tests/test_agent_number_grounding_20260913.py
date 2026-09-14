"""Agent answers use only supplied facts, and their numbers are checked.

2026-09-13: agent jobs gathered Command Center facts first, but nothing told
the model to use only them, and nothing compared the numbers in its answer with
what it was sent. These tests pin:

* the rule is in every watchlist agent contract and in Maria's one-pass prompt
* numbers that match the supplied context (exactly, rounded, as percent or
  fraction, or as a change between two supplied figures) are supported
* counts, days, list numbers, years, dates and model names are not checked
* an answer with invented figures is demoted to RESEARCH_MORE below the 40 %
  gate, names the numbers, and keeps the original in the report
* record and off modes change nothing
* the gap resolver does not accept a demoted result as proof

Pure: no database, no model.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import agent_number_grounding as G  # noqa: E402
from lib import cio_agent_contract as C  # noqa: E402

CONTEXT = """Symbol: SCHG
Position: $8, 0.2 shares, 0.0% allocation, account: schwab_taxable
RSI: 49.38, Beta: 1.12, Sector: Technology
SMA20: -0.66%, SMA50: 0.76%, SMA200: 9.4%
Strategy: growth, Support: $34.55, Resistance: $35.855
Stop: $34.35, Target: $36.40, R:R: 1.55
Recent prices: $35.16, $35.02, $34.90, $35.40, $35.31
Alpha Vantage: Analyst target: $38.00, 52W high: $36.12, 52W low: $27.80, Div yield: 0.41%
"""


def _parsed(summary, narrative="", evidence=None, rec="BUY", conf=0.72):
    return {
        "summary": summary, "full_narrative": narrative, "recommendation": rec, "confidence": conf,
        "evidence": evidence or [], "data_i_doubt": "none", "reason_codes": ["technical_support"],
        "next_action": "",
    }


def test_rule_is_in_every_watchlist_contract_and_maria_prompt():
    block = C.build_base_json_instruction()
    assert "USE ONLY SUPPLIED FACTS" in block and "checked against the supplied context" in block
    assert "USE ONLY SUPPLIED FACTS" in C.build_base_json_instruction(include_global_rules=False)
    src = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text()
    one_pass = src[src.index("def _run_maria_one_pass"):src.index("# Backward-compatible aliases")]
    assert "GROUNDING_RULE" in one_pass and "_last_maria_prompt = prompt" in one_pass


def test_exact_rounded_percent_and_derived_numbers_are_supported():
    texts = [
        "SCHG at $35.16 sits above support $34.55 with RSI 49.4 and a 1.55 R:R.",
        "Target $36.4 is 3.5% above the last close; analyst target $38.",
        "Dividend yield 0.41%; stop $34.35 is $0.81 below the close.",
    ]
    r = G.check_grounding(texts, CONTEXT)
    assert r["verdict"] == "grounded" and r["unsupported"] == [], r


def test_trivial_numbers_dates_and_model_names_are_not_checked():
    texts = ["Review in 14 days; see rule G4 and item 3 of 5. Filed 2026-09-13 at 10:00.",
             "Model: deepseek-flash gpt-5.4 said Q3 and 10-K matter.",
             "Hold it in the 401k, not the Roth; confidence 0.85 (conf: 72%), 85% confident."]
    assert G.check_grounding(texts, CONTEXT)["verdict"] == "no_numbers"


def test_negative_supplied_numbers_still_support_a_quoted_value():
    # "SMA20: -26.84%" in the context; the agent writes "26.84% below the 20-day".
    r = G.check_grounding(["Price is 26.84% below the 20-day and 33.19% below the 50-day."],
                          "SMA20: -26.84%, SMA50: -33.19%")
    assert r["unsupported"] == [], r
    assert [n["value"] for n in G.extract_numbers("gpt-5.4 on 2026-09-13")] == [2026.0]


def test_derived_values_do_not_make_every_percentage_pass():
    # With pairwise changes across every supplied figure and a relative tolerance,
    # an invented 27.3% matched by accident. Only dollar-figure changes, at the
    # precision written, may support a claim.
    r = G.check_grounding(["Up 27.3% this quarter; margin 18.6%; 12.9% growth."], CONTEXT)
    assert set(r["unsupported"]) == {"27.3%", "18.6%", "12.9%"}
    ok = G.check_grounding(["The close of $35.16 is 1.8% above support."], CONTEXT)
    assert ok["unsupported"] == [], ok


def test_invented_figures_are_ungrounded_and_demoted():
    p = _parsed("SCHG trades at $412.50 with a $520 target, up 27.3% this quarter.",
                evidence=[{"tag": "fact", "text": "P/E of 44.8 and revenue $2.1B"}])
    out, rep = G.apply_number_grounding(p, CONTEXT, mode_override="enforce")
    assert rep["verdict"] == "ungrounded" and rep["demoted"] is True
    assert set(rep["unsupported"]) >= {"$412.50", "$520", "27.3%", "44.8", "$2.1B"}
    assert out["recommendation"] == "RESEARCH_MORE" and out["confidence"] <= 0.39
    assert out["reason_codes"][-1] == "UNGROUNDED_NUMBERS" and "technical_support" in out["reason_codes"]
    assert out["summary"].startswith("Unverified numbers, not in the supplied data: $412.50")
    assert "numbers not found in the supplied context" in out["data_i_doubt"]
    assert rep["original_recommendation"] == "BUY" and rep["original_confidence"] == 0.72
    assert p["recommendation"] == "BUY", "the input is not mutated"


def test_one_stray_number_among_many_real_ones_is_not_demoted():
    p = _parsed("SCHG $35.16, support $34.55, stop $34.35, target $36.40, RSI 49.38, yield 0.41%, beta 1.12, "
                "and roughly 6.8% upside to $38.")
    out, rep = G.apply_number_grounding(p, CONTEXT, mode_override="enforce")
    assert rep["verdict"] == "grounded" and out["recommendation"] == "BUY"


def test_record_and_off_modes_change_nothing(monkeypatch):
    p = _parsed("Price $412.50, target $520, up 27.3%.")
    out, rep = G.apply_number_grounding(p, CONTEXT, mode_override="record")
    assert rep["verdict"] == "ungrounded" and rep["demoted"] is False and out is p
    monkeypatch.setenv(G.MODE_ENV, "off")
    out2, rep2 = G.apply_number_grounding(p, CONTEXT)
    assert rep2["verdict"] == "not_checked" and out2 is p


def test_default_mode_enforces_and_record_is_one_env_var_away(monkeypatch):
    monkeypatch.delenv(G.MODE_ENV, raising=False)
    assert G.mode() == "enforce"
    p = _parsed("Price $412.50, target $520, up 27.3%.")
    out, rep = G.apply_number_grounding(p, CONTEXT)
    assert rep["demoted"] is True and out["recommendation"] == "RESEARCH_MORE"
    monkeypatch.setenv(G.MODE_ENV, "record")
    out2, rep2 = G.apply_number_grounding(p, CONTEXT)
    assert rep2["verdict"] == "ungrounded" and rep2["demoted"] is False and out2 is p
    monkeypatch.setenv(G.MODE_ENV, "nonsense")
    assert G.mode() == "enforce"


def _load_report_script():
    key = "_tested_report_agent_number_grounding"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / "scripts" / "report_agent_number_grounding.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def test_report_summarises_stored_checks_by_agent():
    S = _load_report_script()
    rows = [
        ("maria", {"number_grounding": {"verdict": "grounded", "unsupported": []}}),
        ("maria", '{"number_grounding": {"verdict": "ungrounded", "demoted": true, "unsupported": ["$412.50", "27.3%"]}}'),
        ("risk_agent", {"number_grounding": {"verdict": "no_numbers"}}),
        ("steph", {"no_report": True}),
        ("steph", "not json"),
    ]
    rep = S.summarize(rows)
    assert rep["results"] == 3 and rep["ungrounded"] == 1 and rep["ungrounded_share"] == 0.333
    assert rep["agents"]["maria"]["demoted"] == 1 and rep["agents"]["maria"]["ungrounded_share"] == 0.5
    assert ("$412.50", 1) in rep["agents"]["maria"]["top_unsupported"]
    assert "steph" not in rep["agents"]


def test_missing_prompt_text_is_reported_not_guessed():
    p = _parsed("Price $412.50, target $520, up 27.3%.")
    out, rep = G.apply_number_grounding(p, "", mode_override="enforce")
    assert rep["verdict"] == "not_checked" and out is p


def test_thresholds_come_from_env(monkeypatch):
    monkeypatch.delenv(G.MIN_UNSUPPORTED_ENV, raising=False)
    monkeypatch.delenv(G.MAX_SHARE_ENV, raising=False)
    assert G.check_grounding(["x"], CONTEXT)["thresholds"] == {"min_unsupported": 3, "max_share": 0.5}
    monkeypatch.setenv(G.MIN_UNSUPPORTED_ENV, "5")
    r = G.check_grounding(["Price $412.50, target $520, up 27.3%."], CONTEXT)
    assert r["verdict"] == "grounded" and r["thresholds"]["min_unsupported"] == 5


def _load_resolver():
    key = "_tested_data_gap_resolver_grounding"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / "scripts" / "data_gap_resolver.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self, rows):
        self.calls, self._rows, self.rowcount = [], [rows], 1

    def execute(self, sql, params=None):
        self.calls.append((" ".join(str(sql).split()), params))

    def fetchall(self):
        return self._rows.pop(0) if self._rows else []


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits = cur, 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def test_gap_resolver_does_not_accept_a_demoted_result_as_proof():
    R = _load_resolver()
    cur = _Cur([(9, "SCHG", "stale_news", "gap_1", "completed", "res-gap_1", 0, True)])
    R.verify_dispatched(_Conn(cur), cur)
    sql = cur.calls[0][0]
    assert "'UNGROUNDED_NUMBERS' = ANY(r.reason_codes)" in sql
    updates = [s for s, _ in cur.calls if s.startswith("UPDATE data_gap_registry")]
    assert len(updates) == 1 and "status = 'open'" in updates[0]
    assert "unverified numbers" in cur.calls[-1][1][0]

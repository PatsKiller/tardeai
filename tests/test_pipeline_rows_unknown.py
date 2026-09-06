"""`rows_produced` must distinguish "produced nothing" from "nobody measured".

Measured 2026-09-06. `pipeline_zero_rows` was firing on five pipelines:

    cio_decision_engine            277 runs/24h   3,010 runs/7d
    symbol_enrichment              180 runs/24h   1,265 runs/7d
    process_watchlist_agent_jobs    44 runs/24h
    social_ingest                    2 runs/24h

Every one of them had **never** recorded a non-zero row count in its entire
history, and only 7 of 44 pipeline keys ever had. The pipelines were not broken.

`PipelineRun.__init__` set `self._rows = 0` and `run_complete` defaulted to 0, so
any caller that never calls `.rows()` writes `{"rows_produced": 0}` on every
successful run. 20 scripts use PipelineRun; 4 call `.rows()`.

So 0 meant both "I produced nothing" and "nobody told me". The alarm therefore
carried no information in either direction — it could not fire on a real outage
(indistinguishable from the standing noise) and could not stop firing on a
healthy pipeline. AGENTS.md: two states cannot express "no input".
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SRC = (ROOT / "scripts" / "pipeline_registry.py").read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


CODE = _code_only(SRC)


def test_run_complete_defaults_to_not_measured():
    """The exact defect: a default of 0 is a claim nobody made."""
    import pipeline_registry as pr

    sig = inspect.signature(pr.run_complete)
    assert sig.parameters["rows_processed"].default is None, (
        "defaulting to 0 makes every unreporting pipeline look like it produced nothing")


def test_the_context_manager_starts_unmeasured():
    import pipeline_registry as pr

    run = pr.PipelineRun.__new__(pr.PipelineRun)
    pr.PipelineRun.__init__(run, "probe")
    assert run._rows is None, "_rows must start unmeasured, not zero"


def test_calling_rows_records_the_value_including_a_real_zero():
    """A pipeline that measured and found nothing must still be able to say 0 —
    that is a real signal and must keep firing the alarm."""
    import pipeline_registry as pr

    run = pr.PipelineRun.__new__(pr.PipelineRun)
    pr.PipelineRun.__init__(run, "probe")
    run.rows(0)
    assert run._rows == 0
    run.rows(17)
    assert run._rows == 17


def test_no_zero_default_survives_in_source():
    """Guard against the default creeping back on either side."""
    assert "self._rows = 0" not in CODE
    assert "rows_processed: int = 0" not in CODE


def test_the_column_is_written_as_a_typed_bigint():
    """Untyped, psycopg sends None as SQL NULL but jsonb_build_object needs the
    cast to produce JSON null rather than erroring on an unknown type."""
    assert "'rows_produced', %s::bigint" in CODE


def test_cio_decision_engine_reports_its_count():
    """The loudest false positive — 3,010 runs in 7 days, none reporting."""
    src = (ROOT / "scripts" / "cio_decision_engine.py").read_text(encoding="utf-8")
    code = _code_only(src)
    assert "_run.rows(len(decisions))" in code, (
        "the engine builds decisions and must report how many")

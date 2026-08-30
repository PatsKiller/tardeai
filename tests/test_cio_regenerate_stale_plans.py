"""Regeneration must refuse to run against no evidence.

`augment_multi_domain_evidence` is fail-soft: with no Data Broker snapshot it
silently refreshes nothing. A regeneration tool built on top would then rewrite
every plan back to the same stale numbers and report success — which happened
three times while developing this, because running from a tree without data/
makes `lib.data_broker` resolve somewhere empty.

A domain COUNT is not a sufficient check: that empty tree still returns 18
domains, with empty bodies. The precondition has to be the field the tool
actually consumes.
"""
import re
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "scripts" / "cio_regenerate_stale_plans.py"


def _src():
    return TOOL.read_text(encoding="utf-8")


def test_it_checks_the_field_it_depends_on_not_just_domain_count():
    s = _src()
    assert "cash_buying_power" in s
    assert "total_cash" in s
    assert "isinstance(_cash, (int, float))" in s


def test_it_exits_nonzero_when_evidence_is_missing():
    assert re.search(r"refusing to regenerate", _src())
    assert "return 2" in _src()


def test_it_clears_the_old_narrative_before_rebuilding():
    """The builder folds existing_summary forward; regenerating in place left
    the previous multi-domain line, stale cash and all, inside `summary`."""
    s = _src()
    assert "scratch" in s
    assert re.search(r'for _f in \("summary", "multi_domain_summary", "thesis_alignment"\)', s)


def test_it_reverifies_after_regenerating():
    """The receipt must not overstate what it fixed."""
    s = _src()
    assert "after = _blocked(fresh)" in s
    assert "still_blocked" in s


def test_llm_narratives_are_skipped_by_default():
    s = _src()
    assert "--include-llm" in s
    assert "skipped_llm" in s


def test_it_is_dry_run_by_default():
    s = _src()
    assert '"--apply", action="store_true"' in s
    assert "store = CIOPlanStore() if args.apply else None" in s


def test_it_documents_the_cwd_requirement():
    """CIOPlanStore uses a relative path; the mistake was made twice on 2026-08-30."""
    assert "cwd MUST be the served release" in _src()

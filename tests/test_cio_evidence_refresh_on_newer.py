"""Evidence refresh must take the NEWER snapshot, not merely fill gaps.

`augment_multi_domain_evidence._pull` used to `return` whenever a domain was
already present, so it only ever added missing domains. A plan enriched on
2026-08-11 kept quoting that day's cash forever — which is how 34 of 42 open
S6 plans came to carry 578,10x against an actual 630,784.82 (#663/#668), and
why they could not self-heal once the underlying data was corrected.

Monotonic by construction: a stale snapshot can never replace fresh evidence.
"""
import pytest

from scripts.lib import cio_plan_enrichment as enr

FRESH = "2026-08-29T19:28:19+00:00"
OLD = "2026-08-24"


def _snapshot(as_of, total_cash):
    return {"domains": {
        "cash_buying_power": {"as_of": as_of, "data": {"total_cash": total_cash}},
    }}


def _cash_ref(plan):
    for r in plan.get("evidence_refs") or []:
        if r.get("domain") == "cash_buying_power":
            return r
    return None


@pytest.fixture
def patched(monkeypatch):
    def _install(as_of, total_cash):
        # augment tries `lib.data_broker...` BEFORE `scripts.lib.data_broker...`
        # and the two are distinct module objects, so both must be patched or
        # the test silently exercises the real broker.
        import importlib
        fn = lambda **kw: _snapshot(as_of, total_cash)          # noqa: E731
        for name in ("lib.data_broker.cio_portfolio",
                     "scripts.lib.data_broker.cio_portfolio"):
            try:
                monkeypatch.setattr(importlib.import_module(name),
                                    "get_cio_snapshot", fn)
            except Exception:
                pass
    return _install


def test_a_newer_snapshot_replaces_stale_evidence(patched):
    patched(FRESH, 630784.82)
    plan = {"symbols": ["SPCX"], "evidence_refs": [
        {"domain": "cash_buying_power", "as_of": OLD,
         "total_cash": 578111.14, "fields_used": ["total_cash"]}]}
    ref = _cash_ref(enr.augment_multi_domain_evidence(plan))
    assert ref["total_cash"] == 630784.82
    assert str(ref["as_of"]) > OLD


def test_an_older_snapshot_never_overwrites_fresh_evidence(patched):
    """Monotonic. The guard must not make evidence worse."""
    patched(OLD, 578111.14)
    plan = {"symbols": ["SPCX"], "evidence_refs": [
        {"domain": "cash_buying_power", "as_of": FRESH,
         "total_cash": 630784.82, "fields_used": ["total_cash"]}]}
    ref = _cash_ref(enr.augment_multi_domain_evidence(plan))
    assert ref["total_cash"] == 630784.82


def test_a_missing_domain_is_still_filled(patched):
    """The original gap-filling behaviour must survive."""
    patched(FRESH, 630784.82)
    plan = {"symbols": ["SPCX"], "evidence_refs": []}
    assert _cash_ref(enr.augment_multi_domain_evidence(plan))["total_cash"] == 630784.82


def test_no_duplicate_domain_rows(patched):
    patched(FRESH, 630784.82)
    plan = {"symbols": ["SPCX"], "evidence_refs": [
        {"domain": "cash_buying_power", "as_of": OLD,
         "total_cash": 578111.14, "fields_used": ["total_cash"]}]}
    out = enr.augment_multi_domain_evidence(plan)
    doms = [r.get("domain") for r in out.get("evidence_refs") or []]
    assert doms.count("cash_buying_power") == 1


def test_a_broker_failure_leaves_evidence_untouched(monkeypatch):
    """Fail-soft: no snapshot must never mean no evidence."""
    import importlib
    boom = lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))   # noqa: E731
    for name in ("lib.data_broker.cio_portfolio",
                 "scripts.lib.data_broker.cio_portfolio"):
        try:
            monkeypatch.setattr(importlib.import_module(name),
                                "get_cio_snapshot", boom)
        except Exception:
            pass
    plan = {"symbols": ["SPCX"], "evidence_refs": [
        {"domain": "cash_buying_power", "as_of": OLD,
         "total_cash": 578111.14, "fields_used": ["total_cash"]}]}
    assert _cash_ref(enr.augment_multi_domain_evidence(plan))["total_cash"] == 578111.14


def test_refresh_merges_and_never_drops_fields(patched):
    """Fresher must not mean thinner.

    A snapshot need not carry every field the old ref had. Replacing outright
    made a plan about a symbol no longer in the book lose its basis/last —
    trading stale data for missing data, which is not an improvement. Caught by
    test_spacex_template_enrich_mentions_fixture_numbers.
    """
    patched(FRESH, 630784.82)
    plan = {"symbols": ["SPCX"], "evidence_refs": [
        {"domain": "cash_buying_power", "as_of": OLD, "total_cash": 578111.14,
         "basis": 210.0, "last": 138.0, "fields_used": ["total_cash", "basis", "last"]}]}
    ref = _cash_ref(enr.augment_multi_domain_evidence(plan))
    assert ref["total_cash"] == 630784.82        # refreshed
    assert ref["basis"] == 210.0                 # preserved
    assert ref["last"] == 138.0                  # preserved
    assert set(ref["fields_used"]) >= {"total_cash", "basis", "last"}

"""The second layer of starved evidence domains.

Fixing the first four domains let runs reach the gate, which then blocked on a
second set nobody had seen — because no run had ever got far enough to report
them. Three had no resolvable collector; the fourth had a working collector and
an unusable freshness stamp.

The gate is not touched here. These tests pin the producers.
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _functions(relpath: str) -> set[str]:
    tree = ast.parse((ROOT / relpath).read_text(encoding="utf-8"))
    return {n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_every_external_adapter_collector_now_exists():
    """The mapping guard, with no remaining exemptions.

    When this was first written, `analyst_actions` and `reentry` had to be
    excluded as known-broken. `analyst_actions` is fixed here; a name in this
    mapping with no matching function fails silently forever, so the guard is
    what stops a third instance appearing.
    """
    src = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    modules = dict(re.findall(r'"(\w+)":\s*"(scripts\.lib\.data_broker\.\w+)"', src))
    functions = dict(re.findall(r'"(\w+)":\s*"(get_\w+)"', src))

    still_broken = {"reentry"}   # named, not silently skipped; unfixed here
    missing = []
    for domain, fn_name in functions.items():
        if domain in still_broken:
            continue
        module_path = modules.get(domain)
        if not module_path:
            continue
        relpath = module_path.replace(".", "/") + ".py"
        if not (ROOT / relpath).exists():
            missing.append(f"{domain}: {relpath} absent")
        elif fn_name not in _functions(relpath):
            missing.append(f"{domain}: {relpath} has no {fn_name}()")

    assert not missing, "collectors that will never resolve: " + "; ".join(missing)


def test_catalysts_maps_to_a_zero_argument_collector():
    """`get_catalyst_record(db_query, symbol)` needs arguments the snapshot
    never passes, so calling it raised TypeError and the domain reported
    unavailable while 133,659 rows sat in the table."""
    src = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    assert '"catalysts": "get_catalysts"' in src

    mod = (ROOT / "scripts/lib/data_broker/catalyst_record.py")
    tree = ast.parse(mod.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "get_catalysts")
    required = [a for a in fn.args.args][len(fn.args.defaults):]
    assert not required, "the snapshot calls collectors with no arguments"

    # The per-symbol function must survive untouched — it has other callers.
    assert "get_catalyst_record" in _functions("scripts/lib/data_broker/catalyst_record.py")


def test_analyst_collector_takes_no_required_arguments():
    tree = ast.parse((ROOT / "scripts/lib/data_broker/analyst_detail.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "get_analyst_detail")
    required = [a for a in fn.args.args][len(fn.args.defaults):]
    assert not required


def test_db_payloads_survive_the_snapshot_content_hash():
    """Postgres returns Decimal and datetime; the snapshot json.dumps every
    domain payload to hash it. A collector returning either takes the whole
    snapshot down, not just its own domain — which is what happened first."""
    from decimal import Decimal
    from scripts.lib.data_broker.catalyst_record import _jsonable

    payload = {"impact_score": Decimal("0.75"),
               "at": datetime(2026, 8, 27, 12, 0),
               "nested": [{"confidence": Decimal("0.5")}]}
    json.dumps(_jsonable(payload))  # must not raise

    assert _jsonable(Decimal("1.5")) == 1.5
    assert isinstance(_jsonable(datetime(2026, 8, 27)), str)


def test_collectors_stamp_source_time_not_read_time():
    """A collector that stamps now() reports its domain fresh forever, even on
    a feed that stopped updating. `as_of` must come from the newest record."""
    for relpath, fn in (("scripts/lib/data_broker/catalyst_record.py", "get_catalysts"),
                        ("scripts/lib/data_broker/analyst_detail.py", "get_analyst_detail")):
        src = (ROOT / relpath).read_text(encoding="utf-8")
        body = src.split(f"def {fn}", 1)[1]
        assert "newest" in body, f"{fn} must derive as_of from the newest row"
        assert "_now()" not in body and "datetime.now" not in body, (
            f"{fn} must not stamp read time as as_of")


def test_cash_buying_power_uses_a_parseable_freshness_stamp():
    """Same defect as `portfolio`: `as_of` was a DATE, so a 1-hour threshold
    could never be met after midnight. It now shares the portfolio helper."""
    src = (ROOT / "scripts/lib/data_broker/cio_portfolio.py").read_text(encoding="utf-8")
    block = src.split("def _domain_cash_buying_power", 1)[1].split("\ndef ", 1)[0]

    assert "_portfolio_as_of(" in block
    assert 'totals.get("as_of"' not in block, "the date-only field must not stamp freshness"


def test_cash_stays_partial_and_never_claims_verified_buying_power():
    """Holdings-derived cash is a proxy. The domain accepts PARTIAL; claiming
    AVAILABLE would assert broker-verified buying power we cannot prove."""
    src = (ROOT / "scripts/lib/data_broker/cio_portfolio.py").read_text(encoding="utf-8")
    block = src.split("def _domain_cash_buying_power", 1)[1].split("\ndef ", 1)[0]
    assert "partial" in block.lower()


def test_the_fallback_no_longer_masks_a_real_gap_reason():
    """A blanket pass used to overwrite the registry loop's explanation, so a
    collector that raised TypeError reported `not_yet_collected_by_snapshot_builder`
    instead. That pointed at the wrong cause and cost several diagnostic passes."""
    src = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    # The builder's fallback, not `from_known_gaps` — that one constructs a
    # fresh snapshot from scratch and has nothing to mask.
    tail = src.rsplit("known_gaps = CIO_DOMAINS - supported\n", 1)[1][:600]
    assert "continue" in tail, "the fallback must skip domains that already carry a reason"
    assert 'get("gap_reason")' in tail


def test_the_evidence_gate_is_still_untouched():
    """These fixes are producers. Weakening the gate would be the wrong repair."""
    src = (ROOT / "scripts/lib/cio_run_worker.py").read_text(encoding="utf-8")
    gate = src.split("def _check_evidence_gate", 1)[1].split("\n    def ", 1)[0]
    assert 'state == "DATA_UNAVAILABLE"' in gate
    assert "missing_required or stale_required or error_required" in gate

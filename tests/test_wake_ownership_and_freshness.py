"""Phase 3 (wake ownership) and Phase 4 (freshness), at the behaviour level.

Phase 3: 1,282 wakes were claimed and dispatched; 55 ever became runs. The
reactive cycle builds its dispatcher without a `run_store`, and
`poll_and_dispatch` only calls `create_run()` when one is injected — so it
consumed the queue and produced nothing, leaving the cron entrypoint (which does
carry a run_store) with `dispatched=0`. That, not identity, is why
`HERMES_RESOLVED` has zero occurrences: the trigger cannot fire on a run that is
never created.

Phase 4: an unparseable `as_of` used to leave a domain AVAILABLE forever.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── Phase 3 — the reactive cycle must not claim wakes ──────────────────────

def test_the_reactive_cycle_does_not_claim_wakes_by_default():
    """It enqueues; the documented sole claimant dispatches.

    Asserted on the resolved default of the real function, not on source text.
    """
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import cio_reactive_cycle

    sig = inspect.signature(cio_reactive_cycle.run_once)
    assert sig.parameters["dispatch"].default is False, (
        "a dispatcher without a run_store consumes wakes and creates nothing")


def test_dispatching_remains_available_as_an_explicit_opt_in():
    src = (ROOT / "scripts/cio_reactive_cycle.py").read_text(encoding="utf-8")
    assert '"--dispatch"' in src, "manual dispatch must still be reachable"


def test_only_a_dispatcher_with_a_run_store_creates_runs():
    """The asymmetry that made the leak silent.

    `poll_and_dispatch` marks a wake dispatched either way; it only creates a run
    when a run_store was injected. So a runless caller looks successful.
    """
    src = (ROOT / "scripts/lib/cio_wake_dispatcher.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded = any(
        isinstance(n, ast.If)
        and "run_store" in ast.dump(n.test)
        and "create_run" in ast.dump(n)
        for n in ast.walk(tree)
    )
    assert guarded, "run creation must remain conditional on run_store; this test documents why"


# ── Phase 4 — freshness must fail closed on a parse failure ────────────────

def test_an_unparseable_stamp_is_stale_not_available(monkeypatch):
    """The named trap, exercised — not read.

    `"%Y-%m-%d %H:%M:%S ET"` is holdings.json's own format and `fromisoformat`
    cannot read it, so this is a live format. A six-year-old unparseable stamp
    previously produced AVAILABLE while the same age parseable produced STALE.
    """
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib import cio_financial_snapshot as mod
    import scripts.lib.data_broker.cio_portfolio as cp

    # One collector, one domain, an ancient stamp in the live ET format.
    monkeypatch.setitem(cp._COLLECTORS, "sectors",
                        lambda: {"state": "AVAILABLE", "as_of": "2020-01-01 00:00:00 ET"})
    snap = mod.build_canonical_snapshot()
    assert snap.get_domain_state("sectors") == "STALE", (
        "an unreadable age is not a young age")

    # Control: the same age, parseable, must also be STALE — so the verdict is
    # about the age, not about the parse having failed.
    monkeypatch.setitem(cp._COLLECTORS, "sectors",
                        lambda: {"state": "AVAILABLE", "as_of": "2020-01-01T00:00:00+00:00"})
    assert mod.build_canonical_snapshot().get_domain_state("sectors") == "STALE"

    # And a genuinely fresh parseable stamp must still pass.
    fresh = datetime.now(timezone.utc).isoformat()
    monkeypatch.setitem(cp._COLLECTORS, "sectors",
                        lambda: {"state": "AVAILABLE", "as_of": fresh})
    assert mod.build_canonical_snapshot().get_domain_state("sectors") == "AVAILABLE"


def test_a_missing_stamp_is_flagged_rather_than_blocked():
    """12 domains carry no stamp, four of them required by passing purposes.

    Blocking them would be a silent gate change; flagging makes it visible and
    leaves the decision with the operator.
    """
    src = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    assert "freshness_unverified" in src
    assert 'rec["freshness_unverified"] = True' in src
    # It must NOT coerce state.
    block = src.split("freshness_unverified = ", 1)[1][:400]
    assert 'quality_state = "STALE"' not in block


def test_holdings_detail_no_longer_stamps_freshness_from_a_date():
    """The one-of-two fix: `_portfolio_as_of` was applied to `_domain_portfolio`
    only, while `_domain_holdings_detail` in the same file kept the date-only
    field and reported STALE against 0.6h-old data."""
    src = (ROOT / "scripts/lib/data_broker/cio_portfolio.py").read_text(encoding="utf-8")
    n = src.index("def _domain_holdings_detail")
    block = src[n:src.index("\ndef ", n + 10)]
    assert "_portfolio_as_of(" in block
    assert '"as_of": holdings.get("as_of", "")' not in block
    assert '"positions_as_of"' in block, "the underlying date must stay visible"


def test_the_portfolio_as_of_helper_still_falls_back_conservatively():
    """Anything unconvertible must fall back to the date, which ages out and
    blocks — never to `now`."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib.data_broker.cio_portfolio import _portfolio_as_of

    assert _portfolio_as_of({"generated_at": "garbage"}, {"as_of": "2026-08-26"}) == "2026-08-26"
    assert _portfolio_as_of({}, {"as_of": "2026-08-26"}) == "2026-08-26"
    good = _portfolio_as_of({"generated_at": "2026-08-27 16:45:02 ET"}, {})
    assert datetime.fromisoformat(good).tzinfo is not None

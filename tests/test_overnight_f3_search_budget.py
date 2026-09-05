"""WAVE F3 — per-provider search budget survives process.

Rails:
  * check BEFORE call; return empty / deny when over
  * never fail open (corrupt or unreadable ledger → DENY)
  * daily + monthly per provider
  * durable file under production_state_root/data/runtime — survives cron
  * concurrent processes cannot both spend the last unit (flocked try_consume)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import search_budget as sb

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


# ── durable path ───────────────────────────────────────────────────────────

def test_ledger_path_is_under_runtime_not_a_release_checkout():
    """STORE SET: data/runtime via production_state_root — not portfolio-server/."""
    p = sb.budget_path()
    assert p.as_posix().endswith("data/runtime/search_budget.json")
    assert "portfolio-server/" not in p.as_posix()


def test_budget_path_honours_explicit_root(tmp_path: Path):
    p = sb.budget_path(tmp_path)
    assert p == tmp_path / "data" / "runtime" / "search_budget.json"


# ── never fail open ────────────────────────────────────────────────────────

def test_corrupt_ledger_denies_check_and_try_consume(tmp_path: Path):
    ledger = sb.budget_path(tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{ not json", encoding="utf-8")

    with pytest.raises(sb.BudgetUnavailable):
        sb.status("brave", root=tmp_path)

    v = sb.check("brave", root=tmp_path)
    assert v["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in v["reason"]
    assert v.get("fail_open") is False

    c = sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)
    assert c["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in c["reason"]


def test_record_refuses_to_rebuild_a_corrupt_ledger_as_zeros(tmp_path: Path):
    """The old write path reset an unreadable ledger to {} and overwrote it —
    fail-open on the record side. F3: skip the write; bytes stay corrupt."""
    ledger = sb.budget_path(tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    junk = "{ not json"
    ledger.write_text(junk, encoding="utf-8")

    sb.record("brave", allowed=True, caller="f3", now=NOW, root=tmp_path)
    assert ledger.read_text(encoding="utf-8") == junk


# ── per provider daily + monthly ───────────────────────────────────────────

def test_providers_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "2")
    for _ in range(2):
        assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["allowed"]
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["reason"] == "DAILY_EXHAUSTED"
    # tavily untouched
    assert sb.check("tavily", now=NOW, root=tmp_path)["allowed"] is True
    assert sb.status("tavily", now=NOW, root=tmp_path)["monthly_used"] == 0


def test_monthly_cap_binds_when_daily_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "2")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "100")
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["allowed"]
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["allowed"]
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["reason"] == "MONTHLY_EXHAUSTED"


# ── survives process (fresh interpreter) ───────────────────────────────────

def test_counts_survive_a_fresh_python_process(tmp_path: Path):
    """Cron starts a new process every invocation. In-memory state is gone;
    only the durable file under data/runtime survives."""
    first = sb.try_consume("brave", caller="cron_a", now=NOW, root=tmp_path)
    assert first["allowed"] is True
    ledger = sb.budget_path(tmp_path)
    assert ledger.is_file()

    # Fresh interpreter, same root — must see the prior consume.
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    code = (
        "from pathlib import Path\n"
        "from datetime import datetime, timezone\n"
        "from scripts.lib import search_budget as sb\n"
        f"root = Path({str(tmp_path)!r})\n"
        "now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)\n"
        "st = sb.status('brave', now=now, root=root)\n"
        "print(st['monthly_used'], st['daily_used'], st['ledger_path'])\n"
        "assert st['monthly_used'] == 1 and st['daily_used'] == 1\n"
        "assert 'data/runtime/search_budget.json' in st['ledger_path']\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().startswith("1 1")


def test_try_consume_serializes_last_unit_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two processes racing the last unit: exactly one may spend."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "1")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "100")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    root_s = str(tmp_path)
    code = (
        "from pathlib import Path\n"
        "from datetime import datetime, timezone\n"
        "from scripts.lib import search_budget as sb\n"
        f"root = Path({root_s!r})\n"
        "now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)\n"
        "v = sb.try_consume('brave', caller='race', now=now, root=root)\n"
        "print('ALLOW' if v['allowed'] else 'DENY')\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outcomes = []
    for p in procs:
        out, err = p.communicate(timeout=30)
        assert p.returncode == 0, err
        outcomes.append(out.strip())
    assert outcomes.count("ALLOW") == 1, outcomes
    assert outcomes.count("DENY") == 1, outcomes
    assert sb.status("brave", now=NOW, root=tmp_path)["daily_used"] == 1


# ── representative caller: brave_search never fail-open on missing shared ──

def test_brave_search_source_denies_when_shared_unavailable():
    """Representative caller wire (F3): ImportError of the shared module must
    DENY — not assign ``_shared_check = None`` and fall through to a
    release-relative local ledger.

    Retargeted from `_check_budget` to `_reserve`. The client no longer checks
    and then separately records: it reserves atomically through `try_consume`,
    because check-then-call-then-record let two processes both observe an
    under-limit counter and both spend. The fail-closed property this test
    exists for is unchanged and now lives in the reservation.
    """
    src = (ROOT / "scripts" / "brave_search.py").read_text(encoding="utf-8")
    assert "def _check_budget" not in src, (
        "the check-then-record path returned; it is the check-to-use gap")
    body = src.split("def _reserve", 1)[1].split("def _refund", 1)[0]
    assert "never fail open" in body
    assert "_shared_check = None" not in body
    assert "shared budget unavailable" in body
    # The shared ledger is mandatory: the verdict is consulted unconditionally.
    assert 'try_consume("brave"' in body


def test_every_brave_failure_path_refunds():
    """A reservation is taken BEFORE the request, so each way out that does not
    make a successful call must give the unit back — otherwise the ledger
    charges for work that never happened."""
    src = (ROOT / "scripts" / "brave_search.py").read_text(encoding="utf-8")
    for fn in ("def search(", "def search_news("):
        body = src.split(fn, 1)[1].split("\ndef ", 1)[0]
        assert "_reserve(caller)" in body, f"{fn} does not reserve"
        # missing-key path and exception path both refund
        assert body.count("_refund(caller)") >= 2, (
            f"{fn} has {body.count('_refund(caller)')} refund sites; "
            "the missing-key path and the exception path both need one")


def test_guard_returns_false_when_over_so_callers_return_empty(tmp_path: Path, monkeypatch):
    """Call-site contract: over budget → guard False → caller returns []."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    assert sb.guard("brave", "f3", now=NOW, root=tmp_path) is False
    # A denied attempt is counted under denied_today, not as spend.
    st = sb.status("brave", now=NOW, root=tmp_path)
    assert st["daily_used"] == 0
    assert st["denied_today"] == 1


# ── Monthly reserve: on-demand callers may not be starved by cron ────────────
# Added 2026-09-05 with the ceiling raise (25/850 -> 120/1500). A denied Brave
# call is not a downgrade: brave_search.py returns False and the research is
# lost, because no fallback provider is wired behind a refusal. So a scheduled
# bulk job must not be able to consume the allowance an interactive query needs.

def test_on_demand_caller_may_draw_on_the_reserve(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "1000")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "10000")
    assert sb.effective_monthly_limit("brave", "web_research", 1000) == 1000


def test_scheduled_caller_stops_at_the_reserve_line(tmp_path: Path):
    eff = sb.effective_monthly_limit("brave", "some_cron_job", 1000)
    assert eff == 1000 - sb.reserve_for("brave", 1000)
    assert eff < 1000, "a scheduled caller must not reach the full ceiling"


def test_reserve_refusal_is_distinguishable_from_exhaustion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """MONTHLY_RESERVE_ONLY means 'a manual query would still go out'.

    Collapsing it into MONTHLY_EXHAUSTED would tell an operator the month was
    spent when in fact only the bulk allowance was.
    """
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "10")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "10000")
    # reserve is capped at a fifth => 2 held back, bulk ceiling is 8.
    for _ in range(8):
        assert sb.try_consume("brave", caller="cron", now=NOW, root=tmp_path)["allowed"]
    denied = sb.try_consume("brave", caller="cron", now=NOW, root=tmp_path)
    assert denied["allowed"] is False
    assert denied["reason"] == "MONTHLY_RESERVE_ONLY"
    # ...and the on-demand caller still gets through, which is the whole point.
    assert sb.try_consume("brave", caller="web_research", now=NOW, root=tmp_path)["allowed"]


def test_reserve_can_never_starve_the_whole_budget(tmp_path: Path):
    """NEGATIVE CONTROL for a bug this suite caught during the ceiling raise.

    The reserve was first written as a flat 200 subtracted from the configured
    monthly limit. `SEARCH_BUDGET_BRAVE_MONTHLY=150` then produced an effective
    ceiling of zero: every scheduled call denied, while the ledger reported 0
    used of 150. A provider switched off by a config value that reads as
    caution. The reserve is now capped at a fifth of the budget it comes from.
    """
    for limit in (1, 2, 10, 150, 199, 1000, 1500):
        eff = sb.effective_monthly_limit("brave", "cron", limit)
        assert eff > 0 or limit == 0, f"limit {limit} left no bulk allowance at all"
        assert sb.reserve_for("brave", limit) <= limit // sb.RESERVE_MAX_SHARE
        assert eff <= limit


def test_unknown_caller_is_treated_as_scheduled(tmp_path: Path):
    """Fail closed: an unrecognised caller does not get the reserve."""
    assert sb.effective_monthly_limit("brave", "who_is_this", 1000) < 1000


def test_l2_ledger_resolves_through_the_canonical_state_root(tmp_path: Path):
    """Every tree must resolve the SAME L2 ledger.

    `brave_search._BUDGET_FILE` was `Path(__file__).parent.parent / data/...`,
    so the server (running from a release dir) and cron (running from the dev
    tree) each kept a private counter and each enforced the ceiling against a
    fraction of the traffic. Eight copies of that basename exist on that host.

    The first version of this test asserted the ledger was NOT under the
    importing source tree. That passed locally and failed in CI, correctly: on a
    runner the canonical state root can itself resolve inside the checkout, so
    "outside the tree" is a property of the machine, not of the code. It was
    pinning the environment.

    What actually matters, and holds everywhere, is that the path is CONSTRUCTED
    from the shared canonical root rather than from this module's own location.
    """
    import brave_search as b
    from scripts.lib.search_budget import _state_root, budget_path

    root = _state_root()
    assert b._BUDGET_FILE == root / "data" / "portfolios" / "state" / "brave_search_budget.json"
    assert budget_path().is_relative_to(root)


def test_l2_ledger_path_is_not_built_from_this_modules_location():
    """The source-level half: no `Path(__file__)`-derived budget path.

    Complements the resolution test above, which cannot tell a correct
    construction from a coincidence when the canonical root happens to sit
    inside the checkout — exactly the CI case.
    """
    import ast
    import inspect
    import textwrap

    import brave_search as b

    # The docstring QUOTES the old defect, so scan the code body only — a
    # substring check over the raw source would flag the very comment that
    # explains why the defect is gone.
    fn = ast.parse(textwrap.dedent(inspect.getsource(b._budget_file))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]                      # drop the docstring
    code = ast.unparse(ast.Module(body=fn.body, type_ignores=[]))

    assert "__file__" not in code, (
        "_budget_file() derives the ledger path from this module's location — "
        "that is the defect that gave every importing tree a private counter")
    assert "_state_root" in code


# ── One ledger: caller caps moved here, refunds added ───────────────────────
# The second ledger (brave_search_budget.json) counted for exactly one reason —
# it held CALLER_CAPS. Counting in two places is what let them disagree: they
# matched exactly (52 each) through 2026-09-04 and parted by six on 09-05.

def test_caller_daily_cap_binds_in_the_canonical_ledger(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "10000")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "10000")
    cap = sb.caller_daily_cap("topic_ingestion")
    for _ in range(cap):
        assert sb.try_consume("brave", caller="topic_ingestion", now=NOW,
                              root=tmp_path)["allowed"]
    blocked = sb.try_consume("brave", caller="topic_ingestion", now=NOW, root=tmp_path)
    assert blocked["allowed"] is False
    assert blocked["reason"] == "CALLER_DAILY_CAP"


def test_one_callers_cap_does_not_bind_another(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "10000")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "10000")
    for _ in range(sb.caller_daily_cap("topic_ingestion")):
        sb.try_consume("brave", caller="topic_ingestion", now=NOW, root=tmp_path)
    assert sb.try_consume("brave", caller="web_research", now=NOW, root=tmp_path)["allowed"]


def test_an_unknown_caller_gets_the_default_cap(tmp_path: Path):
    assert sb.caller_daily_cap("never_seen_before") == sb.CALLER_DAILY_CAPS["default"]


def test_refund_returns_exactly_one_unit(tmp_path: Path):
    sb.try_consume("brave", caller="web_research", now=NOW, root=tmp_path)
    before = sb.status("brave", now=NOW, root=tmp_path)["monthly_used"]
    assert sb.refund("brave", caller="web_research", now=NOW, root=tmp_path) is True
    after = sb.status("brave", now=NOW, root=tmp_path)["monthly_used"]
    assert after == before - 1


def test_refund_never_invents_credit(tmp_path: Path):
    """A refund with nothing recorded is the same error class as an invented
    provider limit: a number produced from no observation."""
    assert sb.refund("brave", caller="web_research", now=NOW, root=tmp_path) is False
    assert sb.status("brave", now=NOW, root=tmp_path)["monthly_used"] == 0
    sb.try_consume("brave", caller="web_research", now=NOW, root=tmp_path)
    assert sb.refund("brave", caller="web_research", now=NOW, root=tmp_path) is True
    assert sb.refund("brave", caller="web_research", now=NOW, root=tmp_path) is False
    assert sb.status("brave", now=NOW, root=tmp_path)["monthly_used"] == 0


def test_a_refund_is_not_recorded_as_a_denial(tmp_path: Path):
    """Denial history answers 'did the budget refuse us'. A refund is the budget
    agreeing and the request failing; conflating them ruins that history."""
    import json
    sb.try_consume("brave", caller="web_research", now=NOW, root=tmp_path)
    sb.refund("brave", caller="web_research", now=NOW, root=tmp_path)
    doc = json.loads(sb.budget_path(tmp_path).read_text())
    p = doc["providers"]["brave"]
    day = NOW.strftime("%Y-%m-%d")
    assert int((p.get("refunds") or {}).get(day, 0)) == 1
    assert int((p.get("denied") or {}).get(day, 0)) == 0


def test_refund_frees_the_callers_cap_too(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch):
    """Or a caller that fails its whole allowance is locked out for the day
    having made no successful call."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "10000")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "10000")
    cap = sb.caller_daily_cap("topic_ingestion")
    for _ in range(cap):
        sb.try_consume("brave", caller="topic_ingestion", now=NOW, root=tmp_path)
    assert sb.try_consume("brave", caller="topic_ingestion", now=NOW,
                          root=tmp_path)["reason"] == "CALLER_DAILY_CAP"
    sb.refund("brave", caller="topic_ingestion", now=NOW, root=tmp_path)
    assert sb.try_consume("brave", caller="topic_ingestion", now=NOW,
                          root=tmp_path)["allowed"] is True


def test_refund_on_a_corrupt_ledger_returns_false_and_does_not_rebuild(tmp_path: Path):
    p = sb.budget_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert sb.refund("brave", caller="web_research", now=NOW, root=tmp_path) is False
    assert p.read_text() == "{not json"


def test_brave_client_has_no_live_writer_for_the_retired_ledger():
    """The retired ledger must have no live write path left in the client."""
    import inspect

    import brave_search as b

    src = inspect.getsource(b)
    live = [ln for ln in src.splitlines()
            if "_save_budget(" in ln and not ln.strip().startswith("#")]
    assert live == [], f"the retired ledger still has a writer: {live}"
    assert b._record_call("web_research") is None


def test_the_alarm_sensor_reads_the_binding_ledger():
    """The 2026-08-30 failure was an alarm computing a percentage from a counter
    that saw a fraction of the traffic. It must read the one that binds."""
    import brave_search as b

    st = b.get_budget_status()
    assert "search_budget.json" in st["source"]
    assert st["monthly_limit"] == sb.DEFAULT_LIMITS["brave"]["monthly"]
    assert st["daily_limit"] == sb.DEFAULT_LIMITS["brave"]["daily"]

"""A budget decision must not be reported as a server fault.

MEASURED 2026-09-06. The paid DeepSeek lane returned HTTP 500 to every caller
for 50 minutes. The body said:

    {"code": "RESERVATION_FAILED", "status": 500,
     "message": "COST_CAP_EXCEEDED: daily request cap"}

Three separate defects stacked into one outage, and each one hid the next.

1. THE CODE WAS FLATTENED.
   `reserve_projected_cost()` raises RuntimeError("<MACHINE_CODE>: detail") for
   every governance outcome. The bridge caught all of them and returned
   RESERVATION_FAILED/500. `classify_failure()` lists RESERVATION_FAILED under
   RETRYABLE_TRANSIENT — so a hard cap breach was handed to callers carrying a
   retry policy that says "retry this".

   This is not merely a cosmetic mislabel. The request-count cap is enforced
   ONLY inside reserve_projected_cost; the check_cost_cap() pre-flight covers
   dollar caps alone and has the correct 429 path. So before this change there
   was no route by which a count breach could be reported as anything but a
   server fault.

2. THE TRACEBACK WAS DISCARDED.
   The `except Exception` arm kept only `type(e).__name__`. 2.7 MB of bridge log
   held ZERO tracebacks while every request failed.

3. THE CALLER SPENT ITS QUEUE ON IT.
   hermes_external_feedback_loop caught every exception and `continue`d, so it
   consumed all 46,106 remaining rows marking them FAILED_PROVIDER in minutes.
   Nothing was charged, but the run reported a result as though it had finished.

No database and no network: the reservation is stubbed, and only the pure
classification and control-flow logic is exercised.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

def _codes_raised_by_reservation() -> set[str]:
    """The machine codes reserve_projected_cost() actually raises.

    Parsed from the AST rather than grepped: a code added in a new raise must
    show up here automatically, which is what makes the coverage test below
    catch the next omission instead of the last one.
    """
    src = (ROOT / "scripts" / "lib" / "llm_consumption.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "reserve_projected_cost")
    return {
        node.exc.args[0].value.split(":")[0].strip()
        for node in ast.walk(fn)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and node.exc.args
        and isinstance(node.exc.args[0], ast.Constant)
        and isinstance(node.exc.args[0].value, str)
    }


BRIDGE_SRC = ROOT / "scripts" / "lib" / "cio_governed_model_bridge.py"
LOOP_SRC = ROOT / "scripts" / "hermes_external_feedback_loop.py"


# ── 1. the code survives, and carries the right status ──────────────────────

def test_cap_breach_maps_to_429_not_500():
    """429 is the whole point: it is what makes the refusal non-retryable."""
    from scripts.lib.cio_governed_model_bridge import _RESERVATION_CODE_STATUS

    assert _RESERVATION_CODE_STATUS["COST_CAP_EXCEEDED"] == 429


def test_a_ledger_outage_stays_retryable():
    """Not every reservation failure is terminal. A persistence blip should be
    retried; collapsing it into the same bucket as a cap would be the mirror
    image of the bug being fixed."""
    from scripts.lib.cio_governed_model_bridge import _RESERVATION_CODE_STATUS
    from scripts.lib.cio_provider_retry_v1 import classify_failure

    status = _RESERVATION_CODE_STATUS["COST_PERSISTENCE_UNAVAILABLE"]
    assert status == 503
    assert classify_failure("COST_PERSISTENCE_UNAVAILABLE", http_status=status)["retryable"] is True


def test_every_mapped_code_is_one_the_reservation_actually_raises():
    """A map keyed on codes nobody raises is decoration. Read the raise sites."""
    raised = _codes_raised_by_reservation()
    from scripts.lib.cio_governed_model_bridge import _RESERVATION_CODE_STATUS

    unknown = set(_RESERVATION_CODE_STATUS) - raised
    assert not unknown, f"mapped codes that are never raised: {unknown}"


def test_no_raised_code_is_left_unmapped():
    """The complement, and the one that matters: a code the reservation raises
    but the map omits falls through to RESERVATION_FAILED/500 — exactly the
    defect. This fails when someone adds a raise without a status."""
    raised = _codes_raised_by_reservation()
    from scripts.lib.cio_governed_model_bridge import _RESERVATION_CODE_STATUS

    assert not raised - set(_RESERVATION_CODE_STATUS), (
        f"raised but unmapped, will report as a server fault: "
        f"{raised - set(_RESERVATION_CODE_STATUS)}")


def test_the_old_behaviour_is_the_thing_being_prevented():
    """Documents WHY 500/RESERVATION_FAILED was harmful, so a future reader does
    not 'simplify' the map away. This asserts the retry library's own opinion."""
    from scripts.lib.cio_provider_retry_v1 import classify_failure

    assert classify_failure("RESERVATION_FAILED", http_status=500)["retryable"] is True
    assert classify_failure("COST_CAP_EXCEEDED", http_status=429)["retryable"] is False


# ── 2. the traceback is no longer discarded ─────────────────────────────────

def test_the_reservation_handler_logs_the_traceback():
    """The specific reason the bridge log had no tracebacks across 2.7 MB."""
    src = BRIDGE_SRC.read_text(encoding="utf-8")
    handler = src.split("except RuntimeError as e:", 1)[1].split("# Real provider calls", 1)[0]
    assert handler.count("log.exception") >= 2, (
        "an unmapped reservation failure still leaves no traceback")


def test_a_mapped_refusal_is_logged_without_a_traceback():
    """A cap is expected. Logging it at exception level would restore the noise
    this change removes — it should be a warning, and it must still be visible."""
    src = BRIDGE_SRC.read_text(encoding="utf-8")
    handler = src.split("except RuntimeError as e:", 1)[1].split("except Exception as e:", 1)[0]
    assert "log.warning" in handler


# ── 3. the caller stops instead of spending the queue ───────────────────────

@pytest.fixture(scope="module")
def loop():
    if not (ROOT / ".env").is_file():
        pytest.skip("module reads .env at import time")
    import hermes_external_feedback_loop as m

    return m


@pytest.mark.parametrize("message", [
    "bridge_flash_error:HTTPError:HTTP Error 429: Too Many Requests",
    'COST_CAP_EXCEEDED: daily request cap',
    "POLICY_NOT_ALLOWED: policy FAST not allowed",
])
def test_governance_refusals_are_terminal(loop, message):
    assert loop._is_terminal(message) is True


@pytest.mark.parametrize("message", [
    "HTTPError:HTTP Error 503: Service Unavailable",
    "ReadTimeout: timed out",
    "ConnectionResetError: [Errno 104]",
])
def test_genuine_transients_are_not_terminal(loop, message):
    """Over-broad matching would abort a run on one flaky connection."""
    assert loop._is_terminal(message) is False


def test_the_500_that_caused_the_incident_is_still_not_terminal(loop):
    """Deliberate. The bridge fix is what makes a cap a 429; this loop must not
    start treating every 500 as fatal, or a real transient outage would abort
    the run. The consecutive-failure guard is what covers that case instead."""
    assert loop._is_terminal("HTTPError:HTTP Error 500: Internal Server Error") is False


def test_a_terminal_failure_breaks_the_loop(loop, monkeypatch):
    """The 46,106-row burn, reproduced in miniature."""
    seen: list[int] = []

    def _rate(question, rec, dissent, outcome):
        seen.append(1)
        raise RuntimeError("COST_CAP_EXCEEDED: daily request cap")

    monkeypatch.setattr(loop, "_rate", _rate)
    _run_main(loop, monkeypatch, rows=50)
    assert len(seen) == 1, f"kept going after a terminal refusal: {len(seen)} attempts"


def test_a_flaky_provider_stops_after_the_configured_streak(loop, monkeypatch):
    """Defence in depth: even a failure the loop cannot classify must not cost
    the whole queue."""
    seen: list[int] = []

    def _rate(question, rec, dissent, outcome):
        seen.append(1)
        raise RuntimeError("HTTPError:HTTP Error 500: Internal Server Error")

    monkeypatch.setattr(loop, "_rate", _rate)
    _run_main(loop, monkeypatch, rows=500)
    assert len(seen) == loop.MAX_CONSECUTIVE_FAILURES


def test_an_intermittent_failure_does_not_stop_the_run(loop, monkeypatch):
    """The streak counter must reset on success, or a run with scattered
    failures would abort early and under-report."""
    calls = {"n": 0}

    def _rate(question, rec, dissent, outcome):
        calls["n"] += 1
        if calls["n"] % 3:
            return 0.5, "ok", {"provider": "p", "model": "m"}
        raise RuntimeError("ReadTimeout: timed out")

    monkeypatch.setattr(loop, "_rate", _rate)
    _run_main(loop, monkeypatch, rows=40)
    assert calls["n"] == 40, "reset-on-success is missing; the run stopped early"


def test_an_aborted_run_says_so(loop):
    """A truncated run that prints a normal result reads as a completed one —
    which is how the incident stayed invisible until the row count was checked."""
    src = LOOP_SRC.read_text(encoding="utf-8")
    assert "ABORT:" in src
    assert "left unscored" in src


def test_abandoned_rows_are_never_written(loop):
    """They must stay eligible. A row marked on a failure path would be
    permanently skipped by the `usefulness_score IS NULL` predicate."""
    src = LOOP_SRC.read_text(encoding="utf-8")
    body = src.split("except Exception as exc:", 1)[1].split("consecutive_failures = 0", 1)[0]
    assert "UPDATE" not in body.upper()


# ── harness ─────────────────────────────────────────────────────────────────

def _run_main(loop, monkeypatch, *, rows: int):
    """Drive main() with a fake cursor, no DB and no network."""
    class _Cur:
        def __init__(self):
            self.connection = type("C", (), {"rollback": lambda s: None})()
            self._rows: list = []

        def execute(self, sql, params=None):
            if "FROM hermes_external_research" in sql and "SELECT id" in sql:
                self._rows = [(i, "grok", "AAA", "q", "r", "d", "2026-01-01")
                              for i in range(rows)]
            elif "GROUP BY lane" in sql:
                self._rows = []
            else:
                self._rows = []

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return (0, 0.0)

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(loop, "_db", lambda: _Conn())
    monkeypatch.setattr(loop, "_outcome", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["x", "--max-rows", str(rows)])
    monkeypatch.setattr(loop, "KILL", Path("/nonexistent/HERMES_DISABLED"))
    loop.main()

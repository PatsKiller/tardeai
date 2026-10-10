"""finviz-view-contracts n8n lane: RUN_TIMEOUT at 2026-10-10 01:44Z and 13:11Z (exit 124 at timeout_s 300).

Root cause: the shared throttle state data/state/finviz_throttle.json held ``last_request`` =
1798183561.88 (2026-12-25T07:26:01Z, written 2026-10-09 21:51:48 ET by a process with a wrong clock).
``acquire()`` obeyed it, so every Finviz caller slept its whole throttle timeout (300 s by default) per
request; the lane's old ``--dry-run`` still fetched both views (2 x 300 s) and only skipped the receipt.
A faulthandler dump of the served release's dry run showed it asleep in finviz_throttle.acquire line 70.

Fix pinned here: (1) acquire() discards a ``last_request`` in the future / an absurd ``cooldown_until`` and
keeps it under ``discarded`` as evidence; status() reports it read-only. (2) ``--dry-run`` makes no Finviz
request and writes nothing; it returns its plan before ``_fetch`` is reachable. (3) the real run waits at
most THROTTLE_WAIT_S per view, so its worst case stays under the lane's allowlist timeout_s.
Hermetic: tmp throttle state, tmp receipt, no network, no DB.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2. Install a minimal stand-in ONLY when the real driver is absent, so these
# tests run (not skip) there; nothing here connects -- _latest_quotes is replaced in every main() test.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not connect")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)

import check_finviz_view_contracts as cvc  # noqa: E402
import finviz_throttle  # noqa: E402

COVERS = ["scripts/check_finviz_view_contracts.py", "scripts/finviz_throttle.py"]
FUTURE = 1798183561.8822908  # the value found on the host, 2026-10-10


@pytest.fixture
def throttle(tmp_path, monkeypatch):
    state = tmp_path / "finviz_throttle.json"
    monkeypatch.setattr(finviz_throttle, "_STATE", state)
    monkeypatch.setattr(finviz_throttle, "_LOCK", state.with_suffix(".lock"))
    sleeps: list[float] = []
    clock = [time.time()]

    def _sleep(s):
        sleeps.append(s)
        clock[0] += s

    # A fake clock on the module only (sleep advances it), so no test waits in real time.
    monkeypatch.setattr(finviz_throttle, "time", types.SimpleNamespace(time=lambda: clock[0], sleep=_sleep))
    return state, sleeps


# ── throttle: corrupt state is discarded, not obeyed ─────────────────────────────────────────────


def test_future_last_request_is_discarded_and_recorded(throttle):
    state, sleeps = throttle
    state.write_text(json.dumps({"last_request": FUTURE}))
    now = finviz_throttle.time.time()
    slept = finviz_throttle.acquire(timeout=300)
    st = json.loads(state.read_text())
    assert slept == 0 and sleeps == [], "a future last_request must not make the caller wait"
    assert st["last_request"] == now, "the slot is taken at the real now"
    assert st["discarded"]["fields"] == {"last_request": FUTURE}, "the corrupt value is kept as evidence"


def test_absurd_cooldown_is_discarded_but_a_real_cooldown_is_obeyed(throttle):
    state, sleeps = throttle
    now = time.time()
    state.write_text(json.dumps({"cooldown_until": now + 10 * 86400}))
    assert finviz_throttle.acquire(timeout=300) == 0 and sleeps == []
    assert "cooldown_until" in json.loads(state.read_text())["discarded"]["fields"]

    # Mutation: an honest 60 s Retry-After cooldown must still hold every caller back.
    now = finviz_throttle.time.time()
    state.write_text(json.dumps({"cooldown_until": now + 60}))
    finviz_throttle.acquire(timeout=300)
    st = json.loads(state.read_text())
    assert sum(sleeps) >= 59 and "discarded" not in st, "a real cooldown is honoured"
    assert st["last_request"] >= now + 60


def test_normal_min_interval_still_spaces_requests(throttle):
    state, sleeps = throttle
    state.write_text(json.dumps({"last_request": finviz_throttle.time.time()}))
    finviz_throttle.acquire(timeout=300)
    assert sleeps and sum(sleeps) == pytest.approx(finviz_throttle.MIN_INTERVAL)
    assert "discarded" not in json.loads(state.read_text())


def test_status_is_read_only_and_names_the_corruption(throttle):
    state, _ = throttle
    state.write_text(json.dumps({"last_request": FUTURE}))
    raw = state.read_bytes()
    s = finviz_throttle.status()
    assert s["corrupt"] == {"last_request": FUTURE}
    assert s["would_wait_s"] == 0 and s["last_request_age_s"] is None
    assert state.read_bytes() == raw, "status() must not write"

    state.write_text(json.dumps({"last_request": finviz_throttle.time.time()}))  # mutation: honest state
    s = finviz_throttle.status()
    assert s["corrupt"] == {} and 0 < s["would_wait_s"] <= finviz_throttle.MIN_INTERVAL


# ── lane script: the dry run spends no quota and writes nothing ──────────────────────────────────


@pytest.fixture
def lane(tmp_path, monkeypatch):
    receipt = tmp_path / "finviz_view_contracts_last_run.json"
    monkeypatch.setattr(cvc, "RECEIPT", receipt)
    monkeypatch.setattr(cvc, "_latest_quotes", lambda: None)
    env = {"FINVIZ_API_TOKEN": "secret-token"}
    monkeypatch.setattr(cvc, "_env", lambda k, d="": env.get(k, d))
    status = {"corrupt": {}, "would_wait_s": 0.0}
    monkeypatch.setattr(cvc, "_throttle_status", lambda: dict(status))
    fetched: list[int] = []

    def _fetch(view):
        fetched.append(view)
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(cvc, "_fetch", _fetch)
    return receipt, env, status, fetched


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["check_finviz_view_contracts.py", *argv])
    return cvc.main()


def test_dry_run_makes_no_request_and_writes_no_receipt(lane, monkeypatch, capsys):
    receipt, _env, _status, fetched = lane
    assert _run(monkeypatch, "--dry-run") == 0
    out = capsys.readouterr().out
    assert fetched == [] and not receipt.exists()
    assert "finviz_requests_made=0" in out and f"planned={len(cvc.VIEW_CONTRACTS)}" in out
    assert f"would write {receipt}" in out
    assert "secret-token" not in out, "the token is never printed"


def test_dry_run_report_follows_state(lane, monkeypatch, capsys):
    """Mutation test (AGENTS.md §6): change the state, the report changes."""
    _receipt, env, status, fetched = lane
    status.update(corrupt={"last_request": FUTURE}, would_wait_s=0.0)
    assert _run(monkeypatch, "--dry-run", "--json") == 0
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert plan["finviz_requests_made"] == 0 and plan["token_present"] is True
    assert any("corrupt" in n for n in plan["notes"])
    assert all("<redacted>" in u for u in plan["urls"])

    env.pop("FINVIZ_API_TOKEN")
    status.update(corrupt={}, would_wait_s=500.0)
    assert _run(monkeypatch, "--dry-run", "--json") == 2, "no token: the real run could not start"
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert plan["token_present"] is False
    assert any("not set" in n for n in plan["notes"]) and any("throttle busy" in n for n in plan["notes"])
    assert not any("corrupt" in n for n in plan["notes"])
    assert fetched == []


def test_dry_run_returns_before_fetch_and_receipt_in_source():
    """The ordering is the bug class (AGENTS.md §6, PR #1143): the dry-run return precedes the quota spend."""
    src = inspect.getsource(cvc.main)
    i_dry = src.index("if args.dry_run:")
    i_ret = src.index("return 0 if p[\"token_present\"] else 2")
    assert i_dry < i_ret < src.index("_fetch(view)") < src.index("RECEIPT.write_text")


def test_real_run_still_fetches_and_writes_the_receipt(lane, monkeypatch, capsys):
    receipt, _env, _status, fetched = lane
    assert _run(monkeypatch) == 2, "every view failed: could not run"
    assert fetched == sorted(cvc.VIEW_CONTRACTS)
    rep = json.loads(receipt.read_text())
    assert rep["schema"] == cvc.SCHEMA and len(rep["errors"]) == len(cvc.VIEW_CONTRACTS)


# ── budget: the real run is bounded under the lane's timeout whatever the throttle holds ──────────


def test_fetch_bounds_the_throttle_wait(monkeypatch):
    seen = {}

    class _Resp:
        ok, status_code, text = True, 200, "Ticker\n"

    fake = types.ModuleType("finviz_http")
    fake.finviz_get = lambda url, **kw: (seen.update(url=url, **kw), _Resp())[1]
    monkeypatch.setitem(sys.modules, "finviz_http", fake)
    monkeypatch.setattr(cvc, "_env", lambda k, d="": {"FINVIZ_API_TOKEN": "t"}.get(k, d))
    cvc._fetch(sorted(cvc.VIEW_CONTRACTS)[0])
    assert seen["throttle_timeout"] == cvc.THROTTLE_WAIT_S and seen["timeout"] == cvc.HTTP_TIMEOUT_S


def test_worst_case_fits_the_allowlist_timeout():
    lanes = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    entry = next(e for e in lanes if e["lane_id"] == "finviz-view-contracts")
    worst = cvc.worst_case_seconds(len(cvc.VIEW_CONTRACTS))
    assert worst < entry["timeout_s"] * 0.5, f"worst case {worst}s vs timeout_s {entry['timeout_s']}"
    assert entry["dry_run_arg"] == ["--dry-run"]

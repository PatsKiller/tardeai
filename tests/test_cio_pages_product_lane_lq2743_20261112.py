"""LQ-20261107-2743 part 2: the ``cio.pages`` product builder gets a SHADOW n8n dispatcher lane (``cio-pages-product``).

Release 2 was rolled back because nothing scheduled ``scripts/lib/cc_products/cio_pages.py`` (no lane, 0 stored rows).
Pins that the three config files agree and that the registration can only ever run the write-nothing argv:
  * the registry row is a dispatcher row at stage shadow / dispatch.mode dry_run, matched on the entrypoint, with a
    db_max signal on the build log the builder writes;
  * the allowlist entry runs the entrypoint with ``--dry-run`` and has no live argv (live_arg null);
  * the entrypoint adds ``--lane cio-pages-product`` and imports neither api_v2 nor any broker-side module;
  * compute_due on the real row emits only dry_run, one per 30-minute slot, against a throwaway ledger;
  * the contract is DRAFT at the registry's stage (a non-author reviewer is still needed).
Every fixture is synthetic (tmp_path ledger, no DB, no build, no provider, no broker, no systemd call).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib.lane_dispatch import dispatch_eligible, parse_dispatch_block  # noqa: E402
from scripts.lib.lane_registry import validate_row  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

LID = "cio-pages-product"
SCRIPT = "scripts/cc_products_cio_pages.py"
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
BROKER_TOKENS = ("schwab", "broker", "fidelity", "order", "execution", "trade_exec", "etrade", "ibkr", "alpaca")


def _load(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def row():
    return next(r for r in _load("lane_registry.json")["lanes"] if r.get("lane_id") == LID)


def entry():
    return next(e for e in _load("n8n_run_allowlist.json")["lanes"] if e.get("lane_id") == LID)


def contract():
    return next(c for c in _load("n8n_health_contracts.json")["contracts"] if c.get("id") == LID)


def test_the_row_is_a_shadow_dispatcher_lane_on_the_entrypoint():
    r = row()
    assert validate_row(r) == []
    s = r["scheduler"]
    assert (s["kind"], s["expression"], s["stage"]) == ("n8n", "dispatcher", "shadow")
    assert s["match"] == SCRIPT and (ROOT / SCRIPT).is_file()
    assert r["dispatch"]["mode"] == "dry_run" and r["state"] == "ACTIVE"
    assert tuple(parse_dispatch_block(r).cron) == (s["cadence"],) == ("*/30 * * * *",)
    assert r["active_days"] == [0, 1, 2, 3, 4, 5, 6]
    sig = r["output_signal"]
    assert (sig["kind"], sig["table"], sig["column"]) == ("db_max", "cc_product_build_log", "finished_at")
    assert sig["where"] == "product_id='cio.pages'"
    ok, why = dispatch_eligible(r)
    assert ok, why


def test_the_entry_is_shadow_only_and_runs_the_write_nothing_flag():
    from scripts.n8n_run_executor import validate_entry

    e = entry()
    assert validate_entry(e) is None
    assert e["command"] == ["$PY", SCRIPT]
    assert e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] is None, "shadow: no live argv exists; promotion is the lead's decision"
    assert e["lock_kind"] == "flock" and e["market_gate"] is False
    from scripts.lib.cc_products import cio_pages

    assert e["timeout_s"] > cio_pages.BUILD_TIMEOUT_S, "the executor must not kill the run before the child's deadline"
    assert not [n for n in e["env_names"] if any(t in n.upper() for t in ("SCHWAB", "BROKER", "TOKEN", "SECRET"))]


def _child(code: str) -> dict:
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                         env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"})
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


_PREAMBLE = f"""
import importlib.abc, json, sys
TOKENS = {BROKER_TOKENS!r}
REFUSED = []
class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if any(t in part.lower() for part in name.split(".") for t in TOKENS):
            REFUSED.append(name)
            raise ImportError("refused broker-side module " + name)
        return None
sys.meta_path.insert(0, Refuse())
sys.path.insert(0, {str(ROOT)!r})
"""


def test_the_entrypoint_adds_the_lane_and_imports_no_api_v2_or_broker_module():
    got = _child(_PREAMBLE + """
import runpy
mods = set(sys.modules)
ns = runpy.run_path("scripts/cc_products_cio_pages.py", run_name="lane_probe")
from scripts.lib.cc_products import cio_pages
calls = []
cio_pages.main = lambda args: calls.append(list(args)) or 0
rc1 = ns["main"](["--dry-run"])
rc2 = ns["main"](["--dry-run", "--lane", "other"])
rc3 = ns["main"](["--dry-run", "--lane=x"])
rc4 = ns["main"](["--timeout", "5"])
loaded = sorted(set(sys.modules) - mods)
print(json.dumps({"lane": ns["LANE_ID"], "calls": calls, "rc": [rc1, rc2, rc3, rc4], "refused": REFUSED,
                  "api_v2": [m for m in loaded if m.endswith("api_v2")]}))
""")
    assert got["lane"] == LID
    assert got["calls"] == [["--dry-run", "--lane", LID], ["--dry-run", "--lane", "other"], ["--dry-run", "--lane", "x"],
                            ["--timeout", "5", "--lane", LID]]
    assert got["rc"] == [0, 0, 0, 0]
    assert got["refused"] == [] and got["api_v2"] == []


def test_compute_due_emits_only_dry_run_one_per_thirty_minute_slot(tmp_path, monkeypatch):
    monkeypatch.delenv(D.LIVE_LANES_ENV, raising=False)
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    try:
        allow = {LID: entry()}
        start = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)   # 09:00 ET
        seen = []
        for tick in range(0, 2 * 60 + 5):                            # one tick a minute for two hours
            now = start + timedelta(minutes=tick)
            resp = D.compute_due([row()], allow, POLICIES, store, now)
            assert resp["errors"] == [], resp["errors"]
            for it in resp["items"]:
                assert it["mode"] == "dry_run", "a shadow lane can never be emitted live"
                seen.append(it["slot_local"])
                store.request(run_id=it["idempotency_key"], lane_id=LID, mode="dry_run", requested_by="t",
                              caller_id="t", now=now.timestamp())
                ledger._conn.execute("UPDATE runs SET state='RUN_DONE', finished_at=?, exit_code=0 WHERE run_id=?",
                                     (now.isoformat(), it["idempotency_key"]))
                ledger._conn.commit()
        assert len(seen) == len(set(seen)) >= 4, seen
    finally:
        ledger.close()


def test_the_contract_is_a_draft_at_the_registry_stage():
    c = contract()
    assert c["status"] == "DRAFT" and c["review"]["status"] == "DRAFT" and c["review"]["reviewed_by"] is None
    assert c["stage"] == row()["scheduler"]["stage"] == "shadow"
    assert c["baseline"]["timeout_s"] == entry()["timeout_s"]
    assert c["baseline"]["duration_degraded_above_s"] == 0.8 * entry()["timeout_s"]

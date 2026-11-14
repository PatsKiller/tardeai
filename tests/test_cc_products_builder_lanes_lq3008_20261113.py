"""LQ-20261107-3008: the four ``scripts/cc_products_build.py`` product builders get SHADOW n8n dispatcher lanes.

The sibling ``cio-pages-product`` lane (LQ-2743) already runs its own entrypoint; this pins the same shape for
market_risk.latest, risk, reports.analyst_links and home:
  * a dispatcher row at stage shadow / dispatch.mode dry_run, matched on ``scripts/cc_products_build.py --product <id>``,
    with a db_max signal on the build log filtered to that product;
  * an allowlist entry that runs the entrypoint with ``--dry-run`` and has no live argv (live_arg null);
  * a DRAFT contract (the author is not a reviewer);
  * compute_due on the real rows emits only dry_run, one per slot, against a throwaway ledger;
  * the entrypoint accepts exactly the products the catalogue builds, and imports neither api_v2 nor a broker module.
Synthetic: tmp_path ledger, no DB, no build, no provider, no broker, no systemd call.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib.cc_products import product_builder as PB  # noqa: E402
from scripts.lib.lane_dispatch import dispatch_eligible, parse_dispatch_block  # noqa: E402
from scripts.lib.lane_registry import validate_row  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

SCRIPT = "scripts/cc_products_build.py"
LANES = {
    "market_risk.latest": "cc-product-market-risk",
    "risk": "cc-product-risk",
    "reports.analyst_links": "cc-product-analyst-links",
    "home": "cc-product-home",
}
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
BROKER_TOKENS = ("schwab", "broker", "fidelity", "order", "execution", "trade_exec", "etrade", "ibkr", "alpaca")
PRODUCTS = sorted(LANES)


def _load(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def row(pid):
    return next(r for r in _load("lane_registry.json")["lanes"] if r.get("lane_id") == LANES[pid])


def entry(pid):
    return next(e for e in _load("n8n_run_allowlist.json")["lanes"] if e.get("lane_id") == LANES[pid])


def contract(pid):
    return next(c for c in _load("n8n_health_contracts.json")["contracts"] if c.get("id") == LANES[pid])


def test_the_lanes_cover_exactly_the_catalogue():
    assert sorted(PB.CATALOGUE) == PRODUCTS, "a product added to the catalogue needs a lane (or an explicit exclusion)"


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_row_is_a_shadow_dispatcher_lane_on_the_product_argv(pid):
    r = row(pid)
    assert validate_row(r) == []
    s = r["scheduler"]
    assert (s["kind"], s["expression"], s["stage"]) == ("n8n", "dispatcher", "shadow")
    assert s["match"] == f"{SCRIPT} --product {pid}" and (ROOT / SCRIPT).is_file()
    assert r["dispatch"]["mode"] == "dry_run" and r["state"] == "ACTIVE"
    assert tuple(parse_dispatch_block(r).cron) == (s["cadence"],)
    sig = r["output_signal"]
    assert (sig["kind"], sig["table"], sig["column"]) == ("db_max", "cc_product_build_log", "finished_at")
    assert sig["where"] == f"product_id='{pid}'"
    ok, why = dispatch_eligible(r)
    assert ok, why


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_entry_is_shadow_only_and_runs_the_write_nothing_flag(pid):
    from scripts.n8n_run_executor import validate_entry

    e = entry(pid)
    assert validate_entry(e) is None
    assert e["command"] == ["$PY", SCRIPT, "--product", pid]
    assert e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] is None, "shadow: no live argv exists; promotion is the lead's decision"
    assert e["lock_kind"] == "flock" and e["market_gate"] is False
    assert e["timeout_s"] > PB.CATALOGUE[pid].runner_timeout_s, "the executor must not kill the run before the child's deadline"
    assert not [n for n in e["env_names"] if any(t in n.upper() for t in ("SCHWAB", "BROKER", "TOKEN", "SECRET"))]


def test_every_lane_has_its_own_lock_and_id():
    locks = [entry(p)["lock"] for p in PRODUCTS]
    assert len(set(locks)) == len(locks) and len(set(LANES.values())) == len(LANES)


def _child(code: str) -> dict:
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                         env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"})
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_entrypoint_takes_the_catalogue_products_and_imports_no_api_v2_or_broker_module():
    got = _child(f"""
import importlib.abc, json, runpy, sys
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
mods = set(sys.modules)
ns = runpy.run_path("scripts/cc_products_build.py", run_name="lane_probe")
parsed = {{}}
for pid in {PRODUCTS!r}:
    a = ns["parse"](["--product", pid, "--dry-run"])
    parsed[pid] = [a.product, a.dry_run]
bad = None
try:
    ns["parse"](["--product", "no.such.product", "--dry-run"])
except SystemExit as e:
    bad = e.code
loaded = sorted(set(sys.modules) - mods)
print(json.dumps({{"parsed": parsed, "bad": bad, "refused": REFUSED, "api_v2": [m for m in loaded if m.endswith("api_v2")]}}))
""")
    assert got["parsed"] == {p: [p, True] for p in PRODUCTS}
    assert got["bad"] == 2, "an unknown product is refused by argparse, never built"
    assert got["refused"] == [] and got["api_v2"] == []


@pytest.mark.parametrize("pid", PRODUCTS)
def test_compute_due_emits_only_dry_run_and_never_twice_in_a_slot(pid, tmp_path, monkeypatch):
    monkeypatch.delenv(D.LIVE_LANES_ENV, raising=False)
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    try:
        allow = {LANES[pid]: entry(pid)}
        start = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)   # 09:00 ET
        seen = []
        for tick in range(0, 7 * 60 + 5):                            # one tick a minute for seven hours
            now = start + timedelta(minutes=tick)
            resp = D.compute_due([row(pid)], allow, POLICIES, store, now)
            assert resp["errors"] == [], resp["errors"]
            for it in resp["items"]:
                assert it["mode"] == "dry_run", "a shadow lane can never be emitted live"
                seen.append(it["slot_local"])
                store.request(run_id=it["idempotency_key"], lane_id=LANES[pid], mode="dry_run", requested_by="t",
                              caller_id="t", now=now.timestamp())
                ledger._conn.execute("UPDATE runs SET state='RUN_DONE', finished_at=?, exit_code=0 WHERE run_id=?",
                                     (now.isoformat(), it["idempotency_key"]))
                ledger._conn.commit()
        assert len(seen) == len(set(seen)) >= 1, seen
    finally:
        ledger.close()


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_contract_is_a_draft_until_a_non_author_reviews_it(pid):
    c = contract(pid)
    assert c["status"] == "DRAFT" and c["review"]["status"] == "DRAFT" and c["review"]["reviewed_by"] is None
    assert c["stage"] == row(pid)["scheduler"]["stage"] == "shadow"
    assert c["baseline"]["timeout_s"] == entry(pid)["timeout_s"]
    assert c["baseline"]["duration_degraded_above_s"] == round(0.8 * entry(pid)["timeout_s"], 1)
    assert f"product_id='{pid}'" in json.dumps(c["evidence"]["verify"]) or pid in json.dumps(c["evidence"]["verify"])


# --- LQ-20261113-3075 conditions F-B (cadence vs stale_after_s) -------------------------------------------------
# A shadow lane fires on its own cron; the product it will one day keep fresh goes stale after spec.stale_after_s.
# The shadow cadence is deliberately coarse (a dry run writes nothing, so a faster fire buys nothing), which means
# several lanes fire LESS often than the product needs. That is acceptable only while the lane cannot write.
# These tests pin the cadence values and make the gap a measured, promotion-blocking fact.
SHADOW_CADENCE_S = {            # pid -> seconds between fires of the lane's cron (pinned: change on purpose)
    "market_risk.latest": 1800,
    "risk": 1800,
    "reports.analyst_links": 21600,
    "home": 1800,
}
SHADOW_CRON = {
    "market_risk.latest": "*/30 * * * *",
    "risk": "*/30 * * * *",
    "reports.analyst_links": "0 */6 * * *",
    "home": "*/30 * * * *",
}


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_shadow_cadence_is_pinned_and_matches_the_registry_row(pid):
    r = row(pid)
    assert r["scheduler"]["cadence"] == SHADOW_CRON[pid] and tuple(parse_dispatch_block(r).cron) == (SHADOW_CRON[pid],)
    assert r["expected_cadence_hours"] * 3600 == SHADOW_CADENCE_S[pid]
    assert contract(pid)["baseline"]["freshness_degraded_after_h"] == 3 * r["expected_cadence_hours"]
    assert contract(pid)["baseline"]["freshness_failed_after_h"] == 6 * r["expected_cadence_hours"]


@pytest.mark.parametrize("pid", PRODUCTS)
def test_a_lane_that_fires_less_often_than_half_the_stale_window_cannot_write(pid):
    """cadence <= stale_after_s / 2 is the promotion bar. A lane below it must be dry_run with no live argv."""
    spec = PB.CATALOGUE[pid]
    below_bar = SHADOW_CADENCE_S[pid] > spec.stale_after_s / 2
    if below_bar:
        assert row(pid)["dispatch"]["mode"] == "dry_run" and entry(pid)["live_arg"] is None, (
            f"{pid}: cron every {SHADOW_CADENCE_S[pid]} s vs stale_after_s {spec.stale_after_s}: the stored product would be stale "
            "most of every interval; tighten the cadence before giving this lane a live argv")


def test_the_cadence_gap_is_the_known_set_not_a_silent_one():
    gap = sorted(p for p in PRODUCTS if SHADOW_CADENCE_S[p] > PB.CATALOGUE[p].stale_after_s / 2)
    print("GAP", gap, {p: (SHADOW_CADENCE_S[p], PB.CATALOGUE[p].stale_after_s) for p in PRODUCTS})
    assert gap == ["home", "market_risk.latest", "risk"], (
        "the set of lanes that are too slow to promote changed; update this on purpose and tell the lead", gap)

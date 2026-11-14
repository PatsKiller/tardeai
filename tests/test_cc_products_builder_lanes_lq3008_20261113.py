"""LQ-20261107-3008 + LQ-20261113-3096: the five product-builder n8n dispatcher lanes, promoted shadow -> canary/live.

Lanes: market_risk.latest, risk, reports.analyst_links, home (``scripts/cc_products_build.py --product <id>``) and
cio.pages (``scripts/cc_products_cio_pages.py``, lane cio-pages-product). Pins:
  * a dispatcher row at stage canary / dispatch.mode live, matched on the product argv, with a db_max signal on the
    build log filtered to that product, and ``scheduler.cadence`` == ``dispatch.cron[0]``;
  * an allowlist entry whose ``live_arg`` is [] (the write path) and whose ``dry_run_arg`` stays ``--dry-run``;
  * a REVIEWED contract (LQ-3094 registration review; the 3096 promotion delta is flagged for a re-review);
  * compute_due on the real rows emits live, one per slot, against a throwaway ledger;
  * FRESHNESS MATH: for every fire in a simulated week, the gap to the next fire is under the stale_after_s the
    build will store (``limits_for`` at the fire instant), with a 2x margin outside a DST-transition week;
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
CIO_PAGES = "cio.pages"
LANES[CIO_PAGES] = "cio-pages-product"
MARKET = ["30-59 9 * * 1-5", "* 10-15 * * 1-5", "0-14 16 * * 1-5", "15 16 * * 1-5", "0 0-9,17-23 * * 1-5", "0 * * * 0,6"]
RISK = ["30-58/2 9 * * 1-5", "*/2 10-15 * * 1-5", "0-14/2 16 * * 1-5", "15 16 * * 1-5", "0 0-9,17-23 * * 1-5", "0 * * * 0,6"]
PROMOTED_CRON = {
    "market_risk.latest": MARKET, "home": MARKET, "risk": RISK,
    "reports.analyst_links": ["0 */6 * * *"], CIO_PAGES: ["*/2 * * * *"],
}
# pid -> (baseline freshness_degraded_after_h, freshness_failed_after_h, expected_cadence_hours)
PROMOTED_BASELINE = {
    "market_risk.latest": (2.5, 4.0, 1.0), "home": (2.5, 4.0, 1.0), "risk": (2.5, 4.0, 1.0),
    "reports.analyst_links": (36.0, 168.0, 6.0), CIO_PAGES: (0.1, 0.5, 0.034),
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
    assert sorted(PB.CATALOGUE) == sorted(p for p in PRODUCTS if p != CIO_PAGES), "a product added to the catalogue needs a lane (or an explicit exclusion)"


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_row_is_a_canary_live_dispatcher_lane_on_the_product_argv(pid):
    r = row(pid)
    assert validate_row(r) == []
    s = r["scheduler"]
    assert (s["kind"], s["expression"], s["stage"]) == ("n8n", "dispatcher", "canary")
    if pid != CIO_PAGES:
        assert s["match"] == f"{SCRIPT} --product {pid}" and (ROOT / SCRIPT).is_file()
    assert r["dispatch"]["mode"] == "live" and r["state"] == "ACTIVE"
    assert tuple(parse_dispatch_block(r).cron) == tuple(PROMOTED_CRON[pid])
    assert s["cadence"] == r["dispatch"]["cron"][0], "lane_dispatch requires scheduler.cadence == dispatch.cron[0]"
    assert r["expected_cadence_hours"] == PROMOTED_BASELINE[pid][2]
    sig = r["output_signal"]
    assert (sig["kind"], sig["table"], sig["column"]) == ("db_max", "cc_product_build_log", "finished_at")
    assert sig["where"] == f"product_id='{pid}'"
    ok, why = dispatch_eligible(r)
    assert ok, why


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_entry_has_the_live_argv_and_keeps_the_write_nothing_flag(pid):
    from scripts.n8n_run_executor import validate_entry

    e = entry(pid)
    assert validate_entry(e) is None
    assert e["command"] == (["$PY", "scripts/cc_products_cio_pages.py"] if pid == CIO_PAGES else ["$PY", SCRIPT, "--product", pid])
    assert e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] == [], "promoted: the live argv is the bare command (the write path)"
    assert e["lock_kind"] == "flock" and e["market_gate"] is False
    assert e["timeout_s"] > (110 if pid == CIO_PAGES else PB.CATALOGUE[pid].runner_timeout_s), "the executor must not kill the run before the child's deadline"
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
for pid in {[p for p in PRODUCTS if p != CIO_PAGES]!r}:
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
    assert got["parsed"] == {p: [p, True] for p in PRODUCTS if p != CIO_PAGES}
    assert got["bad"] == 2, "an unknown product is refused by argparse, never built"
    assert got["refused"] == [] and got["api_v2"] == []


@pytest.mark.parametrize("pid", PRODUCTS)
def test_compute_due_emits_live_and_never_twice_in_a_slot(pid, tmp_path, monkeypatch):
    monkeypatch.setenv(D.LIVE_LANES_ENV, LANES[pid])  # the relay live set the render step would produce for this lane
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
                assert it["mode"] == "live", "a promoted lane in the relay live set is emitted live"
                seen.append(it["slot_local"])
                store.request(run_id=it["idempotency_key"], lane_id=LANES[pid], mode="live", requested_by="t",
                              caller_id="t", now=now.timestamp())
                ledger._conn.execute("UPDATE runs SET state='RUN_DONE', finished_at=?, exit_code=0 WHERE run_id=?",
                                     (now.isoformat(), it["idempotency_key"]))
                ledger._conn.commit()
        assert len(seen) == len(set(seen)) >= 1, seen
        if pid in ("market_risk.latest", "home"):
            assert len(seen) >= 6 * 60, "every minute through the 09:30-16:14 window"
    finally:
        ledger.close()


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_contract_is_reviewed_by_a_non_author_and_flags_the_promotion_delta(pid):
    """LQ-20261113-3094 (F-C Option A): the four contracts were reviewed, not grandfathered. The author is cc-sonnet-5."""
    c = contract(pid)
    assert c["status"] == c["review"]["status"] == "REVIEWED"
    by = c["review"]["reviewed_by"]
    assert by and "cc-sonnet-5" not in by.split(";")[0]
    assert c["review"]["reviewed_on"]
    if pid != CIO_PAGES:
        assert "cc-sonnet-6/LQ-3094" in by and "registration only" in c["review"]["note"]
    assert "LQ-3096 PROMOTION DELTA" in c["review"]["note"], "the promotion delta must say it is not covered by the registration review"
    b = c["baseline"]
    assert (b["freshness_degraded_after_h"], b["freshness_failed_after_h"]) == PROMOTED_BASELINE[pid][:2]
    assert c["stage"] == row(pid)["scheduler"]["stage"] == "canary"
    checks = [h["check"] for h in c["healthy"]]
    assert "last_live_run_done" in checks and "shadow_dry_run_done" not in checks
    assert c["baseline"]["timeout_s"] == entry(pid)["timeout_s"]
    assert c["baseline"]["duration_degraded_above_s"] == round(0.8 * entry(pid)["timeout_s"], 1)
    assert f"product_id='{pid}'" in json.dumps(c["evidence"]["verify"]) or pid in json.dumps(c["evidence"]["verify"])


# --- LQ-20261113-3096: the promoted cadence is shorter than the stale window the build stores --------------------
from zoneinfo import ZoneInfo  # noqa: E402
from scripts.lib import cron_schedule as CS  # noqa: E402

ET = ZoneInfo("America/New_York")
# Stored limits per product at a build instant. cio.pages has flat limits (cio_pages.py STALE_AFTER_S / HARD_EXPIRY_S).
CIO_LIMITS = {"stale_after_s": 360, "hard_expiry_s": 1800}


def _limits(pid, at):
    if pid == CIO_PAGES:
        return CIO_LIMITS
    return PB.limits_for(PB.CATALOGUE[pid], at)


def _fires(pid, start, end):
    out = {}
    for expr in row(pid)["dispatch"]["cron"]:
        for f in CS.fires_between(expr, start, end, "America/New_York"):
            out[f.at] = f
    return sorted(out, key=lambda x: x.astimezone(timezone.utc))


WEEK = (datetime(2026, 11, 9, 0, 0, tzinfo=ET), datetime(2026, 11, 16, 0, 0, tzinfo=ET))       # no DST change
DST_FALL = (datetime(2026, 10, 31, 12, 0, tzinfo=ET), datetime(2026, 11, 3, 0, 0, tzinfo=ET))  # fall back Sun 1 Nov
DST_SPRING = (datetime(2027, 3, 13, 12, 0, tzinfo=ET), datetime(2027, 3, 16, 0, 0, tzinfo=ET))  # spring forward Sun 14 Mar


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_gap_to_the_next_fire_is_under_half_the_stale_window_in_an_ordinary_week(pid):
    fires = _fires(pid, *WEEK)
    assert len(fires) >= 28
    worst = 0.0
    for a, b in zip(fires, fires[1:]):
        gap = (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds()
        stale = _limits(pid, a)["stale_after_s"]
        assert gap <= stale / 2, f"{pid}: fire {a.astimezone(ET):%a %H:%M} stores stale_after_s {stale} but the next fire is {gap:.0f} s later"
        worst = max(worst, gap / stale)
    assert worst <= 0.5


@pytest.mark.parametrize("pid", PRODUCTS)
@pytest.mark.parametrize("window", [DST_FALL, DST_SPRING], ids=["fall_back", "spring_forward"])
def test_a_dst_transition_never_lets_the_gap_pass_the_stale_window(pid, window):
    fires = _fires(pid, *window)
    worst = 0.0
    for a, b in zip(fires, fires[1:]):
        gap = (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds()
        worst = max(worst, gap)
        if (pid, window) == (CIO_PAGES, DST_FALL):
            continue  # KNOWN: see the next test
        assert gap < _limits(pid, a)["stale_after_s"], f"{pid}: {a.astimezone(ET):%a %H:%M} gap {gap:.0f} s"


def test_known_gap_cio_pages_loses_the_repeated_fall_back_hour():
    """cron_schedule dedupes by local slot, so the second 01:00-01:59 pass of fall-back night (Sun 1 Nov 2026) has no fire.
    A */2 lane therefore goes 62 minutes between builds once a year, on a Sunday 01:58 EDT -> 02:00 EST, against
    stale_after_s 360. Weekend, markets closed. Pinned so a change to the cron or the dedupe rule is on purpose."""
    fires = _fires(CIO_PAGES, *DST_FALL)
    gaps = [(b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds() for a, b in zip(fires, fires[1:])]
    assert max(gaps) == 3720 and sum(1 for g in gaps if g > 360) == 1


@pytest.mark.parametrize("pid", PRODUCTS)
def test_the_gap_is_under_the_hard_expiry_with_a_margin_of_four(pid):
    fires = _fires(pid, *WEEK)
    for a, b in zip(fires, fires[1:]):
        assert (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds() * 4 <= _limits(pid, a)["hard_expiry_s"]


@pytest.mark.parametrize("pid", ["market_risk.latest", "home", "risk"])
def test_the_open_and_the_close_are_covered(pid):
    """09:30 ET is the first market-tier build; 16:15 ET (the first off-hours minute) has a fire so the stored limits flip."""
    fires = {f.astimezone(ET).strftime("%a %H:%M") for f in _fires(pid, *WEEK)}
    for hhmm in ("09:30", "09:31", "16:14", "16:15", "17:00"):
        if pid == "risk" and hhmm in ("09:31", "16:14"):
            continue  # risk fires on even minutes (09:30, 09:32 ... 16:14 is even; 09:31 is not)
        assert f"Tue {hhmm}" in fires, (pid, hhmm)
    assert "Sat 10:00" in fires and "Tue 09:00" in fires
    assert not [x for x in fires if x.startswith("Tue 16:") and "16:15" < x[4:] < "16:59"], "no market-rate fire after the close"


def test_cio_pages_cadence_matches_the_builder_constant():
    from scripts.lib.cc_products import cio_pages
    assert cio_pages.CADENCE_S == 120 and cio_pages.STALE_AFTER_S == CIO_LIMITS["stale_after_s"]
    assert cio_pages.HARD_EXPIRY_S == CIO_LIMITS["hard_expiry_s"]
    assert tuple(row(CIO_PAGES)["dispatch"]["cron"]) == ("*/2 * * * *",)

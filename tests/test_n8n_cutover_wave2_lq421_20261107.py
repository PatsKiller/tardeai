"""LQ-20261107-421: a lane the registry declares live must actually be dispatchable live.

MEASURED 2026-11-07. Twenty-seven of the thirty-one `both` lanes (host scheduler `cron` AND named in the relay live
list) had never produced one live n8n receipt. None of them was broken; all three arming steps landed TODAY, and
every step before the last one was silent:

* 2026-11-07 00:23:47 ET (``8f97cd903``, CUT1): 24 lanes get a ``scheduler.kind: n8n`` dispatcher row. Relay
  membership plus the surviving cron line is exactly what makes the catalog label a lane ``both`` - so from this
  commit the catalog called them fully cut over while ``dispatch.mode`` did not exist yet.
* 2026-11-07 00:36:35 ET (``4522ef189``): only 3 of the 31 were ``dispatch.mode: live``. 21 had NO dispatch block at
  all and 7 were ``dry_run``. ``n8n_due._eligible_lanes`` skips a row with no/off dispatch block with no
  ``errors[]`` entry and no run row, so those lanes had zero n8n runs of any mode.
* 2026-11-07 01:25:26 ET (``3e5058a4b``, W5): 25 lanes get registry + allowlist + contract + effect-key rows, taking
  the set to 28/31 live, then ``36ef281e7`` (01:35) 29, ``b110ba333`` (01:55) 30, ``498f45d2a`` (03:38) 31/31. Each
  flip carries ``live_arg`` in the same commit, so the render never saw a half-armed row.
* 2026-11-07 08:10:52 ET: the operator's cutover owner step wrote 29 ``effect_owners`` rows
  (``switched_by: operator:john-morning-20261107``, note ``morning cutover 2026-11-07``). Before it, every live
  request for a keyed lane was queued and then refused ``effect:effect_no_owner``: ``news-to-catalyst``
  11:45:03Z, ``agent-watchlist-engine`` 12:00:04Z, ``research-intelligence-queue`` 07:40:03Z. ``news-to-catalyst``
  is the A/B - the same lane, same argv, refused at 11:45:03Z and RUN_DONE at 17:45:05Z.
* 2026-11-07 18:20:07 ET (``e024e6da9``): the lead folds the same owners into ``config/n8n_effect_keys.json``, so
  the config mirror agrees with the ledger the executor actually gates on.

From 13:18Z the same day, live RUN_DONE receipts appear (``update-lockup-earnings-dates`` 13:18:00Z,
``news-ingestion-tail`` 23:00:07Z, ``news-to-catalyst`` 23:45:13Z), so the config is complete and only the slots are
owed.

This module is a FORWARD guard, not a reproduction of that history: it asserts the two config invariants that would
turn a future half-armed rollout into a red test on the release rather than a month of silence (a mode block without
an argv, or a keyed lane that never dispatches). The ledger-side owner gate cannot be a CI gate; it is checked in
the DONE note for LQ-421 with the ledger timestamps above.

Pure config reads. No ledger, no crontab, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "lane_registry.json"
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
EFFECT_KEYS = ROOT / "config" / "n8n_effect_keys.json"

#: Lanes with a slot before Mon 2026-11-09 09:30 ET that LQ-421 named as priority. Pinned so a future edit that
#: un-arms one of them fails here by name instead of disappearing into a render exclude.
PRIORITY_LANES = (
    "tmp-scratch-cleanup",
    "reconcile-exit-advisory-outcomes",
    "reconcile-pullback-outcomes",
    "reconcile-watch-outcomes",
    "agent-calibration-engine",
    "generate-analyst-reports-autonomous-weekly",
    "sec-fundamentals-ingest",
    "aegis-evening-packet",
    "agent-watchlist-engine",
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _live_rows(registry) -> dict[str, dict]:
    rows = registry.get("lanes") if isinstance(registry, dict) else registry
    return {
        r["lane_id"]: r
        for r in rows
        if isinstance(r, dict) and isinstance(r.get("lane_id"), str)
        and isinstance(r.get("dispatch"), dict) and r["dispatch"].get("mode") == "live"
    }


def _excluded_dispatch_live(registry, allowlist) -> dict[str, str]:
    """{lane_id: exclusion reason} for registry rows that declare live dispatch but are not rendered live.

    ``n8n_relay_live_lanes.registry_live_lanes`` is the SAME function the deploy's render uses, so this cannot
    drift from what the relay actually receives.
    """
    from scripts.lib.n8n_relay_live_lanes import registry_live_lanes

    live, excluded = registry_live_lanes(registry, allowlist)
    live_set = set(live)
    return {lane: why for lane, why in excluded.items() if lane in _live_rows(registry) and lane not in live_set}


def test_no_dispatch_live_lane_is_excluded_from_the_relay_render():
    """A row flipped to live whose argv is not armed would be dropped from the render with no trace.

    ``n8n_due`` skips such a lane (``not_allowlisted``) and the dispatcher writes no run row, so the failure mode is
    a lane the registry calls live that n8n has never run - one config edit away from the 2026-11-07 stall.
    """
    registry, allowlist = _load(REGISTRY), _load(ALLOWLIST)
    defects = _excluded_dispatch_live(registry, allowlist)
    assert not defects, (
        "registry rows declare dispatch.mode=live but the relay render excludes them (n8n can never fire them): "
        + ", ".join(f"{lane}={why}" for lane, why in sorted(defects.items()))
    )


def test_negative_control_a_null_live_arg_is_reported():
    """The guard must fail on a half-armed flip, or it proves nothing."""
    registry = {"lanes": [{
        "lane_id": "synthetic-wave2",
        "state": "ACTIVE",
        "scheduler": {"kind": "cron", "stage": "canary"},
        "dispatch": {"mode": "live", "cron": ["30 3 * * 0"], "class": "hygiene", "priority": 4,
                     "tz": "America/New_York", "retry_policy": "none", "wave": "W5"},
    }]}
    allowlist = {"schema": "N8nRunAllowlist@v1", "lanes": [{
        "lane_id": "synthetic-wave2",
        "command": ["python3", "scripts/synthetic_wave2.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": None,
        "lock": "/tmp/synthetic_wave2.lock",
        "timeout_s": 300,
    }]}
    defects = _excluded_dispatch_live(registry, allowlist)
    assert defects == {"synthetic-wave2": "no_allowlist_live_arg"}

    allowlist["lanes"][0]["live_arg"] = ["--apply"]
    assert _excluded_dispatch_live(registry, allowlist) == {}      # armed -> rendered live


def test_priority_lanes_are_rendered_live():
    registry, allowlist = _load(REGISTRY), _load(ALLOWLIST)
    rows = _live_rows(registry)
    live, _excluded = _relay_live(registry, allowlist)
    missing = [lane for lane in PRIORITY_LANES if lane in rows and lane not in live]
    assert not missing, f"priority lanes declared live but not rendered live: {missing}"
    assert [lane for lane in PRIORITY_LANES if lane not in rows] == [], "a priority lane left the live dispatch set"


def _relay_live(registry, allowlist):
    from scripts.lib.n8n_relay_live_lanes import registry_live_lanes

    return registry_live_lanes(registry, allowlist)


def test_every_keyed_n8n_claim_lane_is_live_dispatched():
    """A key the executor will claim on a live run belongs to a lane that is actually live-dispatched.

    ``load_effect_config`` returns exactly the ``n8n_claim`` lanes; a keyed lane at ``dispatch.mode: off`` would
    hold an effect key nobody claims, and its owner row would fence nothing.
    """
    registry, keys = _load(REGISTRY), _load(EFFECT_KEYS)
    rows = {r["lane_id"]: r for r in registry["lanes"]}
    live = set(_live_rows(registry))
    stranded = [
        lane for lane, spec in keys["lanes"].items()
        if spec.get("n8n_claim") and lane not in live
        and ((rows.get(lane) or {}).get("scheduler") or {}).get("kind") != "n8n"
    ]
    assert not stranded, f"n8n_claim keys without a live dispatch row: {sorted(stranded)}"


def test_the_effect_key_flags_todays_wave2_shape():
    """Pin what the analysis measured, so a later 'fix' that re-stages a lane is visible in review.

    ``n8n_claim: false`` is the executor's 'staged only' flag (``load_effect_config`` drops those lanes), so a false
    key never blocks a live run by itself; a true one needs an ``effect_owners`` row or the run is refused
    ``effect_no_owner``. Both halves are asserted here as the two distinct shapes in today's wave.
    """
    keys = _load(EFFECT_KEYS)["lanes"]
    armed = {lane for lane, spec in keys.items() if spec.get("n8n_claim")}
    staged = {lane for lane, spec in keys.items() if spec.get("n8n_claim") is False}
    assert armed and staged                                           # both shapes still exist in the config
    assert armed.isdisjoint(staged)
    assert all(keys[lane].get("process") for lane in armed | staged)  # an effect key always names its process


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

"""LQ-20261107-1231: the categorized self-heal runbook catalog and its engine.

Every fixture here is SYNTHETIC (public repo: no real tickers, holdings, hosts, tokens). The catalog is the operator's
2026-11-08 order: before a non-code failure is escalated, a deterministic runbook must try what a code change cannot.

Test obligations from the plan (SELFHEAL-BEST-PRACTICE-PLAN-20261108.md, RUNBOOK CATALOG):
  * per entry >= 3 tests: matches its fixture; refuses when a precondition fails; idempotent / rate-limited on repeat
  * catalog-wide: schema, action whitelist, explicit unique priorities, no ambiguous fixture, zero unclassified
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import self_heal_runbooks as RB

NOW = datetime(2026, 11, 8, 21, 0, tzinfo=timezone.utc)
LANE = "fixture-lane"

CATALOG = RB.load_catalog()
ENTRIES = dict(CATALOG)

#: One synthetic evidence set per entry. (failure_class, evidence, contract). Each must select exactly its entry.
MATCH_SAMPLE: dict[str, tuple[str, dict, dict | None]] = {
    "A01-flock-held": ("lock_skip", {"reason": "flock_held: another scheduler holds the lane lock"}, None),
    "A02-stale-existence-lock": ("stale_lock", {
        "reason": "stale lock file: the recorded owner is gone",
        "lock_path": "/scratch/synthetic/lane.pidfile", "lock_kind": "pidfile",
        "owner_pid": 999999, "pid_alive": False, "lock_age_s": 7200, "lane_timeout_s": 1800}, None),
    "A03-sqlite-database-locked": ("", {"reason": "OperationalError: database is locked"}, None),
    "A04-pg-lock-not-available": ("", {"reason": "psycopg2.errors.LockNotAvailable: could not obtain lock"}, None),
    "A05-overlapping-schedule": ("overlap", {"reason": "overlapping run: the previous slot is still running"}, None),
    # ---- the nine entries LQ-20261107-1259 added for signatures the 14-day replay found unclassified
    "A06-effect-already-claimed": ("effect_claimed", {
        "reason": "EFFECT_ALREADY_CLAIMED: another run holds the effect key"}, None),
    "B01-rate-limited-429": ("rate_limited", {"reason": "provider returned 429 rate limit", "retries_today": 0}, None),
    "B02-oauth-expired": ("auth", {"reason": "OAuth token expired"}, None),
    "B03-budget-governor-refusal": ("budget", {"reason": "budget governor refusal"}, None),
    "B04-provider-credit-exhausted": ("credit", {"reason": "insufficient_quota: credit exhausted"}, None),
    "C01-late-data": ("data", {"reason": "data is late for the lane", "data_age_h": 30, "reruns_today": 0},
                      {"baseline": {"freshness_failed_after_h": 24}}),
    "C02-empty-output": ("data_quality", {"reason": "empty output: zero rows"}, None),
    "C03-weekend-expected": ("market_closed", {"reason": "market closed for the holiday"}, None),
    "C04-no-briefs": ("", {"reason": "NO_BRIEFS", "reruns_today": 0}, None),
    "C05-stale-source": ("stale_source", {"reason": "source has not updated in 6 h"}, None),
    "C06-output-unverifiable": ("output_unverifiable", {
        "reason": "output_unverifiable: the receipt cannot prove what the run produced"}, None),
    "C07-upstream-verification-failed": ("upstream_verification", {
        "reason": "UPSTREAM_VERIFICATION_FAILED: the dependency's release did not verify"}, None),
    "D01-network-transient": ("network", {"reason": "temporary failure in name resolution", "retries_today": 0}, None),
    "D02-provider-5xx": ("", {"reason": "503 service unavailable", "retries_today": 0}, None),
    "D03-connection-refused": ("", {"reason": "connection refused on the socket", "retries_today": 0}, None),
    "E01-run-timeout-124": ("timeout", {"reason": "RUN_TIMEOUT exit 124"}, None),
    "E02-slow-gateway": ("", {"reason": "GATEWAY_BUSY: the client deadline fired"}, None),
    "F01-executor-lost": ("executor_lost", {"reason": "RUN_TIMEOUT executor_lost"}, None),
    "F02-bridge-route-refused": ("", {"reason": "BRIDGE_ROUTE_REFUSED"}, None),
    "F03-breaker-open": ("breaker_open", {"reason": "circuit breaker open"}, None),
    "F04-dead-letter": ("dead_letter", {"reason": "dead letter queue"}, None),
    "F05-restart-killed-child": ("", {"reason": "killed by a deploy restart", "reruns_today": 0}, None),
    "F06-effect-no-owner": ("effect_no_owner", {"reason": "EFFECT_NO_OWNER: the effect key has no registered owner"},
                            None),
    "G01-disk-floor": ("disk_floor", {"reason": "disk floor reached: ENOSPC"}, None),
    "G02-tmp-enospc": ("", {"reason": "/tmp is full: ENOSPC"}, None),
    "G03-memory-pressure": ("", {"reason": "MemoryError: out of memory"}, None),
    "H01-db-unreachable": ("", {"reason": "could not connect to server: host is down", "retries_today": 0}, None),
    "H02-db-read-only-txn": ("", {"reason": "cannot execute INSERT in a read-only transaction"}, None),
    "H03-schema-missing": ("", {"reason": "UndefinedTable: relation \"fixture\" does not exist"}, None),
    "H04-db-error-while-updating": ("db_error", {
        "reason": "psycopg2.errors.DeadlockDetected: deadlock detected while updating tuple"}, None),
    "H05-db-connection-closed": ("db_connection_closed", {
        "reason": "psycopg2.InterfaceError: connection already closed"}, None),
    "I01-duplicate-registry-row": ("registry_duplicate", {"reason": "duplicate registry row for the lane"}, None),
    "I02-lane-missing-from-registry": ("registry_missing", {"reason": "lane missing from registry"}, None),
    "I03-contract-missing": ("", {"reason": "no health contract for lane"}, None),
    "I04-invalid-config-json": ("", {"reason": "invalid config JSON: JSONDecodeError"}, None),
    "I05-env-names-missing": ("config_env", {
        "reason": "env_names_missing: the lane's entry and the executor allowlist disagree"}, None),
    "I06-log-path-not-a-directory": ("config_path", {
        "reason": "safe_flock: log path component is not a real directory"}, None),
    "J01-code-defect": ("code_error", {"reason": "CODE_ERROR AssertionError"}, None),
    "J02-test-failure": ("test_failure", {"reason": "FAILED tests/fixture_x.py::test_y"}, None),
    "J03-data-defect-in-input": ("data_defect", {
        "reason": "dependency_unavailable: the producer has no rows for the window"}, None),
    "K01-credential-problem": ("credential", {"reason": "invalid api_key"}, None),
    "K02-broker-orders": ("broker", {"reason": "ORDER_REJECTED by broker"}, None),
    "K03-data-correction": ("data_correction", {"reason": "data correction requested"}, None),
    "K04-audit-block": ("audit_block", {"reason": "AUDIT_BLOCK verdict"}, None),
    "K05-unclassified-catch-all": ("", {"reason": "a signature nobody has ever seen"}, None),
}

#: The signatures the operator named as seen on 2026-11-08, and the entry each must reach. Zero unclassified.
SEEN_TODAY = {
    "flock_held": "A01-flock-held",
    "database is locked": "A03-sqlite-database-locked",
    "LockNotAvailable": "A04-pg-lock-not-available",
    "RUN_TIMEOUT exit 124": "E01-run-timeout-124",
    "executor_lost": "F01-executor-lost",
    "BRIDGE_ROUTE_REFUSED": "F02-bridge-route-refused",
    "NO_BRIEFS": "C04-no-briefs",
    "disk floor": "G01-disk-floor",
}


def _plan(entry_id: str, *, now: datetime = NOW, lane: str = LANE, **overrides) -> dict:
    fc, ev, contract = MATCH_SAMPLE[entry_id]
    evidence = {"lane": lane, "signature": f"sig-{entry_id}", **ev}
    evidence.update(overrides)
    return RB.plan_runbook(fc, evidence, contract, now, catalog=CATALOG)


def _pre_names(entry: dict) -> list[str]:
    return [p if isinstance(p, str) else p["check"] for p in entry.get("preconditions") or []]


# ---------------------------------------------------------------- catalog-wide


def test_catalog_loads_with_expected_schema_and_every_action_whitelisted():
    assert CATALOG, "the catalog must not be empty"
    for entry in CATALOG.values():
        assert entry["action"] in RB.ACTION_WHITELIST, entry["id"]
        assert entry["tier"] in RB.TIERS, entry["id"]
        assert entry["category"] in RB.CATEGORIES, entry["id"]
        assert isinstance(entry["priority"], int) and not isinstance(entry["priority"], bool), entry["id"]


def test_categories_cover_the_required_minimum_and_every_entry_is_categorized():
    present = {e["category"] for e in CATALOG.values()}
    assert {"A", "B", "C", "E", "F"} <= present
    assert present <= set(RB.CATEGORIES)
    # A..K is the plan's category set; having a row in each is what keeps every failure family reachable.
    assert present == set(RB.CATEGORIES)


def test_priorities_are_explicit_unique_and_the_catch_all_is_last():
    priorities = [e["priority"] for e in CATALOG.values()]
    assert len(priorities) == len(set(priorities))
    fallbacks = [e for e in CATALOG.values() if not any(e["match"].get(k) for k in
                                                        ("failure_class", "reason_regex", "exception_regex"))]
    assert len(fallbacks) == 1 and fallbacks[0]["id"] == "K05-unclassified-catch-all"
    assert max(priorities) == fallbacks[0]["priority"]


@pytest.mark.parametrize("entry_id", sorted(CATALOG))
def test_every_entry_declares_at_least_three_tests(entry_id):
    assert len(CATALOG[entry_id]["tests"]) >= 3, entry_id


def test_human_only_entries_never_carry_a_mutating_action():
    for entry in CATALOG.values():
        if entry["tier"] == "human_only":
            assert entry["action"] in ("escalate_finding", "release_stale_sqlite_wal_lock"), entry["id"]


def test_validate_catalog_rejects_a_non_whitelisted_action():
    doc = json.loads(RB.CATALOG_PATH.read_text())
    doc["runbooks"][0]["action"] = "delete_everything"
    with pytest.raises(RB.RunbookCatalogError, match="action_not_whitelisted"):
        RB.validate_catalog(doc)


def test_validate_catalog_rejects_a_duplicate_priority():
    doc = json.loads(RB.CATALOG_PATH.read_text())
    doc["runbooks"][1]["priority"] = doc["runbooks"][0]["priority"]
    with pytest.raises(RB.RunbookCatalogError, match="duplicate_priority"):
        RB.validate_catalog(doc)


def test_load_catalog_fails_closed_when_the_file_is_missing(tmp_path):
    with pytest.raises(RB.RunbookCatalogError, match="unreadable"):
        RB.load_catalog(tmp_path / "absent.json")


# ---------------------------------------------------------------- per entry: matches its fixture


@pytest.mark.parametrize("entry_id", sorted(MATCH_SAMPLE))
def test_entry_matches_its_synthetic_fixture_unambiguously(entry_id):
    plan = _plan(entry_id)
    assert plan["entry"] == entry_id, plan["checks"]
    assert plan["ambiguous"] is False
    assert plan["action"] != "none", plan["reason"]
    assert plan["idempotency_key"] and len(plan["idempotency_key"]) == 64


def test_each_operator_named_signature_reaches_a_specific_entry():
    for text, expected in SEEN_TODAY.items():
        plan = RB.plan_runbook("", {"lane": LANE, "reason": text}, None, NOW, catalog=CATALOG)
        assert plan["entry"] == expected, (text, plan["entry"])


def test_every_catalog_entry_has_a_synthetic_fixture_here():
    # Zero unclassified, and no entry may exist without the >=3 tests the plan requires of it.
    assert sorted(MATCH_SAMPLE) == sorted(CATALOG)
    assert all(entry_id in CATALOG for entry_id in SEEN_TODAY.values())


def test_an_unknown_signature_is_escalated_by_the_catch_all_not_left_unclassified():
    plan = RB.plan_runbook("mystery", {"lane": LANE, "reason": "nothing matches this"}, None, NOW, catalog=CATALOG)
    assert plan["entry"] == "K05-unclassified-catch-all"
    assert plan["fallback"] is True
    assert plan["action"] == "escalate_finding"


# ---------------------------------------------------------------- per entry: precondition refusal


def _broken_evidence(entry_id: str) -> tuple[str, dict, dict | None]:
    fc, ev, contract = MATCH_SAMPLE[entry_id]
    evidence = {"lane": LANE, "signature": f"sig-{entry_id}", **ev}
    pre = _pre_names(ENTRIES[entry_id])
    if "owner_pid_dead" in pre:
        evidence["pid_alive"] = True          # the recorded owner is alive: the lock is doing its job
    elif "retries_under_budget" in pre:
        evidence.pop("retries_today", None)   # an unrecorded budget is not zero
    elif "data_is_late" in pre:
        evidence["data_age_h"] = 0.5          # fresh data cannot be "late"
    elif "rerun_not_used_today" in pre:
        evidence["reruns_today"] = 1          # the once-only re-run is spent
    else:
        evidence["lane"] = ""                 # no lane, no action
    return fc, evidence, contract


@pytest.mark.parametrize("entry_id", sorted(
    k for k, e in ENTRIES.items() if e["action"] != "escalate_finding" and e.get("preconditions")))
def test_entry_refuses_when_a_precondition_fails(entry_id):
    fc, evidence, contract = _broken_evidence(entry_id)
    plan = RB.plan_runbook(fc, evidence, contract, NOW, catalog=CATALOG)
    assert plan["entry"] == entry_id
    assert plan["action"] == "none", plan["checks"]
    assert plan["reason"].startswith("precondition_failed:"), plan["reason"]
    assert any(c["ok"] is False for c in plan["checks"])


def test_stale_lock_refuses_a_live_owner_even_when_the_age_is_large():
    plan = _plan("A02-stale-existence-lock", pid_alive=True, lock_age_s=10 * 86400)
    assert plan["action"] == "none" and "owner_pid_dead" in plan["reason"]


def test_stale_lock_refuses_a_kernel_flock_by_kind():
    plan = _plan("A02-stale-existence-lock", lock_kind="flock")
    assert plan["action"] == "none" and "lock_kind_existence" in plan["reason"]


def test_stale_lock_refuses_a_lock_younger_than_the_lane_timeout():
    plan = _plan("A02-stale-existence-lock", lock_age_s=60, lane_timeout_s=1800)
    assert plan["action"] == "none" and "lock_age_gt_lane_timeout" in plan["reason"]


def test_stale_lock_refuses_when_no_lane_timeout_is_recorded():
    _fc, ev, _ctr = MATCH_SAMPLE["A02-stale-existence-lock"]
    ev = dict(ev)
    ev.pop("lane_timeout_s")
    plan = RB.plan_runbook("stale_lock", {"lane": LANE, **ev}, None, NOW, catalog=CATALOG)
    assert plan["action"] == "none" and "lock_age_gt_lane_timeout" in plan["reason"]


def test_late_data_refuses_without_a_contract_threshold():
    plan = RB.plan_runbook("data", {"lane": LANE, "reason": "data is late", "data_age_h": 30}, {}, NOW,
                           catalog=CATALOG)
    assert plan["action"] == "none" and "contract_freshness_present" in plan["reason"]


def test_late_data_uses_the_contract_degraded_threshold_when_failed_is_absent():
    contract = {"baseline": {"freshness_degraded_after_h": 6}}
    plan = RB.plan_runbook("data", {"lane": LANE, "reason": "data is late", "data_age_h": 7, "reruns_today": 0},
                           contract, NOW, catalog=CATALOG)
    assert plan["action"] == "rerun_once_via_gateway"


def test_quota_refuses_at_the_daily_retry_cap():
    plan = _plan("B01-rate-limited-429", retries_today=3)
    assert plan["action"] == "none" and "retries_under_budget" in plan["reason"]


def test_quota_at_the_attempt_cap_escalates_instead_of_deferring_again():
    plan = _plan("B01-rate-limited-429", attempts=3)
    assert plan["action"] == "escalate_finding"
    assert "max_attempts_reached" in plan["reason"]


def test_a_noop_runbook_also_escalates_when_its_attempt_budget_is_spent():
    plan = _plan("A01-flock-held", attempts=3)
    assert plan["action"] == "escalate_finding"
    assert plan["reason"].startswith("max_attempts_reached")
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "escalation_rendered"


# ---------------------------------------------------------------- per entry: idempotent / rate-limited


@pytest.mark.parametrize("entry_id", sorted(MATCH_SAMPLE))
def test_repeat_plan_is_byte_identical_and_keeps_its_key(entry_id):
    first = _plan(entry_id)
    second = _plan(entry_id)
    assert first == second
    assert first["idempotency_key"] == second["idempotency_key"]


def test_idempotency_key_changes_across_et_days_and_not_within_one():
    same_day = _plan("K05-unclassified-catch-all", now=NOW + timedelta(hours=2))
    next_day = _plan("K05-unclassified-catch-all", now=NOW + timedelta(days=1))
    assert _plan("K05-unclassified-catch-all")["idempotency_key"] == same_day["idempotency_key"]
    assert next_day["idempotency_key"] != same_day["idempotency_key"]


MUTATING_ENTRIES = sorted(k for k, e in ENTRIES.items()
                          if e["action"] not in RB.NON_MUTATING_ACTIONS + ("escalate_finding",))


@pytest.mark.parametrize("entry_id", MUTATING_ENTRIES)
def test_a_second_mutating_action_in_the_same_hour_is_rate_limited(entry_id):
    recent = (NOW - timedelta(seconds=60)).isoformat()
    plan = _plan(entry_id, lane_last_action_at=recent)
    assert plan["action"] == "none", plan["checks"]
    assert "rate_limited" in plan["reason"]


@pytest.mark.parametrize("entry_id", sorted(
    k for k, e in ENTRIES.items() if e["action"] in ("noop_wait_recheck", "mark_weekend_expected")))
def test_observing_actions_are_not_blocked_by_the_lane_rate_limit(entry_id):
    recent = (NOW - timedelta(seconds=60)).isoformat()
    plan = _plan(entry_id, lane_last_action_at=recent)
    assert plan["action"] == ENTRIES[entry_id]["action"]


def test_quota_deferral_jitter_is_deterministic_bounded_and_in_the_future():
    plan = _plan("B01-rate-limited-429")
    again = _plan("B01-rate-limited-429")
    assert plan["next_attempt_at"] == again["next_attempt_at"]
    delta = datetime.fromisoformat(plan["next_attempt_at"]) - NOW
    assert timedelta(seconds=300) <= delta <= timedelta(seconds=600)


# ---------------------------------------------------------------- the execution-lane rail


@pytest.mark.parametrize("entry_id", MUTATING_ENTRIES)
def test_no_mutating_action_is_planned_on_an_execution_lane(entry_id):
    plan = _plan(entry_id, lane="scalp-live-orders")
    assert plan["action"] == "none"
    assert "refused_execution_lane" in plan["reason"]


def test_escalation_still_happens_on_an_execution_lane_because_a_human_must_know():
    plan = _plan("K02-broker-orders", lane="broker-execution")
    assert plan["action"] == "escalate_finding"
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "escalation_rendered"
    assert "broker" in receipt["finding_text"]
    assert "broker-execution" in receipt["finding_text"]  # the {lane} placeholder is rendered, not left literal
    assert "{lane}" not in receipt["finding_text"]


# ---------------------------------------------------------------- apply_runbook


@pytest.mark.parametrize("entry_id", sorted(MATCH_SAMPLE))
def test_dry_run_is_the_default_and_touches_nothing(entry_id, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    plan = _plan(entry_id)
    receipt = RB.apply_runbook(plan, now=NOW)
    assert receipt["schema"] == RB.RECEIPT_SCHEMA and receipt["dry_run"] is True
    assert receipt["wrote"] is False
    assert receipt["action_taken"].startswith("would_")
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before


def test_apply_refuses_an_object_that_is_not_a_plan():
    with pytest.raises(RB.RunbookPlanError):
        RB.apply_runbook({"action": "release_stale_flock"})


def test_stale_pidfile_is_archived_not_deleted(tmp_path):
    lock = tmp_path / "lane.pidfile"
    lock.write_text("999999\n", encoding="utf-8")
    plan = _plan("A02-stale-existence-lock", lock_path=str(lock))
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "stale_lock_archived"
    assert receipt["wrote"] is True and receipt["lock_probe"] == "free"
    assert not lock.exists()
    archived = tmp_path / "lane.pidfile.stale-20261108T210000Z"
    assert archived.is_file() and archived.read_text(encoding="utf-8") == "999999\n"


def test_stale_pidfile_with_a_live_flock_holder_is_refused_at_apply_time(tmp_path):
    lock = tmp_path / "lane.pidfile"
    lock.write_text("999999\n", encoding="utf-8")
    plan = _plan("A02-stale-existence-lock", lock_path=str(lock))
    fd = lock.open("r")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
    assert receipt["action_taken"] == "lock_held_refused"
    assert receipt["wrote"] is False and lock.is_file()


def test_apply_on_a_flock_kind_lock_reports_free_and_removes_nothing(tmp_path):
    lock = tmp_path / "lane.lock"
    lock.write_text("", encoding="utf-8")
    plan = _plan("A02-stale-existence-lock", lock_path=str(lock))
    plan["_apply"]["lock_kind"] = "flock"  # defence in depth: apply re-checks the kind, it does not trust the plan
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "lock_free"
    assert receipt["wrote"] is False and lock.is_file()


def test_apply_on_an_absent_lock_is_a_no_op(tmp_path):
    plan = _plan("A02-stale-existence-lock", lock_path=str(tmp_path / "gone.pidfile"))
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "lock_absent" and receipt["wrote"] is False


def test_lock_release_refuses_a_never_touch_path_even_with_a_dead_owner(tmp_path):
    forbidden = tmp_path / "persistent-state" / "lane.pidfile"
    forbidden.parent.mkdir()
    forbidden.write_text("999999\n", encoding="utf-8")
    plan = _plan("A02-stale-existence-lock", lock_path=str(forbidden))
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "refused"
    assert "never-touch" in receipt["reason"]
    assert forbidden.is_file()


def test_lock_release_refuses_a_relative_path():
    plan = _plan("A02-stale-existence-lock", lock_path="lane.pidfile")
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "refused" and "not absolute" in receipt["reason"]


def test_sqlite_lock_primitive_never_removes_a_wal_or_shm_file(tmp_path):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    wal = db_dir / "fixture.sqlite-wal"
    wal.write_text("synthetic", encoding="utf-8")
    plan = RB.plan_runbook("", {"lane": LANE, "reason": "database is locked"}, None, NOW, catalog=CATALOG)
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["action_taken"] == "sqlite_lock_reported"
    assert receipt["wrote"] is False and wal.is_file()


def test_escalation_receipt_renders_a_deterministic_finding_with_the_human_steps():
    plan = _plan("G01-disk-floor")
    first = RB.apply_runbook(plan, dry_run=False, now=NOW)
    second = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert first["action_taken"] == "escalation_rendered"
    assert first["finding_text"] == second["finding_text"]
    assert LANE in first["finding_text"] and "G01-disk-floor" in first["finding_text"]
    assert "disk_hygiene.py --dry-run" in first["finding_text"]


def test_receipt_carries_the_verify_contract_and_the_key():
    plan = _plan("C01-late-data")
    receipt = RB.apply_runbook(plan, dry_run=False, now=NOW)
    assert receipt["idempotency_key"] == plan["idempotency_key"]
    assert receipt["verify"]["kind"] == "freshness_restored"
    assert receipt["action_taken"] == "rerun_requested"
    assert receipt["at"] == NOW.isoformat()

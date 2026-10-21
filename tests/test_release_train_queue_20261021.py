"""Release Train v2, Phase 1: contracts, queue store, classifier, census and the read-only CC view (2026-10-21).

Hermetic: fake db_query callables and fake DB-API connections (the required CI runner has no psycopg2, which is
stubbed only when absent), tmp receipts and tmp STOP latches. No database, no network, no git writes, no send.
Every risk class has a positive-control fixture.
"""
from __future__ import annotations

import json
import re
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

from lib import release_train_census as CEN  # noqa: E402
from lib import release_train_classify as CLS  # noqa: E402
from lib import release_train_contracts as C  # noqa: E402
from lib import release_train_queue as Q  # noqa: E402
from lib import release_train_view as V  # noqa: E402
from lib import test_impact as TI  # noqa: E402

NOW = datetime(2026, 10, 21, 21, 30, tzinfo=timezone.utc)
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
TRAIN = "rt-20261021-1800-a1b2c3"
WIN = "2026-10-21T18:00-04:00"
TS = "2026-10-21T20:30:00+00:00"
TS2 = "2026-10-21T22:41:07+00:00"


# ── fixtures: one valid document per contract ──────────────────────────────────────────────────────────────────


def submission(**kw):
    d = {"schema": "TrainSubmission@v1", "submission_id": f"rts-1901-{SHA_A[:12]}", "repo": "PatsKiller/tardeai",
         "pr_number": 1901, "head_sha": SHA_A, "head_ref": "feat/x", "base_ref": "main", "agent": "claude:s1",
         "submitted_at": TS, "depends_on": [1899], "requested_window": "18:00",
         "local_evidence": [{"kind": "test_run", "ref": "tests/test_x.py", "sha256": None, "passed": True}]}
    d.update(kw)
    return d


def candidate(**kw):
    d = {"schema": "TrainCandidate@v1", "train_id": TRAIN, "window_id": WIN, "repo": "PatsKiller/tardeai",
         "base_sha": SHA_C, "members": [
             {"pr_number": 1899, "head_sha": SHA_B, "risk_class": "eligible", "order": 1},
             {"pr_number": 1901, "head_sha": SHA_A, "risk_class": "needs_operator", "order": 2,
              "ride_approval_ref": "approval:1901:" + SHA_A}],
         "dependency_graph": {"1901": [1899]}, "policy_version": "2026-10-21.1",
         "classifier_version": CLS.CLASSIFIER_VERSION,
         "check_manifest": ["cio-hardening", "agent-governance", "release-readiness", "ci-gate"],
         "frozen_at": TS, "candidate_sha": None}
    d.update(kw)
    return d


def evidence(**kw):
    d = {"schema": "TrainEvidence@v1", "evidence_id": "ev-ci-123456", "train_id": TRAIN, "candidate_sha": SHA_A,
         "kind": "ci_run", "name": "ci-gate", "conclusion": "success", "collected_at": TS,
         "workflow": "cio-production-hardening-ci.yml", "run_id": 123456, "run_attempt": 1}
    d.update(kw)
    return d


def control(**kw):
    d = {"schema": "ReleaseControl@v1", "control_id": "rtc-0001", "command": "stop", "actor": "john@tailnet",
         "actor_source": "command_center", "requested_at": TS, "idempotency_key": "idem-0001-stop",
         "expected_control_version": 3, "state": "requested", "reason": "operator stop"}
    d.update(kw)
    return d


def outcome(**kw):
    d = {"schema": "TrainOutcome@v1", "train_id": TRAIN, "window_id": WIN, "outcome": "RELEASED_VERIFIED",
         "members": [1899, 1901], "started_at": TS, "finished_at": TS2, "base_sha": SHA_C, "candidate_sha": SHA_A,
         "main_sha": SHA_A, "served_sha": SHA_A}
    d.update(kw)
    return d


def event(**kw):
    d = {"schema": "TrainEvent@v1", "event_id": "rte-1901-aaaaaaaaaaaa-submitted", "event_type": "submitted",
         "subject_kind": "pr", "subject_id": "pr:1901", "pr_number": 1901, "train_id": None,
         "state_after": "submitted", "actor": "agent:claude", "occurred_at": TS,
         "payload": {"head_sha": SHA_A, "agent": "claude:s1"}, "evidence_refs": [],
         "idempotency_key": "submit:1901:" + SHA_A}
    d.update(kw)
    return d


FIXTURES = {"TrainSubmission@v1": submission, "TrainCandidate@v1": candidate, "TrainEvidence@v1": evidence,
            "ReleaseControl@v1": control, "TrainOutcome@v1": outcome, "TrainEvent@v1": event}


# ── contracts ─────────────────────────────────────────────────────────────────────────────────────────────────


def _keywords(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            if k in ("properties", "$defs"):
                for sub in v.values():
                    _keywords(sub, out)
            elif k in ("items", "additionalProperties") and isinstance(v, dict):
                _keywords(v, out)
    return out


@pytest.mark.parametrize("name", sorted(C.SCHEMA_FILES))
def test_schema_files_are_named_and_use_only_supported_keywords(name):
    doc = C.load_schema(name)
    assert doc["title"] == name
    assert doc["properties"]["schema"] == {"const": name}
    assert doc["additionalProperties"] is False
    assert _keywords(doc, set()) <= C.SUPPORTED_KEYWORDS


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_positive_fixture_validates(name):
    assert C.validate(FIXTURES[name]()) == []


def test_jsonschema_agrees_with_builtin_validator_when_installed():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # CI has no jsonschema; the builtin validator is what runs there
        assert C.validate(event(seq=0)) != []  # still assert something real
        return
    cases = []
    for name, fx in FIXTURES.items():
        cases += [(name, fx()), (name, fx(schema="Nope@v1")), (name, {**fx(), "extra": 1})]
    cases += [("TrainEvent@v1", event(occurred_at="2026-10-21 20:30")),
              ("TrainEvidence@v1", evidence(conclusion="passed")),
              ("TrainSubmission@v1", submission(head_sha="ABC"))]
    for name, d in cases:
        js_ok = not list(Draft202012Validator(C.load_schema(name)).iter_errors(d))
        if d.get("occurred_at") == "2026-10-21 20:30":
            js_ok = False  # jsonschema treats format as an annotation; ours asserts it
        assert js_ok == (C.schema_errors(name, d) == []), (name, d)


@pytest.mark.parametrize("doc,needle", [
    (submission(submission_id="rts-1901-000000000000"), "submission_id must be"),
    (submission(depends_on=[1901]), "may not depend on itself"),
    (candidate(members=[{"pr_number": 1, "head_sha": SHA_A, "risk_class": "needs_operator", "order": 1}],
               dependency_graph={}), "ride_approval_ref"),
    (candidate(dependency_graph={"1899": [1901]}), "must come after"),
    (candidate(dependency_graph={"1901": [7]}), "non-member"),
    (evidence(run_id=None), "ci_run evidence needs"),
    (control(command="resume", reason=""), "resume needs a reason"),
    (control(state="stopped", command="pause", acknowledged_at=TS, stopped_at=TS2), "only a stop"),
    (control(state="acknowledged"), "needs acknowledged_at"),
    (control(state="stopped", acknowledged_at=TS2, stopped_at=TS), "out of order"),
    (outcome(outcome="NO_OP"), "NO_OP has no members"),
    (outcome(served_sha=None), "needs served_sha"),
    (outcome(outcome="ROLLED_BACK"), "needs rollback_target"),
    (outcome(finished_at="2026-10-21T19:00:00+00:00"), "finished_at before"),
    (outcome(failure_attribution={"attributed": [4242]}), "non-members"),
    (event(subject_id="pr:7"), "subject_id must be pr:1901"),
    (event(state_after="ready"), "state_after must equal"),
    (event(event_type="classified", state_after="classified", payload={}), "risk_class"),
    (event(subject_kind="train", subject_id=f"train:{TRAIN}", train_id=TRAIN, pr_number=None,
           event_type="outcome_recorded", state_after=None, payload={"outcome": "X"}), "payload:"),
])
def test_program_rules_refuse(doc, needle):
    errs = C.validate(doc)
    assert any(needle in e for e in errs), errs


def test_schema_refuses_held_member_bad_sha_naive_time_and_unknown_key():
    assert C.validate(candidate(members=[{"pr_number": 1, "head_sha": SHA_A, "risk_class": "held", "order": 1}]))
    assert C.validate(submission(head_sha="abc"))
    assert C.validate(event(occurred_at="2026-10-21T20:30:00"))  # naive: no offset
    assert C.validate({**event(), "surprise": 1})
    assert C.validate({"schema": "TrainPlan@v1"})  # proposed names stay proposed


def test_skipped_and_neutral_evidence_never_qualify():
    assert C.evidence_qualifies(evidence(), SHA_A)
    for c in ("skipped", "neutral", "pending", "failure"):
        assert not C.evidence_qualifies(evidence(conclusion=c), SHA_A)
    assert not C.evidence_qualifies(evidence(), SHA_B)  # wrong candidate


def test_more_restrictive_ordering():
    assert C.RISK_CLASSES == ("eligible", "needs_operator", "held", "blocked")
    assert C.more_restrictive("held", "needs_operator") == "held"
    assert C.more_restrictive("eligible", "blocked") == "blocked"


# ── migration ─────────────────────────────────────────────────────────────────────────────────────────────────

MIG = ROOT / "migrations" / "2026_10_21_release_queue.sql"
MIG_DOWN = ROOT / "migrations" / "2026_10_21_release_queue.down.sql"


def _sql_body(path):
    return "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("--"))


def test_migration_is_append_only_additive_and_never_drops():
    sql = _sql_body(MIG)
    assert "CREATE TABLE IF NOT EXISTS release_queue_events" in sql
    assert "CREATE TABLE IF NOT EXISTS release_queue " in sql
    assert "BEFORE UPDATE OR DELETE ON release_queue_events" in sql
    assert "BEFORE TRUNCATE ON release_queue_events" in sql
    assert "RAISE EXCEPTION 'release_queue_events is append-only" in sql
    assert "REFERENCES release_queue_events (seq)" in sql
    assert sql.strip().startswith("BEGIN;") and sql.strip().endswith("COMMIT;")
    for bad in ("DROP ", "DELETE FROM", "TRUNCATE release", "ALTER TABLE"):
        assert bad not in sql.upper().replace("BEFORE TRUNCATE", ""), bad
    down = _sql_body(MIG_DOWN)
    assert "RENAME TO release_queue_events_archived_20261021" in down
    assert "DROP" not in down.upper()


def test_migration_state_and_class_vocabularies_match_contracts():
    sql = MIG.read_text()
    blocks = re.findall(r"state(?:_after)? IN \(([^)]*)\)", sql)
    assert len(blocks) == 2
    for b in blocks:
        assert tuple(re.findall(r"'([a-z_]+)'", b)) == C.QUEUE_STATES
    risk = re.search(r"risk_class IN \(([^)]*)\)", sql).group(1)
    assert tuple(re.findall(r"'([a-z_]+)'", risk)) == C.RISK_CLASSES


# ── queue store ───────────────────────────────────────────────────────────────────────────────────────────────


def db_missing(sql, params=None, fetch="all"):
    if "to_regclass" in sql:
        return {"events": False, "queue": False}
    raise AssertionError(f"queried an unmigrated store: {sql}")


def db_down(sql, params=None, fetch="all"):
    return None


def db_raises(sql, params=None, fetch="all"):
    raise RuntimeError("boom")


class FakeDb:
    """Answers the store's read SQL from in-memory events and projection rows."""

    def __init__(self, events=(), queue=(), fail_after_probe=False):
        self.events = [dict(e) for e in events]
        self.queue = [dict(r) for r in queue]
        self.fail_after_probe = fail_after_probe
        self.sql = []

    def __call__(self, sql, params=None, fetch="all"):
        self.sql.append(sql)
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP)\b", sql), sql
        if "to_regclass" in sql:
            return {"events": True, "queue": True}
        if self.fail_after_probe:
            return None
        if "GROUP BY state" in sql:
            by = {}
            for r in self.queue:
                by[r["state"]] = by.get(r["state"], 0) + 1
            return [{"state": k, "n": v} for k, v in by.items()]
        if sql.startswith("SELECT pr_number FROM release_queue"):
            return [{"pr_number": r["pr_number"]} for r in self.queue]
        if "FROM release_queue " in sql or sql.rstrip().endswith("FROM release_queue"):
            rows = [r for r in self.queue if not params or len(params) == 1 or r["state"] == params[0]]
            return [{c: r.get(c) for c in Q.QUEUE_COLUMNS} for r in rows][: int(params[-1])]
        evs = sorted(self.events, key=lambda e: e["seq"])
        if "event_type = 'outcome_recorded' AND payload->>'outcome'" in sql:
            m = [e for e in evs if e["event_type"] == "outcome_recorded"
                 and e["payload"].get("outcome") in params[0]]
            return m[-1:]
        if "event_type = 'outcome_recorded' ORDER BY seq DESC" in sql:
            return [e for e in evs if e["event_type"] == "outcome_recorded"][-1:]
        if "HAVING bool_and" in sql:
            ids = {}
            for e in evs:
                if e.get("train_id"):
                    ids.setdefault(e["train_id"], []).append(e)
            live = [(max(x["seq"] for x in v), k) for k, v in ids.items()
                    if all(x["event_type"] != "outcome_recorded" for x in v)]
            return [{"train_id": k} for _, k in sorted(live, reverse=True)[:1]]
        if "min(seq) AS first_seq" in sql:
            first = {}
            for e in evs:
                if e.get("train_id"):
                    first.setdefault(e["train_id"], e["seq"])
            rows = sorted(((s, t) for t, s in first.items()), reverse=True)
            if "HAVING min(seq) <" in sql:
                rows = [(s, t) for s, t in rows if s < params[0]]
            return [{"train_id": t, "first_seq": s} for s, t in rows[: int(params[-1])]]
        if "train_id = ANY" in sql:
            return [e for e in evs if e.get("train_id") in params[0]]
        if "WHERE train_id = %s" in sql:
            return [e for e in evs if e.get("train_id") == params[0]]
        if "WHERE seq > %s" in sql:
            out = [e for e in evs if e["seq"] > params[0]]
            i = 1
            if "train_id = %s" in sql:
                out = [e for e in out if e.get("train_id") == params[i]]
                i += 1
            if "pr_number = %s" in sql:
                out = [e for e in out if e.get("pr_number") == params[i]]
            return out[: int(params[-1])]
        raise AssertionError(f"unexpected SQL: {sql}")


def stored(e, seq):
    return {**e, "seq": seq, "recorded_at": e["occurred_at"]}


def train_events():
    t = dict(subject_kind="train", subject_id=f"train:{TRAIN}", train_id=TRAIN, pr_number=None)
    return [
        stored(event(), 1),
        stored(event(event_id="e-frozen-0001", event_type="frozen", state_after="selected", payload=candidate(),
                     idempotency_key=None, **t), 2),
        stored(event(event_id="e-evid-0001", event_type="evidence_recorded", state_after="qualified",
                     payload=evidence(), idempotency_key=None, **t), 3),
        stored(event(event_id="e-out-0001", event_type="outcome_recorded", state_after="released",
                     payload=outcome(), occurred_at=TS2, idempotency_key=None, **t), 4),
    ]


@pytest.mark.parametrize("db,state", [(db_missing, "NOT_MIGRATED"), (db_down, "DB_UNAVAILABLE"),
                                      (db_raises, "DB_UNAVAILABLE")])
def test_reads_report_unavailable_never_zero(db, state):
    assert Q.probe(db)["state"] == state
    c = Q.read_counts(db)
    assert c["counts"] is None and c["store_state"] == state and c["reason"]
    q = Q.read_queue(db)
    assert q["rows"] is None and q["total"] is None
    assert Q.read_events(db)["events"] is None
    assert Q.read_last_outcome(db)["outcome"] is None and Q.read_last_outcome(db)["store_state"] == state
    assert Q.read_trains(db)["trains"] is None
    assert Q.read_current_train(db)["train"] is None
    assert Q.read_train(db, TRAIN)["found"] is None


def test_failure_after_a_good_probe_is_unavailable_not_empty():
    db = FakeDb(fail_after_probe=True)
    assert Q.read_counts(db)["counts"] is None
    assert Q.read_counts(db)["store_state"] == "DB_UNAVAILABLE"
    assert Q.read_queue(db)["rows"] is None
    assert Q.read_events(db)["events"] is None


def test_readable_empty_store_is_a_real_zero():
    db = FakeDb()
    c = Q.read_counts(db)
    assert c["store_state"] == "OK" and c["counts"] == {"ready": 0, "held": 0, "needs_operator": 0, "blocked": 0,
                                                        "in_train": 0, "other": 0, "total": 0}
    lo = Q.read_last_outcome(db)
    assert lo["outcome"] is None and lo["reason"] == "no_outcome_recorded"
    assert Q.read_trains(db)["trains"] == []
    assert Q.read_current_train(db)["reason"] == "no_train_in_progress"


def test_train_reads_fold_history_current_and_verified():
    evs = train_events()
    db = FakeDb(events=evs)
    t = Q.read_train(db, TRAIN, now=NOW)
    assert t["found"] and t["train"]["history_class"] == "verified"
    assert t["train"]["served_sha"] == SHA_A and t["train"]["members"][0]["pr_number"] == 1899
    assert len(t["train"]["evidence"]) == 1 and len(t["train"]["events"]) == 3
    assert Q.read_train(FakeDb(events=evs), "rt-20261022-0000-zzzz")["found"] is False
    lv = Q.read_last_verified(db)["verified"]
    assert lv == {"train_id": TRAIN, "served_sha": SHA_A, "verified_at": TS2, "outcome": "RELEASED_VERIFIED",
                  "window_id": WIN}
    trains = Q.read_trains(db)["trains"]
    assert trains[0]["member_count"] == 2 and trains[0]["history_class"] == "verified"
    assert Q.read_current_train(db)["train"] is None
    live = FakeDb(events=evs[:3])
    cur = Q.read_current_train(live, now=NOW)["train"]
    assert cur["train_id"] == TRAIN and cur["phase"] == "qualified" and cur["member_count"] == 2


def test_trains_pagination_cursor():
    evs = []
    for i, tid in enumerate(["rt-20261019-1800-aaaa", "rt-20261020-1800-bbbb", "rt-20261021-1800-cccc"]):
        evs.append(stored(event(event_id=f"e-t-{i:06d}", subject_kind="train", subject_id=f"train:{tid}",
                                train_id=tid, pr_number=None, event_type="selected", state_after="selected",
                                idempotency_key=None), i + 1))
    db = FakeDb(events=evs)
    p1 = Q.read_trains(db, limit=2)
    assert [t["train_id"] for t in p1["trains"]] == ["rt-20261021-1800-cccc", "rt-20261020-1800-bbbb"]
    p2 = Q.read_trains(db, limit=2, before_seq=p1["next_before_seq"])
    assert [t["train_id"] for t in p2["trains"]] == ["rt-20261019-1800-aaaa"] and p2["next_before_seq"] is None


def test_projection_is_a_deterministic_fold():
    evs = [stored(event(payload={"head_sha": SHA_A, "agent": "a", "requested_window": "18:00",
                                 "depends_on": [1899]}), 1),
           stored(event(event_id="e-cls-00001", event_type="classified", state_after="classified",
                        payload={"risk_class": "held", "reasons": [{"rule": "broker_active_trader"}]},
                        idempotency_key=None), 2),
           stored(event(event_id="e-held-0001", event_type="held", state_after="held", payload={},
                        idempotency_key=None), 3)]
    rows = Q.project(evs)
    assert rows == Q.project(list(evs))
    r = rows[1901]
    assert r["state"] == "held" and r["risk_class"] == "held" and r["blocker"] == "broker_active_trader"
    assert r["intended_window"] == "18:00" and r["depends_on"] == [1899] and r["last_event_seq"] == 3


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    def fetchone(self):
        return self.conn.fetchone_result

    def fetchall(self):
        return self.conn.rows


class FakeConn:
    def __init__(self, fetchone_result=(7,), rows=()):
        self.executed, self.commits, self.cursors = [], 0, 0
        self.fetchone_result, self.rows = fetchone_result, list(rows)

    def cursor(self):
        self.cursors += 1
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def test_append_event_validates_before_touching_the_db_and_is_idempotent():
    conn = FakeConn()
    with pytest.raises(Q.InvalidEvent):
        Q.append_event(conn, event(subject_id="pr:7"))
    with pytest.raises(Q.InvalidEvent):
        Q.append_event(conn, event(seq=5))
    assert conn.cursors == 0 and not conn.executed
    assert Q.append_event(conn, event()) == 7
    sql, params = conn.executed[0]
    assert sql.startswith("INSERT INTO release_queue_events") and "ON CONFLICT DO NOTHING RETURNING seq" in sql
    assert json.loads(params[list(c for c in Q.EVENT_COLUMNS if c not in ("seq", "recorded_at")).index("payload")])
    assert Q.append_event(FakeConn(fetchone_result=None), event()) is None  # duplicate idempotency key: no-op


def test_rebuild_projection_upserts_and_never_deletes():
    rows = [tuple(stored(event(), 1).get(c) for c in Q.EVENT_COLUMNS)]
    conn = FakeConn(rows=rows)
    assert Q.rebuild_projection(conn) == 1
    sqls = " ".join(s for s, _ in conn.executed)
    assert "ON CONFLICT (pr_number) DO UPDATE" in sqls
    assert not re.search(r"\b(DELETE|TRUNCATE|DROP)\b", sqls)


# ── classifier ────────────────────────────────────────────────────────────────────────────────────────────────

POLICY = CLS.load_policy()
TIERS = TI.load_tiers()
EMPTY_MAP = {"rdeps": {}}


def cls(paths, *, policy=POLICY, imap=EMPTY_MAP, semantic=None, **kw):
    items = [p if isinstance(p, dict) else {"path": p, "status": "M", "lines_added": 1, "lines_deleted": 0}
             for p in paths]
    return CLS.classify_change({"paths": items, "semantic_config": semantic or {}, **kw}, policy, tiers=TIERS,
                               impact_map=imap)


def rules(res):
    return {r["rule"] for r in res["reasons"]}


def test_real_policy_is_valid_and_unarmed():
    assert CLS.validate_policy(POLICY) == []
    assert POLICY["armed"] is False and all(w["enabled"] is False for w in POLICY["windows"])


def test_every_ci_risk_tier_category_is_mapped_by_the_train_policy():
    # A new HIGH category would classify held (unknown); this pins that the seed is reviewed when tiers change.
    assert set(TIERS["high"]) <= set(POLICY["seed"]["high_category_class"])


# positive controls, one per class

def test_positive_control_eligible():
    r = cls(["docs/ops/SOMETHING.md", "scripts/pr_overlap_check.py", "tests/test_x.py"])
    assert r["class"] == "eligible", r["reasons"]


@pytest.mark.parametrize("path,rule", [
    ("AGENTS.md", "agents_policy"),
    ("config/cc_auth.yaml", "auth_secrets"),
    (".githooks/pre-push", "guard_ci_enforcement"),
    ("scripts/run_cio_hardening_ci.py", "guard_ci_enforcement"),
    ("config/lane_registry.json", "scheduler_live_list"),
    ("config/n8n_run_allowlist.json", "scheduler_live_list"),
    ("migrations/2026_10_22_x.sql", "migrations"),
])
def test_positive_control_needs_operator_surfaces(path, rule):
    r = cls([path])
    assert r["class"] == "needs_operator" and rule in rules(r), r["reasons"]


def test_positive_control_needs_operator_deletion_oversize_and_semantic_key():
    assert cls([{"path": "docs/old.md", "status": "D"}])["class"] == "needs_operator"
    big = [{"path": f"docs/x{i}.md", "status": "A", "lines_added": 10, "lines_deleted": 0} for i in range(61)]
    r = cls(big)
    assert r["class"] == "needs_operator" and "oversized" in rules(r)
    r = cls(["config/host_comms_intent_routes.json"],
            semantic={"config/host_comms_intent_routes.json": ["routes.agents/x.enabled"]})
    assert r["class"] == "needs_operator" and "semantic_config" in rules(r)
    ok = cls(["config/host_comms_intent_routes.json"],
             semantic={"config/host_comms_intent_routes.json": ["routes.agents/x.subject_template"]})
    assert ok["class"] == "eligible", ok["reasons"]


def test_positive_control_held_unknown_risk():
    r = cls(["weird/new_top_level.bin"])
    assert r["class"] == "held" and "unknown_risk" in rules(r)
    r = cls(["config/host_comms_intent_routes.json"])  # eligible path, but keys unknown
    assert r["class"] == "held" and "unknown_risk" in rules(r)


@pytest.mark.parametrize("path", ["scripts/brokers/execution_guard.py", "scripts/active_trader/foo.py",
                                  "scripts/alpaca_stop_manager.py",
                                  "apps/command-center-v3/src/pages/ActiveTraderPage.tsx"])
def test_positive_control_broker_always_held_even_on_an_eligible_glob(path):
    r = cls([path])
    assert r["class"] == "held" and "broker_active_trader" in rules(r), r["reasons"]


def test_broker_plus_operator_surface_stays_held_more_restrictive_wins():
    r = cls(["scripts/brokers/x.py", "AGENTS.md", "docs/a.md"])
    assert r["class"] == "held"


def test_positive_control_blocked_train_self_and_invalid_input():
    r = cls(["scripts/lib/release_train_classify.py"])
    assert r["class"] == "blocked" and "train_self" in rules(r)
    assert cls(["config/release_train_policy.json", "scripts/brokers/x.py"])["class"] == "blocked"
    assert cls([])["class"] == "blocked"
    assert cls(["docs/a.md"], head_sha="abc")["class"] == "blocked"
    bad = json.loads(json.dumps(POLICY))
    bad["armed"] = True
    assert cls(["docs/a.md"], policy=bad)["class"] == "blocked"


def test_import_closure_launders_nothing():
    imap = {"rdeps": {"scripts/lib/harmless.py": ["scripts/lib/mid.py"],
                      "scripts/lib/mid.py": ["scripts/brokers/order_path.py", "tests/test_mid.py"]}}
    r = cls(["scripts/lib/harmless.py"], imap=imap)
    assert r["class"] == "held" and "import_closure" in rules(r)
    detail = next(x["detail"] for x in r["reasons"] if x["rule"] == "import_closure")
    assert "scripts/lib/harmless.py -> scripts/lib/mid.py -> scripts/brokers/order_path.py" in detail
    capped = json.loads(json.dumps(POLICY))
    capped["import_closure"]["max_depth"] = 1
    assert cls(["scripts/lib/harmless.py"], imap=imap, policy=capped)["class"] == "eligible"


def test_unavailable_closure_holds_code_but_not_docs():
    r = cls(["scripts/lib/harmless.py"], imap=None)
    assert r["class"] == "held" and "import_closure_unavailable" in rules(r) and r["closure"]["status"] == \
        "UNAVAILABLE"
    assert cls(["docs/a.md"], imap=None)["class"] == "eligible"


def test_generated_file_inherits_generator_and_consumer_class():
    assert cls(["docs/INDEX.md"])["class"] == "eligible"
    pol = json.loads(json.dumps(POLICY))
    pol["generated"].append({"globs": ["docs/generated/broker_report.md"],
                             "generator": "scripts/brokers/execution_guard.py", "consumers": []})
    r = cls(["docs/generated/broker_report.md"], policy=pol)
    assert r["class"] == "held" and any(x["rule"].startswith("generated:") for x in r["reasons"])
    pol["generated"].append({"globs": ["docs/generated/ghost.md"], "generator": "scripts/no_such_gen.py"})
    assert cls(["docs/generated/ghost.md"], policy=pol)["class"] == "held"
    gen_items = [{"path": "docs/INDEX.md", "status": "M", "lines_added": 99999, "lines_deleted": 0}]
    assert cls(gen_items)["class"] == "eligible"  # generated output is not counted for size


def test_unmapped_ci_tier_category_is_held():
    tiers = json.loads(json.dumps(TIERS))
    tiers["high"]["brand_new_surface"] = {"globs": ["docs/brand_new/**"], "gates": []}
    r = CLS.classify_change({"paths": [{"path": "docs/brand_new/a.md", "status": "M"}]}, POLICY, tiers=tiers,
                            impact_map=EMPTY_MAP)
    assert r["class"] == "held"


def test_semantic_config_diff_and_segment_matching():
    before = {"a": {"b": 1, "live": False}, "c": [1, 2], "d": 1}
    after = {"a": {"b": 2, "live": True}, "c": [1, 3], "e": 1}
    assert CLS.semantic_config_diff(before, after) == ["a.b", "a.live", "c", "d", "e"]
    pats = POLICY["semantic_config"]["protected_key_segment_patterns"]
    assert CLS._protected_keys(["routes.x.delivery_window"], pats) == []  # "delivery" is not "live"
    assert CLS._protected_keys(["lanes.x.live_arg", "x.dispatch.mode"], pats) == ["lanes.x.live_arg",
                                                                                 "x.dispatch.mode"]


def test_import_graph_uses_imports_not_string_references(tmp_path):
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts" / "lib" / "leaf.py").write_text("X = 1\n")
    (tmp_path / "scripts" / "user.py").write_text("from lib import leaf\n")
    (tmp_path / "scripts" / "mention.py").write_text('DOC = "see scripts/lib/leaf.py"\n')
    m = CLS.build_import_rdeps(tmp_path)
    assert m["rdeps"]["scripts/lib/leaf.py"] == ["scripts/user.py"]


def test_classify_cli_paths_mode_is_read_only(capsys):
    assert CLS.main(["--paths", "docs/a.md", "--no-closure", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["class"] == "eligible" and out["closure"]["status"] == "UNAVAILABLE"


# ── census ────────────────────────────────────────────────────────────────────────────────────────────────────


def pr(n, **kw):
    d = {"number": n, "title": f"PR {n}", "draft": False, "head": f"feat/{n}", "base": "main", "holds": [],
         "conflict": False, "required_checks": {"status": "PASS"}}
    d.update(kw)
    return d


def summary_doc(prs, **kw):
    d = {"schema": "PrHygieneAudit@v1", "as_of": "2026-10-21T10:30:12+00:00", "open_prs": len(prs), "prs": prs}
    d.update(kw)
    return d


CENSUS_PRS = [pr(1, head="train/rt-1"), pr(2, draft=True), pr(3, holds=["DO-NOT-MERGE"], conflict=True),
              pr(4, base="wt/x"), pr(5, conflict=True), pr(6, conflict=None),
              pr(7, required_checks={"status": "FAIL"}), pr(8, required_checks={"status": "PENDING"}),
              pr(9, required_checks={}), pr(10), pr(11)]


def test_census_buckets_are_exclusive_and_sum_to_open():
    c = CEN.build_census(summary_doc(CENSUS_PRS), queued={11})
    got = {b["name"]: b["prs"] for b in c["buckets"]}
    assert got == {"train_internal": [1], "queued": [11], "draft": [2], "held": [3], "stacked": [4],
                   "conflicting": [5], "mergeability_unknown": [6], "checks_failing": [7], "checks_pending": [8],
                   "checks_unknown": [9], "unqueued_clean": [10]}
    assert c["status"] == "COMPLETE" and c["invariant_holds"] and c["bucket_total"] == c["open_prs"] == 11
    flat = [n for b in c["buckets"] for n in b["prs"]]
    assert len(flat) == len(set(flat))
    assert all(b["as_of"] == "2026-10-21T10:30:12+00:00" for b in c["buckets"])


@pytest.mark.parametrize("doc,status,reason", [
    (summary_doc(CENSUS_PRS, open_prs=12), "ok", "invariant_mismatch"),
    (summary_doc(CENSUS_PRS + [pr(10)], open_prs=12), "ok", "duplicate_pr_rows"),
    (summary_doc([pr(1), {"title": "no number"}], open_prs=2), "ok", "row_without_number"),
    (summary_doc([pr(i) for i in range(1, 501)]), "ok", "possible_truncation"),
    (summary_doc(CENSUS_PRS), "failed", "last_run_failed"),
])
def test_census_incomplete_when_the_invariant_cannot_be_trusted(doc, status, reason):
    c = CEN.build_census(doc, receipt_status=status)
    assert c["status"] == "INCOMPLETE" and reason in c["incomplete_reasons"]


def write_receipt(tmp_path, summary, status="ok"):
    p = tmp_path / "pr-hygiene-audit_last.json"
    p.write_text(json.dumps({"schema": "LaneRunReceipt@v2", "lane_id": "pr-hygiene-audit", "status": status,
                             "finished_at": "2026-10-21T10:30:14+00:00", "summary": summary}))
    return p


def test_census_field_unavailable_stale_ok(tmp_path):
    f = CEN.load_census(tmp_path / "missing.json", now=NOW)
    assert f["freshness"] == "UNAVAILABLE" and f["value"] is None and f["reason"] == "no_receipt"
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert CEN.load_census(bad, now=NOW)["reason"] == "receipt_unreadable"
    p = write_receipt(tmp_path, summary_doc(CENSUS_PRS))
    ok = CEN.load_census(p, now=NOW)
    assert ok["freshness"] == "OK" and ok["value"]["status"] == "COMPLETE"
    assert ok["value"]["receipt"]["queue_membership"] == "UNAVAILABLE"
    stale = CEN.load_census(p, now=NOW + timedelta(days=2))
    assert stale["freshness"] == "STALE" and stale["value"] is not None
    failed = tmp_path / "f.json"
    failed.write_text(json.dumps({"status": "failed", "summary": {}, "ok_at": "2026-10-20T10:00:00+00:00"}))
    assert CEN.load_census(failed, now=NOW)["reason"] == "last_run_failed"


def test_census_reads_the_pr_hygiene_receipt_shape():
    # The lane (feat/pr-hygiene-audit-20261021 @ db7bb9da2) writes these keys in summary.prs[] via _compact().
    keys = {"number", "title", "url", "draft", "head", "head_sha", "base", "age_days", "idle_days", "holds",
            "behind_main", "conflict", "mergeability_source", "contained_in_main", "required_checks"}
    used = {"number", "head", "draft", "holds", "base", "conflict", "required_checks"}
    assert used <= keys
    assert CEN.SUMMARY_SCHEMA == "PrHygieneAudit@v1" and CEN.LANE_ID == "pr-hygiene-audit"


# ── view ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_windows_are_new_york_wall_clock_and_dst_safe():
    w = V.upcoming_windows(POLICY, NOW)  # 17:30 EDT
    assert [x["local_time"] for x in w] == ["18:00", "00:00", "06:00", "08:00"]
    assert w[0]["window_id"] == "2026-10-21T18:00-04:00" and w[0]["starts_in_seconds"] == 1800
    assert all(x["enabled"] is False for x in w)
    # 2026-11-01: EDT -> EST at 02:00. From 23:00 EDT on Oct 31 the next 00:00 is EDT, the next 06:00 is EST.
    w2 = {x["local_time"]: x for x in V.upcoming_windows(POLICY, datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc))}
    assert w2["00:00"]["window_id"] == "2026-11-01T00:00-04:00"
    assert w2["06:00"]["window_id"] == "2026-11-01T06:00-05:00"
    assert w2["06:00"]["starts_in_seconds"] == 8 * 3600  # 03:00Z -> 11:00Z
    # spring forward 2027-03-14
    w3 = {x["local_time"]: x for x in V.upcoming_windows(POLICY, datetime(2027, 3, 14, 5, 30, tzinfo=timezone.utc))}
    assert w3["06:00"]["window_id"] == "2027-03-14T06:00-04:00"


def test_stop_latch_vocabulary_and_fail_closed(tmp_path):
    s = V.read_stop(tmp_path)
    assert s["state"] == "ABSENT" and s["effective_stop"] is False and s["reader"] == "file"
    (tmp_path / "STOP.json").write_text(json.dumps({"latched_at": TS, "window_id": "w", "reason": "verify_failed"}))
    s = V.read_stop(tmp_path)
    assert s["state"] == "SET" and s["effective_stop"] and s["latch_reason"] == "verify_failed"
    (tmp_path / "STOP.json").write_text("{corrupt")
    s = V.read_stop(tmp_path)
    assert s["state"] == "UNREADABLE" and s["effective_stop"] is True
    (tmp_path / "STOP.json").write_text("[1, 2]")
    assert V.read_stop(tmp_path)["state"] == "UNREADABLE"


def test_stop_uses_release_window_read_latch_when_present(tmp_path):
    class State:
        def __init__(self, root):
            self.root = root

        def read_latch(self):
            return "SET", {"latched_at": TS}

    mod = types.SimpleNamespace(State=State, STATE_DIR=tmp_path)
    s = V.read_stop(release_window_module=mod)
    assert s["reader"] == "release_window.State.read_latch" and s["state"] == "SET"
    assert s["state_dir"] == str(tmp_path) and s["state_dir_source"] == "release_window.STATE_DIR"

    class Weird(State):
        def read_latch(self):
            return "MAYBE", None

    assert V.read_stop(release_window_module=types.SimpleNamespace(State=Weird, STATE_DIR=tmp_path))["state"] == \
        "UNREADABLE"


def test_state_dir_resolves_like_release_window(tmp_path, monkeypatch):
    mod = types.SimpleNamespace(STATE_DIR=tmp_path / "rw")
    monkeypatch.delenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", raising=False)
    assert V.resolve_state_dir(mod) == (tmp_path / "rw", "release_window.STATE_DIR")
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(tmp_path / "env"))
    assert V.resolve_state_dir(mod) == (tmp_path / "env", "env:TRADEAI_RELEASE_WINDOW_STATE_DIR")
    monkeypatch.delenv("TRADEAI_RELEASE_WINDOW_STATE_DIR")
    import release_window as RW
    assert V.resolve_state_dir() == (Path(RW.STATE_DIR), "release_window.STATE_DIR")


def _fields(data):
    return {k: v for k, v in data.items() if isinstance(v, dict) and "freshness" in v}


def test_summary_before_the_migration_is_unavailable_never_zero(tmp_path):
    d = V.build_summary(db_missing, now=NOW, census_path=tmp_path / "none.json", stop_dir=tmp_path)
    assert d["status"] == "DEGRADED"
    for k in ("queue_counts", "current_train", "last_verified", "last_outcome"):
        assert d[k]["value"] is None and d[k]["freshness"] == "UNAVAILABLE" and d[k]["reason"] == "not_migrated"
    assert d["store"]["value"]["state"] == "NOT_MIGRATED"
    assert d["census"]["freshness"] == "UNAVAILABLE" and d["census"]["reason"] == "no_receipt"
    assert d["armed"]["value"] is False and d["standing_policy"]["value"]["state"] == "NOT_CONFIGURED"
    assert d["stop"]["value"]["state"] == "ABSENT"
    assert d["state_dir"]["value"]["path"] == str(tmp_path)
    assert d["next_window"]["value"]["local_time"] == "18:00"
    for f in _fields(d).values():
        assert set(f) == {"value", "as_of", "freshness", "source", "reason"}
        if f["freshness"] == "UNAVAILABLE":
            assert f["value"] is None


def test_summary_with_a_live_store(tmp_path):
    evs = train_events()
    queue = [{"pr_number": 1901, "repo": "r/r", "state": "held", "updated_at": TS},
             {"pr_number": 1899, "repo": "r/r", "state": "ready", "updated_at": TS}]
    p = write_receipt(tmp_path, summary_doc([pr(1901), pr(1899), pr(1777)]))
    d = V.build_summary(FakeDb(events=evs, queue=queue), now=NOW, census_path=p, stop_dir=tmp_path)
    assert d["queue_counts"]["value"]["held"] == 1 and d["queue_counts"]["value"]["ready"] == 1
    assert d["last_verified"]["value"]["served_sha"] == SHA_A
    assert d["current_train"]["value"] is None and d["current_train"]["reason"] == "no_train_in_progress"
    assert d["last_outcome"]["value"]["outcome"] == "RELEASED_VERIFIED"
    b = {x["name"]: x["prs"] for x in d["census"]["value"]["buckets"]}
    assert b["queued"] == [1899, 1901] and b["unqueued_clean"] == [1777]
    assert d["census"]["value"]["receipt"]["queue_membership"] == "OK"


def test_summary_times_out_slow_sources_instead_of_blocking(tmp_path):
    def slow(sql, params=None, fetch="all"):
        time.sleep(2.0)
        return {"events": True, "queue": True}

    t0 = time.monotonic()
    d = V.build_summary(slow, now=NOW, census_path=tmp_path / "none.json", stop_dir=tmp_path, timeout_s=0.3)
    assert time.monotonic() - t0 < 1.5
    assert d["queue_counts"]["freshness"] == "UNAVAILABLE" and d["queue_counts"]["reason"] == "timeout"
    assert d["sources"]["store"]["status"] == "TIMEOUT"


def test_stop_probe_failure_renders_unavailable(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise PermissionError("nope")

    monkeypatch.setattr(V, "read_stop", boom)
    d = V.build_summary(db_missing, now=NOW, census_path=tmp_path / "x.json", stop_dir=tmp_path)
    assert d["stop"]["freshness"] == "UNAVAILABLE" and d["stop"]["value"] is None


def test_queue_payload_rows_and_unavailable(tmp_path):
    q = V.build_queue(db_missing, {}, now=NOW, census_path=tmp_path / "none.json")
    assert q["rows"] is None and q["total"] is None and q["store_state"] == "NOT_MIGRATED"
    assert q["freshness"] == "UNAVAILABLE" and q["census"]["freshness"] == "UNAVAILABLE"
    p = write_receipt(tmp_path, summary_doc([pr(1901, title="fix(x): y")]))
    queue = [{"pr_number": 1901, "repo": "r/r", "state": "held", "risk_reasons": "[]", "depends_on": "[1899]",
              "updated_at": datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)}]
    q = V.build_queue(FakeDb(queue=queue), {}, now=NOW, census_path=p)
    r = q["rows"][0]
    assert r["title"] == "fix(x): y" and r["census_bucket"] == "queued" and r["depends_on"] == [1899]
    assert r["as_of"] == "2026-10-21T19:00:00+00:00" and r["age_seconds"] == 9000


def test_handle_routes_get_only_and_leaves_stop_and_non_get_alone():
    V.clear_cache()
    db = FakeDb(events=train_events())
    assert V.handle(V.ROUTE, "POST", {}, db) is None
    assert V.handle(V.ROUTE + "/stop", "GET", {}, db) is None
    assert V.handle(V.ROUTE + "/stop", "POST", {}, db) is None
    assert V.handle(V.ROUTE + "/queue", "DELETE", {}, db) is None
    assert V.handle("/api/v2/coordination/events", "GET", {}, db) is None
    assert V.handle(V.ROUTE + "/queue", "GET", {"limit": "0"}, db)[0] == 400
    assert V.handle(V.ROUTE + "/queue", "GET", {"state": "nope"}, db)[1]["error"] == "bad_state"
    assert V.handle(V.ROUTE + "/events", "GET", {"pr": "x"}, db)[1]["error"] == "bad_pr"
    assert V.handle(V.ROUTE + "/trains", "GET", {"limit": "101"}, db)[1]["error"] == "bad_limit"
    assert V.handle(V.ROUTE + "/trains/BAD", "GET", {}, db)[1]["error"] == "bad_train_id"
    st, body = V.handle(V.ROUTE + "/trains/rt-20990101-0000-zzzz", "GET", {}, db)
    assert st == 404 and body["error"] == "train_not_found"
    st, body = V.handle(V.ROUTE + f"/trains/{TRAIN}", "GET", {}, db)
    assert st == 200 and body["data"]["train"]["history_class"] == "verified"
    st, body = V.handle(V.ROUTE + "/trains", "GET", {}, db)
    assert st == 200 and body["data"]["trains"][0]["train_id"] == TRAIN
    st, body = V.handle(V.ROUTE + "/events", "GET", {"after_seq": "2", "limit": "1"}, db)
    assert [e["seq"] for e in body["data"]["events"]] == [3] and body["data"]["next_after_seq"] == 3
    n = len(db.sql)
    V.handle(V.ROUTE + "/events", "GET", {"after_seq": "2", "limit": "1"}, db)
    assert len(db.sql) == n  # cached
    V.clear_cache()


def test_api_v2_dispatches_the_view(monkeypatch, tmp_path):
    import scripts.api_v2 as api_v2

    V.clear_cache()
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(api_v2, "_db_query", db_missing)
    st, body = api_v2.handle("/api/v2/coordination/release-train", method="GET", query={})
    assert st == 200 and body["data"]["schema"] == "ReleaseTrainSummary@v1"
    assert body["data"]["queue_counts"]["reason"] == "not_migrated"
    st, body = api_v2.handle("/api/v2/coordination/release-train/queue", method="GET", query={})
    assert st == 200 and body["data"]["rows"] is None
    V.clear_cache()


def test_api_doc_names_every_route_and_summary_field(tmp_path):
    doc = (ROOT / "docs" / "ops" / "RELEASE_TRAIN_API.md").read_text()
    for route in ("/api/v2/coordination/release-train`", "release-train/queue", "release-train/trains`",
                  "release-train/trains/{train_id}", "release-train/events"):
        assert route in doc, route
    d = V.build_summary(db_missing, now=NOW, census_path=tmp_path / "x.json", stop_dir=tmp_path)
    for k in d:
        assert f'"{k}"' in doc, k
    for k in ("ABSENT", "SET", "UNREADABLE", "ReleaseTrainList@v1", "next_before_seq"):
        assert k in doc

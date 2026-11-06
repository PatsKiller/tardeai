"""Release train D7 — live selection is census-first and honours the Work pipeline controls
(ANCHOR RELEASE_TRAIN_CENSUS_LIVE_P6_T9_20261023; DSN-20261021-release-train-P6-T9).

Measured 2026-10-23: live selection read the Phase 1 ``release_queue`` store first. Nothing submits PRs to that store
(its only writer is the controller's own event sink), so it reads OK and EMPTY, and the old store-first source treated
a readable empty store as a real empty: a live train would select nothing with ~50 open PRs in the census. PR #2033
fixed this for shadow only. The operator plan of 2026-10-23 (§2, option a plus the Work pipeline controls) makes live
census-first too:

* ``default_queue_source()`` is the census-first ``ShadowQueueSource`` for live as well; there is no store-first or
  empty-store fallback, the store is metadata and the controller keeps writing its events;
* ``tasks/batch_queue.json`` (``BatchQueue@v1``, the Work pipeline's batch queue): held PRs never ride; next-batch PRs
  go first in list order; then every other ready PR whose required checks the census saw PASS on its exact head,
  oldest first; an absent file means census-only; an unreadable one fails closed;
* eligibility is otherwise unchanged (drafts, hygiene holds, conflicts, red checks, the classifier, protected
  surfaces), and an integration conflict still ejects the PR from this train only (deferred, never dropped).

Hermetic: the controller test world under tmp_path (temp git repos, fake GitHub, fake deploy host, temp control
state). No network, DB, systemd, broker, or live server.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_release_train_controller_20261021 import NOW, StaticQueue, World  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state-root"))
    monkeypatch.setenv("TRADEAI_AGENT_CLAIMS_DIR", str(tmp_path / "claims"))


def _green(sha):
    return {"status": "PASS", "failed": [], "head": sha}


def _census(w, numbers=None, per_pr=None):
    """Census entries for the World's PRs: green on their exact head unless ``per_pr`` overrides the census row."""
    per_pr = per_pr or {}
    out = []
    for n, sha in sorted(w.repo.heads.items()):
        if numbers is not None and n not in numbers:
            continue
        census = per_pr.get(n, {"required_checks": _green(sha)})
        out.append(T.QueueEntry(pr=n, head_sha=sha, depends_on=w.deps.get(n, ()), census=dict(census)))
    return out


def _batch_queue(tmp_path, *, next_batch=(), held=(), body=None):
    p = tmp_path / "claims" / "tasks" / "batch_queue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = json.dumps(
            {
                "schema": "BatchQueue@v1",
                "next_batch": [{"pr": n, "by": "operator", "at": "2026-10-23T20:00:00Z"} for n in next_batch],
                "held_prs": {str(n): {"by": "operator", "reason": "test"} for n in held},
                "pr_notes": {},
                "updated_at": "2026-10-23T20:00:00Z",
                "history": [],
            }
        )
    p.write_text(body)
    return p


def _source(w, census=None, path=None, store=None):
    return T.ShadowQueueSource(
        store if store is not None else StaticQueue([]),
        StaticQueue(census if census is not None else _census(w)),
        T.BatchQueueControls(path),
    )


# ── the live source is census-first ───────────────────────────────────────────────────────────────


def test_default_queue_source_is_census_first_for_live_and_shadow():
    for src in (T.default_queue_source(), T.default_queue_source(shadow=True)):
        assert isinstance(src, T.ShadowQueueSource)
        assert isinstance(src.store, T.Phase1StoreQueueSource)
        assert isinstance(src.census, T.HygieneReceiptGhQueueSource)
        assert isinstance(src.controls, T.BatchQueueControls)
    assert not hasattr(T, "FallbackQueueSource")


def test_build_controller_passes_the_census_first_source_to_live_too():
    # build_controller(live=True) needs the armed GitHub App writer, so pin the source line itself.
    src = (ROOT / "scripts/lib/release_train_controller.py").read_text()
    body = src[src.index("def build_controller(") : src.index("def render(")]
    assert "queue=default_queue_source(shadow=not live)" in body
    dq = src[src.index("def default_queue_source(") : src.index("class Classifier(")]
    assert "FallbackQueueSource" not in dq and "if shadow" not in dq


def test_live_train_selects_from_the_census_when_the_store_is_empty(tmp_path):
    w = World(tmp_path)
    code, rec, _ = w.run(queue=_source(w))
    assert code == T.EXIT_OK and rec["outcome"] == T.RELEASED_VERIFIED, rec["steps"]
    assert rec["queue"]["source"].startswith("census-first:") and "store ok, 0 riding" in rec["queue"]["source"]
    assert "batch_queue absent" in rec["queue"]["source"]
    assert rec["selection"]["members"] == [11, 12]
    # the controller still writes its event log (the store's writer) for the members it selected and released
    evs = w.events()
    assert {e["pr_number"] for e in evs if e["event_type"] == "released"} == {11, 12}
    assert {e["pr_number"] for e in evs if e["event_type"] == "classified"} == {11, 12}


def test_store_rows_are_metadata_and_never_add_a_pr(tmp_path):
    w = World(tmp_path)
    store = StaticQueue(
        [
            T.QueueEntry(pr=12, head_sha="a" * 40, census={"queue_state": "ready"}),
            T.QueueEntry(pr=99, head_sha="b" * 40, census={"queue_state": "ready"}),
        ]
    )
    snap = _source(w, store=store).snapshot()
    assert [e.pr for e in snap.entries] == [11, 12]
    assert snap.entries[1].census["store"] == {"queue_state": "ready"}
    assert "never ride" in snap.source and "[99]" in snap.source


# ── the Work pipeline controls ────────────────────────────────────────────────────────────────────


def test_held_prs_never_ride_even_when_listed_next(tmp_path):
    w = World(tmp_path)
    path = _batch_queue(tmp_path, next_batch=(11,), held=(11,))
    code, rec = w.controller(live=False, queue=_source(w, path=path)).run(NOW)
    assert rec["selection"]["excluded"] == {"11": "HELD_BY_OPERATOR"}
    assert rec["selection"]["members"] == [12] and rec["selection"]["next_batch"] == []


def test_a_held_pr_is_excluded_from_a_live_train(tmp_path):
    w = World(tmp_path)
    path = _batch_queue(tmp_path, held=(12,))
    code, rec, _ = w.run(queue=_source(w, path=path))
    assert rec["outcome"] == T.RELEASED_VERIFIED, rec["steps"]
    assert rec["selection"]["members"] == [11] and rec["selection"]["excluded"] == {"12": "HELD_BY_OPERATOR"}
    assert not any(e["pr_number"] == 12 for e in w.events() if e["event_type"] in ("classified", "released"))


def test_next_batch_goes_first_in_list_order_then_oldest_first(tmp_path):
    prs = [(n, {f"docs/{n}.md": f"{n}\n"}) for n in (11, 12, 13, 14)]
    w = World(tmp_path, prs=prs)
    path = _batch_queue(tmp_path, next_batch=(14, 12))
    snap = _source(w, path=path).snapshot()
    assert [e.pr for e in snap.entries] == [14, 12, 11, 13]
    code, rec = w.controller(live=False, queue=_source(w, path=path)).run(NOW)
    assert rec["selection"]["members"] == [14, 12, 11, 13]
    assert rec["selection"]["next_batch"] == [14, 12]
    assert rec["manifest"]["members"][0]["pr"] == 14


def test_the_train_limit_keeps_the_next_batch(tmp_path):
    prs = [(n, {f"docs/{n}.md": f"{n}\n"}) for n in (11, 12, 13)]
    w = World(tmp_path, prs=prs)
    path = _batch_queue(tmp_path, next_batch=(13,))
    code, rec = w.controller(live=False, queue=_source(w, path=path), max_prs=2).run(NOW)
    assert rec["selection"]["members"] == [13, 11]
    assert rec["selection"]["excluded"] == {"12": "OVER_TRAIN_LIMIT:2"}


def test_a_dependency_still_goes_before_a_next_batch_dependent(tmp_path):
    prs = [(11, {"docs/a.md": "a\n"}), (12, {"docs/b.md": "b\n"}, (11,)), (13, {"docs/c.md": "c\n"})]
    w = World(tmp_path, prs=prs)
    path = _batch_queue(tmp_path, next_batch=(12,))
    code, rec = w.controller(live=False, queue=_source(w, path=path)).run(NOW)
    assert rec["selection"]["members"] == [11, 12, 13]


def test_absent_batch_queue_is_census_only_oldest_first(tmp_path):
    prs = [(n, {f"docs/{n}.md": f"{n}\n"}) for n in (13, 11, 12)]
    w = World(tmp_path, prs=prs)
    ctl = T.BatchQueueControls().read()
    assert ctl.state == "absent" and ctl.path == str(tmp_path / "claims" / "tasks" / "batch_queue.json")
    snap = _source(w).snapshot()
    assert snap.complete and [e.pr for e in snap.entries] == [11, 12, 13]
    code, rec = w.controller(live=False, queue=_source(w)).run(NOW)
    assert rec["selection"]["members"] == [11, 12, 13] and rec["selection"]["next_batch"] == []


@pytest.mark.parametrize(
    "body,why",
    [
        ("{broken", "batch_queue_unreadable:json"),
        (json.dumps({"schema": "Other@v1"}), "batch_queue_unreadable:schema"),
        (json.dumps(["not", "an", "object"]), "batch_queue_unreadable:schema"),
        (json.dumps({"schema": "BatchQueue@v1", "next_batch": [{"no": 1}]}), "batch_queue_unreadable:pr_number"),
        (json.dumps({"schema": "BatchQueue@v1", "held_prs": "11"}), "batch_queue_unreadable:shape"),
    ],
)
def test_an_unreadable_batch_queue_fails_closed(tmp_path, body, why):
    w = World(tmp_path)
    path = _batch_queue(tmp_path, body=body)
    snap = _source(w, path=path).snapshot()
    assert not snap.complete and why in snap.reasons
    code, rec = w.controller(live=False, queue=_source(w, path=path)).run(NOW)
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "QUEUE_INCOMPLETE" and why in rec["detail"]


def test_batch_queue_reader_reads_the_work_pipeline_format(tmp_path):
    # The shape scripts/lib/work_pipeline_commands.py writes (#2024): next_batch rows {pr, by, at}; held_prs keyed
    # by the PR number as a string.
    path = _batch_queue(tmp_path, next_batch=(30, 20, 30, 10), held=(10,))
    ctl = T.BatchQueueControls(path).read()
    assert ctl.state == "ok" and ctl.next_batch == (30, 20) and ctl.held == frozenset({10})


# ── eligibility unchanged: red checks, conflicts, drafts, the classifier ──────────────────────────


def test_only_prs_green_on_their_exact_head_ride(tmp_path):
    prs = [(n, {f"docs/{n}.md": f"{n}\n"}) for n in (11, 12, 13, 14, 15, 16)]
    w = World(tmp_path, prs=prs)
    h = w.repo.heads
    census = _census(
        w,
        per_pr={
            11: {"required_checks": {"status": "FAIL", "failed": ["ci-gate"], "head": h[11]}},
            12: {"required_checks": {"status": "PENDING", "head": h[12]}},
            13: {"required_checks": _green("e" * 40)},  # green on an older head
            14: {},  # no census row (opened after the census ran)
            15: {"required_checks": {"status": "UNKNOWN", "head": h[15]}},
        },
    )
    path = _batch_queue(tmp_path, next_batch=(11,))  # a red next-batch PR is still ejected
    code, rec = w.controller(live=False, queue=_source(w, census=census, path=path)).run(NOW)
    assert rec["selection"]["members"] == [16]
    assert rec["selection"]["excluded"] == {
        "11": "CHECKS_FAILING:ci-gate",
        "12": "NOT_GREEN_ON_HEAD:PENDING",
        "13": "NOT_GREEN_ON_HEAD:HEAD_MOVED:eeeeeeeee",
        "14": "NOT_GREEN_ON_HEAD:NO_CENSUS_ROW",
        "15": "NOT_GREEN_ON_HEAD:UNKNOWN",
    }


def test_drafts_hygiene_holds_and_census_conflicts_stay_out(tmp_path):
    prs = [(n, {f"docs/{n}.md": f"{n}\n"}) for n in (11, 12, 13, 14)]
    w = World(tmp_path, prs=prs)
    h = w.repo.heads
    census = _census(
        w,
        per_pr={
            12: {"required_checks": _green(h[12]), "holds": ["do-not-merge"]},
            13: {"required_checks": _green(h[13]), "conflict": True},
        },
    )
    census[0].draft = True  # 11
    path = _batch_queue(tmp_path, next_batch=(11, 12, 13))
    code, rec = w.controller(live=False, queue=_source(w, census=census, path=path)).run(NOW)
    assert rec["selection"]["members"] == [14]
    ex = rec["selection"]["excluded"]
    assert ex["11"] == "DRAFT" and ex["12"].startswith("HELD_BY_HYGIENE") and ex["13"] == "CONFLICTING"


def test_the_classifier_still_decides_for_a_next_batch_pr(tmp_path):
    w = World(tmp_path)

    class HoldEleven:
        version = "test-hold-11/1"
        policy_version = "test-policy/1"

        def classify(self, entry, change):
            return ("held", ["broker surface"]) if entry.pr == 11 else ("eligible", ["test"])

    path = _batch_queue(tmp_path, next_batch=(11,))
    code, rec = w.controller(live=False, queue=_source(w, path=path), classifier=HoldEleven()).run(NOW)
    assert rec["selection"]["members"] == [12] and rec["selection"]["excluded"]["11"].startswith("held:")


def test_an_integration_conflict_is_ejected_and_deferred_to_the_next_train(tmp_path):
    w = World(tmp_path, prs=[(21, {"app.txt": "A\nline2\n"}), (22, {"app.txt": "B\nline2\n"})])
    path = _batch_queue(tmp_path)
    code, rec, _ = w.run(queue=_source(w, path=path))
    assert rec["outcome"] == T.RELEASED_VERIFIED, rec["steps"]
    assert rec["selection"]["members"] == [21, 22]
    assert rec["integration"]["ejected"]["22"].startswith("MERGE_CONFLICT")
    assert [e["pr_number"] for e in w.events() if e["event_type"] == "released"] == [21]
    # deferred, not dropped: the census still lists it, so the next train considers it again on its new head
    assert 22 in [e.pr for e in _source(w, path=path).snapshot().entries]

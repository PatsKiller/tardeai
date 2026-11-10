"""The Releases & Schedules page's deployment-log probe (LQ-20261107-1794), 2026-11-10.

The operator asked for a deployment log on the Ops page: what was deployed, when, what it fixed, and what the truth
of each fix is. The data is a lead-owned ``DeploymentLog@v1`` file rebuilt after every activation; this probe is the
only thing between that file and the page.

Hermetic (AGENTS.md §24.6): every path is under ``tmp_path``, ``TRADEAI_STATE_ROOT`` points at it, git / crontab are
injected stubs, and no fixture is real. The repository is PUBLIC, so the synthetic rows below carry invented ticket
ids and subjects — no real ticker, holding, account or path.

The safety property under test is the operator's own: **never render VERIFIED unless the builder recorded VERIFIED.**
So the probe is pinned to copy ``items[].truth`` verbatim — no upper-casing, no promotion of a truthy string, no
default state — and to answer UNAVAILABLE (never an empty, all-good log) for every way the file can fail to be read.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import releases_schedules_view as R  # noqa: E402

NOW = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)  # 11:00 ET
GEN = "2026-11-10T10:55:13-05:00"
RELEASE = "2476dace2-live-integration-20261110-105345"


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRADEAI_DEPLOYMENT_LOG", raising=False)
    R.clear_cache()
    yield
    R.clear_cache()


def _item(lq: str, state, text: str | None = "recorded by the builder") -> dict:
    return {"lq": lq, "title": f"the fix for {lq}", "owner": "agent-example", "truth": {"state": state, "text": text}}


def _deploy(sha: str = "abcdef123", **kw) -> dict:
    row = {"activated_at": "2026-11-10T10:54:24-05:00", "activated_et": "Tue 11-10 10:54 ET", "kind": "deploy",
           "release": f"{sha}-live-integration-20261110-105345", "sha": sha,
           "previous_release": "000011112-live-integration-20261110-104729", "previous_sha": "000011112",
           "commit_count": 1,
           "commits": [{"sha": "fedcba987", "subject": "LQ-9001: invented subject for a synthetic fixture",
                        "lq": ["LQ-9001"]}],
           "items": [_item("LQ-9001", "VERIFIED")], "is_current": False}
    row.update(kw)
    return row


def _write(tmp_path: Path, rows: list, **top) -> Path:
    doc = {"schema": "DeploymentLog@v1", "generated_at": GEN, "since": "2026-11-03", "current_release": RELEASE,
           "summary": {"deploys": len(rows), "rollbacks": 0, "lq_items": 1, "verified": 1, "not_remeasured": 0},
           "truth_rule": "VERIFIED only when the outcome was re-measured on live", "deployments": rows}
    doc.update(top)
    p = tmp_path / "deployments.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ── the happy path ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_probe_serves_the_log_it_was_given(tmp_path):
    f = R.read_deployment_log(_write(tmp_path, [_deploy(is_current=True)]), NOW, serving_release=RELEASE)
    assert f["freshness"] == "OK" and f["reason"] is None
    assert f["as_of"] == GEN and f["age_s"] == 287  # 10:55:13 ET -> 11:00:00 ET
    assert f["source"] == "file:deployment_log/deployments.json"  # relative: no home path on the wire
    v = f["value"]
    assert v["since"] == "2026-11-03" and v["current_release"] == RELEASE
    assert v["deployments_total"] == 1 and v["shown"] == 1 and v["truncated"] is False
    assert v["summary"]["verified"] == 1 and "re-measured" in v["truth_rule"]
    row = v["deployments"][0]
    assert row["activated_et"] == "Tue 11-10 10:54 ET" and row["short_sha"] == "abcdef123"
    assert row["kind"] == "deploy" and row["rollback"] is False and row["is_current"] is True


def test_a_rollback_kind_is_flagged_from_the_kind_alone(tmp_path):
    p = _write(tmp_path, [_deploy(kind="rollback"), _deploy(sha="123456789", kind="rollback/reactivate")])
    rows = R.read_deployment_log(p, NOW)["value"]["deployments"]
    assert [r["rollback"] for r in rows] == [True, True]


# ── truth travels verbatim: no promotion, no default, no upper-casing ──────────────────────────────────────────────

def test_truth_is_copied_verbatim_and_never_promoted(tmp_path):
    states = ["VERIFIED", "NOT_REMEASURED", "NO_CHANGE", "UNTRACKED", "verified", "", None, "SOMETHING_NEW"]
    row = _deploy(items=[_item(f"LQ-{9000 + i}", s, f"text {i}") for i, s in enumerate(states)])
    got = R.read_deployment_log(_write(tmp_path, [row]), NOW)["value"]["deployments"][0]["items"]
    assert [i["truth"]["state"] for i in got] == states  # exactly what the builder wrote, in the same case
    assert [i["truth"]["text"] for i in got] == [f"text {i}" for i in range(len(states))]
    # the only string this module is allowed to call VERIFIED is the builder's own VERIFIED
    assert [i["lq"] for i in got if i["truth"]["state"] == "VERIFIED"] == ["LQ-9000"]


def test_a_missing_truth_object_does_not_become_a_state(tmp_path):
    row = _deploy(items=[{"lq": "LQ-9002", "title": "no truth member", "owner": "x"}])
    item = R.read_deployment_log(_write(tmp_path, [row]), NOW)["value"]["deployments"][0]["items"][0]
    assert item["truth"] == {"state": None, "text": None}


def test_is_current_is_strictly_the_builders_boolean(tmp_path):
    rows = [_deploy(kind="deploy", is_current=True), _deploy(sha="111111111", is_current="true"),
            _deploy(sha="222222222", is_current=1), _deploy(sha="333333333")]
    got = R.read_deployment_log(_write(tmp_path, rows), NOW)["value"]["deployments"]
    assert [r["is_current"] for r in got] == [True, False, False, False]


# ── size: subjects, per-row cap, row cap ──────────────────────────────────────────────────────────────────────────

def test_commits_are_trimmed_to_subjects_and_the_count_is_kept(tmp_path):
    row = _deploy(commit_count=2, commits=[{"sha": "a" * 9, "subject": "one", "lq": ["LQ-1"]},
                                           {"sha": "b" * 9, "subject": "two", "lq": []},
                                           {"sha": "c" * 9, "lq": ["LQ-3"]}])  # no subject: not a line to show
    got = R.read_deployment_log(_write(tmp_path, [row]), NOW)["value"]["deployments"][0]
    assert got["commits"] == ["one", "two"] and got["commits_shown"] == 2 and got["commit_count"] == 2
    assert "sha" not in json.dumps(got["commits"])


def test_commit_subjects_are_capped_per_row_and_the_true_count_survives(tmp_path):
    big = _deploy(commit_count=500, commits=[{"sha": "d" * 9, "subject": f"subject {i}"} for i in range(500)])
    got = R.read_deployment_log(_write(tmp_path, [big]), NOW)["value"]["deployments"][0]
    assert got["commits_shown"] == R.MAX_COMMITS_PER_DEPLOYMENT == len(got["commits"])
    assert got["commit_count"] == 500  # the page can still say "500 commits"


def test_only_the_newest_rows_are_served_and_the_total_is_stated(tmp_path):
    rows = [_deploy(sha=f"{i:09d}", release=f"{i:09d}-synthetic") for i in range(210)]
    v = R.read_deployment_log(_write(tmp_path, rows), NOW)["value"]
    assert v["deployments_total"] == 210 and v["shown"] == R.MAX_DEPLOYMENTS == 200 and v["truncated"] is True
    assert v["deployments"][0]["release"] == "000000000-synthetic"  # the file's order (newest first) is preserved


def test_the_served_payload_is_bounded_even_for_an_absurd_file(tmp_path):
    """The file grows every deploy. A worst-case row must not make the response proportional to the file."""
    rows = [_deploy(sha=f"{i:09d}", commit_count=5000,
                    commits=[{"sha": "e" * 9, "subject": "x" * 120} for _ in range(5000)],
                    items=[_item(f"LQ-{9000 + j}", "NOT_REMEASURED", "t" * 200) for j in range(200)])
            for i in range(210)]
    v = R.read_deployment_log(_write(tmp_path, rows), NOW)["value"]
    assert len(json.dumps(v)) < R.MAX_DEPLOYMENT_LOG_BYTES


# ── every failure is UNAVAILABLE with a reason, never an empty all-good log ───────────────────────────────────────

def test_a_missing_file_is_unavailable_never_an_empty_log(tmp_path):
    f = R.read_deployment_log(tmp_path / "nothing-here.json", NOW)
    assert f["freshness"] == "UNAVAILABLE" and f["value"] is None and "absent" in f["reason"]
    assert f["as_of"] is None and f["age_s"] is None


def test_a_corrupt_file_is_unavailable(tmp_path):
    p = tmp_path / "deployments.json"
    p.write_text("{not json at all", encoding="utf-8")
    f = R.read_deployment_log(p, NOW)
    assert f["freshness"] == "UNAVAILABLE" and f["value"] is None and "unreadable" in f["reason"]


def test_a_json_document_that_is_not_an_object_is_unavailable(tmp_path):
    p = tmp_path / "deployments.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert R.read_deployment_log(p, NOW)["freshness"] == "UNAVAILABLE"


def test_a_foreign_schema_is_unavailable_and_named(tmp_path):
    f = R.read_deployment_log(_write(tmp_path, [_deploy()], schema="DeploymentLog@v2"), NOW)
    assert f["freshness"] == "UNAVAILABLE" and f["value"] is None and "DeploymentLog@v2" in f["reason"]


def test_a_log_without_a_deployments_list_is_unavailable(tmp_path):
    f = R.read_deployment_log(_write(tmp_path, [], deployments="nope"), NOW)
    assert f["freshness"] == "UNAVAILABLE" and "deployments list" in f["reason"]


def test_an_oversized_file_is_unavailable_and_says_so_with_its_size(tmp_path, monkeypatch):
    """448 KB today and growing: the 512 KB default reader would call a real log corrupt. The cap is explicit and
    the reason carries the size, so "too large" is never mistaken for "unreadable" or for an empty log."""
    monkeypatch.setattr(R, "MAX_DEPLOYMENT_LOG_BYTES", 4096)
    p = _write(tmp_path, [_deploy(commit_count=99, commits=[{"sha": "f" * 9, "subject": "y" * 400} for _ in range(99)])])
    assert p.stat().st_size > 4096
    f = R.read_deployment_log(p, NOW)
    assert f["freshness"] == "UNAVAILABLE" and f["value"] is None
    assert "too large" in f["reason"] and str(p.stat().st_size) in f["reason"] and "unreadable" not in f["reason"]


# ── currentness: an unstamped or behind log is STALE, and the data still renders ──────────────────────────────────

def test_a_log_without_a_generated_stamp_is_stale_not_current(tmp_path):
    doc_path = _write(tmp_path, [_deploy()])
    doc = json.loads(doc_path.read_text())
    doc.pop("generated_at")
    doc_path.write_text(json.dumps(doc))
    f = R.read_deployment_log(doc_path, NOW)
    assert f["freshness"] == "STALE" and "does not state when" in f["reason"]
    assert f["value"]["shown"] == 1 and f["as_of"] is None


def test_a_log_behind_the_serving_release_is_stale_and_names_both(tmp_path):
    p = _write(tmp_path, [_deploy()])
    f = R.read_deployment_log(p, NOW, serving_release="999999999-live-integration-20261110-120000")
    assert f["freshness"] == "STALE" and f["value"]["shown"] == 1
    assert RELEASE in f["reason"] and "999999999-live-integration-20261110-120000" in f["reason"]


def test_the_right_current_release_is_not_flagged(tmp_path):
    p = _write(tmp_path, [_deploy()])
    assert R.read_deployment_log(p, NOW, serving_release=RELEASE)["freshness"] == "OK"
    assert R.read_deployment_log(p, NOW, serving_release=None)["freshness"] == "OK"  # nothing to compare: no claim


# ── wiring: the section exists in the response, resolves from the state root, and reports its own source ──────────

def _build(**paths):
    base = {k: Path("/nonexistent/nowhere") for k in
            ("releases_base", "deploy_state_dir", "canonical_source", "release_window_state_dir", "ledger",
             "live_lanes_env", "registry", "main_ci_receipt", "deployment_log")}
    base.update(paths)
    return R.build(lambda *a, **k: None, now=NOW, paths=base, git=lambda a: (128, ""),
                   crontab_reader=lambda: ("", "none", "crontab -l unavailable", None))


def test_build_serves_the_section_and_its_own_source(tmp_path):
    d = _build(deployment_log=_write(tmp_path, [_deploy(is_current=True)]))
    assert d["deployment_log"]["freshness"] == "OK"
    assert d["deployment_log"]["value"]["deployments"][0]["is_current"] is True
    assert d["sources"]["deployment_log"]["status"] == "OK"


def test_build_keeps_an_absent_log_unavailable_and_never_green(tmp_path):
    d = _build()
    assert d["deployment_log"]["freshness"] == "UNAVAILABLE" and d["deployment_log"]["value"] is None
    assert d["deployment_log"]["reason"] and d["sources"]["deployment_log"]["status"] == "OK"
    assert d["status"] != "OK"


def test_the_default_path_follows_the_state_root(tmp_path, monkeypatch):
    """No hardcoded home path: the probe resolves where the lead's builder writes, under the state root."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    p = R.default_paths()["deployment_log"]
    assert p == tmp_path / "state" / "data" / "runtime" / "deployment_log" / "deployments.json"
    monkeypatch.setenv("TRADEAI_DEPLOYMENT_LOG", str(tmp_path / "other.json"))
    assert R.default_paths()["deployment_log"] == tmp_path / "other.json"


def test_the_probe_writes_nothing(tmp_path):
    p = _write(tmp_path, [_deploy()])
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    R.read_deployment_log(p, NOW, serving_release=RELEASE)
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["deployments.json"]

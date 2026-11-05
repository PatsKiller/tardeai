"""Approvals > Activations: packets reconciled with what is live; humane titles, proposer and age.

Synthetic registry, packets and claims only. No live store, no network, no host files.
"""
import json
import subprocess

from scripts.lib import activation_reconcile as R
from scripts.lib import operator_approvals as core

REGISTRY = {
    "lane-on": {"lane_id": "lane-on", "state": "ACTIVE", "state_since": "2032-01-02",
                "scheduler": {"kind": "n8n"}, "dispatch": {"mode": "live"}},
    "lane-off": {"lane_id": "lane-off", "state": "NEVER_SCHEDULED", "scheduler": {"kind": "systemd"}},
}


def facts(**overrides):
    base = dict(registry=REGISTRY, served_policy="9.1.0", n8n_live={"lane-on"},
                is_released=lambda sha: sha.startswith("a"))
    base.update(overrides)
    return R.Facts(**base)


def test_every_live_check_true_resolves_as_already_live():
    target = {"live_when": [{"lane": "lane-on", "state": "ACTIVE", "scheduler": "n8n", "dispatch_mode": "live"},
                            {"n8n_live": "lane-on"}, {"released_commit": "a" * 40}]}
    result = R.reconcile(target, facts())
    assert result["state"] == R.LIVE
    assert result["reason"].startswith("Already live: lane lane-on ACTIVE on n8n · dispatch live since 2032-01-02")
    assert len(result["evidence"]) == 3


def test_a_failing_or_unreadable_check_keeps_the_packet_waiting_and_names_it():
    result = R.reconcile({"live_when": [{"lane": "lane-on"}, {"lane": "lane-off", "state": "ACTIVE"}]}, facts())
    assert result["state"] == R.WAITING
    assert "lane lane-off: state NEVER_SCHEDULED (needs ACTIVE)" in result["reason"]
    unknown = R.reconcile({"live_when": [{"n8n_live": "lane-on"}]}, facts(n8n_live=None))
    assert unknown["state"] == R.WAITING and "n8n live list unreadable" in unknown["reason"]
    missing = R.reconcile({"live_when": [{"lane": "lane-gone"}]}, facts())
    assert missing["state"] == R.WAITING and "not in the lane registry" in missing["reason"]
    unreleased = R.reconcile({"live_when": [{"released_commit": "b" * 40}]}, facts())
    assert unreleased["state"] == R.WAITING and "not in the served release" in unreleased["reason"]
    no_registry = R.reconcile({"live_when": [{"lane": "lane-on"}]}, facts(registry=None))
    assert no_registry["state"] == R.WAITING and "unreadable" in no_registry["reason"]


def test_no_declared_target_stays_waiting_and_says_why():
    result = R.reconcile(None, facts())
    assert result["state"] == R.WAITING and "No activation target is declared" in result["reason"]


def test_a_policy_package_built_on_an_older_version_is_superseded():
    result = R.reconcile({"policy_base": "9.0.0"}, facts())
    assert result["state"] == R.SUPERSEDED and "9.0.0" in result["reason"] and "9.1.0" in result["reason"]
    same = R.reconcile({"policy_base": "9.1.0"}, facts())
    assert same["state"] == R.WAITING


def test_title_comes_from_the_readme_heading_never_the_slug():
    readme = "# Fixture packet: switch the widget on\n\n```\nStatus: DRAFT\nas_of: 2032-01-03T10:00:00Z\n```\n"
    meta = R.describe(kind="packet", ident="fixture-switch-20320103", path="docs/ops/packets/x/README.md",
                      readme_text=readme, owner=None, target=None, added=None)
    assert meta["title"] == "Fixture packet: switch the widget on"
    assert meta["created_at"] == "2032-01-03T10:00:00Z" and meta["created_at_basis"] == "README as_of"
    assert R.humanize_slug("fixture-switch-20320103") == "Fixture switch (Jan 3)"


def test_proposer_order_owner_then_claim_then_trailer_then_unknown_with_reason():
    owned = R.describe(kind="packet", ident="p", path="a", readme_text="# T\nOwner: platform. More prose here.\n",
                       owner=None, target=None, added=None)
    assert owned["proposed_by"] == "platform" and owned["proposed_by_basis"] == "packet owner"
    added = {"sha": "c" * 40, "at": "2032-01-04T00:00:00Z", "agent": "Fixture Agent"}
    claimed = R.describe(kind="packet", ident="p", path="a", readme_text="# T\n", owner=None, target=None,
                         added=added, claims={"c" * 40: "vendor/agent-x"})
    assert claimed["proposed_by"] == "vendor/agent-x (claim)" and claimed["created_at"] == "2032-01-04T00:00:00Z"
    trailer = R.describe(kind="packet", ident="p", path="a", readme_text="# T\n", owner=None, target=None, added=added)
    assert trailer["proposed_by"] == "Fixture Agent (agent)"
    unknown = R.describe(kind="packet", ident="p", path="a", readme_text="# T\n", owner=None, target=None, added=None)
    assert unknown["proposed_by"].startswith("unknown — ") and unknown["created_at"] is None
    design = R.describe(kind="design", ident="DSN-1", path="d", readme_text=None, owner="Operator; prepared by x",
                        target=None, added=None, title="Fixture design title")
    assert design["title"] == "Fixture design title" and design["proposed_by"] == "Operator"


def test_claim_index_maps_commit_shas_to_vendor_and_agent(tmp_path):
    (tmp_path / "c1.json").write_text(json.dumps({"vendor": "v", "agent": "a", "head_sha": "d" * 40}))
    (tmp_path / "bad.json").write_text("{not json")
    assert R.claim_index(tmp_path) == {"d" * 40: "v/a"}
    assert R.claim_index(None) == {}


def test_added_commits_parses_one_git_log_call():
    log = ("@@" + "e" * 40 + "|2032-01-05T09:00:00-05:00|Fixture Agent <x@example.test>\n\n"
           "docs/ops/packets/one/README.md\n")
    calls = []

    def git(*args):
        calls.append(args)
        return log
    found = R.added_commits(git, ["docs/ops/packets/one/README.md"], "f" * 40)
    assert found["docs/ops/packets/one/README.md"] == {"sha": "e" * 40, "at": "2032-01-05T14:00:00Z", "agent": "Fixture Agent"}
    assert len(calls) == 1 and calls[0][:2] == ("log", "f" * 40)

    def broken(*args):
        raise subprocess.CalledProcessError(128, "git")
    assert R.added_commits(broken, ["x"], "f" * 40) == {}


def test_queue_keeps_resolved_rows_out_of_the_pending_count_but_returns_them():
    sha = "1" * 40
    doc = core.document("{}", source_sha=sha, version="fixture-packet")
    waiting = core.item(ident="design:waiting", kind="ACTIVATE", title="Waiting fixture", proposed_by="p",
                        created_at="2032-01-01T00:00:00Z", doc=doc, source="design_registry")
    done = core.item(ident="design:done", kind="ACTIVATE", title="Done fixture", proposed_by="p",
                     created_at="2032-01-02T00:00:00Z", doc=doc, source="design_registry")
    done["reconcile"] = {"state": "LIVE", "evidence": ["lane x ACTIVE"], "reason": "Already live: lane x ACTIVE."}
    from datetime import datetime, timezone
    data = core.queue_projection({"designs": lambda: {"rows": [waiting], "resolved": [done], "gap": None}},
                                 decisions=[], now=datetime(2032, 1, 3, tzinfo=timezone.utc))
    assert [r["id"] for r in data["items"]] == ["design:waiting"]
    assert data["pending_count"] == 1
    assert [r["id"] for r in data["resolved"]] == ["design:done"]


def test_every_declared_target_names_a_real_packet_and_a_valid_check():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    targets = R.load_targets(root)
    assert targets
    registry = R.load_registry(root)
    for packet, target in targets.items():
        assert (root / "docs/ops/packets" / packet / "README.md").is_file(), packet
        for check in target.get("live_when") or []:
            assert set(check) & {"lane", "n8n_live", "released_commit"}, (packet, check)
            if "lane" in check:
                assert check["lane"] in registry, (packet, check["lane"])

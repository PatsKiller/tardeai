"""Release Train v2 merge freeze enforcement (AGENTS.md §25.3; docs/ops/RELEASE_TRAIN_MERGE_FREEZE.md).

Proves, hermetically (temp state dirs, fake gh, injected clocks; the repo policy is read as shipped):
  * window math from the policy schedule: weekday 12:00/18:00, Saturday 06-21 every 3 h, Sunday 00-21 every 3 h,
    no Saturday/Monday 00:00 or 03:00; the freeze starts 30 real minutes before a window across both DST changes;
  * terminal detection from the train's records: request pending, receipt ACKNOWLEDGED (running, stale flagged),
    terminal receipts (NO_OP, REFUSED, RELEASED_VERIFIED) end it, a live train state without an outcome holds it,
    an expired request or a window with no request releases it after grace;
  * unreadable receipts: frozen in the 30-min pre-window only, open after the window opens, with a warning;
    an unreadable policy reads frozen; STOP lifts all but a running train;
  * exemptions: the train's own train/<id> batch PR (same repo, base main, optional author pin), the operator label
    freeze-exempt, a base other than main;
  * CI: an open batch PR freezes everyone else; statuses are posted only on change, always for the event PR, never on
    drafts; the lead window turns them pending; dry run posts nothing;
  * the merge helpers refuse (check-pr exit 3, Tier 2 MERGE_FREEZE, agent_merge_pr.sh), and the readers of main's
    required checks (census, tree-attested promote, claim lifecycle, Work pipeline) drop the freeze context;
  * the Releases & schedules view carries the verdict; the workflow is shaped as documented.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import yaml

from scripts import release_train_freeze as CLI
from scripts.lib import merge_freeze_context as MFC
from scripts.lib import release_train_freeze as F
from scripts.lib import release_train_window_view as V

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
UTC = timezone.utc
CFG = F.load_config()
POLICY = V.read_policy()


def et(y, mo, d, h, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=ET)


def ci(now, **kw):
    return F.evaluate(now, policy=kw.pop("policy", POLICY), cfg=kw.pop("cfg", CFG), mode="ci", **kw)


def host(now, sdir, **kw):
    return F.evaluate(now, policy=kw.pop("policy", POLICY), cfg=kw.pop("cfg", CFG), mode="host", state_dir=sdir, **kw)


def codes(v):
    return [r["code"] for r in v["reasons"]]


# ── config pins ───────────────────────────────────────────────────────────────────────────────────────────────


def test_config_valid_and_pinned_to_its_sources():
    assert F.validate_config(CFG) == []
    assert CFG["starts_min_before_window"] == 30 and CFG["exempt_label"] == "freeze-exempt"
    n8n = json.loads((ROOT / "config" / "release_train_n8n.json").read_text())
    assert CFG["request_grace_min"] == n8n["grace_min"]
    example = json.loads((ROOT / "config" / "release_train_delegation.example.json").read_text())
    assert example["merge_freeze"] == {"starts_min_before_window": CFG["starts_min_before_window"],
                                       "ends": CFG["ends"], "applies_to": CFG["applies_to"]}
    from scripts.lib import release_capability as CAP

    assert F.TRAIN_ID_RE.pattern == CAP.TRAIN_RE.pattern
    from scripts.lib import agent_claim_lifecycle as LC

    assert MFC.FREEZE_CONTEXT == F.FREEZE_CONTEXT == LC.MERGE_FREEZE_CONTEXT == "train-merge-freeze"
    assert POLICY is not None and POLICY["armed"] is True


def test_config_rejects_out_of_bounds():
    bad = dict(CFG, starts_min_before_window=-1, ends="whenever", train_pr_authors="x")
    errs = F.validate_config(bad)
    assert any("starts_min_before_window" in e for e in errs) and any("ends" in e for e in errs)
    assert any("train_pr_authors" in e for e in errs)


# ── window math ───────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("when,frozen,window", [
    (et(2026, 10, 26, 11, 29, 59), False, None),            # Mon: 1 s before the 12:00 freeze
    (et(2026, 10, 26, 11, 30), True, "12:00"),
    (et(2026, 10, 26, 11, 59, 59), True, "12:00"),
    (et(2026, 10, 26, 17, 30), True, "18:00"),
    (et(2026, 10, 26, 5, 45), False, None),                 # weekday 06:00 is not scheduled
    (et(2026, 10, 26, 8, 45), False, None),                 # 09:00 is weekend only
    (et(2026, 10, 30, 23, 45), False, None),                # Fri night: no Saturday 00:00
    (et(2026, 10, 31, 2, 45), False, None),                 # no Saturday 03:00
    (et(2026, 10, 31, 5, 30), True, "06:00"),               # Saturday opens at 06:00
    (et(2026, 10, 31, 8, 40), True, "09:00"),
    (et(2026, 10, 31, 14, 31), True, "15:00"),
    (et(2026, 10, 31, 20, 59), True, "21:00"),
    (et(2026, 10, 31, 23, 30), True, "00:00"),              # Sunday 00:00 (the Saturday-night overnight)
    (et(2026, 11, 2, 2, 45), False, None),                  # Mon 03:00 is not scheduled (Nov 2)
    (et(2026, 11, 1, 23, 45), False, None),                 # Sun night: no Monday 00:00
])
def test_schedule_freezes_exactly_the_policy_windows(when, frozen, window):
    v = ci(when)
    assert v["frozen"] is frozen, (when, v["summary"])
    if window:
        r = v["reasons"][0]
        assert r["code"] == F.PRE_WINDOW
        assert datetime.fromisoformat(r["starts_at"]).astimezone(ET).strftime("%H:%M") == window


def test_dst_fall_back_freeze_is_thirty_real_minutes():
    # Sun 2026-11-01: 02:00 EDT -> 01:00 EST. The 03:00 EST window is 08:00 UTC; its freeze starts 07:30 UTC.
    start = et(2026, 11, 1, 3)
    assert start.astimezone(UTC) == datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    assert not ci(datetime(2026, 11, 1, 7, 29, 59, tzinfo=UTC))["frozen"]
    v = ci(datetime(2026, 11, 1, 7, 30, tzinfo=UTC))
    assert codes(v) == [F.PRE_WINDOW] and v["reasons"][0]["freeze_from"] == "2026-11-01T07:30:00+00:00"
    # the Sunday 00:00 window that night is still EDT (04:00 UTC)
    assert ci(datetime(2026, 11, 1, 3, 30, tzinfo=UTC))["reasons"][0]["starts_at"] == "2026-11-01T04:00:00+00:00"
    # the first weekday after: Mon 12:00 EST = 17:00 UTC, freeze from 16:30 UTC
    assert not ci(datetime(2026, 11, 2, 16, 29, tzinfo=UTC))["frozen"]
    assert ci(datetime(2026, 11, 2, 16, 30, tzinfo=UTC))["frozen"]


def test_dst_spring_forward_freeze_is_thirty_real_minutes():
    # Sun 2026-03-08: 02:00 EST -> 03:00 EDT. 03:00 EDT = 07:00 UTC; the freeze starts 06:30 UTC (01:30 EST),
    # not at a wall-clock 02:30 that does not exist.
    assert not ci(datetime(2026, 3, 8, 6, 29, 59, tzinfo=UTC))["frozen"]
    v = ci(datetime(2026, 3, 8, 6, 30, tzinfo=UTC))
    assert v["frozen"] and v["reasons"][0]["starts_at"] == "2026-03-08T07:00:00+00:00"
    assert datetime(2026, 3, 8, 6, 30, tzinfo=UTC).astimezone(ET).strftime("%H:%M %Z") == "01:30 EST"
    # Saturday 2026-03-07 21:00 EST is 02:00 UTC
    assert ci(datetime(2026, 3, 8, 1, 30, tzinfo=UTC))["reasons"][0]["starts_at"] == "2026-03-08T02:00:00+00:00"


def test_next_freeze_and_imminent_lead():
    v = ci(et(2026, 10, 26, 11, 10))
    assert not v["frozen"] and v["next_freeze"]["freeze_from"] == "2026-10-26T15:30:00+00:00"
    assert v["imminent"] is False
    v = ci(et(2026, 10, 26, 11, 16))
    assert not v["frozen"] and v["imminent"] is True
    assert "Mon 11:30 ET" in v["summary"]


def test_not_armed_never_freezes_and_unreadable_policy_freezes():
    off = dict(POLICY, armed=False)
    assert not ci(et(2026, 10, 26, 11, 45), policy=off)["frozen"]
    v = ci(et(2026, 10, 26, 9, 0), policy=None)
    assert codes(v) == [F.POLICY_UNREADABLE] and v["armed"] is None


def test_delegation_longer_freeze_wins():
    t = et(2026, 10, 26, 11, 20)
    assert not ci(t)["frozen"]
    v = ci(t, delegation_min=45)
    assert v["frozen"] and v["starts_min_before_window"] == 45
    assert ci(t, delegation_min=10)["starts_min_before_window"] == 30   # never shorter than the repo config


# ── terminal detection (host) ─────────────────────────────────────────────────────────────────────────────────

START = et(2026, 10, 26, 12)          # Monday 12:00 ET
RID = "rtw-20261026-1200-win"


def spool(tmp_path) -> Path:
    s = tmp_path / "release_window"
    for d in ("journal", "pending", "claimed", "receipts"):
        (s / "train_requests" / d).mkdir(parents=True)
    return s


def put_request(s: Path, expires: datetime, shadow=False):
    (s / "train_requests" / "journal" / f"{RID}.json").write_text(json.dumps(
        {"request_id": RID, "window_slot": "1200", "shadow": shadow, "expires_at": expires.isoformat()}))


def put_receipt(s: Path, state: str, outcome=None, refusal=None):
    (s / "train_requests" / "receipts" / f"{RID}.json").write_text(json.dumps(
        {"request_id": RID, "state": state, "outcome": outcome, "refusal": refusal, "train_id": "rt-20261026-1200-ab12",
         "acknowledged_at": "2026-10-26T15:00:00+00:00", "finished_at": None if state == "ACKNOWLEDGED" else
         "2026-10-26T16:20:00+00:00", "shadow": False}))


def put_train(s: Path, tid: str, outcome=None, phase="qualify", updated=START):
    d = s / "trains" / tid
    d.mkdir(parents=True)
    body = {"schema": "x", "train_id": tid, "phase": phase, "window_id": "2026-10-26T12:00-04:00",
            "updated_at": updated.astimezone(UTC).isoformat()}
    if outcome:
        body["outcome"] = {"outcome": outcome}
    (d / "state.json").write_text(json.dumps(body))


def test_pre_window_is_frozen_regardless_of_records(tmp_path):
    s = spool(tmp_path)
    put_receipt(s, "COMPLETED", outcome="NO_OP")        # even a terminal receipt cannot end a freeze before start
    assert codes(host(START - timedelta(minutes=10), s)) == [F.PRE_WINDOW]


def test_window_open_awaiting_request_until_grace(tmp_path):
    s = spool(tmp_path)
    assert codes(host(START + timedelta(minutes=5), s)) == [F.AWAITING_REQUEST]
    v = host(START + timedelta(minutes=15), s)
    assert not v["frozen"], v["summary"]


def test_pending_request_holds_until_it_expires(tmp_path):
    s = spool(tmp_path)
    put_request(s, START + timedelta(minutes=15))
    assert codes(host(START + timedelta(minutes=10), s)) == [F.WINDOW_TRAIN_PENDING]
    v = host(START + timedelta(minutes=16), s)
    assert not v["frozen"] and any("expired unclaimed" in w for w in v["warnings"])


def test_acknowledged_receipt_holds_and_flags_stale(tmp_path):
    s = spool(tmp_path)
    put_request(s, START + timedelta(minutes=15))
    put_receipt(s, "ACKNOWLEDGED")
    v = host(START + timedelta(minutes=50), s)
    assert codes(v) == [F.WINDOW_TRAIN_RUNNING] and "stale" not in v["reasons"][0]
    v = host(START + timedelta(hours=5), s)
    assert codes(v) == [F.WINDOW_TRAIN_RUNNING] and v["reasons"][0]["stale"] is True
    assert any("train-orphan-resolve" in w for w in v["warnings"])


@pytest.mark.parametrize("state,outcome,refusal", [
    ("COMPLETED", "NO_OP", None),
    ("COMPLETED", "RELEASED_VERIFIED", None),
    ("COMPLETED", "ROLLED_BACK", None),
    ("REFUSED", None, {"code": "NOT_ARMED", "detail": "x"}),
    ("EXPIRED", None, {"code": "EXPIRED", "detail": "x"}),
    ("FAILED", None, {"code": "CONTROLLER_FAILED", "detail": "x"}),
])
def test_terminal_receipt_ends_the_freeze(tmp_path, state, outcome, refusal):
    s = spool(tmp_path)
    put_request(s, START + timedelta(minutes=15))
    put_receipt(s, state, outcome=outcome, refusal=refusal)
    v = host(START + timedelta(minutes=20), s)
    assert not v["frozen"], (state, v["reasons"])


def test_live_train_without_outcome_holds_any_time(tmp_path):
    s = spool(tmp_path)
    put_train(s, "rt-20261026-1200-ab12")                   # e.g. a forced canary or the train after its receipt
    put_train(s, "rt-20261025-1800-cd34", outcome="RELEASED_VERIFIED")
    v = host(START + timedelta(hours=2), s)
    assert codes(v) == [F.TRAIN_IN_FLIGHT] and v["reasons"][0]["train_id"] == "rt-20261026-1200-ab12"
    (s / "trains" / "rt-x").mkdir()
    (s / "trains" / "rt-x" / "state.json").write_text("{not json")
    assert codes(host(START + timedelta(hours=2), s)).count(F.TRAIN_IN_FLIGHT) == 2   # unreadable = in flight


def test_unreadable_receipts_freeze_pre_window_only(tmp_path):
    missing = tmp_path / "nope"
    v = host(START - timedelta(minutes=5), missing)
    assert codes(v) == [F.PRE_WINDOW] and v["receipts"] == "UNREADABLE"
    v = host(START + timedelta(minutes=5), missing)
    assert not v["frozen"] and any("unreadable" in w for w in v["warnings"])
    s = spool(tmp_path)
    (s / "train_requests" / "receipts" / f"{RID}.json").write_text("{torn")
    v = host(START + timedelta(minutes=5), s)
    assert not v["frozen"] and any("unreadable" in w for w in v["warnings"])


def test_stop_lifts_scheduled_freeze_but_not_a_running_train(tmp_path):
    s = spool(tmp_path)
    v = host(START - timedelta(minutes=5), s, stop_state="SET")
    assert not v["frozen"] and any("STOP" in w for w in v["warnings"])
    assert host(START - timedelta(minutes=5), s, stop_state="UNREADABLE")["frozen"]   # only SET lifts
    put_request(s, START + timedelta(minutes=15))
    put_receipt(s, "ACKNOWLEDGED")
    assert codes(host(START + timedelta(minutes=5), s, stop_state="SET")) == [F.WINDOW_TRAIN_RUNNING]


def test_host_verdict_reads_files_and_never_raises(tmp_path):
    s = spool(tmp_path)
    bad_cfg = tmp_path / "cfg.json"
    bad_cfg.write_text("{}")
    v = F.host_verdict(START - timedelta(minutes=5), state_dir=s, config_path=bad_cfg,
                       delegation_path=tmp_path / "no-delegation.json")
    assert v["frozen"] and v["stop"] == "ABSENT" and any("using defaults" in w for w in v["warnings"])
    (s / "STOP.json").write_text(json.dumps({"by": "operator"}))
    assert not F.host_verdict(START - timedelta(minutes=5), state_dir=s)["frozen"]


# ── exemptions and decisions ──────────────────────────────────────────────────────────────────────────────────

TRAIN_PR = {"number": 2200, "base": "main", "head": "train/rt-20261026-1200-ab12", "cross_repo": False,
            "author": "tradeai-release-train[bot]", "labels": []}
AGENT_PR = {"number": 2101, "base": "main", "head": "feat/x", "cross_repo": False, "author": "PatsKiller",
            "labels": []}


def test_exemptions():
    assert F.exemption(TRAIN_PR, CFG) == "train_batch_pr"
    assert F.exemption(dict(TRAIN_PR, cross_repo=True), CFG) is None
    assert F.exemption(dict(TRAIN_PR, head="train/whatever"), CFG) is None
    assert F.exemption(dict(TRAIN_PR, base="develop"), CFG) == "not_main"
    assert F.exemption(AGENT_PR, CFG) is None
    assert F.exemption(dict(AGENT_PR, labels=["freeze-exempt"]), CFG) == "freeze_exempt_label"
    assert F.exemption(dict(AGENT_PR, base="feat/release-train-arm-20261025"), CFG) == "not_main"
    pinned = dict(CFG, train_pr_authors=["tradeai-release-train[bot]"])
    assert F.exemption(TRAIN_PR, pinned) == "train_batch_pr"
    assert F.exemption(dict(TRAIN_PR, author="PatsKiller"), pinned) is None


def test_pr_decision_states():
    frozen = ci(et(2026, 10, 26, 11, 45))
    d = F.pr_decision(frozen, AGENT_PR, CFG)
    assert not d["allowed"] and d["state"] == "pending" and "REFUSED" in d["message"]
    assert "Mon 12:00 ET" in d["message"] and "freeze-exempt" in d["message"]
    assert len(d["description"]) <= F.DESCRIPTION_MAX
    d = F.pr_decision(frozen, TRAIN_PR, CFG)
    assert d["allowed"] and d["state"] == "success" and "freeze active" in d["description"]
    soon = ci(et(2026, 10, 26, 11, 20))
    assert F.pr_decision(soon, AGENT_PR, CFG)["allowed"]                       # host: exact time
    d = F.pr_decision(soon, AGENT_PR, CFG, lead_pending=True)                  # CI: cron latency lead
    assert d["state"] == "pending" and "starts Mon 11:30 ET" in d["description"]
    assert F.pr_decision(ci(et(2026, 10, 26, 9, 0)), AGENT_PR, CFG, lead_pending=True)["state"] == "success"


# ── CI ────────────────────────────────────────────────────────────────────────────────────────────────────────


def gql_node(pr, sha, status=None, draft=False):
    return {"number": pr["number"], "isDraft": draft, "headRefName": pr["head"], "headRefOid": sha,
            "baseRefName": pr["base"], "isCrossRepository": pr["cross_repo"], "author": {"login": pr["author"]},
            "labels": {"nodes": [{"name": x} for x in pr["labels"]]},
            "commits": {"nodes": [{"commit": {"status": {"context": status} if status else None}}]}}


def test_ci_batch_pr_open_freezes_everyone_else():
    prs = [CLI.pr_from_graphql(gql_node(TRAIN_PR, "t" * 40)), CLI.pr_from_graphql(gql_node(AGENT_PR, "a" * 40))]
    plan = CLI.ci_plan(et(2026, 10, 26, 12, 20), prs, None, policy=POLICY, cfg=CFG)
    assert codes(plan["verdict"]) == [F.BATCH_PR_OPEN]
    by = {p["pr"]: p for p in plan["posts"]}
    assert by[2200]["state"] == "success" and by[2101]["state"] == "pending"
    # without the batch PR, 20 min after the window opened, CI cannot know the train state: open
    plan = CLI.ci_plan(et(2026, 10, 26, 12, 20), prs[1:], None, policy=POLICY, cfg=CFG)
    assert not plan["verdict"]["frozen"] and plan["posts"][0]["state"] == "success"


def test_ci_posts_only_changes_skips_drafts_forces_event_pr():
    t = et(2026, 10, 26, 11, 45)
    v = ci(t)
    want = F.pr_decision(v, AGENT_PR, CFG, lead_pending=True)
    same = CLI.pr_from_graphql(gql_node(AGENT_PR, "a" * 40, {"state": "PENDING", "description": want["description"]}))
    draft = CLI.pr_from_graphql(gql_node(dict(AGENT_PR, number=2102), "b" * 40, draft=True))
    stale = CLI.pr_from_graphql(gql_node(dict(AGENT_PR, number=2103), "c" * 40,
                                         {"state": "SUCCESS", "description": "No merge freeze"}))
    plan = CLI.ci_plan(t, [same, draft, stale], None, policy=POLICY, cfg=CFG)
    assert [p["pr"] for p in plan["posts"]] == [2103]
    event = CLI.pr_from_event({"pull_request": {
        "number": 2101, "draft": False, "labels": [{"name": "freeze-exempt"}], "user": {"login": "PatsKiller"},
        "head": {"ref": "feat/x", "sha": "e" * 40, "repo": {"full_name": "o/r"}},
        "base": {"ref": "main", "repo": {"full_name": "o/r"}}}})
    plan = CLI.ci_plan(t, [same, draft, stale], event, policy=POLICY, cfg=CFG)
    posts = {p["pr"]: p for p in plan["posts"]}
    assert posts[2101]["sha"] == "e" * 40 and posts[2101]["state"] == "success"   # labelled: exempt, forced post
    assert 2102 not in posts


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        for prefix, resp in self.responses:
            if argv[:len(prefix)] == prefix:
                return resp(argv) if callable(resp) else resp
        raise AssertionError(argv)


def _gql_page(nodes):
    return 0, json.dumps({"data": {"repository": {"pullRequests": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}), ""


def test_cli_ci_dry_run_posts_nothing_and_apply_posts_the_context(capsys):
    nodes = [gql_node(AGENT_PR, "a" * 40)]
    r = FakeRunner([(["gh", "api", "graphql"], _gql_page(nodes)), (["gh", "api", "-X", "POST"], (0, "{}", ""))])
    assert CLI.main(["ci", "--repo", "o/r", "--now", "2026-10-26T11:45:00-04:00"], runner=r) == 0
    out = capsys.readouterr().out
    assert "WOULD post #2101" in out and "dry run: nothing posted" in out
    assert not any(c[:4] == ["gh", "api", "-X", "POST"] for c in r.calls)
    assert CLI.main(["ci", "--repo", "o/r", "--now", "2026-10-26T11:45:00-04:00", "--apply",
                     "--run-url", "https://x/run/1"], runner=r) == 0
    post = next(c for c in r.calls if c[:4] == ["gh", "api", "-X", "POST"])
    assert post[4] == "repos/o/r/statuses/" + "a" * 40
    assert "context=train-merge-freeze" in post and "state=pending" in post and "target_url=https://x/run/1" in post


def test_cli_check_pr_refuses_with_exit_3_and_honours_the_label(tmp_path, capsys):
    s = spool(tmp_path)
    view = {"number": 2101, "baseRefName": "main", "headRefName": "feat/x", "isCrossRepository": False,
            "labels": [], "author": {"login": "PatsKiller"}, "state": "OPEN"}
    base = ["check-pr", "2101", "--repo", "o/r", "--state-dir", str(s), "--delegation", str(tmp_path / "none"),
            "--now"]
    r = FakeRunner([(["gh", "pr", "view"], (0, json.dumps(view), ""))])
    assert CLI.main(base + ["2026-10-26T11:45:00-04:00"], runner=r) == CLI.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "REFUSED" in err and "Mon 12:00 ET" in err
    assert CLI.main(base + ["2026-10-26T10:00:00-04:00"], runner=r) == 0
    r = FakeRunner([(["gh", "pr", "view"], (0, json.dumps(dict(view, labels=[{"name": "freeze-exempt"}])), ""))])
    assert CLI.main(base + ["2026-10-26T11:45:00-04:00"], runner=r) == 0
    r = FakeRunner([(["gh", "pr", "view"], (1, "", "HTTP 502"))])            # unreadable PR: no exemption
    assert CLI.main(base + ["2026-10-26T11:45:00-04:00"], runner=r) == CLI.EXIT_REFUSED


def test_cli_status_prints_reasons(tmp_path, capsys):
    s = spool(tmp_path)
    CLI.main(["status", "--state-dir", str(s), "--delegation", str(tmp_path / "none"),
              "--now", "2026-10-31T05:40:00-04:00"])
    out = capsys.readouterr().out
    assert out.startswith("FROZEN") and "Sat 06:00 ET" in out and "PRE_WINDOW" in out


# ── enforcement points ────────────────────────────────────────────────────────────────────────────────────────


def test_agent_merge_helper_checks_the_freeze_before_merging():
    text = (ROOT / "scripts" / "agent_merge_pr.sh").read_text()
    check = text.index("release_train_freeze.py\" check-pr")
    merge = text.index('gh pr merge "$PR"')
    assert check < merge and 'exit 3' in text[check:merge]


def test_tier2_merge_refuses_during_freeze_and_lets_exempt_through(tmp_path):
    from scripts.lib import work_pipeline_tier2 as T2

    doc = {"state": "open", "merged": False, "number": 2101, "user": {"login": "PatsKiller"}, "labels": [],
           "head": {"sha": "a" * 40, "ref": "feat/x", "repo": {"full_name": "o/r"}},
           "base": {"ref": "main", "repo": {"full_name": "o/r"}}}

    def runner(argv, stdin=None):
        path = argv[4]
        if path.endswith("/protection/required_status_checks"):
            return 0, json.dumps({"contexts": ["ci-gate", "train-merge-freeze"]}), ""
        if "/check-runs" in path:
            return 0, json.dumps({"check_runs": [{"name": "ci-gate", "conclusion": "success",
                                                  "started_at": "2026-10-26T15:00:00Z"}]}), ""
        return 0, json.dumps(doc), ""

    frozen = ci(et(2026, 10, 26, 11, 45))
    hosts = SimpleNamespace(runner=runner, merge_freeze=lambda: frozen)
    import scripts.lib.ops_controls_core as OCC

    with pytest.raises(OCC.OpsError) as ei:
        T2.merge_preconditions(hosts, "o/r", 2101, "a" * 40)
    assert ei.value.code == "MERGE_FREEZE"
    doc["labels"] = [{"name": "freeze-exempt"}]
    pre = T2.merge_preconditions(hosts, "o/r", 2101, "a" * 40)
    assert pre["required"] == ["ci-gate"] and pre["merge_freeze"]["exempt"] == "freeze_exempt_label"
    doc["labels"] = []
    hosts.merge_freeze = lambda: ci(et(2026, 10, 26, 10, 0))
    assert T2.merge_preconditions(hosts, "o/r", 2101, "a" * 40)["merge_freeze"]["frozen"] is False

    def boom():
        raise OSError("x")

    hosts.merge_freeze = boom
    with pytest.raises(OCC.OpsError) as ei:
        T2.merge_preconditions(hosts, "o/r", 2101, "a" * 40)
    assert ei.value.code == "MERGE_FREEZE_UNKNOWN"


def test_required_check_readers_drop_the_freeze_context():
    from scripts import pr_hygiene_audit as PH
    from scripts.lib import agent_claim_lifecycle as LC
    from scripts.lib import tree_attested_promote as TAP

    prot = {"contexts": ["cio-hardening", "train-merge-freeze", "ci-gate"],
            "checks": [{"context": "train-merge-freeze"}, {"context": "ci-gate"}]}
    names, src = PH.required_contexts(SimpleNamespace(slug="o/r", api=lambda path: prot))
    assert names == ["cio-hardening", "ci-gate"] and src == "branch_protection"
    assert TAP.required_contexts(SimpleNamespace(gh_pages=lambda path: [prot]), "o/r") == ["ci-gate", "cio-hardening"]
    got, warn = LC.GitHubReader.required_contexts(SimpleNamespace(repo="o/r", get=lambda path: (prot, None)), "main")
    assert got == ["ci-gate", "cio-hardening"] and warn is None
    wp = (ROOT / "scripts" / "lib" / "work_pipeline.py").read_text()
    assert "without_freeze_context(req)" in wp


def test_releases_view_carries_the_freeze(tmp_path):
    from scripts.lib import releases_schedules_view as RSV

    s = spool(tmp_path)
    v = RSV.read_merge_freeze(START - timedelta(minutes=5), s)
    assert v["frozen"] is True and v["reasons"][0]["code"] == F.PRE_WINDOW and v["summary"].startswith("Merge freeze")
    v = RSV.read_merge_freeze(START - timedelta(hours=2), s)
    assert v["frozen"] is False and v["next_freeze"]["slot"] == "1200"


def test_workflow_shape():
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "train-merge-freeze.yml").read_text())
    on = doc.get(True, doc.get("on"))
    assert on["pull_request"]["branches"] == ["main"]
    assert {"opened", "synchronize", "reopened", "ready_for_review", "labeled", "unlabeled", "edited"} <= set(
        on["pull_request"]["types"])
    assert on["schedule"] and "workflow_dispatch" in on
    assert doc["permissions"] == {"contents": "read", "pull-requests": "read", "statuses": "write"}
    job = doc["jobs"]["merge-freeze-evaluate"]
    steps = json.dumps(job["steps"])
    assert "github.event.pull_request.base.sha" in steps                  # main's code and policy, not the head's
    assert "release_train_freeze.py ci --apply" in steps
    assert "pip install" not in steps                                      # stdlib only

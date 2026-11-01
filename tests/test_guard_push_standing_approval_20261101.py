"""AGENTS.md §28.15 item 8 (c): a STANDING operator push approval (operator, 2026-11-01: "Yes, draft stand and approval.").

One operator comment ``APPROVE_PUSH_STANDING <glob> until <YYYY-MM-DD>`` on the configured standing-approval issue
satisfies ONLY the "approved plan" step for the pusher's own live claim on a branch the glob covers. Every other check
(canonical remote, fast-forward, budget, broker paths, claim held by the pusher) still runs.

Hermetic: reuses the item-8 harness (temp guard tree, temp bare remote, fake ``gh``). The fake ``gh`` here also answers
the issue, issue-list and paginated comment endpoints. Mutation tests patch the COPIED guard tree to drop one check and
prove the matching refusal flips to an allow, so each check is load-bearing.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_guard_item8_grant_free_push_20261025 import (BRANCH, GH_DOCS, HOOKS, OK_COMMENT, OTHER_COMMENT,  # noqa: F401
                                                             SESSION, Env, _classify, _refused, agents_md, pytestmark)

STANDING_POLICY = "29.4.0"

REPO = "PatsKiller/tardeai"
ISSUE = 50
URL = f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-"
TITLE = "Standing push approvals"

_spec = importlib.util.spec_from_file_location("guard_push_free_under_test", HOOKS / "guard_push_free.py")
gpf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpf)  # type: ignore[union-attr]


def _day(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d")


def _ts(offset_days: int = 0, minute: int = 0) -> str:
    d = datetime.now(timezone.utc).replace(hour=0, minute=minute, second=0, microsecond=0) + timedelta(days=offset_days)
    return d.isoformat().replace("+00:00", "Z")


def comment(cid: int, body: str, *, login: str = "PatsKiller", created: str | None = None,
            html: str | None = None, updated: str | None = None) -> dict:
    made = created or _ts(0, cid % 60)
    return {"id": cid, "user": {"login": login}, "body": body, "created_at": made, "updated_at": updated or made,
            "html_url": f"{URL}{cid}" if html is None else html}


FAKE_GH = """#!/usr/bin/python3 -I
import json, sys
EXACT = json.loads(open(%r).read())
DOCS = %r
path = sys.argv[2] if len(sys.argv) > 2 else ""
if path in EXACT:
    print(json.dumps(EXACT[path]))
    sys.exit(0)
for k, v in DOCS.items():
    if path.endswith("/" + k):
        print(json.dumps(v))
        sys.exit(0)
sys.exit(1)
"""


LIST = f"repos/{REPO}/issues?creator=PatsKiller&state=all&sort=created&direction=asc"
COMMENTS = f"repos/{REPO}/issues/{ISSUE}/comments?direction=asc"
EVENTS = f"repos/{REPO}/issues/{ISSUE}/events?direction=asc"


def _pg(path: str, n: int = 1) -> str:
    return f"{path}&per_page=100&page={n}"


def standing(E: Env, comments: list[dict], *, state: str = "open", number: int | None = ISSUE,
             listed: list[dict] | None = None, pages: list[list[dict]] | None = None,
             events: list[dict] | None = None, issue_author: str = "PatsKiller", extra: dict | None = None,
             **cfg) -> None:
    """Point the fake gh + test config at a standing-approval issue carrying ``comments`` (oldest first)."""
    exact = {f"repos/{REPO}/issues/{ISSUE}": {"number": ISSUE, "state": state, "title": TITLE,
                                              "user": {"login": issue_author}},
             _pg(EVENTS): events or []}
    for n, page in enumerate(pages or [comments], 1):
        exact[_pg(COMMENTS, n)] = page
    exact[_pg(LIST)] = listed if listed is not None else [
        {"number": ISSUE, "title": TITLE, "user": {"login": "PatsKiller"}}]
    exact.update(extra or {})
    data = E.tmp / "fake-gh-exact.json"
    data.write_text(json.dumps(exact))
    E.gh.write_text(FAKE_GH % (str(data), GH_DOCS))
    E.cfg["standing_issue"] = number
    E.cfg.update(cfg)
    E.write_cfg()


@pytest.fixture
def E(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    e.build(agents=agents_md(STANDING_POLICY))  # (c) is live only under main's AGENTS.md 29.4.0+ ACTIVE
    return e


def ok_line(glob: str = "feat/*", days: int = 30) -> str:
    return f"APPROVE_PUSH_STANDING {glob} until {_day(days)}"


def mutate(E: Env, old: str, new: str) -> None:
    p = E.tree / ".cursor" / "hooks" / "guard_push_free.py"
    s = p.read_text()
    assert s.count(old) == 1, old
    p.write_text(s.replace(old, new))


# =========================================================================== allow


def test_standing_comment_admits_claimed_branch_and_is_logged_by_url(E):
    E.claim(note="working on it")  # no Operator-approval line at all
    standing(E, [comment(101, "standing approval for agent branches\n" + ok_line())])
    out = E.checker()
    assert out["allow"] and out["outcome"] == "pushed", out
    assert out["approval_ref"] == f"{URL}101"
    intent, done = E.events()
    for ev in (intent, done):
        assert ev["approval_ref"] == f"{URL}101" and ev["standing_approval_url"] == f"{URL}101"
        assert ev["plan"]["source"] == "claim+standing" and ev["plan"]["approval_kind"] == "standing_comment"
        assert ev["plan"]["approval_glob"] == "feat/*" and ev["plan"]["claim_id"]
        assert "standing approval" in ev["rule"]
    assert E.remote_sha(f"refs/heads/{BRANCH}") == E.git("rev-parse", "HEAD")


def test_issue_found_by_operator_title_when_number_unset(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())], number=None,
             listed=[{"number": 7, "title": TITLE, "user": {"login": "someone-else"}},
                     {"number": ISSUE, "title": TITLE, "user": {"login": "PatsKiller"}},
                     {"number": 3, "title": TITLE + " (copy)", "user": {"login": "PatsKiller"}}])
    out = E.checker(mode="check")
    assert out["allow"] and out["plan"]["approval_issue"] == str(ISSUE), out


def test_no_operator_issue_with_title_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())], number=None,
             listed=[{"number": ISSUE, "title": TITLE, "user": {"login": "someone-else"}}])
    _refused(E, E.checker(), "no operator issue titled")


def test_backticked_glob_and_expiry_today_admit(E):
    E.claim(note="x")
    standing(E, [comment(101, f"APPROVE_PUSH_STANDING `feat/item8-*` until {_day(0)}")])
    assert E.checker(mode="check")["allow"]


def test_expiry_exactly_at_cap_admits(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(days=45), created=_ts(0))])
    assert E.checker(mode="check")["allow"]


def test_newest_valid_line_wins_over_older_invalid(E):
    E.claim(note="x")
    standing(E, [comment(101, f"APPROVE_PUSH_STANDING feat/* until {_day(-1)}"), comment(102, ok_line())])
    out = E.checker(mode="check")
    assert out["allow"] and out["approval_ref"] == f"{URL}102"


def test_standing_after_revoke_admits(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line()), comment(102, "REVOKE_PUSH_STANDING"), comment(103, ok_line())])
    out = E.checker(mode="check")
    assert out["allow"] and out["approval_ref"] == f"{URL}103"


# =========================================================================== the per-branch path is unchanged


def test_per_branch_approval_still_wins_when_standing_exists(E):
    E.claim()  # note: Operator-approval: OK_COMMENT (APPROVE_PUSH <branch>)
    standing(E, [comment(101, ok_line())])
    out = E.checker()
    assert out["allow"], out
    done = E.events()[-1]
    assert done["approval_ref"] == OK_COMMENT and done["plan"]["source"] == "claim"
    assert done["standing_approval_url"] == "" and done["rule"] == "AGENTS.md 21.0.0 §28.15 item 8 (a)"


def test_per_branch_approval_works_with_no_standing_issue(E):
    E.claim()
    standing(E, [], number=None, listed=[])
    assert E.checker()["allow"]


def test_bad_per_branch_ref_with_no_standing_still_refused(E):
    E.claim(note=f"Operator-approval: {OTHER_COMMENT}")
    standing(E, [], number=None, listed=[])
    out = E.checker()
    _refused(E, out, "not authored by the operator")
    assert "no operator issue titled" in out["reason"]


# =========================================================================== refusals


def test_expired_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, f"APPROVE_PUSH_STANDING feat/* until {_day(-1)}", created=_ts(-10))])
    _refused(E, E.checker(), "expired")


@pytest.mark.parametrize("until", ["", "2026-13-01", "2026-11-31", "11/30/2026", "never", "2026-1-5"])
def test_malformed_or_missing_expiry_refused(E, until):
    E.claim(note="x")
    standing(E, [comment(101, f"APPROVE_PUSH_STANDING feat/* until {until}".rstrip())])
    _refused(E, E.checker())


def test_expiry_beyond_cap_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(days=46), created=_ts(0))])
    _refused(E, E.checker(), "more than 45 days")


def test_configured_cap_applies(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(days=10), created=_ts(0))], standing_max_days=7)
    _refused(E, E.checker(), "more than 7 days")


@pytest.mark.parametrize("login", ["someone-else", "patskiller", "PatsKiller[bot]", ""])
def test_non_operator_author_refused(E, login):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(), login=login)])
    _refused(E, E.checker(), "no unrevoked")


@pytest.mark.parametrize("html", [f"https://github.com/{REPO}/issues/51#issuecomment-101",
                                  f"https://github.com/someone/fork/issues/{ISSUE}#issuecomment-101",
                                  f"{URL}999", ""])
def test_comment_not_on_the_standing_issue_refused(E, html):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(), html=html)])
    _refused(E, E.checker(), "no unrevoked")


def test_revoked_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line()), comment(102, "pausing agent pushes\nREVOKE_PUSH_STANDING")])
    _refused(E, E.checker(), "no unrevoked")


def test_revoke_by_non_operator_does_not_revoke(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line()), comment(102, "REVOKE_PUSH_STANDING", login="someone-else")])
    assert E.checker(mode="check")["allow"]


def test_revoking_comment_with_a_grant_line_grants_nothing(E):
    E.claim(note="x")
    standing(E, [comment(101, "REVOKE_PUSH_STANDING\n" + ok_line())])
    _refused(E, E.checker(), "no unrevoked")


@pytest.mark.parametrize("glob", ["wt/*", "feat/other-*", "fix/*", "feat/item8-demo-2026102?x", "docs/item8-demo-*"])
def test_branch_outside_glob_refused(E, glob):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(glob))])
    _refused(E, E.checker(), "does not cover")


@pytest.mark.parametrize("glob", ["*", "**", "*/*", "main", "ma*", "m?in", "release/*", "train/*", "release/x",
                                  "[m]ain", "feat/../main", "feat/*/main", "feat/[a]*", "Feat/*", "ops/*", "/*",
                                  "feat/", "head/*", "master*"])
def test_glob_that_could_reach_protected_or_unknown_prefix_refused(E, glob):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(glob))])
    _refused(E, E.checker())


def test_protected_prefix_in_config_is_ignored(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line("release/*"))], standing_prefixes=["release/", "train/", "main/", "feat/"])
    _refused(E, E.checker(), "is not one of")
    assert "release/" not in gpf.standing_prefixes({"standing_prefixes": ["release/", "train/", "feat/"]})


def test_policy_ratification_token_in_comment_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line() + "\nAPPROVE_AGENTS_POLICY_29_2_0 2407 abc")])
    _refused(E, E.checker(), "no unrevoked")


def test_closed_issue_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())], state="closed")
    _refused(E, E.checker(), "not an open issue")


def test_comment_cap_fails_closed(E):
    E.claim(note="x")
    full = [comment(1000 + i, "noise") for i in range(100)]
    standing(E, [], pages=[[comment(101, ok_line())] + full[:99], full], standing_max_pages=2)
    _refused(E, E.checker(), "more than 200 entries")


# ---------------------------------------------------------------- every other check still runs under a standing ok


def test_claim_held_by_another_session_refused(E):
    E.claim(note="x", session="s-other-20261101")
    standing(E, [comment(101, ok_line())])
    _refused(E, E.checker(), "no live claim")


def test_stale_claim_refused(E):
    E.claim(note="x", heartbeat="2026-10-01T00:00:00Z")
    standing(E, [comment(101, ok_line())])
    _refused(E, E.checker(), "no live claim")


def test_handoff_path_never_uses_standing(E):
    E.coordinator()
    (E.handoffs / "TASK.md").write_text(f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\n")
    standing(E, [comment(101, ok_line())])
    _refused(E, E.checker(session=None))


def test_budget_still_binds(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())])
    E.set_budget_count(50)
    _refused(E, E.checker(), "push budget used")


def test_broker_paths_still_held(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())])
    E.commit("broker", path="scripts/brokers/x.py")
    _refused(E, E.checker(), "broker")


def test_non_fast_forward_still_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())])
    assert E.checker()["allow"]
    E.git("reset", "-q", "--hard", "HEAD~1")
    E.commit("divergent", path="g.txt")
    pushed = len([e for e in E.events() if e.get("event") == "grant-free-push"])
    out = E.checker()
    assert not out["allow"] and "fast-forward" in out["reason"], out
    assert len([e for e in E.events() if e.get("event") == "grant-free-push"]) == pushed


def test_main_is_never_covered_even_by_function_call():
    cfg = dict(gpf.DEFAULTS)
    for b in ("main", "master", "release/x", "train/2026-11-01", "HEAD"):
        with pytest.raises(gpf.Refused, match="never covers"):
            gpf.standing_approval(b, cfg)


@pytest.mark.parametrize("glob,ok", [("wt/*", True), ("feat/x-*", True), ("chore/?ab*", True), ("docs/a", True),
                                     ("fix/*", True), ("*", False), ("wt/", False), ("release/*", False),
                                     ("train/*", False), ("main", False), ("wt/*/x", False), ("wt/[a-z]*", False)])
def test_glob_validation_unit(glob, ok):
    assert (gpf.standing_glob_problem(glob, dict(gpf.DEFAULTS)) is None) == ok


# =========================================================================== mutation tests


MUTATIONS = {
    "expired": ("        elif exp < today:\n", "        elif False:\n",
                lambda: [comment(101, f"APPROVE_PUSH_STANDING feat/* until {_day(-1)}", created=_ts(-10))]),
    "non-operator": ("        if _login(c) != op:\n            continue\n", "",
                     lambda: [comment(101, ok_line(), login="someone-else")]),
    "revoked": ("            lines = []  # voids everything before it, and the revoking comment itself\n            continue\n",
                "            pass\n",
                lambda: [comment(101, ok_line()), comment(102, "REVOKE_PUSH_STANDING")]),
    "outside-prefix": ("        elif not _standing_glob_re(glob).match(branch):\n", "        elif False:\n",
                       lambda: [comment(101, ok_line("feat/other-*"))]),
    "glob-prefix": ("    if m.group(\"prefix\") not in standing_prefixes(cfg):\n", "    if False:\n",
                    lambda: [comment(101, ok_line("feat/*"))], {"standing_prefixes": ["wt/"]}),
    "cap": ("        elif (exp - made.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).days > max_days:\n",
            "        elif False:\n", lambda: [comment(101, ok_line(days=120), created=_ts(0))]),
    # r2 (security review of #2450)
    "edited": ('        if str(c.get("updated_at") or "") != str(c.get("created_at") or ""):\n',
               "        if False:\n", lambda: [comment(101, ok_line(), created=_ts(-5), updated=_ts(0, 5))]),
    "close-cutoff": ("        if cutoff is not None and made <= cutoff:\n", "        if False:\n",
                     lambda: [comment(101, ok_line(), created=_ts(-3))],
                     {"events": [{"event": "closed", "created_at": _ts(-2)}]}),
    "duplicate-title": ("        if len(nums) > 1:\n", "        if False:\n",
                        lambda: [comment(101, ok_line())],
                        {"number": None, "listed": [{"number": ISSUE, "title": TITLE, "user": {"login": "PatsKiller"}},
                                                    {"number": 900, "title": TITLE, "user": {"login": "PatsKiller"}}]}),
    "fence": ("                  for m in STANDING_RE.finditer(_unfenced(body))]", "                  for m in STANDING_RE.finditer(body)]",
              lambda: [comment(101, f"```\n{ok_line()}\n```")]),
    "revoke-lenient": ('        if "REVOKE_PUSH_STANDING" in body.upper():', '        if body.startswith("REVOKE_PUSH_STANDING"):',
                       lambda: [comment(101, ok_line()), comment(102, "**REVOKE_PUSH_STANDING**")]),
    "issue-author": ("    if _login(doc) != op:\n", "    if False:\n", lambda: [comment(101, ok_line())],
                     {"issue_author": "someone-else"}),
    # r3
    "indented-code": ('    return _INDENTED_CODE_RE.sub("", _FENCE_RE.sub("", _HTML_COMMENT_RE.sub("", body)))',
                      '    return _FENCE_RE.sub("", _HTML_COMMENT_RE.sub("", body))',
                      lambda: [comment(101, f"Example:\n\n    {ok_line()}\n")]),
    "html-comment": ('    return _INDENTED_CODE_RE.sub("", _FENCE_RE.sub("", _HTML_COMMENT_RE.sub("", body)))',
                     '    return _INDENTED_CODE_RE.sub("", _FENCE_RE.sub("", body))',
                     lambda: [comment(101, f"<!--\n{ok_line()}\n-->")]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_mutation_each_check_is_load_bearing(E, name):
    old, new, comments, *cfg = MUTATIONS[name]
    E.claim(note="x")
    standing(E, comments(), **(cfg[0] if cfg else {}))
    assert not E.checker(mode="check")["allow"], f"{name}: refused on the real guard"
    mutate(E, old, new)
    assert E.checker(mode="check")["allow"], f"{name}: mutation did not flip the refusal; the test is not sensitive"


def test_mutation_glob_covering_main_layers():
    """Dropping the glob check alone still leaves '*' unmatchable; dropping the branch guard alone still refuses main
    via the evaluate() protected-name check. Here: the glob check itself flags each protected reach."""
    cfg = dict(gpf.DEFAULTS, standing_prefixes=["wt/", "release/"])
    assert "release/" not in gpf.standing_prefixes(cfg)
    for g in ("*", "release/*", "train/*", "main", "ma*"):
        assert gpf.standing_glob_problem(g, cfg) is not None, g


# =========================================================================== r2: security review of #2450 (B1-B3, M1-M3)


def _issue_row(n: int, *, title: str = TITLE, login: str = "PatsKiller", pr: bool = False) -> dict:
    d = {"number": n, "title": title, "user": {"login": login}}
    return {**d, "pull_request": {}} if pr else d


# ---- B1: the issue lookup


def test_b1_issue_found_past_the_first_page_oldest_first(E):
    E.claim(note="x")
    page1 = [_issue_row(3000 + i, title=f"pr {i}", pr=True) for i in range(100)]
    standing(E, [comment(101, ok_line())], number=None, listed=page1,
             extra={_pg(LIST, 2): [_issue_row(ISSUE)]})
    out = E.checker(mode="check")
    assert out["allow"] and out["plan"]["approval_issue"] == str(ISSUE), out


def test_b1_two_operator_issues_with_the_title_refuse(E):
    """A newer same-title issue must never shadow a revoked original: duplicates refuse outright."""
    E.claim(note="x")
    standing(E, [comment(101, ok_line()), comment(102, "REVOKE_PUSH_STANDING")], number=None,
             listed=[_issue_row(ISSUE), _issue_row(900)])
    _refused(E, E.checker(), "2 operator issues are titled")


def test_b1_lower_numbered_pr_with_the_title_is_not_the_issue(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())], number=None, listed=[_issue_row(7, pr=True), _issue_row(ISSUE)])
    out = E.checker(mode="check")
    assert out["allow"] and out["plan"]["approval_issue"] == str(ISSUE), out


def test_b1_only_a_pr_with_the_title_refuses(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())], number=None, listed=[_issue_row(ISSUE, pr=True)])
    _refused(E, E.checker(), "no operator issue titled")


def test_b1_issue_list_unreadable_page_two_fails_closed(E):
    E.claim(note="x")
    page1 = [_issue_row(3000 + i, title=f"pr {i}", pr=True) for i in range(100)]
    standing(E, [comment(101, ok_line())], number=None, listed=page1)  # page 2 missing
    _refused(E, E.checker(), "could not read the operator's issues")


@pytest.mark.parametrize("number", [ISSUE, None])
def test_b1_issue_opened_by_someone_else_refused(E, number):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())], number=number, issue_author="someone-else",
             listed=[_issue_row(ISSUE)])
    _refused(E, E.checker(), "not opened by the operator")


# ---- B2: gh writes that could forge or revive an approval need a gh-write grant


@pytest.mark.parametrize("cmd", [
    "gh api repos/PatsKiller/tardeai/issues/50/comments -fbody='APPROVE_PUSH_STANDING wt/* until 2026-12-15'",
    "gh api repos/PatsKiller/tardeai/issues/50/comments -Fbody=@/tmp/approve.txt",
    "gh api -fbody='APPROVE_PUSH_STANDING wt/* until 2026-12-15' repos/PatsKiller/tardeai/issues/comments/123 -XPATCH",
    "gh api repos/PatsKiller/tardeai/issues/50/comments --input body.json",
    "gh api repos/PatsKiller/tardeai/issues/50/comments --input=body.json",
    "gh api repos/PatsKiller/tardeai/issues -Ftitle='Standing push approvals'",
    "gh issue reopen 50", "gh issue close 50", "gh issue create --title 'Standing push approvals' --body x",
    "gh issue edit 7 --title 'Standing push approvals'", "gh issue delete 50 --yes", "gh issue transfer 50 o/r",
    "cd /x && gh issue reopen 50 -R PatsKiller/tardeai",
])
def test_b2_gh_issue_and_attached_field_writes_are_gh_write(cmd):
    assert _classify(cmd) == "gh-write", cmd


@pytest.mark.parametrize("cmd", ["gh issue view 50", "gh issue list --state all", "gh issue status",
                                 "gh api repos/o/r/issues/50/comments", "gh api 'repos/o/r/issues?per_page=100'"])
def test_b2_gh_issue_reads_stay_unguarded(cmd):
    assert _classify(cmd) == "none", cmd


@pytest.mark.parametrize("cmd", ["gh issue reopen 50", "gh issue create --title x --body y",
                                 "gh api repos/o/r/issues/50/comments -fbody=x"])
def test_b2_hook_denies_without_a_grant(E, cmd):
    assert E.hook(cmd).get("permission") != "allow", cmd


# ---- B3: a close voids for good, even after a reopen


def _closed(at: str) -> dict:
    return {"event": "closed", "created_at": at, "actor": {"login": "PatsKiller"}}


def test_b3_reopened_issue_does_not_revive_earlier_approvals(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(), created=_ts(-3))],
             events=[_closed(_ts(-2)), {"event": "reopened", "created_at": _ts(-1)}])
    _refused(E, E.checker(), "no unrevoked")


def test_b3_approval_posted_after_the_reopen_admits(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(), created=_ts(-3)), comment(102, ok_line(), created=_ts(0, 30))],
             events=[_closed(_ts(-2)), {"event": "reopened", "created_at": _ts(-1)}])
    out = E.checker(mode="check")
    assert out["allow"] and out["approval_ref"] == f"{URL}102", out


def test_b3_latest_close_wins(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(), created=_ts(-1))],
             events=[_closed(_ts(-5)), _closed(_ts(0, 30))])
    _refused(E, E.checker(), "no unrevoked")


def test_b3_events_unreadable_fails_closed(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line())])
    data = json.loads((E.tmp / "fake-gh-exact.json").read_text())
    del data[_pg(EVENTS)]
    (E.tmp / "fake-gh-exact.json").write_text(json.dumps(data))
    _refused(E, E.checker(), "could not read the events")


# ---- M1: edited operator comments refuse


def test_m1_edited_approval_refused(E):
    E.claim(note="x")
    standing(E, [comment(101, ok_line(), created=_ts(-5), updated=_ts(0, 5))])
    _refused(E, E.checker(), "was edited")


def test_m1_edited_comment_anywhere_after_the_close_refuses(E):
    """An edit could have removed a revoke: the whole path refuses, even with a later clean approval."""
    E.claim(note="x")
    standing(E, [comment(101, "note", created=_ts(-2), updated=_ts(0, 1)), comment(102, ok_line())])
    _refused(E, E.checker(), "was edited")


def test_m1_edit_before_the_latest_close_is_ignored(E):
    E.claim(note="x")
    standing(E, [comment(101, "old", created=_ts(-5), updated=_ts(-4)), comment(102, ok_line(), created=_ts(0, 30))],
             events=[_closed(_ts(-3))])
    assert E.checker(mode="check")["allow"]


def test_m1_edited_non_operator_comment_is_ignored(E):
    E.claim(note="x")
    standing(E, [comment(101, "hi", login="someone-else", updated=_ts(0, 59)), comment(102, ok_line())])
    assert E.checker(mode="check")["allow"]


# ---- M2: a revoke counts however it is written


@pytest.mark.parametrize("body", ["- REVOKE_PUSH_STANDING (all of them)", "**REVOKE_PUSH_STANDING**",
                                  "please revoke_push_standing now", "> REVOKE_PUSH_STANDING",
                                  "```\nREVOKE_PUSH_STANDING\n```", "`REVOKE_PUSH_STANDING`"])
def test_m2_revoke_in_any_markup_or_case_revokes(E, body):
    E.claim(note="x")
    standing(E, [comment(101, ok_line()), comment(102, body)])
    _refused(E, E.checker(), "no unrevoked")


# ---- M3: gated on main's AGENTS.md 29.4.0+ ACTIVE


@pytest.mark.parametrize("version,header,row", [("29.2.1", "ACTIVE", "ACTIVE"), ("29.3.0", "ACTIVE", "ACTIVE"),
                                                ("29.4.0", "PROPOSED", "PROPOSED"), ("29.4.0", "ACTIVE", "PROPOSED")])
def test_m3_standing_needs_main_agents_29_4_0_active(tmp_path, version, header, row):
    e = Env(tmp_path)
    e.build(agents=agents_md(version, header, row))
    e.claim(note="x")
    standing(e, [comment(101, ok_line())])
    out = e.checker(mode="check")
    assert not out["allow"], out
    # an older ACTIVE main still lets the per-branch path work; the others fail the base policy gate first
    if header == "ACTIVE" and row == "ACTIVE":
        assert "needs AGENTS.md 29.4.0+ ACTIVE" in out["reason"], out


def test_m3_per_branch_path_unaffected_below_29_4_0(tmp_path):
    e = Env(tmp_path)
    e.build(agents=agents_md("29.2.1"))
    e.claim()
    standing(e, [comment(101, ok_line())])
    assert e.checker()["allow"]


def test_m3_later_versions_admit(tmp_path):
    e = Env(tmp_path)
    e.build(agents=agents_md("30.0.0"))
    e.claim(note="x")
    standing(e, [comment(101, ok_line())])
    assert e.checker(mode="check")["allow"]


# ---- follow-ups


@pytest.mark.parametrize("fence", ["```", "~~~", "```text"])
def test_fenced_example_is_not_an_approval(E, fence):
    E.claim(note="x")
    close = fence[:3]
    standing(E, [comment(101, f"Example for docs:\n{fence}\n{ok_line()}\n{close}\n")])
    _refused(E, E.checker(), "no unrevoked")


def test_unterminated_fence_hides_the_rest(E):
    E.claim(note="x")
    standing(E, [comment(101, f"```\n{ok_line()}\n")])
    _refused(E, E.checker(), "no unrevoked")


def test_line_after_a_closed_fence_counts(E):
    E.claim(note="x")
    standing(E, [comment(101, f"```\nexample\n```\n{ok_line()}")])
    assert E.checker(mode="check")["allow"]


def test_non_int_comment_id_fails_closed(E):
    E.claim(note="x")
    standing(E, [{**comment(101, ok_line()), "id": "abc", "html_url": f"{URL}abc"}])
    _refused(E, E.checker(), "no usable id")


def test_expiry_is_utc_and_cap_counts_from_the_comment_utc_date():
    """Unit: a comment at 23:30 ET on day D is day D+1 in UTC; the cap counts from the UTC date."""
    made = datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)  # 2026-11-01 23:30 ET
    assert gpf._date("2026-12-17") - made.replace(hour=0, minute=0) == timedelta(days=45)


# =========================================================================== r3: re-review of #2451


@pytest.mark.parametrize("cmd", [
    "gh issue -R PatsKiller/tardeai reopen 50",
    "gh issue --repo PatsKiller/tardeai comment 50 --body 'APPROVE_PUSH_STANDING wt/* until 2026-12-15'",
    "gh issue -R PatsKiller/tardeai edit 7 --title 'Standing push approvals'",
])
def test_b2_flag_before_subcommand(E, cmd):
    assert _classify(cmd) == "gh-write", cmd
    assert E.hook(cmd).get("permission") != "allow", cmd


@pytest.mark.parametrize("cmd", ["gh issue --repo=PatsKiller/tardeai close 50", "gh pr -R o/r comment 5 -b x",
                                 "gh pr --repo o/r review 5 --approve", "gh issue -R o/r -x y create --title t",
                                 "gh alias set ic 'issue comment'", "gh alias import aliases.yml"])
def test_b2_more_flag_and_alias_writes(cmd):
    assert _classify(cmd) == "gh-write", cmd


@pytest.mark.parametrize("cmd", ["gh auth token", "gh auth -h github.com token", "gh auth status --show-token",
                                 "gh auth status -t"])
def test_gh_auth_token_is_secret(E, cmd):
    assert _classify(cmd) == "secret", cmd
    assert E.hook(cmd).get("permission") != "allow", cmd


@pytest.mark.parametrize("cmd", ["gh issue -R o/r view 50", "gh issue list --search reopen", "gh pr -R o/r view 5",
                                 "gh alias list", "gh auth status", "gh pr create --title x --body y"])
def test_flag_forms_of_reads_stay_unguarded(cmd):
    assert _classify(cmd) == "none", cmd


def test_indented_code_block_counts(E):
    """Named after the reviewer's finding; the fix is that an approval in a 4-space indented code block does NOT
    count (it renders as an example, not as an instruction)."""
    E.claim(note="x")
    standing(E, [comment(101, f"Example:\n\n    {ok_line()}\n")])
    _refused(E, E.checker(), "no unrevoked")


def test_tab_indented_approval_does_not_count(E):
    E.claim(note="x")
    standing(E, [comment(101, f"\t{ok_line()}")])
    _refused(E, E.checker(), "no unrevoked")


def test_html_comment_hidden_approval_counts(E):
    """Named after the reviewer's finding; the fix is that an approval inside <!-- --> (invisible on GitHub) does
    NOT count, terminated or not."""
    E.claim(note="x")
    for body in (f"<!--\n{ok_line()}\n-->", f"<!-- note\n{ok_line()}\n"):
        standing(E, [comment(101, body)])
        _refused(E, E.checker(), "no unrevoked")


def test_approval_after_html_comment_still_counts(E):
    E.claim(note="x")
    standing(E, [comment(101, f"<!-- hidden -->\n{ok_line()}\n   ")])
    assert E.checker(mode="check")["allow"]


@pytest.mark.parametrize("rv", ["<!-- REVOKE_PUSH_STANDING -->", "    REVOKE_PUSH_STANDING", "\tREVOKE_PUSH_STANDING"])
def test_hidden_or_indented_revoke_still_revokes(E, rv):
    E.claim(note="x")
    standing(E, [comment(101, ok_line()), comment(102, rv)])
    _refused(E, E.checker(), "no unrevoked")

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

from tests.test_guard_item8_grant_free_push_20261025 import (BRANCH, GH_DOCS, HOOKS, OK_COMMENT, OTHER_COMMENT,
                                                             SESSION, Env, _refused, pytestmark)  # noqa: F401

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
            html: str | None = None) -> dict:
    return {"id": cid, "user": {"login": login}, "body": body, "created_at": created or _ts(0, cid % 60),
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


def standing(E: Env, comments: list[dict], *, state: str = "open", number: int | None = ISSUE,
             listed: list[dict] | None = None, pages: list[list[dict]] | None = None, **cfg) -> None:
    """Point the fake gh + test config at a standing-approval issue carrying ``comments`` (oldest first)."""
    exact = {f"repos/{REPO}/issues/{ISSUE}": {"number": ISSUE, "state": state, "title": TITLE,
                                              "user": {"login": "PatsKiller"}}}
    for n, page in enumerate(pages or [comments], 1):
        exact[f"repos/{REPO}/issues/{ISSUE}/comments?per_page=100&page={n}"] = page
    exact[f"repos/{REPO}/issues?creator=PatsKiller&state=open&per_page=100"] = listed if listed is not None else [
        {"number": ISSUE, "title": TITLE, "user": {"login": "PatsKiller"}}]
    data = E.tmp / "fake-gh-exact.json"
    data.write_text(json.dumps(exact))
    E.gh.write_text(FAKE_GH % (str(data), GH_DOCS))
    E.cfg["standing_issue"] = number
    E.cfg.update(cfg)
    E.write_cfg()


@pytest.fixture
def E(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    e.build()
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
    _refused(E, E.checker(), "no open operator issue")


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
    assert "no open operator issue" in out["reason"]


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
    _refused(E, E.checker(), "more than 200 comments")


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
    "non-operator": ('    op = [c for c in comments if str((c.get("user") or {}).get("login") or "") == cfg["operator_login"]\n',
                     "    op = [c for c in comments if True\n",
                     lambda: [comment(101, ok_line(), login="someone-else")]),
    "revoked": ("            lines = []  # voids everything before it, and the revoking comment itself\n            continue\n",
                "            pass\n",
                lambda: [comment(101, ok_line()), comment(102, "REVOKE_PUSH_STANDING")]),
    "outside-prefix": ("        elif not _standing_glob_re(glob).match(branch):\n", "        elif False:\n",
                       lambda: [comment(101, ok_line("feat/other-*"))]),
    "glob-prefix": ("    if m.group(\"prefix\") not in standing_prefixes(cfg):\n", "    if False:\n",
                    lambda: [comment(101, ok_line("feat/*"))], {"standing_prefixes": ["wt/"]}),
    "cap": ("        elif (exp - made.replace(hour=0, minute=0, second=0, microsecond=0)).days > max_days:\n",
            "        elif False:\n", lambda: [comment(101, ok_line(days=120), created=_ts(0))]),
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

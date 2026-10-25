#!/usr/bin/env python3
"""release_train_freeze.py — enforce the Release Train v2 merge freeze (AGENTS.md §25.3).

    python3 scripts/release_train_freeze.py status [--json] [--now ISO]          # host verdict (read-only)
    python3 scripts/release_train_freeze.py check-pr <N> [--repo O/R] [--now ISO]  # merge helpers: 0 allowed, 3 refused
    python3 scripts/release_train_freeze.py ci --repo O/R --event-name E --event-file F [--apply]

``status``    the host verdict: schedule (config/release_train_policy.json) + the train's receipts and states in the
              release-window state dir. Writes nothing.
``check-pr``  what ``scripts/agent_merge_pr.sh`` (and any merge wrapper) runs before merging: the host verdict plus
              the PR's exemptions (the train's own ``train/<id>`` batch PR, opened by the App's bot for a live
              train; a base other than main). The ``freeze-exempt`` label is NOT honoured here: agents use the
              operator's gh identity, so who applied it cannot be told apart. A stale train raises its P1 here.
              Exit 0 = may merge, 3 = refused (the message names the freeze and when it ends), 2 = usage. A PR
              it cannot read is judged without exemptions.
``ci``        the GitHub Actions half (``.github/workflows/train-merge-freeze.yml``): computes the CI verdict (the
              pre-window freeze + an open ``train/<id>`` batch PR; a runner cannot read host receipts) and sets the
              ``train-merge-freeze`` commit status on every open non-draft PR into main whose status differs, and
              always on the event's PR. The label counts only when its labeled-event actor is in
              operator_logins. Without ``--apply`` it prints what it would post and posts nothing.

Paths: ``--state-dir`` overrides the release-window state dir (default: resolved exactly as release_window.py does);
``--policy`` / ``--config`` override the repo files (tests and the real-layout proof use a temp root).

MBI_BEHAVIOR = 0. Never merges, pushes, promotes or touches the STOP latch. The only writes are ``ci --apply``'s
commit statuses through ``gh api`` with the workflow's token.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import release_train_freeze as F  # noqa: E402

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
Runner = Callable[[list[str]], tuple[int, str, str]]

_GQL = """query($owner:String!,$name:String!,$base:String!,$after:String){repository(owner:$owner,name:$name){
pullRequests(states:OPEN,first:100,after:$after,baseRefName:$base){pageInfo{hasNextPage endCursor}
nodes{number isDraft headRefName headRefOid baseRefName isCrossRepository author{login __typename}
labels(first:50){nodes{name}}
commits(last:1){nodes{commit{status{context(name:"%s"){state description}}}}}}}}}""" % F.FREEZE_CONTEXT


def _run(argv: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", type(exc).__name__
    return p.returncode, p.stdout, p.stderr


def _now(arg: Optional[str]) -> datetime:
    if not arg:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(arg.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise SystemExit("--now needs an offset (e.g. 2026-10-25T11:45:00-04:00)")
    return dt


def _state_dir(arg: Optional[str]) -> Path:
    if arg:
        return Path(arg)
    from scripts.lib import release_train_window as RTW  # noqa: PLC0415 - host only

    return RTW.resolve_state_dir()


def host_verdict(args: argparse.Namespace) -> dict:
    return F.host_verdict(_now(args.now), state_dir=_state_dir(args.state_dir),
                          policy_path=Path(args.policy) if args.policy else None,
                          config_path=Path(args.config) if args.config else None,
                          delegation_path=Path(args.delegation) if args.delegation else None)


def bot_login(login: Any, is_bot: bool = False) -> Optional[str]:
    """One login form for a GitHub App: REST says ``slug[bot]``, GraphQL says ``slug`` (typename Bot) and
    ``gh pr view`` says ``app/slug``. All become ``slug[bot]``."""
    if not isinstance(login, str) or not login:
        return None
    if login.startswith("app/"):
        return login[4:] + "[bot]"
    if is_bot and not login.endswith("[bot]"):
        return login + "[bot]"
    return login


# ── PR records ────────────────────────────────────────────────────────────────────────────────────────────────


def pr_from_gh_view(doc: dict) -> dict:
    return {"number": doc.get("number"), "base": doc.get("baseRefName"), "head": doc.get("headRefName"),
            "cross_repo": bool(doc.get("isCrossRepository")),
            "author": bot_login((doc.get("author") or {}).get("login"), bool((doc.get("author") or {}).get("is_bot"))),
            "labels": [x.get("name") for x in doc.get("labels") or [] if isinstance(x, dict)],
            "state": doc.get("state")}


def pr_from_event(event: dict) -> Optional[dict]:
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        return None
    head, base = pr.get("head") or {}, pr.get("base") or {}
    hrepo, brepo = (head.get("repo") or {}).get("full_name"), (base.get("repo") or {}).get("full_name")
    return {"number": pr.get("number"), "base": base.get("ref"), "head": head.get("ref"), "sha": head.get("sha"),
            "cross_repo": not (hrepo and hrepo == brepo),
            "author": bot_login((pr.get("user") or {}).get("login"), (pr.get("user") or {}).get("type") == "Bot"),
            "labels": [x.get("name") for x in pr.get("labels") or [] if isinstance(x, dict)],
            "draft": bool(pr.get("draft")), "status": None}


def pr_from_graphql(node: dict) -> dict:
    commits = ((node.get("commits") or {}).get("nodes") or [{}])
    ctx = ((((commits[-1] or {}).get("commit") or {}).get("status") or {}).get("context")) if commits else None
    return {"number": node.get("number"), "base": node.get("baseRefName"), "head": node.get("headRefName"),
            "sha": node.get("headRefOid"), "cross_repo": bool(node.get("isCrossRepository")),
            "author": bot_login((node.get("author") or {}).get("login"),
                                (node.get("author") or {}).get("__typename") == "Bot"),
            "labels": [x.get("name") for x in (node.get("labels") or {}).get("nodes") or [] if isinstance(x, dict)],
            "draft": bool(node.get("isDraft")),
            "status": {"state": str(ctx.get("state") or "").lower(), "description": ctx.get("description")}
            if isinstance(ctx, dict) else None}


def list_open_prs(repo: str, base: str, runner: Runner) -> list[dict]:
    owner, name = repo.split("/", 1)
    out, after = [], None
    for _ in range(20):
        argv = ["gh", "api", "graphql", "-f", f"query={_GQL}", "-F", f"owner={owner}", "-F", f"name={name}",
                "-F", f"base={base}"]
        if after:
            argv += ["-F", f"after={after}"]
        rc, so, se = runner(argv)
        if rc != 0:
            raise RuntimeError(f"gh graphql rc={rc}: {(se or so).strip()[-200:]}")
        page = ((json.loads(so).get("data") or {}).get("repository") or {}).get("pullRequests") or {}
        out += [pr_from_graphql(n) for n in page.get("nodes") or [] if isinstance(n, dict)]
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    return out


def label_actor(repo: str, number: int, label: str, runner: Runner) -> Optional[str]:
    """The login that most recently applied ``label`` to the PR (its ``labeled`` issue events), or None."""
    q = f'.[] | select(.event == "labeled" and .label.name == "{label}") | .actor.login'
    rc, so, _se = runner(["gh", "api", "--paginate", f"repos/{repo}/issues/{int(number)}/events", "--jq", q])
    if rc != 0:
        return None
    lines = [x.strip() for x in so.splitlines() if x.strip()]
    return lines[-1] if lines else None


def attach_label_actors(repo: str, prs: list[dict], label: str, runner: Runner) -> None:
    for p in prs:
        if p and label in (p.get("labels") or []) and p.get("number") is not None:
            p["label_actor"] = label_actor(repo, int(p["number"]), label, runner)


# ── commands ──────────────────────────────────────────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    v = host_verdict(args)
    if args.json:
        print(json.dumps(v, indent=1, sort_keys=True))
    else:
        print(("FROZEN  " if v["frozen"] else "OPEN    ") + v["summary"])
        for r in v["reasons"]:
            print(f"  - {r['code']}: {r.get('detail')}")
        for w in v["warnings"]:
            print(f"  ! {w}")
    return EXIT_OK


def cmd_check_pr(args: argparse.Namespace, runner: Runner = _run, alert_send: Any = None) -> int:
    v = host_verdict(args)
    pr = None
    argv = ["gh", "pr", "view", str(args.pr), "--json",
            "number,baseRefName,headRefName,isCrossRepository,labels,author,state"]  # author.is_bot included
    if args.repo:
        argv += ["--repo", args.repo]
    rc, so, se = runner(argv)
    if rc == 0:
        try:
            pr = pr_from_gh_view(json.loads(so))
        except ValueError:
            pr = None
    cfg = F.load_config(Path(args.config) if args.config else None)
    # Agents share the operator's gh identity, so the label cannot be attributed: the agent helper ignores it.
    d = F.pr_decision(v, pr, cfg, allow_label=False)
    for a in F.alert_stale(v, send=alert_send):
        print(f"merge-freeze: P1 for stale train {a.get('id')}: accepted={a.get('accepted')}", file=sys.stderr)
    for w in v["warnings"]:
        print(f"merge-freeze warning: {w}", file=sys.stderr)
    if pr is None and v["frozen"]:
        print(f"merge-freeze: could not read PR {args.pr} ({(se or '').strip()[-120:]}); judged without exemptions",
              file=sys.stderr)
    if args.json:
        print(json.dumps({"verdict": v, "pr": pr, "decision": d}, indent=1, sort_keys=True))
    if d["allowed"]:
        if not args.json:
            print(f"merge-freeze: PR {args.pr} may merge ({d['exempt'] or 'no freeze'})")
        return EXIT_OK
    if not args.json:
        print(f"merge-freeze: PR {args.pr} {d['message']}", file=sys.stderr)
    return EXIT_REFUSED


def ci_plan(now: datetime, prs: list[dict], event_pr: Optional[dict], *, policy: Optional[dict], cfg: dict) -> dict:
    """The CI verdict and the statuses to post. Pure (tests drive it with fixtures)."""
    batch = [{"number": p["number"], "head": p["head"]} for p in prs if F.is_train_batch_pr(p, cfg)]
    v = F.evaluate(now, policy=policy, cfg=cfg, mode="ci", batch_prs=batch)
    v["warnings"].append("CI cannot read the host's train receipts: after a window opens it freezes only while the "
                         "train's batch PR is open; the host merge helpers enforce the full freeze")
    posts = []
    seen = set()
    targets = ([event_pr] if event_pr else []) + [p for p in prs if not p.get("draft")]
    for p in targets:
        if not p.get("sha") or p["number"] in seen:
            continue
        seen.add(p["number"])
        d = F.pr_decision(v, p, cfg, lead_pending=True)
        cur = p.get("status") or {}
        forced = event_pr is not None and p is event_pr
        if forced or cur.get("state") != d["state"] or cur.get("description") != d["description"]:
            posts.append({"pr": p["number"], "sha": p["sha"], "state": d["state"], "description": d["description"]})
    return {"verdict": v, "posts": posts}


def cmd_ci(args: argparse.Namespace, runner: Runner = _run) -> int:
    now = _now(args.now)
    cfg = F.load_config(Path(args.config) if args.config else None)
    from scripts.lib import release_train_window_view as V  # noqa: PLC0415

    policy = V.read_policy(Path(args.policy) if args.policy else None)
    event_pr = None
    if args.event_name in ("pull_request", "pull_request_target") and args.event_file:
        event_pr = pr_from_event(json.loads(Path(args.event_file).read_text(encoding="utf-8")))
        if event_pr and event_pr.get("base") != cfg["base_branch"]:
            event_pr = None                     # a stacked PR: the freeze is about merges to main
    prs = list_open_prs(args.repo, cfg["base_branch"], runner)
    attach_label_actors(args.repo, prs + ([event_pr] if event_pr else []), cfg["exempt_label"], runner)
    plan = ci_plan(now, prs, event_pr, policy=policy, cfg=cfg)
    v = plan["verdict"]
    print(("FROZEN  " if v["frozen"] else ("IMMINENT" if v["imminent"] else "OPEN    ")) + "  " + v["summary"])
    for w in v["warnings"]:
        print(f"  ! {w}")
    failures = 0
    for p in plan["posts"]:
        line = f"#{p['pr']} {p['sha'][:9]} -> {p['state']}: {p['description']}"
        if not args.apply:
            print("WOULD post " + line)
            continue
        argv = ["gh", "api", "-X", "POST", f"repos/{args.repo}/statuses/{p['sha']}", "-f", f"state={p['state']}",
                "-f", f"context={F.FREEZE_CONTEXT}", "-f", f"description={p['description']}"]
        if args.run_url:
            argv += ["-f", f"target_url={args.run_url}"]
        rc, so, se = runner(argv)
        print(("posted " if rc == 0 else f"FAILED rc={rc} ") + line)
        failures += rc != 0
    print(f"{len(prs)} open PRs into {cfg['base_branch']}; {len(plan['posts'])} status update(s)"
          + ("" if args.apply else " (dry run: nothing posted)"))
    return 1 if failures else EXIT_OK


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="release_train_freeze.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--now", help="evaluate at this instant (ISO-8601 with offset); default: the clock")
        p.add_argument("--state-dir", help="release-window state dir (default: as release_window.py resolves it)")
        p.add_argument("--policy", help="release train policy path (default: config/release_train_policy.json)")
        p.add_argument("--config", help="freeze config path (default: config/release_train_merge_freeze.json)")
        p.add_argument("--delegation", help="standing delegation path (default: the host's)")
        p.add_argument("--json", action="store_true")

    common(sub.add_parser("status", help="the host verdict"))
    c = sub.add_parser("check-pr", help="may this PR merge now? exit 0 yes, 3 refused")
    c.add_argument("pr")
    c.add_argument("--repo")
    common(c)
    ci = sub.add_parser("ci", help="GitHub Actions: set the train-merge-freeze commit status")
    ci.add_argument("--repo", required=True)
    ci.add_argument("--event-name", default="schedule")
    ci.add_argument("--event-file")
    ci.add_argument("--run-url")
    ci.add_argument("--apply", action="store_true", help="post the statuses (default: print them)")
    ci.add_argument("--now")
    ci.add_argument("--policy")
    ci.add_argument("--config")
    return ap


def main(argv: Optional[list[str]] = None, runner: Runner = _run, alert_send: Any = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "check-pr":
        return cmd_check_pr(args, runner, alert_send)
    return cmd_ci(args, runner)


if __name__ == "__main__":
    sys.exit(main())

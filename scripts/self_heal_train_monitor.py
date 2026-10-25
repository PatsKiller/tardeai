#!/usr/bin/env python3
"""self_heal_train_monitor.py — watch the release train, main CI and the post-release testers; fix small errors.

Operator 2026-10-25 (verbatim, voice-typed): "Arm the fixer and also a logger that tracks what was fixed, but this
train should be no different than submitting in [to GitHub]. Somebody needs to monitor it, if there's little errors
they need to correct it as long as they're adhering to our agents.md."

One tick (host systemd timer every 5 min, independent of n8n: the monitor must not depend on what it monitors):

  1. read  main CI of main HEAD (gh, GET only), train outcomes / stale trains / window receipts, post-release tester
           and nightly sweep receipts, the fixer's state (scripts/self_heal_fixer.py) and this lane's own state
  2. decide one remediation per failure signature (scripts/lib/self_heal_train_intake.py): deterministic first (no
           model), refused scope -> P1 + coordinator task, train machinery -> coordinator, else the Claude Code fixer
  3. act   ONLY when LIVE (AGENTS.md >= 20.4.0 ACTIVE with section 28.14 ACTIVE at origin/main):
             rerun failed CI jobs once (known infra flake) | regenerate + open ONE fix PR (ci_gates canonical bytes,
             docs/INDEX.md, disk packet pins) | train-reconcile (dry run first; live only when nothing is AMBIGUOUS) |
             hand the defect to the fixer (data/self_heal/fixer_defects.jsonl, N8nCodeDefect@v1) |
             coordinator task (scripts/agent_claim.py task add) | P1 via telegram_alert.send_telegram
           In SHADOW every decision is logged as ``shadow-proposed`` and nothing is executed, launched or sent.
  4. track open fixes to an outcome (fix-PR-open -> fixed-released -> verified; gave-up / escalated), hand
           non-eligible fix PRs (the train's NOT_RIDING reason is held / blocked / needs_operator) to the coordinator
  5. log   every change of a fix as one row of the append-only fix log data/self_heal/fix_log.jsonl
           (SelfHealFixLog@v1), write state + the heartbeat receipt (ok/ok_at) the cron outage watchdog measures

    python3 scripts/self_heal_train_monitor.py                 # dry run: print decisions, write nothing
    python3 scripts/self_heal_train_monitor.py --apply         # tick (shadow until 28.14 is ACTIVE)
    python3 scripts/self_heal_train_monitor.py --status

Fix PRs are ordinary PRs: normal CI, the train merges them when eligible; this lane and the fixer never merge, never
deploy, never edit crontab/systemd, never touch broker code, credentials, guard/policy or the train's own files.
Exit 0 = tick ran (including shadow / nothing to do); 2 = cannot run (config unreadable). MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import self_heal_train_intake as TI  # noqa: E402

CONFIG = ROOT / "config" / "self_heal_train_monitor.json"
LANE_ID = "self-heal-train-monitor"
HEARTBEAT_SCHEMA = "SelfHealTrainMonitorTick@v1"
CANONICAL_DEFAULT = Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"
CURRENT_SHA_DEFAULT = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA"

Runner = Callable[..., dict]
Sender = Callable[[str, str], bool]


def run(argv: list[str], *, cwd: Optional[Path] = None, env: Optional[dict] = None, timeout: float = 240) -> dict:
    try:
        p = subprocess.run(
            argv, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True, timeout=timeout
        )
        return {"rc": p.returncode, "out": p.stdout, "err": p.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"rc": 124, "out": "", "err": f"{type(exc).__name__}: {exc}"}


def default_sender(text: str, priority: str) -> bool:
    from telegram_alert import send_telegram  # the one chokepoint; imported only on a live send

    return bool(
        send_telegram(
            text,
            priority=priority,
            producer="self_heal_train_monitor",
            message_class="operator_alert",
            dedupe_minutes=0 if priority == "P1" else None,
        )
    )


def state_root(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def _atomic_write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- gather


def gather_ci(runner: Runner, *, repo: Path, cfg: dict) -> tuple[list[TI.Finding], dict]:
    r = runner(
        [
            "gh",
            "run",
            "list",
            "--branch",
            "main",
            "--event",
            "push",
            "--limit",
            "60",
            "--json",
            "databaseId,headSha,workflowName,conclusion,status,createdAt,url",
        ],
        cwd=repo,
        timeout=60,
    )
    if r["rc"] != 0:
        return [], {"ci": "UNAVAILABLE", "why": (r["err"] or "")[-200:]}
    try:
        rows = json.loads(r["out"] or "[]")
    except ValueError:
        return [], {"ci": "UNAVAILABLE", "why": "gh run list: not JSON"}
    head, latest = TI.head_runs(rows)
    red = TI.red_runs(latest)
    details: dict = {}
    for run_ in red[:6]:
        rid = run_.get("databaseId")
        v = runner(["gh", "run", "view", str(rid), "--json", "jobs"], cwd=repo, timeout=60)
        jobs: list = []
        try:
            doc = json.loads(v["out"] or "{}") if v["rc"] == 0 else {}
            jobs = [j.get("name") for j in doc.get("jobs") or [] if j.get("conclusion") in ("failure", "timed_out")]
        except ValueError:
            pass
        # run_attempt is not a gh run list/view field; the REST run object carries it (GET)
        a = runner(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{rid}", "--jq", ".run_attempt"], cwd=repo, timeout=60
        )
        attempt = (
            int((a.get("out") or "1").strip() or 1) if a["rc"] == 0 and (a.get("out") or "").strip().isdigit() else 1
        )
        lg = runner(["gh", "run", "view", str(rid), "--log-failed"], cwd=repo, timeout=120)
        tail = int(cfg["sources"].get("ci_log_tail_chars", 6000))
        details[rid] = {"failed_jobs": jobs, "attempt": attempt, "log_tail": (lg.get("out") or "")[-tail * 3 :]}
    pending = sum(1 for x in latest if x.get("status") != "completed")
    return TI.detect_ci(head, red, details, tail_chars=int(cfg["sources"].get("ci_log_tail_chars", 6000))), {
        "ci": "RED" if red else ("PENDING" if pending else "GREEN"),
        "head": head,
        "workflows": len(latest),
    }


# ---------------------------------------------------------------- deterministic generators (pure on a tree)


def gen_ci_gates_canonical(tree: Path) -> list[str]:
    from lib import ci_gates as G

    changed = []
    for p in sorted((tree / G.GATES_DIR_REL).glob("*.json")):
        raw = p.read_text(encoding="utf-8")
        doc = G.validate(json.loads(raw), stem=p.stem)  # malformed -> GateRegistryError: a human decides
        text = G.render(doc)
        if text != raw:
            p.write_text(text, encoding="utf-8")
            changed.append(f"{G.GATES_DIR_REL}/{p.name}")
    return changed


def gen_disk_packet_repin(tree: Path, packet_rel: str) -> list[str]:
    """Re-derive config pins + the review's pins digest (precedents 583512363, dcbdd0d08). Byte format kept: 2-space
    JSON, insertion order, trailing newline. Never touches decision/approval/contract/rules fields."""
    packet = tree / packet_rel
    pins_p, review_p = packet / "activation-input-sha256.json", packet / "review.required.json"
    pins = json.loads(pins_p.read_text(encoding="utf-8"))
    new = {name: hashlib.sha256((tree / "config" / name).read_bytes()).hexdigest() for name in pins}
    changed = []
    if new != pins:
        pins_p.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
        changed.append(f"{packet_rel}/activation-input-sha256.json")
    review = json.loads(review_p.read_text(encoding="utf-8"))
    digest = hashlib.sha256(pins_p.read_bytes()).hexdigest()
    if review.get("source_config_pins_sha256") != digest:
        review["source_config_pins_sha256"] = digest
        review_p.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        changed.append(f"{packet_rel}/review.required.json")
    return changed


# ---------------------------------------------------------------- the tick


class Tick:
    def __init__(
        self,
        *,
        cfg: dict,
        root: Path,
        repo: Path,
        live: bool,
        write: bool,
        now: datetime,
        runner: Runner,
        sender: Sender,
        environ: Mapping[str, str],
    ) -> None:
        self.cfg, self.root, self.repo, self.live, self.write, self.now = cfg, root, repo, live, write, now
        self.runner, self.sender, self.environ = runner, sender, environ
        s = cfg["state"]
        self.fix_log = root / s["fix_log_rel"]
        self.state_path = root / s["state_rel"]
        self.defects_path = root / s["fixer_defects_rel"]
        self.state = _load(self.state_path) or TI.new_state()
        self.rows: list[dict] = []
        self.actions: list[dict] = []
        self.mode = "live" if live else "shadow"

    # -- bookkeeping
    def rec_for(self, f: TI.Finding) -> dict:
        fid = TI.fix_id(f.signature)
        rec = self.state["fixes"].get(fid)
        if rec is None:
            rec = {
                "fix_id": fid,
                "signature": f.signature,
                "source": f.source,
                "kind": f.kind,
                "title": f.title,
                "detected_at": self.now.isoformat(),
                "evidence_refs": f.evidence_refs,
                "attempts": 0,
                "outcome": "detected",
                "detail": f.detail,
                "rules_done": [],
            }
            self.state["fixes"][fid] = rec
            self.log(rec, "detected")
        elif rec.get("outcome") in ("fixed-released", "fixed-no-release", "cleared"):
            # the same signature is back after it was fixed or cleared: a new episode with a fresh attempt budget
            rec.update(
                attempts=0,
                rules_done=[],
                last_remediation=None,
                pr_number=None,
                pr_head=None,
                released_sha=None,
                verified_at=None,
                noted_at=None,
                coordinator_task=None,
                detected_at=self.now.isoformat(),
            )
            self.set_outcome(rec, "detected", "recurred", f.detail)
        rec.update(last_seen_at=self.now.isoformat(), title=f.title, evidence_refs=f.evidence_refs[:10])
        return rec

    def log(self, rec: dict, event: str, detail: str = "") -> None:
        row = TI.log_row(rec, event=event, now=self.now, mode=self.mode, detail=detail)
        self.rows.append(row)

    def set_outcome(self, rec: dict, outcome: str, event: str, detail: str = "", **fields: Any) -> None:
        rec.update(fields)
        rec["outcome"] = outcome
        rec["updated_at"] = self.now.isoformat()
        self.log(rec, event, detail)

    def capped(self, counter: str, cap_key: str) -> bool:
        return TI.day_count(self.state, self.now, counter) >= int(self.cfg["budgets"][cap_key])

    # -- side effects (live only; each is one bounded subprocess or append)
    def page(self, rec: dict, text: str, priority: str = "P1") -> None:
        msg = f"🛠 self-heal {priority}: {text[:300]}\n{self.cfg['notify']['link']}"
        self.actions.append({"action": "page", "priority": priority, "fix_id": rec["fix_id"], "text": msg})
        if not self.live or self.capped("p1", "max_p1_alerts_per_day"):
            return
        try:
            ok = self.sender(msg, priority)
        except Exception as exc:  # noqa: BLE001 — a send failure is recorded, never fatal to the tick
            ok, rec["page_error"] = False, f"{type(exc).__name__}"[:80]
        if priority == "P1":
            TI.bump(self.state, self.now, "p1")
        rec["paged_at"] = self.now.isoformat() if ok else rec.get("paged_at")

    def coordinator(self, rec: dict, title: str, areas: list[str], priority: int = 2) -> None:
        self.actions.append({"action": "coordinator_task", "fix_id": rec["fix_id"], "title": title})
        if not self.live or rec.get("coordinator_task") or self.capped("coord", "max_coordinator_tasks_per_day"):
            return
        sub = {
            "{python}": sys.executable,
            "{priority}": str(priority),
            "{title}": f"[self-heal] {title}"[:150],
            "{areas}": ",".join(areas[:5]) or "docs/ops/SELF_HEAL_TRAIN_FIXER.md",
        }
        argv = [sub.get(a, a) for a in self.cfg["coordinator"]["argv"]]
        # --areas takes several values: expand the joined placeholder back into separate argv items
        i = argv.index(sub["{areas}"])
        argv[i : i + 1] = sub["{areas}"].split(",")
        r = self.runner(argv, cwd=self.repo, timeout=60)
        TI.bump(self.state, self.now, "coord")
        rec["coordinator_task"] = (r.get("out") or "")[-200:] if r["rc"] == 0 else None
        rec["coordinator_error"] = None if r["rc"] == 0 else (r.get("err") or "")[-200:]

    # -- remediations
    def act(self, f: TI.Finding, rec: dict, decision: dict) -> None:
        kind = decision["remediation"]
        rec["remediation_kind"] = kind if kind != "refused" else f"refused:{decision['scope'].split(':', 1)[0]}"
        if not self.live:
            self.set_outcome(rec, "shadow-proposed", "proposed", f"would: {kind} ({decision.get('why') or ''})")
            self.actions.append({"action": "propose", "fix_id": rec["fix_id"], "remediation": kind})
            return
        rec["attempts"] = int(rec.get("attempts") or 0) + 1
        rec["last_action_at"] = self.now.isoformat()
        rec["last_remediation"] = kind
        if kind.startswith("deterministic:"):
            rule = next(r for r in self.cfg["deterministic"] if r["id"] == decision["rule"])
            rec.setdefault("rules_done", []).append(rule["id"])
            return self.deterministic(f, rec, rule)
        if kind == "refused":
            self.set_outcome(rec, "escalated", "refused", f"refused scope {decision['scope']}")
            self.page(rec, f"{f.title} — refused scope {decision['scope']}; coordinator task opened")
            return self.coordinator(rec, f"{f.title} (refused scope {decision['scope']})", f.paths, 1)
        if kind == "coordinator":
            self.set_outcome(rec, "escalated", "coordinator", decision.get("why", ""))
            if decision.get("priority") == "P1":
                self.page(rec, f"{f.title} — {decision.get('why')}")
            return self.coordinator(
                rec, f"{f.title}: {decision.get('why')}", f.paths, 1 if decision.get("priority") == "P1" else 2
            )
        # claude_code: hand the defect to the existing fixer
        if self.capped("handoff", "max_fixer_handoffs_per_day"):
            rec["attempts"] -= 1
            self.log(rec, "deferred", "daily fixer hand-off cap reached")
            return
        doc = TI.fixer_record(f, now=self.now, episode=int(rec["attempts"]))
        self.defects_path.parent.mkdir(parents=True, exist_ok=True)
        with self.defects_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, sort_keys=True) + "\n")
        TI.bump(self.state, self.now, "handoff")
        self.set_outcome(
            rec,
            "fixer-queued",
            "fixer_handoff",
            f"defect {doc['code_defect']['defect_id']}",
            defect_id=doc["code_defect"]["defect_id"],
            remediation_kind="claude_code",
        )

    def deterministic(self, f: TI.Finding, rec: dict, rule: dict) -> None:
        if self.capped("det", "max_deterministic_actions_per_day"):
            self.log(rec, "deferred", "daily deterministic cap reached")
            return
        TI.bump(self.state, self.now, "det")
        kind = rule["kind"]
        if kind == "rerun_failed_jobs_once":
            if self.capped("rerun", "max_ci_reruns_per_day"):
                return self.log(rec, "deferred", "daily CI rerun cap reached")
            TI.bump(self.state, self.now, "rerun")
            argv = [a.replace("{run_id}", str(f.meta.get("run_id"))) for a in rule["argv"]]
            r = self.runner(argv, cwd=self.repo, timeout=60)
            ok = r["rc"] == 0
            return self.set_outcome(
                rec,
                "remediating" if ok else "detected",
                "ci_rerun",
                f"gh run rerun {f.meta.get('run_id')} --failed: rc={r['rc']}",
                rerun_run_id=f.meta.get("run_id"),
            )
        if kind == "train_reconcile":
            sub = {"{python}": sys.executable}
            dry = self.runner(
                [sub.get(a, a) for a in rule["dry_argv"]],
                cwd=ROOT,
                timeout=float(self.cfg["budgets"]["subprocess_timeout_s"]),
            )
            if dry["rc"] != 0 or "AMBIGUOUS" in (dry.get("out") or ""):
                self.set_outcome(
                    rec,
                    "escalated",
                    "reconcile_ambiguous",
                    f"train-reconcile dry run rc={dry['rc']}: not forced; operator decides",
                )
                self.page(rec, f"{f.title}: train-reconcile is ambiguous (rc={dry['rc']}); operator reconcile needed")
                return self.coordinator(rec, f"{f.title}: ambiguous reconcile", [], 1)
            live = self.runner(
                [sub.get(a, a) for a in rule["live_argv"]],
                cwd=ROOT,
                timeout=float(self.cfg["budgets"]["subprocess_timeout_s"]),
            )
            return self.set_outcome(
                rec,
                "remediating" if live["rc"] == 0 else "detected",
                "train_reconcile",
                f"train-reconcile --live rc={live['rc']}",
            )
        if kind == "regenerate_pr":
            return self.regen_pr(f, rec, rule)

    def regen_pr(self, f: TI.Finding, rec: dict, rule: dict) -> None:
        base_tmp = Path(self.environ.get("TMPDIR") or tempfile.gettempdir())
        wt = base_tmp / f"self-heal-regen-{rec['fix_id']}-{int(self.now.timestamp())}"
        g = lambda *a, **k: self.runner(["git", "-C", str(self.repo), *a], timeout=120, **k)  # noqa: E731
        g("fetch", "-q", "origin", "main")
        add = g("worktree", "add", "--detach", str(wt), "origin/main")
        if add["rc"] != 0:
            return self.set_outcome(rec, "detected", "regen_failed", f"worktree add rc={add['rc']}")
        try:
            if rule.get("generator") == "ci_gates_canonical":
                changed = gen_ci_gates_canonical(wt)
            elif rule.get("generator") == "disk_packet_repin":
                changed = gen_disk_packet_repin(wt, rule["packet_rel"])
            else:
                argv = [a.replace("{python}", sys.executable) for a in rule["generator_argv"]]
                self.runner(argv, cwd=wt, timeout=float(self.cfg["budgets"]["subprocess_timeout_s"]))
                st = self.runner(["git", "-C", str(wt), "status", "--porcelain"], timeout=60)
                changed = [ln[3:].strip() for ln in (st.get("out") or "").splitlines() if ln.strip()]
            stray = [p for p in changed if not TI._match(p, rule["allowed_paths"])]
            if stray or not changed:
                why = f"stray paths {stray[:5]}" if stray else "generator changed nothing: not this failure"
                return self.set_outcome(rec, "detected", "regen_no_fix", why)
            branch = f"{self.cfg['regen_pr']['branch_prefix']}{rule['id']}-{self.now.strftime('%Y%m%d%H%M')}"
            title = f"self-heal: {rule['id']} ({f.title})"[:120]
            body = (
                f"Deterministic self-heal remediation `{rule['id']}` (no model) for: {f.title}\n\n"
                f"Evidence: {', '.join(f.evidence_refs[:3])}\n\nChanged: {', '.join(changed)}\n\n"
                "An ordinary PR: normal CI; the release train merges it when eligible. Never merged by the "
                "self-heal lane. Rules: AGENTS.md section 28.14; docs/ops/SELF_HEAL_TRAIN_FIXER.md.\n"
            )
            msg = f"self-heal: {rule['id']}\n\n{f.title}\n\n" + "\n".join(self.cfg["regen_pr"]["commit_trailers"])
            gw = lambda *a: self.runner(["git", "-C", str(wt), *a], timeout=120)  # noqa: E731
            gw("checkout", "-q", "-b", branch)
            gw("add", "--", *changed)
            c = gw("commit", "-q", "-m", msg)
            env = {**os.environ, "TRADEAI_REMOTE_PUSH_AUTHORIZED": "1"}
            p = self.runner(
                ["git", "-C", str(wt), "push", "-q", "origin", f"HEAD:refs/heads/{branch}"], env=env, timeout=180
            )
            if c["rc"] != 0 or p["rc"] != 0:
                return self.set_outcome(rec, "detected", "regen_failed", f"commit rc={c['rc']} push rc={p['rc']}")
            head = (gw("rev-parse", "HEAD").get("out") or "").strip()
            bf = wt.parent / f"{wt.name}.body.md"
            bf.write_text(body, encoding="utf-8")
            pr = self.runner(
                [
                    "gh",
                    "pr",
                    "create",
                    "--head",
                    branch,
                    "--base",
                    "main",
                    "--title",
                    title,
                    "--body-file",
                    str(bf),
                    "--label",
                    self.cfg["regen_pr"]["label"],
                ],
                cwd=self.repo,
                timeout=120,
            )
            url = (pr.get("out") or "").strip().splitlines()[-1:] or [""]
            num = int(url[0].rsplit("/", 1)[-1]) if url[0].rsplit("/", 1)[-1].isdigit() else None
            self.set_outcome(
                rec,
                "fix-PR-open" if num else "detected",
                "fix_pr_opened",
                f"{rule['id']}: {url[0]}",
                pr_number=num,
                pr_head=head,
                model_cost_usd=0.0,
            )
        finally:
            self.runner(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(wt)], timeout=60)

    # -- lifecycle of open fixes
    def advance(
        self, present: set[str], fixer_jobs: list[dict], riding: dict[int, str], *, ci_settled: bool = True
    ) -> None:
        """Move open fixes. ``present`` = signatures observed this tick. A CI-sourced fix is judged absent only
        when main CI of HEAD is settled (GREEN or RED): pending or unreadable CI proves nothing."""
        cur_sha = self.current_sha()
        by_defect = {j.get("defect_id"): j for j in fixer_jobs if j.get("defect_id")}
        prefixes = tuple(self.cfg["coordinator"]["non_eligible_reason_prefixes"])
        for rec in self.state["fixes"].values():
            out, sig = rec.get("outcome"), rec.get("signature")
            if out in TI.TERMINAL_OUTCOMES or rec.get("updated_at") == self.now.isoformat():
                continue  # judged on a later tick: this tick's observation predates its own action
            absent = sig not in present and (rec.get("source") != "ci" or ci_settled)
            still = sig in present
            if out in ("fixer-queued", "fix-PR-open") and rec.get("defect_id") in by_defect:
                self.from_fixer(rec, by_defect[rec["defect_id"]])  # the fixer owns its PR's lifecycle
                out = rec.get("outcome")
            elif out == "fix-PR-open" and rec.get("pr_number") and self.live:
                self.track_pr(rec, cur_sha)
                out = rec.get("outcome")
            if out == "fix-PR-open" and rec.get("pr_number") in riding and not rec.get("coordinator_task"):
                reason = riding[rec["pr_number"]]
                if reason.startswith(prefixes):
                    self.log(rec, "not_eligible", f"train: {reason[:160]}")
                    self.coordinator(
                        rec, f"fix PR #{rec['pr_number']} not eligible for the train: {reason[:80]}", [], 2
                    )
            if out == "remediating" and absent:
                self.set_outcome(
                    rec,
                    "fixed-no-release",
                    "verified",
                    "failure no longer observed after remediation",
                    verified_at=self.now.isoformat(),
                )
            elif out == "remediating" and still and (rec.get("source") != "ci" or ci_settled):
                if int(rec.get("attempts") or 0) >= int(self.cfg["dedupe"]["max_attempts_per_signature"]):
                    self.give_up(rec)
                else:
                    self.set_outcome(rec, "detected", "remediation_failed", "still failing after the remediation")
            elif out == "fixed-released-pending" and absent:
                self.set_outcome(
                    rec,
                    "fixed-released",
                    "verified",
                    "failure no longer observed on the release",
                    verified_at=self.now.isoformat(),
                )
            elif out in ("detected", "shadow-proposed", "escalated") and absent:
                self.set_outcome(rec, "cleared", "cleared", "failure no longer observed")
            elif (
                out == "detected"
                and still
                and self.live
                and int(rec.get("attempts") or 0) >= int(self.cfg["dedupe"]["max_attempts_per_signature"])
            ):
                self.give_up(rec)

    def give_up(self, rec: dict) -> None:
        self.set_outcome(rec, "gave-up", "gave_up", f"{rec.get('attempts')} attempts; still failing")
        self.page(rec, f"{rec.get('title')} — gave up after {rec.get('attempts')} attempts")
        self.coordinator(rec, f"{rec.get('title')}: self-heal gave up", [], 1)

    def from_fixer(self, rec: dict, job: dict) -> None:
        st = job.get("state")
        fields = {
            "pr_number": job.get("pr_number"),
            "pr_head": job.get("head_sha"),
            "model_cost_usd": job.get("cost_usd"),
        }
        if st in ("fix_pr_opened",) and rec.get("outcome") != "fix-PR-open":
            self.set_outcome(rec, "fix-PR-open", "fix_pr_opened", str(job.get("pr_url") or ""), **fields)
        elif st in ("fix_deployed", "output_recovered", "incident_resolved"):
            rec.update(fields)
            self.set_outcome(
                rec, "fixed-released-pending", "released", f"fixer {st}", released_sha=job.get("release_sha")
            )
        elif st in ("fix_failed", "fix_refused", "fix_closed", "fix_interrupted"):
            rec.update(fields)
            if int(rec.get("attempts") or 0) >= int(self.cfg["dedupe"]["max_attempts_per_signature"]):
                self.give_up(rec)
            else:
                self.set_outcome(rec, "detected", "fixer_failed", f"fixer {st}: {str(job.get('reason'))[:120]}")
        elif st == "fix_ready_local":
            rec["detail"] = "fixer: fix committed locally; push gated by the fixer's policy gate"

    def track_pr(self, rec: dict, cur_sha: Optional[str]) -> None:
        r = self.runner(
            ["gh", "pr", "view", str(rec["pr_number"]), "--json", "state,mergeCommit,headRefOid"],
            cwd=self.repo,
            timeout=60,
        )
        try:
            doc = json.loads(r["out"] or "{}") if r["rc"] == 0 else {}
        except ValueError:
            doc = {}
        if doc.get("state") == "CLOSED":
            return self.set_outcome(rec, "detected", "fix_pr_closed", f"PR #{rec['pr_number']} closed unmerged")
        merge = (doc.get("mergeCommit") or {}).get("oid")
        if doc.get("state") == "MERGED" and merge and cur_sha:
            anc = self.runner(["git", "-C", str(self.repo), "merge-base", "--is-ancestor", merge, cur_sha], timeout=60)
            if anc["rc"] == 0:
                self.set_outcome(
                    rec, "fixed-released-pending", "released", f"merge {merge[:12]} is in CURRENT", released_sha=cur_sha
                )

    def current_sha(self) -> Optional[str]:
        p = Path(self.environ.get("TRADEAI_CURRENT_SHA_FILE") or CURRENT_SHA_DEFAULT)
        try:
            return p.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def released_notes(self) -> None:
        for rec in self.state["fixes"].values():
            if rec.get("outcome") == "fixed-released" and not rec.get("noted_at"):
                self.page(
                    rec,
                    f"fixed + released: {rec.get('title')} (PR #{rec.get('pr_number')}, "
                    f"{str(rec.get('released_sha') or '')[:9]})",
                    priority="P2",
                )
                rec["noted_at"] = self.now.isoformat()

    def flush(self) -> None:
        if not self.write:
            return
        if self.rows:
            self.fix_log.parent.mkdir(parents=True, exist_ok=True)
            with self.fix_log.open("a", encoding="utf-8") as fh:  # append-only; never rewritten
                for row in self.rows:
                    fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        _atomic_write(self.state_path, self.state)


def tick(
    cfg: dict,
    *,
    root: Path,
    repo: Path,
    write: bool,
    now: datetime,
    runner: Runner,
    sender: Sender,
    environ: Mapping[str, str],
    agents_text: Optional[str] = None,
) -> dict:
    if agents_text is None:
        r = runner(["git", "-C", str(repo), "show", "origin/main:AGENTS.md"], timeout=60)
        agents_text = r.get("out") or "" if r["rc"] == 0 else ""
    gate = TI.policy_gate(agents_text, cfg)
    t = Tick(
        cfg=cfg,
        root=root,
        repo=repo,
        live=bool(gate["live"] and write),
        write=write,
        now=now,
        runner=runner,
        sender=sender,
        environ=environ,
    )
    src = cfg["sources"]
    release_dir = Path(environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR") or (root / src["release_state_dir_rel"]))
    ci_findings, ci_status = gather_ci(runner, repo=repo, cfg=cfg)
    findings = (
        ci_findings
        + TI.detect_train(release_dir, now=now, cfg=cfg)
        + TI.detect_tester(root / src["tester_dir_rel"], now=now, cfg=cfg)
    )
    present = {f.signature for f in findings}
    started = 0
    decisions = []
    for f in findings:
        rec = t.rec_for(f)
        ok, why = TI.gate(t.state, f, now=now, cfg=cfg)
        d = TI.decide(
            f,
            {**cfg, "deterministic": [r for r in cfg["deterministic"] if r["id"] not in (rec.get("rules_done") or [])]},
        )
        decisions.append({"fix_id": rec["fix_id"], "title": f.title, "decision": d, "gate": why})
        if not ok or started >= int(cfg["budgets"]["max_new_fix_jobs_per_tick"]):
            continue
        if rec.get("outcome") == "shadow-proposed" and not t.live:
            continue  # already proposed in shadow; one row per proposal, not one per tick
        started += 1
        t.act(f, rec, d)
    fixer_state = _load(root / src["fixer_state_rel"]) or {}
    t.advance(
        present,
        list((fixer_state.get("jobs") or {}).values()),
        TI.not_riding(release_dir),
        ci_settled=ci_status.get("ci") in ("GREEN", "RED"),
    )
    t.released_notes()
    t.flush()
    hb = {
        "schema": HEARTBEAT_SCHEMA,
        "lane_id": LANE_ID,
        "ok": True,
        "ok_at": now.astimezone(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "mode": t.mode if write else "dry_run",
        "policy": gate,
        "ci": ci_status,
        "findings": len(findings),
        "decisions": decisions[:40],
        "actions": t.actions[:40],
        "fix_log_rows": len(t.rows),
        "open_fixes": sum(1 for r in t.state["fixes"].values() if r.get("outcome") not in TI.TERMINAL_OUTCOMES),
    }
    if write:
        _atomic_write(root / cfg["state"]["heartbeat_rel"], hb)
    return hb


def main(
    argv: Optional[list[str]] = None,
    *,
    now: Optional[datetime] = None,
    runner: Runner = run,
    sender: Sender = default_sender,
    environ: Optional[Mapping[str, str]] = None,
) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="write state/log/heartbeat; act only when LIVE")
    ap.add_argument("--dry-run", action="store_true", help="default: print decisions, write nothing")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args(argv)
    environ = dict(os.environ if environ is None else environ)
    now = now or datetime.now(timezone.utc)
    try:
        cfg = TI.load_config(Path(args.config))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "why": f"config unreadable: {exc}"}))
        return 2
    root = state_root(environ)
    repo = Path(environ.get("TRADEAI_CANONICAL_SOURCE") or CANONICAL_DEFAULT)
    if args.status:
        rows = TI.project(TI.read_fix_log(root / cfg["state"]["fix_log_rel"]))
        print(
            json.dumps(
                {"fixes": rows[:50], "heartbeat": _load(root / cfg["state"]["heartbeat_rel"])}, indent=1, default=str
            )
        )
        return 0
    write = bool(args.apply) and not args.dry_run
    if write and (root / cfg["arming"]["kill_switch_rel"]).exists():
        hb = {
            "schema": HEARTBEAT_SCHEMA,
            "lane_id": LANE_ID,
            "ok": True,
            "ok_at": now.isoformat(),
            "ended_at": now.isoformat(),
            "mode": "disabled",
            "why": cfg["arming"]["kill_switch_rel"],
        }
        _atomic_write(root / cfg["state"]["heartbeat_rel"], hb)
        print(json.dumps(hb))
        return 0
    lock_fh = None
    if write:
        lock_p = root / cfg["state"]["lock_rel"]
        lock_p.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = lock_p.open("w")
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"busy": True, "why": "another tick holds the lock"}))
            return 0
    try:
        hb = tick(cfg, root=root, repo=repo, write=write, now=now, runner=runner, sender=sender, environ=environ)
    finally:
        if lock_fh is not None:
            lock_fh.close()
    print(json.dumps(hb, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

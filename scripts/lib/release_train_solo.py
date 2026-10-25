"""Solo shared-infra trains (Release Train v2; AGENTS.md 20.4.0 "hands-off delivery", 2026-10-25).

Operator, 2026-10-25 (verbatim): "fully done, fully automatic, no input by me, for the train systems unless there's
an issue." Before this module a ``needs_operator`` PR never rode a train. A shared-infra change (scheduler, lane
registry, n8n allowlist, systemd units, comms routes, n8n config, deploy-adjacent scripts) now rides ALONE -- a train
of exactly one member, never mixed with eligible PRs -- once the coordinator's adversarial review says MERGE.

Gate. Everything here is OFF unless ``hands_off_policy.policy_state_from_path(<code root>/AGENTS.md)["active"]``
(20.4.0 or later ACTIVE in the train's own exact-main tree, read at call time; no flag, no environment override).
While it is off the controller behaves exactly as before: needs_operator is excluded.

Eligibility (``evaluate``), ALL required; DENY WINS (config/release_train_solo_shared_infra.json):

  1. policy gate active;
  2. the classifier's overall class is exactly ``needs_operator`` (held / blocked never ride);
  3. title starts ``[shared-infra] ``;
  4. ``shared-infra-review`` concluded ``success`` on the exact head SHA (latest run, trusted app);
  5. the body has a ``Real-layout proof:`` line (``hands_off_policy.real_layout_ref``);
  6. a PR comment carries ``Adversarial-review: MERGE reviewer=<ref> head=<sha> coordinator=<session>``
     (``hands_off_policy.parse_receipt``) whose head is a prefix of the PR head and whose session holds a coordinator
     claim (``coordination/COORDINATOR``) on the agent claim board (live, stale or done; not abandoned);
  7. every changed path matches ``allow_globs``; none matches ``deny_globs``, a ``deny_policy_rules`` rule of
     config/release_train_policy.json, or the controller's ``PROTECTED_SURFACES``; no classifier reason names a
     ``deny_reason_rules`` rule (deletion, oversized, unknown risk, guard / policy / broker / auth / migrations).

Precedence (``choose``): ``batch_first`` (default) -- a window with an eligible batch carries the batch; the solo
candidate waits for a window with none. Exactly one solo member, chosen in batch-queue order. Never mixed.

Verification (``verify_release``): for a solo train the controller adds three checks to release_window's
verification, run against the promoted release directory, with the previous release as baseline: n8n allowlist
(every lane valid, refused == {}), lane registry (no NEW violation), cron-outage watchdog dry run (no NEW CRIT /
missed lane / refusal). A failed check takes the controller's existing path: rollback to the bound target, STOP
latch, quarantine, P1.

AUTHORITY: READ_ONLY_ADVISORY (selection reads GitHub GET + the claim board; verification runs read-only
validators). MBI_BEHAVIOR = 0: no broker, no order path, no credential read.
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

try:
    from scripts.lib import hands_off_policy as HOP
except ImportError:  # pragma: no cover - scripts/ on sys.path
    from lib import hands_off_policy as HOP  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "release_train_solo_shared_infra.json"
SCHEMA = "ReleaseTrainSoloSharedInfra@v1"
TRAIN_KIND_BATCH = "batch"
TRAIN_KIND_SOLO = "solo_shared_infra"
PRECEDENCES = ("batch_first", "solo_first")
VERIFY_CHECKS = ("n8n_allowlist", "lane_registry", "watchdog_dry_run")
_LIST_KEYS = ("allow_globs", "deny_globs", "deny_policy_rules", "deny_reason_rules", "trusted_check_apps")


# ── config ────────────────────────────────────────────────────────────────────────────────────────────────────


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_config(doc: Any) -> list[str]:
    if not isinstance(doc, Mapping):
        return ["config is not an object"]
    errs = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    for k in _LIST_KEYS:
        v = doc.get(k)
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and x for x in v):
            errs.append(f"{k} must be a non-empty list of strings")
    if not isinstance(doc.get("title_prefix"), str) or not doc["title_prefix"].startswith("[shared-infra]"):
        errs.append("title_prefix must start with [shared-infra]")
    if not isinstance(doc.get("required_check"), str) or not doc.get("required_check"):
        errs.append("required_check must be a check name")
    if doc.get("precedence") not in PRECEDENCES:
        errs.append(f"precedence must be one of {list(PRECEDENCES)}")
    return errs


def _match(path: str, globs: Iterable[str]) -> bool:
    for g in globs:
        if fnmatch.fnmatchcase(path, g):
            return True
        if g.startswith("**/") and fnmatch.fnmatchcase(path, g[3:]):
            return True
        if g.endswith("/**") and (path == g[:-3] or path.startswith(g[:-2])):
            return True
        if "/**/" in g and fnmatch.fnmatchcase(path, g.replace("/**/", "/")):
            return True  # "a/**/b" also matches "a/b" (zero directories)
    return False


# ── eligibility ───────────────────────────────────────────────────────────────────────────────────────────────


def reason_rules(reasons: Iterable[Any]) -> list[str]:
    """Rule names from classifier reasons: dicts ({"rule": ...}) or the controller's ``"rule:path"`` strings."""
    out = []
    for r in reasons or ():
        if isinstance(r, Mapping):
            out.append(str(r.get("rule") or ""))
            continue
        s = str(r)
        if s.startswith("ci_risk_tiers:"):
            out.append(":".join(s.split(":")[:2]))
        else:
            out.append(s.split(":", 1)[0])
    return [x for x in out if x]


def path_findings(paths: Sequence[str], cfg: Mapping[str, Any], *, policy: Optional[Mapping[str, Any]] = None,
                  is_protected: Callable[[str], bool] = lambda _p: False) -> list[str]:
    """Why these paths cannot ride solo ([] = they can). Deny wins; a path outside the allow list refuses."""
    out: list[str] = []
    if not paths:
        return ["NO_CHANGED_PATHS"]
    deny_rules = set(cfg.get("deny_policy_rules") or ())
    rule_globs = [(r.get("id"), r.get("globs") or ()) for r in ((policy or {}).get("rules") or ())
                  if r.get("id") in deny_rules]
    for p in paths:
        if is_protected(p):
            out.append(f"DENY_PROTECTED_SURFACE:{p}")
        elif _match(p, cfg.get("deny_globs") or ()):
            out.append(f"DENY_GLOB:{p}")
        elif any(_match(p, globs) for _id, globs in rule_globs):
            rid = next(_id for _id, globs in rule_globs if _match(p, globs))
            out.append(f"DENY_POLICY_RULE:{rid}:{p}")
        elif not _match(p, cfg.get("allow_globs") or ()):
            out.append(f"NOT_SHARED_INFRA:{p}")
    return out


def check_green(runs: Iterable[Mapping[str, Any]], sha: str, name: str, apps: Iterable[str]) -> tuple[bool, str]:
    """The latest run of ``name`` on exactly ``sha`` from a trusted app is completed/success."""
    mine = [r for r in runs or () if r.get("name") == name and r.get("head_sha") == sha
            and r.get("app") in set(apps)]
    if not mine:
        return False, "MISSING"
    latest = max(mine, key=lambda r: int(r.get("id") or 0))
    if latest.get("status") != "completed":
        return False, str(latest.get("status") or "UNKNOWN").upper()
    if latest.get("conclusion") != "success":
        return False, str(latest.get("conclusion") or "UNKNOWN").upper()
    return True, "SUCCESS"


def find_receipt(comments: Iterable[Any], head_sha: str, claim_rows: Iterable[Mapping[str, Any]]) -> tuple[
        Optional[dict], str]:
    """The newest receipt bound to ``head_sha`` whose coordinator session holds a coordinator claim."""
    rows = list(claim_rows or ())
    why = "NO_RECEIPT"
    for c in reversed(list(comments or ())):
        body = c.get("body") if isinstance(c, Mapping) else c
        for rcpt in reversed(HOP.parse_receipt(str(body or ""))):
            if not head_sha.startswith(rcpt["head"]):
                why = "RECEIPT_HEAD_MISMATCH"
                continue
            claim = HOP.coordinator_session_ok(rcpt["coordinator"], rows, live_only=False)
            if claim is None:
                why = "RECEIPT_NOT_FROM_COORDINATOR"
                continue
            out = dict(rcpt)
            out["claim_id"] = str(claim.get("claim_id") or "")
            if isinstance(c, Mapping) and c.get("author"):
                out["author"] = str(c["author"])[:80]
            return out, "OK"
    return None, why


def evaluate(*, pr: int, head_sha: str, title: str, risk: str, reasons: Iterable[Any], paths: Sequence[str],
             pr_text: Optional[Mapping[str, Any]], runs: Iterable[Mapping[str, Any]],
             claim_rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], policy_state: Mapping[str, Any],
             train_policy: Optional[Mapping[str, Any]] = None,
             is_protected: Callable[[str], bool] = lambda _p: False) -> dict:
    """Pure: may this PR ride as the only member of a train? ``{"eligible", "why", "receipt", ...}``."""
    why: list[str] = []
    if not policy_state.get("active"):
        return {"pr": pr, "eligible": False, "why": [f"POLICY_NOT_ACTIVE:{policy_state.get('detail')}"]}
    errs = validate_config(cfg)
    if errs:
        return {"pr": pr, "eligible": False, "why": ["CONFIG_INVALID:" + "; ".join(errs)[:200]]}
    if risk != "needs_operator":
        why.append(f"CLASS_NOT_NEEDS_OPERATOR:{risk}")
    text = pr_text or {}
    if not pr_text:
        why.append("PR_TEXT_UNREADABLE")
    t = str(text.get("title") or title or "")
    if not t.startswith(str(cfg["title_prefix"])):
        why.append("TITLE_NOT_SHARED_INFRA")
    ok, state = check_green(runs, head_sha, str(cfg["required_check"]), cfg["trusted_check_apps"])
    if not ok:
        why.append(f"SHARED_INFRA_REVIEW_NOT_GREEN:{state}")
    proof = HOP.real_layout_ref(str(text.get("body") or ""))
    if not proof:
        why.append("NO_REAL_LAYOUT_PROOF")
    receipt, rwhy = find_receipt(text.get("comments") or (), head_sha, claim_rows)
    if receipt is None:
        why.append(rwhy)
    why.extend(path_findings(list(paths), cfg, policy=train_policy, is_protected=is_protected))
    deny = set(cfg.get("deny_reason_rules") or ())
    bad = sorted({r for r in reason_rules(reasons) if r in deny})
    why.extend(f"DENY_REASON:{r}" for r in bad)
    return {"pr": pr, "head_sha": head_sha, "eligible": not why, "why": why, "receipt": receipt,
            "real_layout_proof": proof, "paths": len(paths)}


def ride_ref(verdict: Mapping[str, Any]) -> str:
    """TrainCandidate@v1 ``ride_approval_ref`` for the solo member (<= 200 chars)."""
    r = verdict.get("receipt") or {}
    return (f"solo-shared-infra adversarial-review MERGE reviewer={r.get('reviewer')} "
            f"coordinator={r.get('coordinator')} head={str(r.get('head'))[:12]}")[:200]


def choose(batch: Sequence[Any], solo: Sequence[Any], precedence: str = "batch_first") -> tuple[str, list, dict]:
    """(kind, members, deferred{pr: reason}). ``batch`` is the ordered eligible list; ``solo`` the eligible solo
    candidates in queue order. Never mixed; a solo train has exactly one member."""
    def pr_of(x: Any) -> int:
        return int(getattr(x, "pr", x))

    if precedence not in PRECEDENCES:
        precedence = "batch_first"
    deferred: dict[int, str] = {}
    if solo and (precedence == "solo_first" or not batch):
        pick, rest = solo[0], list(solo[1:])
        for s in rest:
            deferred[pr_of(s)] = "SOLO_ONE_PER_TRAIN"
        for b in batch:
            deferred[pr_of(b)] = "BATCH_DEFERRED_SOLO_FIRST"
        return TRAIN_KIND_SOLO, [pick], deferred
    for s in solo:
        deferred[pr_of(s)] = "SOLO_DEFERRED_BATCH_FIRST"
    return TRAIN_KIND_BATCH, list(batch), deferred


# ── verification (solo trains only) ───────────────────────────────────────────────────────────────────────────

_ALLOWLIST_SNIPPET = r"""
import json, sys
root = sys.argv[1]
sys.path[:0] = [root, root + "/scripts"]
import scripts.n8n_run_executor as X
doc = json.load(open(root + "/config/n8n_run_allowlist.json", encoding="utf-8"))
if doc.get("schema") != X.ALLOWLIST_SCHEMA:
    print(json.dumps({"lanes": 0, "refused": {"$schema": "bad_allowlist_schema"}}))
    raise SystemExit(1)
lanes = [e for e in (doc.get("lanes") or []) if isinstance(e, dict)]
refused = {}
for e in lanes:
    p = X.validate_entry(e)
    if p:
        refused[str(e.get("lane_id"))] = p
print(json.dumps({"lanes": len(lanes), "refused": refused}, sort_keys=True))
raise SystemExit(1 if refused or not lanes else 0)
"""

Runner = Callable[[list, Path, dict, float], tuple[int, str]]


def _subprocess_runner(argv: list, cwd: Path, env: dict, timeout: float) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
                           check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 99, json.dumps({"runner_error": type(exc).__name__})
    return p.returncode, p.stdout


def _json_tail(out: str) -> Optional[dict]:
    """The JSON document a validator printed (whole stdout, else the first '{' to the end)."""
    out = (out or "").strip()
    for cand in (out, out[out.find("{"):] if "{" in out else ""):
        try:
            d = json.loads(cand)
            return d if isinstance(d, dict) else None
        except ValueError:
            continue
    return None


def allowlist_check(release: Path, *, python: str, env: dict, run: Runner, timeout: float) -> dict:
    rc, out = run([python, "-I", "-c", _ALLOWLIST_SNIPPET, str(release)], release, env, timeout)
    d = _json_tail(out) or {}
    refused = d.get("refused")
    ok = rc == 0 and isinstance(refused, dict) and not refused and int(d.get("lanes") or 0) > 0
    return {"ok": ok, "rc": rc, "lanes": d.get("lanes"), "refused": refused if isinstance(refused, dict) else None}


def _registry_keys(d: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for k in ("errors", "dispatch_findings", "inactive_n8n_rows", "state_drift_conflicts"):
        for v in d.get(k) or ():
            keys.add(f"{k}:{json.dumps(v, sort_keys=True, default=str)[:300]}")
    for v in d.get("undeclared") or ():
        if isinstance(v, Mapping):
            keys.add(f"undeclared:{v.get('kind')}:{v.get('expression')}")
        else:
            keys.add(f"undeclared:{v}")
    return keys


def lane_registry_check(release: Path, baseline: Path, *, python: str, env: dict, run: Runner,
                        timeout: float) -> dict:
    argv = [python, "scripts/check_lane_registry.py", "--json"]
    rc_new, out_new = run(argv, release, env, timeout)
    rc_old, out_old = run(argv, baseline, env, timeout)
    new, old = _json_tail(out_new), _json_tail(out_old)
    if rc_new not in (0, 1) or new is None:
        return {"ok": False, "rc": rc_new, "reason": "CANNOT_RUN"}
    added = sorted(_registry_keys(new) - (_registry_keys(old) if old is not None else set()))
    return {"ok": not added, "rc": rc_new, "baseline_rc": rc_old, "new_violations": added[:20],
            "baseline_readable": old is not None}


_WD_RANK = {"OK": 0, "UNKNOWN": 1, "WARN": 2, "CRIT": 3}


def _wd_keys(d: Mapping[str, Any]) -> set[str]:
    out = {f"missed:{x}" for x in d.get("missed_lane_ids") or ()}
    out |= {f"refusal:{json.dumps(x, sort_keys=True, default=str)[:300]}" for x in d.get("refusals") or ()}
    return out


def watchdog_check(release: Path, baseline: Path, *, python: str, env: dict, run: Runner, timeout: float) -> dict:
    argv = [python, "scripts/cron_outage_watchdog.py", "--dry-run"]
    rc_new, out_new = run(argv, release, env, timeout)
    rc_old, out_old = run(argv, baseline, env, timeout)
    new, old = _json_tail(out_new), _json_tail(out_old)
    if rc_new not in (0, 1) or new is None or new.get("mode") not in (None, "dry_run"):
        return {"ok": False, "rc": rc_new, "reason": "CANNOT_RUN"}
    st_new = str(new.get("status") or "UNKNOWN").upper()
    st_old = str((old or {}).get("status") or "UNKNOWN").upper()
    added = sorted(_wd_keys(new) - (_wd_keys(old) if old is not None else set()))
    worse_crit = st_new == "CRIT" and st_old != "CRIT"
    return {"ok": not added and not worse_crit, "rc": rc_new, "status": st_new, "baseline_status": st_old,
            "new_findings": added[:20]}


def verify_release(release: Path, baseline: Path, *, python: str = sys.executable, env: Optional[dict] = None,
                   run: Runner = _subprocess_runner, timeout: float = 180.0) -> dict:
    """The three solo-train checks, release_window ``_verify`` shape: {name: {"ok": bool, ...}}. Never raises."""
    env = dict(env or {})
    out: dict[str, dict] = {}
    for name, fn in (("n8n_allowlist", lambda: allowlist_check(release, python=python, env=env, run=run,
                                                                timeout=timeout)),
                     ("lane_registry", lambda: lane_registry_check(release, baseline, python=python, env=env,
                                                                   run=run, timeout=timeout)),
                     ("watchdog_dry_run", lambda: watchdog_check(release, baseline, python=python, env=env,
                                                                 run=run, timeout=timeout))):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 - a check that cannot run is a failed check, never a pass
            out[name] = {"ok": False, "reason": f"ERROR:{type(exc).__name__}"}
    return out


# ── host readers (defaults; tests inject) ─────────────────────────────────────────────────────────────────────


def policy_state(code_root: Path = ROOT) -> dict:
    return HOP.policy_state_from_path(Path(code_root) / "AGENTS.md")


def claim_rows() -> list[dict]:
    try:
        return HOP._claim_rows(None)
    except Exception:  # noqa: BLE001 - an unreadable board has no coordinator (fail closed)
        return []

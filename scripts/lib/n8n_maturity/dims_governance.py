"""Governance, security, CI and docs dimensions (7, 8, 11, 12) of the n8n platform maturity scorer.

Every number is read through ``core.Probe`` (read-only by construction). Missing evidence scores 0 and
is UNVERIFIED (a whole dimension) or PARTIAL (one sub-criterion); nothing is assumed.

Scoring convention shared by the four collectors (see each docstring for the sub-criteria):

* a sub-criterion that MEETS its gate scores 10;
* a sub-criterion below its gate scores ``core.ratio_score(fraction, 1.0)`` — linear 0 → 8.0, so it is
  always < 8.0 unless the fraction is exactly 1;
* a sub-criterion whose evidence could not be read is ``None`` (scored 0, dimension PARTIAL);
* dimension score = ``core.mean_score`` of the sub-scores; when any sub-criterion misses its gate the
  dimension is capped at ``GATE_CAP`` (7.9), so "gate met" ⇔ score ≥ 8.0.

Secrets: environment VALUES are never read into results. Container env is inspected with a docker
template that prints names only; the systemd ``Environment`` property is parsed for one non-secret
key (``TRADEAI_EXECUTOR_ENV_ALLOWLIST``) and everything else is discarded; ``.env`` files are never
opened (AGENTS never-grantable ``secret`` scope).
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from . import core

# Code (not data) lives in the repo that holds this file; data comes from probe.root / probe.proj.
_CODE_REPO = Path(__file__).resolve().parents[3]

GATE_CAP = 7.9
WINDOW_HOURS = 24.0

# ---- governance defaults ------------------------------------------------------------------------
DEFAULT_GRANT_TIERS = ("cron", "config-write", "service")
DEFAULT_GRANT_SKEW_S = 120
RECEIPT_MAX_AGE_H = 26.0
P16 = {"script": "check_n8n_activation_grants", "lane": "n8n-activation-grants",
       "receipt": "data/runtime/n8n_activation_grants_last.json"}
P18 = {"script": "check_n8n_workflow_drift", "lane": "n8n-workflow-drift-check",
       "receipt": "data/runtime/n8n_workflow_drift_last.json"}
GUARD_HOOK_TOKEN = "agents_guard_pretooluse"
GUARD_HOOK_LOG = "data/runtime/agents_guard_hook.jsonl"

# ---- security defaults --------------------------------------------------------------------------
RELAY_UNIT = "tradeai-n8n-run-relay.service"
EXECUTOR_UNIT = "tradeai-n8n-run-executor.service"
FULL_ENV_FILES = ("tradeai/env",)          # path suffixes of the full rendered secrets env
RELAY_ALLOWLIST_MODULE = "scripts/lib/n8n_relay_env.py"
EXECUTOR_MODULE = "scripts/n8n_run_executor.py"
EXECUTOR_MODE_ENV = "TRADEAI_EXECUTOR_ENV_ALLOWLIST"
RUN_ALLOWLIST = "config/n8n_run_allowlist.json"
APP_ROLE = "n8n_app"
DB_USER_ENV = "DB_POSTGRESDB_USER"
DEFAULT_DB_CONTAINER = "m8m-n8n-db"
DEFAULT_APP_CONTAINER = "m8m-n8n"
CODE_STAGE_WEIGHT = 0.25                   # credit for "built and served" before "live"
PASSWORD_NAME_RE = re.compile(r"(^|_)(PASSWORD|PASSWD|PASS|PWD)(_|$)", re.IGNORECASE)
_ENV_NAMES_TEMPLATE = '{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}'

# ---- CI defaults --------------------------------------------------------------------------------
NIGHTLY_MAX_AGE_H = 36.0
CI_GATE_MAX_AGE_H = 48.0
NIGHTLY_STREAK_TOP = 7
CI_GATE_JOB = "ci-gate"

# ---- docs defaults ------------------------------------------------------------------------------
DOCS_AGENTS = "AGENTS.md"
DOCS_ADR = ("docs/architecture/n8n/ADR_COORDINATION_SECRETS.md",)
DOCS_RUNBOOKS = (
    "docs/ops/AGENTS_GUARD_HOOK.md",
    "docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md",
    "docs/ops/ROLLBACK_COMMANDS.md",
    "docs/implementation/n8n-parallel/17-n8n-operating-model-20261008.md",
    "docs/implementation/n8n-parallel/lanes/*.md",
    "docs/implementation/n8n-maturity/*.md",
)
UNIT_RUNBOOKS = ("docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md", "docs/ops/ROLLBACK_COMMANDS.md")
DEPLOY_SCRIPT = "scripts/cio_phase2_exact_main_deploy.sh"
DOCS_FINDINGS_ZERO_AT = 20
_PATH_REF_RE = re.compile(r"`((?:scripts|config|docs|tests|bin|\.github|infra)/[A-Za-z0-9_./-]+?)(?::\d+(?:-\d+)?)?`")
_PROPOSED_RE = re.compile(r"\b(\d+\.\d+\.\d+)\s*\(?\s*PROPOSED\b")
_BOUND_UNITS_RE = re.compile(r"TRADEAI_CURRENT_BOUND_UNITS:-([^}\"]*)")



# ================================================================================================
# shared helpers
# ================================================================================================

def _met_score(fraction: Optional[float]) -> Optional[float]:
    """10 when the gate fraction is fully met, linear 0→8 below (core.ratio_score), None when unread."""
    if fraction is None:
        return None
    return 10.0 if fraction >= 1.0 else core.ratio_score(max(0.0, fraction), 1.0)


def _combine(dim_id: str, rule: str, parts: list[tuple[str, Optional[float]]], metrics: dict,
             ev: list[dict], notes: list[str]) -> dict:
    score, status, extra = core.mean_score(parts)
    gate_pass = all(v is not None and v >= 10.0 for _, v in parts)
    if not gate_pass:
        score = min(score, GATE_CAP)
    metrics = {**metrics, "sub_scores": {n: (None if v is None else round(v, 2)) for n, v in parts}}
    if status == core.UNVERIFIED:
        return core.unverified(dim_id, rule, "; ".join(extra + notes) or "no evidence", metrics=metrics,
                               evidence_list=ev)
    return core.dim_result(dim_id, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=extra + notes)


def _rule(probe: core.Probe, dim_id: str) -> str:
    return probe.cfg(dim_id).get("gate_rule") or "gate not configured"


def _home(probe: core.Probe) -> Path:
    h = probe.env.get("HOME")
    return Path(h) if h else Path.home()


def _load_module(name: str, rel: str) -> ModuleType:
    """Import a repo script by path (its pure functions only). Raises on failure."""
    key = f"_n8nmat_{name}"
    if key in sys.modules:
        return sys.modules[key]
    for p in (str(_CODE_REPO), str(_CODE_REPO / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(key, _CODE_REPO / rel)
    if spec is None or spec.loader is None:
        raise ImportError(rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[key] = mod
    return mod


def _age_h(probe: core.Probe, ts: Any) -> Optional[float]:
    d = core.parse_ts(ts)
    return None if d is None else round((probe.now - d).total_seconds() / 3600.0, 2)


def _docker_names(probe: core.Probe) -> Optional[list[tuple[str, str]]]:
    rc, out, _ = probe.run(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"])
    if rc != 0:
        return None
    rows = []
    for line in out.splitlines():
        if "\t" in line:
            n, img = line.split("\t", 1)
            rows.append((n.strip(), img.strip()))
    return rows


def _containers(probe: core.Probe, dim_id: str) -> tuple[str, str]:
    """(n8n app container, n8n db container): config, else discovered from ``docker ps``, else defaults."""
    c = probe.cfg(dim_id)
    app, db = c.get("n8n_container"), c.get("n8n_db_container")
    if app and db:
        return app, db
    rows = _docker_names(probe) or []
    if not db:
        db = next((n for n, img in rows if "n8n" in n.lower() and "postgres" in img.lower()), DEFAULT_DB_CONTAINER)
    if not app:
        app = next((n for n, img in rows if "n8nio/n8n" in img.lower()), None) or next(
            (n for n, img in rows if "n8n" in n.lower() and "postgres" not in img.lower()), DEFAULT_APP_CONTAINER)
    return app, db


def _select_json(probe: core.Probe, container: str, sql: str) -> Any:
    """One SELECT through ``docker exec <db> psql`` (probe allowlist). Raises RuntimeError on failure."""
    rc, out, err = probe.run(["docker", "exec", container, "psql", "-U", "n8n", "-d", "n8n", "-t", "-A", "-c", sql])
    if rc != 0:
        raise RuntimeError(f"psql rc={rc}: {(err or '').strip()[:160]}")
    text = (out or "").strip()
    if not text:
        raise RuntimeError("psql returned no output")
    return json.loads(text)


def _env_names(probe: core.Probe, container: str) -> Optional[list[str]]:
    """Container env NAMES only (docker template splits on '='; values never leave docker)."""
    rc, out, _ = probe.run(["docker", "inspect", container, "--format", _ENV_NAMES_TEMPLATE])
    if rc != 0:
        return None
    return sorted({ln.strip() for ln in out.splitlines() if ln.strip() and "=" not in ln})


def _systemctl_props(probe: core.Probe, unit: str, props: list[str]) -> Optional[list[tuple[str, str]]]:
    argv = ["systemctl", "--user", "show", unit]
    for p in props:
        argv += ["-p", p]
    rc, out, _ = probe.run(argv)
    if rc != 0:
        return None
    return [tuple(line.split("=", 1)) for line in out.splitlines() if "=" in line]  # type: ignore[misc]


def _served_root(probe: core.Probe, dim_id: str) -> tuple[Path, str]:
    c = probe.cfg(dim_id).get("served_code_root")
    if c:
        return Path(c), "config"
    served = probe.root.parent / "portfolio-server" / "CURRENT"
    if served.exists():
        return served, "served CURRENT"
    return probe.proj, "repo checkout (served CURRENT absent)"


# ================================================================================================
# 7 governance
# ================================================================================================

def _guard_audit_log(probe: core.Probe) -> Path:
    c = probe.cfg("governance").get("guard_audit_log")
    if c:
        return Path(c)
    if probe.env.get("GUARD_AUDIT_LOG"):
        return Path(probe.env["GUARD_AUDIT_LOG"])
    return _home(probe) / "logs" / "cursor-agent-audit.jsonl"


def _grant_coverage(probe: core.Probe, db: str, ev: list[dict], metrics: dict, notes: list[str]) -> tuple[
        Optional[float], list[dict]]:
    """Fraction of ACTIVE workflows whose current activation is GRANTED (P16 checker logic, by id)."""
    cfg = probe.cfg("governance")
    try:
        p16 = _load_module("p16", "scripts/check_n8n_activation_grants.py")
        inv = p16.inv
        evidence = {
            "workflows": _select_json(probe, db, inv.WORKFLOW_LIST_SQL) or [],
            "publish_history": _select_json(probe, db, inv.PUBLISH_HISTORY_SQL) or [],
            "published_versions": _select_json(probe, db, inv.PUBLISHED_VERSION_SQL) or [],
            "version_history": _select_json(probe, db, inv.VERSION_HISTORY_SQL) or [],
        }
    except Exception as exc:  # noqa: BLE001 — unread evidence, not a clean result
        notes.append(f"active workflows unread: {type(exc).__name__}: {str(exc)[:160]}")
        return None, []
    workflows = list(evidence["workflows"])
    active = [w for w in workflows if w.get("active")]
    ev.append(core.evidence(f"docker exec {db} psql SELECT workflow_entity/publish history", workflows=len(workflows),
                            active=len(active)))
    log = _guard_audit_log(probe)
    try:
        grants = p16.load_grants(log)
    except (OSError, FileNotFoundError) as exc:
        notes.append(f"guard audit log unread: {type(exc).__name__}")
        return None, workflows
    ev.append(core.evidence(str(log.name), grants_issued=len(grants), via="guard audit jsonl (what `guard log` reads)"))
    tiers = tuple(cfg.get("grant_tiers") or DEFAULT_GRANT_TIERS)
    epoch = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
    rows = p16.reconcile(p16.activation_events(evidence, since=epoch), grants, tiers=tiers,
                         skew_s=int(cfg.get("grant_skew_s", DEFAULT_GRANT_SKEW_S)))
    name_only_ok = bool(cfg.get("count_name_only_as_granted", False))
    ok_status = {"GRANTED"} | ({"NAME_ONLY_GRANT"} if name_only_ok else set())
    per: dict[str, str] = {}
    for w in active:
        wid = str(w.get("id"))
        mine = [r for r in rows if r["workflow_id"] == wid]
        cur = [r for r in mine if r["version_id"] == str(w.get("activeVersionId") or w.get("versionId"))] or mine
        per[wid] = cur[-1]["status"] if cur else "NO_ACTIVATION_EVENT"
    granted = sum(1 for s in per.values() if s in ok_status)
    counts: dict[str, int] = {}
    for s in per.values():
        counts[s] = counts.get(s, 0) + 1
    metrics.update(active_workflows=len(active), active_granted=granted, activation_status_counts=counts,
                   ungranted_ids=sorted(w for w, s in per.items() if s not in ok_status)[:20])
    if not active:
        notes.append("no active n8n workflows: grant coverage vacuously 100%")
        return 1.0, workflows
    return granted / len(active), workflows


def _check_scheduled(probe: core.Probe, spec: dict, crontab: Optional[str], timers: Optional[str],
                     workflows: list[dict], key: str, ev: list[dict], metrics: dict) -> tuple[Optional[float], str]:
    """P16/P18: scheduled (crontab line / user timer / active non-shadow n8n workflow) AND a fresh receipt."""
    script, lane = spec["script"], spec["lane"]
    how = []
    if crontab is not None:
        for line in crontab.splitlines():
            s = line.strip()
            if s and not s.startswith("#") and script in s:
                how.append("crontab")
                break
    if timers is not None and (lane in timers or script.replace("_", "-") in timers):
        how.append("systemd-timer")
    for w in workflows:
        if w.get("active") and str(w.get("name") or "") == lane:
            how.append("n8n")
            break
    shadow = any(w.get("active") and str(w.get("name") or "") == f"{lane}-shadow" for w in workflows)
    sched_known = crontab is not None or timers is not None or bool(workflows)
    rpath = probe.root / spec["receipt"]
    rec = probe.json(rpath)
    age = _age_h(probe, (rec or {}).get("as_of")) if isinstance(rec, dict) else None
    max_age = float(probe.cfg("governance").get("receipt_max_age_hours", RECEIPT_MAX_AGE_H))
    fresh = age is not None and age <= max_age
    metrics[key] = {"scheduled_by": how, "shadow_only": shadow and not how, "receipt_age_h": age,
                    "receipt_fresh": fresh, "fanin_wired": (rec or {}).get("fanin_wired") if isinstance(rec, dict) else None}
    ev.append(core.evidence(spec["receipt"], age_h=age, scheduled_by=",".join(how) or "none"))
    if not sched_known and rec is None:
        return None, f"{key}: schedule sources and receipt unread"
    return (1.0 if how else 0.0) * 0.5 + (0.5 if fresh else 0.0), ""


def _guard_hook(probe: core.Probe, ev: list[dict], metrics: dict) -> Optional[float]:
    """AGENTS PreToolUse hook installed in any Claude settings file (read only)."""
    paths = probe.cfg("governance").get("claude_settings_paths")
    if paths:
        cands = [Path(p) for p in paths]
    else:
        home = _home(probe) / ".claude"
        cands = [home / "settings.json", home / "settings.local.json",
                 probe.proj / ".claude" / "settings.json", probe.proj / ".claude" / "settings.local.json"]
    read_any, installed, mode = False, [], None
    for p in cands:
        d = probe.json(p)
        if d is None:
            continue
        read_any = True
        for entry in ((d.get("hooks") or {}).get("PreToolUse") or []) if isinstance(d, dict) else []:
            for h in (entry or {}).get("hooks") or []:
                cmd = str((h or {}).get("command") or "")
                if GUARD_HOOK_TOKEN in cmd:
                    scope = "repo" if probe.proj in p.parents else "user"
                    installed.append(f"{scope}:{p.name}")
                    m = re.search(r"TRADEAI_AGENTS_GUARD_MODE=(\w+)", cmd)
                    mode = m.group(1) if m else mode
    rows = probe.rows(probe.root / GUARD_HOOK_LOG, since=probe.since(WINDOW_HOURS))
    metrics["guard_hook"] = {"installed_in": installed, "mode": mode,
                             "decisions_24h": None if rows is None else len(rows)}
    ev.append(core.evidence("~/.claude/settings*.json hooks.PreToolUse", installed=bool(installed), mode=mode))
    if not read_any:
        return None
    return 1.0 if installed else 0.0


def collect_governance(probe: core.Probe) -> dict:
    """7 Governance enforced.

    Sub-criteria (each 10 when met, ``ratio_score(fraction, 1)`` below; mean; capped 7.9 on a miss):
      grants     = active n8n workflows whose current activation is GRANTED by a guard grant naming the
                   workflow id in an activation tier / active workflows (P16 checker reconcile logic, n8n DB
                   via docker exec SELECT, guard audit jsonl). Gate 100%.
      p16, p18   = 0.5 × scheduled (uncommented crontab line running the checker, a user timer naming the
                   lane, or an ACTIVE non-shadow n8n workflow named the lane) + 0.5 × receipt fresh
                   (``as_of`` ≤ receipt_max_age_hours). Gate both.
      guard_hook = PreToolUse hook command containing ``agents_guard_pretooluse`` in a Claude settings file.
    """
    dim, rule = "governance", _rule(probe, "governance")
    ev: list[dict] = []
    metrics: dict = {}
    notes: list[str] = []
    _app, db = _containers(probe, dim)
    grants_frac, workflows = _grant_coverage(probe, db, ev, metrics, notes)
    crontab = probe.crontab()
    rc, timers, _ = probe.run(["systemctl", "--user", "list-timers", "--all", "--no-pager"])
    timers = timers if rc == 0 else None
    p16, n16 = _check_scheduled(probe, P16, crontab, timers, workflows, "p16", ev, metrics)
    p18, n18 = _check_scheduled(probe, P18, crontab, timers, workflows, "p18", ev, metrics)
    notes += [n for n in (n16, n18) if n]
    hook = _guard_hook(probe, ev, metrics)
    parts = [("grants", _met_score(grants_frac)), ("p16_scheduled_alerting", _met_score(p16)),
             ("p18_scheduled_alerting", _met_score(p18)), ("guard_hook_installed", _met_score(hook))]
    return _combine(dim, rule, parts, metrics, ev, notes)


# ================================================================================================
# 8 security
# ================================================================================================

def _relay_env(probe: core.Probe, served: Path, ev: list[dict], metrics: dict) -> Optional[float]:
    """Relay unit does not load the full secrets env; the relay env allowlist module is served."""
    cfg = probe.cfg("security")
    unit = cfg.get("relay_unit", RELAY_UNIT)
    props = _systemctl_props(probe, unit, ["EnvironmentFiles", "LoadState"])
    code = (served / RELAY_ALLOWLIST_MODULE).exists()
    if props is None:
        metrics["relay_env"] = {"unit_read": False, "allowlist_module_served": code}
        return None
    files = [v.split(" (")[0] for k, v in props if k == "EnvironmentFiles"]
    load = next((v for k, v in props if k == "LoadState"), None)
    full = [f for f in files if any(f.endswith(s) for s in cfg.get("full_env_files", FULL_ENV_FILES))]
    live = load == "loaded" and not full
    metrics["relay_env"] = {"load_state": load, "env_files": [Path(f).name for f in files],
                            "loads_full_secrets_env": bool(full), "allowlist_module_served": code}
    ev.append(core.evidence(f"systemctl --user show {unit} -p EnvironmentFiles", full_env=bool(full), load=load))
    return 1.0 if live else (CODE_STAGE_WEIGHT if code else 0.0)


def _p7(probe: core.Probe, served: Path, ev: list[dict], metrics: dict, notes: list[str]) -> Optional[float]:
    """P7 per-lane executor env allowlist: code served, then enforced per allowlisted lane."""
    cfg = probe.cfg("security")
    src = probe.text(served / EXECUTOR_MODULE)
    allow = probe.json(served / RUN_ALLOWLIST)
    if src is None:
        metrics["p7"] = {"executor_read": False}
        return None
    code = EXECUTOR_MODE_ENV in src
    lanes = (allow or {}).get("lanes") if isinstance(allow, dict) else None
    if isinstance(lanes, list):
        lanes = {str(x.get("lane_id")): x for x in lanes if isinstance(x, dict)}
    lanes = lanes if isinstance(lanes, dict) else {}
    props = _systemctl_props(probe, cfg.get("executor_unit", EXECUTOR_UNIT), ["Environment"])
    mode = None
    if props is not None:
        for _k, v in props:
            for tok in v.split():
                if tok.startswith(EXECUTOR_MODE_ENV + "="):
                    mode = tok.split("=", 1)[1].strip("'\"")
    effective_global = mode or "report"
    if mode is None:
        notes.append(f"{EXECUTOR_MODE_ENV} not in the executor unit Environment= (EnvironmentFiles not read) → "
                     "code default 'report'")
    enforced = 0
    for _lid, e in lanes.items():
        if not isinstance(e, dict):
            continue
        names_ok = isinstance(e.get("env_names"), list)
        lane_mode = str(e.get("env_allowlist_mode") or "")
        if code and effective_global == "enforce" and names_ok and lane_mode != "report":
            enforced += 1
    frac = (enforced / len(lanes)) if lanes else 0.0
    metrics["p7"] = {"code_served": code, "global_mode": effective_global, "lanes": len(lanes),
                     "lanes_enforced": enforced}
    ev.append(core.evidence(f"{EXECUTOR_MODULE} + {RUN_ALLOWLIST}", code=code, mode=effective_global,
                            lanes=len(lanes), enforced=enforced))
    if not code:
        return 0.0
    if frac >= 1.0:
        return 1.0
    return CODE_STAGE_WEIGHT + (1 - CODE_STAGE_WEIGHT) * frac


def _app_role(probe: core.Probe, app: str, db: str, ev: list[dict], metrics: dict, notes: list[str]) -> Optional[float]:
    """0.3 role exists + 0.3 role is not superuser/createrole + 0.4 the n8n container connects as it."""
    role = probe.cfg("security").get("app_role", APP_ROLE)
    try:
        rows = _select_json(probe, db, (
            "SELECT coalesce(json_agg(json_build_object('rolname', rolname, 'super', rolsuper, "
            "'createrole', rolcreaterole, 'createdb', rolcreatedb)), '[]'::json) FROM pg_roles "
            "WHERE rolname NOT LIKE 'pg\\_%'")) or []
    except Exception as exc:  # noqa: BLE001
        notes.append(f"pg_roles unread: {type(exc).__name__}: {str(exc)[:120]}")
        metrics["app_role"] = {"read": False}
        return None
    r = next((x for x in rows if x.get("rolname") == role), None)
    rc, out, _ = probe.run(["docker", "inspect", app, "--format",
                            '{{range .Config.Env}}{{if eq (index (split . "=") 0) "' + DB_USER_ENV + '"}}{{.}}{{end}}{{end}}'])
    db_user = out.strip().split("=", 1)[1] if rc == 0 and out.strip().startswith(DB_USER_ENV + "=") else None
    exists = r is not None
    least = exists and not r.get("super") and not r.get("createrole")
    used = db_user == role
    metrics["app_role"] = {"role": role, "exists": exists, "least_privilege": least, "container_db_user": db_user,
                           "superusers": sorted(x["rolname"] for x in rows if x.get("super"))}
    ev.append(core.evidence(f"docker exec {db} psql SELECT pg_roles", role_exists=exists, least_privilege=least,
                            container_uses_role=used))
    return 0.3 * exists + 0.3 * least + 0.4 * used


def _compose_literal_passwords(probe: core.Probe, app: str) -> tuple[Optional[list[str]], Optional[str]]:
    """Password-like keys with a LITERAL value in the n8n compose file (names only; never the value)."""
    rc, out, _ = probe.run(["docker", "inspect", app, "--format",
                            '{{index .Config.Labels "com.docker.compose.project.config_files"}}'])
    if rc != 0 or not out.strip():
        return None, None
    path = Path(out.strip().split(",")[0])
    text = probe.text(path)
    if text is None:
        return None, path.name
    bad = []
    for line in text.splitlines():
        m = re.match(r"\s*-?\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.*)$", line)
        if not m or not PASSWORD_NAME_RE.search(m.group(1)) or m.group(1).upper().endswith("_FILE"):
            continue
        val = m.group(2).strip().strip("'\"")
        if val and "${" not in val and not val.startswith("/run/secrets"):
            bad.append(m.group(1))
    return sorted(set(bad)), path.name


def _password_out(probe: core.Probe, app: str, db: str, ev: list[dict], metrics: dict) -> Optional[float]:
    """Fraction of checks clean: each n8n container env has no password-named key (``*_FILE`` is fine);
    the compose file has no literal password value. ``.env`` files are never read."""
    containers = probe.cfg("security").get("password_containers") or [app, db]
    checks: list[bool] = []
    per: dict[str, Any] = {}
    for c in containers:
        names = _env_names(probe, c)
        if names is None:
            per[c] = None
            continue
        pw = [n for n in names if PASSWORD_NAME_RE.search(n) and not n.upper().endswith("_FILE")]
        per[c] = pw
        checks.append(not pw)
    literal, compose = _compose_literal_passwords(probe, app)
    if literal is not None:
        checks.append(not literal)
    metrics["password_out"] = {"container_password_env_names": per, "compose_file": compose,
                               "compose_literal_password_keys": literal,
                               "owner_password_dotenv": "not inspected (.env is a never-grantable secret file)"}
    ev.append(core.evidence("docker inspect <n8n containers> env NAMES", containers=len(containers),
                            clean=sum(checks), checks=len(checks)))
    if not checks:
        return None
    return sum(checks) / len(checks)


def collect_security(probe: core.Probe) -> dict:
    """8 Security — four sub-criteria, each 10 when met, ``ratio_score(value, 1)`` below; mean; cap 7.9.

      relay_env_allowlist = 1 when the relay unit is loaded and none of its EnvironmentFiles is the full
                            secrets env (suffix ``tradeai/env``); else 0.25 if the allowlist module
                            (scripts/lib/n8n_relay_env.py) is in the served code root; else 0.
      p7                  = 0 without the P7 code (``TRADEAI_EXECUTOR_ENV_ALLOWLIST`` in the served executor);
                            else 0.25 + 0.75 × (allowlisted lanes enforced / lanes), enforced = global mode
                            ``enforce`` AND ``env_names`` list AND lane mode ≠ report; all lanes enforced = 1.
      n8n_app_role        = 0.3 role exists + 0.3 not superuser/createrole + 0.4 n8n container's
                            DB_POSTGRESDB_USER is that role (pg_roles SELECT; docker inspect one key).
      password_out        = clean checks / checks: per n8n container no password-named env key (``*_FILE``
                            allowed; NAMES only) + compose file holds no literal password value.
    """
    dim, rule = "security", _rule(probe, "security")
    ev: list[dict] = []
    metrics: dict = {}
    notes: list[str] = []
    served, served_how = _served_root(probe, dim)
    metrics["code_root"] = served_how
    app, db = _containers(probe, dim)
    parts = [("relay_env_allowlist", _met_score(_relay_env(probe, served, ev, metrics))),
             ("p7_executor_env_allowlist", _met_score(_p7(probe, served, ev, metrics, notes))),
             ("n8n_app_role", _met_score(_app_role(probe, app, db, ev, metrics, notes))),
             ("password_out_of_env", _met_score(_password_out(probe, app, db, ev, metrics)))]
    return _combine(dim, rule, parts, metrics, ev, notes)


# ================================================================================================
# 11 CI signal
# ================================================================================================

def _repo_slug(probe: core.Probe) -> Optional[str]:
    """owner/repo: config ``repo`` → env GH_REPO → origin url parsed from the checkout's git config text."""
    c = probe.cfg("ci_signal").get("repo") or probe.env.get("GH_REPO")
    if c:
        return str(c)
    gitp = probe.proj / ".git"
    common = gitp
    if gitp.is_file():
        t = probe.text(gitp) or ""
        m = re.search(r"gitdir:\s*(.+)", t)
        if not m:
            return None
        gd = Path(m.group(1).strip())
        gd = gd if gd.is_absolute() else (probe.proj / gd)
        cd = (probe.text(gd / "commondir") or "").strip()
        common = (gd / cd).resolve() if cd else gd
    cfg_text = probe.text(common / "config") or ""
    m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', cfg_text, re.S)
    if not m:
        return None
    m2 = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", m.group(1))
    return f"{m2.group(1)}/{m2.group(2)}" if m2 else None


def _discover_workflows(probe: core.Probe) -> tuple[Optional[str], Optional[str]]:
    cfg = probe.cfg("ci_signal")
    nightly, gate = cfg.get("nightly_workflow"), cfg.get("ci_gate_workflow")
    wdir = probe.proj / ".github" / "workflows"
    files = sorted(list(wdir.glob("*.yml")) + list(wdir.glob("*.yaml"))) if wdir.is_dir() else []
    for f in files:
        t = probe.text(f) or ""
        if not nightly and re.search(r"^\s*schedule:\s*$", t, re.M) and re.search(r"cron:", t):
            nightly = f.name
        if not gate and re.search(rf"^\s{{2}}{re.escape(CI_GATE_JOB)}:\s*$", t, re.M):
            gate = f.name
    return nightly, gate


def _runs(probe: core.Probe, slug: str, workflow: str, extra: list[str]) -> Optional[list[dict]]:
    rc, out, _ = probe.run(["gh", "run", "list", "-R", slug, "--workflow", workflow, "--branch", "main", *extra,
                            "--json", "conclusion,status,createdAt,headSha,event,databaseId", "-L", "20"])
    if rc != 0:
        return None
    try:
        rows = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    return sorted([r for r in rows if isinstance(r, dict)], key=lambda r: str(r.get("createdAt") or ""), reverse=True)


def collect_ci_signal(probe: core.Probe) -> dict:
    """11 CI signal — nightly green and ci-gate green on main (gh read-only).

      nightly = latest COMPLETED scheduled run of the nightly workflow on main is ``success`` and ≤
                nightly_max_age_hours old. Met → 8 + 2 × min(green streak, nightly_streak_top)/top
                (10 = a week of green nights); missed → 0.
      ci_gate = latest COMPLETED non-pull_request run on main of the workflow that defines the ``ci-gate``
                job is ``success`` and ≤ ci_gate_max_age_hours old → 10; else 0 (no main run = 0).
    Dimension = mean; capped 7.9 unless both are met.
    """
    dim, rule = "ci_signal", _rule(probe, "ci_signal")
    cfg = probe.cfg(dim)
    ev: list[dict] = []
    metrics: dict = {}
    notes: list[str] = []
    slug = _repo_slug(probe)
    nightly_wf, gate_wf = _discover_workflows(probe)
    metrics.update(repo=slug, nightly_workflow=nightly_wf, ci_gate_workflow=gate_wf)
    if not slug:
        return core.unverified(dim, rule, "GitHub repo slug unknown (config ci_signal.repo / GH_REPO / origin)",
                               metrics=metrics)

    nightly_score: Optional[float] = None
    nightly_met = False
    if nightly_wf:
        runs = _runs(probe, slug, nightly_wf, ["--event", "schedule"])
        if runs is None:
            notes.append("nightly runs unread (gh failed)")
        else:
            done = [r for r in runs if r.get("status") == "completed"]
            latest = done[0] if done else None
            age = _age_h(probe, latest.get("createdAt")) if latest else None
            streak = 0
            for r in done:
                if r.get("conclusion") != "success":
                    break
                streak += 1
            max_age = float(cfg.get("nightly_max_age_hours", NIGHTLY_MAX_AGE_H))
            nightly_met = bool(latest and latest.get("conclusion") == "success" and age is not None and age <= max_age)
            top = int(cfg.get("nightly_streak_top", NIGHTLY_STREAK_TOP))
            nightly_score = (8.0 + 2.0 * min(streak, top) / top) if nightly_met else 0.0
            metrics["nightly"] = {"latest_conclusion": (latest or {}).get("conclusion"), "latest_age_h": age,
                                  "latest_sha": str((latest or {}).get("headSha") or "")[:12] or None,
                                  "green_streak": streak, "completed_runs": len(done)}
            ev.append(core.evidence(f"gh run list --workflow {nightly_wf} --branch main --event schedule",
                                    latest=(latest or {}).get("conclusion"), age_h=age, streak=streak))
    else:
        notes.append("no scheduled workflow found in .github/workflows")

    gate_score: Optional[float] = None
    if gate_wf:
        runs = _runs(probe, slug, gate_wf, [])
        if runs is None:
            notes.append("ci-gate runs unread (gh failed)")
        else:
            main_runs = [r for r in runs if r.get("event") != "pull_request"]
            done = [r for r in main_runs if r.get("status") == "completed"]
            latest = done[0] if done else None
            age = _age_h(probe, latest.get("createdAt")) if latest else None
            max_age = float(cfg.get("ci_gate_max_age_hours", CI_GATE_MAX_AGE_H))
            met = bool(latest and latest.get("conclusion") == "success" and age is not None and age <= max_age)
            gate_score = 10.0 if met else 0.0
            metrics["ci_gate"] = {"main_runs": len(main_runs), "latest_conclusion": (latest or {}).get("conclusion"),
                                  "latest_event": (latest or {}).get("event"), "latest_age_h": age,
                                  "latest_sha": str((latest or {}).get("headSha") or "")[:12] or None}
            if not main_runs:
                notes.append(f"{gate_wf} has no run on main (pull_request runs only)")
            ev.append(core.evidence(f"gh run list --workflow {gate_wf} --branch main", main_runs=len(main_runs),
                                    latest=(latest or {}).get("conclusion"), age_h=age))
    else:
        notes.append(f"no workflow defines a `{CI_GATE_JOB}` job")

    parts = [("nightly_green", nightly_score), ("ci_gate_green_on_main", gate_score)]
    score, status, extra = core.mean_score(parts)
    gate_pass = nightly_met and gate_score == 10.0
    if not gate_pass:
        score = min(score, GATE_CAP)
    metrics["sub_scores"] = {n: (None if v is None else round(v, 2)) for n, v in parts}
    if status == core.UNVERIFIED:
        return core.unverified(dim, rule, "; ".join(extra + notes), metrics=metrics, evidence_list=ev)
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=extra + notes)


# ================================================================================================
# 12 docs synced
# ================================================================================================

def _expand(probe: core.Probe, patterns: list[str]) -> list[str]:
    out: list[str] = []
    for p in patterns:
        if any(ch in p for ch in "*?["):
            out += sorted(str(x.relative_to(probe.proj)) for x in probe.proj.glob(p) if x.is_file())
        else:
            out.append(p)
    return list(dict.fromkeys(out))


def _dangling(probe: core.Probe, text: str) -> list[str]:
    bad = set()
    for m in _PATH_REF_RE.finditer(text):
        p = m.group(1).rstrip(".")
        if fnmatch.fnmatch(p, "*[*?<>{}$]*") or "…" in p:
            continue
        if not (probe.proj / p).exists():
            bad.add(p)
    return sorted(bad)


def collect_docs_synced(probe: core.Probe) -> dict:
    """12 Docs synced — drift findings across AGENTS.md, the n8n ADR and the runbooks (read in-process).

    Checks (each finding counts 1):
      agents_policy_state  scripts/check_agents_policy_state.check(AGENTS.md, on_main=True) errors.
      stale_proposed       ADR/runbook text "X.Y.Z PROPOSED" where the AGENTS.md history row for X.Y.Z is ACTIVE.
      dangling_refs        backticked repo paths (scripts/ config/ docs/ tests/ bin/ .github/ infra/) in any doc
                           in scope that do not exist in the checkout.
      runbook_units        each unit in the deploy script's TRADEAI_CURRENT_BOUND_UNITS default that a
                           deploy/rollback runbook does not mention.
    Score: 0 findings with every check run → 10; else min(7.9, 8 × (1 − findings / findings_zero_at)).
    A check that cannot run (doc missing) is UNVERIFIED for that check → dimension PARTIAL, gate fails.
    """
    dim, rule = "docs_synced", _rule(probe, "docs_synced")
    cfg = probe.cfg(dim)
    ev: list[dict] = []
    notes: list[str] = []
    findings: dict[str, list[str]] = {}
    ran: dict[str, bool] = {}

    agents_rel = cfg.get("agents_path", DOCS_AGENTS)
    agents = probe.text(probe.proj / agents_rel)
    rows: list[dict] = []
    if agents is None:
        ran["agents_policy_state"] = False
    else:
        try:
            aps = _load_module("agents_state", "scripts/check_agents_policy_state.py")
            findings["agents_policy_state"] = list(aps.check(agents, on_main=True))
            rows = aps.version_rows(agents)
            ran["agents_policy_state"] = True
        except Exception as exc:  # noqa: BLE001
            notes.append(f"agents policy-state check failed: {type(exc).__name__}")
            ran["agents_policy_state"] = False
    active_versions = {r["version"] for r in rows if r["status"].upper().startswith("ACTIVE")}

    adr = _expand(probe, list(cfg.get("adr_paths") or DOCS_ADR))
    runbooks = _expand(probe, list(cfg.get("runbook_paths") or DOCS_RUNBOOKS))
    scope = [agents_rel] + adr + runbooks
    texts: dict[str, Optional[str]] = {p: (agents if p == agents_rel else probe.text(probe.proj / p)) for p in scope}
    missing_docs = [p for p, t in texts.items() if t is None]

    stale: list[str] = []
    if rows:
        for p in adr + runbooks:
            t = texts.get(p)
            if t is None:
                continue
            for v in sorted({m.group(1) for m in _PROPOSED_RE.finditer(t)}):
                if v in active_versions:
                    stale.append(f"{p}: says {v} PROPOSED (AGENTS.md row ACTIVE)")
        ran["stale_proposed"] = True
    else:
        ran["stale_proposed"] = False
    findings["stale_proposed"] = stale

    dangling: list[str] = []
    for p, t in texts.items():
        if t is not None:
            dangling += [f"{p} → {x}" for x in _dangling(probe, t)]
    findings["dangling_refs"] = dangling
    ran["dangling_refs"] = any(t is not None for t in texts.values())

    deploy = probe.text(probe.proj / cfg.get("deploy_script", DEPLOY_SCRIPT))
    unit_rb = list(cfg.get("unit_runbooks") or UNIT_RUNBOOKS)
    m = _BOUND_UNITS_RE.search(deploy or "")
    units_missing: list[str] = []
    if m and all(texts.get(r, probe.text(probe.proj / r)) is not None for r in unit_rb):
        units = m.group(1).split()
        for r in unit_rb:
            t = texts.get(r) or probe.text(probe.proj / r) or ""
            units_missing += [f"{r}: {u}" for u in units if u not in t and u.replace(".service", "") not in t]
        ran["runbook_units"] = True
    else:
        ran["runbook_units"] = False
        notes.append("runbook unit check not run (deploy script bound-unit default or a runbook unreadable)")
    findings["runbook_units"] = units_missing

    total = sum(len(v) for v in findings.values())
    zero_at = float(cfg.get("findings_zero_at", DOCS_FINDINGS_ZERO_AT))
    all_ran = all(ran.values())
    metrics = {"drift_findings": total, "by_check": {k: len(v) for k, v in findings.items()},
               "checks_ran": ran, "docs_in_scope": len(scope), "docs_missing": missing_docs,
               "examples": {k: v[:5] for k, v in findings.items() if v}}
    for k, v in findings.items():
        ev.append(core.evidence(f"docs drift: {k}", findings=len(v), ran=ran.get(k)))
    if not any(ran.values()):
        return core.unverified(dim, rule, "no docs drift check could run", metrics=metrics, evidence_list=ev)
    if missing_docs:
        notes.append(f"docs in scope not found: {', '.join(missing_docs[:5])}")
    gate_pass = total == 0 and all_ran
    score = 10.0 if gate_pass else min(GATE_CAP, 8.0 * max(0.0, 1.0 - total / zero_at))
    status = core.VERIFIED if all_ran else core.PARTIAL
    if not all_ran:
        notes.append("UNVERIFIED checks: " + ", ".join(k for k, v in ran.items() if not v))
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=notes)


COLLECTORS = {
    "governance": collect_governance,
    "security": collect_security,
    "ci_signal": collect_ci_signal,
    "docs_synced": collect_docs_synced,
}

__all__ = ["COLLECTORS", "collect_governance", "collect_security", "collect_ci_signal", "collect_docs_synced"]

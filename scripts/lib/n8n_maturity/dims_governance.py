"""Governance, security, CI and docs dimensions (7, 8, 11, 12) of the n8n platform maturity scorer.

Every number is read through ``core.Probe`` (read-only by construction). Missing evidence scores 0 and
is UNVERIFIED (a whole dimension) or PARTIAL (one sub-criterion); nothing is assumed.

Every threshold, weight, unit/container name and doc path comes from config/n8n_platform_maturity.json
(top-level ``gate_score`` / ``gate_cap`` / ``window_hours`` and ``dimensions.<id>.*``); a missing key raises
``core.ConfigError`` before any evidence is read (the orchestrator marks the dimension UNVERIFIED). There
are no in-code fallbacks.

Scoring convention shared by the four collectors (see each docstring for the sub-criteria):

* a sub-criterion that MEETS its gate scores 10;
* a sub-criterion below its gate scores ``core.ratio_score(fraction, 1.0, gate_score=gate_score)`` —
  linear 0 → gate_score, so it is always < gate_score unless the fraction is exactly 1;
* a sub-criterion whose evidence could not be read — or whose denominator is empty (0 active workflows,
  0 allowlisted lanes, no run on main, no doc in scope) — is ``None`` (scored 0, dimension PARTIAL);
  an empty input never passes;
* dimension score = ``core.mean_score`` of the sub-scores; when any sub-criterion misses its gate the
  dimension is capped at ``gate_cap``, so "gate met" ⇔ score ≥ gate_score.

Secrets: environment VALUES are never read into results. Container env is inspected with a docker
template that prints names only; the systemd ``Environment`` property is parsed for one non-secret
key (``executor_mode_env``) and everything else is discarded; ``.env`` files are never opened
(AGENTS never-grantable ``secret`` scope). psql runs only through ``core.psql_argv`` (read-only
transaction, one SELECT that passes ``core.is_safe_sql``).
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

# Pinned by core.DOCKER_INSPECT_TEMPLATES (the only single-key env template the allowlist accepts).
DB_USER_ENV = "DB_POSTGRESDB_USER"
_ENV_NAMES_TEMPLATE = '{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}'
_DB_USER_TEMPLATE = '{{range .Config.Env}}{{if eq (index (split . "=") 0) "' + DB_USER_ENV + '"}}{{.}}{{end}}{{end}}'
_COMPOSE_TEMPLATE = '{{index .Config.Labels "com.docker.compose.project.config_files"}}'

PASSWORD_NAME_RE = re.compile(r"(^|_)(PASSWORD|PASSWD|PASS|PWD)(_|$)", re.IGNORECASE)
_PATH_REF_RE = re.compile(r"`((?:scripts|config|docs|tests|bin|\.github|infra)/[A-Za-z0-9_./-]+?)(?::\d+(?:-\d+)?)?`")
_PROPOSED_RE = re.compile(r"\b(\d+\.\d+\.\d+)\s*\(?\s*PROPOSED\b")
_BOUND_UNITS_RE = re.compile(r"TRADEAI_CURRENT_BOUND_UNITS:-([^}\"]*)")

PG_ROLES_SQL = ("SELECT coalesce(json_agg(json_build_object('rolname', rolname, 'super', rolsuper, "
                "'createrole', rolcreaterole, 'createdb', rolcreatedb)), '[]'::json) FROM pg_roles "
                "WHERE left(rolname, 3) <> 'pg_'")


# ================================================================================================
# shared helpers
# ================================================================================================

def _gate(probe: core.Probe) -> tuple[float, float]:
    """(gate_score, gate_cap) from the top-level config — required."""
    return float(core.need_top(probe.config, "gate_score")), float(core.need_top(probe.config, "gate_cap"))


def _met_score(fraction: Optional[float], gate_score: float) -> Optional[float]:
    """10 when the gate fraction is fully met, linear 0→gate_score below, None when unread/undefined."""
    if fraction is None:
        return None
    return 10.0 if fraction >= 1.0 else core.ratio_score(max(0.0, fraction), 1.0, gate_score=gate_score)


def _combine(probe: core.Probe, dim_id: str, rule: str, parts: list[tuple[str, Optional[float]]], metrics: dict,
             ev: list[dict], notes: list[str]) -> dict:
    _gs, _cap = _gate(probe)
    score, status, extra = core.mean_score(parts)
    gate_pass = all(v is not None and v >= 10.0 for _, v in parts)
    score = core.cap_on_fail(probe, score, gate_pass)
    metrics = {**metrics, "sub_scores": {n: (None if v is None else round(v, 2)) for n, v in parts}}
    if status == core.UNVERIFIED:
        return core.unverified(dim_id, rule, "; ".join(extra + notes) or "no evidence", metrics=metrics,
                               evidence_list=ev)
    return core.dim_result(dim_id, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=extra + notes)


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


def _db_target(probe: core.Probe, dim_id: str) -> dict:
    """n8n containers + DB login from config (required keys)."""
    return {"app": str(probe.need(dim_id, "n8n_container")), "db": str(probe.need(dim_id, "n8n_db_container")),
            "user": str(probe.need(dim_id, "n8n_db_user")), "name": str(probe.need(dim_id, "n8n_db_name"))}


def _select_json(probe: core.Probe, tgt: dict, sql: str) -> Any:
    """One SELECT via ``core.psql_argv`` (docker exec, read-only transaction). Raises on failure."""
    if not core.is_safe_sql(sql):
        raise PermissionError("SQL refused by core.is_safe_sql")
    rc, out, err = probe.run(core.psql_argv(sql, user=tgt["user"], db=tgt["name"], container=tgt["db"]))
    if rc != 0:
        raise RuntimeError(f"psql rc={rc}: {(err or '').strip()[:160]}")
    text = (out or "").strip()
    if not text:
        raise RuntimeError("psql returned no output")
    return json.loads(text)


def _env_names(probe: core.Probe, container: str) -> Optional[list[str]]:
    """Container env NAMES only (docker template splits on '='; values never leave docker). Empty → None."""
    rc, out, _ = probe.run(["docker", "inspect", container, "--format", _ENV_NAMES_TEMPLATE])
    if rc != 0:
        return None
    names = sorted({ln.strip() for ln in out.splitlines() if ln.strip() and "=" not in ln})
    return names or None


def _systemctl_props(probe: core.Probe, unit: str, props: list[str]) -> Optional[list[tuple[str, str]]]:
    argv = ["systemctl", "--user", "show", unit]
    for p in props:
        argv += ["-p", p]
    rc, out, _ = probe.run(argv)
    if rc != 0:
        return None
    return [tuple(line.split("=", 1)) for line in out.splitlines() if "=" in line]  # type: ignore[misc]


def _unit_env_value(probe: core.Probe, unit: str, name: str) -> Optional[str]:
    """The value of ONE named ``Environment=`` assignment in a user unit's files. systemd's ``Environment``
    property (every value) is never requested: the unit file + drop-in PATHS are, and only ``name=`` is
    extracted from their ``Environment=`` lines (later files override earlier ones, as systemd does)."""
    props = _systemctl_props(probe, unit, ["FragmentPath", "DropInPaths"])
    if props is None:
        return None
    paths: list[str] = []
    for k, v in props:
        if k in ("FragmentPath", "DropInPaths"):
            paths.extend(p for p in v.split() if p.startswith("/"))
    pat = re.compile(r"""(?:^|\s|["'])""" + re.escape(name) + r"""=([^\s"']*)""")
    value: Optional[str] = None
    for path in paths:
        text = probe.text(Path(path))
        for line in (text or "").splitlines():
            line = line.strip()
            if not line.startswith("Environment="):
                continue
            m = pat.search(line[len("Environment="):])
            if m:
                value = m.group(1)
    return value


def _served_root(probe: core.Probe, dim_id: str) -> tuple[Path, str]:
    c = probe.cfg(dim_id).get("served_code_root")
    if c:
        return Path(c), "config"
    served = probe.root.parent / "portfolio-server" / "CURRENT"
    if served.exists():
        return served, "served CURRENT"
    return probe.proj, "repo checkout (served CURRENT absent)"


def _weights(raw: Any, keys: tuple[str, ...], where: str) -> dict[str, float]:
    if not isinstance(raw, dict) or any(k not in raw for k in keys):
        raise core.ConfigError(f"config {where} must define {', '.join(keys)}")
    w = {k: float(raw[k]) for k in keys}
    total = sum(w.values())
    if total <= 0:
        raise core.ConfigError(f"config {where} weights sum to 0")
    return {k: v / total for k, v in w.items()}


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


def _grant_coverage(probe: core.Probe, tgt: dict, gcfg: dict, ev: list[dict], metrics: dict,
                    notes: list[str]) -> tuple[Optional[float], list[dict]]:
    """Fraction of ACTIVE workflows whose current activation is GRANTED (P16 checker logic, by id).
    0 active workflows → None (nothing to prove; never a vacuous 100%)."""
    try:
        p16 = _load_module("p16", "scripts/check_n8n_activation_grants.py")
        inv = p16.inv
        evidence = {
            "workflows": _select_json(probe, tgt, inv.WORKFLOW_LIST_SQL) or [],
            "publish_history": _select_json(probe, tgt, inv.PUBLISH_HISTORY_SQL) or [],
            "published_versions": _select_json(probe, tgt, inv.PUBLISHED_VERSION_SQL) or [],
            "version_history": _select_json(probe, tgt, inv.VERSION_HISTORY_SQL) or [],
        }
    except Exception as exc:  # noqa: BLE001 — unread evidence, not a clean result
        notes.append(f"active workflows unread: {type(exc).__name__}: {str(exc)[:160]}")
        return None, []
    workflows = list(evidence["workflows"])
    active = [w for w in workflows if w.get("active")]
    ev.append(core.evidence(f"docker exec {tgt['db']} psql SELECT workflow_entity/publish history",
                            workflows=len(workflows), active=len(active)))
    metrics.update(active_workflows=len(active))
    if not active:
        notes.append("no active n8n workflows: grant coverage undefined (UNVERIFIED, not a vacuous 100%)")
        return None, workflows
    log = _guard_audit_log(probe)
    try:
        grants = p16.load_grants(log)
    except OSError as exc:
        notes.append(f"guard audit log unread: {type(exc).__name__}")
        return None, workflows
    ev.append(core.evidence(str(log.name), grants_issued=len(grants), via="guard audit jsonl (what `guard log` reads)"))
    epoch = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
    rows = p16.reconcile(p16.activation_events(evidence, since=epoch), grants, tiers=gcfg["tiers"],
                         skew_s=gcfg["skew_s"])
    ok_status = {"GRANTED"} | ({"NAME_ONLY_GRANT"} if gcfg["name_only_ok"] else set())
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
    metrics.update(active_granted=granted, activation_status_counts=counts,
                   ungranted_ids=sorted(w for w, s in per.items() if s not in ok_status)[:20])
    return granted / len(active), workflows


def _check_scheduled(probe: core.Probe, spec: dict, gcfg: dict, crontab: Optional[str], timers: Optional[str],
                     workflows: list[dict], key: str, ev: list[dict], metrics: dict) -> tuple[Optional[float], str]:
    """P16/P18: weighted scheduled + receipt fresh + alerting (fresh receipt with ``fanin_wired`` true).

    A receipt that is stale, future-dated or unparseable is neither fresh nor alerting; a receipt alone
    (unscheduled) earns only the fresh share."""
    script, lane = str(spec["script"]), str(spec["lane"])
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
    rel = str(spec["receipt"])
    rec = probe.json(probe.root / rel)
    rec = rec if isinstance(rec, dict) else None
    age = _age_h(probe, rec.get("as_of")) if rec else None
    fresh = age is not None and -gcfg["future_skew_h"] <= age <= gcfg["receipt_max_age_h"]
    alerting = bool(fresh and rec and rec.get("fanin_wired") is True)
    metrics[key] = {"scheduled_by": how, "shadow_only": shadow and not how, "receipt_age_h": age,
                    "receipt_fresh": fresh, "fanin_wired": rec.get("fanin_wired") if rec else None,
                    "alerting": alerting}
    ev.append(core.evidence(rel, age_h=age, scheduled_by=",".join(how) or "none", alerting=alerting))
    if not sched_known and rec is None:
        return None, f"{key}: schedule sources and receipt unread"
    w = gcfg["weights"]
    return w["scheduled"] * bool(how) + w["receipt_fresh"] * fresh + w["alerting"] * alerting, ""


def _guard_hook(probe: core.Probe, gcfg: dict, ev: list[dict], metrics: dict) -> Optional[float]:
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
        if not isinstance(d, dict):
            continue
        read_any = True
        for entry in ((d.get("hooks") or {}).get("PreToolUse") or []):
            for h in (entry or {}).get("hooks") or []:
                cmd = str((h or {}).get("command") or "")
                if gcfg["hook_token"] in cmd:
                    scope = "repo" if probe.proj in p.parents else "user"
                    installed.append(f"{scope}:{p.name}")
                    m = re.search(r"TRADEAI_AGENTS_GUARD_MODE=(\w+)", cmd)
                    mode = m.group(1) if m else mode
    rows = probe.rows(probe.root / gcfg["hook_log"], since=probe.since(gcfg["window_h"]))
    metrics["guard_hook"] = {"installed_in": installed, "mode": mode,
                             "decisions_in_window": None if rows is None else len(rows),
                             "window_hours": gcfg["window_h"]}
    ev.append(core.evidence("~/.claude/settings*.json hooks.PreToolUse", installed=bool(installed), mode=mode))
    if not read_any:
        return None
    return 1.0 if installed else 0.0


def _governance_cfg(probe: core.Probe) -> dict:
    dim = "governance"
    return {
        "tiers": tuple(probe.need(dim, "grant_tiers")),
        "skew_s": int(probe.need(dim, "grant_skew_s")),
        "name_only_ok": bool(probe.need(dim, "count_name_only_as_granted")),
        "receipt_max_age_h": float(probe.need(dim, "receipt_max_age_hours")),
        "future_skew_h": float(probe.need(dim, "receipt_future_skew_s")) / 3600.0,
        "weights": _weights(probe.need(dim, "check_weights"), ("scheduled", "receipt_fresh", "alerting"),
                            "dimensions.governance.check_weights"),
        "p16": dict(probe.need(dim, "p16")),
        "p18": dict(probe.need(dim, "p18")),
        "hook_token": str(probe.need(dim, "guard_hook_token")),
        "hook_log": str(probe.need(dim, "guard_hook_log")),
        "window_h": probe.window_hours(dim),
    }


def collect_governance(probe: core.Probe) -> dict:
    """7 Governance enforced.

    Sub-criteria (each 10 when met, ``ratio_score(fraction, 1)`` below; mean; capped at gate_cap on a miss):
      grants     = active n8n workflows whose current activation is GRANTED by a guard grant naming the
                   workflow id in an activation tier / active workflows (P16 checker reconcile logic, n8n DB
                   via psql_argv SELECT, guard audit jsonl). Gate 100%. 0 active → UNVERIFIED sub-criterion.
      p16, p18   = check_weights.scheduled × scheduled (uncommented crontab line running the checker, a user
                   timer naming the lane, or an ACTIVE non-shadow n8n workflow named the lane)
                   + check_weights.receipt_fresh × receipt ``as_of`` within receipt_max_age_hours
                   + check_weights.alerting × fresh receipt with ``fanin_wired`` true. Gate = all three.
      guard_hook = PreToolUse hook command containing guard_hook_token in a Claude settings file.
    """
    dim = "governance"
    rule = str(probe.need(dim, "gate_rule"))
    gs, _cap = _gate(probe)
    gcfg = _governance_cfg(probe)
    tgt = _db_target(probe, dim)
    ev: list[dict] = []
    metrics: dict = {}
    notes: list[str] = []
    grants_frac, workflows = _grant_coverage(probe, tgt, gcfg, ev, metrics, notes)
    crontab = probe.crontab()
    rc, timers, _ = probe.run(["systemctl", "--user", "list-timers", "--all", "--no-pager"])
    timers_txt: Optional[str] = timers if rc == 0 else None
    p16, n16 = _check_scheduled(probe, gcfg["p16"], gcfg, crontab, timers_txt, workflows, "p16", ev, metrics)
    p18, n18 = _check_scheduled(probe, gcfg["p18"], gcfg, crontab, timers_txt, workflows, "p18", ev, metrics)
    notes += [n for n in (n16, n18) if n]
    hook = _guard_hook(probe, gcfg, ev, metrics)
    parts = [("grants", _met_score(grants_frac, gs)), ("p16_scheduled_alerting", _met_score(p16, gs)),
             ("p18_scheduled_alerting", _met_score(p18, gs)), ("guard_hook_installed", _met_score(hook, gs))]
    return _combine(probe, dim, rule, parts, metrics, ev, notes)


# ================================================================================================
# 8 security
# ================================================================================================

def _relay_env(probe: core.Probe, scfg: dict, served: Path, ev: list[dict], metrics: dict) -> Optional[float]:
    """Relay unit does not load the full secrets env; the relay env allowlist module is served."""
    unit = scfg["relay_unit"]
    props = _systemctl_props(probe, unit, ["EnvironmentFiles", "LoadState"])
    code = (served / scfg["relay_allowlist_module"]).exists()
    if props is None:
        metrics["relay_env"] = {"unit_read": False, "allowlist_module_served": code}
        return None
    files = [v.split(" (")[0] for k, v in props if k == "EnvironmentFiles"]
    load = next((v for k, v in props if k == "LoadState"), None)
    if load is None:
        metrics["relay_env"] = {"unit_read": False, "allowlist_module_served": code}
        return None
    full = [f for f in files if any(f.endswith(s) for s in scfg["full_env_files"])]
    live = load == "loaded" and not full
    metrics["relay_env"] = {"load_state": load, "env_files": [Path(f).name for f in files],
                            "loads_full_secrets_env": bool(full), "allowlist_module_served": code}
    ev.append(core.evidence(f"systemctl --user show {unit} -p EnvironmentFiles", full_env=bool(full), load=load))
    return 1.0 if live else (scfg["code_stage_weight"] if code else 0.0)


def _p7(probe: core.Probe, scfg: dict, served: Path, ev: list[dict], metrics: dict,
        notes: list[str]) -> Optional[float]:
    """P7 per-lane executor env allowlist: code served, then enforced per allowlisted lane.
    0 allowlisted lanes (or the allowlist unread) → None: nothing to enforce is not 'all enforced'."""
    mode_env = scfg["executor_mode_env"]
    src = probe.text(served / scfg["executor_module"])
    if src is None:
        metrics["p7"] = {"executor_read": False}
        return None
    code = mode_env in src
    if not code:
        metrics["p7"] = {"code_served": False}
        ev.append(core.evidence(scfg["executor_module"], code=False))
        return 0.0
    allow = probe.json(served / scfg["run_allowlist"])
    lanes = allow.get("lanes") if isinstance(allow, dict) else None
    if isinstance(lanes, list):
        lanes = {str(x.get("lane_id")): x for x in lanes if isinstance(x, dict)}
    lanes = lanes if isinstance(lanes, dict) else {}
    mode = _unit_env_value(probe, scfg["executor_unit"], mode_env)
    if mode is None:
        notes.append(f"{mode_env} not in the executor unit file Environment= lines (EnvironmentFiles not read) → "
                     "not counted as enforce")
    enforced = sum(1 for e in lanes.values() if isinstance(e, dict) and mode == "enforce"
                   and isinstance(e.get("env_names"), list) and str(e.get("env_allowlist_mode") or "") != "report")
    metrics["p7"] = {"code_served": True, "global_mode": mode, "lanes": len(lanes), "lanes_enforced": enforced}
    ev.append(core.evidence(f"{scfg['executor_module']} + {scfg['run_allowlist']}", code=True, mode=mode,
                            lanes=len(lanes), enforced=enforced))
    if not lanes:
        notes.append("p7: no allowlisted lanes read — enforcement coverage undefined (UNVERIFIED)")
        return None
    frac = enforced / len(lanes)
    if frac >= 1.0:
        return 1.0
    w = scfg["code_stage_weight"]
    return w + (1 - w) * frac


def _app_role(probe: core.Probe, scfg: dict, tgt: dict, ev: list[dict], metrics: dict,
              notes: list[str]) -> Optional[float]:
    """Weighted: role exists + role is not superuser/createrole + the n8n container connects as it.
    An empty pg_roles read or an unread container DB user → None (never a clean pass)."""
    role = scfg["app_role"]
    try:
        rows = _select_json(probe, tgt, PG_ROLES_SQL) or []
    except Exception as exc:  # noqa: BLE001
        notes.append(f"pg_roles unread: {type(exc).__name__}: {str(exc)[:120]}")
        metrics["app_role"] = {"read": False}
        return None
    if not rows:
        notes.append("pg_roles returned no roles (unread)")
        metrics["app_role"] = {"read": False}
        return None
    r = next((x for x in rows if x.get("rolname") == role), None)
    rc, out, _ = probe.run(["docker", "inspect", tgt["app"], "--format", _DB_USER_TEMPLATE])
    db_user = (out.strip().split("=", 1)[1].strip() or None) if rc == 0 and out.strip().startswith(DB_USER_ENV + "=") else None
    exists = r is not None
    least = bool(exists and not r.get("super") and not r.get("createrole"))
    used = db_user == role
    metrics["app_role"] = {"role": role, "exists": exists, "least_privilege": least, "container_db_user": db_user,
                           "superusers": sorted(x["rolname"] for x in rows if x.get("super"))}
    ev.append(core.evidence(f"docker exec {tgt['db']} psql SELECT pg_roles", role_exists=exists,
                            least_privilege=least, container_uses_role=used))
    if db_user is None:
        notes.append(f"n8n container {DB_USER_ENV} unread")
        return None
    w = scfg["app_role_weights"]
    return w["exists"] * exists + w["least_privilege"] * least + w["container_uses_role"] * used


def _compose_literal_passwords(probe: core.Probe, app: str) -> tuple[Optional[list[str]], Optional[str]]:
    """Password-like keys with a LITERAL value in the n8n compose file (names only; never the value)."""
    rc, out, _ = probe.run(["docker", "inspect", app, "--format", _COMPOSE_TEMPLATE])
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


def _password_out(probe: core.Probe, tgt: dict, ev: list[dict], metrics: dict, notes: list[str]) -> Optional[float]:
    """Fraction of checks clean: each n8n container env has no password-named key (``*_FILE`` is fine);
    the compose file has no literal password value. ``.env`` files are never read. Any unread check →
    None (a partial read is not a clean pass)."""
    containers = probe.cfg("security").get("password_containers") or [tgt["app"], tgt["db"]]
    checks: list[bool] = []
    per: dict[str, Any] = {}
    unread: list[str] = []
    for c in containers:
        names = _env_names(probe, c)
        if names is None:
            per[c] = None
            unread.append(f"env names of {c}")
            continue
        pw = [n for n in names if PASSWORD_NAME_RE.search(n) and not n.upper().endswith("_FILE")]
        per[c] = pw
        checks.append(not pw)
    literal, compose = _compose_literal_passwords(probe, tgt["app"])
    if literal is None:
        unread.append("compose file")
    else:
        checks.append(not literal)
    metrics["password_out"] = {"container_password_env_names": per, "compose_file": compose,
                               "compose_literal_password_keys": literal, "unread": unread,
                               "owner_password_dotenv": "not inspected (.env is a never-grantable secret file)"}
    ev.append(core.evidence("docker inspect <n8n containers> env NAMES", containers=len(containers),
                            clean=sum(checks), checks=len(checks)))
    if unread:
        notes.append("password_out unread: " + ", ".join(unread))
        if all(checks) or not checks:
            return None
    return sum(checks) / len(checks)


def _security_cfg(probe: core.Probe) -> dict:
    dim = "security"
    return {
        "relay_unit": str(probe.need(dim, "relay_unit")),
        "executor_unit": str(probe.need(dim, "executor_unit")),
        "relay_allowlist_module": str(probe.need(dim, "relay_allowlist_module")),
        "executor_module": str(probe.need(dim, "executor_module")),
        "executor_mode_env": str(probe.need(dim, "executor_mode_env")),
        "run_allowlist": str(probe.need(dim, "run_allowlist")),
        "full_env_files": tuple(probe.need(dim, "full_env_files")),
        "app_role": str(probe.need(dim, "app_role")),
        "code_stage_weight": float(probe.need(dim, "code_stage_weight")),
        "app_role_weights": _weights(probe.need(dim, "app_role_weights"),
                                     ("exists", "least_privilege", "container_uses_role"),
                                     "dimensions.security.app_role_weights"),
    }


def collect_security(probe: core.Probe) -> dict:
    """8 Security — four sub-criteria, each 10 when met, ``ratio_score(value, 1)`` below; mean; cap gate_cap.

      relay_env_allowlist = 1 when the relay unit is loaded and none of its EnvironmentFiles is the full
                            secrets env (full_env_files suffixes); else code_stage_weight if the allowlist
                            module is in the served code root; else 0.
      p7                  = 0 without the P7 code (executor_mode_env in the served executor); else
                            code_stage_weight + (1 − w) × (allowlisted lanes enforced / lanes), enforced =
                            global mode ``enforce`` AND ``env_names`` list AND lane mode ≠ report; 0 lanes → None.
      n8n_app_role        = app_role_weights: exists + not superuser/createrole + the n8n container's
                            DB_POSTGRESDB_USER is that role (pg_roles SELECT; docker inspect one key).
      password_out        = clean checks / checks: per n8n container no password-named env key (``*_FILE``
                            allowed; NAMES only) + compose file holds no literal password value.
    """
    dim = "security"
    rule = str(probe.need(dim, "gate_rule"))
    gs, _cap = _gate(probe)
    scfg = _security_cfg(probe)
    tgt = _db_target(probe, dim)
    ev: list[dict] = []
    metrics: dict = {}
    notes: list[str] = []
    served, served_how = _served_root(probe, dim)
    metrics["code_root"] = served_how
    parts = [("relay_env_allowlist", _met_score(_relay_env(probe, scfg, served, ev, metrics), gs)),
             ("p7_executor_env_allowlist", _met_score(_p7(probe, scfg, served, ev, metrics, notes), gs)),
             ("n8n_app_role", _met_score(_app_role(probe, scfg, tgt, ev, metrics, notes), gs)),
             ("password_out_of_env", _met_score(_password_out(probe, tgt, ev, metrics, notes), gs))]
    return _combine(probe, dim, rule, parts, metrics, ev, notes)


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


def _discover_workflows(probe: core.Probe, gate_job: str) -> tuple[Optional[str], Optional[str]]:
    cfg = probe.cfg("ci_signal")
    nightly, gate = cfg.get("nightly_workflow"), cfg.get("ci_gate_workflow")
    wdir = probe.proj / ".github" / "workflows"
    files = sorted(list(wdir.glob("*.yml")) + list(wdir.glob("*.yaml"))) if wdir.is_dir() else []
    for f in files:
        t = probe.text(f) or ""
        if not nightly and re.search(r"^\s*schedule:\s*$", t, re.M) and re.search(r"cron:", t):
            nightly = f.name
        if not gate and re.search(rf"^\s{{2}}{re.escape(gate_job)}:\s*$", t, re.M):
            gate = f.name
    return nightly, gate


def _runs(probe: core.Probe, slug: str, workflow: str, branch: str, limit: int,
          extra: list[str]) -> Optional[list[dict]]:
    rc, out, _ = probe.run(["gh", "run", "list", "-R", slug, "--workflow", workflow, "--branch", branch, *extra,
                            "--json", "conclusion,status,createdAt,headSha,event,databaseId", "-L", str(limit)])
    if rc != 0:
        return None
    try:
        rows = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list):
        return None
    return sorted([r for r in rows if isinstance(r, dict)], key=lambda r: str(r.get("createdAt") or ""), reverse=True)


def collect_ci_signal(probe: core.Probe) -> dict:
    """11 CI signal — nightly green and ci-gate green on main (gh run list, read-only).

      nightly = latest COMPLETED ``nightly_event`` run of the nightly workflow on ``branch`` is ``success`` and
                ≤ nightly_max_age_hours old. Met → gate_score + (10 − gate_score) × min(green streak,
                nightly_streak_top)/top (10 = a full streak); missed → 0. No completed run → None.
      ci_gate = latest COMPLETED non-pull_request run on ``branch`` of the workflow that defines the
                ``ci_gate_job`` job is ``success`` and ≤ ci_gate_max_age_hours old → 10; else 0.
                No completed run on the branch → None (UNVERIFIED, not a 0 VERIFIED).
    Dimension = mean; capped at gate_cap unless both are met; both None → UNVERIFIED.
    """
    dim = "ci_signal"
    rule = str(probe.need(dim, "gate_rule"))
    gs, _cap = _gate(probe)
    branch = str(probe.need(dim, "branch"))
    event = str(probe.need(dim, "nightly_event"))
    gate_job = str(probe.need(dim, "ci_gate_job"))
    limit = int(probe.need(dim, "runs_limit"))
    nightly_max_age = float(probe.need(dim, "nightly_max_age_hours"))
    gate_max_age = float(probe.need(dim, "ci_gate_max_age_hours"))
    top = int(probe.need(dim, "nightly_streak_top"))
    if top <= 0:
        raise core.ConfigError("config dimensions.ci_signal.nightly_streak_top must be > 0")
    ev: list[dict] = []
    metrics: dict = {}
    notes: list[str] = []
    slug = _repo_slug(probe)
    nightly_wf, gate_wf = _discover_workflows(probe, gate_job)
    metrics.update(repo=slug, nightly_workflow=nightly_wf, ci_gate_workflow=gate_wf)
    if not slug:
        return core.unverified(dim, rule, "GitHub repo slug unknown (config ci_signal.repo / GH_REPO / origin)",
                               metrics=metrics)

    nightly_score: Optional[float] = None
    nightly_met = False
    if nightly_wf:
        runs = _runs(probe, slug, nightly_wf, branch, limit, ["--event", event])
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
            nightly_met = bool(latest and latest.get("conclusion") == "success" and age is not None
                               and 0 <= age <= nightly_max_age)
            if latest is None:
                notes.append(f"{nightly_wf} has no completed {event} run on {branch}")
            else:
                nightly_score = (gs + (10.0 - gs) * min(streak, top) / top) if nightly_met else 0.0
            metrics["nightly"] = {"latest_conclusion": (latest or {}).get("conclusion"), "latest_age_h": age,
                                  "latest_sha": str((latest or {}).get("headSha") or "")[:12] or None,
                                  "green_streak": streak, "completed_runs": len(done)}
            ev.append(core.evidence(f"gh run list --workflow {nightly_wf} --branch {branch} --event {event}",
                                    latest=(latest or {}).get("conclusion"), age_h=age, streak=streak))
    else:
        notes.append("no scheduled workflow found in .github/workflows")

    gate_score: Optional[float] = None
    if gate_wf:
        runs = _runs(probe, slug, gate_wf, branch, limit, [])
        if runs is None:
            notes.append("ci-gate runs unread (gh failed)")
        else:
            main_runs = [r for r in runs if r.get("event") != "pull_request"]
            done = [r for r in main_runs if r.get("status") == "completed"]
            latest = done[0] if done else None
            age = _age_h(probe, latest.get("createdAt")) if latest else None
            met = bool(latest and latest.get("conclusion") == "success" and age is not None
                       and 0 <= age <= gate_max_age)
            if latest is None:
                notes.append(f"{gate_wf} has no completed run on {branch} (pull_request runs only) — UNVERIFIED")
            else:
                gate_score = 10.0 if met else 0.0
            metrics["ci_gate"] = {"main_runs": len(main_runs), "latest_conclusion": (latest or {}).get("conclusion"),
                                  "latest_event": (latest or {}).get("event"), "latest_age_h": age,
                                  "latest_sha": str((latest or {}).get("headSha") or "")[:12] or None}
            ev.append(core.evidence(f"gh run list --workflow {gate_wf} --branch {branch}", main_runs=len(main_runs),
                                    latest=(latest or {}).get("conclusion"), age_h=age))
    else:
        notes.append(f"no workflow defines a `{gate_job}` job")

    parts = [("nightly_green", nightly_score), ("ci_gate_green_on_main", gate_score)]
    score, status, extra = core.mean_score(parts)
    gate_pass = nightly_met and gate_score == 10.0
    score = core.cap_on_fail(probe, score, gate_pass)
    metrics["sub_scores"] = {n: (None if v is None else round(v, 2)) for n, v in parts}
    if status == core.UNVERIFIED:
        return core.unverified(dim, rule, "; ".join(extra + notes), metrics=metrics, evidence_list=ev)
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=extra + notes)


# ================================================================================================
# 12 docs synced
# ================================================================================================

def _expand(probe: core.Probe, patterns: list[str]) -> tuple[list[str], list[str]]:
    """(files, patterns that matched nothing)."""
    out: list[str] = []
    empty: list[str] = []
    for p in patterns:
        if any(ch in p for ch in "*?["):
            hits = sorted(str(x.relative_to(probe.proj)) for x in probe.proj.glob(p) if x.is_file())
            if not hits:
                empty.append(p)
            out += hits
        else:
            out.append(p)
    return list(dict.fromkeys(out)), empty


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
    Score: 0 findings with every check run and every doc in scope read → 10; else
    min(gate_cap, gate_score × (1 − findings / findings_zero_at)).
    A check with no input (doc missing, no ADR/runbook read, no bound units) did NOT run: it is UNVERIFIED,
    never a 0-finding pass; any such check or missing in-scope doc → PARTIAL and the gate fails.
    """
    dim = "docs_synced"
    rule = str(probe.need(dim, "gate_rule"))
    gs, cap = _gate(probe)
    agents_rel = str(probe.need(dim, "agents_path"))
    adr_pats = list(probe.need(dim, "adr_paths"))
    rb_pats = list(probe.need(dim, "runbook_paths"))
    unit_rb = list(probe.need(dim, "unit_runbooks"))
    deploy_rel = str(probe.need(dim, "deploy_script"))
    zero_at = float(probe.need(dim, "findings_zero_at"))
    if zero_at <= 0:
        raise core.ConfigError("config dimensions.docs_synced.findings_zero_at must be > 0")
    ev: list[dict] = []
    notes: list[str] = []
    findings: dict[str, list[str]] = {}
    ran: dict[str, bool] = {}

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
    findings.setdefault("agents_policy_state", [])
    active_versions = {r["version"] for r in rows if r["status"].upper().startswith("ACTIVE")}

    adr, adr_empty = _expand(probe, adr_pats)
    runbooks, rb_empty = _expand(probe, rb_pats)
    scope = list(dict.fromkeys([agents_rel] + adr + runbooks))
    texts: dict[str, Optional[str]] = {p: (agents if p == agents_rel else probe.text(probe.proj / p)) for p in scope}
    missing_docs = [p for p, t in texts.items() if t is None] + [f"{p} (no match)" for p in adr_empty + rb_empty]
    others_read = [p for p in adr + runbooks if texts.get(p) is not None]

    stale: list[str] = []
    if rows and others_read:
        for p in others_read:
            for v in sorted({m.group(1) for m in _PROPOSED_RE.finditer(texts[p] or "")}):
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

    deploy = probe.text(probe.proj / deploy_rel)
    m = _BOUND_UNITS_RE.search(deploy or "")
    units = m.group(1).split() if m else []
    rb_texts = {r: (texts[r] if r in texts else probe.text(probe.proj / r)) for r in unit_rb}
    units_missing: list[str] = []
    if units and unit_rb and all(t is not None for t in rb_texts.values()):
        for r, t in rb_texts.items():
            units_missing += [f"{r}: {u}" for u in units if u not in (t or "") and u.replace(".service", "") not in (t or "")]
        ran["runbook_units"] = True
    else:
        ran["runbook_units"] = False
        notes.append("runbook unit check not run (no bound units in the deploy script default, no unit runbooks, "
                     "or a runbook unreadable)")
    findings["runbook_units"] = units_missing

    total = sum(len(v) for v in findings.values())
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
    complete = all_ran and not missing_docs
    gate_pass = total == 0 and complete
    score = 10.0 if gate_pass else min(cap, gs * max(0.0, 1.0 - total / zero_at))
    status = core.VERIFIED if complete else core.PARTIAL
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

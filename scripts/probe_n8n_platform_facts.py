#!/usr/bin/env python3
"""probe_n8n_platform_facts.py — measure the six §23.24 platform elements (FW-P1..P6) on this host. Read-only.

Why: the framework checker scored FW-P1..P6 from a hand-cited file (``docs/implementation/n8n-maturity/data/
n8n_platform_facts_20261015.json``) — a measurement of 2026-10-15 that nothing re-takes, and that anyone could edit
to PASS. The release-train import (step F) is blocked on these six (``framework_pending_evidence.json``
``platform_blocking``). This probe re-measures each one from the host itself and emits the same
``N8nPlatformFacts@v1`` shape with ``source_kind: "host_probe"`` and ``probed_at``; ``check_n8n_workflow_framework``
only lets a platform element PASS from a fresh host probe (a cited file can at most be PARTIAL), and
``check_n8n_import_ready.py --probe-host`` runs this probe in-process and prints each element with its evidence.

What it reads (every command is a fixed argv, no shell; no secret value is ever read or printed):

* FW-P1 — n8n container env, ONLY the allowlisted non-secret keys (``ENV_ALLOWLIST``; the docker template drops every
  other variable inside the daemon): ``EXECUTIONS_DATA_SAVE_ON_SUCCESS`` = all, ``EXECUTIONS_DATA_PRUNE`` = true,
  ``EXECUTIONS_DATA_MAX_AGE`` > 0 (retention), ``EXECUTIONS_DATA_PRUNE_MAX_COUNT``.
* FW-P2 — the role n8n connects as (``DB_POSTGRESDB_USER`` from the same allowlisted env) in ``pg_roles``: one SELECT
  in a read-only transaction through ``docker exec m8m-n8n-db psql`` (the lab's documented read path).
* FW-P3 — ``systemctl --user is-enabled/is-active tradeai-n8n-drift-watch.timer`` and a fresh live
  ``N8nDriftWatch@v1`` receipt (``scripts/n8n_drift_watch.py``) whose verdict is CLEAN or DRIFT (CANNOT_RUN fails),
  plus a fresh ``N8nWorkflowDriftReceipt@v1``.
* FW-P4 — the relay listener (``ss -ltn``: bound to the lab bridge gateway, not 0.0.0.0), the lab network
  (``docker network inspect``: subnet, bridge name) and live ufw rules. The probe reads them with two exact
  read-only ``sudo -n /usr/sbin/ufw status`` commands; a saved capture is diagnostic only and can never authorize
  PASS. PASS needs: ufw active,
  default incoming deny/reject, an ALLOW from the lab subnet on the lab bridge to the relay port, a DENY to the relay
  port after it, and no other ALLOW in front of the DENY that covers the relay.
* FW-P5 — compare the configured ``@sha256:`` manifest digest against ImageInspect ``.RepoDigests``. The probe reads the running container's image ID, then inspects that exact image object; it does not treat a container-config image reference as proof of the manifest digest. The env
  keys ``N8N_BLOCK_ENV_ACCESS_IN_NODE=true``, ``N8N_COMMUNITY_PACKAGES_ENABLED=false``.
* FW-P6 — ``systemctl --user is-enabled/is-active tradeai-n8n-host-deadman.timer`` and a fresh live
  ``N8nHostDeadman@v1`` receipt (``scripts/n8n_host_deadman.py``) that runs outside n8n.

    python3 scripts/probe_n8n_platform_facts.py                 # print the facts (dry run; writes nothing)
    python3 scripts/probe_n8n_platform_facts.py --write         # also write $STATE_ROOT/data/runtime/n8n_platform_facts_last.json

Exit 0 always when the probe ran (a FAIL is a fact, not an error); 2 when it could not run at all.
AUTHORITY: READ_ONLY_ADVISORY. No privileged writes, n8n writes, DB writes, or sends. sudo is used only for the exact read-only UFW status queries; other host queries use docker, systemctl, and ss.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402
from scripts.lib.n8n_pilot_observations import state_root  # noqa: E402

NO_CONSUMER_REASON = (
    "operator-run probe (packet n8n-platform-hardening-20261022); consumed in-process by "
    "scripts/check_n8n_import_ready.py --probe-host and, as a file, by check_n8n_workflow_framework.py "
    "--platform-facts. Not scheduled."
)
SCHEMA = "N8nPlatformFacts@v1"
SOURCE_KIND = "host_probe"
RECEIPT_REL = Path("data") / "runtime" / "n8n_platform_facts_last.json"
UFW_CAPTURE_REL = Path("data") / "runtime" / "ufw_status_n8n_relay.txt"
SUDO_BIN = "/usr/bin/sudo"
UFW_BIN = "/usr/sbin/ufw"
N8N_CONTAINER = "m8m-n8n"
DB_CONTAINER = "m8m-n8n-db"
LAB_NETWORK = "m8m-n8n_lab"
RELAY_PORT = 18092
DRIFT_TIMER = "tradeai-n8n-drift-watch.timer"
DEADMAN_TIMER = "tradeai-n8n-host-deadman.timer"
DRIFT_WATCH_REL = Path("data") / "runtime" / "n8n_drift_watch_last.json"
DRIFT_RECEIPT_REL = Path("data") / "runtime" / "n8n_workflow_drift_last.json"
DEADMAN_REL = Path("data") / "runtime" / "n8n_host_deadman_last.json"
DRIFT_MAX_AGE_MIN = 45.0  # 3 x the 15-minute timer
DEADMAN_MAX_AGE_MIN = 15.0  # 3 x the 5-minute timer
UFW_MAX_AGE_DAYS = 7.0

#: The only container env keys this probe reads. Secrets (DB passwords, N8N_ENCRYPTION_KEY) are NOT here, and the
#: docker template below emits only these keys, so no other value ever leaves the docker daemon.
ENV_ALLOWLIST = (
    "EXECUTIONS_DATA_SAVE_ON_SUCCESS",
    "EXECUTIONS_DATA_SAVE_ON_ERROR",
    "EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS",
    "EXECUTIONS_DATA_PRUNE",
    "EXECUTIONS_DATA_MAX_AGE",
    "EXECUTIONS_DATA_PRUNE_MAX_COUNT",
    "EXECUTIONS_DATA_HARD_DELETE_BUFFER",
    "N8N_BLOCK_ENV_ACCESS_IN_NODE",
    "N8N_COMMUNITY_PACKAGES_ENABLED",
    "N8N_COMMUNITY_PACKAGES_PREVENT_LOADING",
    "N8N_UNVERIFIED_PACKAGES_ENABLED",
    "DB_POSTGRESDB_USER",
    "DB_POSTGRESDB_DATABASE",
    "POSTGRES_USER",
    "POSTGRES_DB",
)
_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

Runner = Callable[[list[str]], tuple[int, str, str]]


def default_runner(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout, p.stderr


def env_template(keys: tuple[str, ...] = ENV_ALLOWLIST) -> str:
    cond = " ".join(f'(eq $k "{k}")' for k in keys)
    return '{{range .Config.Env}}{{$k := index (split . "=") 0}}{{if or ' + cond + "}}{{println .}}{{end}}{{end}}"


def read_env(container: str, run: Runner) -> dict[str, str]:
    rc, out, err = run(["docker", "inspect", container, "--format", env_template()])
    if rc != 0:
        raise RuntimeError(f"docker inspect {container}: exit {rc}: {err.strip()[:160]}")
    env: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k in ENV_ALLOWLIST:  # belt and braces: never keep a key outside the allowlist
                env[k] = v
    return env


def _bool(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    return str(v).strip().strip('"').lower() in {"1", "true", "yes", "on"}


def _int(v: Optional[str]) -> Optional[int]:
    try:
        return int(str(v).strip().strip('"'))
    except (TypeError, ValueError):
        return None


def _parse_ts(ts: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else None


def _fact(value: Any, evidence: str, **detail: Any) -> dict[str, Any]:
    return {"value": value, "evidence": evidence, **({"detail": detail} if detail else {})}


# ── FW-P1 ───────────────────────────────────────────────────────────────────────────────────────────────────────


def p1_facts(env: dict[str, str]) -> dict[str, dict]:
    save = env.get("EXECUTIONS_DATA_SAVE_ON_SUCCESS", "all (n8n 2.43 default; key absent)")
    prune = _bool(env.get("EXECUTIONS_DATA_PRUNE"))
    prune = True if prune is None else prune  # n8n 2.43 default pruneData = true
    max_age = _int(env.get("EXECUTIONS_DATA_MAX_AGE"))
    max_age = 336 if max_age is None else max_age  # n8n 2.43 default pruneDataMaxAge = 336 h
    max_count = _int(env.get("EXECUTIONS_DATA_PRUNE_MAX_COUNT"))
    max_count = 10000 if max_count is None else max_count
    save_value = "all" if save.startswith("all") else save
    ev = (
        f"container env EXECUTIONS_DATA_SAVE_ON_SUCCESS={env.get('EXECUTIONS_DATA_SAVE_ON_SUCCESS', '<unset>')} "
        f"EXECUTIONS_DATA_PRUNE={env.get('EXECUTIONS_DATA_PRUNE', '<unset>')} "
        f"EXECUTIONS_DATA_MAX_AGE={env.get('EXECUTIONS_DATA_MAX_AGE', '<unset>')}h "
        f"EXECUTIONS_DATA_PRUNE_MAX_COUNT={env.get('EXECUTIONS_DATA_PRUNE_MAX_COUNT', '<unset>')} "
        f"EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS={env.get('EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS', '<unset>')}"
    )
    return {
        "executions_save_on_success_default": _fact(save_value, ev),
        "executions_save_on_error_default": _fact(env.get("EXECUTIONS_DATA_SAVE_ON_ERROR", "all"), ev),
        "executions_prune": _fact(prune, ev),
        "executions_max_age_h": _fact(max_age, ev),
        "executions_prune_max_count": _fact(max_count, ev),
    }


# ── FW-P2 ───────────────────────────────────────────────────────────────────────────────────────────────────────


def p2_facts(n8n_env: dict[str, str], db_env: dict[str, str], run: Runner) -> dict[str, dict]:
    role = n8n_env.get("DB_POSTGRESDB_USER") or ""
    admin = db_env.get("POSTGRES_USER") or "n8n"
    db = n8n_env.get("DB_POSTGRESDB_DATABASE") or db_env.get("POSTGRES_DB") or "n8n"
    if not (_ROLE_RE.match(role) and _ROLE_RE.match(admin) and _ROLE_RE.match(db)):
        return {"n8n_db_role_superuser": _fact(None, f"n8n DB role name unreadable or unsafe: {role!r}")}
    sql = (
        "select coalesce((select json_build_object('role', rolname, 'rolsuper', rolsuper, 'rolcreaterole', "
        "rolcreaterole, 'rolcreatedb', rolcreatedb, 'rolreplication', rolreplication, 'rolbypassrls', rolbypassrls) "
        f"from pg_roles where rolname = '{role}'), json_build_object('role', '{role}', 'missing', true))"
    )
    rc, out, err = run(
        [
            "docker",
            "exec",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            DB_CONTAINER,
            "psql",
            "-X",
            "-U",
            admin,
            "-d",
            db,
            "-tAc",
            sql,
        ]
    )
    if rc != 0:
        return {"n8n_db_role_superuser": _fact(None, f"pg_roles read failed: exit {rc}: {err.strip()[:120]}")}
    try:
        row = json.loads(out.strip())
    except ValueError:
        return {"n8n_db_role_superuser": _fact(None, "pg_roles read returned no JSON")}
    if row.get("missing"):
        return {"n8n_db_role_superuser": _fact(None, f"role {role} (DB_POSTGRESDB_USER) not in pg_roles")}
    elevated = [k for k in ("rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls") if row.get(k)]
    return {
        "n8n_db_role_superuser": _fact(
            bool(row.get("rolsuper")) or bool(elevated),
            f"pg_roles {role} (DB_POSTGRESDB_USER): rolsuper={'t' if row.get('rolsuper') else 'f'}"
            + (f"; also {','.join(elevated)}" if elevated else ""),
            role=role,
            attributes=row,
        )
    }


# ── FW-P3 / FW-P6: timer + fresh receipt ─────────────────────────────────────────────────────────────────────────


def timer_state(unit: str, run: Runner) -> dict[str, str]:
    out = {}
    for verb in ("is-enabled", "is-active"):
        rc, so, se = run(["systemctl", "--user", verb, unit])
        out[verb] = (so.strip() or se.strip() or f"exit {rc}").splitlines()[0][:40] if (so or se) else f"exit {rc}"
    return out


def _receipt(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _age_min(ts: Any, now: datetime) -> Optional[float]:
    t = _parse_ts(ts)
    return None if t is None else round((now - t).total_seconds() / 60.0, 1)


def p3_facts(root: Path, now: datetime, run: Runner) -> dict[str, dict]:
    t = timer_state(DRIFT_TIMER, run)
    watch = _receipt(root / DRIFT_WATCH_REL) or {}
    drift = _receipt(root / DRIFT_RECEIPT_REL) or {}
    wage = _age_min(watch.get("as_of"), now)
    dage = _age_min(drift.get("as_of"), now)
    problems = []
    if t.get("is-enabled") != "enabled" or t.get("is-active") != "active":
        problems.append("timer not enabled+active")
    if watch.get("schema") != "N8nDriftWatch@v1":
        problems.append("no watch receipt")
    else:
        if watch.get("mode") != "live":
            problems.append(f"watch receipt mode {watch.get('mode')}")
        if wage is None or wage > DRIFT_MAX_AGE_MIN or wage < -5:
            problems.append(f"watch receipt age {wage} min > {DRIFT_MAX_AGE_MIN:g}")
        if watch.get("verdict") not in ("CLEAN", "DRIFT"):
            problems.append(f"last verdict {watch.get('verdict')}")
        if not str(watch.get("p1_path") or "").startswith("host:"):
            problems.append("no host P1 path on the receipt")
    if drift.get("schema") != "N8nWorkflowDriftReceipt@v1" or dage is None or dage > DRIFT_MAX_AGE_MIN:
        problems.append("drift receipt absent or stale")
    ev = (
        f"{DRIFT_TIMER} {t.get('is-enabled')}/{t.get('is-active')}; {DRIFT_WATCH_REL} "
        f"{watch.get('verdict', 'absent')} age {wage} min; {DRIFT_RECEIPT_REL} {drift.get('verdict', 'absent')} age {dage} min"
    )
    return {"drift_check_scheduled": _fact(not problems, ev + ("" if not problems else " — " + "; ".join(problems)))}


def p6_facts(root: Path, now: datetime, run: Runner) -> dict[str, dict]:
    t = timer_state(DEADMAN_TIMER, run)
    rec = _receipt(root / DEADMAN_REL) or {}
    age = _age_min(rec.get("checked_at"), now)
    problems = []
    if t.get("is-enabled") != "enabled" or t.get("is-active") != "active":
        problems.append("timer not enabled+active")
    if rec.get("schema") != "N8nHostDeadman@v1":
        problems.append("no dead-man receipt")
    else:
        if rec.get("mode") != "live":
            problems.append(f"receipt mode {rec.get('mode')}")
        if age is None or age > DEADMAN_MAX_AGE_MIN or age < -5:
            problems.append(f"receipt age {age} min > {DEADMAN_MAX_AGE_MIN:g}")
        if rec.get("runs_inside_n8n") is not False or not str(rec.get("alert_path") or "").startswith("host:"):
            problems.append("receipt does not show a host alert path outside n8n")
    ev = f"{DEADMAN_TIMER} {t.get('is-enabled')}/{t.get('is-active')}; {DEADMAN_REL} {rec.get('status', 'absent')} age {age} min"
    return {
        "host_dead_man_outside_n8n": _fact(not problems, ev + ("" if not problems else " — " + "; ".join(problems)))
    }


# ── FW-P4: ufw ───────────────────────────────────────────────────────────────────────────────────────────────────

_RULE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.*?)\s+(ALLOW|DENY|REJECT|LIMIT)(?:\s+(IN|OUT|FWD))?\s+(.*?)\s*(?:#.*)?$")


def parse_ufw(text: str) -> dict[str, Any]:
    status = re.search(r"^Status:\s*(\S+)", text, re.M)
    default = re.search(r"^Default:\s*(.*)$", text, re.M)
    rules = []
    for line in text.splitlines():
        m = _RULE_RE.match(line.strip())
        if not m or "(v6)" in line:
            continue
        rules.append(
            {
                "n": int(m.group(1)),
                "to": m.group(2).strip(),
                "action": m.group(3),
                "dir": m.group(4) or "IN",
                "from": m.group(5).strip(),
            }
        )
    return {
        "status": status.group(1).lower() if status else None,
        "default": default.group(1).strip() if default else None,
        "rules": rules,
    }


def _to_parts(to: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'172.19.0.1 18092/tcp on br-x' -> (addr, port, iface); 'Anywhere' -> ('Anywhere', None, None);
    '18092/tcp' -> (None, '18092/tcp', None)."""
    iface = None
    if " on " in f" {to} ":
        to, iface = re.split(r"\s+on\s+", f" {to} ".strip(), maxsplit=1)
        iface = iface.strip()
    parts = to.split()
    addr = port = None
    for p in parts:
        if re.match(r"^\d+(?::\d+)?(?:/(tcp|udp))?$", p) or p.lower() in {"ssh", "http", "https"}:
            port = p
        else:
            addr = p
    return addr, port, iface


def _port_covers(port: Optional[str], target: int) -> bool:
    if port is None:
        return True
    if port.lower() in {"ssh", "http", "https"}:
        return False
    base, _, proto = port.partition("/")
    if proto and proto != "tcp":
        return False
    if ":" in base:
        lo, hi = base.split(":", 1)
        return int(lo) <= target <= int(hi)
    return int(base) == target


def _addr_covers(addr: Optional[str], relay_ip: str) -> bool:
    if addr in (None, "Anywhere"):
        return True
    if "/" in addr:
        import ipaddress  # noqa: PLC0415

        try:
            return ipaddress.ip_address(relay_ip) in ipaddress.ip_network(addr, strict=False)
        except ValueError:
            return False
    return addr == relay_ip


def ufw_verdict(text: str, *, relay_ip: str, port: int, subnet: str, bridge: str) -> tuple[bool, list[str], dict]:
    u = parse_ufw(text)
    problems: list[str] = []
    if u["status"] != "active":
        problems.append(f"ufw status {u['status']}")
    if not u["default"] or not re.search(r"(deny|reject)\s*\(incoming\)", u["default"]):
        problems.append(f"default incoming not deny/reject ({u['default']})")
    allow = deny = None
    for r in u["rules"]:
        addr, rport, iface = _to_parts(r["to"])
        if r["dir"] != "IN":
            continue
        if addr == relay_ip and rport and _port_covers(rport, port):
            if r["action"] == "ALLOW" and iface == bridge and r["from"] == subnet and allow is None:
                allow = r
            elif r["action"] in ("DENY", "REJECT") and iface is None and r["from"] == "Anywhere" and deny is None:
                deny = r
    if allow is None:
        problems.append(f"no ALLOW IN on {bridge} from {subnet} to {relay_ip} {port}/tcp")
    if deny is None:
        problems.append(f"no DENY IN to {relay_ip} {port}/tcp from Anywhere")
    if allow and deny and allow["n"] > deny["n"]:
        problems.append(f"ALLOW rule [{allow['n']}] is after the DENY rule [{deny['n']}]")
    if deny:
        for r in u["rules"]:
            if r["n"] >= deny["n"] or r is allow or r["action"] not in ("ALLOW", "LIMIT") or r["dir"] != "IN":
                continue
            addr, rport, _iface = _to_parts(r["to"])
            if _addr_covers(addr, relay_ip) and _port_covers(rport, port):
                problems.append(f"rule [{r['n']}] '{r['to']} {r['action']} {r['from']}' shadows the relay DENY")
    return not problems, problems, {"allow": allow, "deny": deny, "status": u["status"], "default": u["default"]}


def p4_facts(root: Path, now: datetime, run: Runner, ufw_path: Path) -> dict[str, dict]:
    problems: list[str] = []
    rc, out, err = run(
        [
            "docker",
            "network",
            "inspect",
            LAB_NETWORK,
            "--format",
            "{{.Id}} {{range .IPAM.Config}}{{.Subnet}} {{.Gateway}}{{end}}",
        ]
    )
    netid = subnet = gateway = None
    if rc == 0 and len(out.split()) >= 3:
        netid, subnet, gateway = out.split()[:3]
    else:
        problems.append(f"docker network inspect {LAB_NETWORK}: exit {rc} {err.strip()[:80]}")
    bridge = f"br-{netid[:12]}" if netid else None
    rc, out, _ = run(["ss", "-ltnH"])
    binds = sorted(
        {ln.split()[3] for ln in out.splitlines() if len(ln.split()) >= 4 and ln.split()[3].endswith(f":{RELAY_PORT}")}
    )
    if gateway and f"{gateway}:{RELAY_PORT}" not in binds:
        problems.append(f"relay not listening on {gateway}:{RELAY_PORT} (binds {binds})")
    wide = [b for b in binds if b.startswith(("0.0.0.0:", "*:", "[::]:"))]
    if wide:
        problems.append(f"relay bound wide: {wide}")
    detail: dict[str, Any] = {
        "bridge": bridge,
        "subnet": subnet,
        "gateway": gateway,
        "binds": binds,
        "ufw_capture": str(ufw_path),
    }
    rc_v, verbose, err_v = run([SUDO_BIN, "-n", UFW_BIN, "status", "verbose"])
    rc_n, numbered, err_n = run([SUDO_BIN, "-n", UFW_BIN, "status", "numbered"])
    text = ""
    trusted_live = rc_v == 0 and rc_n == 0
    if trusted_live:
        text = verbose + "\n" + numbered
        detail["ufw_evidence_source"] = "live_read_only_sudo"
    else:
        problems.append(
            "live UFW status unavailable through the exact read-only sudo commands "
            f"(verbose exit {rc_v}, numbered exit {rc_n}); a saved capture cannot authorize PASS"
        )
        detail["ufw_evidence_source"] = "untrusted_capture_or_unavailable"
        try:
            st = ufw_path.stat()
            text = ufw_path.read_text(encoding="utf-8")
            age_d = (now.timestamp() - st.st_mtime) / 86400.0
            detail["ufw_capture_age_days"] = round(age_d, 2)
            if age_d > UFW_MAX_AGE_DAYS:
                problems.append(f"ufw capture {age_d:.1f} d old > {UFW_MAX_AGE_DAYS:g} d")
        except FileNotFoundError:
            problems.append(f"no diagnostic UFW capture at {ufw_path}")
        except OSError as exc:
            problems.append(f"ufw capture unreadable: {type(exc).__name__}")
    if text and gateway and subnet and bridge:
        _ok, ufw_problems, picked = ufw_verdict(text, relay_ip=gateway, port=RELAY_PORT, subnet=subnet, bridge=bridge)
        problems.extend(ufw_problems)
        detail["ufw"] = picked
    ev = f"relay binds {binds or 'none'}; lab {bridge} {subnet}; ufw evidence={detail['ufw_evidence_source']}"
    return {
        "relay_bind_firewall_verified": _fact(
            not problems, ev + ("" if not problems else " — " + "; ".join(problems)), **detail
        )
    }


# ── FW-P5 ───────────────────────────────────────────────────────────────────────────────────────────────────────


def p5_facts(env: dict[str, str], run: Runner) -> dict[str, dict]:
    # RepoDigests is an ImageInspect field, not a ContainerInspect field. Read
    # the running container's configured reference and immutable image ID first,
    # then inspect that exact local image object.
    rc, out, err = run(
        ["docker", "inspect", "--type=container", N8N_CONTAINER, "--format", "{{.Config.Image}}\n{{.Image}}"]
    )
    image = None
    image_id = None
    repo_digests: list[str] = []
    if rc == 0:
        lines = out.splitlines()
        image = lines[0].strip() if lines else None
        image_id = lines[1].strip() if len(lines) > 1 else None
    if image_id and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        rc_img, out_img, _err_img = run(["docker", "image", "inspect", image_id, "--format", "{{json .RepoDigests}}"])
        if rc_img == 0:
            try:
                parsed = json.loads(out_img.strip())
                repo_digests = [str(value) for value in parsed] if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                repo_digests = []
    pinned_digest = image.split("@", 1)[1] if image and "@sha256:" in image else None
    running = next((value for value in repo_digests if value.rsplit("@", 1)[-1] == pinned_digest), None)
    ev_img = f"container .Config.Image={image}; image ID={image_id}; image RepoDigests={repo_digests}"
    if pinned_digest and not running:
        ev_img += " — pinned manifest digest is NOT present in the running image RepoDigests (recreate or registry proof pending)"
        image_value = image.split("@", 1)[0]  # not a verified pin until the manifest digest is present
    else:
        image_value = image or ""
    block = _bool(env.get("N8N_BLOCK_ENV_ACCESS_IN_NODE"))
    community = _bool(env.get("N8N_COMMUNITY_PACKAGES_ENABLED"))
    return {
        "image_pinned": _fact(image_value, ev_img),
        "block_env_access_in_node": _fact(
            block is True, f"N8N_BLOCK_ENV_ACCESS_IN_NODE={env.get('N8N_BLOCK_ENV_ACCESS_IN_NODE', '<unset>')}"
        ),
        "community_packages_disabled": _fact(
            community is False, f"N8N_COMMUNITY_PACKAGES_ENABLED={env.get('N8N_COMMUNITY_PACKAGES_ENABLED', '<unset>')}"
        ),
    }


# ── assemble ────────────────────────────────────────────────────────────────────────────────────────────────────


def probe(
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    run: Optional[Runner] = None,
    ufw_status: Optional[Path] = None,
) -> dict[str, Any]:
    """All six elements, measured now. Raises RuntimeError only when the n8n container itself cannot be read."""
    now = now or datetime.now(timezone.utc)
    root = root or state_root()
    run = run or default_runner
    n8n_env = read_env(N8N_CONTAINER, run)
    try:
        db_env = read_env(DB_CONTAINER, run)
    except RuntimeError:
        db_env = {}
    facts: dict[str, dict] = {}
    facts.update(p1_facts(n8n_env))
    facts.update(p2_facts(n8n_env, db_env, run))
    facts.update(p3_facts(root, now, run))
    facts.update(p4_facts(root, now, run, ufw_status or (root / UFW_CAPTURE_REL)))
    facts.update(p5_facts(n8n_env, run))
    facts.update(p6_facts(root, now, run))
    return {
        "schema": SCHEMA,
        "source_kind": SOURCE_KIND,
        "as_of": now.replace(microsecond=0).isoformat(),
        "probed_at": now.replace(microsecond=0).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "source": "scripts/probe_n8n_platform_facts.py (host probe: docker inspect allowlisted env keys, pg_roles "
        "SELECT, systemctl --user, ss, docker network inspect, operator ufw capture)",
        "facts": facts,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--write", action="store_true", help=f"also write $STATE_ROOT/{RECEIPT_REL}")
    ap.add_argument("--out", default=None, help="write the facts to this path instead")
    ap.add_argument("--state-root", default=None)
    ap.add_argument("--ufw-status", default=None, help=f"operator ufw capture (default $STATE_ROOT/{UFW_CAPTURE_REL})")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.state_root) if a.state_root else state_root()
    try:
        doc = probe(root=root, ufw_status=Path(a.ufw_status) if a.ufw_status else None)
    except RuntimeError as exc:
        print(f"probe_n8n_platform_facts CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    if a.write or a.out:
        path = Path(a.out) if a.out else root / RECEIPT_REL
        atomic_write_json(path, doc)
        doc["written"] = str(path)
    if a.json:
        print(json.dumps(doc, indent=1, default=str))
        return 0
    from check_n8n_workflow_framework import score_platform  # noqa: PLC0415

    for k, v in score_platform(doc, now=datetime.now(timezone.utc)).items():
        print(f"{k} {v['status'].upper():7s} {v['evidence']}")
    print(f"({'written ' + doc['written'] if doc.get('written') else 'dry run, nothing written'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

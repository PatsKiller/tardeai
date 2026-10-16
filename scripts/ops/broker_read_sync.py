#!/usr/bin/env python3
"""broker_read_sync — READ-ONLY portfolio sync from every broker, runnable by an agent under a `broker-read` grant.

Operator, 2026-10-16: "make that bash so agents can run, make amendment, not trading just reading". This is the
repo form of the operator-run ``~/n8n-maturity-verification/sync_all_readonly.sh``: the same eight steps, in the
same order, with the same argv (``scripts/lib/broker_read_sync_policy.STEPS``, a closed allowlist). It reads
positions and transactions from Schwab, Alpaca (live read), moomoo and SnapTrade and writes only our own stores.
It never places, changes or cancels an order. Policy: AGENTS.md 14.0.0 §24.11 (PROPOSED until the operator's
``APPROVE_AGENTS_POLICY_14_0_0 <pr_number> <head_sha>``; until then §0 rule 2 is unchanged and only the operator
runs this).

    scripts/ops/broker_read_sync.sh --plan      # preflight + the step plan; reads nothing, needs no grant
    scripts/ops/broker_read_sync.sh             # DRY RUN (default): every step's dry mode — still a live read
    scripts/ops/broker_read_sync.sh --apply     # real sync into our stores

It refuses (exit 2, receipt written) unless ALL of these hold:
  * an active operator ``broker-read`` grant in the guard ledger (``~/.cursor/approvals``; one use per run);
  * the trading lock is LOCKED for schwab, alpaca, moomoo and snaptrade (``lib.trading_lock``);
  * the Schwab access mode resolves to ``read_only`` for the step processes (forced per process; the
    config file stays as the operator left it);
  * the static capability audit of every step's effective import closure is clean
    (``broker_read_sync_policy.audit``: no order write, order route, stop writer, re-auth/refresh or direct
    sender is reachable outside the runtime stubs);
  * it runs from the served release (``~/trade-ai-releases/portfolio-server/CURRENT``) and that release has a
    ``.env`` (checked with stat; never opened here).

Credentials: this process never opens ``.env``. Each step runs as
``bash --noprofile --norc -c 'cd ROOT; set -a; . ./.env; set +a; export TRADEAI_SCHWAB_ACCESS_MODE=read_only;
exec python scripts/ops/broker_read_sync_child.py STEP MODE'`` with PYTHON*/BASH_ENV injection variables
removed, and all step output is scrubbed of token-like strings before it is printed or stored.

No re-auth, 2FA or token-refresh flow is reachable: the child stubs them and refuses non-GET HTTP to broker
hosts. When a broker reports no/invalid login token, the run stops with ``needs_operator_reauth`` (exit 3); the
re-auth itself stays the operator's (``schwab_token_manager.py reauth-url`` / ``exchange-code``).

Receipt: ``BrokerReadSyncReceipt@v1`` JSON under ``<persistent-state>/data/runtime/broker_read_sync/``
(``TRADEAI_BROKER_READ_SYNC_RECEIPT_DIR`` overrides the directory), with each step's rc, status, scrubbed output
tail and the per-account status the steps reported.

Exit codes: 0 ok · 1 a step failed · 2 refused · 3 needs_operator_reauth · 4 a runtime guard tripped.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pwd
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import broker_read_sync_policy as policy  # noqa: E402

CHILD = ROOT / "scripts" / "ops" / "broker_read_sync_child.py"
EXIT_OK, EXIT_STEP_FAILED, EXIT_REFUSED, EXIT_REAUTH, EXIT_GUARD = 0, 1, 2, 3, 4
STEP_TIMEOUT_S = 900
TAIL_LINES = 15
# Removed from the environment handed to a step shell: they could inject code before the guards install.
SCRUB_ENV = ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PYTHONINSPECT", "PYTHONUSERBASE", "BASH_ENV", "ENV",
             "LD_PRELOAD", "LD_LIBRARY_PATH", "GUARD_APPROVALS_DIR", "TRADEAI_SCHWAB_ACCESS_MODE_PATH")
BOOT = ('cd -- "$1" || exit 70; set -a; . ./.env >/dev/null 2>&1 || exit 71; set +a; '
        'export TRADEAI_SCHWAB_ACCESS_MODE=read_only TRADEAI_BROKER_READ_SYNC=1; '
        'exec "$2" -u "$3" "$4" "$5"')
REAUTH_MARKERS = ("no schwab login token", "needs_reauth", "needs reauth", "re-auth required", "reauth required",
                  "token degraded", "refresh token expired", "invalid_grant", "needs_operator_reauth")


# ------------------------------------------------------------------------------------------------ scrubbing

_SCRUB_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)(\"?[A-Za-z0-9_]*(?:token|secret|password|passwd|api[_-]?key|app[_-]?key|access[_-]?key|"
                r"private[_-]?key|client[_-]?id|consumer[_-]?key|cookie|session[_-]?id|signature|enc[_-]?key)"
                r"[A-Za-z0-9_]*\"?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&}]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)([?&](?:access_token|refresh_token|code|token|apikey|api_key|signature|sig|key)=)[^&\s\"']+"),
     r"\1[REDACTED]"),
    (re.compile(r"\b(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{32,}={0,2}"), "[REDACTED_LONG]"),
)


def scrub(text: str) -> str:
    """Replace token-like substrings (JWTs, bearer values, key=value secrets, query secrets, long opaque runs)."""
    out = text or ""
    for rx, repl in _SCRUB_RULES:
        out = rx.sub(repl, out)
    return out


# ------------------------------------------------------------------------------------------------ environment

def operator_home() -> Path:
    """The account's home from the passwd database — HOME in the environment is not trusted."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def served_root() -> Path:
    return operator_home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"


def ledger_dir() -> Path:
    """The real guard ledger. GUARD_APPROVALS_DIR is ignored on purpose: a ledger an agent can point
    elsewhere is a ledger an agent can write its own grant into."""
    return operator_home() / ".cursor" / "approvals"


def receipt_dir() -> Path:
    env = os.environ.get("TRADEAI_BROKER_READ_SYNC_RECEIPT_DIR")
    if env:
        return Path(env)
    try:
        from lib.canonical_store_registry import production_state_root

        base = Path(production_state_root())
    except Exception:  # noqa: BLE001
        base = operator_home() / "trade-ai-releases" / "persistent-state"
    return base / "data" / "runtime" / "broker_read_sync"


def child_env(root: Path, base: Optional[dict[str, str]] = None) -> dict[str, str]:
    env = {k: v for k, v in (os.environ if base is None else base).items() if k not in SCRUB_ENV}
    env["HOME"] = str(operator_home())
    env["TRADEAI_SCHWAB_ACCESS_MODE"] = policy.SCHWAB_MODE
    env["TRADEAI_BROKER_READ_SYNC"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_SHA"] = Path(os.path.realpath(root)).name.split("-", 1)[0]
    return env


def resolved_child_mode(env: dict[str, str]) -> dict[str, Any]:
    """What lib.schwab_access_mode will resolve in a step process given this environment."""
    from lib import schwab_access_mode as sam

    saved = {k: os.environ.get(k) for k in ("TRADEAI_SCHWAB_ACCESS_MODE", "TRADEAI_SCHWAB_ACCESS_MODE_PATH")}
    try:
        for k in saved:
            if env.get(k) is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = env[k]
        return sam.status()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------------------------------------ preflight

def _load_guard_ledger(root: Path):
    path = root / ".cursor" / "hooks" / "guard_ledger.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("broker_read_guard_ledger", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def grant_state(root: Path, adir: Path) -> dict[str, Any]:
    gl = _load_guard_ledger(root)
    if gl is None:
        return {"active": False, "error": "guard_ledger.py not found in this release"}
    try:
        listed = gl.ledger_list(adir)
    except Exception as exc:  # noqa: BLE001
        return {"active": False, "error": f"ledger unreadable: {type(exc).__name__}"}
    rec = (listed.get("active") or {}).get(policy.GRANT_TIER)
    if not rec:
        return {"active": False, "ledger_state": listed.get("state")}
    now = int(time.time())
    return {"active": True, "expires_in_s": int(rec.get("expires", 0)) - now, "uses_left": rec.get("uses"),
            "reason": scrub(str(rec.get("reason", "")))[:200]}


def consume_grant(root: Path, adir: Path) -> bool:
    gl = _load_guard_ledger(root)
    if gl is None:
        return False
    try:
        return bool(gl.ledger_consume_grant(policy.GRANT_TIER, adir=adir).get("consumed"))
    except Exception:  # noqa: BLE001
        return False


def lock_states() -> dict[str, dict[str, Any]]:
    from lib import trading_lock as tl

    out = {}
    for broker in policy.LOCK_BROKERS:
        st = tl.lock_state(broker=broker)
        out[broker] = {"locked": bool(st.get("locked", True)), "reason": str(st.get("reason", ""))[:160]}
    return out


def policy_status(root: Path) -> str:
    """ACTIVE / PROPOSED / ABSENT for the 14.0.0 row of this release's AGENTS.md (informational)."""
    try:
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return "ABSENT"
    m = re.search(rf"^\| {re.escape(policy.POLICY_VERSION)} \| [^|]+\| (\w+)", text, re.M)
    return m.group(1).upper() if m else "ABSENT"


def preflight(
    root: Path,
    *,
    need_grant: bool,
    adir: Optional[Path] = None,
    served: Optional[Path] = None,
    grant_fn: Optional[Callable[[Path, Path], dict[str, Any]]] = None,
    lock_fn: Optional[Callable[[], dict[str, dict[str, Any]]]] = None,
    mode_fn: Optional[Callable[[dict[str, str]], dict[str, Any]]] = None,
    audit_fn: Optional[Callable[[Path], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Evaluate every refusal condition. Pure of brokers: reads the ledger, the lock files, the switch file and
    repository source; stats (never opens) .env."""
    adir = adir or ledger_dir()
    served = served or served_root()
    refusals: list[str] = []
    grant = (grant_fn or grant_state)(root, adir)
    if need_grant and not grant.get("active"):
        refusals.append("broker_read_grant_missing")
    locks = (lock_fn or lock_states)()
    for broker, st in locks.items():
        if not st.get("locked", False):
            refusals.append(f"trading_lock_not_locked:{broker}")
    env = child_env(root)
    mode = (mode_fn or resolved_child_mode)(env)
    if mode.get("mode") != policy.SCHWAB_MODE:
        refusals.append("schwab_access_mode_not_read_only")
    cap = (audit_fn or policy.audit)(root)
    if not cap.get("ok"):
        kinds = sorted({f"{f.get('kind')}:{f.get('module')}" for f in cap.get("findings", [])})
        refusals.extend(f"capability_found:{k}" for k in kinds)
    try:
        same_release = Path(os.path.realpath(root)) == Path(os.path.realpath(served))
    except OSError:
        same_release = False
    if not same_release:
        refusals.append("not_served_release")
    if not (root / ".env").is_file():  # stat only
        refusals.append("env_file_missing")
    return {
        "refusals": refusals,
        "grant": grant,
        "trading_lock": locks,
        "schwab_access_mode": {"mode": mode.get("mode"), "source": mode.get("source")},
        "capability_audit": {"ok": bool(cap.get("ok")), "findings": cap.get("findings", [])[:50],
                             "steps": cap.get("steps", {})},
        "release": {"root": str(root), "served_root": str(served), "same_release": same_release,
                    "git_sha": env["GIT_SHA"]},
        "policy_14_0_0": policy_status(root),
    }


# ------------------------------------------------------------------------------------------------ run

def _json_objects(text: str) -> list[Any]:
    dec = json.JSONDecoder()
    out, i = [], 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return out
        try:
            obj, end = dec.raw_decode(text, i)
            out.append(obj)
            i = end
        except ValueError:
            i += 1


def accounts_from_output(raw: str) -> dict[str, str]:
    """Per-account status the steps print: positions_sync's summary (accounts_ok / accounts_failed / accounts)
    and schwab_position_sync's ``{account: {status: ...}}`` blocks. Statuses only, scrubbed."""
    found: dict[str, str] = {}
    for obj in _json_objects(raw):
        if not isinstance(obj, dict):
            continue
        for k in obj.get("accounts_ok") or []:
            found[str(k)] = "ok"
        for k in obj.get("accounts_failed") or []:
            found[str(k)] = "failed"
        accts = obj.get("accounts")
        if isinstance(accts, dict):
            for k, v in accts.items():
                if isinstance(v, dict) and v.get("status") is not None:
                    found[str(k)] = str(v.get("status"))
        if len(obj) == 1:
            (k, v), = obj.items()
            if isinstance(v, dict) and "status" in v:
                found[str(k)] = str(v["status"])
    return {scrub(k)[:40]: scrub(v)[:60] for k, v in found.items()}


def classify(step: policy.Step, rc: int, raw: str) -> str:
    low = (raw or "").lower()
    if policy.GUARD_MARK.lower() in low:
        return "guard_tripped"
    if step.broker != "none" and any(m in low for m in REAUTH_MARKERS):
        return "needs_operator_reauth"
    if rc != 0 and step.broker != "none":
        from lib import schwab_access_mode as sam

        if sam.is_auth_failure(raw[-4000:]):
            return "needs_operator_reauth"
    return "ok" if rc == 0 else "failed"


def run_child(root: Path, step: policy.Step, mode: str) -> tuple[int, str]:
    cmd = ["/bin/bash", "--noprofile", "--norc", "-c", BOOT, "broker_read_sync", str(root), sys.executable,
           str(CHILD), step.id, mode]
    try:
        proc = subprocess.run(cmd, env=child_env(root), capture_output=True, text=True, timeout=STEP_TIMEOUT_S,
                              check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return 124, out + f"\n[broker_read_sync] step timed out after {STEP_TIMEOUT_S}s"


def run_steps(root: Path, mode: str, runner: Optional[Callable[[Path, policy.Step, str], tuple[int, str]]] = None,
              emit: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], str]:
    runner = runner or run_child
    results: list[dict[str, Any]] = []
    outcome = "ok"
    for step in policy.STEPS:
        argv = step.argv(mode)
        if argv is None:
            continue
        emit(f"\n=== {step.label}{'' if mode == 'apply' else ' (dry)'}")
        t0 = time.monotonic()
        rc, raw = runner(root, step, mode)
        status = classify(step, rc, raw)
        tail = scrub(raw).splitlines()[-TAIL_LINES:]
        for line in tail:
            emit(line)
        emit(f"    rc={rc} status={status}")
        results.append({"id": step.id, "label": step.label, "script": step.script, "argv": list(argv),
                        "broker": step.broker, "rc": rc, "status": status,
                        "duration_s": round(time.monotonic() - t0, 2),
                        "accounts": accounts_from_output(raw), "output_tail": tail})
        if status == "guard_tripped":
            outcome = "guard_tripped"
            break
        if status == "needs_operator_reauth":
            outcome = "needs_operator_reauth"
            break
        if status == "failed":
            outcome = "partial"
    return results, outcome


def write_receipt(doc: dict[str, Any], directory: Optional[Path] = None) -> Path:
    d = directory or receipt_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"broker_read_sync_{doc['run_id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="broker_read_sync", description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write our stores (default: dry run of every step)")
    g.add_argument("--plan", action="store_true", help="preflight and print the plan; contacts no broker")
    return ap.parse_args(argv)  # anything else — a step name, an extra flag — is an argparse error (exit 2)


def main(argv: Optional[list[str]] = None, *, root: Path = ROOT, emit: Callable[[str], None] = print,
         **preflight_kw: Any) -> int:
    args = parse_args(argv)
    mode = "plan" if args.plan else ("apply" if args.apply else "dry_run")
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%S%fZ") + f"_{mode}"
    pre = preflight(root, need_grant=(mode != "plan"), **preflight_kw)
    doc: dict[str, Any] = {
        "schema": policy.SCHEMA_RECEIPT, "run_id": run_id, "mode": mode, "started_at": started.isoformat(),
        "authority": "READ_ONLY_BROKER_SYNC", "mbi": 0, "grant_tier": policy.GRANT_TIER,
        "policy": {"version": policy.POLICY_VERSION, "status": pre["policy_14_0_0"], "token": policy.POLICY_TOKEN},
        "preflight": pre, "steps": [], "accounts": {},
    }
    emit(f"broker_read_sync mode={mode.upper()} schwab_access={policy.SCHWAB_MODE} "
         f"release={pre['release']['git_sha']} policy_14_0_0={pre['policy_14_0_0']}")
    if pre["policy_14_0_0"] != "ACTIVE":
        emit("NOTE: AGENTS.md 14.0.0 is not ACTIVE — under §0 rule 2 only the operator may run this against a "
             "broker; an agent may run --plan only.")
    for st in policy.STEPS:
        a = st.argv("apply" if mode == "plan" else mode)
        emit(f"  step {st.id:<20} {st.script} {' '.join(a) if a is not None else '(skipped in dry run)'}")
    if mode == "plan":
        emit("  (plan shows the --apply argv; a dry run uses each step's dry argv)")
    if pre["refusals"]:
        doc.update(outcome="refused", refusals=pre["refusals"])
        emit("REFUSED: " + ", ".join(pre["refusals"]))
        code = EXIT_REFUSED
    elif mode == "plan":
        doc.update(outcome="planned", refusals=[])
        emit("PLAN OK: preflight clean; no broker contacted.")
        code = EXIT_OK
    elif not consume_grant(root, preflight_kw.get("adir") or ledger_dir()):
        doc.update(outcome="refused", refusals=["broker_read_grant_not_consumable"])
        emit("REFUSED: broker_read_grant_not_consumable")
        code = EXIT_REFUSED
    else:
        results, outcome = run_steps(root, mode, emit=emit)
        merged: dict[str, str] = {}
        for r in results:
            merged.update(r["accounts"])
        doc.update(steps=results, accounts=merged, outcome=outcome, refusals=[])
        code = {"ok": EXIT_OK, "partial": EXIT_STEP_FAILED, "needs_operator_reauth": EXIT_REAUTH,
                "guard_tripped": EXIT_GUARD}[outcome]
        if outcome == "needs_operator_reauth":
            emit("STOPPED: needs_operator_reauth — a broker has no valid login token; re-auth is the operator's.")
    doc["finished_at"] = datetime.now(timezone.utc).isoformat()
    doc["exit_code"] = code
    try:
        emit(f"receipt: {write_receipt(doc)}")
    except OSError as exc:
        emit(f"receipt write failed: {type(exc).__name__}")
        code = code or EXIT_STEP_FAILED
    return code


if __name__ == "__main__":
    sys.exit(main())

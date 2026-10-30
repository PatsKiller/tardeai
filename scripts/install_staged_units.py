#!/usr/bin/env python3
"""Install the reviewed staged host systemd USER units a release carries (config/staged_user_units.json).

Called by scripts/cio_phase2_exact_main_deploy.sh promote (after CURRENT moved and the bound units
restarted), so a unit admitted in the repo reaches the host at the next release with no operator step
and no TTY acknowledgement. Per group, in this order:

  1. admission: the group's config must say enabled + REVIEWED, else PENDING_ADMISSION (nothing written);
  2. dry-run (AGENTS rule 7): the group's own --dry-run must exit in ok_exit and print the expected JSON,
     else the group is REFUSED (nothing installed, nothing enabled). Its output is recorded;
  3. one-time steps (e.g. a refusal ack): preview first, then the apply flag; done ids are remembered;
  4. install: an installed copy that differs is ARCHIVED (moved, never deleted) before the new copy
     is written; daemon-reload; enable --now;
  5. first run + verify: start the oneshot service once, read back is-active for each enabled unit and
     the group's receipt (fresh, expected schema/mode).

Every unit file is validated before anything is installed (validate_unit_text): a service runs exactly one
ExecStart of the release venv (%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python) on a release
scripts/<x>.py; no User=/Group=, no ExecStartPre/Post/Stop/Reload/Condition hooks; [Install] only
WantedBy=timers.target/default.target; a timer's Unit= names a service of its group; source_dir is ops/systemd.

A failed run (exit 1) sends ONE P1 through the host chokepoint (telegram_alert.send_telegram_outcome),
deduplicated by failure fingerprint in the state file; needs-action and platform-health read the receipt.
When the dry-run reports findings beyond the group's one-time acks, the receipt and output say
"will page: ..." before the first live run.

Modes: plan (default; writes nothing), apply, rollback (disable --now + archive the installed copies),
retire --target <dir> (rollback only the groups this release's manifest has and the target's lacks; the deploy
runs it on rollback before applying the target's manifest).
An unchanged, already-active group is UNCHANGED and does nothing. The receipt is
data/runtime/staged_units_install_latest.json under the state root. Exit 0 = every admitted group OK
or UNCHANGED; 1 = some group failed (the deploy logs it, the release stays live); 2 = usage/manifest.

No credential, broker, DB, crontab or n8n path. Commands are argv lists (no shell); only
scripts/*.py under the release are executed, with this interpreter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "StagedUserUnits@v1"
RECEIPT = "data/runtime/staged_units_install_latest.json"
STATE = "data/runtime/staged_units_install_state.json"
DEFAULT_MANIFEST = "config/staged_user_units.json"
UNIT_SUFFIXES = (".service", ".timer", ".path")
SOURCE_DIR = "ops/systemd"
RELEASE_PYTHON = "%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python"
RELEASE_SCRIPT_PREFIXES = ("scripts/", "%h/trade-ai-releases/portfolio-server/CURRENT/scripts/")
FORBIDDEN_SERVICE_KEYS = ("User", "Group", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost",
                          "ExecReload", "ExecCondition", "DynamicUser", "PAMName")
ALLOWED_WANTED_BY = ("timers.target", "default.target")
NOTIFY_PRODUCER = "install_staged_units"
FIRST_RUN_TIMEOUT_S = 90
RECEIPT_MAX_AGE_S = 180


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def parse_unit(text: str) -> list[tuple[str, str, str]]:
    """(section, key, value) for every assignment; comments and blanks dropped. Continuations are refused."""
    rows, section = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if raw.rstrip().endswith("\\"):
            rows.append((section, "__continuation__", line))
            continue
        key, sep, value = line.partition("=")
        rows.append((section, key.strip() if sep else "__malformed__", value.strip()))
    return rows


def validate_unit_text(name: str, text: str, group_units: list[str]) -> list[str]:
    """Refusals for one staged unit file (empty = installable). Reviewed shape only; anything else is refused."""
    errs: list[str] = []
    rows = parse_unit(text)
    for section, key, value in rows:
        if key in ("__continuation__", "__malformed__"):
            errs.append(f"{name}: unparseable line {value[:60]!r}")
        if section == "Install":
            if key != "WantedBy":
                errs.append(f"{name}: [Install] {key}= not allowed (only WantedBy)")
            elif any(t not in ALLOWED_WANTED_BY for t in value.split()):
                errs.append(f"{name}: WantedBy={value} (only {'/'.join(ALLOWED_WANTED_BY)})")
    if name.endswith(".service"):
        svc = [(k, v) for sec, k, v in rows if sec == "Service"]
        for key, _ in svc:
            if key in FORBIDDEN_SERVICE_KEYS:
                errs.append(f"{name}: {key}= not allowed")
        execs = [v for k, v in svc if k == "ExecStart"]
        if len(execs) != 1:
            errs.append(f"{name}: exactly one ExecStart= required, found {len(execs)}")
        else:
            argv = execs[0].split()
            script = argv[1] if len(argv) > 1 else ""
            if not argv or argv[0] != RELEASE_PYTHON:
                errs.append(f"{name}: ExecStart must run {RELEASE_PYTHON}")
            if not (script.startswith(RELEASE_SCRIPT_PREFIXES) and script.endswith(".py") and ".." not in script):
                errs.append(f"{name}: ExecStart must run a release scripts/<x>.py")
            if any(ch in execs[0] for ch in ";|&`$<>"):
                errs.append(f"{name}: ExecStart must not contain shell syntax")
    elif name.endswith(".timer"):
        targets = [v for sec, k, v in rows if sec == "Timer" and k == "Unit"]
        if len(targets) != 1 or targets[0] not in group_units:
            errs.append(f"{name}: Timer Unit= must name one service of its group")
    elif name.endswith(".path"):
        errs.append(f"{name}: .path units are not admitted yet")
    return errs


def validate_manifest(doc: dict) -> list[str]:
    errs = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    seen = set()
    for i, g in enumerate(doc.get("groups") or []):
        gid = str(g.get("id") or "")
        if not gid or gid in seen:
            errs.append(f"groups[{i}]: id missing or duplicate")
        seen.add(gid)
        units = g.get("units") or []
        if not units or any(not isinstance(u, str) or "/" in u or not u.endswith(UNIT_SUFFIXES) for u in units):
            errs.append(f"{gid}: units must be bare *.service/*.timer/*.path names")
        if any(u not in units for u in g.get("enable") or []):
            errs.append(f"{gid}: enable must name units of the group")
        if g.get("first_run") and g["first_run"] not in units:
            errs.append(f"{gid}: first_run must name a unit of the group")
        if g.get("source_dir") != SOURCE_DIR:
            errs.append(f"{gid}: source_dir must be {SOURCE_DIR}")
        adm = g.get("admission") or {}
        if not adm.get("config") or not isinstance(adm.get("require"), dict) or not adm["require"]:
            errs.append(f"{gid}: admission.config + admission.require are required")
        if not (g.get("dry_run") or {}).get("argv"):
            errs.append(f"{gid}: dry_run.argv is required (AGENTS rule 7)")
        argvs = [(g.get("dry_run") or {}).get("argv") or []] + [s.get("argv") or [] for s in g.get("once") or []]
        for argv in argvs:
            if not argv or not str(argv[0]).startswith("scripts/") or not str(argv[0]).endswith(".py") \
                    or ".." in Path(str(argv[0])).parts:
                errs.append(f"{gid}: commands must start with a release scripts/*.py path")
        for s in g.get("once") or []:
            if not s.get("id") or not s.get("apply_flag"):
                errs.append(f"{gid}: once steps need id and apply_flag")
    return errs


class Host:
    """systemctl --user, argv only. TRADEAI_SYSTEMCTL names a substitute binary (tests)."""

    def __init__(self) -> None:
        self.bin = os.environ.get("TRADEAI_SYSTEMCTL") or "systemctl"
        self.calls: list[str] = []

    def run(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        argv = [self.bin, "--user", *args]
        self.calls.append(" ".join(["systemctl", "--user", *args]))
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(argv, 124, "", str(exc))

    def is_active(self, unit: str) -> bool:
        return self.run("is-active", "--quiet", unit).returncode == 0


def run_script(release: Path, state_root: Path, argv: list[str], timeout: int = 120) -> dict:
    env = dict(os.environ)
    env["TRADEAI_STATE_ROOT"] = str(state_root)
    try:
        proc = subprocess.run([sys.executable, *argv], cwd=release, env=env, capture_output=True, text=True,
                              timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        rc, out, err = 124, "", str(exc)
    parsed = None
    try:
        parsed = json.loads(out)
    except ValueError:
        for line in reversed(out.strip().splitlines()):
            try:
                parsed = json.loads(line)
                break
            except ValueError:
                continue
    return {"argv": argv, "exit": rc, "json": parsed if isinstance(parsed, dict) else None,
            "stderr_tail": err[-600:]}


def summarize_dry_run(doc: dict | None) -> dict | None:
    if not isinstance(doc, dict):
        return None
    keep = ("schema", "mode", "status", "observed_at", "missed_lane_ids", "collection_gaps", "alert_required")
    out = {k: doc.get(k) for k in keep if k in doc}
    out["refusal_keys"] = [r.get("key") for r in doc.get("refusals") or [] if isinstance(r, dict)][:20]
    out["coverage_gap_count"] = len(doc.get("coverage_gap_lane_ids") or [])
    return out


def will_page(doc: dict | None, group: dict) -> list[str]:
    """Findings in the dry-run report that the first live run will page for (the group's one-time acks excluded)."""
    if not isinstance(doc, dict):
        return []
    acked = set()
    for step in group.get("once") or []:
        argv = list(step.get("argv") or [])
        if "--ack-refusal" in argv and argv.index("--ack-refusal") + 1 < len(argv):
            acked.add(argv[argv.index("--ack-refusal") + 1])
    out = [f"missed:{lane}" for lane in doc.get("missed_lane_ids") or []]
    out += [f"refusal:{r.get('job_id')}:{r.get('key')}" for r in doc.get("refusals") or []
            if isinstance(r, dict) and r.get("active", True) and r.get("key") not in acked]
    out += [f"monitor:{m.get('id')}" for m in doc.get("monitor_incidents") or [] if isinstance(m, dict)]
    return out


def admitted(release: Path, group: dict) -> tuple[bool, str]:
    adm = group["admission"]
    try:
        cfg = json.loads((release / adm["config"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"admission config unreadable: {exc.__class__.__name__}"
    for key, want in adm["require"].items():
        if cfg.get(key) != want:
            return False, f"{adm['config']} {key}={cfg.get(key)!r} (needs {want!r})"
    if not str(cfg.get("approved_by") or "").strip():
        return False, f"{adm['config']} approved_by is empty"
    return True, "admitted"


def unit_diff(release: Path, unit_dir: Path, group: dict) -> list[dict]:
    rows = []
    for unit in group["units"]:
        src, dst = release / group["source_dir"] / unit, unit_dir / unit
        s, d = sha(src), sha(dst)
        rows.append({"unit": unit, "source_sha256": s, "installed_sha256": d,
                     "change": "MISSING_SOURCE" if s is None else "NEW" if d is None else
                     "UNCHANGED" if s == d else "CHANGED"})
    return rows


def receipt_fresh(state_root: Path, verify: dict, since: datetime) -> tuple[bool, str]:
    rel = verify.get("receipt")
    if not rel:
        return True, "no receipt declared"
    try:
        doc = json.loads((state_root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"{rel} unreadable"
    for key, want in (verify.get("receipt_expect") or {}).items():
        if doc.get(key) != want:
            return False, f"{rel} {key}={doc.get(key)!r} (needs {want!r})"
    try:
        at = datetime.fromisoformat(str(doc.get(verify.get("receipt_clock") or "observed_at")).replace("Z", "+00:00"))
    except ValueError:
        return False, f"{rel} clock unreadable"
    if at.tzinfo is None or at < since.replace(microsecond=0) or (now_utc() - at).total_seconds() > RECEIPT_MAX_AGE_S:
        return False, f"{rel} not written by this install's first run (clock {doc.get('observed_at')})"
    return True, f"{rel} fresh ({iso(at)}, status {doc.get('status')})"


def apply_group(release: Path, unit_dir: Path, state_root: Path, group: dict, state: dict, host: Host,
                stamp: str, *, plan: bool) -> dict:
    gid = group["id"]
    out: dict = {"id": gid, "lane_id": group.get("lane_id")}
    ok, why = admitted(release, group)
    out["admission"] = why
    if not ok:
        out["status"] = "PENDING_ADMISSION"
        return out
    diff = unit_diff(release, unit_dir, group)
    out["units"] = diff
    if any(r["change"] == "MISSING_SOURCE" for r in diff):
        out["status"] = "FAILED"
        out["reason"] = "a staged source unit is missing from the release"
        return out
    unit_errs = [e for u in group["units"]
                 for e in validate_unit_text(u, (release / group["source_dir"] / u).read_text(encoding="utf-8"),
                                             group["units"])]
    if unit_errs:
        out["status"] = "REFUSED_UNIT"
        out["reason"] = "; ".join(unit_errs)[:600]
        return out
    changed = [r["unit"] for r in diff if r["change"] in ("NEW", "CHANGED")]
    inactive = [u for u in group.get("enable") or [] if not host.is_active(u)]
    pending_once = [s for s in group.get("once") or [] if s["id"] not in (state.get("once_done") or {})]
    if not changed and not inactive and not pending_once:
        out["status"] = "UNCHANGED"
        return out
    if plan:
        out["status"] = "WOULD_INSTALL"
        out["would"] = {"archive_then_install": [r["unit"] for r in diff if r["change"] == "CHANGED"],
                        "install": [r["unit"] for r in diff if r["change"] == "NEW"],
                        "dry_run": group["dry_run"]["argv"], "once": [s["id"] for s in pending_once],
                        "enable_now": group.get("enable") or [], "first_run": group.get("first_run")}
        return out

    # 2. dry-run first (rule 7); a failed dry-run refuses the whole group.
    dr = group["dry_run"]
    res = run_script(release, state_root, list(dr["argv"]))
    doc = res["json"]
    expect_ok = isinstance(doc, dict) and all(doc.get(k) == v for k, v in (dr.get("expect") or {}).items())
    out["dry_run"] = {"argv": res["argv"], "exit": res["exit"], "expected_shape": expect_ok,
                      "summary": summarize_dry_run(doc), "stderr_tail": res["stderr_tail"] if not expect_ok else ""}
    if res["exit"] not in (dr.get("ok_exit") or [0]) or not expect_ok:
        out["status"] = "REFUSED_DRY_RUN"
        return out
    out["will_page"] = will_page(doc, group)

    # 3. one-time steps: preview, then apply; remembered by id.
    done = state.setdefault("once_done", {})
    out["once"] = []
    for step in pending_once:
        preview = run_script(release, state_root, list(step["argv"]))
        rec = {"id": step["id"], "preview_exit": preview["exit"], "preview": preview["json"]}
        reason = (preview["json"] or {}).get("reason")
        if preview["exit"] == 0 and (preview["json"] or {}).get("ok") is True:
            applied = run_script(release, state_root, list(step["argv"]) + [step["apply_flag"]])
            rec.update(apply_exit=applied["exit"], apply=applied["json"])
            if applied["exit"] == 0 and (applied["json"] or {}).get("ok") is True:
                rec["result"] = "APPLIED"
            else:
                rec["result"] = "APPLY_FAILED"
        elif reason in (step.get("done_when_reason") or []):
            rec["result"] = f"NOT_NEEDED:{reason}"
        else:
            rec["result"] = "PREVIEW_FAILED"
        out["once"].append(rec)
        if rec["result"] == "APPLIED" or rec["result"].startswith("NOT_NEEDED"):
            done[step["id"]] = {"at": iso(now_utc()), "result": rec["result"], "release": str(release)}
        else:
            out["status"] = "FAILED"
            out["reason"] = f"one-time step {step['id']} {rec['result']}; units not enabled"
            return out

    # 4. archive-on-replace, install, reload, enable.
    archive = unit_dir / f"archived-staged-units-{stamp}"
    manifest_lines = []
    for r in diff:
        if r["change"] == "UNCHANGED":
            continue
        dst = unit_dir / r["unit"]
        if r["change"] == "CHANGED":
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(archive / r["unit"]))
            manifest_lines.append(f"archived {r['unit']} {r['installed_sha256']}")
        else:
            manifest_lines.append(f"new {r['unit']}")
        atomic_write(dst, (release / group["source_dir"] / r["unit"]).read_bytes())
    if manifest_lines:
        archive.mkdir(parents=True, exist_ok=True)
        with open(archive / "MANIFEST", "a", encoding="utf-8") as stream:
            stream.write("\n".join(f"{gid} {line}" for line in manifest_lines) + "\n")
        out["archive"] = str(archive)
    started = now_utc()
    if host.run("daemon-reload").returncode != 0:
        out["status"] = "FAILED"
        out["reason"] = "daemon-reload failed"
        return out
    en = group.get("enable") or []
    if en:
        r = host.run("enable", "--now", *en)
        if r.returncode != 0:
            out["status"] = "FAILED"
            out["reason"] = f"enable --now failed: {(r.stderr or '').strip()[-200:]}"
            return out

    # 5. first live run (after the dry-run and the one-time steps), then read back.
    if group.get("first_run"):
        r = host.run("start", group["first_run"], timeout=FIRST_RUN_TIMEOUT_S)
        out["first_run"] = {"unit": group["first_run"], "exit": r.returncode}
    verify = group.get("verify") or {}
    checks = {u: host.is_active(u) for u in verify.get("active") or en}
    fresh, detail = receipt_fresh(state_root, verify, started)
    out["verify"] = {"active": checks, "receipt": detail, "receipt_ok": fresh}
    state.setdefault("installed", {})[gid] = {"at": iso(now_utc()), "release": str(release),
                                              "units": {r["unit"]: r["source_sha256"] for r in diff}}
    out["status"] = "INSTALLED" if all(checks.values()) and fresh else "VERIFY_FAILED"
    return out


def rollback_group(release: Path, unit_dir: Path, group: dict, host: Host, stamp: str) -> dict:
    archive = unit_dir / f"archived-staged-units-rollback-{stamp}"
    if group.get("enable"):
        host.run("disable", "--now", *group["enable"])
    moved = []
    for unit in group["units"]:
        dst = unit_dir / unit
        if dst.exists():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(archive / unit))
            moved.append(unit)
    if moved:
        with open(archive / "MANIFEST", "a", encoding="utf-8") as stream:
            stream.write("".join(f"{group['id']} rolled-back {u}\n" for u in moved))
    host.run("daemon-reload")
    return {"id": group["id"], "status": "ROLLED_BACK" if moved else "NOTHING_INSTALLED", "archived": moved,
            "archive": str(archive) if moved else None}


def retire_groups(release: Path, target: Path, manifest: dict, unit_dir: Path, host: Host, stamp: str) -> list[dict]:
    """Roll back every group of this release's manifest that the target release's manifest does not carry."""
    try:
        keep = {g.get("id") for g in json.loads((target / DEFAULT_MANIFEST).read_text(encoding="utf-8"))["groups"]}
    except (OSError, ValueError, KeyError, TypeError):
        keep = set()
    return [rollback_group(release, unit_dir, g, host, stamp) for g in manifest["groups"] if g["id"] not in keep]


def failure_fingerprint(results: list[dict]) -> str:
    bad = sorted(f"{r['id']}:{r['status']}:{r.get('reason') or ''}" for r in results if r.get("status") not in GOOD)
    return hashlib.sha256(json.dumps(bad).encode()).hexdigest()[:16]


def telegram_p1(body: str) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from telegram_alert import send_telegram_outcome

    return send_telegram_outcome(body, priority="P1", dedupe_minutes=0, producer=NOTIFY_PRODUCER,
                                 message_class="operator_alert")


def notify_failure(receipt: dict, state: dict, sender) -> dict:
    """One P1 per distinct failure (fingerprint in the state file); a recovery clears it. Delivery is receipted."""
    fp = failure_fingerprint(receipt["groups"])
    if receipt["ok"]:
        state.pop("notified_failure", None)
        return {"status": "NOT_REQUIRED", "delivered": False}
    if (state.get("notified_failure") or {}).get("fingerprint") == fp:
        return {"status": "DUPLICATE_SUPPRESSED", "delivered": False, "fingerprint": fp}
    lines = [f"{r['id']}: {r['status']}" + (f" — {r.get('reason')}" if r.get("reason") else "")
             for r in receipt["groups"] if r.get("status") not in GOOD]
    body = ("STAGED UNIT INSTALL FAILED · action required\n" + "\n".join(lines)[:1500]
            + f"\nRelease {receipt['release']}\nReceipt {RECEIPT}; the release itself stays live."
            + "\nInspect: scripts/install_staged_units.py plan --release <CURRENT>")
    try:
        outcome = sender(body)
    except Exception:  # noqa: BLE001 — a failed send is receipted, never raised
        outcome = {"status": "FAILED", "delivered": False}
    outcome = outcome if isinstance(outcome, dict) else {"status": "UNCONFIRMED", "delivered": False}
    result = {k: outcome.get(k) for k in ("status", "accepted", "delivered")}
    result["fingerprint"] = fp
    if outcome.get("delivered") is True or outcome.get("accepted") is True:
        state["notified_failure"] = {"fingerprint": fp, "at": iso(now_utc())}
    return result


GOOD = {"UNCHANGED", "INSTALLED", "PENDING_ADMISSION", "WOULD_INSTALL", "ROLLED_BACK", "NOTHING_INSTALLED"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("mode", nargs="?", default="plan", choices=("plan", "apply", "rollback", "retire"))
    ap.add_argument("--target", type=Path, help="retire: the release being rolled back to")
    ap.add_argument("--no-notify", action="store_true", help="never send the failure P1 (proofs)")
    ap.add_argument("--release", type=Path, required=True, help="the release dir whose manifest/units are installed")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST, help="release-relative manifest path")
    ap.add_argument("--unit-dir", type=Path, default=Path.home() / ".config/systemd/user")
    ap.add_argument("--state-root", type=Path,
                    default=Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases/persistent-state"))
    ap.add_argument("--group", action="append", help="limit to these group ids")
    args = ap.parse_args(argv)
    release = args.release.resolve()
    try:
        manifest = json.loads((release / args.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "reason": f"manifest unreadable: {exc}"}))
        return 2
    errs = validate_manifest(manifest)
    if errs:
        print(json.dumps({"ok": False, "reason": "manifest invalid", "errors": errs}))
        return 2
    groups = [g for g in manifest["groups"] if not args.group or g["id"] in args.group]
    host = Host()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    state_path = args.state_root / STATE
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    results = []
    if args.mode == "retire":
        if not args.target:
            print(json.dumps({"ok": False, "reason": "retire needs --target"}))
            return 2
        results = retire_groups(release, args.target.resolve(), manifest, args.unit_dir, host, stamp)
    for g in groups if args.mode != "retire" else []:
        if args.mode == "rollback":
            results.append(rollback_group(release, args.unit_dir, g, host, stamp))
        else:
            results.append(apply_group(release, args.unit_dir, args.state_root, g, state, host, stamp,
                                       plan=args.mode == "plan"))
    receipt = {"schema": "StagedUnitsInstall@v1", "mode": args.mode, "at": iso(now_utc()), "release": str(release),
               "unit_dir": str(args.unit_dir), "ok": all(r["status"] in GOOD for r in results),
               "groups": results, "systemctl_calls": host.calls}
    if args.mode != "plan":
        receipt["notification"] = (notify_failure(receipt, state, telegram_p1) if not args.no_notify
                                   else {"status": "NOT_REQUESTED", "delivered": False})
        atomic_json(state_path, state)
        atomic_json(args.state_root / RECEIPT, receipt)
    else:
        print(json.dumps(receipt, indent=2))
    for r in results:
        print(f"{r['id']}: {r['status']}" + (f" — {r.get('reason')}" if r.get("reason") else "")
              + (f" — {r['verify']['receipt']}" if r.get("verify") else ""))
        if r.get("will_page"):
            print(f"{r['id']}: will page: {', '.join(r['will_page'])[:600]}")
    if receipt.get("notification", {}).get("status") not in (None, "NOT_REQUIRED", "NOT_REQUESTED"):
        print(f"failure P1: {receipt['notification'].get('status')}")
    print("receipt → " + (str(args.state_root / RECEIPT) if args.mode != "plan" else "(plan: nothing written)"))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

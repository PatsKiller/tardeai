#!/usr/bin/env python3
"""OPERATOR-ONLY system-unit packet. No daemon, broker, server or credential calls in tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, time as walltime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
UNIT = "tradeai-continuous.service"
TIMER = "tradeai-continuous.timer"
CANONICAL = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PORTFOLIO = Path("/home/johnclaw/trade-ai-releases/portfolio-server")
CURRENT = PORTFOLIO / "CURRENT"
PERSISTENT = Path("/home/johnclaw/trade-ai-releases/persistent-state")
MANAGED = Path("/etc/systemd/system/tradeai-continuous.service.d/zzzz-wp27-current.conf")
RECEIPTS = Path("/var/lib/tradeai/operator-packets/continuous-from-current-20261023")
LOCK = "/run/lock/tradeai-continuous.lock"
OLD_ARGV = ["/usr/bin/flock", "-n", "-E", "0", LOCK, CANONICAL + "/linux_launchers/run_continuous.sh"]
NEW_ARGV = [
    "/usr/bin/flock",
    "-n",
    "-E",
    "0",
    LOCK,
    "/usr/bin/env",
    f"PROJECT_ROOT={CURRENT}",
    str(CURRENT / "linux_launchers/run_continuous.sh"),
]
PROPERTIES = "FragmentPath,DropInPaths,MainPID,WorkingDirectory,ExecStart,ActiveState,SubState,User"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def outside_window(now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("zoned clock required")
    et = now.astimezone(ZoneInfo("America/New_York"))
    # Conservative: blocks holidays too. No calendar/network/env override can widen it.
    if et.weekday() < 5 and walltime(4) <= et.time() < walltime(16, 15):
        raise ValueError("refused during weekday 04:00–16:15 America/New_York")


def argv_from_show(value: str) -> list[str]:
    match = re.fullmatch(r"\{ path=[^;]+ ; argv\[\]=(.*?) ; ignore_errors=(?:yes|no) ; .* \}", value)
    if not match:
        raise ValueError("unexpected systemd ExecStart format; operator review/rebuild required")
    return shlex.split(match.group(1))


def validate_config(snapshot: dict) -> None:
    config = snapshot["config"]
    if config["User"] != "johnclaw":
        raise ValueError("unexpected service user")
    if config["argv"] not in (OLD_ARGV, NEW_ARGV):
        raise ValueError("unexpected ExecStart; exact flock lock/arguments must be reviewed")
    if config["WorkingDirectory"] not in (CANONICAL, str(CURRENT), snapshot["release"]["path"]):
        raise ValueError("unexpected WorkingDirectory")


def require_fresh(preview: dict, now: datetime, current: dict) -> None:
    if preview.get("schema") != "ContinuousCurrentPreview@v1":
        raise ValueError("not a preview receipt")
    age = (now - datetime.fromisoformat(preview["at"])).total_seconds()
    if age < 0 or age > 900:
        raise ValueError("preview expired/future; capture a fresh preview")
    if preview["snapshot"]["config"] != current["config"] or preview["snapshot"]["release"] != current["release"]:
        raise ValueError("unit configuration or CURRENT changed since preview")
    if preview["payload_sha256"] != digest((HERE / "continuous-current.conf").read_bytes()):
        raise ValueError("payload changed since preview")


class Host:
    """Real host adapter; never constructed/called by fixture tests."""

    def command(self, *args: str) -> str:
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()

    def properties(self, unit=UNIT):
        raw = self.command("systemctl", "show", unit, "--property=" + PROPERTIES)
        return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)

    def release(self):
        if not CURRENT.is_symlink():
            raise ValueError("CURRENT must be the release symlink")
        path = CURRENT.resolve(strict=True)
        if path.parent != PORTFOLIO or not (path / "linux_launchers/run_continuous.sh").is_file():
            raise ValueError("CURRENT target/launcher invalid")
        sha = (path / "BUILD_SHA").read_text().strip()
        if not re.fullmatch(r"[a-f0-9]{40}", sha) or not path.name.startswith(sha[:9] + "-"):
            raise ValueError("CURRENT BUILD_SHA does not match release identity")
        for suffix in ("logs", "data/runtime", "data/cio"):
            if (path / suffix).resolve(strict=True) != PERSISTENT / suffix:
                raise ValueError(f"store path differs from persistent state: {suffix}")
        return {"path": str(path), "sha": sha}

    def snapshot(self):
        props = self.properties()
        timer = dict(
            line.split("=", 1)
            for line in self.command(
                "systemctl", "show", TIMER, "--property=FragmentPath,ActiveState,SubState,UnitFileState"
            ).splitlines()
            if "=" in line
        )
        if props.get("FragmentPath") != "/etc/systemd/system/tradeai-continuous.service":
            raise ValueError("unexpected system fragment path")
        paths = [props["FragmentPath"], *shlex.split(props.get("DropInPaths", ""))]
        hashes = {}
        for name in paths:
            path = Path(name)
            if not path.is_absolute() or path.is_symlink():
                raise ValueError("unit source must be a regular absolute file")
            hashes[name] = digest(path.read_bytes())
        config = {
            "User": props.get("User"),
            "WorkingDirectory": props.get("WorkingDirectory"),
            "argv": argv_from_show(props.get("ExecStart", "")),
            "files": hashes,
        }
        return {
            "config": config,
            "release": self.release(),
            "runtime": {
                "active": props.get("ActiveState"),
                "sub": props.get("SubState"),
                "pid": int(props.get("MainPID", "0")),
                "timer": timer,
            },
        }

    def folder(self):
        RECEIPTS.mkdir(parents=True, exist_ok=True, mode=0o700)
        if RECEIPTS.is_symlink() or RECEIPTS.stat().st_uid != 0:
            raise ValueError("receipt root must be root-owned, not symlinked")
        RECEIPTS.chmod(0o700)
        return Path(tempfile.mkdtemp(prefix="run-", dir=RECEIPTS))

    def save(self, folder, name, value):
        path = folder / name
        with path.open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        path.chmod(0o600)
        return path

    def load(self, path):
        original = Path(path)
        path = original.resolve(strict=True)
        if original.is_symlink() or path.parent.parent != RECEIPTS or path.stat().st_uid != 0:
            raise ValueError("receipt must be root-owned inside the packet receipt root")
        if path.stat().st_mode & 0o077:
            raise ValueError("receipt must be private (0600)")
        return json.loads(path.read_text())

    def install(self, folder):
        MANAGED.parent.mkdir(parents=True, exist_ok=True)
        if MANAGED.parent.is_symlink() or MANAGED.is_symlink():
            raise ValueError("managed drop-in must not be a symlink")
        existed = MANAGED.exists()
        if existed:
            shutil.copy2(MANAGED, folder / "before.conf")
        payload = (HERE / "continuous-current.conf").read_bytes()
        pending = folder / "installed.conf"
        pending.write_bytes(payload)
        pending.chmod(0o644)
        # Same /etc destination; never overwrite another packet's managed file.
        if existed and MANAGED.read_bytes() != payload:
            raise ValueError("managed drop-in differs; inspect it rather than overwrite")
        descriptor, name = tempfile.mkstemp(prefix=".wp27-", dir=MANAGED.parent)
        os.close(descriptor)
        temporary = Path(name)
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, MANAGED)
        return {"existed": existed, "sha256": digest(payload), "managed": str(MANAGED)}

    def reload(self):
        self.command("systemctl", "daemon-reload")

    def restart(self):
        self.command("systemctl", "restart", UNIT)

    def proof(self, expected: str):
        # PID identity and MainPID checked on both sides to reject restart/PID reuse races.
        for _ in range(20):
            props = self.properties()
            pid = int(props.get("MainPID", "0"))
            if props.get("ActiveState") == "active" and pid > 0:
                proc = Path("/proc") / str(pid)
                try:
                    first = (proc / "stat").read_text()
                    cwd = os.readlink(proc / "cwd")
                    second = (proc / "stat").read_text()
                    again = self.properties()
                    start1 = first[first.rfind(")") + 2 :].split()[19]
                    start2 = second[second.rfind(")") + 2 :].split()[19]
                    if cwd == expected and start1 == start2 and again.get("MainPID") == str(pid):
                        return {"passed": True, "pid": pid, "cwd": cwd, "start_ticks": start1}
                except (OSError, IndexError):
                    pass
            time.sleep(1)
        raise ValueError("no stable active MainPID with expected cwd; installed config is not runtime proof")

    def rollback(self, receipt_path, receipt):
        managed = receipt["installed"]
        if (
            managed["managed"] != str(MANAGED)
            or MANAGED.is_symlink()
            or digest(MANAGED.read_bytes()) != managed["sha256"]
        ):
            raise ValueError("managed drop-in drift; refusing rollback")
        folder = Path(receipt_path).parent
        # Archive, never delete. Restore only our exact prior drop-in.
        retired = folder / "retired-installed.conf"
        if retired.exists():
            raise ValueError("rollback already attempted; inspect archived state")
        if managed["existed"]:
            before = folder / "before.conf"
            if digest(before.read_bytes()) != receipt["before_dropin_sha256"]:
                raise ValueError("rollback backup digest mismatch")
        shutil.copy2(MANAGED, retired)
        archived = MANAGED.with_name(MANAGED.name + ".archived-" + folder.name)
        if archived.exists():
            raise ValueError("archive destination exists")
        MANAGED.rename(archived)
        if managed["existed"]:
            shutil.copy2(before, MANAGED)


def registry_proposal(snapshot, now):
    """A review-only system-scope row; never changes operative registry or the user timer."""
    timer = snapshot["runtime"].get("timer", {})
    enabled = timer.get("UnitFileState") == "enabled" and timer.get("ActiveState") == "active"
    return {
        "lane_id": "tradeai-continuous-system",
        "owner": "platform",
        "scheduler": {"kind": "systemd", "expression": TIMER, "scope": "system"},
        "expected_cadence_hours": 24.0,
        "state": "ACTIVE" if enabled else "PAUSED",
        "state_since": now.date().isoformat(),
        "state_reason": "Operator preview observed system timer "
        + ("enabled and active" if enabled else "not both enabled and active"),
        "output_signal": {"kind": "none"},
        "reason_confidence": "ESTABLISHED",
        "reason_evidence": "Privileged WP-27 preview metadata; runtime/output acceptance remains separate. Preserve the existing PAUSED user-timer row; no timer is enabled by this packet.",
    }


def preview(host, now):
    outside_window(now)
    snapshot = host.snapshot()
    validate_config(snapshot)
    folder = host.folder()
    receipt = {
        "schema": "ContinuousCurrentPreview@v1",
        "at": now.isoformat(),
        "snapshot": snapshot,
        "payload_sha256": digest((HERE / "continuous-current.conf").read_bytes()),
    }
    host.save(folder, "registry-proposal.json", registry_proposal(snapshot, now))
    return host.save(folder, "preview.json", receipt)


def apply(host, now, approved_preview, *, restart=False):
    outside_window(now)
    old = host.load(approved_preview)
    current = host.snapshot()
    validate_config(current)
    require_fresh(old, now, current)
    folder = host.folder()
    receipt = {
        "schema": "ContinuousCurrentInstall@v1",
        "at": now.isoformat(),
        "before": current,
        "approved_preview": str(approved_preview),
        "status": "APPLY_STARTED",
        "restart_requested": restart,
    }
    host.save(folder, "started.json", receipt)
    outside_window(host.now())
    receipt["installed"] = host.install(folder)
    receipt["before_dropin_sha256"] = current["config"]["files"].get(str(MANAGED))
    recovery = host.save(folder, "installed-before-reload.json", receipt)
    print(f"RECOVERY_RECEIPT={recovery}", file=sys.stderr)
    outside_window(host.now())
    host.reload()
    installed = host.snapshot()
    if installed["config"]["argv"] != NEW_ARGV or installed["config"]["WorkingDirectory"] != str(CURRENT):
        receipt["status"] = "CONFIGURATION_FAILED"
        host.save(folder, "failed.json", receipt)
        raise ValueError("effective unit does not use expected CURRENT launch; inspect receipt")
    if installed["release"] != current["release"]:
        receipt["status"] = "CURRENT_CHANGED"
        host.save(folder, "failed.json", receipt)
        raise ValueError("CURRENT changed during install; no restart performed")
    receipt["status"] = "CONFIGURED_PENDING_RESTART_OR_NATURAL_FIRE"
    if restart:
        # Recheck the actual clock immediately before the sole runtime mutation.
        outside_window(host.now())
        host.restart()
        try:
            receipt["runtime_proof"] = host.proof(current["release"]["path"])
            final = host.snapshot()
            if final["release"] != current["release"] or final["config"] != installed["config"]:
                raise ValueError("CURRENT or unit changed during PID proof")
            receipt["runtime_proof"]["verified_at"] = host.now().isoformat()
            receipt["status"] = "RUNNING_FROM_VERIFIED_CURRENT"
        except ValueError as exc:
            receipt["status"] = "RUNTIME_PROOF_FAILED"
            host.save(folder, "failed.json", receipt)
            raise ValueError(f"{exc}; operator may preview rollback") from exc
    return host.save(folder, "installed.json", receipt)


def rollback(host, now, receipt_path, *, apply_change=False, restart=False):
    outside_window(now)
    receipt = host.load(receipt_path)
    if receipt.get("schema") != "ContinuousCurrentInstall@v1" or "installed" not in receipt:
        raise ValueError("not an installation receipt")
    if not apply_change:
        return {
            "status": "ROLLBACK_PREVIEW",
            "managed": receipt["installed"]["managed"],
            "restore_previous": receipt["installed"]["existed"],
            "restart": restart,
        }
    outside_window(host.now())
    host.rollback(receipt_path, receipt)
    outside_window(host.now())
    host.reload()
    proof = None
    if restart:
        outside_window(host.now())
        host.restart()
        expected = receipt["before"]["config"]["WorkingDirectory"]
        if expected == str(CURRENT):
            expected = host.release()["path"]
        proof = host.proof(expected)
    folder = host.folder()
    return host.save(
        folder,
        "rollback.json",
        {"schema": "ContinuousCurrentRollback@v1", "at": now.isoformat(), "receipt": str(receipt_path), "proof": proof},
    )


def confirm(phrase):
    if not sys.stdin.isatty() or input(f"Type {phrase}: ") != phrase:
        raise ValueError("operator TTY and exact typed phrase required")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "rollback", "check"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-preview")
    parser.add_argument("--receipt")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("system unit: run these operator commands through sudo")
    host = Host()
    host.now = lambda: datetime.now(timezone.utc)
    now = host.now()
    outside_window(now)
    if args.action == "check":
        release = host.release()
        proof = host.proof(release["path"])
        if host.release() != release:
            raise ValueError("CURRENT changed during PID proof")
        proof["verified_at"] = host.now().isoformat()
        print(json.dumps(proof, indent=2))
    elif args.action == "rollback":
        if not args.receipt:
            raise ValueError("rollback requires the exact installation receipt")
        if args.apply:
            confirm("ROLLBACK-CONTINUOUS-CURRENT")
        result = rollback(host, host.now(), args.receipt, apply_change=args.apply, restart=args.restart)
        print(json.dumps(result) if isinstance(result, dict) else result)
    elif args.apply:
        if not args.approved_preview:
            raise ValueError("apply requires --approved-preview")
        confirm("INSTALL-CONTINUOUS-CURRENT")
        # Re-capture clock after the operator's input, before the first write.
        print(apply(host, host.now(), args.approved_preview, restart=args.restart))
    else:
        print(preview(host, now))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"REFUSED: {exc}")

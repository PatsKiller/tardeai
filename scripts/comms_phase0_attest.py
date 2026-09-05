#!/usr/bin/env python3
"""Phase 0 communications gateway runtime attestation helper.

Captures SHA, normalization mode, chokepoint ratchet status, and systemd/crontab
hints into docs/audit/_evidence/. Does not print secret values.

Usage (from repo root or CURRENT):
  PYTHONPATH=scripts python3 scripts/comms_phase0_attest.py
  PYTHONPATH=scripts python3 scripts/comms_phase0_attest.py --out docs/audit/_evidence
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        return (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    except Exception as e:
        return f"[error] {e}\n"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None, help="Evidence output directory")
    ap.add_argument(
        "--current",
        type=Path,
        default=Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"),
        help="Live CURRENT release path (optional)",
    )
    args = ap.parse_args()
    root = _repo_root()
    out = args.out or (root / "docs" / "audit" / "_evidence")
    out.mkdir(parents=True, exist_ok=True)

    attested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = args.current if args.current.is_dir() else root

    sha_lines = [
        f"attested_at_utc={attested_at}",
        f"attestation_root={root}",
        f"CURRENT_path={cur}",
        f"CURRENT_realpath={cur.resolve() if cur.exists() else ''}",
        f"SOURCE_COMMIT={_read_text(cur / 'SOURCE_COMMIT')}",
        f"GIT_SHA={_read_text(cur / 'GIT_SHA')}",
        f"BUILD_SHA={_read_text(cur / 'BUILD_SHA')}",
        f"worktree_HEAD={_run(['git', 'rev-parse', 'HEAD'], cwd=root).strip()}",
    ]
    (out / "sha_attestation.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    # Normalization mode (best-effort)
    mode_path = out / "normalization_mode.json"
    try:
        sys.path.insert(0, str((cur if (cur / "scripts").is_dir() else root) / "scripts"))
        from alert_runtime_mode import mode_diagnostics  # type: ignore

        mode_path.write_text(json.dumps(mode_diagnostics(), indent=2, default=str) + "\n", encoding="utf-8")
    except Exception as e:
        mode_path.write_text(json.dumps({"error": str(e)}, indent=2) + "\n", encoding="utf-8")

    # Chokepoint report
    checker = (cur / "scripts" / "check_telegram_chokepoint.py")
    if not checker.is_file():
        checker = root / "scripts" / "check_telegram_chokepoint.py"
    if checker.is_file():
        report = _run([sys.executable, str(checker), "--report"], cwd=checker.parent.parent)
        (out / "chokepoint_report_live.txt").write_text(report, encoding="utf-8")
        baseline = checker.parent.parent / "config" / "telegram_chokepoint_baseline.json"
        if baseline.is_file():
            (out / "telegram_chokepoint_baseline.json").write_text(
                baseline.read_text(encoding="utf-8"), encoding="utf-8"
            )

    # systemd / crontab (names only)
    (out / "systemd_timers.txt").write_text(
        _run(["bash", "-lc", "systemctl --user list-timers --all 2>/dev/null | rg -i 'cio|telegram|delivery|notif|advisory|alert' || true"]),
        encoding="utf-8",
    )
    (out / "systemd_units.txt").write_text(
        _run(["bash", "-lc", "systemctl --user list-units --all 2>/dev/null | rg -i 'cio|telegram|delivery|notif|advisory|alert' || true"]),
        encoding="utf-8",
    )
    (out / "crontab_full.txt").write_text(
        _run(["bash", "-lc", "crontab -l 2>/dev/null || true"]),
        encoding="utf-8",
    )

    summary = {
        "attested_at_utc": attested_at,
        "out": str(out),
        "SOURCE_COMMIT": _read_text(cur / "SOURCE_COMMIT"),
        "hint": "Review docs/audit/_evidence then refresh docs/audit/*.md",
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

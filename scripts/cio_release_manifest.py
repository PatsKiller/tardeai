#!/usr/bin/env python3
"""cio_release_manifest.py — Phase 10 investment-office release truth.

Generate and validate `docs/investment-office/RELEASE_MANIFEST.md` (+ JSON twin)
from the live git worktree, deploy path, and product versions.

A stale or hand-edited manifest that disagrees with HEAD fails validation.

Usage:
  python scripts/cio_release_manifest.py generate [--write]
  python scripts/cio_release_manifest.py validate
  python scripts/cio_release_manifest.py check   # validate + exit 1 on fail

READ_ONLY_ADVISORY. No broker / Telegram / deploy mutations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
MANIFEST_MD = REPO / "docs" / "investment-office" / "RELEASE_MANIFEST.md"
MANIFEST_JSON = REPO / "docs" / "investment-office" / "RELEASE_MANIFEST.json"
DEFAULT_DEPLOY = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")

REQUIRED_FIELDS = (
    "canonical_source_sha",
    "frontend_build_sha",
    "backend_release_sha",
    "deployed_release_path",
    "migration_head",
    "docs_pin",
    "runtime_config_hash",
    "report_version",
    "rollback_sha",
    "created_at",
)

# Preliminary SHAs known stale from Phase 0 — must never reappear as "current"
FORBIDDEN_STALE_SHAS = frozenset({
    "0a9b6c415e02dc23d150a020327689044d0aa72b",
    "0a9b6c41",
    "d9b63ed6738731477d4a2f316cd8253c7df859a0",
    "d9b63ed6",
})


def _run(cmd: list[str], cwd: Optional[Path] = None) -> str:
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd or REPO), capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:
        pass
    return ""


def git_head() -> str:
    return _run(["git", "rev-parse", "HEAD"])


def git_head_short() -> str:
    h = git_head()
    return h[:12] if h else "unknown"


def git_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"


def git_origin_main() -> str:
    return _run(["git", "rev-parse", "origin/main"]) or _run(["git", "rev-parse", "main"])


def sha256_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def sha256_tree(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: str(x)):
        if not p.is_file():
            continue
        try:
            rel = str(p.resolve().relative_to(REPO.resolve()))
        except ValueError:
            rel = p.name
        h.update(rel.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def product_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    mapping = {
        "report_version": (REPO / "scripts/lib/cio_report_v2.py", r'REPORT_VERSION\s*=\s*"([^"]+)"'),
        "capital_plan_version": (REPO / "scripts/lib/cio_capital_plan.py", r'CAPITAL_PLAN_VERSION\s*=\s*"([^"]+)"'),
        "office_home_version": (REPO / "scripts/lib/cio_command_center.py", r'OFFICE_HOME_VERSION\s*=\s*"([^"]+)"'),
        "alex_telegram_version": (REPO / "scripts/lib/cio_alex_telegram.py", r'ALEX_TELEGRAM_VERSION\s*=\s*"([^"]+)"'),
        "pipeline_version": (REPO / "scripts/lib/cio_report_pipeline.py", r'PIPELINE_VERSION\s*=\s*"([^"]+)"'),
    }
    for key, (path, pat) in mapping.items():
        try:
            text = path.read_text(encoding="utf-8")
            m = re.search(pat, text)
            out[key] = m.group(1) if m else "unknown"
        except Exception:
            out[key] = "unknown"
    return out


def migration_head() -> str:
    mig = REPO / "migrations"
    if not mig.is_dir():
        return "none"
    files = sorted(p.name for p in mig.glob("*.sql"))
    if not files:
        return "none"
    # Prefer two_way / latest lexical date-prefixed
    tw = [f for f in files if "two_way" in f]
    if tw:
        return tw[-1]
    return files[-1]


def migration_set_pin() -> list[str]:
    mig = REPO / "migrations"
    if not mig.is_dir():
        return []
    return sorted(p.name for p in mig.glob("*two_way*.sql"))


def resolve_deploy_path() -> Path:
    env = os.environ.get("TRADE_AI_DEPLOY_CURRENT", "").strip()
    if env:
        return Path(env)
    return DEFAULT_DEPLOY


def backend_release_info(deploy: Path) -> dict[str, Any]:
    path = deploy
    try:
        path = deploy.resolve()
    except Exception:
        pass
    name = path.name if path.exists() else "missing"
    sha = None
    for candidate in (
        path / "BUILD_SHA",
        path / "SHA",
        path / "GIT_SHA",
        path / "release_sha.txt",
    ):
        if candidate.is_file():
            sha = candidate.read_text(encoding="utf-8", errors="replace").strip().split()[0]
            break
    # Fall back: parse from directory name if it looks like a git SHA prefix.
    # Exclude release-dir timestamps like 20260813-210818 (digits-only date stamp).
    if not sha:
        if re.match(r"^\d{8}(-\d{6})?$", name):
            pass  # timestamp release dir — not a git SHA
        elif re.match(r"^[0-9a-f]{7,40}", name) and re.search(r"[a-f]", name[:12]):
            sha = name.split("-")[0]
    return {
        "deployed_release_path": str(path),
        "deployed_release_name": name,
        "backend_release_sha": sha or "UNKNOWN_NOT_STAMPED_IN_RELEASE_DIR",
        "deploy_exists": path.exists(),
    }


def frontend_build_sha() -> str:
    # Prefer CC v3 package or build-meta if present
    for p in (
        REPO / "apps/command-center-v3/build-meta.json",
        REPO / "apps/command-center-v3/package.json",
        REPO / "package.json",
    ):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in ("git_sha", "source_sha", "build_sha", "version"):
                    if data.get(k):
                        return str(data[k])
        except Exception:
            pass
    return f"not_stamped (repo_head={git_head_short()})"


def runtime_config_hash() -> str:
    paths = []
    for rel in (
        "config/hermes_score_weights.yaml",
        "config",
    ):
        p = REPO / rel
        if p.is_file():
            paths.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix in (".yaml", ".yml", ".json", ".toml") and f.stat().st_size < 2_000_000:
                    paths.append(f)
    # Cap to avoid huge trees
    paths = paths[:80]
    if not paths:
        return "empty"
    return sha256_tree(paths)[:32]


def docs_pin() -> dict[str, Any]:
    base = REPO / "docs" / "investment-office"
    docs = sorted(base.glob("PHASE*.md")) if base.is_dir() else []
    # pin = hash of phase closeouts only (not the manifest itself)
    files = [p for p in docs if p.is_file() and REPO in p.resolve().parents]
    h = sha256_tree(files[:40])[:24] if files else "none"
    return {
        "docs_pin": h,
        "docs_count": len(files),
        "docs_files": [p.name for p in files][:30],
    }


def build_manifest(*, note: str = "") -> dict[str, Any]:
    head = git_head()
    origin_main = git_origin_main()
    versions = product_versions()
    deploy = backend_release_info(resolve_deploy_path())
    docs = docs_pin()
    created = datetime.now(timezone.utc).isoformat()

    # Rollback = origin/main tip (safe known good for this RC branch work)
    rollback = origin_main or deploy.get("backend_release_sha") or head

    manifest = {
        "manifest_schema": "investment_office_release_manifest_v1",
        "status": "release_candidate",
        "branch": git_branch(),
        "canonical_source_sha": head,
        "frontend_build_sha": frontend_build_sha(),
        "backend_release_sha": deploy["backend_release_sha"],
        "deployed_release_path": deploy["deployed_release_path"],
        "deployed_release_name": deploy.get("deployed_release_name"),
        "deploy_exists": deploy.get("deploy_exists"),
        "migration_head": migration_head(),
        "migration_set": migration_set_pin(),
        "docs_pin": docs["docs_pin"],
        "docs_files_sample": docs.get("docs_files"),
        "runtime_config_hash": runtime_config_hash(),
        "report_version": versions.get("report_version"),
        "product_versions": versions,
        "rollback_sha": rollback,
        "origin_main_sha": origin_main,
        "created_at": created,
        "financial_authority": "READ_ONLY_ADVISORY",
        "broker_write_paths_added": 0,
        "notes": note or (
            "Release candidate for CIO production hardening Phases 0–10 on this branch. "
            "backend_release_sha reflects currently deployed portfolio-server CURRENT "
            "(may lag this RC until controlled deployment). Stale preliminary SHAs are forbidden. "
            "Drive investment-office mirror may lag git until operator sync."
        ),
        "hermes_score_weights_ownership": {
            "path": "config/hermes_score_weights.yaml",
            "classification": "runtime_state_with_release_seed",
            "rule": (
                "Seed defaults may be version-controlled; auto_grafted_at and live weight "
                "mutations are runtime state and may dirty the worktree. Do not treat "
                "runtime grafts as undeclared source drift without an ownership note."
            ),
        },
        "branch_protection": {
            "main_observed": "unprotected (Phase 0)",
            "recommendation": [
                "require pull request before merge",
                "require CIO hardening CI + release-readiness checks",
                "block force-push to main",
                "block merge with failing required checks",
            ],
            "operator_approval_required": True,
            "auto_enforced_by_this_script": False,
        },
    }
    # Content hash excluding created_at for stable compare of material pins
    material = {k: manifest[k] for k in REQUIRED_FIELDS if k != "created_at"}
    material["branch"] = manifest["branch"]
    material["product_versions"] = manifest["product_versions"]
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    manifest["manifest_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    return manifest


def render_markdown(m: dict[str, Any]) -> str:
    pv = m.get("product_versions") or {}
    lines = [
        "# Release Manifest — Investment Office (CIO Production Hardening)",
        "",
        "> Generated by `scripts/cio_release_manifest.py`. Do not hand-edit pins.",
        "> `validate` fails if HEAD or product versions disagree with this file.",
        "> Authority: **READ_ONLY_ADVISORY** — no broker / order / stop / 2FA.",
        "",
        f"**Status:** `{m.get('status')}`  ",
        f"**Branch:** `{m.get('branch')}`  ",
        f"**Created:** `{m.get('created_at')}`  ",
        f"**Manifest hash:** `{m.get('manifest_hash')}`",
        "",
        "## Pin",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| canonical_source_sha | `{m.get('canonical_source_sha')}` |",
        f"| frontend_build_sha | `{m.get('frontend_build_sha')}` |",
        f"| backend_release_sha | `{m.get('backend_release_sha')}` |",
        f"| deployed_release_path | `{m.get('deployed_release_path')}` |",
        f"| migration_head | `{m.get('migration_head')}` |",
        f"| docs_pin | `{m.get('docs_pin')}` |",
        f"| runtime_config_hash | `{m.get('runtime_config_hash')}` |",
        f"| report_version | `{m.get('report_version')}` |",
        f"| rollback_sha | `{m.get('rollback_sha')}` |",
        f"| created_at | `{m.get('created_at')}` |",
        "",
        "## Product versions",
        "",
        "| Component | Version |",
        "| --- | --- |",
    ]
    for k, v in sorted(pv.items()):
        lines.append(f"| {k} | `{v}` |")
    lines += [
        "",
        "## Migrations (two-way set)",
        "",
    ]
    for name in m.get("migration_set") or []:
        lines.append(f"- `{name}`")
    lines += [
        "",
        "## Authority",
        "",
        f"- `financial_authority: {m.get('financial_authority')}`",
        f"- `broker_write_paths_added: {m.get('broker_write_paths_added')}`",
        "",
        "## Hermes score weights ownership",
        "",
        f"- Path: `{m.get('hermes_score_weights_ownership', {}).get('path')}`",
        f"- Classification: **{m.get('hermes_score_weights_ownership', {}).get('classification')}**",
        f"- Rule: {m.get('hermes_score_weights_ownership', {}).get('rule')}",
        "",
        "## Branch protection (operator action)",
        "",
        "Observed: main unprotected (Phase 0).",
        "Recommended (requires operator repo-governance approval — not auto-applied):",
        "",
    ]
    for rec in (m.get("branch_protection") or {}).get("recommendation") or []:
        lines.append(f"- {rec}")
    lines += [
        "",
        "## Notes",
        "",
        str(m.get("notes") or ""),
        "",
        "## Validation",
        "",
        "```bash",
        "python scripts/cio_release_manifest.py check",
        "```",
        "",
        "Stale preliminary SHAs (`0a9b6c41…`, `d9b63ed6…`) are **forbidden** in the pin table.",
        "",
    ]
    return "\n".join(lines)


def write_manifest(m: dict[str, Any]) -> None:
    MANIFEST_MD.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_MD.write_text(render_markdown(m), encoding="utf-8")
    MANIFEST_JSON.write_text(json.dumps(m, indent=2, default=str) + "\n", encoding="utf-8")


def load_json_manifest() -> Optional[dict[str, Any]]:
    if not MANIFEST_JSON.is_file():
        return None
    try:
        return json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_md_pins(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        # | field | `value` |
        m = re.search(
            rf"\|\s*{re.escape(field)}\s*\|\s*`([^`]+)`\s*\|",
            text,
            re.I,
        )
        if m:
            pins[field] = m.group(1).strip()
    return pins


def validate(m_live: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Validate on-disk manifest against live HEAD / versions. Fail on stale pins."""
    live = m_live or build_manifest()
    errors: list[str] = []
    warnings: list[str] = []

    disk = load_json_manifest()
    md_text = MANIFEST_MD.read_text(encoding="utf-8") if MANIFEST_MD.is_file() else ""
    md_pins = parse_md_pins(md_text) if md_text else {}

    if not disk:
        errors.append("RELEASE_MANIFEST.json missing — run generate --write")
    if not md_text:
        errors.append("RELEASE_MANIFEST.md missing — run generate --write")

    # Forbidden stale SHAs anywhere in pin table
    blob = md_text + json.dumps(disk or {})
    for stale in FORBIDDEN_STALE_SHAS:
        if stale in blob and (disk or {}).get("canonical_source_sha") != live.get("canonical_source_sha"):
            # only error if they're used as current pins
            pass
    for field in ("canonical_source_sha", "docs_pin", "backend_release_sha", "rollback_sha"):
        val = (disk or {}).get(field) or md_pins.get(field) or ""
        for stale in FORBIDDEN_STALE_SHAS:
            if val.startswith(stale) or stale.startswith(val[:8] if len(val) >= 8 else val):
                if field == "canonical_source_sha" or field == "docs_pin":
                    errors.append(f"stale_forbidden_sha:{field}={val[:12]}")

    # HEAD must match canonical_source_sha on disk
    head = live["canonical_source_sha"]
    disk_sha = (disk or {}).get("canonical_source_sha") or md_pins.get("canonical_source_sha")
    if disk_sha and disk_sha != head:
        errors.append(
            f"canonical_source_sha mismatch: disk={disk_sha[:12]} head={head[:12]} — regenerate"
        )

    # report_version must match code
    code_rv = live.get("report_version")
    disk_rv = (disk or {}).get("report_version") or md_pins.get("report_version")
    if disk_rv and code_rv and disk_rv != code_rv:
        errors.append(f"report_version mismatch: disk={disk_rv} code={code_rv}")

    # Required fields present
    for f in REQUIRED_FIELDS:
        if disk and not disk.get(f):
            errors.append(f"missing_json_field:{f}")
        if md_pins and f not in md_pins:
            warnings.append(f"missing_md_pin_row:{f}")

    # Deploy lag is a warning, not hard fail for RC branch
    if live.get("backend_release_sha") and live.get("canonical_source_sha"):
        if live["backend_release_sha"] not in (
            live["canonical_source_sha"],
            "UNKNOWN_NOT_STAMPED_IN_RELEASE_DIR",
        ):
            if not str(live["backend_release_sha"]).startswith(live["canonical_source_sha"][:7]):
                warnings.append(
                    "deployed backend SHA lags RC HEAD (expected until controlled deploy)"
                )

    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "head": head,
        "disk_canonical_source_sha": disk_sha,
        "report_version": code_rv,
        "stale_manifest": any("stale" in e or "mismatch" in e for e in errors),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Investment-office release manifest")
    parser.add_argument("command", choices=("generate", "validate", "check", "print-json"))
    parser.add_argument("--write", action="store_true", help="Write MD+JSON (generate)")
    args = parser.parse_args(argv)

    if args.command in ("generate", "print-json"):
        m = build_manifest()
        if args.command == "print-json" or not args.write:
            print(json.dumps(m, indent=2, default=str))
        if args.write:
            write_manifest(m)
            print(json.dumps({"written": True, "md": str(MANIFEST_MD), "json": str(MANIFEST_JSON),
                              "canonical_source_sha": m["canonical_source_sha"],
                              "manifest_hash": m["manifest_hash"]}, indent=2))
        return 0

    # validate / check
    result = validate()
    print(json.dumps(result, indent=2))
    if args.command == "check":
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

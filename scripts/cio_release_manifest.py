#!/usr/bin/env python3
"""cio_release_manifest.py — Phase 10 investment-office release truth.

Generate and validate `docs/investment-office/RELEASE_MANIFEST.md` (+ JSON twin)
from the live git worktree, deploy path, and product versions.

A stale or hand-edited manifest that disagrees with HEAD fails validation.

Usage:
  python scripts/cio_release_manifest.py generate [--write] [--out-dir DIR]
  python scripts/cio_release_manifest.py validate
  python scripts/cio_release_manifest.py check              # full pin vs HEAD
  python scripts/cio_release_manifest.py check-committed    # read-only integrity
  python scripts/cio_release_manifest.py candidate          # write candidate only

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

SCHEMA_V1 = "investment_office_release_manifest_v1"
SCHEMA_V2 = "investment_office_release_manifest_v2"

# v1 pin table — committed historical manifests remain valid without v2 fields.
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

# Explicit identity fields for investment_office_release_manifest_v2.
# Generated manifests always emit these. Committed v1 pins are not rewritten.
V2_EXPLICIT_FIELDS = (
    "status",
    "release_content_sha",
    "release_attestation_sha",
    "remote_main_sha_at_manifest",
    "backend_release_sha",
    "frontend_build_sha",
    "report_source_sha",
    "deployed_release_path",
    "deployed_release_name",
    "manifest_generated_from_sha",
    "manifest_created_at",
    "manifest_hash",
    "rollback_content_sha",
    "financial_authority",
)

CLASS_RUNTIME = "RUNTIME_CONTENT"
CLASS_ATTESTATION = "RELEASE_ATTESTATION_ONLY"
CLASS_UNKNOWN = "UNKNOWN"

PIN_ONLY_PATHS = frozenset({
    "docs/investment-office/RELEASE_MANIFEST.md",
    "docs/investment-office/RELEASE_MANIFEST.json",
})

# Notes must not claim a 3-way exact SHA when main is attestation-only.
SAME_FULL_SHA_NOTE_FRAGMENTS = (
    "Git main, portfolio-server CURRENT, and this manifest pin the same full SHA",
    "Git main, CURRENT, and this manifest pin the same full SHA",
)
ATTESTATION_ONLY_NOTE = (
    "Git main is the release-attestation commit; CURRENT runs the attested content SHA."
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


def classify_release_commit(sha: str) -> dict[str, Any]:
    """RUNTIME_CONTENT vs RELEASE_ATTESTATION_ONLY.

    A pin-only commit (or a merge whose first-parent diff is only RELEASE_MANIFEST*)
    attests the first parent. That first parent is the runtime content SHA.
    Example: faff6ac1 (merge of pin 4bfe90fd) attests content 7986e923.
    """
    sha = (sha or "").strip()
    empty = {
        "class": CLASS_UNKNOWN,
        "sha": sha,
        "first_parent": "",
        "changed": [],
        "extra": [],
        "release_content_sha": sha,
        "release_attestation_sha": sha,
        "attestation_only": False,
        "ok": False,
    }
    if not sha:
        return empty
    parent = _run(["git", "rev-parse", f"{sha}^1"])
    changed: list[str] = []
    if parent:
        changed = [
            ln.strip()
            for ln in _run(["git", "diff", "--name-only", f"{parent}..{sha}"]).splitlines()
            if ln.strip()
        ]
    extra = sorted(set(changed) - set(PIN_ONLY_PATHS))
    if parent and changed and not extra:
        return {
            "class": CLASS_ATTESTATION,
            "sha": sha,
            "first_parent": parent,
            "changed": changed,
            "extra": extra,
            "release_content_sha": parent,
            "release_attestation_sha": sha,
            "attestation_only": True,
            "ok": True,
        }
    return {
        "class": CLASS_RUNTIME if sha else CLASS_UNKNOWN,
        "sha": sha,
        "first_parent": parent,
        "changed": changed,
        "extra": extra,
        "release_content_sha": sha,
        "release_attestation_sha": sha,
        "attestation_only": False,
        "ok": bool(sha),
    }


def resolve_release_identity(
    *,
    head: Optional[str] = None,
    origin_main: Optional[str] = None,
) -> dict[str, Any]:
    """Explicit content vs attestation identity for a generated v2 manifest.

    If HEAD is an attestation merge/pin, content is the attested parent
    (currently 7986e923 when HEAD is faff6ac1). Otherwise content is HEAD.
    Historical committed pins are not rewritten here.
    """
    head_sha = (head if head is not None else git_head()).strip()
    main_sha = (origin_main if origin_main is not None else git_origin_main()).strip()
    head_cls = classify_release_commit(head_sha)
    main_cls = classify_release_commit(main_sha) if main_sha else {
        "class": CLASS_UNKNOWN,
        "attestation_only": False,
        "release_content_sha": "",
        "release_attestation_sha": "",
    }
    content = str(head_cls.get("release_content_sha") or head_sha)
    attestation = str(head_cls.get("release_attestation_sha") or head_sha)
    return {
        "head": head_sha,
        "origin_main": main_sha,
        "head_class": head_cls.get("class"),
        "main_class": main_cls.get("class"),
        "attestation_only": bool(head_cls.get("attestation_only")),
        "release_content_sha": content,
        "release_attestation_sha": attestation,
        "remote_main_sha_at_manifest": main_sha,
        "remote_main_content_sha": str(main_cls.get("release_content_sha") or main_sha),
        "remote_main_attestation_only": bool(main_cls.get("attestation_only")),
        "manifest_generated_from_sha": head_sha,
    }


def notes_claim_same_full_sha(notes: str) -> bool:
    text = notes or ""
    return any(frag in text for frag in SAME_FULL_SHA_NOTE_FRAGMENTS)


def rollback_content_sha_for(rollback_sha: str) -> str:
    cls = classify_release_commit(rollback_sha)
    return str(cls.get("release_content_sha") or rollback_sha or "")


def _sha_matches(a: Any, b: Any) -> bool:
    aa, bb = str(a or "").strip(), str(b or "").strip()
    if not aa or not bb:
        return False
    n = min(len(aa), len(bb), 40)
    if n < 7:
        return False
    return aa[:n] == bb[:n]


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
    # Prefer the BUILT stamp, then the tracked one, then a package version.
    #
    # dist/build-meta.json leads because it is what vite actually produced on this
    # machine, so it reports the artifact that exists rather than a stamp left by
    # some past deploy. The repo copy is now generated-and-ignored
    # (see .gitignore), so on a fresh clone it is absent; without dist ahead of it
    # this function would silently fall through to package.json's "3.0.0" and
    # publish that as frontend_build_sha — a version string masquerading as a
    # commit. validate_committed() only checks the field is non-empty, so nothing
    # would have caught it.
    for p in (
        REPO / "apps/command-center-v3/dist/build-meta.json",
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
    ident = resolve_release_identity()
    head = ident["head"]
    origin_main = ident["origin_main"]
    content_sha = ident["release_content_sha"]
    attestation_sha = ident["release_attestation_sha"]
    attestation_only = bool(ident["attestation_only"])
    versions = product_versions()
    deploy = backend_release_info(resolve_deploy_path())
    docs = docs_pin()
    created = datetime.now(timezone.utc).isoformat()

    # Prefer previous production release as rollback when we are on main production.
    # Fall back to origin/main tip for RC branch work.
    rollback = origin_main or deploy.get("backend_release_sha") or head
    prev_env = os.environ.get("CIO_ROLLBACK_SHA", "").strip()
    if prev_env:
        rollback = prev_env
    rollback_content = os.environ.get("CIO_ROLLBACK_CONTENT_SHA", "").strip() or rollback_content_sha_for(
        str(rollback or "")
    )

    # Production when HEAD == origin/main and live backend matches the
    # required *content* SHA (attestation merges are not the live BUILD_SHA),
    # or when operator forces CIO_RELEASE_STATUS=production.
    forced = os.environ.get("CIO_RELEASE_STATUS", "").strip().lower()
    backend = str(deploy.get("backend_release_sha") or "")
    live_matches_head = _sha_matches(backend, head)
    live_matches_content = _sha_matches(backend, content_sha)
    on_main_tip = bool(head and origin_main and head == origin_main)
    if forced in ("production", "prod"):
        status = "production"
    elif forced in ("release_candidate", "rc"):
        status = "release_candidate"
    elif on_main_tip and (live_matches_content or (live_matches_head and not attestation_only)):
        status = "production"
    else:
        status = "release_candidate"

    if attestation_only:
        default_note = (
            f"{ATTESTATION_ONLY_NOTE} "
            "Stale preliminary SHAs are forbidden. Authority remains READ_ONLY_ADVISORY."
        )
    elif status == "production":
        default_note = (
            "Production investment-office release: Git main, portfolio-server CURRENT, "
            "and this manifest pin the same full SHA. Stale preliminary SHAs are forbidden. "
            "Authority remains READ_ONLY_ADVISORY."
        )
    else:
        default_note = (
            "Release candidate for CIO production hardening on this branch. "
            "backend_release_sha reflects currently deployed portfolio-server CURRENT "
            "(may lag this RC until controlled deployment). Stale preliminary SHAs are forbidden. "
            "Drive investment-office mirror may lag git until operator sync."
        )

    notes = note or default_note
    if attestation_only and notes_claim_same_full_sha(notes):
        # Never emit the exact-SHA claim on an attestation-only HEAD, even if
        # the operator passed a note that still uses the v1 wording.
        notes = default_note

    # Legacy aliases: canonical_source_sha == content; origin_main_sha == remote main.
    frontend = frontend_build_sha()
    manifest = {
        "manifest_schema": SCHEMA_V2,
        "status": status,
        "branch": git_branch(),
        "release_content_sha": content_sha,
        "release_attestation_sha": attestation_sha,
        "remote_main_sha_at_manifest": ident["remote_main_sha_at_manifest"],
        "canonical_source_sha": content_sha,  # legacy alias of release_content_sha
        "origin_main_sha": ident["remote_main_sha_at_manifest"],  # legacy alias
        "frontend_build_sha": frontend,
        "backend_release_sha": deploy["backend_release_sha"],
        "report_source_sha": content_sha,
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
        "rollback_content_sha": rollback_content,
        "manifest_generated_from_sha": ident["manifest_generated_from_sha"],
        "manifest_created_at": created,
        "created_at": created,  # legacy alias of manifest_created_at
        "financial_authority": "READ_ONLY_ADVISORY",
        "broker_write_paths_added": 0,
        "attestation_only": attestation_only,
        "head_commit_class": ident["head_class"],
        "notes": notes,
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
            "main_observed": "protected (Phase 11 operator enablement)",
            "enabled_rules": [
                "required_pull_request_reviews (0 approving, dismiss stale)",
                "allow_force_pushes=false",
                "allow_deletions=false",
            ],
            "recommendation": [
                "require pull request before merge",
                "require CIO hardening CI + release-readiness checks as required status contexts once stable on main",
                "block force-push to main",
                "block merge with failing required checks",
            ],
            "operator_approval_required": False,
            "auto_enforced_by_this_script": False,
            "note": "Status-check contexts left empty so first main PR is not blocked before the workflow runs.",
        },
    }
    # Content hash excluding created_at for stable compare of material pins
    material = {k: manifest[k] for k in REQUIRED_FIELDS if k != "created_at"}
    material["branch"] = manifest["branch"]
    material["product_versions"] = manifest["product_versions"]
    for k in (
        "release_content_sha",
        "release_attestation_sha",
        "remote_main_sha_at_manifest",
        "report_source_sha",
        "rollback_content_sha",
        "manifest_generated_from_sha",
        "financial_authority",
    ):
        material[k] = manifest[k]
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
        f"| release_content_sha | `{m.get('release_content_sha')}` |",
        f"| release_attestation_sha | `{m.get('release_attestation_sha')}` |",
        f"| remote_main_sha_at_manifest | `{m.get('remote_main_sha_at_manifest')}` |",
        f"| frontend_build_sha | `{m.get('frontend_build_sha')}` |",
        f"| backend_release_sha | `{m.get('backend_release_sha')}` |",
        f"| report_source_sha | `{m.get('report_source_sha')}` |",
        f"| deployed_release_path | `{m.get('deployed_release_path')}` |",
        f"| deployed_release_name | `{m.get('deployed_release_name')}` |",
        f"| migration_head | `{m.get('migration_head')}` |",
        f"| docs_pin | `{m.get('docs_pin')}` |",
        f"| runtime_config_hash | `{m.get('runtime_config_hash')}` |",
        f"| report_version | `{m.get('report_version')}` |",
        f"| rollback_sha | `{m.get('rollback_sha')}` |",
        f"| rollback_content_sha | `{m.get('rollback_content_sha')}` |",
        f"| manifest_generated_from_sha | `{m.get('manifest_generated_from_sha')}` |",
        f"| manifest_created_at | `{m.get('manifest_created_at')}` |",
        f"| created_at | `{m.get('created_at')}` |",
        f"| financial_authority | `{m.get('financial_authority')}` |",
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
        f"Observed: {m.get('branch_protection', {}).get('main_observed', 'unknown')}.",
        "Recommended / residual:",
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
    fields = list(dict.fromkeys((*REQUIRED_FIELDS, *V2_EXPLICIT_FIELDS)))
    for field in fields:
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
    for field in (
        "canonical_source_sha",
        "release_content_sha",
        "release_attestation_sha",
        "docs_pin",
        "backend_release_sha",
        "rollback_sha",
        "rollback_content_sha",
    ):
        val = (disk or {}).get(field) or md_pins.get(field) or ""
        if not val:
            continue
        for stale in FORBIDDEN_STALE_SHAS:
            if val.startswith(stale) or (len(val) >= 8 and stale.startswith(val[:8])):
                if field in (
                    "canonical_source_sha",
                    "release_content_sha",
                    "release_attestation_sha",
                    "docs_pin",
                ):
                    errors.append(f"stale_forbidden_sha:{field}={val[:12]}")

    # Content SHA on disk must match live content identity. HEAD may be an
    # attestation merge/pin whose first parent is that content SHA.
    live_content = (live.get("release_content_sha") or live.get("canonical_source_sha") or "")
    head = git_head() or live.get("manifest_generated_from_sha") or live_content
    disk_sha = (
        (disk or {}).get("release_content_sha")
        or (disk or {}).get("canonical_source_sha")
        or md_pins.get("release_content_sha")
        or md_pins.get("canonical_source_sha")
    )
    if disk_sha and disk_sha != live_content and disk_sha != head:
        parent = _run(["git", "rev-parse", "HEAD^"])
        pin_only_allowed = set(PIN_ONLY_PATHS)
        if parent and disk_sha == parent:
            changed = {
                ln.strip()
                for ln in _run(["git", "diff", "--name-only", f"{parent}..{head}"]).splitlines()
                if ln.strip()
            }
            if changed and changed <= pin_only_allowed:
                warnings.append(
                    "canonical_source_sha pins parent content commit; "
                    "HEAD is pin-only RELEASE_MANIFEST update (OK)"
                )
            else:
                errors.append(
                    f"canonical_source_sha mismatch: disk={disk_sha[:12]} head={head[:12]} "
                    f"— parent pin but non-manifest changes {sorted(changed - pin_only_allowed)[:5]}"
                )
        else:
            errors.append(
                f"canonical_source_sha mismatch: disk={disk_sha[:12]} head={head[:12]} — regenerate"
            )
    elif disk_sha and disk_sha != head and disk_sha == live_content:
        warnings.append(
            "canonical_source_sha / release_content_sha pins attested content; "
            "HEAD is the release-attestation commit (OK)"
        )

    if live.get("attestation_only") and notes_claim_same_full_sha(str(live.get("notes") or "")):
        errors.append("notes_claim_same_full_sha_on_attestation_only")
    if (disk or {}).get("manifest_schema") == SCHEMA_V2:
        disk_content = (disk or {}).get("release_content_sha") or ""
        disk_attest = (disk or {}).get("release_attestation_sha") or ""
        if (
            disk_content
            and disk_attest
            and disk_content != disk_attest
            and notes_claim_same_full_sha(str((disk or {}).get("notes") or ""))
        ):
            errors.append("notes_claim_same_full_sha_on_attestation_only")
        if (disk or {}).get("financial_authority") not in (None, "READ_ONLY_ADVISORY"):
            errors.append(f"bad_authority:{(disk or {}).get('financial_authority')}")

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
    live_pin = live.get("release_content_sha") or live.get("canonical_source_sha")
    if live.get("backend_release_sha") and live_pin:
        if live["backend_release_sha"] not in (
            live_pin,
            live.get("release_attestation_sha"),
            "UNKNOWN_NOT_STAMPED_IN_RELEASE_DIR",
        ):
            if not str(live["backend_release_sha"]).startswith(str(live_pin)[:7]):
                warnings.append(
                    "deployed backend SHA lags RC HEAD (expected until controlled deploy)"
                )

    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "head": head,
        "live_content_sha": live_content,
        "disk_canonical_source_sha": disk_sha,
        "disk_release_content_sha": (disk or {}).get("release_content_sha"),
        "disk_release_attestation_sha": (disk or {}).get("release_attestation_sha"),
        "report_version": code_rv,
        "stale_manifest": any("stale" in e or "mismatch" in e for e in errors),
    }


def pin_only_parent(head_sha: str, disk_sha: str) -> dict[str, Any]:
    """True when HEAD^1..HEAD only touches RELEASE_MANIFEST* and disk pins that parent."""
    head = (head_sha or "").strip()
    disk = (disk_sha or "").strip()
    if not head or not disk or head == disk:
        return {"ok": head == disk and bool(head), "reason": "equal_or_empty"}
    parent = _run(["git", "rev-parse", f"{head}^1"])
    if not parent:
        return {"ok": False, "reason": "no_parent"}
    if parent != disk and not (disk.startswith(parent[:12]) or parent.startswith(disk[:12])):
        return {"ok": False, "reason": "disk_not_parent", "parent": parent}
    changed = {
        ln.strip()
        for ln in _run(["git", "diff", "--name-only", f"{parent}..{head}"]).splitlines()
        if ln.strip()
    }
    extra = sorted(changed - PIN_ONLY_PATHS)
    return {
        "ok": bool(changed) and not extra,
        "parent": parent,
        "changed": sorted(changed),
        "extra": extra,
        "reason": "pin_only" if (changed and not extra) else "non_manifest_changes",
    }


def validate_committed() -> dict[str, Any]:
    """Read-only integrity of the committed manifest. Does NOT require HEAD pin.

    Phase 2: this is what CI must run. It must never rewrite the files.
    """
    errors: list[str] = []
    warnings: list[str] = []
    disk = load_json_manifest()
    md_text = MANIFEST_MD.read_text(encoding="utf-8") if MANIFEST_MD.is_file() else ""
    md_pins = parse_md_pins(md_text) if md_text else {}
    if not disk:
        errors.append("RELEASE_MANIFEST.json missing")
    if not md_text:
        errors.append("RELEASE_MANIFEST.md missing")
    live_versions = product_versions()
    if disk:
        for f in REQUIRED_FIELDS:
            if not disk.get(f):
                errors.append(f"missing_json_field:{f}")
        if disk.get("financial_authority") not in (None, "READ_ONLY_ADVISORY"):
            errors.append(f"bad_authority:{disk.get('financial_authority')}")
        drv = disk.get("report_version")
        if drv and live_versions.get("report_version") and drv != live_versions["report_version"]:
            errors.append(
                f"report_version mismatch: disk={drv} code={live_versions['report_version']}"
            )
        pv = disk.get("product_versions") or {}
        for k, code_v in live_versions.items():
            if pv.get(k) and pv.get(k) != code_v:
                warnings.append(f"product_version_lag:{k} disk={pv.get(k)} code={code_v}")
        for field in (
            "canonical_source_sha",
            "release_content_sha",
            "release_attestation_sha",
            "docs_pin",
            "backend_release_sha",
        ):
            val = str(disk.get(field) or "")
            if not val:
                continue
            for stale in FORBIDDEN_STALE_SHAS:
                if val.startswith(stale) or (len(val) >= 8 and stale.startswith(val[:8])):
                    errors.append(f"stale_forbidden_sha:{field}={val[:12]}")
        if md_pins:
            for k in ("canonical_source_sha", "report_version"):
                if md_pins.get(k) and disk.get(k) and md_pins[k] != disk[k]:
                    errors.append(f"md_json_pin_mismatch:{k}")
        schema = str(disk.get("manifest_schema") or SCHEMA_V1)
        if schema == SCHEMA_V2:
            for f in V2_EXPLICIT_FIELDS:
                if not disk.get(f):
                    errors.append(f"missing_v2_field:{f}")
            content = str(disk.get("release_content_sha") or "")
            attest = str(disk.get("release_attestation_sha") or "")
            if content and attest and content != attest and notes_claim_same_full_sha(str(disk.get("notes") or "")):
                errors.append("notes_claim_same_full_sha_on_attestation_only")
            if disk.get("canonical_source_sha") and content and disk.get("canonical_source_sha") != content:
                errors.append("legacy_alias_mismatch:canonical_source_sha!=release_content_sha")
            if disk.get("origin_main_sha") and disk.get("remote_main_sha_at_manifest"):
                if disk["origin_main_sha"] != disk["remote_main_sha_at_manifest"]:
                    warnings.append("legacy_alias_lag:origin_main_sha!=remote_main_sha_at_manifest")
        elif schema not in (SCHEMA_V1, ""):
            warnings.append(f"unknown_manifest_schema:{schema}")
    return {
        "ok": len(errors) == 0,
        "mode": "committed_integrity",
        "mutated": False,
        "errors": errors,
        "warnings": warnings,
        "disk_canonical_source_sha": (disk or {}).get("canonical_source_sha"),
        "disk_release_content_sha": (disk or {}).get("release_content_sha"),
        "disk_release_attestation_sha": (disk or {}).get("release_attestation_sha"),
        "disk_status": (disk or {}).get("status"),
        "disk_schema": (disk or {}).get("manifest_schema"),
        "code_report_version": live_versions.get("report_version"),
    }


def write_manifest_to(m: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "RELEASE_MANIFEST.md"
    js = out_dir / "RELEASE_MANIFEST.json"
    md.write_text(render_markdown(m), encoding="utf-8")
    payload = {k: v for k, v in m.items() if k != "docs_files_sample"}
    js.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return {"md": md, "json": js}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Investment-office release manifest")
    parser.add_argument(
        "command",
        choices=("generate", "validate", "check", "check-committed", "candidate", "print-json"),
    )
    parser.add_argument("--write", action="store_true", help="Write MD+JSON (generate → committed paths)")
    parser.add_argument(
        "--out-dir",
        default="",
        help="Write generate/candidate output here instead of docs/ (never mutates committed files)",
    )
    args = parser.parse_args(argv)

    if args.command in ("generate", "print-json", "candidate"):
        m = build_manifest()
        if args.command == "print-json" or (args.command == "generate" and not args.write and not args.out_dir):
            print(json.dumps(m, indent=2, default=str))
        out_dir = Path(args.out_dir) if args.out_dir else None
        if args.command == "candidate":
            dest = out_dir or (REPO / "data" / "audit" / "manifest_candidate")
            paths = write_manifest_to(m, dest)
            print(json.dumps({
                "written": True,
                "mode": "candidate",
                "mutated_committed": False,
                "md": str(paths["md"]),
                "json": str(paths["json"]),
                "canonical_source_sha": m["canonical_source_sha"],
                "release_content_sha": m.get("release_content_sha"),
                "release_attestation_sha": m.get("release_attestation_sha"),
                "manifest_hash": m["manifest_hash"],
                "status": m.get("status"),
                "manifest_schema": m.get("manifest_schema"),
            }, indent=2))
            return 0
        if args.write and out_dir:
            paths = write_manifest_to(m, out_dir)
            print(json.dumps({
                "written": True, "mode": "out_dir", "mutated_committed": False,
                "md": str(paths["md"]), "json": str(paths["json"]),
                "canonical_source_sha": m["canonical_source_sha"],
                "manifest_hash": m["manifest_hash"],
            }, indent=2))
            return 0
        if args.write:
            write_manifest(m)
            print(json.dumps({
                "written": True, "md": str(MANIFEST_MD), "json": str(MANIFEST_JSON),
                "canonical_source_sha": m["canonical_source_sha"],
                "release_content_sha": m.get("release_content_sha"),
                "release_attestation_sha": m.get("release_attestation_sha"),
                "manifest_hash": m["manifest_hash"],
                "manifest_schema": m.get("manifest_schema"),
            }, indent=2))
        return 0

    if args.command == "check-committed":
        result = validate_committed()
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["ok"] else 1

    # validate / check (full HEAD pin)
    result = validate()
    print(json.dumps(result, indent=2))
    if args.command == "check":
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

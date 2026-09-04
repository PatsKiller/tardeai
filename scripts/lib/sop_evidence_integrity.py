"""SOP 1.2.0 evidence integrity — control-surface digests and validators.

Two evidence layers (do not conflate):

1. **In-repository reproducible evidence** binds to a deterministic
   ``control_surface_digest`` over a sorted manifest of governance sources.
   It must **not** embed the SHA of the commit that contains it.

2. **Runtime exact-head attestation** is generated *after* checkout/commit by
   local verification or CI. It names ``git rev-parse HEAD`` / ``GITHUB_SHA``
   and lives outside the tracked tree (``artifacts/sop-attestations/``).
   Embedding an exact-head claim inside the commit it attests creates an
   endless parent-SHA sequence and is rejected by the validator.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts.lib.sop_toolchain import PINNED_RUFF_VERSION as PINNED_RUFF  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_REL = "config/sop_120_control_surface.manifest.json"
EVIDENCE_DIR_REL = "docs/implementation/maturity-program/sop-1.2.0-20260902"
RUNTIME_ATTESTATION_SCHEMA = "SopRuntimeAttestation@v1"
EXPECTED_CORE_TESTS = 121

# Authoritative (current) evidence basenames — must be non-empty and coherent.
CURRENT_EVIDENCE = frozenset(
    {
        "EVIDENCE_ARCHITECTURE.md",
        "FULL_TEST_MATRIX.txt",
        "RUFF_SHELLCHECK.txt",
        "CONTROL7_WORKFLOW_PROOF.txt",
        "CONTROL7_LOCAL_EQUIVALENT.txt",
        "CONTROL6_INDEX_FINGERPRINT.txt",
        "MATURITY_SCORECARD.md",
        "AUTHORITY_NON_REGRESSION.txt",
        "VERIFIER_RUNBOOK.md",
        "ADVERSARIAL_WORKTREE_IDENTITY.txt",
        "STAGE_00_PREFLIGHT.md",
        "STAGE_01_PR_COLLISION.md",
        "EAC13CFD0_DRIVE_MANIFEST_DISPOSITION.md",
        "SECRETS_POSITIVE_CONTROL.txt",
    }
)

# Historical / superseded — retained for audit; not authoritative PASS subjects.
SUPERSEDED_EVIDENCE = frozenset(
    {
        "FINAL_EXACT_STATE.txt",
        "CONTROL6_INDEX_CHECK.txt",
        "CONTROL6_INDEX_DIFFSTAT.txt",
        "CONTROL6_INDEX_FINAL_CHECK.txt",
        "CONTROL6_INDEX_FULL_DIFF.txt",
        "CONTROL6_INDEX_RECHECK.txt",
        "CONTROL6_INDEX_STABLE.txt",
        "CONTROL6_INDEX_WRITE.txt",
        "EXTENDED_TESTS.txt",
        "POST_RUFF_FORMAT_TESTS.txt",
        "OPEN_PR_COLLISION_INVENTORY.json",
    }
)

_PLACEHOLDER_RE = re.compile(
    r"(run_check_index_after|see_post_regen|see_docs_INDEX|PENDING_SHA|"
    r"TBD|TODO_FILL|FIXME_EVIDENCE|unresolved.?placeholder)",
    re.I,
)
# Claims that an evidence blob embeds *its containing* commit (forbidden in CURRENT).
_SELF_HEAD_CLAIM_RE = re.compile(
    r"(?im)^(?:source_head|final_head|immutable_head|this_commit|containing_commit)\s*="
    r"\s*[0-9a-f]{40}\s*$"
)
_EXIT_RE = re.compile(r"(?im)^(?P<key>EXIT_[A-Za-z0-9_]+)\s*=\s*(?P<val>-?\d+)\b")
_SHA40_RE = re.compile(r"\b[0-9a-f]{40}\b", re.I)


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    path = root / MANIFEST_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "SopControlSurfaceManifest@v1":
        raise ValueError(f"unexpected manifest schema: {data.get('schema')}")
    paths = list(data.get("paths") or [])
    if paths != sorted(paths):
        raise ValueError("manifest paths must be sorted lexicographically")
    if len(paths) != len(set(paths)):
        raise ValueError("manifest paths contain duplicates")
    return data


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def control_surface_digest(root: Path | None = None) -> dict[str, Any]:
    """Return digest facts for the control surface.

    Digest = SHA-256 over newline-joined ``path\\tcontent_sha256`` lines in
    sorted manifest order (UTF-8). Missing paths fail closed.
    """
    root = root or ROOT
    manifest = load_manifest(root)
    lines: list[str] = []
    per_file: dict[str, str] = {}
    missing: list[str] = []
    for rel in manifest["paths"]:
        p = root / rel
        if not p.is_file():
            missing.append(rel)
            continue
        digest = file_sha256(p)
        per_file[rel] = digest
        lines.append(f"{rel}\t{digest}")
    if missing:
        raise FileNotFoundError(f"control-surface paths missing: {missing}")
    blob = ("\n".join(lines) + "\n").encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()
    return {
        "schema": "SopControlSurfaceDigest@v1",
        "manifest": MANIFEST_REL,
        "digest": digest,
        "path_count": len(per_file),
        "per_file": per_file,
    }


def workflow_facts(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    wf = root / ".github/workflows/agent-governance.yml"
    text = wf.read_text(encoding="utf-8")
    lines = text.splitlines()
    return {
        "path": ".github/workflows/agent-governance.yml",
        "lines": len(lines),
        "blob_sha256": file_sha256(wf),
        "has_path_filters": bool(re.search(r"(?m)^\s*paths:\s*$", text)),
        "triggers": {
            "pull_request": "pull_request:" in text,
            "push_main": bool(re.search(r"(?s)push:\s*\n\s*branches:\s*\[[^\]]*main", text)),
            "workflow_dispatch": "workflow_dispatch:" in text,
        },
        "pinned_ruff_install": f'pip install "ruff=={PINNED_RUFF}"' in text
        or f"pip install 'ruff=={PINNED_RUFF}'" in text,
        "ruff_or_true": "ruff || true" in text or "install ruff || true" in text,
        "step_names": re.findall(r"(?m)^\s+-\s+name:\s+(.+)$", text),
    }


def _evidence_path(name: str, root: Path) -> Path:
    return root / EVIDENCE_DIR_REL / name


def validate_in_repo_evidence(root: Path | None = None) -> list[str]:
    """Return a list of machine-readable error codes (empty => PASS)."""
    root = root or ROOT
    errors: list[str] = []
    try:
        digest_facts = control_surface_digest(root)
    except Exception as exc:  # noqa: BLE001
        return [f"CONTROL_SURFACE_DIGEST_UNAVAILABLE:{exc}"]

    digest = digest_facts["digest"]
    wf = workflow_facts(root)

    # Manifest / workflow hygiene
    if wf["has_path_filters"]:
        errors.append("WORKFLOW_HAS_PATH_FILTERS")
    if not all(wf["triggers"].values()):
        errors.append("WORKFLOW_TRIGGERS_INCOMPLETE")
    if wf["ruff_or_true"]:
        errors.append("WORKFLOW_RUFF_OR_TRUE")
    if not wf["pinned_ruff_install"]:
        errors.append("WORKFLOW_RUFF_PIN_MISSING")

    ev_dir = root / EVIDENCE_DIR_REL
    if not ev_dir.is_dir():
        errors.append("EVIDENCE_DIR_MISSING")
        return errors

    # Current evidence must exist, non-empty, no placeholders, no self-HEAD claims
    for name in sorted(CURRENT_EVIDENCE):
        p = _evidence_path(name, root)
        if not p.is_file():
            errors.append(f"CURRENT_EVIDENCE_MISSING:{name}")
            continue
        raw = p.read_text(encoding="utf-8")
        if len(raw.strip()) == 0:
            errors.append(f"CURRENT_EVIDENCE_EMPTY:{name}")
            continue
        if _PLACEHOLDER_RE.search(raw):
            errors.append(f"PLACEHOLDER:{name}")
        if _SELF_HEAD_CLAIM_RE.search(raw):
            errors.append(f"SELF_REF_HEAD_CLAIM:{name}")

    # Superseded must be marked
    for name in sorted(SUPERSEDED_EVIDENCE):
        p = _evidence_path(name, root)
        if not p.is_file():
            continue
        raw = p.read_text(encoding="utf-8")
        if "SUPERSEDED_NON_AUTHORITATIVE" not in raw:
            errors.append(f"SUPERSEDED_UNMARKED:{name}")
        if len(raw.strip()) == 0:
            errors.append(f"SUPERSEDED_EMPTY:{name}")

    # FULL_TEST_MATRIX bindings
    matrix = _evidence_path("FULL_TEST_MATRIX.txt", root)
    if matrix.is_file():
        mt = matrix.read_text(encoding="utf-8")
        if f"control_surface_digest={digest}" not in mt:
            errors.append("MATRIX_DIGEST_MISMATCH")
        if f"PYTEST_CORE={EXPECTED_CORE_TESTS}" not in mt and f"expected_pytest_core={EXPECTED_CORE_TESTS}" not in mt:
            errors.append("MATRIX_TEST_TOTAL_MISMATCH")
        exits = {m.group("key"): int(m.group("val")) for m in _EXIT_RE.finditer(mt)}
        # Required successful exits
        for key in (
            "EXIT_lease_canonical",
            "EXIT_session",
            "EXIT_identity",
            "EXIT_quality_unit",
            "EXIT_clients",
            "EXIT_drive",
            "EXIT_policy",
            "EXIT_quality",
            "EXIT_ruff_check",
            "EXIT_ruff_format",
            "EXIT_shellcheck",
            "EXIT_diffcheck",
            "EXIT_secrets",
        ):
            if key in exits and exits[key] != 0:
                errors.append(f"MATRIX_NONZERO_PASS_CLAIM:{key}={exits[key]}")
        if exits.get("EXIT_missing_ruff") not in (None, 2):
            errors.append("MATRIX_MISSING_RUFF_SEMANTICS")
        if exits.get("EXIT_positive_control") not in (None, 1):
            errors.append("MATRIX_POSITIVE_CONTROL_SEMANTICS")

    # RUFF_SHELLCHECK
    rs = _evidence_path("RUFF_SHELLCHECK.txt", root)
    if rs.is_file():
        rt = rs.read_text(encoding="utf-8")
        if PINNED_RUFF not in rt:
            errors.append("RUFF_VERSION_MISMATCH")
        if "EXIT_ruff_check=0" not in rt or "EXIT_ruff_format=0" not in rt:
            errors.append("RUFF_EXIT_SEMANTICS")
        if "EXIT_shellcheck=0" not in rt:
            errors.append("SHELLCHECK_EXIT_SEMANTICS")
        if "EXIT_missing_ruff_negative=2" not in rt:
            errors.append("MISSING_RUFF_NEGATIVE_SEMANTICS")
        if f"control_surface_digest={digest}" not in rt:
            errors.append("RUFF_EVIDENCE_DIGEST_MISMATCH")

    # CONTROL7 workflow proof
    c7 = _evidence_path("CONTROL7_WORKFLOW_PROOF.txt", root)
    if c7.is_file():
        c7t = c7.read_text(encoding="utf-8")
        if f"workflow_blob_sha256={wf['blob_sha256']}" not in c7t:
            errors.append("WORKFLOW_BLOB_HASH_MISMATCH")
        if f"workflow_lines={wf['lines']}" not in c7t:
            errors.append("WORKFLOW_LINE_COUNT_MISMATCH")
        if f"control_surface_digest={digest}" not in c7t:
            errors.append("WORKFLOW_PROOF_DIGEST_MISMATCH")
        if "path_filters=absent" not in c7t and "path_filters=none" not in c7t:
            errors.append("WORKFLOW_PROOF_PATH_FILTERS_UNSTATED")

    # CONTROL7 local equivalent must not record failures while cited as PASS
    loc = _evidence_path("CONTROL7_LOCAL_EQUIVALENT.txt", root)
    if loc.is_file():
        lt = loc.read_text(encoding="utf-8")
        # Fail only on live recorded exits / tracebacks, not prose about history.
        if re.search(r"(?m)^EXIT_quality=1\b", lt) or re.search(r"(?m)^Traceback \(most recent call last\):", lt):
            errors.append("LOCAL_EQUIVALENT_RECORDS_FAILURE")
        if re.search(r"(?m)^STATUS:\s*SUPERSEDED_NON_AUTHORITATIVE\b", lt):
            errors.append("LOCAL_EQUIVALENT_MARKED_SUPERSEDED_BUT_CURRENT")
        if f"control_surface_digest={digest}" not in lt:
            errors.append("LOCAL_EQUIVALENT_DIGEST_MISMATCH")
        if not re.search(r"(?m)^EXIT_quality=0\b", lt):
            errors.append("LOCAL_EQUIVALENT_QUALITY_EXIT_MISSING")

    # CONTROL6 fingerprint — no live fingerprint embed required; forbid circular claim
    c6 = _evidence_path("CONTROL6_INDEX_FINGERPRINT.txt", root)
    if c6.is_file():
        c6t = c6.read_text(encoding="utf-8")
        if "verify_command=python3 scripts/report_docs_inventory.py --check-index" not in c6t:
            errors.append("INDEX_VERIFY_COMMAND_MISSING")
        if re.search(r"(?i)tree fingerprint:\s*`?[0-9a-f]{12,}", c6t):
            errors.append("INDEX_FINGERPRINT_EMBEDDED")

    # Scorecard must not cite LOCAL_EQUIVALENT if that file still fails (caught above)
    score = _evidence_path("MATURITY_SCORECARD.md", root)
    if score.is_file():
        st = score.read_text(encoding="utf-8")
        if "CONTROL7_LOCAL_EQUIVALENT" in st and "LOCAL_EQUIVALENT_RECORDS_FAILURE" in "".join(errors):
            errors.append("SCORECARD_CITES_FAILING_LOCAL_EQUIVALENT")
        if f"control_surface_digest={digest}" not in st and f"`{digest[:12]}`" not in st:
            # allow short prefix citation
            if "control_surface_digest" not in st:
                errors.append("SCORECARD_DIGEST_UNBOUND")

    # Forbid committed runtime attestations under docs/
    for p in (root / EVIDENCE_DIR_REL).glob("*runtime*attestation*"):
        errors.append(f"RUNTIME_ATTESTATION_COMMITTED:{p.name}")
    for p in (root / "docs").rglob("SopRuntimeAttestation*.json"):
        errors.append(f"RUNTIME_ATTESTATION_COMMITTED:{p.relative_to(root)}")

    # Dedup
    out: list[str] = []
    for e in errors:
        if e not in out:
            out.append(e)
    return out


def validate_runtime_attestation(
    data: dict[str, Any],
    *,
    root: Path | None = None,
    require_ruff: bool = True,
    changed_python: bool = True,
) -> list[str]:
    """Validate a runtime attestation.

    When ``require_ruff`` / ``changed_python`` are true (default for SOP
    governance attestations), Ruff must be present, match the pinned version,
    and must not be recorded as MISSING while commands claim PASS.
    """
    from scripts.lib.sop_toolchain import (
        PINNED_RUFF_VERSION,
        collect_tool_versions,
        parse_ruff_version,
        parse_shellcheck_version,
        resolve_ruff_bin,
    )

    root = root or ROOT
    errors: list[str] = []
    if data.get("schema") != RUNTIME_ATTESTATION_SCHEMA:
        errors.append("ATTESTATION_SCHEMA")
    for key in (
        "schema_version",
        "head_sha",
        "base_sha",
        "control_surface_digest",
        "policy_version",
        "policy_status",
        "workflow_blob_sha256",
        "commands",
        "test_counts",
        "docs_index_fingerprint",
        "tool_versions",
        "clean_state",
        "authority_non_regression",
    ):
        if key not in data:
            errors.append(f"ATTESTATION_MISSING:{key}")
    head = str(data.get("head_sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        errors.append("ATTESTATION_HEAD_SHA")
    try:
        expected = control_surface_digest(root)["digest"]
        if data.get("control_surface_digest") != expected:
            errors.append("ATTESTATION_DIGEST_MISMATCH")
        wf = workflow_facts(root)
        if data.get("workflow_blob_sha256") != wf["blob_sha256"]:
            errors.append("ATTESTATION_WORKFLOW_HASH_MISMATCH")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ATTESTATION_DIGEST_UNAVAILABLE:{exc}")
    counts = data.get("test_counts") or {}
    if int(counts.get("core", -1)) != EXPECTED_CORE_TESTS:
        errors.append("ATTESTATION_TEST_COUNT")

    tools = data.get("tool_versions") or {}
    recorded_ruff = str(tools.get("ruff") or "")
    live = collect_tool_versions(root=root)
    resolved = resolve_ruff_bin(root=root)

    if require_ruff or changed_python:
        if recorded_ruff.upper() == "MISSING" or not recorded_ruff:
            errors.append("ATTESTATION_RUFF_RECORDED_MISSING")
        if resolved is None:
            errors.append("ATTESTATION_RUFF_TOOL_MISSING")
        else:
            live_parsed = parse_ruff_version(str(live.get("ruff_raw") or live.get("ruff") or ""))
            rec_parsed = parse_ruff_version(recorded_ruff) or (
                recorded_ruff if re.fullmatch(r"\d+\.\d+\.\d+", recorded_ruff) else None
            )
            if live_parsed and rec_parsed and live_parsed != rec_parsed:
                errors.append("ATTESTATION_RUFF_VERSION_MISMATCH")
            if rec_parsed and rec_parsed != PINNED_RUFF_VERSION:
                errors.append("ATTESTATION_RUFF_PIN_MISMATCH")
            if recorded_ruff.upper() == "MISSING" and live_parsed:
                errors.append("ATTESTATION_RUFF_FALSE_MISSING")

    # Required command PASS cannot coexist with missing tool.
    cmds = data.get("commands") or []
    ruff_related = {"ruff_check", "ruff_format", "quality", "pytest_core", "shellcheck"}
    for c in cmds:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "")
        exit_code = c.get("exit")
        if (
            exit_code == 0
            and recorded_ruff.upper() == "MISSING"
            and (name in ruff_related or "ruff" in name or name == "pytest_core")
        ):
            # pytest_core itself does not need ruff, but quality/ruff commands do.
            if name in {"ruff_check", "ruff_format", "quality"} or "ruff" in name:
                errors.append(f"ATTESTATION_PASS_WITH_MISSING_TOOL:{name}")
        if exit_code == 0 and name == "shellcheck" and str(tools.get("shellcheck") or "").upper() == "MISSING":
            errors.append("ATTESTATION_PASS_WITH_MISSING_TOOL:shellcheck")

    # ShellCheck must be recorded as an exact version, not a banner, and must
    # agree with the live tool. A banner-only or hand-edited value fails closed.
    recorded_sc = str(tools.get("shellcheck") or "")
    live_sc = parse_shellcheck_version(str(live.get("shellcheck_raw") or live.get("shellcheck") or ""))
    if not recorded_sc or recorded_sc.upper() == "MISSING":
        if live_sc:
            errors.append("ATTESTATION_SHELLCHECK_FALSE_MISSING")
    else:
        rec_sc = parse_shellcheck_version(recorded_sc)
        if rec_sc is None:
            errors.append("ATTESTATION_SHELLCHECK_VERSION_UNPARSEABLE")
        elif live_sc and rec_sc != live_sc:
            errors.append("ATTESTATION_SHELLCHECK_VERSION_MISMATCH")

    if changed_python and recorded_ruff.upper() == "MISSING":
        errors.append("ATTESTATION_CHANGED_PYTHON_REQUIRES_RUFF")

    out: list[str] = []
    for e in errors:
        if e not in out:
            out.append(e)
    return out

#!/usr/bin/env python3
"""Current-main host convergence — pure, testable safety core.

Holds the load-bearing DECISIONS the convergence packet depends on (build-source enforcement, phase
gating, secret redaction, agent-runtime contract classification, build-meta provenance). No I/O, no
network, no host mutation — the shell scripts call these and refuse to proceed when they raise. This
is what the validation tests pin so the packet cannot regress into an unsafe deployment.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

SOURCE_MODE_EXACT = "STAGED_EXACT_REF"
SOURCE_MODE_LIVE = "LIVE_CHECKOUT"
PINNED_ARCHIVE = "PINNED_GIT_OBJECT_ARCHIVE"

AGENT_RUNTIME_CONTRACT = "agent-runtime-command-center-read-api-v1"
_AUTHORITY_KEYS = ("mutation", "provider_call", "service_control", "schedule_change", "financial_action")

# Required reconciled-behavior markers the STAGED build must contain before any install (Part B).
WATCH_MARKERS = ("ADMITTED", "RESEARCH_ONLY", "QUARANTINED")
DEFENSE_MARKERS = ("ELIGIBLE NOW", "RESEARCH WATCH", "AVOID", "NO DECISION")
AGENTS_MARKERS = ("SHADOW", "DESIGNED", "NOT_RUN", "UNAVAILABLE")
AGENT_RUNTIME_MARKER = (AGENT_RUNTIME_CONTRACT,)


class ConvergenceError(Exception): ...
class BuildSourceError(ConvergenceError): ...
class PhaseGateError(ConvergenceError): ...


# ── build-source enforcement: the candidate must come from the staged exact-ref, never the live tree ──
def validate_build_source(mode: str) -> None:
    if mode != SOURCE_MODE_EXACT:
        raise BuildSourceError(
            f"frontend build input must be {SOURCE_MODE_EXACT}; got {mode!r} — building from the live "
            "checkout is forbidden (a dirty/divergent tree can produce an unrelated bundle)")


def _require_full_sha(source_commit: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", (source_commit or "")):
        raise BuildSourceError("requires the full 40-character source commit (no short SHA)")
    return source_commit


def build_meta(source_commit: str, contracts: Mapping[str, str]) -> dict:
    """Provenance stamp for the candidate bundle. Requires the FULL 40-char commit (no short SHA)."""
    _require_full_sha(source_commit)
    return {"source_commit": source_commit, "source_mode": PINNED_ARCHIVE,
            "frontend_build_source": SOURCE_MODE_EXACT, "live_checkout_build_input": "NONE",
            "contracts": dict(contracts)}


# ── two-phase gating: CONNECT can never run before a passed MOUNT + a SEPARATE explicit ack ──
def can_run_connect(mount_passed: bool, connect_ack: bool) -> bool:
    if not mount_passed:
        raise PhaseGateError("CONNECT blocked: MOUNT phase has not passed")
    if not connect_ack:
        raise PhaseGateError("CONNECT blocked: a separate explicit operator acknowledgement is required")
    return True


# ── agent-runtime contract classification (matches the read-plane envelope) ──
def _zero_authority(body: Mapping) -> bool:
    auth = body.get("authority") or {}
    return all(auth.get(k) is False for k in _AUTHORITY_KEYS)


def classify_agent_runtime(http_code: int, body: Mapping | None) -> str:
    body = body or {}
    if http_code == 404:
        return "MOUNT_ABSENT"
    if http_code == 503:
        if body.get("read_only") is True and body.get("connected") is False and _zero_authority(body):
            return "MOUNTED_DISCONNECTED"
        return "MOUNTED_DISCONNECTED_MALFORMED"
    if http_code == 200:
        if body.get("read_only") is True and body.get("connected") is True and _zero_authority(body):
            return "CONNECTED_READ_ONLY"
        return "CONNECTED_MALFORMED"
    return f"UNEXPECTED_HTTP_{http_code}"


def mount_contract_ok(http_code: int, body: Mapping | None) -> bool:
    """MOUNT success = deployed-but-disconnected: 503, read_only, zero-authority, connected:false."""
    return classify_agent_runtime(http_code, body) == "MOUNTED_DISCONNECTED"


def connect_contract_ok(http_code: int, body: Mapping | None, expected_role: str) -> bool:
    """CONNECT success = 200, read_only, zero-authority, connected:true, exact reader role."""
    body = body or {}
    return (classify_agent_runtime(http_code, body) == "CONNECTED_READ_ONLY"
            and body.get("reader_role") == expected_role)


# ── reconciled-behavior marker verification (before candidate install) ──
def verify_markers(bundle_text: str, required: Sequence[str]) -> dict:
    present = [m for m in required if m in bundle_text]
    missing = [m for m in required if m not in bundle_text]
    return {"ok": not missing, "present": present, "missing": missing}


# ── static-bundle install / swap / restore decisions (Phase INSTALL + rollback restore) ──
REQUIRED_DIST_FILES = ("index.html", "build-meta.json")
# markers that must survive into the MINIFIED candidate bundle before it may touch the host
REQUIRED_BUNDLE_MARKERS = ("ADMITTED", "QUARANTINED", "ELIGIBLE", "NO DECISION", "agent-runtime")
_HASHED_ASSET = re.compile(r"assets/index-[A-Za-z0-9_-]+\.(?:js|css)$")


def dist_shape_ok(files: Sequence[str]) -> bool:
    """A dir is an installable/restorable dist only if it has index.html, build-meta.json and >=1 asset."""
    fs = set(files)
    return all(r in fs for r in REQUIRED_DIST_FILES) and any(f.startswith("assets/") for f in fs)


def swap_parity(live_files: Sequence[str], candidate_files: Sequence[str]) -> dict:
    """Which live-served files the candidate does NOT provide. Content-hashed bundle assets
    (assets/index-<hash>.js|css) are EXPECTED to be replaced — the new index.html points at the new
    hash — so they are 'superseded', not 'dropped'. Any OTHER missing file is a served-asset
    regression and blocks the swap."""
    missing = set(live_files) - set(candidate_files)
    dropped = sorted(f for f in missing if not _HASHED_ASSET.search(f))
    superseded = sorted(f for f in missing if _HASHED_ASSET.search(f))
    return {"ok": not dropped, "dropped": dropped, "superseded_assets": superseded}


def install_precheck(candidate_meta: Mapping) -> None:
    """Refuse to install a candidate whose build-meta cannot prove exact-ref provenance and the
    agent-runtime contract. Accepts contracts as a list or a {name: contract} mapping."""
    validate_build_source(candidate_meta.get("frontend_build_source", ""))
    _require_full_sha(candidate_meta.get("source_commit", ""))
    contracts = candidate_meta.get("contracts") or {}
    values = list(contracts.values()) if isinstance(contracts, Mapping) else list(contracts)
    if AGENT_RUNTIME_CONTRACT not in values:
        raise BuildSourceError(f"candidate build-meta must declare {AGENT_RUNTIME_CONTRACT}")


def smoke_ok(results: Mapping[str, int], expected: Sequence[int] = (200,)) -> bool:
    """Post-swap HTTP smoke passes only if every probed route returned an expected code."""
    return bool(results) and all(code in expected for code in results.values())


def backup_dir_name(stamp: str, prefix: str = "cc-dist") -> str:
    if not re.fullmatch(r"[0-9]{8}_[0-9]{6}", stamp or ""):
        raise ConvergenceError("backup stamp must be YYYYmmdd_HHMMSS")
    return f"{prefix}-{stamp}"


# ── secret redaction for all evidence/logs ──
_SECRET_PATTERNS = [
    re.compile(r"postgres(?:ql)?://[^\s\"']+", re.I),
    re.compile(r"(?:PG)?PASSWORD\s*[=:]\s*\S+", re.I),
    re.compile(r"(?:api[_-]?key|secret|token|refresh_token|access_token|bearer)\s*[=:]\s*\S+", re.I),
    re.compile(r"APCA-API-[A-Z-]+\s*[=:]\s*\S+", re.I),
]


def redact(text: str) -> str:
    out = text or ""
    for p in _SECRET_PATTERNS:
        out = p.sub("[REDACTED]", out)
    return out


def contains_secret(text: str) -> bool:
    return any(p.search(text or "") for p in _SECRET_PATTERNS)


# ── rollback manifest ──
def rollback_manifest(*, backend_hashes: Mapping[str, str], static_backup: str | None,
                      static_build_meta: Mapping | None, reader_env_present: bool,
                      reader_env_mode: str | None, dropin_present: bool, service_state: str,
                      watch_packets: Mapping[str, str], defense_snapshots: Mapping[str, str]) -> dict:
    return {
        "backend_hashes": dict(backend_hashes),
        "static_backup": static_backup, "static_build_meta": dict(static_build_meta or {}),
        "reader": {"env_present": reader_env_present, "env_mode": reader_env_mode, "dropin_present": dropin_present},
        "service_state": service_state,
        "watch_packets": dict(watch_packets), "defense_snapshots": dict(defense_snapshots),
        "manifest_version": "convergence-rollback-v1",
    }

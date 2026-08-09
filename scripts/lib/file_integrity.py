"""
File Integrity Verification — ensures the Trade AI server is reading the CANONICAL,
uncorrupted state files, not stale copies from old release directories.

Key Principle: NEVER silently patch integrity violations.
  - Hash mismatch on canonical file → P0 alert, do NOT patch
  - Server reading non-canonical file → P0 alert, fix server config
  - Multiple copies of critical files → P1 alert, recommend cleanup
  - File simply stale (old timestamp, hash matches) → safe to trigger refresh pipeline
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FileIntegrity:
    """Verifies file integrity by comparing canonical files against a manifest of expected hashes."""

    def __init__(self, project_root: str | Path | None = None):
        self._project_root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent.parent
        self._manifest_path = self._project_root / "data" / "runtime" / "file_integrity_manifest.json"
        self._manifest: dict[str, Any] = {}
        self._loaded = False

    # ── Manifest loading ──────────────────────────────────────────────────────

    def load_manifest(self) -> dict[str, Any]:
        if not self._manifest_path.exists():
            raise FileNotFoundError(
                f"Integrity manifest not found at {self._manifest_path}. "
                f"Run scripts/generate_integrity_manifest.py to create it."
            )
        self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        self._loaded = True
        return self._manifest

    @property
    def manifest(self) -> dict[str, Any]:
        if not self._loaded:
            self.load_manifest()
        return self._manifest

    # ── Hashing ────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_sha256(file_path: str | Path) -> str:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Cannot compute hash: {p} does not exist")
        return hashlib.sha256(p.read_bytes()).hexdigest()

    # ── Single file verification ──────────────────────────────────────────────

    def verify_file(self, file_key: str) -> dict[str, Any]:
        """
        Verify a single file against the manifest.
        Returns a dict with keys: status, alerts[], file_key, canonical_path, expected_hash,
        actual_hash, size_match, stale, age_minutes, max_age_minutes, error.
        """
        manifest = self.manifest
        if file_key not in manifest["files"]:
            return {
                "status": "UNKNOWN_FILE",
                "alerts": [{"severity": "P0", "message": f"File key '{file_key}' not in integrity manifest"}],
                "file_key": file_key,
            }

        entry = manifest["files"][file_key]
        canonical_path = self._project_root / entry["canonical_path"]
        alerts: list[dict[str, str]] = []
        result: dict[str, Any] = {
            "status": "OK",
            "file_key": file_key,
            "canonical_path": str(canonical_path),
            "expected_hash": entry["sha256"],
            "expected_size": entry.get("size"),
            "actual_hash": None,
            "actual_size": None,
            "size_match": None,
            "hash_match": None,
            "stale": None,
            "age_minutes": None,
            "max_age_minutes": entry.get("max_age_minutes"),
            "alerts": alerts,
        }

        if not canonical_path.exists():
            result["status"] = "MISSING"
            alerts.append({
                "severity": "P0",
                "message": f"[MISSING] Canonical file not found: {canonical_path}",
            })
            return result

        # Compute actual hash
        try:
            actual_hash = self.compute_sha256(canonical_path)
            actual_size = canonical_path.stat().st_size
        except Exception as e:
            result["status"] = "UNREADABLE"
            alerts.append({
                "severity": "P0",
                "message": f"[UNREADABLE] Cannot read canonical file {canonical_path}: {e}",
            })
            return result

        result["actual_hash"] = actual_hash
        result["actual_size"] = actual_size

        # Hash comparison
        expected_hash = entry["sha256"]
        result["hash_match"] = (actual_hash == expected_hash)
        if not result["hash_match"]:
            result["status"] = "HASH_MISMATCH"
            alerts.append({
                "severity": "P0",
                "message": (
                    f"[CORRUPTED] Canonical file hash mismatch for {file_key} at {canonical_path}. "
                    f"Expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
                ),
                "action": "DO NOT PATCH AUTOMATICALLY — investigate corruption/tampering. "
                          "Run generate_integrity_manifest.py if this is a legitimate update.",
            })

        # Size comparison (secondary check, hash is authoritative)
        expected_size = entry.get("size")
        if expected_size is not None and actual_size != expected_size:
            result["size_match"] = False
            if result["status"] == "OK":
                result["status"] = "SIZE_MISMATCH"
                alerts.append({
                    "severity": "P0",
                    "message": (
                        f"[SIZE_MISMATCH] Canonical file {file_key} size changed: "
                        f"expected {expected_size}, got {actual_size}"
                    ),
                    "action": "File has been modified. Run generate_integrity_manifest.py to update manifest.",
                })
        else:
            result["size_match"] = True

        # Staleness check (only if hash matches — stale is about age, not corruption)
        max_age = entry.get("max_age_minutes")
        if max_age is not None:
            mtime = canonical_path.stat().st_mtime
            age_seconds = datetime.now().timestamp() - mtime
            age_minutes = age_seconds / 60.0
            result["age_minutes"] = round(age_minutes, 1)
            result["stale"] = age_minutes > max_age

            if result["stale"]:
                if result["status"] == "OK" and result["hash_match"] is True:
                    # Safe staleness: file unmodified, just old — OK to trigger refresh
                    result["status"] = "STALE"
                    alerts.append({
                        "severity": "P1",
                        "message": (
                            f"[STALE] {file_key} is {age_minutes:.0f}m old "
                            f"(max {max_age}m) — trigger refresh pipeline {entry.get('source_pipeline', '')}"
                        ),
                        "action": "Safe to trigger refresh — hash matches manifest, file is simply old.",
                    })
                else:
                    # File is stale AND corrupted — corruption takes priority
                    alerts.append({
                        "severity": "P1",
                        "message": (
                            f"[STALE+CORRUPT] {file_key} is {age_minutes:.0f}m old AND has integrity issues. "
                            f"Fix integrity first, then refresh."
                        ),
                    })

        return result

    # ── Full verification ─────────────────────────────────────────────────────

    def verify_all(self) -> dict[str, Any]:
        """
        Verify all files in the manifest. Returns a summary dict with overall status
        and per-file results.
        """
        manifest = self.manifest
        results: dict[str, Any] = {
            "manifest_version": manifest.get("version"),
            "manifest_generated": manifest.get("generated"),
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "total_files": 0,
            "ok": 0,
            "stale": 0,
            "p0_alerts": 0,
            "p1_alerts": 0,
            "files": {},
        }

        for file_key in manifest["files"]:
            result = self.verify_file(file_key)
            results["files"][file_key] = result
            results["total_files"] += 1

            if result["status"] == "OK":
                results["ok"] += 1
            elif result["status"] == "STALE":
                results["stale"] += 1

            for alert in result.get("alerts", []):
                if alert["severity"] == "P0":
                    results["p0_alerts"] += 1
                elif alert["severity"] == "P1":
                    results["p1_alerts"] += 1

        if results["p0_alerts"] > 0:
            results["overall_status"] = "CRITICAL"
        elif results["p1_alerts"] > 0:
            results["overall_status"] = "WARNING"
        else:
            results["overall_status"] = "HEALTHY"

        return results

    # ── Stale copy detection ──────────────────────────────────────────────────

    def scan_stale_copies(self) -> list[dict[str, Any]]:
        """
        Scan the filesystem for any file named like a critical basename that exists
        OUTSIDE the canonical path. Returns a list of stale copy findings.
        """
        manifest = self.manifest
        critical_basenames = manifest.get("critical_basenames", [])
        if not critical_basenames:
            # Fallback: extract basenames from canonical paths
            critical_basenames = [
                os.path.basename(entry["canonical_path"])
                for entry in manifest["files"].values()
            ]

        stale_copies: list[dict[str, Any]] = []

        for basename in critical_basenames:
            canonical_path = None
            for file_key, entry in manifest["files"].items():
                if os.path.basename(entry["canonical_path"]) == basename:
                    canonical_path = self._project_root / entry["canonical_path"]
                    break

            # Walk the project tree looking for this basename
            found_paths: list[Path] = []
            for root, _dirs, files in os.walk(str(self._project_root)):
                # Skip .git, __pycache__, venv, node_modules
                skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".cursor"}
                dir_basename = os.path.basename(root)
                if dir_basename in skip_dirs:
                    _dirs[:] = []
                    continue
                if basename in files:
                    full_path = Path(root) / basename
                    found_paths.append(full_path)

            canonical_abs = canonical_path.resolve() if canonical_path else None

            for fp in found_paths:
                resolved = fp.resolve()
                # Skip the canonical path itself
                if canonical_abs and resolved == canonical_abs.resolve():
                    continue

                # Skip obvious backup directories (file_backups/, backups/, *.bak)
                fp_str = str(resolved)
                if any(seg in fp_str for seg in ["/file_backups/", "/backups/", ".bak"]):
                    continue

                try:
                    actual_hash = self.compute_sha256(resolved)
                    actual_size = resolved.stat().st_size
                except Exception:
                    actual_hash = "UNREADABLE"
                    actual_size = 0

                # Determine which file_key this belongs to
                matching_key = os.path.splitext(basename)[0]
                canonical_entry = None
                for fk, entry in manifest["files"].items():
                    if os.path.basename(entry["canonical_path"]) == basename:
                        matching_key = fk
                        canonical_entry = entry
                        break

                stale_copies.append({
                    "file_key": matching_key,
                    "basename": basename,
                    "canonical_path": str(canonical_abs) if canonical_abs else "UNKNOWN",
                    "stale_copy_path": str(resolved),
                    "stale_copy_hash": actual_hash,
                    "stale_copy_size": actual_size,
                    "severity": "P1",
                    "message": (
                        f"[STALE_COPY] Extra copy of {basename} found at {resolved}. "
                        f"Canonical path is {canonical_abs}. "
                        f"Stale copy is {'different from' if canonical_entry and actual_hash != canonical_entry.get('sha256') else 'identical to'} canonical."
                    ),
                })

        return stale_copies

    # ── Server path cross-check ───────────────────────────────────────────────

    def cross_check_server_reading(self, server_dir: str | None = None) -> dict[str, Any]:
        """
        Cross-check what the live server is reading against the canonical manifest.
        If server_dir is None, discovers it automatically from port 7777.

        Returns a dict with server_dir, files the server would read, and whether
        each is canonical.
        """
        if server_dir is None:
            server_dir = self._discover_server_directory()

        manifest = self.manifest
        result: dict[str, Any] = {
            "status": "OK",
            "server_dir": server_dir,
            "server_pid": self._find_port_pid(7777),
            "alerts": [],
            "files": {},
        }

        if not server_dir:
            result["status"] = "NO_SERVER_FOUND"
            result["alerts"].append({
                "severity": "P2",
                "message": "No live server found on port 7777",
            })
            return result

        server_root = Path(server_dir)

        for file_key, entry in manifest["files"].items():
            canonical_path = self._project_root / entry["canonical_path"]
            server_path = server_root / entry["canonical_path"]

            canonical_exists = canonical_path.exists()
            server_exists = server_path.exists()

            file_result: dict[str, Any] = {
                "file_key": file_key,
                "canonical_path": str(canonical_path),
                "server_path": str(server_path),
                "canonical_exists": canonical_exists,
                "server_has_copy": server_exists,
                "server_reads_canonical": False,
                "alerts": [],
            }

            if server_exists:
                # Check if server is reading the canonical file
                try:
                    canonical_resolved = canonical_path.resolve()
                    server_resolved = server_path.resolve()
                    file_result["server_reads_canonical"] = (canonical_resolved == server_resolved)
                except Exception:
                    file_result["server_reads_canonical"] = False

                if not file_result["server_reads_canonical"]:
                    # P0: Server is reading a non-canonical file
                    try:
                        server_hash = self.compute_sha256(server_path)
                        canonical_hash = entry.get("sha256", "")
                        hash_matches = (server_hash == canonical_hash)
                    except Exception:
                        server_hash = "UNREADABLE"
                        hash_matches = False

                    file_result["server_hash"] = server_hash
                    file_result["server_hash_matches_canonical"] = hash_matches

                    alert = {}
                    if hash_matches:
                        # Same content but different path — could be a legit copy
                        alert = {
                            "severity": "P0",
                            "message": (
                                f"[NON_CANONICAL_SAME_CONTENT] Server is reading {file_key} "
                                f"from {server_path} instead of canonical {canonical_path}. "
                                f"Content matches but path differs — likely an old release directory."
                            ),
                            "action": "Update server to read from canonical path or regenerate release.",
                        }
                    else:
                        # DIFFERENT content AND different path — server has stale/wrong data
                        alert = {
                            "severity": "P0",
                            "message": (
                                f"[NON_CANONICAL_STALE] Server is reading {file_key} "
                                f"from {server_path} instead of canonical {canonical_path}. "
                                f"Content is DIFFERENT — server may be serving stale/corrupt data."
                            ),
                            "action": "DO NOT PATCH the stale file. Fix server configuration to read canonical path.",
                        }
                    result["alerts"].append(alert)
                    file_result["alerts"] = [alert]

            elif canonical_exists:
                # Server is missing a file that exists canonically
                alert = {
                    "severity": "P1",
                    "message": (
                        f"[MISSING_ON_SERVER] {file_key} exists at canonical path {canonical_path} "
                        f"but is missing from server directory {server_path}"
                    ),
                }
                result["alerts"].append(alert)
                file_result["alerts"].append(alert)

            result["files"][file_key] = file_result

        # Determine overall status
        has_p0 = any(
            a.get("severity") == "P0"
            for f in result["files"].values()
            for a in f.get("alerts", [])
        )
        if has_p0:
            result["status"] = "CRITICAL"

        return result

    # ── Discovery helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _find_port_pid(port: int) -> int | None:
        try:
            result = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=5
            )
            import re
            for line in result.stdout.split("\n"):
                if f":{port}" in line:
                    m = re.search(r"pid=(\d+)", line)
                    if m:
                        return int(m.group(1))
        except Exception:
            pass
        return None

    @staticmethod
    def _discover_server_directory() -> str | None:
        """Discover the directory the live server on port 7777 is running from."""
        pid = FileIntegrity._find_port_pid(7777)
        if not pid:
            return None
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            return cwd
        except Exception:
            pass
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read()
            import re
            m = re.search(rb"/(?:[^/\s]+/)+[^/\s]+\.py", cmdline)
            if m:
                script = m.group(0).decode()
                server_dir = str(Path(script).resolve().parent.parent)
                if os.path.isdir(server_dir):
                    return server_dir
        except Exception:
            pass
        return None

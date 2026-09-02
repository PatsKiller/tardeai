"""Pure decision helpers for AGENTS.md Drive mirror (SOP Stage 8 fixtures).

No network. No credentials. Used by tests to prove create/update/duplicate/
readback/hash-mismatch behavior without writing to Drive.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class MirrorDecision:
    action: str  # create | update | stop_duplicate | reject_hash_mismatch | reject_readback
    file_id: Optional[str]
    reason: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decide_mirror_action(
    *,
    matching_files: list[dict[str, Any]],
    stable_file_id: Optional[str],
    local_sha: str,
    remote_sha: Optional[str],
    readback_ok: bool,
) -> MirrorDecision:
    """Decide create/update/stop given folder listing and readback result.

    matching_files: non-trashed Drive objects named AGENTS.md in the target folder.
    """
    live = [f for f in matching_files if not f.get("trashed")]
    if len(live) > 1:
        return MirrorDecision("stop_duplicate", None, f"{len(live)} AGENTS.md files; operator must reconcile")
    if not readback_ok:
        return MirrorDecision(
            "reject_readback",
            stable_file_id or (live[0].get("id") if live else None),
            "readback download failed; manifest not written",
        )
    if remote_sha is not None and remote_sha != local_sha:
        return MirrorDecision(
            "reject_hash_mismatch",
            stable_file_id or (live[0].get("id") if live else None),
            f"BYTE MISMATCH local={local_sha} remote={remote_sha}",
        )
    if len(live) == 0 and not stable_file_id:
        return MirrorDecision("create", None, "zero matching files — create exactly one")
    if stable_file_id:
        return MirrorDecision("update", stable_file_id, "update existing stable file id")
    if len(live) == 1:
        return MirrorDecision("update", str(live[0].get("id")), "one match — update that id")
    return MirrorDecision("create", None, "fallback create")

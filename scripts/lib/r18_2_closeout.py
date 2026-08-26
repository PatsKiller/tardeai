"""R18.2 local closeout. Does not push. Does not flip the canary."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.lib.cio_delivery_audit import audit_delivery_flags
from scripts.lib.persistent_state_root import GOOD_PERSISTENT_ROOT, is_provisioned, load_stamp

AUTHORITY = "READ_ONLY_ADVISORY"


def closeout() -> dict[str, Any]:
    flags = audit_delivery_flags()
    stamp = load_stamp()
    provisioned = is_provisioned()
    return {
        "schema": "R18_2_PRODUCTION_HARDENING@v1",
        "GOOD_PERSISTENT_ROOT": str(GOOD_PERSISTENT_ROOT),
        "provisioned": provisioned,
        "stamp": {k: stamp.get(k) for k in ("schema", "path", "legacy_source", "n_copied") if stamp},
        "canary_changed": False,
        "LIVE_CIO_DELIVERY_AUTHORIZATION_REQUIRED": flags.get("LIVE_CIO_DELIVERY_AUTHORIZATION_REQUIRED"),
        "authorization_one_liner": flags.get("authorization_one_liner"),
        "destructive_cleanup": False,
        "github": {"pushes": 0, "ci_cycles": 0},
        "authority": AUTHORITY,
        "financial_action": False,
        "exact_one_sync_command": (
            "TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin feat/r18-2-production-hardening "
            "&& gh pr create --base main --head feat/r18-2-production-hardening "
            "--title \"feat(r18.2): persistent-state root, product completeness, delivery audit\" "
            "--body \"R18.2 production hardening. One PR, one CI. Canary unchanged.\""
        ),
    }

"""Deduplicated operational errors through the existing incident-ledger writer."""

from pathlib import Path
import logging

LOG = logging.getLogger(__name__)


def record_failure(scope, error, *, root=None):
    """Never leak exception text; fixture/source checkouts cannot write host state."""
    kind = type(error).__name__
    explicit_root = root is not None
    LOG.warning("watch_review_failure", extra={"stage": scope, "error_class": kind})
    try:
        from scripts.lib import incidents

        if root is None:
            from scripts.lib.persistent_state_root import good_persistent_root

            root = good_persistent_root()
            if (Path(__file__).resolve().parents[2] / "data/cio").resolve() != (root / "data/cio").resolve():
                raise ValueError("incident_runtime_root_unproven")
        rec, _ = incidents.open_incident(
            source={"kind": "job", "job": "watch-review"},
            title="Watch CIO review unavailable",
            where="watch-review:" + scope,
            fingerprint="watch-review:" + scope + ":" + kind,
            evidence=["error_class:" + kind, "surface:watch-system-suggests"],
            owner="watch-review",
            actor="watch-review",
            d=Path(root) / incidents.DEFAULT_REL if explicit_root else incidents.incidents_dir(),
        )
        return rec["id"]
    except Exception as exc:
        LOG.warning("watch_review_incident_unavailable", extra={"stage": scope, "error_class": type(exc).__name__})
        return None

"""n8n_live_inventory.py — read-only view of the lab n8n instance for governance checks.

AGENTS.md 3.0.0 §23.10 P16 (attribution), P17 (registry-first) and P18 (drift) all need the same three
reads of the n8n database: which workflows are active, what their nodes look like, and when each one was
published. This module is the one place those reads live, so the three checks cannot disagree about what
"active" means.

Every read is a single ``SELECT`` through ``docker exec <db container> psql -U n8n -d n8n -tAc`` (the
lab's documented read path; no host port, no credential on this side). ``run_select`` refuses anything
that is not a SELECT, so a caller cannot widen this into a write. CI has no docker: the callers take a
committed snapshot or a fixture file instead, and a failed live read raises ``InventoryUnavailable`` —
"could not look" is never reported as "nothing there".

The generated workflow set (``docs/implementation/n8n-parallel/workflows/generated/INDEX.json``) is the
allowlist of known workflow ids: every live and shadow id the generator emitted, committed and pending.

AUTHORITY: READ_ONLY_ADVISORY. No n8n writes, no imports, no activation, no network.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

NO_CONSUMER_REASON = (
    "library for the n8n governance checks (check_lane_registry n8n source, check_n8n_workflow_drift, "
    "check_n8n_activation_grants); it defines snapshot schema literals that those scripts read and write."
)

ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated"
GENERATED_INDEX = GENERATED_DIR / "INDEX.json"
#: Committed list of ACTIVE workflows (id, name) captured from the live instance. CI reads this; the
#: host reads live. Refresh with ``check_lane_registry.py --n8n-live --n8n-snapshot-out <this path>``.
ACTIVE_SNAPSHOT = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "active_workflows_snapshot.json"
SNAPSHOT_SCHEMA = "N8nActiveWorkflowSnapshot@v1"

DB_CONTAINER = "m8m-n8n-db"
DB_USER = "n8n"
DB_NAME = "n8n"

UNDECLARED_N8N_WORKFLOW = "UNDECLARED_N8N_WORKFLOW"

_SELECT_ONLY = re.compile(r"^\s*select\b", re.I)
_WRITE_WORDS = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do)\b", re.I)

WORKFLOW_LIST_SQL = (
    "select coalesce(json_agg(json_build_object('id', id, 'name', name, 'active', active, "
    "'versionId', \"versionId\", 'activeVersionId', \"activeVersionId\", 'updatedAt', \"updatedAt\") "
    "order by id), '[]'::json) from workflow_entity"
)
ACTIVE_LIST_SQL = WORKFLOW_LIST_SQL + " where active"
WORKFLOW_BODIES_SQL = (
    "select coalesce(json_agg(json_build_object('id', id, 'name', name, 'active', active, "
    "'nodes', nodes, 'connections', connections, 'settings', settings, 'versionId', \"versionId\", "
    "'activeVersionId', \"activeVersionId\", 'updatedAt', \"updatedAt\") order by id), '[]'::json) "
    "from workflow_entity"
)
#: Activation evidence. workflow_publish_history records UI activate/deactivate; workflow_published_version
#: records the version currently published (createdAt = when it was published; updatedAt is touched on every
#: n8n restart, so it is NOT an activation time); workflow_history records each imported/saved version.
PUBLISH_HISTORY_SQL = (
    "select coalesce(json_agg(json_build_object('workflow_id', \"workflowId\", 'version_id', \"versionId\", "
    "'event', event, 'at', \"createdAt\") order by \"createdAt\"), '[]'::json) from workflow_publish_history"
)
PUBLISHED_VERSION_SQL = (
    "select coalesce(json_agg(json_build_object('workflow_id', \"workflowId\", 'version_id', "
    '"publishedVersionId", \'at\', "createdAt", \'updated_at\', "updatedAt") order by "createdAt"), '
    "'[]'::json) from workflow_published_version"
)
VERSION_HISTORY_SQL = (
    "select coalesce(json_agg(json_build_object('workflow_id', \"workflowId\", 'version_id', \"versionId\", "
    "'authors', authors, 'at', \"createdAt\") order by \"createdAt\"), '[]'::json) from workflow_history"
)


class InventoryUnavailable(RuntimeError):
    """The live read could not be performed (no docker, container down, bad output)."""


Runner = Callable[..., Any]


def run_select(sql: str, *, container: str = DB_CONTAINER, runner: Optional[Runner] = None, timeout: int = 30) -> Any:
    """Run one SELECT that returns a single JSON value and parse it. Refuses anything else."""
    if not _SELECT_ONLY.match(sql) or _WRITE_WORDS.search(sql) or ";" in sql:
        raise ValueError("n8n_live_inventory runs a single SELECT only")
    cmd = ["docker", "exec", container, "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", sql]
    run = runner or subprocess.run
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InventoryUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if getattr(proc, "returncode", 1) != 0:
        raise InventoryUnavailable(f"psql exit {proc.returncode}: {str(proc.stderr or '').strip()[:200]}")
    out = str(proc.stdout or "").strip()
    if not out:
        raise InventoryUnavailable("psql returned no output")
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise InventoryUnavailable(f"psql output is not JSON: {exc}") from exc


def read_active_workflows(*, container: str = DB_CONTAINER, runner: Optional[Runner] = None) -> list[dict]:
    rows = run_select(ACTIVE_LIST_SQL, container=container, runner=runner)
    return [r for r in rows or [] if r.get("active")]


def read_workflow_bodies(*, container: str = DB_CONTAINER, runner: Optional[Runner] = None) -> list[dict]:
    return list(run_select(WORKFLOW_BODIES_SQL, container=container, runner=runner) or [])


def read_activation_evidence(*, container: str = DB_CONTAINER, runner: Optional[Runner] = None) -> dict:
    return {
        "workflows": list(run_select(WORKFLOW_LIST_SQL, container=container, runner=runner) or []),
        "publish_history": list(run_select(PUBLISH_HISTORY_SQL, container=container, runner=runner) or []),
        "published_versions": list(run_select(PUBLISHED_VERSION_SQL, container=container, runner=runner) or []),
        "version_history": list(run_select(VERSION_HISTORY_SQL, container=container, runner=runner) or []),
    }


# ── the generated set: the allowlist of known ids, and the git copy of each ───────────────────────


def load_generated_index(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else GENERATED_INDEX
    return json.loads(p.read_text(encoding="utf-8"))


def known_workflow_ids(index: Optional[dict] = None, *, path: Optional[Path] = None) -> dict[str, str]:
    """{workflow id: lane_id} for every live and shadow id in the generated INDEX (committed and pending)."""
    idx = index if index is not None else load_generated_index(path)
    out: dict[str, str] = {}
    for lane in idx.get("lanes") or []:
        for key in ("live_workflow_id", "shadow_workflow_id"):
            wid = lane.get(key)
            if wid:
                out[str(wid)] = str(lane.get("lane_id") or "")
    return out


def git_workflows(generated_dir: Optional[Path] = None) -> dict[str, tuple[Path, dict]]:
    """{workflow id: (file, workflow json)} for every generated workflow file, pending included."""
    base = Path(generated_dir) if generated_dir else GENERATED_DIR
    out: dict[str, tuple[Path, dict]] = {}
    for f in sorted(base.rglob("*.json")):
        if f.name == "INDEX.json":
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("id") and isinstance(doc.get("nodes"), list):
            out[str(doc["id"])] = (f, doc)
    return out


# ── the committed snapshot CI reads ────────────────────────────────────────────────────────────────


def snapshot_doc(active: Iterable[dict], *, captured_at: str, source: str) -> dict:
    rows = sorted(({"id": str(w["id"]), "name": str(w.get("name") or "")} for w in active), key=lambda r: r["id"])
    return {
        "schema": SNAPSHOT_SCHEMA,
        "captured_at": captured_at,
        "source": source,
        "authority": "READ_ONLY_ADVISORY",
        "count": len(rows),
        "workflows": rows,
    }


def load_active_snapshot(path: Optional[Path] = None) -> list[dict]:
    p = Path(path) if path else ACTIVE_SNAPSHOT
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"{p}: schema must be {SNAPSHOT_SCHEMA}")
    return [{"id": str(w["id"]), "name": str(w.get("name") or ""), "active": True} for w in doc.get("workflows") or []]


def discover_n8n(active: Iterable[dict]) -> list[dict]:
    """Discovery rows in the lane-registry shape: one per ACTIVE workflow, keyed by its id."""
    return [
        {"kind": "n8n", "expression": str(w["id"]), "name": str(w.get("name") or "")}
        for w in active
        if w.get("active", True)
    ]

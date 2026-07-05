"""White-Space Discovery — research workspaces: loader, router, isolation gate.

A workspace is an isolation boundary for research output (spec Part F).
Two ship in config/hermes_research_workspaces.yaml:

  trade_ai      default workspace; trading_related, owns the market/portfolio
                research domains and the Command Center / topic_monitor /
                watch_directives / research_sources surfaces.
  nyc_loft_law  NON-trading legal workspace (housing law, NYC regulation,
                case law, tenant rights, landlord compliance, zoning); its
                surfaces are legal/article registries only.

Isolation rules (HARD, enforced here, not by config alone):
  * assert_can_write(workspace_id, surface) — a workspace may write only its
    own output_surfaces, and a trading_related: false workspace can NEVER
    write a trading surface (TRADE_SURFACES) even if the yaml listed one
    (the loader also rejects such a yaml). Violations raise
    WorkspaceIsolationError.
  * assert_tradeable_signal(candidate_or_meta) — a candidate stamped with a
    non-trading workspace (e.g. nyc_loft_law) can never be consumed as a
    trading signal; raises WorkspaceIsolationError.
  * Candidates are stamped with meta_json.workspace_id + workspace_domain by
    inbox.upsert_candidate's enrichment (workspace derived from the research
    domain via workspace_for_domain; sticky once set).

Fail-closed by design: a missing, unparseable, or ambiguous workspace yaml
(duplicate domain claims, unknown default, auto_promote: true, a non-trading
workspace listing a trading surface) raises WorkspaceConfigError — intake
never proceeds against a broken isolation config.

Advisory-only: never imports broker/execution modules, never touches the DB.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACES_PATH = Path(os.getenv("HERMES_RESEARCH_WORKSPACES_YAML")
                       or PROJECT_ROOT / "config" / "hermes_research_workspaces.yaml")

# Surfaces that are trading inputs. A trading_related: false workspace can
# never write these — hard rule, independent of what any yaml says.
TRADE_SURFACES = frozenset({
    "watchlist", "watch_directives", "proposals",
    "staged_ticker_review", "trade_queue",
})


class WorkspaceConfigError(Exception):
    """Raised when the workspace registry fails validation (fail closed)."""


class WorkspaceIsolationError(Exception):
    """Raised on any cross-workspace write / trading-signal violation."""


_cache: dict[str, Any] | None = None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise WorkspaceConfigError(f"workspace registry missing: {path}")
    import yaml
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise WorkspaceConfigError(f"unparseable workspace yaml {path}: {e}") from e
    if not isinstance(data, dict):
        raise WorkspaceConfigError(
            f"workspace yaml {path} must be a mapping, got {type(data).__name__}")
    return data


def _str_list(spec: dict, key: str, *, ws: str, lower: bool = True) -> list[str]:
    raw = spec.get(key)
    if not isinstance(raw, list) or not raw or not all(isinstance(x, str) and x.strip()
                                                       for x in raw):
        raise WorkspaceConfigError(
            f"workspace {ws!r}: {key} must be a non-empty list of strings")
    out = [x.strip() for x in raw]
    return [x.lower() for x in out] if lower else out


def _validate_workspace(ws_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise WorkspaceConfigError(f"workspace {ws_id!r} must be a mapping")
    if "trading_related" not in spec or not isinstance(spec["trading_related"], bool):
        raise WorkspaceConfigError(
            f"workspace {ws_id!r}: trading_related must be an explicit boolean")
    if bool(spec.get("auto_promote")):
        raise WorkspaceConfigError(
            f"workspace {ws_id!r}: auto_promote must be false (hard rule)")

    trading = bool(spec["trading_related"])
    surfaces = _str_list(spec, "output_surfaces", ws=ws_id)
    if not trading:
        bad = sorted(set(surfaces) & TRADE_SURFACES)
        if bad:
            raise WorkspaceConfigError(
                f"workspace {ws_id!r} is trading_related=false but lists trading "
                f"surface(s) {bad} — forbidden (isolation hard rule)")

    return {
        "workspace_id": ws_id,
        "description": str(spec.get("description") or "").strip(),
        "trading_related": trading,
        "auto_promote": False,  # always false — hard rule
        "domains": _str_list(spec, "domains", ws=ws_id),
        "output_surfaces": surfaces,
        "requires_professional_review_label": bool(
            spec.get("requires_professional_review_label", False)),
        "no_legal_advice_label": bool(spec.get("no_legal_advice_label", False)),
    }


def load_workspaces(path: Path | str | None = None,
                    force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """Load + validate the workspace registry. Returns {workspace_id: spec}.

    The result dict also carries the default under load_workspaces()[...] via
    default_workspace(); every validation failure raises WorkspaceConfigError
    (fail closed). Cached for the default path; explicit paths (tests) always
    load fresh.
    """
    global _cache
    default_path = path is None
    if default_path and _cache is not None and not force_reload:
        return _cache["workspaces"]

    data = _read_yaml(Path(path) if path else WORKSPACES_PATH)
    raw = data.get("workspaces")
    if not isinstance(raw, dict) or not raw:
        raise WorkspaceConfigError("workspace yaml must define a non-empty "
                                   "'workspaces' mapping")

    workspaces: dict[str, dict[str, Any]] = {}
    domain_owner: dict[str, str] = {}
    for ws_id, spec in raw.items():
        ws_id = str(ws_id).strip().lower()
        workspaces[ws_id] = _validate_workspace(ws_id, spec)
        for dom in workspaces[ws_id]["domains"]:
            if dom in domain_owner:
                raise WorkspaceConfigError(
                    f"domain {dom!r} claimed by both {domain_owner[dom]!r} and "
                    f"{ws_id!r} — a domain may belong to at most one workspace")
            domain_owner[dom] = ws_id

    default = str(data.get("default_workspace") or "").strip().lower()
    if default not in workspaces:
        raise WorkspaceConfigError(
            f"default_workspace {default!r} is not a defined workspace "
            f"(defined: {sorted(workspaces)})")

    if default_path:
        # explicit-path loads (tests) never poison the module cache
        _cache = {"workspaces": workspaces, "default": default,
                  "domain_owner": domain_owner}
    return workspaces


def _loaded() -> dict[str, Any]:
    load_workspaces()
    assert _cache is not None
    return _cache


def default_workspace() -> str:
    """The workspace id that owns every unclaimed domain."""
    return _loaded()["default"]


def get_workspace(workspace_id: str) -> dict[str, Any]:
    """Fetch one workspace spec. Unknown id raises (fail closed)."""
    key = str(workspace_id or "").strip().lower()
    workspaces = _loaded()["workspaces"]
    if key not in workspaces:
        raise WorkspaceConfigError(
            f"unknown workspace {workspace_id!r} (defined: {sorted(workspaces)})")
    return dict(workspaces[key])


def workspace_for_domain(domain: str) -> str:
    """Route a research domain to its owning workspace id.

    Exactly one workspace may claim a domain (validated at load); every
    unclaimed domain belongs to the default workspace.
    """
    key = str(domain or "").strip().lower()
    loaded = _loaded()
    return loaded["domain_owner"].get(key, loaded["default"])


def assert_can_write(workspace_id: str, surface: str) -> None:
    """ISOLATION ENFORCEMENT — the single write gate for workspace output.

    Raises WorkspaceIsolationError when:
      * the workspace is trading_related: false and the surface is a trading
        surface (watchlist / watch_directives / proposals /
        staged_ticker_review / trade_queue) — ALWAYS blocked; or
      * the surface is not one of the workspace's declared output_surfaces.
    Unknown workspace ids raise WorkspaceConfigError (fail closed).
    """
    ws = get_workspace(workspace_id)
    key = str(surface or "").strip().lower()
    if not key:
        raise WorkspaceIsolationError("empty surface name")
    if key in TRADE_SURFACES and not ws["trading_related"]:
        raise WorkspaceIsolationError(
            f"workspace {ws['workspace_id']!r} is non-trading and can NEVER "
            f"write trading surface {key!r}")
    if key not in ws["output_surfaces"]:
        raise WorkspaceIsolationError(
            f"workspace {ws['workspace_id']!r} may not write surface {key!r} "
            f"(allowed: {ws['output_surfaces']})")


def candidate_workspace(candidate_or_meta: dict[str, Any] | None) -> str:
    """Workspace id stamped on a candidate row / meta dict (or derived from
    its research domain; default workspace as the last resort)."""
    obj = candidate_or_meta or {}
    meta = obj.get("meta_json") if isinstance(obj.get("meta_json"), dict) else obj
    ws = str((meta or {}).get("workspace_id") or "").strip().lower()
    if ws and ws in _loaded()["workspaces"]:
        return ws
    domain = str((meta or {}).get("research_domain")
                 or (meta or {}).get("workspace_domain") or "").strip().lower()
    if domain:
        return workspace_for_domain(domain)
    return default_workspace()


def assert_tradeable_signal(candidate_or_meta: dict[str, Any] | None) -> None:
    """ISOLATION ENFORCEMENT — a candidate from a non-trading workspace
    (e.g. nyc_loft_law) can never be consumed as a trading signal."""
    ws_id = candidate_workspace(candidate_or_meta)
    ws = get_workspace(ws_id)
    if not ws["trading_related"]:
        raise WorkspaceIsolationError(
            f"candidate belongs to non-trading workspace {ws_id!r} and can "
            f"never be used as a trading signal")


# test/support hook
def _reset_cache() -> None:
    global _cache
    _cache = None

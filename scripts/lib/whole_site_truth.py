#!/usr/bin/env python3
"""whole_site_truth.py — server-side authority for the Command Center's own honesty.

Three separate defects share one root cause: the browser was allowed to decide
something only the server can know.

  * Eleven ``/v3/control-plane/*`` routes compile fixture JSON into the bundle and
    label themselves PREVIEW/FIXTURE from a client constant, while nine live
    ``/api/v3/control-plane/*`` domains exist and answer. A page that ships its
    own label can ship the wrong one, and a fixture that renders identically to
    live data is indistinguishable from live data.
  * The admin write token and operator identity live in ``localStorage``. A value
    the browser can set is not an authorization decision; it is a request.
  * ``/v3-next`` is served from ``/home/johnclaw/deploy/v3-next/current``, outside
    the repository, with no build manifest — an operator cannot tell what code
    they are looking at.

This module answers all three from the server, deterministically, so the UI
renders a fact instead of asserting one.

AUTHORITY: READ_ONLY_ADVISORY. Pure inspection — stat, read, parse. No write, no
broker, no order, no scheduler, no credential, no production mutation. Nothing
here decides whether an operator may act; it reports who decides.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "WholeSiteTruth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "1.0.0"

# ── Data modes ───────────────────────────────────────────────────────────────
# A surface renders exactly one of these, and the SERVER says which.
LIVE_GOVERNED = "LIVE_GOVERNED"  # a served endpoint answered with real data
PREVIEW_FIXTURE = "PREVIEW_FIXTURE"  # a build-time fixture is compiled into the bundle
FROZEN_SNAPSHOT = "FROZEN_SNAPSHOT"  # a captured point-in-time artifact, never refreshed
UNAVAILABLE = "UNAVAILABLE"  # the backing source is absent or unreadable
UNKNOWN = "UNKNOWN"  # could not be determined — never guessed

#: Control-plane surfaces, keyed by SPA route. ``domain`` is the control_plane_api
#: domain that backs it; ``bundled_fixture`` is the module that compiles JSON into
#: the bundle. A route with a bundled fixture can never be reported LIVE_GOVERNED
#: without the live domain also answering.
CONTROL_PLANE_SURFACES: dict[str, dict[str, Any]] = {
    "/v3/control-plane": {"domain": None, "bundled_fixture": None, "tranche": "hub"},
    "/v3/control-plane/system": {"domain": None, "bundled_fixture": None, "tranche": "hub"},
    "/v3/control-plane/agents": {
        "domain": "agents",
        "bundled_fixture": "pages/control-plane/r22/mocks/agents.json",
        "tranche": "r22",
    },
    "/v3/control-plane/workflows": {
        "domain": "workflows",
        "bundled_fixture": "pages/control-plane/r22/mocks/workflows.json",
        "tranche": "r22",
    },
    "/v3/control-plane/research": {
        "domain": "research",
        "bundled_fixture": "pages/control-plane/r23/preview/research.json",
        "tranche": "r23",
    },
    "/v3/control-plane/data": {
        "domain": "stores",
        "bundled_fixture": "pages/control-plane/r23/preview/stores.json",
        "tranche": "r23",
    },
    "/v3/control-plane/identity": {
        "domain": "identity",
        "bundled_fixture": "pages/control-plane/r23/preview/identity.json",
        "tranche": "r23",
    },
    "/v3/control-plane/notifications": {
        "domain": "notifications",
        "bundled_fixture": "pages/control-plane/r23/preview/notifications.json",
        "tranche": "r23",
    },
    "/v3/control-plane/learning": {
        "domain": "learning",
        "bundled_fixture": "pages/control-plane/r24/frozen/learning.json",
        "tranche": "r24",
    },
    "/v3/control-plane/maturity": {
        "domain": "maturity",
        "bundled_fixture": "pages/control-plane/r24/frozen/maturity.json",
        "tranche": "r24",
    },
    "/v3/control-plane/audit": {
        "domain": "audit",
        "bundled_fixture": "pages/control-plane/r24/frozen/audit.json",
        "tranche": "r24",
    },
}

FRONTEND_SRC = "apps/command-center-v3/src"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(root: Path | str | None = None) -> Path:
    return Path(root) if root else ROOT


# ── 1. Control-plane surface authority (F08) ─────────────────────────────────


def _served_state_root() -> Path:
    """The root the RUNNING service reads, not the checkout this file lives in.

    control_plane_api resolves stores under ``TRADEAI_STATE_ROOT`` when set and
    otherwise under its own package root. A worktree copy of the code therefore
    reports UNAVAILABLE for stores the deployed service serves perfectly well —
    the same producer/served fork this campaign exists to make visible. Reporting
    the checkout's answer as the operator's answer would be a new lie, so the
    served root is resolved explicitly and both answers are published.
    """
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return Path.home() / "trade-ai-releases" / "persistent-state"


def _probe_domain(domain: str, state_root: Path, root: Path) -> dict[str, Any]:
    """One in-process control_plane_api read, pinned to an explicit state root."""
    import sys

    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    prev = os.environ.get("TRADEAI_STATE_ROOT")
    os.environ["TRADEAI_STATE_ROOT"] = str(state_root)
    try:
        import control_plane_api as cpa  # type: ignore

        if domain not in cpa.CONTROL_PLANE_DOMAINS:
            return {"served": False, "reason": f"domain {domain!r} is not registered"}
        status, body = cpa.handle(f"/api/v3/control-plane/{domain}")
    except Exception as exc:  # noqa: BLE001
        return {"served": False, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        if prev is None:
            os.environ.pop("TRADEAI_STATE_ROOT", None)
        else:
            os.environ["TRADEAI_STATE_ROOT"] = prev
    if status != 200 or not isinstance(body, dict):
        return {"served": False, "reason": f"HTTP {status}"}
    data = body.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    return {
        "served": True,
        "http_status": status,
        "ok": bool(body.get("ok")),
        "data_quality": body.get("data_quality"),
        "evidence_class": body.get("evidence_class"),
        "freshness": body.get("freshness"),
        "item_count": len(items) if isinstance(items, list) else None,
        "reason": None,
    }


def _domain_state(domain: str | None, root: Path) -> dict[str, Any]:
    """What the operator's browser actually gets, plus what this checkout would give."""
    if not domain:
        return {
            "served": False,
            "data_quality": None,
            "item_count": None,
            "reason": "no backing domain",
            "state_root": None,
            "checkout": None,
            "roots_disagree": False,
        }
    served_root = _served_state_root()
    served = _probe_domain(domain, served_root, root)
    checkout = _probe_domain(domain, root, root)
    served["state_root"] = str(served_root)
    served["checkout"] = {
        "state_root": str(root),
        "data_quality": checkout.get("data_quality"),
        "item_count": checkout.get("item_count"),
    }
    served["roots_disagree"] = served.get("data_quality") != checkout.get("data_quality")
    return served


def _fixture_state(rel: str | None, root: Path) -> dict[str, Any]:
    if not rel:
        return {"bundled": False, "path": None, "bytes": None, "item_count": None}
    p = root / FRONTEND_SRC / rel
    if not p.is_file():
        return {"bundled": False, "path": rel, "bytes": None, "item_count": None}
    raw = p.read_bytes()
    n = None
    try:
        doc = json.loads(raw)
        payload = doc.get("payload") if isinstance(doc, dict) else None
        body = payload if isinstance(payload, dict) else (doc.get("data") if isinstance(doc, dict) else None)
        if isinstance(body, dict) and isinstance(body.get("items"), list):
            n = len(body["items"])
    except Exception:  # noqa: BLE001
        n = None
    return {"bundled": True, "path": rel, "bytes": len(raw), "item_count": n}


def control_plane_surface_authority(root: Path | str | None = None) -> dict[str, Any]:
    """Server-declared data mode for every ``/v3/control-plane/*`` route.

    The mode is derived from what the server can actually serve, never from a
    constant in the bundle:

      LIVE_GOVERNED    the backing domain answered with ``data_quality=AVAILABLE``
      UNAVAILABLE      the domain answered but has no usable data
      PREVIEW_FIXTURE  no live domain; a build-time fixture is compiled in
      FROZEN_SNAPSHOT  an r24 captured artifact with no live domain behind it
      UNKNOWN          nothing could be determined

    ``banner_required`` is true for every mode except LIVE_GOVERNED, and
    ``banner_dismissible`` is always false: a fixture that can be dismissed is a
    fixture that will be mistaken for live data.
    """
    r = _root(root)
    surfaces = []
    for route, spec in CONTROL_PLANE_SURFACES.items():
        dom = _domain_state(spec["domain"], r)
        fix = _fixture_state(spec["bundled_fixture"], r)
        quality = dom.get("data_quality")

        if dom["served"] and quality == "AVAILABLE":
            mode = LIVE_GOVERNED
            why = f"/api/v3/control-plane/{spec['domain']} answered data_quality=AVAILABLE"
        elif dom["served"] and quality in ("UNAVAILABLE", "INVALID_SCHEMA", "EMPTY"):
            mode = UNAVAILABLE
            why = f"/api/v3/control-plane/{spec['domain']} answered data_quality={quality}"
        elif fix["bundled"] and spec["tranche"] == "r24":
            mode = FROZEN_SNAPSHOT
            why = f"no live domain; frozen artifact {fix['path']} is compiled into the bundle"
        elif fix["bundled"]:
            mode = PREVIEW_FIXTURE
            why = f"no live domain; fixture {fix['path']} is compiled into the bundle"
        elif spec["domain"] is None and not fix["bundled"]:
            mode = PREVIEW_FIXTURE
            why = "navigation-only shadow route with no backing data source"
        else:
            mode = UNKNOWN
            why = dom.get("reason") or "no evidence either way"

        surfaces.append(
            {
                "route": route,
                "tranche": spec["tranche"],
                "data_mode": mode,
                "reason": why,
                "banner_required": mode != LIVE_GOVERNED,
                "banner_dismissible": False,
                "live_domain": spec["domain"],
                "live": dom,
                "bundled_fixture": fix,
                "fixture_may_be_rendered_as_live": False,
            }
        )

    counts: dict[str, int] = {}
    for s in surfaces:
        counts[s["data_mode"]] = counts.get(s["data_mode"], 0) + 1
    return {
        "schema": "ControlPlaneSurfaceAuthority@v1",
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "decided_by": "server",
        "surface_count": len(surfaces),
        "mode_counts": dict(sorted(counts.items())),
        "surfaces": surfaces,
        "rule": (
            "A surface may render LIVE_GOVERNED only when its backing domain answered with "
            "usable data. Every other mode requires an undismissable banner naming the mode "
            "and the reason. A compiled fixture is never a fallback for a failed live read."
        ),
    }


# ── 2. Operator identity / authorization boundary (F09) ──────────────────────

CLIENT_STORED_CREDENTIAL_KEYS = ("admin_write_token", "admin_operator")


def _grep(root: Path, pattern: str, *paths: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "grep", "-l", "-E", pattern, "--", *paths],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    return sorted({ln for ln in out.splitlines() if ln.strip()})


def operator_identity_boundary(root: Path | str | None = None, env: dict | None = None) -> dict[str, Any]:
    """Where the authorization decision is actually made, and where it is not.

    The browser stores ``admin_write_token`` and ``admin_operator`` and sends both
    in the POST body. The token is a *bearer secret*; the operator name is only a
    *claim*. Two different questions follow, and the UI must not merge them:

      1. Is the write authorized?  Only if ``admin_write_guard.access_ok`` compares
         the supplied token against ``ADMIN_WRITE_TOKEN``. That guard returns True
         when the variable is UNSET ("air-gapped default: access is open"), so the
         gate is DECLARED in code and EFFECTIVE only when the running process has
         the variable configured. Declared is not effective.
      2. Is the operator who they say they are?  No. Nothing verifies the name. It
         is an audit label, and a surface that renders it as a verified identity is
         asserting something no component checked.
    """
    r = _root(root)
    environ = env if env is not None else os.environ
    client_files = _grep(r, "|".join(CLIENT_STORED_CREDENTIAL_KEYS), f"{FRONTEND_SRC}/")

    guard = r / "scripts" / "admin_write_guard.py"
    declared = False
    open_when_unset = False
    guard_detail = "scripts/admin_write_guard.py not found"
    if guard.is_file():
        gsrc = guard.read_text(errors="replace")
        declared = "ADMIN_WRITE_TOKEN" in gsrc and "def access_ok" in gsrc
        open_when_unset = bool(re.search(r"return\s*\(?\s*not\s+expected", gsrc))
        guard_detail = "admin_write_guard.access_ok compares the supplied token to ADMIN_WRITE_TOKEN"

    token_configured = bool(environ.get("ADMIN_WRITE_TOKEN"))
    effective = declared and (token_configured or not open_when_unset)

    findings = [
        {
            "id": "AUTHZ-01",
            "statement": "the write token is a long-lived bearer secret held in browser localStorage",
            "keys": ["admin_write_token"],
            "client_files": client_files,
            "is_security_boundary": False,
            "scoped": False,
            "expiring": False,
            "why": (
                "The server holds the secret and compares it, so the browser is not the decision "
                "point; but an unscoped, non-expiring bearer token in localStorage survives every "
                "tab, is readable by any script on the origin, and cannot be revoked per operator."
            ),
        },
        {
            "id": "AUTHZ-02",
            "statement": "operator identity is an unverified client-supplied claim",
            "keys": ["admin_operator"],
            "client_files": client_files,
            "verified_by_server": False,
            "why": (
                "`admin_operator` is written straight into the append-only audit row. It labels the "
                "row; it authenticates no one. Any surface presenting it as a verified identity is "
                "asserting something no component checked."
            ),
        },
        {
            "id": "AUTHZ-03",
            "statement": "the write gate is declared in code and effective only when configured",
            "declared_in": "scripts/admin_write_guard.py::access_ok",
            "declared": declared,
            "open_when_unset": open_when_unset,
            "token_configured_in_this_process": token_configured,
            "effective": effective,
            "detail": guard_detail,
            "why": (
                "access_ok returns True when ADMIN_WRITE_TOKEN is unset. With the variable absent "
                "the guarded door is open and the UI would look identical. Declared-versus-effective "
                "must be reported, never assumed."
            ),
        },
    ]

    return {
        "schema": "OperatorIdentityBoundary@v1",
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "client_storage_is_security_boundary": False,
        "write_gate_declared": declared,
        "write_gate_effective": effective,
        "server_enforces_write_authorization": effective,
        "operator_identity_verified": False,
        "identity_display_source": "client_claim",
        "findings": findings,
        "ui_requirement": (
            "Render the operator name as an unverified audit label, never as an identity. When "
            "write_gate_effective is false, every guarded control must be visibly disabled with the "
            "exact reason; it must never appear armed."
        ),
    }


# ── 3. /v3-next lineage (F10) ────────────────────────────────────────────────

V3_NEXT_ROOT = Path("/home/johnclaw/deploy/v3-next/current")


def v3_next_lineage(static_root: Path | str | None = None, root: Path | str | None = None) -> dict[str, Any]:
    """Git / build / release lineage for the ``/v3-next`` bundle, or an explicit
    NONCANONICAL verdict when there is none.

    ``/v3-next`` is served from a directory outside the repository. If that
    directory carries no manifest, the honest answer is that the served code has
    no provable lineage — not silence.
    """
    r = _root(root)
    d = Path(static_root) if static_root else V3_NEXT_ROOT
    served_by = _grep(r, "v3-next", "scripts/")

    if not d.is_dir():
        return {
            "schema": "V3NextLineage@v1",
            "calculation_version": CALCULATION_VERSION,
            "authority": AUTHORITY,
            "as_of": _now(),
            "static_root": str(d),
            "exists": False,
            "lineage": "ABSENT",
            "canonical": False,
            "served_by": served_by,
            "operator_label": "NONCANONICAL — /v3-next static root is not present on this host",
        }

    manifest = None
    manifest_path = None
    for name in ("build-meta.json", "build_manifest.json", "release.json", "manifest.json"):
        p = d / name
        if p.is_file():
            manifest_path = str(p)
            try:
                manifest = json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                manifest = None
            break

    files = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    newest = max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=None)
    inside_repo = str(d).startswith(str(r))

    sha = None
    if isinstance(manifest, dict):
        sha = manifest.get("git_sha") or manifest.get("source_sha") or manifest.get("build_sha")

    lineage = "PROVEN" if sha else ("MANIFEST_WITHOUT_SHA" if manifest else "NONE")
    return {
        "schema": "V3NextLineage@v1",
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "static_root": str(d),
        "exists": True,
        "inside_repository": inside_repo,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "git_sha": sha,
        "lineage": lineage,
        "canonical": bool(sha) and inside_repo,
        "file_count": len(files),
        "files": files[:50],
        "newest_file_mtime_utc": (datetime.fromtimestamp(newest, tz=timezone.utc).isoformat() if newest else None),
        "served_by": served_by,
        "operator_label": (
            f"lineage {sha[:12]}"
            if sha
            else "NONCANONICAL — served from outside the repository with no build manifest; "
            "the running code cannot be traced to a commit"
        ),
    }


# ── 4. Registered-route disposition (F12.4, orphan pages, OptionsHub) ────────

ROUTE_PATTERN = re.compile(r'path="([^"]+)"')


def registered_routes(root: Path | str | None = None) -> list[str]:
    r = _root(root)
    app = r / FRONTEND_SRC / "App.tsx"
    if not app.is_file():
        return []
    return sorted(set(ROUTE_PATTERN.findall(app.read_text())))


def route_disposition(root: Path | str | None = None) -> dict[str, Any]:
    """Every registered SPA route with an explicit disposition.

    A route is ORPHAN when nothing in the shell links to it: reachable by URL,
    invisible in navigation, and therefore never re-verified by anyone.
    """
    r = _root(root)
    src = r / FRONTEND_SRC
    routes = registered_routes(r)
    app_text = (src / "App.tsx").read_text() if (src / "App.tsx").is_file() else ""

    nav_text = ""
    for cand in (
        "components/Nav.tsx",
        "components/NavBar.tsx",
        "components/Shell.tsx",
        "components/AppShell.tsx",
        "components/Sidebar.tsx",
        "App.tsx",
    ):
        p = src / cand
        if p.is_file():
            nav_text += p.read_text()
    for p in sorted(src.rglob("*.tsx")):
        t = p.read_text(errors="replace")
        if "NavLink" in t or 'to="/' in t:
            nav_text += t

    rows = []
    for route in routes:
        if route in ("/*", "*"):
            rows.append(
                {
                    "route": route,
                    "kind": "catch-all",
                    "linked": True,
                    "disposition": "KEEP",
                    "reason": "SPA 404 fallback",
                }
            )
            continue
        concrete = "/" + route.lstrip("/")
        param = ":" in route
        linked = (
            f'"{concrete}"' in nav_text
            or f"'{concrete}'" in nav_text
            or f'to="{concrete}"' in nav_text
            or f'"/v3{concrete}"' in nav_text
        )
        if param:
            stem = concrete.split(":")[0].rstrip("/")
            linked = linked or (stem and (f"{stem}/" in nav_text))
        cp = concrete.startswith("/control-plane")
        if cp:
            disp, why = "PREVIEW_LABELLED", "control-plane shadow namespace; mode declared by the server"
        elif param:
            disp, why = "KEEP", "parameterised detail route reached from a parent surface"
        elif linked:
            disp, why = "KEEP", "linked from the shell navigation"
        else:
            disp, why = (
                "ORPHAN_LABELLED",
                (
                    "reachable by URL but not linked from navigation; "
                    "must declare its own provenance because nothing else will"
                ),
            )
        rows.append(
            {
                "route": concrete,
                "kind": "param" if param else "static",
                "linked": bool(linked),
                "disposition": disp,
                "reason": why,
            }
        )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
    return {
        "schema": "RouteDisposition@v1",
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "route_count": len(rows),
        "disposition_counts": dict(sorted(counts.items())),
        "routes": rows,
        "app_routes_declared": len(ROUTE_PATTERN.findall(app_text)),
    }

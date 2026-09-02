"""Auto-discover Command Center SPA routes and client API calls."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_TSX = Path("apps/command-center-v3/src/App.tsx")
SRC_ROOT = Path("apps/command-center-v3/src")

ROUTE_RE = re.compile(
    r"""<Route\b[^>]*\bpath\s*=\s*(?:\{\s*)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
# Also catch path="..." without requiring Route adjacency for Navigate aliases
PATH_ATTR_RE = re.compile(r"""\bpath\s*=\s*['"]([^'"]+)['"]""")
API_RE = re.compile(r"""['"`](/api/v2/[^'"`\s?#]+)""")
API_HEALTH_RE = re.compile(r"""['"`](/api/health[^'"`\s?#]*)""")
BUILD_META_RE = re.compile(r"""['"`](/v3/build-meta\.json)""")
TEMPLATE_JUNK = re.compile(r"\$\{|/encodeURIComponent|/\$\{")


@dataclass
class DiscoveredRoute:
    path: str
    url: str
    source: str = str(APP_TSX)


@dataclass
class DiscoveredApi:
    path: str
    method_hint: str = "GET"
    sources: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    basename: str = "/v3"
    routes: list[DiscoveredRoute] = field(default_factory=list)
    apis: list[DiscoveredApi] = field(default_factory=list)
    spa_shell_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "basename": self.basename,
            "route_count": len(self.routes),
            "api_count": len(self.apis),
            "routes": [asdict(r) for r in self.routes],
            "apis": [asdict(a) for a in self.apis],
            "spa_shell_urls": self.spa_shell_urls,
        }


def _normalize_api(raw: str) -> str | None:
    p = raw.split("?")[0].rstrip("/")
    if not p:
        return None
    if TEMPLATE_JUNK.search(p):
        # Keep static prefix before template
        p = re.split(r"/\$\{|/\$\{|/\$\{", p)[0]
        p = p.rstrip("/")
        if p.count("/") < 3 and not p.endswith(("/api/v2", "/api/health")):
            # too truncated
            if not p.startswith("/api/"):
                return None
    # Drop pure template leftovers
    if "${" in p:
        return None
    return p or None


def discover_routes(repo_root: Path) -> DiscoveryResult:
    app = repo_root / APP_TSX
    text = app.read_text(encoding="utf-8", errors="replace")
    paths = set(ROUTE_RE.findall(text))
    # Filter comment junk
    paths = {p for p in paths if not p.startswith("*") and p != "/*"}
    routes: list[DiscoveredRoute] = []
    for p in sorted(paths):
        url = f"/v3/{p}" if p not in {"", "index"} else "/v3/"
        if p == "index":
            url = "/v3/"
        elif not p.startswith("/"):
            url = f"/v3/{p}"
        else:
            url = f"/v3{p}"
        # collapse //
        url = re.sub(r"/{2,}", "/", url)
        if not url.startswith("/v3"):
            url = "/v3/" + url.lstrip("/")
        routes.append(DiscoveredRoute(path=p, url=url, source=str(APP_TSX)))

    # Ensure index
    if not any(r.url == "/v3/" for r in routes):
        routes.insert(0, DiscoveredRoute(path="index", url="/v3/", source=str(APP_TSX)))

    api_map: dict[str, DiscoveredApi] = {}
    src = repo_root / SRC_ROOT
    for fp in src.rglob("*.ts*"):
        try:
            t = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(fp.relative_to(repo_root))
        for m in API_RE.findall(t):
            norm = _normalize_api(m)
            if not norm:
                continue
            api = api_map.setdefault(norm, DiscoveredApi(path=norm))
            if rel not in api.sources:
                api.sources.append(rel)
        for m in API_HEALTH_RE.findall(t):
            norm = _normalize_api(m) or "/api/health"
            api = api_map.setdefault(norm, DiscoveredApi(path=norm))
            if rel not in api.sources:
                api.sources.append(rel)
        for m in BUILD_META_RE.findall(t):
            api = api_map.setdefault(m, DiscoveredApi(path=m))
            if rel not in api.sources:
                api.sources.append(rel)

    # Always include identity endpoints used by runtime audit
    for required in (
        "/api/v2/overview",
        "/api/v2/risk",
        "/api/v2/portfolio/performance",
        "/api/v2/portfolio/book-map",
        "/api/v2/health",
        "/api/v2/trade-ai/summary",
        "/api/v2/risk-regime/latest",
        "/api/v2/paper-proposals",
        "/api/v2/health/proposals",
        "/api/v2/journal",
        "/api/v2/research-intelligence/freshness",
        "/api/health",
        "/v3/build-meta.json",
    ):
        api_map.setdefault(required, DiscoveredApi(path=required, sources=["harness:required"]))

    apis = [api_map[k] for k in sorted(api_map)]
    spa = sorted({r.url for r in routes if ":" not in r.url})
    return DiscoveryResult(routes=routes, apis=apis, spa_shell_urls=spa)


def load_route_ledger(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_to_ledger(
    discovered: DiscoveryResult,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Fail when a page or request is unaccounted for relative to ledger."""
    ledger_routes = {
        (r.get("url") or r.get("route") or "").rstrip("/") or "/"
        for r in ledger.get("routes", ledger.get("spa_routes", []))
    }
    # normalize ledger
    ledger_routes = {
        r if r.startswith("/v3") else f"/v3{r}" if r.startswith("/") else f"/v3/{r}" for r in ledger_routes if r
    }
    ledger_routes = {re.sub(r"/{2,}", "/", r).rstrip("/") or "/v3/" for r in ledger_routes}
    # Fix /v3 alone
    ledger_routes = {
        "/v3/" if r in {"/v3", ""} else (r if r.endswith("/") or ":" in r or r.count("/") > 2 else r)
        for r in ledger_routes
    }

    disc_routes = set()
    for r in discovered.routes:
        u = r.url.rstrip("/") or "/v3/"
        if u == "/v3":
            u = "/v3/"
        disc_routes.add(u)

    ledger_apis = {
        (a.get("path") or a.get("route") or "").split("?")[0]
        for a in ledger.get("apis", ledger.get("api_routes", ledger.get("endpoints", [])))
    }
    ledger_apis = {p for p in ledger_apis if p.startswith("/")}
    disc_apis = {a.path for a in discovered.apis}

    # Required contract APIs (explicit ledger membership). Discovery may find
    # hundreds of client strings; the harness fails only when a *ledger* API is
    # missing from discovery, or a discovered *page* is missing from the ledger.
    required_apis = set(ledger.get("required_apis") or ledger_apis)

    def static_key(u: str) -> str:
        parts = []
        for part in u.split("/"):
            if part.startswith(":"):
                parts.append(":param")
            else:
                parts.append(part)
        return "/".join(parts)

    ledger_static = {static_key(u) for u in ledger_routes}
    unaccounted_pages = sorted(u for u in disc_routes if static_key(u) not in ledger_static and ":" not in u)
    # Ledger/required APIs not present in discovery → unaccounted request
    unaccounted_apis = sorted(p for p in required_apis if p not in disc_apis)

    missing_from_discovery_routes = sorted(
        u for u in ledger_routes if static_key(u) not in {static_key(x) for x in disc_routes} and ":" not in u
    )

    ok = not unaccounted_pages and not unaccounted_apis
    return {
        "ok": ok,
        "unaccounted_pages": unaccounted_pages,
        "unaccounted_apis": unaccounted_apis,
        "missing_from_discovery_routes": missing_from_discovery_routes,
        "discovered_route_count": len(disc_routes),
        "ledger_route_count": len(ledger_routes),
        "discovered_api_count": len(disc_apis),
        "ledger_api_count": len(ledger_apis),
        "required_api_count": len(required_apis),
    }

#!/usr/bin/env python3
"""Repo-wide invariant: paid Brave traffic leaves this repository in exactly
one place — ``scripts/lib/brave_research_router.py``.

Measured 2026-08-30, four callers held their own Brave client and never
imported the budgeted one, so ~85% of real traffic bypassed the ledger and the
budget alarm reported ``monthly_pct: 17.6, "ok"`` while the provider sat at its
spend ceiling. A working alarm on an unrepresentative sensor.

This test exists so that regression cannot recur silently: a new caller that
builds its own request fails CI here rather than in next month's bill.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The only module permitted to name the provider endpoint.
CANONICAL = REPO / "scripts" / "lib" / "brave_research_router.py"

#: Credential validators legitimately call the provider to answer "is this key
#: alive?". They consume a real credit and must count it via search_budget.note,
#: but they are not research callers and do not belong behind the research
#: router. Each is listed deliberately, not matched by pattern.
CREDENTIAL_VALIDATORS = {
    REPO / "scripts" / "secret_validators.py",
    REPO / "scripts" / "credential_monitor.py",
}

#: Modules that name the provider host as a **needle** — they grep other files
#: for bypasses. They must never fetch it, which is asserted separately below
#: rather than assumed from membership here.
HOST_DETECTORS = {
    REPO / "scripts" / "research_truth_inventory.py",
}

SKIP_DIRS = {".git", "node_modules", "dist", "build", "_archive", ".venv", "archive", "reference"}

PROVIDER_HOST = "api.search.brave.com"
PROVIDER_HEADER = "X-Subscription-Token"


def _python_files() -> list[Path]:
    out: list[Path] = []
    for p in REPO.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.parts[-2:] == ("tests", p.name) and p.name.startswith("test_"):
            continue
        out.append(p)
    return out


def _string_constants(path: Path) -> set[str]:
    """String literals in executable positions — not comments, not docstrings."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    }


def test_only_the_router_names_the_provider_endpoint():
    offenders = []
    for path in _python_files():
        if path == CANONICAL or path in CREDENTIAL_VALIDATORS or path in HOST_DETECTORS:
            continue
        if any(PROVIDER_HOST in s for s in _string_constants(path)):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "these modules build their own Brave request instead of routing "
        f"through brave_research_router: {sorted(offenders)}"
    )


def test_host_detectors_compare_against_the_host_but_never_fetch_it():
    """Membership in HOST_DETECTORS is not a free pass.

    A module allowed to *name* the provider host must use it only as a needle.
    The moment one of them opens a connection to it, it is a bypass with an
    exemption, which is worse than an ordinary bypass because the test that
    would have caught it is the one letting it through.
    """
    for path in HOST_DETECTORS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if PROVIDER_HOST not in node.value:
                continue
            in_comparison = any(isinstance(q, ast.Compare) and node in ast.walk(q) for q in ast.walk(tree))
            assert in_comparison, f"{path.name} uses the provider host outside a comparison"
        # And it must not send the credential either.
        assert PROVIDER_HEADER not in path.read_text(encoding="utf-8"), f"{path.name} sends the subscription header"


def test_only_the_router_sends_the_subscription_header():
    offenders = []
    for path in _python_files():
        if path == CANONICAL or path in CREDENTIAL_VALIDATORS:
            continue
        if any(PROVIDER_HEADER in s for s in _string_constants(path)):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"these modules send the Brave credential directly: {sorted(offenders)}"


def _resolves_key(path: Path) -> bool:
    """True when the file *resolves* the Brave key, not merely mentions it.

    Distinguishes a key read — ``os.getenv("BRAVE_SEARCH_API_KEY")``,
    ``os.environ[...]``, or hand-parsing ``.env`` — from a user-facing message
    ("add BRAVE_SEARCH_API_KEY to .env") or an inventory label. A plain
    substring scan cannot tell those apart and would force real code to be
    reworded to satisfy a test.
    """
    KEY = "BRAVE_SEARCH_API_KEY"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        # os.getenv(KEY) / os.environ.get(KEY)
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in {"getenv", "get"}:
                for a in node.args:
                    if isinstance(a, ast.Constant) and a.value == KEY:
                        return True
            # line.startswith("BRAVE_SEARCH_API_KEY=") — hand-rolled .env parse
            if name == "startswith":
                for a in node.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith(KEY + "="):
                        return True
        # os.environ["BRAVE_SEARCH_API_KEY"]
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == KEY:
                return True
    return False


def test_research_callers_do_not_resolve_the_api_key_themselves():
    """A private key read is how a bypass starts.

    Secrets administration, the env-display allowlists and the credential
    validators legitimately resolve the variable; research acquisition modules
    must not.
    """
    allowed_names = {
        "secrets_admin.py",
        "secret_validators.py",
        "credential_monitor.py",
        "telegram_command_handler.py",
        "portfolio_server.py",
        "api_v2.py",
        "brave_research_router.py",
    }
    offenders = [str(p.relative_to(REPO)) for p in _python_files() if p.name not in allowed_names and _resolves_key(p)]
    assert not offenders, f"research modules resolving the Brave key directly: {sorted(offenders)}"


@pytest.mark.parametrize(
    "module",
    [
        "scripts/brave_search.py",
        "scripts/web_research.py",
        "scripts/aegis_social_sentiment.py",
        "scripts/aegis_transcript_discovery.py",
        "phase2b_analyst.py",
    ],
)
def test_known_former_bypass_callers_now_route(module):
    """The five modules that previously held their own client."""
    src = (REPO / module).read_text(encoding="utf-8")
    assert "brave_research_router" in src, f"{module} does not use the router"
    assert PROVIDER_HOST not in src, f"{module} still names the provider host"


def test_credential_validators_still_count_their_spend():
    """Validators are exempt from the router, not from the ledger.

    They consume a real credit to answer "is this key alive?", so a validator
    that stopped counting would under-report usage exactly the way the four
    bypass callers did.
    """
    for path in CREDENTIAL_VALIDATORS:
        src = path.read_text(encoding="utf-8")
        assert "search_budget" in src, f"{path.name} calls the provider without counting it in the ledger"

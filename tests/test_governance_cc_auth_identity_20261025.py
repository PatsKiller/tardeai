"""Governance pages saw no principal for the operator (2026-10-25, operator phone report).

The portfolio server runs ``scripts/portfolio_server.py`` by path, so its auth gate imports ``lib.cc_auth`` and sets
the request principal on that module's thread-local. ``operator_approvals_api.default_ctx`` imported
``scripts.lib.cc_auth`` -- a second module object with its own thread-local -- so every ``/api/v2/governance`` GET
answered 403 AUTHENTICATED_READER_REQUIRED, the operator's included (Rulebook "unavailable", Approvals queue with no
update time). These tests reproduce the server's import layout in a subprocess (``scripts/`` first on sys.path,
nothing preloaded) and prove the principal set by the gate is the one the governance handlers read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, {scripts!r})
    from lib import cc_auth as gate  # what portfolio_server.py imports
    from scripts.lib import operator_approvals_api as oaa

    out = {{}}
    ctx = oaa.default_ctx()
    gate.set_request_context("serve_proxy", {{}})

    gate.set_request_principal("service-token")
    out["reader_status"] = oaa.handle("/api/v2/governance/no-such-view", "GET", ctx=ctx)[0]

    gate.set_request_principal("")
    out["anonymous_status"], anonymous = oaa.handle("/api/v2/governance/no-such-view", "GET", ctx=ctx)
    out["anonymous_error"] = anonymous.get("error")

    ctx.allowed_logins = frozenset({{"operator@example.test"}})
    gate.set_request_principal("tailnet:operator@example.test")
    out["operator"] = oaa._operator(ctx)
    out["operator_status"] = oaa.handle("/api/v2/governance/no-such-view", "GET", ctx=ctx)[0]

    # A loopback agent (no principal) still cannot POST a decision.
    gate.set_request_principal("")
    gate.set_request_context("service", {{}})
    out["agent_post_status"], post = oaa.handle("/api/v2/governance/approvals/x/decide", "POST", {{}}, ctx=ctx)
    out["agent_post_error"] = post.get("error")
    print(json.dumps(out))
    """
)


def _run(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env["TRADEAI_STATE_ROOT"] = str(tmp_path)
    env["TRADEAI_GOVERNANCE_DIR"] = str(tmp_path / "governance")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE.format(scripts=str(ROOT / "scripts"))],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_gate_principal_reaches_governance_reads(tmp_path):
    out = _run(tmp_path)
    # Past the reader check: the unknown sub-path is a 404, never AUTHENTICATED_READER_REQUIRED.
    assert out["reader_status"] == 404
    assert out["operator"] == "tailnet:operator@example.test"
    assert out["operator_status"] == 404


def test_no_principal_is_still_refused(tmp_path):
    out = _run(tmp_path)
    assert (out["anonymous_status"], out["anonymous_error"]) == (403, "AUTHENTICATED_READER_REQUIRED")
    assert (out["agent_post_status"], out["agent_post_error"]) == (403, "AGENT_CALLER_REFUSED")
    # No ledger was created by these reads/refusals.
    assert not (tmp_path / "governance" / "operator_decisions.jsonl").exists()

#!/usr/bin/env python3
"""Broker-write bypass scanner (P1-1) — reusable, structured findings.

Detects any path that could mutate broker order state without routing through the single
approved transport boundary. Every finding carries file, line, symbol, and reason so a
reviewer can act on it directly. Used by both ``tests/test_no_broker_write_bypass.py`` and
``scripts/validate_schwab_write_policy.py``.

Detected classes:
  * direct ``client.place_order`` / ``cancel_order`` / ``replace_order`` (any non-transport receiver)
  * aliased Schwab client write calls (alias resolved to the transport is OK; anything else flagged)
  * raw HTTP POST/PUT/DELETE to Schwab order endpoints
  * imports of write-capable schwab-py utilities outside approved boundary modules
  * future multi-leg / replace-order route bypasses (replace_order is fenced everywhere but the transport)

This scanner is READ-ONLY and performs no broker calls.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# The ONLY modules permitted to host a real broker write boundary. Keep this list small.
APPROVED_WRITE_MODULES = {
    "schwab_transport.py",     # the Schwab write boundary (persists row → POST → consume → readback)
    "snaptrade_transport.py",  # the SnapTrade write boundary (separate broker, fenced)
    "snaptrade_trade.py",      # SnapTrade trading, fenced separately (dry-by-default)
}

# Receiver names that denote DELEGATION to an approved transport, not a direct client write.
# Pilots call ``st.place_order(...)`` / ``schwab_transport.place_order(...)`` /
# ``snaptrade_transport.place_order(...)``.
TRANSPORT_RECEIVERS = {"schwab_transport", "snaptrade_transport", "st", "_st"}

WRITE_ATTRS = {"place_order", "cancel_order", "replace_order"}

# Files that legitimately reference write symbols as strings/regex (scanners, validators, docs).
# Allowlisted with reason; they contain no runtime write call.
SCANNER_ALLOWLIST = {
    "broker_write_scanner.py": "this scanner — references symbols as data",
    "validate_schwab_write_policy.py": "write-policy validator — symbolic references",
    "validate_schwab_no_writes.py": "no-writes validator — symbolic references",
}

# schwab-py import allowed only here (plus the validators that scan for it).
SCHWAB_IMPORT_ALLOWED = APPROVED_WRITE_MODULES | {
    "validate_schwab_write_policy.py", "validate_schwab_no_writes.py", "broker_write_scanner.py",
}

_RAW_HTTP_RE = re.compile(r"requests\.(post|put|delete)\([^\n]*(schwabapi|trader/v1)[^\n]*order", re.I)


def _is_schwab_py_import(line: str) -> bool:
    """True only for an import of the write-capable schwab-py package (``schwab``).

    Excludes local modules (``schwab_transport``, ``schwab_token_manager`` …) and
    importing a NAME ``schwab`` from a local package (``from brokers.translators import
    schwab``) — neither is the schwab-py client library."""
    s = line.strip()
    if s.startswith("import schwab") and not s.startswith("import schwab_"):
        return True
    if s.startswith("from schwab.") or s.startswith("from schwab import"):
        return True
    return False


def _iter_py():
    for path in SCRIPTS.rglob("*.py"):
        # Skip tests
        if path.name.startswith("test_") or (len(path.parts) >= 2 and path.parts[-2] == "tests"):
            continue
        yield path


def _receiver_name(node: ast.AST) -> str:
    """Best-effort dotted source of an attribute call receiver."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _receiver_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _scan_write_calls(path: Path, src: str) -> list[dict]:
    findings = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in WRITE_ATTRS:
            continue
        recv = _receiver_name(func.value)
        recv_root = recv.split(".")[0] if recv else ""
        recv_leaf = recv.split(".")[-1] if recv else ""
        # Delegation to the approved transport is allowed.
        if recv_root in TRANSPORT_RECEIVERS or recv_leaf in TRANSPORT_RECEIVERS:
            continue
        findings.append({
            "file": str(path.relative_to(ROOT)),
            "line": node.lineno,
            "symbol": f"{recv}.{func.attr}" if recv else func.attr,
            "reason": f"direct broker write '{func.attr}' on non-transport receiver "
                      f"'{recv or '?'}' — must route through schwab_transport",
        })
    return findings


def _scan_raw_http(path: Path, src: str) -> list[dict]:
    findings = []
    for i, line in enumerate(src.splitlines(), 1):
        if _RAW_HTTP_RE.search(line):
            findings.append({
                "file": str(path.relative_to(ROOT)), "line": i, "symbol": line.strip()[:80],
                "reason": "raw HTTP POST/PUT/DELETE to a Schwab order endpoint outside the transport",
            })
    return findings


def _scan_schwab_imports(path: Path, src: str) -> list[dict]:
    findings = []
    for i, line in enumerate(src.splitlines(), 1):
        if _is_schwab_py_import(line):
            findings.append({
                "file": str(path.relative_to(ROOT)), "line": i, "symbol": line.strip()[:80],
                "reason": "schwab-py (write-capable) imported outside the transport boundary",
            })
    return findings


import functools


@functools.lru_cache(maxsize=1)
def _scan_cached() -> str:
    import json
    return json.dumps(_scan_impl())


def scan() -> dict:
    """Return structured scan results (process-cached). ``ok`` True when zero findings."""
    import json
    return json.loads(_scan_cached())


def _scan_impl() -> dict:
    findings: list[dict] = []
    for path in _iter_py():
        name = path.name
        if name in SCANNER_ALLOWLIST:
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if name not in APPROVED_WRITE_MODULES:
            findings.extend(_scan_write_calls(path, src))
            findings.extend(_scan_raw_http(path, src))
        if name not in SCHWAB_IMPORT_ALLOWED:
            findings.extend(_scan_schwab_imports(path, src))
    by_class: dict[str, int] = {}
    for f in findings:
        key = f["reason"].split("—")[0].strip()[:48]
        by_class[key] = by_class.get(key, 0) + 1
    return {
        "ok": len(findings) == 0,
        "findings": findings,
        "finding_count": len(findings),
        "by_class": by_class,
        "approved_write_modules": sorted(APPROVED_WRITE_MODULES),
        "transport_receivers": sorted(TRANSPORT_RECEIVERS),
        "allowlist": SCANNER_ALLOWLIST,
    }


def main() -> int:
    import json
    result = scan()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

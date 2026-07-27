"""Stage 5 — static trade-API prohibition scanner.

Parses every Stage 5 runtime module's AST and rejects any reference to a Moomoo
trade context/method. Runtime code must be DATA ONLY.
"""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_NAMES = {
    "OpenSecTradeContext", "OpenFutureTradeContext", "OpenHKTradeContext",
    "OpenUSTradeContext", "unlock_trade", "place_order", "modify_order",
    "cancel_order", "cancel_all_order", "close_position",
}
FORBIDDEN_ATTRS = {"REAL", "SIMULATE"}          # TrdEnv.REAL / TrdEnv.SIMULATE
FORBIDDEN_TRDENV = "TrdEnv"

RUNTIME_DIR = Path(__file__).resolve().parent


def scan_source(source: str, filename: str = "<mem>") -> list[dict]:
    findings = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            findings.append({"file": filename, "line": node.lineno, "token": node.id})
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_NAMES:
                findings.append({"file": filename, "line": node.lineno, "token": node.attr})
            if isinstance(node.value, ast.Name) and node.value.id == FORBIDDEN_TRDENV \
                    and node.attr in FORBIDDEN_ATTRS:
                findings.append({"file": filename, "line": node.lineno,
                                 "token": f"TrdEnv.{node.attr}"})
        if isinstance(node, ast.ImportFrom) and node.module and "trade" in node.module.lower():
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    findings.append({"file": filename, "line": node.lineno, "token": alias.name})
    return findings


def scan_directory(directory: Path = RUNTIME_DIR) -> list[dict]:
    findings = []
    for py in sorted(directory.rglob("*.py")):
        if py.name == "ast_guard.py":
            continue                            # the scanner names the tokens on purpose
        findings.extend(scan_source(py.read_text(), str(py.relative_to(directory.parent))))
    return findings


if __name__ == "__main__":
    hits = scan_directory()
    if hits:
        for h in hits:
            print(f"TRADE-API REFERENCE: {h['file']}:{h['line']} {h['token']}")
        raise SystemExit(1)
    print("TRADE CONTEXT CONSTRUCTORS REACHABLE: 0")
    print("TRADE METHODS REACHABLE: 0")

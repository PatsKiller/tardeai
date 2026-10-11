#!/usr/bin/env python3
"""Shrink-only ratchet: notifier sends that declare no notification-intent priority.

AGENTS.md §24.1 (4.6.0): senders emit notification intents -- the sender declares P1/P2/P3 and
``telegram_alert_router.route_intent`` decides; the text classifier no longer guesses from wording. A
``send_telegram`` / ``send_telegram_with_id`` / ``send_telegram_document`` call (any import alias) with no
``priority=`` keyword is an UNDECLARED send. ``bypass_router`` sites are gated separately, by
``BYPASS_ALLOWLIST`` in tests/test_notification_intents_20261010.py, and are not counted here.

The ratchet runs against config/notification_intent_baseline.json (file -> undeclared count):

  * a file not in the baseline that has an undeclared send fails (new senders declare an intent);
  * a file whose count grew fails;
  * a file whose count SHRANK also fails until the baseline is lowered -- so a migration is recorded
    where the next agent reads, and the baseline can only move down;
  * ``--update-baseline`` lowers or removes entries only. It refuses to add a file or raise a count.

    scripts/check_notification_intents.py              # enforce
    scripts/check_notification_intents.py --report     # per-file table
    scripts/check_notification_intents.py --update-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "config" / "notification_intent_baseline.json"
NOTIFIER_FUNCS = {"send_telegram", "send_telegram_with_id", "send_telegram_document"}
# The notifier itself and its router define/forward the API; they are not producers.
EXEMPT = {"scripts/telegram_alert.py", "scripts/telegram_alert_router.py"}


def _aliases(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """Names bound to the notifier's send functions, and names bound to the telegram_alert module."""
    fn_alias: dict[str, str] = {}
    mod_alias: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[-1] == "telegram_alert":
            for a in n.names:
                if a.name in NOTIFIER_FUNCS:
                    fn_alias[a.asname or a.name] = a.name
                elif a.name == "telegram_alert":           # from scripts import telegram_alert [as x]
                    mod_alias.add(a.asname or a.name)
        elif isinstance(n, ast.ImportFrom) and n.module == "scripts":
            for a in n.names:
                if a.name == "telegram_alert":
                    mod_alias.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[-1] == "telegram_alert":
                    mod_alias.add(a.asname or a.name)
    return fn_alias, mod_alias


def notifier_calls(tree: ast.AST) -> list[tuple[int, str, bool, bool]]:
    """(line, function, declares_priority, is_bypass) for each call into the notifier."""
    fn_alias, mod_alias = _aliases(tree)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f, name = n.func, None
        if isinstance(f, ast.Name) and f.id in fn_alias:
            name = fn_alias[f.id]
        elif isinstance(f, ast.Attribute) and f.attr in NOTIFIER_FUNCS and ast.unparse(f.value) in mod_alias:
            name = f.attr
        if not name:
            continue
        kws = {k.arg: k.value for k in n.keywords}
        pr = kws.get("priority")
        declared = pr is not None and not (isinstance(pr, ast.Constant) and pr.value is None)
        bp = kws.get("bypass_router")
        bypass = (bp is not None and not (isinstance(bp, ast.Constant) and bp.value is False)) or (
            name == "send_telegram_document" and not declared and bp is None)
        out.append((n.lineno, name, declared, bypass))
    return out


def measure(root: Path = ROOT) -> dict[str, int]:
    """file -> count of undeclared, non-bypass notifier sends (scripts/ only; tests are not producers)."""
    found: dict[str, int] = {}
    for p in sorted((root / "scripts").rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if rel in EXEMPT:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)   # a producer's own escape warnings are not ours
                tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        n = sum(1 for _, _, declared, bypass in notifier_calls(tree) if not declared and not bypass)
        if n:
            found[rel] = n
    return found


def compare(measured: dict[str, int], base: dict[str, int]) -> list[str]:
    failures = []
    for rel, n in sorted(measured.items()):
        if rel not in base:
            failures.append(f"NEW undeclared send in {rel} ({n}) -- pass priority='P1'|'P2'|'P3' (AGENTS.md §24.1)")
        elif n > base[rel]:
            failures.append(f"{rel} grew {base[rel]} -> {n}")
    for rel, allowed in sorted(base.items()):
        if measured.get(rel, 0) < allowed:
            failures.append(f"{rel} shrank {allowed} -> {measured.get(rel, 0)}: shrink-only baseline, lower it "
                            f"(scripts/check_notification_intents.py --update-baseline)")
    return failures


def _load_baseline() -> dict[str, int]:
    return {k: int(v) for k, v in json.loads(BASELINE.read_text(encoding="utf-8")).get("files", {}).items()}


def _write_baseline(files: dict[str, int]) -> None:
    BASELINE.write_text(json.dumps(
        {"_note": "Notifier sends with no notification-intent priority (AGENTS.md §24.1). Shrink-only: "
                  "scripts/check_notification_intents.py fails on a new file, growth, or an entry above "
                  "the measured count; --update-baseline only lowers.",
         "total": sum(files.values()),
         "files": dict(sorted(files.items()))}, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    measured = measure()
    if not BASELINE.is_file():
        print(f"[notification-intents] FAIL: no baseline at {BASELINE}", file=sys.stderr)
        return 1
    base = _load_baseline()
    if a.update_baseline:
        grow = {f: n for f, n in measured.items() if n > base.get(f, 0)}
        if grow:
            print(f"[notification-intents] REFUSED: the baseline only shrinks; these would add or grow: {grow}",
                  file=sys.stderr)
            return 1
        _write_baseline(measured)
        print(f"[notification-intents] baseline lowered: {sum(base.values())} -> {sum(measured.values())} "
              f"undeclared sends in {len(measured)} files")
        return 0
    print(f"[notification-intents] undeclared notifier sends: {sum(measured.values())} in {len(measured)} files "
          f"(baseline {sum(base.values())})")
    if a.report:
        for rel, n in sorted(measured.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"    {n:3d}  {rel}")
    failures = compare(measured, base)
    if failures:
        print("[notification-intents] FAIL", file=sys.stderr)
        for f in failures:
            print("   " + f, file=sys.stderr)
        return 1
    print("[notification-intents] pass (shrink-only ratchet held)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

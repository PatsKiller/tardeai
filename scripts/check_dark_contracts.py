#!/usr/bin/env python3
"""Every versioned contract must have a caller, or say why it does not.

    python3 scripts/check_dark_contracts.py            # report
    python3 scripts/check_dark_contracts.py --json
    python3 scripts/check_dark_contracts.py --fail-on-new   # CI gate

The recurring defect in this codebase is building a versioned contract and never
wiring the caller. Each artifact passes its own tests, so nothing reports a
problem. The 2026-08-27 census found **38 modules defining a versioned schema
literal with zero non-test production consumers**, and at least five separate
instances were diagnosed by hand that day — including, humiliatingly, the
remediation shipped that same day.

A module may legitimately have no consumer yet. What it may not do is be silent
about it. Declare, at module level:

    NO_CONSUMER_REASON = "shadow substrate; cutover vehicle is PR #505"

That turns invisible debt into a named, greppable list. This gate fails only on
a NEW dark contract — the existing 38 are seeded in KNOWN_DARK below so the debt
is inherited explicitly rather than grandfathered silently.

Deliberately NOT enforced: transitive darkness. A module whose only consumer is
itself dark is still dark in effect, and the census found three such chains. But
"has a consumer" is objective and cheap; "has a consumer that runs" needs the
scheduler graph and would make this gate flaky. The transitive list is reported,
never enforced.

A scheduled entrypoint has a caller without having an importer, so it may
declare instead:

    SCHEDULED_ENTRYPOINT = "cron: 40 6 * * * -- daily 06:40"

That is a declaration, not a probe. An earlier version read the live crontab,
which made the verdict depend on the machine running the gate -- it passed
locally and failed in CI on the same commit -- and counted commented-out cron
lines as scheduled.

AUTHORITY: READ_ONLY_ADVISORY. Static analysis only, repo-only inputs.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

NO_CONSUMER_REASON = (
    "this IS the guard; CI invokes it, nothing imports it. Self-exclusion from the "
    "corpus is deliberate -- see audit()."
)

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

SCHEMA_LITERAL = re.compile(r'["\']([A-Za-z_][A-Za-z0-9_]*@v\d+[\w.]*)["\']')

# The 2026-08-27 census baseline. Inherited debt, named rather than hidden.
# Removing a name from this list is progress; adding one requires a
# NO_CONSUMER_REASON in the module instead.
KNOWN_DARK: dict[str, str] = {
    "scripts/lib/alert_semantic_aggregation.py": "census 2026-08-27",
    "scripts/lib/cio_advisory_notify.py": "census 2026-08-27",
    "scripts/lib/cio_curation_run.py": "census 2026-08-27",
    "scripts/lib/cio_intelligence_outcomes.py": "census 2026-08-27",
    "scripts/lib/cio_office_cycle.py": "census 2026-08-27",
    "scripts/lib/control_plane_contract_v1.py": "census 2026-08-27",
    "scripts/lib/decision_rationale.py": "census 2026-08-27",
    "scripts/lib/embedding_policy.py": "census 2026-08-27",
    "scripts/lib/free_first_scheduler_health.py": "census 2026-08-27",
    "scripts/lib/hermes_golden_judge.py": "census 2026-08-27",
    "scripts/lib/intelligence_coverage_v2.py": "census 2026-08-27",
    "scripts/lib/memory_m2_v2.py": "census 2026-08-27; PR #505 is the cutover vehicle",
    "scripts/lib/memory_vector_index_benchmark.py": "census 2026-08-27",
    "scripts/lib/proactive_cio.py": "census 2026-08-27",
    "scripts/lib/provider_spend_snapshot.py": "census 2026-08-27",
    "scripts/lib/r17_gui_pane.py": "census 2026-08-27",
    "scripts/lib/r18_2_closeout.py": "census 2026-08-27; zero references repo-wide",
    "scripts/lib/r18_data_closeout.py": "census 2026-08-27",
    "scripts/lib/symbol_thesis_event_wake.py": "census 2026-08-27",
    "scripts/lib/tradeai_record_envelope.py": "census 2026-08-27",
    # Entrypoint half of the census: define a schema, no importer, no schedule.
    "scripts/audit_local_model_decommission.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/dump_research_prompt_fixture.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/materialize_cio_seasonality_history.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/r71_health_audit.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/refresh_advisory_maturity_evidence.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/repair_health_threshold_tuning_noise.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/repair_hermes_backlog_taxonomy.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/research_output_token_report.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/sandbox_output_ceiling_20.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
    "scripts/symbol_thesis_integration_audit.py": "census 2026-08-27 (entrypoint, unimported and unscheduled)",
}


def _is_test(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return "tests" in parts or path.name.startswith("test_")


def definers() -> dict[str, list[str]]:
    """Modules that define a versioned schema literal, and which literals."""
    out: dict[str, list[str]] = {}
    for path in SCRIPTS.rglob("*.py"):
        if _is_test(path) or "__pycache__" in str(path):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        literals = sorted(set(SCHEMA_LITERAL.findall(src)))
        if literals:
            out[str(path.relative_to(REPO))] = literals
    return out


def declared_reason(rel: str) -> str | None:
    """A module-level NO_CONSUMER_REASON, if the author declared one."""
    return declared_module_string(rel, "NO_CONSUMER_REASON")


def build_reference_index(corpus, names, literals):
    """One tokenizing pass over the corpus, not one regex scan per definer.

    The first version compiled a regex per module and re-scanned ~2,300 files for
    each -- O(n*m), over five minutes. A CI gate that slow does not get run,
    which would make this guard an instance of the very defect it exists to
    catch. Tokenize once; look up.
    """
    token = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:@v\d+[\w.]*)?")
    wanted = set(names) | set(literals)
    index = {}
    for rel, text in corpus.items():
        for tok in set(token.findall(text)):
            if tok in wanted:
                index.setdefault(tok, set()).add(rel)
    return index


def module_compiles(rel: str) -> tuple[bool, str]:
    """Does this file actually compile? `compile()`, never `ast.parse()`.

    `ast.parse()` ACCEPTS a misplaced `from __future__` import; `compile()`
    refuses it. That difference is not academic. Commit aa21559c put a
    module-level NO_CONSUMER_REASON above the `__future__` import in
    scripts/cio_event_lifecycle_census.py to satisfy THIS gate. The file was a
    SyntaxError for 10 hours -- unimportable, unrunnable -- while this gate
    read the declaration straight back out of it with `ast.parse` and reported
    green, and its numbers were quoted the whole time.

    Bytes, not str: the UTF-8 codec strips a BOM exactly as the interpreter
    does, so this asks the same question `python <file>` asks. A str read would
    raise on a BOM that does not, in fact, stop the file from running.
    """
    try:
        compile((REPO / rel).read_bytes(), rel, "exec")
    except SyntaxError as exc:
        return False, f"{exc.msg} (line {exc.lineno})"
    except (OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def declared_module_string(rel: str, name: str) -> str | None:
    """A module-level string constant, if the author declared one.

    Callers must check `module_compiles(rel)` first. A file that does not
    compile returns None here, which is indistinguishable from a file that
    simply carries no declaration -- so on its own this cannot tell "declared
    nothing" from "cannot be parsed at all".
    """
    try:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name) and target.id == name
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    return node.value.value
    return None


def audit() -> dict[str, Any]:
    defs = definers()
    corpus: dict[str, str] = {}
    for path in SCRIPTS.rglob("*.py"):
        if _is_test(path) or "__pycache__" in str(path):
            continue
        rel = str(path.relative_to(REPO))
        # Exclude self: KNOWN_DARK lists the seeded modules as path strings, and
        # the tokenizer reads those as references -- the guard would report its
        # own baseline as consumed. It did, on the first run: inherited=0.
        if rel == "scripts/check_dark_contracts.py":
            continue
        try:
            corpus[rel] = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

    # A declaration is a claim about a file that RUNS. Verify that first: this
    # gate demands a module-level NO_CONSUMER_REASON, and the obvious place to
    # put one is the top of the file -- above `from __future__`, which is a
    # SyntaxError. The gate that induces that shape must be the gate that
    # catches it, or it launders a dead file into a green check.
    uncompilable = []
    for rel in sorted(corpus):
        ok, why = module_compiles(rel)
        if not ok:
            uncompilable.append({"module": rel, "error": why})

    names = {Path(rel).stem for rel in defs}
    all_lits = {lit for lits in defs.values() for lit in lits}
    index = build_reference_index(corpus, names, all_lits)

    dark, declared, inherited, new = [], [], [], []
    for rel, literals in sorted(defs.items()):
        refs = set(index.get(Path(rel).stem, set()))
        for lit in literals:
            refs |= index.get(lit, set())
        refs.discard(rel)                      # self-reference is not a consumer
        if refs:
            continue
        # A scheduled entrypoint has a caller even with no importer -- but it
        # must SAY so. Reading the live crontab made the verdict depend on which
        # machine ran the gate: locally the Phase 2 jobs were skipped, in CI
        # (no crontab) the same commits failed. It also matched COMMENTED-OUT
        # lines, so a switched-off job counted as scheduled. Declare it instead.
        if declared_module_string(rel, "SCHEDULED_ENTRYPOINT"):
            continue
        reason = declared_reason(rel)
        row = {"module": rel, "schemas": literals, "consumers": 0, "reason": reason}
        dark.append(row)
        if reason:
            declared.append(row)
        elif rel in KNOWN_DARK:
            row["reason"] = f"INHERITED: {KNOWN_DARK[rel]}"
            inherited.append(row)
        else:
            new.append(row)

    return {
        "schema": "DarkContractAudit@v1",
        "authority": "READ_ONLY_ADVISORY",
        "uncompilable": uncompilable,
        "definers": len(defs),
        "zero_consumer": len(dark),
        "declared": len(declared),
        "inherited": len(inherited),
        "new": new,
        "inherited_list": [r["module"] for r in inherited],
        "declared_list": [r["module"] for r in declared],
        # A seeded entry that now HAS a consumer is progress worth naming.
        "resolved_since_baseline": sorted(
            set(KNOWN_DARK) - {r["module"] for r in dark}
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail on a NEW dark contract")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-new", action="store_true",
                    help="exit 1 when a module defines a versioned schema with no consumer "
                         "and no NO_CONSUMER_REASON")
    args = ap.parse_args()
    result = audit()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"uncompilable modules      : {len(result['uncompilable'])}")
        for row in result["uncompilable"]:
            print(f"    ✗ {row['module']}  {row['error']}")
        print(f"versioned-schema definers : {result['definers']}")
        print(f"zero-consumer             : {result['zero_consumer']}")
        print(f"  inherited (seeded)      : {result['inherited']}")
        print(f"  declared NO_CONSUMER_REASON: {result['declared']}")
        print(f"  NEW (unexplained)       : {len(result['new'])}")
        for row in result["new"]:
            print(f"    ✗ {row['module']}  defines {', '.join(row['schemas'])}")
        if result["resolved_since_baseline"]:
            print(f"\n  resolved since baseline ({len(result['resolved_since_baseline'])}):")
            for m in result["resolved_since_baseline"]:
                print(f"    ✓ {m}")

    # Order matters: report the unrunnable file BEFORE the consumer verdict.
    # A module that cannot compile has no consumers and no declaration in any
    # meaningful sense, and reporting it as "declared, 0 new" is the specific
    # false green this gate shipped for 10 hours.
    if result["uncompilable"]:
        print("\nFAIL: a module under scripts/ does not compile. Its declaration, its\n"
              "consumers and its schemas are all unverifiable until it does.\n"
              "compile() -- not ast.parse() -- is the check; ast.parse accepts a\n"
              "module-level statement placed above `from __future__`, which is\n"
              "exactly how a NO_CONSUMER_REASON added to satisfy THIS gate broke\n"
              "the file it was added to.", file=sys.stderr)
        for row in result["uncompilable"]:
            print(f"  {row['module']}: {row['error']}", file=sys.stderr)
        return 1

    if args.fail_on_new and result["new"]:
        print("\nFAIL: a new versioned contract has no caller and no NO_CONSUMER_REASON.\n"
              "Wire a consumer, or declare at module level:\n"
              '    NO_CONSUMER_REASON = "why this has no caller yet"', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

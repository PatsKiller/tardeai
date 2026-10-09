#!/usr/bin/env python3
"""Every protected asset the repo declares has a backup and a restore, or a named gap.

    python3 scripts/check_backup_coverage.py                 # report
    python3 scripts/check_backup_coverage.py --json
    python3 scripts/check_backup_coverage.py --fail-on-new   # CI gate
    python3 scripts/check_backup_coverage.py --state-root <persistent-state dir>   # also check host layout

Operator question 2026-10-09: "should each push check whether it needs to edit the
recovery scripts, to keep backup and recovery in sync?" The answer adopted: a gate that
FAILS when a change adds something backup/restore does not cover, and names the gap. It
never edits a recovery script. The author updates config/backup_coverage_manifest.json in
the same PR -- either by naming the mechanism that already covers the new asset, or by
recording it as a gap (mechanism NONE) and adding it to the baseline with a reason.

Declared assets (repo-only inputs, so the verdict does not depend on the machine):

  store:<domain>            config/data_source_authority.json domains[].store
  persistent_tree:<rel>     served_from.linked_dirs + scripts/lib/persistent_state_root.py
                            PERSISTENT_TREES + scripts/lib/persistent_overlay.py OVERLAY_RELS
  unit:<file>               config/systemd/user/* (unit files and .d drop-in dirs)
  secret:<NAME>             config/secret_registry.yaml secrets keys (names only)
  pg_table:<schema>.<tbl>   CREATE TABLE in migrations/, sql/migrations/, sql/*.sql,
                            linux_port_v2/linux/migrations/
  fixed ids                 FIXED_ASSETS below (databases, n8n, ledger, crontab ...)
  ps:<rel>                  only with --state-root: top-level dirs of persistent-state and
                            of its data/ dir (a host check; CI never passes it)

Every declared asset must resolve to an asset class in the manifest. Kinds other than
pg_table must be listed by exact id (a wildcard cannot silently admit a new store or
unit). A table may be admitted by a schema pattern (pg_table:public.*), because pg_dump
covers a schema, not a table list.

Ratchet: an asset whose class has coverage NONE or PARTIAL is a gap. Today's gaps are
listed in config/backup_coverage_baseline.json. A gap not in the baseline fails; a
baseline entry that is no longer a gap is reported so the baseline can shrink.

Exit codes: 0 pass (or report mode), 1 a new unmapped asset or new gap, 2 could not run.

AUTHORITY: READ_ONLY_ADVISORY. Static analysis of repo files (plus an optional read-only
directory listing). It never runs a backup, a restore or a delete.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any

NO_CONSUMER_REASON = (
    "this IS the guard; CI runs it through tests/test_backup_coverage_gate_20261009.py "
    "(GATES backup_coverage_gate_20261009) and nothing imports it."
)

REPO = Path(__file__).resolve().parents[1]
MANIFEST_REL = "config/backup_coverage_manifest.json"
BASELINE_REL = "config/backup_coverage_baseline.json"
MANIFEST_SCHEMA = "BackupCoverageManifest@v1"
BASELINE_SCHEMA = "BackupCoverageBaseline@v1"
REPORT_SCHEMA = "BackupCoverageReport@v1"

COVERAGE_VALUES = ("FULL", "PARTIAL", "NONE")
GAP_COVERAGE = ("PARTIAL", "NONE")
GLOB_KINDS = ("pg_table",)

# Assets that no repo registry declares but that a restore needs. The manifest must list each.
FIXED_ASSETS = (
    "pg_database:trade_ai",
    "pg_database:postgres",
    "pg_cluster:roles",
    "n8n:lab_db",
    "n8n:workflows",
    "n8n:encryption_key",
    "coordination_ledger:n8n_coordination_ledger.sqlite",
    "crontab:user",
    "host_systemd:installed_units",
    "host_systemd:installed_dropins",
    "code:repo",
    "docs:repo_docs",
    "docs:generated_docs",
    "local_secret:broker_credentials_env",
    "local_secret:backup_gpg_passphrase",
    "claude_memory:file_memory",
    "apps:openclaw_and_dof",
)

MIGRATION_GLOBS = (
    "migrations/**/*.sql",
    "sql/migrations/**/*.sql",
    "sql/*.sql",
    "linux_port_v2/linux/migrations/**/*.sql",
)
CREATE_TABLE = re.compile(
    r"\bcreate\s+(?:unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?([A-Za-z0-9_\".]+)",
    re.IGNORECASE,
)
SQL_LINE_COMMENT = re.compile(r"--[^\n]*")
PG_BACKUP_SCRIPT = "linux_launchers/run_pg_backup.sh"
PG_EXCLUDE = re.compile(r"--exclude-table-data=['\"]?([A-Za-z0-9_.*]+)")


# ---------------------------------------------------------------- declared assets

def _add(out: dict[str, str], asset: str, source: str) -> None:
    out.setdefault(asset, source)


def _tuple_literal(path: Path, name: str) -> list[str]:
    """Read a module-level tuple of strings by AST (never imports the module)."""
    if not path.is_file():
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if name in targets and isinstance(value, (ast.Tuple, ast.List)):
            return [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _load_yaml_secret_names(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return sorted((data.get("secrets") or {}).keys())
    except ImportError:  # pragma: no cover - CI has PyYAML; fallback keeps the gate honest
        names, inside = [], False
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.match(r"^secrets:\s*$", line):
                inside = True
                continue
            if inside and re.match(r"^\S", line):
                inside = False
            m = re.match(r"^  ([A-Za-z0-9_]+):\s*$", line)
            if inside and m:
                names.append(m.group(1))
        return sorted(names)


def _normalise_table(raw: str) -> str:
    name = raw.replace('"', "").strip().lower().rstrip(";(")
    return name if "." in name else f"public.{name}"


def collect_declared(repo: Path) -> dict[str, str]:
    """Return {asset_id: source citation} for every repo-declared asset."""
    out: dict[str, str] = {}
    auth = repo / "config/data_source_authority.json"
    if auth.is_file():
        data = json.loads(auth.read_text(encoding="utf-8"))
        for d in data.get("domains", []):
            _add(out, f"store:{d['domain']}", "config/data_source_authority.json")
        for rel in (data.get("served_from") or {}).get("linked_dirs", []):
            _add(out, f"persistent_tree:data/{rel}", "config/data_source_authority.json#served_from.linked_dirs")
    for rel in _tuple_literal(repo / "scripts/lib/persistent_state_root.py", "PERSISTENT_TREES"):
        _add(out, f"persistent_tree:{rel}", "scripts/lib/persistent_state_root.py#PERSISTENT_TREES")
    for rel in _tuple_literal(repo / "scripts/lib/persistent_overlay.py", "OVERLAY_RELS"):
        _add(out, f"persistent_tree:{rel}", "scripts/lib/persistent_overlay.py#OVERLAY_RELS")
    units = repo / "config/systemd/user"
    if units.is_dir():
        for p in sorted(units.iterdir()):
            if p.name.startswith("."):
                continue
            _add(out, f"unit:{p.name}", "config/systemd/user")
    for name in _load_yaml_secret_names(repo / "config/secret_registry.yaml"):
        _add(out, f"secret:{name}", "config/secret_registry.yaml")
    seen: set[Path] = set()
    for pattern in MIGRATION_GLOBS:
        for path in sorted(repo.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            text = SQL_LINE_COMMENT.sub("", path.read_text(encoding="utf-8", errors="replace"))
            for m in CREATE_TABLE.finditer(text):
                _add(out, f"pg_table:{_normalise_table(m.group(1))}", path.relative_to(repo).as_posix())
    for asset in FIXED_ASSETS:
        _add(out, asset, "scripts/check_backup_coverage.py#FIXED_ASSETS")
    return out


def collect_host_state(state_root: Path) -> dict[str, str]:
    """Top-level entries of persistent-state and of its data/ dir (names only; read-only)."""
    out: dict[str, str] = {}
    if not state_root.is_dir():
        raise FileNotFoundError(f"state root not found: {state_root}")
    for p in sorted(state_root.iterdir()):
        _add(out, f"ps:{p.name}", f"--state-root listing ({state_root.name})")
    data = state_root / "data"
    if data.is_dir():
        for p in sorted(data.iterdir()):
            _add(out, f"ps:data/{p.name}", f"--state-root listing ({state_root.name}/data)")
    return out


# ---------------------------------------------------------------- manifest

def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest schema must be {MANIFEST_SCHEMA}")
    mechanisms = manifest.get("mechanisms") or {}
    seen_ids: set[str] = set()
    seen_covers: dict[str, str] = {}
    for cls in manifest.get("asset_classes") or []:
        cid = cls.get("id") or "<missing id>"
        if cid in seen_ids:
            errors.append(f"duplicate asset class id {cid}")
        seen_ids.add(cid)
        coverage = cls.get("coverage")
        if coverage not in COVERAGE_VALUES:
            errors.append(f"{cid}: coverage must be one of {COVERAGE_VALUES}")
        mechs = cls.get("mechanism")
        mech_list = mechs if isinstance(mechs, list) else [mechs]
        if not mech_list or any(not m for m in mech_list):
            errors.append(f"{cid}: mechanism is required (use \"NONE\" when nothing backs it up)")
        for m in mech_list:
            if m and m != "NONE" and m not in mechanisms:
                errors.append(f"{cid}: mechanism {m!r} is not defined in mechanisms")
        if "NONE" in mech_list and coverage != "NONE":
            errors.append(f"{cid}: mechanism NONE requires coverage NONE")
        if coverage == "NONE" and mech_list != ["NONE"]:
            errors.append(f"{cid}: coverage NONE requires mechanism NONE")
        if coverage in GAP_COVERAGE and not str(cls.get("gap") or "").strip():
            errors.append(f"{cid}: coverage {coverage} requires a gap note")
        if coverage != "NONE" and not str(cls.get("restore") or "").strip():
            errors.append(f"{cid}: a covered class needs a restore procedure")
        for pat in cls.get("covers") or []:
            if pat in seen_covers:
                errors.append(f"{pat} is listed in both {seen_covers[pat]} and {cid}")
            seen_covers[pat] = cid
            kind = pat.split(":", 1)[0]
            if any(ch in pat for ch in "*?[") and kind not in GLOB_KINDS:
                errors.append(f"{cid}: wildcard {pat!r} not allowed for kind {kind!r} (list exact ids)")
    return errors


def check_pg_exclusions(repo: Path, manifest: dict[str, Any]) -> list[str]:
    """The manifest's claim about pg_dump must match the flags the backup script really passes."""
    script = repo / PG_BACKUP_SCRIPT
    if not script.is_file():
        return []
    live = sorted(set(PG_EXCLUDE.findall(script.read_text(encoding="utf-8"))))
    mech = (manifest.get("mechanisms") or {}).get("pg_dump_local") or {}
    declared = sorted(mech.get("pg_exclude_table_data") or [])
    errors = []
    if live != declared:
        errors.append(
            f"{PG_BACKUP_SCRIPT} excludes table data for {live} but mechanisms.pg_dump_local."
            f"pg_exclude_table_data says {declared}: update the manifest and move the affected "
            f"pg_table patterns between classes"
        )
    partial = {p for c in manifest.get("asset_classes") or [] if c.get("coverage") in GAP_COVERAGE
               for p in c.get("covers") or [] if str(p).startswith("pg_table:")}
    for pat in live:
        if f"pg_table:{pat}" not in partial:
            errors.append(f"pg_table:{pat} has its data excluded by {PG_BACKUP_SCRIPT} but is not in a PARTIAL/NONE class")
    return errors


def resolve(asset: str, classes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for cls in classes:
        if asset in (cls.get("covers") or []):
            return cls
    kind = asset.split(":", 1)[0]
    if kind in GLOB_KINDS:
        for cls in classes:
            for pat in cls.get("covers") or []:
                if any(ch in pat for ch in "*?[") and fnmatch.fnmatchcase(asset, pat):
                    return cls
    return None


def suggest(asset: str, classes: list[dict[str, Any]]) -> str:
    kind = asset.split(":", 1)[0]
    same_kind = [c["id"] for c in classes if any(str(p).startswith(kind + ":") for p in c.get("covers") or [])]
    if same_kind:
        return (
            f'add "{asset}" to the "covers" list of the asset class that backs it up '
            f"(classes holding {kind} assets: {', '.join(same_kind)}); if nothing backs it up, "
            f'add it to a class with "mechanism": "NONE" and a gap note, and add it to {BASELINE_REL}'
        )
    return (
        f'add an asset class covering "{asset}" with its mechanism and restore procedure, '
        f'or "mechanism": "NONE" plus a gap note and a {BASELINE_REL} entry'
    )


def audit(repo: Path, state_root: Path | None = None,
          manifest_path: Path | None = None, baseline_path: Path | None = None) -> dict[str, Any]:
    manifest = load_json(manifest_path or repo / MANIFEST_REL)
    baseline = load_json(baseline_path or repo / BASELINE_REL)
    errors = validate_manifest(manifest) + check_pg_exclusions(repo, manifest)
    if baseline.get("schema") != BASELINE_SCHEMA:
        errors.append(f"baseline schema must be {BASELINE_SCHEMA}")
    classes = manifest.get("asset_classes") or []
    declared = collect_declared(repo)
    if state_root is not None:
        declared.update(collect_host_state(state_root))
    baseline_gaps: dict[str, Any] = baseline.get("gaps") or {}

    unmapped, new_gaps, known_gaps, covered = [], [], [], 0
    for asset in sorted(declared):
        cls = resolve(asset, classes)
        if cls is None:
            unmapped.append({"asset": asset, "source": declared[asset], "fix": suggest(asset, classes)})
            continue
        if cls.get("coverage") in GAP_COVERAGE:
            row = {"asset": asset, "class": cls["id"], "coverage": cls["coverage"],
                   "gap": cls.get("gap"), "source": declared[asset]}
            if asset in baseline_gaps:
                known_gaps.append(row)
            else:
                row["fix"] = (
                    f'new gap: back "{asset}" up (move it to a covered class) or accept it by adding '
                    f'"{asset}": "{cls["coverage"]}: <reason>" to {BASELINE_REL} gaps'
                )
                new_gaps.append(row)
        else:
            covered += 1
    gap_assets = {r["asset"] for r in known_gaps}
    shrinkable = sorted(a for a in baseline_gaps
                        if a not in gap_assets and (state_root is not None or not a.startswith("ps:")))
    return {
        "schema": REPORT_SCHEMA,
        "declared": len(declared),
        "covered": covered,
        "manifest_errors": errors,
        "unmapped": unmapped,
        "new_gaps": new_gaps,
        "known_gaps": known_gaps,
        "baseline_shrinkable": shrinkable,
        "host_checked": state_root is not None,
        "ok": not errors and not unmapped and not new_gaps,
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        f"backup coverage: {report['declared']} declared assets, {report['covered']} covered, "
        f"{len(report['known_gaps'])} known gaps (baseline), {len(report['new_gaps'])} new gaps, "
        f"{len(report['unmapped'])} not in manifest"
        + (" [host persistent-state checked]" if report["host_checked"] else ""),
    ]
    for e in report["manifest_errors"]:
        lines.append(f"  [MANIFEST] {e}")
    for r in report["unmapped"]:
        lines.append(f"  [NOT IN MANIFEST] {r['asset']}  (declared by {r['source']})")
        lines.append(f"      -> {r['fix']}")
    for r in report["new_gaps"]:
        lines.append(f"  [NEW GAP] {r['asset']}  class={r['class']} coverage={r['coverage']}: {r['gap']}")
        lines.append(f"      -> {r['fix']}")
    by_class: dict[str, int] = {}
    for r in report["known_gaps"]:
        by_class[r["class"]] = by_class.get(r["class"], 0) + 1
    for cid, n in sorted(by_class.items()):
        lines.append(f"  [known gap] {cid}: {n} asset(s)")
    for a in report["baseline_shrinkable"]:
        lines.append(f"  [baseline can shrink] {a} is no longer a gap (or no longer declared); remove it from {BASELINE_REL}")
    lines.append("PASS" if report["ok"] else "FAIL")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--fail-on-new", action="store_true", help="exit 1 on an unmapped asset or a new gap")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--state-root", type=Path, default=None,
                    help="also check top-level persistent-state dirs (read-only listing)")
    args = ap.parse_args(argv)
    try:
        report = audit(args.repo, state_root=args.state_root)
    except (OSError, ValueError, KeyError) as exc:
        print(f"check_backup_coverage: could not run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1) if args.json else render(report))
    if args.fail_on_new and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

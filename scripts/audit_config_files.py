#!/usr/bin/env python3
"""
audit_config_files.py — Scan project for YAML/JSON files and classify them.

Outputs:
  data/audits/config_file_audit.json
  docs/project/CONFIG_FILE_DB_MIGRATION_AUDIT.md
"""
import hashlib, json, os, sys, time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))

EXCLUDE_DIRS = {
    ".venv", "node_modules", ".git", "logs", "backups", "archive",
    "dist", "build", "__pycache__", "file_backups", ".next",
}

EXCLUDE_PATH_CONTAINS = [
    "command-center-v2-backup", "command-center-v2_backup",
    "package-lock.json", ".claude/",
]

# Classification rules by path patterns
CATEGORY_RULES = [
    # Strategies
    (lambda p: "config/strategies/" in p and p.endswith(".yaml"), "strategy_config", "migrate_to_domain_table", "Strategy YAML — already loaded dynamically; DB domain table preferred"),
    # Screeners
    (lambda p: "assets/screeners" in p, "screener_config", "migrate_to_domain_table", "Screener config — domain table preferred"),
    # Agent config
    (lambda p: "config/agents" in p or "agents/" in p, "agent_config", "migrate_to_generic_config_documents", "Agent config — generic config_documents table"),
    # Asset/portfolio config
    (lambda p: "assets/" in p and ("accounts" in p or "weights" in p or "intent" in p), "portfolio_config", "migrate_to_generic_config_documents", "Portfolio config YAML — DB-backed with file fallback"),
    # Indicator/thesis config
    (lambda p: "config/" in p and ("indicator" in p or "thesis" in p or "classification" in p or "beta" in p or "runtime" in p or "discovery" in p), "runtime_config", "migrate_to_generic_config_documents", "Runtime config — generic config_documents"),
    # Holdings — CRITICAL
    (lambda p: "holdings.json" in p and "state/" in p, "authoritative_state", "keep_as_file", "CRITICAL: portfolio authority file. DB mirror only."),
    # Personal situation
    (lambda p: "personal_situation.json" in p, "authoritative_state", "keep_as_file", "Personal data — DB table already exists, audit/compare only"),
    # Other state files
    (lambda p: "data/portfolios/state/" in p and not any(x in p for x in ["cache", "freshness", "snapshot"]), "runtime_state", "keep_as_file_and_cache", "State file — may have DB equivalent, compare only"),
    # Enrichment/memory caches
    (lambda p: "ticker_enrichment_cache" in p or "ticker_memory" in p, "cache", "keep_as_file_and_cache", "Large cache — DB table exists, checksum compare only"),
    # Catalyst/scored caches
    (lambda p: "catalyst_cache" in p or "scored_tickers" in p or "scalp_live" in p or "proposal_fit" in p or "state.json" == Path(p).name, "cache", "keep_as_file", "Disposable daily cache — do not migrate"),
    # Snapshots
    (lambda p: "snapshots/" in p, "cache", "keep_as_file", "Daily rotating snapshot — disposable"),
    # Reports
    (lambda p: "reports/" in p, "report_output", "keep_as_file", "Generated report artifact"),
    # Charts
    (lambda p: "charts/" in p, "report_output", "keep_as_file", "Generated chart artifact"),
    # Ingestion logs
    (lambda p: "data/logs/" in p or "ingestion_summary" in p, "cache", "keep_as_file", "Ingestion log — disposable"),
    # Frontend package
    (lambda p: "package.json" in p or "tsconfig" in p, "frontend_package_config", "keep_as_file", "Frontend toolchain config — never migrate"),
    # Live run state
    (lambda p: "live_run_state" in p, "runtime_state", "keep_as_file_and_cache", "Pipeline run state — compare to pipeline_runs table"),
    # Pipeline YAML
    (lambda p: "pipeline" in p and p.endswith((".yaml", ".yml")), "pipeline_config", "migrate_to_domain_table", "Pipeline config — domain table preferred"),
    # YouTube cookies
    (lambda p: "cookie" in p.lower(), "credentials_or_env_like", "never_migrate_secret", "Contains credentials — never migrate to DB"),
]


def classify(path_str):
    """Classify a file by path pattern."""
    for test, cat, rec, reason in CATEGORY_RULES:
        if test(path_str):
            return cat, rec, reason
    return "unknown", "keep_as_file", "Unclassified — review manually"


def sha256(path):
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "error"


def detect_shape(path):
    """Detect top-level JSON/YAML shape."""
    try:
        text = Path(path).read_text(errors="replace")[:10000]
        if path.endswith((".yaml", ".yml")):
            import yaml
            obj = yaml.safe_load(text)
        else:
            obj = json.loads(text)
        if isinstance(obj, dict):
            return "object"
        elif isinstance(obj, list):
            return "array"
        else:
            return "scalar"
    except Exception:
        return "invalid_or_binary"


def scan():
    """Scan project for YAML/JSON files."""
    results = []
    for root, dirs, files in os.walk("."):
        # Prune excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if not f.endswith((".yaml", ".yml", ".json")):
                continue
            rel = os.path.join(root, f)
            # Skip excluded path patterns
            if any(x in rel for x in EXCLUDE_PATH_CONTAINS):
                continue
            stat = os.stat(rel)
            category, recommendation, reason = classify(rel)
            results.append({
                "path": rel,
                "extension": Path(f).suffix,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "checksum": sha256(rel),
                "shape": detect_shape(rel),
                "category": category,
                "migration_recommendation": recommendation,
                "reason": reason,
            })
    return sorted(results, key=lambda x: (x["category"], x["path"]))


def generate_markdown(results):
    """Generate audit markdown report."""
    lines = [
        "# Config File DB Migration Audit",
        f"\nGenerated: {datetime.now().isoformat()}",
        f"Total files scanned: {len(results)}",
        "",
    ]
    # Summary by category
    cats = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r)
    lines.append("## Summary by Category\n")
    lines.append("| Category | Count | Recommendation |")
    lines.append("|----------|-------|----------------|")
    for cat, items in sorted(cats.items()):
        recs = set(i["migration_recommendation"] for i in items)
        lines.append(f"| {cat} | {len(items)} | {', '.join(recs)} |")

    # Summary by recommendation
    recs = {}
    for r in results:
        recs.setdefault(r["migration_recommendation"], []).append(r)
    lines.append("\n## Summary by Recommendation\n")
    lines.append("| Recommendation | Count |")
    lines.append("|----------------|-------|")
    for rec, items in sorted(recs.items()):
        lines.append(f"| {rec} | {len(items)} |")

    # Detail: files to migrate
    migrate = [r for r in results if "migrate" in r["migration_recommendation"]]
    if migrate:
        lines.append("\n## Files Recommended for DB Migration\n")
        lines.append("| Path | Category | Size | Shape |")
        lines.append("|------|----------|------|-------|")
        for r in migrate:
            lines.append(f"| `{r['path']}` | {r['category']} | {r['size_bytes']} | {r['shape']} |")

    # Detail: authoritative state
    auth = [r for r in results if r["category"] == "authoritative_state"]
    if auth:
        lines.append("\n## Authoritative State Files (DO NOT migrate blindly)\n")
        lines.append("| Path | Size | Recommendation | Reason |")
        lines.append("|------|------|----------------|--------|")
        for r in auth:
            lines.append(f"| `{r['path']}` | {r['size_bytes']} | {r['migration_recommendation']} | {r['reason']} |")

    # Detail: keep as file
    keep = [r for r in results if r["migration_recommendation"] == "keep_as_file"]
    lines.append(f"\n## Files Kept as File ({len(keep)} files)\n")
    lines.append("Disposable caches, generated artifacts, frontend config. No action needed.")

    return "\n".join(lines)


def main():
    print("Scanning project for YAML/JSON files...")
    results = scan()
    print(f"Found {len(results)} files")

    # Write JSON audit
    audit_path = PROJECT_ROOT / "data" / "audits" / "config_file_audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Written: {audit_path}")

    # Write markdown report
    md_path = PROJECT_ROOT / "docs" / "project" / "CONFIG_FILE_DB_MIGRATION_AUDIT.md"
    md_path.write_text(generate_markdown(results))
    print(f"Written: {md_path}")

    # Print summary
    cats = {}
    for r in results:
        cats.setdefault(r["migration_recommendation"], 0)
        cats[r["migration_recommendation"]] += 1
    print("\nSummary:")
    for k, v in sorted(cats.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

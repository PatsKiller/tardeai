#!/usr/bin/env python3
"""Refresh read-only live evidence consumed by MaturityScorecard@v1.

This collector performs no provider calls, no model inference, and no service or
financial mutation. It writes bounded latest snapshots under data/cio.

Lane ``advisory-maturity-evidence`` (n8n dispatcher row, stage shadow; operator "yes rebuild 1417",
2026-10-21). Run from the release root, as a path (the n8n argv) or as a module:

    python scripts/refresh_advisory_maturity_evidence.py --dry-run   # collect and report, write nothing
    python -m scripts.refresh_advisory_maturity_evidence             # rewrite the four snapshots

A real run atomically rewrites data/cio/{rag_freshness,pin_integrity,gpu_policy,ops_tree_pin_audit}_latest.json
and writes the LaneRunReceipt ``<state_root>/data/runtime/advisory-maturity-evidence_last.json``.
``--dry-run`` runs the same read-only collectors (SELECT through a READ ONLY session, read-only VCS
queries, ``ollama list/ps``, ``crontab -l``, ``systemctl --user show``) and prints one DRY-RUN line; it
writes no snapshot and no receipt. The DB credentials come from the environment, or from the release
``.env`` restricted to ``_ENV_KEYS``. Exit codes: 0 = snapshots written; 1 = a write failed; 2 = usage.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # a plain `python scripts/refresh_advisory_maturity_evidence.py` (the n8n argv)
    sys.path.insert(0, str(ROOT))

from scripts.audit_no_local_generative_routing import audit as routing_audit  # noqa: E402
from scripts.lib.current_pin_integrity import collect_pin_report, collect_process_freshness  # noqa: E402
from scripts.ops_tree_pin_audit import CURRENT_HOME, build_report, load_crontab  # noqa: E402

OUT_DIR = Path("data/cio")
EMBEDDING_MODEL = "nomic-embed-text"
LANE_ID = "advisory-maturity-evidence"
#: The only names read from the release .env (refactor contract rule 6: never the whole file).
_ENV_KEYS = frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"})
SNAPSHOTS = (
    "rag_freshness_latest.json",
    "pin_integrity_latest.json",
    "gpu_policy_latest.json",
    "ops_tree_pin_audit_latest.json",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(row, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _run(argv: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)[:240]
    return proc.returncode, proc.stdout or proc.stderr or ""


def parse_ollama_list(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines()[1:]:
        columns = line.split()
        if not columns:
            continue
        name = columns[0]
        lowered = name.lower()
        kind = "EMBEDDING" if "embed" in lowered else "GENERATIVE"
        rows.append({"name": name, "kind": kind, "digest": columns[1] if len(columns) > 1 else ""})
    return rows


def collect_gpu_policy(*, now: datetime | None = None) -> dict[str, Any]:
    stamp = (now or _now()).replace(microsecond=0).isoformat()
    source = routing_audit()
    list_rc, list_text = _run(["ollama", "list"])
    ps_rc, ps_text = _run(["ollama", "ps"])
    models = parse_ollama_list(list_text) if list_rc == 0 else []
    generative = [r["name"] for r in models if r["kind"] == "GENERATIVE"]
    embeddings = [r["name"] for r in models if r["kind"] == "EMBEDDING"]
    acceptance_path = ROOT / "data/runtime/gpu/embedding_acceptance_latest.json"
    try:
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        acceptance = {}
    embedding_accepted = bool(
        acceptance.get("accepted") is True
        and acceptance.get("model") == EMBEDDING_MODEL
        and int(acceptance.get("dimension") or 0) == 768
        and acceptance.get("reproducibility_pass") is True
        and acceptance.get("gpu_utilization_proven") is True
        and acceptance.get("generative_resident") is False
    )
    exact_embedding_inventory = all(name.split(":", 1)[0] == EMBEDDING_MODEL for name in embeddings)
    if not models and list_rc == 0:
        mode = "DISABLED"
    elif embedding_accepted and not generative and embeddings and exact_embedding_inventory:
        mode = "EMBEDDINGS_ONLY"
    else:
        mode = "NONCOMPLIANT"
    compliant = bool(
        source.get("violation_count") == 0
        and not generative
        and mode in {"EMBEDDINGS_ONLY", "DISABLED"}
        and list_rc == 0
        and ps_rc == 0
    )
    return {
        "schema": "GpuPolicyEvidence@v1", "as_of": stamp,
        "authority": "READ_ONLY_ADVISORY", "financial_action": False,
        "gpu_mode": mode, "compliance_score": 1.0 if compliant else 0.0,
        "source_violation_count": int(source.get("violation_count") or 0),
        "installed_generative_count": len(generative),
        "installed_embedding_count": len(embeddings),
        "installed_generative_models": generative,
        "installed_embedding_models": embeddings,
        "embedding_acceptance": "PASS" if embedding_accepted else "NOT_PROVEN",
        "ollama_list_rc": list_rc, "ollama_ps_rc": ps_rc,
        "active_model_names": [r["name"] for r in parse_ollama_list(ps_text)] if ps_rc == 0 else [],
    }


def _env_values(root: Path) -> dict[str, str]:
    """The DB_* names only: the environment first, then the release .env for a missing name."""
    values = {k: os.environ[k] for k in _ENV_KEYS if k in os.environ}
    path = root / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in _ENV_KEYS:
                values.setdefault(key, value.strip().strip("'\""))
    return values


def collect_rag_freshness(*, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    stamp_dt = now or _now()
    row: dict[str, Any] = {
        "schema": "RagFreshnessEvidence@v1", "as_of": stamp_dt.replace(microsecond=0).isoformat(),
        "authority": "READ_ONLY_ADVISORY", "financial_action": False,
        "freshness_score": 0.0, "total_embeddings": 0, "fresh_embeddings_7d": 0,
    }
    try:
        import psycopg2
        env = _env_values(root)
        conn = psycopg2.connect(
            host=env.get("DB_HOST", "localhost"), port=env.get("DB_PORT", "5432"),
            dbname=env.get("DB_NAME", "trade_ai"), user=env.get("DB_USER", "trade_ai"),
            password=env.get("DB_PASSWORD"), connect_timeout=5,
        )
        conn.set_session(readonly=True, autocommit=True)  # SELECT only; the server refuses any write
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), MAX(created_at),
                       COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')
                FROM content_embeddings
            """)
            total, newest, fresh = cur.fetchone()
        conn.close()
        age_s = (stamp_dt - newest.astimezone(timezone.utc)).total_seconds() if newest else None
        row.update({
            "total_embeddings": int(total or 0), "fresh_embeddings_7d": int(fresh or 0),
            "latest_embedding_at": newest.isoformat() if newest else None,
            "latest_embedding_age_seconds": age_s,
            "freshness_score": 1.0 if total and age_s is not None and age_s <= 7 * 86400 else 0.0,
            "query_ok": True,
        })
    except Exception as exc:  # noqa: BLE001
        row.update({"query_ok": False, "error_class": type(exc).__name__})
    return row


def collect_pin(*, now: datetime | None = None) -> dict[str, Any]:
    stamp = now or _now()
    pin = collect_pin_report(now=stamp)
    process = collect_process_freshness(now=stamp)
    pin_match = bool(pin.get("ok") and process.get("loaded_pin_sha") == process.get("current_pin_sha"))
    process_fresh = bool(process.get("ok"))
    return {
        "schema": "PinIntegrityEvidence@v1", "as_of": stamp.replace(microsecond=0).isoformat(),
        "authority": "READ_ONLY_ADVISORY", "financial_action": False,
        "integrity_score": 1.0 if pin_match and process_fresh else 0.0,
        "pin_match": pin_match, "process_fresh": process_fresh,
        "source_pin": pin.get("source_commit"), "loaded_pin": process.get("loaded_pin_sha"),
        "current_pin": process.get("current_pin_sha"), "process_started_at": process.get("process_started_at"),
        "pin_firing": pin.get("firing") or [], "process_firing": process.get("firing") or [],
    }


def collect_tree(*, now: datetime | None = None) -> dict[str, Any]:
    stamp = now or _now()
    report = build_report(
        unit_dir=Path.home() / ".config/systemd/user",
        crontab_text=load_crontab(None), current=CURRENT_HOME, include_effective=True,
    )
    combined = report["combined"]
    total = int(combined.get("tradeai_n") or 0)
    drift = int(combined.get("drift_n") or 0)
    return {
        "schema": "TreeRootIntegrityEvidence@v1", "as_of": stamp.replace(microsecond=0).isoformat(),
        "authority": "READ_ONLY_ADVISORY", "financial_action": False,
        "integrity_score": round((total - drift) / total, 6) if total else 0.0,
        "tradeai_n": total, "drift_n": drift, "by_class": combined.get("by_class") or {},
        "current": report.get("current"), "drift_samples": combined.get("drift_samples") or [],
    }


def collect(*, root: Path = ROOT, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Run the four read-only collectors. Writes nothing."""
    stamp = now or _now()
    return {
        "rag_freshness_latest.json": collect_rag_freshness(root=root, now=stamp),
        "pin_integrity_latest.json": collect_pin(now=stamp),
        "gpu_policy_latest.json": collect_gpu_policy(now=stamp),
        "ops_tree_pin_audit_latest.json": collect_tree(now=stamp),
    }


def refresh(*, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    stamp = now or _now()
    rows = collect(root=root, now=stamp)
    for name, row in rows.items():
        _atomic_json(root / OUT_DIR / name, row)
    return {"ok": True, "as_of": stamp.replace(microsecond=0).isoformat(), "artifacts": rows}


def scores(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rag = rows.get("rag_freshness_latest.json") or {}
    pin = rows.get("pin_integrity_latest.json") or {}
    gpu = rows.get("gpu_policy_latest.json") or {}
    tree = rows.get("ops_tree_pin_audit_latest.json") or {}
    return {
        "rag_freshness_score": rag.get("freshness_score"), "rag_query_ok": rag.get("query_ok"),
        "pin_integrity_score": pin.get("integrity_score"),
        "gpu_mode": gpu.get("gpu_mode"), "gpu_compliance_score": gpu.get("compliance_score"),
        "tree_integrity_score": tree.get("integrity_score"), "tree_drift_n": tree.get("drift_n"),
    }


def _receipt_lib():
    from scripts.lib import lane_last_receipt

    return lane_last_receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="collect and report; write no snapshot and no receipt")
    args = ap.parse_args(argv)
    lr = _receipt_lib()
    if args.dry_run:
        rows = collect()
        lr.dry_run_report(LANE_ID, scores(rows),
                          would_write=[f"{OUT_DIR / name} (atomic replace)" for name in SNAPSHOTS])
        return 0
    started = _now().isoformat()
    try:
        result = refresh()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="refresh_advisory_maturity_evidence.py", error=f"{type(exc).__name__}: {exc}")
        print(json.dumps({"ok": False, "error": type(exc).__name__}, sort_keys=True))
        return 1
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="refresh_advisory_maturity_evidence.py", summary=scores(result["artifacts"]),
                          output={"produced_count": len(result["artifacts"]), "attempted_count": len(SNAPSHOTS)})
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

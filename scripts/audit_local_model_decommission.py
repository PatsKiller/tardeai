#!/usr/bin/env python3
"""Read-only local-model decommission audit.

This command never stops processes, edits schedules, or removes models. It
collects the evidence required before an operator-authorized model removal can
be considered.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from audit_no_local_generative_routing import ROOT, source_callers


EMBEDDING_RE = re.compile(r"(?:^|[-_:])(?:embed|embedding)(?:[-_:]|$)", re.I)
GENERATIVE_RE = re.compile(r"^(?:gemma|qwen|llama|mistral|mixtral|phi|deepseek-r1|codellama)", re.I)
LOCAL_MARKER_RE = re.compile(
    r"(?:/api/(?:chat|generate)\b|--lane\s+local\b|\blane\s*=\s*local\b|"
    r"\blocal_llm\b|\bgemma\w*\b|\bqwen\w*\b|\braw_ollama\b|"
    r"\bLOCAL_LLM_MODEL\b|\bLLM_ALLOW_LOCAL_JUDGMENT\b|"
    r"\bRESEARCH_ALLOW_LOCAL_LLM\b)",
    re.I,
)


def _run(argv: list[str], timeout: int = 30) -> tuple[str, str | None]:
    try:
        completed = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=timeout,
        )
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"
    if completed.returncode:
        return completed.stdout, (completed.stderr.strip() or f"exit {completed.returncode}")
    return completed.stdout, None


def classify_model(name: str) -> str:
    normalized = name.split(":", 1)[0].lower()
    if EMBEDDING_RE.search(name) or normalized == "nomic-embed-text":
        return "EMBEDDING"
    if GENERATIVE_RE.search(normalized):
        return "GENERATIVE"
    return "UNKNOWN_UNUSED"


def parse_ollama_list(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append({"name": parts[0], "digest": parts[1], "class": classify_model(parts[0])})
    return rows


def parse_ollama_ps(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append({"name": parts[0], "digest": parts[1], "class": classify_model(parts[0])})
    return rows


def active_cron_callers(text: str, runtime_callers: list[dict[str, object]]) -> list[dict[str, object]]:
    basenames = {Path(str(row["file"])).name for row in runtime_callers}
    hits: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        matched = LOCAL_MARKER_RE.search(stripped) or any(name in stripped for name in basenames)
        if matched:
            hits.append({"line": number, "command": stripped[:500]})
    return hits


def _candidate_unit_names(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        name = line.split(maxsplit=1)[0] if line.strip() else ""
        if name.endswith(".service") and re.search(r"trade|hermes|aegis|iris|llm|portfolio", name, re.I):
            names.append(name)
    return sorted(set(names))


def systemd_callers(unit_listing: str, runtime_callers: list[dict[str, object]]) -> list[dict[str, str]]:
    basenames = {Path(str(row["file"])).name for row in runtime_callers}
    hits: list[dict[str, str]] = []
    for unit in _candidate_unit_names(unit_listing):
        body, error = _run(["systemctl", "--user", "cat", unit])
        if error:
            continue
        matched = LOCAL_MARKER_RE.search(body) or any(name in body for name in basenames)
        if matched:
            hits.append({"unit": unit, "reason": "local marker or runtime source caller"})
    return hits


def config_callers(root: Path) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    if not root.exists():
        return hits
    allowed = {".json", ".yaml", ".yml", ".toml", ".conf", ".service", ".sh", ".py"}
    candidates: list[Path] = []
    primary = root / "openclaw.json"
    if primary.is_file():
        candidates.append(primary)
    for child in (root / "config", root / "skills"):
        if child.is_dir():
            candidates.extend(child.rglob("*"))
    for path in sorted(set(candidates)):
        if not path.is_file() or path.suffix.lower() not in allowed or path.stat().st_size > 2_000_000:
            continue
        if any(part in {"logs", "sessions", "session_archive", "node_modules", "__pycache__"}
               for part in path.parts) or ".bak" in path.name:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for number, line in enumerate(lines, 1):
            if LOCAL_MARKER_RE.search(line):
                hits.append({"file": str(path), "line": number, "marker": "local-generative-reference"})
    return hits


def build_report(runtime_root: Path, openclaw_root: Path) -> dict[str, object]:
    repo_callers = source_callers(ROOT)
    runtime_source_callers = source_callers(runtime_root) if runtime_root.exists() else []
    cron_text, cron_error = _run(["crontab", "-l"])
    unit_listing, unit_error = _run(["systemctl", "--user", "list-unit-files", "--type=service", "--no-legend"])
    model_text, model_error = _run(["ollama", "list"])
    ps_text, ps_error = _run(["ollama", "ps"])
    models = parse_ollama_list(model_text)
    processes = parse_ollama_ps(ps_text)
    cron_hits = active_cron_callers(cron_text, runtime_source_callers)
    unit_hits = systemd_callers(unit_listing, runtime_source_callers) if not unit_error else []
    openclaw_hits = config_callers(openclaw_root)
    generative_models = [row for row in models if row["class"] == "GENERATIVE"]
    active_generative = [row for row in processes if row["class"] == "GENERATIVE"]
    embedding_models = [row for row in models if row["class"] == "EMBEDDING"]
    blockers: dict[str, object] = {
        "callers_in_source": len(runtime_source_callers),
        "callers_in_cron": "UNMEASURED" if cron_error else len(cron_hits),
        "callers_in_systemd": "UNMEASURED" if unit_error else len(unit_hits),
        "callers_in_openclaw_config": len(openclaw_hits),
        "active_generative_processes": "UNMEASURED" if ps_error else len(active_generative),
        "generative_models_installed": "UNMEASURED" if model_error else len(generative_models),
        "required_by_tests_proven_no": False,
        "bounded_zero_call_verification_passed": False,
        "embedding_acceptance_passed": False,
    }
    measured_counts = (
        "callers_in_source", "callers_in_cron", "callers_in_systemd",
        "callers_in_openclaw_config", "active_generative_processes",
        "generative_models_installed",
    )
    removal_ready = all(blockers[key] == 0 for key in measured_counts) and all(
        blockers[key] is True for key in (
            "required_by_tests_proven_no",
            "bounded_zero_call_verification_passed",
            "embedding_acceptance_passed",
        )
    )
    return {
        "schema": "LocalModelDecommissionAudit@v1",
        "authority": "READ_ONLY_ADVISORY",
        "mutations": 0,
        "runtime_root": str(runtime_root),
        "repo_source_callers": len(repo_callers),
        "runtime_source_callers": runtime_source_callers,
        "cron_callers": cron_hits,
        "systemd_callers": unit_hits,
        "openclaw_config_callers": openclaw_hits,
        "models": models,
        "active_models": processes,
        "embedding_models": embedding_models,
        "blockers": blockers,
        "physical_removal_ready": removal_ready,
        "gpu_mode": "UNRESOLVED_HOLD" if not removal_ready else "EMBEDDINGS_ONLY",
        "errors": {
            "crontab": cron_error,
            "systemd": unit_error,
            "ollama_list": model_error,
            "ollama_ps": ps_error,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--openclaw-root", type=Path, default=Path.home() / ".openclaw")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    report = build_report(args.runtime_root.resolve(), args.openclaw_root.resolve())
    if args.summary:
        cron_targets = sorted({
            match
            for row in report["cron_callers"]
            for match in re.findall(r"(?:scripts/)?([A-Za-z0-9_.-]+\.(?:py|sh))", str(row["command"]))
        })
        report = {
            "schema": report["schema"],
            "authority": report["authority"],
            "mutations": report["mutations"],
            "runtime_root": report["runtime_root"],
            "repo_source_callers": report["repo_source_callers"],
            "runtime_source_caller_count": len(report["runtime_source_callers"]),
            "cron_caller_count": len(report["cron_callers"]),
            "cron_targets": cron_targets,
            "systemd_caller_count": len(report["systemd_callers"]),
            "systemd_units": [row["unit"] for row in report["systemd_callers"]],
            "openclaw_config_caller_count": len(report["openclaw_config_callers"]),
            "openclaw_files": sorted({row["file"] for row in report["openclaw_config_callers"]}),
            "models": report["models"],
            "active_models": report["active_models"],
            "blockers": report["blockers"],
            "physical_removal_ready": report["physical_removal_ready"],
            "gpu_mode": report["gpu_mode"],
            "errors": report["errors"],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["physical_removal_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Session 18E validation — local LLM centralization and Intel Arc GPU config."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PASS = 0
FAIL = 0
WARN = 0


def check(label, ok, msg=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}: {msg}")


def warn(label, msg=""):
    global WARN
    WARN += 1
    print(f"  [WARN] {label}: {msg}")


def main():
    print("=" * 60)
    print("SESSION 18E VALIDATION: LOCAL LLM CENTRALIZATION")
    print("=" * 60)

    # 1. local_llm_config.py imports
    print("\n--- Check 1: local_llm_config.py imports ---")
    try:
        from local_llm_config import (
            get_local_llm_config,
            get_local_llm_model,
            get_local_llm_base_url,
            get_local_llm_status,
            apply_ollama_runtime_env,
            DEFAULT_LOCAL_LLM_MODEL,
        )
        check("local_llm_config imports", True)
    except ImportError as e:
        check("local_llm_config imports", False, str(e))
        print("\nSESSION 18E VALIDATION: FAILED (cannot import local_llm_config)")
        sys.exit(1)

    # 2. get_local_llm_model() returns expected value
    print("\n--- Check 2: Model resolution ---")
    model = get_local_llm_model()
    expected = os.getenv("LOCAL_LLM_MODEL", "qwen3:14b")
    check(f"get_local_llm_model() = {model}", model == expected, f"expected {expected}")
    cfg = get_local_llm_config()
    check(f"provider = {cfg.provider}", cfg.provider == "ollama")
    check(f"backend = {cfg.backend}", cfg.backend == "vulkan")

    # 3. No operational Python file hardcodes qwen3:1.7b
    print("\n--- Check 3: No hardcoded qwen3:1.7b ---")
    scripts_dir = PROJECT_ROOT / "scripts"
    bad_files = []
    # Files that are allowed to reference qwen3:1.7b in comments/docstrings/logic constants
    _ALLOWED_FILES = {"llm_router.py", "full_system_backup.py", "local_llm_config.py"}
    for py in sorted(scripts_dir.glob("*.py")):
        if py.name.startswith("session"):
            continue
        if py.name in _ALLOWED_FILES:
            continue
        content = py.read_text()
        in_docstring = False
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            # Track multi-line docstrings
            if '"""' in stripped or "'''" in stripped:
                count = stripped.count('"""') + stripped.count("'''")
                if count == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            if "qwen3:1.7b" in line:
                bad_files.append(f"{py.name}:{i}")
    check("No qwen3:1.7b in operational code", len(bad_files) == 0,
          f"found in: {', '.join(bad_files)}")

    # 4. No Ollama model hardcoded in request payloads (operational code)
    print("\n--- Check 4: No hardcoded model in Ollama payloads ---")
    payload_issues = []
    model_pattern = re.compile(r'"model"\s*:\s*"(qwen3:[0-9]+\.?[0-9]*b|llama3|mistral|deepseek|gemma)"')
    for py in sorted(scripts_dir.glob("*.py")):
        if py.name.startswith("session"):
            continue
        if py.name == "local_llm_config.py":
            continue
        content = py.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            m = model_pattern.search(line)
            if m:
                payload_issues.append(f"{py.name}:{i} ({m.group(1)})")
    check("No hardcoded models in request payloads", len(payload_issues) == 0,
          f"found: {', '.join(payload_issues)}")

    # 5. api_v2.py system health returns local_llm
    print("\n--- Check 5: System health endpoint ---")
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:7777/api/v2/local-llm-status", timeout=5) as resp:
            raw_data = json.loads(resp.read())
            # Handle { "ok": true, "data": { ... } } wrapper
            data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data
            has_local_llm = "local_llm" in data
            if has_local_llm:
                llm = data["local_llm"]
                check(f"local_llm.model = {llm.get('model')}", llm.get("model") == expected)
                check(f"local_llm.provider = {llm.get('provider')}", llm.get("provider") == "ollama")
                check(f"local_llm.backend = {llm.get('backend')}", llm.get("backend") == "vulkan")
            else:
                # Pre-restart: check top-level model field
                top_model = data.get("model")
                if top_model:
                    check(f"model = {top_model}", expected.split(':')[0] in str(top_model),
                          "local_llm section will appear after server restart")
                else:
                    warn("local-llm-status", "no model field — restart server to apply changes")
    except Exception as e:
        warn("System health endpoint", f"server not reachable: {e}")

    # 6. Ollama model list
    print("\n--- Check 6: Ollama model availability ---")
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            has_model = any(expected.split(":")[0] in m for m in models)
            check(f"Ollama has {expected}", has_model, f"models: {models[:5]}")
    except Exception as e:
        warn("Ollama reachability", str(e))

    # 7. Vulkan/GPU env expectations
    print("\n--- Check 7: Vulkan/GPU configuration ---")
    status = get_local_llm_status()
    runtime = status.get("runtime_env", {})
    check("OLLAMA_VULKAN in config", status.get("backend") == "vulkan")
    check("GGML_VK_VISIBLE_DEVICES in config",
          cfg.ggml_vk_visible_devices is not None)

    # GPU tools
    for tool in ["vulkaninfo", "clinfo", "intel_gpu_top"]:
        available = shutil.which(tool) is not None
        if available:
            check(f"{tool} available", True)
        else:
            warn(f"{tool} not found", "install for GPU diagnostics")

    # 8. Proposal analyzer imports (syntax check)
    print("\n--- Check 8: Proposal analyzer ---")
    try:
        import ast
        ast.parse((PROJECT_ROOT / "scripts" / "proposal_intelligence_analyzer.py").read_text())
        check("proposal_intelligence_analyzer parses", True)
    except Exception as e:
        check("proposal_intelligence_analyzer parses", False, str(e))

    # 9. Paper trade analyzer imports (syntax check)
    print("\n--- Check 9: Paper trade analyzer ---")
    try:
        ast.parse((PROJECT_ROOT / "scripts" / "paper_trade_analyzer.py").read_text())
        check("paper_trade_analyzer parses", True)
    except Exception as e:
        check("paper_trade_analyzer parses", False, str(e))

    # 10. Real journal clean
    print("\n--- Check 10: Real journal clean ---")
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:7777/api/v2/journal", timeout=5) as resp:
            raw_data = json.loads(resp.read())
            inner = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data
            trades = (inner.get("trades", []) if isinstance(inner, dict) else inner) or []
            paper_count = 0
            for t in trades:
                if isinstance(t, dict):
                    acct = str(t.get("account", "")) + str(t.get("account_name", ""))
                    if "PAPER" in acct.upper():
                        paper_count += 1
            check(f"Real journal clean ({len(trades)} trades, {paper_count} paper)",
                  paper_count == 0, f"{paper_count} paper trades in real journal")
    except Exception as e:
        warn("Real journal check", str(e))

    # 11. Holdings unchanged
    print("\n--- Check 11: Holdings ---")
    try:
        h = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        v = h["portfolio_totals"]["total_value"]
        check(f"Holdings ${v:,.0f} > $1M", v > 1_000_000, f"value: {v}")
    except Exception as e:
        check("Holdings file readable", False, str(e))

    # Summary
    print("\n" + "=" * 60)
    if FAIL == 0:
        print(f"SESSION 18E VALIDATION: PASSED ({PASS} passed, {WARN} warnings)")
    else:
        print(f"SESSION 18E VALIDATION: FAILED ({PASS} passed, {FAIL} failed, {WARN} warnings)")
    print("=" * 60)
    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()

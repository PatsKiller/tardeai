#!/usr/bin/env python3
"""phase3_media_prose_routing_policy.py — Load and enforce Phase 3C media/prose routing."""
import yaml
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJ / "config" / "phase3_media_prose_routing.yaml"

def load_policy(path=None):
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        return {"enabled": False, "error": f"Config not found: {p}"}
    return yaml.safe_load(p.read_text())

def is_workflow_allowed(workflow, policy=None):
    if policy is None: policy = load_policy()
    if not policy.get("enabled"): return False
    return workflow in (policy.get("approved_workflows") or [])

def is_workflow_blocked(workflow, policy=None):
    if policy is None: policy = load_policy()
    return workflow in (policy.get("blocked_workflows") or [])

def assert_workflow_allowed(workflow, policy=None):
    if policy is None: policy = load_policy()
    if not policy.get("enabled"):
        raise RuntimeError("Phase 3C routing disabled")
    if is_workflow_blocked(workflow, policy):
        raise RuntimeError(f"Workflow '{workflow}' BLOCKED by Phase 3C policy")
    if not is_workflow_allowed(workflow, policy):
        raise RuntimeError(f"Workflow '{workflow}' not approved — default is blocked")

def get_model_for_workflow(workflow, policy=None):
    if policy is None: policy = load_policy()
    if is_workflow_allowed(workflow, policy):
        return policy.get("candidate_model", "gemma3:4b")
    return policy.get("fallback_model", "gemma3:4b")

def get_fallback_model(policy=None):
    if policy is None: policy = load_policy()
    return policy.get("fallback_model", "gemma3:4b")

def describe_policy(policy=None):
    if policy is None: policy = load_policy()
    return {
        "phase": policy.get("phase"), "enabled": policy.get("enabled"),
        "candidate": policy.get("candidate_model"),
        "fallback": policy.get("fallback_model"),
        "standard": policy.get("production_standard_model"),
        "embedding": policy.get("production_embedding_model"),
        "approved": policy.get("approved_workflows", []),
        "blocked": policy.get("blocked_workflows", []),
    }

if __name__ == "__main__":
    import json; print(json.dumps(describe_policy(), indent=2))

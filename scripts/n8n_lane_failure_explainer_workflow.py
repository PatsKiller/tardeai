#!/usr/bin/env python3
"""Generate the shadow workflow for the lane-failure explainer. Do not import it.

Writes one inactive workflow JSON. The operator imports it later, under a grant
that names the workflow id, and only after the §23.10 preconditions are met.
This script does not talk to n8n.

    python3 scripts/n8n_lane_failure_explainer_workflow.py
    python3 scripts/n8n_lane_failure_explainer_workflow.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.n8n_workflow_templates import (  # noqa: E402
    CREDENTIAL_NAME,
    HTTP_TIMEOUT_MS,
    RELAY_URL_PLACEHOLDER,
    RELAY_URL_VAR,
    TIMEZONE,
)

DEFAULT_OUT = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated"
WORKFLOW_NAME = "n8n-lane-failure-explainer-shadow"
TEMPLATE_ID = "n8n_lane_failure_explainer@v1"
BRIDGE_AGENT_PLACEHOLDER = "http://BRIDGE_AGENT_HOST:8766/v1/agent"
_UUID_NS = uuid.UUID("b7e1c2d3-4a5f-4e70-8192-a3b4c5d6e7f8")
NODE_MANUAL = "Manual shadow"
NODE_SET = "Relay constants"
NODE_AGENT = "Explain lane failure"
NODE_MODEL = "Bridge Agent endpoint"
NODE_LAST = "GET runs last"
NODE_RECENT = "GET runs recent"
NODE_LANE = "GET lane row"


def _node_id(name: str) -> str:
    return str(uuid.uuid5(_UUID_NS, f"{WORKFLOW_NAME}:{name}"))


def _wf_id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def _tool_url(suffix: str) -> str:
    base = "$('Relay constants').item.json." + RELAY_URL_VAR
    lane = "$('Relay constants').item.json.lane_id"
    return "={{ " + base + " }}/" + suffix.replace("{lane}", "{{ " + lane + " }}")


def _set_node(relay_url: str) -> dict:
    return {
        "id": _node_id(NODE_SET),
        "name": NODE_SET,
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [480, 300],
        "parameters": {
            "assignments": {
                "assignments": [
                    {
                        "id": _node_id("url"),
                        "name": RELAY_URL_VAR,
                        "type": "string",
                        "value": relay_url,
                    },
                    {
                        "id": _node_id("lane"),
                        "name": "lane_id",
                        "type": "string",
                        "value": "LANE_ID",
                    },
                ]
            },
            "includeOtherFields": False,
            "options": {},
        },
    }


def _tool(name: str, url: str, description: str, position: list[int]) -> dict:
    return {
        "id": _node_id(name),
        "name": name,
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.2,
        "position": position,
        "credentials": {"httpHeaderAuth": {"id": CREDENTIAL_NAME, "name": CREDENTIAL_NAME}},
        "parameters": {
            "method": "GET",
            "url": url,
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "toolDescription": description,
            "options": {"timeout": HTTP_TIMEOUT_MS},
        },
    }


def build_workflow(relay_url: str = RELAY_URL_PLACEHOLDER) -> dict:
    """Inactive shadow workflow. active is false. Nothing here is imported."""
    nodes = [
        {
            "id": _node_id(NODE_MANUAL),
            "name": NODE_MANUAL,
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [240, 300],
            "parameters": {},
        },
        _set_node(relay_url),
        {
            "id": _node_id(NODE_AGENT),
            "name": NODE_AGENT,
            "type": "@n8n/n8n-nodes-langchain.agent",
            "typeVersion": 3.1,
            "position": [760, 300],
            "parameters": {
                "promptType": "define",
                "text": "=" + TEMPLATE_ID + " lane_id={{ $('Relay constants').item.json.lane_id }}",
                "options": {"maxIterations": 4},
            },
        },
        {
            "id": _node_id(NODE_MODEL),
            "name": NODE_MODEL,
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1,
            "position": [760, 520],
            "notes": "Placeholder for the governed bridge Agent endpoint. No provider credential.",
            "parameters": {
                "model": "bridge-agent-placeholder",
                "options": {"baseURL": BRIDGE_AGENT_PLACEHOLDER, "maxTokens": 800, "timeout": 30000},
            },
        },
        _tool(
            NODE_LAST,
            _tool_url("runs/{lane}/last"),
            "Read the newest run receipt for this lane.",
            [980, 120],
        ),
        _tool(
            NODE_RECENT,
            _tool_url("runs/{lane}/recent?n=10"),
            "Read up to 10 recent run receipts for this lane.",
            [980, 300],
        ),
        _tool(
            NODE_LANE,
            _tool_url("lanes/{lane}"),
            "Read the lane registry row: owner, cadence, output signal, and scheduler kind.",
            [980, 480],
        ),
    ]
    connections = {
        NODE_MANUAL: {"main": [[{"node": NODE_SET, "type": "main", "index": 0}]]},
        NODE_SET: {"main": [[{"node": NODE_AGENT, "type": "main", "index": 0}]]},
        NODE_MODEL: {"ai_languageModel": [[{"node": NODE_AGENT, "type": "ai_languageModel", "index": 0}]]},
        NODE_LAST: {"ai_tool": [[{"node": NODE_AGENT, "type": "ai_tool", "index": 0}]]},
        NODE_RECENT: {"ai_tool": [[{"node": NODE_AGENT, "type": "ai_tool", "index": 0}]]},
        NODE_LANE: {"ai_tool": [[{"node": NODE_AGENT, "type": "ai_tool", "index": 0}]]},
    }
    return {
        "id": _wf_id(WORKFLOW_NAME),
        "name": WORKFLOW_NAME,
        "active": False,
        "shadow": True,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": TIMEZONE, "shadow": True, "saveManualExecutions": False},
        "meta": {
            "generator": "scripts/n8n_lane_failure_explainer_workflow.py",
            "shadow": True,
            "mode": "dry_run",
            "imported": False,
            "activated": False,
            "process_id": "n8n_lane_failure_explainer",
            "template_id": TEMPLATE_ID,
            "authority": "READ_ONLY_ADVISORY",
            "model_endpoint_placeholder": BRIDGE_AGENT_PLACEHOLDER,
        },
    }


def render(relay_url: str = RELAY_URL_PLACEHOLDER) -> str:
    return json.dumps(build_workflow(relay_url), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(out: Path, relay_url: str = RELAY_URL_PLACEHOLDER) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{WORKFLOW_NAME}.json"
    path.write_text(render(relay_url), encoding="utf-8")
    return path


def check(out: Path, relay_url: str = RELAY_URL_PLACEHOLDER) -> list[str]:
    path = out / f"{WORKFLOW_NAME}.json"
    if not path.exists():
        return [f"missing: {path.name}"]
    if path.read_text(encoding="utf-8") != render(relay_url):
        return [f"stale: {path.name}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--relay-url", default=RELAY_URL_PLACEHOLDER)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    if args.check:
        diffs = check(out, args.relay_url)
        print(json.dumps({"mode": "check", "diffs": diffs, "out": str(out)}))
        return 1 if diffs else 0
    path = write(out, args.relay_url)
    print(json.dumps({"mode": "write", "path": str(path), "imported": False, "active": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

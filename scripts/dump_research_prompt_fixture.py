#!/usr/bin/env python3
"""Dump the exact redacted stateful research prompt for acceptance evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.hermes_external_researcher import PROMPT
from scripts.lib.research_prompt_context import build_research_prompt_context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NOC")
    parser.add_argument("--question", default="What changed in the standing NOC investment thesis?")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()

    if args.env_file and args.env_file.is_file():
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    context = build_research_prompt_context(
        args.symbol,
        question=args.question,
        root=args.root,
    )
    prompt = PROMPT.replace("{question}", args.question).replace(
        "{context}", json.dumps(context, sort_keys=True, default=str)
    )
    artifact = {
        "schema": "ResearchPromptAcceptanceFixture@v1",
        "symbol": args.symbol.upper(),
        "source_root": str(args.root),
        "prompt_context_hash": context.get("prompt_context_hash"),
        "redacted": True,
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "prompt_context": context,
        "exact_prompt": prompt,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "symbol": args.symbol.upper(),
        "prompt_context_hash": context.get("prompt_context_hash"),
        "prompt_chars": len(prompt),
        "authority": "READ_ONLY_ADVISORY",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

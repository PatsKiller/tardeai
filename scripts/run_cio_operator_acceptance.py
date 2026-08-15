#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.lib.cio_operator_acceptance import run_acceptance


def main() -> int:
    rep = run_acceptance()
    print(json.dumps({
        "acceptance": rep["acceptance"],
        "overall": rep["overall"],
        "failed": rep["failed"],
        "learning_runtime": rep["learning_runtime"],
        "authority": rep["authority"],
    }, indent=2))
    return 0 if rep["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

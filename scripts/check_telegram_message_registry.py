#!/usr/bin/env python3
"""Lint the canonical Telegram message registry."""
from __future__ import annotations

import json
import sys

from lib.message_contract import MESSAGE_REGISTRY, REGISTRY_VERSION, lint_registry


def main() -> int:
    errors = lint_registry()
    report = {"registry_version": REGISTRY_VERSION, "registered_types": len(MESSAGE_REGISTRY), "errors": errors}
    print(json.dumps(report, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

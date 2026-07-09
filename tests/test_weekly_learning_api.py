#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
from weekly_learning_api import review_snippet  # noqa: E402


def test_unwraps_json_weekly_summary():
    raw = '```json\n{"weekly_summary": "Strong week on BIRD swing."}\n```'
    assert review_snippet(raw) == "Strong week on BIRD swing."


def test_plain_text_passthrough():
    assert review_snippet("The trade on DXCM was a small win.") == "The trade on DXCM was a small win."
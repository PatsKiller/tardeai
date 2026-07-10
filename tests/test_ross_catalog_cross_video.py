#!/usr/bin/env python3
"""Tests for Ross catalog cross-video clip inference."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from ross_catalog_cross_video import infer_clip_symbols  # noqa: E402


def check(name, cond):
    if cond:
        print(f"  [PASS] {name}")
        return True
    print(f"  [FAIL] {name}")
    return False


def main():
    ok = True
    td = date(2026, 7, 9)
    entries = [
        {
            "trade_date": td,
            "video_id": "49ykxodJcFc",
            "video_title": "250% Short Squeeze on Breaking News!",
            "symbols_traded": ["VRX"],
            "net_pnl_usd": 24359.4,
            "extraction_method": "hermes",
            "extraction_confidence": 0.9,
            "hermes_review_json": {},
            "winners": [],
            "losers": [],
        },
        {
            "trade_date": td,
            "video_id": "eFau-kkYvh8",
            "video_title": "+$19,000 In One Trade..",
            "symbols_traded": [],
            "net_pnl_usd": 19000.0,
            "extraction_method": "regex",
            "extraction_confidence": 0.7,
            "hermes_review_json": {},
            "winners": [],
            "losers": [],
        },
    ]
    out = infer_clip_symbols(entries)
    clip = next(e for e in out if e["video_id"] == "eFau-kkYvh8")
    ok &= check("infers VRX on clip", "VRX" in (clip.get("symbols_traded") or []))
    ok &= check("method cross_video", clip.get("extraction_method") == "cross_video")
    ok &= check("confidence bumped", (clip.get("extraction_confidence") or 0) >= 0.85)

    if not ok:
        sys.exit(1)
    print("All ross_catalog_cross_video checks passed.")


if __name__ == "__main__":
    main()
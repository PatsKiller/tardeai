#!/usr/bin/env python3
"""Render Trade AI Institutional Report v2 — Phase 4 unified exporter.

One canonical model snapshot feeds HTML + DOCX + PDF via the shared view layer
(`scripts/lib/cio_report_view.py` + `scripts/lib/cio_report_render.py`).

Usage:
  python scripts/render_cio_report_files.py [model.json] [out_dir]

Defaults:
  model  = /tmp/cio_report_v2_model.json
  out_dir = <repo>/exports

READ_ONLY_ADVISORY. No broker / Telegram.
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
EXPORTS = REPO / "exports"

# Ensure package imports resolve when run as a script
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


def _load_model(src: pathlib.Path) -> dict:
    model = json.loads(src.read_text(encoding="utf-8"))
    # API wrappers sometimes nest under data
    if "data" in model and "report_version" not in model and isinstance(model["data"], dict):
        model = model["data"]
    return model


def build_docx(model: dict, out: pathlib.Path):
    """Backward-compatible DOCX entrypoint — routes through shared view."""
    from scripts.lib.cio_report_render import render_docx_from_view
    from scripts.lib.cio_report_view import build_report_view
    view = model.get("view") if isinstance(model.get("view"), dict) else build_report_view(model)
    return render_docx_from_view(view, out)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    src = pathlib.Path(argv[0]) if argv else pathlib.Path("/tmp/cio_report_v2_model.json")
    out_dir = pathlib.Path(argv[1]) if len(argv) > 1 else EXPORTS

    if not src.exists():
        print(f"model not found: {src}", file=sys.stderr)
        return 2

    model = _load_model(src)
    from scripts.lib.cio_report_render import export_report_formats

    result = export_report_formats(model, out_dir, basename="cio_institutional_report_v2")
    print(json.dumps({
        "ok": result.get("ok"),
        "architecture_version": result.get("architecture_version"),
        "facts_fingerprint": result.get("facts_fingerprint"),
        "paths": result.get("paths"),
        "errors": result.get("errors"),
        "parity": result.get("parity"),
    }, indent=2, default=str))
    # Success if at least HTML landed (DOCX/PDF optional by environment)
    return 0 if result.get("paths", {}).get("html") else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Canonical Trade AI Institutional Report v2 generator — Phase 7 pipeline.

One model snapshot → shared view → HTML / PDF / DOCX + immutable instance
manifest + cross-format parity claims.

Usage:
  python scripts/render_cio_report_files.py \\
    --source live \\
    --formats html,pdf,docx \\
    --out exports/

  python scripts/render_cio_report_files.py \\
    --source file \\
    --model /tmp/cio_report_v2_model.json \\
    --formats html,docx \\
    --out /tmp/report_out

Legacy positional form still works:
  python scripts/render_cio_report_files.py [model.json] [out_dir]

READ_ONLY_ADVISORY. No broker / Telegram / order / stop authority.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any, Optional

REPO = pathlib.Path(__file__).resolve().parent.parent
EXPORTS = REPO / "exports"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


def _load_model(src: pathlib.Path) -> dict:
    model = json.loads(src.read_text(encoding="utf-8"))
    if "data" in model and "report_version" not in model and isinstance(model["data"], dict):
        model = model["data"]
    return model


def _load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _source_sha() -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO), capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def assemble_live_model() -> dict[str, Any]:
    """Assemble a live report model from holdings + capital plan + MS Part B.

    Uses the live book only. Refuses a synthetic $100k fallback.
    Fail-soft on optional DB/MS companions. Never contacts a broker.
    """
    from scripts.lib.cio_live_report import build_report_from_live_sources

    return build_report_from_live_sources(
        source_sha=_source_sha(),
        attach_live_queue=True,
        allow_ms_assemble=True,
        now=datetime.now(timezone.utc),
    )


def build_docx(model: dict, out: pathlib.Path):
    """Backward-compatible DOCX entrypoint — routes through shared view."""
    from scripts.lib.cio_report_render import render_docx_from_view
    from scripts.lib.cio_report_view import build_report_view
    view = model.get("view") if isinstance(model.get("view"), dict) else build_report_view(model)
    return render_docx_from_view(view, out)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    # Legacy positional: model.json out_dir
    legacy = (
        len(argv) >= 1
        and not argv[0].startswith("-")
        and not any(a.startswith("--") for a in argv)
    )

    parser = argparse.ArgumentParser(
        description="Trade AI Institutional Report v2 — Phase 7 pipeline",
    )
    parser.add_argument(
        "--source",
        choices=("live", "file"),
        default="file",
        help="live = assemble from holdings/DB; file = load --model JSON",
    )
    parser.add_argument(
        "--model",
        default="/tmp/cio_report_v2_model.json",
        help="Path to report model JSON when --source=file",
    )
    parser.add_argument(
        "--formats",
        default="html,pdf,docx",
        help="Comma-separated: html,pdf,docx",
    )
    parser.add_argument(
        "--out",
        default=str(EXPORTS),
        help="Output directory",
    )
    parser.add_argument(
        "--basename",
        default="cio_institutional_report_v2",
        help="Output file basename",
    )
    parser.add_argument(
        "--report-id",
        default=None,
        help="Optional fixed report_id (default: generated)",
    )

    if legacy:
        # map positional to namespace
        args = parser.parse_args([])
        args.source = "file"
        args.model = argv[0]
        args.out = argv[1] if len(argv) > 1 else str(EXPORTS)
        # Legacy positional defaults to HTML (always available). PDF/DOCX via --formats.
        args.formats = "html"
        args.basename = "cio_institutional_report_v2"
        args.report_id = None
    else:
        args = parser.parse_args(argv)

    formats = [f.strip().lower() for f in str(args.formats).split(",") if f.strip()]
    out_dir = pathlib.Path(args.out)

    if args.source == "live":
        model = assemble_live_model()
    else:
        src = pathlib.Path(args.model)
        if not src.exists():
            print(json.dumps({"ok": False, "error": f"model not found: {src}"}), file=sys.stderr)
            return 2
        model = _load_model(src)

    from scripts.lib.cio_report_render import export_report_formats

    result = export_report_formats(
        model,
        out_dir,
        basename=args.basename,
        formats=formats,
        report_id=args.report_id,
    )

    summary = {
        "ok": result.get("ok"),
        "report_id": result.get("report_id"),
        "architecture_version": result.get("architecture_version"),
        "facts_fingerprint": result.get("facts_fingerprint"),
        "formats_requested": formats,
        "paths": result.get("paths"),
        "errors": result.get("errors"),
        "phase7_exit_gate": result.get("phase7_exit_gate"),
        "claims": {
            "files_created": list(((result.get("claims") or {}).get("files_created") or {}).keys()),
        },
        "authority": "READ_ONLY_ADVISORY",
    }
    print(json.dumps(summary, indent=2, default=str))

    gate = result.get("phase7_exit_gate") or {}
    # Success: HTML present + key-value parity PASS (PDF/DOCX env-optional)
    if not result.get("paths", {}).get("html"):
        return 1
    if gate.get("HTML_PDF_DOCX_KEY_VALUE_PARITY") == "FAIL":
        return 3
    if gate.get("CLI_CLAIMS_EQ_FILES_CREATED") == "FAIL":
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prospectus print-fidelity check: does the PDF and the Word download look like the HTML report?

For each report JSON it renders
  * the HTML report as the reader sees it (light theme, print width) → one full-page screenshot (Chromium),
  * the PDF (Chromium print, print_render) → page PNGs (pdftoppm),
  * the DOCX (LibreOffice, print_render) → PDF (soffice) → page PNGs,
  * and, as "before", the previous renderers (WeasyPrint PDF, python-docx DOCX) the same way,
then scores
  * palette similarity: quantised colour histogram of HTML vs each format (do the design colours survive?),
  * page similarity: PDF page i vs DOCX page i (blurred, downscaled grayscale; do the two downloads match?),
and writes side-by-side PNGs: ``<SYM>-overview.png`` (HTML | PDF before | PDF after | DOCX before | DOCX after) and
``<SYM>-pages.png`` (PDF after page i | DOCX after page i).

Usage:
  python scripts/prospectus_print_fidelity.py --out DIR [--threshold 0.85] [REPORT.json ...]
With no REPORT the public synthetic fixture (apps/command-center-v3/e2e/fixtures/prospectus-fund.json) is used.
Real reports: copy their prospectus.json into a TEMP dir first and keep the output private (the repo is public).
Needs python playwright + its Chromium, LibreOffice (soffice) and pdftoppm; exits 2 naming what is missing.
Exit 0 = every score at or above the threshold, 1 = below. READ_ONLY_ADVISORY: renders only (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.prospectus import print_render as P, render  # noqa: E402

FIXTURE = ROOT / "apps/command-center-v3/e2e/fixtures/prospectus-fund.json"


def missing_tools(s: dict) -> list[str]:
    out = []
    if P.chromium_available():
        out.append(P.chromium_available())
    if not P.soffice_path(s):
        out.append("soffice (LibreOffice)")
    if not shutil.which("pdftoppm"):
        out.append("pdftoppm (poppler-utils)")
    try:
        import PIL  # noqa: F401, PLC0415
    except ImportError:
        out.append("Pillow")
    return out


def pdf_pages(pdf: Path, prefix: Path, dpi: int = 50) -> list[Path]:
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefix)], check=True, timeout=120)
    return sorted(prefix.parent.glob(prefix.name + "-*.png"))


def docx_pages(docx: bytes, work: Path, name: str, s: dict) -> list[Path]:
    src = work / f"{name}.docx"
    src.write_bytes(docx)
    out = P.soffice_convert(src, work, "pdf", s)
    return pdf_pages(out, work / f"{name}-p")


def html_shot(doc: dict, work: Path, s: dict) -> Path:
    page = work / "reader.html"
    html = render.html(doc, theme="light", print_mode=True)
    page.write_text(P.strip_citations(html), encoding="utf-8")
    shot = work / "reader.png"
    res = P.run_chromium({"_dir": str(work), "html_path": str(page), "full_page_png": str(shot),
                          "shot_width_px": 816, "scale": 1}, float(s["chromium_timeout_s"]))
    if not res.get("ok"):
        raise RuntimeError(f"html screenshot failed: {res.get('error')}")
    return shot


def _palette(img, bins: int = 6) -> list[float]:
    small = img.convert("RGB").resize((200, max(1, int(200 * img.height / img.width))))
    hist = [0] * (bins ** 3)
    step = 256 // bins + 1
    raw = small.tobytes()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        hist[(r // step) * bins * bins + (g // step) * bins + (b // step)] += 1
    total = float(sum(hist)) or 1.0
    return [h / total for h in hist]


def palette_similarity(a, b) -> float:
    """Histogram intersection of quantised colours, white excluded (page background differs in amount only)."""
    ha, hb = _palette(a), _palette(b)
    ha[-1] = hb[-1] = 0.0
    sa, sb = sum(ha) or 1.0, sum(hb) or 1.0
    return round(sum(min(x / sa, y / sb) for x, y in zip(ha, hb)), 3)


def page_similarity(a, b) -> float:
    from PIL import ImageFilter  # noqa: PLC0415
    size = (85, 110)
    ga = a.convert("L").filter(ImageFilter.GaussianBlur(2)).resize(size)
    gb = b.convert("L").filter(ImageFilter.GaussianBlur(2)).resize(size)
    diff = sum(abs(x - y) for x, y in zip(ga.tobytes(), gb.tobytes())) / (size[0] * size[1] * 255.0)
    return round(1.0 - diff, 3)


def stack(paths: list[Path], width: int):
    from PIL import Image  # noqa: PLC0415
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims = [im.resize((width, int(im.height * width / im.width))) for im in ims]
    h = sum(im.height for im in ims) + 6 * max(0, len(ims) - 1)
    out = Image.new("RGB", (width, max(1, h)), (128, 128, 128))
    y = 0
    for im in ims:
        out.paste(im, (0, y))
        y += im.height + 6
    return out


def side_by_side(cols: list, labels: list[str], path: Path, height: int | None = None) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415
    height = height or max(c.height for c in cols)
    cols = [c.resize((max(1, int(c.width * height / c.height)), height)) if c.height > height else c for c in cols]
    w = sum(c.width for c in cols) + 12 * (len(cols) - 1)
    canvas = Image.new("RGB", (w, height + 28), (90, 90, 90))
    draw = ImageDraw.Draw(canvas)
    x = 0
    for c, lab in zip(cols, labels):
        canvas.paste(c, (x, 28))
        draw.text((x + 6, 8), lab, fill=(255, 255, 255))
        x += c.width + 12
    canvas.save(path)


def check(doc: dict, out_dir: Path, s: dict, threshold: float) -> dict:
    from PIL import Image  # noqa: PLC0415
    sym = str(doc.get("symbol") or "DOC")
    with tempfile.TemporaryDirectory(prefix="prospectus-fidelity-") as tmp:
        work = Path(tmp)
        shot = html_shot(doc, work, s)
        rep: dict = {}
        files = P.render_print(doc, render.chart_pngs(doc), fallback_pdf=render.pdf, fallback_docx=render.docx, cfg=None,
                               report=rep)
        pngs = render.chart_pngs(doc)
        before_pdf, before_docx = render.pdf(doc, pngs), render.docx(doc, pngs)
        pages: dict[str, list[Path]] = {}
        for key, data in (("pdf_after", files.get("prospectus.pdf")), ("pdf_before", before_pdf)):
            if data:
                (work / f"{key}.pdf").write_bytes(data)
                pages[key] = pdf_pages(work / f"{key}.pdf", work / key)
        for key, data in (("docx_after", files.get("prospectus.docx")), ("docx_before", before_docx)):
            if data:
                pages[key] = docx_pages(data, work, key, s)
        html_img = Image.open(shot).convert("RGB")
        scores: dict = {"symbol": sym, "renderer": {k: rep.get(k) for k in ("pdf", "docx")}, "reasons": rep.get("reasons"),
                        "pages": {k: len(v) for k, v in pages.items()}}
        for key in ("pdf_after", "docx_after", "pdf_before", "docx_before"):
            if pages.get(key):
                scores[f"palette_html_vs_{key}"] = palette_similarity(html_img, stack(pages[key], 425))
        a, b = pages.get("pdf_after") or [], pages.get("docx_after") or []
        per = [page_similarity(Image.open(x), Image.open(y)) for x, y in zip(a, b)]
        scores["page_pdf_vs_docx_mean"] = round(sum(per) / len(per), 3) if per else 0.0
        scores["page_pdf_vs_docx_min"] = min(per) if per else 0.0
        width = 425
        cols, labels = [html_img.resize((width, int(html_img.height * width / html_img.width)))], ["HTML report"]
        for key, lab in (("pdf_before", "PDF before"), ("pdf_after", "PDF after"), ("docx_before", "Word before"),
                         ("docx_after", "Word after")):
            if pages.get(key):
                cols.append(stack(pages[key], width))
                labels.append(lab)
        out_dir.mkdir(parents=True, exist_ok=True)
        side_by_side(cols, labels, out_dir / f"{sym}-overview.png", height=6000)
        if a and b:
            pairs = []
            for x, y in zip(a, b):
                ix, iy = Image.open(x).convert("RGB"), Image.open(y).convert("RGB")
                pair = Image.new("RGB", (ix.width + iy.width + 12, max(ix.height, iy.height)), (90, 90, 90))
                pair.paste(ix, (0, 0))
                pair.paste(iy, (ix.width + 12, 0))
                pairs.append(pair)
            grid = Image.new("RGB", (pairs[0].width, sum(p.height + 12 for p in pairs)), (60, 60, 60))
            y = 0
            for p in pairs:
                grid.paste(p, (0, y))
                y += p.height + 12
            grid.save(out_dir / f"{sym}-pages.png")
        for key in ("pdf_after", "docx_after"):
            for i, p in enumerate(pages.get(key) or [], 1):
                shutil.copy(p, out_dir / f"{sym}-{key}-{i:02d}.png")
        shutil.copy(shot, out_dir / f"{sym}-html.png")
    gates = [scores.get("palette_html_vs_pdf_after", 0.0), scores.get("palette_html_vs_docx_after", 0.0),
             scores["page_pdf_vs_docx_mean"]]
    scores["threshold"] = threshold
    scores["pass"] = all(g >= threshold for g in gates)
    return scores


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reports", nargs="*", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threshold", type=float, default=0.85)
    args = ap.parse_args(argv)
    s = P.settings()
    missing = missing_tools(s)
    if missing:
        print(json.dumps({"ok": False, "missing": missing}))
        return 2
    docs = []
    for p in args.reports or [FIXTURE]:
        data = json.loads(p.read_text(encoding="utf-8"))
        docs.append(data.get("doc") if isinstance(data.get("doc"), dict) else data)
    results = [check(d, args.out, s, args.threshold) for d in docs]
    (args.out / "fidelity.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

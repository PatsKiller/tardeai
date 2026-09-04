/**
 * Squarified treemap layout. Pure geometry, no React, so it can be tested directly.
 *
 * Extracted from BookTreemap.tsx when it was emitting NaN rect geometry: /v3 logged 50
 * console errors on every load -- "<rect> attribute width: Expected length, NaN" and the
 * same for height, 25 rows x 2 attributes.
 *
 * The inner call passes `Math.max(0, groupHeight - HEADER)`, so any group rect shorter
 * than the 13px group header arrived with height 0. Then the available area was 0, every
 * normalised size became 0, and `thick = sum / along` evaluated 0/0.
 *
 * A box with no area cannot hold a rectangle. Saying so is the difference between drawing
 * nothing and drawing NaN -- and the browser keeps a NaN-sized element, complaining only
 * in a console nobody reads.
 */

export interface TreemapItem {
  size: number
  payload: any
}

export interface TreemapRect {
  x: number
  y: number
  w: number
  h: number
  payload: any
}

export function squarify(items: TreemapItem[], x: number, y: number, w: number, h: number): TreemapRect[] {
  const out: TreemapRect[] = []

  // A box with no area cannot hold a rectangle, and saying so here is the difference
  // between drawing nothing and drawing NaN.
  //
  // The inner call passes `Math.max(0, gr.h - HEAD)`, so any group rect shorter than the
  // 13px group header arrived with height 0. Then `area` was 0, every normalised size
  // became 0, and `thick = sum / along` evaluated 0/0 -> NaN, which went straight into
  // <rect width height>. That produced 50 console errors per load of /v3 --
  // "<rect> attribute width: Expected length, NaN" -- 25 rows x 2 attributes.
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return out

  let rest = items.filter(i => Number.isFinite(i.size) && i.size > 0).sort((a, b) => b.size - a.size)
  const total = rest.reduce((s, i) => s + i.size, 0) || 1
  let area = w * h
  rest = rest.map(i => ({ ...i, size: (i.size / total) * area }))
  let cx = x, cy = y, cw = w, ch = h
  while (rest.length) {
    const strip: typeof rest = []
    const along = Math.min(cw, ch)
    let best = Infinity
    for (const it of rest) {
      strip.push(it)
      const sum = strip.reduce((s, i) => s + i.size, 0)
      const thick = sum / along
      const worst = Math.max(...strip.map(i => {
        const len = i.size / thick
        return Math.max(thick / len, len / thick)
      }))
      if (worst > best) { strip.pop(); break }
      best = worst
    }
    const sum = strip.reduce((s, i) => s + i.size, 0)
    const thick = sum / along
    let off = 0
    for (const it of strip) {
      const len = it.size / thick
      // Belt and braces: a degenerate strip must not emit geometry at all. Rendering a
      // non-finite width is worse than rendering nothing, because the browser keeps the
      // element and only complains in the console.
      if (!Number.isFinite(len) || !Number.isFinite(thick)) continue
      if (cw >= ch) out.push({ x: cx, y: cy + off, w: thick, h: len, payload: it.payload })
      else out.push({ x: cx + off, y: cy, w: len, h: thick, payload: it.payload })
      off += len
    }
    if (cw >= ch) { cx += thick; cw -= thick } else { cy += thick; ch -= thick }
    rest = rest.slice(strip.length)
  }
  return out
}

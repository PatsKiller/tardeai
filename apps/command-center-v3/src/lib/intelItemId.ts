// A card's identity is what the card says, never where it happens to sit in the list.
//
// Why (measured 2026-11-07 19:20 ET, /v3/intelligence/classic): the Command Center list is assembled
// from ~13 feeds and used `id: `${source}-${out.length}``. Every time one more feed resolved, the
// positions shifted, so React saw a NEW key for an unchanged card, unmounted it and mounted another.
// Each mounted card reads its own verdict (/api/v2/inference/ensemble) and its lane readiness
// (/api/v2/llm/oauth-lanes), so the churn alone produced 26 ensemble reads and 21 identical lane
// reads in 27 s and the page never reached network idle. The same id is also the ensemble target_id
// stored per verdict, so a positional id can never be found again on the next render.
//
// The id is content-derived, deterministic and URL-safe: source, type and symbol as slugs plus a
// 32-bit FNV-1a tag of the title. Genuinely identical rows are told apart by an occurrence counter
// that depends only on how many identical rows came before, not on the position of unrelated rows.

export type IntelIdInput = {
  source?: string | null
  type?: string | null
  symbol?: string | null
  title?: string | null
}

export function idSlug(value: unknown, fallback = 'x'): string {
  const s = String(value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return s.slice(0, 40) || fallback
}

/** Stable 32-bit FNV-1a of the title, as 8 lowercase hex digits. */
export function titleTag(title: unknown): string {
  const s = String(title ?? '').trim()
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/**
 * Content identity for one intelligence card.
 * `occurrence` is 0 for the first row with this content and n-1 for the n-th; only used to keep two
 * genuinely identical rows distinct, never to encode list position.
 */
export function intelItemId(item: IntelIdInput, occurrence = 0): string {
  const base = [
    idSlug(item.source, 'unknown'),
    idSlug(item.type, 'intelligence'),
    idSlug(item.symbol, 'na'),
    titleTag(item.title),
  ].join('-')
  return occurrence > 0 ? `${base}~${occurrence + 1}` : base
}

/** Stored-product envelope, as the frontend reads it (combined Home, operator controlling decision 2026-11-13).
 *
 *  Producers (scripts/lib/cc_products/read_path.py `_envelope`, DSN-20261112-PRECOMPUTE-CACHE) serve either
 *    a) the envelope itself: { product, scope, status, as_of, built_at, next_refresh_at, stale_after_s, hard_expiry_s,
 *       age_s, seq, etag, reason, data, last_good, served_from, source_watermarks }, or
 *    b) the page body with the envelope fields under `_product` (cio_pages_route: { ...page, _product: {...} }).
 *  A route that is not (yet) a stored product carries neither: it is computed per request, and its clock is whatever
 *  the body says (as_of / generated_at), never the build time of anything.
 *
 *  Rules drawn from the decision: source time (as_of) and build time (built_at) are shown separately — a fresh build
 *  never makes a stale source look fresh; a product that is BUILDING / UNKNOWN / missing (or an HTTP 503 "building")
 *  is UNKNOWN with its reason, never blank and never an all-clear. Pure functions. */

export type ProductStatus = 'OK' | 'STALE' | 'UNKNOWN' | 'BUILDING' | 'NOT A PRODUCT'

export interface ProductClock {
  /** The product state as served; a route with no envelope is 'NOT A PRODUCT' (request-time computation). */
  status: ProductStatus
  /** What the section may claim: only OK is current; STALE is stale; everything else is UNKNOWN. */
  verdict: 'OK' | 'STALE' | 'UNKNOWN'
  product: string | null
  asOf: string | null
  builtAt: string | null
  nextRefreshAt: string | null
  staleAfterS: number | null
  hardExpiryS: number | null
  ageS: number | null
  /** Version key both sections must agree on: seq, else etag, else as_of (null = no version on the wire). */
  version: string | null
  servedFrom: string | null
  reason: string | null
}

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const STATUSES: ReadonlySet<string> = new Set(['OK', 'STALE', 'UNKNOWN', 'BUILDING'])

function meta(body: unknown): Obj | null {
  if (!isObj(body)) return null
  if (isObj(body._product)) return { ...body._product, product: body._product.product ?? body.product ?? null }
  if (typeof body.product === 'string' && typeof body.status === 'string' && 'built_at' in body) return body
  return null
}

/** The clock of a body a section read. `httpStatus` lets a 503 "building" answer read as UNKNOWN with its reason. */
export function productClock(body: unknown, httpStatus = 200): ProductClock {
  const m = meta(body)
  if (httpStatus === 503 || (!m && httpStatus !== 200)) {
    const why = isObj(body) ? (str(body.reason) || str(body.status) || str(body.error)) : null
    return blank('UNKNOWN', `HTTP ${httpStatus}${why ? ` — ${why}` : ''}: no product served`)
  }
  if (!m) {
    const asOf = isObj(body) ? (str(body.as_of) || (isObj(body.data) ? str(body.data.as_of) : null) || str(body.generated_at)) : null
    return { ...blank('NOT A PRODUCT', 'computed per request: no stored product for this route yet'), asOf }
  }
  const raw = String(m.status || '').toUpperCase()
  const status: ProductStatus = STATUSES.has(raw) ? raw as ProductStatus : 'UNKNOWN'
  const seq = m.seq
  const version = seq != null && seq !== '' ? `seq ${String(seq)}` : (str(m.etag) ? `etag ${str(m.etag)}` : (str(m.as_of) ? `as_of ${str(m.as_of)}` : null))
  let reason = str(m.reason)
  if (status === 'BUILDING' && !reason) reason = 'not built yet'
  if (status === 'UNKNOWN' && !reason) reason = raw ? `served status ${raw}` : 'no status on the envelope'
  return {
    status, verdict: status === 'OK' ? 'OK' : status === 'STALE' ? 'STALE' : 'UNKNOWN',
    product: str(m.product), asOf: str(m.as_of), builtAt: str(m.built_at), nextRefreshAt: str(m.next_refresh_at),
    staleAfterS: num(m.stale_after_s), hardExpiryS: num(m.hard_expiry_s), ageS: num(m.age_s),
    version, servedFrom: str(m.served_from), reason,
  }
}

function blank(status: ProductStatus, reason: string): ProductClock {
  return { status, verdict: 'UNKNOWN', product: null, asOf: null, builtAt: null, nextRefreshAt: null, staleAfterS: null,
    hardExpiryS: null, ageS: null, version: null, servedFrom: null, reason }
}

/** Both sections must draw the same published version of a product. Returns the defect text, or null. */
export function versionMismatch(path: string, a: ProductClock | null, b: ProductClock | null): string | null {
  if (!a || !b || !a.version || !b.version) return null
  if (a.version === b.version) return null
  return `DEFECT: ${path} drawn from two product versions (${a.version} vs ${b.version}) — the sections must read one version`
}

/** The combined Home's stored-products bundle (wt/home-products-lead, DSN-20261112-PRECOMPUTE-CACHE §6.1 envelope).
 *  Until that route is served, the read is UNKNOWN with its HTTP reason (a 404 is "not deployed yet", never empty-OK). */
export const PRODUCTS_HOME_API = '/api/v2/products/home'

/** Re-derive the verdict from the clocks the page holds, at `nowMs` (a 304 or a long-open tab moves time, not the body).
 *  Age is SOURCE age (as_of), never build age: a fresh build of a stale source stays stale. It only ever downgrades:
 *  OK -> STALE past stale_after_s; anything -> UNKNOWN past hard_expiry_s. A clock with no as_of keeps the served
 *  verdict (the server's age_s already said what it knew). */
export function clockAt(c: ProductClock, nowMs: number): ProductClock {
  const src = c.asOf ? Date.parse(c.asOf) : NaN
  if (!Number.isFinite(src) || c.status === 'NOT A PRODUCT') return c
  const ageS = Math.max(0, Math.floor((nowMs - src) / 1000))
  if (c.hardExpiryS != null && ageS > c.hardExpiryS && c.verdict !== 'UNKNOWN') {
    return { ...c, status: 'UNKNOWN', verdict: 'UNKNOWN', ageS, reason: `past hard expiry (${ageS}s > ${c.hardExpiryS}s): not current` }
  }
  if (c.staleAfterS != null && ageS > c.staleAfterS && c.verdict === 'OK') {
    return { ...c, status: 'STALE', verdict: 'STALE', ageS, reason: `source ${ageS}s old > stale after ${c.staleAfterS}s` }
  }
  return { ...c, ageS }
}

/** Every product in a /api/v2/products/home body: a single envelope, { products: [envelope…] },
 *  { products: { id: envelope } }, or any of those under { ok, data }. Unrecognised shapes give one UNKNOWN row. */
export function productsFromBundle(body: unknown): Array<{ id: string; clock: ProductClock }> {
  let b: unknown = body
  if (isObj(b) && b.ok !== undefined && isObj(b.data) && !('built_at' in b)) b = b.data
  const one = (id: string, env: unknown) => {
    const clock = productClock(env)
    return { id: clock.product || id, clock: clock.status === 'NOT A PRODUCT' ? { ...clock, ...blank('UNKNOWN', 'bundle entry carries no product envelope') } : clock }
  }
  if (isObj(b) && Array.isArray(b.products)) return b.products.map((e, i) => one(isObj(e) && str(e.product) ? String(e.product) : `#${i}`, e))
  if (isObj(b) && isObj(b.products)) return Object.entries(b.products).map(([id, e]) => one(id, e))
  if (meta(b)) return [one('home', b)]
  return [{ id: PRODUCTS_HOME_API, clock: blank('UNKNOWN', 'unrecognised products/home body: no envelope') }]
}

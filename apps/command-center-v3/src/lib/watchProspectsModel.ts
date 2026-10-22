/** Watch prospects — the page model for the /v3/watch redesign (Gate 3 mockup, operator directive 2026-10-22).
 *
 *  The server (GET /api/v3/data-broker/watch-prospects, scripts/lib/data_broker/watch_prospects.py) owns every
 *  judgment: lane, conviction, stance, conflicts, next trigger, next step. This file only shapes it for display,
 *  ties armed alerts to prospects (orphans listed), and holds the tooltip text. No colour literals (design tokens). */

export type LaneId = 'actionable' | 'forming' | 'reentry' | 'manage' | 'expired'

export type Side = { value: unknown; source: string | null; at: string | null }
export type Conflict = { kind: string; summary: string; a: Side; b: Side }
export type Component = { key: string; label: string; value: number | null; weight: number | null; detail?: string | null; source?: string | null }
export type NextAction = {
  kind: 'propose' | 'set_alert' | 'protect' | 'resolve_conflict' | 'review_add' | 'decide' | 'open_position' | 'none' | string
  label: string
  reason: string
  href?: string | null
  seed?: Record<string, number | null> | null
}
export type SurfaceRow = { surface: string; value: string; source: string | null; joined: boolean }
export type ProspectRow = {
  symbol: string
  company?: string | null
  security_guid?: string | null
  identity_status?: string | null
  lane: LaneId
  stage: string
  why: string
  summary: string
  conviction: number | null
  conviction_rank?: number | null
  conviction_components: Component[]
  conviction_missing: string[]
  conviction_source: string
  conviction_as_of: string | null
  conviction_stale: boolean
  stance: string | null
  whats_missing: string[]
  conflicts: Conflict[]
  next_trigger: { label: string; level_ref: number | null; inside: boolean; distance_pct: number | null; observed_by: string | null }
  next_action: NextAction
  price: number | null
  price_as_of?: string | null
  rsi: number | null
  held: boolean
  trade_ai_state?: string | null
  reentry_state?: string | null
  surfaces: SurfaceRow[]
  evidence_at: string | null
  expires_at: string | null
  stale: boolean
}
export type Lane = { id: LaneId; label: string; hint: string; count: number; cap: number; items: ProspectRow[]; overflow: string[] }
export type ProspectsPayload = {
  ok: boolean
  schema: string
  generated_at: string
  source: 'interim_adapter' | 'cio_prospect' | string
  interim: boolean
  source_label: string
  sources: Record<string, any>
  curation: { one_membership: boolean; caps: Record<string, number>; sort_order: string; expiry: string }
  lanes: Lane[]
  counts: Record<string, number>
}
export type WatchAlert = {
  id: number
  symbol: string
  condition_type: string
  threshold: number | null
  active: boolean
  created_at?: string | null
  last_fired_at?: string | null
  note?: string | null
}

export const LANE_ORDER: LaneId[] = ['actionable', 'forming', 'reentry', 'manage', 'expired']

/** Tone per lane — a design-token tone name, never a colour. */
export const LANE_TONE: Record<LaneId, 'success' | 'warning' | 'ai' | 'info' | 'neutral'> = {
  actionable: 'success', forming: 'warning', reentry: 'ai', manage: 'info', expired: 'neutral',
}

export function unwrap(raw: any): ProspectsPayload | null {
  const d = raw?.data && raw?.data?.lanes ? raw.data : raw
  return d && Array.isArray(d.lanes) ? (d as ProspectsPayload) : null
}

export function laneById(p: ProspectsPayload, id: LaneId): Lane | undefined {
  return p.lanes.find(l => l.id === id)
}

export function allRows(p: ProspectsPayload): ProspectRow[] {
  return p.lanes.flatMap(l => l.items)
}

/** conviction → tone: ≥ 75 success, ≥ 55 warning, else danger; none → neutral. */
export function convictionTone(c: number | null | undefined): 'success' | 'warning' | 'danger' | 'neutral' {
  if (c == null || !Number.isFinite(c)) return 'neutral'
  return c >= 75 ? 'success' : c >= 55 ? 'warning' : 'danger'
}

export function stanceTone(s: string | null | undefined): 'success' | 'warning' | 'danger' | 'info' | 'ai' | 'neutral' {
  const v = String(s || '').toUpperCase()
  if (['ADD', 'BUY', 'BUY_SETUP'].includes(v)) return 'success'
  if (['RE_ENTER', 'RE-ENTER'].includes(v)) return 'ai'
  if (['HOLD'].includes(v)) return 'info'
  if (['WATCH'].includes(v)) return 'warning'
  if (['TRIM', 'EXIT', 'AVOID', 'TRIM_REVIEW', 'EXIT_REVIEW', 'SELL'].includes(v)) return 'danger'
  return 'neutral'
}

export function stanceLabel(s: string | null | undefined): string {
  return s ? String(s).replace(/_/g, '-') : 'no stance'
}

/** Tone of the one next-step button. */
export function stepTone(kind: string): 'success' | 'danger' | 'warning' | 'info' | 'neutral' {
  if (kind === 'propose') return 'success'
  if (kind === 'protect') return 'danger'
  if (kind === 'resolve_conflict') return 'warning'
  if (kind === 'none') return 'neutral'
  return 'info'
}

// ── alerts tied to prospects ─────────────────────────────────────────────────

export type TiedAlerts = {
  armed: WatchAlert[]
  tied: { alert: WatchAlert; symbol: string; lane: LaneId }[]
  orphans: { alert: WatchAlert; why: string }[]
  bySymbol: Record<string, WatchAlert[]>
}

function alertsOf(raw: any): WatchAlert[] {
  const d = raw?.data?.alerts ? raw.data : raw
  const list = Array.isArray(d?.alerts) ? d.alerts : []
  return list.filter((a: any) => a && a.symbol)
}

/** Why an armed alert belongs to no prospect on this page — from the alert's own note, never guessed. */
export function orphanWhy(a: WatchAlert): string {
  const note = String(a.note || '')
  if (/ladder#\d+/i.test(note)) return `trim-ladder alert (${note}) — its symbol is not a prospect on this page`
  if (/defense|hedge/i.test(note)) return `hedge alert (${note}) — not tied to a prospect`
  return note ? `${note} — its symbol is not a prospect on this page` : 'its symbol is not a prospect on this page'
}

/** Every ACTIVE alert either belongs to a prospect (same symbol, any lane) or is listed as an orphan. */
export function tieAlerts(p: ProspectsPayload | null, rawAlerts: any): TiedAlerts {
  const armed = alertsOf(rawAlerts).filter(a => a.active)
  const laneOf = new Map<string, LaneId>()
  if (p) {
    for (const l of p.lanes) {
      for (const r of l.items) laneOf.set(r.symbol.toUpperCase(), l.id)
      for (const s of l.overflow || []) if (!laneOf.has(s.toUpperCase())) laneOf.set(s.toUpperCase(), l.id)
    }
  }
  const tied: TiedAlerts['tied'] = []
  const orphans: TiedAlerts['orphans'] = []
  const bySymbol: Record<string, WatchAlert[]> = {}
  for (const a of armed) {
    const sym = String(a.symbol).toUpperCase()
    const lane = laneOf.get(sym)
    if (lane) {
      tied.push({ alert: a, symbol: sym, lane })
      ;(bySymbol[sym] ||= []).push(a)
    } else {
      orphans.push({ alert: a, why: orphanWhy(a) })
    }
  }
  return { armed, tied, orphans, bySymbol }
}

export function alertLabel(a: WatchAlert): string {
  const t = a.threshold == null ? '—' : String(a.threshold)
  const cond = String(a.condition_type || '')
    .replace('price_cross_below', 'price <')
    .replace('price_cross_above', 'price >')
    .replace('rsi_below', 'RSI <')
    .replace('rsi_above', 'RSI >')
    .replace(/_/g, ' ')
  return `${a.symbol} ${cond} ${t}`
}

export function ageDays(iso: string | null | undefined, now: Date): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? Math.floor((now.getTime() - t) / 86_400_000) : null
}

// ── seeds for the existing operator forms ────────────────────────────────────

/** Seed for the existing WatchlistProposeModal (POST /api/v2/watchlist/:sym/propose). Reference levels only. */
export function proposeSeed(r: ProspectRow) {
  const s = r.next_action.seed || {}
  const entry = s.entry_ref ?? null
  const stop = s.stop_ref ?? null
  const planTarget = s.target_ref ?? null
  const rr = entry != null && stop != null && planTarget != null && entry > stop && planTarget > entry
    ? (planTarget - entry) / (entry - stop) : null
  return { it: { symbol: r.symbol, company: r.company }, entry, stop, planTarget, rr, ladder: null }
}

/** Seed for the existing ReEntryAlertArmModal (POST /api/v2/watch/alerts). */
export function alertIntel(r: ProspectRow) {
  const s = r.next_action.seed || {}
  return {
    price: (s.price ?? r.price) ?? null,
    rsi: (s.rsi ?? r.rsi) ?? null,
    entryLow: s.entry_low_ref ?? null,
    entryHigh: s.entry_high_ref ?? null,
  }
}

// ── header chips and drawers ─────────────────────────────────────────────────

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return '—'
  return t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET'
}

export function conflictCount(p: ProspectsPayload): number {
  return LANE_ORDER.filter(l => l !== 'expired')
    .reduce((n, id) => n + (laneById(p, id)?.items || []).reduce((m, r) => m + r.conflicts.length, 0), 0)
}

export type Chip = { key: string; label: string; value: string; tone: 'success' | 'warning' | 'danger' | 'neutral'; tip: string }

export function headerChips(p: ProspectsPayload): Chip[] {
  const held = p.sources?.held || {}
  const conv = p.sources?.conviction || {}
  const nConf = conflictCount(p)
  return [
    {
      key: 'source', label: 'Source', value: p.interim ? p.source_label : 'CIO prospect record · 1 writer',
      tone: p.interim ? 'warning' : 'success', tip: TOOLTIPS.source(p),
    },
    { key: 'updated', label: 'Updated', value: fmtTime(p.generated_at), tone: 'neutral', tip: TOOLTIPS.updated(conv.as_of) },
    {
      key: 'holdings', label: 'Holdings', value: `${held.source || 'unknown'}${held.stale ? ' · stale' : ''}`,
      tone: held.stale ? 'danger' : 'success', tip: TOOLTIPS.holdings,
    },
    { key: 'conflicts', label: 'Conflicts', value: `${nConf} shown, not hidden`, tone: nConf ? 'warning' : 'neutral', tip: TOOLTIPS.conflicts },
  ]
}

export type Drawer = { id: 'alerts' | 'expired' | 'how'; title: string; summary: string }

export function drawers(p: ProspectsPayload, t: TiedAlerts): Drawer[] {
  const exp = laneById(p, 'expired')
  return [
    {
      id: 'alerts', title: 'Alerts tied to prospects',
      summary: `${t.armed.length} armed → ${t.tied.length} belong to a prospect · ${t.orphans.length} orphaned`,
    },
    { id: 'expired', title: 'Expired and invalidated', summary: `${exp?.count ?? 0} · auto-closed, not counted as live` },
    { id: 'how', title: 'How this page works', summary: p.interim ? 'one record per security · interim adapter' : 'one record, one writer' },
  ]
}

// ── tooltips (accurate to what the server does) ──────────────────────────────

export const TOOLTIPS = {
  source: (p: ProspectsPayload) => p.interim
    ? 'Interim: the CIO prospect store is not live yet. This page builds the same record from today\'s sources — '
      + 'conviction from the CIO opportunity projection, stage and expiry from the Watch decision standards, Trade AI '
      + 'state from the decision projection, held from the broker-synced Watch held reader, and the re-entry desk.'
    : 'Every row is the CIO prospect record: one row per security, written only by the CIO agent.',
  updated: (convAsOf?: string | null) => `When this page's record was composed (cached 60 s). Conviction as of ${fmtTime(convAsOf)}.`,
  holdings: 'Held names come from the one Watch held reader: broker-synced positions_current, falling back to '
    + 'holdings.json with a stated reason if the store is stale or empty.',
  conflicts: 'Two inputs that disagree about the same security (for example the conviction stance vs today\'s desk '
    + 'synthesis). Both values, sources and times are shown; nothing here picks a winner. Expired rows are not counted.',
  lane: {
    actionable: 'Not held, signal active, a proposable rule fired (proposal ready / entry plan ready / re-entry ready) and Trade AI did not fail it.',
    forming: 'Not held and live, but the setup has not confirmed: shown with its distance to the trigger.',
    reentry: 'Sold names: the deterministic re-entry desk says NEAR ENTRY, or the Watch decision placed the name in its re-entry category (near, waiting or blocked).',
    manage: 'Every held name, whatever its signal says — a held name is managed, never entered.',
    expired: 'Not held, and the signal passed its expiry or was invalidated. Closed automatically; it returns when new evidence arrives.',
  } as Record<LaneId, string>,
  conviction: 'CIO conviction 0–100 from its named components (weights shown in the record). Interim source: the CIO opportunity curator.',
  stance: 'The CIO stance: posture and priority only. It never sizes, orders or stops.',
  why: 'Why this security is in this lane, and what evidence is still missing before the next stage.',
  trigger: 'The observable level that moves the stage next — a reference level, never an order.',
  step: 'The one next step for this row. Propose opens your Propose form (you size it; it goes to Proposals for approval); '
    + 'Set alert arms an advisory Watch alert; Protect first opens Open Trades.',
  sameRecord: 'What each surface shows for this security. Interim: only the sources this page reads are joined; the others say "not joined" instead of guessing.',
  classic: 'The previous Watch Intelligence view, kept for one release.',
}

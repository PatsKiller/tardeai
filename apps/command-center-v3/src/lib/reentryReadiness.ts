// Re-entry readiness in ordinary words (FQ-051).
//
// The page printed the writer's own codes as its operator text: the chip read BUY READY, the lane title announced
// "Telegram BUY_READY / ENTRY_NEAR", the summary counted "N buy-ready · M entry-near", and the empty state told the
// operator the runner "writes one per BUY_READY / ENTRY_NEAR symbol". Those are file-format names, not answers to the
// question the reader has ("is this ready to buy, or nearly?").
//
// The mapping is the only place the codes are interpreted. An unlisted state is NOT described as ready and NOT guessed
// into a neighbour's meaning — it says the page does not recognise it, and the code itself stays available as the chip's
// secondary detail.
//
// OBS-B2-4d: the words state what the PACKET recorded, never what is true now. A packet is written at one instant and
// then sits in the store; live 2026-11-14 the visible packets were 25.9–55.2 h old with markets closed, and the chip
// asserted present readiness beside an "alert 55.2h ago" the eye skips. "Recorded" keeps the claim at the packet's own
// clock, which the card prints beside it.
export type Readiness = { words: string; recognises: boolean }

const WORDS: Record<string, string> = {
  BUY_READY: 'Recorded ready to buy',
  ENTRY_NEAR: 'Recorded near the entry zone',
  WATCH: 'Watching',
}

const clean = (v: unknown) => String(v ?? '').replace(/\s+/g, ' ').trim()

export function readinessOf(state: string | null | undefined): Readiness {
  const code = clean(state).toUpperCase()
  if (!code) return { words: 'No state recorded', recognises: false }
  const w = WORDS[code]
  return w ? { words: w, recognises: true } : { words: 'Unrecognised state', recognises: false }
}

/** The chip's words. Never the code itself. */
export function readinessWords(state: string | null | undefined): string {
  return readinessOf(state).words
}

/** The lane's own title: what the thing is, without the file-format names. */
export const LANE_TITLE = 'Entry alerts (buy-ready and entry-near packets)'

/** The one-line summary, in the reader's words rather than the writer's. */
export function readinessSummary(counts: Record<string, number> | null | undefined, rows: number): string {
  const c = counts ?? {}
  const ready = Number(c.BUY_READY ?? 0)
  const near = Number(c.ENTRY_NEAR ?? 0)
  const other = Math.max(0, rows - ready - near)
  const parts = [`${ready} recorded ready to buy`, `${near} recorded near the entry zone`]
  if (other > 0) parts.push(`${other} other`)
  return parts.join(' · ')
}

/** The empty state: what happened, not what the runner writes. */
export function emptyText(maxAgeHours: number | null | undefined): string {
  const h = typeof maxAgeHours === 'number' && Number.isFinite(maxAgeHours) ? `${maxAgeHours}h` : 'the window'
  return `No entry alert in the last ${h}. The entry runner saves one when a symbol becomes ready to buy or nears its entry zone.`
}

// ---------------------------------------------------------------------------------------------------------------
// OBS-B2-4d (lead 11:24 ET; DR-R02): one page, four counts, four different populations. Live 2026-11-14 the
// re-entry ledger held 93 symbols, the resistance cache 95, and the entry-alert index 36 current packets plus 275
// older ones. Each printed as a bare number, so 36 packets could be read as "36 symbols tracked". Every count below
// carries the population it counts, the unit it is counted in, the rule that selected it and the clock it was read
// at. A count the server did not send is stated as not sent — never filled with 0.
// ---------------------------------------------------------------------------------------------------------------

const plural = (n: number, one: string): string => `${n} ${n === 1 ? one : `${one}s`}`

/** An ISO instant is called UTC only when the string says UTC. A +05:00 string is not labelled UTC. */
export function clockUtc(iso: unknown): string | null {
  const s = clean(iso)
  const m = s.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/)
  if (!m) return null
  // A stamp with no offset at all served no offset: it is not labelled UTC and not said to have one (OBS-B2-4d F3).
  if (!/(?:Z|[+-]00:00)$/.test(s) && !/[+-]\d{2}:\d{2}$/.test(s)) return `${m[1]} ${m[2]} (offset not published)`
  return /(?:Z|[+-]00:00)$/.test(s) ? `${m[1]} ${m[2]} UTC` : `${m[1]} ${m[2]} (offset as served)`
}

/** Distinct symbols in a packet list: the index serves one row per (symbol, account) (FQ-096). */
export function distinctSymbols(rows: Array<{ symbol?: string | null }> | null | undefined): number {
  if (!Array.isArray(rows)) return 0
  const seen = new Set<string>()
  for (const row of rows) {
    const s = clean(row?.symbol).toUpperCase()
    if (s) seen.add(s)
  }
  return seen.size
}

export type PacketCounts = {
  count?: number | null
  rows?: Array<{ symbol?: string | null }> | null
  stale?: unknown[] | null
  max_age_h?: number | null
  max_age_basis?: string | null
}

/** The entry-alert lane's two populations, in packets and in symbols, with the window and its basis. */
export function packetPopulations(p: PacketCounts): string {
  const symbols = Array.isArray(p.rows) ? distinctSymbols(p.rows) : null
  const current = typeof p.count === 'number' && Number.isFinite(p.count)
    ? `${plural(p.count, 'current packet')}${symbols != null ? ` · ${plural(symbols, 'symbol')}` : ' · symbol count not sent'}`
    : 'current packet count not sent'
  const window = typeof p.max_age_h === 'number' && Number.isFinite(p.max_age_h)
    ? `${p.max_age_h} h ${p.max_age_basis === 'trading_days' ? 'trading window (weekends and exchange holidays not counted)' : 'window'}`
    : 'the window'
  const older = !Array.isArray(p.stale)
    ? 'older packet count not sent'
    : p.stale.length === 0
      ? `none older than the ${window}`
      : `${plural(p.stale.length, 'packet')} older than the ${window}, kept in history`
  return `${current} · ${older}`
}

export type ResistanceCounts = {
  symbol_count?: number | null
  symbols?: Record<string, unknown> | null
  generated_at?: string | null
  matching?: number | null
}

/** The resistance cache's universe: the rule is the producer's (reentry_resistance._symbols), stated as it is. */
export function resistancePopulation(r: ResistanceCounts): string {
  const n = typeof r.symbol_count === 'number' && Number.isFinite(r.symbol_count)
    ? r.symbol_count
    : r.symbols && typeof r.symbols === 'object' ? Object.keys(r.symbols).length : null
  const size = n == null ? 'resistance universe size not published' : `${plural(n, 'symbol')} in the resistance universe (mandate, rotation and symbols sold in the last 365 days)`
  const clock = clockUtc(r.generated_at)
  const when = clock ? `generated ${clock}` : 'generation time not published'
  const match = typeof r.matching === 'number' && Number.isFinite(r.matching) ? ` · ${r.matching} matching the filter` : ''
  return `${size} · ${when}${match}`
}

export type LedgerCounts = { symbol_count?: number | null; generated_at?: string | null }

/** The re-entry evidence's rows: one row per exited symbol, a different universe from the two above.
 *  OBS-B2-4d F1: the clock must be the EVIDENCE's. The decision desk stamps ``computed_at`` per request, so dating
 *  a 23.9 h-old population with it printed "computed <now>" over yesterday's data — the same false freshness this
 *  item removed. The exit cache is generated, not computed at read: say generated, and take its ``generated_at``. */
export function ledgerPopulation(l: LedgerCounts): string {
  const size = typeof l.symbol_count === 'number' && Number.isFinite(l.symbol_count)
    ? `${plural(l.symbol_count, 'symbol')} in the re-entry ledger`
    : 're-entry ledger size not published'
  const clock = clockUtc(l.generated_at)
  return `${size}${clock ? ` · generated ${clock}` : ' · generation time not published'}`
}

export type PopulationInput = { ledger?: LedgerCounts; resistance?: ResistanceCounts; packets?: PacketCounts }

/** One sentence naming every population a surface actually holds, and saying they do not add up to anything.
 *  A surface that holds fewer than the four names only those — it never prints "0" for one it did not read. */
export function populationLegend(i: PopulationInput): string {
  const parts: string[] = []
  if (i.ledger !== undefined) parts.push(ledgerPopulation(i.ledger))
  if (i.resistance !== undefined) parts.push(resistancePopulation(i.resistance))
  if (i.packets !== undefined) parts.push(packetPopulations(i.packets))
  if (!parts.length) return 'No population count is available: none was sent.'
  return `Counts cover different populations — ${parts.join(' · ')}. One symbol can appear in more than one.`
}

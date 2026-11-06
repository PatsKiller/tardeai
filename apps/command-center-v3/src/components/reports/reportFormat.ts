// Reports redesign v001 (operator-approved 2026-11-06) — the READ-SIDE formatting layer.
//
// Stored report text is never rewritten. This module turns a markdown/Telegram body into
// (a) sections for the reader (chips + collapsible cards) and (b) typed inline tokens so the
// renderer can apply the operator's ask, verbatim: "the Marvel ticker in bold, the -46% in red,
// and what we really need to look at highlighted or italicized".
//
//   ticker   → bold                      (MRVL, **MRVL**, BRK.B)
//   pct      → red when negative, green when positive (sign required; 56-72% is a range, not -72%)
//   arrow    → ↑27 green, ↓1 red         (estimate-revision counts)
//   key      → highlighted: a bold lead sentence ("**This is a valuation selloff…**")
//   look     → italic: "what to look at" text (⚠ flags, "check …", "Verdict:", "watch …")
//
// Pure functions only (no React) so node tests cover them: reportFormat.test.ts.

export type Tone = 'neg' | 'pos' | 'flat'
export type Tok =
  | { k: 'text'; v: string }
  | { k: 'ticker'; v: string }
  | { k: 'pct'; v: string; tone: Tone }
  | { k: 'arrow'; v: string; tone: Tone }
  | { k: 'bold'; v: Tok[] }
  | { k: 'key'; v: Tok[] }
  | { k: 'look'; v: Tok[] }
  | { k: 'code'; v: string }
  | { k: 'url'; v: string }
  | { k: 'route'; v: string }

// Upper-case words that are NOT tickers in report prose. Kept deliberately broad: a missed bold
// on a real ticker is cosmetic; a bolded "CPI" or "RED" reads as noise.
export const NOT_TICKER = new Set([
  'A', 'I', 'AM', 'PM', 'ET', 'EST', 'EDT', 'UTC', 'US', 'USA', 'USD', 'EU', 'UK', 'AI', 'ML', 'IT', 'TV', 'OK', 'NO', 'NOT',
  'AND', 'OR', 'THE', 'FOR', 'TO', 'OF', 'IN', 'ON', 'AT', 'BY', 'IS', 'BE', 'IF', 'AS', 'UP', 'ALL', 'ANY', 'NEW', 'NOW',
  'STOP', 'STOPS', 'RISK', 'HEAT', 'NEED', 'ITEM', 'ETF', 'ETFS', 'IRA', 'EOD', 'RSI', 'ATR', 'PNL', 'YTD', 'MTD', 'QTD',
  'CIO', 'NAV', 'CEF', 'SELL', 'BUY', 'HOLD', 'ADD', 'TRIM', 'GO', 'WAIT', 'RED', 'GREEN', 'AMBER', 'ORANGE', 'YELLOW',
  'CPI', 'PPI', 'PCE', 'GDP', 'FOMC', 'FED', 'EPS', 'PE', 'FY', 'FWD', 'TTM', 'YOY', 'QOQ', 'MOM', 'DB', 'API', 'LLM',
  'OPEN', 'CLOSE', 'HIGH', 'LOW', 'NOTE', 'DATA', 'GAPS', 'KEY', 'TOP', 'NEXT', 'LAST', 'WEEK', 'DAY', 'DAYS', 'MON',
  'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV',
  'DEC', 'Q1', 'Q2', 'Q3', 'Q4', 'H1', 'H2', 'SPDR', 'IPO', 'SEC', 'CEO', 'CFO', 'P1', 'P2', 'P3', 'N', 'PR', 'PRS',
  'DIP', 'SMA', 'EMA', 'MACD', 'VWAP', 'OI', 'IV', 'DTE', 'ATH', 'HWM', 'DCA', 'ROTH', 'SSDI', 'TODO', 'FYI', 'ASAP',
  'WARN', 'INFO', 'ERROR', 'FAIL', 'PASS', 'LIVE', 'DRY', 'RUN', 'TIER', 'SHOCK', 'VERDICT', 'URGENT', 'CRITICAL',
  'CONCENTRATED_TECH', 'NYSE', 'NASDAQ', 'OTC', 'ADR', 'REIT', 'BDC', 'MLP', 'LLC', 'INC', 'CORP', 'LTD', 'PLC',
])

const TICKER_RX = /^[A-Z]{1,5}(?:\.[A-Z])?$/
export function isTicker(w: string, known?: Set<string>): boolean {
  if (known && known.has(w)) return true
  if (!TICKER_RX.test(w) || w.replace('.', '').length < 2) return false
  return !NOT_TICKER.has(w)
}

// "what to look at" cues — a sentence carrying one of these is rendered italic (look).
export const LOOK_RX = /(⚠|\bcheck (?:before|again|this|it|that|the)\b|\bverdict:|\bwatch\b|\bwhat to watch\b|\brefresh\b|\bbefore (?:adding|treating|buying)\b|\bdon'?t (?:anchor|panic|chase)\b|\bkey (?:level|risk|question)\b|\blook at\b|\bnot a recommendation\b)/i

const pctTone = (s: string): Tone => (/^[-−]/.test(s) ? 'neg' : /^\+/.test(s) ? 'pos' : 'flat')

// Leaf tokenizer: tickers, signed percents, ↑/↓ counts, `code`, urls, /v3 routes.
// Signed % must not follow a digit (so "56-72%" stays a range) and must start a token.
const LEAF_RX = /(`[^`\n]+`|https?:\/\/[^\s)]+|\/v[23]\/[a-z0-9-]+|(?<![\w.%])[+\-−]\d+(?:\.\d+)?%|[↑↓]\d+|\b[A-Z]{1,5}(?:\.[A-Z])?\b)/g

export function leafTokens(text: string, known?: Set<string>): Tok[] {
  const out: Tok[] = []
  let last = 0
  const push = (t: Tok) => {
    const prev = out[out.length - 1]
    if (t.k === 'text' && prev && prev.k === 'text') prev.v += t.v
    else out.push(t)
  }
  for (const m of text.matchAll(LEAF_RX)) {
    const tok = m[0], i = m.index ?? 0
    if (i > last) push({ k: 'text', v: text.slice(last, i) })
    if (tok.startsWith('`')) push({ k: 'code', v: tok.slice(1, -1) })
    else if (/^https?:/.test(tok)) push({ k: 'url', v: tok })
    else if (/^\/v[23]\//.test(tok)) push({ k: 'route', v: tok })
    else if (/%$/.test(tok)) push({ k: 'pct', v: tok, tone: pctTone(tok) })
    else if (/^[↑↓]/.test(tok)) push({ k: 'arrow', v: tok, tone: tok.startsWith('↑') ? 'pos' : 'neg' })
    else if (isTicker(tok, known)) push({ k: 'ticker', v: tok })
    else push({ k: 'text', v: tok })
    last = i + tok.length
  }
  if (last < text.length) push({ k: 'text', v: text.slice(last) })
  return out
}

const wordCount = (s: string) => s.trim().split(/\s+/).filter(Boolean).length

// Split plain text into sentences, marking the "look" ones italic. Keeps every character.
function lookSplit(text: string, known?: Set<string>): Tok[] {
  // a ⚠ flag: everything from ⚠ to the end of the line is what to look at
  const warn = text.indexOf('⚠')
  if (warn >= 0) {
    const head = text.slice(0, warn)
    return [...lookSplit(head, known), { k: 'look', v: leafTokens(text.slice(warn), known) }]
  }
  if (!LOOK_RX.test(text)) return leafTokens(text, known)
  // split after sentence punctuation that is followed by whitespace ("8.8%" is not a boundary);
  // the capture group keeps the separators so no character is dropped
  const parts = text.split(/((?<=[.!?;])\s+)/)
  const out: Tok[] = []
  for (const p of parts) {
    if (!p) continue
    if (!/\S/.test(p)) { out.push({ k: 'text', v: p }); continue }
    if (LOOK_RX.test(p) && wordCount(p) >= 3) {
      const lead = p.match(/^\s*/)?.[0] || ''
      if (lead) out.push({ k: 'text', v: lead })
      out.push({ k: 'look', v: leafTokens(p.slice(lead.length), known) })
    } else out.push(...leafTokens(p, known))
  }
  return out
}

/** Inline tokens for one line of report text. `known` = symbols the API extracted for this item. */
export function tokenize(text: string, known?: Set<string>): Tok[] {
  const out: Tok[] = []
  const rx = /\*\*([^*\n]+)\*\*|(?<![\w*])\*([^*\n]+)\*(?![\w*])/g
  let last = 0
  for (const m of text.matchAll(rx)) {
    const i = m.index ?? 0
    if (i > last) out.push(...lookSplit(text.slice(last, i), known))
    const inner = (m[1] ?? m[2] ?? '').trim()
    if (isTicker(inner, known) || /^[A-Z]{1,5}(?:\.[A-Z])?$/.test(inner)) out.push({ k: 'ticker', v: inner })
    // a bold lead sentence / claim (≥ 4 words) is the "highlight what matters" case
    else if (wordCount(inner) >= 4) out.push({ k: 'key', v: leafTokens(inner, known) })
    else out.push({ k: 'bold', v: leafTokens(inner, known) })
    last = i + m[0].length
  }
  if (last < text.length) out.push(...lookSplit(text.slice(last), known))
  return out
}

/** Flatten tokens back to plain text (tests + summaries). */
export function plain(toks: Tok[]): string {
  return toks.map(t => (Array.isArray(t.v) ? plain(t.v) : t.v)).join('')
}

// ── sections ───────────────────────────────────────────────────────────────────────────────────
export interface ReportSection { id: string; title: string; chip: string; summary: string; body: string; bullets: number }
export interface ParsedReport { title: string; intro: string; sections: ReportSection[] }

const stripMd = (s: string) => s.replace(/\*\*|`/g, '').replace(/^\s*[-•▪◦·*]\s+/, '').replace(/\s+/g, ' ').trim()

/** A short chip label: drop "1. ", parentheticals and trailing qualifiers. */
export function chipLabel(title: string): string {
  let t = title.replace(/^\s*\d+[.)]\s*/, '').replace(/\s*\([^)]*\)\s*/g, ' ').trim()
  t = t.replace(/^known gaps.*$/i, 'Gaps').replace(/\s+—.*$/, '').replace(/:\s.*$/, '')
  if (t.length > 26) t = t.slice(0, 24).replace(/\s+\S*$/, '') + '…'
  return t || title.slice(0, 24)
}

/** One-line summary for a section header: its first bold lead, else its first line. */
export function sectionSummary(body: string): string {
  const lines = body.split('\n').map(l => l.trim()).filter(Boolean)
  if (!lines.length) return ''
  const bold = lines[0].match(/\*\*([^*]+)\*\*/)
  let s = stripMd(bold && wordCount(bold[1]) >= 3 ? bold[1] : lines[0])
  s = s.replace(/\.$/, '')
  return s.length > 90 ? s.slice(0, 88).replace(/\s+\S*$/, '') + '…' : s
}

const slug = (s: string, i: number) => `s${i}-` + s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 24)

/** Split on markdown "## " (and "# " after the title). Bodies with no headers become one section. */
export function parseReport(md: string, fallbackTitle = ''): ParsedReport {
  const lines = (md || '').split('\n')
  let title = fallbackTitle
  const intro: string[] = []
  const sections: ReportSection[] = []
  let cur: { title: string; lines: string[] } | null = null
  let sawTitle = false
  const close = () => {
    if (!cur) return
    const body = cur.lines.join('\n').replace(/^\n+|\n+$/g, '')
    if (body.trim() || cur.title) {
      const i = sections.length
      sections.push({ id: slug(cur.title, i), title: cur.title, chip: chipLabel(cur.title), summary: sectionSummary(body), body,
        bullets: body.split('\n').filter(l => /^\s*[-•▪◦·]\s+/.test(l)).length })
    }
    cur = null
  }
  for (const line of lines) {
    const h = line.match(/^(#{1,3})\s+(.*)$/)
    if (h) {
      const text = h[2].trim()
      if (h[1].length === 1 && !sawTitle && !sections.length && !cur) { title = text; sawTitle = true; continue }
      close()
      cur = { title: text.replace(/\*\*/g, ''), lines: [] }
      continue
    }
    if (cur) cur.lines.push(line)
    else intro.push(line)
  }
  close()
  return { title, intro: intro.join('\n').trim(), sections }
}

// ── as-of + gaps (read from the text until the generator writes meta.as_of / meta.gaps) ────────────
export interface AsOf { text: string | null; gaps: string[]; gapsSection: string | null }

export function extractAsOf(parsed: ParsedReport, meta?: any): AsOf {
  const gapSec = parsed.sections.find(s => /\bgaps?\b/i.test(s.title))
  let gaps: string[] = gapSec ? gapSec.body.split('\n').filter(l => /^\s*[-•▪◦·]\s+/.test(l)).map(stripMd) : []
  if (Array.isArray(meta?.gaps)) gaps = meta.gaps.map((g: any) => (typeof g === 'string' ? g : g?.text || '')).filter(Boolean)
  let text: string | null = null
  if (meta?.as_of && typeof meta.as_of === 'object') {
    text = Object.entries(meta.as_of).map(([k, v]) => `${k} = ${v}`).join(' · ')
  } else {
    const m = parsed.intro.match(/\*\*\s*data as[- ]of:?\s*\*\*:?\s*([^\n]+)/i) || parsed.intro.match(/data as[- ]of:?\s*([^\n]+)/i)
    if (m) text = stripMd(m[1])
  }
  return { text, gaps, gapsSection: gapSec?.id ?? null }
}

// ── market report kind + group staleness ───────────────────────────────────────────────────────
export const MARKET_TITLE_RX = /\b(selloff|sell-off|market[ -]move|market report|deep dive \+ monday plan)\b/i
export const isMarketReport = (it: { category?: string; type?: string; title?: string } | null | undefined): boolean =>
  !!it && (it.category === 'market_reports' || /^market_/.test(it.type || '') || MARKET_TITLE_RX.test(it.title || ''))

/** Expected cadence (days) per category → age label + tone. */
export const CADENCE_DAYS: Record<string, number> = {
  morning_briefs: 1, digests: 1, recovery: 1, trade_ai_live: 1, hermes_alerts: 1, alerts: 1, advisories: 1, system: 1,
  weekly_reviews: 7, portfolio_briefs: 7, critique: 7, learning: 7, research: 7, eod_trades: 1, incubator: 7,
  monthly: 31, market_reports: 7, dividends: 31, regime: 31, paper: 7, health_agent: 7, escalations: 7,
}
export function ageLabel(lastAt: string | null | undefined, cadenceDays: number, now = Date.now()): { text: string; tone: 'ok' | 'warn' | 'bad' | 'none' } {
  if (!lastAt) return { text: 'never', tone: 'none' }
  const days = Math.floor((now - new Date(lastAt).getTime()) / 86_400_000)
  if (!Number.isFinite(days)) return { text: '—', tone: 'none' }
  if (days >= Math.max(14, cadenceDays * 3)) return { text: `stopped ${days}d`, tone: 'bad' }
  if (days > cadenceDays + 1) return { text: `${days}d old`, tone: 'warn' }
  return { text: days <= 0 ? 'today' : `${days}d ago`, tone: 'ok' }
}

/** Search box syntax: sector:X / trend:Y are client-side filters; the rest goes to the server. */
export function splitQuery(q: string): { text: string; sector?: string; trend?: string } {
  const sector = q.match(/sector:(\S+)/i)?.[1]
  const trend = q.match(/trend:(\S+)/i)?.[1]
  return { text: q.replace(/(sector|trend):\S+/gi, '').replace(/\s+/g, ' ').trim(), sector, trend }
}

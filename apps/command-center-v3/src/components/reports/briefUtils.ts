export const SUPER_TABS: { key: string; label: string; categories: string[] }[] = [
  { key: 'briefs', label: 'Briefs & Digests', categories: ['morning_briefs', 'digests', 'portfolio_briefs'] },
  { key: 'cadence', label: 'Cadence', categories: ['weekly_reviews', 'monthly', 'incubator'] },
  { key: 'intel', label: 'Intel & Trades', categories: ['research', 'eod_trades', 'critique', 'learning'] },
  { key: 'ops', label: 'Ops & Risk', categories: ['alerts', 'advisories', 'recovery', 'dividends', 'regime', 'paper', 'system'] },
]

export interface BriefSection { id: string; label: string; body: string }

const SECTION_RX = [
  { id: 'exec', label: 'Executive Summary', rx: /executive summary/i },
  { id: 'risk', label: 'Immediate Risk', rx: /immediate risk/i },
  { id: 'steph', label: 'Steph Review', rx: /steph review/i },
  { id: 'recovery', label: 'Recovery Watch', rx: /recovery watch/i },
  { id: 'rotation', label: 'Rotation / Regime', rx: /rotation|regime|sector/i },
  { id: 'next', label: 'Ranked Next Actions', rx: /ranked next action|action items|next actions/i },
  { id: 'intel', label: 'Intelligence', rx: /intelligence|news|catalyst/i },
]

export function parseBriefSections(text: string): BriefSection[] {
  if (!text?.trim()) return []
  const lines = text.split('\n')
  const sections: BriefSection[] = []
  let cur: BriefSection | null = null

  const headerOf = (line: string): BriefSection | null => {
    const t = line.trim()
    const md = t.match(/^(#{1,4})\s+(.*)$/)
    const tg = /^\*[^*]+\*$/.test(t) || /^[A-Z][A-Z \/&0-9]{3,}:?$/.test(t)
    if (!md && !tg) return null
    const label = (md ? md[2] : t).replace(/^\*|\*$/g, '').replace(/^#+\s*/, '').trim()
    const hit = SECTION_RX.find(s => s.rx.test(label))
    if (!hit) return { id: `sec-${sections.length}`, label, body: '' }
    return { id: hit.id, label: hit.label, body: '' }
  }

  for (const line of lines) {
    const h = headerOf(line)
    if (h) {
      if (cur?.body.trim()) sections.push(cur)
      cur = { ...h, body: '' }
      continue
    }
    if (cur) cur.body += (cur.body ? '\n' : '') + line
  }
  if (cur?.body.trim()) sections.push(cur)
  return sections.filter(s => s.body.trim().length > 20).slice(0, 8)
}

export function executiveSummaryText(text: string): string {
  const secs = parseBriefSections(text)
  const exec = secs.find(s => s.id === 'exec')
  if (exec) return exec.body.trim().slice(0, 1200)
  const first = text.replace(/\s+/g, ' ').trim()
  const m = first.match(/^.{80,500}?[.!?](\s|$)/)
  return (m ? m[0] : first.slice(0, 400)).trim()
}

export function rankedActionLines(text: string): string[] {
  const out: string[] = []
  const rx = /ranked next action/i
  let inBlock = false
  for (const line of (text || '').split('\n')) {
    const t = line.trim()
    if (rx.test(t)) { inBlock = true; continue }
    if (inBlock && (/^#{1,4}\s+|^\*[^*]+\*$/.test(t) || /^[A-Z][A-Z \/&0-9]{3,}:?$/.test(t))) break
    if (inBlock && (/^[•\-▪◦·*\d]+[.)]?\s+/.test(t) || /^[A-Z]{2,5}:/.test(t))) {
      const clean = t.replace(/^[•\-▪◦·*\d]+[.)]?\s+/, '').trim()
      if (clean.length > 8) out.push(clean)
    }
  }
  return out.slice(0, 12)
}
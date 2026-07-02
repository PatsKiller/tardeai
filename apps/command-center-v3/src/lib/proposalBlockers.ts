export type BlockerCategory = 'strategy' | 'trade_plan' | 'oversight' | 'sizing' | 'thesis' | 'other'

export function categorizeBlocker(msg: string): BlockerCategory {
  const m = String(msg || '').toLowerCase()
  if (m.includes('sleeve') || m.includes('yaml')) return 'strategy'
  if (m.includes('trade plan') || m.includes('gambling')) return 'trade_plan'
  if (m.includes('oversight') || m.includes('agent') || m.includes('block')) return 'oversight'
  if (m.includes('cap') || m.includes('shares') || m.includes('risk') || m.includes('investment')) return 'sizing'
  if (m.includes('r:r') || m.includes('thesis') || m.includes('zone') || m.includes('drift')) return 'thesis'
  return 'other'
}

const CAT_LABEL: Record<BlockerCategory, string> = {
  strategy: 'Strategy',
  trade_plan: 'Trade plan',
  oversight: 'Oversight',
  sizing: 'Sizing',
  thesis: 'Thesis',
  other: 'Other',
}

export function dedupeBlockers(messages: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of messages) {
    const m = String(raw || '').trim()
    if (!m) continue
    const key = m.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(m)
  }
  return out
}

export function groupBlockers(messages: string[]): { category: BlockerCategory; label: string; items: string[] }[] {
  const deduped = dedupeBlockers(messages)
  const buckets = new Map<BlockerCategory, string[]>()
  for (const m of deduped) {
    const cat = categorizeBlocker(m)
    if (!buckets.has(cat)) buckets.set(cat, [])
    buckets.get(cat)!.push(m)
  }
  const order: BlockerCategory[] = ['strategy', 'trade_plan', 'oversight', 'sizing', 'thesis', 'other']
  return order
    .filter(c => buckets.has(c))
    .map(c => ({ category: c, label: CAT_LABEL[c], items: buckets.get(c)! }))
}

export function collectCardBlockers(p: any, evalData: any, ov: any, opts?: { operatorRoute?: boolean }): string[] {
  const operatorRoute = Boolean(opts?.operatorRoute)
  const sizingViolations: string[] = evalData?.violations || p.broker_sizing?.violations || p.evaluation?.violations || []
  const hardGateViolations = sizingViolations.filter(
    (v: string) => !/exceed max|exceeds cap|SIZE_TOO_SMALL|policy cap|Operator/i.test(v),
  )
  const msgs = [
    ...hardGateViolations,
    ...(!operatorRoute ? (ov?.violations || []) : []),
    ...(!operatorRoute ? sizingViolations.filter((v: string) => !(ov?.violations || []).includes(v)) : []),
  ]
  return dedupeBlockers(msgs)
}
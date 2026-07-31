import { useMemo } from 'react'
import { useApi } from './useApi'
import { intelligenceItemId as stableId } from '../lib/intelligenceItemId'
import type { IntelItem } from '../lib/intelBrief'

function first(...xs: any[]) { return xs.find(x => x !== undefined && x !== null && x !== '') }

function ago(v: any): { label: string; hours: number | null } {
  if (!v) return { label: 'unknown', hours: null }
  const t = new Date(v).getTime()
  if (!Number.isFinite(t)) return { label: 'unknown', hours: null }
  const h = Math.max(0, (Date.now() - t) / 36e5)
  if (h < 1) return { label: 'just now', hours: h }
  if (h < 48) return { label: `${Math.round(h)}h ago`, hours: h }
  return { label: `${Math.round(h / 24)}d ago`, hours: h }
}

function confidenceFrom(x: any, fallback = 0.65) {
  const v = first(x.confidence, x.research_confidence, x.eval_confidence, x.score != null ? Number(x.score) / 100 : null)
  const y = Number(v)
  if (!Number.isFinite(y)) return fallback
  return y > 1 ? Math.min(1, y / 100) : Math.min(1, Math.max(0, y))
}

function severityFrom(x: any): IntelItem['severity'] {
  const s = String(first(x.severity, x.priority, x.operator_priority, x.advisory_flag, x.status, x.decision, x.recommendation, '')).toLowerCase()
  if (/critical|urgent|triggered|blocked|stop|risk|avoid|sell|unprotected|failed/.test(s)) return 'critical'
  if (/caution|stale|warn|wait|hold|pending|review|neutral|partial/.test(s)) return 'warning'
  if (/positive|buy|go|bullish|fresh|protected|completed|ok|pass/.test(s)) return 'positive'
  return 'info'
}

function priorityRank(it: IntelItem) {
  if (it.type === 'risk' || it.type === 'telegram/action') return 0
  if (it.type === 'open-trade' && it.severity === 'critical') return 1
  if (it.type === 'external-lm-report') return 2
  if (it.type === 'risk' || it.type === 'telegram/action' || it.type === 'open-trade') return 3
  if (it.severity === 'critical') return 4
  if (it.severity === 'warning') return 5
  return 6
}

function sortByPriority(a: IntelItem, b: IntelItem) {
  return priorityRank(a) - priorityRank(b) || (1 - a.confidence) - (1 - b.confidence) || b.confidence - a.confidence
}

export function isActNowItem(it: IntelItem) {
  if (it.type === 'risk' || it.type === 'telegram/action' || it.type === 'open-trade') return true
  if (it.type === 'external-lm-report' && it.severity === 'critical') return true
  return it.confidence >= 0.55 && !!it.action && it.severity !== 'info'
}

export function useIntelCommandItems() {
  const { data: command } = useApi<any>('/api/v2/command', 60_000)
  const { data: brief } = useApi<any>('/api/v2/morning-brief', 300_000)
  const { data: reportIntel } = useApi<any>('/api/v2/hermes/subject-intel-map?type=report', 300_000)
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: openTrades } = useApi<any>('/api/v2/open-trades/intelligence', 60_000)
  const { data: inference } = useApi<any>('/api/v2/inference/latest', 120_000)
  const { data: ensembleFeed } = useApi<any>('/api/v2/inference/ensemble?limit=200', 120_000)

  const cmd = command?.data ?? command ?? {}

  const ensembleById = useMemo(() => {
    const m = new Map<string, IntelItem['ensemble'] extends infer E ? E : never>()
    const rows: any[] = Array.isArray(ensembleFeed) ? ensembleFeed : (ensembleFeed?.data ?? [])
    rows.filter((r: any) => r.target_type === 'signal').forEach((r: any) => {
      if (!r.target_id || m.has(r.target_id)) return
      const votes = typeof r.votes === 'string' ? JSON.parse(r.votes || '[]') : (r.votes ?? [])
      const lanes = typeof r.lanes_used === 'string' ? JSON.parse(r.lanes_used || '[]') : (r.lanes_used ?? votes.map((v: any) => v.lane))
      m.set(r.target_id, { score: Number(r.final_score) || 0, decision: r.final_decision === 'approve' ? 'approve' : 'block', consensus: !!r.consensus_reached, lanes })
    })
    return m
  }, [ensembleFeed])

  const items = useMemo<IntelItem[]>(() => {
    const out: IntelItem[] = []
    const add = (x: Partial<IntelItem> & { raw?: any }) => {
      if (!x.title) return
      const a = ago((x.raw as any)?.at ?? (x.raw as any)?.updated_at ?? (x.raw as any)?.created_at ?? (x.raw as any)?.generated_at)
      const type = x.type || 'intelligence'
      const source = x.source || 'unknown'
      const id = stableId(type, source, x.symbol, String(x.title))
      out.push({
        id, source, type, symbol: x.symbol, title: String(x.title), summary: x.summary,
        severity: x.severity || severityFrom(x.raw ?? x), confidence: x.confidence ?? confidenceFrom(x.raw ?? x),
        freshnessH: x.freshnessH ?? a.hours, model: x.model, lane: x.lane, action: x.action,
        raw: x.raw ?? x, ensemble: ensembleById.get(id),
      })
    }
    const priceBy: Record<string, number> = {}
    ;(risk?.positions ?? []).forEach((p: any) => { const c = Number(p.current_price); if (p.symbol && Number.isFinite(c)) priceBy[String(p.symbol).toUpperCase()] = c })
    const seenStop = new Set<string>()
    ;(risk?.positions ?? []).forEach((p: any) => { if (p.symbol && (p.triggered || p.triggered_stop)) seenStop.add(String(p.symbol).toUpperCase()) })
    ;(risk?.positions ?? []).filter((p: any) => p.triggered || p.near_stop || p.unprotected || p.triggered_stop).slice(0, 25).forEach((p: any) => {
      const sym = String(p.symbol ?? '').toUpperCase()
      const cp = Number(p.current_price), sp = Number(p.stop_price ?? p.stop)
      const ok = Number.isFinite(cp) && Number.isFinite(sp) && sp > 0
      const breach = ok ? Math.abs(cp - sp) / sp : 0
      const conf = ok ? Math.min(.96, .60 + Math.min(breach * 3, .36)) : .45
      add({ source: '/api/v2/risk', type: 'risk', symbol: p.symbol, title: `${p.symbol} risk/stop review`, summary: `${p.account ?? ''} stop ${p.stop_price ?? p.stop ?? '—'} · current ${p.current_price ?? '—'}`, severity: 'critical', confidence: conf, raw: p, action: 'verify stop / protection' })
    })
    ;(cmd.triggered_detail ?? []).slice(0, 20).forEach((s: any) => {
      const sym = String(s.symbol ?? '').toUpperCase()
      if (sym && seenStop.has(sym)) return
      add({ source: '/api/v2/command', type: 'telegram/action', symbol: s.symbol, title: `${s.symbol} triggered stop from command feed`, summary: `Stop ${s.stop_price ?? s.stop ?? '—'}`, severity: 'critical', confidence: .7, raw: s, action: 'confirm broker state' })
    })
    const lmGroups: Record<string, { e: any; key: string; ts: number }> = {}
    Object.entries(reportIntel?.map ?? {}).forEach(([key, arr]: any) => (arr ?? []).forEach((e: any) => {
      const subj = String(key).replace(/[_:-]?\d{4}-\d{2}-\d{2}.*$/, '').trim() || String(key)
      const ts = Date.parse(e.at ?? e.created_at ?? '') || 0
      const cur = lmGroups[subj]
      if (!cur || ts > cur.ts) lmGroups[subj] = { e, key, ts }
    }))
    Object.values(lmGroups).slice(0, 5).forEach(({ e, key }) => add({
      source: '/api/v2/hermes/subject-intel-map?type=report', type: 'external-lm-report',
      title: e.recommendation ?? key, summary: e.dissent ?? '', model: e.model, lane: e.lane,
      confidence: confidenceFrom(e, .7), raw: { ...e, key }, action: 'review report', severity: severityFrom(e),
    }))
    ;(openTrades?.positions ?? []).filter((p: any) => ['critical', 'high'].includes(String(p.operator_priority ?? '').toLowerCase())).slice(0, 15).forEach((p: any) => {
      add({ source: '/api/v2/open-trades/intelligence', type: 'open-trade', symbol: p.symbol, title: `${p.symbol} ${p.operator_decision ?? 'position review'}`, summary: p.decision_reason ?? p.strategy_rationale, severity: severityFrom(p), confidence: .75, raw: p, action: p.primary_next_review ?? 'review position' })
    })
    ;(brief?.action_items ?? []).slice(0, 3).forEach((a: any, i: number) => add({
      source: '/api/v2/morning-brief', type: 'brief-action',
      title: typeof a === 'string' ? a : (a.message ?? a.title ?? `Action ${i + 1}`),
      summary: typeof a === 'object' ? a.reason ?? '' : '', raw: a, action: 'review',
    }))
    return out.sort(sortByPriority)
  }, [risk, cmd, brief, reportIntel, openTrades, ensembleById])

  const actNowItems = useMemo(() => items.filter(isActNowItem), [items])
  const monitorItems = useMemo(() => items.filter(it => !isActNowItem(it)), [items])

  return { items, actNowItems, monitorItems, inference, loading: !risk && !command }
}

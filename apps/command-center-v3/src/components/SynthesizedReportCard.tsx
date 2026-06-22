// SynthesizedReportCard — professional trade-desk report card (v3 stack: inline styles + CSS vars).
// In-stack translation of the requested design (no Tailwind/shadcn/lucide). Renders a synthesized insight,
// severity rail, symbol/sector/trend chips, quality/ensemble badge, and inline action buttons.

export interface ReportCardItem {
  id: string
  source?: string
  type?: string
  channel?: string
  title: string
  summary?: string                 // full body; first sentence is used as the synthesized insight
  synthesized_insight?: string     // explicit insight if the backend provides one
  severity?: string                // critical | warning | info | positive (+ urgent/high/etc.)
  symbols?: string[]
  symbol?: string
  sector?: string
  trend?: string
  created_at?: string
  quality_score?: number           // 0..100 or 0..1
  finance_score?: number           // 0..100 finance-substance (reports_portal)
  retirement_relevance?: string    // high | medium | null
  ensemble?: { score?: number; decision?: string; consensus?: boolean; lanes?: string[] } | null
  actions?: { label: string; url?: string; action?: string }[]
  action_classes?: string[]
  action_count?: number
  has_actions?: boolean
  docx_file?: { filename: string; url: string; size_kb?: number }
}

const SEV = (s?: string) => {
  const v = (s || '').toLowerCase()
  if (/crit|urgent|triggered|danger|broken/.test(v)) return { c: '#ef4444', bg: 'rgba(239,68,68,.13)', label: 'CRITICAL' }
  if (/warn|weak|caution|high|stale|pending|review/.test(v)) return { c: '#f59e0b', bg: 'rgba(245,158,11,.13)', label: 'WARNING' }
  if (/pos|ok|pass|protected|good|approve/.test(v)) return { c: '#22c55e', bg: 'rgba(34,197,94,.13)', label: 'POSITIVE' }
  return { c: '#60a5fa', bg: 'rgba(96,165,250,.13)', label: 'INFO' }
}
function insightOf(it: ReportCardItem): string {
  if (it.synthesized_insight) return it.synthesized_insight
  const b = (it.summary || '').replace(/\s+/g, ' ').trim()
  if (!b) return ''
  const m = b.match(/^.{40,240}?[.!?](\s|$)/)
  return (m ? m[0] : b.slice(0, 200)).trim()
}
function ago(iso?: string): string {
  if (!iso) return ''
  const h = (Date.now() - Date.parse(iso)) / 3.6e6
  if (!Number.isFinite(h)) return ''
  return h < 1 ? 'just now' : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`
}
// Action URLs from the backend are absolute (hardcoded tailscale host for Telegram/email). In the dashboard
// that navigates OFF to another instance — strip to the same-origin path so the link stays in this app.
function relUrl(u?: string): string | undefined {
  if (!u) return u
  try { const p = new URL(u); return p.pathname + p.search + p.hash } catch { return u }
}
const chip: React.CSSProperties = { fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 5, background: 'var(--bg2)', color: 'var(--text2)' }
const TREND_C = (t?: string) => /bull|up|strong/i.test(t || '') ? '#22c55e' : /bear|down|weak/i.test(t || '') ? '#ef4444' : '#a855f7'

export default function SynthesizedReportCard(
  { item, onAction, compact, selected, footer }:
  { item: ReportCardItem; onAction?: (action: string, id: string) => void; compact?: boolean; selected?: boolean; footer?: React.ReactNode }
) {
  const sv = SEV(item.severity)
  const insight = insightOf(item)
  const syms = (item.symbols && item.symbols.length ? item.symbols : item.symbol ? [item.symbol] : []).slice(0, 4)
  const q = item.quality_score == null ? null : item.quality_score > 1 ? Math.round(item.quality_score) : Math.round(item.quality_score * 100)
  const fin = item.finance_score == null ? null : Math.round(item.finance_score)
  const en = item.ensemble
  return (
    <div style={{
      background: selected ? 'rgba(96,165,250,.06)' : 'var(--bg1)', border: '1px solid var(--border)',
      borderLeft: `4px solid ${sv.c}`, borderRadius: 11, padding: compact ? '10px 12px' : '13px 15px',
      outline: selected ? '1px solid #60a5fa' : 'none', cursor: onAction ? 'default' : 'pointer',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', gap: 7, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 8.5, fontWeight: 900, padding: '1px 6px', borderRadius: 4, color: sv.c, background: sv.bg }}>{sv.label}</span>
            {item.type && <span style={{ fontSize: 9, color: 'var(--text3)' }}>{item.type}</span>}
            {syms.map(s => <span key={s} style={{ fontSize: 11, fontWeight: 800, color: '#60a5fa', fontFamily: 'monospace' }}>{s}</span>)}
          </div>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', lineHeight: 1.35, marginTop: 5 }}>{item.title}</div>
          {insight && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, lineHeight: 1.45, display: '-webkit-box', WebkitLineClamp: compact ? 2 : 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{insight}</div>}
          {/* chips: only the ones that exist, and never in compact (narrow list) — keeps the list scannable */}
          {!compact && (item.sector || item.trend || q != null || fin != null || item.retirement_relevance || (en && en.decision)) && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 7, alignItems: 'center' }}>
              {item.sector && <span style={chip}>{item.sector}</span>}
              {item.trend && <span style={{ ...chip, color: TREND_C(item.trend) }}>{item.trend}</span>}
              {fin != null && fin >= 28 && <span style={{ ...chip, color: fin >= 70 ? '#22c55e' : '#60a5fa' }}>finance {fin}</span>}
              {item.retirement_relevance && <span style={{ ...chip, color: item.retirement_relevance === 'high' ? '#f59e0b' : 'var(--text2)' }}>retire {item.retirement_relevance}</span>}
              {q != null && <span style={{ ...chip, color: q >= 72 ? '#22c55e' : q >= 50 ? '#f59e0b' : '#ef4444' }}>quality {q}%</span>}
              {en && en.decision && <span style={{ ...chip, color: en.decision === 'approve' ? '#22c55e' : '#ef4444' }}>ensemble {en.decision}{en.score != null ? ` ${en.score}` : ''}{en.lanes?.length ? ` · ${en.lanes.length} lanes` : ''}</span>}
            </div>
          )}
        </div>
        <div style={{ textAlign: 'right', whiteSpace: 'nowrap', fontSize: 9.5, color: 'var(--text3)' }}>
          {ago(item.created_at)}{item.channel ? <><br />{item.channel}</> : null}
          {item.docx_file?.url && (
            <><br /><a href={relUrl(item.docx_file.url)} download={item.docx_file.filename} onClick={e => e.stopPropagation()} style={{ fontSize: 9, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Word ↓</a></>
          )}
        </div>
      </div>
      {/* footer slot (full card only) — live embeds like the ensemble verdict, above the action row */}
      {!compact && footer && <div style={{ marginTop: 8 }}>{footer}</div>}
      {/* actions only on the FULL card (reader/feed) — the compact list opens the reader on click, which has them */}
      {!compact && (item.actions && item.actions.length > 0) && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
          {item.actions.slice(0, 5).map((a, i) => {
            const slug = a.action || (a.url?.startsWith('#') ? a.url.slice(1) : undefined)
            const external = a.url && !a.url.startsWith('#')
            if (external) return <a key={i} href={relUrl(a.url)} onClick={e => e.stopPropagation()} style={{ fontSize: 10, fontWeight: 700, padding: '5px 11px', borderRadius: 6, border: '1px solid #60a5fa55', background: '#60a5fa14', color: '#60a5fa', textDecoration: 'none' }}>{a.label} →</a>
            return <button key={i} onClick={e => { e.stopPropagation(); onAction?.(slug || a.label, item.id) }} style={{ fontSize: 10, fontWeight: 700, padding: '5px 11px', borderRadius: 6, border: slug ? '1px solid #60a5fa55' : '1px solid var(--border)', background: slug ? '#60a5fa14' : 'var(--bg2)', color: slug ? '#60a5fa' : 'var(--text1)', cursor: 'pointer' }}>{a.label}{slug ? ' →' : ''}</button>
          })}
        </div>
      )}
    </div>
  )
}

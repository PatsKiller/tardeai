import type { ReactNode } from 'react'
import SynthesizedReportCard from '../SynthesizedReportCard'
import { SUPER_TABS } from './briefUtils'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }
const SEV: Record<string, string> = { critical: '#dc2626', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }
const sevColor = (s?: string) => SEV[(s || 'info').toLowerCase()] || '#60a5fa'

const RISK_CLASSES = ['stop_triggered', 'unprotected_position', 'risk_review']
const SYSTEM_CLASSES = ['system_health', 'cron_or_backup', 'llm_review']
type QV = '' | 'today' | 'needs_action' | 'risk' | 'approvals' | 'hermes' | 'system' | 'critical'

const QUICK_VIEWS: { key: QV; label: string }[] = [
  { key: '', label: 'All' }, { key: 'today', label: 'Today' }, { key: 'needs_action', label: 'Needs action' },
  { key: 'risk', label: 'Risk / Stops' }, { key: 'approvals', label: 'Approvals' }, { key: 'hermes', label: 'Hermes' },
  { key: 'system', label: 'System' }, { key: 'critical', label: 'Critical' },
]

const ACT_ROUTE: Record<string, string> = {
  stop_triggered: '/v3/risk', unprotected_position: '/v3/risk', risk_review: '/v3/risk',
  approval_needed: '/v3/trading', broker_manual: '/v3/trading', hermes_review: '/v3/hermes',
  system_health: '/v3/system', cron_or_backup: '/v3/system', llm_review: '/v3/system',
  research_needed: '/v3/research-intelligence', portfolio_review: '/v3/portfolio', recovery: '/v3/risk',
}

function ActionPill({ cls }: { cls: string }) {
  const c = cls.includes('stop') || cls.includes('risk') ? '#ef4444' : cls.includes('approval') ? '#a855f7' : '#60a5fa'
  return <span style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: c + '22', color: c }}>{cls.replace(/_/g, ' ')}</span>
}

function MiniBarChart({ rows, color }: { rows: { label: string; value: number; color?: string }[]; color?: string }) {
  const max = Math.max(1, ...rows.map(r => r.value))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ fontSize: 10, color: 'var(--text2)', width: 78, flexShrink: 0, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
          <div style={{ flex: 1, height: 9, background: 'var(--bg2)', borderRadius: 5, overflow: 'hidden' }}>
            <div style={{ width: `${(r.value / max) * 100}%`, height: '100%', background: r.color || color || '#60a5fa', borderRadius: 5 }} />
          </div>
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', width: 30, textAlign: 'right' }}>{r.value}</span>
        </div>
      ))}
    </div>
  )
}

function SeverityBadge({ sev }: { sev?: string }) {
  const c = sevColor(sev)
  return <span style={{ fontSize: 9.5, fontWeight: 800, padding: '2px 7px', borderRadius: 5, background: c + '22', color: c, textTransform: 'uppercase' }}>{sev || 'info'}</span>
}

function Kpi({ label, value, color, active, onClick }: { label: string; value: number | string; color?: string; active?: boolean; onClick?: () => void }) {
  return (
    <div onClick={onClick} style={{ ...card, padding: '11px 13px', cursor: onClick ? 'pointer' : 'default', borderColor: active ? (color || '#60a5fa') : 'var(--border)', background: active ? (color || '#60a5fa') + '12' : 'var(--bg1)' }}>
      <div style={{ fontSize: 22, fontWeight: 900, color: color || 'var(--text0)', lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3, textTransform: 'uppercase', letterSpacing: 0.3, fontWeight: 700 }}>{label}</div>
    </div>
  )
}

interface Props {
  categories: any[]
  superTab: string
  setSuperTab: (v: string) => void
  active: string
  setActive: (v: string) => void
  archiveCategories: any[]
  activeCat: any
  qInput: string
  setQInput: (v: string) => void
  days: number | ''
  setDays: (v: number | '') => void
  qv: QV
  setQv: (v: QV) => void
  items: any[]
  rawItems: any[]
  loading: boolean
  total: number
  matching: number
  qvCounts: Record<string, number> | null
  qvScanned: number
  pages: number
  page: number
  setPage: (fn: (p: number) => number) => void
  selId: string | null
  setSelId: (v: string) => void
  selected: any
  kpis: any
  effDays: number | ''
  reportActions: any[]
  fmtDate: (s?: string) => string
  renderArticle: (text: string) => ReactNode
  onPurge: () => void
  onStatClick: (qv: QV) => void
}

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''
const relUrl = (u?: string) => (u ? u.replace(/^https?:\/\/[^/]+/, '') : u)

export default function ReportsArchive(props: Props) {
  const {
    categories, superTab, setSuperTab, active, setActive, archiveCategories, activeCat,
    qInput, setQInput, days, setDays, qv, setQv, items, rawItems, loading, total, matching, qvCounts,
    qvScanned, pages, page, setPage,
    selId, setSelId, selected, kpis, effDays, reportActions, fmtDate, renderArticle, onPurge, onStatClick,
  } = props

  const k = kpis || {}
  // WS-A (v3): chip values come from the SAME /reports/list pass that serves the list below —
  // one corpus (this category + day window + search), so chips can never disagree with the list.
  const qc = qvCounts || {}
  const capped = qvScanned > 0 && qvScanned < total
  const sevRows = Object.entries(k.by_severity || {}).map(([label, value]: any) => ({ label, value, color: sevColor(label) })).sort((a: any, b: any) => b.value - a.value)
  const catRows = (k.by_category || []).slice(0, 7).map((c: any) => ({ label: c.label, value: c.count }))

  const sectorFilter = qInput.match(/sector:(\S+)/i)?.[1]
  const trendFilter = qInput.match(/trend:(\S+)/i)?.[1]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: 12, color: 'var(--text3)' }}>Professional archive · search by ticker, sector:trend, topic, or channel</div>
        <button onClick={onPurge} style={{ fontSize: 10.5, fontWeight: 600, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text3)', cursor: 'pointer' }}>Retention / purge</button>
      </div>

      <div>
        <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 4 }}>
          · archive — {activeCat?.label || active} · {effDays ? `${effDays}d` : 'all time'}{capped ? ` · counts over newest ${qvScanned} of ${total}` : ''}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
          <Kpi label="In scope" value={total} />
          <Kpi label="Today" value={qc.today ?? '—'} color="#4ade80" active={qv === 'today'} onClick={() => onStatClick(qv === 'today' ? '' : 'today')} />
          <Kpi label="Critical" value={qc.critical ?? '—'} color="#ef4444" active={qv === 'critical'} onClick={() => onStatClick(qv === 'critical' ? '' : 'critical')} />
          <Kpi label="Needs action" value={qc.needs_action ?? '—'} color="#a855f7" active={qv === 'needs_action'} onClick={() => onStatClick(qv === 'needs_action' ? '' : 'needs_action')} />
          <Kpi label="Risk / Stop" value={qc.risk ?? '—'} color="#f59e0b" active={qv === 'risk'} onClick={() => onStatClick(qv === 'risk' ? '' : 'risk')} />
          <Kpi label="Approvals" value={qc.approvals ?? '—'} color="#a855f7" active={qv === 'approvals'} onClick={() => onStatClick(qv === 'approvals' ? '' : 'approvals')} />
          <Kpi label="System" value={qc.system ?? '—'} color="#60a5fa" active={qv === 'system'} onClick={() => onStatClick(qv === 'system' ? '' : 'system')} />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {SUPER_TABS.map(t => (
          <button key={t.key} onClick={() => setSuperTab(t.key)} style={{
            fontSize: 11, fontWeight: superTab === t.key ? 800 : 600, padding: '5px 11px', borderRadius: 7, cursor: 'pointer',
            border: `1px solid ${superTab === t.key ? '#60a5fa' : 'var(--border)'}`,
            background: superTab === t.key ? 'rgba(96,165,250,.12)' : 'var(--bg1)', color: superTab === t.key ? '#60a5fa' : 'var(--text2)',
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4 }}>
        {archiveCategories.map((c: any) => {
          const on = c.key === active
          return (
            <button key={c.key} onClick={() => setActive(c.key)} style={{
              fontSize: 11.5, fontWeight: on ? 800 : 600, padding: '6px 10px', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
              border: `1px solid ${on ? '#60a5fa' : 'var(--border)'}`, background: on ? 'rgba(96,165,250,.10)' : 'var(--bg1)', color: on ? '#60a5fa' : 'var(--text2)',
            }}>{c.icon} {c.label} <span style={{ fontSize: 9.5, fontWeight: 800, color: on ? '#60a5fa' : 'var(--text3)' }}>{c.count}</span></button>
          )
        })}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>Quick views</span>
        {QUICK_VIEWS.map(v => (
          <button key={v.key || 'all'} onClick={() => setQv(v.key)} style={{
            fontSize: 11, fontWeight: qv === v.key ? 800 : 600, padding: '5px 11px', borderRadius: 7, cursor: 'pointer',
            border: `1px solid ${qv === v.key ? '#a855f7' : 'var(--border)'}`, background: qv === v.key ? 'rgba(168,85,247,.12)' : 'var(--bg1)', color: qv === v.key ? '#d8b4fe' : 'var(--text2)',
          }}>{v.label}</button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 340px', minWidth: 300, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ ...card, padding: 9, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input value={qInput} onChange={e => setQInput(e.target.value)}
              placeholder="Search · AAPL · sector:Technology · trend:bullish · russell · rotation"
              style={{ flex: 1, minWidth: 140, fontSize: 12, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }} />
            <div style={{ display: 'flex', gap: 3 }}>
              {([['', 'All'], [1, '1d'], [7, '7d'], [30, '30d'], [90, '90d']] as any).map(([v, l]: any) => (
                <button key={l} onClick={() => setDays(v)} style={{ fontSize: 10, fontWeight: 700, padding: '5px 7px', borderRadius: 5, cursor: 'pointer',
                  border: `1px solid ${days === v ? '#60a5fa' : 'var(--border)'}`, background: days === v ? 'rgba(96,165,250,.10)' : 'transparent', color: days === v ? '#60a5fa' : 'var(--text3)' }}>{l}</button>
              ))}
            </div>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--text3)', padding: '0 2px' }}>{items.length} shown{qv ? ` · ${matching} matching '${qv.replace('_', ' ')}'` : ''} · {total} total in scope{(sectorFilter || trendFilter) ? ` · filtered` : ''}</div>

          {loading && rawItems.length === 0 && <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>loading…</div>}
          {!loading && items.length === 0 && <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>no reports here</div>}

          {items.map((it: any) => {
            const id = `${it.source}-${it.id}`
            const on = !!(selected && `${selected.source}-${selected.id}` === id)
            if (sectorFilter && !(it.sector || '').toLowerCase().includes(sectorFilter.toLowerCase())) return null
            if (trendFilter && !(it.trend || '').toLowerCase().includes(trendFilter.toLowerCase())) return null
            return (
              <div key={id} onClick={() => setSelId(id)}>
                <SynthesizedReportCard item={it} selected={on} compact />
              </div>
            )
          })}

          {pages > 1 && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center' }}>
              <button disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))} style={{ fontSize: 11, padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page <= 1 ? 'var(--text3)' : 'var(--text1)', cursor: page <= 1 ? 'not-allowed' : 'pointer' }}>← Newer</button>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>page {page} of {pages}</span>
              <button disabled={page >= pages} onClick={() => setPage(p => Math.min(pages, p + 1))} style={{ fontSize: 11, padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page >= pages ? 'var(--text3)' : 'var(--text1)', cursor: page >= pages ? 'not-allowed' : 'pointer' }}>Older →</button>
            </div>
          )}
        </div>

        <div style={{ flex: '1 1 440px', minWidth: 340 }}>
          {!selected ? (
            <div style={{ ...card, padding: 36, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>select a report to read</div>
          ) : (
            <article style={{ ...card, borderTop: `3px solid ${sevColor(selected.severity)}`, padding: '16px 20px' }}>
              <header style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 900, color: 'var(--text0)', lineHeight: 1.3 }}>{selected.title}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <span>{fmtDate(selected.created_at)}</span><span>· {selected.channel}</span>
                    {selected.sector && <span style={{ color: '#a855f7' }}>· {selected.sector}</span>}
                    {selected.trend && <span style={{ color: '#22c55e' }}>· {selected.trend}</span>}
                    {selected.finance_score != null && <span>· finance {selected.finance_score}</span>}
                  </div>
                </div>
                <SeverityBadge sev={selected.severity} />
              </header>
              <SynthesizedReportCard item={selected} />
              <div style={{ marginTop: 12 }}>{renderArticle(selected.summary || '')}</div>
            </article>
          )}
        </div>

        <div style={{ flex: '1 1 240px', minWidth: 230, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ ...card, padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 900, color: 'var(--text0)', marginBottom: 8 }}>Extracted actions</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 320, overflowY: 'auto' }}>
              {reportActions.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>none for this report</div>}
              {reportActions.map((a: any) => (
                <div key={a.id || a.action_class} style={{ padding: '7px 8px', borderRadius: 7, background: 'var(--bg2)', borderLeft: `3px solid ${sevColor(a.severity)}` }}>
                  <ActionPill cls={a.action_class} />
                  <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4 }}>{a.text}</div>
                  <a href={relUrl(FQDN + (a.route || ACT_ROUTE[a.action_class] || '/v3/reports'))} style={{ fontSize: 9.5, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>{a.route_label || 'Open'} →</a>
                </div>
              ))}
            </div>
          </div>
          {sevRows.length > 0 && <div style={{ ...card, padding: 12 }}><div style={{ fontSize: 12, fontWeight: 900, marginBottom: 8 }}>Severity <span style={{ fontSize: 8.5, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>· portal sample · {effDays || 7}d · all categories</span></div><MiniBarChart rows={sevRows} /></div>}
          {catRows.length > 0 && <div style={{ ...card, padding: 12 }}><div style={{ fontSize: 12, fontWeight: 900, marginBottom: 8 }}>Categories <span style={{ fontSize: 8.5, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>· portal sample · {effDays || 7}d</span></div><MiniBarChart rows={catRows} color="#60a5fa" /></div>}
        </div>
      </div>
    </div>
  )
}
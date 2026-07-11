import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import SynthesizedReportCard from '../components/SynthesizedReportCard'
import type { ReportCardItem } from '../components/SynthesizedReportCard'
import { EnsembleValidationInline } from '../components/EnsembleValidationCard'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubPanel } from '../lib/terminalHubChrome'

// Retirement Intelligence — synthesized trade-desk view of the Golden-Window Roth strategy, income
// durability, key dates, accounts/timeline, and Hermes knowledge research (Roth/MAPT/Medicare/SSDI/estate).
// Shared card language across tabs; Planning Research is searchable/filterable + on-demand multi-LLM
// ensemble (retirement/finance/risk sub-scores). Advisory only — confirm with an elder-law/tax professional.

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Overview', 'Accounts', 'Timeline', 'Planning Research'] as const

const slug = (s: string) => 'ret_' + (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 50)

// ── synthesized rail-card (matches SynthesizedReportCard's visual language for the metric-style Overview) ──
function RailCard({ rail, title, sub, children, onDrill, chips, panelStyle, terminalUi }:
  { rail: string; title: string; sub?: string; children?: React.ReactNode; onDrill?: () => void; chips?: { t: string; c: string }[]; panelStyle: React.CSSProperties; terminalUi: boolean }) {
  return (
    <div className={terminalUi ? 'cc-panel' : undefined} onClick={onDrill} style={{ ...panelStyle, borderLeft: `4px solid ${rail}`, cursor: onDrill ? 'pointer' : 'default' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>{title}</div>
        {sub && <div style={{ fontSize: 10, color: 'var(--text3)' }}>{sub}</div>}
        <span style={{ flex: 1 }} />
        {(chips ?? []).map((ch, i) => <span key={i} style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 5, background: ch.c + '1f', color: ch.c }}>{ch.t}</span>)}
      </div>
      <div style={{ marginTop: 10 }}>{children}</div>
    </div>
  )
}

// Planning-research topic categories (the Roth/MAPT/Medicare/SSDI/estate buckets the operator researches).
const CATS: { key: string; label: string; rx: RegExp | null }[] = [
  { key: 'all', label: 'All', rx: null },
  { key: 'roth', label: 'Roth', rx: /roth|conversion|golden.?window|rmd/i },
  { key: 'mapt', label: 'MAPT/Medicaid', rx: /mapt|medicaid|asset protection|lookback|trust|spend.?down/i },
  { key: 'medicare', label: 'Medicare', rx: /medicare|irmaa|part [bd]|advantage|premium/i },
  { key: 'ssdi', label: 'SSDI', rx: /ssdi|disability|sga|social security/i },
  { key: 'estate', label: 'Estate', rx: /estate|elder law|lien|homestead|probate|will|special needs/i },
  { key: 'income', label: 'Income', rx: /dividend|cef|covered call|income|nav|annuit|bond|yield/i },
]
const catMatch = (key: string, blob: string) => { const c = CATS.find(x => x.key === key); return !c?.rx || c.rx.test(blob) }

export default function RetirementHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const panel = terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const [search, setSearch] = useState('')
  const [cat, setCat] = useState('all')
  const [ensOpen, setEnsOpen] = useState<Record<string, boolean>>({})
  const { data: ret } = useApi<any>('/api/v2/retirement', 300_000)
  const { data: planning } = useApi<any>('/api/v2/retirement/planning-research', 300_000)

  // /api/v2/retirement returns accounts as a dict {total, roth, traditional, taxable} — normalize to rows
  const _rawAccts = ret?.accounts
  const _acctLabel: Record<string, string> = { roth: 'Roth IRA', traditional: 'Traditional / Rollover IRA', taxable: 'Taxable', rollover: 'Rollover IRA' }
  const accounts: any[] = Array.isArray(_rawAccts)
    ? _rawAccts
    : (_rawAccts && typeof _rawAccts === 'object')
      ? Object.entries(_rawAccts)
          .filter(([k]) => k !== 'total')
          .map(([k, v]) => ({ name: _acctLabel[k] ?? (k.charAt(0).toUpperCase() + k.slice(1)), type: k, value: Number(v) || 0 }))
      : []
  const timeline = ret?.timeline ?? []
  const golden = ret?.golden_window ?? {}
  const divIncome = ret?.dividend_income ?? {}

  // flatten planning items (theme attached) for search/filter
  const planItems = useMemo(() => {
    const out: any[] = []
    for (const th of (planning?.themes ?? [])) for (const it of (th.items ?? [])) out.push({ ...it, theme: th.theme })
    return out
  }, [planning])
  const planFiltered = useMemo(() => {
    const q = search.trim().toLowerCase()
    // Prioritize, don't dump: researched/promoted items first, then by confidence, then most recent.
    const rank = (x: any) => (x.status === 'promoted' || x.status === 'embedded' ? 2 : x.status === 'staged' ? 1 : 0)
    return planItems.filter(it => {
      const blob = `${it.topic} ${it.summary ?? ''} ${it.theme ?? ''}`
      return (!q || blob.toLowerCase().includes(q)) && catMatch(cat, blob)
    }).sort((a, b) =>
      rank(b) - rank(a) ||
      (Number(b.confidence) || 0) - (Number(a.confidence) || 0) ||
      String(b.at || '').localeCompare(String(a.at || '')))
  }, [planItems, search, cat])

  if (!ret) return <div style={{ padding: 24, color: 'var(--text3)' }}>Loading retirement data…</div>

  const toCard = (it: any): ReportCardItem => ({
    id: slug(it.topic), type: it.theme, channel: it.model,
    title: it.topic, summary: it.summary || it.thesis,
    severity: it.status === 'promoted' || it.status === 'embedded' ? 'positive' : 'info',
    created_at: it.at, quality_score: it.confidence != null ? Number(it.confidence) : undefined,
  })

  return (
    <div>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Retirement Intelligence</div>
          <div style={hubSubtitle(terminalUi)}>Age {ret.current_age ?? '—'} · {accounts.length} accounts · Golden-Window Roth · as of {ret.as_of ?? '—'}</div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={hubTab(tab === t, terminalUi)}>{t}{t === 'Planning Research' && planItems.length ? ` (${planItems.length})` : ''}</button>
          ))}
        </div>
      </div>

      {tab === 'Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <RailCard rail="#f59e0b" title="Golden Window — Roth Conversion Strategy" sub="advisory · confirm with tax pro"
            chips={[{ t: 'retirement', c: '#f59e0b' }]} panelStyle={panel} terminalUi={terminalUi}
            onDrill={() => onDrill({ title: 'Golden Window', subtitle: 'Roth conversion strategy', endpoint: '/api/v2/retirement', rows: [golden] })}>
            {golden.start_year ? (
              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                <Metric label="Window" value={`${golden.start_year}–${golden.end_year}`} />
                <Metric label="Annual conversion" value={fmt$(golden.annual_conversion ?? 0, 0)} color="#f59e0b" />
                <Metric label="Bracket ceiling" value={golden.bracket_ceiling ?? '—'} />
              </div>
            ) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No window configured.</div>}
            <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 10, lineHeight: 1.5 }}>
              Convert into the low-bracket window before RMDs/Medicare; watch the IRMAA 2-year MAGI lookback so a conversion year doesn't lift Part B/D surcharges two years later.
            </div>
          </RailCard>

          <RailCard rail="#22c55e" title="Dividend Income — Durability" sub="unearned income (does not count toward SSDI SGA)"
            chips={[{ t: 'income', c: '#22c55e' }]} panelStyle={panel} terminalUi={terminalUi}>
            <div style={{ display: 'flex', gap: 24, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <div><div style={{ fontSize: 26, fontWeight: 900, color: '#22c55e' }}>{fmt$(divIncome.annual_total ?? 0, 0)}</div><div style={{ fontSize: 9, color: 'var(--text3)' }}>per year</div></div>
              <Metric label="Monthly avg" value={`${fmt$(divIncome.monthly_avg ?? 0, 0)}/mo`} />
              {divIncome.yield_pct != null && <Metric label="Portfolio yield" value={`${divIncome.yield_pct}%`} />}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 10, lineHeight: 1.5 }}>
              For sustainability check coverage vs return-of-capital / NAV erosion — high yield funded by destructive ROC is not durable income.
            </div>
          </RailCard>

          {ret.key_dates && (
            <div className={terminalUi ? 'cc-panel' : undefined} style={{ ...panel, gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>Key Dates</div>
              {Object.entries(ret.key_dates).map(([k, v]: [string, any]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 6px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                  <span style={{ color: 'var(--text2)' }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'Accounts' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={panel}>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>Accounts ({accounts.length})</div>
          {accounts.map((a: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: a.name ?? a.account, subtitle: a.type ?? '', endpoint: '/api/v2/retirement', rows: [a] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{a.name ?? a.account}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{a.type ?? a.account_type ?? '—'}</div>
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(a.value ?? a.balance ?? 0, 0)}</div>
            </div>
          ))}
        </div>
      )}

      {tab === 'Timeline' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={panel}>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 10 }}>Retirement Timeline</div>
          {timeline.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No timeline data.</div> :
            timeline.map((t: any, i: number) => (
              <div key={i} onClick={() => onDrill({ title: t.label ?? t.event ?? `Event ${i}`, subtitle: t.year ?? t.date ?? '', endpoint: '/api/v2/retirement', rows: [t] })}
                style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <span style={{ color: 'var(--text0)' }}>{t.label ?? t.event ?? t.description ?? JSON.stringify(t).slice(0, 60)}</span>
                <span style={{ color: 'var(--text2)', fontFamily: 'monospace' }}>{t.year ?? t.date ?? t.age ?? ''}</span>
              </div>
            ))}
        </div>
      )}

      {tab === 'Planning Research' && (
        <div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 12, lineHeight: 1.5 }}>
            Hermes knowledge research on your retirement / estate / tax / Medicare topics (routed from the topics you add via Telegram). {planItems.length} researched items. Advisory — consult an elder-law attorney + tax advisor.
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search Roth, MAPT, Medicare, SSDI, estate…"
              style={{ flex: '1 1 240px', minWidth: 180, fontSize: 12, padding: '7px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 7, color: 'var(--text0)' }} />
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {CATS.map(c => {
                const on = cat === c.key
                return <button key={c.key} onClick={() => setCat(c.key)} style={{ fontSize: 11, fontWeight: on ? 800 : 600, padding: '6px 11px', borderRadius: 7, cursor: 'pointer',
                  border: `1px solid ${on ? '#a855f7' : 'var(--border)'}`, background: on ? 'rgba(168,85,247,.12)' : 'var(--bg1)', color: on ? '#d8b4fe' : 'var(--text2)' }}>{c.label}</button>
              })}
            </div>
          </div>

          {!planning && <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading…</div>}
          {planning && planFiltered.length === 0 && <div style={{ ...panel, color: 'var(--text3)', fontSize: 11, textAlign: 'center' }}>{planItems.length === 0 ? 'No planning research yet — topics are queued; Hermes researches them on its loop.' : 'No items match this filter.'}</div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(440px, 1fr))', gap: 14 }}>
            {planFiltered.map((it: any) => {
              const id = slug(it.topic)
              const srcs = (it.sources ?? []).slice(0, 5)
              return (
                <div key={id} onClick={() => onDrill({ title: it.topic, subtitle: it.theme, endpoint: '/api/v2/retirement/planning-research', rows: [it] })}>
                  <SynthesizedReportCard item={toCard(it)} footer={
                    <div onClick={e => e.stopPropagation()}>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 9, color: 'var(--text3)', alignItems: 'center' }}>
                        <span>{it.status ?? 'staged'}</span>
                        {it.source_count > 0 && <span>· {it.source_count} vetted src</span>}
                        {srcs.map((s: any, j: number) => <span key={j} title={s.title ?? ''} style={{ background: 'rgba(34,197,94,.10)', color: '#22c55e', borderRadius: 4, padding: '1px 6px' }}>{s.source}</span>)}
                      </div>
                      <button onClick={() => setEnsOpen(o => ({ ...o, [id]: !o[id] }))} style={{ marginTop: 8, fontSize: 10.5, fontWeight: 800, padding: '5px 11px', borderRadius: 7, cursor: 'pointer',
                        border: '1px solid #a855f766', background: ensOpen[id] ? 'rgba(168,85,247,.18)' : 'var(--bg2)', color: '#d8b4fe' }}>⚖ Ensemble {ensOpen[id] ? '▲' : '▾'} <span style={{ color: 'var(--text3)', fontWeight: 500 }}>retirement/finance/risk</span></button>
                      {ensOpen[id] && (
                        <EnsembleValidationInline targetType="signal" targetId={id} subject={it.topic}
                          content={`${it.topic}\n${it.thesis ?? ''}\n${it.summary ?? ''}`.slice(0, 1200)} />
                      )}
                    </div>
                  } />
                </div>
              )
            })}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 10 }}>Source: /api/v2/retirement/planning-research → topic_research (Hermes knowledge research). Ensemble = free-lane multi-LLM (grok/chatgpt/local), advisory only.</div>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, color = 'var(--text0)' }: { label: string; value: any; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, fontWeight: 800 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 900, color, marginTop: 2 }}>{value || '—'}</div>
    </div>
  )
}

/**
 * Research Intelligence — first-class intelligence cockpit (CC v3).
 * Taxonomy-tagged feed from Hermes + auto-research + topic_monitor.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'

interface Props { onDrill: (ctx: DrillContext) => void }

type Cat = {
  id: string
  label: string
  color?: string
  description?: string
  priority?: number
}

type Item = {
  id: string
  title: string
  summary?: string
  thesis?: string | null
  symbol?: string | null
  categories?: string[]
  primary_category?: string
  priority?: string
  confidence?: number | null
  freshness_hours?: number | null
  created_at?: string
  source_system?: string
  research_type?: string
  is_holdings?: boolean
  sources?: { title?: string; url?: string; source?: string }[]
  actionability?: string
  model?: string
}

const PRI_COLOR: Record<string, string> = {
  high: '#f59e0b',
  normal: '#60a5fa',
  low: '#64748b',
}

function fmtAge(h?: number | null) {
  if (h == null || !Number.isFinite(h)) return '—'
  if (h < 24) return `${Math.round(h)}h`
  return `${Math.floor(h / 24)}d`
}

function Chip({ label, color, active, onClick }: {
  label: string; color?: string; active?: boolean; onClick?: () => void
}) {
  const c = color || '#94a3b8'
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        fontSize: 11, fontWeight: 800, padding: '5px 11px', borderRadius: 8, cursor: 'pointer',
        border: `1px solid ${active ? c : 'rgba(148,163,184,.28)'}`,
        background: active ? `${c}22` : 'transparent',
        color: active ? c : 'var(--text2)',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
}

function IntelCard({ item, catMeta, onOpen }: {
  item: Item
  catMeta: Record<string, Cat>
  onOpen: () => void
}) {
  const pri = item.priority || 'normal'
  const pc = PRI_COLOR[pri] || PRI_COLOR.normal
  const primary = item.primary_category || item.categories?.[0] || ''
  const catColor = catMeta[primary]?.color || '#94a3b8'
  return (
    <article
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
      style={{
        borderRadius: 12,
        border: `1px solid ${item.is_holdings ? 'rgba(34,197,94,.35)' : 'rgba(148,163,184,.16)'}`,
        borderLeft: `3px solid ${pc}`,
        background: 'var(--bg1)',
        padding: '12px 14px',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minHeight: 140,
        boxShadow: '0 4px 16px rgba(0,0,0,.12)',
        transition: 'border-color .15s, transform .12s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 4 }}>
            {item.symbol && (
              <span style={{
                fontFamily: 'var(--mono, monospace)', fontWeight: 900, fontSize: 13, color: '#60a5fa',
              }}>
                {item.symbol}
              </span>
            )}
            <span style={{
              fontSize: 9, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase',
              color: catColor, border: `1px solid ${catColor}55`, borderRadius: 4, padding: '2px 6px',
            }}>
              {catMeta[primary]?.label || primary}
            </span>
            {item.is_holdings && (
              <span style={{
                fontSize: 9, fontWeight: 800, color: '#22c55e', background: 'rgba(34,197,94,.12)',
                border: '1px solid rgba(34,197,94,.35)', borderRadius: 4, padding: '2px 6px',
              }}>
                HOLDING
              </span>
            )}
            <span style={{
              fontSize: 9, fontWeight: 800, color: pc, textTransform: 'uppercase',
            }}>
              {pri}
            </span>
          </div>
          <div style={{
            fontSize: 13, fontWeight: 800, color: 'var(--text0)', lineHeight: 1.35,
            overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          }}>
            {item.title}
          </div>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text3)', textAlign: 'right', flexShrink: 0 }}>
          <div>{fmtAge(item.freshness_hours)}</div>
          {item.confidence != null && (
            <div style={{ color: 'var(--text2)', fontWeight: 700 }}>
              {Math.round(Number(item.confidence) * (Number(item.confidence) <= 1 ? 100 : 1))}%
            </div>
          )}
        </div>
      </div>
      <div style={{
        fontSize: 11.5, color: 'var(--text2)', lineHeight: 1.45, flex: 1,
        overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
      }}>
        {item.summary || item.thesis || '—'}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>
          {item.source_system} · {item.research_type || '—'}
          {item.model ? ` · ${item.model}` : ''}
        </div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa' }}>
          {item.actionability?.slice(0, 36) || 'Open →'}
        </div>
      </div>
    </article>
  )
}

export default function ResearchIntelligenceHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const [priority, setPriority] = useState<string | null>(null)
  const [holdingsOnly, setHoldingsOnly] = useState(false)
  const [lane, setLane] = useState<'all' | 'retirement' | 'dividends' | 'macro_sector'>('all')

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (category) p.set('category', category)
    if (priority) p.set('priority', priority)
    if (holdingsOnly) p.set('holdings_only', '1')
    p.set('limit', '100')
    return p.toString()
  }, [q, category, priority, holdingsOnly])

  const { data, loading, error, refetch } = useApi<any>(
    `/api/v2/research-intelligence?${qs}`,
    90_000,
  )

  const cats: Cat[] = data?.taxonomy?.categories || []
  const catMeta = useMemo(() => {
    const m: Record<string, Cat> = {}
    for (const c of cats) m[c.id] = c
    return m
  }, [cats])

  const items: Item[] = data?.items || []
  const lanes = data?.priority_lanes || {}
  const stats = data?.stats || {}

  // Priority lanes come from full match set (not just page) so Retirement / Dividends /
  // Macro never appear empty when holdings stop-noise dominates the default grid.
  const displayItems: Item[] = useMemo(() => {
    if (lane === 'all') return items
    const laneItems = (lanes[lane] as Item[]) || []
    if (laneItems.length) return laneItems
    // Fallback: client filter if API omitted lane (older server)
    if (lane === 'retirement') return items.filter(i => i.categories?.includes('retirement_tax'))
    if (lane === 'dividends') return items.filter(i => i.categories?.includes('dividend_income'))
    if (lane === 'macro_sector') {
      return items.filter(i =>
        i.categories?.includes('macro_geo') || i.categories?.includes('sector_thematic'))
    }
    return items
  }, [lane, items, lanes])

  const openItem = (item: Item) => {
    onDrill({
      title: item.symbol ? `${item.symbol} · ${item.title}` : item.title,
      subtitle: [
        item.primary_category && (catMeta[item.primary_category]?.label || item.primary_category),
        item.priority,
        item.source_system,
        item.actionability,
      ].filter(Boolean).join(' · '),
      endpoint: '/api/v2/research-intelligence',
      rows: [item],
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Header */}
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
        <div>
          <div style={hubTitle()}>Research Intelligence</div>
          <div style={hubSubtitle(terminalUi)}>
            Taxonomy-tagged cockpit · Hermes · auto-research · topic monitor · holdings-aware
            {stats.matched != null && ` · ${stats.matched} matched`}
            {loading ? ' · loading…' : ''}
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <Link to="/intelligence?tab=research" style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textDecoration: 'none' }}>
            Legacy Research Topics →
          </Link>
          <Link to="/retirement" style={{ fontSize: 11, fontWeight: 700, color: '#a855f7', textDecoration: 'none' }}>
            Retirement hub →
          </Link>
          <Link to="/hermes" style={{ fontSize: 11, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>
            Hermes →
          </Link>
          <button
            type="button"
            onClick={() => refetch()}
            style={{
              fontSize: 11, fontWeight: 800, padding: '5px 10px', borderRadius: 7, cursor: 'pointer',
              border: '1px solid rgba(96,165,250,.45)', background: 'rgba(96,165,250,.12)', color: '#60a5fa',
            }}
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8,
      }}>
        {[
          { l: 'In view', v: String(displayItems.length), c: 'var(--text0)' },
          { l: 'High priority', v: String(stats.high_priority ?? 0), c: '#f59e0b' },
          { l: 'Holdings-linked', v: String(stats.holdings_linked ?? 0), c: '#22c55e' },
          { l: 'Holdings universe', v: String(stats.holdings_count ?? 0), c: '#60a5fa' },
          { l: 'Taxonomy cats', v: String(cats.length), c: '#a855f7' },
        ].map(k => (
          <div key={k.l} style={{
            background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px',
          }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', letterSpacing: '.06em', textTransform: 'uppercase' }}>{k.l}</div>
            <div style={{ fontSize: 18, fontWeight: 900, color: k.c, marginTop: 2 }}>{k.v}</div>
          </div>
        ))}
      </div>

      {/* Priority lanes */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {([
          ['all', 'All intelligence'],
          ['retirement', 'Retirement & tax'],
          ['dividends', 'Dividends & income'],
          ['macro_sector', 'Macro / sector'],
        ] as const).map(([id, lab]) => (
          <Chip
            key={id}
            label={lab}
            color={id === 'retirement' ? '#a855f7' : id === 'dividends' ? '#22c55e' : id === 'macro_sector' ? '#f59e0b' : '#60a5fa'}
            active={lane === id}
            onClick={() => { setLane(id); if (id !== 'all') setCategory(null) }}
          />
        ))}
      </div>

      {/* Taxonomy filter */}
      <div style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 12,
      }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 }}>
          Taxonomy
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          <Chip label="All categories" active={!category} onClick={() => setCategory(null)} />
          {cats.map(c => (
            <Chip
              key={c.id}
              label={`${c.label}${stats.by_category?.[c.id] != null ? ` (${stats.by_category[c.id]})` : ''}`}
              color={c.color}
              active={category === c.id}
              onClick={() => { setCategory(c.id); setLane('all') }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search title, thesis, symbol…"
            style={{
              flex: '1 1 220px', minWidth: 180, fontSize: 12, padding: '7px 10px', borderRadius: 8,
              border: '1px solid var(--border)', background: 'var(--bg0)', color: 'var(--text0)',
            }}
          />
          <Chip label="High only" color="#f59e0b" active={priority === 'high'} onClick={() => setPriority(priority === 'high' ? null : 'high')} />
          <Chip label="Holdings only" color="#22c55e" active={holdingsOnly} onClick={() => setHoldingsOnly(v => !v)} />
        </div>
      </div>

      {error && (
        <div style={{ padding: 12, borderRadius: 10, border: '1px solid rgba(239,68,68,.4)', color: '#ef4444', fontSize: 12 }}>
          Failed to load research intelligence: {error}
        </div>
      )}

      {/* Grid */}
      {loading && !data ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>Loading intelligence feed…</div>
      ) : displayItems.length === 0 ? (
        <div style={{
          padding: 32, textAlign: 'center', color: 'var(--text3)', fontSize: 12,
          border: '1px dashed var(--border)', borderRadius: 12,
        }}>
          No items match these filters. Try clearing search or category.
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: 12,
        }}>
          {displayItems.map(item => (
            <IntelCard
              key={item.id}
              item={item}
              catMeta={catMeta}
              onOpen={() => openItem(item)}
            />
          ))}
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--text3)', lineHeight: 1.45 }}>
        {data?.note}
        {' '}Source: <code>/api/v2/research-intelligence</code>
        {' · '}Ingestion: <code>topic_ingestion.py</code> + Hermes autonomous loop
        {' · '}Taxonomy: <code>config/research_intelligence_taxonomy.json</code>
      </div>
    </div>
  )
}

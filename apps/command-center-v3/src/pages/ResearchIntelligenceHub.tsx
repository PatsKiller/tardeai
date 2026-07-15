/**
 * Research Intelligence v2 — professional intelligence cockpit (CC v3).
 * Freshness tiers · archive search · stars/votes/notes · retirement pillar.
 */
import { useCallback, useMemo, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'
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
  pillar?: boolean
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
  freshness_tier?: string
  freshness_label?: string
  needs_refresh?: boolean
  is_archived?: boolean
  refresh_cadence_hours?: number
  created_at?: string
  source_system?: string
  research_type?: string
  is_holdings?: boolean
  sources?: { title?: string; url?: string; source?: string }[]
  source_count?: number
  actionability?: string
  model?: string
  sentiment?: string
  key_questions?: string[]
  data_gaps?: string[]
  starred?: boolean
  vote?: number | null
  operator_note?: string | null
  status?: string
}

const PRI_COLOR: Record<string, string> = {
  high: '#f59e0b',
  normal: '#60a5fa',
  low: '#64748b',
}

const TIER_COLOR: Record<string, string> = {
  live: '#22c55e',
  fresh: '#60a5fa',
  aging: '#f59e0b',
  stale: '#f97316',
  archive: '#64748b',
}

const SENT_COLOR: Record<string, string> = {
  bullish: '#22c55e',
  bearish: '#ef4444',
  neutral: '#94a3b8',
}

function Chip({ label, color, active, onClick, small }: {
  label: string; color?: string; active?: boolean; onClick?: () => void; small?: boolean
}) {
  const c = color || '#94a3b8'
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        fontSize: small ? 10 : 11, fontWeight: 800,
        padding: small ? '3px 8px' : '5px 11px',
        borderRadius: 8, cursor: onClick ? 'pointer' : 'default',
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

function Badge({ children, color }: { children: ReactNode; color: string }) {
  return (
    <span style={{
      fontSize: 9, fontWeight: 800, letterSpacing: '.04em', textTransform: 'uppercase',
      color, border: `1px solid ${color}55`, borderRadius: 4, padding: '2px 6px',
      background: `${color}14`,
    }}>
      {children}
    </span>
  )
}

async function postFeedback(body: Record<string, unknown>) {
  const r = await fetch('/api/v2/research-intelligence/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

function IntelCard({ item, catMeta, view, onOpen, onFeedback }: {
  item: Item
  catMeta: Record<string, Cat>
  view: 'cards' | 'list' | 'compact'
  onOpen: () => void
  onFeedback: (id: string, patch: Partial<Item>) => void
}) {
  const pri = item.priority || 'normal'
  const pc = PRI_COLOR[pri] || PRI_COLOR.normal
  const primary = item.primary_category || item.categories?.[0] || ''
  const catColor = catMeta[primary]?.color || '#94a3b8'
  const tier = item.freshness_tier || 'aging'
  const tc = TIER_COLOR[tier] || TIER_COLOR.aging
  const sc = SENT_COLOR[item.sentiment || 'neutral'] || SENT_COLOR.neutral

  const toggleStar = async (e: MouseEvent) => {
    e.stopPropagation()
    const next = !item.starred
    onFeedback(item.id, { starred: next })
    await postFeedback({
      item_id: item.id,
      starred: next,
      source_system: item.source_system,
      source_table: item.source_system === 'hermes' ? 'hermes_research_intelligence' : undefined,
      symbol: item.symbol,
      categories: item.categories,
    })
  }

  const vote = async (e: MouseEvent, v: number) => {
    e.stopPropagation()
    const next = item.vote === v ? 0 : v
    onFeedback(item.id, { vote: next || null })
    await postFeedback({
      item_id: item.id,
      vote: next,
      source_system: item.source_system,
      symbol: item.symbol,
      categories: item.categories,
    })
  }

  if (view === 'compact') {
    return (
      <div
        onClick={onOpen}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
        style={{
          display: 'grid',
          gridTemplateColumns: 'auto 1fr auto auto auto',
          gap: 10, alignItems: 'center',
          padding: '8px 12px',
          borderBottom: '1px solid rgba(148,163,184,.1)',
          cursor: 'pointer',
          background: item.starred ? 'rgba(250,204,21,.04)' : 'transparent',
        }}
      >
        <button type="button" onClick={toggleStar} style={{
          border: 'none', background: 'transparent', cursor: 'pointer',
          color: item.starred ? '#facc15' : 'var(--text3)', fontSize: 14, padding: 0,
        }} title="Star">{item.starred ? '★' : '☆'}</button>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 12, fontWeight: 700, color: 'var(--text0)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {item.symbol && <span style={{ color: '#60a5fa', marginRight: 6 }}>{item.symbol}</span>}
            {item.title}
          </div>
        </div>
        <Badge color={catColor}>{catMeta[primary]?.label || primary}</Badge>
        <span style={{ fontSize: 10, color: tc, fontWeight: 700 }}>{item.freshness_label || '—'}</span>
        <span style={{ fontSize: 10, color: pc, fontWeight: 800, textTransform: 'uppercase' }}>{pri}</span>
      </div>
    )
  }

  if (view === 'list') {
    return (
      <article
        onClick={onOpen}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 200px',
          gap: 14,
          padding: '14px 16px',
          borderRadius: 12,
          border: `1px solid ${item.is_holdings ? 'rgba(34,197,94,.3)' : 'rgba(148,163,184,.14)'}`,
          borderLeft: `3px solid ${pc}`,
          background: 'var(--bg1)',
          cursor: 'pointer',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6, alignItems: 'center' }}>
            <button type="button" onClick={toggleStar} style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              color: item.starred ? '#facc15' : 'var(--text3)', fontSize: 15, padding: 0, lineHeight: 1,
            }}>★</button>
            {item.symbol && (
              <span style={{ fontFamily: 'var(--mono, monospace)', fontWeight: 900, fontSize: 13, color: '#60a5fa' }}>
                {item.symbol}
              </span>
            )}
            <Badge color={catColor}>{catMeta[primary]?.label || primary}</Badge>
            {item.is_holdings && <Badge color="#22c55e">Holding</Badge>}
            {item.is_archived && <Badge color="#64748b">Archived</Badge>}
            {item.needs_refresh && <Badge color="#f97316">Needs refresh</Badge>}
            <Badge color={sc}>{item.sentiment || 'neutral'}</Badge>
          </div>
          <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', lineHeight: 1.35, marginBottom: 6 }}>
            {item.title}
          </div>
          <div style={{
            fontSize: 12, color: 'var(--text2)', lineHeight: 1.5,
            overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
          }}>
            {item.summary || item.thesis || '—'}
          </div>
          {!!item.key_questions?.length && (
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text3)' }}>
              Q: {item.key_questions[0]}
            </div>
          )}
        </div>
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8,
          borderLeft: '1px solid rgba(148,163,184,.12)', paddingLeft: 12,
        }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: tc, textAlign: 'right' }}>
            {item.freshness_label}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', textAlign: 'right' }}>
            {item.source_system} · {item.research_type || '—'}
            {item.source_count ? ` · ${item.source_count} src` : ''}
          </div>
          {item.confidence != null && (
            <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text1)' }}>
              {Math.round(Number(item.confidence) * (Number(item.confidence) <= 1 ? 100 : 1))}% conf
            </div>
          )}
          <div style={{ fontSize: 11, fontWeight: 700, color: '#60a5fa', textAlign: 'right' }}>
            {item.actionability?.slice(0, 42) || 'Open →'}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" onClick={e => vote(e, 1)} style={voteBtn(item.vote === 1, '#22c55e')}>▲</button>
            <button type="button" onClick={e => vote(e, -1)} style={voteBtn(item.vote === -1, '#ef4444')}>▼</button>
          </div>
        </div>
      </article>
    )
  }

  // cards (default)
  return (
    <article
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter') onOpen() }}
      style={{
        borderRadius: 14,
        border: `1px solid ${item.is_holdings ? 'rgba(34,197,94,.35)' : 'rgba(148,163,184,.14)'}`,
        borderLeft: `3px solid ${pc}`,
        background: 'linear-gradient(165deg, var(--bg1) 0%, rgba(15,23,42,.55) 100%)',
        padding: '14px 15px',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 9,
        minHeight: 168,
        boxShadow: '0 6px 20px rgba(0,0,0,.16)',
        position: 'relative',
      }}
    >
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: `linear-gradient(90deg, ${tc}, transparent)`,
        borderRadius: '14px 14px 0 0',
      }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 5 }}>
            <button type="button" onClick={toggleStar} style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              color: item.starred ? '#facc15' : 'var(--text3)', fontSize: 14, padding: 0, lineHeight: 1,
            }} title="Star for priority">{item.starred ? '★' : '☆'}</button>
            {item.symbol && (
              <span style={{ fontFamily: 'var(--mono, monospace)', fontWeight: 900, fontSize: 13, color: '#60a5fa' }}>
                {item.symbol}
              </span>
            )}
            <Badge color={catColor}>{catMeta[primary]?.label || primary}</Badge>
            {item.is_holdings && <Badge color="#22c55e">Holding</Badge>}
            {item.is_archived && <Badge color="#64748b">Archived</Badge>}
            <span style={{ fontSize: 9, fontWeight: 800, color: pc, textTransform: 'uppercase' }}>{pri}</span>
          </div>
          <div style={{
            fontSize: 13.5, fontWeight: 800, color: 'var(--text0)', lineHeight: 1.35,
            overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          }}>
            {item.title}
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: 10, fontWeight: 800, color: tc }}>{item.freshness_label || '—'}</div>
          {item.confidence != null && (
            <div style={{ fontSize: 11, color: 'var(--text2)', fontWeight: 700, marginTop: 2 }}>
              {Math.round(Number(item.confidence) * (Number(item.confidence) <= 1 ? 100 : 1))}%
            </div>
          )}
        </div>
      </div>
      <div style={{
        fontSize: 12, color: 'var(--text2)', lineHeight: 1.45, flex: 1,
        overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
      }}>
        {item.summary || item.thesis || '—'}
      </div>
      {(item.needs_refresh || item.data_gaps?.length) && (
        <div style={{ fontSize: 10, color: '#f97316', fontWeight: 700 }}>
          {item.needs_refresh ? '↻ Due for refresh' : ''}
          {item.data_gaps?.length ? ` · Gap: ${item.data_gaps[0].slice(0, 60)}` : ''}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>
          {item.source_system} · {item.research_type || '—'}
          {item.source_count ? ` · ${item.source_count} sources` : ''}
          {item.model ? ` · ${item.model}` : ''}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button type="button" onClick={e => vote(e, 1)} style={voteBtn(item.vote === 1, '#22c55e')} title="Useful">▲</button>
          <button type="button" onClick={e => vote(e, -1)} style={voteBtn(item.vote === -1, '#ef4444')} title="Not useful">▼</button>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa' }}>
            {item.actionability?.slice(0, 28) || 'Open →'}
          </div>
        </div>
      </div>
    </article>
  )
}

function voteBtn(active: boolean, color: string): CSSProperties {
  return {
    fontSize: 11, fontWeight: 900, padding: '2px 6px', borderRadius: 5, cursor: 'pointer',
    border: `1px solid ${active ? color : 'rgba(148,163,184,.3)'}`,
    background: active ? `${color}22` : 'transparent',
    color: active ? color : 'var(--text3)',
  }
}

export default function ResearchIntelligenceHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const [priority, setPriority] = useState<string | null>(null)
  const [holdingsOnly, setHoldingsOnly] = useState(false)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [starredOnly, setStarredOnly] = useState(false)
  const [freshness, setFreshness] = useState<string | null>(null)
  const [sentiment, setSentiment] = useState<string | null>(null)
  const [lane, setLane] = useState<'all' | 'retirement' | 'dividends' | 'macro_sector'>('all')
  const [view, setView] = useState<'cards' | 'list' | 'compact'>('cards')
  const [localPatch, setLocalPatch] = useState<Record<string, Partial<Item>>>({})

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (category) p.set('category', category)
    if (priority) p.set('priority', priority)
    if (holdingsOnly) p.set('holdings_only', '1')
    if (includeArchived) p.set('include_archived', '1')
    if (starredOnly) p.set('starred_only', '1')
    if (freshness) p.set('freshness', freshness)
    if (sentiment) p.set('sentiment', sentiment)
    p.set('limit', '120')
    return p.toString()
  }, [q, category, priority, holdingsOnly, includeArchived, starredOnly, freshness, sentiment])

  const { data, loading, error, refetch } = useApi<any>(
    `/api/v2/research-intelligence?${qs}`,
    90_000,
  )
  const { data: freshData } = useApi<any>('/api/v2/research-intelligence/freshness', 120_000)

  const cats: Cat[] = data?.taxonomy?.categories || []
  const catMeta = useMemo(() => {
    const m: Record<string, Cat> = {}
    for (const c of cats) m[c.id] = c
    return m
  }, [cats])

  const items: Item[] = useMemo(() => {
    const raw: Item[] = data?.items || []
    return raw.map(it => ({ ...it, ...(localPatch[it.id] || {}) }))
  }, [data?.items, localPatch])

  const lanes = data?.priority_lanes || {}
  const stats = data?.stats || {}
  const tierCounts = stats.by_freshness || {}

  const displayItems: Item[] = useMemo(() => {
    if (lane === 'all') return items
    const laneItems = ((lanes[lane] as Item[]) || []).map(it => ({ ...it, ...(localPatch[it.id] || {}) }))
    if (laneItems.length) return laneItems
    if (lane === 'retirement') return items.filter(i => i.primary_category === 'retirement_tax')
    if (lane === 'dividends') return items.filter(i => i.categories?.includes('dividend_income'))
    if (lane === 'macro_sector') {
      return items.filter(i =>
        i.categories?.includes('macro_geo') || i.categories?.includes('sector_thematic'))
    }
    return items
  }, [lane, items, lanes, localPatch])

  const onFeedback = useCallback((id: string, patch: Partial<Item>) => {
    setLocalPatch(prev => ({ ...prev, [id]: { ...(prev[id] || {}), ...patch } }))
  }, [])

  const openItem = (item: Item) => {
    onDrill({
      title: item.symbol ? `${item.symbol} · ${item.title}` : item.title,
      subtitle: [
        item.freshness_label,
        item.primary_category && (catMeta[item.primary_category]?.label || item.primary_category),
        item.priority,
        item.source_system,
        item.actionability,
      ].filter(Boolean).join(' · '),
      endpoint: '/api/v2/research-intelligence',
      rows: [item],
    })
  }

  const staleTopics = freshData?.stale_topics || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Header */}
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
        <div>
          <div style={hubTitle()}>Research Intelligence</div>
          <div style={hubSubtitle(terminalUi)}>
            Professional intelligence desk · freshness · archive · retirement pillar
            {stats.matched != null && ` · ${stats.matched} matched`}
            {loading ? ' · loading…' : ''}
            {data?.version ? ` · v${data.version}` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <Link to="/intelligence?tab=research" style={linkStyle('#94a3b8')}>Legacy Topics →</Link>
          <Link to="/retirement" style={linkStyle('#a855f7')}>Retirement hub →</Link>
          <Link to="/hermes" style={linkStyle('#60a5fa')}>Hermes →</Link>
          <Link to="/portfolio" style={linkStyle('#22c55e')}>Portfolio →</Link>
          <button type="button" onClick={() => refetch()} style={btnStyle}>↻ Refresh</button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8 }}>
        {[
          { l: 'In view', v: String(displayItems.length), c: 'var(--text0)' },
          { l: 'High priority', v: String(stats.high_priority ?? 0), c: '#f59e0b' },
          { l: 'Holdings', v: String(stats.holdings_linked ?? 0), c: '#22c55e' },
          { l: 'Needs refresh', v: String(stats.needs_refresh ?? 0), c: '#f97316' },
          { l: 'Live / Fresh', v: `${tierCounts.live || 0}/${tierCounts.fresh || 0}`, c: '#22c55e' },
          { l: 'Stale topics', v: String(freshData?.stale_topic_count ?? '—'), c: '#a855f7' },
          { l: 'Starred', v: String(stats.starred_in_view ?? 0), c: '#facc15' },
          { l: 'Archive in view', v: String(stats.archived_in_view ?? 0), c: '#64748b' },
        ].map(k => (
          <div key={k.l} style={{
            background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px',
          }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', letterSpacing: '.06em', textTransform: 'uppercase' }}>{k.l}</div>
            <div style={{ fontSize: 17, fontWeight: 900, color: k.c, marginTop: 2 }}>{k.v}</div>
          </div>
        ))}
      </div>

      {/* Priority lanes + view mode */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {([
            ['all', 'All intelligence', '#60a5fa'],
            ['retirement', 'Retirement & tax', '#a855f7'],
            ['dividends', 'Dividends & income', '#22c55e'],
            ['macro_sector', 'Macro / sector', '#f59e0b'],
          ] as const).map(([id, lab, col]) => (
            <Chip
              key={id}
              label={`${lab}${stats.lane_counts?.[id] != null ? ` (${stats.lane_counts[id]})` : ''}`}
              color={col}
              active={lane === id}
              onClick={() => { setLane(id); if (id !== 'all') setCategory(null) }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['cards', 'list', 'compact'] as const).map(v => (
            <Chip key={v} label={v} small active={view === v} onClick={() => setView(v)}
              color="#94a3b8" />
          ))}
        </div>
      </div>

      {/* Filters panel */}
      <div style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 14, padding: 14,
      }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 }}>
          Taxonomy & filters
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          <Chip label="All categories" active={!category} onClick={() => setCategory(null)} />
          {cats.map(c => (
            <Chip
              key={c.id}
              label={`${c.pillar ? '◆ ' : ''}${c.label}${stats.by_category?.[c.id] != null ? ` (${stats.by_category[c.id]})` : ''}`}
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
            placeholder="Search title, thesis, symbol, retirement terms…"
            style={{
              flex: '1 1 240px', minWidth: 200, fontSize: 13, padding: '9px 12px', borderRadius: 9,
              border: '1px solid var(--border)', background: 'var(--bg0)', color: 'var(--text0)',
            }}
          />
          <Chip label="High only" color="#f59e0b" active={priority === 'high'}
            onClick={() => setPriority(priority === 'high' ? null : 'high')} />
          <Chip label="Holdings" color="#22c55e" active={holdingsOnly}
            onClick={() => setHoldingsOnly(v => !v)} />
          <Chip label="★ Starred" color="#facc15" active={starredOnly}
            onClick={() => setStarredOnly(v => !v)} />
          <Chip label="Include archive" color="#64748b" active={includeArchived}
            onClick={() => setIncludeArchived(v => !v)} />
          {(['live', 'fresh', 'aging', 'stale', 'archive'] as const).map(t => (
            <Chip key={t} label={t} small color={TIER_COLOR[t]} active={freshness === t}
              onClick={() => setFreshness(freshness === t ? null : t)} />
          ))}
          {(['bullish', 'bearish', 'neutral'] as const).map(s => (
            <Chip key={s} label={s} small color={SENT_COLOR[s]} active={sentiment === s}
              onClick={() => setSentiment(sentiment === s ? null : s)} />
          ))}
        </div>
      </div>

      {/* Stale monitor alert */}
      {staleTopics.length > 0 && (
        <div style={{
          padding: '10px 14px', borderRadius: 10,
          border: '1px solid rgba(168,85,247,.35)', background: 'rgba(168,85,247,.08)',
          fontSize: 12, color: 'var(--text1)',
        }}>
          <strong style={{ color: '#a855f7' }}>{staleTopics.length} topic monitors due for refresh</strong>
          {' · '}
          {staleTopics.slice(0, 5).map((t: any) => t.topic_id || t.display_name).join(', ')}
          {staleTopics.length > 5 ? '…' : ''}
          <span style={{ color: 'var(--text3)' }}>
            {' '}— run topic_ingestion / research_intelligence_refresh
          </span>
        </div>
      )}

      {error && (
        <div style={{ padding: 12, borderRadius: 10, border: '1px solid rgba(239,68,68,.4)', color: '#ef4444', fontSize: 12 }}>
          Failed to load research intelligence: {error}
        </div>
      )}

      {/* Feed */}
      {loading && !data ? (
        <div style={{ padding: 48, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
          Loading intelligence feed…
        </div>
      ) : displayItems.length === 0 ? (
        <div style={{
          padding: 40, textAlign: 'center', color: 'var(--text3)', fontSize: 12,
          border: '1px dashed var(--border)', borderRadius: 14,
        }}>
          No items match these filters.
          {lane === 'retirement' && (
            <div style={{ marginTop: 8 }}>
              Retirement corpus is building — seed topics via{' '}
              <code>research_intelligence_retirement_seed.py --apply</code> then topic_ingestion.
            </div>
          )}
        </div>
      ) : view === 'compact' ? (
        <div style={{
          background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden',
        }}>
          {displayItems.map(item => (
            <IntelCard key={item.id} item={item} catMeta={catMeta} view={view}
              onOpen={() => openItem(item)} onFeedback={onFeedback} />
          ))}
        </div>
      ) : view === 'list' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {displayItems.map(item => (
            <IntelCard key={item.id} item={item} catMeta={catMeta} view={view}
              onOpen={() => openItem(item)} onFeedback={onFeedback} />
          ))}
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(310px, 1fr))',
          gap: 12,
        }}>
          {displayItems.map(item => (
            <IntelCard key={item.id} item={item} catMeta={catMeta} view={view}
              onOpen={() => openItem(item)} onFeedback={onFeedback} />
          ))}
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--text3)', lineHeight: 1.5 }}>
        {data?.note}
        {' '}API: <code>/api/v2/research-intelligence</code>
        {' · '}Freshness: <code>/api/v2/research-intelligence/freshness</code>
        {' · '}Feedback: <code>POST …/feedback</code>
        {' · '}Policy: <code>config/research_intelligence_freshness.json</code>
        {' · '}Archive never deletes — toggle “Include archive” to search history.
      </div>
    </div>
  )
}

const linkStyle = (c: string): CSSProperties => ({
  fontSize: 11, fontWeight: 700, color: c, textDecoration: 'none',
})

const btnStyle: CSSProperties = {
  fontSize: 11, fontWeight: 800, padding: '5px 10px', borderRadius: 7, cursor: 'pointer',
  border: '1px solid rgba(96,165,250,.45)', background: 'rgba(96,165,250,.12)', color: '#60a5fa',
}

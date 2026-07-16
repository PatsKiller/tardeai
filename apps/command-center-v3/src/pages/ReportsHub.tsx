import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import MorningCommandStrip, { buildStripCells } from '../components/reports/MorningCommandStrip'
import ReportsArchive from '../components/reports/ReportsArchive'
import BriefSectionPanels from '../components/reports/BriefSectionPanels'
import ActionDeck, { buildDeckActions } from '../components/reports/ActionDeck'
import ReportCoverageStrip from '../components/reports/ReportCoverageStrip'
import ReportSearch from '../components/reports/ReportSearch'
import DocxDownloads from '../components/reports/DocxDownloads'
import ReportLibrary from '../components/reports/ReportLibrary'
import AnalystReportsPanel from '../components/reports/AnalystReportsPanel'
import { parseBriefSections, executiveSummaryText, rankedActionLines, SUPER_TABS } from '../components/reports/briefUtils'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab } from '../lib/terminalHubChrome'

// v3 Reports — a COMMAND PORTAL for everything sent to the operator (Telegram / email / SIEM): briefs,
// digests, alerts, advisories, recovery, dividends, regime, paper, system. Visual KPI summary + extracted
// action queue + advanced filters/quick-views + split-pane reader. Every report body stays fully readable
// (Telegram/markdown rendered). Source: /api/v2/reports/* (read-only). Search · filter · paginate · purge.

interface Props { onDrill: (ctx: DrillContext) => void }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }
const SEV: Record<string, string> = { critical: '#dc2626', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }
const sevColor = (s?: string) => SEV[(s || 'info').toLowerCase()] || '#60a5fa'
const fmtDate = (s?: string) => {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) + ' · ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

// Same-origin so report action links open the CURRENT host's page, not a hardcoded tailscale instance
// (the prior absolute host sent every action link to the wrong page when viewed on localhost/another host).
const FQDN = typeof window !== 'undefined' ? window.location.origin : ''
// Backend action urls are absolute (tailscale host baked in for Telegram/email) — strip to a same-origin path.
const relUrl = (u?: string) => (u ? u.replace(/^https?:\/\/[^/]+/, '') : u)
const VALID = new Set(['portfolio', 'risk', 'trading', 'strategy', 'agents', 'intelligence', 'hermes', 'retirement', 'journal', 'watchlist', 'watchpool', 'sectors', 'reports', 'system', 'manual-execution'])
// every legacy/brief page slug → a REAL v3 route + friendly label (no dead links)
const PAGE: Record<string, { label: string; route: string }> = {
  risk: { label: 'Risk', route: '/v3/risk' }, approvals: { label: 'Approvals', route: '/v3/trading' },
  recovery: { label: 'Recovery', route: '/v3/risk' }, reco: { label: 'Recovery', route: '/v3/risk' },   // Recovery Watch lives in the Risk hub
  actions: { label: 'Actions', route: '/v3/' }, trading: { label: 'Trading', route: '/v3/trading' },     // Action Inbox is on Home
  journal: { label: 'Journal', route: '/v3/journal' }, system: { label: 'System', route: '/v3/system' },
  portfolio: { label: 'Portfolio', route: '/v3/portfolio' }, 'research-topics': { label: 'Research', route: '/v3/intelligence' },
  research: { label: 'Research', route: '/v3/intelligence' }, proposals: { label: 'Proposals', route: '/v3/trading' },
  'paper-proposals': { label: 'Proposals', route: '/v3/trading' }, 'paper-status': { label: 'Trading', route: '/v3/trading' },
  alerts: { label: 'System', route: '/v3/system' }, siem: { label: 'System', route: '/v3/system' },
}
function pageLink(path: string) {
  const seg = (path.split('/')[2] || '').toLowerCase()
  if (PAGE[seg]) return PAGE[seg]
  if (VALID.has(seg)) return { label: seg.charAt(0).toUpperCase() + seg.slice(1), route: `/v3/${seg}` }
  return { label: 'Open', route: '/v3/' }   // unknown slug → home, never a dead /v3/<x>
}

// ── markdown/Telegram → React: **bold** *bold* `code`, dashboard links, urls. NOTE: NO _italic_ rule —
// the data is full of snake_case (reentry_candidate, hold_for_reentry) and underscore-italic ate them. ──
// tokens that look like tickers but aren't — don't turn these into per-symbol links
const NOT_TICKER = new Set(['STOP', 'STOPS', 'RISK', 'HEAT', 'NEED', 'ITEM', 'ETF', 'IRA', 'EOD', 'RSI', 'ATR',
  'PNL', 'YTD', 'ET', 'EST', 'EDT', 'AM', 'PM', 'US', 'USD', 'CIO', 'AI', 'NAV', 'CEF', 'OK', 'NO',
  'SELL', 'BUY', 'HOLD', 'ADD', 'TRIM', 'GO', 'WAIT'])
// Per-ticker deep-link in the report body. `sym` = the line's leading ticker (RTX:/CACI:) so its page link
// carries ?symbol=. `riskLine` = a stop/triggered line → also turn each ticker token into a /v3/risk?symbol=X
// link, so "8 stops TRIGGERED: PFLT, LHX, LMT…" gives one-click access to EACH position (operator ask).
function inline(text: string, sym?: string, riskLine?: boolean): ReactNode[] {
  const parts: ReactNode[] = []
  const re = riskLine
    ? /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|https?:\/\/[^\s)]+|\/v[23]\/[a-z0-9-]+|\b[A-Z]{2,5}\b)/g
    : /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|https?:\/\/[^\s)]+|\/v[23]\/[a-z0-9-]+)/g
  let last = 0, m: RegExpExecArray | null, key = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**')) parts.push(<b key={key++} style={{ color: 'var(--text0)', fontWeight: 800 }}>{tok.slice(2, -2)}</b>)
    else if (tok.startsWith('*')) parts.push(<b key={key++} style={{ color: 'var(--text0)', fontWeight: 800 }}>{tok.slice(1, -1)}</b>)
    else if (tok.startsWith('`')) parts.push(<code key={key++} style={{ fontFamily: 'monospace', fontSize: '.92em', background: 'var(--bg0)', padding: '1px 5px', borderRadius: 4, color: '#a5d6ff' }}>{tok.slice(1, -1)}</code>)
    else if (tok.startsWith('/v')) { const { label, route } = pageLink(tok); const r = sym && /\/v3\/(risk|trading|portfolio)/.test(route) ? `${route}?symbol=${sym}` : route; parts.push(<a key={key++} href={FQDN + r} target="_blank" rel="noreferrer" style={{ fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 4, background: '#60a5fa18', color: '#60a5fa', textDecoration: 'none', whiteSpace: 'nowrap' }}>{label}{sym ? ` ${sym}` : ''} ↗</a>) }
    else if (riskLine && /^[A-Z]{2,5}$/.test(tok) && !NOT_TICKER.has(tok)) { parts.push(<a key={key++} href={FQDN + `/v3/risk?symbol=${tok}`} target="_blank" rel="noreferrer" title={`open ${tok} risk / stop`} style={{ color: '#60a5fa', fontWeight: 700, fontFamily: 'monospace', textDecoration: 'none', borderBottom: '1px dotted #60a5fa66' }}>{tok}</a>) }
    else parts.push(<a key={key++} href={tok} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', wordBreak: 'break-all' }}>{tok}</a>)
    last = m.index + tok.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}
// the line's leading ticker ("RTX: …", "- CACI: …") and whether it's a stop/risk line
const lineSym = (t: string): string | undefined => (t.match(/^[•\-▪◦·*\s]*\d*\.?\s*([A-Z]{2,5}):/) || [])[1]
const isRiskLine = (t: string): boolean => /\bstop|\btrigger|unprotected|protective|stop-?loss/i.test(t)

function Article({ text }: { text: string }) {
  const lines = (text || '').split('\n')
  return (
    <div style={{ fontSize: 13.5, color: 'var(--text1)', lineHeight: 1.65 }}>
      {lines.map((line, i) => {
        const t = line.trim()
        if (!t) return <div key={i} style={{ height: 9 }} />
        if (/^---+$/.test(t)) return <hr key={i} style={{ border: 'none', borderTop: '1px solid var(--border-subtle)', margin: '12px 0' }} />
        const md = t.match(/^(#{1,4})\s+(.*)$/)                 // markdown header  # / ## / ###
        const tg = /^\*[^*]+\*$/.test(t) || /^[A-Z][A-Z \/&0-9]{3,}:?$/.test(t)   // *SECTION* or ALLCAPS
        if (md || tg) {
          const lvl = md ? md[1].length : 2
          const label = (md ? md[2] : t).replace(/^\*|\*$/g, '').replace(/^#+\s*/, '')
          const sid = sectionIdOf(label)
          return <div key={i} id={sid ? `rsec-${sid}` : undefined} style={{ scrollMarginTop: 12, fontSize: lvl <= 1 ? 16 : lvl === 2 ? 12.5 : 11.5, fontWeight: 900, letterSpacing: lvl >= 2 ? .4 : 0, textTransform: lvl >= 2 ? 'uppercase' : 'none', color: lvl <= 1 ? 'var(--text0)' : '#60a5fa', marginTop: i ? 14 : 0, marginBottom: 4 }}>{inline(label)}</div>
        }
        const bul = t.match(/^[•\-▪◦·*]\s+(.*)$/)
        if (bul) return <div key={i} style={{ display: 'flex', gap: 8, paddingLeft: 4, marginBottom: 3 }}><span style={{ color: 'var(--text3)' }}>•</span><span style={{ flex: 1 }}>{inline(bul[1], lineSym(bul[1]), isRiskLine(bul[1]))}</span></div>
        const num = t.match(/^(\d+)\.\s+(.*)$/)
        if (num) return <div key={i} style={{ display: 'flex', gap: 8, paddingLeft: 4, marginBottom: 3 }}><span style={{ color: '#60a5fa', fontWeight: 800 }}>{num[1]}.</span><span style={{ flex: 1 }}>{inline(num[2], lineSym(num[2]), isRiskLine(num[2]))}</span></div>
        return <div key={i} style={{ marginBottom: 3 }}>{inline(line, lineSym(t), isRiskLine(t))}</div>
      })}
    </div>
  )
}

// ── small visual primitives ──────────────────────────────────────────────────────────────────────────
function SeverityBadge({ sev }: { sev?: string }) {
  const c = sevColor(sev)
  return <span style={{ fontSize: 9.5, fontWeight: 800, padding: '2px 7px', borderRadius: 5, background: c + '22', color: c, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{sev || 'info'}</span>
}

// ── quick views: predicate over a list item + matching action classes / severities ────────────────────
const RISK_CLASSES = ['stop_triggered', 'unprotected_position', 'risk_review']
const SYSTEM_CLASSES = ['system_health', 'cron_or_backup', 'llm_review']
type QV = '' | 'today' | 'needs_action' | 'risk' | 'approvals' | 'hermes' | 'system' | 'critical'
type HubMode = 'library' | 'brief' | 'archive' | 'analyst'
const isToday = (s?: string) => { if (!s) return false; const d = new Date(s); const n = new Date(); return d.toDateString() === n.toDateString() }
function qvMatchesItem(qv: QV, it: any): boolean {
  const cls: string[] = it.action_classes || []
  switch (qv) {
    case '': return true
    case 'today': return isToday(it.created_at)
    case 'needs_action': return !!it.has_actions
    case 'risk': return cls.some(c => RISK_CLASSES.includes(c))
    case 'approvals': return cls.includes('approval_needed') || cls.includes('broker_manual')
    case 'hermes': return cls.includes('hermes_review')
    case 'system': return cls.some(c => SYSTEM_CLASSES.includes(c))
    case 'critical': return ['urgent', 'critical'].includes((it.severity || '').toLowerCase())
    default: return true
  }
}
// ── Reader "Key sections": recognized markdown headers → anchor ids in Article body ──
const SECTIONS = [
  { id: 'exec', label: 'Executive Summary', rx: /executive summary/i },
  { id: 'risk', label: 'Immediate Risk', rx: /immediate risk/i },
  { id: 'steph', label: 'Steph Review', rx: /steph review/i },
  { id: 'recovery', label: 'Recovery Watch', rx: /recovery watch/i },
  { id: 'next', label: 'Ranked Next Actions', rx: /ranked next action/i },
]
const sectionIdOf = (text: string): string | undefined => SECTIONS.find(s => s.rx.test(text))?.id

export default function ReportsHub({ onDrill }: Props) {
  void onDrill
  const [terminalUi] = useTerminalUi()
  const { data: cats } = useApi<any>('/api/v2/reports/categories', 60_000)
  const categories = cats?.categories || []
  const [mode, setMode] = useState<HubMode>(() => {
    try {
      const q = new URLSearchParams(window.location.search)
      const m = (q.get('mode') || '').trim().toLowerCase()
      if (m === 'analyst' || m === 'archive' || m === 'brief' || m === 'library') return m as HubMode
      const sym = (q.get('symbol') || '').trim()
      const typ = (q.get('type') || '').trim()
      if (q.get('generate') === '1' || (sym && typ.startsWith('symbol_'))) return 'analyst'
    } catch { /* ignore */ }
    return 'library'
  })
  const [superTab, setSuperTab] = useState('briefs')
  const [active, setActive] = useState<string>('morning_briefs')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [days, setDays] = useState<number | ''>(7)
  const [qv, setQv] = useState<QV>('')
  const [purge, setPurge] = useState(false)
  const [selId, setSelId] = useState<string | null>(null)
  const [briefExpanded, setBriefExpanded] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [searchQ, setSearchQ] = useState('')

  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const briefListPath = '/api/v2/reports/list?category=morning_briefs&page=1&per_page=10&days=1'
  const { data: briefList } = useApi<any>(briefListPath, 0)

  useEffect(() => { const t = setTimeout(() => { setQ(qInput); setPage(1) }, 350); return () => clearTimeout(t) }, [qInput])
  useEffect(() => { const t = setTimeout(() => setSearchQ(searchInput), 350); return () => clearTimeout(t) }, [searchInput])
  useEffect(() => {
    const grp = SUPER_TABS.find(s => s.key === superTab)
    if (grp && !grp.categories.includes(active)) setActive(grp.categories[0])
  }, [superTab]) // eslint-disable-line
  useEffect(() => { setPage(1) }, [active, days, q])
  useEffect(() => { setSelId(null) }, [active, days, q, page])

  const effDays = qv === 'today' ? 1 : days
  const summaryPath = `/api/v2/reports/portal-summary?days=${effDays || 7}`
  const { data: summary } = useApi<any>(summaryPath, 0)
  // Action Queue (Phase 2): fetch the FULL extracted set; the AQ has its own Now/Risk/Approvals/System/
  // Research/All tabs (independent of the page quick-views, which filter the report LIST). This is what
  // lets the queue default to a small "Now" set instead of hundreds of rows.
  const actionsPath = `/api/v2/reports/action-items?days=${effDays || 7}&limit=1000`
  const { data: actionsData } = useApi<any>(actionsPath, 0)
  const listPath = useMemo(() =>
    `/api/v2/reports/list?category=${active}&q=${encodeURIComponent(q)}&page=${page}&per_page=15${effDays ? `&days=${effDays}` : ''}`,
    [active, q, page, effDays])
  const { data: list, loading } = useApi<any>(listPath, 0)

  const rawItems = list?.items || []
  const items = useMemo(() => rawItems.filter((it: any) => qvMatchesItem(qv, it)), [rawItems, qv])
  const total = list?.total ?? 0
  const pages = list?.pages ?? 1
  const activeCat = categories.find((c: any) => c.key === active)

  // auto-select first result when nothing selected
  const selected = useMemo(() => items.find((it: any) => `${it.source}-${it.id}` === selId) || items[0] || null, [items, selId])
  const allActions = actionsData?.actions || []
  const reportActions = useMemo(() => {
    if (!selected) return []
    const rid = `${selected.source}-${selected.id}`, seen = new Set<string>()
    return allActions.filter((a: any) => a.report_id === rid).filter((a: any) => { if (seen.has(a.action_class)) return false; seen.add(a.action_class); return true })
  }, [selected, allActions])

  const k = summary?.kpis || {}

  const archiveCategories = useMemo(() => {
    const grp = SUPER_TABS.find(s => s.key === superTab)
    if (!grp) return categories
    return categories.filter((c: any) => grp.categories.includes(c.key))
  }, [categories, superTab])

  const todayBriefs: any[] = briefList?.items || []
  const aegisBrief = useMemo(() => todayBriefs.find((b: any) => (b.type || '').includes('aegis')) || todayBriefs[0] || null, [todayBriefs])
  const tradeAiBrief = useMemo(() => todayBriefs.find((b: any) => (b.type || '').includes('trade_ai')), [todayBriefs])
  const todayBrief: any = aegisBrief
  const unifiedBriefBody = useMemo(() => {
    const parts: string[] = []
    if (aegisBrief?.summary) parts.push(`*Aegis Morning Brief*\n${aegisBrief.summary}`)
    if (tradeAiBrief?.summary) parts.push(`*Trade AI Morning Brief*\n${tradeAiBrief.summary}`)
    return parts.join('\n\n---\n\n')
  }, [aegisBrief, tradeAiBrief])
  const briefBody = unifiedBriefBody || todayBrief?.summary || ''
  // Staleness guard — briefs snapshot portfolio/risk figures at generation time (created_at from
  // /api/v2/reports/list). Re-check every minute so a page left open still warns honestly.
  const [nowTs, setNowTs] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNowTs(Date.now()), 60_000)
    return () => window.clearInterval(t)
  }, [])
  const briefGeneratedAt: string | undefined = aegisBrief?.created_at || tradeAiBrief?.created_at
  const briefAgeMin = useMemo(() => {
    if (!briefGeneratedAt) return null
    const ms = nowTs - new Date(briefGeneratedAt).getTime()
    return Number.isFinite(ms) ? Math.floor(ms / 60_000) : null
  }, [briefGeneratedAt, nowTs])
  const briefIsStale = briefAgeMin != null && briefAgeMin > 120
  const briefSections = useMemo(() => parseBriefSections(briefBody), [briefBody])
  const briefExec = useMemo(() => executiveSummaryText(briefBody), [briefBody])
  const todayBriefActions = useMemo(() => {
    const briefs = [aegisBrief, tradeAiBrief].filter(Boolean)
    if (!briefs.length) return []
    const ridSet = new Set(briefs.map((b: any) => `${b.source}-${b.id}`))
    const seen = new Map<string, any>()
    for (const a of allActions.filter((x: any) => ridSet.has(x.report_id))) {
      const norm = (a.text || '').toLowerCase().replace(/[$%,]/g, '').replace(/\d+(\.\d+)?/g, '#').replace(/\s+/g, ' ').trim().slice(0, 80)
      const key = `${(a.symbol || '').toUpperCase()}|${a.action_class}|${norm}`
      const ex = seen.get(key)
      if (!ex) seen.set(key, { ...a, _classes: [a.action_class] })
      else if (a.action_class && !ex._classes.includes(a.action_class)) ex._classes.push(a.action_class)
    }
    return [...seen.values()]
  }, [aegisBrief, tradeAiBrief, allActions])
  const positions = risk?.positions || []
  const deckActions = useMemo(() => buildDeckActions({
    briefActions: todayBriefActions,
    triggeredPositions: positions.filter((p: any) => p.triggered).map((p: any) => ({
      symbol: p.symbol, stop_price: p.stop_price ?? p.stop, market_value: p.market_value,
    })),
    rankedLines: rankedActionLines(briefBody),
    cap: 8,
  }), [todayBriefActions, positions, briefBody])
  const triggeredN = positions.filter((p: any) => p.triggered).length
  const unprotN = positions.filter((p: any) => !p.stop_price && !p.triggered).length
  const stripCells = buildStripCells({
    portfolioValue: overview?.portfolio_value,
    todayChange: overview?.today_change,
    heatPct: risk?.portfolio_heat_pct,
    triggeredCount: triggeredN,
    unprotectedCount: unprotN,
    regimeLabel: regime?.regime_label,
    vix: tradeAi?.vix,
    onRisk: () => { window.open(FQDN + '/v3/risk', '_blank') },
    onPortfolio: () => { window.open(FQDN + '/v3/portfolio', '_blank') },
  })

  const modeBtn = (m: HubMode, label: string) => {
    const on = mode === m
    return (
      <button key={m} onClick={() => setMode(m)} style={hubTab(on, terminalUi)}>{label}</button>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1480, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ ...hubTitle(), margin: 0 }}>
          {mode === 'library' ? 'Report Library' : mode === 'brief' ? 'Morning Brief' : mode === 'analyst' ? 'Analyst Reports' : 'Report Archive'}
        </h1>
        <span style={hubSubtitle(terminalUi)}>
          {mode === 'library'
            ? 'every report the system produces — cadence lanes · freshness rails · in-page viewer'
            : mode === 'brief'
            ? (todayBrief ? fmtDate(todayBrief.created_at) : 'loading today\'s brief…')
            : mode === 'analyst'
              ? 'analyst-grade reports · Word/PDF export · intelligence deep dives'
              : 'searchable operator reports, alerts, and advisories'}
        </span>
        <span style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: 6 }}>
          {modeBtn('library', 'Library')}
          {modeBtn('brief', "Today's Brief")}
          {modeBtn('analyst', 'Analyst Reports')}
          {modeBtn('archive', 'Archive')}
        </div>
      </div>

      {/* Global search — all Telegram / email / SIEM / ai_reports stores */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          placeholder="Search all reports (symbol, topic, retirement, weekly…)…"
          style={{ flex: 1, fontSize: 12, padding: '8px 12px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text0)' }}
        />
        {searchInput && (
          <button onClick={() => { setSearchInput(''); setSearchQ('') }} style={{ fontSize: 10, fontWeight: 700, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text3)', cursor: 'pointer' }}>Clear</button>
        )}
      </div>
      {searchQ && (
        <ReportSearch
          query={searchQ}
          onSelect={(it) => { setMode('archive'); setActive(it.category || 'morning_briefs'); setSelId(`${it.source}-${it.id}`); setSearchInput(''); setSearchQ('') }}
          onArchive={() => { setMode('archive'); setQInput(searchQ); setQ(searchQ); setSearchInput(''); setSearchQ('') }}
        />
      )}

      {mode === 'library' && !searchQ && <LibraryMode />}

      {mode === 'analyst' && !searchQ && (
        <AnalystReportsPanel />
      )}

      {mode === 'brief' && !searchQ && (
        <>
      <ReportCoverageStrip categories={categories} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <MorningCommandStrip cells={stripCells} />
          {!aegisBrief && !tradeAiBrief ? (
            <div style={{ ...card, padding: 32, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
              No morning brief for today yet. Check Archive → Morning Briefs, or wait for the daily Aegis cron (System → Jobs).
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ fontSize: 15, fontWeight: 900, color: 'var(--text0)' }}>Unified Morning Intelligence</div>
                {aegisBrief && <SeverityBadge sev={aegisBrief.severity} />}
                {tradeAiBrief && <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 5, background: '#60a5fa18', color: '#60a5fa' }}>Aegis + Trade AI</span>}
                {(aegisBrief?.has_actions || tradeAiBrief?.has_actions) && (
                  <span style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b' }}>
                    {(aegisBrief?.action_count || 0) + (tradeAiBrief?.action_count || 0)} actions
                  </span>
                )}
              </div>
              {(aegisBrief || tradeAiBrief) && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 9, color: 'var(--text3)' }}>
                  {aegisBrief && <span>🛡 Aegis · {fmtDate(aegisBrief.created_at)}</span>}
                  {tradeAiBrief && <span>📊 Trade AI · {fmtDate(tradeAiBrief.created_at)}</span>}
                </div>
              )}
              {briefIsStale && briefGeneratedAt && (
                <div style={{
                  ...card, padding: '10px 14px', fontSize: 12, fontWeight: 600, color: '#f59e0b',
                  border: '1px solid rgba(245,158,11,.5)', background: 'rgba(245,158,11,.08)',
                }}>
                  ⚠ This brief was generated {briefAgeMin}m ago at {new Date(briefGeneratedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}. Portfolio and risk figures reflect that snapshot, not live data.
                </div>
              )}
              <BriefSectionPanels sections={briefSections} executiveFallback={briefExec} />
              <DocxDownloads itemDocx={aegisBrief?.docx_file || tradeAiBrief?.docx_file} />
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
                  <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>Your action list</div>
                  <span style={{ fontSize: 10, color: 'var(--text3)' }}>{deckActions.length} item{deckActions.length === 1 ? '' : 's'} · today&apos;s brief + live stops</span>
                </div>
                <ActionDeck actions={deckActions} />
              </div>
              {briefBody.length > 400 && (
                <div style={{ ...card, padding: '12px 16px' }}>
                  <button onClick={() => setBriefExpanded(e => !e)} style={{ fontSize: 11, fontWeight: 700, padding: 0, border: 'none', background: 'transparent', color: '#60a5fa', cursor: 'pointer' }}>
                    {briefExpanded ? '▲ Hide full report' : '▼ Full report (Telegram markdown)'}
                  </button>
                  {briefExpanded && <div style={{ marginTop: 12 }}><Article text={briefBody} /></div>}
                </div>
              )}
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                Also on Home → Morning Command · Archive for historical briefs
              </div>
            </>
          )}
        </div>
        </>
      )}

      {mode === 'archive' && !searchQ && (
        <ReportsArchive
          categories={categories}
          superTab={superTab}
          setSuperTab={setSuperTab}
          active={active}
          setActive={setActive}
          archiveCategories={archiveCategories}
          activeCat={activeCat}
          qInput={qInput}
          setQInput={setQInput}
          days={days}
          setDays={setDays}
          qv={qv}
          setQv={setQv}
          items={items}
          rawItems={rawItems}
          loading={loading}
          total={total}
          pages={pages}
          page={page}
          setPage={setPage}
          selId={selId}
          setSelId={setSelId}
          selected={selected}
          kpis={k}
          effDays={effDays}
          reportActions={reportActions}
          fmtDate={fmtDate}
          renderArticle={(text) => <Article text={text} />}
          onPurge={() => setPurge(true)}
          onStatClick={(newQv) => setQv(newQv)}
        />
      )}

      {purge && <PurgeModal category={active} categoryLabel={activeCat?.label || ''} onClose={() => setPurge(false)} />}
    </div>
  )
}

function PurgeModal({ category, categoryLabel, onClose }: { category: string; categoryLabel: string; onClose: () => void }) {
  const [olderThan, setOlderThan] = useState(90)
  const [scope, setScope] = useState<'category' | 'all'>('category')
  const [preview, setPreview] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<any>(null)
  const run = async (apply: boolean) => {
    setBusy(true)
    try {
      const b: any = { older_than_days: olderThan, apply }
      if (scope === 'category') b.category = category
      const r = await fetch('/api/v2/reports/purge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(x => x.json())
      if (apply) setDone(r); else setPreview(r)
    } finally { setBusy(false) }
  }
  useEffect(() => { run(false) }, [olderThan, scope]) // eslint-disable-line
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ ...card, padding: 18, width: 'min(440px,94vw)', border: '1px solid #ef444466' }}>
        <div style={{ fontSize: 14, fontWeight: 900, color: '#f87171' }}>🗑 Purge old reports</div>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 8 }}>Delete reports older than <b style={{ color: 'var(--text0)' }}>{olderThan} days</b> in:</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          {([['category', categoryLabel], ['all', 'All categories']] as any).map(([v, l]: any) => (
            <button key={v} onClick={() => setScope(v)} style={{ fontSize: 11, fontWeight: 700, padding: '5px 10px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${scope === v ? '#ef4444' : 'var(--border)'}`, background: scope === v ? '#ef444418' : 'transparent', color: scope === v ? '#f87171' : 'var(--text2)' }}>{l}</button>
          ))}
        </div>
        <input type="range" min={7} max={365} value={olderThan} onChange={e => setOlderThan(Number(e.target.value))} style={{ width: '100%', marginTop: 12, accentColor: '#ef4444' }} />
        <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 8 }}>
          {done ? <span style={{ color: '#22c55e' }}>✓ Deleted {done.total} report(s).</span>
            : preview ? <>Would delete <b style={{ color: '#f87171' }}>{preview.total}</b> report(s).</>
              : 'calculating…'}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ fontSize: 11, padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>{done ? 'close' : 'cancel'}</button>
          {!done && <button disabled={busy || !preview?.total} onClick={() => run(true)} style={{ fontSize: 11, fontWeight: 800, padding: '6px 16px', borderRadius: 6, border: 'none', background: preview?.total ? '#dc2626' : 'var(--bg2)', color: preview?.total ? '#fff' : 'var(--text3)', cursor: preview?.total ? 'pointer' : 'not-allowed' }}>{busy ? '…' : `Delete ${preview?.total || 0}`}</button>}
        </div>
      </div>
    </div>
  )
}


// WS-A: light wrapper — fetches only the catalog (not the heavy /api/v2/reports aggregate)
function LibraryMode() {
  const { data } = useApi<any>('/api/v2/reports/catalog', 300_000)
  return <ReportLibrary catalog={data?.catalog} />
}

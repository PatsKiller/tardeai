import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import SynthesizedReportCard from '../components/SynthesizedReportCard'

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

const CLASS_LABEL: Record<string, string> = {
  stop_triggered: 'Stop triggered', unprotected_position: 'Unprotected', risk_review: 'Risk',
  approval_needed: 'Approval', broker_manual: 'Broker manual', portfolio_review: 'Portfolio',
  research_needed: 'Research', hermes_review: 'Hermes', system_health: 'System',
  cron_or_backup: 'Cron/Backup', llm_review: 'LLM', informational: 'Info',
}
const CLASS_COLOR: Record<string, string> = {
  stop_triggered: '#ef4444', unprotected_position: '#ef4444', risk_review: '#f59e0b',
  approval_needed: '#a855f7', broker_manual: '#a855f7', portfolio_review: '#eab308',
  research_needed: '#14b8a6', hermes_review: '#14b8a6', system_health: '#60a5fa',
  cron_or_backup: '#60a5fa', llm_review: '#60a5fa', informational: 'var(--text3)',
}
function ActionPill({ cls }: { cls: string }) {
  const c = CLASS_COLOR[cls] || '#60a5fa'
  return <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 7px', borderRadius: 4, background: c + '1c', color: c, whiteSpace: 'nowrap' }}>{CLASS_LABEL[cls] || cls}</span>
}

function MiniBarChart({ rows, color }: { rows: { label: string; value: number; color?: string }[]; color?: string }) {
  const max = Math.max(1, ...rows.map(r => r.value))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ fontSize: 10, color: 'var(--text2)', width: 78, flexShrink: 0, textAlign: 'right', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.label}</span>
          <div style={{ flex: 1, height: 9, background: 'var(--bg2)', borderRadius: 5, overflow: 'hidden' }}>
            <div style={{ width: `${(r.value / max) * 100}%`, height: '100%', background: r.color || color || '#60a5fa', borderRadius: 5 }} />
          </div>
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', width: 30, textAlign: 'right' }}>{r.value}</span>
        </div>
      ))}
    </div>
  )
}

// ── quick views: predicate over a list item + matching action classes / severities ────────────────────
const RISK_CLASSES = ['stop_triggered', 'unprotected_position', 'risk_review']
const SYSTEM_CLASSES = ['system_health', 'cron_or_backup', 'llm_review']
type QV = '' | 'today' | 'needs_action' | 'risk' | 'approvals' | 'hermes' | 'system' | 'critical'
const QUICK_VIEWS: { key: QV; label: string }[] = [
  { key: '', label: 'All' }, { key: 'today', label: 'Today' }, { key: 'needs_action', label: 'Needs action' },
  { key: 'risk', label: 'Risk / Stops' }, { key: 'approvals', label: 'Approvals' }, { key: 'hermes', label: 'Hermes' },
  { key: 'system', label: 'System' }, { key: 'critical', label: 'Critical' },
]
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
// ── Action Queue tabs (Phase 2): the right rail defaults to a small actionable "Now" set, not hundreds ──
const APPROVAL_CLASSES = ['approval_needed', 'broker_manual']
const RESEARCH_CLASSES = ['research_needed', 'hermes_review', 'portfolio_review']
type AQTab = 'now' | 'risk' | 'approvals' | 'system' | 'research' | 'all'
const AQ_TABS: { key: AQTab; label: string }[] = [
  { key: 'now', label: 'Now' }, { key: 'risk', label: 'Risk' }, { key: 'approvals', label: 'Approvals' },
  { key: 'system', label: 'System' }, { key: 'research', label: 'Research' }, { key: 'all', label: 'All' },
]
function aqMatch(tab: AQTab, a: any): boolean {
  const cls: string[] = a._classes || (a.action_class ? [a.action_class] : [])
  const urgent = ['urgent', 'critical'].includes((a.severity || '').toLowerCase())
  const has = (set: string[]) => cls.some(c => set.includes(c))
  switch (tab) {
    case 'all': return true
    case 'risk': return has(RISK_CLASSES)
    case 'approvals': return has(APPROVAL_CLASSES)
    case 'system': return has(SYSTEM_CLASSES)
    case 'research': return has(RESEARCH_CLASSES)
    case 'now': return urgent || isToday(a.created_at) || has([...RISK_CLASSES, ...APPROVAL_CLASSES, ...SYSTEM_CLASSES])
    default: return true
  }
}

// ── Reader "Key sections" (Phase 4): recognized markdown headers → anchor chips that scroll the body ──
const SECTIONS = [
  { id: 'exec', label: 'Executive Summary', rx: /executive summary/i },
  { id: 'risk', label: 'Immediate Risk', rx: /immediate risk/i },
  { id: 'steph', label: 'Steph Review', rx: /steph review/i },
  { id: 'recovery', label: 'Recovery Watch', rx: /recovery watch/i },
  { id: 'next', label: 'Ranked Next Actions', rx: /ranked next action/i },
]
const sectionIdOf = (text: string): string | undefined => SECTIONS.find(s => s.rx.test(text))?.id

// "What matters" briefing groups (Phase 4) — the selected report's actions grouped by canonical target_type,
// each a one-click exact deep-link. Order = operator priority.
const WM_GROUPS: { tt: string; label: string; c: string }[] = [
  { tt: 'risk_stop', label: 'Immediate risk', c: '#ef4444' },
  { tt: 'approval', label: 'Approvals', c: '#f59e0b' },
  { tt: 'recovery', label: 'Recovery', c: '#a855f7' },
  { tt: 'research', label: 'Research', c: '#14b8a6' },
  { tt: 'system', label: 'System', c: '#60a5fa' },
  { tt: 'hermes', label: 'Hermes', c: '#22d3ee' },
  { tt: 'portfolio', label: 'Portfolio', c: '#eab308' },
]

// Reader synthesis strip — surfaces the enriched fields (sector / trend / finance / retirement / ensemble
// votes) that reports_portal now attaches per item. Only renders the facets that actually exist (honest).
const TREND_C = (t?: string) => /bull|up|strong/i.test(t || '') ? '#22c55e' : /bear|down|weak/i.test(t || '') ? '#ef4444' : '#a855f7'
function SynthStrip({ it }: { it: any }) {
  const fin = it.finance_score == null ? null : Math.round(it.finance_score)
  const en = it.ensemble
  const chips: ReactNode[] = []
  const C = (key: string, label: string, color: string) => chips.push(
    <span key={key} style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: color + '18', color }}>{label}</span>)
  if (it.sector) C('sec', it.sector, '#94a3b8')
  if (it.trend) C('tr', it.trend, TREND_C(it.trend))
  if (fin != null && fin >= 28) C('fin', `finance ${fin}`, fin >= 70 ? '#22c55e' : '#60a5fa')
  if (it.retirement_relevance) C('ret', `retire ${it.retirement_relevance}`, it.retirement_relevance === 'high' ? '#f59e0b' : '#94a3b8')
  if (en && en.decision) C('en', `ensemble ${en.decision}${en.score != null ? ` ${en.score}` : ''}${en.lanes?.length ? ` · ${en.lanes.join('/')}` : ''}`, en.decision === 'approve' ? '#22c55e' : '#ef4444')
  if (!chips.length) return null
  return <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 9 }}>{chips}</div>
}

function Kpi({ label, value, color, active, onClick, sub, strong }: { label: string; value: number | string; color?: string; active?: boolean; onClick?: () => void; sub?: string; strong?: boolean }) {
  // strong = higher visual priority (Risk/Stops, Approvals): persistent tinted border + left rail.
  const c = color || '#60a5fa'
  return (
    <div onClick={onClick} style={{
      ...card, padding: '11px 13px', cursor: onClick ? 'pointer' : 'default',
      borderColor: active ? c : strong ? c + '66' : 'var(--border)',
      borderLeft: strong ? `4px solid ${c}` : (card as any).border,
      background: active ? c + '18' : strong ? c + '0b' : 'var(--bg1)',
    }}>
      <div style={{ fontSize: 23, fontWeight: 900, color: color || 'var(--text0)', lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 10, color: strong ? c : 'var(--text2)', marginTop: 3, textTransform: 'uppercase', letterSpacing: .3, fontWeight: 800 }}>{label}</div>
      {sub && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export default function ReportsHub({ onDrill }: Props) {
  void onDrill
  const { data: cats } = useApi<any>('/api/v2/reports/categories', 60_000)
  const categories = cats?.categories || []
  const [active, setActive] = useState<string>('morning_briefs')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [days, setDays] = useState<number | ''>(7)
  const [qv, setQv] = useState<QV>('')
  const [purge, setPurge] = useState(false)
  const [selId, setSelId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [aqTab, setAqTab] = useState<AQTab>('now')   // Action Queue defaults to the actionable "Now" set

  useEffect(() => { const t = setTimeout(() => { setQ(qInput); setPage(1) }, 350); return () => clearTimeout(t) }, [qInput])
  useEffect(() => { setPage(1) }, [active, days, q])
  useEffect(() => { setSelId(null); setExpanded(false) }, [active, days, q, page])

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
  const allActions = actionsData?.actions || []   // raw extracted (full set); AQ tabs filter the deduped view
  // the selected report's own actions (one per class) for the "What matters" briefing block
  const reportActions = useMemo(() => {
    if (!selected) return []
    const rid = `${selected.source}-${selected.id}`, seen = new Set<string>()
    return allActions.filter((a: any) => a.report_id === rid).filter((a: any) => { if (seen.has(a.action_class)) return false; seen.add(a.action_class); return true })
  }, [selected, allActions])
  // Dedup: one underlying item emits the SAME symbol+text under several action_classes (e.g. an RTX recovery
  // escalation shows as Stop-triggered + Unprotected + System). Collapse to one row, merging the classes
  // into pills and keeping the highest severity — so the queue isn't 3× the same line.
  const sevRank = (s: string) => ({ urgent: 4, critical: 4, warning: 2, info: 1 } as any)[(s || '').toLowerCase()] || 0
  const dedupedActions = useMemo(() => {
    const seen = new Map<string, any>()
    for (const a of allActions) {
      // Normalize volatile numbers ($ amounts, %, counts) out of the key so the SAME recurring advisory
      // re-emitted daily — "Portfolio $1.28M … 8 stops triggered, 7 unprotected" vs the next day's
      // "$1.26M … 6 stops triggered" — collapses to ONE card (the most recent) instead of 7 near-identical
      // rows flooding the queue. Distinct symbols keep distinct keys.
      const norm = (a.text || '').toLowerCase().replace(/[$%,]/g, '').replace(/\d+(\.\d+)?/g, '#').replace(/\s+/g, ' ').trim().slice(0, 90)
      const key = `${(a.symbol || '').toUpperCase()}|${norm}`
      const ex = seen.get(key)
      if (!ex) { seen.set(key, { ...a, _classes: [a.action_class], _dupes: 1 }) }
      else {
        ex._dupes++
        if (a.action_class && !ex._classes.includes(a.action_class)) ex._classes.push(a.action_class)
        if (sevRank(a.severity) > sevRank(ex.severity)) ex.severity = a.severity
        if (sevRank(a.severity) >= sevRank(ex.severity)) { ex.route = a.route; ex.route_label = a.route_label; ex.target = a.target }
      }
    }
    return [...seen.values()]
  }, [allActions])
  // AQ tab filter + cap (Now is capped at 12 priority items; other tabs show up to 40). sev-then-recency order.
  const aqRank = (a: any) => sevRank(a.severity) * 1e13 + (Date.parse(a.created_at || '') || 0)
  const aqFiltered = useMemo(() => dedupedActions.filter((a: any) => aqMatch(aqTab, a)).sort((x: any, y: any) => aqRank(y) - aqRank(x)), [dedupedActions, aqTab])
  const aqCap = aqTab === 'now' ? 12 : 40
  const aqShown = aqFiltered.slice(0, aqCap)

  const k = summary?.kpis || {}
  const sevRows = Object.entries(summary?.by_severity || {}).map(([label, value]: any) => ({ label, value, color: sevColor(label) }))
    .sort((a: any, b: any) => b.value - a.value)
  const catRows = (summary?.by_category || []).slice(0, 7).map((c: any) => ({ label: c.label, value: c.count }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1480, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: 20, fontWeight: 900, color: 'var(--text0)', margin: 0 }}>Reports Command Portal</h1>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>operator reports, actions, briefings, alerts, and advisories</span>
        <span style={{ flex: 1 }} />
        <button onClick={() => setPurge(true)} style={{ fontSize: 10.5, fontWeight: 600, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text3)', cursor: 'pointer' }}>Retention / purge old reports</button>
      </div>

      {/* KPI grid (Phase 3): action-first hierarchy. Risk/Stops + Approvals get persistent visual priority.
          Clicking a card focuses the report list AND the Action Queue tab. */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        <Kpi label="Needs action now" value={k.open_actions ?? '—'} color="#a855f7" sub={`${k.total ?? 0} reports · 7d`}
          active={qv === 'needs_action'} onClick={() => { setQv(qv === 'needs_action' ? '' : 'needs_action'); setAqTab('now') }} />
        <Kpi label="Critical / urgent" value={k.critical_urgent ?? '—'} color="#ef4444" sub={`${k.today ?? 0} today`}
          active={qv === 'critical'} onClick={() => setQv(qv === 'critical' ? '' : 'critical')} />
        <Kpi label="Risk / stops" value={k.risk_stop ?? '—'} color="#f59e0b" strong sub="open risk actions"
          active={qv === 'risk'} onClick={() => { setQv(qv === 'risk' ? '' : 'risk'); setAqTab('risk') }} />
        <Kpi label="Approvals" value={k.approvals ?? '—'} color="#f59e0b" strong sub="awaiting sign-off"
          active={qv === 'approvals'} onClick={() => { setQv(qv === 'approvals' ? '' : 'approvals'); setAqTab('approvals') }} />
        <Kpi label="System blockers" value={k.system_hermes ?? '—'} color="#60a5fa" sub="system · hermes"
          active={qv === 'system'} onClick={() => { setQv(qv === 'system' ? '' : 'system'); setAqTab('system') }} />
        <Kpi label="Reports today" value={k.today ?? '—'} color="var(--text0)" sub={`${k.total ?? 0} in ${effDays || 7}d`} />
      </div>

      {/* Quick views */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>Quick views</span>
        {QUICK_VIEWS.map(v => {
          const on = qv === v.key
          return <button key={v.key || 'all'} onClick={() => setQv(v.key)} style={{ fontSize: 11, fontWeight: on ? 800 : 600, padding: '5px 11px', borderRadius: 7, cursor: 'pointer', border: `1px solid ${on ? '#a855f7' : 'var(--border)'}`, background: on ? 'rgba(168,85,247,.12)' : 'var(--bg1)', color: on ? '#d8b4fe' : 'var(--text2)' }}>{v.label}</button>
        })}
      </div>

      {/* Category chips — compact, scrollable */}
      <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4 }}>
        {categories.map((c: any) => {
          const on = c.key === active
          return (
            <button key={c.key} onClick={() => setActive(c.key)} style={{
              fontSize: 11.5, fontWeight: on ? 800 : 600, padding: '6px 10px', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
              border: `1px solid ${on ? '#60a5fa' : 'var(--border)'}`, background: on ? 'rgba(96,165,250,.10)' : 'var(--bg1)',
              color: on ? '#60a5fa' : 'var(--text2)', display: 'flex', alignItems: 'center', gap: 5,
            }}>
              <span>{c.icon}</span>{c.label}
              <span style={{ fontSize: 9.5, fontWeight: 800, padding: '0 5px', borderRadius: 7, background: on ? '#60a5fa22' : 'var(--bg2)', color: on ? '#60a5fa' : 'var(--text3)' }}>{c.count}</span>
            </button>
          )
        })}
      </div>

      {/* Three-pane body */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>

        {/* LEFT — filters + list */}
        <div style={{ flex: '1 1 340px', minWidth: 300, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ ...card, padding: 9, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input value={qInput} onChange={e => setQInput(e.target.value)} placeholder={`Search ${activeCat?.label || ''}…`}
              style={{ flex: 1, minWidth: 140, fontSize: 12, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }} />
            <div style={{ display: 'flex', gap: 3 }}>
              {([['', 'All'], [1, '1d'], [7, '7d'], [30, '30d'], [90, '90d']] as any).map(([v, l]: any) => (
                <button key={l} onClick={() => setDays(v)} style={{ fontSize: 10, fontWeight: 700, padding: '5px 7px', borderRadius: 5, cursor: 'pointer',
                  border: `1px solid ${days === v ? '#60a5fa' : 'var(--border)'}`, background: days === v ? 'rgba(96,165,250,.10)' : 'transparent', color: days === v ? '#60a5fa' : 'var(--text3)' }}>{l}</button>
              ))}
            </div>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--text3)', padding: '0 2px', display: 'flex', justifyContent: 'space-between' }}>
            <span>{items.length} shown{total > items.length ? ` · ${total} total` : ''}{qv ? ` · ${QUICK_VIEWS.find(v => v.key === qv)?.label}` : ''}</span>
            {qv ? <span onClick={() => setQv('')} style={{ color: '#a855f7', cursor: 'pointer', fontWeight: 700 }}>clear quick view</span> : null}
          </div>

          {loading && rawItems.length === 0 && <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>loading…</div>}
          {!loading && items.length === 0 && <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>no reports here{q ? ` matching “${q}”` : ''}{qv ? ` · ${QUICK_VIEWS.find(v => v.key === qv)?.label}` : ''}</div>}

          {items.map((it: any) => {
            const id = `${it.source}-${it.id}`
            const on = !!(selected && `${selected.source}-${selected.id}` === id)
            return (
              <div key={id} onClick={() => setSelId(id)}>
                <SynthesizedReportCard item={it} selected={on} compact />
                {(it.has_actions || (it.action_classes || []).length > 0) && (
                  <div style={{ display: 'flex', gap: 4, margin: '-4px 0 2px 12px', flexWrap: 'wrap', alignItems: 'center' }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)' }}>{it.action_count} action{it.action_count === 1 ? '' : 's'} →</span>
                    {(it.action_classes || []).slice(0, 3).map((c: string) => <ActionPill key={c} cls={c} />)}
                  </div>
                )}
              </div>
            )
          })}

          {pages > 1 && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', margin: '4px 0' }}>
              <button disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))} style={{ fontSize: 11, padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page <= 1 ? 'var(--text3)' : 'var(--text1)', cursor: page <= 1 ? 'not-allowed' : 'pointer' }}>← Newer</button>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>page {page} of {pages}</span>
              <button disabled={page >= pages} onClick={() => setPage(p => Math.min(pages, p + 1))} style={{ fontSize: 11, padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page >= pages ? 'var(--text3)' : 'var(--text1)', cursor: page >= pages ? 'not-allowed' : 'pointer' }}>Older →</button>
            </div>
          )}
        </div>

        {/* CENTER — reader */}
        <div style={{ flex: '1 1 440px', minWidth: 340 }}>
          {!selected ? (
            <div style={{ ...card, padding: 36, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>select a report to read it here</div>
          ) : (() => {
            const body = selected.summary || ''
            const long = body.length > 1400
            const cut = long ? (body.lastIndexOf('\n', 1400) > 600 ? body.lastIndexOf('\n', 1400) : 1400) : body.length
            const shown = long && !expanded ? body.slice(0, cut) : body
            return (
              <article style={{ ...card, borderTop: `3px solid ${sevColor(selected.severity)}`, padding: '16px 20px' }}>
                <header style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 16, fontWeight: 900, color: 'var(--text0)', lineHeight: 1.3 }}>{selected.title}</div>
                    <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      <span>{fmtDate(selected.created_at)}</span><span>· {selected.channel}</span><span>· {selected.type}</span>
                      {selected.symbol && <span style={{ fontWeight: 800, color: '#60a5fa' }}>· {selected.symbol}</span>}
                    </div>
                  </div>
                  <SeverityBadge sev={selected.severity} />
                </header>
                <SynthStrip it={selected} />
                {/* "What matters" briefing (Phase 4): the report's actions grouped by canonical target, each a
                    one-click EXACT deep-link (stop drawer / approval modal / recovery / system tab / research). */}
                {reportActions.length > 0 && (
                  <div style={{ marginTop: 11, padding: '10px 12px', borderRadius: 9, background: 'var(--bg2)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 9, fontWeight: 900, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .5, marginBottom: 7 }}>What matters</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {WM_GROUPS.map(g => {
                        const grp = reportActions.filter((a: any) => (a.target?.target_type || '') === g.tt)
                        if (!grp.length) return null
                        return (
                          <div key={g.tt} style={{ display: 'flex', gap: 7, alignItems: 'center', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: 9.5, fontWeight: 800, color: g.c, minWidth: 92 }}>{g.label}</span>
                            {grp.slice(0, 6).map((a: any) => {
                              const tg = a.target || {}; const low = tg.target_confidence === 'low'
                              return <a key={a.id} href={relUrl(FQDN + (tg.route || a.route))} title={tg.reason || ''} style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 6, textDecoration: 'none', border: `1px solid ${low ? 'var(--border)' : g.c + '55'}`, background: low ? 'var(--bg1)' : g.c + '14', color: low ? 'var(--text3)' : g.c }}>{low ? 'Open related page' : (tg.route_label || a.route_label)} →</a>
                            })}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
                {/* Key sections anchor chips — scroll the (auto-expanded) body to a recognized header */}
                {(() => {
                  const present = SECTIONS.filter(s => s.rx.test(body))
                  if (!present.length) return null
                  return (
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
                      <span style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase' }}>Jump to</span>
                      {present.map(s => (
                        <button key={s.id} onClick={() => { setExpanded(true); setTimeout(() => document.getElementById(`rsec-${s.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60) }}
                          style={{ fontSize: 9.5, fontWeight: 700, padding: '3px 9px', borderRadius: 99, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>{s.label}</button>
                      ))}
                    </div>
                  )
                })()}
                <div style={{ height: 12 }} />
                <Article text={shown} />
                {long && <button onClick={() => setExpanded(e => !e)} style={{ marginTop: 8, fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'transparent', color: '#60a5fa', cursor: 'pointer' }}>{expanded ? '▲ show less' : '▼ read full report'}</button>}
                {(selected.actions || []).length > 0 && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap', paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
                    {selected.actions.map((a: any, i: number) => (
                      <a key={i} href={relUrl(a.url)} style={{ fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid #60a5fa55', background: '#60a5fa14', color: '#60a5fa', textDecoration: 'none' }}>{a.label} →</a>
                    ))}
                  </div>
                )}
              </article>
            )
          })()}
        </div>

        {/* RIGHT — action queue + symbols + bars (sticky so it stays in view while the page scrolls) */}
        <div style={{ flex: '1 1 240px', minWidth: 230, display: 'flex', flexDirection: 'column', gap: 10, position: 'sticky', top: 8, alignSelf: 'flex-start', maxHeight: 'calc(100vh - 24px)', overflowY: 'auto' }}>
          <div style={{ ...card, padding: 12 }}>
            {/* sticky header so the queue title + tabs stay visible while the list scrolls */}
            <div style={{ position: 'sticky', top: 0, background: 'var(--bg1)', zIndex: 1, paddingBottom: 6 }}>
              <div style={{ fontSize: 12, fontWeight: 900, color: 'var(--text0)', marginBottom: 7 }}>Action Queue</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
                {AQ_TABS.map(t => {
                  const on = aqTab === t.key
                  const n = dedupedActions.filter((a: any) => aqMatch(t.key, a)).length
                  return <button key={t.key} onClick={() => setAqTab(t.key)} style={{ fontSize: 9.5, fontWeight: on ? 800 : 600, padding: '3px 8px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${on ? '#a855f7' : 'var(--border)'}`, background: on ? 'rgba(168,85,247,.14)' : 'var(--bg2)', color: on ? '#d8b4fe' : 'var(--text3)' }}>{t.label} <span style={{ opacity: .7 }}>{n}</span></button>
                })}
              </div>
              <div style={{ fontSize: 9.5, color: 'var(--text3)', fontWeight: 600 }}>
                Showing {aqShown.length} {aqTab === 'now' ? 'priority' : aqTab} action{aqShown.length === 1 ? '' : 's'} of {allActions.length} extracted
                {aqFiltered.length > aqShown.length ? ` · ${aqFiltered.length - aqShown.length} more` : ''}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 420, overflowY: 'auto', marginTop: 4 }}>
              {aqShown.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>no {aqTab === 'all' ? '' : aqTab + ' '}actions in this window</div>}
              {aqShown.map((a: any) => (
                <div key={a.id} style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '8px 9px', borderRadius: 7, background: 'var(--bg2)', borderLeft: `3px solid ${sevColor(a.severity)}` }}>
                  <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
                    {(a._classes || [a.action_class]).map((c: string) => <ActionPill key={c} cls={c} />)}
                    {a.symbol && <span style={{ fontSize: 10, fontWeight: 800, color: '#60a5fa', fontFamily: 'monospace' }}>{a.symbol}</span>}
                  </div>
                  <div style={{ fontSize: 10.5, color: 'var(--text2)', lineHeight: 1.4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{a.text}</div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    {(() => { const tg = a.target || {}; const low = tg.target_confidence === 'low'; return (
                      <a href={relUrl(FQDN + (tg.route || a.route))} title={tg.reason || ''} style={{ fontSize: 9.5, fontWeight: 800, color: low ? 'var(--text3)' : '#60a5fa', textDecoration: 'none', border: `1px solid ${low ? 'var(--border)' : '#60a5fa44'}`, borderRadius: 5, padding: '2px 7px' }}>{low ? 'Open related page' : (tg.route_label || a.route_label)} →</a>
                    ) })()}
                    <span style={{ fontSize: 8.5, color: 'var(--text3)' }}>{a.category}</span>
                    <span style={{ fontSize: 8.5, color: 'var(--text3)' }}>· {fmtDate(a.created_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {(summary?.top_symbols || []).length > 0 && (
            <div style={{ ...card, padding: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 900, color: 'var(--text0)', marginBottom: 8 }}>Top symbols</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {summary.top_symbols.slice(0, 10).map((s: any) => (
                  <span key={s.symbol} style={{ fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 6, background: 'var(--bg2)', color: '#60a5fa' }}>{s.symbol} <span style={{ color: 'var(--text3)', fontWeight: 600 }}>{s.count}</span></span>
                ))}
              </div>
            </div>
          )}

          {sevRows.length > 0 && (
            <div style={{ ...card, padding: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 900, color: 'var(--text0)', marginBottom: 8 }}>Severity</div>
              <MiniBarChart rows={sevRows} />
            </div>
          )}
          {catRows.length > 0 && (
            <div style={{ ...card, padding: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 900, color: 'var(--text0)', marginBottom: 8 }}>Top categories</div>
              <MiniBarChart rows={catRows} color="#60a5fa" />
            </div>
          )}
        </div>
      </div>

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

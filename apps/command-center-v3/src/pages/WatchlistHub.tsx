import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import { useProAnalystMap } from '../components/ProAnalystPill'
import DiscoveryPanel from '../components/DiscoveryPanel'
import ToSWatchlists from '../components/ToSWatchlists'
import { useAnalystReportMap } from '../hooks/useAnalystReportMap'
import WatchlistCard from '../components/WatchlistCard'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import { exitLadder } from '../lib/exitLadder'
import { parseProposalAccounts, parseSizingPolicy } from '../lib/watchlistProposeSizing'

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'
const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 16 }
const SEL: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: TEXT0 }


// A directive's IDENTITY: a ticker directive is identified by its SYMBOL (label is just its list
// membership, often the generic "Watchlist"); a sector/trend directive is identified by its theme label.
const dirName = (d: any) => d.kind === 'ticker' ? (d.symbol || d.label || '—') : (d.label || d.kind)
// For a ticker directive, the named LIST it belongs to — only if it's a real list (not generic/self).
const dirList = (d: any) => {
  if (d.kind !== 'ticker') return null
  const l = d.label
  if (!l || l === d.symbol || l.toLowerCase() === 'watchlist' || /^watch\s/i.test(l)) return null
  return l
}

const Pill = ({ text, color, tip, strong = false }: any) => (
  <span title={tip} style={{ fontSize: strong ? 10.5 : 9.5, fontWeight: strong ? 800 : 700, padding: strong ? '3px 8px' : '2px 7px', borderRadius: 5, background: color + '22', color, border: `1px solid ${color}66`, whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default' }}>{text}</span>
)

const ORIGIN_OPTS = [['all', 'All'], ['trade_ai_screener', 'Screener'], ['agent_discovery', 'AI-discovered'], ['operator', 'Operator-directive'], ['hermes', 'Hermes'], ['portfolio', 'Portfolio']]

export default function WatchlistHub({ onDrill, embedded }: Props) {
  const { data: wl, loading: wlLoading, refetch: refetchWl } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: summary } = useApi<any>('/api/v2/watchlist/summary', 120_000)
  const { data: adv } = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120_000)
  const { data: wd, refetch: refetchWd } = useApi<any>('/api/v2/watch-directives', 60_000)
  const { data: ext, refetch: refetchExt } = useApi<any>('/api/v2/hermes/external-intel-map', 60_000)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const { data: outcomesData } = useApi<any>('/api/v2/rec-intel/outcomes', 300_000)   // purchased→sold outcomes (real closed trades)
  const reportMap = useAnalystReportMap()
  const { data: curateStatus, refetch: refetchCurate } = useApi<any>('/api/v2/hermes/curate-top20', 20_000)
  const paMap = useProAnalystMap()
  const { data: fvStrip } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: acctRaw } = useApi<any>('/api/v2/proposal-accounts', 120_000)
  const proposalAccounts = useMemo(() => parseProposalAccounts(acctRaw), [acctRaw])
  const sizingPolicy = useMemo(() => parseSizingPolicy(acctRaw), [acctRaw])
  const { data: holdRaw } = useApi<any>('/api/v2/portfolio/holdings', 300_000)
  // symbol → per-account held rows, for held-aware sizing on cards
  const heldMap = useMemo(() => {
    const rows: any[] = holdRaw?.holdings ?? holdRaw?.data?.holdings ?? []
    const m: Record<string, { account: string; shares: number; market_value: number }[]> = {}
    for (const h of rows) {
      const sym = String(h?.symbol || '').toUpperCase()
      const shares = Number(h?.shares)
      if (!sym || !Number.isFinite(shares) || shares <= 0) continue
      ;(m[sym] ??= []).push({ account: String(h.account || ''), shares, market_value: Number(h.market_value) || 0 })
    }
    return m
  }, [holdRaw])

  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const extMap: Record<string, any[]> = ext?.map ?? {}
  const curateRunning = !!curateStatus?.running
  const items: any[] = wl?.items ?? []
  const advMap: Record<string, any> = {}
  for (const a of (adv?.advisories ?? [])) advMap[a.symbol] = a
  // count only advisories whose symbol is actually IN the displayed items, so the KPI tiles match
  // what clicking them filters to (an advisory for a symbol outside the 200-item window isn't shown)
  const itemSyms = new Set(items.map(i => i.symbol))
  const advisories: any[] = (adv?.advisories ?? []).filter((a: any) => itemSyms.has(a.symbol))
  const cautionN = advisories.filter(a => a.advisory_flag === 'caution').length
  const favorableN = advisories.filter(a => a.advisory_flag === 'favorable').length
  const byStatus = summary?.by_status ?? {}
  const outMap: Record<string, any> = outcomesData?.outcomes ?? {}   // symbol → purchased→sold outcome
  const directives: any[] = wd?.directives ?? []
  const sectorTrendDirs = directives.filter(d => d.kind === 'sector' || d.kind === 'trend')
  // Actionable vs dormant — a directive earns a chip only if it's doing something: a named ticker, or a
  // sector/trend that has actually surfaced or staged a symbol. The ~100 archived/0-hit trend research-
  // topics (Roth/Medicare/MAPT planning themes that can never produce a tradeable ticker) are dormant noise
  // — folded behind a collapsed toggle so the section shows what's live, not a wall of zeros.
  const dirActivity = (d: any) => (d.hit_count ?? (d.hit_symbols?.length ?? 0)) + (d.staged_count ?? 0)
  const isActionableDir = (d: any) => d.status !== 'archived' && (d.kind === 'ticker' || dirActivity(d) > 0)
  const actionableDirs = directives.filter(isActionableDir).sort((a, b) => dirActivity(b) - dirActivity(a))
  // Dormant = live-but-quiet discovery trends (active/paused, 0 hits). Archived directives are RETIRED
  // (e.g. knowledge themes moved to the research pipeline) — hidden entirely, not even in the dormant list.
  const dormantDirs = directives.filter(d => d.status !== 'archived' && !isActionableDir(d))

  const [fOrigin, setFOrigin] = useState('all')
  const [fBand, setFBand] = useState('all')
  const [fKind, setFKind] = useState('all')
  const [fDir, setFDir] = useState('all')
  const [fStatus, setFStatus] = useState('all')
  const [fRating, setFRating] = useState('all')
  const [fCio, setFCio] = useState('all')
  const [fList, setFList] = useState('all')
  const [fHeld, setFHeld] = useState(false)   // held-only (currently-owned positions)
  const [fStarred, setFStarred] = useState(false)   // operator-starred only
  const [starOverride, setStarOverride] = useState<Record<string, boolean>>({})   // optimistic star state until items refetch
  const [fSector, setFSector] = useState('all')
  const [fAnalyst, setFAnalyst] = useState('all')   // analyst catalyst: upgrade / downgrade
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [page, setPage] = useState(0)
  const [showDormantDirs, setShowDormantDirs] = useState(false)   // collapse the 0-hit research-topic directives
  const [showDirectives, setShowDirectives] = useState(false)   // Watch Directives chip wall — collapsed by default (it's a long list; the Directive filter dropdown still works)
  const [ensOpen, setEnsOpen] = useState<Record<string, boolean>>({})   // per-card on-demand ensemble (avoids 24 fetches on mount)
  const [refreshBusy, setRefreshBusy] = useState<Record<string, string>>({})   // per-symbol manual refresh status
  const [proposeSeed, setProposeSeed] = useState<WatchlistProposeSeed | null>(null)
  const [actionToast, setActionToast] = useState('')
  const [buildBusy, setBuildBusy] = useState<Record<string, string>>({})
  const PER_PAGE = 12
  const isStarred = (it: any) => starOverride[String(it.symbol).toUpperCase()] ?? !!it.starred
  // operator star: always-in-window + sorted first (server) + faster entry-plan refresh (server). Optimistic.
  const toggleStar = (it: any) => {
    const sym = String(it.symbol).toUpperCase(); const next = !isStarred(it)
    setStarOverride(o => ({ ...o, [sym]: next }))
    fetch('/api/v2/watchlist/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: sym, starred: next }) })
      .then(() => setTimeout(refetchWl, 800)).catch(() => setStarOverride(o => ({ ...o, [sym]: !next })))   // revert on failure
  }
  const starredCount = useMemo(() => items.filter(isStarred).length, [items, starOverride])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setPage(0), [fOrigin, fBand, fKind, fDir, fStatus, fRating, fCio, fList, fHeld, fStarred, fSector, fAnalyst, search])   // reset to page 1 on any filter change
  // named watch lists (directive labels) present across the items, for the List filter
  const listOpts = useMemo(() => Array.from(new Set(
    items.flatMap((i: any) => String(i.watch_lists || '').split(' · ').map(s => s.trim()).filter(Boolean))
  )).sort(), [items])
  const sectorOpts = useMemo(() => Array.from(new Set(
    items.map((i: any) => String(i.profile_sector || '').trim()).filter(Boolean)
  )).sort(), [items])
  // distinct currently-held symbols present in the loaded items (drives the Held-only toggle count)
  const heldCount = useMemo(() => new Set(items
    .filter((it: any) => it.in_portfolio || outMap[String(it.symbol).toUpperCase()]?.held)
    .map((it: any) => String(it.symbol).toUpperCase())).size, [items, outMap])

  const openDesk = (sym: string) => {
    window.location.href = `/v3/trading?tab=Entry+Desk&symbol=${sym}`
  }

  const openProposeModal = (it: any, opts?: { account_key?: string; risk_pct?: 1 | 2 }) => {
    const entry = it.entry_limit != null ? Number(it.entry_limit) : null
    const stop = it.entry_stop != null ? Number(it.entry_stop) : null
    const planTarget = it.entry_target != null ? Number(it.entry_target) : null
    const pa = paMap[it.symbol]
    const street = pa?.target != null && Number(pa.target) > 0 ? Number(pa.target) : null
    const rr = it.entry_rr != null ? Number(it.entry_rr)
      : (entry && stop && planTarget && entry > stop && planTarget > entry ? (planTarget - entry) / (entry - stop) : null)
    setProposeSeed({
      it, entry, stop, planTarget, rr,
      ladder: entry != null || stop != null ? exitLadder(entry, stop, planTarget, street) : null,
      pa,
      ...(opts ?? {}),
    })
  }

  const buildPlan = async (sym: string) => {
    const key = String(sym).toUpperCase()
    setBuildBusy(b => ({ ...b, [key]: '…' }))
    try {
      const r = await fetch(`/api/v2/watchlist/${key}/plan`, { method: 'POST' })
      const j = await r.json()
      const payload = j?.data ?? j
      if (payload?.ok) {
        setBuildBusy(b => ({ ...b, [key]: 'queued' }))
        setActionToast(`${key} — entry planner queued (~1–2 min)`)
        setTimeout(() => { refetchWl(); setBuildBusy(b => { const nxt = { ...b }; delete nxt[key]; return nxt }) }, 3000)
      } else {
        setBuildBusy(b => ({ ...b, [key]: 'error' }))
        setActionToast(payload?.error || 'Build plan failed')
      }
    } catch {
      setBuildBusy(b => ({ ...b, [key]: 'error' }))
      setActionToast('Build plan failed')
    }
  }

  const refreshSymbol = async (sym: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const key = String(sym).toUpperCase()
    setRefreshBusy(b => ({ ...b, [key]: '…' }))
    try {
      const r = await fetch(`/api/v2/watchlist/${key}/refresh`, { method: 'POST' })
      const j = await r.json()
      const payload = j?.data ?? j
      if (payload?.ok) {
        const n = payload.requeued ?? 0
        setRefreshBusy(b => ({ ...b, [key]: n ? `queued ${n}` : 'refreshed' }))
        setTimeout(() => { refetchWl(); setRefreshBusy(b => { const nxt = { ...b }; delete nxt[key]; return nxt }) }, 2500)
      } else {
        setRefreshBusy(b => ({ ...b, [key]: 'error' }))
      }
    } catch {
      setRefreshBusy(b => ({ ...b, [key]: 'error' }))
    }
  }

  const runChatgptTop20 = async () => {
    if (curateRunning) return
    try {
      await fetch('/api/v2/hermes/curate-top20', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lanes: 'chatgpt' }) })
      setTimeout(() => { refetchCurate(); refetchExt() }, 1500)
    } catch { /* advisory only */ }
  }

  // The DB legitimately holds >1 row per symbol (portfolio holding + ai_discovered + ai_watchlist alias +
  // per-bucket). Collapse to ONE card per symbol, keeping the RICHEST row (directive-associated, then
  // highest score) so the displayed card always carries the directive badge/plan — not a barer alias
  // (fix 2026-06-19: operator ticker tags appeared "not associated" when a barer dupe won the dedup).
  const bestBySym = useMemo(() => {
    const best = new Map<string, { row: any; rich: number }>()
    for (const it of items) {
      const sym = String(it.symbol).toUpperCase()
      const rich = (it.directive_id ? 1e9 : 0) + (Number(it.score) || 0)
      const cur = best.get(sym)
      if (!cur || rich > cur.rich) best.set(sym, { row: it, rich })
    }
    return best
  }, [items])

  const visible = useMemo(() => {
    const q = search.trim().toUpperCase()
    // Directive filter: a ticker directive links items by directive_id, but a trend/sector directive
    // surfaces them via hits (by symbol). Match on EITHER (fix 2026-06-19 — trend filter showed 0).
    const selDir = fDir !== 'all' ? directives.find(d => String(d.id) === fDir) : null
    const selDirSyms = new Set<string>((selDir?.hit_symbols ?? []).map((s: string) => String(s).toUpperCase()))
    return items.filter(it => {
      const symU = String(it.symbol).toUpperCase()
      if (bestBySym.get(symU)?.row !== it) return false   // one (richest) row per symbol
      // Search is a DIRECT symbol lookup — it bypasses the other filters so a specific ticker is always
      // findable (operator 2026-06-18: "can't filter HPE" — HPE is CIO=IGNORE and the Buy-side filter hid it).
      if (q) return symU.includes(q)
      if (fStatus !== 'all' && it.status !== fStatus) return false
      if (fOrigin !== 'all') {
        if (fOrigin === 'operator') { if (!it.directive_id && it.origin_system !== 'operator') return false }
        else if (it.origin_system !== fOrigin) return false
      }
      if (fKind !== 'all') { const itp = (it.instrument_type || 'stock').toLowerCase(); const norm = itp === 'inverse_etf' ? 'etf' : itp; if (norm !== fKind) return false }
      if (fDir !== 'all' && String(it.directive_id) !== fDir && !selDirSyms.has(symU)) return false
      if (fHeld && !(it.in_portfolio || outMap[symU]?.held)) return false   // held-only (currently owned)
      if (fStarred && !isStarred(it)) return false   // operator-starred only
      if (fBand === 'any') { if (!advMap[it.symbol]) return false }   // "with setup advisory"
      else if (fBand !== 'all') { const b = advMap[it.symbol]?.advisory_flag || 'none'; if (b !== fBand) return false }
      if (fRating !== 'all') { const rec = paMap[it.symbol]?.rec || 'no_coverage'; if (fRating === 'buy_plus' ? !['strong_buy', 'buy'].includes(rec) : rec !== fRating) return false }
      if (fCio !== 'all') {
        const cv = String(it.latest_recommendation || '').toUpperCase()
        if (fCio === 'buy_side') { if (!['BUY', 'STRONG_BUY', 'ADD', 'ADD_ON_PULLBACK'].includes(cv)) return false }
        else if (fCio === 'avoid_side') { if (!['AVOID', 'IGNORE', 'SELL', 'TRIM'].includes(cv)) return false }
        else if (fCio === 'none') { if (cv) return false }
        else if (cv !== fCio) return false
      }
      if (fList !== 'all') {
        const lists = String(it.watch_lists || '').split(' · ').map((s: string) => s.trim())
        if (fList === '__none' ? lists.filter(Boolean).length > 0 : !lists.includes(fList)) return false
      }
      if (fSector !== 'all' && String(it.profile_sector || '').trim() !== fSector) return false
      if (fAnalyst !== 'all' && it.catalyst_type !== (fAnalyst === 'upgrade' ? 'analyst_upgrade' : 'analyst_downgrade')) return false
      return true
    })
      // starred first (stable — preserves the server's hermes order within each group; also reflects an
      // optimistic toggle immediately, before the server-ordered refetch lands)
      .sort((a, b) => (isStarred(b) ? 1 : 0) - (isStarred(a) ? 1 : 0))
  }, [items, bestBySym, fOrigin, fKind, fDir, fBand, fStatus, fRating, fCio, fList, fHeld, fStarred, starOverride, fSector, fAnalyst, search, paMap, advMap, directives, outMap])

  const pageCount = Math.max(1, Math.ceil(visible.length / PER_PAGE))
  const curPage = Math.min(page, pageCount - 1)
  const pageItems = visible.slice(curPage * PER_PAGE, (curPage + 1) * PER_PAGE)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: embedded ? 10 : 16 }}>
        {!embedded && (
          <div>
            <div style={{ fontSize: 22, fontWeight: 900, color: TEXT0 }}>Watchlist</div>
            <div style={{ fontSize: 12, color: MUTED }}>{byStatus.active ?? items.length} active · {byStatus.researched ?? 0} researched · {byStatus.removed ?? 0} removed · larger CIO cards</div>
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginLeft: embedded ? 0 : 'auto' }}>
          <button onClick={runChatgptTop20} disabled={curateRunning} title="Run ChatGPT curation on the top-20 ranked names." style={{ padding: embedded ? '6px 10px' : '9px 15px', fontSize: embedded ? 10 : 12, fontWeight: 800, borderRadius: 8, border: '1px solid #10a37f', cursor: curateRunning ? 'default' : 'pointer', background: curateRunning ? 'rgba(16,163,127,.15)' : 'rgba(16,163,127,.12)', color: '#34d399', opacity: curateRunning ? 0.7 : 1 }}>{curateRunning ? `✦ ChatGPT… ${curateStatus?.chatgpt_curated_top20 ?? 0}/20` : '✦ ChatGPT Top 20'}</button>
          <button onClick={() => setShowAdd(true)} style={{ padding: embedded ? '6px 12px' : '9px 17px', fontSize: embedded ? 10 : 12, fontWeight: 800, borderRadius: 8, border: 'none', cursor: 'pointer', background: PURPLE, color: '#fff' }}>+ Add Watch</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 14 }}>
        {[
          { label: 'Loaded · top by rank', value: items.length, color: TEXT0, tip: `top ${items.length} by Hermes rank (not the full ${(byStatus.active ?? 0) + (byStatus.researched ?? 0)}-name universe) — click to clear all filters`, onClick: () => { setFBand('all'); setFStatus('all'); setFOrigin('all'); setFRating('all'); setFCio('all'); setFList('all'); setFKind('all'); setFDir('all'); setFHeld(false); setFSector('all'); setFAnalyst('all'); setSearch('') } },
          { label: 'With setup advisory', value: advisories.length, color: BLUE, tip: 'filter to names that have a setup advisory', onClick: () => setFBand('any') },
          { label: 'Caution band', value: cautionN, color: RED, tip: 'filter to caution-band names', onClick: () => setFBand('caution') },
          { label: 'Favorable band', value: favorableN, color: GREEN, tip: 'filter to favorable-band names', onClick: () => setFBand('favorable') },
        ].map(k => (
          <div key={k.label} title={k.tip} onClick={k.onClick} style={{ ...panel, textAlign: 'center', cursor: 'pointer', outline: (k.label === 'With setup advisory' && fBand === 'any') || (k.label === 'Caution band' && fBand === 'caution') || (k.label === 'Favorable band' && fBand === 'favorable') ? `1px solid ${k.color}` : 'none' }}>
            <div style={{ fontSize: 26, fontWeight: 900, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 4, textTransform: 'uppercase' }}>{k.label} <span style={{ color: DIM }}>▸</span></div>
          </div>
        ))}
      </div>

      <DiscoveryPanel onAdded={refetchWl} />
      <ToSWatchlists />

      {directives.length > 0 && (
        <div style={{ ...panel, marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: showDirectives ? 8 : 0, flexWrap: 'wrap' }}>
            <button onClick={() => setShowDirectives(v => !v)} title={showDirectives ? 'collapse the directive list' : 'expand the directive list'} style={{ fontSize: 14, fontWeight: 900, color: TEXT0, background: 'none', border: 'none', padding: 0, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}><span style={{ fontSize: 11, color: MUTED }}>{showDirectives ? '▾' : '▸'}</span>Watch Directives <span style={{ fontSize: 10, color: MUTED, fontWeight: 500 }}>· operator standing instructions</span></button>
            <span style={{ fontSize: 10, color: MUTED }}>{actionableDirs.length} active · sorted by hits + staged{showDirectives ? '' : ' · click to expand'}</span>
          </div>
          {showDirectives && (() => {
            const renderDir = (d: any) => {
              const nHits = d.hit_count ?? (d.hit_symbols ?? []).length; const nStaged = d.staged_count ?? 0
              return <div key={d.id} onClick={() => setFDir(fDir === String(d.id) ? 'all' : String(d.id))} title={fDir === String(d.id) ? 'click to clear this directive filter' : 'filter list to this directive'} style={{ padding: '7px 11px', background: 'var(--bg2)', borderRadius: 9, cursor: 'pointer', border: fDir === String(d.id) ? `1px solid ${PURPLE}` : '1px solid var(--border)' }}><div style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Pill text={d.kind} color={PURPLE} /><span style={{ fontSize: 12, fontWeight: 800, color: TEXT0 }}>{dirName(d)}</span>{dirList(d) && <Pill text={`☰ ${dirList(d)}`} color="#22d3ee" tip="list membership" />}<Pill text={d.status} color={d.status === 'active' ? GREEN : d.status === 'paused' ? AMBER : MUTED} /></div><div style={{ fontSize: 10, color: MUTED, marginTop: 3 }}>{nHits} hit{nHits === 1 ? '' : 's'} · {nStaged} staged</div></div>
            }
            return <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{actionableDirs.map(renderDir)}</div>
              {actionableDirs.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>No active directives with hits yet — named tickers and surfacing sector/trend themes will appear here.</div>}
              {dormantDirs.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <button onClick={() => setShowDormantDirs(v => !v)} style={{ fontSize: 10.5, fontWeight: 700, padding: '5px 11px', borderRadius: 7, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED }}>
                    {showDormantDirs ? '▲ Hide' : '▾ Show'} {dormantDirs.length} dormant directive{dormantDirs.length === 1 ? '' : 's'} <span style={{ color: DIM }}>· 0 hits / archived research-topics</span>
                  </button>
                  {showDormantDirs && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8, opacity: 0.7 }}>{dormantDirs.map(renderDir)}</div>}
                </div>
              )}
            </>
          })()}
        </div>
      )}

      <div style={{ ...panel, marginBottom: 12, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Status<select style={SEL} value={fStatus} onChange={e => setFStatus(e.target.value)}><option value="all">Active + Researched</option><option value="active">Active only</option><option value="researched">Researched only</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Position<button onClick={() => setFHeld(h => !h)} title="show only currently-held positions (the ● held badge)" style={{ fontSize: 11, padding: '6px 11px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${fHeld ? '#ffa726' : 'var(--border)'}`, background: fHeld ? 'rgba(255,167,38,.14)' : 'var(--bg2)', color: fHeld ? '#ffa726' : MUTED, fontWeight: fHeld ? 800 : 500, whiteSpace: 'nowrap' }}>● Held only{heldCount ? ` (${heldCount})` : ''}</button></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Starred<button onClick={() => setFStarred(s => !s)} title="show only operator-starred symbols (★) — they always show first and refresh faster" style={{ fontSize: 11, padding: '6px 11px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${fStarred ? '#fbbf24' : 'var(--border)'}`, background: fStarred ? 'rgba(251,191,36,.14)' : 'var(--bg2)', color: fStarred ? '#fbbf24' : MUTED, fontWeight: fStarred ? 800 : 500, whiteSpace: 'nowrap' }}>★ Starred only{starredCount ? ` (${starredCount})` : ''}</button></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Origin<select style={SEL} value={fOrigin} onChange={e => setFOrigin(e.target.value)}>{ORIGIN_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Advisory band<select style={SEL} value={fBand} onChange={e => setFBand(e.target.value)}><option value="all">All</option><option value="any">With advisory</option><option value="favorable">Favorable</option><option value="caution">Caution</option><option value="none">None</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Analyst rating<span style={{ display: 'flex', gap: 5 }}>{[['all', 'All', MUTED], ['strong_buy', 'Strong Buy', GREEN], ['buy_plus', 'Buy+', '#86efac'], ['hold', 'Hold', AMBER], ['no_coverage', 'No coverage', MUTED]].map(([k, lbl, c]) => <button key={k} onClick={() => setFRating(k as string)} style={{ fontSize: 10, padding: '5px 10px', borderRadius: 6, cursor: 'pointer', border: `1px solid ${fRating === k ? c : 'var(--border)'}`, background: fRating === k ? `color-mix(in srgb, ${c} 18%, transparent)` : 'var(--bg2)', color: fRating === k ? c as string : MUTED, fontWeight: fRating === k ? 800 : 500 }}>{lbl}</button>)}</span></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>CIO view<select style={SEL} value={fCio} onChange={e => setFCio(e.target.value)}><option value="all">All</option><option value="buy_side">Buy-side (BUY/ADD/pullback)</option><option value="BUY">BUY</option><option value="STRONG_BUY">STRONG_BUY</option><option value="ADD">ADD</option><option value="ADD_ON_PULLBACK">ADD_ON_PULLBACK</option><option value="HOLD">HOLD</option><option value="RESEARCH_MORE">RESEARCH_MORE</option><option value="TRIM">TRIM</option><option value="avoid_side">Avoid-side (AVOID/IGNORE/SELL/TRIM)</option><option value="AVOID">AVOID</option><option value="IGNORE">IGNORE</option><option value="none">No CIO view</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>List<select style={SEL} value={fList} onChange={e => setFList(e.target.value)}><option value="all">All lists</option>{listOpts.map(l => <option key={l} value={l}>{l}</option>)}<option value="__none">— no list —</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Sector<select style={SEL} value={fSector} onChange={e => setFSector(e.target.value)}><option value="all">All sectors</option>{sectorOpts.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Analyst action<select style={SEL} value={fAnalyst} onChange={e => setFAnalyst(e.target.value)}><option value="all">All</option><option value="upgrade">⬆ Upgrades</option><option value="downgrade">⬇ Downgrades</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Instrument<select style={SEL} value={fKind} onChange={e => setFKind(e.target.value)}><option value="all">All</option><option value="stock">Stocks</option><option value="etf">ETFs / inverse</option><option value="fund">Funds</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Directive<select style={SEL} value={fDir} onChange={e => setFDir(e.target.value)}><option value="all">All</option>{directives.map(d => <option key={d.id} value={String(d.id)}>{dirName(d)}{dirList(d) ? ` · ${dirList(d)}` : ''} ({d.kind})</option>)}</select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Search<input style={SEL} value={search} onChange={e => setSearch(e.target.value)} placeholder="symbol" /></label>
        <div style={{ marginLeft: 'auto', fontSize: 11, color: TEXT2 }}>{visible.length} / {items.length} shown</div>
      </div>

      <div style={{ fontSize: 11, color: AMBER, marginBottom: 12, padding: '9px 13px', background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.28)', borderRadius: 7 }}>{adv?.disclaimer ?? 'Advisory only — current technical posture vs the post-trade prior. Never gates promotion/scoring.'}</div>
      {actionToast && (
        <div style={{ fontSize: 11, color: GREEN, marginBottom: 10, padding: '8px 12px', background: 'rgba(34,197,94,.1)', border: '1px solid rgba(34,197,94,.25)', borderRadius: 7 }}>
          {actionToast}
          {actionToast.includes('proposal') && (
            <a href="/v3/trading?tab=Proposals" style={{ marginLeft: 10, color: BLUE, fontWeight: 700 }}>Open Proposals →</a>
          )}
        </div>
      )}

      <div style={panel}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 15, fontWeight: 900, color: TEXT0 }}>Watchlist ({visible.length})</div>
          {pageCount > 1 && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={curPage === 0} style={{ ...SEL, cursor: curPage === 0 ? 'default' : 'pointer', opacity: curPage === 0 ? 0.4 : 1 }}>‹ Prev</button>
              <span style={{ fontSize: 11, color: TEXT2, fontWeight: 700, minWidth: 96, textAlign: 'center' }}>Page {curPage + 1} / {pageCount} · {curPage * PER_PAGE + 1}-{Math.min((curPage + 1) * PER_PAGE, visible.length)}</span>
              <button onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))} disabled={curPage >= pageCount - 1} style={{ ...SEL, cursor: curPage >= pageCount - 1 ? 'default' : 'pointer', opacity: curPage >= pageCount - 1 ? 0.4 : 1 }}>Next ›</button>
            </div>
          )}
        </div>
        {visible.length === 0 && (wlLoading || wl == null) && items.length === 0 ? (
          // First load of /watchlist/items enriches the full universe and can take several seconds — show a
          // real loading state so an empty grid doesn't read as "no matches / data outage" while it resolves.
          <div style={{ color: MUTED, fontSize: 12, padding: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ display: 'inline-block', width: 12, height: 12, border: `2px solid ${MUTED}`, borderTopColor: 'transparent', borderRadius: '50%', animation: 'wl-spin 0.8s linear infinite' }} />
            Loading watchlist…
            <style>{`@keyframes wl-spin { to { transform: rotate(360deg) } }`}</style>
          </div>
        ) : visible.length === 0 ? (() => {
          const sd = fDir !== 'all' ? directives.find((d: any) => String(d.id) === fDir) : null
          const nh = (sd?.hit_symbols ?? []).length
          const resetAll = () => { setFBand('all'); setFStatus('all'); setFOrigin('all'); setFRating('all'); setFCio('all'); setFList('all'); setFKind('all'); setFDir('all'); setFHeld(false); setFSector('all'); setFAnalyst('all'); setSearch('') }
          const link = (c: string, t: string, fn: () => void) => <span onClick={fn} style={{ color: c, cursor: 'pointer', textDecoration: 'underline', fontWeight: 700 }}>{t}</span>
          return <div style={{ color: MUTED, fontSize: 12, padding: 16 }}>
            {sd
              ? <>Directive <b style={{ color: TEXT0 }}>{sd.label}</b> has surfaced <b style={{ color: TEXT0 }}>{nh}</b> watchlist item{nh === 1 ? '' : 's'}{nh === 0 ? ` (no hits${sd.status !== 'active' ? `; directive is ${sd.status}` : ''})` : ''}. {link(PURPLE, 'Clear directive filter', () => setFDir('all'))}</>
              : <>No items match the filters. {link(BLUE, 'Reset all filters', resetAll)}</>}
          </div>
        })() : (
          <>
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            width: '100%',
            minWidth: 0,
          }}>
            {pageItems.map((it: any) => {
              const symKey = String(it.symbol).toUpperCase()
              const outcome = outMap[symKey]
              return (
                <div key={it.id} style={{ minWidth: 0, width: '100%' }}>
                <WatchlistCard
                  it={it}
                  adv={advMap[it.symbol]}
                  sc={cardMap[it.symbol]}
                  pa={paMap[it.symbol]}
                  outcome={outcome ? { ...outcome, sold: (outcome.closed_trades ?? 0) > 0 } : undefined}
                  llms={extMap[it.symbol] || []}
                  fv={fvMap[it.symbol]}
                  reportEntry={reportMap[symKey]}
                  paMap={paMap}
                  accounts={proposalAccounts}
                  heldPositions={heldMap[symKey]}
                  maxDeployPctOfCash={sizingPolicy.maxDeployPctOfCash}
                  ensOpen={!!ensOpen[it.id]}
                  refreshState={refreshBusy[symKey]}
                  isStarred={isStarred(it)}
                  onDrill={onDrill}
                  onToggleStar={e => { e.stopPropagation(); toggleStar(it) }}
                  onRefresh={e => refreshSymbol(it.symbol, e)}
                  onToggleEns={() => setEnsOpen(o => ({ ...o, [it.id]: !o[it.id] }))}
                  onPropose={openProposeModal}
                  onAdjust={it => openDesk(it.symbol)}
                  onBuildPlan={buildPlan}
                  onOpenDesk={openDesk}
                />
                </div>
              )
            })}
          </div>
          </>
        )}
        {pageCount > 1 && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'center', marginTop: 14 }}>
            <button onClick={() => { setPage(p => Math.max(0, p - 1)); window.scrollTo({ top: 0, behavior: 'smooth' }) }} disabled={curPage === 0} style={{ ...SEL, cursor: curPage === 0 ? 'default' : 'pointer', opacity: curPage === 0 ? 0.4 : 1 }}>‹ Prev</button>
            <span style={{ fontSize: 11, color: TEXT2, fontWeight: 700, minWidth: 96, textAlign: 'center' }}>Page {curPage + 1} / {pageCount}</span>
            <button onClick={() => { setPage(p => Math.min(pageCount - 1, p + 1)); window.scrollTo({ top: 0, behavior: 'smooth' }) }} disabled={curPage >= pageCount - 1} style={{ ...SEL, cursor: curPage >= pageCount - 1 ? 'default' : 'pointer', opacity: curPage >= pageCount - 1 ? 0.4 : 1 }}>Next ›</button>
          </div>
        )}
        <div style={{ fontSize: 9.5, color: MUTED, marginTop: 10 }}>Decision-first cards — CIO view, confidence, R:R, L/S/target, model, data-quality flags, and reasoning visible by default. Street analyst shown with divergence when CIO disagrees. Advisory-only — never places trades.</div>
      </div>

      {showAdd && <AddWatchModal onClose={() => setShowAdd(false)} onCreated={() => { refetchWd(); refetchWl() }} paMap={paMap} lists={listOpts} />}
      {proposeSeed && (
        <WatchlistProposeModal
          seed={proposeSeed}
          onClose={() => setProposeSeed(null)}
          onProposed={res => {
            setActionToast(res.message || `${res.symbol} queued as proposal #${res.proposal_id}`)
            refetchWl()
          }}
        />
      )}
    </div>
  )
}

function AddWatchModal({ onClose, onCreated, paMap, lists = [] }: { onClose: () => void; onCreated: () => void; paMap: any; lists?: string[] }) {
  const { data: sectorsData } = useApi<any>('/api/v2/watch/sectors', 600_000)
  const [kind, setKind] = useState<'ticker' | 'sector' | 'trend'>('ticker')
  const [symbol, setSymbol] = useState('')
  const [sector, setSector] = useState('')
  const [keywords, setKeywords] = useState('')
  const [seeds, setSeeds] = useState('')
  const [label, setLabel] = useState('')
  const [rationale, setRationale] = useState('')
  const [priority, setPriority] = useState('normal')
  const [taOn, setTaOn] = useState(true)
  const [hermesOn, setHermesOn] = useState(true)
  const [ttl, setTtl] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const sectors: any[] = sectorsData?.sectors ?? []
  const selSector = sectors.find(s => s.sector === sector)
  const div = (paMap?.[(symbol || '').toUpperCase()]?.divergence) as string | undefined
  const governor = kind === 'ticker' ? `Operator-named ticker → evaluated immediately${div ? ` · current Street divergence: ${div}` : ''}` : 'Resolved symbols stage for one-tap promote if qualified'
  const fld: React.CSSProperties = { fontSize: 11, padding: '7px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: TEXT0, width: '100%' }
  const lbl: React.CSSProperties = { fontSize: 10, color: MUTED, display: 'block', marginBottom: 4 }
  const save = async () => {
    setBusy(true); setMsg(null)
    const syms = (s: string) => s.toUpperCase().split(/[ ,\s]+/).filter(Boolean)
    let spec: any = {}, autoLabel = label
    if (kind === 'ticker') { spec = { symbol: symbol.toUpperCase().trim() }; autoLabel = label || `watch ${symbol.toUpperCase().trim()}` }
    else if (kind === 'sector') { spec = { finviz_sector: sector }; autoLabel = label || `sector ${sector}` }
    else { spec = { keywords: keywords.split(',').map(s => s.trim()).filter(Boolean), ...(seeds ? { seed_symbols: syms(seeds) } : {}) }; autoLabel = label || `trend ${keywords.slice(0, 30)}` }
    try {
      const r = await fetch('/api/v2/watch/directives', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, label: autoLabel, spec, rationale, priority, ttl_days: ttl ? Number(ttl) : null, trade_ai_enabled: taOn, hermes_enabled: hermesOn }) })
      const j = await r.json()
      if (j.ok) { const sv = j.serviced?.status; setMsg(`✓ Created directive #${j.directive_id}` + (sv === 'PROMOTED' ? ' — symbol promoted now' : sv === 'STAGED_FOR_REVIEW' ? ' — staged for review' : sv === 'MONITORED_NO_QUALIFY' ? ' — watching now' : sv ? ` — ${sv}` : '')); onCreated(); setTimeout(onClose, sv ? 1600 : 900) }
      else setMsg(`Error: ${j.error}`)
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(false)
  }
  const canSave = kind === 'ticker' ? !!symbol.trim() : kind === 'sector' ? !!sector : !!keywords.trim()
  return <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.58)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}><div onClick={e => e.stopPropagation()} style={{ ...panel, width: 540, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto' }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}><div style={{ fontSize: 16, fontWeight: 900, color: TEXT0 }}>Add Watch Directive</div><button onClick={onClose} style={{ background: 'none', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 16 }}>x</button></div><div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>{(['ticker', 'sector', 'trend'] as const).map(k => <button key={k} onClick={() => setKind(k)} style={{ flex: 1, padding: '7px 0', fontSize: 11, borderRadius: 7, border: 'none', cursor: 'pointer', textTransform: 'capitalize', background: kind === k ? 'rgba(168,85,247,.2)' : 'var(--bg2)', color: kind === k ? '#d8b4fe' : MUTED, fontWeight: kind === k ? 800 : 500 }}>{k}</button>)}</div>{kind === 'ticker' && <div style={{ marginBottom: 10 }}><label style={lbl}>Symbol</label><input style={fld} value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="RKLB" autoFocus /></div>}{kind === 'sector' && <div style={{ marginBottom: 10 }}><label style={lbl}>Sector</label><select style={fld} value={sector} onChange={e => setSector(e.target.value)}><option value="">— select sector —</option>{sectors.map(s => <option key={s.sector} value={s.sector}>{s.sector} ({s.count})</option>)}</select>{selSector && <div style={{ fontSize: 10, color: MUTED, marginTop: 6, padding: '7px 9px', background: 'var(--bg2)', borderRadius: 6 }}>Resolves to the sector ETF + up to 25 constituents. First: {(selSector.sample || []).join(', ')}</div>}</div>}{kind === 'trend' && <><div style={{ marginBottom: 10 }}><label style={lbl}>Keywords</label><input style={fld} value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="AI datacenter, power" autoFocus /></div><div style={{ marginBottom: 10 }}><label style={lbl}>Seed symbols</label><input style={fld} value={seeds} onChange={e => setSeeds(e.target.value)} placeholder="NVDA, VRT" /></div></>}<div style={{ marginBottom: 10 }}><label style={lbl}>List / label <span style={{ color: MUTED, fontWeight: 400 }}>— pick an existing list or type a new one</span></label><input style={fld} list="watchlist-list-names" value={label} onChange={e => setLabel(e.target.value)} placeholder="e.g. Data Center (blank = general Watchlist)" /><datalist id="watchlist-list-names">{lists.map(l => <option key={l} value={l} />)}</datalist></div><div style={{ marginBottom: 10 }}><label style={lbl}>Rationale / thesis</label><input style={fld} value={rationale} onChange={e => setRationale(e.target.value)} placeholder="why watch this" /></div><div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}><label style={{ flex: 1, ...lbl }}>Priority<select style={fld} value={priority} onChange={e => setPriority(e.target.value)}><option value="normal">normal</option><option value="high">high</option></select></label><label style={{ flex: 1, ...lbl }}>TTL days<input style={fld} value={ttl} onChange={e => setTtl(e.target.value.replace(/\D/g, ''))} placeholder="standing" /></label></div><div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 11, color: TEXT2 }}><label><input type="checkbox" checked={taOn} onChange={e => setTaOn(e.target.checked)} /> Trade AI</label><label><input type="checkbox" checked={hermesOn} onChange={e => setHermesOn(e.target.checked)} /> Hermes</label></div><div style={{ fontSize: 10, color: MUTED, marginBottom: 12, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 6, borderLeft: `3px solid ${PURPLE}` }}><b style={{ color: TEXT2 }}>How it promotes:</b> {governor}</div>{msg && <div style={{ fontSize: 11, color: msg.startsWith('Error') ? RED : GREEN, marginBottom: 10 }}>{msg}</div>}<div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}><button onClick={onClose} style={{ padding: '8px 14px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: TEXT2, cursor: 'pointer' }}>Cancel</button><button disabled={busy || !canSave} onClick={save} style={{ padding: '8px 18px', fontSize: 11, fontWeight: 800, borderRadius: 6, border: 'none', background: PURPLE, color: '#fff', cursor: busy || !canSave ? 'not-allowed' : 'pointer', opacity: busy || !canSave ? 0.5 : 1 }}>Save Directive</button></div></div></div>
}

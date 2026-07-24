import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { marketAwareStale } from '../lib/watchlistCardV4'
import { watchV5Enabled, enqueueStrategyRefresh, pollRefreshRun, fetchDeskSummary } from '../lib/watchV5'
import { isExtremeVolItem } from '../lib/watchlistVolatility'
import { useApi, useConnectionHealth } from '../hooks/useApi'
import { BB, T, focusStyle } from '../lib/watchTokens'
import { Chip } from '../components/TerminalChip'
import ShadowBatchButton from '../components/ShadowBatchButton'
import type { DrillContext } from '../components/DetailDrawer'
import { useProAnalystMap } from '../components/ProAnalystPill'
import DiscoveryPanel from '../components/DiscoveryPanel'
import ToSWatchlists from '../components/ToSWatchlists'
import { useAnalystReportMap } from '../hooks/useAnalystReportMap'
import WatchlistCardV4 from '../components/WatchlistCardV4'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import { exitLadder } from '../lib/exitLadder'
import { parseProposalAccounts, parseSizingPolicy, type RiskPct } from '../lib/watchlistProposeSizing'
import { LevelLines, useLevels } from '../lib/supportResistance'

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean; lane?: 'screener_finds' }

const TEXT0 = BB.text0
const TEXT1 = BB.text1
const TEXT2 = BB.text2
const MUTED = BB.text3
const DIM = BB.text3
const GREEN = BB.green
const RED = BB.red
const AMBER = BB.orange
const BLUE = T.link
const PURPLE = T.extIntel.hermes
const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 2, padding: 16 }
const SEL: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 2, color: TEXT0 }


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
  <span title={tip} style={{ fontSize: strong ? 10.5 : 9.5, fontWeight: strong ? 800 : 700, padding: strong ? '3px 8px' : '2px 7px', borderRadius: 2, background: color + '22', color, border: `1px solid ${color}66`, whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default' }}>{text}</span>
)

const ORIGIN_OPTS = [['all', 'All'], ['screener_finds', 'Screener Finds (buy-side)'], ['trade_ai_screener', 'Screener'], ['agent_discovery', 'AI-discovered'], ['operator', 'Operator-directive'], ['hermes', 'Hermes'], ['portfolio', 'Portfolio']]

export default function WatchlistHub({ onDrill, embedded, lane }: Props) {
  const levels = useLevels()
  // CIO-view filter is pushed server-side (cio=) so it searches the FULL universe before the
  // 200-row window — client-side alone missed verdicts on names ranked below the load size
  const [fCio, setFCio] = useState('all')
  const [fOrigin, setFOrigin] = useState('all')
  const [search, setSearch] = useState('')
  const symLookup = useMemo(() => {
    const q = search.trim().toUpperCase()
    return /^[A-Z]{1,5}$/.test(q) ? q : ''
  }, [search])
  const screenerLane = lane === 'screener_finds' || fOrigin === 'screener_finds'
  // Ticker search always hits direct DB lookup (even on Screener Finds) so graduated names like
  // DUG (CIO drifted off buy-side) still show a card instead of "0 / 16 shown".
  const wlPath = symLookup
    ? `/api/v2/watchlist/items?symbol=${encodeURIComponent(symLookup)}`
    : screenerLane
    ? '/api/v2/watchlist/items?lane=screener_finds'
    : `/api/v2/watchlist/items?sort=hermes${fCio !== 'all' ? `&cio=${encodeURIComponent(fCio)}` : ''}`
  const { data: wl, loading: wlLoading, refetch: refetchWl } = useApi<any>(wlPath, 60_000)
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
  const extremeVolN = useMemo(() => items.filter(isExtremeVolItem).length, [items])
  const tightStopN = useMemo(() => items.filter((it: any) =>
    it.plan_stop_tight === true || it.plan_stop_tight_vs_atr20 === true || it.plan_stop_tight_vs_atr === true,
  ).length, [items])
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
  // Watch Desk v2 (B3): governed row actions + needs-review ordering + proposed fold
  const [dirSort, setDirSort] = useState<'activity' | 'needs_review'>('activity')
  const proposedDirs = directives.filter((d: any) => d.status === 'proposed')
  const dirAction = async (id: number, action: string, targetId?: number) => {
    try {
      const r = await fetch('/api/v2/watch/directives/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, action, target_id: targetId }) }).then(x => x.json())
      if (!(r?.ok ?? r?.data?.ok)) alert(`Action failed: ${r?.error || r?.data?.error || 'error'}`)
      refetchWd()
    } catch { alert('Action failed — server unreachable') }
  }
  const spark = (arr?: number[]) => {
    const bars = '▁▂▃▄▅▆▇█'; const a = arr || []
    const mx = Math.max(1, ...a)
    return a.map(v => bars[Math.min(7, Math.round((v / mx) * 7))]).join('')
  }

  const [fBand, setFBand] = useState('all')
  const [fKind, setFKind] = useState('all')
  const [fDir, setFDir] = useState('all')
  const [fStatus, setFStatus] = useState('all')
  const [fRating, setFRating] = useState('all')
  const [fList, setFList] = useState('all')
  const [fHeld, setFHeld] = useState(false)   // held-only (currently-owned positions)
  const [fStarred, setFStarred] = useState(false)   // operator-starred only
  const [starOverride, setStarOverride] = useState<Record<string, boolean>>({})   // optimistic star state until items refetch
  const [fSector, setFSector] = useState('all')
  const [fAnalyst, setFAnalyst] = useState('all')   // analyst catalyst: upgrade / downgrade
  const [fVol, setFVol] = useState<'all' | 'extreme' | 'tight_stop'>('all')

  // v4 (B1): saved views — named filter presets, SERVER-side (ui_prefs) because the
  // operator works desktop+phone over Tailscale; localStorage doesn't travel. Max 8.
  const VIEWS_KEY = 'watchlist.saved_views'
  const { data: viewsPref, refetch: refetchViews } = useApi<any>(`/api/v2/ui/prefs/get?key=${VIEWS_KEY}`, 0)
  const savedViews: Array<{ name: string; f: any }> = viewsPref?.value ?? []
  const currentFilters = () => ({ fCio, fOrigin, fBand, fKind, fDir, fStatus, fRating, fList, fHeld, fStarred, fSector, fAnalyst, fVol, search })
  const applyView = (v: any) => {
    const f = v.f || {}
    setFCio(f.fCio ?? 'all'); setFOrigin(f.fOrigin ?? 'all'); setFBand(f.fBand ?? 'all'); setFKind(f.fKind ?? 'all')
    setFDir(f.fDir ?? 'all'); setFStatus(f.fStatus ?? 'all'); setFRating(f.fRating ?? 'all'); setFList(f.fList ?? 'all')
    setFHeld(!!f.fHeld); setFStarred(!!f.fStarred); setFSector(f.fSector ?? 'all'); setFAnalyst(f.fAnalyst ?? 'all')
    setFVol(f.fVol ?? 'all'); setSearch(f.search ?? '')
    setActionToast(`View applied — ${v.name}`)
  }
  const saveViews = async (views: any[]) => {
    await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: VIEWS_KEY, value: views.slice(0, 8) }) })
    refetchViews()
  }

  // v4 (B2): bulk row selection (≤25) → bulk Star / bulk Alert with one confirm.
  // (Stage/Hide have no per-row watchlist endpoints — flagged in the closeout, not faked.)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const selSyms = Object.keys(selected).filter(s => selected[s])
  const [showAdd, setShowAdd] = useState(false)
  const [page, setPage] = useState(0)
  const [showDormantDirs, setShowDormantDirs] = useState(false)   // collapse the 0-hit research-topic directives
  const [showDirectives, setShowDirectives] = useState(false)   // Watch Directives chip wall — collapsed by default (it's a long list; the Directive filter dropdown still works)
  const [ensOpen, setEnsOpen] = useState<Record<string, boolean>>({})   // per-card on-demand ensemble (avoids 24 fetches on mount)
  const [refreshBusy, setRefreshBusy] = useState<Record<string, string>>({})   // per-symbol manual refresh status
  const autoRefreshDone = useRef<Set<string>>(new Set())   // one auto-refresh per symbol per session
  const autoRefreshBusy = useRef(false)
  const { degraded: connDegraded } = useConnectionHealth()
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
  useEffect(() => setPage(0), [fOrigin, fBand, fKind, fDir, fStatus, fRating, fCio, fList, fHeld, fStarred, fSector, fAnalyst, fVol, search])   // reset to page 1 on any filter change
  // named watch lists (directive labels) present across the items, for the List filter
  const listOpts = useMemo(() => Array.from(new Set(
    items.flatMap((i: any) => String(i.watch_lists || '').split(' · ').map(s => s.trim()).filter(Boolean))
  )).sort(), [items])
  const sectorOpts = useMemo(() => Array.from(new Set(
    items.map((i: any) => String(i.profile_sector || '').trim()).filter(Boolean)
  )).sort(), [items])
  // Currently held = live portfolio only (in_portfolio from holdings, or heldMap shares>0).
  // Never use rec-intel outcomes.held for this — that is purchase/sale history, not open position.
  const heldCount = useMemo(() => new Set(items
    .filter((it: any) => {
      const sym = String(it.symbol).toUpperCase()
      return !!(it.in_portfolio || (heldMap[sym] && heldMap[sym].length > 0))
    })
    .map((it: any) => String(it.symbol).toUpperCase())).size, [items, heldMap])

  const openDesk = (sym: string) => {
    window.location.href = `/v3/trading?tab=Entry+Desk&symbol=${sym}`
  }

  const openProposeModal = (it: any, opts?: { account_key?: string; risk_pct?: RiskPct }) => {
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

  const waitEnrichmentFresh = useCallback(async (key: string, maxMs = 90_000): Promise<boolean> => {
    const deadline = Date.now() + maxMs
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 5000))
      try {
        const r = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(key)}`)
        const j = await r.json()
        const it = ((j?.data ?? j)?.items ?? [])[0]
        if (it?.last_enriched_at && !marketAwareStale(it.last_enriched_at)) return true
      } catch { /* retry */ }
    }
    return false
  }, [])

  const runRefresh = useCallback(async (sym: string, mode: 'manual' | 'auto' = 'manual'): Promise<boolean> => {
    const key = String(sym).toUpperCase()
    setRefreshBusy(b => ({ ...b, [key]: mode === 'auto' ? 'auto…' : '…' }))
    try {
      const r = await fetch(`/api/v2/watchlist/${key}/refresh`, { method: 'POST' })
      const j = await r.json().catch(() => ({}))
      const payload = j?.data ?? j
      const accepted = r.ok && (payload?.ok || payload?.queued)
      if (accepted) {
        const n = payload.requeued ?? 0
        const bg = payload?.queued === true || r.status === 202
        if (mode === 'auto' && bg) {
          autoRefreshDone.current.add(key)
          setRefreshBusy(b => ({ ...b, [key]: 'auto queued' }))
          setActionToast(`${key} — refresh queued (background)`)
          window.setTimeout(() => { refetchWl(); setRefreshBusy(b => { const nxt = { ...b }; delete nxt[key]; return nxt }) }, 20_000)
          return true
        }
        if (payload.enriched === false) {
          setRefreshBusy(b => ({ ...b, [key]: 'enrich failed' }))
          if (mode === 'manual') {
            setActionToast(`${key} — technicals failed${payload.enrich_warning ? ` (${String(payload.enrich_warning).slice(0, 80)})` : ''}; news/agents still queued`)
          }
        } else {
          setRefreshBusy(b => ({ ...b, [key]: mode === 'auto' ? (n ? `auto queued ${n}` : 'auto ok') : (n ? `queued ${n}` : 'refreshed') }))
          if (mode === 'manual') {
            setActionToast(bg ? `${key} — refresh queued; CIO agents will update in ~1–2 min` : `${key} — news + catalyst + technicals refreshed; CIO agents prioritized`)
          }
        }
        if (mode === 'auto') {
          autoRefreshDone.current.add(key)
          const fresh = await waitEnrichmentFresh(key, 45_000)
          await refetchWl()
          setRefreshBusy(b => { const nxt = { ...b }; delete nxt[key]; return nxt })
          return fresh
        }
        setTimeout(() => { refetchWl(); setRefreshBusy(b => { const nxt = { ...b }; delete nxt[key]; return nxt }) }, bg ? 20_000 : 2500)
        return true
      }
      setRefreshBusy(b => ({ ...b, [key]: 'error' }))
      return false
    } catch {
      setRefreshBusy(b => ({ ...b, [key]: 'error' }))
      return false
    }
  }, [refetchWl, waitEnrichmentFresh])

  const refreshSymbol = async (sym: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await runRefresh(sym, 'manual')
  }

  // ── V5 canonical strategy refresh: enqueue → poll → refetch. The packet is
  //    rebuilt server-side (LOCAL_QUANT by default — zero model-lane cost).
  const [strategyBusy, setStrategyBusy] = useState<Record<string, boolean>>({})
  const refreshStrategy = useCallback(async (syms: string[], reason = 'manual_card_refresh') => {
    const keys = syms.map(s => String(s).toUpperCase())
    setStrategyBusy(b => ({ ...b, ...Object.fromEntries(keys.map(k => [k, true])) }))
    try {
      const res = await enqueueStrategyRefresh(keys, { scope: 'AFFECTED_DIMENSIONS', tier: 'LOCAL_QUANT', reason })
      if (!res.ok || !res.run_id) {
        setActionToast(`Strategy refresh failed to enqueue: ${res.error ?? 'unknown'}`)
        return
      }
      setActionToast(`Strategy refresh queued (run ${res.run_id}) — ${res.queued ?? 0} symbol(s)`)
      const done = await pollRefreshRun(res.run_id, { timeoutMs: 300_000 })
      const jobs = done?.jobs ?? []
      const okN = jobs.filter(j => ['COMPLETE', 'SKIPPED_CURRENT'].includes(j.state)).length
      const badN = jobs.filter(j => j.state === 'FAILED').length
      setActionToast(badN
        ? `Strategy refresh: ${okN} rebuilt, ${badN} failed — ${jobs.find(j => j.state === 'FAILED')?.error ?? ''}`.slice(0, 160)
        : `Strategy refresh complete — ${okN} packet(s) current`)
      await refetchWl()
      void refetchDeskSummary()
    } finally {
      setStrategyBusy(b => { const n = { ...b }; keys.forEach(k => delete n[k]); return n })
    }
  }, [refetchWl])

  // Desk-toolbar summary (server-owned freshness counts)
  const [deskSummary, setDeskSummary] = useState<any>(null)
  const refetchDeskSummary = useCallback(async () => {
    try { setDeskSummary(await fetchDeskSummary()) } catch { /* toolbar is best-effort */ }
  }, [])
  useEffect(() => {
    if (!watchV5Enabled()) return
    void refetchDeskSummary()
    const t = window.setInterval(() => void refetchDeskSummary(), 60_000)
    return () => window.clearInterval(t)
  }, [refetchDeskSummary])

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
      if (screenerLane) return true   // lane API already narrowed to buy-side screener pins
      if (fStatus !== 'all' && it.status !== fStatus) return false
      if (fOrigin !== 'all') {
        if (fOrigin === 'screener_finds') return true
        if (fOrigin === 'operator') { if (!it.directive_id && it.origin_system !== 'operator') return false }
        else if (it.origin_system !== fOrigin) return false
      }
      if (fKind !== 'all') { const itp = (it.instrument_type || 'stock').toLowerCase(); const norm = itp === 'inverse_etf' ? 'etf' : itp; if (norm !== fKind) return false }
      if (fDir !== 'all' && String(it.directive_id) !== fDir && !selDirSyms.has(symU)) return false
      if (fHeld && !(it.in_portfolio || (heldMap[symU] && heldMap[symU].length > 0))) return false   // currently owned only
      if (fStarred && !isStarred(it)) return false   // operator-starred only
      if (fBand === 'any') { if (!advMap[it.symbol]) return false }   // "with setup advisory"
      else if (fBand !== 'all') { const b = advMap[it.symbol]?.advisory_flag || 'none'; if (b !== fBand) return false }
      if (fRating !== 'all') { const rec = paMap[it.symbol]?.rec || 'no_coverage'; if (fRating === 'buy_plus' ? !['strong_buy', 'buy'].includes(rec) : rec !== fRating) return false }
      if (fCio !== 'all') {
        // match the research-card rec OR the CIO synthesis verdict — most ADD_ON_PULLBACK views
        // live only in the synthesis (top-200 audit 2026-07-06: 0 research vs 3 synthesis), so
        // checking latest_recommendation alone made the filter return an empty page
        const cvs = [it.latest_recommendation, it.synthesis_recommendation]
          .map(v => String(v || '').toUpperCase()).filter(Boolean)
        if (fCio === 'buy_side') { if (!cvs.some(c => ['BUY', 'STRONG_BUY', 'ADD', 'ADD_ON_PULLBACK'].includes(c))) return false }
        else if (fCio === 'avoid_side') { if (!cvs.some(c => ['AVOID', 'IGNORE', 'SELL', 'TRIM'].includes(c))) return false }
        else if (fCio === 'none') { if (cvs.length) return false }
        else if (!cvs.includes(fCio)) return false
      }
      if (fList !== 'all') {
        const lists = String(it.watch_lists || '').split(' · ').map((s: string) => s.trim())
        if (fList === '__none' ? lists.filter(Boolean).length > 0 : !lists.includes(fList)) return false
      }
      if (fSector !== 'all' && String(it.profile_sector || '').trim() !== fSector) return false
      if (fAnalyst !== 'all' && it.catalyst_type !== (fAnalyst === 'upgrade' ? 'analyst_upgrade' : 'analyst_downgrade')) return false
      if (fVol === 'extreme' && !isExtremeVolItem(it)) return false
      if (fVol === 'tight_stop' && !(it.plan_stop_tight || it.plan_stop_tight_vs_atr20 || it.plan_stop_tight_vs_atr)) return false
      return true
    })
      // starred first (stable — preserves the server's hermes order within each group; also reflects an
      // optimistic toggle immediately, before the server-ordered refetch lands)
      .sort((a, b) => (isStarred(b) ? 1 : 0) - (isStarred(a) ? 1 : 0))
  }, [items, bestBySym, fOrigin, fKind, fDir, fBand, fStatus, fRating, fCio, fList, fHeld, fStarred, starOverride, fSector, fAnalyst, fVol, search, paMap, advMap, directives, heldMap, screenerLane])

  const pageCount = Math.max(1, Math.ceil(visible.length / PER_PAGE))
  const curPage = Math.min(page, pageCount - 1)
  const pageItems = visible.slice(curPage * PER_PAGE, (curPage + 1) * PER_PAGE)

  // v4 (A5): shared alert-composer flow — used by the 🔔 button and the `a` key
  const armAlert = useCallback(async (it: any) => {
    const cond = window.prompt(`Alert for ${it.symbol} — condition (price_cross_above | price_cross_below | rsi_above | rsi_below):`, 'price_cross_below')
    if (!cond) return
    const th = window.prompt('Threshold:', cond.startsWith('rsi') ? '40' : String(it.last_price ?? it.price ?? ''))
    if (!th) return
    const r = await fetch('/api/v2/watch/alerts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: it.symbol, condition_type: cond.trim(), threshold: Number(th) }) }).then(x => x.json())
    setActionToast((r?.ok ?? r?.data?.ok) ? `Alert armed — ${it.symbol} ${cond} ${th}` : `Alert failed: ${r?.error || r?.data?.error}`)
  }, [])

  // v4 (A5): keyboard nav — j/k focus, Enter expands the focused card's ensemble,
  // s stars, a arms an alert. (x/hide: watchlist rows have no hide action — flagged in closeout.)
  const [kbIdx, setKbIdx] = useState(-1)
  useEffect(() => { setKbIdx(-1) }, [curPage, visible.length])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement
      if (tgt && ['INPUT', 'TEXTAREA', 'SELECT'].includes(tgt.tagName)) return
      if (!pageItems.length) return
      if (e.key === 'j') setKbIdx(i => Math.min(pageItems.length - 1, i + 1))
      else if (e.key === 'k') setKbIdx(i => Math.max(0, i - 1))
      else if (e.key === 'Enter' && kbIdx >= 0 && pageItems[kbIdx]) { const it = pageItems[kbIdx]; setEnsOpen(o => ({ ...o, [it.id]: !o[it.id] })) }
      else if (e.key === 's' && kbIdx >= 0 && pageItems[kbIdx]) toggleStar(pageItems[kbIdx])
      else if (e.key === 'a' && kbIdx >= 0 && pageItems[kbIdx]) void armAlert(pageItems[kbIdx])
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pageItems, kbIdx, armAlert])   // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-refresh STALE cards on the current page (market-aware; once per symbol per session).
  // One at a time — each refresh is heavy; parallel refreshes used to wedge the API thread pool.
  useEffect(() => {
    // V5: the SERVER owns refresh cadence (watch_decision_scheduler + policy YAML).
    // The legacy one-per-session browser sweep only runs with V5 rolled back.
    if (watchV5Enabled()) return
    if (connDegraded || autoRefreshBusy.current) return
    const staleOnPage = pageItems.filter(it => {
      const key = String(it.symbol).toUpperCase()
      if (autoRefreshDone.current.has(key)) return false
      return !!it.last_enriched_at && marketAwareStale(it.last_enriched_at)
    })
    if (!staleOnPage.length) return
    const it = staleOnPage[0]
    const key = String(it.symbol).toUpperCase()
    autoRefreshBusy.current = true
    setActionToast(`Auto-refreshing stale card: ${key}`)
    void (async () => {
      try {
        await runRefresh(it.symbol, 'auto')
      } finally {
        autoRefreshBusy.current = false
      }
    })()
  }, [pageItems, curPage, runRefresh, connDegraded])

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
          <button onClick={runChatgptTop20} disabled={curateRunning} title="Run ChatGPT curation on the top-20 ranked names." style={{ padding: embedded ? '6px 10px' : '9px 15px', fontSize: embedded ? 10 : 12, fontWeight: 800, borderRadius: 2, border: `1px solid ${T.extIntel.gpt}`, cursor: curateRunning ? 'default' : 'pointer', background: curateRunning ? 'rgba(16, 163, 127, 0.15)' : 'rgba(16, 163, 127, 0.12)', color: BB.green, opacity: curateRunning ? 0.7 : 1 }}>{curateRunning ? `✦ ChatGPT… ${curateStatus?.chatgpt_curated_top20 ?? 0}/20` : '✦ ChatGPT Top 20'}</button>
          <button onClick={() => setShowAdd(true)} style={{ padding: embedded ? '6px 12px' : '9px 17px', fontSize: embedded ? 10 : 12, fontWeight: 800, borderRadius: 2, border: 'none', cursor: 'pointer', background: PURPLE, color: BB.text0 }}>+ Add Watch</button>
          <ShadowBatchButton embedded={embedded} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 14 }}>
        {[
          { label: `Top ${items.length} of ${wl?.universe_count ?? '…'} · Hermes rank`, value: items.length, color: TEXT0, tip: `top ${items.length} by Hermes rank (not the full ${(byStatus.active ?? 0) + (byStatus.researched ?? 0)}-name universe) — click to clear all filters`, onClick: () => { setFBand('all'); setFStatus('all'); setFOrigin('all'); setFRating('all'); setFCio('all'); setFList('all'); setFKind('all'); setFDir('all'); setFHeld(false); setFSector('all'); setFAnalyst('all'); setFVol('all'); setSearch('') } },
          { label: 'Extreme vol · ATR₂₀', value: extremeVolN, color: RED, tip: 'filter to extreme volatility (ATR₂₀ ≥10%) — Maria/Telegram period', onClick: () => setFVol(v => v === 'extreme' ? 'all' : 'extreme') },
          { label: 'Tight stop · <1× ATR₂₀', value: tightStopN, color: AMBER, tip: 'filter to entry plans with stop inside 1× ATR₂₀', onClick: () => setFVol(v => v === 'tight_stop' ? 'all' : 'tight_stop') },
          { label: 'With setup advisory', value: advisories.length, color: BLUE, tip: 'filter to names that have a setup advisory', onClick: () => setFBand('any') },
          { label: 'Caution band', value: cautionN, color: cautionN ? RED : 'var(--text3)', tip: 'setup_quality_prior engine — sample-gated: bands render only when a setup has sufficient historical sample. 0 is honest, not broken.', onClick: () => setFBand('caution') },
          { label: 'Favorable band', value: favorableN, color: favorableN ? GREEN : 'var(--text3)', tip: 'setup_quality_prior engine — sample-gated: bands render only when a setup has sufficient historical sample. 0 is honest, not broken.', onClick: () => setFBand('favorable') },
        ].map(k => (
          <div key={k.label} title={k.tip} onClick={k.onClick} style={{ ...panel, textAlign: 'center', cursor: 'pointer', outline: (k.label.startsWith('Extreme vol') && fVol === 'extreme') || (k.label.startsWith('Tight stop') && fVol === 'tight_stop') || (k.label === 'With setup advisory' && fBand === 'any') || (k.label === 'Caution band' && fBand === 'caution') || (k.label === 'Favorable band' && fBand === 'favorable') ? `1px solid ${k.color}` : 'none' }}>
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
              const lastHit = d.last_hit_at ? String(d.last_hit_at).slice(0, 10) : 'never'
              return <div key={d.id} onClick={() => setFDir(fDir === String(d.id) ? 'all' : String(d.id))} title={fDir === String(d.id) ? 'click to clear this directive filter' : 'filter list to this directive'} style={{ padding: '7px 11px', background: 'var(--bg2)', borderRadius: 2, cursor: 'pointer', border: fDir === String(d.id) ? `1px solid ${PURPLE}` : '1px solid var(--border)' }}><div style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Pill text={d.kind} color={PURPLE} /><span style={{ fontSize: 12, fontWeight: 800, color: TEXT0 }}>{dirName(d)}</span>{dirList(d) && <Pill text={`☰ ${dirList(d)}`} color={T.link} tip="list membership" />}<Pill text={d.status} color={d.status === 'active' ? GREEN : d.status === 'paused' ? AMBER : MUTED} />{(d.aliases_n ?? 0) > 0 && <Pill text={`${d.aliases_n} alias`} color={T.extIntel.hermes} tip="near-dup labels absorbed by the family gate" />}</div><div style={{ fontSize: 10, color: MUTED, marginTop: 3 }}>{nHits} hits · {nStaged} staged · 7d {d.hits_7d ?? 0} · 30d {d.hits_30d ?? 0} · age {d.age_days ?? '—'}d · last {lastHit}{d.alpha_21d_median != null ? ` · 21d α ${d.alpha_21d_median > 0 ? '+' : ''}${d.alpha_21d_median}% (n=${d.alpha_n})` : ' · α n/a'}{d.conv_pct != null ? ` · conv ${d.conv_pct}%` : ''} <span style={{ fontFamily: BB.mono, fontVariantNumeric: 'tabular-nums', color: PURPLE }} title="hits per week, last 8 weeks">{spark(d.spark_8w)}</span></div><div style={{ display: 'flex', gap: 5, marginTop: 4 }} onClick={e => e.stopPropagation()}>{d.status === 'active' && <button onClick={() => dirAction(d.id, 'pause')} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 2, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Pause</button>}{(d.status === 'paused' || d.status === 'proposed') && <button onClick={() => dirAction(d.id, 'resume')} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 2, border: '1px solid var(--border)', background: 'transparent', color: GREEN, cursor: 'pointer' }}>{d.status === 'proposed' ? 'Promote' : 'Resume'}</button>}{d.status !== 'archived' && <button onClick={() => dirAction(d.id, 'archive')} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 2, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Archive</button>}{d.kind === 'trend' && d.status === 'active' && <button onClick={() => { const tid = window.prompt(`Merge #${d.id} '${dirName(d)}' into directive id:`); if (tid) dirAction(d.id, 'merge_into', Number(tid)) }} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 2, border: '1px solid var(--border)', background: 'transparent', color: T.extIntel.hermes, cursor: 'pointer' }}>Merge…</button>}</div></div>
            }
            return <>
              <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
                <button onClick={() => setDirSort(s => s === 'activity' ? 'needs_review' : 'activity')} style={{ fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 2, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>
                  Sort: {dirSort === 'activity' ? 'hits + staged' : 'needs review (worst α, then coldest)'}
                </button>
                {proposedDirs.length > 0 && <span style={{ fontSize: 10.5, color: AMBER }}>Proposed directives ({proposedDirs.length}) — over the {'{'}150{'}'} trend cap; Promote to activate</span>}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{(dirSort === 'activity' ? actionableDirs : [...actionableDirs].sort((a: any, b: any) => ((a.alpha_21d_median ?? 99) - (b.alpha_21d_median ?? 99)) || String(a.last_hit_at || '0').localeCompare(String(b.last_hit_at || '0')))).map(renderDir)}</div>
              {proposedDirs.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8, opacity: 0.85 }}>{proposedDirs.map(renderDir)}</div>}
              {actionableDirs.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>No active directives with hits yet — named tickers and surfacing sector/trend themes will appear here.</div>}
              {dormantDirs.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <button onClick={() => setShowDormantDirs(v => !v)} style={{ fontSize: 10.5, fontWeight: 700, padding: '5px 11px', borderRadius: 2, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED }}>
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
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Position<button onClick={() => setFHeld(h => !h)} title="show only currently-held positions (the ● held badge)" style={{ fontSize: 11, padding: '6px 11px', borderRadius: 2, cursor: 'pointer', border: `1px solid ${fHeld ? BB.amber : 'var(--border)'}`, background: fHeld ? 'rgba(255, 176, 0, 0.14)' : 'var(--bg2)', color: fHeld ? BB.amber : MUTED, fontWeight: fHeld ? 800 : 500, whiteSpace: 'nowrap' }}>● Held only{heldCount ? ` (${heldCount})` : ''}</button></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Starred<button onClick={() => setFStarred(s => !s)} title="show only operator-starred symbols (★) — they always show first and refresh faster" style={{ fontSize: 11, padding: '6px 11px', borderRadius: 2, cursor: 'pointer', border: `1px solid ${fStarred ? BB.amber : 'var(--border)'}`, background: fStarred ? 'rgba(255, 176, 0, 0.14)' : 'var(--bg2)', color: fStarred ? BB.amber : MUTED, fontWeight: fStarred ? 800 : 500, whiteSpace: 'nowrap' }}>★ Starred only{starredCount ? ` (${starredCount})` : ''}</button></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Origin<select style={SEL} value={fOrigin} onChange={e => setFOrigin(e.target.value)}>{ORIGIN_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Advisory band<select style={SEL} value={fBand} onChange={e => setFBand(e.target.value)}><option value="all">All</option><option value="any">With advisory</option><option value="favorable">Favorable ({favorableN})</option><option value="caution">Caution ({cautionN})</option><option value="none">None</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Analyst rating<span style={{ display: 'flex', gap: 5 }}>{[['all', 'All', MUTED], ['strong_buy', 'Strong Buy', GREEN], ['buy_plus', 'Buy+', BB.green], ['hold', 'Hold', AMBER], ['no_coverage', 'No coverage', MUTED]].map(([k, lbl, c]) => <button key={k} onClick={() => setFRating(k as string)} style={{ fontSize: 10, padding: '5px 10px', borderRadius: 2, cursor: 'pointer', border: `1px solid ${fRating === k ? c : 'var(--border)'}`, background: fRating === k ? `color-mix(in srgb, ${c} 18%, transparent)` : 'var(--bg2)', color: fRating === k ? c as string : MUTED, fontWeight: fRating === k ? 800 : 500 }}>{lbl}</button>)}</span></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>CIO view<select style={SEL} value={fCio} onChange={e => setFCio(e.target.value)}><option value="all">All</option><option value="buy_side">Buy-side (BUY/ADD/pullback)</option><option value="BUY">BUY</option><option value="STRONG_BUY">STRONG_BUY</option><option value="ADD">ADD</option><option value="ADD_ON_PULLBACK">ADD_ON_PULLBACK</option><option value="HOLD">HOLD</option><option value="RESEARCH_MORE">RESEARCH_MORE</option><option value="TRIM">TRIM</option><option value="avoid_side">Avoid-side (AVOID/IGNORE/SELL/TRIM)</option><option value="AVOID">AVOID</option><option value="IGNORE">IGNORE</option><option value="none">No CIO view</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>List<select style={SEL} value={fList} onChange={e => setFList(e.target.value)}><option value="all">All lists</option>{listOpts.map(l => <option key={l} value={l}>{l}</option>)}<option value="__none">— no list —</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Sector<select style={SEL} value={fSector} onChange={e => setFSector(e.target.value)}><option value="all">All sectors</option>{sectorOpts.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Analyst action<select style={SEL} value={fAnalyst} onChange={e => setFAnalyst(e.target.value)}><option value="all">All</option><option value="upgrade">⬆ Upgrades</option><option value="downgrade">⬇ Downgrades</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Instrument<select style={SEL} value={fKind} onChange={e => setFKind(e.target.value)}><option value="all">All</option><option value="stock">Stocks</option><option value="etf">ETFs / inverse</option><option value="fund">Funds</option></select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Directive<select style={SEL} value={fDir} onChange={e => setFDir(e.target.value)}><option value="all">All</option>{directives.map(d => <option key={d.id} value={String(d.id)}>{dirName(d)}{dirList(d) ? ` · ${dirList(d)}` : ''} ({d.kind})</option>)}</select></label>
        <label style={{ fontSize: 10, color: MUTED, display: 'flex', flexDirection: 'column', gap: 3 }}>Search<input style={SEL} value={search} onChange={e => setSearch(e.target.value)} placeholder="symbol (e.g. DUG — searches full DB)" /></label>
        <div style={{ marginLeft: 'auto', fontSize: 11, color: TEXT2 }}>{visible.length} / {items.length} shown</div>
      </div>

      {/* v4 (B1): saved views chip row */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.05em', color: BB.text3 }}>VIEWS</span>
        {savedViews.map((v, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
            <button onClick={() => applyView(v)} style={{ fontSize: 10, fontWeight: 700, padding: '2px 9px', borderRadius: 999, border: `1px solid ${BB.border}`, background: 'var(--bg2)', color: BB.text2, cursor: 'pointer' }}>{v.name}</button>
            <button title="delete view" onClick={() => saveViews(savedViews.filter((_, j) => j !== i))}
                    style={{ fontSize: 10, border: 'none', background: 'transparent', color: BB.text3, cursor: 'pointer' }}>×</button>
          </span>
        ))}
        {savedViews.length < 8 && (
          <button onClick={() => { const name = window.prompt('Save current filters + search as view:'); if (name) void saveViews([...savedViews, { name: name.slice(0, 24), f: currentFilters() }]) }}
                  style={{ fontSize: 10, fontWeight: 700, padding: '2px 9px', borderRadius: 999, border: `1px dashed ${BB.border}`, background: 'transparent', color: BB.text3, cursor: 'pointer' }}>+ save view</button>
        )}
      </div>

      {/* v4 (B2): bulk action bar — appears when rows are selected */}
      {selSyms.length > 0 && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, padding: '6px 10px', background: 'rgba(255, 176, 0, 0.08)', border: `1px solid ${BB.amber}44`, borderRadius: 2, fontSize: 11 }}>
          <b style={{ color: BB.amber }}>{selSyms.length} selected</b>
          <span style={{ color: BB.text3 }}>(cap 25)</span>
          <button style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, border: `1px solid ${BB.amber}`, background: 'rgba(255, 176, 0, 0.14)', color: BB.amber, cursor: 'pointer' }}
            onClick={() => {
              const syms = selSyms.slice(0, 25)
              if (!window.confirm(`Star ${syms.length} symbols?`)) return
              syms.forEach(s => { const it = items.find((x: any) => String(x.symbol).toUpperCase() === s); if (it && !isStarred(it)) toggleStar(it) })
              setActionToast(`Starred ${syms.length} symbols`); setSelected({})
            }}>★ Star all</button>
          <button style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, border: `1px solid ${BB.amber}`, background: 'transparent', color: BB.amber, cursor: 'pointer' }}
            onClick={async () => {
              const syms = selSyms.slice(0, 25)
              const cond = window.prompt(`Bulk alert for ${syms.length} symbols — condition (rsi_below | rsi_above | price_cross_below | price_cross_above):`, 'rsi_below')
              if (!cond) return
              const th = window.prompt('Threshold (applied to all):', cond.startsWith('rsi') ? '40' : '')
              if (!th) return
              if (!window.confirm(`Arm ${syms.length} alerts: ${cond} ${th}?`)) return
              let ok = 0
              for (const s of syms) {
                const r = await fetch('/api/v2/watch/alerts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: s, condition_type: cond.trim(), threshold: Number(th) }) }).then(x => x.json()).catch(() => null)
                if (r?.ok ?? r?.data?.ok) ok++
              }
              setActionToast(`Alerts armed on ${ok}/${syms.length}`); setSelected({})
            }}>🔔 Alert all</button>
          {/* V5 (Section 7): decision-desk bulk actions — cap 25, cost preview, idempotent server-side */}
          {watchV5Enabled() && (
            <>
              <button style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, border: `1px solid ${T.link}88`, background: 'transparent', color: T.link, cursor: 'pointer' }}
                disabled={Object.keys(strategyBusy).length > 0}
                onClick={() => {
                  const syms = selSyms.slice(0, 25)
                  if (!window.confirm(`Rebuild LOCAL strategies for ${syms.length} symbols?\nDeterministic — zero model calls, ~1–2 min.`)) return
                  void refreshStrategy(syms, 'bulk_local_rebuild'); setSelected({})
                }}>⟳ Rebuild Local</button>
              <button style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, border: `1px solid ${T.link}88`, background: 'transparent', color: T.link, cursor: 'pointer' }}
                disabled={Object.keys(strategyBusy).length > 0}
                onClick={async () => {
                  const syms = selSyms.slice(0, 25)
                  if (!window.confirm(`Run STANDARD BLIND for ${syms.length} symbols?\nEstimated model-lane calls: ${2 * syms.length} (free OAuth lanes — Grok + ChatGPT). Paid cost: $0.`)) return
                  const res = await enqueueStrategyRefresh(syms, { scope: 'AFFECTED_DIMENSIONS', tier: 'STANDARD_BLIND', force: true, reason: 'bulk_standard_blind' })
                  if (!res.ok || !res.run_id) { setActionToast(`Blind refresh failed: ${res.error ?? 'unknown'}`); return }
                  setActionToast(`Standard Blind queued (run ${res.run_id}) — ${res.queued} symbols, est ${res.estimated_lane_calls} lane calls`)
                  setSelected({})
                  const done = await pollRefreshRun(res.run_id, { timeoutMs: 420_000 })
                  const bad = done?.jobs?.filter(j => j.state === 'FAILED').length ?? 0
                  setActionToast(bad ? `Blind refresh: ${bad} failed — see run ${res.run_id}` : `Blind refresh complete (run ${res.run_id})`)
                  await refetchWl(); void refetchDeskSummary()
                }}>◎ Standard Blind</button>
              <button style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, border: `1px solid ${BB.border}`, background: 'transparent', color: BB.text2, cursor: 'pointer' }}
                onClick={async () => {
                  const syms = selSyms.slice(0, 25)
                  const r = await fetch('/api/v2/watch/decision/premium/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbols: syms }) }).then(x => x.json()).catch(() => null)
                  const d = r?.data ?? r
                  setActionToast(d?.allowed === false
                    ? `Premium: ${String(d.reason || '').slice(0, 120)}`
                    : `Premium estimate: ${d?.estimated_calls ?? syms.length} calls ≈ $${d?.estimated_cost_usd ?? '?'} (${d?.provider ?? '?'})`)
                }}>$ Premium Estimate</button>
              <button style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, border: `1px solid ${BB.border}`, background: 'transparent', color: BB.text2, cursor: 'pointer' }}
                onClick={() => {
                  const syms = selSyms.slice(0, 25)
                  if (!window.confirm(`Refresh INPUTS (news/technicals/enrichment) for ${syms.length} symbols? Packets are NOT rebuilt.`)) return
                  syms.forEach((s, i) => window.setTimeout(() => void runRefresh(s, 'manual'), i * 1500))
                  setActionToast(`Inputs refresh queued for ${syms.length} symbols (staggered)`); setSelected({})
                }}>Refresh Inputs</button>
            </>
          )}
          <button style={{ fontSize: 10, padding: '3px 10px', borderRadius: 2, border: `1px solid ${BB.border}`, background: 'transparent', color: BB.text3, cursor: 'pointer' }} onClick={() => setSelected({})}>Clear</button>
        </div>
      )}

      <div style={{ fontSize: 11, color: AMBER, marginBottom: 12, padding: '9px 13px', background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.28)', borderRadius: 2 }}>{adv?.disclaimer ?? 'Advisory only — current technical posture vs the post-trade prior. Never gates promotion/scoring.'}</div>
      {screenerLane && symLookup && visible[0] && !visible[0].screener_pinned && (
        <div style={{ fontSize: 11, color: AMBER, marginBottom: 10, padding: '8px 12px', background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 2 }}>
          <b style={{ color: TEXT0 }}>{symLookup}</b> graduated out of active Screener Finds — CIO is now{' '}
          <b>{String(visible[0].synthesis_recommendation || visible[0].latest_recommendation || 'non-buy-side').replace(/_/g, ' ')}</b>
          {' '}(lane requires BUY / STRONG_BUY / ADD / ADD_ON_PULLBACK). Showing direct lookup card.
        </div>
      )}
      {actionToast && (
        <div style={{ fontSize: 11, color: GREEN, marginBottom: 10, padding: '8px 12px', background: 'rgba(34,197,94,.1)', border: '1px solid rgba(34,197,94,.25)', borderRadius: 2 }}>
          {actionToast}
          {actionToast.includes('proposal') && (
            <a href="/v3/trading?tab=Proposals" style={{ marginLeft: 10, color: BLUE, fontWeight: 700 }}>Open Proposals →</a>
          )}
        </div>
      )}

      <div style={panel}>
        {/* V5 DESK TOOLBAR — server-owned freshness truth + bounded page refresh */}
        {watchV5Enabled() && deskSummary?.ok && (
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 10,
                        padding: '6px 10px', border: `1px solid ${T.link}44`, borderRadius: 2, fontSize: 11 }}>
            <b style={{ letterSpacing: '.06em', color: TEXT0 }}>WATCH DECISION DESK</b>
            <span style={{ color: TEXT2 }}>{deskSummary.symbols} packets</span>
            <span style={{ color: BB.green }}>{deskSummary.current} current</span>
            <span style={{ color: BB.amber }}>{deskSummary.due_soon} due soon</span>
            <span style={{ color: BB.red }}>{deskSummary.stale} stale</span>
            {deskSummary.refreshing > 0 && <span style={{ color: T.link }}>{deskSummary.refreshing} refreshing</span>}
            {deskSummary.failed > 0 && <span style={{ color: BB.red }}>{deskSummary.failed} failed</span>}
            <span style={{ color: TEXT2 }}>· {deskSummary.session} · TTL {deskSummary.ttl_hours}h · policy v{deskSummary.policy_version}</span>
            <button
              onClick={() => {
                const syms = pageItems.filter(it => it.decision_packet).map(it => String(it.symbol).toUpperCase())
                if (syms.length) void refreshStrategy(syms, 'toolbar_refresh_page')
              }}
              disabled={Object.keys(strategyBusy).length > 0}
              style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, padding: '2px 8px', cursor: 'pointer',
                       background: 'transparent', color: T.link, border: `1px solid ${T.link}66`, borderRadius: 2 }}>
              Refresh Current Page
            </button>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ fontSize: 15, fontWeight: 900, color: TEXT0 }}>Watchlist ({visible.length})</div>
            <span title="Security Card v4 — live on all desk surfaces (watchlist, proposals, positions, options)"
                  style={{ fontSize: 10, fontWeight: 800, padding: '3px 10px', borderRadius: 2, color: T.link, background: `${T.link}22`, border: `1px solid ${T.link}55` }}>
              {watchV5Enabled() ? 'Decision Desk v5' : 'Card v4 · live'}
            </span>
          </div>
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
            {symLookup
              ? screenerLane
                ? <><b style={{ color: TEXT0 }}>{symLookup}</b> is not in the watchlist DB (or was removed). If it was auto-researched, check <span onClick={() => window.location.href = '/v3/intelligence?tab=research'} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Intelligence → Research</span>. Active Screener Finds require buy-side CIO. {link(BLUE, 'Clear search', () => setSearch(''))}</>
                : <><b style={{ color: TEXT0 }}>{symLookup}</b> is not on the watchlist (or was removed). Check <span onClick={() => window.location.href = '/v3/intelligence?tab=research'} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Intelligence → Research</span> for auto-research briefs. {link(BLUE, 'Clear search', () => setSearch(''))}</>
              : sd
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
              const kbFocused = pageItems[kbIdx]?.id === it.id
              // Live holdings only — never outcome history or stale source=portfolio rows.
              const held = !!(it.in_portfolio || (heldMap[symKey] && heldMap[symKey].length > 0))
              return (
                <div key={it.id} ref={el => { if (kbFocused && el) el.scrollIntoView({ block: 'nearest' }) }}
                     style={{ minWidth: 0, width: '100%', ...focusStyle(kbFocused) }}>
                {/* v4 (B2/B3): select-for-bulk + HELD pill — rendered AROUND the locked Card v4 */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '1px 4px' }}>
                  <input type="checkbox" checked={!!selected[symKey]} title="select for bulk Star/Alert"
                         onChange={e => setSelected(o => ({ ...o, [symKey]: e.target.checked }))}
                         style={{ accentColor: BB.amber, cursor: 'pointer' }} />
                  {held && <Chip kind="state" tone="green"
                                 title="Currently held in live portfolio (holdings.json)">HELD</Chip>}
                  {/* Levels ride in the wrapper strip, not inside Card v4 — that card family is
                      LOCKED to the approved format and is bugfix-only. */}
                  <LevelLines symbol={symKey} row={levels[symKey]} />
                </div>
                {/* Watch Desk v3 (WS-C): deterministic context strip — reuses server _hermes_setup; not a quality score */}
                {it.setup_context && (
                  <div title={it.setup_context.label} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10.5, color: 'var(--text3)', padding: '2px 4px' }}>
                    <span style={{ fontFamily: BB.mono, fontVariantNumeric: 'tabular-nums', fontWeight: 800, color: T.link }}>{it.setup_context.glyphs}</span>
                    <span style={{ fontWeight: 700 }}>{it.setup_context.type}</span>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>· {it.setup_context.hint}</span>
                    <button title="Arm an alert on this symbol (WS-B): price/RSI threshold, evaluated every 20 min RTH"
                      onClick={(e) => { e.stopPropagation(); void armAlert(it) }}
                      style={{ marginLeft: 'auto', fontSize: 11, border: 'none', background: 'transparent', color: T.link, cursor: 'pointer' }}>🔔</button>
                  </div>
                )}
                <WatchlistCardV4
                  it={it}
                  adv={advMap[symKey] ?? advMap[it.symbol]}
                  sc={cardMap[symKey] ?? cardMap[it.symbol]}
                  pa={paMap[symKey] ?? paMap[it.symbol]}
                  outcome={outcome ? { ...outcome, sold: (outcome.closed_trades ?? 0) > 0 } : undefined}
                  llms={extMap[symKey] ?? extMap[it.symbol] ?? []}
                  fv={fvMap[symKey] ?? fvMap[it.symbol]}
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
                  onRefreshStrategy={watchV5Enabled() ? (e => { e.stopPropagation(); void refreshStrategy([it.symbol]) }) : undefined}
                  strategyRefreshing={!!strategyBusy[symKey]}
                  onToggleEns={() => setEnsOpen(o => ({ ...o, [it.id]: !o[it.id] }))}
                  onPropose={openProposeModal}
                  onAdjust={it => openDesk(it.symbol)}
                  onBuildPlan={buildPlan}
                  onOpenDesk={openDesk}
                  onCioDone={() => void refetchWl()}
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
        <div style={{ fontSize: 10, color: MUTED, marginTop: 10 }}>Decision-first cards — CIO view, confidence, R:R, L/S/target, model, data-quality flags, and reasoning visible by default. Street analyst shown with divergence when CIO disagrees. Advisory-only — never places trades.</div>
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
  const fld: React.CSSProperties = { fontSize: 11, padding: '7px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 2, color: TEXT0, width: '100%' }
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
  return <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.58)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}><div onClick={e => e.stopPropagation()} style={{ ...panel, width: 540, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto' }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}><div style={{ fontSize: 16, fontWeight: 900, color: TEXT0 }}>Add Watch Directive</div><button onClick={onClose} style={{ background: 'none', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 16 }}>x</button></div><div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>{(['ticker', 'sector', 'trend'] as const).map(k => <button key={k} onClick={() => setKind(k)} style={{ flex: 1, padding: '7px 0', fontSize: 11, borderRadius: 2, border: 'none', cursor: 'pointer', textTransform: 'capitalize', background: kind === k ? 'rgba(167, 139, 250, 0.2)' : 'var(--bg2)', color: kind === k ? T.extIntel.hermes : MUTED, fontWeight: kind === k ? 800 : 500 }}>{k}</button>)}</div>{kind === 'ticker' && <div style={{ marginBottom: 10 }}><label style={lbl}>Symbol</label><input style={fld} value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="RKLB" autoFocus /></div>}{kind === 'sector' && <div style={{ marginBottom: 10 }}><label style={lbl}>Sector</label><select style={fld} value={sector} onChange={e => setSector(e.target.value)}><option value="">— select sector —</option>{sectors.map(s => <option key={s.sector} value={s.sector}>{s.sector} ({s.count})</option>)}</select>{selSector && <div style={{ fontSize: 10, color: MUTED, marginTop: 6, padding: '7px 9px', background: 'var(--bg2)', borderRadius: 2 }}>Resolves to the sector ETF + up to 25 constituents. First: {(selSector.sample || []).join(', ')}</div>}</div>}{kind === 'trend' && <><div style={{ marginBottom: 10 }}><label style={lbl}>Keywords</label><input style={fld} value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="AI datacenter, power" autoFocus /></div><div style={{ marginBottom: 10 }}><label style={lbl}>Seed symbols</label><input style={fld} value={seeds} onChange={e => setSeeds(e.target.value)} placeholder="NVDA, VRT" /></div></>}<div style={{ marginBottom: 10 }}><label style={lbl}>List / label <span style={{ color: MUTED, fontWeight: 400 }}>— pick an existing list or type a new one</span></label><input style={fld} list="watchlist-list-names" value={label} onChange={e => setLabel(e.target.value)} placeholder="e.g. Data Center (blank = general Watchlist)" /><datalist id="watchlist-list-names">{lists.map(l => <option key={l} value={l} />)}</datalist></div><div style={{ marginBottom: 10 }}><label style={lbl}>Rationale / thesis</label><input style={fld} value={rationale} onChange={e => setRationale(e.target.value)} placeholder="why watch this" /></div><div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}><label style={{ flex: 1, ...lbl }}>Priority<select style={fld} value={priority} onChange={e => setPriority(e.target.value)}><option value="normal">normal</option><option value="high">high</option></select></label><label style={{ flex: 1, ...lbl }}>TTL days<input style={fld} value={ttl} onChange={e => setTtl(e.target.value.replace(/\D/g, ''))} placeholder="standing" /></label></div><div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 11, color: TEXT2 }}><label><input type="checkbox" checked={taOn} onChange={e => setTaOn(e.target.checked)} /> Trade AI</label><label><input type="checkbox" checked={hermesOn} onChange={e => setHermesOn(e.target.checked)} /> Hermes</label></div><div style={{ fontSize: 10, color: MUTED, marginBottom: 12, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 2, borderLeft: `3px solid ${PURPLE}` }}><b style={{ color: TEXT2 }}>How it promotes:</b> {governor}</div>{msg && <div style={{ fontSize: 11, color: msg.startsWith('Error') ? RED : GREEN, marginBottom: 10 }}>{msg}</div>}<div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}><button onClick={onClose} style={{ padding: '8px 14px', fontSize: 11, borderRadius: 2, border: '1px solid var(--border)', background: 'var(--bg2)', color: TEXT2, cursor: 'pointer' }}>Cancel</button><button disabled={busy || !canSave} onClick={save} style={{ padding: '8px 18px', fontSize: 11, fontWeight: 800, borderRadius: 2, border: 'none', background: PURPLE, color: BB.text0, cursor: busy || !canSave ? 'not-allowed' : 'pointer', opacity: busy || !canSave ? 0.5 : 1 }}>Save Directive</button></div></div></div>
}

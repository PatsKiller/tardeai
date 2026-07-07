import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApi } from '../hooks/useApi'
import ManualExecutionModal, { type ManualExecSeed } from './ManualExecutionModal'
import BrokerPromoteModal, { type BrokerPromoteSeed } from './BrokerPromoteModal'
import BrokerRouteConfirmModal from './BrokerRouteConfirmModal'
import ManualExecutionLog from './ManualExecutionLog'
import ExecutionPathsStrip from './ExecutionPathsStrip'
import BrokerProposalCard from './BrokerProposalCard'
import BrokerProposalCardV4 from './BrokerProposalCardV4'
import { useCardsV4 } from '../lib/cardsV4'
import ProtectionProposalCard from './ProtectionProposalCard'
import QueueHealthPanel from './QueueHealthPanel'
import ProposalQueueSummaryBar from './ProposalQueueSummaryBar'
import GradingAuditMethodology from './GradingAuditMethodology'
import DeskAutomationBar from './DeskAutomationBar'
import { brokerOf, formatCloudRanAt, pickFreshOversight } from '../lib/brokerThesis'
import { desk } from '../lib/proposalDeskTheme'
import type { BrokerAccount } from './BrokerAccountPicker'

// #30 — narrow-screen detection so fixed card grids fall back to single column without restructuring layout.
function useIsNarrow(maxWidth = 720) {
  const query = `(max-width: ${maxWidth}px)`
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches,
  )
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(query)
    const onChange = () => setNarrow(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])
  return narrow
}

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const RED = '#ef4444'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const
const inp = { fontSize: 12, padding: '6px 9px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: '100%' } as const
const btn = (c: string, busy = false, primary = false) => ({
  fontSize: 11,
  fontWeight: primary ? 800 : 700,
  padding: '6px 13px',
  borderRadius: 7,
  border: primary ? `1px solid ${c}` : `1px solid ${desk.border}`,
  background: primary ? `${c}1f` : desk.bgInset,
  color: primary ? c : desk.text,
  cursor: busy ? 'not-allowed' as const : 'pointer' as const,
  whiteSpace: 'nowrap' as const,
})
const sel = { ...inp, width: 'auto', minWidth: 110, cursor: 'pointer' } as const

type ListFilters = {
  page: number
  pageSize: number
  sort: string
  kind: string
  source: string
  zone: string
  account: string
  symbol: string
  rrPreset: string
}

const DEFAULT_FILTERS: ListFilters = {
  page: 1,
  pageSize: 15,
  sort: 'priority',
  kind: 'all',
  source: '',
  zone: '',
  account: '',
  symbol: '',
  rrPreset: '',
}

const isProtectionProposal = (p: { queue_kind?: string; proposal_kind?: string; id?: number }) =>
  p.queue_kind === 'protection' || p.proposal_kind === 'protection' || (typeof p.id === 'number' && p.id < 0)

const entryProposalIds = (rows: { id?: number; queue_kind?: string; proposal_kind?: string }[]) =>
  rows.filter(p => !isProtectionProposal(p)).map(p => p.id).filter((id): id is number => typeof id === 'number' && id > 0)

const proposalLaneKey = (p: any) => {
  const lane = p.routing_lane || p.source_attribution?.routing_lane
    || (/schwab|fidelity/i.test(String(p.intended_broker || p.account || '')) ? 'live_2fa' : 'paper_atm')
  return `${String(p.symbol || '').toUpperCase()}:${lane}`
}

/** One card per symbol × lane — prefer filled trade, else oldest proposal id. */
const dedupeEntryProposals = (rows: any[]) => {
  const protection = rows.filter(isProtectionProposal)
  const entries = rows.filter(p => !isProtectionProposal(p))
  const best = new Map<string, any>()
  for (const p of entries) {
    const key = proposalLaneKey(p)
    const prev = best.get(key)
    if (!prev) { best.set(key, p); continue }
    const pFilled = p.traded?.status === 'open' || p.lane_gates?.paper_atm?.status === 'filled'
    const prevFilled = prev.traded?.status === 'open' || prev.lane_gates?.paper_atm?.status === 'filled'
    if (pFilled && !prevFilled) { best.set(key, p); continue }
    if (!pFilled && prevFilled) continue
    if ((p.id || 0) < (prev.id || 0)) best.set(key, p)
  }
  const kept = new Set([...best.values()].map((p: any) => p.id))
  return [...protection, ...entries.filter(p => kept.has(p.id))]
}

const RR_PRESET_SORT: Record<string, string> = {
  best: 'rr_live',
  live_2: 'rr_live',
  live_15: 'rr_live',
  planned_2: 'rr',
}

export default function BrokerProposals({ focusSymbol }: { focusSymbol?: string } = {}) {
  // Global card-family v4 evaluation toggle (switch UI lives on the Watch hub).
  const [cardsV4] = useCardsV4()
  const ProposalCard = cardsV4 ? BrokerProposalCardV4 : BrokerProposalCard
  const [listFilters, setListFilters] = useState<ListFilters>(DEFAULT_FILTERS)
  const [bypassCache, setBypassCache] = useState(false)
  const [view, setView] = useState<'active' | 'expired'>('active')
  const listPath = useMemo(() => {
    const p = new URLSearchParams()
    if (view === 'expired') p.set('status', 'EXPIRED')
    p.set('page', String(listFilters.page))
    p.set('page_size', String(listFilters.pageSize))
    if (bypassCache) p.set('refresh', '1')
    const sort = listFilters.rrPreset && RR_PRESET_SORT[listFilters.rrPreset]
      ? RR_PRESET_SORT[listFilters.rrPreset]
      : listFilters.sort
    if (sort) p.set('sort', sort)
    if (listFilters.kind && listFilters.kind !== 'all') p.set('kind', listFilters.kind)
    if (listFilters.source) p.set('source', listFilters.source)
    if (listFilters.zone) p.set('zone', listFilters.zone)
    if (listFilters.account) p.set('account', listFilters.account)
    if (listFilters.symbol) p.set('symbol', listFilters.symbol)
    if (listFilters.rrPreset) p.set('rr_preset', listFilters.rrPreset)
    return `/api/v2/broker-proposals?${p.toString()}`
  }, [listFilters, bypassCache, view])

  const [fastPoll, setFastPoll] = useState(false)
  const { data, loading, error, stale, refetch } = useApi<any>(listPath, fastPoll ? 15_000 : 30_000)
  useEffect(() => {
    const qs = data?.queue_summary
    setFastPoll(Boolean(qs && qs.route_ready === 0 && (qs.blocked ?? 0) > 0))
  }, [data?.queue_summary])
  const { data: outcomesData } = useApi<any>('/api/v2/rec-intel/outcomes', 300_000)
  const { data: fvStrip } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: pullbackData } = useApi<any>('/api/v2/pullback-macd/candidates', 60_000)
  const { data: propHealth } = useApi<any>('/api/v2/health/proposals', 120_000)
  const execReady = propHealth?.execution_readiness
  const isNarrow = useIsNarrow(720)

  // #31 — stamp last-updated time whenever the list payload changes; derive next auto-refresh (30s poll).
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)
  useEffect(() => { if (data) setLastUpdated(Date.now()) }, [data])

  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const outMap: Record<string, any> = outcomesData?.outcomes ?? {}
  const accounts: BrokerAccount[] = data?.accounts ?? []
  const strategies: string[] = data?.strategies ?? []
  const proposals: any[] = data?.proposals ?? []
  const pullbackTriggers = (pullbackData?.candidates ?? []).filter((c: any) => c.tier === 'trigger')
  // "in queue" = triggers whose linked proposal is actually LIVE (PENDING/APPROVED) — i.e. what the
  // source=pullback_macd list shows. Triggers pointing to expired/rejected proposals are NOT queued;
  // counting them (old bug: `.filter(c => c.proposal_id)`) made the widget claim more than the list.
  const pullbackPending = pullbackTriggers.filter((c: any) => c.proposal_live)
  const pullbackStale = pullbackTriggers.filter((c: any) => c.proposal_id && !c.proposal_live)

  const [f, setF] = useState<any>({ account: '', symbol: '', shares: '', entry: '', stop: '', target: '', strategy_id: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [routeMsg, setRouteMsg] = useState<Record<number, string>>({})
  const [routeIntent, setRouteIntent] = useState<Record<number, {
    intent_id: string
    symbol: string
    summary?: string
    trade?: any
    trade_packet?: any
    policy_warnings?: string[]
  }>>({})
  const [routeSeed, setRouteSeed] = useState<any | null>(null)
  const [routeApproveTk, setRouteApproveTk] = useState<Record<number, string>>({})
  const [routeApproveCode, setRouteApproveCode] = useState<Record<number, string>>({})
  const [routeBusy, setRouteBusy] = useState<Record<number, boolean>>({})
  const [heldOnly, setHeldOnly] = useState(false)
  const [focus, setFocus] = useState((focusSymbol || '').toUpperCase())
  const [modalSeed, setModalSeed] = useState<ManualExecSeed | null>(null)
  const [adjustSeed, setAdjustSeed] = useState<BrokerPromoteSeed | null>(null)
  const [destAccount, setDestAccount] = useState<Record<number, string>>({})
  const [oversightBusy, setOversightBusy] = useState<Record<number, boolean>>({})
  const [cloudBusy, setCloudBusy] = useState<Record<number, boolean>>({})
  const [refreshBusy, setRefreshBusy] = useState<Record<number, boolean>>({})
  const [oversightMsg, setOversightMsg] = useState<Record<number, string>>({})
  const [acctPreview, setAcctPreview] = useState<Record<number, { account: string; evaluation: any }>>({})
  const [acctPreviewBusy, setAcctPreviewBusy] = useState<Record<number, boolean>>({})
  const [detailMap, setDetailMap] = useState<Record<number, any>>({})
  const [detailBusy, setDetailBusy] = useState<Record<number, boolean>>({})
  const [batchCloudBusy, setBatchCloudBusy] = useState(false)
  const [batchCloudMsg, setBatchCloudMsg] = useState('')
  // #31 — bulk select across cards (reuses existing cloud-batch / refresh-batch flows; no new routing/2FA).
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [validateBusy, setValidateBusy] = useState<Record<number, boolean>>({})
  const [litmusMap, setLitmusMap] = useState<Record<number, any>>({})
  const [agentBatchBusy, setAgentBatchBusy] = useState(false)
  const [reconcileBusy, setReconcileBusy] = useState(false)
  const [llmMatureBusy, setLlmMatureBusy] = useState(false)
  const [bulkActionBusy, setBulkActionBusy] = useState(false)
  const [bulkActionMsg, setBulkActionMsg] = useState('')
  const [cardActionBusy, setCardActionBusy] = useState<Record<number, boolean>>({})
  const [resizeBusy, setResizeBusy] = useState<Record<number, boolean>>({})
  const detailLoadedRef = useRef<Set<number>>(new Set())
  const detailInflightRef = useRef<Set<number>>(new Set())
  const cloudPollRef = useRef<Record<number, ReturnType<typeof setInterval>>>({})
  const pagination = data?.pagination ?? { page: 1, page_size: 15, total: 0, total_pages: 1 }
  const queueTotal = Number(pagination.total || proposals.length || 0)
  const queuePageSize = Number(pagination.page_size || listFilters.pageSize || 15)
  const queueTotalPages = Math.max(
    Number(pagination.total_pages || 1),
    queueTotal > 0 ? Math.ceil(queueTotal / queuePageSize) : 1,
  )
  const queuePage = Number(pagination.page || listFilters.page || 1)
  const hasQueuePages = queueTotalPages > 1

  const patchFilters = (patch: Partial<ListFilters>) => {
    setListFilters(prev => {
      const next = { ...prev, ...patch }
      if (patch.page === undefined && Object.keys(patch).some(k => k !== 'page')) {
        next.page = 1
      }
      return next
    })
    detailLoadedRef.current.clear()
    setDetailMap({})
  }

  const fetchProposalDetail = useCallback(async (pid: number, opts?: { force?: boolean }) => {
    if (!opts?.force && (detailLoadedRef.current.has(pid) || detailInflightRef.current.has(pid))) return
    detailInflightRef.current.add(pid)
    setDetailBusy(b => ({ ...b, [pid]: true }))
    try {
      const r = await fetch('/api/v2/broker-proposals/detail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid, light: true }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok && d?.id) {
        detailLoadedRef.current.add(pid)
        setDetailMap(prev => ({ ...prev, [pid]: d }))
        const cloudSt = String(d?.oversight?.cloud_review?.status || d?.intel?.oversight?.cloud_review?.status || '').toLowerCase()
        if (cloudSt === 'running') {
          setCloudBusy(m => ({ ...m, [pid]: true }))
          if (!cloudPollRef.current[pid]) {
            cloudPollRef.current[pid] = setInterval(() => {
              detailLoadedRef.current.delete(pid)
              fetchProposalDetail(pid, { force: true })
            }, 15_000)
          }
        } else {
          setCloudBusy(m => ({ ...m, [pid]: false }))
          if (cloudPollRef.current[pid]) {
            clearInterval(cloudPollRef.current[pid])
            delete cloudPollRef.current[pid]
          }
        }
      }
    } catch { /* keep list row */ }
    finally {
      detailInflightRef.current.delete(pid)
      setDetailBusy(b => ({ ...b, [pid]: false }))
    }
  }, [])

  useEffect(() => () => {
    for (const t of Object.values(cloudPollRef.current)) clearInterval(t)
  }, [])

  // Light detail (DB-only oversight, no Schwab) for every card on the current page.
  useEffect(() => {
    if (!proposals.length || loading) return
    let cancelled = false
    const run = async () => {
      await new Promise(r => setTimeout(r, 800))
      if (cancelled) return
      for (const p of proposals) {
        if (isProtectionProposal(p)) continue
        if (!p.detail_pending && detailLoadedRef.current.has(p.id)) continue
        fetchProposalDetail(p.id)
        await new Promise(r => setTimeout(r, 250))
        if (cancelled) return
      }
    }
    run()
    return () => { cancelled = true }
  }, [proposals, fetchProposalDetail, loading])

  useEffect(() => {
    if (!proposals.length) return
    setDestAccount(prev => {
      const next = { ...prev }
      for (const p of proposals) {
        if (!next[p.id]) next[p.id] = p.account || accounts[0]?.account_key || ''
      }
      return next
    })
  }, [proposals, accounts])

  const mergeProposal = (raw: any) => {
    const detail = detailMap[raw.id] || {}
    const merged = { ...raw, ...detail }
    const intel = merged.intel || detail.intel
    if (intel?.company) {
      merged.sector = merged.sector || intel.company.sector
      merged.industry = merged.industry || intel.company.industry
      merged.instrument_type = merged.instrument_type || intel.company.instrument_type
      if (intel.company.description) merged.company_description = intel.company.description
    }
    if (intel?.strategy) {
      merged.strategy_display_name = intel.strategy.display_name || merged.strategy_display_name
      merged.strategy_type_label = intel.strategy.strategy_type_label || merged.strategy_type_label
      merged.strategy_description = intel.strategy.purpose || merged.strategy_description
    }
    // Light detail prefetch uses DB price — must not clobber list live-quote thesis band.
    const listFresh = raw.price_stale === false || (raw.thesis_validity && !raw.thesis_validity.price_stale)
    const detailStale = detail.price_stale === true || detail.thesis_validity?.zone_status === 'stale_price'
    if (listFresh && detailStale) {
      merged.thesis_validity = raw.thesis_validity
      merged.price_stale = raw.price_stale
      merged.live_rr = raw.live_rr
      merged.quote_last = raw.quote_last
      merged.quote_bid = raw.quote_bid
      merged.quote_ask = raw.quote_ask
      merged.refreshed_at = raw.refreshed_at
      merged.quote_provider = raw.quote_provider
      merged.price_drift_pct = raw.price_drift_pct
    }
    const freshOv = pickFreshOversight(
      detail.oversight,
      detail.intel?.oversight,
      detail.evaluation?.oversight,
      acctPreview[raw.id]?.evaluation?.oversight,
      raw.evaluation?.oversight,
      raw.oversight,
    )
    if (freshOv && Object.keys(freshOv).length) {
      merged.oversight = freshOv
      merged.evaluation = { ...(merged.evaluation || raw.evaluation || {}), oversight: freshOv }
      const baseIntel = detail.intel || merged.intel || raw.intel
      if (baseIntel?.ok === true) {
        merged.intel = {
          ...baseIntel,
          oversight: pickFreshOversight(freshOv, baseIntel.oversight),
          agent_reviews: freshOv.agents?.reviews || baseIntel.agent_reviews || [],
        }
      } else if (!baseIntel?.lazy) {
        merged.intel = {
          ok: true,
          oversight: freshOv,
          agent_reviews: freshOv.agents?.reviews || [],
        }
      } else {
        merged.intel = baseIntel
      }
    }
    const preview = acctPreview[raw.id]
    if (preview) merged._preview = preview
    return merged
  }

  const isHeld = (sym: string) => !!outMap[String(sym).toUpperCase()]?.held
  const heldN = proposals.filter(p => isHeld(p.symbol)).length
  let shown = heldOnly ? proposals.filter(p => isHeld(p.symbol)) : proposals
  if (focus && proposals.some(p => String(p.symbol).toUpperCase() === focus)) {
    shown = shown.filter(p => String(p.symbol).toUpperCase() === focus)
  }
  shown = dedupeEntryProposals(shown)

  const set = (k: string, v: any) => setF({ ...f, [k]: v })

  const postJson = async (path: string, body: object) => {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    return r.json()
  }

  const afterQueueMutation = () => {
    setBypassCache(true)
    refetch?.()
    setTimeout(() => setBypassCache(false), 2000)
  }

  const bulkAction = async (action: string, ids: number[], reason?: string) => {
    setBulkActionBusy(true)
    setBulkActionMsg('')
    try {
      const res = await postJson('/api/v2/broker-proposals/bulk-action', { proposal_ids: ids, action, reason })
      setBulkActionMsg(res.ok ? `✅ ${action}: ${res.succeeded}/${res.total}` : `⚠ ${res.error || action}`)
      if (res.ok) afterQueueMutation()
    } catch (e: any) {
      setBulkActionMsg(`⚠ ${String(e?.message || e).slice(0, 80)}`)
    } finally {
      setBulkActionBusy(false)
    }
  }

  const resizeToCap = async (pid: number) => {
    setResizeBusy(m => ({ ...m, [pid]: true }))
    try {
      const res = await postJson('/api/v2/broker-proposals/resize-to-cap', { proposal_id: pid })
      if (res.ok) afterQueueMutation()
    } finally {
      setResizeBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const cardAction = async (pid: number, action: 'reject' | 'expire', reason: string) => {
    setCardActionBusy(m => ({ ...m, [pid]: true }))
    try {
      await bulkAction(action, [pid], reason)
    } finally {
      setCardActionBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const queueAgentBatch = async () => {
    setAgentBatchBusy(true)
    try {
      await postJson('/api/v2/broker-proposals/queue-agent-batch', {})
      afterQueueMutation()
    } finally {
      setAgentBatchBusy(false)
    }
  }

  const reconcileSleeves = async () => {
    setReconcileBusy(true)
    try {
      const res = await postJson('/api/v2/broker-proposals/reconcile-sleeves', {})
      setBulkActionMsg(res.ok ? `✅ Reconciled ${res.updated} sleeve(s)` : `⚠ reconcile failed`)
      if (res.ok) afterQueueMutation()
    } finally {
      setReconcileBusy(false)
    }
  }

  const matureLlmStage2b = async (ids?: number[]) => {
    setLlmMatureBusy(true)
    try {
      const res = await postJson('/api/v2/broker-proposals/mature-llm-stage-2b', { proposal_ids: ids })
      setBulkActionMsg(res.ok ? `✅ LLM stage 2b: ${res.reviewed} reviewed` : `⚠ LLM mature failed`)
      if (res.ok) afterQueueMutation()
    } finally {
      setLlmMatureBusy(false)
    }
  }
  const refreshAll = () => { refetch?.() }

  const submit = async () => {
    if (!(f.account && f.symbol && f.shares && f.entry && f.stop && f.target)) {
      setMsg('fill account, symbol, shares, entry, stop, target')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/manual-submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account: f.account, symbol: f.symbol.toUpperCase(), strategy_id: f.strategy_id || strategies[0],
          shares: Number(f.shares), entry: Number(f.entry), stop: Number(f.stop), target: Number(f.target),
        }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (d.success) {
        setMsg(`✅ Manual proposal #${d.proposal_id} created for ${f.symbol.toUpperCase()} (${brokerOf(f.account)})`)
        setF({ ...f, symbol: '', shares: '', entry: '', stop: '', target: '' })
        refreshAll()
      } else setMsg(`⛔ ${d.message || d.error || 'failed'}`)
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const openRouteReview = (p: any) => {
    const pid = p.id
    setRouteIntent(prev => { const n = { ...prev }; delete n[pid]; return n })
    setRouteApproveTk(prev => { const n = { ...prev }; delete n[pid]; return n })
    setRouteApproveCode(prev => { const n = { ...prev }; delete n[pid]; return n })
    setRouteMsg(m => ({ ...m, [pid]: '' }))
    setRouteSeed({ ...p, account: destAccount[pid] ?? p.account ?? '' })
  }

  const handleRouteComplete = (pid: number, d: any) => {
    if (d.mode === 'awaiting_approval' && d.intent_id) {
      const summ = d.summary?.summary || d.summary || ''
      const trade = d.trade_packet || d.trade || {}
      setRouteIntent(prev => ({
        ...prev,
        [pid]: {
          intent_id: d.intent_id,
          symbol: String(d.symbol || trade.symbol || '').toUpperCase(),
          summary: summ,
          trade,
          trade_packet: trade,
          policy_warnings: d.policy_warnings || trade.policy_warnings,
        },
      }))
      const short = String(d.intent_id).slice(0, 8)
      setRouteMsg(prev => ({
        ...prev,
        [pid]: `🔐 2FA required — intent ${short}${d.ttl_min ? ` · ${d.ttl_min}min` : ''}`,
      }))
      refetch?.()
      return
    }
    const leg = d.order_spec?.orderLegCollection?.[0]
    const bracket = d.bracket ? ' OTOCO bracket' : ''
    const wouldSubmit = leg
      ? ` · would POST${bracket}: ${leg.instruction} ${leg.quantity} ${leg.instrument?.symbol} ${d.order_spec.orderType} $${d.order_spec.price}`
      : ''
    const m = d.ok && d.record_only
      ? `📝 ${d.detail}`
      : d.gated
        ? `🔒 ${d.detail}${wouldSubmit}`
        : d.ok
          ? `✅ routed`
          : `⛔ ${d.error || d.detail || 'failed'}`
    setRouteMsg(prev => ({ ...prev, [pid]: m }))
    refetch?.()
  }

  const confirmRoute = async (pid: number, channel: 'web' | 'telegram') => {
    const intent = routeIntent[pid]
    if (!intent?.intent_id) {
      setRouteMsg(prev => ({ ...prev, [pid]: '⛔ no active intent — click Auto route first' }))
      return
    }
    setRouteBusy(b => ({ ...b, [pid]: true }))
    try {
      const code = channel === 'web'
        ? (routeApproveTk[pid] || '').trim().toUpperCase()
        : (routeApproveCode[pid] || '').trim()
      const r = await fetch('/api/v2/broker-proposals/route/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent_id: intent.intent_id, channel, code }),
      }).then(x => x.json())
      const d = r.data ?? r
      const oid = d.broker_order_id ?? d.result?.broker_order_id
      const st = d.status ?? d.result?.status
      const submitted = st === 'submitted' || st === 'filled' || d.ok === true
      if (d.stage === 'confirm' && d.ok && d.fully_approved === false) {
        setRouteMsg(prev => ({ ...prev, [pid]: 'channel confirmed — waiting on other factor' }))
      } else if (submitted && d.ok !== false) {
        setRouteIntent(prev => { const n = { ...prev }; delete n[pid]; return n })
        setRouteMsg(prev => ({ ...prev, [pid]: `✅ LIVE bracket placed · order #${oid ?? '—'} (${st ?? 'submitted'})` }))
        refetch?.()
      } else {
        setRouteMsg(prev => ({ ...prev, [pid]: `⛔ ${d.error || d.result?.error || 'confirm failed'}` }))
      }
    } catch (e: any) {
      setRouteMsg(prev => ({ ...prev, [pid]: '⛔ ' + String(e).slice(0, 80) }))
    } finally {
      setRouteBusy(b => ({ ...b, [pid]: false }))
    }
  }

  const openManual = (p: any) => {
    const acct = destAccount[p.id] || p.account || accounts[0]?.account_key || ''
    setModalSeed({ symbol: p.symbol, account: acct, proposal_id: p.id, execution_type: 'equity' })
  }

  const fetchAccountPreview = useCallback(async (p: any, acct: string) => {
    if (!acct) return
    const pid = p.id
    if (acct === (p.account || '')) {
      setAcctPreview(prev => { const n = { ...prev }; delete n[pid]; return n })
      return
    }
    setAcctPreviewBusy(b => ({ ...b, [pid]: true }))
    try {
      const r = await fetch('/api/v2/broker-proposals/evaluate-promote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: pid,
          account: acct,
          strategy_id: p.strategy_id,
          shares: Number(p.proposed_shares),
          entry: Number(p.proposed_entry),
          stop: Number(p.proposed_stop),
          target: Number(p.proposed_target1),
        }),
      }).then(x => x.json())
      const ev = r.data ?? r
      setAcctPreview(prev => ({ ...prev, [pid]: { account: acct, evaluation: ev } }))
    } catch {
      setAcctPreview(prev => ({ ...prev, [pid]: { account: acct, evaluation: null } }))
    } finally {
      setAcctPreviewBusy(b => ({ ...b, [pid]: false }))
    }
  }, [])

  useEffect(() => {
    if (!proposals.length) return
    for (const p of proposals) {
      const dest = destAccount[p.id] ?? p.account ?? ''
      if (dest && dest !== p.account && !acctPreview[p.id]) {
        fetchAccountPreview(p, dest)
      }
    }
  }, [proposals, destAccount, acctPreview, fetchAccountPreview])

  const validateTrade = async (p: any, opts?: { runCloud?: boolean }) => {
    const pid = p.id
    const dest = destAccount[pid] || p.account || ''
    setValidateBusy(m => ({ ...m, [pid]: true }))
    setOversightMsg(m => ({ ...m, [pid]: '' }))
    try {
      const r = await fetch('/api/v2/broker-proposals/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: pid,
          account: dest || undefined,
          refresh: 1,
          run_cloud: opts?.runCloud ? 1 : 0,
        }),
      }).then(x => x.json())
      const d = r.data?.facts ? r.data : (r.data?.data ?? r.litmus ?? r.data ?? r)
      if (r.ok && Array.isArray(d?.facts) && d.facts.length) {
        setLitmusMap(prev => ({ ...prev, [pid]: d }))
        const cloudRan = d.cloud_review?.ran_at
        const cloudSt = d.cloud_review?.status
        setOversightMsg(m => ({
          ...m,
          [pid]: `Litmus ${d.verdict || '—'}${d.validated_at ? ` · ${d.validated_at}` : ''}`
            + (cloudSt && cloudSt !== 'not_run'
              ? ` · cloud ${String(cloudSt).toUpperCase()}${cloudRan ? ` (${formatCloudRanAt(cloudRan).label})` : ''}`
              : ''),
        }))
        const freshOv = d.oversight || (d.evaluation?.oversight ? d.evaluation.oversight : null)
        detailLoadedRef.current.add(pid)
        setDetailMap(prev => ({
          ...prev,
          [pid]: {
            ...(prev[pid] || {}),
            thesis_validity: d.thesis_validity ?? prev[pid]?.thesis_validity,
            live_rr: d.live_rr ?? prev[pid]?.live_rr,
            current_price: d.live_price ?? prev[pid]?.current_price,
            refreshed_at: d.validated_at_utc ?? prev[pid]?.refreshed_at,
            quote_provider: d.quote?.provider ?? prev[pid]?.quote_provider,
            price_drift_pct: d.drift_pct ?? prev[pid]?.price_drift_pct,
            gate_status: d.gate_status ?? prev[pid]?.gate_status,
            evaluation: d.evaluation
              ? { ...(prev[pid]?.evaluation || {}), ...d.evaluation, oversight: freshOv || d.evaluation?.oversight }
              : prev[pid]?.evaluation,
            oversight: freshOv || prev[pid]?.oversight,
            intel: freshOv ? {
              ...(prev[pid]?.intel || { ok: true }),
              ok: true,
              oversight: freshOv,
              agent_reviews: freshOv.agents?.reviews || prev[pid]?.intel?.agent_reviews || [],
            } : prev[pid]?.intel,
          },
        }))
        if (opts?.runCloud || d.cloud_run) {
          detailLoadedRef.current.delete(pid)
          setTimeout(() => fetchProposalDetail(pid, { force: true }), 2000)
        }
        refetch?.()
      } else {
        setOversightMsg(m => ({
          ...m,
          [pid]: `⛔ Validate: ${r.error || d?.error || 'no facts returned'}`,
        }))
      }
    } catch (e: any) {
      setOversightMsg(m => ({ ...m, [pid]: `⛔ Validate: ${String(e).slice(0, 80)}` }))
    } finally {
      setValidateBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const refreshPrices = async (p: any) => {
    const pid = p.id
    const dest = destAccount[pid] || p.account || ''
    setRefreshBusy(m => ({ ...m, [pid]: true }))
    try {
      const r = await fetch('/api/v2/broker-proposals/refresh-prices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid, account: dest || undefined }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok && d?.id) {
        detailLoadedRef.current.add(pid)
        setDetailMap(prev => ({ ...prev, [pid]: d }))
        if (dest && dest !== (p.account || '')) {
          setAcctPreview(prev => ({
            ...prev,
            [pid]: { account: dest, evaluation: d.evaluation || r.recalibration?.evaluation },
          }))
        }
      }
    } catch { /* ignore */ }
    finally {
      setRefreshBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const queueOversight = async (pid: number) => {
    setOversightBusy(m => ({ ...m, [pid]: true }))
    setOversightMsg(m => ({ ...m, [pid]: '' }))
    try {
      const r = await fetch('/api/v2/broker-proposals/queue-oversight', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid }),
      }).then(x => x.json())
      setOversightMsg(m => ({ ...m, [pid]: r.ok ? '✅ Local reviews queued' : `⛔ ${r.error || 'failed'}` }))
      if (r.ok) setTimeout(() => { detailLoadedRef.current.delete(pid); fetchProposalDetail(pid) }, 5000)
    } catch (e: any) {
      setOversightMsg(m => ({ ...m, [pid]: '⛔ ' + String(e).slice(0, 60) }))
    } finally {
      setOversightBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const runCloudOversight = async (pid: number) => {
    setCloudBusy(m => ({ ...m, [pid]: true }))
    setOversightMsg(m => ({ ...m, [pid]: 'Running Grok+ChatGPT…' }))
    try {
      const r = await fetch('/api/v2/broker-proposals/run-cloud-oversight', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid, timeout: 120 }),
      }).then(x => x.json())
      const payload = r.data ?? r
      if (r.ok) {
        const cloud = payload.cloud || {}
        const oversight = payload.oversight || {}
        const verdict = cloud.consensus?.verdict || cloud.status || oversight.cloud_review?.status || 'done'
        const ran = cloud.ran_at || oversight.cloud_review?.ran_at
        const ts = ran ? formatCloudRanAt(ran).label : ''
        setOversightMsg(m => ({
          ...m,
          [pid]: `✅ Cloud: ${verdict}${ts ? ` · ${ts}` : ''}`,
        }))
        setDetailMap(prev => ({
          ...prev,
          [pid]: {
            ...(prev[pid] || {}),
            oversight,
            evaluation: {
              ...(prev[pid]?.evaluation || {}),
              oversight,
              warnings: oversight.warnings || prev[pid]?.evaluation?.warnings,
              violations: oversight.violations || prev[pid]?.evaluation?.violations,
              status: prev[pid]?.evaluation?.status === 'BLOCK' ? 'BLOCK' : oversight.status,
            },
            intel: {
              ...(prev[pid]?.intel || {}),
              ok: true,
              oversight,
              agent_reviews: oversight.agents?.reviews || prev[pid]?.intel?.agent_reviews || [],
            },
          },
        }))
        detailLoadedRef.current.delete(pid)
        await fetchProposalDetail(pid, { force: true })
        refetch?.()
      } else {
        setOversightMsg(m => ({ ...m, [pid]: `⛔ ${r.error || payload.error || 'failed'}` }))
      }
    } catch (e: any) {
      setOversightMsg(m => ({ ...m, [pid]: '⛔ ' + String(e).slice(0, 60) }))
    } finally {
      setCloudBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const [refreshAllBusy, setRefreshAllBusy] = useState(false)

  const refreshPricesBatch = async (ids: number[]) => {
    const valid = ids.filter(Boolean)
    if (!valid.length) return
    setRefreshAllBusy(true)
    try {
      const r = await fetch('/api/v2/broker-proposals/refresh-prices-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_ids: valid }),
      }).then(x => x.json())
      if (r.ok) {
        setBypassCache(true)
        detailLoadedRef.current.clear()
        setDetailMap({})
        refetch?.()
        setTimeout(() => setBypassCache(false), 2500)
        // Re-queue cloud oversight when prices move thesis zone (oversight freshness coupling).
        try {
          await fetch('/api/v2/broker-proposals/queue-cloud-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope: 'ids', proposal_ids: valid, max: 30 }),
          })
        } catch { /* non-fatal */ }
      }
    } catch { /* ignore */ }
    finally {
      setRefreshAllBusy(false)
    }
  }

  const refreshAllPrices = () => refreshPricesBatch(entryProposalIds(shown))

  const queueCloudBatch = async (scope: 'page' | 'filtered' | 'selected', selectedList?: number[]) => {
    setBatchCloudBusy(true)
    setBatchCloudMsg('Queuing Grok+ChatGPT…')
    try {
      const max = 30
      const body = (scope === 'page' || scope === 'selected')
        ? { scope: 'ids', proposal_ids: scope === 'selected' ? (selectedList || []).filter(id => id > 0) : entryProposalIds(shown), max }
        : {
            scope: 'filtered',
            max,
            filters: {
              sort: listFilters.rrPreset && RR_PRESET_SORT[listFilters.rrPreset] ? RR_PRESET_SORT[listFilters.rrPreset] : listFilters.sort,
              source: listFilters.source || undefined,
              zone: listFilters.zone || undefined,
              account: listFilters.account || undefined,
              symbol: listFilters.symbol || undefined,
              rr_preset: listFilters.rrPreset || undefined,
            },
          }
      const r = await fetch('/api/v2/broker-proposals/queue-cloud-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok) {
        const n = d.queued_count ?? (d.queued?.length ?? 0)
        const sk = d.skipped_count ?? (d.skipped?.length ?? 0)
        setBatchCloudMsg(`✅ Queued cloud for ${n}${sk ? ` · skipped ${sk} (cached/running)` : ''}`)
        for (const pid of (d.queued || [])) {
          setCloudBusy(m => ({ ...m, [pid]: true }))
          detailLoadedRef.current.delete(pid)
          if (!cloudPollRef.current[pid]) {
            cloudPollRef.current[pid] = setInterval(() => {
              detailLoadedRef.current.delete(pid)
              fetchProposalDetail(pid, { force: true })
            }, 15_000)
          }
        }
        setTimeout(() => {
          for (const pid of (d.queued || [])) fetchProposalDetail(pid, { force: true })
        }, 4000)
      } else {
        setBatchCloudMsg(`⛔ ${r.error || d.error || 'failed'}`)
      }
    } catch (e: any) {
      setBatchCloudMsg(`⛔ ${String(e).slice(0, 80)}`)
    } finally {
      setBatchCloudBusy(false)
    }
  }

  // #31 — bulk select helpers
  const shownIds = entryProposalIds(shown)
  const selectedShownIds = shownIds.filter(id => selectedIds.has(id))
  const allShownSelected = shownIds.length > 0 && selectedShownIds.length === shownIds.length
  const toggleSelected = (pid: number) => setSelectedIds(prev => {
    const next = new Set(prev)
    if (next.has(pid)) next.delete(pid); else next.add(pid)
    return next
  })
  const selectAllShown = () => setSelectedIds(prev => {
    const next = new Set(prev)
    if (allShownSelected) { for (const id of shownIds) next.delete(id) }
    else { for (const id of shownIds) next.add(id) }
    return next
  })
  const clearSelection = () => setSelectedIds(new Set())
  const enterSelectMode = () => { setSelectMode(true) }
  const exitSelectMode = () => { setSelectMode(false); clearSelection() }
  const bulkRefreshSelected = () => refreshPricesBatch(selectedShownIds)
  const bulkCloudSelected = () => queueCloudBatch('selected', selectedShownIds)

  const fmtClock = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

  const qs = data?.queue_summary
  const blockedN = qs?.blocked ?? 0
  const unrouted48 = execReady?.broker_unrouted_48h ?? 0
  const lowLink = (execReady?.link_rate_pct ?? 100) < (execReady?.target_link_rate_pct ?? 15)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: '100%', maxWidth: 1180, marginInline: 'auto' }}>
      {(blockedN > 0 || unrouted48 > 0 || lowLink) && (
        <div style={{ padding: '10px 14px', borderRadius: 10, background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.35)', fontSize: 11, lineHeight: 1.5 }}>
          <div style={{ fontWeight: 700, color: '#f59e0b', marginBottom: 4 }}>Execution readiness</div>
          {blockedN > 0 && <div style={{ color: 'var(--text2)' }}>{blockedN} proposal(s) blocked in queue — expand cards for lane gates.</div>}
          {unrouted48 > 0 && <div style={{ color: 'var(--text2)' }}>{unrouted48} unrouted &gt;48h — link or dismiss stale proposals.</div>}
          {lowLink && <div style={{ color: 'var(--text2)' }}>Link rate {execReady?.link_rate_pct ?? '—'}% below target {execReady?.target_link_rate_pct ?? 15}%.</div>}
          <a href="/v3/health" style={{ display: 'inline-block', marginTop: 6, fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>Health → proposals →</a>
        </div>
      )}
      {modalSeed && (
        <ManualExecutionModal seed={modalSeed} onClose={() => setModalSeed(null)} onLogged={refreshAll} />
      )}
      {adjustSeed && (
        <BrokerPromoteModal seed={adjustSeed} mode="adjust" onClose={() => setAdjustSeed(null)} onPromoted={refreshAll} />
      )}
      {routeSeed && (
        <BrokerRouteConfirmModal
          proposal={routeSeed}
          account={destAccount[routeSeed.id] ?? routeSeed.account ?? ''}
          accounts={accounts}
          onClose={() => setRouteSeed(null)}
          onRouted={d => handleRouteComplete(routeSeed.id, d)}
        />
      )}

      {focus && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, fontSize: 11.5, background: 'rgba(96,165,250,.1)', border: '1px solid rgba(96,165,250,.35)', color: '#93c5fd' }}>
          <span>Focused on <b style={{ fontFamily: 'monospace', color: TEXT0 }}>{focus}</b>.</span>
          <button onClick={() => setFocus('')} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, padding: '3px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>show all</button>
        </div>
      )}

      <GradingAuditMethodology />

      <DeskAutomationBar
        automation={data?.desk_automation}
        queueGeneratedAt={data?.queue_summary?.generated_at}
      />

      <QueueHealthPanel
        autoOpen={data?.queue_summary?.route_ready === 0 && (data?.queue_summary?.blocked ?? 0) > 0}
        onRequeued={() => { setBypassCache(true); refetch?.(); setTimeout(() => setBypassCache(false), 2000) }}
      />
      <ProposalQueueSummaryBar
        summary={data?.queue_summary}
        onQueueAgents={queueAgentBatch}
        onReconcile={reconcileSleeves}
        onMatureLlm={() => matureLlmStage2b(entryProposalIds(shown))}
        agentBusy={agentBatchBusy}
        reconcileBusy={reconcileBusy}
        llmBusy={llmMatureBusy}
      />
      {bulkActionMsg && (
        <div style={{ fontSize: 11, marginBottom: 8, color: bulkActionMsg.startsWith('✅') ? GREEN : AMBER }}>{bulkActionMsg}</div>
      )}

      {pullbackTriggers.length > 0 && (
        <div style={{
          padding: '10px 12px', borderRadius: 10, marginBottom: 4,
          background: 'linear-gradient(90deg, rgba(245,158,11,.14), rgba(34,197,94,.06))',
          border: '1px solid rgba(245,158,11,.45)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: AMBER }}>Pullback / MACD triggers</span>
            <span style={{ fontSize: 10, color: MUTED }}>
              {pullbackPending.length} in queue · {pullbackTriggers.length} active trigger{pullbackTriggers.length === 1 ? '' : 's'}
              {pullbackStale.length > 0 && (
                <span style={{ color: AMBER }}> · {pullbackStale.length} expired/rejected (no live proposal)</span>
              )}
            </span>
            <button
              onClick={() => patchFilters({ source: 'pullback_macd', page: 1, sort: 'priority' })}
              style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 6,
                border: `1px solid ${AMBER}66`, background: `${AMBER}18`, color: AMBER, cursor: 'pointer' }}
            >
              Show pullback only
            </button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {pullbackTriggers.map((c: any) => {
              // three states so the widget never overstates the queue: live proposal (green, in the
              // filtered list), dead-linked proposal (red — expired/rejected, NOT in the list), or none.
              const live = !!c.proposal_live
              const dead = !!c.proposal_id && !live
              const col = live ? GREEN : dead ? RED : AMBER
              const tail = live ? ` · #${c.proposal_id}`
                : dead ? ` · ${String(c.proposal_status || 'gone').toLowerCase()}`
                : ' · no proposal'
              return (
                <button
                  key={c.symbol}
                  onClick={() => patchFilters({ symbol: c.symbol, source: '', page: 1 })}
                  title={live ? `Proposal #${c.proposal_id} live in queue · ${c.pullback_pct}% off high`
                    : dead ? `Proposal #${c.proposal_id} is ${String(c.proposal_status || 'gone').toLowerCase()} — not in the queue; re-scan to refresh`
                    : 'No proposal yet — run the pullback scan'}
                  style={{
                    fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${col}55`, background: `${col}14`, color: col,
                  }}
                >
                  {c.symbol} · {Number(c.pullback_pct).toFixed(1)}%{tail}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {!!data?.hygiene?.changed && (
        <div style={{ padding: '8px 12px', borderRadius: 8, fontSize: 11, background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.35)', color: AMBER }}>
          Auto-cleared {data.hygiene.changed} stale broker row(s)
          {(data.hygiene.expired || data.hygiene.rejected) ? ` (${data.hygiene.expired || 0} expired · ${data.hygiene.rejected || 0} superseded)` : ''}.
        </div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
        padding: '12px 14px', borderRadius: desk.radiusLg, border: `1px solid ${desk.border}`, background: desk.bg,
      }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: desk.text, letterSpacing: '-.01em' }}>
            Path B · Broker proposals
          </div>
          <div style={{ fontSize: 10, color: desk.textDim, marginTop: 3, maxWidth: 520, lineHeight: 1.45 }}>
            Live-route queue with thesis validation, agent consensus, and Litmus pre-check before 2FA.
            P0 validation caps are advisory — oversight BLOCK still hard-stops auto-route.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <div style={{ display: 'inline-flex', borderRadius: desk.radius, overflow: 'hidden', border: `1px solid ${desk.border}` }}>
            {(['active', 'expired'] as const).map(v => (
              <button key={v} onClick={() => { setView(v); setListFilters(f => ({ ...f, page: 1 })) }}
                style={{
                  padding: '5px 14px', fontSize: 11, fontWeight: 700, cursor: 'pointer', border: 'none',
                  background: view === v ? desk.bgInset : 'transparent',
                  color: view === v ? desk.text : desk.textDim, textTransform: 'capitalize',
                }}>
                {v}
              </button>
            ))}
          </div>
          <details style={{ fontSize: 10 }}>
            <summary style={{ cursor: 'pointer', color: desk.blue, fontWeight: 600, listStyle: 'none' }}>Execution paths</summary>
            <div style={{ marginTop: 8, maxWidth: 480 }}>
              <ExecutionPathsStrip variant="live" />
            </div>
          </details>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            onClick={() => { setBypassCache(true); refetch?.(); setTimeout(() => setBypassCache(false), 2000) }}
            disabled={loading}
            aria-label="Reload proposal queue"
            style={btn(BLUE, loading)}
          >
            {loading ? '…' : '↻ Reload queue'}
          </button>
          {shown.length > 0 && (
            <button onClick={refreshAllPrices} disabled={refreshAllBusy} aria-label="Refresh all prices and recalibrate" style={btn(GREEN, refreshAllBusy, true)} title="Batch Schwab quotes for this page — updates live R:R and thesis band">
              {refreshAllBusy ? '…' : '↻ Refresh all + recalibrate'}
            </button>
          )}
        </div>
      </div>

      <ManualExecutionLog mode="equity" onRefresh={refreshAll} />

      <details style={card}>
        <summary style={{ fontSize: 13, fontWeight: 800, color: TEXT0, cursor: 'pointer' }}>Manual submit (ad-hoc)</summary>
        <div style={{ display: 'grid', gridTemplateColumns: isNarrow ? '1fr 1fr' : 'repeat(4, 1fr)', gap: 10, fontSize: 11, marginTop: 12 }}>
          <label>Account
            <select style={inp} value={f.account} onChange={e => set('account', e.target.value)}>
              <option value="">— select —</option>
              {accounts.map(a => <option key={a.account_key} value={a.account_key}>{brokerOf(a.account_key)} · {a.display_name || a.account_key}</option>)}
            </select>
          </label>
          <label>Strategy
            <select style={inp} value={f.strategy_id} onChange={e => set('strategy_id', e.target.value)}>
              {strategies.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Symbol<input style={inp} value={f.symbol} onChange={e => set('symbol', e.target.value.toUpperCase())} placeholder="AAPL" /></label>
          <label>Shares<input style={inp} value={f.shares} onChange={e => set('shares', e.target.value.replace(/[^0-9]/g, ''))} /></label>
          <label>Entry<input style={inp} value={f.entry} onChange={e => set('entry', e.target.value)} /></label>
          <label>Stop<input style={inp} value={f.stop} onChange={e => set('stop', e.target.value)} /></label>
          <label>Target<input style={inp} value={f.target} onChange={e => set('target', e.target.value)} /></label>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button onClick={submit} disabled={busy} style={btn(GREEN, busy)}>{busy ? '…' : 'Create proposal'}</button>
          </div>
        </div>
        {msg && <div style={{ fontSize: 11, marginTop: 9, color: msg.startsWith('✅') ? GREEN : AMBER }}>{msg}</div>}
      </details>

      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0 }}>
            Proposals ({shown.length}{heldOnly ? ` on page` : ''}
            {queueTotal ? ` · ${queueTotal} total` : ''}
            {hasQueuePages ? ` · page ${queuePage}/${queueTotalPages}` : ''})
          </div>
          <button onClick={() => setHeldOnly(h => !h)} aria-pressed={heldOnly} aria-label="Show held-symbol proposals only" style={{
            fontSize: 10.5, fontWeight: 800, padding: '5px 11px', borderRadius: 6, cursor: 'pointer',
            border: `1px solid ${heldOnly ? BLUE : 'var(--border)'}`, background: heldOnly ? 'rgba(96,165,250,.14)' : 'transparent', color: heldOnly ? BLUE : MUTED,
          }}>● Held only{heldN ? ` (${heldN})` : ''}</button>
          {shown.length > 0 && (
            <button
              onClick={() => selectMode ? exitSelectMode() : enterSelectMode()}
              aria-pressed={selectMode}
              aria-label={selectMode ? 'Exit bulk select mode' : 'Enter bulk select mode'}
              style={{
                fontSize: 10.5, fontWeight: 800, padding: '5px 11px', borderRadius: 6, cursor: 'pointer',
                border: `1px solid ${selectMode ? AMBER : 'var(--border)'}`, background: selectMode ? 'rgba(245,158,11,.14)' : 'transparent', color: selectMode ? AMBER : MUTED,
              }}
            >☑ Select{selectedShownIds.length ? ` (${selectedShownIds.length})` : ''}</button>
          )}
          <span style={{ flex: 1 }} />
          {lastUpdated && (
            <span style={{ fontSize: 9, color: MUTED }} title="List auto-refreshes every 30s">
              updated {fmtClock(lastUpdated)}{loading ? ' · refreshing…' : ' · next ~30s'}
            </span>
          )}
          {(stale || data?.cached) && (
            <span style={{ fontSize: 9, color: AMBER }}>
              {data?.cached ? `cached ${data.cache_age_sec ?? ''}s` : 'cached data'}
            </span>
          )}
          {data?.autocal?.updated > 0 && (
            <span style={{ fontSize: 9, color: GREEN }}>
              auto-recal {data.autocal.updated} row(s)
            </span>
          )}
          {data?.autocal?.skipped && data?.autocal?.reason === 'throttled' && (
            <span style={{ fontSize: 9, color: MUTED }} title="Background job recalibrates stale prices every 5m">
              prices auto-sync · next ~{data.autocal.sec_until_next ?? '?'}s
            </span>
          )}
          {data?.curator?.curated != null && (
            <span style={{ fontSize: 9, color: BLUE }} title="30m trading-hours curator: prices, criteria, strategy, support lines">
              curated {data.curator.curated} row(s)
              {data.curator.expired ? ` · ${data.curator.expired} expired` : ''}
            </span>
          )}
        </div>

        <div style={{ ...card, marginBottom: 12, padding: '10px 12px' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: TEXT0, marginBottom: 8 }}>
            Queue filters · sort · pagination
          </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Sort
            <select style={sel} value={listFilters.sort} onChange={e => patchFilters({ sort: e.target.value })}>
              <option value="priority">Priority (Hermes · newest)</option>
              <option value="zone">Thesis zone</option>
              <option value="rr_live">Live R:R</option>
              <option value="rr">Planned R:R</option>
              <option value="hermes">Hermes score</option>
              <option value="symbol">Symbol A–Z</option>
              <option value="created">Newest</option>
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Type
            <select style={sel} value={listFilters.kind} onChange={e => patchFilters({ kind: e.target.value })}>
              <option value="all">All</option>
              <option value="broker">Broker-routed</option>
              <option value="proposal">Proposals</option>
              <option value="protection">Protection</option>
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Source
            <select style={sel} value={listFilters.source} onChange={e => patchFilters({ source: e.target.value })}>
              <option value="">All</option>
              <option value="pullback_macd">Pullback / MACD</option>
              <option value="watchlist">Watchlist</option>
              <option value="proposal">Proposal</option>
              <option value="both">Both</option>
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Zone
            <select style={sel} value={listFilters.zone} onChange={e => patchFilters({ zone: e.target.value })}>
              <option value="">All</option>
              <option value="comfortable">Comfortable</option>
              <option value="approaching">Approaching</option>
              <option value="at_risk">At risk</option>
              <option value="invalid">Invalid</option>
              <option value="stale_price">Stale price (refresh needed)</option>
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            R:R / quality
            <select style={sel} value={listFilters.rrPreset} onChange={e => patchFilters({ rrPreset: e.target.value })}>
              <option value="">Any</option>
              <option value="best">Best setups (actionable · live ≥2)</option>
              <option value="live_2">Live R:R ≥ 2.0</option>
              <option value="live_15">Live R:R ≥ 1.5</option>
              <option value="planned_2">Planned R:R ≥ 2.0</option>
              <option value="actionable">Actionable thesis only</option>
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Account
            <select style={sel} value={listFilters.account} onChange={e => patchFilters({ account: e.target.value })}>
              <option value="">All</option>
              {accounts.map(a => (
                <option key={a.account_key} value={a.account_key}>
                  {brokerOf(a.account_key)} · {a.display_name || a.account_key}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Symbol
            <input
              style={{ ...inp, width: 72 }}
              value={listFilters.symbol}
              placeholder="e.g. DLR"
              aria-label="Filter proposals by symbol"
              onChange={e => patchFilters({ symbol: e.target.value.toUpperCase() })}
            />
          </label>
          {(listFilters.kind !== 'all' || listFilters.source || listFilters.zone || listFilters.account || listFilters.symbol || listFilters.rrPreset || listFilters.sort !== 'priority') && (
            <button
              onClick={() => patchFilters({ ...DEFAULT_FILTERS })}
              style={{ fontSize: 10, fontWeight: 700, padding: '5px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}
            >
              Clear filters
            </button>
          )}
          <span style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 2px' }} />
          <button
            onClick={() => queueCloudBatch('page')}
            disabled={batchCloudBusy || shown.length === 0}
            title="Queue Grok+ChatGPT for visible cards on this page only"
            style={btn(AMBER, batchCloudBusy || shown.length === 0)}
          >
            {batchCloudBusy ? '…' : `☁ Run cloud · page (${shown.length})`}
          </button>
          <button
            onClick={() => queueCloudBatch('filtered')}
            disabled={batchCloudBusy || !(queueTotal > 0)}
            title="Queue Grok+ChatGPT for up to 30 proposals matching current filters"
            style={btn(AMBER, batchCloudBusy || !(queueTotal > 0))}
          >
            {batchCloudBusy ? '…' : `☁ Run cloud · filtered (≤30 of ${queueTotal || 0})`}
          </button>
          {hasQueuePages && (
            <>
              <span style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 2px' }} />
              <button
                disabled={queuePage <= 1 || loading}
                onClick={() => patchFilters({ page: Math.max(1, queuePage - 1) })}
                style={btn(BLUE, loading || queuePage <= 1)}
              >
                ← Prev
              </button>
              <span style={{ fontSize: 10, color: MUTED }}>Page {queuePage} / {queueTotalPages}</span>
              <button
                disabled={queuePage >= queueTotalPages || loading}
                onClick={() => patchFilters({ page: Math.min(queueTotalPages, queuePage + 1) })}
                style={btn(BLUE, loading || queuePage >= queueTotalPages)}
              >
                Next →
              </button>
              <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
                Per page
                <select
                  style={sel}
                  value={listFilters.pageSize}
                  onChange={e => patchFilters({ pageSize: Number(e.target.value), page: 1 })}
                >
                  {[10, 15, 20, 30, 50].map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            </>
          )}
        </div>
        </div>
        {(listFilters.rrPreset === 'live_2' || listFilters.rrPreset === 'live_15' || listFilters.rrPreset === 'best') && (
          <div style={{ fontSize: 10, color: MUTED, marginBottom: 8 }}>
            Live R:R excludes prices older than 20m — ↻ Refresh all prices first; stale cards show gray “stale_price”.
          </div>
        )}
        {batchCloudMsg && (
          <div style={{ fontSize: 11, marginBottom: 10, color: batchCloudMsg.startsWith('✅') ? GREEN : AMBER }}>
            {batchCloudMsg}
          </div>
        )}

        {loading && proposals.length === 0 && !error && (
          <div style={{ fontSize: 11, color: MUTED }}>
            Loading broker queue… {stale ? '(showing cached)' : '(API may take 10–20s when server is busy)'}
          </div>
        )}
        {error && proposals.length === 0 && (
          <div style={{ fontSize: 11, color: AMBER }}>Unavailable ({error}) — <span role="button" tabIndex={0} aria-label="Retry loading proposals" onClick={() => refetch?.()} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') refetch?.() }} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>retry</span></div>
        )}
        {!loading && !error && proposals.length === 0 && (
          <div style={{ fontSize: 11, color: MUTED }}>No proposals match the current Type filter{listFilters.kind !== 'all' ? ` (${listFilters.kind})` : ''}.</div>
        )}
        {proposals.length > 0 && shown.length === 0 && (
          <div style={{ fontSize: 11, color: MUTED }}>No held-symbol proposals. <span role="button" tabIndex={0} onClick={() => setHeldOnly(false)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setHeldOnly(false) }} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Show all</span></div>
        )}

        {selectMode && shown.length > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 12,
            padding: '8px 12px', borderRadius: 8, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)',
          }}>
            <button
              onClick={selectAllShown}
              aria-label={allShownSelected ? 'Deselect all on page' : 'Select all on page'}
              style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 11px', borderRadius: 6, cursor: 'pointer', border: '1px solid var(--border)', background: 'transparent', color: BLUE }}
            >{allShownSelected ? '☐ Deselect page' : '☑ Select page'}</button>
            <span style={{ fontSize: 11, color: AMBER, fontWeight: 700 }}>{selectedShownIds.length} selected</span>
            <span style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 2px' }} />
            <button
              onClick={bulkRefreshSelected}
              disabled={refreshAllBusy || selectedShownIds.length === 0}
              aria-label="Refresh prices for selected proposals"
              title="Batch Schwab quotes for the selected cards"
              style={btn(GREEN, refreshAllBusy || selectedShownIds.length === 0)}
            >{refreshAllBusy ? '…' : `↻ Refresh selected (${selectedShownIds.length})`}</button>
            <button
              onClick={bulkCloudSelected}
              disabled={batchCloudBusy || selectedShownIds.length === 0}
              aria-label="Run cloud oversight for selected proposals"
              title="Queue Grok+ChatGPT for the selected cards"
              style={btn(AMBER, batchCloudBusy || selectedShownIds.length === 0)}
            >{batchCloudBusy ? '…' : `☁ Run cloud selected (${selectedShownIds.length})`}</button>
            <button onClick={() => bulkAction('resize_to_cap', selectedShownIds)} disabled={bulkActionBusy || selectedShownIds.length === 0}
              style={btn(BLUE, bulkActionBusy || selectedShownIds.length === 0)}>Resize to cap</button>
            <button onClick={() => bulkAction('reject', selectedShownIds, 'operator_bulk_reject')} disabled={bulkActionBusy || selectedShownIds.length === 0}
              style={btn(RED, bulkActionBusy || selectedShownIds.length === 0)}>Reject</button>
            <button onClick={() => bulkAction('expire', selectedShownIds, 'operator_bulk_expire')} disabled={bulkActionBusy || selectedShownIds.length === 0}
              style={btn(MUTED, bulkActionBusy || selectedShownIds.length === 0)}>Expire</button>
            <button onClick={() => bulkAction('reject', entryProposalIds(shown).filter(id => {
              const p = shown.find(x => x.id === id)
              return p && (p.thesis_zone === 'invalid' || (p.live_rr != null && Number(p.live_rr) < 2))
            }), 'invalid_thesis_bulk')} disabled={bulkActionBusy}
              style={btn(RED, bulkActionBusy)} title="Reject all invalid-thesis rows on page">Reject invalid thesis</button>
            <span style={{ flex: 1 }} />
            <button
              onClick={exitSelectMode}
              aria-label="Exit bulk select mode"
              style={{ fontSize: 10, fontWeight: 700, padding: '5px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}
            >Done</button>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {shown.some(isProtectionProposal) && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, marginBottom: 8, textTransform: 'uppercase' }}>
                Protection / ATM ({shown.filter(isProtectionProposal).length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {shown.filter(isProtectionProposal).map(rawP => (
                  <ProtectionProposalCard key={rawP.id} proposal={rawP} />
                ))}
              </div>
            </div>
          )}
          {shown.filter(p => !isProtectionProposal(p)).length > 0 && (
            <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, marginBottom: 4, textTransform: 'uppercase' }}>
              Entry proposals ({shown.filter(p => !isProtectionProposal(p)).length})
            </div>
          )}
          {shown.filter(p => !isProtectionProposal(p)).map(rawP => {
            const p = mergeProposal(rawP)
            const dest = destAccount[p.id] ?? p.account ?? ''
            return (
              <ProposalCard
                key={p.id}
                proposal={p}
                accounts={accounts}
                destAccount={dest}
                onDestAccountChange={acct => {
                  setDestAccount(prev => ({ ...prev, [p.id]: acct }))
                  fetchAccountPreview(p, acct)
                }}
                fvMap={fvMap}
                detailLoading={Boolean(rawP.detail_pending && !detailMap[p.id] && detailBusy[p.id])}
                refreshBusy={!!refreshBusy[p.id]}
                oversightBusy={!!oversightBusy[p.id]}
                cloudBusy={!!cloudBusy[p.id]}
                oversightMsg={oversightMsg[p.id]}
                routeMsg={routeMsg[p.id]}
                routeIntent={routeIntent[p.id]}
                routeBusy={!!routeBusy[p.id]}
                routeApproveTk={routeApproveTk[p.id] || ''}
                routeApproveCode={routeApproveCode[p.id] || ''}
                onRouteApproveTkChange={v => setRouteApproveTk(prev => ({ ...prev, [p.id]: v }))}
                onRouteApproveCodeChange={v => setRouteApproveCode(prev => ({ ...prev, [p.id]: v }))}
                onConfirmRoute={ch => confirmRoute(p.id, ch)}
                acctPreviewBusy={!!acctPreviewBusy[p.id]}
                onRefresh={() => { refreshPrices(p); if (p.detail_pending) fetchProposalDetail(p.id, { force: true }) }}
                onEdit={opts => setAdjustSeed({ proposal_id: p.id, symbol: p.symbol, account: dest, shares: opts?.shares })}
                onManual={() => openManual(p)}
                onRoute={() => openRouteReview(p)}
                onQueueOversight={() => queueOversight(p.id)}
                onRunCloudOversight={() => runCloudOversight(p.id)}
                litmus={litmusMap[p.id]}
                validateBusy={!!validateBusy[p.id]}
                onValidate={() => validateTrade(p)}
                narrow={isNarrow}
                selectMode={selectMode}
                selected={selectedIds.has(p.id)}
                onToggleSelected={() => toggleSelected(p.id)}
                onResizeToCap={() => resizeToCap(p.id)}
                onReject={() => cardAction(p.id, 'reject', 'operator_card_reject')}
                onExpire={() => cardAction(p.id, 'expire', 'operator_card_expire')}
                resizeBusy={!!resizeBusy[p.id]}
                actionBusy={!!cardActionBusy[p.id]}
              />
            )
          })}
        </div>

        {hasQueuePages && shown.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
            <button
              disabled={queuePage <= 1 || loading}
              onClick={() => patchFilters({ page: Math.max(1, queuePage - 1) })}
              style={btn(BLUE, loading || queuePage <= 1)}
            >
              ← Prev
            </button>
            <span style={{ fontSize: 11, color: MUTED }}>Page {queuePage} / {queueTotalPages}{queueTotal ? ` (${queueTotal} proposals)` : ''}</span>
            <button
              disabled={queuePage >= queueTotalPages || loading}
              onClick={() => patchFilters({ page: Math.min(queueTotalPages, queuePage + 1) })}
              style={btn(BLUE, loading || queuePage >= queueTotalPages)}
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
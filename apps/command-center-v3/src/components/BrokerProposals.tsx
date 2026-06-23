import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApi } from '../hooks/useApi'
import ManualExecutionModal, { type ManualExecSeed } from './ManualExecutionModal'
import BrokerPromoteModal, { type BrokerPromoteSeed } from './BrokerPromoteModal'
import ManualExecutionLog from './ManualExecutionLog'
import ExecutionPathsStrip from './ExecutionPathsStrip'
import BrokerProposalCard from './BrokerProposalCard'
import { brokerOf } from '../lib/brokerThesis'
import type { BrokerAccount } from './BrokerAccountPicker'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const
const inp = { fontSize: 12, padding: '6px 9px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: '100%' } as const
const btn = (c: string, busy = false) => ({ fontSize: 11, fontWeight: 800, padding: '6px 13px', borderRadius: 7, border: `1px solid ${c}`, background: `${c}1f`, color: c, cursor: busy ? 'not-allowed' as const : 'pointer' as const, whiteSpace: 'nowrap' as const })
const sel = { ...inp, width: 'auto', minWidth: 110, cursor: 'pointer' } as const

type ListFilters = {
  page: number
  pageSize: number
  sort: string
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
  source: '',
  zone: '',
  account: '',
  symbol: '',
  rrPreset: '',
}

const RR_PRESET_SORT: Record<string, string> = {
  best: 'rr_live',
  live_2: 'rr_live',
  live_15: 'rr_live',
  planned_2: 'rr',
}

export default function BrokerProposals({ focusSymbol }: { focusSymbol?: string } = {}) {
  const [listFilters, setListFilters] = useState<ListFilters>(DEFAULT_FILTERS)
  const listPath = useMemo(() => {
    const p = new URLSearchParams()
    p.set('page', String(listFilters.page))
    p.set('page_size', String(listFilters.pageSize))
    const sort = listFilters.rrPreset && RR_PRESET_SORT[listFilters.rrPreset]
      ? RR_PRESET_SORT[listFilters.rrPreset]
      : listFilters.sort
    if (sort) p.set('sort', sort)
    if (listFilters.source) p.set('source', listFilters.source)
    if (listFilters.zone) p.set('zone', listFilters.zone)
    if (listFilters.account) p.set('account', listFilters.account)
    if (listFilters.symbol) p.set('symbol', listFilters.symbol)
    if (listFilters.rrPreset) p.set('rr_preset', listFilters.rrPreset)
    return `/api/v2/broker-proposals?${p.toString()}`
  }, [listFilters])

  const { data, loading, error, stale, refetch } = useApi<any>(listPath, 30_000)
  const { data: outcomesData } = useApi<any>('/api/v2/rec-intel/outcomes', 300_000)
  const { data: fvStrip } = useApi<any>('/api/v2/finviz-strip-map', 300_000)

  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const outMap: Record<string, any> = outcomesData?.outcomes ?? {}
  const accounts: BrokerAccount[] = data?.accounts ?? []
  const strategies: string[] = data?.strategies ?? []
  const proposals: any[] = data?.proposals ?? []

  const [f, setF] = useState<any>({ account: '', symbol: '', shares: '', entry: '', stop: '', target: '', strategy_id: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [routeMsg, setRouteMsg] = useState<Record<number, string>>({})
  const [routeIntent, setRouteIntent] = useState<Record<number, { intent_id: string; symbol: string; summary?: string }>>({})
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
  const detailLoadedRef = useRef<Set<number>>(new Set())
  const detailInflightRef = useRef<Set<number>>(new Set())
  const cloudPollRef = useRef<Record<number, ReturnType<typeof setInterval>>>({})
  const pagination = data?.pagination ?? { page: 1, page_size: 15, total: 0, total_pages: 1 }

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
        body: JSON.stringify({ proposal_id: pid }),
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

  // Prefetch detail for visible page only — matches page_size default.
  const DETAIL_PREFETCH_MAX = listFilters.pageSize
  useEffect(() => {
    if (!proposals.length) return
    let cancelled = false
    const run = async () => {
      await new Promise(r => setTimeout(r, 800))
      if (cancelled) return
      let n = 0
      for (const p of proposals) {
        if (!p.detail_pending) continue
        if (n >= DETAIL_PREFETCH_MAX) break
        await fetchProposalDetail(p.id)
        n++
        if (cancelled) return
      }
    }
    run()
    return () => { cancelled = true }
  }, [proposals, fetchProposalDetail])

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
    const merged = { ...raw, ...(detailMap[raw.id] || {}) }
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

  const set = (k: string, v: any) => setF({ ...f, [k]: v })
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

  const route = async (pid: number) => {
    setRouteBusy(b => ({ ...b, [pid]: true }))
    setRouteMsg(m => ({ ...m, [pid]: '…' }))
    setRouteIntent(prev => { const n = { ...prev }; delete n[pid]; return n })
    setRouteApproveTk(prev => { const n = { ...prev }; delete n[pid]; return n })
    setRouteApproveCode(prev => { const n = { ...prev }; delete n[pid]; return n })
    try {
      const r = await fetch('/api/v2/broker-proposals/route', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (d.mode === 'awaiting_approval' && d.intent_id) {
        const summ = d.summary?.summary || d.summary || ''
        setRouteIntent(prev => ({
          ...prev,
          [pid]: { intent_id: d.intent_id, symbol: String(d.symbol || '').toUpperCase(), summary: summ },
        }))
        const short = String(d.intent_id).slice(0, 8)
        setRouteMsg(prev => ({
          ...prev,
          [pid]: `🔐 2FA required — intent ${short}${d.ttl_min ? ` · ${d.ttl_min}min` : ''}${summ ? ` · ${summ}` : ''}`,
        }))
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
    } catch (e: any) {
      setRouteMsg(prev => ({ ...prev, [pid]: '⛔ ' + String(e).slice(0, 60) }))
    } finally {
      setRouteBusy(b => ({ ...b, [pid]: false }))
    }
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
        const v = cloud.consensus?.verdict || cloud.status || oversight.status || 'done'
        setOversightMsg(m => ({ ...m, [pid]: `✅ Cloud: ${v}` }))
        setDetailMap(prev => ({
          ...prev,
          [pid]: {
            ...(prev[pid] || {}),
            oversight,
            intel: {
              ...(prev[pid]?.intel || {}),
              ok: true,
              oversight,
            },
          },
        }))
        detailLoadedRef.current.add(pid)
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

  const refreshAllPrices = async () => {
    for (const raw of shown) {
      await refreshPrices(mergeProposal(raw))
    }
  }

  const queueCloudBatch = async (scope: 'page' | 'filtered') => {
    setBatchCloudBusy(true)
    setBatchCloudMsg('Queuing Grok+ChatGPT…')
    try {
      const max = 30
      const body = scope === 'page'
        ? { scope: 'ids', proposal_ids: shown.map((p: any) => p.id), max }
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {modalSeed && (
        <ManualExecutionModal seed={modalSeed} onClose={() => setModalSeed(null)} onLogged={refreshAll} />
      )}
      {adjustSeed && (
        <BrokerPromoteModal seed={adjustSeed} mode="adjust" onClose={() => setAdjustSeed(null)} onPromoted={refreshAll} />
      )}

      {focus && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, fontSize: 11.5, background: 'rgba(96,165,250,.1)', border: '1px solid rgba(96,165,250,.35)', color: '#93c5fd' }}>
          <span>Focused on <b style={{ fontFamily: 'monospace', color: TEXT0 }}>{focus}</b>.</span>
          <button onClick={() => setFocus('')} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, padding: '3px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>show all</button>
        </div>
      )}

      <ExecutionPathsStrip variant="live" />

      {!!data?.hygiene?.changed && (
        <div style={{ padding: '8px 12px', borderRadius: 8, fontSize: 11, background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.35)', color: AMBER }}>
          Auto-cleared {data.hygiene.changed} stale broker row(s)
          {(data.hygiene.expired || data.hygiene.rejected) ? ` (${data.hygiene.expired || 0} expired · ${data.hygiene.rejected || 0} superseded)` : ''}.
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, color: TEXT0 }}>Live Broker Queue</div>
          <div style={{ fontSize: 10, color: MUTED, marginTop: 2 }}>
            Path B — Schwab auto/manual · Fidelity FA manual · thesis band + cloud oversight before route
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={() => refetch?.()} disabled={loading} style={btn(BLUE, loading)}>
            {loading ? '…' : '↻ Reload queue'}
          </button>
          {shown.length > 0 && (
            <button onClick={refreshAllPrices} style={btn(GREEN)} title="Refresh live prices + recalc thesis/sizing for all visible cards">
              ↻ Refresh all prices
            </button>
          )}
        </div>
      </div>

      <ManualExecutionLog mode="equity" onRefresh={refreshAll} />

      <details style={card}>
        <summary style={{ fontSize: 13, fontWeight: 800, color: TEXT0, cursor: 'pointer' }}>Manual submit (ad-hoc)</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, fontSize: 11, marginTop: 12 }}>
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
            {pagination.total ? ` · ${pagination.total} total` : ''})
          </div>
          <button onClick={() => setHeldOnly(h => !h)} style={{
            fontSize: 10.5, fontWeight: 800, padding: '5px 11px', borderRadius: 6, cursor: 'pointer',
            border: `1px solid ${heldOnly ? BLUE : 'var(--border)'}`, background: heldOnly ? 'rgba(96,165,250,.14)' : 'transparent', color: heldOnly ? BLUE : MUTED,
          }}>● Held only{heldN ? ` (${heldN})` : ''}</button>
          {stale && <span style={{ fontSize: 9, color: AMBER }}>cached data</span>}
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12, alignItems: 'center' }}>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Sort
            <select style={sel} value={listFilters.sort} onChange={e => patchFilters({ sort: e.target.value })}>
              <option value="priority">Priority (watchlist · Hermes)</option>
              <option value="zone">Thesis zone</option>
              <option value="rr_live">Live R:R</option>
              <option value="rr">Planned R:R</option>
              <option value="hermes">Hermes score</option>
              <option value="symbol">Symbol A–Z</option>
              <option value="created">Newest</option>
            </select>
          </label>
          <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5 }}>
            Source
            <select style={sel} value={listFilters.source} onChange={e => patchFilters({ source: e.target.value })}>
              <option value="">All</option>
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
              onChange={e => patchFilters({ symbol: e.target.value.toUpperCase() })}
            />
          </label>
          {(listFilters.source || listFilters.zone || listFilters.account || listFilters.symbol || listFilters.rrPreset || listFilters.sort !== 'priority') && (
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
            disabled={batchCloudBusy || !(pagination.total > 0)}
            title="Queue Grok+ChatGPT for up to 30 proposals matching current filters"
            style={btn(AMBER, batchCloudBusy || !(pagination.total > 0))}
          >
            {batchCloudBusy ? '…' : `☁ Run cloud · filtered (≤30 of ${pagination.total || 0})`}
          </button>
        </div>
        {(listFilters.rrPreset === 'live_2' || listFilters.rrPreset === 'live_15' || listFilters.rrPreset === 'best') && (
          <div style={{ fontSize: 10, color: MUTED, marginBottom: 8 }}>
            Live R:R uses stored prices — ↻ Refresh all prices on a page if counts look stale.
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
          <div style={{ fontSize: 11, color: AMBER }}>Unavailable ({error}) — <span onClick={() => refetch?.()} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>retry</span></div>
        )}
        {!loading && !error && proposals.length === 0 && (
          <div style={{ fontSize: 11, color: MUTED }}>No Schwab/Fidelity proposals — promote from Proposals tab.</div>
        )}
        {proposals.length > 0 && shown.length === 0 && (
          <div style={{ fontSize: 11, color: MUTED }}>No held-symbol proposals. <span onClick={() => setHeldOnly(false)} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Show all</span></div>
        )}

        {pagination.total_pages > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <button
              disabled={pagination.page <= 1 || loading}
              onClick={() => patchFilters({ page: Math.max(1, pagination.page - 1) })}
              style={btn(BLUE, loading || pagination.page <= 1)}
            >
              ← Prev
            </button>
            <span style={{ fontSize: 11, color: MUTED }}>
              Page {pagination.page} / {pagination.total_pages}
              {pagination.total ? ` (${pagination.total} proposals)` : ''}
            </span>
            <button
              disabled={pagination.page >= pagination.total_pages || loading}
              onClick={() => patchFilters({ page: Math.min(pagination.total_pages, pagination.page + 1) })}
              style={btn(BLUE, loading || pagination.page >= pagination.total_pages)}
            >
              Next →
            </button>
            <label style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 5, marginLeft: 'auto' }}>
              Per page
              <select
                style={sel}
                value={listFilters.pageSize}
                onChange={e => patchFilters({ pageSize: Number(e.target.value), page: 1 })}
              >
                {[10, 15, 20, 30, 50].map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {shown.map(rawP => {
            const p = mergeProposal(rawP)
            const dest = destAccount[p.id] ?? p.account ?? ''
            return (
              <BrokerProposalCard
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
                onEdit={() => setAdjustSeed({ proposal_id: p.id, symbol: p.symbol, account: dest })}
                onManual={() => openManual(p)}
                onRoute={() => route(p.id)}
                onQueueOversight={() => queueOversight(p.id)}
                onRunCloudOversight={() => runCloudOversight(p.id)}
              />
            )
          })}
        </div>

        {pagination.total_pages > 1 && shown.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
            <button
              disabled={pagination.page <= 1 || loading}
              onClick={() => patchFilters({ page: Math.max(1, pagination.page - 1) })}
              style={btn(BLUE, loading || pagination.page <= 1)}
            >
              ← Prev
            </button>
            <span style={{ fontSize: 11, color: MUTED }}>Page {pagination.page} / {pagination.total_pages}</span>
            <button
              disabled={pagination.page >= pagination.total_pages || loading}
              onClick={() => patchFilters({ page: Math.min(pagination.total_pages, pagination.page + 1) })}
              style={btn(BLUE, loading || pagination.page >= pagination.total_pages)}
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
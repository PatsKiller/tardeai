import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'
import TradeInViewDetail from './TradeInViewDetail'
import TradeReplayChart from '../TradeReplayChart'
import { buildReplayTrade } from '../../lib/replayTrade'
import ReportingAuditPanel from './ReportingAuditPanel'
import IndustryPicker from './IndustryPicker'
import BulkTagModal from './BulkTagModal'

const MISSING_COLOR: Record<string, string> = {
  strategy: '#ef4444',
  setup: '#ef4444',
  review: '#ef4444',
  market_regime: '#f59e0b',
  psychology: '#f59e0b',
  operator_review: '#f97316',
}

const MISSING_LABEL: Record<string, string> = {
  strategy: 'Strategy',
  setup: 'Setup type',
  market_regime: 'Market regime',
  psychology: 'Psychology',
  operator_review: 'Operator review',
  review: 'Review',
}

const FILTER_BTN = (active: boolean): CSSProperties => ({
  fontSize: 13,
  fontWeight: active ? 700 : 500,
  padding: '8px 14px',
  borderRadius: 8,
  border: `1px solid ${active ? 'rgba(245,158,11,.5)' : 'var(--border)'}`,
  cursor: 'pointer',
  background: active ? 'rgba(245,158,11,.18)' : 'var(--bg2)',
  color: active ? '#fcd34d' : 'var(--text1)',
})

interface Props {
  account?: string
  days: number
  acctLabel?: Record<string, string>
}

export default function TaggingQueuePanel({ account, days, acctLabel = {} }: Props) {
  const [page, setPage] = useState(1)
  const [missingFilter, setMissingFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [minPnl, setMinPnl] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [activeIdx, setActiveIdx] = useState(0)
  const [detailTrade, setDetailTrade] = useState<any>(null)
  const [chartTrade, setChartTrade] = useState<any>(null)
  const [toast, setToast] = useState('')
  const [showAudit, setShowAudit] = useState(true)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkLabel, setBulkLabel] = useState('')
  const [industryModal, setIndustryModal] = useState<'selected' | 'all' | null>(null)
  const [industryValue, setIndustryValue] = useState('')
  const [busy, setBusy] = useState('')
  const [tick, setTick] = useState(0)
  const tableRef = useRef<HTMLDivElement>(null)


  const q = `/api/v2/journal/tagging-queue?days=${days}&page=${page}&limit=50`
    + `${account ? `&account=${encodeURIComponent(account)}` : ''}`
    + `${missingFilter ? `&missing=${missingFilter}` : ''}`
    + `${symbolFilter ? `&symbol=${encodeURIComponent(symbolFilter)}` : ''}`
    + `${minPnl ? `&min_pnl=${minPnl}` : ''}`
    + `&_t=${tick}`

  const { data: raw, loading } = useApi<any>(q, 60_000)
  const d = (raw as any)?.data ?? raw
  const items: any[] = d?.items || []
  const symbolGroups: { symbol: string; count: number; lot_count?: number; trade_keys: string[] }[] = d?.symbol_groups || []
  const symbolTradeKeys: string[] = [...new Set((d?.filter_symbol_trade_keys || []) as string[])]
  const dupAudit = d?.duplicate_audit

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 4000)
  }

  const refresh = () => setTick(t => t + 1)

  const rowToDetail = (row: any) => ({
    symbol: row.symbol,
    account: row.account,
    na: row.account,
    exitDate: row.close_date,
    close_date: row.close_date,
    entryDate: row.open_date,
    trade_key: row.trade_key,
    pnl: row.net_pnl,
    shares: row.shares,
    ep: row.buy_price,
    xp: row.sell_price,
    pnlPct: row.pnl_pct,
  })

  const openDetail = (row: any) => setDetailTrade(rowToDetail(row))

  const openReplay = (row: any) => setChartTrade(buildReplayTrade(row))

  const skipReview = async (tradeKey: string) => {
    await fetch('/api/v2/journal/tagging-queue/skip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_key: tradeKey, reason: 'Operator marked — no tags needed' }),
    })
    showToast('Marked reviewed (no tags). Queue updated.')
    refresh()
  }

  const autoTagAll = async (silent = false) => {
    setBusy('auto')
    try {
      const r = await fetch('/api/v2/journal/tagging-queue/auto-tag', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days, account: account || undefined }),
      }).then(x => x.json())
      const res = r?.data ?? r
      if (!silent) showToast(`Auto-tagged ${res.applied ?? 0} trades — regime, psychology, industry, setup filled`)
      return res
    } finally {
      setBusy('')
    }
  }

  const backfillIndustryAll = async (silent = false) => {
    setBusy('industry')
    try {
      const r = await fetch('/api/v2/journal/tagging-queue/backfill-industry', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days, account: account || undefined, overwrite: false }),
      }).then(x => x.json())
      const res = r?.data ?? r
      if (!silent) showToast(`Industry backfill: ${res.applied ?? 0} updated · ${res.missing_profile ?? 0} without profile`)
      return res
    } finally {
      setBusy('')
    }
  }

  const autoTagAndBackfill = async () => {
    setBusy('both')
    try {
      const tagRes = await fetch('/api/v2/journal/tagging-queue/auto-tag', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days, account: account || undefined }),
      }).then(x => x.json()).then(r => r?.data ?? r)
      const indRes = await fetch('/api/v2/journal/tagging-queue/backfill-industry', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days, account: account || undefined, overwrite: false }),
      }).then(x => x.json()).then(r => r?.data ?? r)
      showToast(`Auto-tag ${tagRes?.applied ?? 0} · industry backfill ${indRes?.applied ?? 0} (${indRes?.missing_profile ?? 0} no profile)`)
      refresh()
    } finally {
      setBusy('')
    }
  }

  const applyIndustryModal = async () => {
    if (!industryValue.trim()) return
    setBusy('industry')
    try {
      if (industryModal === 'selected') {
        const keys = [...selected]
        if (!keys.length) return
        await fetch('/api/v2/journal/tagging-queue/bulk-tag', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trade_keys: keys, tags: { industry: industryValue } }),
        })
        showToast(`Industry set on ${keys.length} selected trades`)
      } else {
        const r = await fetch('/api/v2/journal/tagging-queue/backfill-industry', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            days, account: account || undefined, industry: industryValue, overwrite: true,
          }),
        }).then(x => x.json())
        const res = r?.data ?? r
        showToast(`Industry "${industryValue}" applied to ${res.applied ?? 0} trades`)
      }
      setIndustryModal(null)
      setIndustryValue('')
      refresh()
    } finally {
      setBusy('')
    }
  }

  const openBulkModal = (keys: string[], label: string) => {
    if (!keys.length) return
    setSelected(new Set(keys))
    setBulkLabel(label)
    setBulkOpen(true)
  }

  const selectSymbolGroup = (sym: string, keys: string[]) => {
    const unique = [...new Set(keys)]
    setSymbolFilter(sym)
    setSelected(new Set(unique))
    setPage(1)
  }

  const selectAllSymbolFromRow = (sym: string) => {
    const grp = symbolGroups.find(g => g.symbol === sym)
    if (grp) selectSymbolGroup(sym, grp.trade_keys)
    else {
      const keys = items.filter(r => r.symbol === sym).map(r => r.trade_key)
      selectSymbolGroup(sym, keys)
    }
  }

  const clearSymbolFilter = () => {
    setSymbolFilter('')
    setSelected(new Set())
    setPage(1)
  }

  const toggleSel = (tk: string) => {
    setSelected(prev => {
      const n = new Set(prev)
      if (n.has(tk)) n.delete(tk)
      else n.add(tk)
      return n
    })
  }

  const onKeyDown = useCallback((e: KeyboardEvent) => {
    if (detailTrade || bulkOpen || chartTrade || industryModal) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, items.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && items[activeIdx]) {
      e.preventDefault()
      openDetail(items[activeIdx])
    }
  }, [items, activeIdx, detailTrade, bulkOpen, chartTrade, industryModal])

  useEffect(() => {
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onKeyDown])

  useEffect(() => { setActiveIdx(0); setPage(1) }, [account, days, missingFilter, minPnl, symbolFilter])

  useEffect(() => {
    if (!symbolFilter || !symbolTradeKeys.length) return
    setSelected(new Set(symbolTradeKeys))
  }, [symbolFilter, symbolTradeKeys.join('|')])

  const confirmAutoTagged = async () => {
    setBusy('confirm')
    try {
      const r = await fetch('/api/v2/journal/tagging-queue/confirm-auto-tagged', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days, account: account || undefined, trade_keys: selected.size ? [...selected] : undefined }),
      }).then(x => x.json())
      const res = r?.data ?? r
      showToast(`Confirmed ${res.applied ?? 0} auto-tagged trades`)
      setSelected(new Set())
      refresh()
    } finally {
      setBusy('')
    }
  }

  const health = d?.queue_health_pct ?? 0
  const autoPending = d?.auto_tagged_pending ?? 0
  const need = d?.need_tagging ?? 0
  const total = d?.total_in_range ?? 0

  return (
    <div>
      {toast && (
        <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 2000, background: '#166534', color: '#fff', padding: '10px 16px', borderRadius: 8, fontSize: 11, boxShadow: '0 4px 20px rgba(0,0,0,.4)' }}>
          {toast}
        </div>
      )}

      {/* Summary bar */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Operator tagging queue</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: need > 0 ? '#f59e0b' : '#22c55e' }}>
            {need} trades need tagging
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>
            {d?.need_tagging_pct ?? 0}% of recent activity · oldest {d?.oldest_trade_date || '—'}
          </div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: health >= 80 ? '#22c55e' : health >= 50 ? '#f59e0b' : '#ef4444' }}>{health}%</div>
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>Queue health</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text0)' }}>{total}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>Trades in range</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 6, justifyContent: 'center' }}>
          <button onClick={() => setShowAudit(!showAudit)} style={{ fontSize: 10, padding: '6px 10px', borderRadius: 5, border: '1px solid var(--border)', background: showAudit ? 'rgba(96,165,250,.15)' : 'var(--bg2)', cursor: 'pointer', color: '#60a5fa' }}>
            {showAudit ? 'Hide' : 'Run'} reporting audit
          </button>
          {selected.size > 0 && (
            <button onClick={() => openBulkModal([...selected], `${selected.size} selected`)} style={{ fontSize: 10, padding: '6px 10px', borderRadius: 5, border: 'none', background: '#a855f7', color: '#fff', cursor: 'pointer' }}>
              Edit & apply ({selected.size})
            </button>
          )}
        </div>
      </div>

      {showAudit && <div style={{ marginBottom: 14 }}><ReportingAuditPanel days={days} /></div>}

      <div style={{ background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.35)', borderRadius: 10, padding: '12px 14px', marginBottom: 12, fontSize: 13, lineHeight: 1.5, color: 'var(--text1)' }}>
        <strong style={{ color: '#93c5fd' }}>What Auto-tag does:</strong> fills <strong>Market regime</strong> (default Ranging), <strong>Psychology</strong> (default Calm), <strong>Industry</strong> (symbol lookup), and <strong>Setup</strong> (AI). Trades <em>stay in the queue</em> until you confirm or edit — use <strong>Same stock</strong> dropdown to bulk-tag all AXTI/TRX legs at once.
        {autoPending > 0 && (
          <span style={{ display: 'block', marginTop: 6, color: '#fcd34d', fontWeight: 700 }}>
            {autoPending} auto-tagged trade{autoPending !== 1 ? 's' : ''} awaiting your review
          </span>
        )}
      </div>

      {/* Auto-tag + industry actions */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
        <button
          disabled={!!busy}
          onClick={() => autoTagAndBackfill()}
          style={{ fontSize: 13, fontWeight: 700, padding: '10px 16px', borderRadius: 8, border: 'none', background: '#f59e0b', color: '#1c1917', cursor: busy ? 'wait' : 'pointer' }}
        >
          {busy === 'both' || busy === 'auto' ? 'Auto-tagging…' : '⚡ Auto-tag + backfill all'}
        </button>
        <button
          disabled={!!busy}
          onClick={() => autoTagAll()}
          style={{ fontSize: 12, fontWeight: 600, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: busy ? 'wait' : 'pointer' }}
        >
          Tags only
        </button>
        <button
          disabled={!!busy}
          onClick={() => backfillIndustryAll()}
          style={{ fontSize: 13, fontWeight: 600, padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)', cursor: busy ? 'wait' : 'pointer' }}
        >
          {busy === 'industry' ? 'Backfilling…' : '🏭 Backfill industries (symbol lookup)'}
        </button>
        <button
          disabled={!!busy}
          onClick={() => { setIndustryModal('all'); setIndustryValue('') }}
          style={{ fontSize: 13, fontWeight: 600, padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(96,165,250,.4)', background: 'rgba(96,165,250,.1)', color: '#93c5fd', cursor: 'pointer' }}
        >
          Edit industry — all trades
        </button>
        {selected.size > 0 && (
          <button
            disabled={!!busy}
            onClick={() => { setIndustryModal('selected'); setIndustryValue('') }}
            style={{ fontSize: 13, fontWeight: 600, padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(96,165,250,.4)', background: 'rgba(96,165,250,.1)', color: '#93c5fd', cursor: 'pointer' }}
          >
            Edit industry — {selected.size} selected
          </button>
        )}
        {autoPending > 0 && (
          <button
            disabled={!!busy}
            onClick={confirmAutoTagged}
            style={{ fontSize: 13, fontWeight: 700, padding: '10px 14px', borderRadius: 8, border: 'none', background: '#22c55e', color: '#fff', cursor: 'pointer' }}
          >
            {busy === 'confirm' ? 'Confirming…' : `✓ Confirm auto-tags (${selected.size || autoPending})`}
          </button>
        )}
      </div>

      {/* Symbol bulk-select chips */}
      <div style={{ background: 'var(--bg1)', border: '1px solid rgba(168,85,247,.35)', borderRadius: 10, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: '#e9d5ff', marginBottom: 8 }}>
          Select same stock — click a symbol to filter + check all its trades, then bulk tag
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          {symbolGroups.slice(0, 20).map(g => {
            const active = symbolFilter === g.symbol
            const lots = g.lot_count ?? g.count
            return (
              <button
                key={g.symbol}
                onClick={() => active ? clearSymbolFilter() : selectSymbolGroup(g.symbol, g.trade_keys)}
                style={{
                  fontSize: 14, fontWeight: 700, padding: '10px 16px', borderRadius: 8, cursor: 'pointer',
                  border: `2px solid ${active ? '#a855f7' : 'var(--border)'}`,
                  background: active ? 'rgba(168,85,247,.25)' : 'var(--bg2)',
                  color: active ? '#f3e8ff' : 'var(--text0)',
                }}
              >
                {g.symbol} · {g.count} trade{g.count !== 1 ? 's' : ''}{lots > g.count ? ` (${lots} lots)` : ''}
              </button>
            )
          })}
        </div>
        {symbolFilter ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', padding: '10px 12px', borderRadius: 8, background: 'rgba(168,85,247,.12)', border: '1px solid rgba(168,85,247,.4)' }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: '#f3e8ff' }}>
              {symbolFilter}: {selected.size} selected
            </span>
            <button
              onClick={() => openBulkModal([...selected], `all ${symbolFilter}`)}
              style={{ fontSize: 14, fontWeight: 800, padding: '10px 18px', borderRadius: 8, border: 'none', background: '#a855f7', color: '#fff', cursor: 'pointer' }}
            >
              Edit tags → apply to all {symbolFilter}
            </button>
            <button
              onClick={confirmAutoTagged}
              style={{ fontSize: 13, fontWeight: 700, padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(34,197,94,.5)', background: 'rgba(34,197,94,.15)', color: '#86efac', cursor: 'pointer' }}
            >
              Confirm {symbolFilter}
            </button>
            <button onClick={clearSymbolFilter} style={{ fontSize: 12, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>
              Clear selection
            </button>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            Or use dropdown:{' '}
            <select
              value={symbolFilter}
              onChange={e => {
                const sym = e.target.value
                if (!sym) clearSymbolFilter()
                else selectSymbolGroup(sym, symbolGroups.find(g => g.symbol === sym)?.trade_keys || [])
              }}
              style={{ fontSize: 13, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }}
            >
              <option value="">All symbols ({d?.queue_total_all ?? need})</option>
              {symbolGroups.map(g => (
                <option key={g.symbol} value={g.symbol}>{g.symbol} ({g.count})</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {dupAudit && (dupAudit.multi_lot_trades ?? 0) > 0 && (
        <div style={{ background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.35)', borderRadius: 10, padding: '10px 14px', marginBottom: 12, fontSize: 12, color: 'var(--text1)' }}>
          <strong style={{ color: '#fcd34d' }}>Duplicate audit:</strong>{' '}
          {dupAudit.hidden_duplicate_rows} extra lot-rows merged into {dupAudit.unique_trades} unique trades
          ({dupAudit.multi_lot_trades} same-day multi-lot).{' '}
          Top: {(dupAudit.items || []).slice(0, 5).map((x: any) => `${x.symbol}×${x.lot_count}`).join(', ')}
          — one tag applies to all lots on that day/account.
        </div>
      )}

      {/* Filters — missing tag */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text1)', marginBottom: 8 }}>Filter by missing tag</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          {['', 'auto_tagged', 'strategy', 'setup', 'market_regime', 'psychology', 'operator_review'].map(m => (
            <button key={m || 'all'} onClick={() => setMissingFilter(m)} style={FILTER_BTN(missingFilter === m)}>
              {m === 'auto_tagged' ? `Auto-tagged (${autoPending})` : m ? (MISSING_LABEL[m] || m) : 'All'}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)', display: 'flex', alignItems: 'center', gap: 8 }}>
            Min |P&L|
            <input
              type="number"
              value={minPnl}
              onChange={e => setMinPnl(e.target.value)}
              placeholder="0"
              style={{ width: 88, fontSize: 14, padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }}
            />
          </label>
          <span style={{ fontSize: 12, color: 'var(--text2)' }}>↑↓ navigate · Enter review · 📈 Replay on each card</span>
        </div>
      </div>

      {/* Trade cards — 3 rows each */}
      <div ref={tableRef} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {items.map((row, i) => {
          const active = i === activeIdx
          const pnlPos = (row.net_pnl ?? 0) >= 0
          return (
            <div
              key={`${row.trade_key}:${i}`}
              onClick={() => setActiveIdx(i)}
              style={{
                background: active ? 'rgba(96,165,250,.08)' : 'var(--bg1)',
                border: `1px solid ${active ? 'rgba(96,165,250,.45)' : 'var(--border)'}`,
                borderRadius: 10,
                padding: '12px 14px',
                cursor: 'pointer',
              }}
            >
              {/* Row 1 — identity + P&L */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
                <input
                  type="checkbox"
                  checked={selected.has(row.trade_key)}
                  onChange={() => toggleSel(row.trade_key)}
                  onClick={e => e.stopPropagation()}
                  style={{ width: 16, height: 16, flexShrink: 0 }}
                />
                <button
                  type="button"
                  title={`Select all ${row.symbol} trades`}
                  onClick={e => { e.stopPropagation(); selectAllSymbolFromRow(row.symbol) }}
                  style={{
                    fontFamily: 'monospace', fontSize: 20, fontWeight: 800, color: symbolFilter === row.symbol ? '#e9d5ff' : 'var(--text0)',
                    background: symbolFilter === row.symbol ? 'rgba(168,85,247,.2)' : 'transparent',
                    border: symbolFilter === row.symbol ? '2px solid #a855f7' : '1px dashed var(--border)',
                    borderRadius: 8, padding: '2px 10px', cursor: 'pointer',
                  }}
                >
                  {row.symbol}
                </button>
                {(row.lot_count ?? 1) > 1 && (
                  <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 6, background: 'rgba(245,158,11,.15)', color: '#fcd34d' }}>
                    {row.lot_count} lots merged
                  </span>
                )}
                <span style={{ fontSize: 18, fontWeight: 700, color: pnlPos ? '#22c55e' : '#ef4444' }}>{fmt$(row.net_pnl, 2)}</span>
                <span style={{ fontSize: 13, color: 'var(--text2)' }}>{row.close_date}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>{acctLabel[row.account] ?? row.account}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: row.direction === 'short' ? '#f97316' : '#60a5fa', textTransform: 'uppercase' }}>{row.direction}</span>
                <span style={{ fontSize: 13, color: 'var(--text2)' }}>{row.shares ?? '—'} sh</span>
              </div>

              {/* Row 2 — tags + readiness */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8, paddingLeft: 28 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text1)' }}>Tags: {row.tag_count}</span>
                <span style={{
                  fontSize: 12, fontWeight: 700, padding: '3px 8px', borderRadius: 6,
                  background: (row.tagging_score ?? 0) >= 75 ? 'rgba(34,197,94,.15)' : 'rgba(245,158,11,.15)',
                  color: (row.tagging_score ?? 0) >= 75 ? '#86efac' : '#fcd34d',
                }}>
                  {row.tagging_score ?? 0}% ready
                </span>
                <span style={{ fontSize: 13, color: 'var(--text1)' }}>{row.tag_summary || '—'}</span>
                {row.market_regime && (
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '3px 8px', borderRadius: 6, background: 'rgba(245,158,11,.12)', color: '#fcd34d' }}>
                    Regime: {row.market_regime}
                  </span>
                )}
                {row.emotion_before && (
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '3px 8px', borderRadius: 6, background: 'rgba(96,165,250,.12)', color: '#93c5fd' }}>
                    Psych: {row.emotion_before}
                  </span>
                )}
                {(row.industry || row.sector) && (
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '3px 8px', borderRadius: 6, background: 'rgba(168,85,247,.12)', color: '#d8b4fe', border: '1px solid rgba(168,85,247,.3)' }}>
                    🏭 {row.industry || row.sector}{row.industry && row.sector && row.sector !== row.industry ? ` · ${row.sector}` : ''}
                  </span>
                )}
                {row.auto_tagged_pending && (
                  <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, background: 'rgba(34,197,94,.15)', color: '#86efac', border: '1px solid rgba(34,197,94,.4)' }}>
                    Auto-tagged — confirm
                  </span>
                )}
                {row.auto_stub && (
                  <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, background: 'rgba(245,158,11,.2)', color: '#fbbf24', border: '1px solid rgba(245,158,11,.4)' }}>
                    AI stub
                  </span>
                )}
              </div>

              {/* Row 3 — missing + actions */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', paddingLeft: 28 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text2)' }}>Missing:</span>
                {(row.missing || []).map((m: string) => (
                  <span
                    key={m}
                    style={{
                      fontSize: 12, fontWeight: 600, padding: '5px 12px', borderRadius: 8,
                      background: (MISSING_COLOR[m] || '#ef4444') + '22',
                      color: MISSING_COLOR[m] || '#ef4444',
                      border: `1px solid ${MISSING_COLOR[m] || '#ef4444'}55`,
                    }}
                  >
                    {MISSING_LABEL[m] || m}
                  </span>
                ))}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap' }} onClick={e => e.stopPropagation()}>
                  <button
                    onClick={() => openReplay(row)}
                    style={{ fontSize: 13, fontWeight: 700, padding: '8px 14px', borderRadius: 8, border: '1px solid rgba(34,197,94,.5)', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}
                  >
                    📈 Replay
                  </button>
                  <button
                    onClick={() => openDetail(row)}
                    style={{ fontSize: 13, fontWeight: 700, padding: '8px 16px', borderRadius: 8, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}
                  >
                    Review & Tag
                  </button>
                  <button
                    onClick={() => skipReview(row.trade_key)}
                    style={{ fontSize: 13, padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}
                  >
                    Skip
                  </button>
                </div>
              </div>
            </div>
          )
        })}
        {loading && <div style={{ padding: 20, textAlign: 'center', color: 'var(--text2)', fontSize: 14 }}>Loading queue…</div>}
        {!loading && items.length === 0 && (
          <div style={{ padding: 28, textAlign: 'center', color: '#22c55e', fontSize: 15, fontWeight: 600, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
            Queue clear — all trades tagged for this filter.
          </div>
        )}
      </div>

      {/* Pagination */}
      {(d?.total_queue ?? 0) > 50 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'center' }}>
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} style={{ fontSize: 9, padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: page > 1 ? 'pointer' : 'default' }}>Prev</button>
          <span style={{ fontSize: 9, color: 'var(--text3)', lineHeight: '24px' }}>Page {page} · {d?.total_queue} in queue</span>
          <button disabled={page * 50 >= (d?.total_queue ?? 0)} onClick={() => setPage(p => p + 1)} style={{ fontSize: 9, padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>Next</button>
        </div>
      )}

      {bulkOpen && selected.size > 0 && (
        <BulkTagModal
          tradeKeys={[...selected]}
          label={bulkLabel}
          symbol={symbolFilter || undefined}
          days={days}
          account={account}
          onClose={() => { setBulkOpen(false); setBulkLabel('') }}
          onApplied={(count) => {
            setBulkOpen(false)
            setBulkLabel('')
            setSelected(new Set())
            showToast(`Applied tags to ${count} trades. Reports refresh in background.`)
            refresh()
          }}
        />
      )}

      {industryModal && (
        <>
          <div onClick={() => setIndustryModal(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1100 }} />
          <div style={{ position: 'fixed', top: '22%', left: '50%', transform: 'translateX(-50%)', width: 440, maxWidth: '92vw', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 12, padding: 18, zIndex: 1101 }}>
            <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6 }}>
              {industryModal === 'all' ? 'Edit industry / sector — all trades in range' : `Edit industry / sector — ${selected.size} selected`}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 12 }}>
              {industryModal === 'all'
                ? 'Sets this industry/sector on every trade in the date filter (overwrites existing). Use after auto-backfill to correct sectors.'
                : 'Applies only to checked rows on this page.'}
            </div>
            <IndustryPicker value={industryValue} onChange={setIndustryValue} />
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button
                disabled={!industryValue.trim() || !!busy}
                onClick={applyIndustryModal}
                style={{ flex: 1, fontSize: 13, fontWeight: 700, padding: 10, borderRadius: 8, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}
              >
                Apply industry
              </button>
              <button onClick={() => setIndustryModal(null)} style={{ fontSize: 13, padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>
                Cancel
              </button>
            </div>
          </div>
        </>
      )}

      {chartTrade && (
        <TradeReplayChart trade={chartTrade} onClose={() => setChartTrade(null)} />
      )}

      {detailTrade && (
        <TradeInViewDetail
          trade={detailTrade}
          initialTab="Review"
          focusTagging
          onClose={() => setDetailTrade(null)}
          onReplay={() => openReplay(detailTrade)}
          onSaved={() => {
            setDetailTrade(null)
            showToast('Trade tagged successfully. Affected reports will refresh in the background.')
            refresh()
          }}
        />
      )}
    </div>
  )
}
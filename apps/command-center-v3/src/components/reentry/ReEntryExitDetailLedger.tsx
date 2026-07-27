import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'

const KEY = 'portfolio.reentry.exit-universe.v1'
const MATERIAL_NOTE = 'Prefer rows with shares+price; blank-share siblings of the same sale are collapsed.'

type ExitRow = {
  event_key: string
  transaction_id?: number | null
  trade_date?: string | null
  trade_time?: string | null
  action?: string | null
  symbol: string
  quantity?: number | null
  price?: number | null
  proceeds_usd?: number | null
  fees?: number | null
  description?: string | null
  account?: string | null
  import_source?: string | null
  matched_event_id?: number | null
  event_status?: string | null
  completion_status?: string | null
  operator_status?: string | null
  proceeds_settled?: boolean | null
  reconciliation?: 'matched' | 'pending'
}

function money(value: number | null | undefined): string { return value == null ? '—' : fmt$(Number(value), 2) }

function normAcct(value?: string | null): string {
  return String(value || '').toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')
}

function proceedsBucket(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return 'na'
  return String(Math.round(Math.abs(Number(value)) * 100) / 100)
}

/** Prefer quantity+price rows; suppress blank-share near-duplicates of the same sale. */
function collapseBlankShareDuplicates(rows: ExitRow[]): { rows: ExitRow[]; suppressed: number } {
  const groups = new Map<string, ExitRow[]>()
  for (const row of rows) {
    const key = [
      String(row.symbol || '').toUpperCase(),
      normAcct(row.account),
      String(row.trade_date || ''),
      proceedsBucket(row.proceeds_usd),
    ].join('|')
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  const out: ExitRow[] = []
  let suppressed = 0
  for (const siblings of groups.values()) {
    if (siblings.length === 1) {
      out.push(siblings[0])
      continue
    }
    const rich = siblings.filter(r => r.quantity != null && Number(r.quantity) !== 0 && r.price != null)
    const blank = siblings.filter(r => r.quantity == null || Number(r.quantity) === 0)
    if (rich.length) {
      out.push(...rich)
      suppressed += blank.length + Math.max(0, siblings.length - rich.length - blank.length)
      // If only blanks beyond rich, they are suppressed; keep any non-blank non-rich (rare)
      const other = siblings.filter(r => !rich.includes(r) && !blank.includes(r))
      out.push(...other)
      suppressed += 0
    } else {
      out.push(...siblings)
    }
  }
  // Preserve original relative order by first-seen index
  const order = new Map(rows.map((r, i) => [r.event_key, i]))
  out.sort((a, b) => (order.get(a.event_key) ?? 0) - (order.get(b.event_key) ?? 0))
  return { rows: out, suppressed }
}

export default function ReEntryExitDetailLedger() {
  const [payload, setPayload] = useState<any>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [showAll, setShowAll] = useState(false)
  const load = () => {
    setError('')
    fetch(`/api/v2/ui/prefs/get?key=${encodeURIComponent(KEY)}`, { cache: 'no-store' })
      .then(async response => {
        const value = await response.json().catch(() => ({}))
        if (!response.ok || value?.ok === false) throw new Error(value?.error || String(response.status))
        setPayload(value?.value ?? value?.data?.value ?? null)
      })
      .catch(value => setError(String(value?.message || value)))
  }
  useEffect(load, [])
  const allRows: ExitRow[] = payload?.rows ?? []
  const collapsed = useMemo(() => collapseBlankShareDuplicates(allRows), [allRows])
  const rows = useMemo(() => collapsed.rows.filter(row => !query.trim() || `${row.symbol} ${row.account} ${row.action} ${row.description} ${row.import_source}`.toUpperCase().includes(query.trim().toUpperCase())), [collapsed.rows, query])
  const shown = rows.slice(0, showAll ? rows.length : 100)
  const counts = payload?.counts ?? {}
  return (
    <div style={{ background: 'var(--bg1)', border: `1px solid ${error ? BB.red : BB.green}`, borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div><div style={{ fontSize: 13, fontWeight: 900, color: error ? BB.red : BB.green }}>FULL BROKER EXIT TRANSACTION LEDGER</div><div style={{ fontSize: 10, color: BB.text3 }}>All real accounts · complete ingested fields · same-day and pending reconciliation remain visible</div></div>
        <div style={{ marginLeft: 'auto', fontSize: 10, color: BB.text3 }}>generated {payload?.generated_at ? String(payload.generated_at).slice(0, 19).replace('T', ' ') : 'not available'} · exits <b>{counts.exits_found ?? allRows.length}</b> · matched <b>{counts.matched ?? '—'}</b> · pending <b style={{ color: Number(counts.pending_reconciliation || 0) ? BB.amber : BB.green }}>{counts.pending_reconciliation ?? '—'}</b>{collapsed.suppressed > 0 && <span style={{ color: BB.amber }}> · {collapsed.suppressed} blank-share duplicate{collapsed.suppressed === 1 ? '' : 's'} collapsed</span>}</div>
      </div>
      {error && <div style={{ color: BB.red, fontSize: 10, marginTop: 5 }}>FULL-FIDELITY CACHE UNAVAILABLE: {error}</div>}
      {!error && !payload && <div style={{ color: BB.text3, fontSize: 10, marginTop: 5 }}>Waiting for the scheduled Watch pass to publish the full exit cache.</div>}
      <div style={{ display: 'flex', gap: 7, marginTop: 8 }}><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search action, symbol, account, description, source…" style={{ minWidth: 330, fontSize: 11, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} /><button onClick={load} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>REFRESH</button><button onClick={() => setShowAll(value => !value)} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${showAll ? BB.blue : 'var(--border)'}`, background: showAll ? BB.blueDim : 'var(--bg2)', color: showAll ? BB.blue : 'var(--text2)' }}>{showAll ? 'SHOW FIRST 100' : `SHOW ALL ${rows.length}`}</button></div>
      <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1450 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '115px 70px 130px 90px 85px 95px 90px 125px 150px 1fr 95px', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Date/time</span><span>Symbol</span><span>Account</span><span>Action</span><span>Shares</span><span>Exit price</span><span>Fees</span><span>Proceeds</span><span>Source</span><span>Description / status</span><span>Open</span></div>
        {shown.map(row => {
          const matched = row.reconciliation === 'matched' || Boolean(row.matched_event_id)
          return <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '115px 70px 130px 90px 85px 95px 90px 125px 150px 1fr 95px', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}>
            <div>{row.trade_date ?? '—'}<br /><span style={{ color: BB.text3 }}>{row.trade_time ?? ''}</span></div><b style={{ fontSize: 12 }}>{row.symbol}</b><span>{row.account ?? '—'}</span><b>{row.action ?? '—'}</b><span>{row.quantity ?? '—'}</span><span>{money(row.price)}</span><span>{money(row.fees)}</span><b>{money(row.proceeds_usd)}</b><span>{row.import_source ?? '—'}</span><div><span>{row.description ?? 'No source description'}</span><br /><b style={{ color: matched ? BB.green : BB.amber }}>{matched ? `MATCHED${row.matched_event_id ? ` #${row.matched_event_id}` : ''}` : 'PENDING RECONCILIATION'}</b>{row.event_status && <span style={{ color: BB.text3 }}> · {row.event_status}</span>}{row.completion_status && <span style={{ color: BB.text3 }}> · {row.completion_status}</span>}{row.proceeds_settled != null && <span style={{ color: row.proceeds_settled ? BB.green : BB.amber }}> · settlement {row.proceeds_settled ? 'verified' : 'pending'}</span>}</div><Link to={`/portfolio/re-entry?symbol=${encodeURIComponent(row.symbol)}`} style={{ fontSize: 10, fontWeight: 800, color: BB.blue, textDecoration: 'none', border: `1px solid ${BB.blue}`, borderRadius: 4, padding: '4px 7px', textAlign: 'center' }}>INTELLIGENCE</Link>
          </div>
        })}
      </div></div>
      {payload && shown.length === 0 && <div style={{ padding: 12, color: BB.text3, fontSize: 10 }}>No transactions match the current filter.</div>}
      <div style={{ marginTop: 7, fontSize: 10, color: BB.text3 }}>{MATERIAL_NOTE} Use the classification/lineage ledger immediately below to assign the persistent mandate, event type, and Rotation Link.</div>
    </div>
  )
}

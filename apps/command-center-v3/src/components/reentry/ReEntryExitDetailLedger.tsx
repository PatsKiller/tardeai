import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'

const KEY = 'portfolio.reentry.exit-universe.v1'

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

type DisplayRow = ExitRow & {
  _suppressed: number
  _badge?: string
}

function money(value: number | null | undefined): string { return value == null ? '—' : fmt$(Number(value), 2) }

function isDismissedLike(row: ExitRow): boolean {
  const blob = `${row.operator_status || ''} ${row.event_status || ''} ${row.completion_status || ''} ${row.description || ''}`.toLowerCase()
  return /\b(dismiss|dismissed|ignored|suppressed|cancelled|canceled|void)\b/.test(blob)
}

function hasQtyAndPrice(row: ExitRow): boolean {
  const q = row.quantity
  const p = row.price
  return q != null && Number.isFinite(Number(q)) && Number(q) !== 0
    && p != null && Number.isFinite(Number(p))
}

function rowCompletenessScore(row: ExitRow): number {
  let score = 0
  if (hasQtyAndPrice(row)) score += 8
  else {
    if (row.quantity != null && Number(row.quantity) !== 0) score += 3
    if (row.price != null && Number.isFinite(Number(row.price))) score += 3
  }
  if (row.proceeds_usd != null && Number.isFinite(Number(row.proceeds_usd))) score += 2
  if (!isDismissedLike(row)) score += 4
  if (row.reconciliation === 'matched' || row.matched_event_id) score += 1
  if (row.description) score += 1
  return score
}

/** Normalize account for grouping (UI collapse only). */
function normAccount(account: string | null | undefined): string {
  return String(account || '')
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '')
}

/**
 * Group key: symbol + account + trade_date + proceeds bucket (±$1) + event_key family.
 * event_key family strips trailing -dismissed / :dismissed / /twin suffixes when present.
 */
function collapseGroupKey(row: ExitRow): string {
  const sym = String(row.symbol || '').toUpperCase()
  const acct = normAccount(row.account)
  const date = String(row.trade_date || '').slice(0, 10)
  const proceeds = Math.round(Number(row.proceeds_usd ?? 0)) // within $1 after round
  let family = String(row.event_key || '')
  family = family
    .replace(/([:_-])(dismissed|ignored|suppressed|void|blank|empty|dup|twin)\d*$/i, '')
    .replace(/(dismissed|ignored|suppressed)$/i, '')
  // If event_key empty, fall back to action so different actions on same day stay separate
  const action = String(row.action || '').toUpperCase()
  return `${sym}|${acct}|${date}|${proceeds}|${family || action}`
}

/** Collapse near-duplicate exit rows for display — never mutates API payload. */
export function collapseExitLedgerRows(rows: ExitRow[]): DisplayRow[] {
  const groups = new Map<string, ExitRow[]>()
  for (const row of rows) {
    const key = collapseGroupKey(row)
    const list = groups.get(key) ?? []
    list.push(row)
    groups.set(key, list)
  }
  const out: DisplayRow[] = []
  for (const members of groups.values()) {
    if (members.length === 1) {
      out.push({ ...members[0], _suppressed: 0 })
      continue
    }
    const ranked = members.slice().sort((a, b) => rowCompletenessScore(b) - rowCompletenessScore(a))
    const winner = ranked[0]
    const suppressed = members.length - 1
    const hadDismissed = members.some(isDismissedLike)
    const winnerFull = hasQtyAndPrice(winner)
    let badge: string | undefined
    if (suppressed > 0 && hadDismissed && winnerFull) {
      badge = 'related dismissed suppressed'
    } else if (suppressed > 0) {
      badge = `${suppressed} related row${suppressed === 1 ? '' : 's'} collapsed`
    }
    out.push({ ...winner, _suppressed: suppressed, _badge: badge })
  }
  // Preserve chronological order of winners
  out.sort((a, b) => {
    const da = `${a.trade_date ?? ''}T${a.trade_time ?? ''}`
    const db = `${b.trade_date ?? ''}T${b.trade_time ?? ''}`
    return db.localeCompare(da)
  })
  return out
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
  const collapsed = useMemo(() => collapseExitLedgerRows(allRows), [allRows])
  const suppressedTotal = useMemo(
    () => collapsed.reduce((sum, row) => sum + (row._suppressed || 0), 0),
    [collapsed],
  )
  const rows = useMemo(
    () => collapsed.filter(row =>
      !query.trim()
      || `${row.symbol} ${row.account} ${row.action} ${row.description} ${row.import_source} ${row._badge || ''}`.toUpperCase().includes(query.trim().toUpperCase()),
    ),
    [collapsed, query],
  )
  const shown = rows.slice(0, showAll ? rows.length : 100)
  const counts = payload?.counts ?? {}
  return (
    <div style={{ background: 'var(--bg1)', border: `1px solid ${error ? BB.red : BB.green}`, borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 900, color: error ? BB.red : BB.green }}>FULL BROKER EXIT TRANSACTION LEDGER</div>
          <div style={{ fontSize: 10, color: BB.text3 }}>
            All real accounts · complete ingested fields · same-day and pending reconciliation remain visible
            {suppressedTotal > 0 ? ` · UI collapsed ${suppressedTotal} near-duplicate row${suppressedTotal === 1 ? '' : 's'} (prefer qty+price over blank shares)` : ''}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 10, color: BB.text3 }}>
          generated {payload?.generated_at ? String(payload.generated_at).slice(0, 19).replace('T', ' ') : 'not available'}
          {' '}· raw exits <b>{counts.exits_found ?? allRows.length}</b>
          {' '}· display <b>{collapsed.length}</b>
          {' '}· matched <b>{counts.matched ?? '—'}</b>
          {' '}· pending <b style={{ color: Number(counts.pending_reconciliation || 0) ? BB.amber : BB.green }}>{counts.pending_reconciliation ?? '—'}</b>
        </div>
      </div>
      {error && <div style={{ color: BB.red, fontSize: 10, marginTop: 5 }}>FULL-FIDELITY CACHE UNAVAILABLE: {error}</div>}
      {!error && !payload && <div style={{ color: BB.text3, fontSize: 10, marginTop: 5 }}>Waiting for the scheduled Watch pass to publish the full exit cache.</div>}
      <div style={{ display: 'flex', gap: 7, marginTop: 8 }}>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search action, symbol, account, description, source…" style={{ minWidth: 330, fontSize: 11, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
        <button type="button" onClick={load} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>REFRESH</button>
        <button type="button" onClick={() => setShowAll(value => !value)} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${showAll ? BB.blue : 'var(--border)'}`, background: showAll ? BB.blueDim : 'var(--bg2)', color: showAll ? BB.blue : 'var(--text2)' }}>{showAll ? 'SHOW FIRST 100' : `SHOW ALL ${rows.length}`}</button>
      </div>
      <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1450 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '115px 70px 130px 90px 85px 95px 90px 125px 150px 1fr 95px', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Date/time</span><span>Symbol</span><span>Account</span><span>Action</span><span>Shares</span><span>Exit price</span><span>Fees</span><span>Proceeds</span><span>Source</span><span>Description / status</span><span>Open</span></div>
        {shown.map(row => {
          const matched = row.reconciliation === 'matched' || Boolean(row.matched_event_id)
          const sharesLabel = row.quantity == null || Number(row.quantity) === 0 ? '—' : String(row.quantity)
          return (
            <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '115px 70px 130px 90px 85px 95px 90px 125px 150px 1fr 95px', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}>
              <div>{row.trade_date ?? '—'}<br /><span style={{ color: BB.text3 }}>{row.trade_time ?? ''}</span></div>
              <b style={{ fontSize: 12 }}>{row.symbol}</b>
              <span>{row.account ?? '—'}</span>
              <b>{row.action ?? '—'}</b>
              <span>{sharesLabel}</span>
              <span>{money(row.price)}</span>
              <span>{money(row.fees)}</span>
              <b>{money(row.proceeds_usd)}</b>
              <span>{row.import_source ?? '—'}</span>
              <div>
                <span>{row.description ?? 'No source description'}</span>
                <br />
                <b style={{ color: matched ? BB.green : BB.amber }}>{matched ? `MATCHED${row.matched_event_id ? ` #${row.matched_event_id}` : ''}` : 'PENDING RECONCILIATION'}</b>
                {row.event_status && <span style={{ color: BB.text3 }}> · {row.event_status}</span>}
                {row.completion_status && <span style={{ color: BB.text3 }}> · {row.completion_status}</span>}
                {row.proceeds_settled != null && <span style={{ color: row.proceeds_settled ? BB.green : BB.amber }}> · settlement {row.proceeds_settled ? 'verified' : 'pending'}</span>}
                {row._badge && (
                  <span style={{ display: 'inline-block', marginTop: 3, fontSize: 10, fontWeight: 800, color: BB.amber, border: `1px solid ${BB.amber}`, borderRadius: 3, padding: '1px 5px' }}>
                    {row._badge}
                  </span>
                )}
              </div>
              <Link to={`/portfolio/re-entry?symbol=${encodeURIComponent(row.symbol)}`} style={{ fontSize: 10, fontWeight: 800, color: BB.blue, textDecoration: 'none', border: `1px solid ${BB.blue}`, borderRadius: 4, padding: '4px 7px', textAlign: 'center' }}>INTELLIGENCE</Link>
            </div>
          )
        })}
      </div></div>
      {payload && shown.length === 0 && <div style={{ padding: 12, color: BB.text3, fontSize: 10 }}>No transactions match the current filter.</div>}
      <div style={{ marginTop: 7, fontSize: 10, color: BB.text3 }}>
        Use the classification/lineage ledger immediately below to assign the persistent mandate, event type, and Rotation Link.
        {' '}Ledger collapse is UI-only (API payload unchanged).
      </div>
    </div>
  )
}

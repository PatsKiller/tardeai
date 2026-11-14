/** Recent discoveries panel (S7/WR-04/WR-05). Reads the live candidate-discovery events and supports the persisted
 *  Add to My List journey: POST the membership write, then READ BACK membership before saying anything is stored.
 *  Watching/research only. */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { ADD_API, MEMBERSHIP_API, RECENT_API, addToMyList, discoveryClock, discoveryRows, isInMyList, type DiscoveryRow } from '../lib/watchDiscoverV002'

const detail = (s: string) => `/watch/intelligence/${encodeURIComponent(s)}`

export type RecentViewProps = {
  rows: DiscoveryRow[]
  clock: { state: string; label: string; asOfText: string | null; dueText?: string; nextText?: string; recovery?: string | null }
  loading: boolean
  error: string | null
  message: string
  member: Record<string, boolean | null | undefined>
  onAdd: (r: DiscoveryRow) => void
}

export function WatchDiscoverRecentV002View(p: RecentViewProps) {
  return (
    <div className="ws2-note" data-testid="discover-recent">
      <div data-testid="discover-recent-clock" data-state={p.clock.state}>
        <strong>Recent discoveries</strong>: {p.rows.length === 0 ? 'no window' : p.clock.label} · candidate-discovery events
        {p.clock.asOfText ? ` · newest event ${p.clock.asOfText}` : ''}
        {p.clock.nextText ? ` · next run ${p.clock.nextText}` : ''}
      </div>
      {p.clock.state === 'STALE' && p.clock.recovery && (
        <div className="bad" data-testid="discover-recent-recovery" role="alert">
          A scheduled run produced no discoveries. {p.clock.recovery}
        </div>
      )}
      {p.loading && p.rows.length === 0 && <div>Loading…</div>}
      {p.error && <div className="bad" data-testid="discover-recent-error">Discoveries could not be read: {p.error}</div>}
      {!p.loading && !p.error && p.rows.length === 0 && (
        <div data-testid="discover-recent-empty">No discovery events in the returned window. That is an empty successful read, not unread data.</div>
      )}
      {p.rows.length > 0 && (
        <ul className="ws2-rows" data-testid="discover-recent-rows">
          {p.rows.map(r => (
            <li key={r.symbol} className="ws2-row" data-testid={`discovery-${r.symbol}`}>
              <Link className="v010-link ws2-sym" to={detail(r.symbol)}>{r.symbol}</Link>
              <span className="ws2-dim">{r.source}</span>
              {r.reason && <span className="ws2-dim">{r.reason.slice(0, 120)}</span>}
              {r.degraded && <span className="v010-pill warn">degraded source</span>}
              {p.member[r.symbol] === true
                ? <span className="v010-pill ok">in My List</span>
                : <button type="button" className="v010-btn" data-testid={`discovery-add-${r.symbol}`} onClick={() => p.onAdd(r)}>Add to My List</button>}
              {/* Review F1: an unread or unreadable membership never speaks as "not in My List". The Add control
                  stays available (adding is harmless and idempotent for the list), but the row says which kind of
                  unknown it is instead of leaving the button to imply a known absence. */}
              {p.member[r.symbol] === undefined && (
                <span className="ws2-dim" data-testid={`discovery-membership-${r.symbol}`} data-membership="unread">
                  membership not checked
                </span>
              )}
              {p.member[r.symbol] === null && (
                <span className="ws2-dim" data-testid={`discovery-membership-${r.symbol}`} data-membership="unknown">
                  membership UNKNOWN — the readback did not include this symbol
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {p.message && <div data-testid="discover-recent-message" role="status">{p.message}</div>}
    </div>
  )
}

export default function WatchDiscoverRecentV002() {
  const { data, loading, error, refetch } = useApi<any>(RECENT_API, 120_000)
  const rows = discoveryRows(data)
  const clock = discoveryClock(rows, Date.now())
  const [message, setMessage] = useState('')
  // undefined = membership never read for this symbol; null = read, and the readback omitted it; true/false = read.
  const [member, setMember] = useState<Record<string, boolean | null | undefined>>({})

  // Read membership once per fetch (GET only). A row the readback omits becomes UNKNOWN, not "not in My List".
  useEffect(() => {
    let alive = true
    const syms = discoveryRows(data).map(r => r.symbol)
    void (async () => {
      let back: unknown = null
      try {
        const res = await fetch(MEMBERSHIP_API, { cache: 'no-store' })
        back = res.ok ? await res.json() : null
      } catch { back = null }
      if (!alive) return
      if (back === null) {
        setMessage('Membership could not be read, so each row says membership not checked.')
        return
      }
      const next: Record<string, boolean | null> = {}
      for (const s of syms) next[s] = isInMyList(back, s)
      setMember(m => ({ ...next, ...m }))
    })()
    return () => { alive = false }
  }, [data])

  const add = async (r: DiscoveryRow) => {
    const post = async (b: { symbol: string; strategy_type: string; source: string }) => {
      const res = await fetch(ADD_API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
      return { ok: res.ok, status: res.status, body: await res.json().catch(() => ({})) }
    }
    const out = await addToMyList(r.symbol, post)
    if (!out.ok) { setMessage(out.message); return }
    let back: unknown = null
    try { back = await (await fetch(MEMBERSHIP_API, { cache: 'no-store' })).json() } catch { back = null }
    const inList = isInMyList(back, r.symbol)
    setMember(m => ({ ...m, [r.symbol]: inList }))
    setMessage(inList === true
      ? `Added ${r.symbol} to My List · readback: in_ai_watchlist true`
      : inList === false
        ? `${r.symbol}: the add was accepted but the readback does not show it in My List yet. Reload to check.`
        : `Add sent for ${r.symbol}; the membership readback did not include it, so membership is UNKNOWN.`)
    refetch()
  }

  return <WatchDiscoverRecentV002View rows={rows} clock={clock} loading={loading && rows.length === 0} error={error ? String(error) : null}
    message={message} member={member} onAdd={r => void add(r)} />
}

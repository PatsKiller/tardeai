/** Choose what you watch (operator 2026-10-23: "I still don't see an area where I can select what I want to watch").
 *
 *  One write for all of it: POST /api/v3/watch/commands/mine {symbol, action: add|remove, note}
 *  (scripts/api_v3_watch_commands.post_mine_decision): add = the operator star + a watchlist_events row
 *  (watch_mine_added); remove = unstar + archive your own ticker directives for it + a watchlist_events row
 *  (watch_mine_removed). Both record the signed-in user. Watching only — never an order, a size or a stop. */
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle } from '../../lib/designTokens'

export const MINE_TIPS = {
  starOn: 'On your watchlist. Click to remove it from My Watchlist (unstars it and archives your own ticker directive; logged with your name). Watching only — no order, no size.',
  starOff: 'Click to add it to My Watchlist (stars it; logged with your name). Watching only — no order, no size.',
  remove: 'Remove from My Watchlist: unstars it, archives your own ticker directive for it, and hides it from your list until you add it again. Logged in watchlist_events with your name and the reason. Watching only.',
  add: 'Add a ticker to My Watchlist. Search by ticker or company name (the security registry and the broker instrument feed). Optional note is kept with the add. Watching only — no order, no size.',
  empty: 'Search a ticker above, or ★ any row in Suggests/Full universe.',
}

export async function mineAction(symbol: string, action: 'add' | 'remove', note?: string, surface = 'watch'): Promise<{ ok: boolean; message: string }> {
  try {
    const r = await fetch('/api/v3/watch/commands/mine', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, action, note: note || undefined, surface }),
    })
    const j = await r.json().catch(() => ({}))
    const d = j?.data ?? j
    if (!r.ok || d?.ok === false) return { ok: false, message: `Could not ${action} ${symbol}: ${d?.error || d?.detail || `HTTP ${r.status}`}` }
    return { ok: true, message: action === 'add' ? `${symbol} added to My Watchlist.` : `${symbol} removed from My Watchlist.` }
  } catch (e) {
    return { ok: false, message: `Could not ${action} ${symbol}: ${String(e).slice(0, 80)}` }
  }
}

export function StarToggle({ symbol, on, onChanged, surface, size = 'md' }: {
  symbol: string; on: boolean; onChanged?: (msg: string) => void; surface?: string; size?: 'sm' | 'md'
}) {
  const [busy, setBusy] = useState(false)
  const [state, setState] = useState(on)
  useEffect(() => setState(on), [on])
  return (
    <button type="button" data-testid="mine-star" data-symbol={symbol} data-on={state ? '1' : '0'} aria-pressed={state} disabled={busy}
      title={state ? MINE_TIPS.starOn : MINE_TIPS.starOff}
      aria-label={state ? `Remove ${symbol} from My Watchlist` : `Add ${symbol} to My Watchlist`}
      onClick={async e => {
        e.stopPropagation()
        setBusy(true)
        const res = await mineAction(symbol, state ? 'remove' : 'add', undefined, surface)
        if (res.ok) setState(!state)
        setBusy(false)
        onChanged?.(res.message)
      }}
      style={{ background: 'none', border: 'none', cursor: busy ? 'wait' : 'pointer', padding: 0, minWidth: size === 'sm' ? 18 : 22,
        fontSize: size === 'sm' ? TYPE.md : TYPE.md + 2, lineHeight: 1, color: state ? TOKENS.warning : TOKENS.text[3] }}>
      {state ? '★' : '☆'}
    </button>
  )
}

export function RemoveButton({ symbol, onChanged }: { symbol: string; onChanged?: (msg: string) => void }) {
  const [busy, setBusy] = useState(false)
  return (
    <button type="button" data-testid="mine-remove" disabled={busy} title={MINE_TIPS.remove}
      onClick={async e => {
        e.stopPropagation()
        const reason = window.prompt(`Remove ${symbol} from My Watchlist? Reason (optional):`, '')
        if (reason === null) return
        setBusy(true)
        const res = await mineAction(symbol, 'remove', reason, 'watch.my_watchlist')
        setBusy(false)
        onChanged?.(res.message)
      }}
      style={{ ...chipStyle('neutral', 'outline', 'sm'), cursor: 'pointer', whiteSpace: 'nowrap' }}>
      Remove
    </button>
  )
}

/** Enter adds the typed ticker when it looks like one (or matches a hit), else the top name match. */
export function pickOnEnter(q: string, hits: { symbol: string }[]): string {
  const t = q.trim().toUpperCase()
  if (hits.some(h => h.symbol === t) || /^[A-Z.\-]{1,6}$/.test(t)) return t
  return hits[0]?.symbol || t
}

type Hit = { symbol: string; name: string | null; identity_status: string | null; on_my_list: boolean; match: string }

const input: CSSProperties = {
  fontSize: TYPE.base, padding: '5px 8px', background: TOKENS.bg[2], color: TOKENS.text[0],
  border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, minWidth: 0,
}

/** The always-visible "Add symbol" box at the top of My Watchlist: typeahead (ticker or name) + optional note. */
export function AddSymbolBox({ onAdded }: { onAdded?: (msg: string) => void }) {
  const [q, setQ] = useState('')
  const [note, setNote] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const seq = useRef(0)
  useEffect(() => {
    const term = q.trim()
    if (!term) { setHits([]); return }
    const my = ++seq.current
    const t = window.setTimeout(async () => {
      try {
        const r = await fetch(`/api/v3/data-broker/watch-symbol-search?q=${encodeURIComponent(term)}`)
        const j = await r.json().catch(() => ({}))
        const d = j?.data ?? j
        if (my === seq.current) { setHits(Array.isArray(d?.results) ? d.results : []); setOpen(true) }
      } catch { if (my === seq.current) setHits([]) }
    }, 200)
    return () => window.clearTimeout(t)
  }, [q])
  const add = async (sym: string) => {
    const s = sym.trim().toUpperCase()
    if (!s) return
    setBusy(true)
    const res = await mineAction(s, 'add', note, 'watch.my_watchlist.add_box')
    setBusy(false)
    setMsg(res.message)
    if (res.ok) { setQ(''); setNote(''); setHits([]); setOpen(false) }
    onAdded?.(res.message)
  }
  return (
    <div data-testid="mine-add-box" title={MINE_TIPS.add}
      style={{ position: 'relative', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', padding: '6px 8px',
        border: `1px solid ${TOKENS.info}`, borderRadius: RADIUS.md, background: TOKENS.bg[1] }}>
      <b style={{ fontSize: TYPE.base, color: TOKENS.info }}>＋ Add symbol</b>
      <input data-testid="mine-add-input" aria-label="Ticker or company name" placeholder="Ticker or company — e.g. NVDA or Nvidia"
        value={q} onChange={e => setQ(e.target.value)} onFocus={() => hits.length && setOpen(true)}
        onKeyDown={e => { if (e.key === 'Enter') add(pickOnEnter(q, hits)) }}
        style={{ ...input, flex: '1 1 200px', fontFamily: FONT.mono }} />
      <input data-testid="mine-add-note" aria-label="Note (optional)" placeholder="Note (optional)" value={note}
        onChange={e => setNote(e.target.value)} style={{ ...input, flex: '1 1 160px' }} />
      <button type="button" data-testid="mine-add-submit" disabled={busy || !q.trim()} onClick={() => add(q)}
        title={MINE_TIPS.add} style={{ ...chipStyle('info', 'soft', 'md'), cursor: 'pointer' }}>Add to my watchlist</button>
      {msg && <span role="status" style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{msg}</span>}
      {open && hits.length > 0 && (
        <div role="listbox" data-testid="mine-add-results"
          style={{ position: 'absolute', top: '100%', left: 8, zIndex: 20, marginTop: 2, minWidth: 280, maxWidth: 'calc(100% - 16px)',
            background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>
          {hits.map(h => (
            <button key={h.symbol} type="button" role="option" aria-selected={false} data-testid="mine-add-hit" data-symbol={h.symbol}
              onClick={() => add(h.symbol)} disabled={h.on_my_list}
              title={h.on_my_list ? 'Already on your watchlist.' : `Add ${h.symbol} to My Watchlist${h.identity_status ? ` (identity ${h.identity_status})` : ''}.`}
              style={{ display: 'flex', gap: 8, width: '100%', textAlign: 'left', padding: '4px 8px', background: 'none', border: 'none',
                borderBottom: `1px solid ${TOKENS.borderSubtle}`, color: TOKENS.text[0], cursor: h.on_my_list ? 'default' : 'pointer', fontSize: TYPE.base }}>
              <b style={{ fontFamily: FONT.mono, minWidth: 56 }}>{h.symbol}</b>
              <span style={{ color: TOKENS.text[2], overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.name || '—'}</span>
              {h.on_my_list && <span style={{ marginLeft: 'auto', color: TOKENS.warning }}>★ yours</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

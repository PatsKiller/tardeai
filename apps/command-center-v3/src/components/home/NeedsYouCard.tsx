/** Home v008 "Needs you" (design home/v008, operator-approved 2026-11-03; spec SPEC_HOME_V008_NEEDS_YOU_APPROVALS_20261103).
 *
 *  The very top of Home, and the same list on Approvals. Shows only real operator decisions from
 *  GET /api/v2/home/approvals, urgent first then newest. Empty → one small green line. Buttons are Approve / Decline /
 *  Ask, and only for request types on the server's CLOSED action list (lib/homeApprovals CLOSED_ACTIONS). Approve and
 *  Decline always pass through an in-page confirm sheet that first re-reads the request with ?revalidate=1, so the
 *  operator sees "This changed" before deciding and the POST carries the exact binding of the card he was shown.
 *  Every click shows the receipt or the refusal the API returned, in its own words. Nothing here decides anything. */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import {
  ACTION_TAG, HOME_APPROVALS, askedBy, blockedText, boundFacts, fetchForConfirm, isClosedAction, isUrgent, needsYouList, postDecision,
  timeLabel, type NeedsYouItem, type NeedsYouQueue, type Outcome, type Verb,
} from '../../lib/homeApprovals'

const warn = toneVars('warning')
const ok = toneVars('success')
const bad = toneVars('danger')
const info = toneVars('info')

const S = {
  card: { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderLeft: `4px solid ${warn.color}`, borderRadius: RADIUS.lg,
    padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } as CSSProperties,
  hd: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } as CSSProperties,
  h2: { margin: 0, fontSize: 16, fontWeight: 700, color: TOKENS.text[0] } as CSSProperties,
  count: { fontSize: TYPE.base, fontWeight: 800, borderRadius: 999, padding: '2px 9px', background: warn.bg, color: warn.color } as CSSProperties,
  sub: { fontSize: TYPE.base, color: TOKENS.text[3], marginLeft: 'auto' } as CSSProperties,
  req: { background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } as CSSProperties,
  h3: { margin: 0, fontSize: 15, lineHeight: 1.35, color: TOKENS.text[0], overflowWrap: 'anywhere' } as CSSProperties,
  tag: { fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.05em', borderRadius: 999, padding: '2px 7px' } as CSSProperties,
  meta: { fontSize: TYPE.sm, color: TOKENS.text[3], fontFamily: FONT.mono, overflowWrap: 'anywhere' } as CSSProperties,
  kv: { display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 10px', fontSize: 13, lineHeight: 1.45, margin: 0 } as CSSProperties,
  dt: { color: TOKENS.text[3] } as CSSProperties,
  dd: { margin: 0, color: TOKENS.text[1], overflowWrap: 'anywhere' } as CSSProperties,
  btn: { minHeight: 46, borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, fontWeight: 700, fontSize: 14, cursor: 'pointer',
    background: TOKENS.bg[2], color: TOKENS.text[0], fontFamily: 'inherit' } as CSSProperties,
}
const approveBtn: CSSProperties = { ...S.btn, background: ok.color, color: TOKENS.bg[0], borderColor: ok.color }
const declineBtn: CSSProperties = { ...S.btn, color: bad.color }
const askBtn: CSSProperties = { ...S.btn, padding: '0 12px', fontWeight: 600, color: TOKENS.text[1] }

const SHEET_CSS = `
[data-testid="needs-you-btns"]{display:grid;grid-template-columns:1fr 1fr auto;gap:8px}
[data-testid="needs-you-btns"] button:disabled{opacity:.55;cursor:not-allowed}
[data-testid="needs-you-card"] button:focus-visible,[data-testid="needs-you-sheet"] button:focus-visible,[data-testid="needs-you-sheet"] textarea:focus-visible{outline:2px solid var(--info-color);outline-offset:2px}
@media (prefers-reduced-motion:reduce){[data-testid="needs-you-card"] *{transition:none!important}}
`

type Sheet = {
  item: NeedsYouItem
  verb: Verb
  phase: 'checking' | 'confirm' | 'blocked' | 'sending'
  binding: string | null
  reason: string | null
  note: string
}

function sheetTitle(verb: Verb, item: NeedsYouItem): string {
  const t = item.title || 'this request'
  return verb === 'approve' ? `Approve: ${t}?` : verb === 'decline' ? `Decline: ${t}?` : `Ask the lead about: ${t}`
}

export function OutcomeLine({ outcome }: { outcome: Outcome }) {
  const tone = outcome.kind === 'done' || outcome.kind === 'question' ? ok : outcome.kind === 'pending' ? info : outcome.kind === 'declined' ? warn : bad
  return (
    <div data-testid="needs-you-outcome" data-kind={outcome.kind} role="status" style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13, color: tone.color }}>
      <b style={{ color: outcome.kind === 'refused' || outcome.kind === 'failed' ? bad.color : TOKENS.text[0] }}>{outcome.text}</b>
      {outcome.receipt
        ? <span style={S.meta} data-testid="needs-you-receipt">Receipt saved to the coordination log · {outcome.receipt.slice(0, 12)}</span>
        : outcome.code ? <span style={S.meta}>{outcome.code.replace(/_/g, ' ').toLowerCase()}</span> : null}
    </div>
  )
}

export function NeedsYouRequest({ item, outcome, blocked, busy, onAct }: {
  item: NeedsYouItem; outcome?: Outcome; blocked?: string | null; busy?: boolean; onAct: (verb: Verb, item: NeedsYouItem) => void
}) {
  const urgent = isUrgent(item)
  const stop = blocked ?? blockedText(item)
  const settled = outcome && (outcome.kind !== 'refused' && outcome.kind !== 'question')
  const tagStyle = { ...S.tag, ...(urgent ? { color: bad.color, background: bad.bg } : { color: info.color, background: info.bg }) }
  const facts = boundFacts(item.facts)
  return (
    <article style={S.req} data-testid="needs-you-request" data-id={item.id} data-type={item.type} aria-label={item.title || 'Request'}>
      <div style={S.hd}>
        <span style={tagStyle}>{urgent ? 'URGENT' : isClosedAction(item.type) ? ACTION_TAG[item.type] : 'DECISION'}</span>
        <span style={S.meta}>{askedBy(item.requester)} · {timeLabel(item.created_at)}{item.expires_at ? ` · expires ${timeLabel(item.expires_at)}` : ''}</span>
      </div>
      <h3 style={S.h3}>{item.title || 'Untitled request'}</h3>
      <dl style={S.kv}>
        {(item.why || item.rule) && <><dt style={S.dt}>Why you</dt><dd style={S.dd}>{[item.why, item.rule].filter(Boolean).join(' · ')}</dd></>}
        {item.what_happens && <><dt style={S.dt}>On approve</dt><dd style={S.dd}>{item.what_happens}</dd></>}
        {item.risk && <><dt style={S.dt}>Risk</dt><dd style={S.dd}>{item.risk}</dd></>}
        {item.undo && <><dt style={S.dt}>Undo</dt><dd style={S.dd}>{item.undo}</dd></>}
        {item.question?.note && <><dt style={S.dt}>You asked</dt><dd style={S.dd}>{item.question.note}</dd></>}
      </dl>
      {facts && <span style={S.meta} data-testid="needs-you-facts">{facts}</span>}
      {outcome && <OutcomeLine outcome={outcome} />}
      {settled ? null : stop ? (
        <div data-testid="needs-you-blocked" style={{ fontSize: 13, color: warn.color }}>{stop}</div>
      ) : (
        <div data-testid="needs-you-btns">
          <button type="button" style={approveBtn} disabled={busy} onClick={() => onAct('approve', item)}>Approve</button>
          <button type="button" style={declineBtn} disabled={busy} onClick={() => onAct('decline', item)}>Decline</button>
          <button type="button" style={askBtn} disabled={busy} onClick={() => onAct('question', item)}>Ask</button>
        </div>
      )}
    </article>
  )
}

export function ConfirmSheet({ sheet, onCancel, onConfirm, onNote }: {
  sheet: Sheet; onCancel: () => void; onConfirm: () => void; onNote: (note: string) => void
}) {
  const primary = useRef<HTMLButtonElement | null>(null)
  const area = useRef<HTMLTextAreaElement | null>(null)
  useEffect(() => {
    if (sheet.phase !== 'confirm') return
    ;(sheet.verb === 'question' ? area.current : primary.current)?.focus()
  }, [sheet.phase, sheet.verb])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && sheet.phase !== 'sending') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel, sheet.phase])
  const sending = sheet.phase === 'sending'
  const yes = sheet.verb === 'approve' ? 'Yes, approve' : sheet.verb === 'decline' ? 'Yes, decline' : 'Send to the lead'
  const yesStyle = sheet.verb === 'approve' ? approveBtn : sheet.verb === 'decline' ? { ...S.btn, color: bad.color, borderColor: bad.border } : { ...S.btn, color: info.color, borderColor: info.border }
  const canSend = sheet.phase === 'confirm' && (sheet.verb !== 'question' || sheet.note.trim().length > 0)
  return (
    <>
      <div data-testid="needs-you-scrim" onClick={sending ? undefined : onCancel} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1000 }} />
      <div data-testid="needs-you-sheet" role="dialog" aria-modal="true" aria-labelledby="needs-you-sheet-title" data-verb={sheet.verb} data-phase={sheet.phase}
        style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 1001, background: TOKENS.bg[2], borderTop: `1px solid ${TOKENS.border}`,
          borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0', maxWidth: 640, margin: '0 auto', boxSizing: 'border-box', maxHeight: '85vh', overflowY: 'auto',
          padding: '16px max(16px, env(safe-area-inset-right, 0px)) calc(20px + env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-left, 0px))',
          display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h4 id="needs-you-sheet-title" style={{ margin: 0, fontSize: 17, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{sheetTitle(sheet.verb, sheet.item)}</h4>
        {sheet.phase === 'checking' && <p role="status" style={{ margin: 0, fontSize: 14, color: TOKENS.text[2] }}>Checking that nothing changed…</p>}
        {sheet.phase === 'blocked' && <p data-testid="needs-you-sheet-blocked" style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: warn.color }}>{sheet.reason}</p>}
        {(sheet.phase === 'confirm' || sending) && sheet.verb !== 'question' && <>
          {sheet.verb === 'approve' && sheet.item.what_happens && <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: TOKENS.text[1] }}>{sheet.item.what_happens}</p>}
          {sheet.verb === 'approve' && sheet.item.risk && <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: TOKENS.text[2] }}>Risk: {sheet.item.risk}{sheet.item.undo ? ` · Undo: ${sheet.item.undo}` : ''}</p>}
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: TOKENS.text[1] }}>
            {sheet.verb === 'approve'
              ? 'This is recorded as your approval from your own logged-in Command Center. Agents can ask, but they can never approve.'
              : 'The lead is told and will not ask again unless something changes.'}
          </p>
          {boundFacts(sheet.item.facts) && <span style={S.meta}>{boundFacts(sheet.item.facts)}</span>}
        </>}
        {(sheet.phase === 'confirm' || sending) && sheet.verb === 'question' && <>
          <label htmlFor="needs-you-note" style={{ fontSize: 14, color: TOKENS.text[1] }}>Your question goes to the lead's inbox. It does not approve or decline anything.</label>
          <textarea id="needs-you-note" ref={area} value={sheet.note} maxLength={2000} rows={3} disabled={sending} onChange={e => onNote(e.target.value)}
            style={{ width: '100%', boxSizing: 'border-box', fontSize: 16, fontFamily: 'inherit', padding: 10, borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`,
              background: TOKENS.bg[0], color: TOKENS.text[0], resize: 'vertical' }} />
        </>}
        <div style={{ display: 'grid', gridTemplateColumns: sheet.phase === 'blocked' || sheet.phase === 'checking' ? '1fr' : '1fr 1fr', gap: 8 }}>
          {(sheet.phase === 'confirm' || sending) && <button type="button" ref={primary} data-testid="needs-you-confirm" style={yesStyle} disabled={!canSend} onClick={onConfirm}>{sending ? 'Sending…' : yes}</button>}
          <button type="button" data-testid="needs-you-cancel" style={S.btn} disabled={sending} onClick={onCancel}>{sheet.phase === 'blocked' ? 'Close' : 'Cancel'}</button>
        </div>
      </div>
    </>
  )
}

/** The card body for a loaded queue. Pure enough to render in a test with renderToStaticMarkup. */
export function NeedsYouView({ queue, error, loading, outcomes = {}, blocked = {}, busyId = null, onAct, surface = 'home' }: {
  queue: NeedsYouQueue | null; error?: string | null; loading?: boolean; outcomes?: Record<string, Outcome>; blocked?: Record<string, string>
  busyId?: string | null; onAct: (verb: Verb, item: NeedsYouItem) => void; surface?: 'home' | 'approvals'
}) {
  const { items, hiddenUnknown } = needsYouList(queue)
  const asOf = queue?.as_of ? timeLabel(queue.as_of) : null
  if (!queue) {
    // An unreadable store is never shown as "Nothing needs you" (home_approvals_api: "never an empty list").
    if (!error && loading) return null
    if (!error) return null
    return (
      <section data-testid="needs-you-card" data-state="unavailable" aria-label="Needs you" style={{ ...S.card, borderLeftColor: TOKENS.border, padding: '8px 14px' }}>
        <div style={S.hd}><h2 style={{ ...S.h2, fontSize: 14 }}>Needs you</h2><span style={{ ...S.sub, overflowWrap: 'anywhere' }}>could not be checked: {error}</span></div>
      </section>
    )
  }
  const open = items.filter(it => { const o = outcomes[it.id]; return !o || o.kind === 'refused' || o.kind === 'question' }).length
  if (items.length === 0) {
    return (
      <section data-testid="needs-you-card" data-state="empty" aria-label="Needs you" style={{ ...S.card, borderLeftColor: ok.color, padding: '8px 14px', gap: 4 }}>
        <div style={S.hd}>
          <h2 style={{ ...S.h2, fontSize: 14 }}>Needs you</h2>
          <span data-testid="needs-you-empty" style={{ color: ok.color, fontWeight: 600, fontSize: 13 }}>{queue.empty_text || 'Nothing needs you'}</span>
          {asOf && <span style={S.sub}>checked {asOf}</span>}
        </div>
        {hiddenUnknown > 0 && <span style={S.meta}>{hiddenUnknown} request(s) not shown: type is not on the reviewed action list.</span>}
      </section>
    )
  }
  return (
    <section data-testid="needs-you-card" data-state="list" aria-label="Needs you" style={S.card}>
      <div style={S.hd}>
        <h2 style={S.h2}>Needs you</h2>
        {open > 0 && <span data-testid="needs-you-count" style={S.count}>{open}</span>}
        {asOf && <span style={S.sub}>updated {asOf}{error ? ' · refresh failed' : ''}</span>}
      </div>
      {items.map(item => <NeedsYouRequest key={item.id} item={item} outcome={outcomes[item.id]} blocked={blocked[item.id]} busy={busyId === item.id} onAct={onAct} />)}
      {(queue.has_more || hiddenUnknown > 0) && <span style={S.meta}>
        {queue.has_more ? `Showing ${items.length} of ${queue.total}. ${surface === 'home' ? 'The rest are on Approvals.' : ''}` : ''}
        {hiddenUnknown > 0 ? ` ${hiddenUnknown} request(s) not shown: type is not on the reviewed action list.` : ''}
      </span>}
    </section>
  )
}

/** The live card: polls the queue, runs the confirm sheet, shows each click's receipt or refusal. */
export default function NeedsYouCard({ surface = 'home' }: { surface?: 'home' | 'approvals' }) {
  const api = useApi<NeedsYouQueue>(HOME_APPROVALS, 60_000)
  const [sheet, setSheet] = useState<Sheet | null>(null)
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({})
  const [blocked, setBlocked] = useState<Record<string, string>>({})
  const opener = useRef<HTMLElement | null>(null)

  const close = useCallback(() => {
    setSheet(null)
    opener.current?.focus?.()
  }, [])

  const onAct = useCallback((verb: Verb, item: NeedsYouItem) => {
    opener.current = (typeof document !== 'undefined' ? document.activeElement : null) as HTMLElement | null
    if (verb === 'question') {
      setSheet({ item, verb, phase: 'confirm', binding: null, reason: null, note: '' })
      return
    }
    setSheet({ item, verb, phase: 'checking', binding: null, reason: null, note: '' })
    fetchForConfirm(item.id).then(({ item: fresh, error }) => {
      setSheet(cur => {
        if (!cur || cur.item.id !== item.id || cur.verb !== verb) return cur
        if (!fresh) return { ...cur, phase: 'blocked', reason: error }
        const stop = blockedText(fresh) ?? (fresh.binding ? null : 'This request could not be bound to the card you were shown. Reload Home and try again.')
        if (stop) {
          setBlocked(b => ({ ...b, [item.id]: stop }))
          return { ...cur, item: { ...cur.item, ...fresh }, phase: 'blocked', reason: stop }
        }
        return { ...cur, item: { ...cur.item, ...fresh }, phase: 'confirm', binding: fresh.binding ?? null }
      })
    })
  }, [])

  const onConfirm = useCallback(() => {
    if (!sheet || sheet.phase !== 'confirm') return
    const { item, verb, binding, note } = sheet
    setSheet({ ...sheet, phase: 'sending' })
    const body = verb === 'question' ? { note: note.trim() } : { binding: binding ?? '' }
    postDecision(item.id, verb, body).then(outcome => {
      setOutcomes(o => ({ ...o, [item.id]: outcome }))
      if (outcome.blocked) setBlocked(b => ({ ...b, [item.id]: outcome.blocked as string }))
      else if (outcome.expired) setBlocked(b => ({ ...b, [item.id]: outcome.text }))
      else if (outcome.kind === 'refused' && (outcome.code === 'NOT_OPEN' || outcome.code === 'NOT_FOUND')) setBlocked(b => ({ ...b, [item.id]: outcome.text }))
      setSheet(null)
      opener.current?.focus?.()
      api.refetch()
    })
  }, [sheet, api])

  return (
    <>
      <style>{SHEET_CSS}</style>
      <NeedsYouView queue={api.data} error={api.error} loading={api.loading} outcomes={outcomes} blocked={blocked}
        busyId={sheet?.item.id ?? null} onAct={onAct} surface={surface} />
      {sheet && <ConfirmSheet sheet={sheet} onCancel={close} onConfirm={onConfirm} onNote={note => setSheet(s => s ? { ...s, note } : s)} />}
    </>
  )
}

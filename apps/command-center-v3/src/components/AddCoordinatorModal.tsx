// Add a coordinator (operator 2026-11-02 addendum to PLAN_CO_COORDINATORS_20261102): pick a vendor, get a default
// id, and copy the ONE server-side join line. The line is rendered by GET /api/v2/coordination/join-command from
// persistent-state/data/coordination/coordinator/join_command.template, so editing that file updates this dialog with
// no deploy. READ-ONLY: there is no appoint button here — appointment stays the operator's word via the lead.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { MobileDetailSheet } from './MobileDetailSheet'
import { useApi } from '../hooks/useApi'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'
import { heartbeatLabel, joinLineForSelection, stateLabel, type CoordinatorRow } from '../lib/coordinators'

const VENDORS = [
  { key: 'claude', label: 'Claude Code' },
  { key: 'codex', label: 'Codex' },
  { key: 'cursor', label: 'Cursor' },
  { key: 'grok', label: 'Grok' },
  { key: 'other', label: 'Other' },
] as const
const DEFAULT_ID: Record<string, string> = { claude: 'claude', codex: 'codex', cursor: 'cursor', grok: 'grok', other: 'other' }
const ID_RE = /^[a-z0-9-]{1,40}$/

type JoinPayload = {
  schema?: string
  template_present?: boolean
  template_path?: string
  template_modified_at?: string | null
  valid?: boolean
  line?: string | null
  error?: string | null
  id?: string
  vendor?: string
}

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 16,
  width: 'min(560px, 92vw)', maxHeight: '86vh', overflow: 'auto', boxSizing: 'border-box',
}
const label: CSSProperties = {
  fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 750,
}
const btn = (active: boolean): CSSProperties => ({
  minHeight: 44, minWidth: 44, padding: '8px 12px', borderRadius: RADIUS.md, cursor: 'pointer',
  border: `1px solid ${active ? TOKENS.primary : TOKENS.border}`,
  background: active ? TOKENS.bg[2] : TOKENS.bg[0],
  color: active ? TOKENS.text[0] : TOKENS.text[1], fontSize: TYPE.sm, fontWeight: active ? 800 : 500,
})
const input: CSSProperties = {
  minHeight: 44, width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: RADIUS.sm,
  border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[0], color: TOKENS.text[0],
  fontFamily: FONT.mono, fontSize: TYPE.sm,
}

function useIsPhone(): boolean {
  const [phone, setPhone] = useState(() => (typeof window !== 'undefined' ? window.matchMedia('(max-width: 820px)').matches : false))
  useEffect(() => {
    const media = window.matchMedia('(max-width: 820px)')
    const update = () => setPhone(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return phone
}

function Body({ coordinators, onClose }: { coordinators: CoordinatorRow[]; onClose: () => void }) {
  const [vendor, setVendor] = useState<string>('claude')
  const [id, setId] = useState<string>(DEFAULT_ID.claude)
  const [copied, setCopied] = useState(false)
  const idOk = ID_RE.test(id)
  const url = `/api/v2/coordination/join-command?id=${encodeURIComponent(id)}&vendor=${encodeURIComponent(vendor)}`
  const api = useApi<JoinPayload>(url, 15_000, { enabled: idOk })
  // useApi keeps the previous payload while the new request loads: only a response that names THIS id and vendor
  // may be shown or copied. A slow or failed request must never leave the old coordinator's line on screen.
  const matchesSelection = !!api.data && api.data.id === id && api.data.vendor === vendor
  const line = idOk ? joinLineForSelection(api.data, id, vendor) : ''
  const templateAt = matchesSelection ? api.data?.template_modified_at : undefined

  const pickVendor = (key: string) => {
    setVendor(key)
    setId(DEFAULT_ID[key] || 'other')
    setCopied(false)
  }

  const copy = async () => {
    if (!line) return
    try {
      await navigator.clipboard.writeText(line)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 14 }} data-testid="add-coordinator-body">
      <div style={{ display: 'grid', gap: 6 }}>
        <div style={label}>which agent</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {VENDORS.map(v => (
            <button key={v.key} type="button" onClick={() => pickVendor(v.key)} style={btn(vendor === v.key)}
              aria-pressed={vendor === v.key} data-testid={`vendor-${v.key}`}>{v.label}</button>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gap: 6 }}>
        <label htmlFor="coordinator-id" style={label}>coordinator id</label>
        <input id="coordinator-id" data-testid="coordinator-id" value={id} onChange={e => { setId(e.target.value.toLowerCase()); setCopied(false) }}
          style={input} autoComplete="off" spellCheck={false} placeholder="codex-a" />
        <div style={{ fontSize: TYPE.xs, color: idOk ? TOKENS.text[3] : TOKENS.danger }}>
          lower-case letters, digits and dashes only ({idOk ? 'valid' : 'invalid'})
        </div>
      </div>

      <div style={{ display: 'grid', gap: 6 }}>
        <div style={label}>join line — copy and paste to the new session</div>
        {matchesSelection && api.data?.template_present === false ? (
          <div role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.text[2], background: TOKENS.bg[2], padding: '8px 10px', borderRadius: RADIUS.sm }}>
            The join template is missing. The operator creates{' '}
            <code>{api.data?.template_path || 'persistent-state/data/coordination/coordinator/join_command.template'}</code>.
          </div>
        ) : (
          <>
            <textarea readOnly value={line} rows={3} data-testid="join-line" aria-label="join line"
              style={{ ...input, fontFamily: FONT.mono, minHeight: 76, resize: 'vertical' }} />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button type="button" onClick={copy} disabled={!line} style={btn(!!line)} data-testid="copy-join-line">
                {copied ? 'Copied' : 'Copy'}
              </button>
              <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>
                template {templateAt ? `updated ${heartbeatLabel(templateAt)}` : 'update time unknown'} · editing it updates this line with no deploy
              </span>
            </div>
          </>
        )}
        {api.error ? <div role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>join line unavailable</div> : null}
      </div>

      <div style={{ display: 'grid', gap: 6 }}>
        <div style={label}>current coordinators</div>
        {coordinators.length ? (
          <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 3 }}>
            {coordinators.map(c => (
              <li key={String(c.id)} style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
                <strong>{c.id}</strong> · {c.vendor || 'vendor?'} · {String(c.role || 'member')} · {stateLabel(c.state)} ·
                {' '}{(c.territories || []).join(', ') || 'no territory'}
              </li>
            ))}
          </ul>
        ) : <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>None appointed yet.</div>}
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button type="button" onClick={onClose} style={btn(false)} data-testid="add-coordinator-close">Close</button>
      </div>
    </div>
  )
}

export default function AddCoordinatorModal({ open, onClose, coordinators }: {
  open: boolean; onClose: () => void; coordinators: CoordinatorRow[]
}) {
  const phone = useIsPhone()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ref.current?.querySelector<HTMLElement>('button, input')?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', onKey)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [open, onClose])
  if (!open) return null
  const body = <Body coordinators={coordinators} onClose={onClose} />
  if (phone) return <MobileDetailSheet title="Add a coordinator" onBack={onClose}>{body}</MobileDetailSheet>
  return createPortal(
    <div style={{ position: 'fixed', inset: 0, zIndex: 1200, background: 'rgba(0,0,0,0.55)', display: 'grid', placeItems: 'center', padding: 16 }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label="Add a coordinator" style={panel} data-testid="add-coordinator-modal">
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Add a coordinator</div>
          <div style={{ ...label, maxWidth: 260 }}>read-only: appointing stays the operator's word via the lead</div>
        </div>
        {body}
      </div>
    </div>,
    document.body,
  )
}

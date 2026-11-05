// One health finding, in the operator's words first and the implementer's detail behind a toggle (FQ-038).
//
// The audit saw a phone screen that was a wall of expanded cards: filesystem paths, unit names, raw event codes and
// command-like repair text, all in the normal view. Nothing is removed — the same fields are here — but the card opens
// with what a person needs (what broke, how bad, who has it, when) and the implementation detail is one tap away.
import { useState, type CSSProperties, type ReactNode } from 'react'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import { fmtAsOf } from '../lib/asOfDisplay'
import { humanizeCode } from '../lib/displayLabels'

const SEV_COLOR: Record<string, string> = {
  critical: TOKENS.danger, warning: TOKENS.warning, info: TOKENS.text[2],
}
const label: CSSProperties = { fontSize: TYPE.xs, fontWeight: 800, color: TOKENS.text[2], textTransform: 'uppercase', letterSpacing: 0.3, marginBottom: 2 }

export type HealthFinding = {
  message?: string | null; why?: string | null; recommended_action?: string | null
  severity?: string | null; category?: string | null; detected_by?: string | null; detected_at?: string | null
  remediation?: { status?: string | null; by?: string | null; at?: string | null; detail?: string | null } | null
}

/** The card's always-visible half: the facts a person acts on. */
export function findingHeadline(f: HealthFinding): string {
  return String(f.message || 'A health check reported a problem, without saying which.')
}

/** Everything implementation-shaped, kept but behind the toggle. */
export function findingDetail(f: HealthFinding): { why: string | null; action: string | null; detail: string | null } {
  const rem = f.remediation || {}
  const clean = (v: unknown) => { const s = String(v ?? '').trim(); return s || null }
  return { why: clean(f.why), action: clean(f.recommended_action), detail: clean(rem.detail) }
}

/** When it broke (or was last handled): the fourth fact the card's own header promises, so it is always visible. */
export function findingWhen(f: HealthFinding): string | null {
  const raw = String((f.remediation || {}).at || f.detected_at || '').trim()
  return raw || null
}

export function HealthFindingCard({ finding, compact = false, categoryLabel, onOpen, children }: {
  finding: HealthFinding
  compact?: boolean
  /** the page's human category label (CAT_LABEL); absent falls back to humanising the producer code */
  categoryLabel?: string | null
  /** the page's drill-down (the /health hub opens its drawer with this); absent means the card is read-only */
  onOpen?: () => void
  /** the page's own action buttons — kept at the call site because they own the remediate state, never forked here */
  children?: ReactNode
}): ReactNode {
  const [open, setOpen] = useState(false)
  const rem = finding.remediation || {}
  const sev = String(finding.severity ?? 'info').toLowerCase()
  const detail = findingDetail(finding)
  const hasDetail = Boolean(detail.why || detail.action || detail.detail)
  const whenRaw = findingWhen(finding)
  const categoryText = String(categoryLabel ?? humanizeCode(finding.category))
  return (
    <div data-testid="health-finding" data-severity={sev} data-openable={onOpen ? 'true' : 'false'}
      onClick={onOpen}
      style={{ padding: '10px 12px', background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`,
        borderLeft: `3px solid ${SEV_COLOR[sev] || TOKENS.border}`, borderRadius: RADIUS.md, marginBottom: 6, minWidth: 0,
        cursor: onOpen ? 'pointer' : 'default' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, textTransform: 'uppercase', color: SEV_COLOR[sev] || TOKENS.text[2] }}>{sev}</span>
        <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }} title={String(finding.category ?? '')}>{categoryText}</span>
        {/* WHEN — always visible, like severity and category; the raw stamp stays in the tooltip */}
        {whenRaw ? <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }} title={whenRaw}>{fmtAsOf(whenRaw)}</span> : null}
        <span style={{ marginLeft: 'auto', fontSize: TYPE.xs, fontWeight: 800, color: TOKENS.text[1] }}>
          {String(rem.status ?? 'detected').replace(/_/g, ' ')}
        </span>
      </div>
      {/* WHAT — the only line a phone shows by default, in the server's own sentence */}
      <div style={{ fontSize: TYPE.base, fontWeight: 700, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>
        {findingHeadline(finding)}
      </div>
      {!compact && (
        <div style={{ display: 'flex', gap: 10, marginTop: 4, flexWrap: 'wrap' }}>
          <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>Seen by {String(finding.detected_by ?? 'the health check')}</span>
          {rem.by ? <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>handled by {String(rem.by)}</span> : null}
        </div>
      )}
      {hasDetail ? (
        <>
          <button type="button" data-testid="health-finding-toggle" aria-expanded={open}
            onClick={e => { e.stopPropagation(); setOpen(v => !v) }}
            style={{ marginTop: 6, minHeight: 44, background: 'none', border: 'none', padding: 0, cursor: 'pointer',
              color: TOKENS.primary, fontSize: TYPE.xs, fontWeight: 700 }}>
            {open ? 'Hide the technical detail' : 'Why, and what to do →'}
          </button>
          {open ? (
            <div data-testid="health-finding-detail" style={{ display: 'grid', gap: 6, marginTop: 6 }}>
              {detail.why ? <div><div style={label}>Why / root cause</div>
                <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], overflowWrap: 'anywhere' }}>{detail.why}</div></div> : null}
              {detail.action ? <div><div style={label}>How (action)</div>
                <div style={{ fontSize: TYPE.sm, color: TOKENS.primary, overflowWrap: 'anywhere' }}>{detail.action}</div></div> : null}
              {detail.detail ? <div><div style={label}>Repair detail</div>
                <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], overflowWrap: 'anywhere' }}>{detail.detail}</div></div> : null}
            </div>
          ) : null}
        </>
      ) : null}
      {children ? (
        <div data-testid="health-finding-actions" onClick={e => e.stopPropagation()}
          style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          {children}
        </div>
      ) : null}
    </div>
  )
}

export default HealthFindingCard

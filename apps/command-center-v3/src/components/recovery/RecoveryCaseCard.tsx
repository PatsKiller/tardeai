/** Recovery & re-entry case card (piece D) — Home's high-impact card and the Risk → Recovery detail share it.
 *  Design: recovery-reentry-mockup-20261103-codex, operator-APPROVED 2026-11-06. Advisory only: renders the server's
 *  case projection; no size, stop, target, order or policy is computed here. Actions stay disabled until a server
 *  endpoint validates them (see lib/recoveryCases.ts). */
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../../lib/designTokens'
import {
  actionStates, eligibilityLine, etTime, fmtPrice, fmtUsd, quoteLabel, reviewGate, NOT_WIRED,
  type RecoveryCaseView, type RecoveryProjection, type ReviewGate,
} from '../../lib/recoveryCases'

const box = { background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: '10px 12px', minWidth: 0 }
// Two-up rows use flex-wrap: the app's phone rule collapses inline grid columns, and the approved mockup is 2×2 at 390.
const pair = { display: 'flex', flexWrap: 'wrap' as const, gap: 8 }
const half = { ...box, flex: '1 1 calc(50% - 4px)' }
const small = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const kicker = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' as const }

function Chip({ tone, children, testId }: { tone: Parameters<typeof toneVars>[0]; children: ReactNode; testId?: string }) {
  const t = toneVars(tone)
  return <span data-testid={testId} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 999, color: t.color, background: t.bg, border: `1px solid ${t.border}`, whiteSpace: 'nowrap' }}>{children}</span>
}

/** Remember the version the operator last reviewed per case; a different version on screen means "changed". */
export function useReviewedVersions() {
  const [seen, setSeen] = useState<Record<string, string | null>>({})
  const note = (cases: RecoveryCaseView[]) => setSeen(prev => {
    let next = prev
    for (const c of cases) if (!(c.key in prev)) { if (next === prev) next = { ...prev }; next[c.key] = c.version }
    return next
  })
  const review = (c: RecoveryCaseView) => setSeen(prev => ({ ...prev, [c.key]: c.version }))
  return { seen, note, review }
}

export function RecoveryCaseCard({ projection, c, gate, unavailable, onReview, heading, footerLink, testId = 'recovery-case-card' }: {
  projection: RecoveryProjection; c: RecoveryCaseView; gate: ReviewGate; unavailable: boolean
  onReview: () => void; heading: string; footerLink?: { to: string; label: string }; testId?: string
}) {
  const [why, setWhy] = useState(false)
  const quote = unavailable ? quoteLabel(null) : quoteLabel(c.quote)
  const actions = actionStates(projection, c, gate, unavailable)
  const highImpact = c.materialityTier === 'T1'
  const warn = toneVars('warning'), bad = toneVars('danger')
  const status = unavailable ? <Chip tone="neutral" testId="recovery-status">Unavailable</Chip>
    : gate === 'changed' ? <Chip tone="warning" testId="recovery-status">Review updated case</Chip>
    : <Chip tone={c.stateTone} testId="recovery-status">{c.stateLabel}</Chip>
  return (
    <section data-testid={testId} data-case-key={c.key} data-case-version={c.version ?? ''} data-review-gate={gate} data-unavailable={unavailable ? 'true' : 'false'}
      style={{ background: TOKENS.bg[1], border: `1px solid ${highImpact ? warn.border : TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0, overflowWrap: 'anywhere' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '12px 16px', borderBottom: `1px solid ${TOKENS.borderSubtle}` }}>
        <span style={{ ...kicker, color: highImpact ? TOKENS.warning : TOKENS.text[2] }}>{heading}</span>
        {status}
      </header>
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: TYPE.xl, fontWeight: 700, color: TOKENS.text[0] }}>{c.symbol}{unavailable ? ' · recovery data unavailable' : ` · ${c.stateLabel.toLowerCase()}`}</h3>
          <p style={{ ...small, margin: '6px 0 0' }}>{c.account} · confirmed exit {c.exitDate ?? 'date unavailable'}{c.materialityTier ? ` · impact tier ${c.materialityTier}` : ''}</p>
          <p style={{ ...small, margin: '4px 0 0' }}>Realized loss <b data-testid="recovery-realized" style={{ ...numStyle, color: c.realizedPnl != null && c.realizedPnl < 0 ? TOKENS.danger : TOKENS.text[1] }}>{fmtUsd(c.realizedPnl)}</b></p>
        </div>

        {unavailable && <div role="status" data-testid="recovery-unavailable" style={{ background: bad.bg, border: `1px solid ${bad.border}`, borderRadius: RADIUS.md, padding: 12 }}>
          <b style={{ color: bad.color }}>Data unavailable</b>
          <p style={{ margin: '4px 0 0', color: TOKENS.text[1] }}>{projection.reason ?? 'The recovery source did not answer.'} Last verified case: {etTime(c.asOf)}. Refresh the case before deciding.</p>
        </div>}
        {!unavailable && gate === 'changed' && <div role="status" data-testid="recovery-changed" style={{ background: bad.bg, border: `1px solid ${bad.border}`, borderRadius: RADIUS.md, padding: 12 }}>
          <b style={{ color: bad.color }}>This case changed</b>
          <p style={{ margin: '4px 0 8px', color: TOKENS.text[1] }}>{c.version ? 'Review the latest case details before deciding. No action uses the earlier version.' : 'This case has no version, so no decision can be bound to it.'}</p>
          {c.version && <button type="button" data-testid="recovery-review-latest" onClick={onReview} style={{ minHeight: 44, padding: '0 14px', color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>Review latest case</button>}
        </div>}

        <div style={pair}>
          <div style={half} data-testid="recovery-quote">
            <div style={small}>Latest quote</div>
            <div style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 700, margin: '4px 0' }}>{quote.value}</div>
            <div style={{ ...small, fontSize: TYPE.xs }}>{quote.detail}</div>
          </div>
          <div style={half} data-testid="recovery-exit">
            <div style={small}>Confirmed exit</div>
            <div style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 700, margin: '4px 0' }}>{fmtPrice(c.exitPrice)}</div>
            <div style={{ ...small, fontSize: TYPE.xs }}>{c.exitDate ?? 'Date unavailable'} · confirmed fill</div>
          </div>
        </div>

        <div style={{ ...box, borderColor: toneVars('info').border }}>
          <div style={{ ...kicker, color: TOKENS.info }}>Next confirmation</div>
          <p data-testid="recovery-next-trigger" style={{ margin: '4px 0 0', color: TOKENS.text[1], fontSize: TYPE.sm }}>Not published by the recovery case store yet. Confidence and the next trigger are evaluated by the state machine but not stored on the case.</p>
        </div>

        <button type="button" aria-expanded={why} onClick={() => setWhy(v => !v)} style={{ alignSelf: 'flex-start', minHeight: 44, background: 'none', border: 0, color: TOKENS.info, cursor: 'pointer', padding: 0, fontSize: TYPE.base }}>{why ? '−' : '+'} Why this case is {c.stateLabel.toLowerCase()}</button>
        {why && <div data-testid="recovery-why" style={small}>
          <p style={{ margin: 0 }}>State {c.stateLabel} since {etTime(c.stateSince)} · source {c.source ?? 'unnamed'}.</p>
          {c.residualNote && <p style={{ margin: '4px 0 0' }}>{c.residualNote}</p>}
          {c.gaps.map(g => <p key={g} style={{ margin: '4px 0 0', color: TOKENS.warning }}>Gap: {g}</p>)}
        </div>}

        <div>
          <h4 style={{ margin: '0 0 6px', fontSize: TYPE.base, color: TOKENS.text[0] }}>Where a plan can be considered</h4>
          {c.eligibility.length === 0 && <p style={{ ...small, margin: 0, color: TOKENS.warning }}>Account eligibility unavailable.</p>}
          {c.eligibility.map(e => { const l = eligibilityLine(e)
            return <div key={e.account} data-testid="recovery-eligibility" style={{ padding: '8px 0', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}><b style={{ fontSize: TYPE.sm }}>{e.account}</b><span style={{ fontSize: TYPE.sm, fontWeight: 700, color: toneVars(l.tone).color }}>{l.value}</span></div>
              {e.reason && <div style={{ ...small, fontSize: TYPE.xs }}>{e.reason}</div>}
            </div> })}
        </div>

        {c.pendingOperatorDecision && <div style={{ background: warn.bg, borderLeft: `3px solid ${warn.border}`, padding: '8px 10px', borderRadius: RADIUS.sm }}>
          <b style={{ color: warn.color, fontSize: TYPE.sm }}>Still needs confirmation</b>
          <p style={{ margin: '2px 0 0', fontSize: TYPE.sm, color: TOKENS.text[1] }}>Account eligibility is an open operator decision. This caveat stays on the case while recovery is tracked.</p>
        </div>}
        <p data-testid="recovery-plan" style={{ ...small, margin: 0 }}><b style={{ color: TOKENS.text[1] }}>Plan:</b> {c.planText ?? 'no approved advisory plan is linked yet. Any plan values must arrive with their evidence and approval.'}</p>
        {c.operatorDecision && <p style={{ ...small, margin: 0 }}>Recorded decision: {c.operatorDecision}{c.operatorNote ? ` · ${c.operatorNote}` : ''}</p>}
      </div>

      <div style={{ padding: '12px 16px', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
        <div style={pair}>
          {actions.map(a => <button key={a.action} type="button" data-action={a.action} data-testid={`recovery-action-${a.action}`} disabled={!a.enabled}
            aria-disabled={!a.enabled} title={a.why ?? undefined}
            style={{ flex: '1 1 calc(50% - 4px)', minWidth: 0, minHeight: 44, borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: a.enabled ? TOKENS.text[0] : TOKENS.text[3], cursor: a.enabled ? 'pointer' : 'not-allowed', fontWeight: 600, fontSize: TYPE.sm, padding: '4px 6px' }}>
            {a.label}{!a.enabled && a.why === NOT_WIRED ? <span style={{ display: 'block', fontSize: TYPE.xs, fontWeight: 400 }}>{NOT_WIRED}</span> : null}
          </button>)}
        </div>
        <p data-testid="recovery-actions-note" style={{ ...small, fontSize: TYPE.xs, margin: '8px 0 0' }}>
          {!projection.actionsWired ? `Actions are not wired yet: ${projection.actionsReason}` : unavailable ? 'Decisions pause until the case can be refreshed.' : gate === 'changed' ? 'All decisions wait for a fresh review of this case.' : 'Each decision is bound to this case, account and version.'}
        </p>
      </div>
      <footer style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center', padding: '8px 16px', borderTop: `1px solid ${TOKENS.borderSubtle}`, ...small, fontSize: TYPE.xs }}>
        <span data-testid="recovery-observed">Case observed {etTime(c.asOf)}{unavailable ? ' · last verified, refresh unavailable' : gate === 'changed' ? ' · changed since the decision view' : ''}</span>
        {footerLink && <Link to={footerLink.to} style={{ color: TOKENS.info, textDecoration: 'none', minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>{footerLink.label} →</Link>}
      </footer>
    </section>
  )
}

/** Feed the review tracker on every new projection, and resolve each case's gate. */
export function useCaseGates(cases: RecoveryCaseView[]) {
  const r = useReviewedVersions()
  const sig = cases.map(c => `${c.key}@${c.version}`).join('|')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { r.note(cases) }, [sig])
  return { gate: (c: RecoveryCaseView) => reviewGate(r.seen[c.key], c), review: r.review }
}

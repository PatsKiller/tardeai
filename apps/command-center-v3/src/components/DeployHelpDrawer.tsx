// In-page operator help for System → Releases & schedules → Deploys (operator clarity).
import type { CSSProperties } from 'react'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'

const overlay: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 80,
  display: 'flex', justifyContent: 'flex-end',
}
const drawer: CSSProperties = {
  width: 'min(420px, 100%)', height: '100%', background: TOKENS.bg[1], borderLeft: `1px solid ${TOKENS.border}`,
  padding: 16, overflowY: 'auto', display: 'grid', gap: 12, boxSizing: 'border-box',
}
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const h3: CSSProperties = { margin: '8px 0 0', fontSize: TYPE.sm, fontWeight: 800, color: TOKENS.text[0] }
const p: CSSProperties = { margin: 0, fontSize: TYPE.sm, color: TOKENS.text[1], lineHeight: 1.45 }
const muted: CSSProperties = { margin: 0, fontSize: TYPE.sm, color: TOKENS.text[2], lineHeight: 1.45 }
const dt: CSSProperties = { fontWeight: 700, color: TOKENS.text[0], fontSize: TYPE.sm }
const dd: CSSProperties = { margin: '0 0 8px', fontSize: TYPE.sm, color: TOKENS.text[1], lineHeight: 1.4 }

const GLOSSARY: Array<{ term: string; def: string }> = [
  { term: 'PR (pull request)', def: 'A proposed change waiting to join main. Approving does not put it on your site yet.' },
  { term: 'Approve', def: 'Your go-ahead to merge (same as Telegram). Adds the operator-merge label so Mergify can queue it.' },
  { term: 'Hold', def: 'Takes back Approve — removes operator-merge so Mergify will not merge it.' },
  { term: 'Merge', def: 'The change lands on main (via Mergify). Still not on the live site until promote.' },
  { term: 'Push Live / promote', def: 'Copies what is already on main onto the live site (CURRENT). Separate from Approve.' },
  { term: 'Update branch (Advanced)', def: 'Pushes code to the PR’s GitHub branch only. Not the live site.' },
  { term: 'READY', def: 'Plain English present + four required checks green + not held/draft/conflict — same rule as Telegram.' },
  { term: 'Four tool gates', def: 'cio-hardening, agent-governance, release-readiness, ci-gate — all must be SUCCESS before Approve.' },
  { term: 'UNKNOWN mergeability', def: 'GitHub has not finished checking whether the branch can merge. Wait/refresh — not the same as a conflict.' },
  { term: 'deploy STOP', def: 'A latch that blocks putting new builds on the site. Clear it from Ops → Controls if you intend to promote.' },
  { term: 'Mergify window', def: 'Merges are blocked Mon–Fri 09:30–16:15 ET even after Approve; evenings/weekends are the usual merge times.' },
]

export default function DeployHelpDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return (
    <div role="dialog" aria-modal="true" aria-label="How Deploys works" data-testid="deploy-help-drawer" style={overlay} onClick={onClose}>
      <aside style={drawer} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <h2 style={h2}>How this page works</h2>
          <button type="button" onClick={onClose} data-testid="deploy-help-close"
            style={{ border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.pill, background: TOKENS.bg[2], color: TOKENS.text[0], padding: '4px 10px', fontWeight: 700, cursor: 'pointer' }}>
            Close
          </button>
        </div>

        <h3 style={h3}>60-second version</h3>
        <p style={p}>
          There are two jobs. <b>Job A:</b> Approve a change so it can merge into main (Telegram or the Approve button).
          <b> Job B:</b> Put what is already on main onto your live site (automatic poller or Push Live).
          Approve never updates the live site by itself.
        </p>
        <p style={muted}>
          Flow: open PR → four checks green + plain English → you Approve → Mergify merges to main (outside market hours) →
          then prepare/promote puts that main build on the site.
        </p>

        <h3 style={h3}>Glossary</h3>
        <dl style={{ margin: 0 }}>
          {GLOSSARY.map(g => (
            <div key={g.term}>
              <dt style={dt}>{g.term}</dt>
              <dd style={dd}>{g.def}</dd>
            </div>
          ))}
        </dl>

        <p style={muted}>
          Deep runbook on the host: <code style={{ fontSize: TYPE.xs }}>docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md</code>
        </p>
      </aside>
    </div>
  )
}

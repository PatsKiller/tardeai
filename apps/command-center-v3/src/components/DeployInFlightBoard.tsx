// Deploy console P1+P2 — the "not live / in flight" open-PR board (DSN-20261029-deploy-console).
// P1 (read-only): fetches GET /api/v2/ops/in-flight (scripts/lib/deploy_in_flight.py) and renders each open PR to
// main with the same agent / task / PR / blocker facts as coordinator status: owner, current task, publication
// state (local-only vs published vs merged vs live), review state and CI state bound to the EXACT head, blockers,
// next action, and the source time of each fact — never the capture time. P2 (write path): four operator actions
// behind POST /api/v2/ops/in-flight/action (scripts/lib/deploy_console_actions.py) — Approve (add operator-merge,
// bound to head SHA), Hold (remove it), Refresh hints, Push (bound git-push grant + fast-forward push). Every POST
// is operator-session + same-origin CSRF protected on the server (cc_auth); no authority is newly granted here.
//
// Missing or head-mismatched facts render UNKNOWN with their reason — never a green, a zero or "auto-rebase".
// Critical status is always visible text, never hover-only. Below 820px each row stacks into a card
// (OpsEvidencePages.css .ops-evidence-table rules) and every td carries a data-label.
import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from './primitives'
import { RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import { ageText } from '../lib/releasesSchedules'
import {
  ACTION_PATH, IN_FLIGHT_PATH, KNOWN_SCHEMAS, agentStateTone, nextActionFor, normalizeCoordination,
  normalizeRow, rowFacts, shortSha,
  type CoordinationAgent, type CoordinationBlock, type InFlightPr, type WorkBlock,
} from '../lib/deployInFlight'

type ActionOutcome = { ok: boolean; outcome?: string; error?: string; refusal?: string; reason?: string }

type Wire = {
  schema?: string
  authority?: string
  generated_at?: string
  repo?: string
  prs?: Array<Record<string, unknown>> | null
  count?: number | null
  status?: string
  freshness?: 'OK' | 'STALE' | 'UNAVAILABLE'
  source?: string
  reason?: string | null
  coordination?: unknown
}

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0, display: 'grid', gap: 8 }
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: 0 }
const tiny: CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3], margin: 0 }
const th: CSSProperties = { padding: '6px 6px', fontSize: TYPE.xs, color: TOKENS.text[3], whiteSpace: 'nowrap', textTransform: 'uppercase', textAlign: 'left', verticalAlign: 'top' }
const td: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }

const stateTone = (s: string): Tone => {
  const u = String(s || '').toUpperCase()
  if (u === 'CLEAN') return 'success'
  if (u === 'BLOCKED') return 'danger'
  if (u === 'DIRTY' || u === 'BEHIND' || u === 'UNSTABLE' || u === 'DRAFT' || u === 'UNKNOWN') return 'warning'
  return 'neutral'
}

const btn = (tone: Tone, disabled: boolean): CSSProperties => {
  const t = toneVars(tone)
  return {
    padding: '2px 8px', borderRadius: RADIUS.pill, border: `1px solid ${t.border}`, background: t.bg, color: t.color,
    fontSize: TYPE.xs, fontWeight: 700, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
    whiteSpace: 'nowrap',
  }
}

const asOfText = (iso: string | null): string => {
  if (!iso) return 'source time not stated'
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return `as of ${iso}`
  return `as of ${ageText(Math.max(0, Math.round((Date.now() - t) / 1000)))}`
}

function AgentCard({ a }: { a: CoordinationAgent }) {
  return <div data-testid={`agent-${a.session}`} style={{ border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.md, padding: 10, display: 'grid', gap: 4, minWidth: 0 }}>
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <b style={{ fontSize: TYPE.sm, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{a.session}</b>
      <Chip tone={agentStateTone(a.state)}>{a.state.toUpperCase()}</Chip>
      {a.reported_state && a.reported_state !== a.state ? <span style={tiny}>source says “{a.reported_state}”</span> : null}
      {a.execution_state ? <span style={tiny}>execution: {a.execution_state}</span> : null}
      {a.agent ? <span style={tiny}>{a.agent}</span> : null}
    </div>
    <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>{a.task ?? 'UNKNOWN · task not stated'}</div>
    <div style={tiny}>
      {a.branch ? <span>branch {a.branch}</span> : <span>branch not stated</span>}
      {a.pr ? <span> · PR #{a.pr}</span> : null}
    </div>
    {a.blocker ? <div style={{ fontSize: TYPE.sm, color: toneVars('danger').color }}>blocked: {a.blocker}</div> : null}
    {a.next_action ? <div style={tiny}>next: {a.next_action}</div> : null}
    <div style={tiny}>{a.as_of ? asOfText(a.as_of) : 'as_of not stated'} · {a.source ?? 'source not stated'}</div>
  </div>
}

function CoordinationPanel({ c }: { c: CoordinationBlock }) {
  return <section data-testid="deploy-coordination" style={panel}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <h2 style={h2}>Agents and current work</h2>
      <ChipRow>
        <Chip tone="warning">{c.status}</Chip>
        {c.as_of ? <Chip tone="neutral">{asOfText(c.as_of)}</Chip> : null}
        {c.source ? <Chip tone="neutral">{c.source}</Chip> : null}
      </ChipRow>
    </div>
    {c.status === 'UNAVAILABLE' || !c.present
      ? <p role="status" style={{ ...muted, color: toneVars('warning').color, fontWeight: 700 }}>
          UNAVAILABLE{c.reason ? ` · ${c.reason}` : ''} — not empty, not idle: unknown.
        </p>
      : <>
        {c.status === 'PARTIAL' && c.reason ? <p style={{ ...muted, color: toneVars('warning').color }}>PARTIAL · {c.reason}</p> : null}
        {c.agents.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
              {c.agents.map(a => <AgentCard key={a.session} a={a} />)}
            </div>
          : <p style={muted}>No agent claim or worklog entries in the sources read.</p>}
      </>}
    <p style={tiny}>
      Read from the canonical claim board and worklogs when the response carries them; each card states its own
      source time and source. A missing source is UNAVAILABLE, never an empty team.
    </p>
  </section>
}

function FactLine({ label, text, tone }: { label: string; text: string; tone: Tone }) {
  return <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 2 }}>
    <span style={{ color: TOKENS.text[3] }}>{label}: </span>
    <span style={{ color: toneVars(tone).color, fontWeight: 600 }}>{text}</span>
  </div>
}

function WorkCell({ p, w }: { p: InFlightPr; w: WorkBlock }) {
  const f = rowFacts(p)
  return <>
    <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{f.owner}</div>
    <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>{f.task}</div>
    {w.present ? null : <div style={tiny}>work facts UNKNOWN · {w.reason}</div>}
  </>
}

function StatusCell({ p }: { p: InFlightPr }) {
  const f = rowFacts(p)
  const w = p.work
  return <>
    <ChipRow>
      <Chip tone={stateTone(p.merge_state)}>{p.merge_state}</Chip>
      <Chip tone={f.draft.tone}>{f.draft.text}</Chip>
      <Chip tone={f.publication.tone}>{f.publication.text}</Chip>
    </ChipRow>
    {p.has_operator_merge ? <div style={tiny}>operator-merge set — approved for the queue</div> : null}
    {p.why_held ? <div style={tiny}>{p.why_held}</div> : null}
    {p.mergeable === 'UNKNOWN' ? <div style={{ ...tiny, color: toneVars('warning').color }}>mergeability not stated (not auto-rebase)</div> : null}
    {w.local_head && w.published_head && w.local_head !== w.published_head
      ? <div style={tiny}>local {shortSha(w.local_head)} ≠ published {shortSha(w.published_head)}</div> : null}
  </>
}

function ChecksCell({ p }: { p: InFlightPr }) {
  const f = rowFacts(p)
  return <>
    <FactLine label="review" text={f.review.text} tone={f.review.tone} />
    <FactLine label="CI" text={f.ci.text} tone={f.ci.tone} />
    <div style={tiny}>bound head {p.head_sha ? shortSha(p.head_sha) : 'not stated'}</div>
    {p.work.review.head_sha && p.work.review.head_sha !== p.head_sha
      ? <div style={{ ...tiny, color: toneVars('danger').color }}>review head {shortSha(p.work.review.head_sha)} ≠ current</div> : null}
    {p.work.ci.head_sha && p.work.ci.head_sha !== p.head_sha
      ? <div style={{ ...tiny, color: toneVars('danger').color }}>CI head {shortSha(p.work.ci.head_sha)} ≠ current</div> : null}
  </>
}

function BlockerCell({ p }: { p: InFlightPr }) {
  const blockers = p.work.blockers
  return <>
    {blockers.length
      ? blockers.map((b, i) => <div key={i} style={{ fontSize: TYPE.sm, color: toneVars('danger').color }}>
          {b.text}{b.owner ? <span style={tiny}> · owner {b.owner}</span> : null}{b.as_of ? <span style={tiny}> · {asOfText(b.as_of)}</span> : null}
        </div>)
      : <div style={tiny}>{p.work.present ? 'no blocker stated' : 'blockers UNKNOWN — work facts absent'}</div>}
    <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 2 }}>
      next: <b style={{ color: TOKENS.text[0] }}>{nextActionFor(p)}</b>
    </div>
  </>
}

export default function DeployInFlightBoard() {
  const api = useApi<Wire>(IN_FLIGHT_PATH, 60_000)
  const [busy, setBusy] = useState<string | null>(null)   // "approve:2211" | "hold:2211" | "push:2211" | "refresh_hints"
  const [last, setLast] = useState<ActionOutcome | null>(null)
  const [overrideBudget, setOverrideBudget] = useState(false)
  const data = api.data
  const known = !!data && (KNOWN_SCHEMAS as readonly string[]).includes(String(data.schema ?? ''))
  const prs: InFlightPr[] | null = known && Array.isArray(data!.prs) ? data!.prs.map(p => normalizeRow(p)) : null
  const coordination = normalizeCoordination(data?.coordination)
  const unavailable = !known || data?.freshness === 'UNAVAILABLE' || (prs === null && !!api.error)
  const staleHint = api.stale || (known && data!.freshness === 'STALE')

  const post = async (body: Record<string, unknown>, key: string): Promise<void> => {
    if (busy) return
    setBusy(key)
    setLast(null)
    try {
      const r = await fetch(ACTION_PATH, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      let out: ActionOutcome | null = null
      try { out = await r.json() } catch { out = null }
      setLast(out ?? { ok: false, error: `HTTP ${r.status}, unreadable body` })
    } catch (e) {
      setLast({ ok: false, error: String(e) })
    } finally {
      setBusy(null)
      api.refetch()
    }
  }

  const approve = (p: InFlightPr) => post({ action: 'approve', pr_number: p.number, head_sha: p.head_sha }, `approve:${p.number}`)
  const hold = (p: InFlightPr) => post({ action: 'hold', pr_number: p.number, head_sha: p.head_sha }, `hold:${p.number}`)
  const push = (p: InFlightPr) => post({ action: 'push', branch: p.branch, head_sha: p.head_sha, override: overrideBudget }, `push:${p.number}`)
  const refreshHints = () => post({ action: 'refresh_hints' }, 'refresh_hints')

  // Unchanged authority: the actions' guards are the same as before; review/CI text never enables a button.
  const canApprove = (p: InFlightPr) => !p.is_draft && p.mergeable !== 'CONFLICTING' && !p.has_operator_merge
  const canHold = (p: InFlightPr) => p.has_operator_merge
  const canPush = (p: InFlightPr) => !p.is_draft && p.branch !== ''

  return <section data-testid="deploy-in-flight" style={{ display: 'grid', gap: 10 }}>
    <div style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={h2}>In flight · open PRs to main</h2>
        <ChipRow>
          {unavailable && !prs
            ? <Chip tone="warning">UNAVAILABLE</Chip>
            : api.loading && !data
              ? <Chip tone="neutral">Loading</Chip>
              : <Chip tone={staleHint ? 'warning' : 'neutral'}>{known && data!.freshness === 'UNAVAILABLE' ? 'UNAVAILABLE' : staleHint ? 'STALE' : data?.status ?? '—'}</Chip>}
          {known && data!.count != null ? <Chip tone="neutral">{data!.count} open</Chip> : null}
          {data?.generated_at ? <Chip tone="neutral">captured {asOfText(data.generated_at)}</Chip> : <Chip tone="warning">capture time not stated</Chip>}
        </ChipRow>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" data-testid="refresh-hints-button" onClick={refreshHints} disabled={busy !== null}
          style={btn('info', busy !== null)} title="Re-runs scripts/run_cio_hardening_ci.py --write-duration-hints (the self-contained duration-hints refresh).">
          Refresh hints
        </button>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
          <input type="checkbox" checked={overrideBudget} onChange={e => setOverrideBudget(e.target.checked)} />
          lift push budget (“override”)
        </label>
        {busy ? <Chip tone="info">working…</Chip> : null}
        {last ? <Chip tone={last.ok ? 'success' : 'danger'}>{last.ok ? (last.outcome ?? 'done') : (last.refusal ?? last.error ?? 'refused')}</Chip> : null}
      </div>

      {unavailable && !prs
        ? <p role="status" style={{ ...muted, color: toneVars('warning').color, fontWeight: 700 }}>
            UNAVAILABLE{data?.reason ? ` · ${data.reason}` : api.error ? ` · ${api.error}` : ''} — not empty, not healthy: unknown.
          </p>
        : null}
    </div>

    <CoordinationPanel c={coordination} />

    {prs !== null && (
      <section style={panel} data-testid="deploy-in-flight-rows">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <h2 style={h2}>Pull requests</h2>
          <span style={tiny}>every fact states its own source time; the frame time is the capture, not the fact</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="ops-evidence-table" aria-label="Open pull requests not yet live" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>PR</th><th style={th}>What it is</th><th style={th}>Owner · task</th><th style={th}>State</th>
                <th style={th}>Review · CI</th><th style={th}>Blocker · next</th><th style={th}>Updated</th><th style={th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {prs.map((p) => {
                const f = rowFacts(p)
                return <tr key={p.number} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                  <td data-label="PR" style={td}>
                    <a href={p.url} target="_blank" rel="noreferrer" style={{ color: TOKENS.primary }}>#{p.number}</a>
                    <div style={tiny}>{p.branch || 'branch not stated'}</div>
                    <div style={tiny}>{p.head_sha ? shortSha(p.head_sha) : 'head not stated'}</div>
                  </td>
                  <td data-label="What it is" style={td}><span style={{ overflowWrap: 'anywhere' }}>{p.title}</span></td>
                  <td data-label="Owner · task" style={td}><WorkCell p={p} w={p.work} /></td>
                  <td data-label="State" style={td}><StatusCell p={p} /></td>
                  <td data-label="Review · CI" style={td}><ChecksCell p={p} /></td>
                  <td data-label="Blocker · next" style={td}><BlockerCell p={p} /></td>
                  <td data-label="Updated" style={td}>
                    <div style={tiny}>{f.asOf ? asOfText(f.asOf) : 'source time not stated'}</div>
                    <div style={tiny}>{f.source ?? 'source not stated'}</div>
                  </td>
                  <td data-label="Actions" style={td}>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <button type="button" data-testid={`approve-${p.number}`} onClick={() => approve(p)}
                        disabled={busy !== null || !canApprove(p)} style={btn('success', busy !== null || !canApprove(p))}
                        title="Adds operator-merge (bound to this head SHA) so Mergify queues the PR.">
                        Approve
                      </button>
                      <button type="button" data-testid={`hold-${p.number}`} onClick={() => hold(p)}
                        disabled={busy !== null || !canHold(p)} style={btn('warning', busy !== null || !canHold(p))}
                        title="Removes operator-merge so Mergify will not queue the PR.">
                        Hold
                      </button>
                      <button type="button" data-testid={`push-${p.number}`} onClick={() => push(p)}
                        disabled={busy !== null || !canPush(p)} style={btn('info', busy !== null || !canPush(p))}
                        title="Issues a git-push guard grant bound to this branch + head SHA and fast-forward pushes it. Force-push stays refused.">
                        Push
                      </button>
                    </div>
                  </td>
                </tr>
              })}
              {!prs.length ? <tr><td colSpan={8} style={{ ...td, color: TOKENS.text[2] }}>No open PRs to main.</td></tr> : null}
            </tbody>
          </table>
        </div>
        <p style={muted}>
          Approve / Hold reuse the same operator-merge label the Telegram tap already sets; Push writes a bound git-push
          grant and fast-forwards (force stays refused). Every action is operator-session + same-origin CSRF protected and
          writes a durable receipt. Review and CI text is display only — it never enables an action. {data?.source ? `Source: ${data.source}.` : ''}
        </p>
      </section>
    )}
  </section>
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import DeskPage, { DeskGap, useDeskTab } from '../components/DeskPage'
import AmendmentReader from '../components/AmendmentReader'
import { GOVERNANCE, KIND_LABEL, useGovernance, waitingSince, type ApprovalItem, type ApprovalQueue } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'
import ResolvedActivations, { type QueueWithResolved } from '../components/approvals/ResolvedActivations'
import { deriveSurfaceState, surfaceGap, type SurfaceShape } from '../lib/surfaceState'
import { SurfaceGap, useReportSurfaceState } from '../components/SurfaceGap'

const tabs = [{ id: 'waiting', label: 'Waiting on you' }, { id: 'POLICY', label: 'Policy' }, { id: 'RELEASE', label: 'Releases' },
  { id: 'SPEND', label: 'Spending caps' }, { id: 'ACTIVATE', label: 'Activations' }, { id: 'DESIGN', label: 'Designs' },
  { id: 'CONFLICT', label: 'Conflicts' }, { id: 'FINANCIAL', label: 'Trade reviews' }, { id: 'history', label: 'Decision history' }]

/** W10 AI-proposed conflict rule: the server only emits this local, allow-listed destination. */
const isRuleProposal = (item: ApprovalItem) => item.source === 'conflict_rule_proposals' && !!item.governed_href?.startsWith('/conflicts/rules?proposal=')

export default function ApprovalsHub() {
  const { id } = useParams()
  if (id) return <AmendmentReader id={id} />
  return <Queue />
}

function Queue() {
  const [active] = useDeskTab(tabs)
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [active])
  const { data, error, refresh, loading } = useGovernance<ApprovalQueue>(`${GOVERNANCE}/approvals?offset=${offset}&kind=${active === 'waiting' || active === 'history' ? '' : active}`)
  // SurfaceState@v1 (BOARD row 36): the decisions line, the source row and the body banner all come from ONE state.
  // The old code derived the decisions line from `!data` while the banner came from `error`, which is how "Loading
  // the latest queue." ended up beside "Queue unavailable".
  const shape: SurfaceShape<ApprovalQueue> = {
    what: 'latest approval queue',
    gaps: d => (d.gaps ?? []).map(g => g.source),
    isEmpty: d => (d.items ?? []).length === 0 && (d.recent ?? []).length === 0,
  }
  const surface = deriveSurfaceState<ApprovalQueue>({ data, error, loading }, shape)
  useReportSurfaceState('Approvals page', surface)
  const surfaceText = surfaceGap(surface, shape)
  // The rendered payload: the state's own data, narrowed once, so nothing below can read a payload the contract
  // refused to hand us (an unreadable/malformed payload has already been turned into a banner by the time we get here).
  const q = surface.data
  const totalKnown = surface.totalKnown && q && q.pending_count !== null
  return <div className="approvals"><DeskPage title="Approvals Center" purpose="Everything waiting for your decision. Read the exact version, then decide."
    tabs={tabs} sources={[{ id: 'approvals', label: 'Approval queue', asOf: surface.data?.as_of,
      gap: surface.state === 'partial' ? 'Some approval sources are unavailable. The total is not yet known.' : undefined }]}
    decisionGap={totalKnown ? `${data!.pending_count} waiting for review.` : surfaceText ? `${surfaceText.title}. The total is not yet known.` : undefined}>
    {active => <div className="stack">
      {!surface.data && <SurfaceGap state={surface} shape={shape} onRetry={refresh} />}
      {surface.data && surface.state === 'partial' && <SurfaceGap state={surface} shape={shape} />}
      {q && <>
        {/* N4 (cc-deepseek-3): when the surface is partial the banner above already says a source did not answer and
            that the total is unknown; this block repeated the same fact in different words ("Some sources need
            attention … known items"). Two sentences for one fact is the contradiction class this page is being fixed
            for, so on partial only the per-source DETAILS remain, with no second headline. */}
        {(q.gaps ?? []).length > 0 && (surface.state === 'partial'
          ? <details><summary>Source details</summary><ul>{(q.gaps ?? []).map(gap => <li key={gap.source}>{gap.source.replace(/_/g, ' ')}: {gap.reason}</li>)}</ul></details>
          : <DeskGap title="Some sources need attention" reason={`${q.known_pending_count} known items. The full total is unavailable.`}>
              <details><summary>Source details</summary><ul>{(q.gaps ?? []).map(gap => <li key={gap.source}>{gap.source.replace(/_/g, ' ')}: {gap.reason}</li>)}</ul></details>
            </DeskGap>)}
        {active === 'history' ? <section className="panel"><h2>Decision history</h2>{q.recent.length ? q.recent.map((record, i) => <article key={i} className="rule">
          <strong>{record.decision.replace(/_/g, ' ')}</strong><p>{record.actor} · {new Date(record.at).toLocaleString()}</p>
          <details><summary>Exact version and comment</summary><code>{record.document_sha}</code><p>{record.comment}</p></details>
        </article>) : <p>No recorded decisions were returned.</p>}</section> : <div className="columns">
          <section className="panel" aria-label="Waiting approvals">
            {q.items.filter(item => active === 'waiting' || item.kind === active).map(item => <article className="queue-row" key={item.id}>
              <span className="badge">{isRuleProposal(item) ? 'AI rule proposal' : KIND_LABEL[item.kind] ?? item.kind}</span><div><h2>{item.title}</h2><p className="muted">{item.version || 'Exact document available in the reader'}</p></div>
              <span>{item.proposed_by ?? 'Proposer not recorded'}</span><span className="muted">{waitingSince(item.created_at)}</span>
              {isRuleProposal(item)
                // Rule proposals are decided only on the conflict rules page (single approval channel). Opening the
                // sheet from here marks the history entry so its ← Back returns to this queue.
                ? <Link className="primary" data-testid="approvals-rule-proposal-link" to={item.governed_href!} state={{ w9DetailOpened: true }}>Review proposal →</Link>
                : <Link className="primary" to={`/approvals/${encodeURIComponent(item.id)}`}>Read &amp; decide</Link>}
            </article>)}
            {!q.items.some(item => active === 'waiting' || item.kind === active) && <p>No items in this view. {q.complete ? '' : 'Some sources are still unavailable.'}</p>}
            <div className="toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
              <button disabled={offset + 50 >= q.filtered_count} onClick={() => setOffset(offset + 50)}>Next</button></div>
            {(active === 'ACTIVATE' || active === 'waiting') && <ResolvedActivations items={(data as QueueWithResolved).resolved} />}
          </section>
          <aside className="stack"><section className="panel"><h2>How a decision is recorded</h2><p>Your authenticated tailnet identity, the exact version you read, and the time are recorded together. Agents can propose and read; they cannot decide.</p></section>
            <section className="panel"><h2>Decided recently</h2>{q.recent.slice(0, 5).map((record, i) => <p key={i}>{record.decision.replace(/_/g, ' ')} · {new Date(record.at).toLocaleDateString()}</p>)}
              <Link className="primary" to="/approvals?tab=history">Full decision history</Link></section>
            <section className="panel"><h2>Notify me</h2><p className="muted">Approval notification delivery and its schedule have not been verified yet.</p></section>
            <section className="panel"><h2>Rulebook</h2><p>AGENTS.md as one document — every chapter and subsection agents follow. Seek, ask (Opus), or propose a new section.</p><Link className="primary" to="/policy">Open Rulebook</Link></section>
            <section className="panel"><h2>Conflicts</h2><p>How disagreements between data sources are decided (not AGENTS.md), and AI-proposed rules waiting for you.</p><Link className="primary" to="/conflicts/rules">How conflicts are decided →</Link></section>
          </aside>
        </div>}
      </>}
    </div>}
  </DeskPage></div>
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import DeskPage, { DeskGap, useDeskTab } from '../components/DeskPage'
import AmendmentReader from '../components/AmendmentReader'
import ReadableTime from '../components/ReadableTime'
import { GOVERNANCE, KIND_LABEL, approvalQueueView, useGovernance, waitingSince, type ApprovalItem, type ApprovalQueue } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'
import ResolvedActivations, { type QueueWithResolved } from '../components/approvals/ResolvedActivations'

const tabs = [{ id: 'waiting', label: 'Waiting on you' }, { id: 'POLICY', label: 'Policy' }, { id: 'RELEASE', label: 'Releases' },
  { id: 'SPEND', label: 'Spending caps' }, { id: 'ACTIVATE', label: 'Activations' }, { id: 'DESIGN', label: 'Designs' },
  { id: 'CONFLICT', label: 'Conflicts' }, { id: 'FINANCIAL', label: 'Trade reviews' }, { id: 'keep_retire', label: 'Keep / retire' }, { id: 'history', label: 'Decision history' }]

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
  const { data, error, refresh } = useGovernance<ApprovalQueue>(`${GOVERNANCE}/approvals?offset=${active === 'keep_retire' ? 0 : offset}&kind=${active === 'waiting' || active === 'history' || active === 'keep_retire' ? '' : active}`, 30000)
  const candidates = data?.keep_retire ?? []
  const view = data ? approvalQueueView(data) : null
  const filtered = view?.members.filter(item => active === 'waiting' || item.kind === active) ?? []
  const visible = view?.canonical ? filtered.slice(offset, offset + 50) : filtered
  const filteredCount = view?.canonical ? filtered.length : data?.filtered_count ?? 0
  return <div className="approvals"><DeskPage title="Approvals Center" purpose="Everything waiting for your decision. Read the exact version, then decide."
    tabs={tabs} sources={[{ id: 'approvals', label: 'Approval queue', asOf: data?.as_of, clockOnly: true,
      gap: view?.gaps.length ? 'Some approval sources need attention. The full total is not yet known.' : undefined }]}
    decisionGap={view?.pendingCount === null ? 'The total is unavailable until every source can be checked.' : view ? `${view.pendingCount} waiting for review.` : 'Loading the latest queue.'}>
    {active => <div className="stack">
      {error && <DeskGap title="Queue unavailable" reason={error}><button onClick={refresh}>Try again</button></DeskGap>}
      {!data && !error && <p role="status">Loading approvals…</p>}
      {data && <>
        {!!view?.gaps.length && <DeskGap title="Some sources need attention" reason={`${view.knownCount} known items. The full total is unavailable.`}>
          <details><summary>Source details</summary><ul>{view.gaps.map(gap => <li key={gap.source}>{gap.source.replace(/_/g, ' ')}: {gap.reason}</li>)}</ul></details>
        </DeskGap>}
        {active === 'waiting' && !!data.evidence_blockers?.length && <section className="panel" aria-label="Needs coordinator evidence">
          <h2>Needs coordinator evidence</h2>
          <p>These items need updated evidence from the coordinator before a decision can be requested.</p>
          {data.evidence_blockers.map(item => <ApprovalCard key={item.id} item={{ ...item, actionable: false }} sourceReady={false} />)}
        </section>}
        {active === 'history' ? <section className="panel"><h2>Decision history</h2>{data.recent.length ? data.recent.map((record, i) => <article key={i} className="rule">
          <strong>{record.decision.replace(/_/g, ' ')}</strong><p>{record.actor} · {new Date(record.at).toLocaleString()}</p>
          <details><summary>Exact version and comment</summary><code>{record.document_sha}</code><p>{record.comment}</p></details>
        </article>) : <p>No recorded decisions were returned.</p>}</section> : active === 'keep_retire' ? <section className="panel" aria-label="Keep or retire candidates">
          <h2>Keep / retire</h2><p>Older proposals remain available here for your decision. Moving them here does not retire or approve them.</p>
          {candidates.slice(offset, offset + 50).map(item => <ApprovalCard key={item.id} item={item} candidate sourceReady={!error && !view?.mismatch} />)}
          {!candidates.length && <p>No keep / retire candidates were returned. {data.complete ? '' : 'Some sources are still unavailable.'}</p>}
          <div className="toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
            <button disabled={offset + 50 >= candidates.length} onClick={() => setOffset(offset + 50)}>Next</button></div>
        </section> : <div className="columns">
          <section className="panel" aria-label="Waiting approvals">
            {visible.map(item => <ApprovalCard key={item.id} item={item} sourceReady={!error && !view?.mismatch} />)}
            {!visible.length && <p>No items in this view. {data.complete ? '' : 'Some sources are still unavailable.'}</p>}
            <div className="toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
              <button disabled={offset + 50 >= filteredCount} onClick={() => setOffset(offset + 50)}>Next</button></div>
            {(active === 'ACTIVATE' || active === 'waiting') && <ResolvedActivations items={(data as QueueWithResolved).resolved} />}
          </section>
          <aside className="stack"><section className="panel"><h2>How a decision is recorded</h2><p>Your authenticated tailnet identity, the exact version you read, and the time are recorded together. Agents can propose and read; they cannot decide.</p></section>
            <section className="panel"><h2>Decided recently</h2>{data.recent.slice(0, 5).map((record, i) => <p key={i}>{record.decision.replace(/_/g, ' ')} · {new Date(record.at).toLocaleDateString()}</p>)}
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

function ApprovalCard({ item, candidate = false, sourceReady = true }: { item: ApprovalItem; candidate?: boolean; sourceReady?: boolean }) {
  const canAct = sourceReady && item.actionable !== false && item.stale !== true
  const showCommand = canAct && item.actionable === true && !!item.source_as_of
  const prUrl = item.pr_url && /^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+$/.test(item.pr_url) ? item.pr_url : null
  const releaseHref = item.governed_href?.replace(/^\/releases(?=[/?#]|$)/, '/system/releases')
  const releaseAction = releaseHref && /^\/system\/releases\/?(?:[?#].*)?$/.test(releaseHref) ? releaseHref : null
  return <article className="queue-row">
    <span className="badge">{candidate ? 'Keep / retire' : isRuleProposal(item) ? 'AI rule proposal' : KIND_LABEL[item.kind] ?? item.kind}</span>
    <div style={{ minWidth: 0 }}><h2>{item.title}</h2><p className="muted">{item.version || 'Exact document available in the reader'}</p>
      {candidate && <p>{item.keep_retire_reason ?? 'Review whether this older proposal is still needed.'}</p>}
      {item.next_action && <p>{item.next_action}{item.next_actor ? ` · ${item.next_actor}` : ''}</p>}
      {item.source_sha && <p className="muted" style={{ overflowWrap: 'anywhere' }}>Exact head: <code>{item.source_sha}</code></p>}
      {item.source_gap && <p className="muted">Missing evidence: <code>{item.source_gap}</code></p>}
      {showCommand && item.policy_approval_command && <div><p>Approval line for this exact version:</p><code style={{ display: 'block', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.policy_approval_command}</code></div>}
      <p className="muted">Source: {item.source.replace(/_/g, ' ')}{item.source_as_of && <> · <ReadableTime value={item.source_as_of} /></>}</p>
      {prUrl && <a href={prUrl} target="_blank" rel="noreferrer">Open pull request #{item.pr}</a>}
    </div>
    <span>{item.proposed_by ?? 'Proposer not recorded'}</span><span className="muted">{waitingSince(item.created_at)}</span>
    {!canAct ? <span className="muted">Latest source verification is needed before deciding.</span> : isRuleProposal(item)
      ? <Link className="primary" data-testid="approvals-rule-proposal-link" to={item.governed_href!} state={{ w9DetailOpened: true }}>Review proposal →</Link>
      : releaseAction ? <Link className="primary" to={releaseAction}>Review release →</Link>
        : <Link className="primary" to={`/approvals/${encodeURIComponent(item.id)}`}>{candidate ? 'Read proposal' : 'Read & decide'}</Link>}
  </article>
}

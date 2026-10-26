import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { DeskGap } from './DeskPage'
import { GOVERNANCE, governanceRequest, governanceRequestId, useGovernance, type PendingPolicyVersion, type PolicyVersionDecision, type PolicyVersions as Versions } from '../lib/operatorApprovals'

/** Rulebook → AGENTS.md versions: the version in force, the PROPOSED versions waiting in open PRs, and the operator's
 *  "Approve version X". Approval records the same decision as the Approvals Center reader (every change read first)
 *  and names the exact token APPROVE_AGENTS_POLICY_<X_Y_Z> <pr> <head>; the coordinator relays it to the PR. */
export default function PolicyVersions() {
  const [params, setParams] = useSearchParams()
  const { data, error, refresh } = useGovernance<Versions>(`${GOVERNANCE}/policy/versions`)
  const openPr = Number(params.get('version') ?? 0) || 0
  const selected = data?.pending.find(p => p.pr === openPr) ?? null
  const open = (pr: number | null) => {
    const next = new URLSearchParams(params)
    if (pr) next.set('version', String(pr)); else next.delete('version')
    setParams(next, { replace: !pr })
  }
  return <section className="panel stack" aria-label="Policy versions" data-testid="policy-versions">
    <h2 style={{ margin: 0, fontSize: 16 }}>Policy versions</h2>
    {error && <DeskGap title="Versions unavailable" reason={error}><button onClick={refresh}>Try again</button></DeskGap>}
    {!data && !error && <p role="status">Loading versions…</p>}
    {data && <>
      <div className="version-current" data-testid="policy-version-current">
        <span className="muted">In force</span>
        <strong style={{ fontSize: 20 }}>{data.current.version ?? 'Unknown'}</strong>
        <span className={data.current.status === 'ACTIVE' ? 'badge success' : 'badge warning'}>{data.current.status ?? 'Unknown'}</span>
        <span className="muted">Effective {data.current.effective_date ?? 'unknown'}{data.current.supersedes ? ` · replaces ${data.current.supersedes}` : ''}</span>
        {!data.current.consistent && <p className="warning" role="alert">The version header and history disagree: {data.current.errors.join('; ')}</p>}
      </div>
      <h3 style={{ margin: '4px 0 0', fontSize: 14 }}>Waiting for your ratification {data.pending_count === null ? '(total unknown)' : `(${data.pending_count})`}</h3>
      {data.gaps.length > 0 && <p className="warning" role="status">Open pull requests could not all be checked, so more versions may be waiting. {data.gaps.map(g => g.reason).join('; ')}</p>}
      {data.pending.length === 0 && data.complete && <p>No proposed version is waiting.</p>}
      {data.pending.map(p => <button key={p.pr} className="version-row" data-testid="policy-version-row" onClick={() => open(p.pr)}>
        <strong>Version {p.version}</strong><span>PR #{p.pr} · {p.title}</span>
        <span className="muted">{p.decision ? p.decision.decision === 'APPROVE' ? 'Approved — awaiting relay' : p.decision.decision.replace(/_/g, ' ') : `${p.changes} changes to read`}</span>
      </button>)}
    </>}
    {data && selected && <VersionSheet item={selected} operator={data.operator} onClose={() => open(null)} onDone={refresh} />}
  </section>
}

function VersionSheet({ item, operator, onClose, onDone }: { item: PendingPolicyVersion; operator: boolean; onClose: () => void; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState<{ decision: PolicyVersionDecision; effect: string; relay: string } | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const phone = window.matchMedia('(max-width: 820px)').matches
  useEffect(() => { heading.current?.focus() }, [item.pr])
  const review = item.review
  const allRead = !!review && review.started && !review.expired && review.read >= review.total
  const decided = saved?.decision ?? item.decision
  const approve = async () => {
    if (busy || !item.token) return
    setBusy(true); setErr('')
    try {
      setSaved(await governanceRequest(`${GOVERNANCE}/policy/versions/approve`, { pr: item.pr, head_sha: item.head_sha, version: item.version, token: item.token, request_id: governanceRequestId() }))
      setConfirming(false); onDone()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return <section className="stack version-sheet" role={phone ? 'dialog' : 'region'} aria-modal={phone || undefined} aria-label={`Version ${item.version}`}
    data-testid="policy-version-sheet" onKeyDown={e => { if (e.key === 'Escape') onClose() }}>
    <button onClick={onClose}>← Back to Rulebook</button>
    <h2 ref={heading} tabIndex={-1} style={{ margin: 0 }}>Version {item.version}</h2>
    <p>{item.title}</p>
    <div className="decision-summary">
      <span>Pull request</span><strong>#{item.pr}</strong>
      <span>Status</span><strong>{item.status}</strong>
      <span>Change class</span><strong>{item.classification ?? 'Not stated'}</strong>
      <span>Touches §0, §2, §17?</span><strong>{item.sensitive_sections.length ? item.sensitive_sections.map(n => `§${n}`).join(', ') : 'No'}</strong>
      <span>Changes read</span><strong data-testid="policy-version-read">{review ? `${review.read} of ${review.total}${review.expired ? ' (session expired)' : ''}` : `0 of ${item.changes}`}</strong>
    </div>
    <details><summary>Exact head and token</summary><p className="muted">Head commit</p><code>{item.head_sha}</code><p className="muted">Ratification token</p><code data-testid="policy-version-token">{item.token ?? 'Unavailable: version or head cannot be bound'}</code></details>
    {item.earlier_head_decisions > 0 && <p className="muted">{item.earlier_head_decisions} earlier decision(s) named an older head and do not count for this one.</p>}
    {err && <p role="alert" className="warning">{err}</p>}
    {decided ? <div role="status" className="success" data-testid="policy-version-decided"><strong>{decided.decision === 'APPROVE' ? `Version ${item.version} approved` : decided.decision.replace(/_/g, ' ')}</strong>
      <p>{decided.actor} · {new Date(decided.at).toLocaleString()}</p>
      {decided.policy_token && <code>{decided.policy_token}</code>}
      {(saved?.relay ?? decided.relay) && <p className="muted">{saved?.relay ?? decided.relay}</p>}</div> : <>
      <Link className="primary" to={`/approvals/${encodeURIComponent(item.id)}`}>{allRead ? 'Re-read the changes' : 'Read the changes'}</Link>
      {!operator && <p className="muted">Only your authenticated operator session can approve. Agents can read this page.</p>}
      {!confirming
        ? <button className="primary" data-testid="policy-version-approve" disabled={!operator || !item.can_approve || !allRead || busy} onClick={() => setConfirming(true)}>
          Approve version {item.version}{!allRead ? ' — read every change first' : ''}</button>
        : <div className="stack confirm" data-testid="policy-version-confirm"><p><strong>Approve version {item.version}?</strong> This records your decision for PR #{item.pr} at head {item.head_sha.slice(0, 12)} with the token below. A new push to the PR makes it a different version.</p>
          <code>{item.token}</code>
          <button className="primary" disabled={busy} onClick={approve}>Yes, approve version {item.version}</button>
          <button disabled={busy} onClick={() => setConfirming(false)}>Cancel</button></div>}
      <p className="muted">Approval names this exact head. The Command Center cannot write to GitHub; the coordinator posts the token to the PR.</p>
    </>}
  </section>
}

import { TOKENS, RADIUS, TYPE } from '../../lib/designTokens'

export default function CioReviewLifecyclePanel({ review, assessment }: { review: any; assessment?: any }) {
  const r = review?.lifecycle || {}
  const clocks: [string, string | undefined][] = [
    ['Created', r.created_at || r.requested_at], ['Researching', r.researching_at || r.started_at],
    ['Answered', r.answered_at || r.completed_at], ['Conflict resolved', r.conflict_resolved_at],
  ]
  const resolved = r.status === 'CONFLICT_RESOLVED'
  const labels: Record<string, string> = { REQUESTED: 'Created', RESEARCHING: 'Researching', ANSWERED_PENDING_CIO: 'Answered — awaiting CIO', CONFLICT_RESOLVED: 'Conflict resolved', BLOCKED: 'Blocked', FAILED: 'Failed', MISSING: 'Missing' }
  return <section data-testid="cio-review-lifecycle" data-status={r.status || 'MISSING'} aria-label="CIO review lifecycle" style={{
    border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1],
    padding: 12, minWidth: 0, overflowWrap: 'anywhere', fontSize: TYPE.base, color: TOKENS.text[1],
  }}>
    <strong style={{ color: resolved ? TOKENS.success : TOKENS.warning }}>CIO review · {labels[r.status] || 'Not measured'}</strong>
    {resolved && r.new_stance && assessment?.stance && String(r.new_stance).toUpperCase() !== String(assessment.stance).toUpperCase() && <p data-testid="cio-review-assessment-drift" style={{ margin: '5px 0', color: TOKENS.warning }}>
      Saved CIO outcome {r.new_stance} differs from retained assessment {assessment.stance}. Assessment as of {assessment.as_of || 'not measured'}; CIO outcome verified {r.conflict_resolved_at || 'not measured'}. Owner reconciliation remains pending.
    </p>}
    <p style={{ margin: '5px 0' }}>{r.reason || 'No saved canonical CIO review outcome is available.'}</p>
    {review?.open && <p style={{ margin: '5px 0' }}>Queue position {review.queue_position ?? 'unknown'} · {review.next_run || 'next run not measured'}</p>}
    <div>CIO stance {r.old_stance || 'unknown'} → {r.new_stance || 'pending authoritative readback'}</div>
    {!resolved && <div style={{ color: TOKENS.text[2] }}>A research answer or classification receipt does not resolve a CIO conflict.</div>}
    <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(95px, auto) minmax(0, 1fr)', gap: '3px 10px', margin: '8px 0' }}>
      {clocks.map(([label, value]) => <div key={label} style={{ display: 'contents' }}><dt>{label}</dt><dd style={{ margin: 0 }}>{value || 'Not observed'}</dd></div>)}
    </dl>
    <div>Request {r.request_id || 'not linked'} · Research {r.research_id || 'not linked'}</div>
    {!!r.evidence_refs?.length && <div title="Saved CIO record evidence references">Evidence: {r.evidence_refs.join(' · ')}</div>}
    <small style={{ color: TOKENS.text[3] }}>Source: Saved CIO record</small>
  </section>
}

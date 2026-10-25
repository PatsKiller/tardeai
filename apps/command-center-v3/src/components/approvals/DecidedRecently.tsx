import { Link } from 'react-router-dom'
import { decidedAt, mergeRecent, outcomeTone, type RecentLike } from '../../lib/designApprovals'
import { useDesignQueue } from './DesignApprovals'
import '../../styles/designApprovals.css'

/** Board 19 "Decided recently": what was decided and its outcome, design decisions included (with titles). */
export default function DecidedRecently({ recent, labels }: { recent: RecentLike[]; labels: Record<string, string> }) {
  const { data, error } = useDesignQueue()
  const rows = mergeRecent(data?.decided_recently ?? [], recent, labels)
  return <section className="panel design-decided" aria-label="Decided recently" data-testid="decided-recently">
    <h2>Decided recently</h2>
    {error && <p className="muted">Design decisions unavailable: {error}</p>}
    {rows.length === 0 && !error && <p className="muted">{data ? 'No recorded decisions yet.' : 'Loading decisions…'}</p>}
    {rows.map(r => <div key={r.id} className="design-decided-row">
      <span>{r.title}<small>{decidedAt(r.at)}{r.recorded === 'recorded in handoff' ? ' · recorded in handoff' : ''}</small></span>
      <span className={`outcome-${outcomeTone(r.outcome)}`}>{r.outcome}</span>
    </div>)}
    <Link className="primary" to="/approvals?tab=history">Full decision history</Link>
  </section>
}

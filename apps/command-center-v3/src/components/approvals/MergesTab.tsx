// Approvals → Merges (Design approvals-pr-review/v001): the digest strip, one row per PR with its independent review's
// verdict, and the side panels. Rows open /approvals/pr:<N> (the review sheet). Read only.
import { Link } from 'react-router-dom'
import type { ApprovalQueue } from '../../lib/operatorApprovals'
import { checksText, classText, etTime, money, short, waited, type MergeRow, type MergesSummary } from '../../lib/prReview'
import '../../styles/prReview.css'

function Strip({ s }: { s: MergesSummary | null }) {
  if (!s) return <section className="panel" aria-label="Digest"><p role="status">Loading the review summary…</p></section>
  return <section className="panel prr-strip" aria-label="Digest" data-testid="merges-strip">
    <strong>Digest</strong>
    <span className="prr-muted">sent {s.digest.last_sent_at ? etTime(s.digest.last_sent_at) : 'not yet'} · next {s.digest.next_at ?? 'unknown'}</span>
    <span className="prr-pill success">{s.counts.ready} ready</span>
    {s.counts.held ? <span className="prr-pill danger">{s.counts.held} held</span> : null}
    {s.counts.hold ? <span className="prr-pill danger">{s.counts.hold} review says hold</span> : null}
    {s.counts.rereviewing ? <span className="prr-pill neutral">{s.counts.rereviewing} re-reviewing</span> : null}
    {s.counts.waiting_credit ? <span className="prr-pill warning">{s.counts.waiting_credit} waiting for credit</span> : null}
    {s.counts.cannot ? <span className="prr-pill danger">{s.counts.cannot} cannot review</span> : null}
    <p className="prr-muted">Each PR has an independent review by a model that did not write it. Approve here or tap "Approve all" in Telegram — both bind to the head shown.</p>
    {!s.store_approved ? <p className="prr-muted" data-testid="merges-store-pending"><strong>Review store not yet approved</strong> (STORE_APPROVAL_PENDING). The reviewer writes nothing until the operator approves the pr_reviews store.</p> : null}
    {s.store_approved && !s.decisions_store_approved ? <p className="prr-muted" data-testid="merges-decisions-pending"><strong>Decision store not yet approved.</strong> Reviews can be read; decisions stay off and Telegram "Approve all" is the working merge approval.</p> : null}
  </section>
}

export default function MergesTab({ queue, summary }: { queue: ApprovalQueue; summary: MergesSummary | null }) {
  const rows = queue.items.filter(i => i.kind === 'MERGE') as unknown as MergeRow[]
  return <div className="columns prr-tab" data-testid="merges-tab">
    <div className="stack">
      <Strip s={summary} />
      <section className="panel" aria-label="PRs waiting for a merge decision">
        <div className="prr-list">
          {rows.length ? <div className="prr-head" aria-hidden="true"><span>PR</span><span>Title · plain summary</span><span>Review verdict</span><span>Class · checks</span><span /></div> : null}
          {rows.map(r => <Link key={r.id} className="prr-row" to={`/approvals/${r.id}`} data-testid={`merge-row-${r.pr}`}>
            <span className="prr-num">#{r.pr}</span>
            <div className="prr-t"><h3>{r.title}</h3>{r.summary ? <p className="prr-muted">{r.summary.split(/(?<=\.)\s/)[0]}</p> : null}</div>
            <span className="prr-v"><span className={`prr-pill ${r.pill.tone}`}>{r.pill.label}</span></span>
            <span className="prr-meta prr-muted">{classText(r.classes)} · {checksText(r.checks, r.checks_green)} · head <span className="prr-mono">{short(r.head_sha, 7)}</span> · {waited(r.created_at)}</span>
            <span className="prr-go">Review →</span>
          </Link>)}
          {!rows.length ? <p>No PRs are waiting for a merge decision. {summary && !summary.store_approved ? 'The reviewer has not run yet.' : ''}</p> : null}
        </div>
      </section>
    </div>
    <aside className="stack">
      <section className="panel"><h2>How a merge approval works</h2><p className="prr-muted">An independent reviewer (never the author) reads the exact head.
        You read its review, then Approve, Hold or Ask. Approve adds <span className="prr-mono">operator-merge</span> for that head only; Mergify merges in the next ET window.
        A new push cancels the approval and starts a new review.</p></section>
      <section className="panel" data-testid="merges-spend"><h2>Review spend today</h2>
        {summary ? <><p><strong>{money(summary.spend.usd_today)}</strong> of {money(summary.spend.cap_usd)} review cap · Anthropic credit</p>
          <p className="prr-muted">{summary.spend.reviews_today} reviews · {summary.spend.questions_today} questions answered · {summary.models ? `${summary.models.normal} normal, ${summary.models.deep} held and shared-infra` : ''}</p></>
          : <p className="prr-muted">Loading…</p>}</section>
      <section className="panel"><h2>Held classes</h2><p className="prr-muted">Broker and orders, secrets, policy text, hooks and guard, merge and deploy tooling. Reviewed here, merged only by you on GitHub.</p></section>
    </aside>
  </div>
}

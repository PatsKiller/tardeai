import {createPortal} from 'react-dom'
import {Link} from 'react-router-dom'
import DeskPage, {DeskGap} from '../components/DeskPage'
import {MobileDetailSheet, useMobilePageDetail} from '../components/MobileDetailSheet'
import {useApi} from '../hooks/useApi'
import {claimHref, planFrom, plansFrom, prUrl, statusWord, stepSummary, type PlanRow, type PlansView} from '../lib/plansModel'
import '../styles/plans.css'

const INDEX = '/api/v2/plans'

function DetailBody({plan}: {plan: PlanRow}) {
  const pr = prUrl(plan)
  const claim = claimHref(plan)
  return (
    <div className="pl-detail">
      <p className="pl-status">{statusWord(plan.status)}</p>
      <p className="pl-meta">
        {plan.vendor ? `Registered by ${plan.vendor}` : 'Vendor unknown'}
        {plan.approved_at ? ` · approved ${plan.approved_at.slice(0, 10)}` : ''}
        {plan.updated_at ? ` · updated ${plan.updated_at.slice(0, 16).replace('T', ' ')}` : ''}
      </p>
      {plan.operator_quote && <blockquote className="pl-quote">“{plan.operator_quote}”</blockquote>}
      <p className="pl-steps-summary">{stepSummary(plan)}</p>
      {Array.isArray(plan.steps) && plan.steps.length > 0 && (
        <ul className="pl-steps">
          {plan.steps.map((s, i) => (
            <li key={`${i}-${s.text}`} className={s.done ? 'pl-step done' : 'pl-step'}>
              <span aria-hidden="true">{s.done ? '✓' : '·'}</span> {s.text}
            </li>
          ))}
        </ul>
      )}
      <p className="pl-links">
        {claim && <Link to={claim}>Claim {plan.claim}</Link>}
        {claim && pr ? ' · ' : ''}
        {pr && <a href={pr} target="_blank" rel="noreferrer">Pull request #{plan.pr}</a>}
        {!claim && !pr && <span>No claim or pull request yet.</span>}
        {plan.branch && <> · <code>{plan.branch}</code></>}
      </p>
      {plan.body && <pre className="pl-body">{plan.body}</pre>}
    </div>
  )
}

export default function PlansPage() {
  const index = useApi<PlansView>(INDEX, 30_000)
  const detail = useMobilePageDetail('plan')
  const selectedId = detail.id
  const one = useApi<PlansView>(selectedId ? `${INDEX}?id=${encodeURIComponent(selectedId)}` : INDEX, 0,
    {enabled: Boolean(selectedId)})
  const rows = plansFrom(index.data)
  const plan = selectedId ? planFrom(one.data) : null
  const waiting = rows.filter(r => r.status === 'approved').length
  const gap = index.error || (index.data && index.data.ok === false ? String(index.data.error || 'Plan store unreadable') : undefined)

  const sheet = plan ? (
    detail.mobile
      ? <MobileDetailSheet title={String(plan.title || plan.id)} onBack={detail.close}><DetailBody plan={plan} /></MobileDetailSheet>
      : createPortal(
          <aside className="pl-panel" role="dialog" aria-modal="false" aria-label={String(plan.title || plan.id)}
            onKeyDown={e => { if (e.key === 'Escape') detail.close() }}>
            <button type="button" className="pl-back" onClick={detail.close}>← Back</button>
            <h2>{plan.title || plan.id}</h2>
            <DetailBody plan={plan} />
          </aside>, document.body)
  ) : null

  return (
    <>
      <DeskPage
        title="Plans"
        purpose="Every approved plan on the server for every agent: who approved it, who picked it up, what is left. Claude Code registers a plan when you leave plan mode; Codex and Cursor use scripts/plan_registry.py."
        sources={[{id: 'plans', label: 'Plan store', gap}]}
        decisions={[]}
        decisionGap={waiting ? `${waiting} approved plan${waiting === 1 ? '' : 's'} nobody has picked up yet.` : 'Nothing approved and unclaimed right now.'}
      >
        <div className="pl-stack">
          <DeskGap title="Plan registry" reason={String(gap)} />
          {index.loading && <p className="pl-empty">Loading plans…</p>}
          {!index.loading && rows.length === 0 && !gap && <p className="pl-empty">No plans registered yet.</p>}
          <ul className="pl-list">
            {rows.map(row => (
              <li key={row.id}>
                <button type="button" className="pl-card" onClick={() => detail.open(row.id)}>
                  <span className="pl-card-title">{row.title || row.id}</span>
                  <span className="pl-card-line">
                    {statusWord(row.status)} · {row.vendor || 'unknown vendor'} · {stepSummary(row)}
                  </span>
                  <span className="pl-card-line pl-card-links">
                    {row.claim ? `claim ${row.claim}` : 'no claim'}
                    {row.pr ? ` · PR #${row.pr}` : ''}
                    {row.branch ? ` · ${row.branch}` : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </DeskPage>
      {sheet}
    </>
  )
}

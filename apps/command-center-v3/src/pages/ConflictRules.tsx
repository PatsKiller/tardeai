import {useEffect, useRef, useState, type ReactNode} from 'react'
import {createPortal} from 'react-dom'
import {Link} from 'react-router-dom'
import DeskPage, {DeskGap} from '../components/DeskPage'
import {MobileDetailSheet, useMobilePageDetail} from '../components/MobileDetailSheet'
import {useApi} from '../hooks/useApi'
import {conflictSource, conflictTime, conflictValue} from '../lib/watchConflictPresentation'
import {
  ACTION_WORDS, TIERS, approvalWords, awaitingAi, coverageWord, decisionBody, decisionError, fingerprint, isPending, liveCountRows, pct, pendingProposals,
  proposalCases, proposalModel, proposalResolutions, proposalTestCount, statusWords, unmatchedStatus,
  type DecisionAction, type MatrixRule, type ProposalCollection, type RuleProposal, type RulebookView, type UnmatchedExample,
} from '../lib/conflictRulesModel'
import '../styles/conflictRules.css'

const RULEBOOK = '/api/v3/conflicts/rulebook'
const PROPOSALS = '/api/v3/conflicts/proposals'

/** Full-screen on a phone (≤ 820 px), side panel on desktop; ← Back always closes. */
function DetailSheet({title, mobile, onBack, children}: {title: string; mobile: boolean; onBack: () => void; children: ReactNode}) {
  const panel = useRef<HTMLElement>(null)
  useEffect(() => { if (!mobile) panel.current?.querySelector<HTMLElement>('[data-detail-focus]')?.focus() }, [mobile, title])
  if (mobile) return <MobileDetailSheet title={title} onBack={onBack}><div className="conflict-rules">{children}</div></MobileDetailSheet>
  return createPortal(<aside ref={panel} role="dialog" aria-modal="false" aria-label={title} className="conflict-rules conflict-rules-panel"
    onKeyDown={event => { if (event.key === 'Escape') onBack() }}>
    <button type="button" className="cr-back" onClick={onBack}>← Back</button>
    {children}
  </aside>, document.body)
}

export default function ConflictRules() {
  const book = useApi<RulebookView>(RULEBOOK, 60_000)
  const proposals = useApi<ProposalCollection>(PROPOSALS, 60_000)
  const ruleDetail = useMobilePageDetail('rule')
  const proposalDetail = useMobilePageDetail('proposal')
  const view = book.data?.schema === 'ConflictRulebookView@v1' ? book.data : null
  const selectedRule = view?.rules.find(rule => rule.id === ruleDetail.id) ?? null
  const proposalList = proposals.data && Array.isArray(proposals.data.proposals) ? proposals.data : null
  const pending = pendingProposals(proposalList)
  const selectedProposal = proposalList?.proposals?.find(p => p.proposal_id === proposalDetail.id) ?? null
  const unmatchedRows = awaitingAi(proposalList)
  const decisionsEnabled = proposalList?.decisions_enabled === true

  return <div className="conflict-rules" data-testid="conflict-rules">
    <DeskPage title="Conflict rules" purpose="How the Command Center decides when two sources disagree: the binding resolution matrix, in plain words."
      sources={[
        {id: 'rulebook', label: 'Conflict rulebook', laneIds: ['conflict-resolver'], gap: view ? undefined : 'Rulebook not loaded yet.'},
        {id: 'ledger', label: 'Conflict ledger', asOf: view?.live.as_of ?? null, laneIds: ['conflict-resolver'],
          gap: view?.live.gap?.reason as string | undefined},
        {id: 'proposals', label: 'AI rule proposals', laneIds: ['conflict-rule-proposals'],
          gap: proposalList ? undefined : (proposals.error || 'AI rule proposals not available yet.')},
      ]}
      decisions={pending.map(proposal => ({id: proposal.proposal_id, title: `Proposed rule: ${proposal.summary || proposal.plain_rule || 'review the AI proposal'} →`,
        href: `/conflicts/rules?proposal=${encodeURIComponent(proposal.proposal_id)}`}))}
      decisionGap={pending.length ? `${pending.length} AI-proposed rule${pending.length === 1 ? '' : 's'} waiting for your approval.` : 'Nothing on this page needs a decision right now.'}>
      <div className="cr-stack">
        {(pending.length > 0 || unmatchedRows.length > 0) && <section className="cr-panel cr-attention" aria-labelledby="cr-proposals" data-testid="cr-proposals">
          <h2 id="cr-proposals">Proposed rules — awaiting your approval</h2>
          <p className="cr-muted">No existing rule matched these cases, so an AI drafted a rule and a resolution. Nothing changes until you approve.</p>
          {pending.length > 0 && !decisionsEnabled && <p className="warning" data-testid="cr-activation-pending">Approval activation pending: you can read every proposal; the decision buttons turn on when the proposal store is activated.</p>}
          {pending.map(proposal => {
            const cases = proposalCases(proposal, proposalList)
            const fixes = proposalResolutions(proposal)
            return <button type="button" key={proposal.proposal_id} className="cr-card" data-testid="cr-proposal-card" onClick={() => proposalDetail.open(proposal.proposal_id)}>
              <span className="cr-card-head"><strong>{proposal.summary || 'Unmatched case — summary not supplied'}</strong>
                <span className="cr-badge warning">{proposal.tier || 'Tier not supplied'}{proposal.never_auto ? ' · never automatic' : ''}</span></span>
              {cases.length > 0 && <span>Case: {cases.map(c => `${c.subject?.label || 'Subject not recorded'} — ${c.summary || 'summary not supplied'}`).join(' · ')}</span>}
              <span><b>Proposed rule:</b> {proposal.plain_rule || 'not supplied'}</span>
              <span><b>Proposed resolution:</b> {fixes.length ? fixes.join(' · ') : 'not supplied'}</span>
              <span className="cr-muted">{(proposal.risks || []).length} risk{(proposal.risks || []).length === 1 ? '' : 's'} · {proposalTestCount(proposal) ?? 'unknown'} test cases · {proposalModel(proposal)}</span>
              <span className="cr-link">Review and decide →</span>
            </button>
          })}
          {unmatchedRows.length > 0 && <>
            <h3>Open conflicts no rule matched</h3>
            <ul className="cr-list" data-testid="cr-unmatched">{unmatchedRows.map(row => <li key={row.signature}>
              <strong>{(row.examples || []).map(e => e.subject?.label).filter(Boolean).join(', ') || 'Subject not recorded'}</strong> — {row.summary || 'summary not supplied'}
              <div className="cr-badge warning">{unmatchedStatus(row)}</div>
            </li>)}</ul>
          </>}
        </section>}

        {book.error && !view && <DeskGap title="Conflict rules unavailable" reason={book.error}><button type="button" onClick={book.refetch}>Try again</button></DeskGap>}
        {!view && !book.error && <p role="status">Loading the rulebook…</p>}
        {view && <Body view={view} openRule={ruleDetail.open} proposalsAvailable={!!proposalList} proposalsError={proposals.error} effective={proposalList?.rulebook ?? null} />}
      </div>
    </DeskPage>

    {selectedRule && <DetailSheet title={`${selectedRule.id} · ${selectedRule.title}`} mobile={ruleDetail.mobile} onBack={ruleDetail.close}>
      <RuleDetail rule={selectedRule} thresholds={view?.thresholds ?? {}} />
    </DetailSheet>}
    {selectedProposal && <DetailSheet title="Proposed rule" mobile={proposalDetail.mobile} onBack={proposalDetail.close}>
      <ProposalDetail key={selectedProposal.proposal_id} proposal={selectedProposal} cases={proposalCases(selectedProposal, proposalList)} enabled={decisionsEnabled} onDecided={proposals.refetch} />
    </DetailSheet>}
  </div>
}

function Body({view, openRule, proposalsAvailable, proposalsError, effective}: {view: RulebookView; openRule: (id: string) => void; proposalsAvailable: boolean
  proposalsError: string | null; effective: ProposalCollection['rulebook']}) {
  const status = statusWords(view.rulebook)
  const live = liveCountRows(view.live.by_kind)
  return <>
    <section className={`cr-panel cr-banner ${status.tone}`} aria-label="Rulebook status" data-testid="cr-status">
      <strong>{status.headline}</strong>
      <span>{status.live}</span>
      <span data-testid="cr-approval">Approval: {approvalWords(view.rulebook.approval)}</span>
      <span>Matrix fingerprint <code>{fingerprint(view.rulebook.matrix_sha256)}</code> · {view.rulebook.matrix_check.verified === true ? 'matches the binding matrix file'
        : view.rulebook.matrix_check.verified === false ? 'does NOT match the matrix file on this host' : view.rulebook.matrix_check.reason || 'not checked'}</span>
      <span className="cr-muted">Version {view.rulebook.version ?? 'unknown'} · {view.coverage_summary.implemented} of {view.coverage_summary.total} rules implemented{view.coverage_summary.missing ? ` · ${view.coverage_summary.missing} missing` : ''}</span>
      {effective?.amendment_count ? <span data-testid="cr-amendments">Effective version {String(effective.version)} · {effective.amendment_count} approved amendment{effective.amendment_count === 1 ? '' : 's'}</span> : null}
      {!proposalsAvailable && <span className="cr-muted" data-testid="cr-proposals-gap">AI rule proposals: not available yet{proposalsError ? ` (${proposalsError})` : ''}.</span>}
      {view.text_gap && <span className="warning">{String(view.text_gap.reason)}</span>}
    </section>

    <section className="cr-panel" aria-labelledby="cr-live">
      <h2 id="cr-live">Open conflicts now</h2>
      {view.live.gap ? <p className="cr-muted" data-testid="cr-live-gap">Not measured: {String(view.live.gap.reason)}.</p>
        : <div className="cr-counts" data-testid="cr-live-counts">
          <div><span>All open</span><strong>{view.live.open_total ?? '—'}</strong></div>
          {live.map(row => <div key={row.kind}><span>{row.label}</span><strong>{row.count}</strong></div>)}
        </div>}
      <Link className="cr-link" to="/watch">See flagged names on Watch →</Link>
    </section>

    <section className="cr-panel" aria-labelledby="cr-tiers">
      <h2 id="cr-tiers">Who wins</h2>
      <p className="cr-muted">Top wins. T0–T2 are facts and gates, never “conflicts”.</p>
      <ol className="cr-tiers" data-testid="cr-tiers">{view.tiers.map(tier => <li key={tier.id}>
        <span className="cr-tier-id">{tier.id}</span>
        <div><strong>{tier.name}</strong><p>{tier.means}</p><p className="cr-muted">Example: {tier.example}</p>
          {tier.id === 'T4' && view.t4_order.length > 0 && <p className="cr-order">{view.t4_order.map(item => item.label).join(' › ')}</p>}</div>
      </li>)}</ol>
    </section>

    <section className="cr-panel" aria-labelledby="cr-rules">
      <h2 id="cr-rules">The rules</h2>
      <p className="cr-muted">Tap a rule for the exact matrix text and the code and tests that enforce it.</p>
      <div className="cr-grid">{view.rules.map(rule => {
        const cover = coverageWord(rule.coverage.status)
        return <button type="button" key={rule.id} className="cr-card" data-testid="cr-rule-card" data-rule={rule.id} onClick={() => openRule(rule.id)}>
          <span className="cr-card-head"><strong>{rule.id} · {rule.title}</strong><span className={`cr-badge ${cover.tone}`}>{cover.label}</span></span>
          <span>{rule.means}</span>
          <span className="cr-muted">Example: {rule.example}</span>
          <span><b>Clears when:</b> {rule.clears}</span>
          <span><b>Owner:</b> {rule.owner}</span>
        </button>
      })}</div>
    </section>

    <section className="cr-panel" aria-labelledby="cr-never">
      <h2 id="cr-never">Never automatic</h2>
      <p className="cr-muted">These always go to a person. The engine never resolves them on its own.</p>
      <ul className="cr-list" data-testid="cr-never">{view.never_auto.map(item => <li key={item.id}>{item.label || item.id.replace(/_/g, ' ')}</li>)}</ul>
    </section>

    <section className="cr-panel" aria-labelledby="cr-scale">
      <h2 id="cr-scale">Action scale</h2>
      <p className="cr-muted">{view.action_scale.text.rule}</p>
      {(['held', 'not_held'] as const).map(kind => <div key={kind} className="cr-scale" data-testid={`cr-scale-${kind}`}>
        <h3>{kind === 'held' ? 'You hold it' : 'You don’t hold it'}</h3>
        <ol aria-label={kind === 'held' ? 'Held action scale' : 'Not-held action scale'}>{view.action_scale[kind].map(step => <li key={step.step}>
          <span className="cr-step">{step.primary}</span>
          <details><summary>Also counts as this step</summary><span className="cr-muted">{step.labels.map(label => label.replace(/_/g, ' ')).join(' · ')}</span></details>
        </li>)}</ol>
        <p className="cr-muted">{view.action_scale.text[kind]}</p>
      </div>)}
    </section>

    <section className="cr-panel" aria-labelledby="cr-conc">
      <h2 id="cr-conc">Concentration limits</h2>
      {view.concentration.gap ? <p className="warning">{String(view.concentration.gap.reason)}</p> : <>
        <p className="cr-muted">From the Investment Policy Statement (one source). “Near limit” warns at {pct((view.concentration.near_limit_fraction ?? NaN) * 100)} of a limit; a breach blocks ADD.</p>
        <table className="cr-table" data-testid="cr-concentration"><thead><tr><th scope="col">Holding</th><th scope="col">Limit</th><th scope="col">Near</th></tr></thead>
          <tbody>{view.concentration.rows.map(row => <tr key={row.key}>
            <th scope="row">{row.label}{row.detection && <span className="cr-muted cr-block">{row.detection}</span>}</th>
            <td>{pct(row.limit_pct)}</td><td>{pct(row.near_limit_pct)}</td>
          </tr>)}</tbody></table>
        {view.concentration.midrange_note && <p className="cr-muted">{view.concentration.midrange_note}</p>}
        <p className="cr-muted">Approved {view.concentration.as_of || 'date not recorded'} · {view.concentration.approval_ref || 'approval not recorded'}</p>
      </>}
    </section>

    <section className="cr-panel" aria-labelledby="cr-life">
      <h2 id="cr-life">Lifecycle of a conflict</h2>
      <ol className="cr-life" data-testid="cr-lifecycle">{view.lifecycle.states.map(state => <li key={state.state}
        className={view.lifecycle.terminal_states.includes(state.state) ? 'terminal' : ''}>
        <strong>{state.state.replace(/_/g, ' ')}</strong><span>{state.means}</span><span className="cr-muted">Who acts: {state.who}</span>
      </li>)}</ol>
      <p className="cr-muted">{view.lifecycle.cadence_design}</p>
      <p data-testid="cr-last-run">{view.lifecycle.last_run
        ? `Last engine run: ${view.lifecycle.last_run.phase || 'phase not recorded'} · ${view.lifecycle.last_run.status || 'status not recorded'} · ${conflictTime(view.lifecycle.last_run.finished_at)}`
        : 'Last engine run: none recorded on this host yet.'}</p>
    </section>
  </>
}

function RuleDetail({rule, thresholds}: {rule: MatrixRule; thresholds: Record<string, unknown>}) {
  const cover = coverageWord(rule.coverage.status)
  const keys = (rule.limits_from || '').split(',').map(key => key.trim().split('.').pop() || '').filter(key => key in thresholds)
  return <div className="cr-detail" data-testid="cr-rule-detail">
    <h2 tabIndex={-1} data-detail-focus>{rule.id} · {rule.title}</h2>
    <span className={`cr-badge ${cover.tone}`} data-testid="cr-rule-status">{cover.label}</span>
    <p>{rule.means}</p>
    <p><b>Example:</b> {rule.example}</p>
    <p><b>What clears it:</b> {rule.clears}</p>
    <p><b>Owner:</b> {rule.owner}</p>
    <h3>Exact rule text (binding matrix)</h3>
    <blockquote className="cr-quote">{rule.exact_text}</blockquote>
    {rule.limits_from && <p className="cr-muted">Thresholds read from <code>{rule.limits_from}</code>
      {keys.map(key => <span key={key} className="cr-block">{key.replace(/_/g, ' ')}: <code>{JSON.stringify(thresholds[key])}</code></span>)}</p>}
    <h3>Implementing code</h3>
    <ul className="cr-list">{rule.coverage.code.map((ref, i) => <li key={i}>{ref.found ? '✓' : '✗ not found'} <code>{ref.path}</code></li>)}</ul>
    <h3>Tests</h3>
    <ul className="cr-list">{rule.coverage.tests.map((ref, i) => <li key={i}>{ref.found ? '✓' : '✗ not found'} <code>{ref.path}</code> · {ref.name.replace(/_/g, ' ')}</li>)}</ul>
    {rule.coverage.gap_note && <p className="warning">{rule.coverage.gap_note}</p>}
  </div>
}

type Step = {stage: 'choose'} | {stage: 'confirm'; action: DecisionAction} | {stage: 'sending'; action: DecisionAction}
  | {stage: 'done'; action: DecisionAction; state: string; amendment: string | null} | {stage: 'failed'; action: DecisionAction; error: string}

function ProposalDetail({proposal, cases, enabled, onDecided}: {proposal: RuleProposal; cases: UnmatchedExample[]; enabled: boolean; onDecided: () => void}) {
  const [step, setStep] = useState<Step>({stage: 'choose'})
  const [action, setAction] = useState<DecisionAction>('approve')
  const [reason, setReason] = useState('')
  const [edited, setEdited] = useState({plain_rule: proposal.plain_rule || '', tier: proposal.tier || ''})
  const [applyCase, setApplyCase] = useState(true)
  const [problem, setProblem] = useState('')
  const fixes = proposalResolutions(proposal)
  const check = (chosen: DecisionAction) => decisionBody(chosen, reason, proposal, edited, applyCase)
  const prepare = (chosen: DecisionAction) => {
    const checked = check(chosen)
    if (!checked.ok) { setProblem(checked.error); return }
    setProblem(''); setStep({stage: 'confirm', action: chosen})
  }
  const send = async (chosen: DecisionAction) => {
    const checked = check(chosen)
    if (!checked.ok) { setProblem(checked.error); setStep({stage: 'choose'}); return }
    setStep({stage: 'sending', action: chosen})
    try {
      const response = await fetch(`${PROPOSALS}/${encodeURIComponent(proposal.proposal_id)}/decision`, {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(checked.body)})
      type Envelope = {ok?: boolean; error?: string; reason?: string; proposal?: RuleProposal; amendment?: {amendment_id?: string} | null
        data?: {proposal?: RuleProposal; amendment?: {amendment_id?: string} | null}}
      let envelope: Envelope | null = null
      try { envelope = await response.json() } catch { /* non-JSON error page */ }
      if (!response.ok || envelope?.ok === false) { setStep({stage: 'failed', action: chosen, error: decisionError(response.status, envelope)}); return }
      const result = envelope?.proposal ? envelope : envelope?.data
      setStep({stage: 'done', action: chosen, state: String(result?.proposal?.status || 'recorded'), amendment: result?.amendment?.amendment_id || null})
      onDecided()
    } catch (err) {
      setStep({stage: 'failed', action: chosen, error: (err as Error).message || 'network error'})
    }
  }
  return <div className="cr-detail" data-testid="cr-proposal-detail">
    <h2 tabIndex={-1} data-detail-focus>{proposal.summary || 'Unmatched case — summary not supplied'}</h2>
    <span className="cr-badge warning">{proposal.tier || 'Tier not supplied'}{proposal.never_auto ? ' · never automatic' : ''}</span>
    {proposal.never_auto && proposal.never_auto_implications && <p className="warning">{proposal.never_auto_implications}</p>}
    <h3>What no rule matched</h3>
    {cases.length ? <ul className="cr-list">{cases.map(c => <li key={c.key}>
      <strong>{c.subject?.label || 'Subject not recorded'}</strong> — {c.summary || 'summary not supplied'}
      {(c.sides || []).map((side, i) => <span key={i} className="cr-block cr-muted">{conflictSource(side)}: {conflictValue(side.value)} · {conflictTime(side.as_of)}</span>)}
    </li>)}</ul> : <p className="cr-muted">The example cases were not supplied.</p>}
    <h3>Proposed rule</h3>
    <blockquote className="cr-quote">{proposal.plain_rule || 'Rule text not supplied'}</blockquote>
    <h3>Proposed resolution for the current case</h3>
    {fixes.length ? <ul className="cr-list">{fixes.map((fix, i) => <li key={i}>{fix}</li>)}</ul> : <p className="cr-muted">Not supplied.</p>}
    <h3>Risks</h3>
    {(proposal.risks || []).length ? <ul className="cr-list">{(proposal.risks || []).map((risk, i) => <li key={i}>{risk}</li>)}</ul> : <p className="cr-muted">No risks were listed.</p>}
    <details><summary>{proposalTestCount(proposal) ?? 'Unknown number of'} test cases</summary>
      <pre className="cr-pre">{JSON.stringify(proposal.test_cases ?? [], null, 2)}</pre></details>
    <p className="cr-muted">Drafted by {proposalModel(proposal)} · {conflictTime(proposal.created_at)}</p>

    {step.stage === 'done' ? <p role="status" className="cr-result success" data-testid="cr-decision-result">
      You {ACTION_WORDS[step.action].done} this rule. Recorded state: {step.state.replace(/_/g, ' ')}{step.amendment ? ` · rulebook amendment ${step.amendment}` : ''}.
      {step.action !== 'reject' && ' The next conflict-engine run re-evaluates the cases under it.'}</p>
    : step.stage === 'failed' ? <div role="alert" className="cr-result danger" data-testid="cr-decision-result">
      <p>Your decision was not recorded: {step.error}.</p><button type="button" onClick={() => setStep({stage: 'choose'})}>Try again</button></div>
    : !isPending(proposal) ? <p className="cr-muted">This proposal is {String(proposal.status || 'not pending').toLowerCase()}; no decision is needed.</p>
    : step.stage === 'confirm' || step.stage === 'sending' ? <div className="cr-confirm" data-testid="cr-confirm">
      <p><b>{ACTION_WORDS[step.action].verb}?</b> Your tailnet identity, this reason and the time are recorded. No order, size or stop is changed.</p>
      <p className="cr-muted">Reason: {reason.trim()}{step.action !== 'reject' ? ` · ${applyCase ? 'also applies' : 'does not apply'} the proposed resolution to the current case` : ''}</p>
      <button type="button" className="cr-primary" disabled={step.stage === 'sending'} onClick={() => send(step.action)}>{step.stage === 'sending' ? 'Recording…' : ACTION_WORDS[step.action].confirm}</button>
      <button type="button" disabled={step.stage === 'sending'} onClick={() => setStep({stage: 'choose'})}>Go back</button>
    </div>
    : <div className="cr-decide">
      <h3>Your decision</h3>
      {!enabled && <p className="warning" data-testid="cr-decisions-disabled">Approval activation pending — decisions cannot be recorded yet.</p>}
      <div className="cr-choice" role="radiogroup" aria-label="Decision">{(['approve', 'edit-and-approve', 'reject'] as const).map(choice => <button type="button" key={choice}
        role="radio" aria-checked={action === choice} disabled={!enabled} onClick={() => { setAction(choice); setProblem('') }}>{ACTION_WORDS[choice].verb}</button>)}</div>
      {action === 'edit-and-approve' && <>
        <label>Edited rule text<textarea aria-label="Edited rule text" value={edited.plain_rule} onChange={event => setEdited({...edited, plain_rule: event.target.value})} /></label>
        <label>Tier<select aria-label="Edited tier" value={edited.tier} onChange={event => setEdited({...edited, tier: event.target.value})}>
          {!TIERS.includes(edited.tier as never) && <option value={edited.tier}>{edited.tier || 'not supplied'}</option>}
          {TIERS.map(tier => <option key={tier} value={tier}>{tier}</option>)}</select></label>
      </>}
      {action !== 'reject' && <label className="cr-check"><input type="checkbox" checked={applyCase} disabled={!enabled} onChange={event => setApplyCase(event.target.checked)} />
        Also record the proposed resolution for the current case</label>}
      <label>Reason (recorded with your decision)<textarea aria-label="Decision reason" value={reason} disabled={!enabled} onChange={event => setReason(event.target.value)} /></label>
      {problem && <p role="alert" className="danger">{problem}</p>}
      <button type="button" className="cr-primary" disabled={!enabled} onClick={() => prepare(action)}>{ACTION_WORDS[action].verb}…</button>
    </div>}
  </div>
}

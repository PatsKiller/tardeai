import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import DeskPage, { DeskGap } from '../components/DeskPage'
import { GOVERNANCE, askAboutRule, governanceRequest, useGovernance, type Policy } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'

export default function PolicyHub() {
  const [params, setParams] = useSearchParams()
  const section = params.get('section') ?? ''
  const offset = Math.max(0, Number(params.get('offset') ?? 0) || 0)
  const { data, error, refresh } = useGovernance<Policy>(`${GOVERNANCE}/policy?section=${encodeURIComponent(section)}&offset=${offset}`)
  const selected = data?.rules.find(rule => rule.id === params.get('rule')) ?? null
  const position = params.get('respond') ?? ''
  const [comment, setComment] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const responseInput = useRef<HTMLTextAreaElement>(null)
  const noticeElement = useRef<HTMLParagraphElement>(null)
  const responseNotice = useRef<HTMLParagraphElement>(null)
  const phone = window.matchMedia('(max-width: 820px)').matches
  const navigate = useNavigate()
  useEffect(() => { if (selected) responseInput.current?.focus() }, [selected?.id, position])
  useEffect(() => { if (notice) (selected ? responseNotice.current : noticeElement.current)?.scrollIntoView({ block: 'nearest' }) }, [notice, selected?.id])
  const closeResponse = () => { const next = new URLSearchParams(params); next.delete('rule'); next.delete('respond'); setParams(next, { replace: true }) }
  const chooseSection = (value: string, page = 0) => {
    const next = new URLSearchParams(params); next.set('section', value); next.set('offset', String(page)); setParams(next)
  }
  const feedback = async () => {
    if (!data || !selected || busy) return
    setBusy(true); setNotice('')
    try {
      if (position === 'QUESTION') {
        await governanceRequest(`${GOVERNANCE}/policy/feedback`, { position, comment, rule_id: selected.id, document_sha: data.document_sha })
        const thread = await askAboutRule(comment, selected.section, selected.text, data.document_sha, data.source_sha)
        navigate(thread ? `/cio/questions/${encodeURIComponent(thread)}` : '/cio/questions')
      } else {
        await governanceRequest(`${GOVERNANCE}/policy/feedback`, { position, comment, rule_id: selected.id, document_sha: data.document_sha })
        setNotice(position === 'DISAGREE' ? 'Your proposed change is now in Approvals.' : 'Your agreement is recorded.'); closeResponse(); refresh()
      }
    } catch (err) { setNotice((err as Error).message) } finally { setBusy(false) }
  }
  return <div className="approvals"><DeskPage title="Rulebook" purpose="Every rule, what it means, and the evidence that it is enforced."
    sources={[{ id: 'policy', label: 'Committed policy', gap: 'Enforcement evidence is measured separately from the document.' }]}
    decisionGap="Questions go to the CIO. Disagreements propose a change for review.">
    {error && <DeskGap title="Rulebook unavailable" reason={error}><button onClick={refresh}>Try again</button></DeskGap>}
    {notice && !selected && <p ref={noticeElement} role="status" className="panel">{notice}</p>}
    {!data && !error && <p role="status">Loading rules…</p>}
    {data && <>
      <div className="counts">{Object.entries(data.counts).map(([name, count]) => <div key={name} className="panel"><span>{name}</span><strong>{count}</strong></div>)}</div>
      <p className="muted">Written-only means no verified evidence is attached to this exact version. A test name alone does not prove enforcement.</p>
      <div className="policy-grid">
        <nav className="panel stack" aria-label="Rulebook sections"><label>Section<select aria-label="Rulebook section" value={section} onChange={event => chooseSection(event.target.value)} style={{ width: '100%' }}><option value="">All sections</option>{data.sections.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <details><summary>Document version</summary><code>{data.source_sha}</code></details><Link className="primary" to="/approvals">Open approvals</Link><Link className="primary" to="/conflicts/rules">Conflict rules →</Link></nav>
        <article aria-label="Policy rules">{data.rules.map(rule => <section key={rule.id} className="rule panel">
          <h2 style={{ fontSize: 14 }}>{rule.section}</h2><p className="rule-text">{rule.text}</p>
          <details><summary>ⓘ In plain words</summary><p>{rule.plain ?? 'A plain-language explanation has not been reviewed for this rule yet.'}</p></details>
          <span className="badge">{rule.status}</span><p className="muted">{rule.reason}</p>
          {Object.keys(rule.evidence).length > 0 && <details><summary>Enforcement evidence</summary><pre>{JSON.stringify(rule.evidence, null, 2)}</pre></details>}
          <div className="rule-actions">{[['AGREE', 'Agree'], ['QUESTION', 'Question'], ['DISAGREE', 'Disagree → propose change']].map(([value, label]) => <button key={value} onClick={() => { const next = new URLSearchParams(params); next.set('rule', rule.id); next.set('respond', value); setParams(next); setComment(''); setNotice('') }}>{label}</button>)}</div>
          {selected?.id === rule.id && <section className="stack rule-response-sheet" role={phone ? 'dialog' : 'region'} aria-modal={phone || undefined} aria-label="Rule response" onKeyDown={event => {
            if (event.key === 'Escape') closeResponse()
            if (!phone || event.key !== 'Tab') return
            const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),textarea,input,a[href]')]
            const first = controls[0], last = controls[controls.length - 1]
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
            if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
          }}><button onClick={closeResponse}>← Back to Rulebook</button><h2>{rule.section}</h2><p className="rule-text">{rule.text}</p><label>{position === 'QUESTION' ? 'Your question' : position === 'DISAGREE' ? 'Proposed change and reason' : 'Optional comment'}<textarea ref={responseInput} aria-label="Rule response comment" value={comment} onChange={event => setComment(event.target.value)} /></label>
            {notice && <p ref={responseNotice} role="alert">{notice}</p>}
            <button className="primary" disabled={busy || (position !== 'AGREE' && !comment.trim())} onClick={feedback}>{position === 'QUESTION' ? 'Ask the CIO with this rule' : position === 'DISAGREE' ? 'Propose change in Approvals' : 'Record agreement'}</button><button onClick={closeResponse}>Cancel</button></section>}
        </section>)}
          <div className="toolbar"><button disabled={!offset} onClick={() => chooseSection(section, Math.max(0, offset - 40))}>Previous rules</button><button disabled={offset + 40 >= data.section_total} onClick={() => chooseSection(section, offset + 40)}>Next rules</button></div>
        </article>
        <aside className="stack"><section className="panel"><h2>Enforcement audit</h2><p>Weekly on Sunday at 20:00 and after an amendment. Mechanical checks map rules to tests and runtime checks; a governed reviewer can propose findings.</p>
          <p className="warning">Last audit: {data.audit.last_audit ?? 'Not measured'}</p><p className="muted">Findings go to Approvals for review. Changes are never applied automatically.</p><Link className="primary" to="/system/ops-controls?tab=jobs">Review audit job</Link></section>
          {data.audit.scope && <section className="panel"><h2>Audit coverage</h2><p>{data.audit.scope}</p><p>Mapped {data.audit.mapped_count ?? 'unknown'} · Unmapped {data.audit.unmapped_count ?? 'unknown'}</p></section>}
          {!!data.audit.findings?.length && <section className="panel"><h2>Latest findings</h2>{data.audit.findings.slice(0, 5).map((finding, index) => <p key={index}>{finding.title}</p>)}<Link className="primary" to="/approvals">Review findings in Approvals</Link></section>}
          <section className="panel"><h2>Your recent responses</h2><p>Agreed {data.positions.filter(p => p.position === 'AGREE').length} · Questions {data.positions.filter(p => p.position === 'QUESTION').length} · Proposed changes {data.positions.filter(p => p.position === 'DISAGREE').length}</p></section></aside>
      </div>
    </>}
  </DeskPage></div>
}

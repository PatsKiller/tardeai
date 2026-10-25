import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import DeskPage, { DeskGap } from './DeskPage'
import { GOVERNANCE, askAboutRule, governanceRequest, governanceRequestId, useGovernance, type ApprovalItem, type Change, type Decision } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'

type Mode = 'changes' | 'whole' | 'side'

function ChangeBlock({ change, review, sha, itemId, isRead, onRead, onFailure }: { change: Change; review: string; sha: string; itemId: string; isRead: boolean; onRead: (id: string) => void; onFailure: (message: string) => void }) {
  const element = useRef<HTMLDivElement>(null)
  const callbacks = useRef({ onRead, onFailure })
  callbacks.current = { onRead, onFailure }
  useEffect(() => {
    if (!review || !element.current || isRead) return
    let timer: ReturnType<typeof setTimeout> | undefined, visible = false, completed = false, stopped = false
    const endpoint = `${GOVERNANCE}/approvals/${encodeURIComponent(itemId)}/read`
    const mark = (phase: string) => governanceRequest(endpoint, { review_id: review, document_sha: sha, change_id: change.id, phase })
    const leave = () => {
      visible = false; clearTimeout(timer)
      if (!completed) void mark('leave').catch(() => {})
    }
    const observer = new IntersectionObserver(entries => {
      if (completed) return
      const isVisible = entries[0].intersectionRatio >= .98 && !document.hidden
      if (!isVisible && visible) { leave(); return }
      if (!isVisible || visible) return
      visible = true
      void mark('enter').then(() => {
        if (!visible || stopped) return
        timer = setTimeout(() => {
          if (!visible || stopped || document.hidden) return
          void mark('read').then(() => {
            if (stopped || !visible) return
            completed = true; callbacks.current.onRead(change.id)
          }).catch(error => callbacks.current.onFailure(error.message))
        }, 3050)
      }).catch(error => callbacks.current.onFailure(error.message))
    }, { threshold: [0, .98, 1] })
    observer.observe(element.current)
    const visibility = () => {
      if (document.hidden && visible) leave()
      else if (!document.hidden && !completed && element.current) { observer.unobserve(element.current); observer.observe(element.current) }
    }
    document.addEventListener('visibilitychange', visibility)
    return () => { stopped = true; clearTimeout(timer); observer.disconnect(); document.removeEventListener('visibilitychange', visibility); if (visible && !completed) leave() }
  }, [review, sha, change.id, itemId, isRead])
  return <div id={change.id} data-change-id={change.id} className={`change ${change.kind === 'removed' ? 'removed' : ''}`}>
    <div ref={element} data-read-target={change.id}><h3>{isRead ? '✓ Read' : change.kind === 'removed' ? 'Removed wording' : 'Added wording'} · {change.section}</h3>
      <p className="rule-text">{change.after || change.before}</p></div>
    <p className="muted">In plain words: {change.plain ?? 'The author has not supplied an explanation yet.'}</p>
    <p className="muted">Why: {change.reason ?? 'A reason has not been attached to this change.'}</p>
  </div>
}

export default function AmendmentReader({ id }: { id: string }) {
  const { data: item, error: loadError, refresh } = useGovernance<ApprovalItem>(`${GOVERNANCE}/approvals/${encodeURIComponent(id)}`)
  const [mode, setMode] = useState<Mode>('changes')
  const [search, setSearch] = useState('')
  const [review, setReview] = useState('')
  const [read, setRead] = useState<Set<string>>(new Set())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [comment, setComment] = useState('')
  const [question, setQuestion] = useState('')
  const [saved, setSaved] = useState<Decision | null>(null)
  const [selection, setSelection] = useState('')
  const title = useRef<HTMLHeadingElement>(null)
  const result = useRef<HTMLDivElement>(null)
  const article = useRef<HTMLElement>(null)
  const navigate = useNavigate()
  const doc = item?.document
  useEffect(() => { setReview(''); setRead(new Set()); setSaved(null); setError('') }, [doc?.document_sha])
  useEffect(() => { title.current?.focus() }, [item?.id])
  useEffect(() => { if (saved || error) result.current?.scrollIntoView({ block: 'nearest' }) }, [saved, error])
  useEffect(() => {
    const captureSelection = () => {
      const selected = window.getSelection()
      if (selected?.anchorNode && selected.focusNode && article.current?.contains(selected.anchorNode) && article.current.contains(selected.focusNode)) {
        const wording = selected.toString().trim()
        if (wording) setSelection(wording.slice(0, 1500))
      }
    }
    // selectionchange also covers a phone's long-press selection, which need not emit mouseup.
    document.addEventListener('selectionchange', captureSelection)
    return () => document.removeEventListener('selectionchange', captureSelection)
  }, [id])
  const onRead = useCallback((key: string) => setRead(previous => new Set([...previous, key])), [])
  const record = async (decision: string) => {
    if (!doc || busy) return
    setBusy(true); setError('')
    try {
      setSaved(await governanceRequest<Decision>(`${GOVERNANCE}/approvals/${encodeURIComponent(id)}/decide`, {
        decision, review_id: review, document_sha: doc.document_sha, request_id: governanceRequestId(),
        comment: selection ? `Selected wording: ${selection}\n\n${comment}` : comment,
      }))
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const begin = async () => {
    if (!doc) return
    setBusy(true); setError('')
    try { const started = await governanceRequest<{ review_id: string }>(`${GOVERNANCE}/approvals/${encodeURIComponent(id)}/open`, { document_sha: doc.document_sha }); setReview(started.review_id) }
    catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const ask = async () => {
    if (!doc || !question.trim()) return
    setBusy(true); setError('')
    try {
      const attached = selection || doc.changes.map(c => `${c.section}\n${c.after || c.before}`).join('\n').slice(0, 18000)
      const thread = await askAboutRule(question, doc.changes[0]?.section ?? 'Document', attached, doc.document_sha, doc.source_sha)
      navigate(thread ? `/cio/questions/${encodeURIComponent(thread)}` : '/cio/questions')
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const allRead = !!doc && doc.changes.every(c => read.has(c.id))
  const changes = doc?.changes.filter(c => !search || `${c.section} ${c.before} ${c.after}`.toLowerCase().includes(search.toLowerCase())) ?? []
  const block = (change: Change) => <ChangeBlock key={change.id} change={change} review={review} sha={doc!.document_sha} itemId={id} isRead={read.has(change.id)} onRead={onRead} onFailure={setError} />
  const blocks = <>{changes.map(block)}</>
  const highlightedWhole = () => {
    if (!doc) return null
    let cursor = 0
    const parts = []
    const additions = doc.changes.filter(c => c.after && typeof c.after_offset === 'number').sort((a, b) => a.after_offset! - b.after_offset!)
    for (const change of additions) {
      const offset = change.after_offset!
      parts.push(<pre key={`text-${cursor}`}>{doc.text.slice(cursor, offset)}</pre>, block(change))
      cursor = offset + change.after.length
    }
    parts.push(<pre key={`text-${cursor}`}>{doc.text.slice(cursor)}</pre>)
    return <>{parts}{doc.changes.some(c => c.before) && <><h2>Removed wording</h2>{doc.changes.filter(c => c.before).map(block)}</>}</>
  }
  return <div className="approvals"><Link className="primary" to="/approvals">← Back to approvals</Link>
    <h1 ref={title} tabIndex={-1} style={{ margin: '16px 0', fontSize: 22 }}>{item?.title ?? 'Read & decide'}</h1>
    <DeskPage title="Document reader" purpose="Read each highlighted change for three seconds. Your decision will name this exact version."
      sources={[{ id: 'document', label: 'Exact document', gap: 'A committed document does not have a scheduled writer clock.' }]} decisionGap="Approval waits until every change has been read.">
      {loadError && <DeskGap title="Review needs attention" reason={loadError}><button onClick={refresh}>Reload document</button></DeskGap>}
      {!item && !loadError && <p role="status">Loading this document…</p>}
      {doc && <>
        <div className="toolbar" aria-label="Reader views"><button aria-pressed={mode === 'changes'} onClick={() => setMode('changes')}>Changes only</button>
          <button aria-pressed={mode === 'whole'} onClick={() => setMode('whole')}>Whole document, highlighted</button>
          <button aria-pressed={mode === 'side'} onClick={() => setMode('side')}>Side by side</button>
          <label>Search changes <input aria-label="Search changes" value={search} onChange={event => setSearch(event.target.value)} /></label>
        </div>
        <div className="reader-grid">
          <nav className="panel toc" aria-label="Document sections">{[...new Set(doc.changes.map(c => c.section))].map(section => <a href={`#${doc.changes.find(c => c.section === section)!.id}`} key={section}>● {section}</a>)}</nav>
          <article ref={article} className="panel" aria-label="Document wording">
            {!review && <button className="primary" disabled={busy} onClick={begin}>Start reading</button>}
            <p className="muted">Each change is marked read after its complete wording has stayed on screen for three seconds.</p>
            {mode === 'changes' && blocks}
            {mode === 'whole' && <><h2>Whole document, highlighted</h2>{highlightedWhole()}</>}
            {mode === 'side' && <><div className="side-by-side"><section><h2>Before</h2><pre>{doc.base_text || 'No earlier wording was supplied.'}</pre></section><section><h2>Proposed</h2><pre>{doc.text}</pre></section></div><h2>Changes to read</h2>{blocks}</>}
            {!changes.length && <p>No highlighted changes match this view.</p>}
          </article>
          <aside className="stack">
            <section className="panel"><h2>Before you decide</h2><div className="decision-summary"><span>Changes read</span><strong aria-live="polite">{read.size} of {doc.changes.length}</strong>
              <span>Touches §0, §2, §17?</span><strong>{doc.prechecks.sensitive_sections.length ? doc.prechecks.sensitive_sections.map(n => `§${n}`).join(', ') : 'No'}</strong>
              <span>Weakens a rule?</span><strong className="warning">{doc.prechecks.weakens_rules === 'REVIEW_REQUIRED' ? 'Review removals' : 'Not assessed'}</strong>
              <span>Policy tests</span><strong>{doc.prechecks.policy_tests.state ?? 'Unknown'}</strong></div>
              <details><summary>Exact version</summary><p>Version {doc.version || 'not labelled'}{item.pr ? ` · PR #${item.pr}` : ''}</p><code>{doc.source_sha}</code><p className="muted">Document fingerprint</p><code>{doc.document_sha}</code></details>
            </section>
            <section className="panel"><h2>Ask about this change</h2><label>Your question<textarea aria-label="Question about this change" value={question} onChange={event => setQuestion(event.target.value)} /></label>
              <button className="primary" disabled={busy || !question.trim()} onClick={ask}>Ask the CIO with this section</button>
              <p className="muted">Select wording in the document to attach it to a question or a request for changes.</p>
              {selection && <p role="status">Selected: {selection}<button onClick={() => setSelection('')}>Clear selection</button></p>}
            </section>
            <section className="panel reader-actions decision-actions" aria-label="Record your decision">
              <div ref={result}>{error && <><p role="alert" className="warning">{error}</p><button onClick={refresh}>Reload document</button></>}</div>
              <label>Comment<textarea aria-label="Decision comment" value={comment} onChange={event => setComment(event.target.value)} /></label>
              {saved ? <div role="status" className="success"><strong>Decision recorded</strong><p>{saved.decision.replace(/_/g, ' ')} · {saved.actor}</p>
                {saved.policy_token && <details><summary>Policy approval record</summary><code>{saved.policy_token}</code></details>}<Link className="primary" to="/approvals">Return to approvals</Link></div> : <>
                {item.decision_mode === 'GOVERNED_PATH' ? item.governed_href ? <Link className="primary" to={item.governed_href}>{item.kind === 'FINANCIAL' ? 'Open existing trade review' : 'Continue to operator controls'}</Link> : <p className="warning">The governed decision path has not been supplied.</p> :
                  <button className="primary" disabled={!review || !allRead || busy} onClick={() => record('APPROVE')}>Approve{!allRead ? ` — read ${doc.changes.length - read.size} more` : ''}</button>}
                <button disabled={!review || busy || !comment.trim()} onClick={() => record('REQUEST_CHANGES')}>Request changes</button>
                <button disabled={!review || busy} onClick={() => record('REJECT')}>Reject</button>
                <p className="muted">Recorded with your tailnet identity and this exact version. Changed wording resets your reading progress.</p>
              </>}
            </section>
          </aside>
        </div>
      </>}
    </DeskPage>
  </div>
}

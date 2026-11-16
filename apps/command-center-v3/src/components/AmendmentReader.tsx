import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import DeskPage, { DeskGap } from './DeskPage'
import DetailHeader from './DetailHeader'
import { GOVERNANCE, askAboutRule, governanceRequest, governanceRequestId, useGovernance, type ApprovalItem, type Change, type Decision } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'

type Mode = 'changes' | 'whole' | 'side'

function ChangeBlock({ change, review, sha, itemId, isRead, onRead, onFailure, allowed }: { allowed: { current: boolean }; change: Change; review: string; sha: string; itemId: string; isRead: boolean; onRead: (id: string) => void; onFailure: (message: string) => void }) {
  const element = useRef<HTMLDivElement>(null)
  const callbacks = useRef({ onRead, onFailure })
  callbacks.current = { onRead, onFailure }
  useEffect(() => {
    if (!review || !element.current || isRead || !allowed.current) return
    let timer: ReturnType<typeof setTimeout> | undefined, visible = false, completed = false, stopped = false
    const endpoint = `${GOVERNANCE}/approvals/${encodeURIComponent(itemId)}/read`
    const mark = (phase: string) => allowed.current ? governanceRequest(endpoint, { review_id: review, document_sha: sha, change_id: change.id, phase }) : Promise.resolve()
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
            if (stopped || !visible || !allowed.current) return
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
  }, [review, sha, change.id, itemId, isRead, allowed])
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
  // An incomplete retained source is readable, never an authority to start a review.
  const readOnly = !!item?.reader_context && (item.reader_context.state !== 'complete' || item.reader_context.decision_eligible !== true)
  const markingAllowed = useRef(false)
  // Updated during render: old observer cleanup cannot POST after a reload/identity change.
  markingAllowed.current = !!doc && item?.id === id && !readOnly
  useEffect(() => { setReview(''); setRead(new Set()); setSaved(null); setError('') }, [doc?.document_sha, readOnly, id])
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
    if (!doc || busy || readOnly) return
    setBusy(true); setError('')
    try {
      setSaved(await governanceRequest<Decision>(`${GOVERNANCE}/approvals/${encodeURIComponent(id)}/decide`, {
        decision, review_id: review, document_sha: doc.document_sha, request_id: governanceRequestId(),
        comment: selection ? `Selected wording: ${selection}\n\n${comment}` : comment,
      }))
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const begin = async () => {
    if (!doc || readOnly) return
    setBusy(true); setError('')
    try { const started = await governanceRequest<{ review_id: string }>(`${GOVERNANCE}/approvals/${encodeURIComponent(id)}/open`, { document_sha: doc.document_sha }); setReview(started.review_id) }
    catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const ask = async () => {
    if (!doc || readOnly || !question.trim()) return
    setBusy(true); setError('')
    try {
      const attached = selection || doc.changes.map(c => `${c.section}\n${c.after || c.before}`).join('\n').slice(0, 18000)
      const thread = await askAboutRule(question, doc.changes[0]?.section ?? 'Document', attached, doc.document_sha, doc.source_sha)
      navigate(thread ? `/cio/questions/${encodeURIComponent(thread)}` : '/cio/questions')
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const allRead = !!doc && doc.changes.every(c => read.has(c.id))
  // A tap on Approve always records or says why not. A disabled button swallowed two phone taps on 2026-10-31.
  const approve = () => {
    if (!doc || readOnly) return
    if (!review) { setError('Approval not recorded: tap "Start reading" first, then read every highlighted change.'); return }
    if (!allRead) { setError(`Approval not recorded: ${doc.changes.length - read.size} of ${doc.changes.length} changes are still unread. Each one must stay fully on screen for three seconds.`); return }
    void record('APPROVE')
  }
  const governed = item?.decision_mode === 'GOVERNED_PATH'
  const governedLabel = item?.kind === 'FINANCIAL' ? 'Open existing trade review' : item?.kind === 'DESIGN' ? 'Approve this design with your passkey →' : 'Continue to operator controls'
  const governedLink = item?.governed_href ? <Link className="primary" data-testid="governed-decision-link" to={item.governed_href}>{governedLabel}</Link> : <p className="warning">The governed decision path has not been supplied.</p>
  const changes = doc?.changes.filter(c => !search || `${c.section} ${c.before} ${c.after}`.toLowerCase().includes(search.toLowerCase())) ?? []
  const block = (change: Change) => <ChangeBlock key={change.id} change={change} review={readOnly ? '' : review} sha={doc!.document_sha} itemId={id} isRead={read.has(change.id)} onRead={onRead} onFailure={setError} allowed={markingAllowed} />
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
  return <div className="approvals">
    {/* Shared header (nav/v001 §5): "‹ Approvals" · title · ✕ replaces the page's own "← Back to approvals". */}
    <DetailHeader back="Approvals" backTo="/approvals" title={item?.title ?? 'Read & decide'} titleAs="h1" titleRef={title} style={{ marginBottom: 16 }} />
    {readOnly && <section className="panel stack warning" role="note" data-testid="partial-source-reader" style={{ marginBottom: 16 }}>
      <h2>Partial source · read-only document</h2>
      <p>{item?.reader_context?.reason || 'Source completeness could not be established.'}</p>
      <p>Retained wording and its exact version are available below. Reading markers, questions and decisions are disabled until the source is complete. This document does not authorize activation.</p>
      <button onClick={refresh}>Reload document</button>
    </section>}
    {governed && <section className="panel stack" role="note" data-testid="governed-decision" style={{ marginBottom: 16 }}>
      <p>{item?.kind === 'DESIGN'
        ? 'Designs are approved on their work-pipeline card with your passkey and typed words. That is the only approval the design registry reads; nothing on this page records it.'
        : 'This decision is made on its governed page. This reader shows the exact version only.'}</p>
      {readOnly ? <p className="muted">The existing owner page remains available for inspection; its own controls enforce authorization.</p> : null}
      {governedLink}
    </section>}
    <DeskPage title="Document reader" purpose={readOnly ? "Inspect retained wording and its exact version. This partial source is read-only." : "Read each highlighted change for three seconds. Your decision will name this exact version."}
      sources={[{ id: 'document', label: 'Exact document', gap: 'A committed document does not have a scheduled writer clock.' }]} decisionGap={readOnly ? "Source incomplete: decisions cannot be recorded from this reader." : "Approval waits until every change has been read."}>
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
            {!review && <button className="primary" disabled={busy || readOnly} onClick={begin}>Start reading</button>}
            <p className="muted">{readOnly ? "Inspect every retained change; read markers are unavailable while the source is incomplete." : "Each change is marked read after its complete wording has stayed on screen for three seconds."}</p>
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
              <button className="primary" disabled={busy || readOnly || !question.trim()} onClick={ask}>Ask the CIO with this section</button>
              <p className="muted">Select wording in the document to attach it to a question or a request for changes.</p>
              {selection && <p role="status">Selected: {selection}<button onClick={() => setSelection('')}>Clear selection</button></p>}
            </section>
            <section className="panel reader-actions decision-actions" aria-label="Record your decision">
              <div ref={result}>{error && <><p role="alert" className="warning">{error}</p><button onClick={refresh}>Reload document</button></>}</div>
              <label>Comment<textarea aria-label="Decision comment" value={comment} onChange={event => setComment(event.target.value)} /></label>
              {saved ? <div role="status" className="success"><strong>Decision recorded</strong><p>{saved.decision.replace(/_/g, ' ')} · {saved.actor}</p>
                {saved.policy_token && <details><summary>Policy approval record</summary><code>{saved.policy_token}</code></details>}<Link className="primary" to="/approvals">Return to approvals</Link></div> : <>
                {governed ? <p className="muted">This decision is made on its governed page. Use the link at the top of this page.</p> :
                  <button className="primary" data-testid="approve-button" data-unready={!review || !allRead ? 'true' : undefined} disabled={busy || readOnly} onClick={approve}>Approve{!allRead ? ` — read ${doc.changes.length - read.size} more` : ''}</button>}
                <button disabled={readOnly || !review || busy || !comment.trim()} onClick={() => record('REQUEST_CHANGES')}>Request changes</button>
                <button disabled={readOnly || !review || busy} onClick={() => record('REJECT')}>Reject</button>
                <p className="muted">Recorded with your tailnet identity and this exact version. Changed wording resets your reading progress.</p>
              </>}
            </section>
          </aside>
        </div>
      </>}
    </DeskPage>
  </div>
}

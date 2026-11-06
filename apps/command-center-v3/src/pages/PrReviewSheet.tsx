// Approvals → Merges → the independent PR review sheet (Design approvals-pr-review/v001; docs/ops/PR_REVIEW_MODAL_SPEC.md §9).
// Phone (≤820 px): full-screen sheet with a 56 px sticky header and ← Back; one column; the decision card is last.
// Desktop (1440): a modal over the Merges list with a section index, the review, and a sticky decision card.
// The review is written by the host reviewer (never the author). The browser only reads it, marks each finding read
// (3 s fully on screen, the existing ledger rule) and records the operator's decision bound to this head SHA.
// Approve on a held PR is "Approve review": it records and adds no label (D6). Nothing here merges.
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { GOVERNANCE, governanceRequest, governanceRequestId, useGovernance } from '../lib/operatorApprovals'
import {
  approveBlock, approveEffect, cancelledApprovals, checksText, classText, etTime, HELD_CLASS_LABEL, money, plusMinus,
  riskLabel, RISK_TONE, SEVERITY_LABEL, SEVERITY_TONE, short, type Finding, type Hunk, type MergeItem, type MergesSummary,
} from '../lib/prReview'
import '../styles/prReview.css'

const SECTIONS = [['prr-verdict', 'Verdict & summary'], ['prr-findings', 'Findings'], ['prr-checks', 'Checks & tests'],
  ['prr-files', 'Files by area'], ['prr-ask', 'Ask'], ['prr-decide', 'Decide']] as const

function useFindingRead(itemId: string, review: string, sha: string, findingKey: string, done: boolean, onRead: (k: string) => void, onFail: (m: string) => void) {
  const el = useRef<HTMLDivElement>(null)
  const cb = useRef({ onRead, onFail })
  cb.current = { onRead, onFail }
  useEffect(() => {
    if (!review || !el.current || done) return
    let timer: ReturnType<typeof setTimeout> | undefined, visible = false, completed = false, stopped = false
    const endpoint = `${GOVERNANCE}/approvals/${encodeURIComponent(itemId)}/read`
    const mark = (phase: string) => governanceRequest(endpoint, { review_id: review, document_sha: sha, change_id: findingKey, phase })
    const leave = () => { visible = false; clearTimeout(timer); if (!completed) void mark('leave').catch(() => {}) }
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
          void mark('read').then(() => { if (!stopped && visible) { completed = true; cb.current.onRead(findingKey) } })
            .catch(e => cb.current.onFail(e.message))
        }, 3050)
      }).catch(e => cb.current.onFail(e.message))
    }, { threshold: [0, .98, 1] })
    observer.observe(el.current)
    return () => { stopped = true; clearTimeout(timer); observer.disconnect(); if (visible && !completed) leave() }
  }, [itemId, review, sha, findingKey, done])
  return el
}

function FindingCard({ f, item, review, read, onRead, onFail, onGo }: { f: Finding; item: MergeItem; review: string; read: boolean; onRead: (k: string) => void; onFail: (m: string) => void; onGo: (f: Finding) => void }) {
  const key = `finding_${f.id}`
  const ref = useFindingRead(item.id, review, item.document.document_sha, key, read, onRead, onFail)
  return <article className="prr-finding" data-testid={`prr-finding-${f.id}`}>
    <div ref={ref}>
      <header><span className={`prr-pill ${SEVERITY_TONE[f.severity]}`}>{SEVERITY_LABEL[f.severity]}</span><strong>{f.title}</strong>
        <span className="prr-read" data-testid={`prr-read-${f.id}`}>{read ? '✓ read' : item.decisions_store_approved ? 'not read yet' : ''}</span></header>
      <div className="prr-mono" style={{ color: 'var(--info-color)', marginTop: 4 }}>{f.file}{f.line != null ? ` · line ${f.line}` : ''}</div>
      <p>{f.detail}</p>
      {f.suggestion ? <p className="prr-muted">Suggestion: {f.suggestion}</p> : null}
    </div>
    <button type="button" className="prr-linkbtn" onClick={() => onGo(f)}>Go to the change →</button>
  </article>
}

function HunkCard({ h, open, focus, onToggle }: { h: Hunk; open: boolean; focus: boolean; onToggle: () => void }) {
  return <div className={`prr-hunk${focus ? ' focus' : ''}`} id={`prr-hunk-${h.id}`} data-testid={`prr-hunk-${h.id}`}>
    <div><span className="prr-pill ai">AI</span><span>{h.note ?? <em className="prr-muted">Not explained by the reviewer</em>}</span></div>
    <button type="button" className="prr-linkbtn" aria-expanded={open} onClick={onToggle}>{open ? 'Hide the code' : `Show the code (${h.lines.length} lines)`}</button>
    {open ? <pre className="prr-code" data-testid="prr-code" tabIndex={0} aria-label={`Code ${h.file} ${h.header}`}>
      <span>{h.header}{'\n'}</span>
      {h.lines.map((ln, i) => <span key={i} className={ln.startsWith('+') ? 'add' : ln.startsWith('-') ? 'del' : undefined}>{ln}{'\n'}</span>)}
      {h.truncated ? <span className="prr-muted">… more lines on GitHub</span> : null}
    </pre> : null}
  </div>
}

export default function PrReviewSheet({ id }: { id: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { data: item, error: loadError, refresh } = useGovernance<MergeItem>(`${GOVERNANCE}/approvals/${encodeURIComponent(id)}`)
  const { data: summary } = useGovernance<MergesSummary>(`${GOVERNANCE}/pr-reviews/summary`)
  const [reviewId, setReviewId] = useState('')
  const [read, setRead] = useState<Set<string>>(new Set())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState<{ decision: string; effect: string } | null>(null)
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('')
  const [openHunks, setOpenHunks] = useState<Set<string>>(new Set())
  const [focusHunk, setFocusHunk] = useState('')
  const sheet = useRef<HTMLElement>(null)
  const askBox = useRef<HTMLTextAreaElement>(null)
  const back = useCallback(() => navigate('/approvals?tab=MERGE'), [navigate])
  const view = item?.document.review
  const rec = view?.review && !view.stale ? view.review : null
  const sha = item?.document.document_sha ?? ''

  useEffect(() => {
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    sheet.current?.focus()
    return () => { document.body.style.overflow = overflow }
  }, [])
  useEffect(() => { setReviewId(''); setRead(new Set()); setSaved(null) }, [sha])
  // One reading session per open, bound to this exact review (§10: the first sheet open writes READ_STARTED).
  useEffect(() => {
    if (!item || !rec || !item.decisions_store_approved || reviewId) return
    governanceRequest<{ review_id: string }>(`${GOVERNANCE}/approvals/${encodeURIComponent(item.id)}/open`, { document_sha: sha })
      .then(r => setReviewId(r.review_id)).catch(e => setError(e.message))
  }, [item?.id, sha, rec?.document_sha, item?.decisions_store_approved, reviewId])

  const onRead = useCallback((k: string) => setRead(p => new Set([...p, k])), [])
  const go = (f: Finding) => {
    const h = rec?.areas.flatMap(a => a.files.flatMap(fl => fl.hunks)).find(x => x.file === f.file && f.line != null && f.line >= x.start_line && f.line <= x.end_line)
    if (!h) return
    setOpenHunks(p => new Set([...p, h.id])); setFocusHunk(h.id)
    requestAnimationFrame(() => document.getElementById(`prr-hunk-${h.id}`)?.scrollIntoView({ block: 'center' }))
  }
  const decide = async (decision: 'APPROVE' | 'HOLD' | 'REQUEST_CHANGES', comment = '') => {
    if (!item || busy) return
    setBusy(true); setError('')
    try {
      setSaved(await governanceRequest(`${GOVERNANCE}/approvals/${encodeURIComponent(item.id)}/decide`,
        { decision, review_id: reviewId, document_sha: sha, request_id: governanceRequestId(), comment }))
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const ask = async () => {
    if (!item || !question.trim() || busy) return
    setBusy(true); setError('')
    try {
      await governanceRequest(`${GOVERNANCE}/approvals/${encodeURIComponent(item.id)}/question`,
        { question: question.trim(), document_sha: sha, request_id: governanceRequestId() })
      setAsked(question.trim()); setQuestion(''); refresh()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const findings = rec?.findings ?? []
  const unread = findings.filter(f => !read.has(`finding_${f.id}`)).length
  const held = !!item?.merge.held
  const block = item ? approveBlock(item, { reviewId, unread, applierLive: !!summary?.label_applier_live }) : 'Loading'
  const headWanted = params.get('head')
  const headMoved = !!(view && headWanted && !view.current_head.startsWith(headWanted))
  const files = rec?.files ?? []
  const title = item ? `#${item.pr} ${item.title}` : 'PR review'
  const sub = view ? `head ${short(view.current_head, 7)}${rec ? ` · ${files.length} files · ${plusMinus(files)}` : ''}` : ''
  const heldPaths = Object.values(rec?.classes.held_paths ?? {}).flat().slice(0, 3).join(', ')
  const cancelled = item ? cancelledApprovals(item.thread.decisions, view?.current_head ?? '') : []

  const verdictCard = view && <section className={`prr-card prr-verdict ${view.pill.tone}`} id="prr-verdict" data-testid="prr-verdict">
    <h2><span>{held && rec ? 'Held · needs your own merge' : view.pill.label}</span>
      {rec ? <span className={`prr-pill ${RISK_TONE[rec.risk.level]}`}>{riskLabel(rec.risk.level)}</span> : null}
      <span className={`prr-pill ${held ? 'danger' : 'info'}`}>{held ? classText(item!.classes) : item!.classes.shared_infra ? 'shared-infra · ships alone' : 'normal'}</span></h2>
    {rec ? <><p>{rec.summary}</p>{rec.risk.why ? <p className="prr-muted">Why {rec.risk.level.toLowerCase()}: {rec.risk.why}</p> : null}
      {held ? <p className="prr-muted" data-testid="prr-held-note">Held class: {rec.classes.held.map(h => HELD_CLASS_LABEL[h] ?? h).join(', ')}{heldPaths ? <> — <span className="prr-mono">{heldPaths}</span></> : null}. Only your own merge on GitHub merges it.</p> : null}
      {rec.verdict === 'CANNOT_REVIEW' ? <p className="prr-muted">Reason: {rec.verdict_reason}</p> : null}</> : null}
  </section>

  const stateBanner = view && (view.stale || !rec) ? <div className={`prr-banner${view.pill.state === 'cannot' ? ' danger' : ''}`} role="status" data-testid="prr-state-banner">
    {view.stale && view.review ? <><strong>New push — this review is out of date.</strong>
      <p>Reviewed head <span className="prr-mono">{short(view.review.head_sha)}</span> · current head <span className="prr-mono">{short(view.current_head)}</span>. Approve is off until the new head is reviewed.</p>
      {cancelled.length ? <p>Your earlier approval of head {short(cancelled[cancelled.length - 1].head_sha)} was cancelled by the new push.</p> : null}
      <p className="prr-muted">{view.queue?.state === 'SETTLING' ? `The new review starts ${etTime(view.queue.next_try_at)} (10 minutes after the last push).` : 'A new review runs on the next 5-minute cycle.'}</p></> : null}
    {!view.review && view.pill.state === 'stale' ? <><strong>Review in progress.</strong><p>{view.queue?.state === 'SETTLING' ? `Starts ${etTime(view.queue.next_try_at)}.` : 'The reviewer picks this PR up on its next 5-minute cycle.'}</p></> : null}
    {view.pill.state === 'credit' ? <><strong>Review waiting for credit.</strong><p>{view.queue?.reason}. Next try: {view.queue?.next_try_at ? etTime(view.queue.next_try_at) : 'when you decide (credit expired)'}.</p>
      <p className="prr-muted">No other paid model is used. Options: raise the cap with /caps, or merge it yourself on GitHub.</p></> : null}
    {view.pill.state === 'cannot' && !rec ? <><strong>Cannot review.</strong><p>{view.queue?.reason}</p><p className="prr-muted">Options: split the PR, or merge it yourself on GitHub.</p></> : null}
  </div> : null

  const whoCard = rec && <section className="prr-card" data-testid="prr-who"><h2>Who reviewed it</h2><dl className="prr-facts">
    <dt>Author</dt><dd>{rec.author.vendor}{rec.author.session ? ` · session ${rec.author.session}` : ''}{rec.author.model ? ` · ${rec.author.model}` : ''}</dd>
    <dt>Reviewer</dt><dd>{rec.reviewer.model} · host review run <span className="prr-mono">{rec.reviewer.run_id}</span> · fresh context</dd>
    <dt>Independent</dt><dd>{rec.independent.ok ? <span className="prr-pill success">Yes — reviewer is not the author</span> : <span className="prr-pill danger">No</span>}</dd>
    {rec.second_read ? <><dt>Second read</dt><dd>{rec.second_read.provider ?? 'OAuth'} (free) · run <span className="prr-mono">{rec.second_read.run_id}</span> · {rec.second_read.verdict ? rec.second_read.verdict.replace(/_/g, ' ').toLowerCase() : `no answer (${rec.second_read.error})`}</dd></> : null}
    <dt>Bound to</dt><dd>head <span className="prr-mono">{short(rec.head_sha, 12)}</span> · base <span className="prr-mono">main@{short(rec.base_sha, 6)}</span></dd>
    <dt>Reviewed</dt><dd>{etTime(rec.created_at)} · {Math.round(rec.reviewer.duration_s)} s · {money(rec.reviewer.cost_usd)}</dd>
  </dl>{rec.second_read?.findings.length ? <p className="prr-muted">Second reader raised: {rec.second_read.findings.map(f => f.title).join('; ')}</p> : null}</section>

  const findingsCard = rec && <section className="prr-card" id="prr-findings"><h2>Findings <small>({findings.length} · read each one before approving)</small></h2>
    {findings.length ? findings.map(f => <FindingCard key={f.id} f={f} item={item!} review={reviewId} read={read.has(`finding_${f.id}`)} onRead={onRead} onFail={setError} onGo={go} />)
      : <p className="prr-muted">The reviewer raised no findings.</p>}
    {rec.dropped_findings ? <p className="prr-muted">{rec.dropped_findings} finding(s) pointed outside the changed lines and were dropped by the harness.</p> : null}
  </section>

  const checksCard = view && <section className="prr-card" id="prr-checks"><h2>Checks and test evidence</h2>
    <p className="prr-muted" style={{ marginBottom: 8 }}>Read from GitHub and the PR, not from the model.</p>
    <div className="prr-checks">{Object.entries(rec?.evidence.checks ?? view.checks).map(([name, state]) => <div className="prr-check" key={name}>
      <span className={`prr-dot${state === 'SUCCESS' ? '' : ' bad'}`} /><span>{name}</span><span>{state.toLowerCase()}</span></div>)}</div>
    {rec ? <dl className="prr-facts">
      <dt>Tests</dt><dd>{rec.evidence.tests_added} new · {rec.evidence.tests_changed} changed test file(s)</dd>
      <dt>Dry run</dt><dd>{rec.evidence.dry_run_quoted ? <span className="prr-pill success">quoted in PR</span> : <span className="prr-pill neutral">not quoted</span>}</dd>
      <dt>Real-layout proof</dt><dd>{rec.evidence.real_layout_proof ? <span className="prr-pill success">present</span> : <span className="prr-pill neutral">absent</span>}{rec.classes.shared_infra ? ' (required for shared-infra)' : ''}</dd>
      <dt>Size</dt><dd>{rec.files.length} files · {plusMinus(rec.files)} · {rec.unexplained_hunks ? `${rec.unexplained_hunks} of ${rec.hunk_count} changes not explained` : 'fully read by the reviewer'}</dd>
    </dl> : null}
  </section>

  const filesCard = rec && <section className="prr-card" id="prr-files"><h2>What changed, by area</h2>
    <p className="prr-muted">Every change has a one-line note. Tap "Show the code" for the exact lines.</p>
    {rec.areas.map((a, i) => <details className="prr-area" key={a.name} open={i === 0 || a.files.some(f => f.hunks.some(h => openHunks.has(h.id)))}>
      <summary><span>{a.name}</span><span className="prr-mono prr-muted">{a.files.length} file{a.files.length === 1 ? '' : 's'} · +{a.additions} −{a.deletions}</span></summary>
      <div className="prr-area-body">{a.files.map(f => <div key={f.path}><div className="prr-file prr-mono">{f.path}</div>
        {f.hunks.map(h => <HunkCard key={h.id} h={h} open={openHunks.has(h.id)} focus={focusHunk === h.id}
          onToggle={() => setOpenHunks(p => { const n = new Set(p); if (n.has(h.id)) n.delete(h.id); else n.add(h.id); return n })} />)}</div>)}</div>
    </details>)}
  </section>

  const askCard = item && <section className="prr-card" id="prr-ask"><h2>Ask about this PR</h2>
    {item.thread.questions.map((q, i) => <div key={i}><div className="prr-qa"><strong>You · {etTime(q.at)}</strong><p style={{ margin: '4px 0 0' }}>{q.question}</p></div>
      <div className="prr-qa answer">{q.answer ? <><span className="prr-pill ai">Reviewer</span> {q.answer} <span className="prr-muted">(answered {etTime(q.answered_at)} · {money(q.cost_usd)})</span></>
        : <span className="prr-muted">Waiting for the reviewer (next 5-minute cycle, inside the $2/day review cap).</span>}</div></div>)}
    {asked && !item.thread.questions.some(q => q.question === asked) ? <p className="prr-muted" role="status">Question recorded. The reviewer answers on its next cycle.</p> : null}
    <label className="prr-muted" htmlFor="prr-question" style={{ display: 'block', marginTop: 10 }}>Your question (the reviewer answers with this PR and its review in view)</label>
    <textarea id="prr-question" ref={askBox} data-testid="prr-question" value={question} onChange={e => setQuestion(e.target.value)} maxLength={1000}
      placeholder="e.g. What happens to existing records?" />
    <div className="prr-stack" style={{ marginTop: 8 }}>
      <button type="button" className="prr-btn primary" data-testid="prr-ask-reviewer" disabled={busy || !question.trim() || !rec || !item.decisions_store_approved} onClick={ask}>Ask the reviewer</button>
      <button type="button" className="prr-btn" data-testid="prr-ask-author" disabled={busy || !question.trim() || !reviewId || !!saved} onClick={() => decide('REQUEST_CHANGES', question.trim())}>Ask the author to change it</button>
    </div>
    <p className="prr-muted" style={{ marginTop: 8 }}>"Ask the author to change it" records Request changes with your words; the PR stays out of the digest until a new head is reviewed.</p>
  </section>

  const decideCard = item && view && <section className="prr-card" id="prr-decide" data-testid="prr-decide"><h2>Your decision</h2>
    <dl className="prr-facts"><dt>Findings read</dt><dd data-testid="prr-read-count"><strong>{findings.length - unread} of {findings.length}</strong></dd>
      <dt>{held ? 'Records' : 'Approves'}</dt><dd>PR #{item.pr} at head <span className="prr-mono">{short(view.current_head, 7)}</span> only</dd></dl>
    {saved ? <div role="status" className="prr-banner" style={{ marginTop: 10 }} data-testid="prr-saved"><strong>Recorded: {saved.decision.replace(/_/g, ' ').toLowerCase()}</strong>
      <p>{saved.effect === 'OPERATOR_MERGE_LABEL' ? 'The host adds operator-merge for this head; Mergify merges in its next ET window.' : saved.effect === 'REVIEW_APPROVED_NO_LABEL' ? 'No label added. Merge it yourself on GitHub.' : 'Recorded in the decision ledger.'}</p></div> : <>
      <div style={{ marginTop: 10 }}><button type="button" className="prr-btn approve" data-testid="prr-approve" disabled={!!block || busy} onClick={() => decide('APPROVE')}>{held ? 'Approve review' : 'Approve merge'}</button></div>
      <div className="prr-decide-row">
        <button type="button" className="prr-btn hold" data-testid="prr-hold" disabled={busy || !reviewId || !item.decisions_store_approved} onClick={() => decide('HOLD')}>Hold</button>
        <button type="button" className="prr-btn" data-testid="prr-ask-jump" onClick={() => { document.getElementById('prr-ask')?.scrollIntoView({ block: 'start' }); askBox.current?.focus({ preventScroll: true }) }}>Ask</button>
      </div>
      {block ? <p className="prr-muted" style={{ marginTop: 8 }} data-testid="prr-block">{block}</p> : null}
      <p className="prr-muted" style={{ marginTop: 8 }}>{approveEffect(held, item.pr, view.current_head)}</p></>}
    {error ? <p role="alert" style={{ color: 'var(--danger-color)', marginTop: 8 }}>{error}</p> : null}
  </section>

  const body = loadError ? <div className="prr-body"><div className="prr-banner danger" role="alert"><strong>Review unavailable</strong><p>{loadError}</p>
    <button type="button" className="prr-btn" onClick={refresh}>Try again</button></div></div>
    : !item || !view ? <div className="prr-body"><p role="status">Loading the review…</p></div>
    : <div className="prr-body">
      <nav className="prr-index prr-card" aria-label="Review sections">{SECTIONS.map(([anchor, label]) => <a key={anchor} href={`#${anchor}`}
        onClick={e => { e.preventDefault(); document.getElementById(anchor)?.scrollIntoView({ block: 'start' }) }}>{label}</a>)}
        {view.url ? <a href={view.url} target="_blank" rel="noreferrer">Open on GitHub ↗</a> : null}</nav>
      <div className="prr-main">{headMoved ? <div className="prr-banner" role="status">The digest link named head {headWanted}; the PR has moved to {short(view.current_head)}.</div> : null}
        {stateBanner}{verdictCard}{whoCard}{findingsCard}{checksCard}{filesCard}{askCard}</div>
      <aside className="prr-side">{decideCard}</aside>
    </div>

  return createPortal(<div className="prr-overlay" data-testid="prr-overlay">
    <section ref={sheet} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className="prr-sheet" data-testid="pr-review-sheet"
      onKeyDown={e => { if (e.key === 'Escape') back() }}>
      <header className="prr-header" data-testid="prr-header"><button type="button" onClick={back} data-testid="prr-back">← Back</button>
        <div className="prr-title"><strong>{title}</strong><span>{sub}</span></div>
        {view ? <span className={`prr-pill ${view.pill.tone}`} data-testid="prr-header-pill">{view.pill.label}</span> : null}</header>
      {body}
    </section></div>, document.body)
}

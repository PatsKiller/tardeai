import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import DeskPage, { DeskGap } from '../components/DeskPage'
import { GOVERNANCE, askAboutRule, governanceRequest, useGovernance, type Policy } from '../lib/operatorApprovals'
import '../styles/operatorApprovals.css'
import { AuditLastLine, RuleMarkdown, type RulebookPolicy, type RulebookRule } from '../components/PolicyRuleParts'

type Sheet =
  | { kind: 'change'; rule: RulebookRule }
  | { kind: 'ask'; section: string; text: string }
  | { kind: 'add' }
  | null

function sectionAnchor(section: string) {
  return `rb-${section.replace(/[^\w]+/g, '-').replace(/^-|-$/g, '').toLowerCase()}`
}

function groupRules(rules: RulebookRule[]) {
  const order: string[] = []
  const bySection = new Map<string, RulebookRule[]>()
  for (const rule of rules) {
    if (!bySection.has(rule.section)) {
      order.push(rule.section)
      bySection.set(rule.section, [])
    }
    bySection.get(rule.section)!.push(rule)
  }
  return order.map(section => ({ section, rules: bySection.get(section)! }))
}

export default function PolicyHub() {
  const [params, setParams] = useSearchParams()
  const focus = params.get('section') ?? ''
  const { data: raw, error, refresh } = useGovernance<Policy>(`${GOVERNANCE}/policy?view=document`)
  const data = raw as unknown as RulebookPolicy | null | undefined
  const [seek, setSeek] = useState('')
  const [sheet, setSheet] = useState<Sheet>(null)
  const [comment, setComment] = useState('')
  const [sectionTitle, setSectionTitle] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const responseInput = useRef<HTMLTextAreaElement>(null)
  const noticeElement = useRef<HTMLParagraphElement>(null)
  const phone = window.matchMedia('(max-width: 820px)').matches
  const navigate = useNavigate()
  const measured = data?.counts_measured === true

  const chapters = useMemo(() => groupRules(data?.rules ?? []), [data?.rules])
  const seekLower = seek.trim().toLowerCase()
  const visible = useMemo(() => {
    if (!seekLower) return chapters
    return chapters
      .map(({ section, rules }) => ({
        section,
        rules: rules.filter(rule =>
          section.toLowerCase().includes(seekLower)
          || (rule.subsection ?? '').toLowerCase().includes(seekLower)
          || rule.text.toLowerCase().includes(seekLower)
          || (rule.plain ?? '').toLowerCase().includes(seekLower)),
      }))
      .filter(chapter => chapter.rules.length > 0 || chapter.section.toLowerCase().includes(seekLower))
  }, [chapters, seekLower])

  useEffect(() => {
    if (!focus || !data) return
    const id = sectionAnchor(focus)
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: 'start' }))
  }, [focus, data?.document_sha])

  useEffect(() => { if (sheet) responseInput.current?.focus() }, [sheet?.kind, (sheet && 'rule' in sheet ? sheet.rule.id : ''), (sheet && 'section' in sheet ? sheet.section : '')])
  useEffect(() => { if (notice && !sheet) noticeElement.current?.scrollIntoView({ block: 'nearest' }) }, [notice, sheet])

  const openSheet = (next: Sheet) => { setSheet(next); setComment(''); setSectionTitle(''); setNotice('') }
  const closeSheet = () => setSheet(null)

  const jump = (section: string) => {
    const next = new URLSearchParams(params)
    next.set('section', section)
    setParams(next, { replace: true })
    document.getElementById(sectionAnchor(section))?.scrollIntoView({ block: 'start' })
  }

  const submit = async () => {
    if (!data || !sheet || busy) return
    setBusy(true); setNotice('')
    try {
      if (sheet.kind === 'add') {
        await governanceRequest(`${GOVERNANCE}/policy/feedback`, {
          position: 'DISAGREE', action: 'add_section', section_title: sectionTitle.trim(),
          comment, document_sha: data.document_sha,
        })
        setNotice('Proposed new section is now in Approvals.'); closeSheet(); refresh()
      } else if (sheet.kind === 'ask') {
        const rule = data.rules.find(r => r.section === sheet.section) ?? data.rules[0]
        if (rule) {
          await governanceRequest(`${GOVERNANCE}/policy/feedback`, {
            position: 'QUESTION', comment, rule_id: rule.id, document_sha: data.document_sha,
          })
        }
        const thread = await askAboutRule(comment, sheet.section, sheet.text, data.document_sha, data.source_sha)
        navigate(thread ? `/cio/questions/${encodeURIComponent(thread)}` : '/cio/questions')
      } else {
        await governanceRequest(`${GOVERNANCE}/policy/feedback`, {
          position: 'DISAGREE', comment, rule_id: sheet.rule.id, document_sha: data.document_sha,
        })
        setNotice('Your proposed change is now in Approvals.'); closeSheet(); refresh()
      }
    } catch (err) { setNotice((err as Error).message) } finally { setBusy(false) }
  }

  const seekAsk = async () => {
    if (!data || !seek.trim() || busy) return
    const matched = visible[0]
    const text = matched
      ? matched.rules.slice(0, 3).map(r => r.text).join('\n\n')
      : data.rules.slice(0, 3).map(r => r.text).join('\n\n')
    const section = matched?.section ?? data.sections[0] ?? 'Rulebook'
    openSheet({ kind: 'ask', section, text })
    setComment(`Seek in Rulebook: ${seek.trim()}\n\nWhat applies, and what should I do?`)
  }

  const versionNote = [
    data?.policy_version ? `AGENTS.md Policy-Version ${data.policy_version}` : 'AGENTS.md — the one agent operating standard',
    `${data?.total_rules ?? '—'} rules in one document.`,
  ].join('. ')

  const sheetLabel = sheet?.kind === 'add' ? 'Propose new section'
    : sheet?.kind === 'ask' ? 'Ask about this section'
    : sheet?.kind === 'change' ? 'Propose a change' : ''

  return <div className="approvals"><DeskPage title="Rulebook" purpose="AGENTS.md as one document — every chapter and subsection agents follow. Seek here; propose changes in Approvals."
    sources={[{ id: 'policy', label: 'Committed policy', asOf: data?.last_reviewed ?? null, clockOnly: true, note: versionNote }]}
    decisionGap="Seek and Ask use the CIO (Opus). Propose a change or a new section when the document should grow.">
    {error && <DeskGap title="Rulebook unavailable" reason={error}><button onClick={refresh}>Try again</button></DeskGap>}
    {notice && !sheet && <p ref={noticeElement} role="status" className="panel">{notice}</p>}
    {!data && !error && <p role="status">Loading Rulebook…</p>}
    {data && <>
      <div className="toolbar rulebook-seek" style={{ marginTop: 0 }}>
        <label style={{ flex: 1, minWidth: 180 }}>Seek in Rulebook
          <input aria-label="Seek in Rulebook" value={seek} onChange={event => setSeek(event.target.value)}
            placeholder="Filter chapters and rules…" style={{ width: '100%' }} />
        </label>
        <button type="button" className="primary" disabled={!seek.trim() || busy} onClick={seekAsk}
          data-testid="rulebook-seek-ask">Ask the CIO (Opus)</button>
        <button type="button" onClick={() => openSheet({ kind: 'add' })} data-testid="rulebook-add-section">Propose new section</button>
        <Link className="primary" to="/approvals">Open approvals</Link>
      </div>
      {!measured && <p className="muted" data-testid="rulebook-audit-gap" style={{ margin: '0 0 8px' }}>
        {data.total_rules} rules · Policy-Version {data.policy_version ?? '—'}. Enforcement audit has not run against this version
        {data.audit.reason ? ` — ${data.audit.reason}` : ''}.
      </p>}
      {measured && <div className="counts" data-testid="rulebook-counts" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 130px), 1fr))' }}>
        {[['RULES', data.total_rules], ['ENFORCED', data.counts.ENFORCED], ['TESTED', data.counts.TESTED], ['VIOLATED', data.counts.VIOLATED]].map(([label, value]) =>
          <div key={String(label)} className="panel" data-testid={`rulebook-count-${label}`}><span>{label === 'RULES' ? 'Rules' : String(label).charAt(0) + String(label).slice(1).toLowerCase()}</span><strong>{value ?? '—'}</strong></div>)}
      </div>}
      <div className="policy-grid">
        <nav className="panel toc" aria-label="Rulebook chapters" data-testid="rulebook-toc">
          <p className="muted" style={{ margin: '0 0 8px' }}>Jump to a chapter — same order as AGENTS.md.</p>
          {data.sections.map(section => {
            const count = data.section_counts?.[section]
            const start = /^\s*0(\s|·|\.)/.test(section)
            return <a key={section} href={`#${sectionAnchor(section)}`} data-testid="rulebook-chapter"
              onClick={event => { event.preventDefault(); jump(section) }}
              aria-current={focus === section ? 'location' : undefined}>
              <span>{section}{start ? ' · start' : ''}</span>
              {count != null && <span className="muted" style={{ marginLeft: 6 }}>{count}</span>}
            </a>
          })}
          <details style={{ marginTop: 8 }}><summary>Document version</summary>
            {data.policy_version && <p style={{ margin: '8px 0 4px' }}>Policy-Version {data.policy_version}</p>}
            <code>{data.source_sha}</code>
          </details>
          <Link to="/conflicts/rules" style={{ marginTop: 8 }}>How source conflicts are decided →</Link>
        </nav>
        <article aria-label="Policy document" data-testid="rulebook-document">
          {visible.length === 0 && <p className="panel">No chapters match that seek.</p>}
          {visible.map(({ section, rules }) => {
            const anchor = sectionAnchor(section)
            let lastSub: string | null | undefined = undefined
            return <section key={section} id={anchor} className="rulebook-chapter panel" data-testid="rulebook-section">
              <header className="rulebook-chapter-head">
                <h2 data-testid="rulebook-section-heading" style={{ fontSize: 18, margin: 0, fontFamily: 'Georgia, serif' }}>{section}</h2>
                <div className="toolbar" style={{ margin: 0 }}>
                  <button type="button" onClick={() => {
                    const rule = rules[0] ?? data.rules.find(r => r.section === section)
                    if (rule) openSheet({ kind: 'change', rule })
                  }}>Propose a change</button>
                  <button type="button" onClick={() => openSheet({
                    kind: 'ask', section, text: rules.slice(0, 5).map(r => r.text).join('\n\n'),
                  })}>Ask about this section</button>
                </div>
              </header>
              {rules.map(rule => {
                const showSub = rule.subsection && rule.subsection !== lastSub
                if (showSub) lastSub = rule.subsection
                return <div key={rule.id} className="rulebook-rule" data-testid="rulebook-rule">
                  {showSub && <h3 className="rulebook-subsection">{rule.subsection}</h3>}
                  {(rule.number || (!rule.subsection && rule.plain)) && (
                    <p className="muted" style={{ margin: '0 0 4px' }}>
                      {rule.number ? `Rule ${rule.number}` : null}
                    </p>
                  )}
                  <RuleMarkdown text={rule.text} testId="rulebook-rule-text" />
                  {rule.plain && <details><summary>In plain words</summary><p>{rule.plain}</p></details>}
                  {measured && <><span className="badge">{rule.status}</span>{rule.reason && <p className="muted">{rule.reason}</p>}</>}
                  {measured && Object.keys(rule.evidence).length > 0 && <details><summary>Enforcement evidence</summary><pre>{JSON.stringify(rule.evidence, null, 2)}</pre></details>}
                  <button type="button" className="rulebook-rule-change" onClick={() => openSheet({ kind: 'change', rule })}>
                    Propose a change to this rule
                  </button>
                </div>
              })}
            </section>
          })}
        </article>
        <aside className="stack">
          <section className="panel"><h2>Enforcement audit</h2>
            <p>Weekly on Sunday at 20:00 and after an amendment. Mechanical checks map rules to tests and runtime checks.</p>
            <AuditLastLine audit={data.audit} />
            <p className="muted">Findings go to Approvals. Changes are never applied automatically.</p>
            <Link className="primary" to="/system/ops-controls?tab=jobs">Review audit job</Link>
          </section>
          {data.audit.scope && <section className="panel"><h2>Audit coverage</h2><p>{data.audit.scope}</p>
            <p>Mapped {data.audit.mapped_count ?? 'unknown'} · Unmapped {data.audit.unmapped_count ?? 'unknown'}</p></section>}
          {!!data.audit.findings?.length && <section className="panel"><h2>Latest findings</h2>
            {data.audit.findings.slice(0, 5).map((finding, index) => <p key={index}>{finding.title}</p>)}
            <Link className="primary" to="/approvals">Review findings in Approvals</Link></section>}
          <section className="panel"><h2>Your recent responses</h2>
            <p>Agreed {data.positions.filter(p => p.position === 'AGREE').length} · Questions {data.positions.filter(p => p.position === 'QUESTION').length} · Proposed changes {data.positions.filter(p => p.position === 'DISAGREE').length}</p>
          </section>
        </aside>
      </div>
    </>}
    {sheet && data && <section className={`stack rule-response-sheet panel`} role={phone ? 'dialog' : 'region'}
      aria-modal={phone || undefined} aria-label={sheetLabel} data-testid="rulebook-sheet"
      onKeyDown={event => {
        if (event.key === 'Escape') closeSheet()
        if (!phone || event.key !== 'Tab') return
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),textarea,input,a[href]')]
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }}>
      <button type="button" onClick={closeSheet}>← Back to Rulebook</button>
      <h2 style={{ margin: 0 }}>{sheetLabel}</h2>
      {sheet.kind === 'change' && <><p className="muted">{sheet.rule.section}</p><RuleMarkdown text={sheet.rule.text} /></>}
      {sheet.kind === 'ask' && <p className="muted">Section: {sheet.section}. The CIO answers with Opus; this is not Agree / Disagree on every rule.</p>}
      {sheet.kind === 'add' && <label>New section title
        <input aria-label="New section title" value={sectionTitle} onChange={event => setSectionTitle(event.target.value)}
          placeholder="e.g. 29 · Observability standards" style={{ width: '100%' }} />
      </label>}
      <label>{sheet.kind === 'ask' ? 'Your question' : sheet.kind === 'add' ? 'What the section should say, and why' : 'Proposed change and reason'}
        <textarea ref={responseInput} aria-label="Rule response comment" value={comment}
          onChange={event => setComment(event.target.value)} />
      </label>
      {notice && <p role="alert">{notice}</p>}
      <button className="primary" disabled={busy || !comment.trim() || (sheet.kind === 'add' && !sectionTitle.trim())}
        onClick={submit}>
        {sheet.kind === 'ask' ? 'Ask the CIO with this section' : sheet.kind === 'add' ? 'Propose section in Approvals' : 'Propose change in Approvals'}
      </button>
      <button type="button" onClick={closeSheet}>Cancel</button>
    </section>}
  </DeskPage></div>
}

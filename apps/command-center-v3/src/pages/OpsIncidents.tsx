// Ops → Incidents (operator 2026-10-27: agents "can't just drop and leave it … report it somewhere in a log that you
// could come back in as a coordinator and look at it"). Read view of GET /api/v2/ops/incidents
// (scripts/lib/incidents_view.py over the IncidentRecord@v1 ledger). Phone-first: list by status with age; tapping a
// row opens a full-screen sheet with ← Back (≤820px) or a side panel (desktop) — evidence, actions taken, PR links.
// The only writes are the operator's Acknowledge and Close as won't-fix, recorded in the operator decisions ledger
// first (POST …/<id>/ack | …/<id>/close). Nothing here retries, merges, releases or fixes anything.
import { useEffect, useRef, useState, type CSSProperties, type Ref } from 'react'
import { useApi } from '../hooks/useApi'
import OpsDeskFrame from '../components/OpsDeskFrame'
import { Chip, ChipRow } from '../components/primitives'
import { MobileDetailSheet, useMobilePageDetail } from '../components/MobileDetailSheet'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import { governanceRequest, governanceRequestId } from '../lib/operatorApprovals'
import {
  ageText, canAct, INCIDENTS_PATH, matchesFilter, refLink, sortIncidents, sourceText, statusLabel, STATUS_FILTERS,
  type Incident, type IncidentDetailWire, type IncidentsWire,
} from '../lib/incidents'

const panel: CSSProperties = { padding: 14, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const muted: CSSProperties = { margin: 0, fontSize: TYPE.sm, color: TOKENS.text[2] }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm }
const btn: CSSProperties = { minHeight: 44, padding: '8px 14px', borderRadius: RADIUS.md, fontSize: TYPE.sm, fontWeight: 700, cursor: 'pointer',
  background: 'transparent', border: `1px solid ${TOKENS.border}`, color: TOKENS.text[0] }
const at = (v: string | null | undefined) => v && Number.isFinite(Date.parse(v))
  ? new Date(v).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET'
  : '—'

function OperatorActions({ inc, onDone }: { inc: Incident; onDone: () => void }) {
  const [mode, setMode] = useState<'idle' | 'close'>('idle')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const can = canAct(inc)
  if (!can.ack && !can.close) return null
  const send = async (verb: 'ack' | 'close') => {
    setBusy(true); setMsg('')
    try {
      await governanceRequest(`${INCIDENTS_PATH}/${encodeURIComponent(inc.id)}/${verb}`, { request_id: governanceRequestId(), comment })
      setMsg(verb === 'ack' ? 'Acknowledged.' : "Closed as won't fix."); setMode('idle'); setComment(''); onDone()
    } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  return <div data-testid="incident-operator-actions" style={{ display: 'grid', gap: 8, borderTop: `1px solid ${TOKENS.border}`, paddingTop: 10 }}>
    <p style={muted}>Your decision is recorded in the operator decisions ledger. It does not retry, fix or release anything.</p>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {can.ack ? <button type="button" data-testid="incident-ack" disabled={busy} onClick={() => send('ack')} style={btn}>Acknowledge</button> : null}
      {can.close && mode === 'idle' ? <button type="button" data-testid="incident-close-start" disabled={busy} onClick={() => setMode('close')} style={btn}>Close as won't fix…</button> : null}
    </div>
    {mode === 'close' ? <div style={{ display: 'grid', gap: 6 }}>
      <label htmlFor={`wontfix-${inc.id}`} style={muted}>Why won't this be fixed? (required)</label>
      <textarea id={`wontfix-${inc.id}`} data-testid="incident-close-comment" value={comment} onChange={e => setComment(e.target.value)} rows={3}
        style={{ width: '100%', boxSizing: 'border-box', fontSize: 16, padding: 8, borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[0], color: TOKENS.text[0] }} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" data-testid="incident-close-confirm" disabled={busy || !comment.trim()} onClick={() => send('close')} style={btn}>Close as won't fix</button>
        <button type="button" onClick={() => { setMode('idle'); setComment('') }} style={btn}>Cancel</button>
      </div>
    </div> : null}
    {msg ? <p role="status" style={{ ...muted, color: TOKENS.text[1] }}>{msg}</p> : null}
  </div>
}

function Detail({ inc, events, titleRef, onChanged }: { inc: Incident; events: Record<string, unknown>[] | null; titleRef?: Ref<HTMLHeadingElement>; onChanged: () => void }) {
  const s = statusLabel(inc.status)
  const facts: Array<[string, string]> = [
    ['Id', inc.id], ['Opened', at(inc.opened_at)], ['Age', ageText(inc.opened_at, inc.closed_at)], ['Source', sourceText(inc)],
    ['Where', inc.where || '—'], ['Owner', inc.owner || '—'], ['Severity', inc.severity || '—'],
  ]
  if (inc.closed_at) facts.push(['Closed', `${at(inc.closed_at)}${inc.resolution ? ` · ${inc.resolution.replace(/_/g, ' ')}` : ''}`])
  if (inc.recurrence_of) facts.push(['Recurrence of', inc.recurrence_of])
  return <div data-testid="incident-detail" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <h3 ref={titleRef} tabIndex={-1} data-detail-focus style={{ margin: 0, fontSize: TYPE.md, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{inc.title}</h3>
    <ChipRow><Chip tone={s.tone}>{s.label}</Chip>{inc.acknowledged ? <Chip tone="neutral">acknowledged</Chip> : null}
      {inc.escalations?.length ? <Chip tone="danger">P1 sent</Chip> : null}</ChipRow>
    {inc.status === 'blocked' ? <div style={{ ...panel, borderColor: toneVars('danger').border }}>
      <p style={{ ...muted, color: TOKENS.text[0] }}><strong>Blocked:</strong> {inc.blocked_reason}</p>
      <p style={{ ...muted, color: TOKENS.text[0], marginTop: 6 }}><strong>Next step:</strong> {inc.handoff}</p>
    </div> : null}
    <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(90px, auto) 1fr', gap: '6px 12px', margin: 0 }}>
      {facts.map(([k, v]) => [<dt key={`${k}-k`} style={muted}>{k}</dt>,
        <dd key={`${k}-v`} style={{ ...mono, margin: 0, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{v}</dd>])}
    </dl>
    {inc.fix_refs?.length ? <div><p style={muted}>Fixed by</p>
      <ul data-testid="incident-fix-refs" style={{ margin: '4px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>{inc.fix_refs.map(r => {
        const l = refLink(r)
        return <li key={`${r.kind}:${r.ref}`} style={{ ...mono, overflowWrap: 'anywhere' }}>
          {l.href ? <a href={l.href} target="_blank" rel="noreferrer" style={{ color: TOKENS.primary, display: 'inline-block', minHeight: 44, lineHeight: '44px' }}>{l.label}</a> : l.label}</li>
      })}</ul></div> : null}
    {inc.evidence?.length ? <div><p style={muted}>Evidence</p>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{inc.evidence.map(e => <li key={e} style={{ ...mono, overflowWrap: 'anywhere' }}>{e}</li>)}</ul></div> : null}
    <div><p style={muted}>Actions taken</p>
      {inc.attempts.length === 0 ? <p style={muted}>None yet.</p> :
        <ol data-testid="incident-attempts" style={{ margin: '4px 0 0', paddingLeft: 18, display: 'grid', gap: 6 }}>
          {inc.attempts.map((a, i) => <li key={`${a.at}-${i}`} style={{ fontSize: TYPE.sm, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>
            <span style={mono}>{at(a.at)}</span> · {a.actor} · <strong>{a.action}</strong>: {a.result}
            {a.ok === false ? ' ✗' : a.ok === true ? ' ✓' : ''}{a.rationale ? <div style={muted}>{a.provider ? `${a.provider}: ` : ''}{a.rationale}</div> : null}
          </li>)}
        </ol>}
    </div>
    {inc.notes?.length ? <div><p style={muted}>Notes</p>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{inc.notes.map((n, i) => <li key={i} style={{ fontSize: TYPE.sm, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>
        <span style={mono}>{at(n.at)}</span> · {n.actor}: {n.text}</li>)}</ul></div> : null}
    <p style={muted}>{events === null ? 'Loading the event log…' : `${events.length} ledger event(s).`}</p>
    <OperatorActions inc={inc} onDone={onChanged} />
  </div>
}

export default function OpsIncidents() {
  const [filter, setFilter] = useState('active')
  const sheet = useMobilePageDetail('detail')
  const titleRef = useRef<HTMLHeadingElement>(null)
  const { data, loading, error, refetch } = useApi<IncidentsWire>(INCIDENTS_PATH, 60_000)
  const selectedId = sheet.id
  const detail = useApi<IncidentDetailWire>(`${INCIDENTS_PATH}/${encodeURIComponent(selectedId || '')}`, 60_000, { enabled: !!selectedId })
  const selected = !selectedId ? null
    : (detail.data?.incident?.id === selectedId ? detail.data.incident : data?.incidents.find(r => r.id === selectedId) ?? null)
  useEffect(() => { if (selectedId && !sheet.mobile) titleRef.current?.focus() }, [selectedId, sheet.mobile])
  const rows = sortIncidents((data?.incidents ?? []).filter(r => matchesFilter(r, filter)))
  const c = data?.summary?.counts
  const metrics = [['open', 'Open', 'danger'], ['fixing', 'Fixing', 'warning'], ['blocked', 'Blocked', 'danger'], ['fixed', 'Fixed', 'success']] as const
  const changed = () => { refetch(); detail.refetch() }
  const body = selected ? <Detail inc={selected} events={detail.data?.events ?? null} titleRef={titleRef} onChanged={changed} /> : null
  return <main style={{ padding: 20, background: TOKENS.bg[0], minWidth: 0 }}>
    <OpsDeskFrame page="incidents" asOf={{ watchers: data?.watchers_as_of, supervisor: data?.supervisor_as_of }}>
      <section aria-label="Incidents" data-testid="ops-incidents" style={{ display: 'grid', gap: 12, minWidth: 0, color: TOKENS.text[0], fontFamily: FONT.sans }}>
        {error ? <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Incidents could not be read: {error}.</div> : null}
        {data && !data.ledger_present ? <div role="status" style={{ ...panel, color: TOKENS.warning }}>The incident ledger has no events yet.</div> : null}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 }}>
          {metrics.map(([k, label, t]) => <div key={k} data-testid={`incident-count-${k}`} style={{ ...panel, padding: '10px 12px', borderColor: toneVars(t).border }}>
            <div style={muted}>{label}</div>
            <strong style={{ ...mono, fontSize: TYPE.xl, color: toneVars(t).color }}>{c ? c[k] : '—'}</strong>
          </div>)}
        </div>
        <div role="group" aria-label="Filter incidents" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {STATUS_FILTERS.map(([k, label]) => <button key={k} type="button" aria-pressed={filter === k} data-testid={`incident-filter-${k}`}
            onClick={() => setFilter(k)}
            style={{ ...btn, background: filter === k ? TOKENS.bg[2] : 'transparent', borderColor: filter === k ? TOKENS.primary : TOKENS.border, color: filter === k ? TOKENS.text[0] : TOKENS.text[2] }}>{label}</button>)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: selected && !sheet.mobile ? 'minmax(0, 1.1fr) minmax(0, 1fr)' : 'minmax(0, 1fr)', gap: 12 }}>
          <div style={{ ...panel, padding: 0 }}>
            {loading && !data ? <p style={{ ...muted, padding: 14 }}>Loading incidents…</p> : null}
            {data && rows.length === 0 ? <p style={{ ...muted, padding: 14 }}>No incidents match this filter.</p> : null}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {rows.map(r => {
                const s = statusLabel(r.status)
                return <li key={r.id} style={{ borderTop: `1px solid ${TOKENS.border}` }}>
                  <button type="button" data-testid={`incident-row-${r.id}`} aria-current={selectedId === r.id} onClick={() => sheet.open(r.id)}
                    style={{ width: '100%', minHeight: 56, display: 'grid', gap: 4, textAlign: 'left', padding: '10px 14px', cursor: 'pointer',
                      background: selectedId === r.id ? TOKENS.bg[2] : 'transparent', border: 0, color: TOKENS.text[0] }}>
                    <span style={{ fontSize: TYPE.sm, fontWeight: 700, overflowWrap: 'anywhere' }}>{r.title}</span>
                    <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                      <Chip tone={s.tone}>{s.label}</Chip>
                      <span style={muted}>{ageText(r.opened_at, r.closed_at)} · {sourceText(r)}{r.fix_refs?.length ? ` · ${refLink(r.fix_refs[0]).label}` : ''}</span>
                    </span>
                  </button>
                </li>
              })}
            </ul>
          </div>
          {selected && !sheet.mobile ? <aside style={panel} aria-label="Incident detail">
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button type="button" onClick={sheet.close} style={btn}>Close</button></div>
            {body}
          </aside> : null}
        </div>
        {selected && sheet.mobile ? <MobileDetailSheet title={selected.title} onBack={sheet.close}>{body}</MobileDetailSheet> : null}
      </section>
    </OpsDeskFrame>
  </main>
}

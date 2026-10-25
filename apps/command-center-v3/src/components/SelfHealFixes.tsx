// Ops → Releases & schedules → Fixes (operator 2026-10-25: "Arm the fixer and also a logger that tracks what was
// fixed"). Read-only view of GET /api/v2/ops/self-heal-fixes (scripts/lib/self_heal_fixes_view.py). One row per fix
// (latest state); tapping a row opens its full history — a full-screen sheet with ← Back on a phone, a side panel on
// desktop. Nothing here starts, merges or releases a fix: fix PRs are ordinary PRs the release train carries.
import { useEffect, useRef, useState, type CSSProperties, type Ref } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from './primitives'
import { MobileDetailSheet, useMobilePageDetail } from './MobileDetailSheet'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import {
  costText, FIX_FILTERS, monitorLine, outcomeLabel, remediationLabel, SELF_HEAL_FIXES_PATH, shortSha, sourceLabel,
  type FixFilter, type FixRow, type SelfHealFixesWire,
} from '../lib/selfHealFixes'

const panel: CSSProperties = { padding: 14, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const muted: CSSProperties = { margin: 0, fontSize: TYPE.sm, color: TOKENS.text[2] }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm }
const at = (v: string | null) => v && Number.isFinite(Date.parse(v))
  ? new Date(v).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET'
  : '—'

const lastOf = <T,>(xs: T[] | null | undefined): T | undefined => (xs && xs.length ? xs[xs.length - 1] : undefined)

function Detail({ row, history, titleRef }: { row: FixRow; history: FixRow[] | null; titleRef?: Ref<HTMLHeadingElement> }) {
  const o = outcomeLabel(row.outcome)
  const facts: Array<[string, string]> = [
    ['Source', sourceLabel(row.source)], ['Detected', at(row.detected_at)], ['Remediation', remediationLabel(row.remediation_kind)],
    ['Attempts', String(row.attempts ?? 0)], ['Model cost', costText(row.model_cost_usd)],
    ['Fix PR', row.pr_number ? `#${row.pr_number} · head ${shortSha(row.pr_head)}` : '—'],
    ['Released', shortSha(row.released_sha)], ['Verified', at(row.verified_at)], ['Signature', row.signature ?? '—'],
  ]
  return <div data-testid="self-heal-fix-detail" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    <h3 ref={titleRef} tabIndex={-1} data-detail-focus style={{ margin: 0, fontSize: TYPE.md, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{row.title ?? row.fix_id}</h3>
    <ChipRow><Chip tone={o.tone}>{o.label}</Chip>{row.mode === 'shadow' ? <Chip tone="neutral">shadow</Chip> : null}</ChipRow>
    {row.detail ? <p style={{ ...muted, overflowWrap: 'anywhere' }}>{row.detail}</p> : null}
    <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(90px, auto) 1fr', gap: '6px 12px', margin: 0 }}>
      {facts.map(([k, v]) => [<dt key={`${k}-k`} style={muted}>{k}</dt>,
        <dd key={`${k}-v`} style={{ ...mono, margin: 0, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{v}</dd>])}
    </dl>
    {row.evidence_refs?.length ? <div><p style={muted}>Evidence</p>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{row.evidence_refs.map(e => <li key={e} style={{ ...mono, overflowWrap: 'anywhere' }}>{e}</li>)}</ul></div> : null}
    <div><p style={muted}>History</p>
      {history === null ? <p style={muted}>Loading history…</p> : history.length === 0 ? <p style={muted}>No events recorded.</p> :
        <ol data-testid="self-heal-fix-history" style={{ margin: '4px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>
          {history.map((h, i) => <li key={`${h.at}-${i}`} style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
            <span style={mono}>{at(h.at)}</span> · {h.event} → {outcomeLabel(h.outcome).label}{h.detail ? ` — ${h.detail}` : ''}</li>)}
        </ol>}
    </div>
  </div>
}

export default function SelfHealFixes({ enabled = true }: { enabled?: boolean }) {
  const [filter, setFilter] = useState<FixFilter>('all')
  const [offset, setOffset] = useState(0)
  const sheet = useMobilePageDetail('fix')
  const titleRef = useRef<HTMLHeadingElement>(null)
  const { data, loading, error } = useApi<SelfHealFixesWire>(`${SELF_HEAL_FIXES_PATH}?filter=${filter}&offset=${offset}&limit=50`, 60_000, { enabled })
  const selectedId = sheet.id
  const detail = useApi<SelfHealFixesWire>(`${SELF_HEAL_FIXES_PATH}?filter=all&limit=1&fix=${encodeURIComponent(selectedId || '')}`, 60_000, { enabled: enabled && !!selectedId })
  const selected = data?.rows.find(r => r.fix_id === selectedId) ?? lastOf(detail.data?.history) ?? null
  useEffect(() => { if (selectedId && !sheet.mobile) titleRef.current?.focus() }, [selectedId, sheet.mobile])
  const mon = monitorLine(data)
  const s = data?.summary
  const metrics = [['open', 'Open', 'info'], ['fixed', 'Fixed', 'success'], ['escalated', 'Escalated', 'danger'], ['proposed', 'Proposed (shadow)', 'neutral']] as const
  const body = selected ? <Detail row={selected} history={detail.data?.history ?? null} titleRef={titleRef} /> : null
  return <section aria-label="Self-heal fixes" data-testid="self-heal-fixes" style={{ display: 'grid', gap: 12, minWidth: 0, color: TOKENS.text[0], fontFamily: FONT.sans }}>
    <div style={{ display: 'grid', gap: 4 }}>
      <h2 style={{ margin: 0, fontSize: TYPE.lg }}>Fixes</h2>
      <p style={muted}>What the self-heal monitor found and fixed: main CI, the release train, post-release tests and the nightly sweep. Fix PRs are ordinary PRs; the train releases them.</p>
      <ChipRow><Chip tone={mon.tone}>{mon.text}</Chip>{s ? <Chip tone="neutral">model cost {costText(s.model_cost_usd)}</Chip> : null}</ChipRow>
    </div>
    {error ? <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Fixes could not be read: {error}.</div> : null}
    {data?.status === 'UNAVAILABLE' ? <div role="status" data-testid="self-heal-fixes-unavailable" style={{ ...panel, color: TOKENS.warning }}>UNAVAILABLE · {data.reason}</div> : null}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
      {metrics.map(([k, label, t]) => <div key={k} style={{ ...panel, padding: '10px 12px', borderColor: toneVars(t).border }}>
        <div style={muted}>{label}</div>
        <strong style={{ ...mono, fontSize: TYPE.xl, color: toneVars(t).color }}>{s && data?.status === 'OK' ? s[k] : '—'}</strong>
      </div>)}
    </div>
    <div role="group" aria-label="Filter fixes" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {FIX_FILTERS.map(([k, label]) => <button key={k} type="button" aria-pressed={filter === k} data-testid={`self-heal-filter-${k}`}
        onClick={() => { setFilter(k); setOffset(0) }}
        style={{ minHeight: 44, padding: '8px 14px', borderRadius: RADIUS.md, fontSize: TYPE.sm, fontWeight: 700, cursor: 'pointer',
          background: filter === k ? TOKENS.bg[2] : 'transparent', border: `1px solid ${filter === k ? TOKENS.primary : TOKENS.border}`, color: filter === k ? TOKENS.text[0] : TOKENS.text[2] }}>{label}</button>)}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: selected && !sheet.mobile ? 'minmax(0, 1.2fr) minmax(0, 1fr)' : 'minmax(0, 1fr)', gap: 12 }}>
      <div style={{ ...panel, padding: 0 }}>
        {loading && !data ? <p style={{ ...muted, padding: 14 }}>Loading fixes…</p> : null}
        {data && data.rows.length === 0 && data.status === 'OK' ? <p style={{ ...muted, padding: 14 }}>No fixes match this filter.</p> : null}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {(data?.rows ?? []).map(r => {
            const o = outcomeLabel(r.outcome)
            return <li key={r.fix_id} style={{ borderTop: `1px solid ${TOKENS.border}` }}>
              <button type="button" data-testid={`self-heal-fix-${r.fix_id}`} aria-current={selectedId === r.fix_id}
                onClick={() => sheet.open(r.fix_id)}
                style={{ width: '100%', minHeight: 56, display: 'grid', gap: 4, textAlign: 'left', padding: '10px 14px', cursor: 'pointer',
                  background: selectedId === r.fix_id ? TOKENS.bg[2] : 'transparent', border: 0, color: TOKENS.text[0] }}>
                <span style={{ fontSize: TYPE.sm, fontWeight: 700, overflowWrap: 'anywhere' }}>{r.title ?? r.fix_id}</span>
                <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                  <Chip tone={o.tone}>{o.label}</Chip>
                  <span style={muted}>{sourceLabel(r.source)} · {remediationLabel(r.remediation_kind)}{r.pr_number ? ` · PR #${r.pr_number}` : ''} · {at(r.at)}</span>
                </span>
              </button>
            </li>
          })}
        </ul>
        {data?.has_more || offset > 0 ? <div style={{ display: 'flex', gap: 8, padding: 10 }}>
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} style={{ minHeight: 44 }}>Previous</button>
          <button type="button" disabled={!data?.has_more} onClick={() => setOffset(offset + 50)} style={{ minHeight: 44 }}>Next</button>
        </div> : null}
      </div>
      {selected && !sheet.mobile ? <aside style={panel} aria-label="Fix detail">
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button type="button" onClick={sheet.close} style={{ minHeight: 44 }}>Close</button></div>
        {body}
      </aside> : null}
    </div>
    {selected && sheet.mobile ? <MobileDetailSheet title={selected.title ?? 'Fix'} onBack={sheet.close}>{body}</MobileDetailSheet> : null}
  </section>
}

// Co-coordinators by territory (operator 2026-11-02, PLAN_CO_COORDINATORS_20261102): who coordinates what, what is
// assigned where, which risky actions are waiting for a second coordinator's check, and what is waiting on the
// operator. Read-only; scripts/coordinator.py is the only writer. Mobile first: cards stack at 412/390 px and the
// tables scroll horizontally rather than truncate. Nothing on this page writes anything.
import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../lib/designTokens'
import {
  byTerritory, heartbeatLabel, sortCoordinators, stateLabel, stateTone,
  type BoardPayload, type CoordinatorsPayload,
} from '../lib/coordinators'

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14,
}
const label: CSSProperties = {
  fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 750,
}
const cell: CSSProperties = { padding: '6px 8px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono, fontSize: TYPE.xs }
const sectionTitle: CSSProperties = { fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }

function Card({ c }: { c: NonNullable<CoordinatorsPayload['coordinators']>[number] }) {
  const tone = stateTone(c.state)
  return (
    <div data-testid="coordinator-card" style={{
      background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12,
      display: 'grid', gap: 6, minWidth: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: TYPE.base, fontWeight: 800, color: TOKENS.text[0] }}>{c.id}</span>
        <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{c.vendor || 'vendor?'}</span>
        <Chip tone={String(c.role) === 'lead' ? 'positive' : 'neutral'} title="role">{String(c.role || 'member')}</Chip>
        <Chip tone={tone} title="heartbeat freshness">{stateLabel(c.state)}</Chip>
      </div>
      <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
        <span style={label}>territories </span>{(c.territories || []).join(', ') || '—'}
      </div>
      <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>
        heartbeat {heartbeatLabel(c.last_heartbeat)}
        {c.where ? ` · ${c.where}` : ''}{c.session ? ` · ${c.session}` : ''}
      </div>
      {c.appointed_quote ? (
        <div title="the operator's words when this coordinator was appointed" style={{ fontSize: TYPE.xs, color: TOKENS.text[3], overflowWrap: 'anywhere' }}>
          “{c.appointed_quote}”
        </div>
      ) : null}
    </div>
  )
}

export default function CoordinatorsPanel() {
  const coordApi = useApi<CoordinatorsPayload>('/api/v2/coordination/coordinators', 30_000)
  const boardApi = useApi<BoardPayload>('/api/v2/coordination/board?limit=30', 30_000)
  const [showBoard, setShowBoard] = useState(false)
  const d = coordApi.data
  const b = boardApi.data
  const rows = sortCoordinators(d?.coordinators)
  const groups = byTerritory(d?.assignments)
  const checks = d?.pending_checks || []
  const decisions = d?.pending_decisions || []
  const inbox = d?.inbox || {}

  if (coordApi.loading && !d) return <div style={panel} data-testid="coordination-coordinators">Loading coordinators…</div>
  if (coordApi.error && !d) return <div style={panel} data-testid="coordination-coordinators">Coordinators unavailable.</div>

  return (
    <div style={{ display: 'grid', gap: 12 }} data-testid="coordination-coordinators">
      <div style={panel}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={sectionTitle}>Coordinators</div>
          <div style={{ ...label, maxWidth: 640 }}>
            by territory · one lead is the one voice to you · nothing here writes
          </div>
        </div>
        {d?.registry_present === false ? (
          <div role="alert" style={{ marginTop: 8, padding: '8px 10px', borderRadius: RADIUS.sm, fontSize: TYPE.sm, color: TOKENS.text[2], background: TOKENS.bg[2] }}>
            No coordinator registry yet. The operator appoints with <code>scripts/coordinator.py appoint --id … --quote “…”</code>.
          </div>
        ) : null}
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={d?.lead ? 'positive' : 'warning'} title="the only coordinator that brings questions to the operator">
            lead: {d?.lead || 'none'}
          </Chip>
          <Chip tone="neutral" title="how long silence marks a coordinator stale">{d?.stale_after_minutes ?? 30}m stale rule</Chip>
          <Chip tone={checks.length ? 'warning' : 'neutral'} title="risky actions waiting for a second coordinator">checks {checks.length}</Chip>
          <Chip tone={decisions.length ? 'warning' : 'neutral'} title="waiting on the operator">waiting on you {decisions.length}</Chip>
        </ChipRow>
        <div style={{ display: 'grid', gap: 10, marginTop: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
          {rows.length ? rows.map(c => <Card key={String(c.id)} c={c} />) : (
            <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>No coordinators appointed.</div>
          )}
        </div>
      </div>

      <div style={panel}>
        <div style={sectionTitle}>Waiting on you</div>
        {decisions.length ? (
          <ul style={{ margin: '8px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>
            {decisions.map((e, i) => (
              <li key={`${e.subject}-${i}`} style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
                <strong>{e.subject}</strong>{e.detail ? ` — ${e.detail}` : ''}
                {e.coordinator ? ` (${e.coordinator})` : ''}
              </li>
            ))}
          </ul>
        ) : <div style={{ marginTop: 6, fontSize: TYPE.sm, color: TOKENS.text[2] }}>Nothing pending.</div>}
      </div>

      <div style={panel}>
        <div style={sectionTitle}>Pending checks</div>
        <div style={{ ...label, marginTop: 2 }}>a risky action needs a DIFFERENT active coordinator's ok before it runs</div>
        {checks.length ? (
          <div style={{ overflowX: 'auto', marginTop: 8 }} data-testid="pending-checks">
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                <th style={{ ...cell, textAlign: 'left' }}>subject</th>
                <th style={{ ...cell, textAlign: 'left' }}>sha</th>
                <th style={{ ...cell, textAlign: 'left' }}>requested by</th>
                <th style={{ ...cell, textAlign: 'left' }}>since</th>
              </tr></thead>
              <tbody>
                {checks.map((e, i) => (
                  <tr key={`${e.subject}-${e.sha}-${i}`}>
                    <td style={cell}>{e.subject}</td>
                    <td style={mono}>{(e.sha || '').slice(0, 12) || '—'}</td>
                    <td style={cell}>{e.coordinator || '—'}</td>
                    <td style={mono}>{e.ts || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div style={{ marginTop: 6, fontSize: TYPE.sm, color: TOKENS.text[2] }}>No pending checks.</div>}
      </div>

      <div style={panel}>
        <div style={sectionTitle}>Assignments by territory</div>
        <div style={{ ...label, marginTop: 2 }}>every agent and every open PR belongs to exactly one territory</div>
        {groups.length ? (
          <div style={{ display: 'grid', gap: 10, marginTop: 8 }} data-testid="assignments">
            {groups.map(g => (
              <div key={g.territory} style={{ display: 'grid', gap: 4 }}>
                <div style={{ fontSize: TYPE.sm, fontWeight: 750, color: TOKENS.text[1] }}>{g.territory}</div>
                <ChipRow>
                  {g.subjects.map(s => <Chip key={s} tone="neutral" title="assigned subject">{s}</Chip>)}
                </ChipRow>
              </div>
            ))}
          </div>
        ) : <div style={{ marginTop: 6, fontSize: TYPE.sm, color: TOKENS.text[2] }}>Nothing assigned yet.</div>}
        {Object.keys(inbox).length ? (
          <ChipRow style={{ marginTop: 10 }}>
            <span style={label}>inbox</span>
            {Object.entries(inbox).map(([id, n]) => <Chip key={id} tone={n ? 'warning' : 'neutral'} title="unread reports">{id} {n}</Chip>)}
          </ChipRow>
        ) : null}
      </div>

      <div style={panel}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={sectionTitle}>Shared notebook</div>
          <button type="button" onClick={() => setShowBoard(v => !v)} style={{
            minHeight: 44, padding: '7px 14px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`,
            background: TOKENS.bg[1], color: TOKENS.text[1], cursor: 'pointer', fontSize: TYPE.sm, fontWeight: 750,
          }}>{showBoard ? 'Hide board' : 'Show board'}</button>
        </div>
        <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], marginTop: 4 }}>
          {b?.board_present === false ? 'BOARD.md not generated yet.' : 'Generated by scripts/coordinator.py board.'}
        </div>
        {showBoard && b?.board_md ? (
          <pre style={{
            marginTop: 8, padding: 10, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`,
            borderRadius: RADIUS.sm, fontFamily: FONT.mono, fontSize: TYPE.xs, color: TOKENS.text[1],
            whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 420, overflow: 'auto',
          }} data-testid="coordination-board-md">{b.board_md}</pre>
        ) : null}
        {b?.events?.length ? (
          <div style={{ marginTop: 10 }} data-testid="coordination-events">
            <div style={label}>recent events</div>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, display: 'grid', gap: 3 }}>
              {b.events.slice(-12).reverse().map((e, i) => (
                <li key={`${e.ts}-${i}`} style={{ fontSize: TYPE.xs, color: TOKENS.text[2], overflowWrap: 'anywhere' }}>
                  <span style={{ fontFamily: FONT.mono }}>{e.ts}</span>{' '}
                  <strong style={{ color: TOKENS.text[1] }}>{e.kind}</strong> {e.subject || ''}
                  {e.detail ? ` — ${e.detail}` : ''}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {boardApi.error ? (
          <div role="alert" style={{ marginTop: 8, fontSize: TYPE.sm, color: toneVars('warning').color }}>
            board read failed: {String(boardApi.error)}
          </div>
        ) : null}
      </div>
    </div>
  )
}

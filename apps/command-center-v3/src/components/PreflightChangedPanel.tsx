import { fmtPx, type PreflightDiff } from '../lib/protectiveStopPreflight'

const TEXT0 = '#f8fafc', MUTED = '#94a3b8', AMBER = '#f59e0b', GREEN = '#22c55e', RED = '#ef4444'

export default function PreflightChangedPanel({ diff, busy, validating, onProceed, onCancel }: {
  diff: PreflightDiff
  busy?: boolean
  validating?: boolean
  onProceed: () => void
  onCancel: () => void
}) {
  return (
    <div data-testid="preflight-changed" style={{ marginTop: 10, padding: '10px 11px', borderRadius: 8, background: 'rgba(245,158,11,.12)', border: `1px solid ${AMBER}` }}>
      <div style={{ fontSize: 12, fontWeight: 900, color: AMBER, marginBottom: 6 }}>Logic changed after live validation</div>
      <div data-testid="preflight-diff" style={{ display: 'grid', gap: 5, fontSize: 11.5, color: TEXT0, lineHeight: 1.45 }}>
        {diff.price && (
          <div><span style={{ color: MUTED, fontWeight: 800 }}>Price: </span>{fmtPx(diff.price.before)} → <b>{fmtPx(diff.price.after)}</b></div>
        )}
        {diff.decision && (
          <div><span style={{ color: MUTED, fontWeight: 800 }}>Decision: </span>{diff.decision.before.replace(/_/g, ' ')} → <b>{diff.decision.after.replace(/_/g, ' ')}</b></div>
        )}
        {diff.state && (
          <div><span style={{ color: MUTED, fontWeight: 800 }}>Status: </span>{diff.state.before} → <b>{diff.state.after}</b></div>
        )}
        {diff.advisoryStop && (
          <div><span style={{ color: MUTED, fontWeight: 800 }}>Advisor stop: </span>{fmtPx(diff.advisoryStop.before)} → <b>{fmtPx(diff.advisoryStop.after)}</b></div>
        )}
        {diff.liveStop && (
          <div><span style={{ color: MUTED, fontWeight: 800 }}>Broker stop: </span>{diff.liveStop.before} → <b>{diff.liveStop.after}</b></div>
        )}
        {diff.action && (
          <div><span style={{ color: MUTED, fontWeight: 800 }}>Recommendation: </span>{diff.action.before} → <b>{diff.action.after}</b></div>
        )}
        {diff.blockers && (diff.blockers.added.length > 0 || diff.blockers.removed.length > 0) && (
          <div>
            {diff.blockers.added.map((m, i) => (
              <div key={`add-${i}`} style={{ color: RED }}>+ {m}</div>
            ))}
            {diff.blockers.removed.map((m, i) => (
              <div key={`rm-${i}`} style={{ color: GREEN }}>− {m}</div>
            ))}
          </div>
        )}
      </div>
      <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button onClick={onProceed} disabled={busy || validating}
          style={{ fontSize: 12, fontWeight: 800, padding: '6px 12px', borderRadius: 6, border: `1px solid ${GREEN}`, background: `${GREEN}22`, color: GREEN, cursor: 'pointer' }}>
          Proceed anyway
        </button>
        <button onClick={onCancel}
          style={{ fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid rgba(148,163,184,.35)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>
          Cancel
        </button>
      </div>
    </div>
  )
}
// Open-position momentum panel. Renders the EVIDENCE STATE emitted by the momentum-exit policy.
//
// CRITICAL OPERATOR-SAFETY BOUNDARY: every state here — including EXIT_SIGNAL — is display-only
// evidence. This panel contains NO order button, POST, broker call, account binding, session
// activation, or auto-flatten control, and never triggers a hidden execution side effect.
// EXIT_ARMED is styled distinctly from EXIT_SIGNAL, and both are described in accessible text.

import type { MotionPosition } from '../../pages/activeTrader.types';
import {
  MOTION_UNKNOWN,
  exitStateClass,
  exitStateDescription,
  exitStateLabel,
  fmtAge,
  fmtPrice,
  fmtR,
  fmtScorePct,
  fmtSeconds,
  humanizeReason,
  scorePctWidth,
} from './motionFormat';

type Props = {
  positions: MotionPosition[];
  degraded: boolean;
};

function PersistenceRow({ label, seconds }: { label: string; seconds: number | null }) {
  return (
    <div className="at-motion-pos__persist-row">
      <span>{label}</span>
      <strong className="mono">{seconds == null ? MOTION_UNKNOWN : fmtSeconds(seconds)}</strong>
    </div>
  );
}

function PositionCard({ p }: { p: MotionPosition }) {
  const isSignal = p.state === 'EXIT_SIGNAL';
  const isArmed = p.state === 'EXIT_ARMED';
  const isProtect = p.state === 'PROTECT_ONLY';
  return (
    <article className={`at-motion-pos ${exitStateClass(p.state)}`} aria-label={`${p.symbol} momentum state ${exitStateLabel(p.state)}`}>
      <header className="at-motion-pos__head">
        <span className="at-motion-pos__sym mono">{p.symbol}</span>
        <span className={`at-motion-pos__state ${exitStateClass(p.state)}`} role="status">
          {/* Non-color cue: a leading glyph + text, so state is legible without color. */}
          <span aria-hidden="true" className="at-motion-pos__glyph">
            {isSignal ? '◆' : isArmed ? '▲' : isProtect ? '⛉' : p.state === 'WATCH' ? '◐' : '●'}
          </span>
          <span className="at-motion-pos__state-label">{exitStateLabel(p.state)}</span>
        </span>
      </header>

      <p className="at-motion-pos__desc">{exitStateDescription(p.state)}</p>

      <div className="at-motion-pos__score">
        <div className="at-motion-pos__score-head">
          <span>deterioration</span>
          <strong className="mono">{fmtScorePct(p.score)}</strong>
          <span className="at-motion-pos__conf">{p.confirmations == null ? MOTION_UNKNOWN : `${p.confirmations} confirming`}</span>
        </div>
        <div className="at-motion-pos__bar" aria-hidden="true">
          <span className="at-motion-pos__bar-fill" style={{ width: `${scorePctWidth(p.score)}%` }} />
        </div>
      </div>

      <dl className="at-motion-pos__levels">
        <div><dt>current</dt><dd className="mono">{fmtPrice(p.price)}</dd></div>
        <div><dt>entry</dt><dd className="mono">{fmtPrice(p.entryPrice)}</dd></div>
        <div><dt>HWM</dt><dd className="mono">{fmtPrice(p.highWatermark)}</dd></div>
        <div><dt>hard stop</dt><dd className="mono">{fmtPrice(p.hardStopPrice)}</dd></div>
        <div><dt>DD from HWM</dt><dd className="mono">{fmtR(p.drawdownFromHighR)}</dd></div>
        <div><dt>evidence age</dt><dd className="mono">{p.evidenceAgeS == null ? MOTION_UNKNOWN : fmtAge(p.evidenceAgeS * 1000)}</dd></div>
      </dl>

      <div className="at-motion-pos__persist" aria-label="Persistence progress">
        <PersistenceRow label="armed for" seconds={p.armedForS} />
        <PersistenceRow label="fire for" seconds={p.fireForS} />
        <PersistenceRow label="recovery for" seconds={p.recoveryForS} />
      </div>

      <footer className="at-motion-pos__foot">
        <span className="at-motion-pos__reason mono">{humanizeReason(p.reasonCode)}</span>
        <span className="at-motion-pos__displayonly">ACCOUNT UNBOUND · NO ORDER PATH</span>
      </footer>
    </article>
  );
}

export default function PositionMomentumPanel({ positions, degraded }: Props) {
  return (
    <section className="at-panel at-motion-positions" aria-labelledby="motion-pos-title">
      <header className="at-panel__header">
        <div>
          <h2 id="motion-pos-title">Open-position momentum <small>account-unbound evidence · no order path</small></h2>
          <p>{degraded ? 'Showing last-good — not live' : 'live momentum-exit evidence states'}</p>
        </div>
        <span className={`at-chip at-chip--${degraded ? 'warning' : 'context'}`}>
          {degraded ? 'NOT LIVE' : `${positions.length} position${positions.length === 1 ? '' : 's'}`}
        </span>
      </header>

      {positions.length === 0 ? (
        <div className="at-motion-positions__empty">No active monitored positions.</div>
      ) : (
        <div className="at-motion-positions__grid">
          {positions.map((p) => <PositionCard key={p.symbol} p={p} />)}
        </div>
      )}
    </section>
  );
}

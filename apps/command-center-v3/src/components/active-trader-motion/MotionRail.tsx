// Near-fire motion rail. Rows update IN PLACE and are keyed + sorted by symbol so a price/priority
// tick never reorders them and never loses the operator's selected row. Each row shows tier,
// admitted/not, lease reason code, last-update age, next-refresh cadence, and a truthful
// stale/unavailable indicator. Read-only: no order control lives here.

import type { MotionDecision, MotionLease } from '../../pages/activeTrader.types';
import { MOTION_UNKNOWN, fmtSeconds, humanizeReason, tierClass } from './motionFormat';

type Props = {
  decisions: MotionDecision[];
  leases: MotionLease[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
  ageLabel: string;   // last-update age for the whole snapshot
  degraded: boolean;  // stale/unavailable — the rail is labelled not-live
};

export default function MotionRail({ decisions, leases, selectedSymbol, onSelect, ageLabel, degraded }: Props) {
  // Stable identity: sort by symbol only. Never by price or priority (would reorder on a tick).
  const rows = [...decisions].sort((a, b) => a.symbol.localeCompare(b.symbol));
  const leasedSymbols = new Set(leases.map((l) => l.symbol));

  return (
    <section className="at-panel at-motion-rail" aria-labelledby="motion-rail-title">
      <header className="at-panel__header">
        <div>
          <h2 id="motion-rail-title">Near-fire motion rail <small>T2 just-in-time admission</small></h2>
          <p>{degraded ? 'Showing last-good — not live' : `updated ${ageLabel}`}</p>
        </div>
        <span className={`at-chip at-chip--${degraded ? 'warning' : 'pass'}`}>
          {degraded ? 'NOT LIVE' : `${rows.length} tracked`}
        </span>
      </header>

      {rows.length === 0 ? (
        <div className="at-motion-rail__empty">
          No near-fire candidates right now. This is the normal empty state, not an error.
        </div>
      ) : (
        <div className="at-motion-rail__table" role="table" aria-label="Near-fire candidates">
          <div className="at-motion-rail__row at-motion-rail__row--head" role="row">
            <span role="columnheader">sym</span>
            <span role="columnheader">tier</span>
            <span role="columnheader">admitted</span>
            <span role="columnheader">reason</span>
            <span role="columnheader">refresh</span>
          </div>
          {rows.map((d) => {
            const selected = d.symbol === selectedSymbol;
            const leased = leasedSymbols.has(d.symbol);
            return (
              <button
                key={d.symbol}
                type="button"
                role="row"
                aria-pressed={selected}
                data-symbol={d.symbol}
                className={`at-motion-rail__row at-motion-rail__row--data ${tierClass(d.tier)}${selected ? ' is-selected' : ''}`}
                onClick={() => onSelect(d.symbol)}
              >
                <span role="cell" className="at-motion-rail__sym mono">{d.symbol}</span>
                <span role="cell" className="at-motion-rail__tier">
                  <span className="at-chip at-chip--context">{d.tier === 'UNKNOWN' ? '—' : d.tier}</span>
                  {leased && <span className="at-motion-rail__leased" title="Holds an active T2 lease"> · leased</span>}
                </span>
                <span role="cell" className="at-motion-rail__admit">
                  {d.admitted
                    ? <span className="at-chip at-chip--pass">admitted</span>
                    : <span className="at-chip at-chip--warning">not admitted</span>}
                </span>
                <span role="cell" className="at-motion-rail__reason mono">{humanizeReason(d.reasonCode)}</span>
                <span role="cell" className="at-motion-rail__refresh mono">
                  {d.refreshAfterS == null ? MOTION_UNKNOWN : `every ${fmtSeconds(d.refreshAfterS)}`}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

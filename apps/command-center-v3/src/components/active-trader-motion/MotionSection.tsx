// Live-motion surface for the Active Trader Review page. Composes the near-fire rail, the T2
// capacity indicator, and the open-position momentum panel over ONE aggregate polling hook.
//
// Honest states only:
//   • endpoint absent/failing with no prior data → MOTION API UNAVAILABLE (fails closed);
//   • prior data + failed refresh            → MOTION DATA STALE (last-good preserved + labelled);
//   • reference/preview                       → REFERENCE SAMPLE (never merged into live counts).
// No mock is ever presented as live. No order/flatten/session control exists on this surface.

import { useMemo, useState } from 'react';
import { useActiveTraderMotion } from '../../hooks/useActiveTraderMotion';
import { MOCK_MOTION_SNAPSHOT } from '../../pages/activeTrader.mock';
import type { MotionSnapshot } from '../../pages/activeTrader.types';
import MotionRail from './MotionRail';
import PositionMomentumPanel from './PositionMomentumPanel';
import T2CapacityIndicator from './T2CapacityIndicator';
import { fmtAge } from './motionFormat';

type Props = {
  reference: boolean;   // preview mode — show the labelled reference sample, do not poll
};

function StatusBanner({
  variant,
  text,
  detail,
}: {
  variant: 'live' | 'stale' | 'unavailable' | 'loading' | 'reference';
  text: string;
  detail?: string;
}) {
  const tone = variant === 'live' ? 'pass'
    : variant === 'stale' || variant === 'reference' ? 'warning'
    : variant === 'unavailable' ? 'fail' : 'context';
  return (
    <div className={`at-motion-banner at-motion-banner--${variant}`} role="status">
      <span className={`at-chip at-chip--${tone}`}>{text}</span>
      {detail && <span className="at-motion-banner__detail">{detail}</span>}
    </div>
  );
}

export default function MotionSection({ reference }: Props) {
  const motion = useActiveTraderMotion({ enabled: !reference });
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  // Reference/preview shows the explicitly-labelled sample; live shows only real fetched data.
  const snapshot: MotionSnapshot | null = reference ? MOCK_MOTION_SNAPSHOT : motion.snapshot;
  const status = reference ? 'reference' : motion.status;
  const degraded = status === 'stale' || status === 'unavailable';

  const ageLabel = useMemo(() => {
    if (reference) return 'reference sample';
    return fmtAge(motion.ageMs);
  }, [reference, motion.ageMs]);

  // Honest banner. Fails closed to UNAVAILABLE when the endpoint gave us nothing (e.g. not built yet).
  let banner: React.ReactNode = null;
  if (reference) {
    banner = <StatusBanner variant="reference" text="REFERENCE SAMPLE" detail="Illustrative only — not live, not counted." />;
  } else if (status === 'unavailable') {
    banner = (
      <StatusBanner
        variant="unavailable"
        text="MOTION API UNAVAILABLE"
        detail={
          motion.lastGoodAt
            ? `last good ${ageLabel} · ${motion.error ?? 'endpoint not responding'}`
            : `endpoint not responding${motion.error ? ` · ${motion.error}` : ''} — this tranche does not implement the aggregate endpoint`
        }
      />
    );
  } else if (status === 'stale') {
    banner = <StatusBanner variant="stale" text="MOTION DATA STALE" detail={`last good ${ageLabel}${motion.error ? ` · ${motion.error}` : ''}`} />;
  } else if (status === 'loading' && !snapshot) {
    banner = <StatusBanner variant="loading" text="LOADING MOTION…" />;
  } else if (status === 'live') {
    banner = <StatusBanner variant="live" text="MOTION LIVE" detail={`updated ${ageLabel} · next in ${motion.nextRefreshS ?? '—'}s`} />;
  }

  return (
    <section className="at-motion" aria-labelledby="motion-heading" data-testid="active-trader-motion">
      <div className="at-motion__bar">
        <h2 id="motion-heading" className="at-motion__title">Live motion <small>aggregate read · one request per cycle</small></h2>
        {/* Deterministic test seams — number of aggregate requests fired and the current fetch status. */}
        <span className="at-motion__seam mono" data-testid="motion-request-count">{motion.requestCount}</span>
        <span className="at-motion__seam-hidden" data-testid="motion-status" aria-hidden="true">{status}</span>
      </div>

      {banner}

      {/* When we have nothing at all (endpoint absent), fail closed — do not render fabricated panels. */}
      {!snapshot ? (
        status === 'loading'
          ? null
          : (
            <div className="at-motion__closed">
              No motion snapshot available. The aggregate endpoint <code>GET /api/v3/active-trader/motion</code> is
              not implemented at this base; the UI is failing closed rather than inventing live values.
            </div>
          )
      ) : (
        <>
          {snapshot.contractOk === false && (
            <StatusBanner variant="stale" text="UNEXPECTED CONTRACT" detail={`payload contract "${snapshot.contract || 'missing'}" ≠ expected`} />
          )}
          <T2CapacityIndicator
            t2={snapshot.t2}
            pushPrimary={snapshot.pushPrimary}
            maxPullFallbacksPerMinute={snapshot.maxPullFallbacksPerMinute}
            degraded={degraded}
          />
          <div className="at-motion__grid">
            <MotionRail
              decisions={snapshot.t2.decisions}
              leases={snapshot.t2.leases}
              selectedSymbol={selectedSymbol}
              onSelect={setSelectedSymbol}
              ageLabel={ageLabel}
              degraded={degraded}
            />
            <PositionMomentumPanel positions={snapshot.positions} degraded={degraded} />
          </div>
        </>
      )}
    </section>
  );
}

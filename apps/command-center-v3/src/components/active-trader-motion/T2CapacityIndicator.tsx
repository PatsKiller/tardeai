// T2 capacity: normal operating usage vs provider ceiling, shown SEPARATELY. The provider hard cap
// is a safety ceiling, never a utilization target — it is labelled "ceiling", never "target".

import type { MotionT2 } from '../../pages/activeTrader.types';
import { MOTION_UNKNOWN } from './motionFormat';

type Props = {
  t2: MotionT2;
  pushPrimary: boolean;
  maxPullFallbacksPerMinute: number | null;
  degraded: boolean; // true when the snapshot is stale/unavailable — caps are shown but flagged not-live
};

function capText(value: number | null): string {
  return value == null ? MOTION_UNKNOWN : String(value);
}

export default function T2CapacityIndicator({ t2, pushPrimary, maxPullFallbacksPerMinute, degraded }: Props) {
  const inUse = t2.leases.length;
  const operating = t2.operatingCap;
  const ceiling = t2.providerHardCap;
  const overOperating = operating != null && inUse > operating;

  return (
    <div className="at-motion-cap" role="group" aria-label="T2 execution capacity">
      <div className={`at-motion-cap__main${overOperating ? ' is-over' : ''}`}>
        <span className="at-motion-cap__label">T2</span>
        <span className="at-motion-cap__usage">
          <strong>{degraded ? MOTION_UNKNOWN : inUse}</strong> / {capText(operating)} operating
        </span>
        <span className="at-motion-cap__sep" aria-hidden="true">·</span>
        <span className="at-motion-cap__ceiling" title="Provider safety ceiling — never a target">
          {capText(ceiling)} provider ceiling
        </span>
      </div>
      <div className="at-motion-cap__meta">
        <span
          className={`at-chip at-chip--${pushPrimary ? 'pass' : 'warning'}`}
          title="Push delivery is primary; pull is a bounded fallback"
        >
          {pushPrimary ? 'PUSH PRIMARY' : 'PUSH NOT PRIMARY'}
        </span>
        <span className="at-motion-cap__budget">
          pull fallback budget: {maxPullFallbacksPerMinute == null ? MOTION_UNKNOWN : `${maxPullFallbacksPerMinute}/min`}
        </span>
      </div>
    </div>
  );
}

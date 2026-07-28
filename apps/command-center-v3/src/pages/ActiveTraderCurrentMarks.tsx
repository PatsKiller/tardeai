type Mark = {
  symbol: string;
  bid?: number | null;
  ask?: number | null;
  last?: number | null;
  source?: string | null;
  provider_at?: string | null;
  received_at?: string | null;
  age_ms?: number | null;
  stale?: boolean;
  available?: boolean;
  fallback?: boolean;
};

type Payload = {
  generated_at?: string;
  snapshot_fresh?: boolean;
  snapshot_reason?: string;
  marks?: Mark[];
};

const px = (value?: number | null) => value == null ? '—' : value.toFixed(2);
const age = (value?: number | null) => value == null ? 'age unknown' : value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(1)}s`;
const clock = (value?: string | null) => value
  ? new Date(value).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'America/New_York' })
  : '—';

export default function ActiveTraderCurrentMarks({ symbols, payload }: { symbols: string[]; payload?: Payload }) {
  if (symbols.length === 0) return null;
  const bySymbol = new Map((payload?.marks ?? []).map(mark => [mark.symbol, mark]));
  return (
    <section className="at-panel" aria-labelledby="current-scanner-marks-title" data-testid="current-scanner-marks">
      <header className="at-panel__header">
        <div>
          <h2 id="current-scanner-marks-title">Current scanner marks</h2>
          <small style={{ color: 'var(--text3)' }}>
            Fast timestamped marks are separate from the immutable scan-time price shown on each scanner card.
          </small>
        </div>
        <span className="at-chip at-chip--context" title={payload?.snapshot_reason ?? 'loading'}>
          {payload?.snapshot_fresh ? 'GATEWAY SNAPSHOT FRESH' : 'APPROVED FALLBACK / WAITING'}
        </span>
      </header>
      <div style={{ display: 'grid', gap: 8 }}>
        {symbols.map(symbol => {
          const mark = bySymbol.get(symbol);
          const unavailable = !mark?.available;
          const stale = Boolean(mark?.stale);
          return (
            <div key={symbol} data-testid={`current-mark-${symbol}`}
              style={{ display: 'grid', gridTemplateColumns: 'minmax(64px,.7fr) repeat(3,minmax(72px,1fr)) minmax(150px,1.6fr)', gap: 10, alignItems: 'center', borderTop: '1px solid var(--border)', padding: '9px 0' }}>
              <strong style={{ color: 'var(--text0)' }}>{symbol}</strong>
              <span><small style={{ color: 'var(--text3)', display: 'block' }}>last</small>{px(mark?.last)}</span>
              <span><small style={{ color: 'var(--text3)', display: 'block' }}>bid</small>{px(mark?.bid)}</span>
              <span><small style={{ color: 'var(--text3)', display: 'block' }}>ask</small>{px(mark?.ask)}</span>
              <span style={{ color: unavailable || stale ? 'var(--warning)' : 'var(--text2)', fontSize: 12 }}>
                {unavailable ? 'UNAVAILABLE' : stale ? 'STALE' : (mark?.source ?? 'unknown source')}
                <small style={{ display: 'block', color: 'var(--text3)' }}>
                  received {clock(mark?.received_at)} ET · {age(mark?.age_ms)}{mark?.fallback ? ' · fallback' : ''}
                </small>
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubStrip } from '../lib/terminalHubChrome'
import { BB } from '../lib/watchlistTerminalTokens'

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

export default function ScreenerFindsHub({ onDrill, embedded }: Props) {
  const [terminalUi] = useTerminalUi()
  const { data } = useApi<any>('/api/v2/screener-finds/candidates', 60_000)
  const count = data?.count ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: terminalUi ? 6 : 12 }}>
      <div className="cc-panel" style={hubStrip(terminalUi)}>
        {terminalUi ? (
          <>
            <span style={{ fontWeight: 800, color: BB.amber, letterSpacing: '.06em' }}>SCREENER FINDS</span>
            {' · '}{count} CIO-qualified · auto-research lane
            {data?.track_record?.n != null && ` · Finds last 90d: ${data.track_record.n} · 21d α median ${data.track_record.median_alpha_21d != null ? `${data.track_record.median_alpha_21d > 0 ? '+' : ''}${data.track_record.median_alpha_21d}%` : 'n/a'} (n=${data.track_record.scored}) · ${data.track_record.converted} converted to proposals`}
          </>
        ) : (
          <>
            <div style={{ fontSize: 13, fontWeight: 800, color: '#f8fafc' }}>🔍 Screener Finds — Auto-Research lane</div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, lineHeight: 1.45 }}>
              {count} active · Finviz screener discoveries with auto-research briefs ·
              stays visible while CIO is <b style={{ color: '#22c55e' }}>BUY</b>, <b style={{ color: '#22c55e' }}>STRONG_BUY</b>, <b style={{ color: '#60a5fa' }}>ADD</b>, or <b style={{ color: '#60a5fa' }}>ADD_ON_PULLBACK</b> ·
              full watchlist cards below
            </div>
          </>
        )}
      </div>
      <WatchlistHub onDrill={onDrill} embedded={embedded ?? true} lane="screener_finds" />
          {/* Watch Desk v3 (D1): the CIO-only lane is structurally thin — full screener+discovery emissions below, evidence attached */}
      {(data?.wide_finds?.length ?? 0) > 0 && (
        <div className="cc-panel" style={{ padding: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.06em', color: 'var(--text3)', marginBottom: 6 }}>
            ALL FINDS (90d) — screener + discovery emissions · CIO-qualified subset highlighted above
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 360, overflowY: 'auto' }}>
            {data.wide_finds.slice(0, 60).map((f: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 10, fontSize: 11, padding: '3px 6px', borderBottom: '1px solid var(--border)', alignItems: 'baseline' }}>
                <span style={{ fontFamily: 'monospace', fontWeight: 800, minWidth: 52 }}>{f.symbol}</span>
                <span style={{ color: 'var(--text3)', minWidth: 92 }}>{f.source_type}</span>
                <span style={{ color: 'var(--text3)', minWidth: 78 }}>{f.emitted_on}</span>
                <span style={{ minWidth: 96, color: f.alpha_21d == null ? 'var(--text3)' : f.alpha_21d > 0 ? '#34d399' : '#f87171' }}>
                  {f.alpha_21d != null ? `21d α ${f.alpha_21d > 0 ? '+' : ''}${f.alpha_21d}%` : (f.verdict || 'pending')}
                </span>
                {f.proposed && <span style={{ color: '#7dd3fc' }}>→ proposal</span>}
              </div>
            ))}
          </div>
        </div>
      )}
</div>
  )
}
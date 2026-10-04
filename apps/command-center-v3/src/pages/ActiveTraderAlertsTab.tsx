import { useMemo, useState } from 'react';
import { useApi } from '../hooks/useApi';
import './activeTrader.css';

// Active Trader Phase 1 — Level 2–confirmed scalp alerts (GET /api/v3/active-trader/alerts).
// Read-only: the feed shows what the engine decided (alert or veto, with the moomoo L2 and tape
// evidence that decided it), what went to Telegram, and how each decision scored afterwards.
// Advisory only — there is no order control anywhere on this tab.

type L2 = { source?: string; levels?: number; depth_ratio?: number | null; spread_bps?: number | null; age_s?: number | null; ts_source?: string | null };
type Tape = { source?: string; prints?: number; buy_ratio?: number | null; age_s?: number | null };
type Score = Record<string, { mfe_r?: number | null; mae_r?: number | null; mfe_pct?: number | null; mae_pct?: number | null }>;
type Decision = {
  id: string; at?: string | null; symbol?: string; kind?: 'ARMED' | 'TRIGGERED'; verdict?: 'ALERT' | 'VETO';
  veto_reasons: string[]; sent: boolean; mode?: string; last?: number | null; entry?: number | null; stop?: number | null;
  r?: number | null; float_mm?: number | null; rvol?: number | null; ign?: number | null; lane?: string | null;
  setup?: string | null; quote_age_s?: number | null; l2: L2; tape?: Tape | null; l2_compare?: L2 | null; score?: Score | null;
};
type Feed = {
  contract?: string; session_date?: string; latest_session_with_decisions?: string | null; mode?: 'send' | 'shadow';
  delivery?: string; generated_at?: string;
  engine?: { window_et?: [string, string]; last_pass_at?: string | null; last_pass_age_s?: number | null; symbols_scored?: number | null;
             last_pass?: { evaluated?: number; alerts?: number; vetoes?: number; sent?: number } | null };
  l2?: { source?: string; levels_proven?: number; proven_at?: string; compare?: string };
  rules?: Record<string, string>;
  counts?: { triggered_alerts?: number; armed_alerts?: number; vetoes?: number; sent?: number; decisions?: number };
  veto_reasons?: Record<string, number>;
  precision?: Record<string, Record<string, { n: number; hit: number; precision: number | null }>>;
  scored_total?: number;
  decisions?: Decision[];
};

const REASON_TEXT: Record<string, string> = {
  QUOTE_STALE: 'quote stale', BOOK_STALE: 'book stale', BOOK_MISSING: 'no L2 book', BOOK_EMPTY: 'book empty',
  BOOK_CROSSED: 'book crossed', SPREAD_WIDE: 'spread too wide', L2_ASK_HEAVY: 'sellers heavier in book',
  TAPE_MISSING: 'no tape', TAPE_STALE: 'tape stale', TAPE_THIN: 'too few prints', TAPE_SELLERS: 'tape selling',
  NO_STOP_REF: 'no valid stop', COOLDOWN: 'cooldown', RATE_LIMIT: 'hourly cap',
};

const n = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d));
const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : `${Math.round(v * 100)}%`);
const timeOf = (iso?: string | null) => (iso ? iso.slice(11, 19) : '—');
const ago = (s?: number | null) => (s == null ? 'never' : s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`);

export default function ActiveTraderAlertsTab() {
  const { data, error, loading } = useApi<Feed>('/api/v3/active-trader/alerts?limit=150', 10_000);
  const [filter, setFilter] = useState<'all' | 'alerts' | 'vetoes'>('all');
  const decisions = useMemo(() => {
    const all = data?.decisions ?? [];
    return filter === 'alerts' ? all.filter(d => d.verdict === 'ALERT') : filter === 'vetoes' ? all.filter(d => d.verdict === 'VETO') : all;
  }, [data, filter]);

  if (loading && !data) return <div className="active-trader-page at-alerts"><div className="at-fullstate">Loading alert feed…</div></div>;
  if (error && !data) return <div className="active-trader-page at-alerts"><div className="at-fullstate at-fullstate--fail">Alert feed unavailable: {String(error)}</div></div>;

  const c = data?.counts ?? {};
  const live = data?.mode === 'send';
  const eng = data?.engine;
  const engineFresh = eng?.last_pass_age_s != null && eng.last_pass_age_s < 420;
  const p5 = data?.precision?.['5m'] ?? {};
  const reasons = Object.entries(data?.veto_reasons ?? {});
  const maxReason = Math.max(1, ...reasons.map(([, v]) => v));

  return (
    <div className="active-trader-page at-alerts" data-testid="at-alerts">
      <header className="at-alerts__hero">
        <div>
          <h1>Scalp alerts <small>Level 2 confirmed</small></h1>
          <p>The engine watches the momentum scanner's names, confirms on the moomoo order book and tape, and tells you when one is ready. You place every trade yourself.</p>
        </div>
        <div className="at-inline at-wrap at-alerts__badges">
          <span className={`at-chip ${live ? 'at-chip--pass' : 'at-chip--warning'}`} data-testid="at-alerts-mode">
            {live ? '● LIVE → Telegram' : '○ SHADOW · journal only'}
          </span>
          <span className={`at-chip ${engineFresh ? 'at-chip--pass' : 'at-chip--context'}`} title="Last engine pass (runs every 5 min, 09:30–11:55 ET)">
            engine {engineFresh ? 'running' : 'idle'} · {ago(eng?.last_pass_age_s)}
          </span>
          <span className="at-chip at-chip--lane" title={data?.l2?.compare}>
            L2 {data?.l2?.source?.split(' ')[0] ?? 'moomoo'} · {data?.l2?.levels_proven ?? 60} levels verified
          </span>
        </div>
      </header>

      <section className="at-alerts__kpis" aria-label="Today">
        <Kpi label="Time to buy" value={c.triggered_alerts ?? 0} tone="green" hint="TRIGGERED alerts today" />
        <Kpi label="Heads-up" value={c.armed_alerts ?? 0} tone="amber" hint="ARMED alerts today" />
        <Kpi label="Sent to Telegram" value={c.sent ?? 0} tone="blue" hint={live ? 'delivered' : 'shadow mode — nothing sent'} />
        <Kpi label="Vetoed" value={c.vetoes ?? 0} tone="muted" hint="blocked by a check (reasons below)" />
        <Kpi label="5-min hit rate" value={precisionText(p5['TRIGGERED:ALERT'])} tone="green" hint="TRIGGERED alerts that reached +1R within 5 min" />
      </section>

      <div className="at-alerts__grid">
        <section className="at-panel at-alerts__feed" aria-labelledby="at-feed-title">
          <header className="at-panel__header">
            <h2 id="at-feed-title">Decisions <small>{data?.session_date}</small></h2>
            <div className="at-inline" role="group" aria-label="Filter">
              {(['all', 'alerts', 'vetoes'] as const).map(f => (
                <button key={f} type="button" className={`at-filter${filter === f ? ' is-on' : ''}`} onClick={() => setFilter(f)}>{f}</button>
              ))}
            </div>
          </header>
          {decisions.length === 0 ? (
            <div className="at-empty-card" data-testid="at-alerts-empty">
              <strong>No decisions {filter === 'all' ? 'yet today' : `(${filter})`}.</strong>
              <p>The engine scores the scanner's names every 5 minutes from {eng?.window_et?.[0] ?? '09:30'} to {eng?.window_et?.[1] ?? '11:55'} ET.
                {live ? ' Alerts that pass every check go straight to Telegram and appear here.' : ' In shadow mode they are recorded here only.'}</p>
              {data?.latest_session_with_decisions && data.latest_session_with_decisions !== data.session_date && (
                <p>Last session with decisions: {data.latest_session_with_decisions}.</p>
              )}
            </div>
          ) : (
            <ol className="at-alerts__list">
              {decisions.map(d => <DecisionRow key={d.id} d={d} />)}
            </ol>
          )}
        </section>

        <aside className="at-alerts__side">
          <section className="at-panel">
            <header className="at-panel__header"><h2>Why signals were blocked</h2></header>
            <div className="at-alerts__reasons">
              {reasons.length === 0 && <div className="at-source">No vetoes today.</div>}
              {reasons.map(([k, v]) => (
                <div key={k} className="at-alerts__reason">
                  <span>{REASON_TEXT[k] ?? k}</span>
                  <div><i style={{ width: `${(v / maxReason) * 100}%` }} /></div>
                  <b>{v}</b>
                </div>
              ))}
            </div>
          </section>

          <section className="at-panel">
            <header className="at-panel__header"><h2>Track record <small>{data?.scored_total ?? 0} scored</small></h2></header>
            <table className="at-alerts__prec">
              <thead><tr><th>reached +1R within</th><th>1 min</th><th>5 min</th><th>15 min</th></tr></thead>
              <tbody>
                {['TRIGGERED:ALERT', 'ARMED:ALERT', 'TRIGGERED:VETO'].map(k => (
                  <tr key={k}>
                    <td>{k === 'TRIGGERED:ALERT' ? 'Time-to-buy alerts' : k === 'ARMED:ALERT' ? 'Heads-up alerts' : 'Vetoed triggers'}</td>
                    {['1m', '5m', '15m'].map(w => <td key={w}>{precisionText(data?.precision?.[w]?.[k])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="at-alerts__note">Every decision — alerts and vetoes — is scored 15 minutes later from minute bars. Vetoed triggers are scored too, so you can see what the checks cost.</p>
          </section>

          <section className="at-panel">
            <header className="at-panel__header"><h2>Rules in force</h2></header>
            <dl className="at-alerts__rules">
              {Object.entries(data?.rules ?? {}).map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
            </dl>
            <p className="at-alerts__note">Advisory only. No order path exists in this engine; stale data never alerts.</p>
          </section>
        </aside>
      </div>
    </div>
  );
}

function precisionText(p?: { n: number; hit: number; precision: number | null }) {
  if (!p || !p.n) return '—';
  return `${pct(p.precision)} (${p.hit}/${p.n})`;
}

function Kpi({ label, value, tone, hint }: { label: string; value: number | string; tone: 'green' | 'amber' | 'blue' | 'muted'; hint: string }) {
  return (
    <div className={`at-kpi at-kpi--${tone}`} title={hint}>
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{hint}</span>
    </div>
  );
}

function DecisionRow({ d }: { d: Decision }) {
  const alert = d.verdict === 'ALERT';
  const trig = d.kind === 'TRIGGERED';
  const s5 = d.score?.['5m'];
  return (
    <li className={`at-alerts__row ${alert ? (trig ? 'is-trigger' : 'is-armed') : 'is-veto'}`} data-testid="at-alert-row">
      <div className="at-alerts__row-head">
        <span className="at-alerts__sym">{d.symbol}</span>
        <span className={`at-chip ${alert ? (trig ? 'at-chip--pass' : 'at-chip--warning') : 'at-chip--fail'}`}>
          {alert ? (trig ? 'TIME TO BUY' : 'HEADS-UP') : `VETO · ${d.kind === 'TRIGGERED' ? 'trigger' : 'armed'}`}
        </span>
        {d.sent && <span className="at-chip at-chip--lane" title="Delivered to Telegram">✓ Telegram</span>}
        <time className="mono">{timeOf(d.at)} ET</time>
      </div>
      {!alert && d.veto_reasons.length > 0 && (
        <div className="at-inline at-wrap at-alerts__vetoes">{d.veto_reasons.map(r => <span key={r} className="at-chip at-chip--context">{REASON_TEXT[r] ?? r}</span>)}</div>
      )}
      <dl className="at-alerts__levels">
        <div><dt>last</dt><dd>{n(d.last)}</dd></div>
        <div><dt>entry</dt><dd>{n(d.entry)}</dd></div>
        <div><dt>stop</dt><dd>{n(d.stop)}</dd></div>
        <div><dt>R</dt><dd>{n(d.r)}</dd></div>
        <div><dt>float</dt><dd>{d.float_mm == null ? '—' : `${n(d.float_mm, 1)}M`}</dd></div>
        <div><dt>RVOL</dt><dd>{d.rvol == null ? '—' : `${n(d.rvol, 1)}x`}</dd></div>
      </dl>
      <div className="at-alerts__evidence">
        <span title={`book age ${n(d.l2?.age_s, 0)}s (${d.l2?.ts_source ?? 'n/a'})`}>
          <b>L2</b> {d.l2?.levels ?? 0} lv · bid/ask {n(d.l2?.depth_ratio)}x · spread {n(d.l2?.spread_bps, 0)} bps
        </span>
        {d.tape && <span><b>tape</b> {pct(d.tape.buy_ratio)} buys · {d.tape.prints ?? 0} prints</span>}
        {d.l2_compare && d.l2_compare.levels ? <span className="at-source">Schwab {d.l2_compare.levels} lv · {n(d.l2_compare.depth_ratio)}x</span> : null}
        {d.setup && <span className="at-source">{d.setup}</span>}
        {s5 && <span className={`at-alerts__score ${(s5.mfe_r ?? 0) >= 1 ? 'is-hit' : ''}`}>5m: +{n(s5.mfe_r, 1)}R / −{n(s5.mae_r, 1)}R</span>}
      </div>
    </li>
  );
}

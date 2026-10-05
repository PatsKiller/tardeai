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
type Exit = { price?: number | null; at?: string | null; pct?: number | null; r?: number | null; min_after?: number | null; reason?: string };
type Outcome = {
  status?: string; result?: 'WORKED' | 'STOPPED' | 'SAME_BAR' | 'NO_TOUCH' | 'AT_OR_BELOW_STOP'; fill?: number | null; fill_source?: string;
  stop?: number | null; risk?: number | null; risk_pct?: number | null; first_touch_at?: string | null; horizon_bars?: number;
  best_exit?: Exit | null; rule_exit?: Exit | null;
};
type Supply = { ask_size_inside?: number; bid_size_inside?: number; ask_shares_near?: number; ask_levels_near?: number; near_pct?: number;
  ask_wall_price?: number; ask_wall_size?: number; ask_wall_x_median?: number | null };
type Trip = { symbol: string; account?: string; qty: number; buy_at?: string | null; buy_price: number; sell_at?: string | null;
  sell_price?: number | null; pnl?: number | null; pnl_pct?: number | null; held_s?: number | null; source: 'active_trader' | 'untagged';
  alert?: { id: string; kind?: string; at?: string | null; ask_at_alert?: number | null; last_at_alert?: number | null; stop?: number | null; lag_s?: number } | null };
type OutcomeAgg = { n: number; WORKED: number; STOPPED: number; NO_TOUCH: number; AT_OR_BELOW_STOP: number; worked_rate?: number | null;
  avg_best_exit_pct?: number | null; avg_rule_exit_pct?: number | null };
type Decision = {
  id: string; at?: string | null; symbol?: string; kind?: 'ARMED' | 'TRIGGERED'; verdict?: 'ALERT' | 'VETO';
  veto_reasons: string[]; sent: boolean; mode?: string; last?: number | null; entry?: number | null; stop?: number | null;
  r?: number | null; float_mm?: number | null; rvol?: number | null; ign?: number | null; lane?: string | null;
  setup?: string | null; quote_age_s?: number | null; l2: L2; tape?: Tape | null; l2_compare?: L2 | null; score?: Score | null;
  supply?: Supply | null; outcome?: Outcome | null; ts_epoch?: number | null;
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
  scored_session?: number;
  outcomes?: { session?: Record<string, OutcomeAgg>; all?: Record<string, OutcomeAgg>; touch_min?: number; horizon_min?: number; pending?: number };
  sessions?: string[];
  your_trades?: Trip[];
  decisions?: Decision[];
};

type Kind = 'all' | 'buy' | 'heads' | 'veto' | 'traded';
type Res = 'any' | 'WORKED' | 'STOPPED' | 'NO_TOUCH' | 'AT_OR_BELOW_STOP' | 'pending';
const KIND_LABEL: Record<Kind, string> = { all: 'All', buy: 'Time to buy', heads: 'Heads-up', veto: 'Vetoed', traded: 'You traded' };
const RES_LABEL: Record<Exclude<Res, 'any'>, string> = {
  WORKED: '+1R before stop', STOPPED: 'stop hit first', NO_TOUCH: 'neither in window', AT_OR_BELOW_STOP: 'already through stop', pending: 'not scored yet',
};
const resultOf = (d: Decision): Exclude<Res, 'any'> => {
  const r = d.outcome?.result;
  return !r ? 'pending' : r === 'SAME_BAR' ? 'STOPPED' : r;
};

const REASON_TEXT: Record<string, string> = {
  QUOTE_STALE: 'quote stale', BOOK_STALE: 'book stale', BOOK_MISSING: 'no L2 book', BOOK_EMPTY: 'book empty',
  BOOK_CROSSED: 'book crossed', SPREAD_WIDE: 'spread too wide', L2_ASK_HEAVY: 'sellers heavier in book',
  TAPE_MISSING: 'no tape', TAPE_STALE: 'tape stale', TAPE_THIN: 'too few prints', TAPE_SELLERS: 'tape selling',
  NO_STOP_REF: 'no valid stop', COOLDOWN: 'cooldown', RATE_LIMIT: 'hourly cap', PRICE_AT_OR_BELOW_STOP: 'price already through stop',
};

const n = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d));
const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : `${Math.round(v * 100)}%`);
const timeOf = (iso?: string | null) => (iso ? iso.slice(11, 19) : '—');
const sgn = (v: number | null | undefined, d = 2, unit = '%') => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}${unit}`);
const sh = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : Math.round(v).toLocaleString());
const hm = (iso?: string | null) => (iso ? iso.slice(11, 16) : '—');
const ago = (s?: number | null) => (s == null ? 'never' : s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`);

export default function ActiveTraderAlertsTab() {
  const [day, setDay] = useState<string>('');
  const { data, error, loading } = useApi<Feed>(`/api/v3/active-trader/alerts?limit=500${day ? `&session_date=${day}` : ''}`, 10_000);
  const [kind, setKind] = useState<Kind>('all');
  const [sym, setSym] = useState<string>('');
  const [res, setRes] = useState<Res>('any');
  const trips = useMemo(() => data?.your_trades ?? [], [data]);
  const tradedIds = useMemo(() => new Set(trips.map(t => t.alert?.id).filter(Boolean) as string[]), [trips]);
  const symbols = useMemo(() => Array.from(new Set((data?.decisions ?? []).map(d => d.symbol).filter(Boolean) as string[])).sort(), [data]);
  const decisions = useMemo(() => (data?.decisions ?? []).filter(d => {
    const alert = d.verdict === 'ALERT';
    if (kind === 'buy' && !(alert && d.kind === 'TRIGGERED')) return false;
    if (kind === 'heads' && !(alert && d.kind === 'ARMED')) return false;
    if (kind === 'veto' && alert) return false;
    if (kind === 'traded' && !tradedIds.has(d.id)) return false;
    if (sym && d.symbol !== sym) return false;
    if (res !== 'any' && resultOf(d) !== res) return false;
    return true;
  }), [data, kind, sym, res, tradedIds]);
  const filtered = kind !== 'all' || sym !== '' || res !== 'any';

  if (loading && !data) return <div className="active-trader-page at-alerts"><div className="at-fullstate">Loading alert feed…</div></div>;
  if (error && !data) return <div className="active-trader-page at-alerts"><div className="at-fullstate at-fullstate--fail">Alert feed unavailable: {String(error)}</div></div>;

  const c = data?.counts ?? {};
  const live = data?.mode === 'send';
  const eng = data?.engine;
  const engineFresh = eng?.last_pass_age_s != null && eng.last_pass_age_s < 420;
  const os = data?.outcomes?.session ?? {};
  const buyAgg = os['TRIGGERED:ALERT'];
  const tagged = trips.filter(t => t.source === 'active_trader');
  const tripPnl = trips.reduce((a, t) => a + (t.pnl ?? 0), 0);
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
        <Kpi label="Time to buy" value={c.triggered_alerts ?? 0} tone="green" tip="TRIGGERED alerts today" />
        <Kpi label="Heads-up" value={c.armed_alerts ?? 0} tone="amber" tip="ARMED alerts today" />
        <Kpi label="Sent to Telegram" value={c.sent ?? 0} tone="blue" tip={live ? 'delivered' : 'shadow mode — nothing sent'} />
        <Kpi label="Vetoed" value={c.vetoes ?? 0} tone="muted" tip="blocked by a check (reasons below)" />
        <Kpi label="Time to buy worked" value={buyAgg?.n ? `${buyAgg.WORKED}/${buyAgg.n}` : '—'} tone="green"
          tip={`reached +1R from the ask at the alert before the stop, within ${data?.outcomes?.touch_min ?? 15} min`} />
        <Kpi label="Your trades" value={trips.length ? `${trips.length} · ${sgn(tripPnl, 2, '')}` : '0'} tone="blue"
          tip={`${tagged.length} after an alert · from your broker fills`} />
      </section>

      <div className="at-alerts__grid">
        <section className="at-panel at-alerts__feed" aria-labelledby="at-feed-title">
          <header className="at-panel__header">
            <h2 id="at-feed-title">Decisions <small>{data?.session_date} · {decisions.length} of {data?.decisions?.length ?? 0}</small></h2>
            <label className="at-alerts__select">
              <span>Day</span>
              <select id="at-alerts-day" value={day || data?.session_date || ''} onChange={e => setDay(e.target.value)}>
                {(data?.sessions?.length ? data.sessions : [data?.session_date ?? '']).map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          </header>
          <div className="at-alerts__filters" data-testid="at-alerts-filters">
            <div className="at-inline at-wrap" role="group" aria-label="Kind">
              {(Object.keys(KIND_LABEL) as Kind[]).map(f => (
                <button key={f} type="button" className={`at-filter${kind === f ? ' is-on' : ''}`} aria-pressed={kind === f} onClick={() => setKind(f)}>{KIND_LABEL[f]}</button>
              ))}
            </div>
            <div className="at-inline at-wrap">
              <label className="at-alerts__select"><span>Symbol</span>
                <select id="at-alerts-symbol" value={sym} onChange={e => setSym(e.target.value)}>
                  <option value="">all</option>
                  {symbols.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              <label className="at-alerts__select"><span>Outcome</span>
                <select id="at-alerts-outcome" value={res} onChange={e => setRes(e.target.value as Res)}>
                  <option value="any">any</option>
                  {(Object.keys(RES_LABEL) as Exclude<Res, 'any'>[]).map(k => <option key={k} value={k}>{RES_LABEL[k]}</option>)}
                </select>
              </label>
              {filtered && <button type="button" className="at-filter" onClick={() => { setKind('all'); setSym(''); setRes('any'); }}>Clear</button>}
            </div>
          </div>
          {decisions.length === 0 ? (
            <div className="at-empty-card" data-testid="at-alerts-empty">
              <strong>{filtered ? 'No decisions match these filters.' : 'No decisions yet today.'}</strong>
              <p>The engine scores the scanner's names every 5 minutes from {eng?.window_et?.[0] ?? '09:30'} to {eng?.window_et?.[1] ?? '11:55'} ET.
                {live ? ' Alerts that pass every check go straight to Telegram and appear here.' : ' In shadow mode they are recorded here only.'}</p>
              {data?.latest_session_with_decisions && data.latest_session_with_decisions !== data.session_date && (
                <p>Last session with decisions: {data.latest_session_with_decisions}.</p>
              )}
            </div>
          ) : (
            <ol className="at-alerts__list">
              {decisions.map(d => <DecisionRow key={d.id} d={d} trips={trips.filter(t => t.alert?.id === d.id)} />)}
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

          <section className="at-panel" data-testid="at-your-trades">
            <header className="at-panel__header"><h2>Your trades <small>{data?.session_date}</small></h2></header>
            <div className="at-alerts__trips">
              {trips.length === 0 && <div className="at-source">No fills on these symbols this day.</div>}
              {trips.map((t, i) => (
                <div key={`${t.symbol}-${t.buy_at}-${i}`} className={`at-alerts__trip ${t.source === 'active_trader' ? 'is-tagged' : ''}`}>
                  <div className="at-inline at-wrap">
                    <b>{t.symbol}</b>
                    <span className={`at-chip ${t.source === 'active_trader' ? 'at-chip--pass' : 'at-chip--context'}`}>
                      {t.source === 'active_trader' ? `after ${t.alert?.kind === 'TRIGGERED' ? 'time-to-buy' : 'heads-up'} ${hm(t.alert?.at)}` : 'untagged'}
                    </span>
                    <span className={`mono ${(t.pnl ?? 0) >= 0 ? 'is-up' : 'is-down'}`}>{t.pnl == null ? 'open' : sgn(t.pnl, 2, '')}</span>
                  </div>
                  <div className="at-source">
                    {sh(t.qty)} sh · bought {n(t.buy_price)} {hm(t.buy_at)}{t.sell_at ? ` · sold ${n(t.sell_price)} ${hm(t.sell_at)} · held ${t.held_s ?? '—'}s` : ''}
                  </div>
                  {t.alert && (
                    <div className="at-source">
                      {Math.floor((t.alert.lag_s ?? 0) / 60)}m{(t.alert.lag_s ?? 0) % 60}s after the alert · ask then {n(t.alert.ask_at_alert)} → you paid {n(t.buy_price)}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className="at-alerts__note">From your broker fills (read-only). A trade is tagged to the latest alert sent on that symbol in the 20 minutes before your buy.</p>
          </section>

          <section className="at-panel">
            <header className="at-panel__header"><h2>Track record <small>{data?.scored_session ?? 0} scored · {data?.outcomes?.pending ?? 0} pending</small></h2></header>
            <TrackTable rows={data?.outcomes?.session ?? {}} caption="This day" />
            <TrackTable rows={data?.outcomes?.all ?? {}} caption="All days" />
            <p className="at-alerts__note">
              Each decision is scored as if you bought at the ask when it was sent, with the engine's stop. Worked = +1R before the stop within {data?.outcomes?.touch_min ?? 15} min;
              a minute that touches both counts as stopped. Best exit is hindsight (the high within {data?.outcomes?.horizon_min ?? 30} min); the rule exit sells on the
              stop, the first 1-min close below the prior bar's low, or at {data?.outcomes?.touch_min ?? 15} min. Bars are Alpaca IEX minute bars. Vetoes are scored too.
            </p>
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

function TrackTable({ rows, caption }: { rows: Record<string, OutcomeAgg>; caption: string }) {
  const keys: [string, string][] = [['TRIGGERED:ALERT', 'Time to buy'], ['ARMED:ALERT', 'Heads-up'], ['TRIGGERED:VETO', 'Vetoed trigger'], ['ARMED:VETO', 'Vetoed heads-up']];
  return (
    <table className="at-alerts__prec">
      <caption>{caption}</caption>
      <thead><tr><th>sent as</th><th>worked</th><th>stopped</th><th>neither</th><th>best exit</th><th>rule exit</th></tr></thead>
      <tbody>
        {keys.map(([k, label]) => {
          const a = rows[k];
          return (
            <tr key={k}>
              <td>{label}</td>
              <td>{a?.n ? `${a.WORKED}/${a.n}` : '—'}</td>
              <td>{a?.n ? a.STOPPED + a.AT_OR_BELOW_STOP : '—'}</td>
              <td>{a?.n ? a.NO_TOUCH : '—'}</td>
              <td>{sgn(a?.avg_best_exit_pct)}</td>
              <td>{sgn(a?.avg_rule_exit_pct)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Kpi({ label, value, tone, tip }: { label: string; value: number | string; tone: 'green' | 'amber' | 'blue' | 'muted'; tip: string }) {
  return (
    <div className={`at-kpi at-kpi--${tone}`} title={tip}>
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{tip}</span>
    </div>
  );
}

function DecisionRow({ d, trips }: { d: Decision; trips: Trip[] }) {
  const alert = d.verdict === 'ALERT';
  const trig = d.kind === 'TRIGGERED';
  const o = d.outcome;
  const r = resultOf(d);
  const sup = d.supply;
  return (
    <li className={`at-alerts__row ${alert ? (trig ? 'is-trigger' : 'is-armed') : 'is-veto'}`} data-testid="at-alert-row">
      <div className="at-alerts__row-head">
        <span className="at-alerts__sym">{d.symbol}</span>
        <span className={`at-chip ${alert ? (trig ? 'at-chip--pass' : 'at-chip--warning') : 'at-chip--fail'}`}>
          {alert ? (trig ? 'TIME TO BUY' : 'HEADS-UP') : `VETO · ${d.kind === 'TRIGGERED' ? 'trigger' : 'armed'}`}
        </span>
        {d.sent && <span className="at-chip at-chip--lane" title="Delivered to Telegram">✓ Telegram</span>}
        {trips.map((t, i) => (
          <span key={i} className="at-chip at-chip--pass" title="Your broker fill, tagged to this alert">
            you bought {n(t.buy_price)} {hm(t.buy_at)}{t.pnl != null ? ` · ${sgn(t.pnl, 2, '')}` : ''}
          </span>
        ))}
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
      </div>
      {sup && sup.ask_size_inside != null && (
        <div className="at-alerts__evidence at-alerts__supply">
          <span><b>supply</b> {sh(sup.ask_size_inside)} sh at the ask · {sh(sup.ask_shares_near)} sh within {sup.near_pct ?? 1}% ({sup.ask_levels_near} lv)</span>
          <span><b>wall</b> {sh(sup.ask_wall_size)} @ {n(sup.ask_wall_price)}{sup.ask_wall_x_median ? ` (${n(sup.ask_wall_x_median, 1)}× median)` : ''}</span>
          <span><b>bid</b> {sh(sup.bid_size_inside)} sh</span>
        </div>
      )}
      <div className={`at-alerts__outcome is-${r.toLowerCase()}`} data-testid="at-alert-outcome">
        {!o ? (
          <span>Not scored yet. Scored about {30 + 2} min after the decision.</span>
        ) : o.result === 'AT_OR_BELOW_STOP' ? (
          <span><b>{RES_LABEL[r]}</b> · at the alert the ask {n(o.fill)} was at or below the stop {n(o.stop)} · high within window {n(o.best_exit?.price)} {hm(o.best_exit?.at)}</span>
        ) : (
          <>
            <span><b>{RES_LABEL[r]}</b>{o.first_touch_at ? ` at ${hm(o.first_touch_at)}` : ''} · if bought at the {o.fill_source} {n(o.fill)}, risk {n(o.risk, 3)} ({n(o.risk_pct, 2)}%)</span>
            {o.best_exit && <span>best exit {n(o.best_exit.price)} at {hm(o.best_exit.at)} <em>{sgn(o.best_exit.pct)}</em> ({sgn(o.best_exit.r, 1, 'R')})</span>}
            {o.rule_exit && <span>rule exit {n(o.rule_exit.price)} at {hm(o.rule_exit.at)} <em>{sgn(o.rule_exit.pct)}</em> · {o.rule_exit.reason}</span>}
          </>
        )}
      </div>
    </li>
  );
}

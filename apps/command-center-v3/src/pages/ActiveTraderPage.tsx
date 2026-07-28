import { useEffect, useMemo, useRef, useState } from 'react';
import type { ActiveTraderDataState, ArmingStatus, BrokerAccount, EngineStatus, RoutingDraft, ScalpSignal, ScannerSignal } from './activeTrader.types';
import { MOCK_ACCOUNTS, MOCK_QUEUE, MOCK_SIGNAL } from './activeTrader.mock';
import './activeTrader.css';

type Props = {
  signals?: ScalpSignal[];              // IGN TRIGGER actionable items; undefined = loading; [] = none
  scannerSignals?: ScannerSignal[];     // scanner GO/momentum-route actionable items
  accounts?: BrokerAccount[];
  onOpenStrategies?: () => void;
  dataState?: ActiveTraderDataState;    // honest state from the API (LIVE_DATA/EMPTY_LIVE_QUEUE/API_UNAVAILABLE)
  actionableCount?: number;
  ignTriggerCount?: number;
  scannerGoCount?: number;
  engineStatus?: EngineStatus;
  arming?: ArmingStatus;                 // pre-fire ladder + L2 arm set
  lastIgnSessionDate?: string | null;   // reference only — last alert-worthy IGN session (NOT the queue)
  registryHash?: string | null;
  registryVersion?: string | null;
};

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });

function Chip({ children, tone = 'context', title }: { children: React.ReactNode; tone?: 'pass' | 'fail' | 'context' | 'warning' | 'lane'; title?: string }) {
  return <span className={`at-chip at-chip--${tone}`} title={title}>{children}</span>;
}

const BANNER: Record<ActiveTraderDataState, { text: string; tone: 'pass' | 'warning' | 'fail' | 'context' }> = {
  LIVE_DATA: { text: 'LIVE DATA CONNECTED', tone: 'pass' },
  DATA_STALE: { text: 'DATA STALE', tone: 'warning' },
  EMPTY_LIVE_QUEUE: { text: 'LIVE QUEUE EMPTY', tone: 'context' },
  API_UNAVAILABLE: { text: 'API UNAVAILABLE', tone: 'fail' },
  REFERENCE_SAMPLE: { text: 'REFERENCE SAMPLE · 0 ACTIONABLE', tone: 'warning' },
  LOADING: { text: 'LOADING…', tone: 'context' },
};

function PermissionQueue({ signals, selectedId, onSelect, actionable, reference }: {
  signals: ScalpSignal[]; selectedId: string | null; onSelect: (s: ScalpSignal) => void; actionable: number; reference: boolean;
}) {
  return (
    <section className="at-panel" aria-labelledby="permission-queue-title">
      <header className="at-panel__header">
        <h2 id="permission-queue-title">Permission queue</h2>
        <Chip tone="warning">{reference ? 'REFERENCE SAMPLE · 0 ACTIONABLE' : `manual paper · ${actionable} actionable`}</Chip>
      </header>
      <div className="at-queue">
        {signals.length === 0 && <div className="at-queue-empty">No signals in the live queue.</div>}
        {signals.map(signal => (
          <button key={signal.id} type="button" aria-pressed={signal.id === selectedId}
            className={`at-queue-row at-queue-row--${signal.state.toLowerCase()}${signal.id === selectedId ? ' is-selected' : ''}`}
            onClick={() => onSelect(signal)}>
            <span className="at-queue-row__symbol">{signal.symbol}<small>{signal.last.toFixed(2)}</small></span>
            <span className="at-queue-row__score">{signal.ign}<small>Δ+{signal.ignDelta}</small></span>
            <span className="at-queue-row__body">
              <strong>{signal.state === 'VETOED' ? `VETOED — ${signal.vetoReason ?? 'gate veto'}` : `${signal.state} · ${signal.cohort}`}</strong>
              <small>{signal.primarySetupLabel} · lane {signal.lane} · R {signal.riskPerShare} / {signal.stopBps}bp</small>
            </span>
            <span className="at-queue-row__action">{(signal.state === 'ARMED' || signal.state === 'TRIGGERED') && !reference ? 'Review' : 'no action'}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ActiveTradeCard({ signal, reference, canRoute, onRoute, onDismiss, onOpenStrategies }: {
  signal: ScalpSignal; reference: boolean; canRoute: boolean; onRoute: () => void; onDismiss: () => void; onOpenStrategies?: () => void;
}) {
  const matched = signal.matchedSetupLabels ?? [signal.primarySetupLabel];
  const multi = matched.filter(Boolean).length > 1;
  const t2NeedsBook = signal.dataTier === 'T2';
  const gate = signal.gateDecision ?? (signal.state === 'VETOED' ? 'VETO' : 'PASS');
  const orderControls = ['Buy Bid', 'Sell Ask', 'Buy Ask', 'Sell Bid', 'Buy MKT', 'Sell MKT', 'Cancel All', 'Cancel', 'Reverse', 'Flatten'];
  return (
    <section className="at-panel at-trade-card" aria-labelledby="active-trade-title">
      <header className="at-panel__header at-trade-card__title-row">
        <div><h2 id="active-trade-title">{signal.symbol} <span>{signal.last.toFixed(2)}</span> <em>+{signal.changePct.toFixed(1)}%</em></h2></div>
        <div className="at-inline"><Chip tone="warning">{signal.mode.replace(/_/g, ' ').toLowerCase()}</Chip></div>
      </header>

      {/* separated identity/evidence chips — lane ≠ setup ≠ data-tier ≠ size ≠ gate */}
      <div className="at-inline at-wrap at-identity-rail">
        <Chip tone="lane" title="Alert lane / event class — NOT a setup">LANE: {signal.lane}</Chip>
        <Chip title="Named deterministic setup">SETUP: {signal.primarySetupLabel}</Chip>
        {multi && <Chip tone="warning" title={`Also matched: ${matched.filter(l => l !== signal.primarySetupLabel).join(', ')}`}>MULTI-SETUP</Chip>}
        <Chip title={t2NeedsBook ? 'Order-book/tape tier — fails closed without entitled fresh L2' : 'Data tier'}>
          DATA: {signal.dataTier}{t2NeedsBook ? ' · L2+TAPE' : ''} · {signal.dataFreshness ?? 'FRESH'}
        </Chip>
        <Chip title="Position-size multiplier (separate from data tier)">SIZE TIER: {signal.tierMultiplier.toFixed(2)}x</Chip>
        <Chip title="Market session">SESSION: {signal.session}</Chip>
        <Chip tone={gate === 'PASS' ? 'pass' : gate === 'VETO' ? 'fail' : 'warning'} title="Deterministic execution-gate decision">GATE: {gate}</Chip>
        <button type="button" className="at-link-button" onClick={onOpenStrategies}>Setups &amp; strategy rules</button>
      </div>
      {multi && <div className="at-multi">PRIMARY: <b>{signal.primarySetupLabel}</b> · ALSO MATCHED: {matched.filter(l => l !== signal.primarySetupLabel).join(', ')}</div>}

      <div className="at-evidence-grid">
        <div className="at-ign"><small>IGN</small><strong>{signal.ign}</strong><span>Δ+{signal.ignDelta} / {signal.ignDeltaMinutes}m</span></div>
        <div className="at-subscore-area">
          <div className="at-subscore-grid">
            {Object.entries(signal.subscores).map(([name, value]) => (
              <div key={name} className="at-subscore"><small>{name}</small><div><span style={{ width: `${value}%` }} /></div><b>{value}</b></div>
            ))}
          </div>
        </div>
      </div>

      <div className="at-fsm" aria-label="Trigger state machine">
        {signal.fsm.map((s, i) => <span key={s} className={s === signal.fsmCurrent ? 'is-current' : ''}>{s}{i < signal.fsm.length - 1 ? '  ›' : ''}</span>)}
        <time>t+00:{String(signal.expiresInSeconds).padStart(2, '0')}</time>
      </div>

      <dl className="at-level-grid">
        <div><dt>entry ref</dt><dd>{signal.entryRef.toFixed(2)}</dd></div>
        <div><dt>stop ref</dt><dd>{signal.stopRef.toFixed(2)}</dd></div>
        <div><dt>R</dt><dd>{signal.riskPerShare.toFixed(2)} / {signal.stopBps}bp</dd></div>
        <div><dt>leg / R</dt><dd>{signal.legToR.toFixed(1)}x</dd></div>
        <div><dt>float</dt><dd>{signal.floatM.toFixed(1)}M</dd></div>
        <div><dt>RVOL_tod</dt><dd>{signal.rvolTod.toFixed(1)}x</dd></div>
      </dl>

      {signal.evidence.length > 0 && <div className="at-chip-rail">{signal.evidence.map(e => <Chip key={e.id} tone={e.tone}>{e.label}</Chip>)}</div>}

      {/* order controls: display-only, semantically + visually disabled with capability tooltips */}
      <div className="at-order-grid" aria-label="Order controls (disabled)">
        {orderControls.map(label => (
          <button key={label} type="button" disabled className="at-order-btn"
            title={label.includes('MKT') ? 'Market entry unavailable — price-controlled entry only' : 'Order routing off in ActiveTrader (manual paper only)'}>
            <span aria-hidden="true">🔒</span> {label}
          </button>
        ))}
        <div className="at-state"><small>POS</small><strong>flat</strong></div><div className="at-state"><small>ORD</small><strong>none</strong></div>
      </div>

      <div className="at-drill"><small>setup {signal.primarySetupId ?? '—'} · v{signal.setupVersion ?? '—'} · registry {(signal.registryHash ?? '—').replace('sha256:', '').slice(0, 12)} · fsm {signal.fsmState ?? signal.fsmCurrent} · setup_state {signal.setupState ?? '—'}</small></div>

      <footer className="at-trade-card__footer">
        <div><strong>Manual paper testing only</strong><small>No automatic order path. Schwab, Moomoo, and Alpaca Live remain non-routable. ActiveTrader session not authorized.</small></div>
        <div className="at-inline">
          <button type="button" onClick={onRoute} disabled={!canRoute}
            title={reference ? 'Reference sample — preview only' : !canRoute ? 'Only an actionable live signal can be routed' : undefined}>
            {reference ? 'Preview allocation example' : 'Prepare paper route'}
          </button>
          <button type="button" className="at-secondary" onClick={onDismiss}>Dismiss</button>
        </div>
      </footer>
    </section>
  );
}

function AccountAllocationModal({ signal, accounts, reference, onClose }: {
  signal: ScalpSignal; accounts: BrokerAccount[]; reference: boolean; onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const openerRef = useRef<Element | null>(null);
  // NO account is preselected — the operator must choose (server verification is required for real routing).
  const [draft, setDraft] = useState<RoutingDraft>({ signalId: signal.id, selectedAccountIds: [], accountShares: {} });
  const selected = accounts.filter(a => draft.selectedAccountIds.includes(a.id));
  const totalShares = selected.reduce((n, a) => n + (draft.accountShares[a.id] || 0), 0);
  const totalNotional = totalShares * signal.entryRef;
  const risk = totalShares * signal.riskPerShare;

  useEffect(() => {
    openerRef.current = document.activeElement;
    const el = dialogRef.current; el?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
      if (e.key === 'Tab' && el) {
        const f = el.querySelectorAll<HTMLElement>('button, input, [href], [tabindex]:not([tabindex="-1"])');
        const list = Array.from(f).filter(n => !n.hasAttribute('disabled'));
        if (!list.length) return;
        const first = list[0], last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener('keydown', onKey, true);
    return () => { document.removeEventListener('keydown', onKey, true); (openerRef.current as HTMLElement | null)?.focus?.(); };
  }, [onClose]);

  const setSel = (account: BrokerAccount, checked: boolean) =>
    setDraft(prev => ({ ...prev, selectedAccountIds: checked ? [...prev.selectedAccountIds, account.id] : prev.selectedAccountIds.filter(x => x !== account.id) }));

  return (
    <div className="at-modal-backdrop" role="presentation" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <section className="at-modal" role="dialog" aria-modal="true" aria-labelledby="route-title" tabIndex={-1} ref={dialogRef}>
        <header className="at-panel__header">
          <div><h2 id="route-title">{reference ? 'Allocation example (reference)' : 'Prepare manual paper order'} <small>{signal.symbol} long</small></h2>
            <p>entry {signal.entryRef} · stop {signal.stopRef} · R {signal.riskPerShare} · IGN {signal.ign}</p></div>
          <Chip tone="warning">environment: server-verify pending</Chip>
        </header>
        <div className="at-account-table">
          <div className="at-account-table__head"><span>Account</span><span>Permissions</span><span>Buying power</span><span>Shares</span><span>Notional</span><span>Risk</span></div>
          {accounts.map(account => {
            const shares = draft.accountShares[account.id] || 0;
            return <div key={account.id} className={`at-account-row ${!account.eligible ? 'is-disabled' : ''}`}>
              <label><input type="checkbox" checked={draft.selectedAccountIds.includes(account.id)} disabled={!account.eligible}
                onChange={e => setSel(account, e.target.checked)} /><span><strong>{account.label}</strong><small>{account.maskedNumber}</small></span></label>
              <span><strong>{account.permissionLabel}</strong>{account.eligibilityReason && <small>{account.eligibilityReason}</small>}</span>
              <span>{account.buyingPower ? usd.format(account.buyingPower) : '—'}</span>
              <span><input type="number" min={0} max={account.maxShares} value={shares} disabled={!account.eligible}
                onChange={e => setDraft(prev => ({ ...prev, accountShares: { ...prev.accountShares, [account.id]: Math.min(account.maxShares, Number(e.target.value || 0)) } }))} /></span>
              <span>{shares ? usd.format(shares * signal.entryRef) : '—'}</span><span>{shares ? money2.format(shares * signal.riskPerShare) : '—'}</span>
            </div>;
          })}
        </div>
        <div className="at-modal-note">No account is preselected. Quantities and risk shown are a client-side preview — a real workflow recomputes them server-side after environment verification. Moomoo is L2/tape data-plane only; Thinkorswim is a manual export/entry workflow, not an API-routable account.</div>
        <dl className="at-summary-grid"><div><dt>Accounts</dt><dd>{selected.length} selected</dd></div><div><dt>Total shares</dt><dd>{totalShares.toLocaleString()}</dd></div><div><dt>Notional (preview)</dt><dd>{usd.format(totalNotional)}</dd></div><div><dt>Risk at stop (preview)</dt><dd>{money2.format(risk)}</dd></div></dl>
        <footer className="at-modal__footer"><p>Final submission is intentionally absent. Order routing is OFF in ActiveTrader; a separate operator-signed, server-verified confirmation ceremony is required.</p>
          <div className="at-inline"><button type="button" className="at-secondary" onClick={onClose}>Cancel</button><button type="button" disabled title="Order routing off — no submit path in this build">Confirm paper order</button></div></footer>
      </section>
    </div>
  );
}

function decisionTone(d: string | null): 'pass' | 'warning' | 'fail' | 'context' {
  return d === 'GO' || d === 'ENTER' || d === 'TAKE' ? 'pass' : d === 'WAIT' ? 'warning' : d === 'AVOID' ? 'fail' : 'context';
}

// Compact engine status — NOT a data dump. Says whether each engine is live and how much it's seen today.
function EngineStatusBar({ es }: { es?: EngineStatus }) {
  if (!es) return null;
  const lastEt = es.scanner.last_scan_at
    ? new Date(es.scanner.last_scan_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York' })
    : '—';
  return (
    <div className="at-enginebar at-inline at-wrap">
      <Chip tone={es.scanner.available ? 'pass' : 'fail'} title="TradeAI orchestrator scanner (trade_ai_scans)">
        {es.scanner.available ? '● TRADEAI SCANNER LIVE' : 'SCANNER DOWN'}
      </Chip>
      <span className="at-enginebar__stat">{es.scanner.go_count_today} GO · {es.scanner.manual_review_count_today} manual-review · {es.scanner.actionable_count_today} actionable{es.scanner.latest_run_label ? ` · run ${es.scanner.latest_run_label}` : ''} · last {lastEt} ET</span>
      <Chip tone={es.ign.market_open ? 'pass' : 'context'} title="IGN/trigger engine (scalp_ignition_events), RTH only">
        {es.ign.market_open ? '● IGN LIVE' : `IGN IDLE · opens ${es.ign.opens_et} ET`}
      </Chip>
      <span className="at-enginebar__stat">{es.ign.today_trigger_count} triggers · {es.ign.today_row_count} rows today</span>
    </div>
  );
}

// Pre-fire visibility: the ignition ladder (what's climbing toward a trigger) + when L2 gets pulled.
const LADDER = ['BELOW', 'IGN_45', 'IGN_60', 'IGN_75', 'IGN_ACCEL', 'TRIGGER'];
function ArmingPanel({ a }: { a: ArmingStatus }) {
  const ladder = a.lane_ladder || {};
  const near = a.near_firing || [];
  const l2 = a.l2;
  return (
    <section className="at-panel at-arming" aria-labelledby="arming-title">
      <header className="at-panel__header">
        <div>
          <h2 id="arming-title">Arming ladder <small>pre-fire · IGN engine</small></h2>
          <p>{a.market_open ? 'RTH live — climbing toward a trigger' : 'IGN engine idle (opens 09:30 ET) — ladder populates at RTH'}</p>
        </div>
        <Chip tone={l2.armed.length ? 'pass' : 'context'} title={l2.note}>
          L2 {l2.enabled ? (l2.armed.length ? `ARMED ×${l2.armed.length}` : 'idle') : 'off'}{l2.max_armed ? ` / ${l2.max_armed}` : ''}
        </Chip>
      </header>
      <div className="at-ladder">
        {LADDER.map(lane => (
          <div key={lane} className={`at-ladder__step${(ladder[lane] || 0) > 0 && lane !== 'BELOW' ? ' is-active' : ''}${lane === 'TRIGGER' ? ' is-trigger' : ''}`}>
            <span className="at-ladder__lane">{lane === 'BELOW' ? 'below' : lane.replace('IGN_', '')}</span>
            <span className="at-ladder__count">{ladder[lane] || 0}</span>
          </div>
        ))}
      </div>
      {near.length > 0 ? (
        <div className="at-livescan__table" role="table" aria-label="Near-firing symbols">
          <div className="at-livescan__row at-livescan__row--head" role="row">
            <span>sym</span><span>lane</span><span>IGN</span><span>state</span><span>setup</span><span>RVOL</span><span>tier</span><span>L2</span>
          </div>
          {near.map(s => (
            <div key={s.symbol} className="at-livescan__row" role="row">
              <span className="mono at-livescan__sym">{s.symbol}</span>
              <span className={`at-chip at-chip--${s.lane === 'IGN_ACCEL' ? 'pass' : s.lane === 'IGN_75' ? 'warning' : 'context'}`}>{s.lane.replace('IGN_', '')}</span>
              <span className="mono">{s.ign}</span>
              <span>{s.setupState === 'ARMED'
                ? <span className="at-chip at-chip--warning">ARMED</span>
                : s.setupState === 'FIRED' ? <span className="at-chip at-chip--pass">FIRED</span>
                : <span className="mono">{s.gate}</span>}</span>
              <span>{s.primarySetupLabel ?? (s.setupState ? s.setupState.replace(/_/g, ' ').toLowerCase() : '—')}</span>
              <span className="mono">{s.rvolTod != null ? `${s.rvolTod.toFixed(1)}x` : '—'}</span>
              <span className="mono">{s.dataTier}</span>
              <span>{s.l2Engaged ? '● L2' : '—'}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="at-livescan__note">
          {a.market_open
            ? 'Nothing arming right now — no symbol is above the first ignition threshold (all BELOW). This is the honest live state, not a gap.'
            : `Ladder is idle until RTH. When the IGN engine runs, symbols climb IGN_45 → IGN_60 → IGN_75 → IGN_ACCEL here; the trigger FSM (IMPULSE → PULLBACK → ARMED → TRIGGERED) fires the entry. ${l2.note}`}
        </div>
      )}
    </section>
  );
}

// One actionable TradeAI orchestrator row (GO or MANUAL_REVIEW). Real scanner fields — no fabricated IGN.
function ScannerRow({ s, selected, onSelect }: { s: ScannerSignal; selected: boolean; onSelect: () => void }) {
  const go = s.decision === 'GO';
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected}
      className={`at-queue-row at-queue-row--scanner${go ? ' at-queue-row--go' : ''}${selected ? ' is-selected' : ''}`}>
      <span className="at-queue-row__symbol">{s.symbol}<small>{s.price != null ? s.price.toFixed(2) : '—'}</small></span>
      <span className="at-queue-row__score">{s.score ?? '—'}<small>{s.grade ?? ''}</small></span>
      <span className="at-queue-row__body">
        <strong>{go ? 'GO' : (s.operatorPill ?? 'MANUAL REVIEW')}</strong>
        <small>{s.setupClass ? `${s.setupClass.replace(/_/g, ' ')} · ` : ''}RVOL {s.rvol != null ? `${s.rvol.toFixed(1)}x` : '—'} · chg {s.changePct != null ? `${s.changePct.toFixed(1)}%` : '—'} · {s.scannedAtEt ?? ''}</small>
      </span>
      <span className="at-queue-row__action">Review</span>
    </button>
  );
}

// Detail card for a TradeAI actionable signal — honest orchestrator evidence, no IGN/subscores invented.
function ScannerCard({ s }: { s: ScannerSignal }) {
  const go = s.decision === 'GO';
  return (
    <section className="at-panel at-trade-card" aria-labelledby="scanner-card-title">
      <header className="at-panel__header at-trade-card__title-row">
        <div><h2 id="scanner-card-title">{s.symbol} <span>{s.price != null ? s.price.toFixed(2) : '—'}</span> <em>{s.changePct != null ? `${s.changePct >= 0 ? '+' : ''}${s.changePct.toFixed(1)}%` : ''}</em></h2></div>
        <div className="at-inline at-wrap">
          <Chip tone={go ? 'pass' : 'warning'}>{s.decision}</Chip>
          {s.operatorPill && <Chip>{s.operatorPill}</Chip>}
          {s.notTradeable && <Chip tone="fail" title="Momentum fire flagged non-auto-tradeable — manual review only">not auto-tradeable</Chip>}
        </div>
      </header>
      <dl className="at-level-grid">
        <div><dt>score</dt><dd>{s.score ?? '—'} {s.grade ?? ''}</dd></div>
        <div><dt>setup</dt><dd>{s.setupClass ? s.setupClass.replace(/_/g, ' ') : (go ? 'GO' : '—')}</dd></div>
        <div><dt>RVOL</dt><dd>{s.rvol != null ? `${s.rvol.toFixed(1)}x` : '—'}</dd></div>
        <div><dt>gap</dt><dd>{s.gapPct != null ? `${s.gapPct.toFixed(1)}%` : '—'}</dd></div>
        <div><dt>float</dt><dd>{s.floatM != null ? `${s.floatM.toFixed(1)}M` : '—'}</dd></div>
        <div><dt>sector</dt><dd>{s.sector ?? '—'}</dd></div>
      </dl>
      {(s.criticVerdict || s.operatorSubtitle) && (
        <div className="at-chip-rail">
          {s.criticVerdict && <Chip tone={go ? 'pass' : 'context'}>critic {s.criticVerdict}</Chip>}
          {s.catalystVerified && <Chip tone="pass">catalyst verified</Chip>}
          {s.operatorSubtitle && <span className="at-source">{s.operatorSubtitle}</span>}
        </div>
      )}
      <div className="at-livescan__note">
        TradeAI orchestrator signal (trade_ai_scans — screener → enrichment → scalp critic). {go
          ? 'GO decision.' : 'MANUAL_REVIEW momentum fire (squeeze / runner / gainer) — surfaced for review, not auto-tradeable.'}
        {' '}No IGN score is fabricated here (that comes only from the RTH IGN engine). Manual paper review only; no order path.
      </div>
    </section>
  );
}

export default function ActiveTraderPage(props: Props) {
  const { signals, scannerSignals, accounts, onOpenStrategies, dataState, actionableCount,
          ignTriggerCount, scannerGoCount, engineStatus, arming, lastIgnSessionDate, registryHash, registryVersion } = props;
  const [preview, setPreview] = useState(false);   // explicit reference-sample preview (never the default)
  const ignItems = signals ?? [];
  const scanItems = scannerSignals ?? [];
  const loading = signals === undefined && scannerSignals === undefined && !engineStatus;
  const totalActionable = actionableCount ?? (ignItems.length + scanItems.length);
  const state: ActiveTraderDataState = preview ? 'REFERENCE_SAMPLE'
    : (dataState ?? (loading ? 'LOADING' : (totalActionable ? 'LIVE_DATA' : 'EMPTY_LIVE_QUEUE')));
  const reference = state === 'REFERENCE_SAMPLE';

  // reference/preview shows the mock IGN layout; live shows the real actionable queue
  const ignQueue = reference ? MOCK_QUEUE : ignItems;
  const acct = reference ? MOCK_ACCOUNTS : (accounts ?? []);
  const sortedIgn = useMemo(() => [...ignQueue].sort((a, b) => b.ign - a.ign), [ignQueue]);
  const [selIgn, setSelIgn] = useState<string | null>(null);
  const [selScan, setSelScan] = useState<string | null>(null);
  const selectedIgn = sortedIgn.find(s => s.id === selIgn) ?? (selScan ? null : sortedIgn[0]) ?? null;
  const selectedScan = scanItems.find(s => s.id === selScan) ?? null;
  const [routing, setRouting] = useState(false);
  const canRoute = !reference && !!selectedIgn && (selectedIgn.state === 'ARMED' || selectedIgn.state === 'TRIGGERED');
  const hasAny = reference || ignItems.length > 0 || scanItems.length > 0;

  return <main className="active-trader-page">
    <div className="active-trader-page__intro">
      <div><h1>Active Trader — Review</h1><p>Actionable momentum-scalp signals to review for a manual paper trade. Manual paper only; no automatic or live order path.</p></div>
      <div className="at-inline at-wrap">
        <Chip tone={totalActionable ? 'pass' : 'context'}>{totalActionable} actionable</Chip>
        <button type="button" className="at-link-button" onClick={() => setPreview(p => !p)}>{preview ? 'Exit preview' : 'Preview example'}</button>
      </div>
    </div>

    {!preview && <EngineStatusBar es={engineStatus} />}
    {!preview && arming && <ArmingPanel a={arming} />}

    {/* scoped authority status — never conflate a global service with this tab's authority */}
    <div className="at-authority-rail at-inline at-wrap">
      <Chip title="This tab">ACTIVE TRADER SESSION: NOT AUTHORIZED</Chip>
      <Chip tone="fail" title="No order routes wired in ActiveTrader">ACTIVE TRADER ROUTES: OFF</Chip>
      <Chip title="Any global 2FA/automation service is scoped OUTSIDE ActiveTrader">GLOBAL SERVICES: OUT OF SCOPE HERE</Chip>
      <span className="at-source">queue: actionable only (IGN TRIGGER + scanner GO)
        {lastIgnSessionDate ? ` · last IGN fire ${lastIgnSessionDate}` : ''}
        {registryVersion ? ` · ${registryVersion}` : ''}{registryHash ? ` ${registryHash.replace('sha256:', '').slice(0, 8)}` : ''}</span>
    </div>

    {state === 'API_UNAVAILABLE' && <div className="at-fullstate at-fullstate--fail">Permission-queue API unavailable — the backend did not respond (not an empty queue).</div>}
    {state === 'LOADING' && <div className="at-fullstate">Loading actionable queue…</div>}

    {!reference && !hasAny && state !== 'LOADING' && state !== 'API_UNAVAILABLE' && (
      <section className="at-panel at-empty-card">
        <strong>No actionable momentum-scalp signals right now.</strong>
        <p>The queue shows only what a human could paper-route today — IGN TRIGGER fires and scanner GO/momentum-route signals. Nothing has crossed that bar yet.</p>
        <ul>
          <li>TradeAI scanner: {engineStatus?.scanner.available ? `live, ${engineStatus.scanner.go_count_today} GO + ${engineStatus.scanner.manual_review_count_today} manual-review today` : 'down'}.</li>
          <li>IGN engine: {engineStatus?.ign.market_open ? `live, ${engineStatus.ign.today_trigger_count} triggers today` : `RTH-only, opens ${engineStatus?.ign.opens_et ?? '09:30'} ET`}{lastIgnSessionDate ? ` — last alert-worthy fire ${lastIgnSessionDate}` : ''}.</li>
        </ul>
        <button type="button" className="at-link-button" onClick={() => setPreview(true)}>Preview the review layout with sample data</button>
      </section>
    )}

    {(reference || ignItems.length > 0) && (
      <div className="active-trader-page__layout">
        <aside><PermissionQueue signals={sortedIgn} selectedId={selectedIgn?.id ?? null} onSelect={s => { setSelIgn(s.id); setSelScan(null); }} actionable={reference ? 0 : ignItems.length} reference={reference} /></aside>
        <div>{selectedIgn
          ? <ActiveTradeCard signal={selectedIgn} reference={reference} canRoute={canRoute || reference}
              onRoute={() => setRouting(true)} onDismiss={() => setSelIgn(null)} onOpenStrategies={onOpenStrategies} />
          : <section className="at-panel at-empty-card">Select an IGN fire from the queue.</section>}
        </div>
      </div>
    )}

    {!reference && scanItems.length > 0 && (
      <div className="active-trader-page__layout">
        <aside>
          <section className="at-panel" aria-labelledby="scanner-go-title">
            <header className="at-panel__header"><h2 id="scanner-go-title">TradeAI actionable <small>{scannerGoCount ?? 0} GO · {scanItems.length} total</small></h2><Chip tone="pass">GO + manual-review</Chip></header>
            <div className="at-queue">
              {scanItems.map(s => <ScannerRow key={s.id} s={s} selected={s.id === selScan} onSelect={() => { setSelScan(s.id); setSelIgn(null); }} />)}
            </div>
          </section>
        </aside>
        <div>{selectedScan ? <ScannerCard s={selectedScan} /> : <section className="at-panel at-empty-card">Select a scanner GO signal.</section>}</div>
      </div>
    )}

    {routing && selectedIgn && <AccountAllocationModal signal={selectedIgn} accounts={acct} reference={reference} onClose={() => setRouting(false)} />}
  </main>;
}

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { App } from './App';

// sample of the real /api/v2/trade-ai/scanner shape (data.tickers)
const SCAN = {
  ok: true,
  data: {
    vix: 16.6, market_regime: 'Neutral', latest_run_label: '0700', stale: false,
    tickers: [
      { symbol: 'EHGO', decision: 'GO', grade: 'A', score: 44, rvol: 35.3, volume: 73055345,
        price: 2.45, change_pct: '39.2', gap_pct: '134.09', float_m: '2.24',
        catalyst: 'registered direct offering closing', not_tradeable: false,
        setup_class: 'RUNNER', critic_verdict: 'CONFIRM' },
      { symbol: 'RTX', decision: 'WAIT', grade: 'B', score: 30, rvol: 1.2, volume: 500000,
        price: 120.5, change_pct: '1.1', gap_pct: '0.4', float_m: '316', catalyst: '' },
      { symbol: 'WLDS', decision: 'NO-GO', grade: 'B', score: 33, rvol: 225, volume: 17300000,
        price: 1.65, change_pct: '11.48', gap_pct: '16.22', float_m: '2.05', not_tradeable: true },
    ],
  },
};

beforeEach(() => {
  window.history.pushState({}, '', '/v3-next/');
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => SCAN } as Response)));
});

describe('/v3-next read-only workspace', () => {
  it('renders every required panel', async () => {
    render(<App />);
    await screen.findByTestId('decision-row-EHGO'); // let the live scan settle
    for (const id of [
      'session-strip', 'decision-deck', 'symbol-decision', 'prime-queue', 'tickets', 'pnl-panel',
      'accounts-panel', 'brokers-panel', 'capabilities-panel', 'rejections-panel',
      'notifications-panel', 'journal-panel', 'feature-modal', 'parity-panel',
      'symbol-selector', 'classic-next-nav', 'observation-gate-panel',
    ]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
  });

  it('surfaces REAL GO/WAIT rows from the live scanner (momentum signals, no RSI, no charts/L2/tape)', async () => {
    render(<App />);
    // real actionable names from /api/v2/trade-ai/scanner
    const go = await screen.findByTestId('decision-row-EHGO');
    expect(go.textContent).toContain('GO');
    expect(await screen.findByTestId('decision-row-RTX')).toBeInTheDocument(); // WAIT
    // NO-GO names are not surfaced in the actionable deck
    expect(screen.queryByTestId('decision-row-WLDS')).not.toBeInTheDocument();
    const deck = screen.getByTestId('decision-deck').textContent || '';
    expect(deck).toMatch(/RVOL/);
    expect(deck).toMatch(/gap/i);
    expect(deck).not.toMatch(/RSI/);
    // raw microstructure panels are gone; L2/tape are inputs only
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
    expect(screen.queryByTestId('level2')).not.toBeInTheDocument();
    expect(screen.getByTestId('decision-note').textContent).toMatch(/trade-ai\/scanner|awareness/i);
  });

  it('classic nav points at untouched /v3, next at /v3-next', () => {
    render(<App />);
    expect(screen.getByTestId('nav-classic')).toHaveAttribute('href', '/v3/');
    expect(screen.getByTestId('nav-next')).toHaveAttribute('aria-current', 'page');
  });

  it('shows the corrected data-only gate badges and no live badge', () => {
    render(<App />);
    expect(screen.getByTestId('moomoo-DATA_AGREEMENT_CLEARED')).toBeInTheDocument();
    expect(screen.getByTestId('moomoo-SESSION_1_ARMED')).toBeInTheDocument();
    expect(screen.getByTestId('moomoo-LIVE_TRADING_BLOCKED')).toBeInTheDocument();
    expect(screen.queryByText(/LIVE_DATA_AVAILABLE|LIVE TRADING ENABLED|CONNECTED LIVE/)).not.toBeInTheDocument();
    expect(screen.getByTestId('moomoo-broker').textContent).toContain('DATA_ONLY_READY');
  });

  it('renders explicit UNAVAILABLE for marks — never fabricated', () => {
    render(<App />);
    // marks/P&L still explicitly unavailable pre-market-data stage
    expect(screen.getByTestId('pnl-panel').textContent).toMatch(/UNAVAILABLE|require|UNVERIFIED/i);
    // TESTB candidate has null rvol/float → Unavailable markers
    const testb = screen.getByTestId('candidate-TESTB');
    expect(testb.querySelectorAll('[data-testid="unavailable"]').length).toBeGreaterThan(0);
  });

  it('every action control is disabled and issues no write', () => {
    render(<App />);
    const actions = screen.getAllByTestId(/^action-/);
    expect(actions.length).toBeGreaterThan(0);
    for (const action of actions) expect(action).toBeDisabled();
  });

  it('feature controls remain read-only and production live modes stay off', () => {
    render(<App />);
    const controls = screen.getByTestId('feature-modal');
    expect(controls.textContent).toContain('mutable via this UI: false');
    expect(controls.textContent).toContain('active_trader_live_canary_enabled');
    expect(controls.textContent).toMatch(/prod OFF/);
  });

  it('parity is baseline captured but production parity is not claimed', () => {
    render(<App />);
    const parity = screen.getByTestId('parity-panel');
    expect(parity.textContent).toContain('BASELINE_CAPTURED');
    expect(parity.textContent).toMatch(/live parity is not claimed/i);
    expect(parity.textContent).toContain('PENDING');
  });

  it('symbol selector is populated from the live scan and switches the detail', async () => {
    render(<App />);
    await screen.findByTestId('decision-row-EHGO');
    // default symbol = first GO (EHGO)
    expect(screen.getByTestId('symbol-decision').textContent).toContain('EHGO');
    fireEvent.change(screen.getByTestId('symbol-select'), { target: { value: 'RTX' } });
    expect(screen.getByTestId('symbol-decision').textContent).toContain('RTX');
  });

  it('masked account ids only', () => {
    render(<App />);
    const accounts = screen.getByTestId('accounts-panel').textContent || '';
    expect(accounts).not.toMatch(/\b\d{6,}\b/);
    expect(accounts).toContain('***');
  });

  it('shows the observation SHA boundary without changing the armed branch', () => {
    render(<App />);
    const gate = screen.getByTestId('observation-gate-panel');
    expect(gate.textContent).toContain('0 of 5');
    expect(gate.textContent).toContain('70a681bb3867');
    expect(gate.textContent).toMatch(/does not modify the armed branch/i);
  });

  it('prime queue selection is reflected in the queue', async () => {
    render(<App />);
    await screen.findByTestId('decision-row-EHGO');
    fireEvent.click(screen.getByTestId('candidate-TESTC'));
    expect(screen.getByTestId('candidate-TESTC')).toHaveAttribute('aria-selected', 'true');
  });
});

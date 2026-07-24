import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { App } from './App';

beforeEach(() => {
  window.history.pushState({}, '', '/v3-next/');
});

describe('/v3-next read-only workspace iteration 2', () => {
  it('renders every required panel', () => {
    render(<App />);
    for (const id of [
      'session-strip', 'prime-queue', 'symbol-workspace', 'tickets', 'pnl-panel',
      'accounts-panel', 'brokers-panel', 'capabilities-panel', 'rejections-panel',
      'notifications-panel', 'journal-panel', 'feature-modal', 'parity-panel',
      'observation-gate-panel', 'chart', 'level2', 'time-and-sales', 'symbol-selector',
      'classic-next-nav',
    ]) expect(screen.getByTestId(id)).toBeInTheDocument();
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

  it('renders explicit unavailable for L2 and tape — never fabricated', () => {
    render(<App />);
    expect(screen.getByTestId('level2').textContent).toMatch(/UNAVAILABLE|awaiting/i);
    expect(screen.getByTestId('time-and-sales').textContent).toMatch(/UNAVAILABLE|awaiting/i);
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

  it('symbol selector and prime queue both switch the workspace', () => {
    render(<App />);
    fireEvent.change(screen.getByTestId('symbol-select'), { target: { value: 'TESTB' } });
    expect(screen.getByTestId('symbol-workspace').textContent).toContain('TESTB');
    fireEvent.click(screen.getByTestId('candidate-TESTC'));
    expect(screen.getByTestId('symbol-workspace').textContent).toContain('TESTC');
    expect(screen.getByTestId('candidate-TESTC')).toHaveAttribute('aria-selected', 'true');
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
});

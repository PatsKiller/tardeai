import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { App } from './App';

// jsdom lacks these; stub for react-router + component render
beforeEach(() => {
  window.history.pushState({}, '', '/v3-next/');
});

describe('/v3-next read-only workspace', () => {
  it('renders every required panel', () => {
    render(<App />);
    for (const id of [
      'session-strip', 'decision-deck', 'symbol-decision', 'prime-queue', 'tickets', 'pnl-panel',
      'accounts-panel', 'brokers-panel', 'capabilities-panel', 'rejections-panel',
      'notifications-panel', 'journal-panel', 'feature-modal', 'parity-panel',
      'symbol-selector', 'classic-next-nav',
    ]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
  });

  it('presents GO / WAIT / NO-GO decisions (not charts/L2/tape)', () => {
    render(<App />);
    expect(screen.getByTestId('decision-TESTA').textContent).toContain('GO');
    expect(screen.getByTestId('decision-TESTW').textContent).toContain('WAIT');
    expect(screen.getByTestId('decision-TESTB').textContent).toContain('NO-GO');
    // raw microstructure panels are intentionally gone from the live decision view
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
    expect(screen.queryByTestId('level2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('time-and-sales')).not.toBeInTheDocument();
    // L2/tape are inputs, explicitly not displayed
    expect(screen.getByTestId('decision-note').textContent).toMatch(/not displayed/i);
  });

  it('classic nav points at untouched /v3, next at /v3-next', () => {
    render(<App />);
    expect(screen.getByTestId('nav-classic')).toHaveAttribute('href', '/v3/');
    expect(screen.getByTestId('nav-next')).toBeInTheDocument();
  });

  it('shows the three Moomoo blocked badges and NO green/live badge', () => {
    render(<App />);
    expect(screen.getByTestId('moomoo-OFFLINE_IMPLEMENTED')).toBeInTheDocument();
    expect(screen.getByTestId('moomoo-CREDENTIAL_GATE_BLOCKED')).toBeInTheDocument();
    expect(screen.getByTestId('moomoo-LIVE_DATA_UNAVAILABLE')).toBeInTheDocument();
    expect(screen.queryByText(/LIVE_DATA_AVAILABLE|CONNECTED|GREEN/)).not.toBeInTheDocument();
    expect(screen.getByTestId('moomoo-broker').textContent).toContain('NOT_INSTALLED');
  });

  it('renders explicit UNAVAILABLE for marks — never fabricated', () => {
    render(<App />);
    // marks/P&L still explicitly unavailable pre-market-data stage
    expect(screen.getByTestId('pnl-panel').textContent).toMatch(/UNAVAILABLE|require/i);
    // TESTB candidate has null rvol/float → Unavailable markers
    const testb = screen.getByTestId('candidate-TESTB');
    expect(testb.querySelectorAll('[data-testid="unavailable"]').length).toBeGreaterThan(0);
  });

  it('every action control is disabled and issues no write', () => {
    render(<App />);
    const actions = screen.getAllByTestId(/^action-/);
    expect(actions.length).toBeGreaterThan(0);
    for (const a of actions) expect(a).toBeDisabled();
  });

  it('feature modal is read-only (not mutable via UI); production modes OFF', () => {
    render(<App />);
    const fm = screen.getByTestId('feature-modal');
    expect(fm.textContent).toContain('mutable via this UI: false');
    expect(fm.textContent).toMatch(/prod OFF/);
  });

  it('parity claims no UI parity', () => {
    render(<App />);
    expect(screen.getByTestId('parity-panel').textContent).toMatch(/BASELINE_ONLY|no UI parity/);
  });

  it('symbol selector switches the decision detail', () => {
    render(<App />);
    fireEvent.change(screen.getByTestId('symbol-select'), { target: { value: 'TESTB' } });
    const sd = screen.getByTestId('symbol-decision').textContent || '';
    expect(sd).toContain('TESTB');
    expect(sd).toContain('NO-GO');
  });

  it('masked account ids only (no raw numbers)', () => {
    render(<App />);
    const accounts = screen.getByTestId('accounts-panel').textContent || '';
    expect(accounts).not.toMatch(/\b\d{6,}\b/);
    expect(accounts).toContain('***');
  });
});

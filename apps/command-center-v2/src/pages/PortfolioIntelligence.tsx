import React, { useEffect, useState, useCallback } from 'react';

// ── Types ────────────────────────────────────────────────────────────────────
interface Position {
  symbol: string;
  name: string;
  account: string;
  security_type: string;
  sector: string;
  industry: string;
  market_value: number;
  cost_basis: number;
  unrealized_gain_loss: number;
  unrealized_pct: number;
  shares: number;
  last_price: number;
  weight_pct: number;
  technicals?: Record<string, any>;
}

interface PIData {
  total_positions: number;
  total_value: number;
  positions: Position[];
  sector_breakdown: Record<string, any>;
  account_breakdown: Record<string, any>;
  security_type_breakdown: Record<string, any>;
  cross_account_symbols: string[];
  classification_rate: number;
}

interface WatchlistContext {
  symbol: string;
  synthesis?: { verdict?: string; synthesis_text?: string; confidence?: number };
  agent_results?: { agent_name: string; verdict?: string; confidence_score?: number; narrative?: string }[];
  strategy_card?: {
    trade_type?: string;
    strategy_label?: string;
    account_fit?: string;
    ideal_entry?: number;
    stop_loss?: number;
    target_price?: number;
    risk_reward?: number;
    support?: number;
    resistance?: number;
  };
  news?: { title: string; published_at?: string; sentiment_score?: number }[];
  summary_verdict?: string;
  in_portfolio?: boolean;
}

// ── Period Returns Bar ───────────────────────────────────────────────────────
interface PeriodData {
  change_pct: number | null;
  change: number | null;
  start_value: number | null;
  start_date: string;
}

function PeriodBar({
  selected, onSelect, periods
}: {
  selected: string;
  onSelect: (p: string) => void;
  periods: Record<string, PeriodData> | null;
}) {
  const LABELS = ['1D','1W','1M','3M','YTD','1Y'];
  const cur = periods?.[selected];

  const fmt$ = (v: number | null) => {
    if (v === null || v === undefined) return '—';
    const abs = Math.abs(v);
    const sign = v >= 0 ? '+' : '-';
    if (abs >= 1000) return `${sign}$${(abs/1000).toFixed(1)}K`;
    return `${sign}$${abs.toFixed(0)}`;
  };

  const fmtPct = (v: number | null) => {
    if (v === null || v === undefined) return '—';
    return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  };

  const color = (v: number | null) =>
    v === null ? '#64748B' : v >= 0 ? '#4ADE80' : '#F87171';

  return (
    <div style={{
      background: '#0D1626', border: '1px solid #1E293B',
      borderRadius: '8px', padding: '12px 16px',
      marginBottom: '16px', display: 'flex',
      alignItems: 'center', gap: '0', flexWrap: 'wrap'
    }}>
      {/* Period buttons */}
      <div style={{ display: 'flex', gap: '4px', marginRight: '20px' }}>
        {LABELS.map(p => (
          <button
            key={p}
            onClick={() => onSelect(p)}
            style={{
              background: selected === p ? '#1E3A5F' : 'transparent',
              border: `1px solid ${selected === p ? '#2E86D4' : '#1E293B'}`,
              color: selected === p ? '#60A5FA' : '#64748B',
              padding: '4px 10px', borderRadius: '4px',
              fontSize: '11px', fontWeight: 600, cursor: 'pointer',
              letterSpacing: '0.05em', transition: 'all 0.15s'
            }}
          >{p}</button>
        ))}
      </div>

      {/* Result */}
      {cur ? (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '18px', fontWeight: 700, color: color(cur.change) }}>
            {fmt$(cur.change)}
          </span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: color(cur.change_pct) }}>
            {fmtPct(cur.change_pct)}
          </span>
          {cur.start_date && (
            <span style={{ fontSize: '11px', color: '#475569' }}>
              since {cur.start_date}
            </span>
          )}
          {cur.change === null && (
            <span style={{ fontSize: '12px', color: '#475569' }}>No snapshot data</span>
          )}
        </div>
      ) : (
        <span style={{ fontSize: '12px', color: '#475569' }}>Loading…</span>
      )}
    </div>
  );
}

// ── Account label map ─────────────────────────────────────────────────────────
const ACCOUNT_LABELS: Record<string, string> = {
  fidelity_401k: 'FIDELITY 401K',
  schwab_rollover_ira: 'SCHWAB ROLLOVER IRA',
  schwab_roth: 'SCHWAB ROTH',
  schwab_taxable: 'SCHWAB TAXABLE',
  tradeai_automated: 'ALPACA PAPER',
  alpaca_taxable_live: 'ALPACA TAXABLE LIVE (READ-ONLY DATA)',
  alpaca_ira_live: 'ALPACA IRA LIVE (READ-ONLY DATA)',
};

const ACCOUNT_COLORS: Record<string, string> = {
  fidelity_401k: '#2E86D4',
  schwab_rollover_ira: '#10B981',
  schwab_roth: '#F59E0B',
  schwab_taxable: '#8B5CF6',
  tradeai_automated: '#FBBF24',
  alpaca_taxable_live: '#F59E0B',
  alpaca_ira_live: '#D97706',
};

// ── Watchlist Drawer ──────────────────────────────────────────────────────────
function WatchlistDrawer({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const [ctx, setCtx] = useState<WatchlistContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) { setCtx(null); return; }
    setLoading(true);
    setError(null);
    fetch(`/api/v2/watchlist/context/${symbol}`)
      .then(r => r.json())
      .then(d => {
        if (d.ok) setCtx(d.data);
        else setError(d.error || 'No watchlist data found');
      })
      .catch(() => setError('Failed to load watchlist data'))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (!symbol) return null;

  const verdictColor = (v?: string) => {
    if (!v) return '#64748B';
    const u = v.toUpperCase();
    if (u.includes('BUY') || u.includes('ADD') || u.includes('STRONG')) return '#10B981';
    if (u.includes('HOLD') || u.includes('WATCH') || u.includes('INCOME')) return '#F59E0B';
    if (u.includes('SELL') || u.includes('TRIM') || u.includes('AVOID')) return '#EF4444';
    return '#64748B';
  };

  const sc = ctx?.strategy_card;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          zIndex: 999, backdropFilter: 'blur(2px)'
        }}
      />
      {/* Drawer */}
      <div style={{
        position: 'fixed', right: 0, top: 0, bottom: 0, width: '480px',
        background: '#0F1629', borderLeft: '1px solid #1E293B',
        zIndex: 1000, overflowY: 'auto', padding: '0',
        boxShadow: '-8px 0 32px rgba(0,0,0,0.6)'
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '20px 24px', borderBottom: '1px solid #1E293B',
          background: '#0D1426', position: 'sticky', top: 0, zIndex: 10
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '22px', fontWeight: 700, color: '#E2E8F0', letterSpacing: '0.05em' }}>{symbol}</span>
            {ctx?.in_portfolio && (
              <span style={{
                background: '#1E3A5F', color: '#60A5FA', fontSize: '10px',
                padding: '2px 8px', borderRadius: '4px', fontWeight: 600
              }}>HELD</span>
            )}
            {ctx?.strategy_card?.trade_type && (
              <span style={{
                background: '#1B2D1B', color: '#4ADE80', fontSize: '10px',
                padding: '2px 8px', borderRadius: '4px', fontWeight: 600
              }}>{ctx.strategy_card.trade_type}</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <a
              href={`/v2/watchlist`}
              style={{ color: '#60A5FA', fontSize: '12px', textDecoration: 'none', marginRight: '8px' }}
              title="Open in Watchlist"
            >
              Open in Watchlist →
            </a>
            <button
              onClick={onClose}
              style={{
                background: 'none', border: '1px solid #334155', color: '#94A3B8',
                width: '32px', height: '32px', borderRadius: '6px',
                cursor: 'pointer', fontSize: '16px', display: 'flex',
                alignItems: 'center', justifyContent: 'center'
              }}
            >×</button>
          </div>
        </div>

        <div style={{ padding: '20px 24px' }}>
          {loading && (
            <div style={{ color: '#60A5FA', textAlign: 'center', padding: '40px', fontSize: '14px' }}>
              Loading watchlist data…
            </div>
          )}
          {error && (
            <div style={{
              background: '#1A1A2E', border: '1px solid #334155',
              borderRadius: '8px', padding: '20px', textAlign: 'center'
            }}>
              <div style={{ color: '#94A3B8', fontSize: '13px', marginBottom: '8px' }}>{error}</div>
              <div style={{ color: '#64748B', fontSize: '12px' }}>
                {symbol} is not on the watchlist yet.{' '}
                <a href="/v2/watchlist" style={{ color: '#60A5FA', textDecoration: 'none' }}>
                  Add it in Watchlist →
                </a>
              </div>
            </div>
          )}

          {ctx && !loading && (
            <>
              {/* Synthesis Verdict */}
              {ctx.synthesis?.verdict && (
                <div style={{
                  background: '#0D1F0D', border: '1px solid #1E3B1E',
                  borderRadius: '8px', padding: '16px', marginBottom: '16px'
                }}>
                  <div style={{ fontSize: '10px', color: '#4ADE80', letterSpacing: '0.1em', marginBottom: '6px' }}>SYNTHESIS VERDICT</div>
                  <div style={{ fontSize: '18px', fontWeight: 700, color: verdictColor(ctx.synthesis.verdict) }}>
                    {ctx.synthesis.verdict.toUpperCase()}
                  </div>
                  {ctx.synthesis.confidence !== undefined && (
                    <div style={{ fontSize: '12px', color: '#64748B', marginTop: '4px' }}>
                      Confidence: {Math.round(ctx.synthesis.confidence * 100)}%
                    </div>
                  )}
                  {ctx.synthesis.synthesis_text && (
                    <div style={{ fontSize: '13px', color: '#94A3B8', marginTop: '10px', lineHeight: '1.6' }}>
                      {ctx.synthesis.synthesis_text.substring(0, 400)}
                      {ctx.synthesis.synthesis_text.length > 400 ? '…' : ''}
                    </div>
                  )}
                </div>
              )}

              {/* Strategy Card */}
              {sc && (sc.ideal_entry || sc.stop_loss || sc.target_price) && (
                <div style={{
                  background: '#0F172A', border: '1px solid #1E293B',
                  borderRadius: '8px', padding: '16px', marginBottom: '16px'
                }}>
                  <div style={{ fontSize: '10px', color: '#60A5FA', letterSpacing: '0.1em', marginBottom: '12px' }}>STRATEGY CARD</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '10px' }}>
                    {sc.ideal_entry && (
                      <div style={{ background: '#1E293B', borderRadius: '6px', padding: '10px' }}>
                        <div style={{ fontSize: '10px', color: '#64748B', marginBottom: '3px' }}>ENTRY</div>
                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#10B981' }}>${sc.ideal_entry.toFixed(2)}</div>
                      </div>
                    )}
                    {sc.stop_loss && (
                      <div style={{ background: '#1E293B', borderRadius: '6px', padding: '10px' }}>
                        <div style={{ fontSize: '10px', color: '#64748B', marginBottom: '3px' }}>STOP</div>
                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#EF4444' }}>${sc.stop_loss.toFixed(2)}</div>
                      </div>
                    )}
                    {sc.target_price && (
                      <div style={{ background: '#1E293B', borderRadius: '6px', padding: '10px' }}>
                        <div style={{ fontSize: '10px', color: '#64748B', marginBottom: '3px' }}>TARGET</div>
                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#60A5FA' }}>${sc.target_price.toFixed(2)}</div>
                      </div>
                    )}
                    {sc.risk_reward && (
                      <div style={{ background: '#1E293B', borderRadius: '6px', padding: '10px' }}>
                        <div style={{ fontSize: '10px', color: '#64748B', marginBottom: '3px' }}>R:R</div>
                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#F59E0B' }}>{sc.risk_reward.toFixed(1)}x</div>
                      </div>
                    )}
                  </div>
                  {sc.account_fit && (
                    <div style={{ fontSize: '12px', color: '#64748B' }}>
                      Best in: <span style={{ color: '#94A3B8' }}>{sc.account_fit}</span>
                    </div>
                  )}
                  {(sc.support || sc.resistance) && (
                    <div style={{ fontSize: '12px', color: '#64748B', marginTop: '4px' }}>
                      Support: <span style={{ color: '#94A3B8' }}>{sc.support ? `$${sc.support.toFixed(2)}` : '—'}</span>
                      {' · '}
                      Resistance: <span style={{ color: '#94A3B8' }}>{sc.resistance ? `$${sc.resistance.toFixed(2)}` : '—'}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Agent Results */}
              {ctx.agent_results && ctx.agent_results.length > 0 && (
                <div style={{
                  background: '#0F172A', border: '1px solid #1E293B',
                  borderRadius: '8px', padding: '16px', marginBottom: '16px'
                }}>
                  <div style={{ fontSize: '10px', color: '#F59E0B', letterSpacing: '0.1em', marginBottom: '12px' }}>AGENT ANALYSIS</div>
                  {ctx.agent_results.map((a, i) => (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                      padding: '8px 0', borderBottom: i < ctx.agent_results!.length - 1 ? '1px solid #1E293B' : 'none'
                    }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '12px', fontWeight: 600, color: '#94A3B8', marginBottom: '3px' }}>
                          {a.agent_name?.replace('_agent','').replace('_',' ').toUpperCase()}
                        </div>
                        {a.narrative && (
                          <div style={{ fontSize: '11px', color: '#64748B', lineHeight: '1.5' }}>
                            {a.narrative.substring(0, 150)}{a.narrative.length > 150 ? '…' : ''}
                          </div>
                        )}
                      </div>
                      <div style={{ marginLeft: '12px', textAlign: 'right', flexShrink: 0 }}>
                        {a.verdict && (
                          <div style={{ fontSize: '11px', fontWeight: 700, color: verdictColor(a.verdict) }}>
                            {a.verdict.toUpperCase()}
                          </div>
                        )}
                        {a.confidence_score !== undefined && (
                          <div style={{ fontSize: '10px', color: '#64748B' }}>
                            {Math.round(a.confidence_score * 100)}%
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Recent News */}
              {ctx.news && ctx.news.length > 0 && (
                <div style={{
                  background: '#0F172A', border: '1px solid #1E293B',
                  borderRadius: '8px', padding: '16px', marginBottom: '16px'
                }}>
                  <div style={{ fontSize: '10px', color: '#8B5CF6', letterSpacing: '0.1em', marginBottom: '12px' }}>RECENT NEWS</div>
                  {ctx.news.slice(0, 4).map((n, i) => (
                    <div key={i} style={{
                      padding: '8px 0',
                      borderBottom: i < Math.min(ctx.news!.length, 4) - 1 ? '1px solid #1E293B' : 'none'
                    }}>
                      <div style={{ fontSize: '12px', color: '#94A3B8', lineHeight: '1.5' }}>{n.title}</div>
                      {n.published_at && (
                        <div style={{ fontSize: '10px', color: '#64748B', marginTop: '3px' }}>
                          {new Date(n.published_at).toLocaleDateString()}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Actions */}
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <a
                  href={`https://finviz.com/quote.ashx?t=${symbol}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'inline-block', background: '#1E3A5F', color: '#60A5FA',
                    textDecoration: 'none', padding: '8px 16px', borderRadius: '6px',
                    fontSize: '12px', fontWeight: 600
                  }}
                >
                  Finviz ↗
                </a>
                <a
                  href={`https://finance.yahoo.com/quote/${symbol}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'inline-block', background: '#1E293B', color: '#94A3B8',
                    textDecoration: 'none', padding: '8px 16px', borderRadius: '6px',
                    fontSize: '12px', fontWeight: 600
                  }}
                >
                  Yahoo ↗
                </a>
                <a
                  href={`/v2/research?symbol=${symbol}`}
                  style={{
                    display: 'inline-block', background: '#1E293B', color: '#94A3B8',
                    textDecoration: 'none', padding: '8px 16px', borderRadius: '6px',
                    fontSize: '12px', fontWeight: 600
                  }}
                >
                  Research →
                </a>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ── Ticker Chip ───────────────────────────────────────────────────────────────
function TickerChip({ symbol, onClick }: { symbol: string; onClick: (s: string) => void }) {
  const [hov, setHov] = useState(false);
  const isMutualFund = symbol.includes('-') || symbol.length > 5;
  if (isMutualFund) {
    return <span style={{ color: '#64748B', fontSize: '13px' }}>{symbol}</span>;
  }
  return (
    <span
      onClick={() => onClick(symbol)}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        color: hov ? '#93C5FD' : '#60A5FA',
        fontWeight: 700, fontSize: '13px', letterSpacing: '0.05em',
        cursor: 'pointer', borderBottom: hov ? '1px solid #60A5FA' : '1px solid transparent',
        transition: 'all 0.15s ease',
      }}
    >
      {symbol}
    </span>
  );
}

// ── Sector Row with expandable positions ─────────────────────────────────────
function SectorRow({
  sector, value, pct, gainPct, positions, selectedAccount, onTickerClick
}: {
  sector: string;
  value: number;
  pct: number;
  gainPct: number | null;
  positions: Position[];
  selectedAccount: string | null;
  onTickerClick: (s: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const filtered = selectedAccount ? positions.filter(p => p.account === selectedAccount) : positions;
  const sectorPositions = filtered.filter(p => p.sector === sector || p.industry === sector);

  return (
    <div style={{ borderBottom: '1px solid #0F172A' }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex', alignItems: 'center', padding: '10px 16px',
          cursor: 'pointer', background: expanded ? '#0D1F3A' : 'transparent',
          transition: 'background 0.15s ease',
        }}
        onMouseEnter={e => { if (!expanded) (e.currentTarget as HTMLElement).style.background = '#0F172A'; }}
        onMouseLeave={e => { if (!expanded) (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
      >
        <span style={{ color: expanded ? '#60A5FA' : '#E2E8F0', fontSize: '13px', flex: 1, fontWeight: expanded ? 600 : 400 }}>
          {sector}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {sectorPositions.length > 0 && (
            <span style={{ fontSize: '10px', color: '#4ADE80', background: '#0D1F0D', padding: '1px 6px', borderRadius: '10px' }}>
              {sectorPositions.length} pos
            </span>
          )}
          <div style={{ width: '120px', height: '4px', background: '#1E293B', borderRadius: '2px', overflow: 'hidden' }}>
            <div style={{ width: `${Math.min(pct * 5, 100)}%`, height: '100%', background: '#2E86D4', borderRadius: '2px' }} />
          </div>
          <span style={{ width: '70px', textAlign: 'right', fontSize: '12px', color: '#94A3B8' }}>
            ${(value / 1000).toFixed(0)}K
          </span>
          <span style={{ width: '36px', textAlign: 'right', fontSize: '11px', color: '#64748B' }}>
            {pct.toFixed(1)}%
          </span>
          <span style={{
            width: '60px', textAlign: 'right', fontSize: '12px',
            color: gainPct === null ? '#64748B' : gainPct >= 0 ? '#4ADE80' : '#F87171'
          }}>
            {gainPct === null ? 'N/A' : `${gainPct > 0 ? '+' : ''}${gainPct.toFixed(1)}%`}
          </span>
          <span style={{ color: '#64748B', fontSize: '12px', marginLeft: '4px' }}>
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </div>

      {expanded && sectorPositions.length > 0 && (
        <div style={{ background: '#0A0F1E', padding: '8px 16px 12px 32px' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '80px 1fr 90px 90px 90px',
            gap: '4px', fontSize: '10px', color: '#475569',
            padding: '4px 0 6px', letterSpacing: '0.05em'
          }}>
            <span>SYMBOL</span><span>NAME</span><span style={{textAlign:'right'}}>VALUE</span>
            <span style={{textAlign:'right'}}>GAIN ($)</span><span style={{textAlign:'right'}}>WEIGHT</span>
          </div>
          {sectorPositions.map((pos, i) => (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '80px 1fr 90px 90px 90px',
              gap: '4px', padding: '5px 0',
              borderTop: '1px solid #0F172A'
            }}>
              <TickerChip symbol={pos.symbol} onClick={onTickerClick} />
              <span style={{ fontSize: '12px', color: '#64748B', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {pos.name}
              </span>
              <span style={{ fontSize: '12px', color: '#94A3B8', textAlign: 'right' }}>
                ${pos.market_value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              </span>
              <span style={{
                fontSize: '11px', textAlign: 'right',
                color: pos.unrealized_pct > 0 ? '#4ADE80' : pos.unrealized_pct < 0 ? '#F87171' : '#64748B',
                lineHeight: '1.3'
              }}>
                {pos.unrealized_gain_loss ? (
                  <>
                    <span style={{display:'block', fontWeight:700}}>
                      {pos.unrealized_gain_loss >= 0 ? '+' : ''}${Math.abs(pos.unrealized_gain_loss) >= 1000
                        ? (Math.abs(pos.unrealized_gain_loss)/1000).toFixed(1)+'K'
                        : Math.abs(pos.unrealized_gain_loss).toFixed(0)}
                    </span>
                    <span style={{display:'block', fontSize:'10px', opacity:0.8}}>
                      {pos.unrealized_pct > 0 ? '+' : ''}{pos.unrealized_pct.toFixed(1)}%
                    </span>
                  </>
                ) : (
                  <span style={{color:'#475569'}}>N/A</span>
                )}
              </span>
              <span style={{ fontSize: '12px', color: '#64748B', textAlign: 'right' }}>
                {pos.weight_pct.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}
      {expanded && sectorPositions.length === 0 && (
        <div style={{ background: '#0A0F1E', padding: '12px 32px', fontSize: '12px', color: '#475569' }}>
          No positions in this sector {selectedAccount ? `for ${ACCOUNT_LABELS[selectedAccount] || selectedAccount}` : ''}.
        </div>
      )}
    </div>
  );
}

// ── Security Type Breakdown ───────────────────────────────────────────────────
function SecurityTypeSection({
  positions, selectedAccount, onTickerClick
}: {
  positions: Position[];
  selectedAccount: string | null;
  onTickerClick: (s: string) => void;
}) {
  const filtered = selectedAccount ? positions.filter(p => p.account === selectedAccount) : positions;
  const byType = filtered.reduce<Record<string, Position[]>>((acc, p) => {
    const t = p.security_type || 'Unknown';
    if (!acc[t]) acc[t] = [];
    acc[t].push(p);
    return acc;
  }, {});

  return (
    <div style={{
      background: '#0D1626', border: '1px solid #1E293B',
      borderRadius: '8px', overflow: 'hidden', marginTop: '16px'
    }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid #1E293B' }}>
        <span style={{ fontSize: '11px', letterSpacing: '0.1em', color: '#64748B', fontWeight: 600 }}>
          SECURITY TYPE CLASSIFICATION
        </span>
      </div>
      {Object.entries(byType).sort((a, b) => b[1].length - a[1].length).map(([type, pos]) => (
        <div key={type} style={{
          display: 'flex', alignItems: 'center', padding: '10px 16px',
          borderBottom: '1px solid #0F172A'
        }}>
          <span style={{ flex: 1, fontSize: '13px', color: '#E2E8F0' }}>{type}</span>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', flex: 2, justifyContent: 'flex-start' }}>
            {pos.map((p, i) => (
              <TickerChip key={i} symbol={p.symbol} onClick={onTickerClick} />
            ))}
          </div>
          <span style={{ fontSize: '12px', color: '#64748B', marginLeft: '16px', minWidth: '24px', textAlign: 'right' }}>
            {pos.length}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Cross-Account Section ─────────────────────────────────────────────────────
function CrossAccountSection({
  positions, selectedAccount, onTickerClick
}: {
  positions: Position[];
  selectedAccount: string | null;
  onTickerClick: (s: string) => void;
}) {
  const allSymbols = positions.map(p => p.symbol);
  const dupes = [...new Set(allSymbols.filter((s, i) => allSymbols.indexOf(s) !== i))];
  if (dupes.length === 0) return null;

  return (
    <div style={{
      background: '#1A0D0D', border: '1px solid #3B1F1F',
      borderRadius: '8px', padding: '16px', marginTop: '16px'
    }}>
      <div style={{ fontSize: '11px', letterSpacing: '0.1em', color: '#F87171', fontWeight: 600, marginBottom: '10px' }}>
        CROSS-ACCOUNT DUPLICATES ({dupes.length})
      </div>
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        {dupes.map((sym, i) => {
          const accts = [...new Set(positions.filter(p => p.symbol === sym).map(p => p.account))];
          return (
            <div key={i} style={{
              background: '#0F0808', border: '1px solid #3B1F1F',
              borderRadius: '6px', padding: '6px 10px', cursor: 'pointer'
            }}>
              <TickerChip symbol={sym} onClick={onTickerClick} />
              <div style={{ fontSize: '10px', color: '#7F1D1D', marginTop: '3px' }}>
                {accts.map(a => ACCOUNT_LABELS[a]?.replace('SCHWAB ', '')?.replace(' IRA', '') || a).join(' + ')}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function PortfolioIntelligence() {
  const [data, setData] = useState<PIData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [watchlistSymbol, setWatchlistSymbol] = useState<string | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState<string>('1M');
  const [periodData, setPeriodData] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    Promise.all([
      fetch('/api/v2/portfolio-intelligence').then(r => r.json()),
      fetch('/api/v2/portfolio/performance').then(r => r.json()).catch(() => null)
    ]).then(([pi, perf]) => {
      if (pi.ok) setData(pi.data);
      if (perf?.ok) setPeriodData(perf.data.periods);
    }).finally(() => setLoading(false));
  }, []);

  const handleTickerClick = useCallback((symbol: string) => {
    setWatchlistSymbol(symbol);
  }, []);

  const handleAccountClick = useCallback((account: string) => {
    setSelectedAccount(prev => prev === account ? null : account);
  }, []);

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: '#60A5FA', fontSize: '14px' }}>
        Loading Portfolio Intelligence…
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ padding: '40px', color: '#EF4444', fontSize: '14px' }}>
        Failed to load portfolio data.
      </div>
    );
  }

  // Filtered positions
  const filteredPositions = selectedAccount
    ? data.positions.filter(p => p.account === selectedAccount)
    : data.positions;

  const filteredValue = filteredPositions.reduce((s, p) => s + p.market_value, 0);

  // Build account breakdown from positions
  const accountMap: Record<string, { positions: Position[]; value: number; pnlPct: number | null }> = {};
  for (const pos of data.positions) {
    if (!accountMap[pos.account]) accountMap[pos.account] = { positions: [], value: 0, pnlPct: null };
    accountMap[pos.account].positions.push(pos);
    accountMap[pos.account].value += pos.market_value;
  }
  // Compute pnl for accounts that have cost basis
  for (const [acct, info] of Object.entries(accountMap)) {
    const totalCost = info.positions.reduce((s, p) => s + (p.cost_basis || 0), 0);
    const totalGain = info.positions.reduce((s, p) => s + (p.unrealized_gain_loss || 0), 0);
    if (totalCost > 0) {
      info.pnlPct = (totalGain / totalCost) * 100;
    }
  }

  // Build sector breakdown from filtered positions
  const sectorMap: Record<string, { value: number; positions: Position[]; totalCost: number; totalGain: number }> = {};
  for (const pos of filteredPositions) {
    const s = pos.sector || pos.industry || 'Unknown';
    if (!sectorMap[s]) sectorMap[s] = { value: 0, positions: [], totalCost: 0, totalGain: 0 };
    sectorMap[s].value += pos.market_value;
    sectorMap[s].positions.push(pos);
    sectorMap[s].totalCost += pos.cost_basis || 0;
    sectorMap[s].totalGain += pos.unrealized_gain_loss || 0;
  }

  const sectorEntries = Object.entries(sectorMap)
    .sort((a, b) => b[1].value - a[1].value);

  const classifiedCount = data.positions.filter(p => p.sector || p.industry).length;
  const classificationRate = data.total_positions > 0
    ? ((classifiedCount / data.total_positions) * 100).toFixed(1)
    : '0';

  return (
    <div style={{ padding: '24px', color: '#E2E8F0', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Watchlist Drawer */}
      <WatchlistDrawer symbol={watchlistSymbol} onClose={() => setWatchlistSymbol(null)} />

      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#F1F5F9', marginBottom: '4px' }}>
          Portfolio Intelligence
        </h1>
        <p style={{ color: '#64748B', fontSize: '13px' }}>
          {selectedAccount ? (
            <>
              <span style={{ color: ACCOUNT_COLORS[selectedAccount] || '#60A5FA', fontWeight: 600 }}>
                {ACCOUNT_LABELS[selectedAccount] || selectedAccount}
              </span>
              {' '}· {filteredPositions.length} positions · ${filteredValue.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              {' '}·{' '}
              <span
                onClick={() => setSelectedAccount(null)}
                style={{ color: '#60A5FA', cursor: 'pointer', textDecoration: 'underline' }}
              >
                Clear filter ×
              </span>
            </>
          ) : (
            <>
              {data.total_positions} positions · 4 accounts · ${data.total_value.toLocaleString('en-US', { maximumFractionDigits: 0 })} · {classificationRate}% classified
              <span style={{ marginLeft: '12px' }}>
                <a href="/v2/portfolio-monitor" style={{ color: '#2E86D4', textDecoration: 'none', fontSize: '12px' }}>
                  → Active signals & stops (Portfolio Monitor)
                </a>
              </span>
            </>
          )}
        </p>
      </div>

      {/* Period Returns */}
      <PeriodBar
        selected={selectedPeriod}
        onSelect={setSelectedPeriod}
        periods={periodData}
      />

      {/* Account Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px', marginBottom: '24px' }}>
        {Object.entries(accountMap).map(([acct, info]) => {
          const isSelected = selectedAccount === acct;
          const color = ACCOUNT_COLORS[acct] || '#60A5FA';
          return (
            <div
              key={acct}
              onClick={() => handleAccountClick(acct)}
              style={{
                background: isSelected ? '#0D1F3A' : '#0D1626',
                border: `1px solid ${isSelected ? color : '#1E293B'}`,
                borderRadius: '8px', padding: '16px',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                boxShadow: isSelected ? `0 0 0 1px ${color}40` : 'none',
                transform: isSelected ? 'translateY(-2px)' : 'none',
              }}
              onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.borderColor = color + '80'; }}
              onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.borderColor = '#1E293B'; }}
            >
              <div style={{ fontSize: '10px', color: isSelected ? color : '#64748B', letterSpacing: '0.1em', marginBottom: '8px', fontWeight: 600 }}>
                {ACCOUNT_LABELS[acct] || acct}
                {isSelected && <span style={{ marginLeft: '6px', fontSize: '9px' }}>✓</span>}
              </div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#F1F5F9', marginBottom: '4px' }}>
                ${(info.value / 1000).toFixed(0)}K
              </div>
              <div style={{ fontSize: '12px', color: '#64748B' }}>
                {info.positions.length} positions
              </div>
              {info.pnlPct !== null && (() => {
                const totalGain = info.positions.reduce((s, p) => s + (p.unrealized_gain_loss || 0), 0);
                const absGain = Math.abs(totalGain);
                const gainStr = totalGain >= 0
                  ? `+$${absGain >= 1000 ? (absGain/1000).toFixed(1)+'K' : absGain.toFixed(0)}`
                  : `-$${absGain >= 1000 ? (absGain/1000).toFixed(1)+'K' : absGain.toFixed(0)}`;
                return (
                  <div style={{ marginTop: '4px' }}>
                    <span style={{ fontSize: '13px', fontWeight: 700, color: info.pnlPct >= 0 ? '#4ADE80' : '#F87171' }}>
                      {info.pnlPct > 0 ? '+' : ''}{info.pnlPct.toFixed(1)}%
                    </span>
                    <span style={{ fontSize: '11px', color: info.pnlPct >= 0 ? '#4ADE80' : '#F87171', marginLeft: '5px', opacity: 0.8 }}>
                      {gainStr}
                    </span>
                    <div style={{ fontSize: '9px', color: '#475569', marginTop: '1px', letterSpacing: '0.05em' }}>
                      UNREALIZED ALL-TIME
                    </div>
                  </div>
                );
              })()}
              {info.pnlPct === null && (
                <div style={{ fontSize: '11px', color: '#475569', marginTop: '4px' }}>
                  P&L N/A — no cost basis
                </div>
              )}
            </div>
          );
        })}
        {/* Classification tile */}
        <div style={{
          background: '#0D1626', border: '1px solid #1E293B',
          borderRadius: '8px', padding: '16px'
        }}>
          <div style={{ fontSize: '10px', color: '#64748B', letterSpacing: '0.1em', marginBottom: '8px', fontWeight: 600 }}>
            CLASSIFICATION
          </div>
          <div style={{ fontSize: '20px', fontWeight: 700, color: '#4ADE80' }}>
            {classificationRate}%
          </div>
          <div style={{ fontSize: '12px', color: '#64748B' }}>
            {classifiedCount}/{data.total_positions} classified
          </div>
        </div>
      </div>

      {/* Sector Breakdown */}
      <div style={{
        background: '#0D1626', border: '1px solid #1E293B',
        borderRadius: '8px', overflow: 'hidden', marginBottom: '0'
      }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #1E293B', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.1em', color: '#64748B', fontWeight: 600 }}>
            SECTOR BREAKDOWN {selectedAccount ? `— ${ACCOUNT_LABELS[selectedAccount] || selectedAccount}` : ''}
          </span>
          <span style={{ fontSize: '11px', color: '#475569' }}>Click row to expand positions</span>
        </div>
        {sectorEntries.map(([sector, info]) => {
          const pct = filteredValue > 0 ? (info.value / filteredValue) * 100 : 0;
          const gainPct = info.totalCost > 0 ? (info.totalGain / info.totalCost) * 100 : null;
          return (
            <SectorRow
              key={sector}
              sector={sector}
              value={info.value}
              pct={pct}
              gainPct={gainPct}
              positions={data.positions}
              selectedAccount={selectedAccount}
              onTickerClick={handleTickerClick}
            />
          );
        })}
      </div>

      {/* Security Type Classification */}
      <SecurityTypeSection
        positions={data.positions}
        selectedAccount={selectedAccount}
        onTickerClick={handleTickerClick}
      />

      {/* Cross-Account */}
      <CrossAccountSection
        positions={data.positions}
        selectedAccount={selectedAccount}
        onTickerClick={handleTickerClick}
      />

      {/* Link to Portfolio Monitor */}
      <div style={{
        background: '#0F172A', border: '1px solid #1E293B',
        borderRadius: '8px', padding: '20px', textAlign: 'center', marginTop: '16px'
      }}>
        <div style={{ color: '#64748B', fontSize: '13px', marginBottom: '8px' }}>
          Position-level data with agent signals, stops, and trim/hold/add recommendations
        </div>
        <a
          href="/v2/portfolio-monitor"
          style={{
            display: 'inline-block', background: '#1E3A5F', color: 'white',
            textDecoration: 'none', padding: '10px 24px', borderRadius: '6px', fontSize: '13px'
          }}
        >
          Open Portfolio Monitor ({data.total_positions} positions) →
        </a>
      </div>
    </div>
  );
}

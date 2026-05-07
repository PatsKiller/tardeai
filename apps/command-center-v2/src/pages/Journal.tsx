import React, { useEffect, useState, useCallback, useMemo } from 'react'

// ── Types ──────────────────────────────────────────────────────────────────
interface Trade {
  trade_key: string
  symbol: string
  account: string
  open_date: string
  close_date: string
  trade_type: string
  shares: number
  buy_price: number
  sell_price: number
  cost_basis: number
  proceeds: number
  pnl: number
  pnl_pct: number
  hold_days: number
  review_id?: number
  setup_type?: string
  setup_family?: string
  execution_score?: number
  followed_plan?: boolean
  lessons?: string
  suggested_setup?: string
  suggested_family?: string
  suggestion_rationale?: string
  suggested_types?: string[]
}

interface ReviewForm {
  trade_key: string
  // Setup
  setup_types: string[]
  setup_family: string
  setup_name: string
  timeframe: string
  direction: string
  market_regime: string
  catalyst_type: string
  // Signals
  entry_signals: string[]
  exit_signals: string[]
  entry_reason: string
  exit_reason: string
  // Psychology
  emotion_before: string
  emotion_during: string
  emotion_after: string
  confidence_before: number
  stress_level: number
  // Execution
  execution_quality_score: number
  sizing_quality_score: number
  risk_management_score: number
  followed_plan: boolean
  well_executed: boolean
  // Risk
  planned_r: number | null
  realized_r: number | null
  // Reflection
  lesson_learned: string
  review_notes: string
  // Tags
  mistake_tags: string[]
  strength_tags: string[]
}

const ENTRY_SIGNALS: { value: string; label: string }[] = [
  { value: 'macd_cross', label: 'MACD Cross' },
  { value: 'rsi_oversold_bounce', label: 'RSI Oversold Bounce' },
  { value: 'rsi_divergence', label: 'RSI Divergence' },
  { value: 'volume_spike_rvol', label: 'Volume Spike / RVOL' },
  { value: 'level2_order_flow', label: 'Level 2 / Order Flow' },
  { value: 'momentum_breakout', label: 'Momentum Breakout' },
  { value: 'gap_up', label: 'Gap Up' },
  { value: 'gap_down', label: 'Gap Down' },
  { value: 'resistance_break', label: 'Resistance Break' },
  { value: 'support_bounce', label: 'Support Bounce' },
  { value: 'moving_avg_cross', label: 'Moving Avg Cross (SMA/EMA)' },
  { value: 'vwap_reclaim', label: 'VWAP Reclaim' },
  { value: 'vwap_reject', label: 'VWAP Reject' },
  { value: 'squeeze_fire', label: 'Squeeze Fire (BB/KC)' },
  { value: 'candlestick_pattern', label: 'Candlestick Pattern' },
  { value: 'premarket_high_break', label: 'Pre-Market High Break' },
  { value: 'float_rotation', label: 'Float Rotation' },
  { value: 'short_squeeze_setup', label: 'Short Squeeze Setup' },
  { value: 'news_catalyst', label: 'News / Catalyst' },
  { value: 'sector_rotation', label: 'Sector Rotation' },
  { value: 'earnings_play', label: 'Earnings Play' },
  { value: 'technical_confluence', label: 'Technical Confluence' },
  { value: 'pullback_to_support', label: 'Pullback to Support' },
]

const EXIT_SIGNALS: { value: string; label: string }[] = [
  { value: 'target_hit', label: 'Target Hit' },
  { value: 'stop_loss_hit', label: 'Stop Loss Hit' },
  { value: 'trailing_stop', label: 'Trailing Stop' },
  { value: 'macd_cross_against', label: 'MACD Cross Against' },
  { value: 'rsi_overbought', label: 'RSI Overbought' },
  { value: 'volume_dry_up', label: 'Volume Dry Up' },
  { value: 'vwap_rejection', label: 'VWAP Rejection' },
  { value: 'time_stop_eod', label: 'Time Stop (EOD)' },
  { value: 'momentum_fade', label: 'Momentum Fade' },
  { value: 'resistance_rejection', label: 'Resistance Rejection' },
  { value: 'risk_reward_achieved', label: 'Risk/Reward Achieved' },
  { value: 'news_reversal', label: 'News Reversal' },
  { value: 'scaling_out_partial', label: 'Scaling Out Partial' },
  { value: 'break_even_stop', label: 'Break Even Stop' },
  { value: 'pattern_failure', label: 'Pattern Failure' },
  { value: 'discretionary_exit', label: 'Discretionary Exit' },
]

const MISTAKE_TAGS: { value: string; label: string }[] = [
  { value: 'sized_too_large', label: 'Sized Too Large' },
  { value: 'sized_too_small', label: 'Sized Too Small' },
  { value: 'chased_entry', label: 'Chased Entry' },
  { value: 'held_too_long', label: 'Held Too Long' },
  { value: 'exited_too_early', label: 'Exited Too Early' },
  { value: 'moved_stop', label: 'Moved Stop' },
  { value: 'no_stop_set', label: 'No Stop Set' },
  { value: 'overtrade', label: 'Overtrade' },
  { value: 'revenge_trade', label: 'Revenge Trade' },
  { value: 'ignored_signal', label: 'Ignored Signal' },
  { value: 'fomo_entry', label: 'FOMO Entry' },
  { value: 'didnt_follow_plan', label: "Didn't Follow Plan" },
]

const STRENGTH_TAGS: { value: string; label: string }[] = [
  { value: 'followed_plan', label: 'Followed Plan' },
  { value: 'cut_loss_fast', label: 'Cut Loss Fast' },
  { value: 'let_winner_run', label: 'Let Winner Run' },
  { value: 'good_entry_timing', label: 'Good Entry Timing' },
  { value: 'proper_sizing', label: 'Proper Sizing' },
  { value: 'patient_entry', label: 'Patient Entry' },
  { value: 'respected_stop', label: 'Respected Stop' },
  { value: 'scaled_out_properly', label: 'Scaled Out Properly' },
  { value: 'read_tape_well', label: 'Read Tape Well' },
]

const DIRECTIONS = ['LONG', 'SHORT'] as const
const MARKET_REGIMES = ['bullish', 'bearish', 'choppy', 'trending', 'ranging'] as const
const CATALYST_TYPES = ['momentum', 'news', 'earnings', 'technical', 'sector'] as const

const SETUP_TYPES = [
  // Day / Scalp
  { value: 'day_scalp', label: 'Day Scalp', family: 'Scalp' },
  { value: 'day_momentum', label: 'Day Momentum', family: 'Momentum' },
  { value: 'day_small_move', label: 'Day Small Move', family: 'Scalp' },
  { value: 'day_failed_breakout', label: 'Failed Breakout', family: 'Momentum' },
  { value: 'gap_and_go', label: 'Gap & Go', family: 'Momentum' },
  { value: 'opening_range_break', label: 'Opening Range Break', family: 'Momentum' },
  { value: 'vwap_bounce', label: 'VWAP Bounce', family: 'Mean Reversion' },
  { value: 'level2_tape_read', label: 'Level 2 / Tape Read', family: 'Scalp' },
  // Swing
  { value: 'swing_momentum', label: 'Swing Momentum', family: 'Swing' },
  { value: 'swing_position', label: 'Swing Position', family: 'Swing' },
  { value: 'pullback_to_ma', label: 'Pullback to MA', family: 'Mean Reversion' },
  { value: 'breakout_retest', label: 'Breakout + Retest', family: 'Momentum' },
  { value: 'mean_reversion', label: 'Mean Reversion', family: 'Mean Reversion' },
  { value: 'squeeze_setup', label: 'Squeeze Setup (BB/KC)', family: 'Momentum' },
  // Position / Long-term
  { value: 'position_trade', label: 'Position Trade', family: 'Core Position' },
  { value: 'long_term_compounder', label: 'Long-Term Compounder', family: 'Core Position' },
  { value: 'value_dip_buy', label: 'Value / Dip Buy', family: 'Value' },
  { value: 'sector_rotation', label: 'Sector Rotation', family: 'Core Position' },
  // Short
  { value: 'short_momentum', label: 'Short Momentum', family: 'Momentum' },
  { value: 'short_overextended', label: 'Short Overextended', family: 'Mean Reversion' },
  { value: 'short_breakdown', label: 'Short Breakdown', family: 'Momentum' },
  // Catalyst
  { value: 'earnings_play', label: 'Earnings Play', family: 'Catalyst' },
  { value: 'news_catalyst', label: 'News / Catalyst', family: 'Catalyst' },
  { value: 'short_squeeze', label: 'Short Squeeze', family: 'Catalyst' },
  // Income
  { value: 'dividend_capture', label: 'Dividend Capture', family: 'Income' },
  { value: 'covered_call', label: 'Covered Call', family: 'Income' },
  // Other
  { value: 'other', label: 'Other', family: 'Other' },
]

const EMOTIONS = ['calm','confident','anxious','fearful','greedy','bored','focused','fomo','revenge','neutral']
const TIMEFRAMES = ['Day','Swing','Position','Long Term']

const ACCT_SHORT: Record<string,string> = {
  fidelity_401k: '401k', schwab_rollover_ira: 'Rollover', schwab_roth: 'Roth', schwab_taxable: 'Taxable'
}

function fmt$(v: number, decimals=0) {
  if (v === undefined || v === null) return '—'
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '-'
  if (abs >= 1000) return `${sign}$${(abs/1000).toFixed(1)}K`
  return `${sign}$${abs.toFixed(decimals)}`
}

// ── Backtest Panel ────────────────────────────────────────────────────────
function BacktestPanel({ tradeKey }: { tradeKey: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const encoded = tradeKey.replace(/:/g, '__')
    fetch(`/api/v2/journal/backtest/${encoded}`).then(r => r.json())
      .then(d => { if (d.ok) setData(d.data); else setData(null) })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tradeKey])

  if (loading) return <div style={{ color:'#64748B',fontSize:'13px' }}>Loading backtest data...</div>
  if (!data) return <div style={{ background:'#1A1500',border:'1px solid #92400E',borderRadius:'8px',padding:'16px',color:'#F59E0B',fontSize:'13px' }}>No backtest data available for this trade</div>

  const gradeColor: Record<string,string> = { A:'#4ADE80', B:'#60A5FA', C:'#F59E0B', D:'#F87171' }
  const gradeBg: Record<string,string> = { A:'#0D1F0D', B:'#0D1A2F', C:'#1A1500', D:'#1F0D0D' }
  const rsiLabel = (rsi: number|null) => rsi == null ? 'N/A' : rsi < 30 ? 'Oversold' : rsi < 50 ? 'Neutral-Low' : rsi < 70 ? 'Neutral-High' : 'Overbought'
  const lblStyle: React.CSSProperties = { fontSize:'10px',color:'#64748B',letterSpacing:'0.1em',display:'block',marginBottom:'6px' }

  return (
    <div style={{ display:'flex',flexDirection:'column',gap:'16px' }}>
      {data.data_quality === 'insufficient' && (
        <div style={{ background:'#1A1500',border:'1px solid #92400E',borderRadius:'8px',padding:'12px',color:'#F59E0B',fontSize:'12px' }}>
          Insufficient price history for this ticker — {data.error_msg || 'limited data available'}
        </div>
      )}

      {/* Grade badges */}
      <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'12px' }}>
        {(['entry_grade','exit_grade','overall_grade'] as const).map(key => {
          const grade = data[key] || 'N/A'
          const label = key === 'entry_grade' ? 'ENTRY GRADE' : key === 'exit_grade' ? 'EXIT GRADE' : 'OVERALL'
          return (
            <div key={key} style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',padding:'14px',textAlign:'center' }}>
              <label style={lblStyle}>{label}</label>
              <span style={{ fontSize:'28px',fontWeight:800,color:gradeColor[grade]||'#64748B',
                background:gradeBg[grade]||'#1E293B',padding:'4px 16px',borderRadius:'8px',
                border:`1px solid ${gradeColor[grade]||'#334155'}` }}>{grade}</span>
            </div>
          )
        })}
      </div>

      {/* Entry metrics */}
      <div style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',padding:'16px' }}>
        <label style={{ ...lblStyle, fontSize:'11px',fontWeight:700,color:'#94A3B8',marginBottom:'12px' }}>ENTRY ANALYSIS</label>
        <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px',fontSize:'12px' }}>
          <div><span style={{ color:'#64748B' }}>RSI at entry: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.entry_rsi != null ? `${data.entry_rsi.toFixed(1)} — ${rsiLabel(data.entry_rsi)}` : 'N/A'}
          </span></div>
          <div><span style={{ color:'#64748B' }}>Volume ratio: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.entry_volume_ratio != null ? `${data.entry_volume_ratio.toFixed(2)}x avg` : 'N/A'}
          </span></div>
          <div><span style={{ color:'#64748B' }}>vs SMA50: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.entry_sma50_dist_pct != null ? `${data.entry_sma50_dist_pct > 0 ? '+' : ''}${data.entry_sma50_dist_pct.toFixed(1)}%` : 'N/A'}
          </span></div>
          <div><span style={{ color:'#64748B' }}>52w percentile: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.entry_52w_percentile != null ? `${data.entry_52w_percentile.toFixed(0)}%` : 'N/A'}
          </span></div>
        </div>
        {data.better_entry_existed && (
          <div style={{ marginTop:'10px',background:'#1A1500',border:'1px solid #92400E',borderRadius:'6px',padding:'8px 12px',fontSize:'11px',color:'#FCD34D' }}>
            Lower entry available: ${data.best_entry_price?.toFixed(2)}{data.entry_savings ? ` (could have saved $${data.entry_savings.toFixed(0)})` : ''}
          </div>
        )}
      </div>

      {/* Exit metrics */}
      <div style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',padding:'16px' }}>
        <label style={{ ...lblStyle, fontSize:'11px',fontWeight:700,color:'#94A3B8',marginBottom:'12px' }}>EXIT ANALYSIS</label>
        <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'10px',fontSize:'12px' }}>
          <div><span style={{ color:'#64748B' }}>+5d max: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.max_price_5d_after ? `$${data.max_price_5d_after.toFixed(2)}` : 'N/A'}
          </span></div>
          <div><span style={{ color:'#64748B' }}>+10d max: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.max_price_10d_after ? `$${data.max_price_10d_after.toFixed(2)}` : 'N/A'}
          </span></div>
          <div><span style={{ color:'#64748B' }}>+20d max: </span><span style={{ color:'#E2E8F0',fontWeight:600 }}>
            {data.max_price_20d_after ? `$${data.max_price_20d_after.toFixed(2)}` : 'N/A'}
          </span></div>
        </div>
        {data.left_on_table_20d != null && data.left_on_table_20d > 0 && (
          <div style={{ marginTop:'10px',fontSize:'12px',color: data.left_on_table_20d > 1000 ? '#F87171' : '#F59E0B' }}>
            +${data.left_on_table_20d.toFixed(0)} left on table (20 days after exit)
            {data.exit_was_early && <span style={{ color:'#F87171',marginLeft:'8px',fontWeight:700 }}>EARLY EXIT</span>}
          </div>
        )}
        {data.exit_rsi != null && (
          <div style={{ marginTop:'6px',fontSize:'11px',color:'#64748B' }}>Exit RSI: {data.exit_rsi.toFixed(1)}</div>
        )}
      </div>
    </div>
  )
}

// ── Entry Signals Panel ───────────────────────────────────────────────────
function EntrySignalsPanel({ tradeKey }: { tradeKey: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const encoded = tradeKey.replace(/:/g, '__')
    fetch(`/api/v2/journal/entry-signals/${encoded}`).then(r => r.json())
      .then(d => { if (d.ok) setData(d.data); else setData(null) })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tradeKey])

  if (loading) return <div style={{ color:'#64748B',fontSize:'13px',marginTop:'16px' }}>Loading entry signals...</div>
  if (!data) return null

  const hasSignals = (data.news_before_entry?.length > 0) || (data.agent_analyses?.length > 0)

  return (
    <div style={{ marginTop:'16px' }}>
      <div style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',padding:'16px' }}>
        <div style={{ fontSize:'11px',fontWeight:700,color:'#94A3B8',letterSpacing:'0.1em',marginBottom:'12px' }}>
          ENTRY SIGNALS — What existed at {data.entry_date}
        </div>
        {!hasSignals ? (
          <div style={{ color:'#475569',fontSize:'12px',fontStyle:'italic' }}>No signals in DB for {data.symbol} at entry time</div>
        ) : (
          <div style={{ display:'flex',flexDirection:'column',gap:'8px' }}>
            {(data.news_before_entry || []).map((n: any, i: number) => (
              <div key={`news-${i}`} style={{ display:'flex',gap:'8px',alignItems:'flex-start',fontSize:'11px',padding:'6px 8px',background:'#0F172A',borderRadius:'4px' }}>
                <span style={{ color:'#475569',minWidth:'70px',flexShrink:0 }}>{(n.published_at || '').slice(0,10)}</span>
                <span style={{ color:'#E2E8F0',flex:1 }}>{n.title}</span>
                {n.sentiment_score != null && (
                  <span style={{ color: n.sentiment_score > 0.3 ? '#4ADE80' : n.sentiment_score < -0.3 ? '#F87171' : '#94A3B8',
                    fontSize:'10px',flexShrink:0 }}>
                    {n.sentiment_score > 0 ? '+' : ''}{n.sentiment_score.toFixed(2)}
                  </span>
                )}
              </div>
            ))}
            {(data.agent_analyses || []).map((a: any, i: number) => (
              <div key={`agent-${i}`} style={{ display:'flex',gap:'8px',alignItems:'flex-start',fontSize:'11px',padding:'6px 8px',background:'#0F172A',borderLeft:'3px solid #60A5FA',borderRadius:'4px' }}>
                <span style={{ color:'#60A5FA',minWidth:'70px',fontWeight:600,flexShrink:0 }}>{a.agent_name}</span>
                <span style={{ color:'#E2E8F0',flex:1 }}>{a.verdict} ({a.confidence_score}%)</span>
                <span style={{ color:'#475569',fontSize:'10px',flexShrink:0 }}>{(a.created_at || '').slice(0,10)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Review Drawer ──────────────────────────────────────────────────────────
const DRAWER_TABS = ['Setup', 'Signals', 'Execution', 'Psychology', 'Review', 'Backtest'] as const
type DrawerTab = typeof DRAWER_TABS[number]

function ChipGrid({ items, selected, onToggle, activeColor = '#2E86D4', activeBg = 'rgba(46,134,212,0.2)' }: {
  items: { value: string; label: string }[]
  selected: string[]
  onToggle: (val: string) => void
  activeColor?: string
  activeBg?: string
}) {
  return (
    <div style={{ display:'flex',flexWrap:'wrap',gap:'4px',maxHeight:'140px',overflowY:'auto',padding:'6px',background:'#0F172A',border:'1px solid #1E293B',borderRadius:'6px' }}>
      {items.map(item => {
        const active = selected.includes(item.value)
        return (
          <button key={item.value} type="button"
            onClick={() => onToggle(item.value)}
            style={{ fontSize:'10px',padding:'3px 8px',borderRadius:'4px',border: active ? `1px solid ${activeColor}` : '1px solid #334155',background: active ? activeBg : 'transparent',color: active ? activeColor : '#94A3B8',cursor:'pointer',whiteSpace:'nowrap' }}>
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

function ScoreSlider({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  const color = value >= 4 ? '#4ADE80' : value === 3 ? '#F59E0B' : '#F87171'
  return (
    <div>
      <label style={{ fontSize:'10px',color:'#64748B',letterSpacing:'0.1em',display:'block',marginBottom:'6px' }}>
        {label} <span style={{ color,fontWeight:700 }}>{value}/5</span>
      </label>
      <input type="range" min="1" max="5" value={value}
        onChange={e => onChange(parseInt(e.target.value))}
        style={{ width:'100%',accentColor:'#2E86D4' }} />
    </div>
  )
}

function ReviewDrawer({ trade, onClose, onSaved }: {
  trade: Trade | null
  onClose: () => void
  onSaved: () => void
}) {
  const defaultForm: ReviewForm = {
    trade_key: '', setup_types: [], setup_family: '', setup_name: '', timeframe: 'Day',
    direction: 'LONG', market_regime: '', catalyst_type: '',
    entry_signals: [], exit_signals: [], entry_reason: '', exit_reason: '',
    emotion_before: 'neutral', emotion_during: 'calm', emotion_after: 'neutral',
    confidence_before: 3, stress_level: 2,
    execution_quality_score: 3, sizing_quality_score: 3, risk_management_score: 3,
    followed_plan: false, well_executed: false,
    planned_r: null, realized_r: null,
    lesson_learned: '', review_notes: '',
    mistake_tags: [], strength_tags: []
  }
  const [form, setForm] = useState<ReviewForm>(defaultForm)
  const [tab, setTab] = useState<DrawerTab>('Setup')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!trade) return
    const tf = trade.hold_days === 0 ? 'Day' : trade.hold_days <= 5 ? 'Swing' : trade.hold_days <= 30 ? 'Position' : 'Long Term'
    const dir = (trade.trade_type || '').toUpperCase() === 'SHORT' ? 'SHORT' : 'LONG'
    setForm({ ...defaultForm, trade_key: trade.trade_key, timeframe: tf, direction: dir,
      setup_family: trade.setup_family || trade.suggested_family || '',
      lesson_learned: trade.lessons || '' })
    setSaved(false)
    setTab('Setup')

    // Load existing review if present
    if (trade.review_id) {
      const encoded = trade.trade_key.replace(/:/g, '__')
      fetch(`/api/v2/journal/review/${encoded}`).then(r => r.json()).then(d => {
        if (d.ok && d.data?.exists && d.data.review) {
          const r = d.data.review
          setForm(prev => ({
            ...prev,
            setup_types: r.setup_types || [],
            setup_family: r.setup_family || prev.setup_family,
            setup_name: r.setup_name || '',
            timeframe: r.timeframe || prev.timeframe,
            direction: r.direction || prev.direction,
            market_regime: r.market_regime || '',
            catalyst_type: r.catalyst_type || '',
            entry_signals: r.entry_signals || [],
            exit_signals: r.exit_signals || [],
            entry_reason: r.entry_type || '',
            exit_reason: r.exit_type || '',
            emotion_before: r.emotion_before || 'neutral',
            emotion_during: r.emotion_during || 'calm',
            emotion_after: r.emotion_after || 'neutral',
            confidence_before: r.confidence_before ?? 3,
            stress_level: r.stress_level ?? 2,
            execution_quality_score: r.execution_quality_score ?? 3,
            sizing_quality_score: r.sizing_quality_score ?? 3,
            risk_management_score: r.risk_management_score ?? 3,
            followed_plan: r.followed_plan ?? false,
            well_executed: r.well_executed ?? false,
            planned_r: r.planned_r ?? null,
            realized_r: r.realized_r ?? null,
            lesson_learned: r.lesson_learned || '',
            review_notes: r.review_notes || '',
            mistake_tags: r.mistake_tags || [],
            strength_tags: r.strength_tags || [],
          }))
        }
      }).catch(() => {})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trade])

  const save = useCallback(async () => {
    if (!form.trade_key) return
    setSaving(true)
    try {
      // Build payload with correct DB field names
      const payload: any = {
        trade_key: form.trade_key,
        setup_types: form.setup_types,
        setup_family: form.setup_family,
        setup_name: form.setup_name || (form.setup_types[0] ? SETUP_TYPES.find(s => s.value === form.setup_types[0])?.label || '' : ''),
        timeframe: form.timeframe,
        direction: form.direction,
        market_regime: form.market_regime,
        catalyst_type: form.catalyst_type,
        entry_signals: form.entry_signals,
        exit_signals: form.exit_signals,
        entry_type: form.entry_reason,
        exit_type: form.exit_reason,
        emotion_before: form.emotion_before,
        emotion_during: form.emotion_during,
        emotion_after: form.emotion_after,
        confidence_before: form.confidence_before,
        stress_level: form.stress_level,
        execution_quality_score: form.execution_quality_score,
        sizing_quality_score: form.sizing_quality_score,
        risk_management_score: form.risk_management_score,
        followed_plan: form.followed_plan,
        well_executed: form.well_executed,
        lesson_learned: form.lesson_learned,
        review_notes: form.review_notes,
        mistake_tags: form.mistake_tags,
        strength_tags: form.strength_tags,
      }
      if (form.planned_r != null) payload.planned_r = form.planned_r
      if (form.realized_r != null) payload.realized_r = form.realized_r
      const res = await fetch('/api/v2/journal/review', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      const d = await res.json()
      if (d.ok) { setSaved(true); setTimeout(() => { onSaved(); onClose() }, 800) }
    } finally { setSaving(false) }
  }, [form, onSaved, onClose])

  if (!trade) return null

  const toggleArr = (arr: string[], val: string) => arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val]
  const inputStyle: React.CSSProperties = { width:'100%',background:'#0F172A',border:'1px solid #1E293B',color:'#E2E8F0',padding:'8px',borderRadius:'6px',fontSize:'12px',boxSizing:'border-box' }
  const selectStyle: React.CSSProperties = { ...inputStyle, padding:'7px 10px' }
  const lblStyle: React.CSSProperties = { fontSize:'10px',color:'#64748B',letterSpacing:'0.1em',display:'block',marginBottom:'6px' }

  return (
    <>
      <div onClick={onClose} style={{ position:'fixed',inset:0,background:'rgba(0,0,0,0.6)',zIndex:999,backdropFilter:'blur(3px)' }} />
      <div style={{
        position:'fixed',top:'2vh',bottom:'2vh',left:'50%',transform:'translateX(-50%)',
        width:'960px',maxWidth:'95vw',background:'#0B1120',
        border:'1px solid #1E293B',borderRadius:'12px',zIndex:1000,overflowY:'auto',
        boxShadow:'0 24px 80px rgba(0,0,0,0.8)',display:'flex',flexDirection:'column'
      }}>
        {/* Header */}
        <div style={{ padding:'16px 24px',borderBottom:'1px solid #1E293B',background:'#0D1426',position:'sticky',top:0,zIndex:10,borderRadius:'12px 12px 0 0',flexShrink:0 }}>
          <div style={{ display:'flex',alignItems:'center',justifyContent:'space-between' }}>
            <div>
              <div style={{ display:'flex',alignItems:'center',gap:'10px' }}>
                <span style={{ fontSize:'22px',fontWeight:800,color:'#F1F5F9',letterSpacing:'0.05em' }}>{trade.symbol}</span>
                <span style={{ fontSize:'12px',fontWeight:700,padding:'3px 10px',borderRadius:'4px',
                  background: trade.pnl>=0 ? '#0D1F0D' : '#1F0D0D',
                  color: trade.pnl>=0 ? '#4ADE80' : '#F87171' }}>
                  {fmt$(trade.pnl)} / {trade.pnl_pct>=0?'+':''}{trade.pnl_pct.toFixed(1)}%
                </span>
                <span style={{ fontSize:'11px',padding:'2px 8px',borderRadius:'4px',background:'#1E293B',color:'#94A3B8',fontFamily:'monospace' }}>{trade.trade_type}</span>
                {trade.review_id && <span style={{ fontSize:'10px',color:'#4ADE80',background:'#0D1F0D',padding:'2px 8px',borderRadius:'4px' }}>REVIEWED</span>}
                {trade.suggested_setup && !trade.review_id && <span style={{ fontSize:'10px',color:'#F59E0B',background:'#1F1800',padding:'2px 8px',borderRadius:'4px' }}>AI DRAFT</span>}
              </div>
              <div style={{ display:'flex',gap:'16px',marginTop:'6px',fontSize:'11px',color:'#64748B' }}>
                <span>Buy: <strong style={{color:'#E2E8F0'}}>${trade.buy_price?.toFixed(2)}</strong></span>
                <span>Sell: <strong style={{color:'#E2E8F0'}}>${trade.sell_price?.toFixed(2)}</strong></span>
                <span>{ACCT_SHORT[trade.account]||trade.account}</span>
                <span style={{ fontWeight:700,color: trade.hold_days === 0 ? '#60A5FA' : trade.hold_days <= 5 ? '#F59E0B' : '#4ADE80' }}>
                  {trade.hold_days === 0 ? 'INTRADAY' : `${trade.hold_days}d`}
                </span>
                <span>{trade.shares} shares</span>
              </div>
            </div>
            <button onClick={onClose} style={{ background:'none',border:'1px solid #334155',color:'#94A3B8',width:'32px',height:'32px',borderRadius:'6px',cursor:'pointer',fontSize:'18px' }}>×</button>
          </div>
          {/* Tab bar */}
          <div style={{ display:'flex',gap:'2px',marginTop:'12px' }}>
            {DRAWER_TABS.map(t => (
              <button key={t} onClick={() => setTab(t)}
                style={{ padding:'6px 16px',borderRadius:'6px 6px 0 0',fontSize:'12px',fontWeight:600,cursor:'pointer',
                  background: tab===t ? '#0B1120' : 'transparent',
                  border: tab===t ? '1px solid #1E293B' : '1px solid transparent',
                  borderBottom: tab===t ? '1px solid #0B1120' : '1px solid #1E293B',
                  color: tab===t ? '#60A5FA' : '#64748B' }}>
                {t}
              </button>
            ))}
          </div>
        </div>

        <div style={{ padding:'20px 24px',flex:1,overflowY:'auto' }}>
          {saved && <div style={{ background:'#0D1F0D',border:'1px solid #166534',borderRadius:'6px',padding:'10px 16px',color:'#4ADE80',fontSize:'13px',marginBottom:'16px',textAlign:'center' }}>Review saved!</div>}

          {/* ─── Tab: Setup ─── */}
          {tab === 'Setup' && <>
            <div style={{ marginBottom:'16px' }}>
              <label style={lblStyle}>SETUP TYPE (select all that apply)</label>
              {trade.suggested_setup && !trade.review_id && (
                <button onClick={() => {
                  const aiTags: string[] = trade.suggested_types || [trade.suggested_setup!]
                  const newTypes = [...form.setup_types]
                  for (const tag of aiTags) { if (!newTypes.includes(tag)) newTypes.push(tag) }
                  const primary = SETUP_TYPES.find(x => x.value === newTypes[0])
                  setForm(f => ({...f, setup_types: newTypes, setup_family: primary?.family || ''}))
                }}
                style={{ marginBottom:'8px',padding:'5px 14px',borderRadius:'4px',fontSize:'11px',cursor:'pointer',fontWeight:600,background:'#1F1800',border:'1px solid #F59E0B',color:'#F59E0B' }}>
                  Use AI suggestion: {trade.suggestion_rationale || trade.suggested_setup}
                </button>
              )}
              <ChipGrid items={SETUP_TYPES} selected={form.setup_types}
                onToggle={val => setForm(f => {
                  const types = toggleArr(f.setup_types, val)
                  return {...f, setup_types: types, setup_family: SETUP_TYPES.find(x => x.value === (types[0]||''))?.family || ''}
                })} />
              {form.setup_types.length > 0 && <div style={{ fontSize:'10px',color:'#60A5FA',marginTop:'4px' }}>{form.setup_types.length} selected: {form.setup_types.map(v => SETUP_TYPES.find(s=>s.value===v)?.label || v).join(', ')}</div>}
            </div>

            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <div>
                <label style={lblStyle}>TIMEFRAME</label>
                <div style={{ display:'flex',gap:'4px',flexWrap:'wrap' }}>
                  {TIMEFRAMES.map(t => (
                    <button key={t} onClick={() => setForm(f => ({...f, timeframe:t}))}
                      style={{ padding:'5px 12px',borderRadius:'4px',fontSize:'11px',cursor:'pointer',
                        background: form.timeframe===t ? '#1E3A5F' : '#0F172A',
                        border: `1px solid ${form.timeframe===t ? '#2E86D4' : '#1E293B'}`,
                        color: form.timeframe===t ? '#60A5FA' : '#64748B' }}>{t}</button>
                  ))}
                </div>
              </div>
              <div>
                <label style={lblStyle}>DIRECTION</label>
                <div style={{ display:'flex',gap:'4px' }}>
                  {DIRECTIONS.map(d => (
                    <button key={d} onClick={() => setForm(f => ({...f, direction:d}))}
                      style={{ padding:'5px 16px',borderRadius:'4px',fontSize:'11px',cursor:'pointer',fontWeight:600,
                        background: form.direction===d ? (d==='LONG'?'#0D1F0D':'#1F0D0D') : '#0F172A',
                        border: `1px solid ${form.direction===d ? (d==='LONG'?'#166534':'#991B1B') : '#1E293B'}`,
                        color: form.direction===d ? (d==='LONG'?'#4ADE80':'#F87171') : '#64748B' }}>{d}</button>
                  ))}
                </div>
              </div>
              <div>
                <label style={lblStyle}>MARKET REGIME</label>
                <select value={form.market_regime} onChange={e => setForm(f => ({...f, market_regime:e.target.value}))} style={selectStyle}>
                  <option value="">Select...</option>
                  {MARKET_REGIMES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>

            <div style={{ marginBottom:'16px' }}>
              <label style={lblStyle}>CATALYST TYPE</label>
              <div style={{ display:'flex',gap:'4px',flexWrap:'wrap' }}>
                {CATALYST_TYPES.map(c => (
                  <button key={c} onClick={() => setForm(f => ({...f, catalyst_type: f.catalyst_type===c ? '' : c}))}
                    style={{ padding:'4px 12px',borderRadius:'4px',fontSize:'11px',cursor:'pointer',textTransform:'capitalize',
                      background: form.catalyst_type===c ? '#1E3A5F' : '#0F172A',
                      border: `1px solid ${form.catalyst_type===c ? '#2E86D4' : '#1E293B'}`,
                      color: form.catalyst_type===c ? '#60A5FA' : '#64748B' }}>{c}</button>
                ))}
              </div>
            </div>
          </>}

          {/* ─── Tab: Signals ─── */}
          {tab === 'Signals' && <>
            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <div>
                <label style={lblStyle}>ENTRY SIGNALS</label>
                <ChipGrid items={ENTRY_SIGNALS} selected={form.entry_signals}
                  onToggle={val => setForm(f => ({...f, entry_signals: toggleArr(f.entry_signals, val)}))} />
                {form.entry_signals.length > 0 && <div style={{ fontSize:'10px',color:'#60A5FA',marginTop:'4px' }}>{form.entry_signals.length} selected</div>}
              </div>
              <div>
                <label style={lblStyle}>EXIT SIGNALS</label>
                <ChipGrid items={EXIT_SIGNALS} selected={form.exit_signals}
                  onToggle={val => setForm(f => ({...f, exit_signals: toggleArr(f.exit_signals, val)}))}
                  activeColor="#4ADE80" activeBg="rgba(22,163,74,0.2)" />
                {form.exit_signals.length > 0 && <div style={{ fontSize:'10px',color:'#4ADE80',marginTop:'4px' }}>{form.exit_signals.length} selected</div>}
              </div>
            </div>
            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <div>
                <label style={lblStyle}>ENTRY REASON</label>
                <textarea value={form.entry_reason} onChange={e => setForm(f => ({...f, entry_reason:e.target.value}))}
                  placeholder="Why did you enter?" rows={3} style={{ ...inputStyle, resize:'vertical' }} />
              </div>
              <div>
                <label style={lblStyle}>EXIT REASON</label>
                <textarea value={form.exit_reason} onChange={e => setForm(f => ({...f, exit_reason:e.target.value}))}
                  placeholder="Why did you exit?" rows={3} style={{ ...inputStyle, resize:'vertical' }} />
              </div>
            </div>
          </>}

          {/* ─── Tab: Execution ─── */}
          {tab === 'Execution' && <>
            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <ScoreSlider label="EXECUTION QUALITY" value={form.execution_quality_score}
                onChange={v => setForm(f => ({...f, execution_quality_score:v}))} />
              <ScoreSlider label="SIZING QUALITY" value={form.sizing_quality_score}
                onChange={v => setForm(f => ({...f, sizing_quality_score:v}))} />
              <ScoreSlider label="RISK MANAGEMENT" value={form.risk_management_score}
                onChange={v => setForm(f => ({...f, risk_management_score:v}))} />
            </div>

            <div style={{ display:'flex',gap:'20px',marginBottom:'16px' }}>
              {[{field:'followed_plan' as const, label:'Followed the plan'}, {field:'well_executed' as const, label:'Well executed'}].map(({field,label}) => (
                <label key={field} style={{ display:'flex',alignItems:'center',gap:'8px',cursor:'pointer' }}>
                  <input type="checkbox" checked={form[field]}
                    onChange={e => setForm(f => ({...f, [field]:e.target.checked}))}
                    style={{ width:'16px',height:'16px',accentColor:'#2E86D4' }} />
                  <span style={{ fontSize:'13px',color:'#94A3B8' }}>{label}</span>
                </label>
              ))}
            </div>

            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <div>
                <label style={lblStyle}>PLANNED R-MULTIPLE</label>
                <div style={{ display:'flex',alignItems:'center',gap:'8px' }}>
                  <input type="number" step="0.1" min="0" value={form.planned_r ?? ''}
                    onChange={e => setForm(f => ({...f, planned_r: e.target.value ? parseFloat(e.target.value) : null}))}
                    placeholder="e.g. 2.0" style={{ ...inputStyle, width:'100px' }} />
                  <span style={{ fontSize:'11px',color:'#64748B' }}>: 1 risk/reward</span>
                </div>
              </div>
              <div>
                <label style={lblStyle}>REALIZED R-MULTIPLE</label>
                <input type="number" step="0.1" value={form.realized_r ?? ''}
                  onChange={e => setForm(f => ({...f, realized_r: e.target.value ? parseFloat(e.target.value) : null}))}
                  placeholder="e.g. -0.7" style={{ ...inputStyle, width:'100px' }} />
              </div>
            </div>
          </>}

          {/* ─── Tab: Psychology ─── */}
          {tab === 'Psychology' && <>
            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              {[{field:'emotion_before' as const, label:'EMOTION BEFORE'}, {field:'emotion_during' as const, label:'EMOTION DURING'}, {field:'emotion_after' as const, label:'EMOTION AFTER'}].map(({field,label}) => (
                <div key={field}>
                  <label style={lblStyle}>{label}</label>
                  <select value={form[field]} onChange={e => setForm(f => ({...f, [field]:e.target.value}))} style={selectStyle}>
                    {EMOTIONS.map(e => <option key={e} value={e}>{e}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <ScoreSlider label="CONFIDENCE BEFORE TRADE" value={form.confidence_before}
                onChange={v => setForm(f => ({...f, confidence_before:v}))} />
              <ScoreSlider label="STRESS LEVEL" value={form.stress_level}
                onChange={v => setForm(f => ({...f, stress_level:v}))} />
            </div>
          </>}

          {/* ─── Tab: Review ─── */}
          {tab === 'Review' && <>
            <div style={{ marginBottom:'16px' }}>
              <label style={lblStyle}>LESSON LEARNED</label>
              <textarea value={form.lesson_learned} onChange={e => setForm(f => ({...f, lesson_learned:e.target.value}))}
                placeholder="What did you learn? What would you do differently?" rows={3}
                style={{ ...inputStyle, resize:'vertical', lineHeight:'1.6' }} />
            </div>
            <div style={{ marginBottom:'16px' }}>
              <label style={lblStyle}>REVIEW NOTES</label>
              <textarea value={form.review_notes} onChange={e => setForm(f => ({...f, review_notes:e.target.value}))}
                placeholder="General trade notes, observations, context..." rows={3}
                style={{ ...inputStyle, resize:'vertical', lineHeight:'1.6' }} />
            </div>
            <div style={{ display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px',marginBottom:'16px' }}>
              <div>
                <label style={lblStyle}>MISTAKES</label>
                <ChipGrid items={MISTAKE_TAGS} selected={form.mistake_tags}
                  onToggle={val => setForm(f => ({...f, mistake_tags: toggleArr(f.mistake_tags, val)}))}
                  activeColor="#F87171" activeBg="rgba(248,113,113,0.15)" />
              </div>
              <div>
                <label style={lblStyle}>STRENGTHS</label>
                <ChipGrid items={STRENGTH_TAGS} selected={form.strength_tags}
                  onToggle={val => setForm(f => ({...f, strength_tags: toggleArr(f.strength_tags, val)}))}
                  activeColor="#4ADE80" activeBg="rgba(74,222,128,0.15)" />
              </div>
            </div>
          </>}

          {tab === 'Backtest' && <>
            <BacktestPanel tradeKey={trade.trade_key} />
            <EntrySignalsPanel tradeKey={trade.trade_key} />
          </>}
        </div>

        {/* Sticky footer */}
        <div style={{ padding:'16px 24px',borderTop:'1px solid #1E293B',background:'#0D1426',flexShrink:0 }}>
          <button onClick={save} disabled={saving || saved || form.setup_types.length === 0}
            style={{
              width:'100%',padding:'12px',borderRadius:'8px',fontSize:'14px',fontWeight:700,cursor:'pointer',
              background: saved ? '#166534' : (form.setup_types.length === 0 ? '#1E293B' : '#1E3A5F'),
              border: `1px solid ${saved ? '#4ADE80' : (form.setup_types.length === 0 ? '#334155' : '#2E86D4')}`,
              color: saved ? '#4ADE80' : (form.setup_types.length === 0 ? '#475569' : '#60A5FA'),
            }}>
            {saving ? 'Saving...' : saved ? 'Saved' : form.setup_types.length === 0 ? 'Select a setup type to save' : 'Save Review'}
          </button>
        </div>
      </div>
    </>
  )
}

// ── Annotation Queue ───────────────────────────────────────────────────────
function AnnotationQueue({ onOpenReview }: { onOpenReview: (t: Trade) => void }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [bulkRunning, setBulkRunning] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/v2/journal/unannotated').then(r=>r.json())
      .then(d => { if (d.ok) setData(d.data) })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const bulkSuggest = async () => {
    setBulkRunning(true)
    await fetch('/api/v2/journal/bulk-suggest', { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' })
    await load()
    setBulkRunning(false)
  }

  if (loading) return <div style={{ color:'#64748B',fontSize:'13px',padding:'16px' }}>Loading annotation queue…</div>
  if (!data || data.unannotated_count === 0) return (
    <div style={{ background:'#0D1F0D',border:'1px solid #166534',borderRadius:'8px',padding:'16px',marginBottom:'16px',display:'flex',alignItems:'center',gap:'12px' }}>
      <span style={{ fontSize:'18px' }}>✓</span>
      <span style={{ color:'#4ADE80',fontSize:'14px',fontWeight:600 }}>All {data?.total || 0} trades reviewed ({data?.coverage_pct || 100}% coverage)</span>
    </div>
  )

  const coveragePct = data.coverage_pct
  const barColor = coveragePct >= 80 ? '#4ADE80' : coveragePct >= 40 ? '#F59E0B' : '#EF4444'

  return (
    <div style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',marginBottom:'20px',overflow:'hidden' }}>
      {/* Queue header */}
      <div style={{ padding:'14px 20px',borderBottom: collapsed ? 'none' : '1px solid #1E293B',display:'flex',alignItems:'center',gap:'12px',cursor:'pointer' }}
        onClick={() => setCollapsed(!collapsed)}>
        <div style={{ flex:1 }}>
          <div style={{ display:'flex',alignItems:'center',gap:'10px' }}>
            <span style={{ fontSize:'13px',fontWeight:700,color:'#F1F5F9' }}>ANNOTATION QUEUE</span>
            <span style={{ background:'#7C2D12',color:'#FCA5A5',fontSize:'10px',fontWeight:700,padding:'2px 8px',borderRadius:'10px' }}>
              {data.unannotated_count} PENDING
            </span>
            <span style={{ fontSize:'11px',color:'#64748B' }}>{data.annotated_count} reviewed of {data.total}</span>
          </div>
          {/* Coverage bar */}
          <div style={{ display:'flex',alignItems:'center',gap:'8px',marginTop:'6px' }}>
            <div style={{ flex:1,height:'4px',background:'#1E293B',borderRadius:'2px',overflow:'hidden' }}>
              <div style={{ width:`${coveragePct}%`,height:'100%',background:barColor,borderRadius:'2px',transition:'width 0.5s ease' }} />
            </div>
            <span style={{ fontSize:'11px',color:barColor,fontWeight:700,minWidth:'36px' }}>{coveragePct}%</span>
          </div>
        </div>
        <div style={{ display:'flex',gap:'8px',alignItems:'center' }}>
          <button onClick={e => { e.stopPropagation(); bulkSuggest() }} disabled={bulkRunning}
            style={{ background:'#1E293B',border:'1px solid #334155',color:'#94A3B8',padding:'6px 14px',borderRadius:'6px',fontSize:'11px',cursor:'pointer',fontWeight:600 }}>
            {bulkRunning ? 'Running…' : '⚡ Auto-classify all'}
          </button>
          <span style={{ color:'#475569',fontSize:'14px' }}>{collapsed ? '▼' : '▲'}</span>
        </div>
      </div>

      {!collapsed && (
        <div style={{ maxHeight:'320px',overflowY:'auto' }}>
          {/* Column headers */}
          <div style={{ display:'grid',gridTemplateColumns:'90px 70px 70px 80px 1fr 120px 80px',gap:'8px',padding:'8px 20px',fontSize:'10px',color:'#475569',letterSpacing:'0.05em',borderBottom:'1px solid #0F172A' }}>
            <span>DATE</span><span>SYMBOL</span><span>TYPE</span><span>P&L</span><span>SUGGESTED SETUP</span><span>ACCT</span><span></span>
          </div>
          {data.unannotated.map((t: Trade, i: number) => (
            <div key={t.trade_key} style={{
              display:'grid',gridTemplateColumns:'90px 70px 70px 80px 1fr 120px 80px',
              gap:'8px',padding:'9px 20px',alignItems:'center',
              background: i%2===0 ? 'transparent' : '#08101E',
              borderBottom:'1px solid #0A1220'
            }}>
              <span style={{ fontSize:'11px',color:'#64748B' }}>{t.close_date}</span>
              <span style={{ fontSize:'13px',fontWeight:700,color:'#60A5FA' }}>{t.symbol}</span>
              <span style={{ fontSize:'11px',color:'#64748B' }}>{t.trade_type}</span>
              <span style={{ fontSize:'12px',fontWeight:600,color:t.pnl>=0?'#4ADE80':'#F87171' }}>{fmt$(t.pnl)}</span>
              <div>
                <span style={{ fontSize:'11px',color:'#F59E0B',background:'#1A1200',padding:'2px 7px',borderRadius:'3px' }}>
                  {t.suggested_setup?.replace(/_/g,' ')}
                </span>
                <span style={{ fontSize:'10px',color:'#475569',marginLeft:'6px' }}>{t.suggestion_rationale}</span>
              </div>
              <span style={{ fontSize:'11px',color:'#64748B' }}>{ACCT_SHORT[t.account]||t.account}</span>
              <button onClick={() => onOpenReview(t)}
                style={{ background:'#1E3A5F',border:'1px solid #2E86D4',color:'#60A5FA',padding:'4px 10px',borderRadius:'4px',fontSize:'11px',cursor:'pointer',fontWeight:600 }}>
                Review →
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Journal Component ─────────────────────────────────────────────────
// ── Previously Traded Tab ─────────────────────────────────────────────────
function PreviouslyTradedTab() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [queuedSymbols, setQueuedSymbols] = useState<Set<string>>(new Set())

  useEffect(() => {
    fetch('/api/v2/journal/previously-traded').then(r=>r.json()).then(d => {
      if (d.ok) setData(d.data?.symbols || [])
    }).finally(() => setLoading(false))
  }, [])

  const triggerDeepAnalysis = async (symbol: string) => {
    setQueuedSymbols(prev => new Set(prev).add(symbol))
    try {
      await fetch('/api/v2/watchlist/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: [symbol], chain: 'full' })
      })
      setTimeout(() => { window.open(`/v2/watchlist/${symbol}`, '_blank') }, 3000)
    } catch (e) { /* ignore */ }
  }

  if (loading) return <div style={{color:'#64748B',fontSize:'13px',padding:'16px'}}>Loading previously traded...</div>

  const signalColor: Record<string,string> = { IN_ZONE:'#4ADE80', WATCH:'#F59E0B', ABOVE_ZONE:'#60A5FA', BELOW_ZONE:'#F87171' }
  const signalBg: Record<string,string> = { IN_ZONE:'#0D1F0D', WATCH:'#1F1800', ABOVE_ZONE:'#0D1626', BELOW_ZONE:'#1F0D0D' }

  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:'10px',marginBottom:'16px'}}>
        {[
          {label:'IN ZONE',count:data.filter(d=>d.reentry_signal==='IN_ZONE').length,color:'#4ADE80'},
          {label:'WATCH',count:data.filter(d=>d.reentry_signal==='WATCH').length,color:'#F59E0B'},
          {label:'BELOW ZONE',count:data.filter(d=>d.reentry_signal==='BELOW_ZONE').length,color:'#F87171'},
          {label:'ABOVE ZONE',count:data.filter(d=>d.reentry_signal==='ABOVE_ZONE').length,color:'#60A5FA'},
        ].map(t => (
          <div key={t.label} style={{background:'#0F172A',border:'1px solid #1E293B',borderRadius:'8px',padding:'12px'}}>
            <div style={{fontSize:'10px',color:'#64748B',fontFamily:'monospace'}}>{t.label}</div>
            <div style={{fontSize:'24px',fontWeight:700,color:t.color}}>{t.count}</div>
          </div>
        ))}
      </div>
      <table style={{width:'100%',borderCollapse:'collapse',fontSize:'12px'}}>
        <thead>
          <tr style={{borderBottom:'1px solid #1E293B'}}>
            {['SYMBOL','SIGNAL','PRICE','ZONE','BEST TRADE','EXIT DATE','vs EXIT',''].map(h =>
              <th key={h} style={{textAlign:'left',padding:'8px',color:'#64748B',fontFamily:'monospace',fontSize:'10px'}}>{h}</th>
            )}
          </tr>
        </thead>
        <tbody>
          {data.map(item => (
            <tr key={item.symbol} style={{borderBottom:'1px solid #0F172A'}}>
              <td style={{padding:'8px'}}>
                <a href={`/v2/watchlist/${item.symbol}`} style={{color:'#60A5FA',fontWeight:700,textDecoration:'none',fontFamily:'monospace'}}>{item.symbol}</a>
              </td>
              <td style={{padding:'8px'}}>
                <span style={{fontSize:'10px',padding:'2px 8px',borderRadius:'4px',fontWeight:600,
                  background:signalBg[item.reentry_signal]||'#1E293B',
                  color:signalColor[item.reentry_signal]||'#64748B'}}>
                  {item.reentry_signal}
                </span>
              </td>
              <td style={{padding:'8px',fontFamily:'monospace',color:'#E2E8F0'}}>${parseFloat(item.current_price||0).toFixed(2)}</td>
              <td style={{padding:'8px',fontFamily:'monospace',color:'#94A3B8',fontSize:'11px'}}>
                ${parseFloat(item.reentry_zone_low||0).toFixed(2)} – ${parseFloat(item.reentry_zone_high||0).toFixed(2)}
              </td>
              <td style={{padding:'8px',color:'#4ADE80',fontWeight:600}}>+{parseFloat(item.best_pnl_pct||0).toFixed(0)}% / ${parseFloat(item.best_pnl||0).toLocaleString()}</td>
              <td style={{padding:'8px',color:'#64748B'}}>{item.last_exit_date}</td>
              <td style={{padding:'8px',fontFamily:'monospace',fontWeight:600,
                color: parseFloat(item.pct_above_exit||0) > 50 ? '#F87171' : parseFloat(item.pct_above_exit||0) < 0 ? '#4ADE80' : '#94A3B8'}}>
                {parseFloat(item.pct_above_exit||0) >= 0 ? '+' : ''}{parseFloat(item.pct_above_exit||0).toFixed(0)}%
              </td>
              <td style={{padding:'8px'}}>
                <button onClick={() => triggerDeepAnalysis(item.symbol)}
                  disabled={queuedSymbols.has(item.symbol)}
                  style={{background:'#1E293B',border:'1px solid #334155',color: queuedSymbols.has(item.symbol) ? '#475569' : '#94A3B8',
                    padding:'3px 10px',borderRadius:'4px',fontSize:'10px',cursor:'pointer',fontWeight:600,whiteSpace:'nowrap'}}>
                  {queuedSymbols.has(item.symbol) ? 'Queued...' : 'Deep Analysis'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Journal() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [unannotated, setUnannotated] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [reviewTrade, setReviewTrade] = useState<Trade | null>(null)
  const [filterType, setFilterType] = useState('All')
  const [filterAcct, setFilterAcct] = useState('All')
  const [filterResult, setFilterResult] = useState('All')
  const [filterAnnotated, setFilterAnnotated] = useState('All')
  const [sortCol, setSortCol] = useState('close_date')
  const [sortDir, setSortDir] = useState<'asc'|'desc'>('desc')
  const [calView, setCalView] = useState<'month'|'list'>('list')
  const [calDate, setCalDate] = useState(new Date())
  const [activeTab, setActiveTab] = useState<'trades'|'prev_traded'>('trades')

  const loadAll = useCallback(async () => {
    setLoading(true)
    const [jRes, uRes] = await Promise.all([
      fetch('/api/v2/journal?limit=500').then(r=>r.json()).catch(()=>({ok:false})),
      fetch('/api/v2/journal/unannotated').then(r=>r.json()).catch(()=>({ok:false}))
    ])
    if (jRes.ok) setTrades(jRes.data?.trades || [])
    if (uRes.ok) setUnannotated(uRes.data?.unannotated || [])
    setLoading(false)
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  // Merge review status into trades
  const tradesWithStatus = useMemo(() => {
    const unannotatedKeys = new Set(unannotated.map((t: Trade) => t.trade_key))
    return trades.map(t => ({
      ...t,
      is_annotated: !unannotatedKeys.has(t.trade_key)
    }))
  }, [trades, unannotated])

  // Stats
  const stats = useMemo(() => {
    if (!tradesWithStatus.length) return null
    const winners = tradesWithStatus.filter(t => t.pnl > 0)
    const losers = tradesWithStatus.filter(t => t.pnl < 0)
    const totalPnl = tradesWithStatus.reduce((s,t) => s+t.pnl, 0)
    const avgWin = winners.length ? winners.reduce((s,t)=>s+t.pnl,0)/winners.length : 0
    const avgLoss = losers.length ? Math.abs(losers.reduce((s,t)=>s+t.pnl,0)/losers.length) : 0
    const pf = avgLoss > 0 ? (winners.reduce((s,t)=>s+t.pnl,0) / Math.abs(losers.reduce((s,t)=>s+t.pnl,0))) : 0
    const expectancy = (winners.length/tradesWithStatus.length)*avgWin - (losers.length/tradesWithStatus.length)*avgLoss
    const annotated = tradesWithStatus.filter(t => (t as any).is_annotated).length
    return {
      total: tradesWithStatus.length, winners: winners.length, losers: losers.length,
      winRate: (winners.length/tradesWithStatus.length*100).toFixed(1),
      totalPnl, avgWin, avgLoss, pf, expectancy,
      annotated, coveragePct: (annotated/tradesWithStatus.length*100).toFixed(0)
    }
  }, [tradesWithStatus])

  // Filter + sort
  const filtered = useMemo(() => {
    let result = tradesWithStatus
    if (filterType !== 'All') result = result.filter(t => t.trade_type === filterType)
    if (filterAcct !== 'All') result = result.filter(t => t.account.includes(filterAcct.toLowerCase()))
    if (filterResult === 'Win') result = result.filter(t => t.pnl > 0)
    if (filterResult === 'Loss') result = result.filter(t => t.pnl < 0)
    if (filterAnnotated === 'Reviewed') result = result.filter(t => (t as any).is_annotated)
    if (filterAnnotated === 'Pending') result = result.filter(t => !(t as any).is_annotated)
    return [...result].sort((a, b) => {
      let av: any = a[sortCol as keyof Trade], bv: any = b[sortCol as keyof Trade]
      if (typeof av === 'string') av = av.toLowerCase(), bv = (bv as string).toLowerCase()
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [tradesWithStatus, filterType, filterAcct, filterResult, filterAnnotated, sortCol, sortDir])

  const sort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const Th = ({ col, label }: { col: string; label: string }) => (
    <th onClick={() => sort(col)} style={{ padding:'9px 12px',textAlign:'left',cursor:'pointer',
      color: sortCol===col ? '#60A5FA' : '#64748B',fontSize:'10px',letterSpacing:'0.08em',
      fontWeight:600,userSelect:'none',whiteSpace:'nowrap' }}>
      {label} {sortCol===col ? (sortDir==='desc'?'↓':'↑') : ''}
    </th>
  )

  const typeColors: Record<string,string> = { DAY:'#60A5FA',LONG:'#4ADE80',SWING:'#F59E0B',SHORT:'#F87171',UNKNOWN:'#64748B' }

  if (loading) return <div style={{ padding:'40px',color:'#60A5FA',fontSize:'14px' }}>Loading Trade Journal…</div>

  return (
    <div style={{ padding:'24px',color:'#E2E8F0',maxWidth:'1400px',margin:'0 auto' }}>
      <ReviewDrawer trade={reviewTrade} onClose={() => setReviewTrade(null)} onSaved={loadAll} />

      {/* Header */}
      <div style={{ marginBottom:'12px',display:'flex',alignItems:'flex-start',justifyContent:'space-between' }}>
        <div>
          <h1 style={{ fontSize:'24px',fontWeight:700,color:'#F1F5F9',marginBottom:'4px' }}>Trade Journal</h1>
          <p style={{ color:'#64748B',fontSize:'13px' }}>
            {stats?.total} closed trades · {filtered.length} shown · {stats?.annotated} reviewed ({stats?.coveragePct}%)
          </p>
        </div>
        <div style={{ display:'flex',gap:'8px' }}>
          <a href="/v2/journal-analytics"
            style={{ background:'#1E293B',border:'1px solid #334155',color:'#94A3B8',padding:'8px 16px',borderRadius:'6px',fontSize:'12px',textDecoration:'none',fontWeight:600 }}>
            Analytics →
          </a>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display:'flex',gap:'4px',marginBottom:'16px',borderBottom:'1px solid #1E293B',paddingBottom:'8px' }}>
        {([['trades','Closed Trades'],['prev_traded','Previously Traded']] as const).map(([key, label]) => (
          <button key={key} onClick={() => setActiveTab(key)}
            style={{ padding:'6px 16px',borderRadius:'4px 4px 0 0',fontSize:'12px',fontWeight:600,cursor:'pointer',
              background: activeTab===key ? '#1E3A5F' : 'transparent',
              border: activeTab===key ? '1px solid #2E86D4' : '1px solid transparent',
              borderBottom: 'none',
              color: activeTab===key ? '#60A5FA' : '#64748B' }}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'prev_traded' && <PreviouslyTradedTab />}
      {activeTab === 'trades' && (<>

      {/* Stats bar */}
      {stats && (
        <div style={{ display:'grid',gridTemplateColumns:'repeat(7,1fr)',gap:'10px',marginBottom:'20px' }}>
          {[
            { label:'NET P&L', value:fmt$(stats.totalPnl), color: stats.totalPnl>=0?'#4ADE80':'#F87171' },
            { label:'WIN RATE', value:`${stats.winRate}%`, color:'#60A5FA' },
            { label:'PROFIT FACTOR', value:stats.pf.toFixed(2), color:'#F59E0B' },
            { label:'AVG WINNER', value:fmt$(stats.avgWin), color:'#4ADE80' },
            { label:'AVG LOSER', value:`-$${stats.avgLoss.toFixed(0)}`, color:'#F87171' },
            { label:'EXPECTANCY', value:fmt$(stats.expectancy), color: stats.expectancy>=0?'#4ADE80':'#F87171' },
            { label:'ANNOTATED', value:`${stats.annotated}/${stats.total}`, color: parseInt(stats.coveragePct)>=80?'#4ADE80':'#F59E0B' },
          ].map(s => (
            <div key={s.label} style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',padding:'14px 16px' }}>
              <div style={{ fontSize:'9px',color:'#64748B',letterSpacing:'0.1em',marginBottom:'6px',fontWeight:600 }}>{s.label}</div>
              <div style={{ fontSize:'18px',fontWeight:700,color:s.color }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Annotation Queue */}
      <AnnotationQueue onOpenReview={setReviewTrade} />

      {/* Filters */}
      <div style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',padding:'12px 16px',marginBottom:'16px' }}>
        <div style={{ display:'flex',gap:'16px',flexWrap:'wrap',alignItems:'center' }}>
          {[
            { label:'Type', options:['All','DAY','LONG','SWING','SHORT','UNKNOWN'], state:filterType, set:setFilterType },
            { label:'Account', options:['All','rollover','roth','taxable','401k'], state:filterAcct, set:setFilterAcct },
            { label:'Result', options:['All','Win','Loss'], state:filterResult, set:setFilterResult },
            { label:'Review', options:['All','Reviewed','Pending'], state:filterAnnotated, set:setFilterAnnotated },
          ].map(({ label, options, state, set }) => (
            <div key={label} style={{ display:'flex',alignItems:'center',gap:'8px' }}>
              <span style={{ fontSize:'10px',color:'#64748B',letterSpacing:'0.08em',fontWeight:600,minWidth:'44px' }}>{label}</span>
              <div style={{ display:'flex',gap:'4px' }}>
                {options.map(o => (
                  <button key={o} onClick={() => set(o)}
                    style={{
                      padding:'3px 10px',borderRadius:'4px',fontSize:'11px',cursor:'pointer',fontWeight:600,
                      background: state===o ? '#1E3A5F' : 'transparent',
                      border: `1px solid ${state===o ? '#2E86D4' : '#1E293B'}`,
                      color: state===o ? '#60A5FA' : '#64748B'
                    }}>{o}</button>
                ))}
              </div>
            </div>
          ))}
          <span style={{ marginLeft:'auto',fontSize:'12px',color:'#475569' }}>{filtered.length} trades</span>
        </div>
      </div>

      {/* Trade Table */}
      <div style={{ background:'#0D1626',border:'1px solid #1E293B',borderRadius:'8px',overflow:'hidden' }}>
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%',borderCollapse:'collapse',fontSize:'13px' }}>
            <thead>
              <tr style={{ borderBottom:'1px solid #1E293B',background:'#0A1018' }}>
                <Th col="close_date" label="CLOSED" />
                <Th col="symbol" label="SYMBOL" />
                <Th col="trade_type" label="TYPE" />
                <Th col="shares" label="SHARES" />
                <Th col="buy_price" label="ENTRY" />
                <Th col="sell_price" label="EXIT" />
                <Th col="pnl" label="P&L" />
                <Th col="pnl_pct" label="%" />
                <Th col="hold_days" label="DAYS" />
                <th style={{ padding:'9px 12px',color:'#64748B',fontSize:'10px',letterSpacing:'0.08em' }}>ACCT</th>
                <th style={{ padding:'9px 12px',color:'#64748B',fontSize:'10px',letterSpacing:'0.08em' }}>SETUP</th>
                <th style={{ padding:'9px 12px',color:'#64748B',fontSize:'10px',letterSpacing:'0.08em' }}>REVIEW</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const isAnnotated = (t as any).is_annotated
                return (
                  <tr key={t.trade_key} style={{
                    borderBottom:'1px solid #0A1220',
                    background: i%2===0 ? 'transparent' : '#08101E',
                    cursor:'pointer'
                  }}
                  onClick={() => setReviewTrade(t)}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background='#0D1F3A'}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = i%2===0 ? 'transparent' : '#08101E'}
                  >
                    <td style={{ padding:'9px 12px',color:'#64748B',fontSize:'12px',whiteSpace:'nowrap' }}>{t.close_date}</td>
                    <td style={{ padding:'9px 12px' }}>
                      <span style={{ fontWeight:700,color:'#60A5FA',letterSpacing:'0.05em' }}>{t.symbol}</span>
                    </td>
                    <td style={{ padding:'9px 12px' }}>
                      <span style={{ fontSize:'10px',fontWeight:700,color:typeColors[t.trade_type]||'#64748B',background:'rgba(255,255,255,0.04)',padding:'2px 6px',borderRadius:'3px' }}>
                        {t.trade_type}
                      </span>
                    </td>
                    <td style={{ padding:'9px 12px',color:'#94A3B8' }}>{t.shares.toLocaleString()}</td>
                    <td style={{ padding:'9px 12px',color:'#94A3B8' }}>${t.buy_price.toFixed(2)}</td>
                    <td style={{ padding:'9px 12px',color:'#94A3B8' }}>${t.sell_price.toFixed(2)}</td>
                    <td style={{ padding:'9px 12px',fontWeight:700,color:t.pnl>=0?'#4ADE80':'#F87171' }}>
                      {t.pnl>=0?'+':''}{t.pnl>=0||t.pnl<=-1000?fmt$(t.pnl):`-$${Math.abs(t.pnl).toFixed(0)}`}
                    </td>
                    <td style={{ padding:'9px 12px',color:t.pnl_pct>=0?'#4ADE80':'#F87171',fontSize:'12px' }}>
                      {t.pnl_pct>=0?'+':''}{t.pnl_pct.toFixed(1)}%
                    </td>
                    <td style={{ padding:'9px 12px',color:'#64748B',fontSize:'12px' }}>{t.hold_days}</td>
                    <td style={{ padding:'9px 12px',color:'#64748B',fontSize:'11px' }}>{ACCT_SHORT[t.account]||t.account}</td>
                    <td style={{ padding:'9px 12px' }}>
                      {t.setup_type ? (
                        <span style={{ fontSize:'10px',color:'#4ADE80',background:'#0D1F0D',padding:'2px 6px',borderRadius:'3px' }}>
                          {t.setup_type.replace(/_/g,' ')}
                        </span>
                      ) : t.suggested_setup ? (
                        <span style={{ fontSize:'10px',color:'#F59E0B',background:'#1A1200',padding:'2px 6px',borderRadius:'3px' }}>
                          ~{t.suggested_setup.replace(/_/g,' ')}
                        </span>
                      ) : (
                        <span style={{ fontSize:'10px',color:'#475569' }}>—</span>
                      )}
                    </td>
                    <td style={{ padding:'9px 12px' }}>
                      {isAnnotated ? (
                        <span style={{ fontSize:'11px',color:'#4ADE80' }}>✓</span>
                      ) : (
                        <span style={{ fontSize:'10px',color:'#F59E0B',background:'#1A1200',padding:'2px 6px',borderRadius:'3px',fontWeight:600 }}>
                          PENDING
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && (
          <div style={{ padding:'40px',textAlign:'center',color:'#475569',fontSize:'13px' }}>No trades match current filters</div>
        )}
      </div>
      </>)}
    </div>
  )
}

import React, { useEffect, useState } from 'react';

const css = `.uti-overlay{position:fixed;top:0;right:0;width:min(960px,55vw);height:100vh;background:#0b1020;border-left:1px solid #334155;box-shadow:-20px 0 50px rgba(0,0,0,.5);z-index:100;display:flex;flex-direction:column;overflow:hidden}.uti-head{display:flex;justify-content:space-between;padding:18px 22px;border-bottom:1px solid #263142}.uti-head h2{margin:0;font-size:20px;color:#e7edf6}.uti-head p{margin:2px 0 0;font-size:11px;color:#94a3b8}.uti-close{font-size:24px;background:none;border:none;color:#94a3b8;cursor:pointer}.uti-tabs{display:flex;gap:4px;padding:8px 22px;border-bottom:1px solid #263142;overflow-x:auto;flex-shrink:0}.uti-tabs button{font-size:10px;padding:4px 10px;border:1px solid #334155;border-radius:6px;background:#0c121d;color:#94a3b8;cursor:pointer;white-space:nowrap}.uti-tabs button.active{background:#2563eb;border-color:#60a5fa;color:#fff}.uti-body{padding:18px 22px;overflow-y:auto;flex:1;font-size:12px;color:#cbd5e1;line-height:1.7}.uti-section{margin-bottom:16px}.uti-section h3{font-size:14px;color:#e7edf6;margin:0 0 8px;border-bottom:1px solid #1f2937;padding-bottom:4px}.uti-kv{display:grid;grid-template-columns:160px 1fr;gap:4px 12px;font-size:11px}.uti-kv dt{color:#94a3b8;font-weight:600}.uti-kv dd{margin:0;color:#e7edf6}.uti-gap{background:#160f13;border:1px solid #7f1d1d;color:#fecaca;border-radius:8px;padding:8px;margin:4px 0;font-size:11px}.uti-badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #334155}.uti-ok{color:#4ade80;border-color:#166534}.uti-warn{color:#fbbf24;border-color:#92400e}.uti-danger{color:#fb7185;border-color:#7f1d1d}.uti-raw{white-space:pre-wrap;background:#020617;border:1px solid #263142;border-radius:10px;padding:12px;font-size:10px;max-height:400px;overflow:auto}`;

const TABS = ['Overview','Source','Proposal','Execution','Stops','Journal','Learning','LLM Review','Data Quality','Raw'] as const;
type Tab = typeof TABS[number];

interface Props {
  symbol?: string; paperTradeId?: number; traceId?: string; proposalId?: string;
  strategyId?: string; account?: string; onClose?: () => void;
}

export default function UnifiedTradeInspector(props: Props) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('Overview');

  useEffect(() => {
    const params = new URLSearchParams();
    if (props.paperTradeId) params.set('paper_trade_id', String(props.paperTradeId));
    else if (props.symbol) params.set('symbol', props.symbol);
    else if (props.traceId) params.set('trace_id', props.traceId);
    else if (props.proposalId) params.set('proposal_id', props.proposalId);
    if (props.strategyId) params.set('strategy_id', props.strategyId);
    if (props.account) params.set('account', props.account);

    fetch(`/api/v2/lifecycle/trade-inspector?${params}`, { cache: 'no-store' })
      .then(r => r.json())
      .then(raw => setData(raw?.data || raw))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [props.symbol, props.paperTradeId, props.traceId, props.proposalId]);

  if (!data && !loading) return null;

  const d = data || {};
  const o = d.overview || {};
  const id = d.resolved_identity || {};

  const KV = ({ items }: { items: [string, any][] }) => (
    <dl className="uti-kv">{items.map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{v === null || v === undefined ? <span style={{color:'#64748b'}}>—</span> : String(v)}</dd></React.Fragment>)}</dl>
  );

  return (
    <div className="uti-overlay"><style>{css}</style>
      <div className="uti-head">
        <div>
          <h2>{o.symbol || id.symbol || 'Trade Inspector'} {o.paper_trade_id ? `#${o.paper_trade_id}` : ''}</h2>
          <p>Resolved via {id.resolution_method || '?'} · {o.status || 'unknown'} · {o.strategy_family || ''} {o.is_ghost ? '(GHOST/DUPLICATE)' : ''}</p>
        </div>
        <button className="uti-close" onClick={props.onClose}>×</button>
      </div>

      <div className="uti-tabs">
        {TABS.map(t => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}
      </div>

      <div className="uti-body">
        {loading && <p>Loading inspector...</p>}

        {tab === 'Overview' && <div className="uti-section">
          <h3>Trade Overview</h3>
          <KV items={[
            ['Symbol', o.symbol], ['Strategy', o.strategy_id], ['Family', o.strategy_family],
            ['Account', o.account], ['Entry', o.entry_price ? `$${o.entry_price.toFixed(2)}` : null],
            ['Exit', o.exit_price ? `$${o.exit_price.toFixed(2)}` : null],
            ['P&L', o.pnl != null ? `$${o.pnl.toFixed(2)}` : null],
            ['Stop', o.stop_loss ? `$${o.stop_loss.toFixed(2)}` : null],
            ['Exit Reason', o.exit_reason || null], ['Status', o.status],
            ['Ghost/Duplicate', o.is_ghost ? 'YES' : 'No'],
          ]} />
        </div>}

        {tab === 'Source' && <div className="uti-section">
          <h3>Signal Source</h3>
          {(d.source?.signals || []).length === 0 ? <p style={{color:'#94a3b8'}}>No signals found for this symbol.</p> :
            (d.source.signals || []).map((s: any, i: number) => (
              <div key={i} style={{marginBottom:8,padding:8,background:'#0c121d',borderRadius:8,border:'1px solid #263142'}}>
                <KV items={[['Signal ID', s.id], ['Score', s.signal_score], ['Grade', s.signal_grade], ['Fired', s.fired_at]]} />
              </div>
            ))}
        </div>}

        {tab === 'Proposal' && <div className="uti-section">
          <h3>Proposals</h3>
          {(d.proposal?.proposals || []).length === 0 ? <p style={{color:'#94a3b8'}}>No proposals found.</p> :
            (d.proposal.proposals || []).map((p: any, i: number) => (
              <div key={i} style={{marginBottom:8,padding:8,background:'#0c121d',borderRadius:8,border:'1px solid #263142'}}>
                <KV items={[['ID', p.id], ['Strategy', p.strategy_id], ['Score', p.signal_score], ['Decision', p.signal_decision], ['Created', p.created_at]]} />
              </div>
            ))}
        </div>}

        {tab === 'Execution' && <div className="uti-section">
          <h3>Execution / TCA</h3>
          {d.execution?.tca ? <KV items={Object.entries(d.execution.tca).slice(0, 15)} /> : <p style={{color:'#94a3b8'}}>No TCA data available.</p>}
        </div>}

        {tab === 'Stops' && <div className="uti-section">
          <h3>Stop Management</h3>
          <KV items={[
            ['DB Stop', d.stops?.db_stop ? `$${d.stops.db_stop.toFixed(2)}` : null],
            ['Stop Order ID', d.stops?.stop_order_id || null],
            ['Verified At', d.stops?.stop_verified_at || null],
          ]} />
          <h3 style={{marginTop:12}}>Stop Change Audit</h3>
          {(d.stops?.change_audit || []).length === 0 ? <p style={{color:'#94a3b8'}}>No stop changes recorded.</p> :
            (d.stops.change_audit || []).map((e: any, i: number) => {
              const p = typeof e.payload === 'string' ? JSON.parse(e.payload || '{}') : (e.payload || {});
              return <div key={i} className="uti-gap" style={{borderColor:'#92400e',background:'#1a1207'}}>
                {e.event_type}: ${p.old_stop} → ${p.new_stop} ({p.reason || 'no reason'})
              </div>;
            })}
        </div>}

        {tab === 'Journal' && <div className="uti-section">
          <h3>Journal</h3>
          <KV items={[['Status', d.journal?.status], ['Exit Reason', d.journal?.exit_reason], ['P&L', d.journal?.pnl != null ? `$${d.journal.pnl}` : null]]} />
        </div>}

        {tab === 'Learning' && <div className="uti-section">
          <h3>Learning</h3>
          <KV items={[['Strategy Family', d.learning?.strategy_family]]} />
          <p style={{color:'#94a3b8'}}>Strategy-level learning rollup available in Journal/Learning workspace.</p>
        </div>}

        {tab === 'LLM Review' && <div className="uti-section">
          <h3>LLM Review</h3>
          <span className={`uti-badge ${d.llm_review?.status === 'complete' ? 'uti-ok' : 'uti-warn'}`}>{d.llm_review?.status || 'not_configured'}</span>
          <p style={{marginTop:8,color:'#94a3b8'}}>{d.llm_review?.status === 'not_configured' ? 'LLM backtesting jobs are not yet deployed (v3.8 design only). No model calls are made by this inspector.' : 'LLM review data available.'}</p>
          {(d.llm_review?.data_quality_gaps || []).map((g: string, i: number) => <div key={i} className="uti-gap">{g}</div>)}
          <p style={{fontSize:10,color:'#64748b',marginTop:8}}>Blocked: Run model, Modify journal, Change strategy automatically, Place trade</p>
        </div>}

        {tab === 'Data Quality' && <div className="uti-section">
          <h3>Data Quality Gaps</h3>
          {(d.data_quality_gaps || []).length === 0 ? <p style={{color:'#4ade80'}}>No data quality gaps detected.</p> :
            (d.data_quality_gaps || []).map((g: any, i: number) => <div key={i} className="uti-gap">{g.gap}: {g.detail}</div>)}
          <h3 style={{marginTop:12}}>Identity Resolution</h3>
          <KV items={Object.entries(d.resolved_identity || {})} />
        </div>}

        {tab === 'Raw' && <div className="uti-section">
          <h3>Raw Data</h3>
          <pre className="uti-raw">{JSON.stringify(d, null, 2)}</pre>
        </div>}
      </div>
    </div>
  );
}

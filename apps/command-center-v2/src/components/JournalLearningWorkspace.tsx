import React, { useEffect, useState } from 'react';

const css = `.jlw{border:1px solid #263142;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.jlw h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.jlw h3{margin:12px 0 6px;font-size:14px;color:#cbd5e1}.jlw p{color:#94a3b8;font-size:12px;margin:0 0 12px}.jlw-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px}.jlw-card{background:#0c121d;border:1px solid #263142;border-radius:10px;padding:10px;text-align:center}.jlw-card strong{display:block;font-size:18px;font-weight:800;color:#e7edf6}.jlw-card span{font-size:10px;color:#94a3b8}.jlw-card.ok strong{color:#4ade80}.jlw-card.warn strong{color:#fbbf24}.jlw-card.danger strong{color:#fb7185}.jlw table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.jlw th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.jlw td{border-bottom:1px solid #1f2937;padding:5px}.jlw .badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #334155}.jlw .gap{background:#160f13;border:1px solid #7f1d1d;color:#fecaca;border-radius:8px;padding:8px;margin:4px 0;font-size:11px}`;

export default function JournalLearningWorkspace({ compact }: { compact?: boolean }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/v2/lifecycle/journal-learning-summary', { cache: 'no-store' })
      .then(r => r.json())
      .then(raw => setData(raw?.data || raw))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="jlw"><style>{css}</style><p>Loading journal/learning data...</p></div>;
  if (!data) return null;

  const d = data;
  return (
    <div className="jlw">
      <style>{css}</style>
      <h2>Journal / Learning / Backtesting</h2>
      <p>Lifecycle outcome summary. {d.clean_closed_count} clean closed trades, {d.ghost_count} ghost/duplicate excluded. Read-only.</p>

      <div className="jlw-grid">
        <div className="jlw-card ok"><strong>{d.open_trade_count ?? 0}</strong><span>Open</span></div>
        <div className="jlw-card"><strong>{d.clean_closed_count ?? 0}</strong><span>Clean Closed</span></div>
        <div className={`jlw-card ${(d.ghost_count || 0) > 0 ? 'warn' : 'ok'}`}><strong>{d.ghost_count ?? 0}</strong><span>Ghost/Dup</span></div>
        <div className="jlw-card"><strong>{d.traced_closed_trade_count ?? 0}</strong><span>Traced</span></div>
        <div className={`jlw-card ${(d.missed_proposal_count || 0) > 0 ? 'warn' : 'ok'}`}><strong>{d.missed_proposal_count ?? 0}</strong><span>Missed Props</span></div>
      </div>

      <div className="jlw-grid">
        <div className="jlw-card"><strong>{d.execution_quality_count ?? 0}</strong><span>TCA Rows</span></div>
        <div className="jlw-card"><strong>{d.stop_audit_event_count ?? 0}</strong><span>Stop Audit</span></div>
        <div className="jlw-card"><strong>{d.lifecycle_trace_count ?? 0}</strong><span>Traces</span></div>
        <div className="jlw-card"><strong>{d.duplicate_groups ?? 0}</strong><span>Dedup Groups</span></div>
        <div className={`jlw-card ${d.duplicate_contamination_status === 'clean' ? 'ok' : 'danger'}`}>
          <strong>{d.duplicate_contamination_status === 'clean' ? 'Clean' : 'Risk'}</strong><span>Contamination</span>
        </div>
      </div>

      {!compact && (d.strategy_summary || []).length > 0 && (
        <>
          <h3>Strategy Performance</h3>
          <table>
            <thead><tr><th>Strategy</th><th>Family</th><th>Closed</th><th>Win Rate</th><th>Total P&L</th></tr></thead>
            <tbody>
              {(d.strategy_summary || []).map((s: any) => (
                <tr key={s.strategy_id}>
                  <td style={{ fontWeight: 700 }}>{s.strategy_id}</td>
                  <td><span className="badge">{s.strategy_family}</span></td>
                  <td>{s.closed_trade_count}</td>
                  <td style={{ color: s.win_rate >= 0.5 ? '#4ade80' : '#fb7185' }}>{(s.win_rate * 100).toFixed(1)}%</td>
                  <td style={{ color: s.total_pnl >= 0 ? '#4ade80' : '#fb7185' }}>${s.total_pnl.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {(d.data_quality_gaps || []).length > 0 && (
        <>
          <h3>Data Quality Gaps</h3>
          {(d.data_quality_gaps || []).map((g: any, i: number) => (
            <div key={i} className="gap">{g.gap}: {g.count} items</div>
          ))}
        </>
      )}
    </div>
  );
}

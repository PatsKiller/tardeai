import React, { useEffect, useState } from 'react';

const css = `.ltp{border:1px solid #263142;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.ltp h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.ltp p{color:#94a3b8;font-size:12px;margin:0 0 12px}.ltp-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:12px}.ltp-card{background:#0c121d;border:1px solid #263142;border-radius:10px;padding:10px;text-align:center}.ltp-card strong{display:block;font-size:22px;font-weight:800;color:#e7edf6}.ltp-card span{font-size:10px;color:#94a3b8}.ltp-card.warn strong{color:#fbbf24}.ltp-card.danger strong{color:#fb7185}.ltp-card.ok strong{color:#4ade80}.ltp-events{max-height:200px;overflow:auto}.ltp-events table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.ltp-events th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.ltp-events td{border-bottom:1px solid #1f2937;padding:5px}`;

export default function LifecycleTracePanel() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/v2/lifecycle/trace-summary', { cache: 'no-store' })
      .then(r => r.json())
      .then(raw => setData(raw?.data || raw))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="ltp"><style>{css}</style><p>Loading trace data...</p></div>;
  if (!data) return null;

  const d = data;
  return (
    <div className="ltp">
      <style>{css}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2>Lifecycle Trace Health</h2>
          <p>Prospect → Signal → Proposal traceability. {d.total_traces} trace chains tracked.</p>
        </div>
        <span style={{ fontSize: 11, padding: '3px 8px', borderRadius: 999, border: '1px solid #166534', color: '#4ade80' }}>
          {d.total_traces} traces
        </span>
      </div>
      <div className="ltp-grid">
        <div className="ltp-card ok"><strong>{d.total_traces}</strong><span>Total Traces</span></div>
        <div className="ltp-card ok"><strong>{d.signals_linked}</strong><span>Signals Linked</span></div>
        <div className="ltp-card ok"><strong>{d.proposals_linked}</strong><span>Proposals Linked</span></div>
        <div className="ltp-card ok"><strong>{d.trades_linked}</strong><span>Trades Linked</span></div>
        <div className={`ltp-card ${d.duplicate_proposal_groups > 0 ? 'warn' : 'ok'}`}><strong>{d.duplicate_proposal_groups}</strong><span>Duplicate Groups</span></div>
        <div className={`ltp-card ${(d.missing_signal_count || 0) > 50 ? 'warn' : 'ok'}`}><strong>{d.missing_signal_count || 0}</strong><span>Missing Signal</span></div>
      </div>
      {(d.latest_events || []).length > 0 && (
        <div className="ltp-events">
          <table>
            <thead><tr><th>Time</th><th>Stage</th><th>Type</th><th>Source</th><th>Status</th></tr></thead>
            <tbody>
              {(d.latest_events || []).slice(0, 10).map((e: any, i: number) => (
                <tr key={i}>
                  <td>{e.event_time ? new Date(e.event_time).toLocaleTimeString() : '—'}</td>
                  <td>{e.stage}</td>
                  <td>{e.event_type}</td>
                  <td>{e.source_table || '—'}</td>
                  <td>{e.status || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

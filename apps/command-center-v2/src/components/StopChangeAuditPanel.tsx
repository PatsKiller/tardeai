import React, { useEffect, useState } from 'react';
const css = `.scap{border:1px solid #92400e;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.scap h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.scap p{color:#94a3b8;font-size:12px;margin:0 0 12px}.scap table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.scap th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.scap td{border-bottom:1px solid #1f2937;padding:5px}.scap .badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #334155}.scap .repair{color:#fb7185;border-color:#7f1d1d}.scap .trailing{color:#fbbf24;border-color:#92400e}.scap .initial{color:#4ade80;border-color:#166534}`;
export default function StopChangeAuditPanel() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetch('/api/v2/atm/stop-change-audit', { cache: 'no-store' }).then(r => r.json()).then(raw => setData(raw?.data || raw)).catch(() => {}); }, []);
  if (!data) return null;
  const events = data.latest_events || [];
  return (
    <div className="scap"><style>{css}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2>Stop Change Audit Trail</h2>
          <p>{data.total_events} stop-change events recorded. Every stop update is tracked with old/new values, source, and reason.</p>
        </div>
        {data.apps_repair_visible && <span className="badge repair">APPS repair visible</span>}
      </div>
      {events.length === 0 ? <p style={{ textAlign: 'center', color: '#94a3b8' }}>No stop-change events recorded yet.</p> : (
        <table><thead><tr>
          <th>Symbol</th><th>Trade #</th><th>Old Stop</th><th>New Stop</th><th>Type</th><th>Source</th><th>Reason</th><th>Approved</th><th>Time</th>
        </tr></thead><tbody>
          {events.map((e: any) => (
            <tr key={e.event_id} style={{ background: e.change_type === 'repair' ? 'rgba(251,113,133,0.04)' : undefined }}>
              <td style={{ fontWeight: 700 }}>{e.symbol}</td>
              <td>#{e.paper_trade_id}</td>
              <td>{e.old_stop != null ? `$${Number(e.old_stop).toFixed(2)}` : '—'}</td>
              <td>{e.new_stop != null ? `$${Number(e.new_stop).toFixed(2)}` : '—'}</td>
              <td><span className={`badge ${e.change_type === 'repair' ? 'repair' : e.change_type === 'trailing_update' ? 'trailing' : 'initial'}`}>{e.change_type}</span></td>
              <td style={{ fontSize: 9 }}>{e.source_script || '—'}</td>
              <td style={{ fontSize: 9, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.reason || '—'}</td>
              <td>{e.approved ? '✓' : '—'}</td>
              <td style={{ fontSize: 9 }}>{e.event_time ? new Date(e.event_time).toLocaleString() : '—'}</td>
            </tr>
          ))}
        </tbody></table>
      )}
    </div>
  );
}

import React, { useEffect, useState } from 'react';
const css = `.stcp{border:1px solid #263142;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.stcp h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.stcp p{color:#94a3b8;font-size:12px;margin:0 0 12px}.stcp table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.stcp th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.stcp td{border-bottom:1px solid #1f2937;padding:5px}.stcp .badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #334155}.stcp .ok{color:#4ade80;border-color:#166534}.stcp .warn{color:#fbbf24;border-color:#92400e}.stcp .danger{color:#fb7185;border-color:#7f1d1d}`;
export default function StopTrailingControlPanel() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetch('/api/v2/atm/stop-trailing-control', { cache: 'no-store' }).then(r => r.json()).then(raw => setData(raw?.data || raw)).catch(() => {}); }, []);
  if (!data || !(data.records || []).length) return null;
  return (
    <div className="stcp"><style>{css}</style>
      <h2>Stop / Trailing / Time-Stop Control</h2>
      <p>{data.total_open_trades} open trades. Shows trailing policy, stop proof, and time-stop status. Read-only — no stop changes.</p>
      <table><thead><tr>
        <th>Symbol</th><th>Strategy</th><th>Family</th><th>Entry</th><th>DB Stop</th><th>Stop Proof</th>
        <th>Trailing Tiers</th><th>Days</th><th>Time-Stop</th><th>Last Change</th>
      </tr></thead><tbody>
        {(data.records || []).map((r: any) => (
          <tr key={r.paper_trade_id}>
            <td style={{ fontWeight: 700 }}>{r.symbol}</td>
            <td style={{ fontSize: 9 }}>{r.strategy_id}</td>
            <td><span className={`badge ${r.strategy_family === 'momentum' ? 'warn' : r.strategy_family === 'income' ? 'ok' : ''}`}>{r.strategy_family}</span></td>
            <td>{r.entry_price ? `$${r.entry_price.toFixed(2)}` : '—'}</td>
            <td>{r.db_stop ? `$${r.db_stop.toFixed(2)}` : '—'}</td>
            <td><span className={`badge ${r.stop_proof_status === 'verified' ? 'ok' : r.stop_proof_status === 'unverified' ? 'warn' : 'danger'}`}>{r.stop_proof_status}</span></td>
            <td style={{ fontSize: 9 }}>{(r.trailing_tiers || []).map((t: any) => `${t.desc}@R=${t.r}`).join(', ') || '—'}</td>
            <td>{r.days_held}d</td>
            <td><span className={`badge ${r.time_stop_status === 'overdue' ? 'danger' : r.time_stop_status === 'review_due' ? 'warn' : 'ok'}`}>{r.time_stop_status}{r.overdue_by_days > 0 ? ` +${r.overdue_by_days}d` : ''}</span></td>
            <td style={{ fontSize: 9, color: '#94a3b8' }}>{r.latest_stop_change ? `${r.latest_stop_change.type} ${r.latest_stop_change.time ? new Date(r.latest_stop_change.time).toLocaleDateString() : ''}` : 'none'}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  );
}

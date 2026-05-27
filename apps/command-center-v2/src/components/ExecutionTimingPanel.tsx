import React, { useEffect, useState } from 'react';
const css = `.etp{border:1px solid #263142;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.etp h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.etp p{color:#94a3b8;font-size:12px;margin:0 0 12px}.etp-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}.etp-card{background:#0c121d;border:1px solid #263142;border-radius:10px;padding:10px;text-align:center}.etp-card strong{display:block;font-size:20px;font-weight:800;color:#e7edf6}.etp-card span{font-size:10px;color:#94a3b8}.etp-card.warn strong{color:#fbbf24}.etp-card.ok strong{color:#4ade80}.etp table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.etp th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.etp td{border-bottom:1px solid #1f2937;padding:5px}`;
export default function ExecutionTimingPanel({ compact }: { compact?: boolean }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetch('/api/v2/atm/execution-timing-health', { cache: 'no-store' }).then(r => r.json()).then(raw => setData(raw?.data || raw)).catch(() => {}); }, []);
  if (!data) return null;
  const d = data;
  return (
    <div className="etp"><style>{css}</style>
      <h2>Execution Timing Health</h2>
      <p>{d.total_recent_trades} recent trades. Timing fields populate on future order lifecycle events.</p>
      <div className="etp-grid">
        <div className="etp-card"><strong>{d.total_recent_trades ?? 0}</strong><span>Recent Trades</span></div>
        <div className={`etp-card ${(d.missing_order_submitted_count || 0) > 0 ? 'warn' : 'ok'}`}><strong>{d.order_submitted_populated ?? 0}</strong><span>Submitted At</span></div>
        <div className={`etp-card ${(d.missing_order_filled_count || 0) > 0 ? 'warn' : 'ok'}`}><strong>{d.order_filled_populated ?? 0}</strong><span>Filled At</span></div>
        <div className={`etp-card ${(d.missing_order_submitted_count || 0) === d.total_recent_trades ? 'warn' : 'ok'}`}><strong>{d.missing_order_submitted_count ?? 0}</strong><span>Missing Timing</span></div>
      </div>
      {!compact && (d.records || []).slice(0, 10).length > 0 && (
        <table><thead><tr><th>Symbol</th><th>Account</th><th>Submitted</th><th>Filled</th><th>TTF (s)</th><th>Fill Price</th><th>Missing</th></tr></thead>
        <tbody>{(d.records || []).slice(0, 10).map((r: any) => (
          <tr key={r.paper_trade_id}>
            <td style={{ fontWeight: 700 }}>{r.symbol}</td><td>{r.account}</td>
            <td style={{ fontSize: 9 }}>{r.order_submitted_at || <span style={{ color: '#fbbf24' }}>null</span>}</td>
            <td style={{ fontSize: 9 }}>{r.order_filled_at || <span style={{ color: '#fbbf24' }}>null</span>}</td>
            <td>{r.time_to_fill_seconds ?? '—'}</td>
            <td>{r.fill_price ? `$${r.fill_price.toFixed(2)}` : '—'}</td>
            <td style={{ fontSize: 9, color: '#fbbf24' }}>{(r.missing_fields || []).join(', ') || '—'}</td>
          </tr>
        ))}</tbody></table>
      )}
    </div>
  );
}

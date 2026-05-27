import React, { useEffect, useState } from 'react';
const css = `.spp{border:1px solid #263142;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.spp h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.spp p{color:#94a3b8;font-size:12px;margin:0 0 12px}.spp-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}.spp-card{background:#0c121d;border:1px solid #263142;border-radius:10px;padding:10px;text-align:center}.spp-card strong{display:block;font-size:20px;font-weight:800;color:#e7edf6}.spp-card span{font-size:10px;color:#94a3b8}.spp-card.ok strong{color:#4ade80}.spp-card.warn strong{color:#fbbf24}.spp-card.danger strong{color:#fb7185}.spp table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.spp th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.spp td{border-bottom:1px solid #1f2937;padding:5px}.spp .badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #334155}`;
export default function StopProofPanel({ compact }: { compact?: boolean }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetch('/api/v2/atm/stop-proof', { cache: 'no-store' }).then(r => r.json()).then(raw => setData(raw?.data || raw)).catch(() => {}); }, []);
  if (!data) return null;
  const d = data;
  return (
    <div className="spp"><style>{css}</style>
      <h2>Broker Stop Proof</h2>
      <p>{d.total_open_trades} open trades. Stop order IDs stored for future orders; broker verification via reconciliation cron.</p>
      <div className="spp-grid">
        <div className={`spp-card ${d.verified_count > 0 ? 'ok' : ''}`}><strong>{d.verified_count ?? 0}</strong><span>Verified</span></div>
        <div className={`spp-card ${(d.missing_stop_order_id_count || 0) > 0 ? 'warn' : 'ok'}`}><strong>{d.missing_stop_order_id_count ?? 0}</strong><span>Missing Order ID</span></div>
        <div className={`spp-card ${(d.no_stop_configured_count || 0) > 0 ? 'danger' : 'ok'}`}><strong>{d.no_stop_configured_count ?? 0}</strong><span>No Stop</span></div>
        <div className="spp-card"><strong>{d.total_open_trades ?? 0}</strong><span>Total Open</span></div>
      </div>
      {!compact && (d.records || []).length > 0 && (
        <table><thead><tr><th>Symbol</th><th>Account</th><th>DB Stop</th><th>Order ID</th><th>Verified</th><th>Status</th></tr></thead>
        <tbody>{(d.records || []).map((r: any) => (
          <tr key={r.paper_trade_id}>
            <td style={{ fontWeight: 700 }}>{r.symbol}</td><td>{r.account}</td>
            <td>{r.db_stop ? `$${r.db_stop.toFixed(2)}` : '—'}</td>
            <td style={{ fontSize: 9 }}>{r.stop_order_id || <span style={{ color: '#fbbf24' }}>not stored</span>}</td>
            <td style={{ fontSize: 9 }}>{r.stop_verified_at || '—'}</td>
            <td><span className="badge" style={{ color: r.verification_status === 'stop_verified' ? '#4ade80' : r.verification_status === 'stop_order_id_missing' ? '#fbbf24' : '#fb7185', borderColor: r.verification_status === 'stop_verified' ? '#166534' : '#92400e' }}>{r.verification_status}</span></td>
          </tr>
        ))}</tbody></table>
      )}
    </div>
  );
}

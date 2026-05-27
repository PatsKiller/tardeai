import React, { useEffect, useState } from 'react';

const css = `.pdp{border:1px solid #92400e;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.pdp h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.pdp p{color:#94a3b8;font-size:12px;margin:0 0 12px}.pdp table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.pdp th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:6px}.pdp td{border-bottom:1px solid #1f2937;padding:6px}.pdp .badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #92400e;color:#fbbf24}`;

export default function ProposalDedupPanel() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/v2/atm/proposal-dedup', { cache: 'no-store' })
      .then(r => r.json())
      .then(raw => setData(raw?.data || raw))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="pdp"><style>{css}</style><p>Loading dedup data...</p></div>;
  if (!data || !(data.groups || []).length) return null;

  return (
    <div className="pdp">
      <style>{css}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2>Proposal Duplicate Audit</h2>
          <p>{data.total_groups} duplicate groups found ({data.total_duplicate_proposals} total proposals). Read-only audit — no proposals are modified.</p>
        </div>
        <span className="badge">{data.total_groups} groups</span>
      </div>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Strategy</th><th>Count</th><th>Canonical</th><th>Duplicates</th><th>Action</th></tr>
        </thead>
        <tbody>
          {(data.groups || []).map((g: any, i: number) => (
            <tr key={i}>
              <td style={{ fontWeight: 700 }}>{g.symbol}</td>
              <td>{g.strategy_id}</td>
              <td>{g.duplicate_count}</td>
              <td>#{g.canonical_proposal_id}</td>
              <td style={{ fontSize: 9, color: '#94a3b8' }}>{JSON.stringify(g.duplicate_proposal_ids)}</td>
              <td style={{ fontSize: 9 }}>{g.recommended_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import React, { useEffect, useState } from 'react';
const css = `.llmrp{border:1px solid #263142;border-radius:14px;background:#0b1019;padding:16px;margin:14px 0}.llmrp h2{margin:0 0 6px;font-size:16px;color:#e7edf6}.llmrp p{color:#94a3b8;font-size:12px;margin:0 0 12px}.llmrp-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}.llmrp-card{background:#0c121d;border:1px solid #263142;border-radius:10px;padding:10px;text-align:center}.llmrp-card strong{display:block;font-size:18px;font-weight:800;color:#e7edf6}.llmrp-card span{font-size:10px;color:#94a3b8}.llmrp-card.ok strong{color:#4ade80}.llmrp-card.warn strong{color:#fbbf24}.llmrp table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.llmrp th{text-align:left;color:#94a3b8;border-bottom:1px solid #263142;padding:5px}.llmrp td{border-bottom:1px solid #1f2937;padding:5px}.llmrp .badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;border:1px solid #334155}`;
export default function LLMBacktestingReviewPanel({ compact }: { compact?: boolean }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { fetch('/api/v2/lifecycle/llm-review-status', { cache: 'no-store' }).then(r => r.json()).then(raw => setData(raw?.data || raw)).catch(() => {}); }, []);
  if (!data) return null;
  const d = data;
  return (
    <div className="llmrp"><style>{css}</style>
      <h2>LLM Backtesting Review</h2>
      <p>Three-stage LLM trade review: close analysis (local), delayed review (local), monthly meta (Grok). Read-only status — no model calls from this panel.</p>
      <div className="llmrp-grid">
        <div className="llmrp-card"><strong>{d.total_reviews ?? 0}</strong><span>Total Reviews</span></div>
        <div className="llmrp-card"><strong>{d.close_analysis_count ?? 0}</strong><span>Close Analysis</span></div>
        <div className="llmrp-card"><strong>{d.delayed_review_count ?? 0}</strong><span>Delayed Review</span></div>
        <div className="llmrp-card"><strong>{d.monthly_meta_count ?? 0}</strong><span>Monthly Meta</span></div>
        <div className={`llmrp-card ${(d.pending_count || 0) > 0 ? 'warn' : 'ok'}`}><strong>{d.pending_count ?? 0}</strong><span>Pending</span></div>
      </div>
      {!compact && (d.latest_reviews || []).length > 0 && (
        <table><thead><tr><th>Symbol</th><th>Stage</th><th>Status</th><th>Model</th><th>Generated</th></tr></thead>
        <tbody>{(d.latest_reviews || []).map((r: any, i: number) => (
          <tr key={i}><td style={{fontWeight:700}}>{r.symbol}</td><td>{r.review_stage}</td>
          <td><span className="badge">{r.status}</span></td><td style={{fontSize:9}}>{r.model_name}</td>
          <td style={{fontSize:9}}>{r.generated_at ? new Date(r.generated_at).toLocaleString() : '—'}</td></tr>
        ))}</tbody></table>
      )}
      {(d.latest_reviews || []).length === 0 && <p style={{textAlign:'center',color:'#64748b'}}>No LLM reviews generated yet. Run trade_close_llm_analyzer.py --dry-run to begin.</p>}
      <p style={{fontSize:9,color:'#64748b',marginTop:8}}>Blocked: Run model from UI, Modify journal, Change strategy, Place trade, Call Grok from UI</p>
    </div>
  );
}

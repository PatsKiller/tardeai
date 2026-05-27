// ProposalHygienePanel.tsx v2.2
// Designed by ChatGPT Chief Architect.
// Install target: apps/command-center-v2/src/components/ProposalHygienePanel.tsx


import React, { useEffect, useMemo, useState } from 'react';


type ProposalRecord = Record<string, any>;
type Payload = {
  ok?: boolean;
  status?: string;
  generated_at?: string;
  total_count?: number;
  recent_count?: number;
  stale_count?: number;
  needs_review_count?: number;
  linked_open_trade_count?: number;
  duplicate_count?: number;
  blocked_count?: number;
  expired_count?: number;
  records?: ProposalRecord[];
  groups?: Record<string, ProposalRecord[]>;
  safety?: Record<string, any>;
  sources?: Record<string, any>;
  error?: string;
};


type Props = {
  fallbackRecords?: ProposalRecord[];
  onOpenProposal?: (proposal: ProposalRecord, all: ProposalRecord[]) => void;
  compact?: boolean;
};


const ENDPOINT = '/api/v2/atm/proposal-hygiene';


const CLASS_ORDER = [
  'all',
  'linked_to_open_trade',
  'recent_pipeline_window',
  'stale_needs_review',
  'blocked_by_risk',
  'duplicate_candidate',
  'expired',
  'rejected',
  'missing_metadata',
  'unknown',
];


function fmt(v: any, fallback = '—') {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}


function ageLabel(hours: any) {
  const h = Number(hours);
  if (!Number.isFinite(h)) return 'Missing age';
  if (h < 1) return '<1h';
  if (h < 48) return `${Math.round(h)}h`;
  return `${Math.round(h / 24)}d`;
}


function toneFor(value: any) {
  const s = String(value || '').toLowerCase();
  if (s.includes('linked') || s.includes('recent') || s.includes('open')) return 'healthy';
  if (s.includes('stale') || s.includes('missing') || s.includes('duplicate') || s.includes('unknown')) return 'warning';
  if (s.includes('blocked') || s.includes('expired') || s.includes('rejected') || s.includes('fail')) return 'danger';
  return 'neutral';
}


function displayClass(c: any) {
  return fmt(c, 'unknown').replace(/_/g, ' ');
}


function normalizeFallback(rows: ProposalRecord[] = []): ProposalRecord[] {
  const now = Date.now();
  const seen = new Map<string, number>();
  rows.forEach((r) => {
    const k = `${r.symbol || r.ticker || ''}|${r.strategy_id || r.strategy || ''}`.toUpperCase();
    seen.set(k, (seen.get(k) || 0) + 1);
  });
  return rows.map((r, index) => {
    const symbol = r.symbol || r.ticker || 'Missing symbol';
    const strategy = r.strategy_id || r.strategy || r.strategy_name || 'Missing strategy';
    const created = r.created_at || r.createdAt || r.timestamp || r.generated_at;
    const createdMs = created ? Date.parse(created) : NaN;
    const ageHours = Number.isFinite(createdMs) ? (now - createdMs) / 36e5 : null;
    const duplicate = (seen.get(`${symbol}|${strategy}`.toUpperCase()) || 0) > 1;
    let classification = r.classification || r.hygiene_classification || 'unknown';
    let reason = r.reason || r.hygiene_reason || '';
    if (!r.proposal_id && !r.id) { classification = 'missing_metadata'; reason = reason || 'Proposal id is missing from source payload.'; }
    else if (duplicate) { classification = 'duplicate_candidate'; reason = reason || 'Same symbol and strategy appears multiple times.'; }
    else if (ageHours !== null && ageHours <= 168) { classification = 'recent_pipeline_window'; reason = reason || 'Proposal is within the normal recent pipeline window.'; }
    return {
      ...r,
      proposal_id: r.proposal_id || r.id || `missing-${index + 1}`,
      symbol,
      strategy_id: strategy,
      status: r.status || r.decision_state || 'Missing status',
      age_hours: ageHours,
      classification,
      reason: reason || 'No source reason provided.',
      linked_open_trade: Boolean(r.linked_open_trade || r.linked_paper_trade_id),
      gate_status: r.gate_status || r.gate_result || 'Gate data unavailable',
      available_safe_actions: r.available_safe_actions || ['Review source record'],
      blocked_actions: r.blocked_actions || ['Expire proposal without operator-approved workflow'],
      raw: r,
    };
  });
}


function CountCard({ label, value, tone = 'neutral' }: { label: string; value: any; tone?: string }) {
  return <div className={`ph-count ph-${tone}`}><strong>{fmt(value, '0')}</strong><span>{label}</span></div>;
}


export default function ProposalHygienePanel({ fallbackRecords = [], onOpenProposal, compact = false }: Props) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all');


  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(ENDPOINT, { cache: 'no-store' });
      if (!res.ok) throw new Error(`${ENDPOINT} returned ${res.status}`);
      const raw = await res.json(); setPayload(raw?.data || raw);
    } catch (err: any) {
      setError(err?.message || String(err));
      const records = normalizeFallback(fallbackRecords);
      setPayload({
        ok: false,
        status: 'fallback',
        total_count: records.length,
        recent_count: records.filter((r) => r.classification === 'recent_pipeline_window').length,
        stale_count: records.filter((r) => String(r.classification).includes('stale')).length,
        needs_review_count: records.filter((r) => ['stale_needs_review', 'missing_metadata', 'duplicate_candidate', 'unknown'].includes(r.classification)).length,
        linked_open_trade_count: records.filter((r) => r.linked_open_trade).length,
        duplicate_count: records.filter((r) => r.classification === 'duplicate_candidate').length,
        blocked_count: records.filter((r) => r.classification === 'blocked_by_risk').length,
        expired_count: records.filter((r) => r.classification === 'expired').length,
        records,
        error: err?.message || String(err),
      });
    } finally {
      setLoading(false);
    }
  }


  useEffect(() => { refresh(); }, []);


  const records = payload?.records || [];
  const filtered = useMemo(() => filter === 'all' ? records : records.filter((r) => r.classification === filter), [records, filter]);
  const counts = useMemo(() => {
    const out: Record<string, number> = { all: records.length };
    records.forEach((r) => { out[r.classification || 'unknown'] = (out[r.classification || 'unknown'] || 0) + 1; });
    return out;
  }, [records]);


  return <section className={`proposal-hygiene ${compact ? 'compact' : ''}`}>
    <style>{css}</style>
    <div className="ph-head">
      <div>
        <div className="ph-eyebrow">ATM proposal hygiene</div>
        <h2>Proposal Visibility & Hygiene</h2>
        <p>Shows proposal identity, age, classification, linked trade state, gate status, reason, and safe operator action.</p>
      </div>
      <div className="ph-actions"><span className={`ph-status ph-${payload?.ok === false ? 'warning' : 'healthy'}`}>{payload?.status || 'loading'}</span><button onClick={refresh}>{loading ? 'Refreshing…' : 'Refresh'}</button></div>
    </div>


    <div className="ph-counts">
      <CountCard label="Total" value={payload?.total_count ?? records.length} />
      <CountCard label="Recent" value={payload?.recent_count ?? 0} tone="healthy" />
      <CountCard label="Stale" value={payload?.stale_count ?? 0} tone="warning" />
      <CountCard label="Needs Review" value={payload?.needs_review_count ?? 0} tone="warning" />
      <CountCard label="Linked Open" value={payload?.linked_open_trade_count ?? 0} tone="healthy" />
      <CountCard label="Blocked" value={payload?.blocked_count ?? 0} tone="danger" />
      <CountCard label="Duplicates" value={payload?.duplicate_count ?? 0} tone="warning" />
      <CountCard label="Expired" value={payload?.expired_count ?? 0} />
    </div>


    {error && <div className="ph-warning">Endpoint unavailable; showing fallback-normalized proposal rows. {error}</div>}


    <div className="ph-filters">
      {CLASS_ORDER.filter((c) => c === 'all' || counts[c]).map((c) => <button key={c} className={filter === c ? 'active' : ''} onClick={() => setFilter(c)}>{displayClass(c)} ({counts[c] || 0})</button>)}
    </div>


    <div className="ph-table-wrap"><table className="ph-table"><thead><tr><th>Proposal</th><th>Symbol</th><th>Strategy</th><th>Status</th><th>Age</th><th>Classification</th><th>Reason</th><th>Linked Trade</th><th>Gates</th><th>Safe Action</th></tr></thead><tbody>
      {filtered.length === 0 && <tr><td colSpan={10} className="empty">No proposal records in this filter.</td></tr>}
      {filtered.map((r, i) => <tr key={`${r.proposal_id || i}-${r.symbol}-${r.strategy_id}`} onClick={() => onOpenProposal?.(r, records)} className={onOpenProposal ? 'clickable' : ''}>
        <td>{fmt(r.proposal_id, 'Missing ID')}</td>
        <td><b>{fmt(r.symbol, 'Missing symbol')}</b></td>
        <td>{fmt(r.strategy_id, 'Missing strategy')}</td>
        <td>{fmt(r.status, 'Missing status')}</td>
        <td>{ageLabel(r.age_hours)}</td>
        <td><span className={`ph-pill ph-${toneFor(r.classification)}`}>{displayClass(r.classification)}</span></td>
        <td>{fmt(r.reason, 'No source reason provided')}</td>
        <td>{r.linked_open_trade ? `Yes #${fmt(r.linked_paper_trade_id, '')}` : 'No linked trade'}</td>
        <td>{fmt(r.gate_status || r.gate_summary, 'Gate data unavailable')}</td>
        <td>{Array.isArray(r.available_safe_actions) ? r.available_safe_actions[0] : fmt(r.operator_action, 'Review')}</td>
      </tr>)}
    </tbody></table></div>


    <div className="ph-foot">Read-only visibility. v2.2 does not expire proposals, place orders, update proposal state, or change ATM mode.</div>
  </section>;
}


const css = `
.proposal-hygiene{border:1px solid #263244;border-radius:18px;background:#0b1019;color:#e8eef8;padding:18px;margin:18px 0;font-family:Inter,system-ui}.ph-head{display:flex;justify-content:space-between;gap:16px}.ph-head h2{margin:4px 0;font-size:22px}.ph-head p{color:#9fb0c4;margin:0}.ph-eyebrow{text-transform:uppercase;letter-spacing:.08em;color:#60a5fa;font-size:12px}.ph-actions{display:flex;gap:8px;align-items:flex-start}.ph-actions button,.ph-filters button{background:#162033;color:#dbeafe;border:1px solid #334155;border-radius:8px;padding:8px 12px;cursor:pointer}.ph-status{border:1px solid #334155;border-radius:999px;padding:6px 10px;font-size:12px;text-transform:uppercase}.ph-counts{display:grid;grid-template-columns:repeat(8,minmax(90px,1fr));gap:10px;margin:16px 0}.ph-count{background:#0d1320;border:1px solid #263244;border-radius:14px;padding:12px}.ph-count strong{display:block;font-size:24px}.ph-count span{color:#9fb0c4;font-size:12px}.ph-healthy strong,.ph-pill.ph-healthy{color:#4ade80}.ph-warning strong,.ph-pill.ph-warning{color:#fbbf24}.ph-danger strong,.ph-pill.ph-danger{color:#fb7185}.ph-warning{margin:12px 0;padding:10px;border:1px solid #92400e;background:#1f1608;border-radius:12px;color:#fde68a}.ph-filters{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.ph-filters button.active{background:#2563eb;border-color:#60a5fa}.ph-table-wrap{overflow:auto}.ph-table{width:100%;border-collapse:collapse;font-size:13px}.ph-table th{text-align:left;color:#9fb0c4;border-bottom:1px solid #263244;padding:9px}.ph-table td{border-bottom:1px solid #1f2937;padding:9px;vertical-align:top}.ph-pill{border:1px solid #334155;border-radius:999px;padding:3px 8px;font-size:11px;text-transform:uppercase;white-space:nowrap}.clickable:hover{background:#101a2b;cursor:pointer}.empty{text-align:center;color:#94a3b8}.ph-foot{margin-top:12px;color:#64748b;font-size:12px}@media(max-width:1200px){.ph-head{display:block}.ph-actions{margin-top:10px}.ph-counts{grid-template-columns:repeat(2,1fr)}}`;
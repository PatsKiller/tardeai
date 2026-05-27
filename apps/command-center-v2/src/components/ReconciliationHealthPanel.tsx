// ReconciliationHealthPanel.tsx.V2_1
// Designed by ChatGPT Chief Architect.
// Install target: apps/command-center-v2/src/components/ReconciliationHealthPanel.tsx


import React, { useEffect, useState } from 'react';


type HealthStatus = 'healthy' | 'warning' | 'stale' | 'mismatch' | 'error' | 'no_data' | 'unknown';


type ReconciliationItem = {
  paper_trade_id?: number | string | null;
  lifecycle_id?: string | null;
  symbol?: string | null;
  strategy_id?: string | null;
  account?: string | null;
  classification?: string | null;
  severity?: string | null;
  reason?: string | null;
  recommended_action?: string | null;
};


type HealthPayload = {
  ok?: boolean;
  status?: HealthStatus;
  status_label?: string;
  last_run_id?: string | null;
  last_run_at?: string | null;
  age_minutes?: number | null;
  cron_fresh?: boolean;
  mode?: string | null;
  journal_source?: string | null;
  db_open_count?: number | null;
  journal_open_count?: number | null;
  matched_count?: number | null;
  mismatch_count?: number | null;
  duplicate_count?: number | null;
  mirror_account_count?: number | null;
  missing_identifier_count?: number | null;
  unresolved_items?: ReconciliationItem[];
  latest_items?: ReconciliationItem[];
  report_path?: string | null;
  safety?: Record<string, any>;
  error?: string | null;
};


type Props = {
  compact?: boolean;
  title?: string;
  showItems?: boolean;
  onOpenItems?: (payload: HealthPayload) => void;
  className?: string;
};


const ENDPOINT = '/api/v2/atm/reconciliation-health';


function statusTone(status?: string): string {
  switch ((status || '').toLowerCase()) {
    case 'healthy': return 'healthy';
    case 'warning': return 'warning';
    case 'stale': return 'warning';
    case 'mismatch': return 'danger';
    case 'error': return 'danger';
    case 'no_data': return 'warning';
    default: return 'neutral';
  }
}


function fmt(v: any, fallback = '—') {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}


function ageLabel(minutes?: number | null) {
  if (minutes === null || minutes === undefined || Number.isNaN(Number(minutes))) return 'unknown age';
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(1)}h ago`;
  return `${(hours / 24).toFixed(1)}d ago`;
}


function CountBox({ label, value, tone = 'neutral' }: { label: string; value: any; tone?: string }) {
  return <div className={`recon-count recon-${tone}`}><strong>{fmt(value, '0')}</strong><span>{label}</span></div>;
}


export default function ReconciliationHealthPanel({ compact = false, title = 'Position Reconciliation Health', showItems = true, onOpenItems, className = '' }: Props) {
  const [payload, setPayload] = useState<HealthPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);


  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(ENDPOINT, { cache: 'no-store' });
      if (!response.ok) throw new Error(`${ENDPOINT} returned ${response.status}`);
      const data = await response.json();
      setPayload(data);
    } catch (err: any) {
      setError(err?.message || String(err));
      setPayload({ ok: false, status: 'error', status_label: 'Endpoint unavailable', error: err?.message || String(err) });
    } finally {
      setLoading(false);
    }
  }


  useEffect(() => { refresh(); }, []);


  const status = payload?.status || 'unknown';
  const tone = statusTone(status);
  const mismatch = Number(payload?.mismatch_count || 0);
  const unresolved = payload?.unresolved_items || [];


  return <section className={`recon-health recon-${tone} ${compact ? 'compact' : ''} ${className}`}>
    <style>{css}</style>
    <div className="recon-head">
      <div>
        <div className="recon-eyebrow">ATM audit-only control</div>
        <h2>{title}</h2>
        <p>{payload?.status_label || (error ? 'Unable to load latest reconciliation run' : 'Latest broker/journal versus DB-open reconciliation status')}</p>
      </div>
      <div className="recon-actions">
        <span className={`recon-status recon-${tone}`}>{fmt(status).toUpperCase()}</span>
        <button onClick={refresh} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
      </div>
    </div>


    <div className="recon-summary-line">
      <span>Last run: <b>{payload?.last_run_at ? ageLabel(payload.age_minutes) : 'not available'}</b></span>
      <span>Mode: <b>{fmt(payload?.mode, 'audit_only')}</b></span>
      <span>Fresh: <b>{payload?.cron_fresh ? 'yes' : 'no/unknown'}</b></span>
      <span>Source: <b>{fmt(payload?.journal_source, 'unknown')}</b></span>
    </div>


    <div className="recon-counts">
      <CountBox label="DB Open" value={payload?.db_open_count} tone="neutral" />
      <CountBox label="Journal Open" value={payload?.journal_open_count} tone="neutral" />
      <CountBox label="Matched" value={payload?.matched_count} tone="healthy" />
      <CountBox label="Mismatches" value={payload?.mismatch_count} tone={mismatch > 0 ? 'danger' : 'healthy'} />
      <CountBox label="Duplicates" value={payload?.duplicate_count} tone={Number(payload?.duplicate_count || 0) > 0 ? 'warning' : 'neutral'} />
      <CountBox label="Mirror Rows" value={payload?.mirror_account_count} tone={Number(payload?.mirror_account_count || 0) > 0 ? 'warning' : 'neutral'} />
    </div>


    {error && <div className="recon-error">{error}</div>}


    {mismatch > 0 && <div className="recon-alert">
      <strong>Reconciliation mismatch detected.</strong>
      <span>{mismatch} database-open record(s) do not match the broker/journal-open set.</span>
      {onOpenItems && <button onClick={() => onOpenItems(payload || {})}>Open Reconciliation Items</button>}
    </div>}


    {showItems && unresolved.length > 0 && <div className="recon-items">
      <h3>Unresolved reconciliation items</h3>
      <table><thead><tr><th>Symbol</th><th>#</th><th>Classification</th><th>Reason</th><th>Recommended Action</th></tr></thead><tbody>
        {unresolved.slice(0, 12).map((item, i) => <tr key={`${item.paper_trade_id || item.symbol || i}`}>
          <td>{fmt(item.symbol)}</td>
          <td>{fmt(item.paper_trade_id)}</td>
          <td><span className={`pill recon-${statusTone(item.severity || item.classification || '')}`}>{fmt(item.classification)}</span></td>
          <td>{fmt(item.reason)}</td>
          <td>{fmt(item.recommended_action)}</td>
        </tr>)}
      </tbody></table>
    </div>}


    <div className="recon-foot">
      <span>Safety: read-only endpoint; cron mode audit-only.</span>
      <span>Report: {fmt(payload?.report_path, 'latest reconciliation report')}</span>
    </div>
  </section>;
}


const css = `
.recon-health{border:1px solid #263244;border-radius:18px;background:#0b1019;color:#e8eef8;padding:18px;margin:18px 0;font-family:Inter,system-ui}.recon-health.compact{padding:14px}.recon-health.recon-healthy{border-color:#166534}.recon-health.recon-warning{border-color:#92400e}.recon-health.recon-danger{border-color:#7f1d1d}.recon-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.recon-head h2{margin:4px 0;font-size:22px}.recon-head p{margin:0;color:#9fb0c4}.recon-eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#60a5fa}.recon-actions{display:flex;align-items:center;gap:8px}.recon-actions button,.recon-alert button{background:#162033;color:#dbeafe;border:1px solid #334155;border-radius:8px;padding:8px 12px;cursor:pointer}.recon-status{border:1px solid #334155;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:800}.recon-status.recon-healthy{color:#4ade80;border-color:#166534}.recon-status.recon-warning{color:#fbbf24;border-color:#92400e}.recon-status.recon-danger{color:#fb7185;border-color:#7f1d1d}.recon-status.recon-neutral{color:#cbd5e1}.recon-summary-line{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0;color:#9fb0c4}.recon-summary-line b{color:#e8eef8}.recon-counts{display:grid;grid-template-columns:repeat(6,minmax(100px,1fr));gap:10px}.recon-count{background:#0d1320;border:1px solid #263244;border-radius:14px;padding:12px}.recon-count strong{display:block;font-size:26px}.recon-count span{font-size:12px;color:#9fb0c4}.recon-count.recon-healthy strong{color:#4ade80}.recon-count.recon-warning strong{color:#fbbf24}.recon-count.recon-danger strong{color:#fb7185}.recon-error{margin-top:12px;padding:10px;border:1px solid #7f1d1d;background:#2b1115;border-radius:10px;color:#fecaca}.recon-alert{display:flex;align-items:center;gap:12px;margin-top:14px;padding:12px;border:1px solid #92400e;background:#1f1608;border-radius:12px;color:#fde68a}.recon-items{margin-top:16px}.recon-items h3{margin:0 0 8px}.recon-items table{width:100%;border-collapse:collapse;font-size:13px}.recon-items th{text-align:left;color:#9fb0c4;border-bottom:1px solid #263244;padding:8px}.recon-items td{border-bottom:1px solid #1f2937;padding:8px}.pill{border:1px solid #334155;border-radius:999px;padding:3px 8px;font-size:11px;text-transform:uppercase}.pill.recon-healthy{color:#4ade80;border-color:#166534}.pill.recon-warning{color:#fbbf24;border-color:#92400e}.pill.recon-danger{color:#fb7185;border-color:#7f1d1d}.recon-foot{display:flex;justify-content:space-between;gap:12px;margin-top:12px;color:#64748b;font-size:12px}@media(max-width:1100px){.recon-head{display:block}.recon-actions{margin-top:10px}.recon-counts{grid-template-columns:repeat(2,1fr)}.recon-foot{display:block}}
`;
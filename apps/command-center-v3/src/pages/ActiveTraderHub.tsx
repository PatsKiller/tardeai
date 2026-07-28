import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import ActiveTraderPage from './ActiveTraderPage';
import ActiveTraderConfigTab from './ActiveTraderConfigTab';
import ActiveTraderCurrentMarks from './ActiveTraderCurrentMarks';
import ScalpStrategyModal from '../components/ScalpStrategyModal';
import type { Setup } from '../components/ScalpStrategyModal';

type SubTab = 'Review' | 'Configuration' | 'Setups';
const SUBTABS: SubTab[] = ['Review', 'Configuration', 'Setups'];

export default function ActiveTraderHub() {
  const [params, setParams] = useSearchParams();
  const raw = (params.get('tab') || 'Review') as SubTab;
  const tab: SubTab = SUBTABS.includes(raw) ? raw : 'Review';
  const setTab = (next: SubTab) => setParams(previous => { previous.set('tab', next); return previous; }, { replace: true });

  const { data: pq } = useApi<any>('/api/v3/active-trader/permission-queue', 5_000, { enabled: tab === 'Review' });
  const { data: firePerf } = useApi<any>('/api/v3/active-trader/fire-performance', 1_500, { enabled: tab === 'Review' });
  const { data: l2Status } = useApi<any>('/api/v3/active-trader/l2-status', 2_000, { enabled: tab === 'Review' });
  const { data: atSetups } = useApi<any>('/api/v3/active-trader/scalp/setups', 60_000);
  const scannerSignals = useMemo(() => pq ? (pq.signals ?? []).filter((signal: any) => signal?.source === 'scanner') : [], [pq]);
  const ignSignals = useMemo(() => pq ? (pq.signals ?? []).filter((signal: any) => signal?.source !== 'scanner') : undefined, [pq]);
  const scannerSymbols = useMemo(() => Array.from(new Set(scannerSignals.map((signal: any) => String(signal.symbol || '').toUpperCase()).filter(Boolean))).sort() as string[], [scannerSignals]);
  const marksPath = `/api/v3/active-trader/current-marks?symbols=${encodeURIComponent(scannerSymbols.join(','))}`;
  const { data: currentMarks } = useApi<any>(marksPath, 1_500, { enabled: tab === 'Review' && scannerSymbols.length > 0 });
  const [strategiesOpen, setStrategiesOpen] = useState(false);

  const engineStatus = pq?.engine_status;
  const statusPill = useMemo(() => {
    if (!engineStatus) return null;
    const scanner = engineStatus.scanner?.available
      ? `TradeAI ${engineStatus.scanner.go_count_today} GO · ${engineStatus.scanner.manual_review_count_today} manual-review`
      : 'scanner down';
    const ign = engineStatus.ign?.market_open
      ? `IGN live · ${engineStatus.ign.today_trigger_count} triggers`
      : `IGN idle · opens ${engineStatus.ign?.opens_et ?? '09:30'} ET`;
    return `${scanner}  ·  ${ign}`;
  }, [engineStatus]);

  return (
    <div className="active-trader-hub">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {SUBTABS.map(item => (
            <button key={item} type="button" onClick={() => setTab(item)} style={{ padding: '7px 16px', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: item === tab ? 700 : 500, border: '1px solid var(--border)', color: item === tab ? 'var(--text0)' : 'var(--text2)', background: item === tab ? 'var(--bg2)' : 'transparent' }}>{item}</button>
          ))}
        </div>
        {tab === 'Review' && statusPill && <span style={{ fontSize: 12, color: 'var(--text3)', fontFamily: 'ui-monospace, Menlo, monospace' }}>{statusPill}</span>}
      </div>

      {tab === 'Review' && (
        <>
          <ActiveTraderCurrentMarks symbols={scannerSymbols} payload={currentMarks ?? undefined} />
          <ActiveTraderPage
            signals={ignSignals}
            scannerSignals={pq ? scannerSignals : undefined}
            accounts={pq?.accounts ?? []}
            dataState={pq?.data_state}
            actionableCount={pq?.actionable_count}
            ignTriggerCount={pq?.ign_trigger_count}
            scannerGoCount={pq?.scanner_go_count}
            engineStatus={pq?.engine_status}
            arming={pq?.arming}
            lastIgnSessionDate={pq?.last_ign_session_date}
            registryHash={pq?.registry_hash}
            registryVersion={pq?.registry_version}
            firePerf={firePerf ?? undefined}
            l2Status={l2Status ?? undefined}
            onOpenStrategies={() => setStrategiesOpen(true)}
          />
          <ScalpStrategyModal open={strategiesOpen} onClose={() => setStrategiesOpen(false)} setups={(atSetups?.setup_registry?.setups ?? []) as Setup[]} registryHash={atSetups?.setup_registry?.registry_hash} />
        </>
      )}

      {tab === 'Configuration' && <ActiveTraderConfigTab />}
      {tab === 'Setups' && <ScalpSetupsInline setups={(atSetups?.setup_registry?.setups ?? []) as Setup[]} registryHash={atSetups?.setup_registry?.registry_hash} />}
    </div>
  );
}

function ScalpSetupsInline({ setups, registryHash }: { setups: Setup[]; registryHash?: string }) {
  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 20, background: 'var(--bg1)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: 'var(--text0)' }}>Setups &amp; strategy rules</h2>
        <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'ui-monospace, Menlo, monospace' }}>registry {registryHash ? registryHash.replace('sha256:', '').slice(0, 8) : '—'} · {setups.length} setups · SHADOW / manual paper only</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {setups.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 13 }}>Setup registry unavailable.</div>}
        {setups.map((setup: any) => (
          <div key={setup.id ?? setup.setup_id ?? setup.label} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: 'var(--bg0)' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{setup.label ?? setup.id}</div>
            <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2, fontFamily: 'ui-monospace, Menlo, monospace' }}>{setup.id ?? setup.setup_id} · v{setup.version ?? '—'}</div>
            {setup.description && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 8, lineHeight: 1.4 }}>{setup.description}</div>}
            {setup.required_data_tier && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>tier {setup.required_data_tier} · window {setup.window ?? setup.session_window ?? '—'}</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

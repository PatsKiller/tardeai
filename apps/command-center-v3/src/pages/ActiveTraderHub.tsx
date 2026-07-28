import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import ActiveTraderPage from './ActiveTraderPage';
import ActiveTraderConfigTab from './ActiveTraderConfigTab';
import ScalpStrategyModal from '../components/ScalpStrategyModal';
import type { Setup } from '../components/ScalpStrategyModal';

type SubTab = 'Review' | 'Configuration' | 'Setups';
const SUBTABS: SubTab[] = ['Review', 'Configuration', 'Setups'];

// Own top-level section (/v3/active-trader) with its own subtabs. Read-only; SHADOW / MANUAL PAPER ONLY.
export default function ActiveTraderHub() {
  const [params, setParams] = useSearchParams();
  const raw = (params.get('tab') || 'Review') as SubTab;
  const tab: SubTab = SUBTABS.includes(raw) ? raw : 'Review';
  const setTab = (t: SubTab) => setParams(p => { p.set('tab', t); return p; }, { replace: true });

  const { data: pq } = useApi<any>('/api/v3/active-trader/permission-queue', 5_000, { enabled: tab === 'Review' });
  const { data: atSetups } = useApi<any>('/api/v3/active-trader/scalp/setups', 60_000);
  const [strategiesOpen, setStrategiesOpen] = useState(false);

  const es = pq?.engine_status;
  const statusPill = useMemo(() => {
    if (!es) return null;
    const scanner = es.scanner?.available ? `TradeAI ${es.scanner.go_count_today} GO · ${es.scanner.manual_review_count_today} manual-review` : 'scanner down';
    const ign = es.ign?.market_open ? `IGN live · ${es.ign.today_trigger_count} triggers` : `IGN idle · opens ${es.ign?.opens_et ?? '09:30'} ET`;
    return `${scanner}  ·  ${ign}`;
  }, [es]);

  return (
    <div className="active-trader-hub">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {SUBTABS.map(t => (
            <button key={t} type="button" onClick={() => setTab(t)}
              style={{
                padding: '7px 16px', borderRadius: 8, cursor: 'pointer', fontSize: 13,
                fontWeight: t === tab ? 700 : 500,
                border: '1px solid var(--border)',
                color: t === tab ? 'var(--text0)' : 'var(--text2)',
                background: t === tab ? 'var(--bg2)' : 'transparent',
              }}>{t}</button>
          ))}
        </div>
        {tab === 'Review' && statusPill && (
          <span style={{ fontSize: 12, color: 'var(--text3)', fontFamily: 'ui-monospace, Menlo, monospace' }}>{statusPill}</span>
        )}
      </div>

      {tab === 'Review' && (
        <>
          <ActiveTraderPage
            signals={pq ? (pq.signals ?? []).filter((s: any) => s?.source !== 'scanner') : undefined}
            scannerSignals={pq ? (pq.signals ?? []).filter((s: any) => s?.source === 'scanner') : undefined}
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
            onOpenStrategies={() => setStrategiesOpen(true)}
          />
          <ScalpStrategyModal
            open={strategiesOpen}
            onClose={() => setStrategiesOpen(false)}
            setups={(atSetups?.setup_registry?.setups ?? []) as Setup[]}
            registryHash={atSetups?.setup_registry?.registry_hash}
          />
        </>
      )}

      {tab === 'Configuration' && <ActiveTraderConfigTab />}

      {tab === 'Setups' && (
        <ScalpSetupsInline setups={(atSetups?.setup_registry?.setups ?? []) as Setup[]} registryHash={atSetups?.setup_registry?.registry_hash} />
      )}
    </div>
  );
}

// Lightweight inline setups view (the modal content as a tab). Read-only registry render.
function ScalpSetupsInline({ setups, registryHash }: { setups: Setup[]; registryHash?: string }) {
  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 20, background: 'var(--bg1)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: 'var(--text0)' }}>Setups &amp; strategy rules</h2>
        <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'ui-monospace, Menlo, monospace' }}>
          registry {registryHash ? registryHash.replace('sha256:', '').slice(0, 8) : '—'} · {setups.length} setups · SHADOW / manual paper only
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {setups.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 13 }}>Setup registry unavailable.</div>}
        {setups.map((s: any) => (
          <div key={s.id ?? s.setup_id ?? s.label} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: 'var(--bg0)' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{s.label ?? s.id}</div>
            <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2, fontFamily: 'ui-monospace, Menlo, monospace' }}>{s.id ?? s.setup_id} · v{s.version ?? '—'}</div>
            {s.description && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 8, lineHeight: 1.4 }}>{s.description}</div>}
            {s.required_data_tier && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>tier {s.required_data_tier} · window {s.window ?? s.session_window ?? '—'}</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

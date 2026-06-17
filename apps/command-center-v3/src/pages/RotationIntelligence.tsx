import React, { useEffect, useState } from 'react';

type RotationPair = {
  action_class?: string;
  from_symbol?: string;
  to_symbol?: string;
  from_account?: string;
  to_account?: string;
  score?: number;
  review_amount?: number;
  rationale?: string;
  evidence?: Record<string, unknown>;
};

type RotationSummary = {
  ok?: boolean;
  advisory_only?: boolean;
  data_quality?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  top_rotation_ideas?: RotationPair[];
  top_pairs?: RotationPair[];
};

const money = (value?: number) =>
  typeof value === 'number'
    ? value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : 'review range unavailable';

export default function RotationIntelligence() {
  const [summary, setSummary] = useState<RotationSummary | null>(null);
  const [question, setQuestion] = useState('Review whether XLB exposure should be reduced to increase SPCX exposure.');
  const [answer, setAnswer] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  async function loadSummary() {
    setError('');
    try {
      const res = await fetch('/api/v2/rotation/summary');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSummary(await res.json());
    } catch (err) {
      setError(`Rotation summary endpoint not wired yet: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function askAdvisor(mode: 'local' | 'oauth_prompt') {
    setLoading(true);
    setError('');
    setAnswer('');
    try {
      const res = await fetch('/api/v2/rotation/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, backend: mode })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAnswer(data.answer || data.instructions || JSON.stringify(data, null, 2));
    } catch (err) {
      setError(`Rotation ask endpoint not wired yet: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSummary();
  }, []);

  const ideas = summary?.top_rotation_ideas || summary?.top_pairs || [];

  return (
    <div style={{ padding: 24, maxWidth: 1180, margin: '0 auto' }}>
      <header style={{ marginBottom: 24 }}>
        <h1>Rotation Intelligence</h1>
        <p>
          Account-aware advisory review for trims, adds, sector shifts, fund/ETF concentration, and local/OAuth LLM second opinions.
          This page is advisory only and does not create orders.
        </p>
      </header>

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 24 }}>
        <div className="card">
          <h3>Safety</h3>
          <p>Advisory only · human review required · no broker action</p>
        </div>
        <div className="card">
          <h3>Data Quality</h3>
          <pre>{JSON.stringify(summary?.data_quality || {}, null, 2)}</pre>
        </div>
        <div className="card">
          <h3>Summary</h3>
          <pre>{JSON.stringify(summary?.summary || {}, null, 2)}</pre>
        </div>
      </section>

      <section className="card" style={{ marginBottom: 24 }}>
        <h2>Ask Rotation Advisor</h2>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          style={{ width: '100%', marginBottom: 12 }}
        />
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button onClick={() => askAdvisor('local')} disabled={loading}>Ask Local LLM</button>
          <button onClick={() => askAdvisor('oauth_prompt')} disabled={loading}>Build OAuth Prompt</button>
          <button onClick={loadSummary}>Refresh Summary</button>
        </div>
        {answer && <pre style={{ whiteSpace: 'pre-wrap', marginTop: 16 }}>{answer}</pre>}
      </section>

      {error && <div style={{ color: '#f59e0b', marginBottom: 16 }}>{error}</div>}

      <section>
        <h2>Rotation Ideas</h2>
        {ideas.length === 0 && <p>No rotation ideas are currently available, or the endpoint has not been wired yet.</p>}
        <div style={{ display: 'grid', gap: 12 }}>
          {ideas.map((idea, idx) => (
            <article className="card" key={`${idea.from_symbol}-${idea.to_symbol}-${idx}`}>
              <h3>{idea.action_class || 'WATCH'} · {idea.from_symbol} → {idea.to_symbol}</h3>
              <p>{idea.rationale}</p>
              <p>
                Score: <strong>{idea.score ?? 'n/a'}</strong> · Review amount: <strong>{money(idea.review_amount)}</strong>
              </p>
              <p>From: {idea.from_account || 'n/a'} · To: {idea.to_account || 'n/a'}</p>
              <details>
                <summary>Evidence</summary>
                <pre>{JSON.stringify(idea.evidence || {}, null, 2)}</pre>
              </details>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

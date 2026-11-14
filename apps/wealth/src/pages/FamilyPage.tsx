import type { Family } from '../routes/families'

// Placeholder route target for the scaffold. It states plainly that the page is not built and
// shows no numbers — no mock data. It is replaced family by family by reviewed batches.
export function FamilyPage({ family }: { family: Family }) {
  return (
    <section aria-labelledby={`h-${family.id}`}>
      <h1 id={`h-${family.id}`}>{family.title}</h1>
      <p><strong>Not built yet.</strong> <em>This page shows no data until its reviewed batch lands.</em></p>
      <p>Decision it serves: {family.decision}</p>
      <details>
        <summary>Backend readers it will reuse</summary>
        <ul>{family.readers.map(r => <li key={r}><code>{r}</code></li>)}</ul>
        {family.gaps.length > 0 && (<><p>Known gaps (owned backend work):</p><ul>{family.gaps.map(g => <li key={g}>{g}</li>)}</ul></>)}
      </details>
    </section>
  )
}

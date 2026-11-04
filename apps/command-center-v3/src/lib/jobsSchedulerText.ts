// FQ-048 (/ops/jobs E) — how each job runs, in everyday words.
//
// Measured live 2026-11-04 (GET /api/v2/jobs-health?filter=all, 50 rows): scheduler values are
// cron 18, systemd 18, n8n 9, none 5, and the card printed them raw. The operator reads "Runs on:
// systemd" and has to know what that means. The exact value stays available as the cell's title.

export function schedulerWords(scheduler: string | null | undefined): string {
  switch (String(scheduler ?? '').trim().toLowerCase()) {
    case 'cron': return 'Scheduled on this machine'
    case 'systemd': return 'Background service on this machine'
    case 'n8n': return 'n8n workflow'
    case 'none': return 'Not scheduled'
    case '': return 'Not recorded'
    default: return String(scheduler)   // an unknown scheduler keeps its own name; never invent one
  }
}

/** The exact scheduler value, for the hover/technical detail — nothing is removed from the page. */
export function schedulerTechnical(scheduler: string | null | undefined): string {
  const raw = String(scheduler ?? '').trim()
  return raw ? `Scheduler: ${raw}` : 'Scheduler not recorded'
}

/**
 * The words for the stage an item is at (FQ-032).
 *
 * Review at 9ff60477c (F2): a line that said the work had FAILED, decided from the cell's RAG colour, is wrong — the
 * producer uses red for more than execution failure. `scripts/lib/work_pipeline.py` renders a stale claim (no
 * heartbeat, no build started) as `stage=claimed, rag=red, label=stale`, exactly like it renders a CI failure as
 * `stage=ci, rag=red, label=1 fail`. Only the producer's own label distinguishes them, so this returns that label and
 * infers nothing from colour. The label map is passed in so this module has no imports and is testable on its own.
 */
export type StageCellLike = { stage: string; rag: string; label?: string }

export function currentStageWords(cells: ReadonlyArray<StageCellLike>, stage: string,
                                  stageLabel: Record<string, string> = {}): string {
  const current = cells.find(c => c.stage === stage)
  return (current?.label || stageLabel[stage] || '').trim() || 'stage not reported'
}

import type { Application } from '../api/client'

export const STEPS = [
  { node: 'parse_job', label: 'Parse job posting' },
  { node: 'research', label: 'Research company' },
  { node: 'fit_analysis', label: 'Analyse fit' },
  { node: 'fit_review', label: 'Your review: fit' },
  { node: 'tailor_bullets', label: 'Tailor CV bullets' },
  { node: 'check_bullets', label: 'Check bullets against CV' },
  { node: 'write_letter', label: 'Write cover letter' },
  { node: 'check_letter', label: 'Check letter against CV' },
  { node: 'content_review', label: 'Your review: content' },
] as const

export type StepState = 'done' | 'active' | 'waiting' | 'failed' | 'pending' | 'skipped'

type AppView = Pick<Application, 'status' | 'next_steps' | 'reviews'>

/** Per-step state, derived from where the graph is (next_steps) and the run status. */
export function stepStates(app: AppView): StepState[] {
  if (app.status === 'completed') return STEPS.map(() => 'done')
  if (app.status === 'rejected') {
    const gate = app.reviews?.at(-1)?.gate
    const stop = STEPS.findIndex((s) => s.node === gate)
    return STEPS.map((_, i) => (i <= stop ? 'done' : 'skipped'))
  }
  // A brand-new run has no checkpoint yet: it is about to start the first step.
  const current = app.next_steps[0] ?? STEPS[0].node
  const at = STEPS.findIndex((s) => s.node === current)
  const here: StepState =
    app.status === 'failed' ? 'failed' : app.status === 'awaiting_approval' ? 'waiting' : 'active'
  return STEPS.map((_, i) => (i < at ? 'done' : i === at ? here : 'pending'))
}

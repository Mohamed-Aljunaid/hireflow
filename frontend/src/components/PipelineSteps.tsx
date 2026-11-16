import type { Application } from '../api/client'
import { STEPS, stepStates, type StepState } from '../lib/steps'

const ICON: Record<StepState, string> = {
  done: '✓',
  active: '…',
  waiting: '!',
  failed: '✕',
  pending: '',
  skipped: '–',
}

const STYLE: Record<StepState, string> = {
  done: 'bg-emerald-500 text-white',
  active: 'bg-indigo-500 text-white animate-pulse',
  waiting: 'bg-amber-400 text-white',
  failed: 'bg-red-500 text-white',
  pending: 'border border-slate-300 bg-white',
  skipped: 'bg-slate-200 text-slate-500',
}

export function PipelineSteps({ app }: { app: Application }) {
  const states = stepStates(app)
  return (
    <ol className="space-y-2" aria-label="Pipeline steps">
      {STEPS.map((step, i) => (
        <li key={step.node} className="flex items-center gap-3 text-sm" data-state={states[i]}>
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${STYLE[states[i]]}`}
            aria-hidden
          >
            {ICON[states[i]]}
          </span>
          <span className={states[i] === 'pending' || states[i] === 'skipped' ? 'text-slate-400' : ''}>
            {step.label}
          </span>
          <span className="sr-only">({states[i]})</span>
        </li>
      ))}
    </ol>
  )
}

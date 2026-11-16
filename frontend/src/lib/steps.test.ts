import { describe, expect, it } from 'vitest'
import { application } from '../test/fixtures'
import { STEPS, stepStates } from './steps'

const at = (node: string) => STEPS.findIndex((s) => s.node === node)

describe('stepStates', () => {
  it('marks steps before the current one done, the current active, the rest pending', () => {
    const states = stepStates(application({ next_steps: ['fit_analysis'] }))
    expect(states.slice(0, at('fit_analysis'))).toEqual(['done', 'done'])
    expect(states[at('fit_analysis')]).toBe('active')
    expect(states.slice(at('fit_analysis') + 1).every((s) => s === 'pending')).toBe(true)
  })

  it('treats a brand-new run (no checkpoint yet) as starting the first step', () => {
    expect(stepStates(application({ next_steps: [] }))[0]).toBe('active')
  })

  it('shows a paused gate as waiting and a failed step as failed', () => {
    const paused = application({ status: 'awaiting_approval', next_steps: ['content_review'] })
    expect(stepStates(paused)[at('content_review')]).toBe('waiting')
    const failed = application({ status: 'failed', next_steps: ['write_letter'] })
    expect(stepStates(failed)[at('write_letter')]).toBe('failed')
  })

  it('follows a claim-check rewrite loop back to the drafting step', () => {
    const states = stepStates(application({ next_steps: ['tailor_bullets'] }))
    expect(states[at('check_bullets')]).toBe('pending')
    expect(states[at('tailor_bullets')]).toBe('active')
  })

  it('marks everything done when completed', () => {
    expect(stepStates(application({ status: 'completed', next_steps: [] }))).toEqual(
      STEPS.map(() => 'done'),
    )
  })

  it('skips the steps after the gate where the user rejected', () => {
    const states = stepStates(
      application({
        status: 'rejected',
        next_steps: [],
        reviews: [{ gate: 'fit_review', action: 'reject', decided_at: 'x' }],
      }),
    )
    expect(states[at('fit_review')]).toBe('done')
    expect(states[at('tailor_bullets')]).toBe('skipped')
    expect(states.at(-1)).toBe('skipped')
  })
})

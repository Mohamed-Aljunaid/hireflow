import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { evidence, fitReport } from '../test/fixtures'
import { FitReview } from './FitReview'

function setup() {
  const onDecide = vi.fn()
  render(<FitReview report={fitReport} evidence={evidence} onDecide={onDecide} />)
  return { onDecide, user: userEvent.setup() }
}

describe('FitReview', () => {
  it('shows scores, verdicts and the cited CV text', () => {
    setup()
    expect(screen.getByText('71')).toBeInTheDocument()
    expect(screen.getByText('Kubernetes in production')).toBeInTheDocument()
    expect(screen.getByText('not met')).toBeInTheDocument()
    expect(screen.getByText(/Led migration of a monolith to FastAPI/)).toBeInTheDocument()
  })

  it('approves with optional feedback', async () => {
    const { onDecide, user } = setup()
    await user.type(screen.getByLabelText('Feedback (optional)'), 'Looks right')
    await user.click(screen.getByRole('button', { name: 'Approve and continue' }))
    expect(onDecide).toHaveBeenCalledWith({ action: 'approve', feedback: 'Looks right' })
  })

  it('rejects', async () => {
    const { onDecide, user } = setup()
    await user.click(screen.getByRole('button', { name: /Reject/ }))
    expect(onDecide).toHaveBeenCalledWith({ action: 'reject', feedback: null })
  })

  it('sends an override that cites real CV evidence and requires a note', async () => {
    const { onDecide, user } = setup()
    await user.click(screen.getAllByRole('button', { name: 'Override verdict' })[1]) // must-3

    await user.selectOptions(screen.getByLabelText('Verdict'), 'partial')
    const save = screen.getByRole('button', { name: 'Save overrides and continue' })
    expect(save).toBeDisabled() // partial needs evidence and a note
    expect(screen.getByText(/Each override needs a reason/)).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText(/Evidence from your CV/), 'skill-5')
    expect(save).toBeDisabled()
    await user.type(screen.getByLabelText('Why (required)'), 'Docker is adjacent')
    expect(save).toBeEnabled()

    await user.click(save)
    expect(onDecide).toHaveBeenCalledWith({
      action: 'edit',
      feedback: null,
      match_overrides: [
        {
          requirement_id: 'must-3',
          verdict: 'partial',
          evidence_refs: ['skill-5'],
          note: 'Docker is adjacent',
        },
      ],
    })
  })

  it('can discard overrides and go back to approve', async () => {
    const { user } = setup()
    await user.click(screen.getAllByRole('button', { name: 'Override verdict' })[0])
    await user.click(screen.getByRole('button', { name: 'Discard overrides' }))
    expect(screen.getByRole('button', { name: 'Approve and continue' })).toBeEnabled()
  })
})

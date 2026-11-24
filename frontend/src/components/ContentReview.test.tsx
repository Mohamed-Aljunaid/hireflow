import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { evidence, letter, tailored } from '../test/fixtures'
import { BulletDiff, ContentReview } from './ContentReview'

function setup(overrides: Partial<Parameters<typeof ContentReview>[0]> = {}) {
  const onDecide = vi.fn()
  render(
    <ContentReview
      tailored={tailored}
      letter={letter}
      evidence={evidence}
      onDecide={onDecide}
      {...overrides}
    />,
  )
  return { onDecide, user: userEvent.setup() }
}

describe('BulletDiff', () => {
  it('marks words added and removed relative to the CV text', () => {
    const { container } = render(
      <BulletDiff original="Cut latency by introducing caching." tailored="Cut p95 latency with caching." />,
    )
    expect([...container.querySelectorAll('ins')].map((n) => n.textContent?.trim())).toContain('p95')
    expect(container.querySelector('del')?.textContent).toContain('introducing')
  })
})

describe('ContentReview', () => {
  it('shows each bullet next to a diff against the CV items it cites', () => {
    setup()
    expect(screen.getByLabelText('Bullet tb-1')).toHaveValue(tailored.bullets[0].text)
    expect(screen.getAllByTestId('bullet-diff')).toHaveLength(2)
    expect(screen.getByText('cites exp-1.b1')).toBeInTheDocument()
    expect(screen.getByLabelText('Paragraph p-1')).toHaveValue(letter.paragraphs[0].text)
  })

  it('approves when nothing was edited', async () => {
    const { onDecide, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(onDecide).toHaveBeenCalledWith({ action: 'approve', feedback: null })
  })

  it('sends only the changed items as text edits', async () => {
    const { onDecide, user } = setup()
    const p2 = screen.getByLabelText('Paragraph p-2')
    await user.clear(p2)
    await user.type(p2, 'Happy to talk any time.')

    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Save 1 edit and finish' }))

    expect(onDecide).toHaveBeenCalledWith({
      action: 'edit',
      feedback: null,
      text_edits: [{ id: 'p-2', text: 'Happy to talk any time.' }],
    })
  })

  it('blocks saving an emptied item', async () => {
    const { user } = setup()
    await user.clear(screen.getByLabelText('Bullet tb-2'))
    expect(screen.getByRole('button', { name: /Save 1 edit/ })).toBeDisabled()
    expect(screen.getByText(/A bullet or paragraph is empty/)).toBeInTheDocument()
    expect(screen.getByText(/undo your edits first/)).toBeInTheDocument()
  })

  it('regenerates with feedback, and rejects', async () => {
    const { onDecide, user } = setup()
    await user.type(screen.getByLabelText(/Feedback for a regeneration/), 'More formal')
    await user.click(screen.getByRole('button', { name: 'Regenerate' }))
    expect(onDecide).toHaveBeenLastCalledWith({ action: 'regenerate', feedback: 'More formal' })

    await user.click(screen.getByRole('button', { name: 'Reject' }))
    expect(onDecide).toHaveBeenLastCalledWith({ action: 'reject', feedback: 'More formal' })
  })

  it('shows claim-check warnings', () => {
    setup({ tailored: { ...tailored, warnings: ['Removed bullet tb-5 after rewrites'] } })
    expect(screen.getByRole('status')).toHaveTextContent('Removed bullet tb-5')
  })
})

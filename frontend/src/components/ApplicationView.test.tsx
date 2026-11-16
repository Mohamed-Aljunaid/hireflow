import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import { application, atContentReview, atFitReview, cv, letter, tailored } from '../test/fixtures'
import { ApplicationView } from './ApplicationView'

function mockApi(...states: ReturnType<typeof application>[]) {
  const get = vi.spyOn(api, 'getApplication')
  for (const s of states.slice(0, -1)) get.mockResolvedValueOnce(s)
  get.mockResolvedValue(states.at(-1)!)
  vi.spyOn(api, 'getCv').mockResolvedValue(cv)
  return get
}

describe('ApplicationView', () => {
  it('shows the fit review when paused there, and the content review after approving', async () => {
    mockApi(atFitReview, atContentReview)
    const resume = vi
      .spyOn(api, 'resume')
      .mockResolvedValue(application({ status: 'running', next_steps: ['tailor_bullets'] }))
    render(<ApplicationView appId="app-1" onStartOver={() => {}} />)

    await screen.findByText('Review the fit analysis')
    expect(screen.getByTestId('status')).toHaveTextContent('Waiting for your review')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Approve and continue' }))

    expect(resume).toHaveBeenCalledWith('app-1', { action: 'approve', feedback: null })
    await screen.findByText(/Review your tailored CV bullets/)
  })

  it('polls while running and stops once the run pauses', async () => {
    const running = application({ status: 'running', next_steps: ['research'] })
    const get = mockApi(running, atFitReview)
    render(<ApplicationView appId="app-1" onStartOver={() => {}} />)

    expect(await screen.findByText(/The agents are working/)).toBeInTheDocument()
    await screen.findByText('Review the fit analysis', {}, { timeout: 3000 })
    const calls = get.mock.calls.length
    await new Promise((r) => setTimeout(r, 1700))
    expect(get.mock.calls.length).toBe(calls) // no polling while waiting for the user
  })

  it('shows the export when completed', async () => {
    mockApi(application({ status: 'completed', next_steps: [], tailored, cover_letter: letter }))
    render(<ApplicationView appId="app-1" onStartOver={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Copy to clipboard' })).toBeInTheDocument()
  })

  it('shows why a run failed', async () => {
    mockApi(application({ status: 'failed', next_steps: ['parse_job'], error: 'rate limited' }))
    render(<ApplicationView appId="app-1" onStartOver={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The pipeline failed: rate limited')
  })

  it('shows API validation errors from a decision and stays on the review', async () => {
    mockApi(atFitReview)
    vi.spyOn(api, 'resume').mockRejectedValue(new ApiError(409, 'not awaiting approval'))
    render(<ApplicationView appId="app-1" onStartOver={() => {}} />)

    await userEvent.setup().click(await screen.findByRole('button', { name: /Reject/ }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('not awaiting approval'),
    )
    expect(screen.getByText('Review the fit analysis')).toBeInTheDocument()
  })
})

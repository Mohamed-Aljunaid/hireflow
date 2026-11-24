import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, api, type JobSearchResult } from '../api/client'
import { listing } from '../test/fixtures'
import { JobSearch } from './JobSearch'

const result = (overrides: Partial<JobSearchResult> = {}): JobSearchResult => ({
  listings: [listing],
  total: 45,
  page: 1,
  has_more: true,
  ...overrides,
})

async function search(text = 'agentic AI') {
  const user = userEvent.setup()
  const onPick = vi.fn()
  render(<JobSearch onPick={onPick} />)
  await user.type(screen.getByLabelText('Job title or skill'), text)
  await user.click(screen.getByRole('button', { name: 'Search' }))
  return { user, onPick }
}

describe('JobSearch', () => {
  it('searches Saudi Arabia by default, links back to Himalayas and picks a job', async () => {
    const searchJobs = vi.spyOn(api, 'searchJobs').mockResolvedValue(result())
    const { user, onPick } = await search()

    expect(searchJobs).toHaveBeenCalledWith('agentic AI', 'SA', 1)
    expect(await screen.findByText('45 jobs found, page 1')).toBeInTheDocument()
    expect(screen.getByText(/Saudi Arabia only/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View on Himalayas' })).toHaveAttribute(
      'href',
      listing.source_url,
    )
    await user.click(screen.getByRole('button', { name: /Use this job/ }))
    expect(onPick).toHaveBeenCalledWith(listing)
  })

  it('pages through the search that was run, not the text being edited', async () => {
    const searchJobs = vi.spyOn(api, 'searchJobs').mockResolvedValueOnce(result())
    const { user } = await search()
    searchJobs.mockResolvedValue(result({ page: 2, has_more: false }))
    await user.type(screen.getByLabelText('Job title or skill'), ' changed')
    await user.click(await screen.findByRole('button', { name: 'Next' }))

    expect(searchJobs).toHaveBeenLastCalledWith('agentic AI', 'SA', 2)
    expect(await screen.findByText(/page 2/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('warns that multi-country listings need an eligibility check', async () => {
    vi.spyOn(api, 'searchJobs').mockResolvedValue(
      result({ listings: [{ ...listing, location_scope: 'multi_country' }] }),
    )
    await search()
    expect(await screen.findByText(/check eligibility/)).toBeInTheDocument()
  })

  it('shows empty results and provider errors', async () => {
    const searchJobs = vi
      .spyOn(api, 'searchJobs')
      .mockResolvedValueOnce(result({ listings: [], total: 0, has_more: false }))
    const { user } = await search()
    expect(await screen.findByText(/No jobs found/)).toBeInTheDocument()

    searchJobs.mockRejectedValue(new ApiError(503, 'rate limiting us'))
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('rate limiting us')
  })

  it('explains why Search is disabled', () => {
    render(<JobSearch onPick={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
    expect(screen.getByText(/at least 2 characters/)).toBeInTheDocument()
  })
})

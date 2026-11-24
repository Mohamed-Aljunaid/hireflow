import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { application, cv, listing } from '../test/fixtures'
import { JobForm } from './JobForm'

it('explains why Start is disabled, then starts the pipeline', async () => {
  const create = vi.spyOn(api, 'createApplication').mockResolvedValue(application())
  const onCreated = vi.fn()
  const user = userEvent.setup()
  render(<JobForm cv={cv} onCreated={onCreated} />)

  const start = screen.getByRole('button', { name: 'Start pipeline' })
  const box = screen.getByLabelText('Job posting')
  await user.type(box, 'short')
  expect(start).toBeDisabled()
  expect(screen.getByText(/at least 50 characters \(5\/50\)/)).toBeInTheDocument()

  const posting = 'x'.repeat(50)
  await user.clear(box)
  await user.click(box)
  await user.paste(posting)
  expect(screen.queryByText(/at least 50 characters/)).not.toBeInTheDocument()
  await user.click(start)

  expect(create).toHaveBeenCalledWith('cv-1', posting, undefined)
  expect(onCreated).toHaveBeenCalled()
})

async function pickJob() {
  vi.spyOn(api, 'searchJobs').mockResolvedValue({
    listings: [listing],
    total: 1,
    page: 1,
    has_more: false,
  })
  const create = vi.spyOn(api, 'createApplication').mockResolvedValue(application())
  const user = userEvent.setup()
  render(<JobForm cv={cv} onCreated={vi.fn()} />)
  await user.type(screen.getByLabelText('Job title or skill'), 'AI')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await user.click(await screen.findByRole('button', { name: /Use this job/ }))
  return { create, user, box: screen.getByLabelText('Job posting') }
}

it('fills the posting from a picked job and sends its apply link', async () => {
  const { create, user, box } = await pickJob()
  expect(box).toHaveValue(listing.posting_text)
  expect(box).toHaveFocus()
  expect(screen.getByText(/Applying to:/)).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Start pipeline' }))
  expect(create).toHaveBeenCalledWith('cv-1', listing.posting_text, listing.apply_url)
})

it('drops the apply link when the posting is replaced', async () => {
  const { create, user, box } = await pickJob()
  await user.clear(box)
  expect(screen.queryByText(/Applying to:/)).not.toBeInTheDocument()
  await user.click(box)
  await user.paste('y'.repeat(60))
  await user.click(screen.getByRole('button', { name: 'Start pipeline' }))
  expect(create).toHaveBeenCalledWith('cv-1', 'y'.repeat(60), undefined)
})

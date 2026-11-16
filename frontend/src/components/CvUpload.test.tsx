import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import { cv } from '../test/fixtures'
import { CvUpload } from './CvUpload'

const file = new File(['Jordan Rivera'], 'cv.txt', { type: 'text/plain' })

describe('CvUpload', () => {
  it('uploads the chosen file and reports the parsed CV', async () => {
    const upload = vi.spyOn(api, 'uploadCv').mockResolvedValue(cv)
    const onUploaded = vi.fn()
    const user = userEvent.setup()
    render(<CvUpload onUploaded={onUploaded} />)

    const button = screen.getByRole('button', { name: 'Upload and parse' })
    expect(button).toBeDisabled()
    await user.upload(screen.getByLabelText('CV file'), file)
    await user.click(button)

    expect(upload).toHaveBeenCalledWith(file)
    expect(onUploaded).toHaveBeenCalledWith(cv)
  })

  it('shows the API error', async () => {
    vi.spyOn(api, 'uploadCv').mockRejectedValue(new ApiError(415, 'unsupported file type'))
    const user = userEvent.setup()
    render(<CvUpload onUploaded={vi.fn()} />)

    await user.upload(screen.getByLabelText('CV file'), file)
    await user.click(screen.getByRole('button', { name: 'Upload and parse' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('unsupported file type')
  })
})

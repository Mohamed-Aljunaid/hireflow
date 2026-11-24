import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { letter, tailored } from '../test/fixtures'
import { ExportPanel } from './ExportPanel'

describe('ExportPanel', () => {
  it('shows bullets and letter as plain text and copies them', async () => {
    const user = userEvent.setup() // installs a clipboard stub
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    render(<ExportPanel tailored={tailored} letter={letter} />)

    const text = screen.getByText(/TAILORED CV BULLETS/).textContent ?? ''
    expect(text).toContain('- Cut p95 latency 40% by introducing Redis caching.')
    expect(text).toContain('Dear Hiring Team,\n\nAt Acme Analytics')
    expect(text).toContain('Best regards,\nJordan Rivera')

    await user.click(screen.getByRole('button', { name: 'Copy to clipboard' }))
    expect(writeText).toHaveBeenCalledWith(text)
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('links to the application page only when the job came from a search', () => {
    const { rerender } = render(<ExportPanel tailored={tailored} letter={letter} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    rerender(<ExportPanel tailored={tailored} letter={letter} applyUrl="https://x.example/apply" />)
    expect(screen.getByRole('link', { name: 'Apply for this job' })).toHaveAttribute(
      'href',
      'https://x.example/apply',
    )
  })

  it('downloads a .txt file', async () => {
    const createObjectURL = vi.fn(() => 'blob:x')
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<ExportPanel tailored={tailored} letter={letter} />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Download .txt' }))

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:x')
  })
})

import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './client'

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
}

describe('api client', () => {
  it('prefixes /api and sends JSON', async () => {
    const fetch = mockFetch(202, { id: 'app-1' })
    await api.resume('app-1', { action: 'approve' })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/applications/app-1/resume')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ action: 'approve' })
  })

  it('surfaces FastAPI string details', async () => {
    mockFetch(409, { detail: 'not awaiting approval' })
    await expect(api.getApplication('x')).rejects.toEqual(
      expect.objectContaining({ status: 409, message: 'not awaiting approval' }),
    )
  })

  it('joins validation error lists', async () => {
    mockFetch(422, { detail: [{ msg: 'field required' }, { msg: 'too short' }] })
    const err = await api.createApplication('cv', 'x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toBe('field required; too short')
  })

  it('uploads the CV as multipart form data', async () => {
    const fetch = mockFetch(201, { id: 'cv-1' })
    await api.uploadCv(new File(['x'], 'cv.txt'))
    expect(fetch.mock.calls[0][1]?.body).toBeInstanceOf(FormData)
  })
})

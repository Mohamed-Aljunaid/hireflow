import type { components } from './schema'

type Schemas = components['schemas']
export type Application = Schemas['ApplicationRead']
export type CV = Schemas['CVRead']
export type ReviewDecision = Schemas['ReviewDecision']
export type MatchOverride = Schemas['MatchOverride']
export type TextEdit = Schemas['TextEdit']
export type FitReport = Schemas['FitReport']
export type TailoredBullets = Schemas['TailoredBullets']
export type CoverLetter = Schemas['CoverLetter']
export type Verdict = Schemas['RequirementMatch']['verdict']

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// FastAPI sends {detail: string} or, for body validation, {detail: [{msg, loc}, ...]}.
function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `${res.status} ${res.statusText}`))
  return body as T
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

export const api = {
  uploadCv(file: File): Promise<CV> {
    const form = new FormData()
    form.append('file', file)
    return request('/cvs', { method: 'POST', body: form })
  },
  getCv: (id: string): Promise<CV> => request(`/cvs/${id}`),
  createApplication: (cvId: string, jobText: string): Promise<Application> =>
    request('/applications', json('POST', { cv_id: cvId, job_text: jobText })),
  getApplication: (id: string): Promise<Application> => request(`/applications/${id}`),
  resume: (id: string, decision: ReviewDecision): Promise<Application> =>
    request(`/applications/${id}/resume`, json('POST', decision)),
}

// Shaped like real API responses (the backend's mock-LLM sample data).
import type {
  Application,
  CoverLetter,
  CV,
  FitReport,
  JobListing,
  TailoredBullets,
} from '../api/client'

export const evidence: Record<string, string> = {
  'exp-1': 'Senior Backend Engineer at Acme Analytics (Mar 2022 - Present)',
  'exp-1.b1': 'Led migration of a monolith to FastAPI microservices serving 2M requests/day.',
  'exp-1.b2': 'Cut p95 latency 40% by introducing Redis caching.',
  'skill-5': 'Docker',
}

export const cv: CV = {
  id: 'cv-1',
  filename: 'cv.pdf',
  content_type: 'application/pdf',
  created_at: '2026-11-16T10:00:00Z',
  parsed: { contact: { name: 'Jordan Rivera' } },
  evidence,
}

export const fitReport: FitReport = {
  overall_score: 71,
  must_have_score: 67,
  nice_to_have_score: 100,
  summary: 'Strong Python/FastAPI fit; Kubernetes is the main gap.',
  matches: [
    {
      requirement_id: 'must-2',
      requirement_text: 'FastAPI or similar async framework',
      importance: 'must',
      verdict: 'met',
      evidence_refs: ['exp-1.b1'],
      rationale: 'Led a FastAPI migration.',
      source: 'analyst',
    },
    {
      requirement_id: 'must-3',
      requirement_text: 'Kubernetes in production',
      importance: 'must',
      verdict: 'not_met',
      evidence_refs: [],
      rationale: 'No Kubernetes on the CV.',
      source: 'analyst',
    },
  ],
  strengths: [],
  gaps: [],
  warnings: [],
}

export const tailored: TailoredBullets = {
  bullets: [
    { id: 'tb-1', text: 'Led FastAPI microservices migration serving 2M requests/day.', source_cv_refs: ['exp-1.b1'], author: 'model' },
    { id: 'tb-2', text: 'Cut p95 latency 40% by introducing Redis caching.', source_cv_refs: ['exp-1.b2'], author: 'model' },
  ],
  warnings: [],
}

export const letter: CoverLetter = {
  salutation: 'Dear Hiring Team,',
  paragraphs: [
    { id: 'p-1', text: 'At Acme Analytics I led a FastAPI migration.', source_cv_refs: ['exp-1'], author: 'model' },
    { id: 'p-2', text: 'I would welcome a conversation.', author: 'model' },
  ],
  closing: 'Best regards,\nJordan Rivera',
  warnings: [],
}

export const listing: JobListing = {
  title: 'Senior AI Engineer',
  company: 'Acme',
  posting_text: 'Senior AI Engineer - Acme\nRemote (Saudi Arabia)\n\nWe build agents with LangGraph.',
  location_scope: 'country_only',
  apply_url: 'https://himalayas.app/jobs/ai?utm_source=api',
  source_url: 'https://himalayas.app/jobs/ai',
  published_at: '2026-11-20T10:00:00Z',
  expires_at: null,
}

export function application(overrides: Partial<Application> = {}): Application {
  return {
    id: 'app-1',
    cv_id: 'cv-1',
    status: 'running',
    error: null,
    created_at: '2026-11-16T10:00:00Z',
    updated_at: '2026-11-16T10:00:00Z',
    next_steps: ['parse_job'],
    pending_review: null,
    reviews: [],
    ...overrides,
  }
}

export const atFitReview = application({
  status: 'awaiting_approval',
  next_steps: ['fit_review'],
  pending_review: { gate: 'fit_review', allowed_actions: ['approve', 'edit', 'reject'], payload: {} },
  fit_report: fitReport,
})

export const atContentReview = application({
  status: 'awaiting_approval',
  next_steps: ['content_review'],
  pending_review: {
    gate: 'content_review',
    allowed_actions: ['approve', 'edit', 'regenerate', 'reject'],
    payload: {},
  },
  reviews: [{ gate: 'fit_review', action: 'approve', decided_at: '2026-11-16T10:01:00Z' }],
  fit_report: fitReport,
  tailored,
  cover_letter: letter,
})

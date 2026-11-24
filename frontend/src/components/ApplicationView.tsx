import { useEffect, useState } from 'react'
import { api, type CV, type ReviewDecision } from '../api/client'
import { useApplication } from '../hooks/useApplication'
import { ContentReview } from './ContentReview'
import { ExportPanel } from './ExportPanel'
import { FitReview } from './FitReview'
import { PipelineSteps } from './PipelineSteps'
import { btnSecondary, card } from './ui'

const STATUS_LABEL: Record<string, string> = {
  running: 'Working…',
  awaiting_approval: 'Waiting for your review',
  completed: 'Completed',
  rejected: 'Stopped by you',
  failed: 'Failed',
}

export function ApplicationView({ appId, onStartOver }: { appId: string; onStartOver: () => void }) {
  const { app, error, update } = useApplication(appId)
  const [cv, setCv] = useState<CV | null>(null)
  const [busy, setBusy] = useState(false)
  const [decideError, setDecideError] = useState<string | null>(null)
  const cvId = app?.cv_id

  useEffect(() => {
    if (cvId) api.getCv(cvId).then(setCv, () => setCv(null))
  }, [cvId])

  async function decide(decision: ReviewDecision) {
    setBusy(true)
    setDecideError(null)
    try {
      update(await api.resume(appId, decision))
    } catch (e) {
      setDecideError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!app) {
    return <p className="text-sm text-slate-600">{error ?? 'Loading application…'}</p>
  }

  const gate = app.status === 'awaiting_approval' ? app.pending_review?.gate : undefined
  const evidence = cv?.evidence ?? {}

  return (
    <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
      <aside className={`${card} h-fit`}>
        <p className="text-xs uppercase tracking-wide text-slate-500">Status</p>
        <p className="mb-4 font-medium" data-testid="status">
          {STATUS_LABEL[app.status] ?? app.status}
        </p>
        <PipelineSteps app={app} />
        <button className={`${btnSecondary} mt-6 w-full`} onClick={onStartOver}>
          New application
        </button>
      </aside>

      <div className="space-y-4">
        {error && <p className="text-sm text-amber-700">Connection problem: {error}. Retrying…</p>}
        {decideError && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {decideError}
          </p>
        )}
        {app.status === 'running' && (
          <p className={`${card} text-sm text-slate-600`}>
            The agents are working. This page updates on its own.
          </p>
        )}
        {app.status === 'failed' && (
          <p role="alert" className={`${card} text-sm text-red-800`}>
            The pipeline failed: {app.error}
          </p>
        )}
        {app.status === 'rejected' && (
          <p className={`${card} text-sm`}>
            You stopped this application.{' '}
            {app.reviews?.at(-1)?.feedback && <>Your note: “{app.reviews?.at(-1)?.feedback}”</>}
          </p>
        )}
        {gate === 'fit_review' && app.fit_report && (
          <FitReview report={app.fit_report} evidence={evidence} busy={busy} onDecide={decide} />
        )}
        {gate === 'content_review' && app.tailored && app.cover_letter && (
          <ContentReview
            key={app.reviews?.length ?? 0} // fresh editor state after a regeneration
            tailored={app.tailored}
            letter={app.cover_letter}
            evidence={evidence}
            busy={busy}
            onDecide={decide}
          />
        )}
        {app.status === 'completed' && app.tailored && app.cover_letter && (
          <ExportPanel
            tailored={app.tailored}
            letter={app.cover_letter}
            applyUrl={app.apply_url}
          />
        )}
      </div>
    </div>
  )
}

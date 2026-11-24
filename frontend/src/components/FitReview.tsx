import { useState } from 'react'
import type { FitReport, MatchOverride, ReviewDecision, Verdict } from '../api/client'
import { btnDanger, btnPrimary, btnSecondary, card, hint, input, verdictStyle } from './ui'

type Props = {
  report: FitReport
  evidence: Record<string, string>
  busy?: boolean
  onDecide: (decision: ReviewDecision) => void
}

type Draft = { verdict: Verdict; evidence_refs: string[]; note: string }

export function FitReview({ report, evidence, busy, onDecide }: Props) {
  const [feedback, setFeedback] = useState('')
  const [overrides, setOverrides] = useState<Record<string, Draft>>({})
  const editing = Object.keys(overrides).length > 0
  const complete = Object.values(overrides).every(
    (o) => o.note.trim() && (o.verdict === 'not_met' || o.evidence_refs.length > 0),
  )
  const fb = feedback.trim() || null

  function setOverride(id: string, patch: Partial<Draft> | null) {
    setOverrides(({ [id]: current, ...rest }) =>
      patch === null ? rest : { ...rest, [id]: { ...current, ...patch } as Draft },
    )
  }

  function submitEdits() {
    const match_overrides: MatchOverride[] = Object.entries(overrides).map(([id, o]) => ({
      requirement_id: id,
      verdict: o.verdict,
      evidence_refs: o.evidence_refs,
      note: o.note.trim(),
    }))
    onDecide({ action: 'edit', feedback: fb, match_overrides })
  }

  return (
    <section className={card} aria-labelledby="fit-title">
      <h2 id="fit-title" className="text-lg font-semibold">
        Review the fit analysis
      </h2>
      <dl className="mt-3 flex gap-6 text-sm">
        {[
          ['Overall', report.overall_score],
          ['Must-haves', report.must_have_score],
          ['Nice-to-haves', report.nice_to_have_score],
        ].map(([label, score]) => (
          <div key={label}>
            <dt className="text-slate-500">{label}</dt>
            <dd className="text-2xl font-semibold">{score ?? '–'}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-sm text-slate-700">{report.summary}</p>

      <ul className="mt-4 divide-y divide-slate-100">
        {report.matches.map((m) => {
          const o = overrides[m.requirement_id]
          return (
            <li key={m.requirement_id} className="py-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="mr-2 font-mono text-xs text-slate-400">{m.requirement_id}</span>
                  {m.requirement_text}
                  {m.importance === 'must' && (
                    <span className="ml-2 rounded bg-slate-100 px-1.5 text-xs">must</span>
                  )}
                </div>
                <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${verdictStyle[m.verdict]}`}>
                  {m.verdict.replace('_', ' ')}
                </span>
              </div>
              <p className="mt-1 text-slate-600">{m.rationale}</p>
              {m.evidence_refs.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
                  {m.evidence_refs.map((ref) => (
                    <li key={ref}>
                      <span className="font-mono">[{ref}]</span> {evidence[ref]}
                    </li>
                  ))}
                </ul>
              )}
              {!o ? (
                <button
                  type="button"
                  className="mt-2 text-xs text-indigo-700 hover:underline"
                  onClick={() =>
                    setOverride(m.requirement_id, {
                      verdict: m.verdict,
                      evidence_refs: m.evidence_refs,
                      note: '',
                    })
                  }
                >
                  Override verdict
                </button>
              ) : (
                <fieldset className="mt-2 space-y-2 rounded-lg bg-slate-50 p-3">
                  <legend className="sr-only">Override {m.requirement_id}</legend>
                  <label className="block text-xs font-medium">
                    Verdict
                    <select
                      className={`${input} mt-1`}
                      value={o.verdict}
                      onChange={(e) =>
                        setOverride(m.requirement_id, { verdict: e.target.value as Verdict })
                      }
                    >
                      <option value="met">met</option>
                      <option value="partial">partial</option>
                      <option value="not_met">not met</option>
                    </select>
                  </label>
                  <label className="block text-xs font-medium">
                    Evidence from your CV (met/partial need at least one)
                    <select
                      multiple
                      size={6}
                      className={`${input} mt-1`}
                      value={o.evidence_refs}
                      onChange={(e) =>
                        setOverride(m.requirement_id, {
                          evidence_refs: Array.from(e.target.selectedOptions, (opt) => opt.value),
                        })
                      }
                    >
                      {Object.entries(evidence).map(([id, text]) => (
                        <option key={id} value={id}>
                          [{id}] {text}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs font-medium">
                    Why (required)
                    <input
                      className={`${input} mt-1`}
                      value={o.note}
                      onChange={(e) => setOverride(m.requirement_id, { note: e.target.value })}
                    />
                  </label>
                  <button
                    type="button"
                    className="text-xs text-slate-600 hover:underline"
                    onClick={() => setOverride(m.requirement_id, null)}
                  >
                    Cancel override
                  </button>
                </fieldset>
              )}
            </li>
          )
        })}
      </ul>

      <label className="mt-4 block text-sm font-medium" htmlFor="fit-feedback">
        Feedback (optional)
      </label>
      <textarea
        id="fit-feedback"
        rows={2}
        className={`${input} mt-1`}
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
      />
      <div className="mt-4 flex flex-wrap gap-2">
        {editing ? (
          <button className={btnPrimary} disabled={busy || !complete} onClick={submitEdits}>
            Save overrides and continue
          </button>
        ) : (
          <button
            className={btnPrimary}
            disabled={busy}
            onClick={() => onDecide({ action: 'approve', feedback: fb })}
          >
            Approve and continue
          </button>
        )}
        <button
          className={btnDanger}
          disabled={busy}
          onClick={() => onDecide({ action: 'reject', feedback: fb })}
        >
          Reject: don't apply
        </button>
        {editing && (
          <button className={btnSecondary} disabled={busy} onClick={() => setOverrides({})}>
            Discard overrides
          </button>
        )}
      </div>
      {editing && !complete && (
        <p className={hint}>
          Each override needs a reason, and met/partial needs at least one CV item selected.
        </p>
      )}
    </section>
  )
}

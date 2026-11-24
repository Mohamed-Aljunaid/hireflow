import { diffWords } from 'diff'
import { useState } from 'react'
import type { CoverLetter, ReviewDecision, TailoredBullets, TextEdit } from '../api/client'
import { btnDanger, btnPrimary, btnSecondary, card, hint, input } from './ui'

type Props = {
  tailored: TailoredBullets
  letter: CoverLetter
  evidence: Record<string, string>
  busy?: boolean
  onDecide: (decision: ReviewDecision) => void
}

/** Word diff: what the tailored bullet changed relative to the CV text it cites. */
export function BulletDiff({ original, tailored }: { original: string; tailored: string }) {
  return (
    <p className="text-xs leading-relaxed" data-testid="bullet-diff">
      {diffWords(original, tailored).map((part, i) =>
        part.added ? (
          <ins key={i} className="bg-emerald-100 text-emerald-900 no-underline">
            {part.value}
          </ins>
        ) : part.removed ? (
          <del key={i} className="bg-red-100 text-red-800">
            {part.value}
          </del>
        ) : (
          <span key={i} className="text-slate-500">
            {part.value}
          </span>
        ),
      )}
    </p>
  )
}

export function ContentReview({ tailored, letter, evidence, busy, onDecide }: Props) {
  const original: Record<string, string> = Object.fromEntries([
    ...tailored.bullets.map((b) => [b.id, b.text]),
    ...letter.paragraphs.map((p) => [p.id, p.text]),
  ])
  const [text, setText] = useState(original)
  const [feedback, setFeedback] = useState('')
  const edits: TextEdit[] = Object.entries(text)
    .filter(([id, t]) => t.trim() !== original[id].trim())
    .map(([id, t]) => ({ id, text: t.trim() }))
  const emptyEdit = Object.values(text).some((t) => !t.trim())
  const fb = feedback.trim() || null
  const warnings = [...(tailored.warnings ?? []), ...(letter.warnings ?? [])]

  const editor = (id: string, label: string, rows: number) => (
    <textarea
      aria-label={label}
      rows={rows}
      className={`${input} ${text[id] !== original[id] ? 'border-indigo-400 bg-indigo-50' : ''}`}
      value={text[id]}
      onChange={(e) => setText({ ...text, [id]: e.target.value })}
    />
  )

  return (
    <section className={card} aria-labelledby="content-title">
      <h2 id="content-title" className="text-lg font-semibold">
        Review your tailored CV bullets and cover letter
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Every item below passed the claim check against your CV. Edits you make are kept as
        your own words.
      </p>
      {warnings.length > 0 && (
        <ul role="status" className="mt-3 space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <h3 className="mt-5 font-medium">CV bullets</h3>
      <ul className="mt-2 space-y-4">
        {tailored.bullets.map((b) => (
          <li key={b.id}>
            {editor(b.id, `Bullet ${b.id}`, 2)}
            <BulletDiff
              original={b.source_cv_refs.map((r) => evidence[r] ?? '').join(' ')}
              tailored={text[b.id]}
            />
            <p className="mt-0.5 font-mono text-xs text-slate-400">
              cites {b.source_cv_refs.join(', ')}
            </p>
          </li>
        ))}
      </ul>

      <h3 className="mt-6 font-medium">Cover letter</h3>
      <div className="mt-2 space-y-3 text-sm">
        <p>{letter.salutation}</p>
        {letter.paragraphs.map((p) => (
          <div key={p.id}>
            {editor(p.id, `Paragraph ${p.id}`, 4)}
            <p className="mt-0.5 font-mono text-xs text-slate-400">
              cites {[...(p.source_cv_refs ?? []), ...(p.company_fact_refs ?? [])].join(', ') || 'nothing'}
            </p>
          </div>
        ))}
        <p className="whitespace-pre-line">{letter.closing}</p>
      </div>

      <label className="mt-5 block text-sm font-medium" htmlFor="content-feedback">
        Feedback for a regeneration (optional)
      </label>
      <textarea
        id="content-feedback"
        rows={2}
        className={`${input} mt-1`}
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
      />

      <div className="mt-4 flex flex-wrap gap-2">
        {edits.length > 0 ? (
          <button
            className={btnPrimary}
            disabled={busy || emptyEdit}
            onClick={() => onDecide({ action: 'edit', feedback: fb, text_edits: edits })}
          >
            Save {edits.length} edit{edits.length > 1 ? 's' : ''} and finish
          </button>
        ) : (
          <button
            className={btnPrimary}
            disabled={busy}
            onClick={() => onDecide({ action: 'approve', feedback: fb })}
          >
            Approve
          </button>
        )}
        <button
          className={btnSecondary}
          disabled={busy || edits.length > 0}
          onClick={() => onDecide({ action: 'regenerate', feedback: fb })}
        >
          Regenerate
        </button>
        <button
          className={btnDanger}
          disabled={busy}
          onClick={() => onDecide({ action: 'reject', feedback: fb })}
        >
          Reject
        </button>
      </div>
      {emptyEdit && <p className={hint}>A bullet or paragraph is empty. Add text to save.</p>}
      {edits.length > 0 && <p className={hint}>To regenerate, undo your edits first.</p>}
    </section>
  )
}

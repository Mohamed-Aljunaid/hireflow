import { useRef, useState } from 'react'
import { api, type Application, type CV, type JobListing } from '../api/client'
import { JobSearch } from './JobSearch'
import { btnPrimary, card, hint, input } from './ui'

const MIN_CHARS = 50 // matches the API's validation

export function JobForm({ cv, onCreated }: { cv: CV; onCreated: (app: Application) => void }) {
  const [text, setText] = useState('')
  const [picked, setPicked] = useState<JobListing | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  const tooShort = text.trim().length < MIN_CHARS

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await api.createApplication(cv.id, text, picked?.apply_url))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  function pick(listing: JobListing) {
    setPicked(listing)
    setText(listing.posting_text)
    box.current?.focus()
  }

  return (
    <div className="space-y-4">
      <JobSearch onPick={pick} />
      <form onSubmit={submit} className={card}>
        <h2 className="text-lg font-semibold">3. Check or paste the job posting</h2>
        <p className="mt-1 text-sm text-slate-600">
          CV: <span className="font-medium">{cv.parsed.contact.name}</span> ({cv.filename})
        </p>
        {picked && (
          <p className="mt-2 text-sm text-slate-600">
            Applying to: <span className="font-medium">{picked.title}</span>, {picked.company} (
            <a className="underline" href={picked.source_url} target="_blank" rel="noopener">
              View on Himalayas
            </a>
            ){' '}
            <button
              type="button"
              className="text-indigo-700 hover:underline"
              onClick={() => {
                setPicked(null)
                setText('')
              }}
            >
              Clear
            </button>
          </p>
        )}
        <label className="mt-4 block text-sm font-medium" htmlFor="job-text">
          Job posting
        </label>
        <textarea
          id="job-text"
          ref={box}
          rows={12}
          className={`${input} mt-1 font-mono`}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            // Emptied to paste another posting: the old apply link no longer belongs to it.
            if (!e.target.value.trim()) setPicked(null)
          }}
          placeholder="Paste the full posting: title, company, requirements…"
        />
        {error && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {error}
          </p>
        )}
        <button type="submit" className={`${btnPrimary} mt-4`} disabled={tooShort || busy}>
          {busy ? 'Starting…' : 'Start pipeline'}
        </button>
        {tooShort && (
          <p className={hint}>
            Paste at least {MIN_CHARS} characters ({text.trim().length}/{MIN_CHARS}).
          </p>
        )}
      </form>
    </div>
  )
}

import { useState } from 'react'
import { api, type Application, type CV } from '../api/client'
import { btnPrimary, card, input } from './ui'

const MIN_CHARS = 50 // matches the API's validation

export function JobForm({ cv, onCreated }: { cv: CV; onCreated: (app: Application) => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tooShort = text.trim().length < MIN_CHARS

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await api.createApplication(cv.id, text))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className={card}>
      <h2 className="text-lg font-semibold">2. Paste the job posting</h2>
      <p className="mt-1 text-sm text-slate-600">
        CV: <span className="font-medium">{cv.parsed.contact.name}</span> ({cv.filename})
      </p>
      <label className="mt-4 block text-sm font-medium" htmlFor="job-text">
        Job posting
      </label>
      <textarea
        id="job-text"
        rows={12}
        className={`${input} mt-1 font-mono`}
        value={text}
        onChange={(e) => setText(e.target.value)}
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
    </form>
  )
}

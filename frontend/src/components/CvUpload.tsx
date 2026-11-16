import { useState } from 'react'
import { api, type CV } from '../api/client'
import { btnPrimary, card } from './ui'

export function CvUpload({ onUploaded }: { onUploaded: (cv: CV) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      onUploaded(await api.uploadCv(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className={card}>
      <h2 className="text-lg font-semibold">1. Upload your CV</h2>
      <p className="mt-1 text-sm text-slate-600">PDF, DOCX or TXT, up to 5 MB.</p>
      <label className="mt-4 block text-sm font-medium" htmlFor="cv-file">
        CV file
      </label>
      <input
        id="cv-file"
        type="file"
        accept=".pdf,.docx,.txt,.md"
        className="mt-1 block text-sm"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {error}
        </p>
      )}
      <button type="submit" className={`${btnPrimary} mt-4`} disabled={!file || busy}>
        {busy ? 'Parsing CV…' : 'Upload and parse'}
      </button>
    </form>
  )
}

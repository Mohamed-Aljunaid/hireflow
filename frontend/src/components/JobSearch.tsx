import { useState } from 'react'
import { api, type JobListing, type JobSearchResult } from '../api/client'
import { btnPrimary, btnSecondary, card, hint, input } from './ui'

const COUNTRIES = [
  ['SA', 'Saudi Arabia'],
  ['AE', 'United Arab Emirates'],
  ['QA', 'Qatar'],
  ['KW', 'Kuwait'],
  ['BH', 'Bahrain'],
  ['OM', 'Oman'],
  ['EG', 'Egypt'],
  ['JO', 'Jordan'],
] as const

export function JobSearch({ onPick }: { onPick: (listing: JobListing) => void }) {
  const [q, setQ] = useState('')
  const [country, setCountry] = useState('SA')
  const [result, setResult] = useState<JobSearchResult | null>(null)
  // What `result` was searched with, so paging ignores edits made since.
  const [searched, setSearched] = useState({ q: '', country: 'SA' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tooShort = q.trim().length < 2

  async function load(query: { q: string; country: string }, page: number) {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.searchJobs(query.q, query.country, page))
      setSearched(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    void load({ q: q.trim(), country }, 1)
  }

  const countryName = COUNTRIES.find(([code]) => code === searched.country)?.[1]
  const scopeLabel: Record<JobListing['location_scope'], string> = {
    country_only: `${countryName} only`,
    worldwide: 'Worldwide',
    multi_country: 'Several countries: check eligibility',
  }

  return (
    <section className={card} aria-labelledby="search-title">
      <h2 id="search-title" className="text-lg font-semibold">
        2. Find a remote job
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Or skip this and paste a posting below. Jobs from{' '}
        <a className="underline" href="https://himalayas.app" target="_blank" rel="noopener">
          Himalayas
        </a>
        .
      </p>
      <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="min-w-48 flex-1 text-sm font-medium">
          Job title or skill
          <input
            className={`${input} mt-1`}
            value={q}
            maxLength={100}
            onChange={(e) => setQ(e.target.value)}
            placeholder="agentic AI"
          />
        </label>
        <label className="text-sm font-medium">
          Open to people in
          <select
            className={`${input} mt-1`}
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          >
            {COUNTRIES.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className={btnPrimary} disabled={tooShort || busy}>
          {busy ? 'Searching…' : 'Search'}
        </button>
      </form>
      {tooShort && <p className={hint}>Type at least 2 characters to search.</p>}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {error}
        </p>
      )}

      {result && (
        <>
          <p role="status" className="mt-4 text-sm text-slate-600">
            {result.total === 0
              ? 'No jobs found. Try a broader search.'
              : `${result.total} jobs found, page ${result.page}`}
          </p>
          <ul className="mt-2 divide-y divide-slate-100">
            {result.listings.map((job) => (
              <li
                key={job.source_url}
                className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
              >
                <div>
                  <p className="font-medium">{job.title}</p>
                  <p className="text-slate-600">
                    {job.company}
                    {job.published_at && <> · {new Date(job.published_at).toLocaleDateString()}</>}
                  </p>
                  <p className="text-xs text-slate-500">
                    {scopeLabel[job.location_scope]} ·{' '}
                    <a className="underline" href={job.source_url} target="_blank" rel="noopener">
                      View on Himalayas
                    </a>
                  </p>
                </div>
                <button
                  className={btnSecondary}
                  aria-label={`Use this job: ${job.title}, ${job.company}`}
                  onClick={() => onPick(job)}
                >
                  Use this job
                </button>
              </li>
            ))}
          </ul>
          {(result.page > 1 || result.has_more) && (
            <div className="mt-3 flex gap-2">
              <button
                className={btnSecondary}
                disabled={busy || result.page === 1}
                onClick={() => load(searched, result.page - 1)}
              >
                Previous
              </button>
              <button
                className={btnSecondary}
                disabled={busy || !result.has_more}
                onClick={() => load(searched, result.page + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

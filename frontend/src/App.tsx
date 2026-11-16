import { useEffect, useState } from 'react'
import { api, type CV } from './api/client'
import { ApplicationView } from './components/ApplicationView'
import { CvUpload } from './components/CvUpload'
import { JobForm } from './components/JobForm'

// ?cv=<id>&app=<id> in the URL, so a refresh (or a shared link) resumes where you were.
function readParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name)
}

function writeParams(params: Record<string, string | null>) {
  const url = new URL(window.location.href)
  for (const [k, v] of Object.entries(params)) {
    if (v) url.searchParams.set(k, v)
    else url.searchParams.delete(k)
  }
  window.history.replaceState(null, '', url)
}

export default function App() {
  const [cv, setCv] = useState<CV | null>(null)
  const [cvId, setCvId] = useState(readParam('cv'))
  const [appId, setAppId] = useState(readParam('app'))

  useEffect(() => {
    if (cvId && !cv) api.getCv(cvId).then(setCv, () => setCvId(null))
  }, [cvId, cv])

  function startOver() {
    writeParams({ app: null })
    setAppId(null)
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 py-4">
          <h1 className="text-xl font-semibold">HireFlow</h1>
          <p className="text-sm text-slate-600">
            Tailor your CV and cover letter to a job, with every claim checked against your CV.
          </p>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        {appId ? (
          <ApplicationView appId={appId} onStartOver={startOver} />
        ) : cv ? (
          <div className="space-y-4">
            <JobForm
              cv={cv}
              onCreated={(app) => {
                writeParams({ app: app.id })
                setAppId(app.id)
              }}
            />
            <button
              className="text-sm text-slate-600 hover:underline"
              onClick={() => {
                writeParams({ cv: null })
                setCv(null)
                setCvId(null)
              }}
            >
              Use a different CV
            </button>
          </div>
        ) : cvId ? (
          <p className="text-sm text-slate-600">Loading CV…</p>
        ) : (
          <CvUpload
            onUploaded={(uploaded) => {
              writeParams({ cv: uploaded.id })
              setCvId(uploaded.id)
              setCv(uploaded)
            }}
          />
        )}
      </main>
    </div>
  )
}

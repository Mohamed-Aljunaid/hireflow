import { useState } from 'react'
import type { CoverLetter, TailoredBullets } from '../api/client'
import { exportText } from '../lib/exportText'
import { btnPrimary, btnSecondary, card } from './ui'

export function ExportPanel({ tailored, letter }: { tailored: TailoredBullets; letter: CoverLetter }) {
  const text = exportText(tailored, letter)
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: 'application.txt' })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className={card} aria-labelledby="export-title">
      <h2 id="export-title" className="text-lg font-semibold">
        Done: your application material
      </h2>
      <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-sm">
        {text}
      </pre>
      <div className="mt-4 flex gap-2">
        <button className={btnPrimary} onClick={copy}>
          {copied ? 'Copied' : 'Copy to clipboard'}
        </button>
        <button className={btnSecondary} onClick={download}>
          Download .txt
        </button>
      </div>
    </section>
  )
}

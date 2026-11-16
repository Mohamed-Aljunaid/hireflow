import { useCallback, useEffect, useState } from 'react'
import { api, type Application } from '../api/client'

/** Loads an application and polls it while the pipeline is running. */
export function useApplication(id: string, intervalMs = 1500) {
  const [app, setApp] = useState<Application | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const next = await api.getApplication(id)
        if (cancelled) return
        setApp(next)
        setError(null)
        if (next.status === 'running') timer = setTimeout(tick, intervalMs)
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
        timer = setTimeout(tick, intervalMs * 2) // keep trying: the API may be restarting
      }
    }
    void tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [id, intervalMs, generation])

  // After a resume: show the server's answer right away, then poll again.
  const update = useCallback((next: Application) => {
    setApp(next)
    setGeneration((g) => g + 1)
  }, [])

  return { app, error, update }
}

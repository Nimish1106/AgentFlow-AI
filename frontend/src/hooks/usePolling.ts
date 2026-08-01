/**
 * Polling data hook.
 *
 * The backend exposes no websocket or SSE channel, so the dashboard polls
 * (SRS Phase 7). Three behaviours matter for a console left open all day:
 *
 * - Polling pauses while the tab is hidden, and refetches immediately on
 *   return. A backgrounded dashboard should not keep hitting the API.
 * - In-flight requests are aborted when the effect re-runs or the component
 *   unmounts, so a slow response cannot overwrite newer state.
 * - A failed poll keeps the last good data on screen and surfaces the error
 *   alongside it. Blanking a populated table because one request failed is
 *   worse than showing slightly stale data with a warning.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export interface PollingState<T> {
  data: T | null
  error: string | null
  /** True only for the very first load, so tables can show a skeleton once. */
  loading: boolean
  /** True while any refetch is in flight, including background polls. */
  refreshing: boolean
  lastUpdated: Date | null
  refetch: () => void
}

export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  deps: readonly unknown[] = [],
): PollingState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  // Kept in a ref so changing the fetcher identity every render does not
  // restart the interval. Assigned in an effect, never during render:
  // mutating a ref while rendering is unsafe under concurrent rendering.
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  }, [fetcher])

  const mountedRef = useRef(true)
  const controllerRef = useRef<AbortController | null>(null)
  const [nonce, setNonce] = useState(0)

  const refetch = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    mountedRef.current = true

    const run = async () => {
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller

      setRefreshing(true)
      try {
        const result = await fetcherRef.current(controller.signal)
        if (!mountedRef.current || controller.signal.aborted) return
        setData(result)
        setError(null)
        setLastUpdated(new Date())
      } catch (err) {
        if (!mountedRef.current || controller.signal.aborted) return
        // An aborted fetch is a normal consequence of navigating; not an error.
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Request failed')
      } finally {
        if (mountedRef.current && !controller.signal.aborted) {
          setRefreshing(false)
          setLoading(false)
        }
      }
    }

    void run()
    let timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void run()
    }, intervalMs)

    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return
      // Catch up straight away, then restart the cadence from now.
      void run()
      window.clearInterval(timer)
      timer = window.setInterval(() => {
        if (document.visibilityState === 'visible') void run()
      }, intervalMs)
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      mountedRef.current = false
      controllerRef.current?.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, nonce, ...deps])

  return { data, error, loading, refreshing, lastUpdated, refetch }
}

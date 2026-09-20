import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'

/**
 * REST call wrapper hook (SRD 5.2: hooks/useApi.js). Fetches once on mount
 * (and whenever `deps` changes), exposes {data, error, loading, refetch}.
 * Every component reading REST data goes through this rather than calling
 * `api.*` directly in an effect, so loading/error handling is consistent.
 */
export function useApi(fetcher, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refetch = useCallback(() => {
    let cancelled = false
    setLoading(true)
    fetcherRef.current(api)
      .then((result) => {
        if (!cancelled) {
          setData(result)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => refetch(), [refetch])

  return { data, error, loading, refetch }
}

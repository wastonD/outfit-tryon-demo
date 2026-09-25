import { useEffect, useRef, useState, type DependencyList } from 'react'

// 通用轮询 hook：立即请求一次，只要 isDone(data) 还是 false 就每隔 intervalMs 再请求一次，
// 进入终态后自动停止。deps 变化（例如切换了 id）会重新开始轮询。
export function usePoll<T>(
  fetcher: () => Promise<T>,
  isDone: (data: T) => boolean,
  intervalMs = 2000,
  deps: DependencyList = [],
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const isDoneRef = useRef(isDone)
  isDoneRef.current = isDone

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const result = await fetcherRef.current()
        if (cancelled) return
        setData(result)
        setError(null)
        setLoading(false)
        if (!isDoneRef.current(result)) {
          timer = setTimeout(tick, intervalMs)
        }
      } catch (e) {
        if (cancelled) return
        setError(e)
        setLoading(false)
      }
    }

    setLoading(true)
    tick()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps])

  return { data, error, loading }
}

import { useEffect, useRef } from 'react'

/**
 * IntersectionObserver-based infinite scroll sentinel (phase 12b):
 * place a sentinel div at the end of the list; while it is visible and the
 * query has more pages, `loadMore` fires.
 */
export function useInfiniteScroll(
  sentinelRef: React.RefObject<HTMLElement | null>,
  hasMore: boolean,
  isLoading: boolean,
  loadMore: () => void,
): void {
  const busy = useRef(false)
  useEffect(() => {
    const element = sentinelRef.current
    if (!element || !hasMore) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !busy.current) {
          busy.current = true
          loadMore()
        }
      },
      { rootMargin: '400px 0px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [sentinelRef, hasMore, loadMore])

  // Release the guard once the fetch triggered by the observer finished.
  useEffect(() => {
    if (!isLoading) busy.current = false
  }, [isLoading])
}

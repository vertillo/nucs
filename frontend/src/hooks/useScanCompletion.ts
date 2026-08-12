import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useScanStatus } from '../api/settings'
import type { ScanStatus } from '../api/settings'

type ScanType = NonNullable<ScanStatus['running']>['type']

/**
 * Central scan-completion invalidation (spec 6.8, phase 6).
 *
 * Watches the shared `['scan-status']` query (same cache entry ActivityBar,
 * Feed and Settings already subscribe to — react-query dedupes, so this hook
 * adds no polling) and fires exactly once when a previously-running scan is
 * observed finished: running → idle, or running(A) → running(B) when two
 * scans start back-to-back inside one 3s poll window (scan A still completed;
 * scan B's own completion fires when B later goes idle).
 *
 * This fixes "Feed displays 1 release until page refresh, then displays 19"
 * (spec:1389): discovery commits new releases while the Feed's cached
 * `['releases']` pages sat stale because nothing invalidated them on
 * completion. Invalidation happens ONCE at the transition (spec:1393) — never
 * by polling the Feed (spec:1391).
 *
 * Invalidated families (spec:1371-1385):
 * - releases/feat completion → `releases` (+ every `['releases', filters]`
 *   page), `release` (every open detail), `releases-count`, `scan-status`,
 *   `errors`.
 * - library completion → `artists` (+ filtered variants), `artists-count`,
 *   `scan-status`, `errors`.
 * - an unknown future scan type invalidates both families (safe default).
 *
 * Cancelled runs invalidate too (Metis G4): the registry clears `running`
 * identically for ok / error / cancelled, and a cancelled run may leave
 * partial committed work (spec:1261 preserves already-committed releases) that
 * must surface without a manual refresh.
 *
 * M1 date-transition staleness (Oracle M1) — accepted behavior, documented:
 * the releases API computes view membership (released vs upcoming) from dates
 * on every request, so the API is always correct; only the client cache can go
 * stale at a no-scan midnight boundary. With `refetchOnWindowFocus: false`
 * (main.tsx) that staleness surfaces at the next scan-completion invalidation
 * or the next Feed mount, and the daily 04:00 releases scan is the guaranteed
 * refresh. No polling is added for this. API-side correctness is locked by
 * the deterministic injectable-date backend tests (today_override seam —
 * `test_api_release_detail_favorite_hidden_survive_date_transition` and the
 * released/upcoming view tests); the frontend has no unit-test framework by
 * convention, so the gate here is the build plus this documented contract.
 */
export function useScanCompletion() {
  const queryClient = useQueryClient()
  const { data } = useScanStatus()
  const prevTypeRef = useRef<ScanType | null>(null)

  useEffect(() => {
    const prevType = prevTypeRef.current
    const currentType = data?.running?.type ?? null
    prevTypeRef.current = currentType

    // Only a previously-observed run ending counts: idle→running and
    // still-running polls must not invalidate (that would be polling-in-
    // disguise). StrictMode double-effects re-read the updated ref, so the
    // invalidation still fires exactly once per transition.
    if (prevType === null || prevType === currentType) return

    queryClient.invalidateQueries({ queryKey: ['scan-status'] })
    queryClient.invalidateQueries({ queryKey: ['errors'] })

    if (prevType === 'releases' || prevType === 'feat') {
      queryClient.invalidateQueries({ queryKey: ['releases'] })
      queryClient.invalidateQueries({ queryKey: ['release'] })
      queryClient.invalidateQueries({ queryKey: ['releases-count'] })
    } else if (prevType === 'library') {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    } else {
      // Unknown future scan type: refresh both families rather than nothing.
      queryClient.invalidateQueries({ queryKey: ['releases'] })
      queryClient.invalidateQueries({ queryKey: ['release'] })
      queryClient.invalidateQueries({ queryKey: ['releases-count'] })
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    }
  }, [data, queryClient])
}

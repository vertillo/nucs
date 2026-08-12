import { useCancelScan, useScanStatus } from '../api/settings'
import { ApiError } from '../api/client'
import Toast, { useToast } from './Toast'

const PHASE_LABEL: Record<string, string> = {
  starting: 'Starting…',
  'library scan': 'Scanning library…',
  scanning: 'Scanning library…',
  cleanup: 'Cleaning up…',
  'matching artists': 'Matching artists…',
  'level 1': 'Checking releases…',
  'level 2': 'Checking featuring…',
  'enriching covers and links': 'Fetching covers and links…',
}

/**
 * Global background-activity bar (phase 12b): polls /scans/status every 3s
 * only while a scan is running and shows the phase + a progress bar on every
 * page. Rendered by App below the navbar.
 *
 * Spec 6.5: a Cancel button appears while a cancellable scan runs. Clicking it
 * flips the button to a disabled `Cancelling…` state (driven by the mutation
 * plus the polled `cancel_requested` flag, so duplicate requests are
 * impossible) and the bar stays visible until the backend reports the job
 * finished/cancelled (running == null).
 */
export default function ActivityBar() {
  const status = useScanStatus()
  const cancelScan = useCancelScan()
  const { toast, show } = useToast()
  const running = status.data?.running ?? null

  if (!running) return <Toast toast={toast} />

  const { total, done, phase } = running.progress
  const determinate = total > 0
  const percent = determinate ? Math.min(100, Math.round((done / total) * 100)) : null
  const label = PHASE_LABEL[phase] ?? `${phase}…`
  const cancelling = cancelScan.isPending || running.cancel_requested

  const onCancel = () => {
    cancelScan.mutate(running.type, {
      onError: (error) =>
        show(error instanceof ApiError ? error.message : 'Could not cancel the scan', 'error'),
    })
  }

  return (
    <>
      <div
        role="status"
        aria-live="polite"
        className="border-b border-light-border bg-light-surface dark:border-dark-border dark:bg-dark-surface"
      >
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-1.5 text-xs text-light-textDim dark:text-dark-textDim">
          <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-light-border border-t-accent dark:border-dark-border dark:border-t-accent" />
          <span className="shrink-0 font-medium text-light-text dark:text-dark-text">{label}</span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-light-surface2 dark:bg-dark-surface2">
            {determinate ? (
              <div
                className="h-full rounded-full bg-accent transition-all"
                style={{ width: `${percent}%` }}
              />
            ) : (
              <div className="h-full w-full animate-pulse rounded-full bg-accent/50" />
            )}
          </div>
          {percent !== null && <span className="shrink-0 tabular-nums">{percent}%</span>}
          {running.cancellable && (
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling}
              className="shrink-0 rounded-full border border-danger px-2.5 py-0.5 text-xs font-medium text-dangerText transition-colors hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50 dark:text-danger"
            >
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
        </div>
      </div>
      <Toast toast={toast} />
    </>
  )
}

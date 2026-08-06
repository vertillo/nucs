import { useScanStatus } from '../api/settings'

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
 */
export default function ActivityBar() {
  const status = useScanStatus()
  const running = status.data?.running ?? null

  if (!running) return null

  const { total, done, phase } = running.progress
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null
  const label = PHASE_LABEL[phase] ?? `${phase}…`

  return (
    <div
      role="status"
      aria-live="polite"
      className="border-b border-light-border bg-light-surface dark:border-dark-border dark:bg-dark-surface"
    >
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-1.5 text-xs text-light-textDim dark:text-dark-textDim">
        <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-light-border border-t-accent dark:border-dark-border dark:border-t-accent" />
        <span className="shrink-0 font-medium text-light-text dark:text-dark-text">{label}</span>
        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-light-surface2 dark:bg-dark-surface2">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${percent ?? 8}%` }}
          />
        </div>
        {percent !== null && <span className="shrink-0 tabular-nums">{percent}%</span>}
      </div>
    </div>
  )
}

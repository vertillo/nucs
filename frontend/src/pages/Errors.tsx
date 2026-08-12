import { useState } from 'react'

import {
  useClearErrors,
  useDiagnosticReport,
  useErrors,
  useMarkAllErrorsRead,
  useMarkErrorRead,
  useMarkErrorUnread,
  type AppErrorItem,
} from '../api/errors'
import Toast, { useToast } from '../components/Toast'

type ErrorFilter = 'unread' | 'all'

const FILTER_TABS: { value: ErrorFilter; label: string }[] = [
  { value: 'unread', label: 'Unread' },
  { value: 'all', label: 'All' },
]

function formatTs(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
}

function exportPayload(items: AppErrorItem[]): string {
  return JSON.stringify(
    {
      app: 'nucs',
      exported_at: new Date().toISOString(),
      count: items.length,
      errors: items.map(({ id, ts, source, level, message, stack, context }) => ({
        id,
        ts,
        source,
        level,
        message,
        stack,
        context,
      })),
    },
    null,
    2,
  )
}

export default function Errors() {
  const { data, isPending, isError, refetch } = useErrors()
  const clear = useClearErrors()
  const markRead = useMarkErrorRead()
  const markUnread = useMarkErrorUnread()
  const markAllRead = useMarkAllErrorsRead()
  const diagnosticReport = useDiagnosticReport()
  const { toast, show } = useToast()
  const [filter, setFilter] = useState<ErrorFilter>('unread')
  const [openIds, setOpenIds] = useState<Set<number>>(new Set())
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [copied, setCopied] = useState(false)
  const [copiedDiag, setCopiedDiag] = useState(false)

  const all = data?.items ?? []
  const total = data?.total ?? 0
  const unreadTotal = data?.unread_total ?? 0
  const items = filter === 'unread' ? all.filter((error) => !error.read) : all

  function toggle(id: number) {
    setOpenIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    const allSelected = items.length > 0 && selectedIds.size === items.length
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(items.map((e) => e.id)))
    }
  }

  async function copyDiagnosticReport() {
    try {
      const ids = [...selectedIds]
      const markdown = await diagnosticReport.mutateAsync(ids)
      await navigator.clipboard.writeText(markdown)
      setCopiedDiag(true)
      setTimeout(() => setCopiedDiag(false), 2000)
    } catch {
      show('Copy diagnostic report failed', 'error')
    }
  }

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(exportPayload(items))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      show('Copy failed — use the download button', 'error')
    }
  }

  function downloadAll() {
    const blob = new Blob([exportPayload(items)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `nucs-errors-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function handleMarkAllRead() {
    markAllRead.mutate(undefined, {
      onSuccess: () => show('All errors marked as read'),
      onError: (error) => show(error.message, 'error'),
    })
  }

  function handleToggleRead(error: AppErrorItem) {
    const mutation = error.read ? markUnread : markRead
    mutation.mutate(error.id, {
      onError: (err) => show(err.message, 'error'),
    })
  }

  function handleClear() {
    if (!window.confirm(`Delete all ${total} recorded errors? This cannot be undone.`)) return
    clear.mutate(undefined, {
      onSuccess: () => show('Errors cleared'),
      onError: (error) => show(error.message, 'error'),
    })
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">
          Errors {total > 0 && <span className="text-lg text-light-textDim dark:text-dark-textDim">({total})</span>}
        </h1>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleMarkAllRead}
            disabled={markAllRead.isPending || unreadTotal === 0}
            className="rounded-full bg-light-surface2 px-4 py-1.5 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            {markAllRead.isPending ? 'Marking…' : 'Mark all as read'}
          </button>
          <button
            type="button"
            onClick={copyDiagnosticReport}
            disabled={diagnosticReport.isPending || items.length === 0}
            className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          >
            {diagnosticReport.isPending ? 'Generating…' : copiedDiag ? 'Copied ✓' : 'Copy diagnostic report'}
          </button>
          <button
            type="button"
            onClick={copyAll}
            disabled={items.length === 0}
            className="rounded-full bg-light-surface2 px-4 py-1.5 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            {copied ? 'Copied ✓' : 'Copy JSON'}
          </button>
          <button
            type="button"
            onClick={downloadAll}
            disabled={items.length === 0}
            className="rounded-full bg-light-surface2 px-4 py-1.5 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            Download .json
          </button>
          <button
            type="button"
            onClick={handleClear}
            disabled={clear.isPending || total === 0}
            className="rounded-full border border-danger px-4 py-1.5 text-sm font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
          >
            {clear.isPending ? 'Clearing…' : 'Clear all'}
          </button>
        </div>
      </div>

      <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
        These are the background failures (scans, providers, matching) and client-side errors. Marking read only
        clears the badge — errors stay until Clear all. Use Copy JSON or Download to report them.
      </p>

      <div
        role="tablist"
        aria-label="Error filter"
        className="mt-4 inline-flex rounded-full bg-light-surface2 p-1 dark:bg-dark-surface2"
      >
        {FILTER_TABS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={filter === value}
            onClick={() => setFilter(value)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              filter === value
                ? 'bg-accent text-black'
                : 'text-light-textDim hover:text-light-text dark:text-dark-textDim dark:hover:text-dark-text'
            }`}
          >
            {label} ({value === 'unread' ? unreadTotal : total})
          </button>
        ))}
      </div>

      {isPending && <p className="mt-8 text-light-textDim dark:text-dark-textDim">Loading…</p>}

      {isError && (
        <div className="mt-8 flex flex-col items-center gap-3 text-center">
          <p className="text-light-textDim dark:text-dark-textDim">Something went wrong loading errors.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Retry
          </button>
        </div>
      )}

      {!isPending && !isError && items.length === 0 && (
        <p className="mt-16 text-center text-light-textDim dark:text-dark-textDim">
          {filter === 'unread' && total > 0 ? 'No unread errors.' : 'No errors recorded.'}
        </p>
      )}

      {!isPending && !isError && items.length > 0 && (
        <>
          <div className="mt-3 flex items-center gap-2">
            <input
              type="checkbox"
              id="select-all-errors"
              checked={selectedIds.size === items.length && items.length > 0}
              onChange={toggleSelectAll}
              className="h-4 w-4 rounded border-light-border text-accent focus:ring-accent dark:border-dark-border"
            />
            <label htmlFor="select-all-errors" className="text-xs text-light-textDim dark:text-dark-textDim">
              {selectedIds.size > 0 ? `${selectedIds.size} selected` : 'Select all visible'}
            </label>
          </div>
          <ul className="mt-2 space-y-2">
            {items.map((error) => {
              const open = openIds.has(error.id)
              const selected = selectedIds.has(error.id)
              return (
                <li
                  key={error.id}
                  className="overflow-hidden rounded-2xl bg-light-surface dark:bg-dark-surface"
                >
                  <div className="flex items-start gap-2 px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleSelect(error.id)}
                      aria-label={`Select error ${error.id}`}
                      className="mt-1.5 h-4 w-4 shrink-0 rounded border-light-border text-accent focus:ring-accent dark:border-dark-border"
                    />
                    <button
                      type="button"
                      onClick={() => toggle(error.id)}
                      aria-expanded={open}
                      className="flex min-w-0 flex-1 items-start justify-between gap-4 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <span className="flex min-w-0 items-start gap-2">
                        {!error.read && (
                          <span
                            aria-label="Unread"
                            className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent shadow-sm shadow-black/30"
                          />
                        )}
                        <span className="min-w-0">
                          <span className="block text-sm font-medium text-light-text dark:text-dark-text">
                            {error.message}
                          </span>
                          <span className="mt-0.5 block text-xs text-light-textDim dark:text-dark-textDim">
                            {formatTs(error.ts)} · {error.source} · {error.level}
                          </span>
                        </span>
                      </span>
                      <span className="shrink-0 text-sm text-light-textDim dark:text-dark-textDim">
                        {open ? '▾' : '▸'}
                      </span>
                    </button>
                  </div>
                  {open && (
                    <div className="space-y-2 border-t border-light-border px-4 py-3 dark:border-dark-border">
                      {error.stack && (
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-light-bg p-3 text-xs text-light-text dark:bg-dark-bg dark:text-dark-text">
                          {error.stack}
                        </pre>
                      )}
                      {error.context != null && (
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-light-bg p-3 text-xs text-light-text dark:bg-dark-bg dark:text-dark-text">
                          {typeof error.context === 'string' ? error.context : JSON.stringify(error.context, null, 2)}
                        </pre>
                      )}
                      {!error.stack && error.context == null && (
                        <p className="text-xs text-light-textDim dark:text-dark-textDim">
                          No stack or context recorded.
                        </p>
                      )}
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={() => handleToggleRead(error)}
                          disabled={markRead.isPending || markUnread.isPending}
                          className="rounded-full bg-light-surface2 px-3 py-1 text-xs font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
                        >
                          {error.read ? 'Mark unread' : 'Mark read'}
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}

      <Toast toast={toast} />
    </div>
  )
}

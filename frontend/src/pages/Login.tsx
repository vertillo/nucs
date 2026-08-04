import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

const INVALID_CREDENTIALS = 'Invalid credentials'
const GENERIC_ERROR = 'Something went wrong. Try again.'

export default function Login() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ username, password }),
      })
      if (response.status === 204) {
        await queryClient.invalidateQueries({ queryKey: ['me'] })
        navigate('/', { replace: true })
        return
      }
      setError(response.status === 401 ? INVALID_CREDENTIALS : GENERIC_ERROR)
    } catch {
      setError(GENERIC_ERROR)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-light-bg px-4 dark:bg-dark-bg">
      <div className="w-full max-w-sm rounded-2xl bg-light-surface p-8 shadow-lg shadow-black/5 dark:bg-dark-surface dark:shadow-black/40">
        <div className="mb-6 text-center">
          <div className="text-4xl">🎵</div>
          <h1 className="mt-2 text-2xl font-bold text-light-text dark:text-dark-text">nucs</h1>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="username"
              className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
            >
              Username
            </label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-xl border border-light-border bg-light-bg px-3 py-2 text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-bg dark:text-dark-text"
            />
          </div>
          <div>
            <label
              htmlFor="password"
              className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
            >
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-light-border bg-light-bg px-3 py-2 text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-bg dark:text-dark-text"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-full bg-accent px-4 py-2 font-semibold text-white transition-colors hover:bg-accentHover active:bg-accentActive disabled:opacity-50"
          >
            Log in
          </button>
        </form>
      </div>
    </div>
  )
}

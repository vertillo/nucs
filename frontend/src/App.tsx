import { useEffect } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { get } from './api/client'
import { applyTheme, getStoredTheme } from './theme'

import Navbar from './components/Navbar'
import Login from './pages/Login'
import Feed from './pages/Feed'
import ReleaseDetail from './pages/ReleaseDetail'
import Artists from './pages/Artists'
import Settings from './pages/Settings'

interface Me {
  username: string
  theme: 'dark' | 'light'
}

function useMe() {
  return useQuery<Me>({
    queryKey: ['me'],
    queryFn: () => get<Me>('/api/v1/auth/me'),
  })
}

function RequireAuth() {
  const { data, isPending, isError } = useMe()

  useEffect(() => {
    if (data && data.theme !== getStoredTheme()) {
      applyTheme(data.theme)
    }
  }, [data])

  if (isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-light-bg dark:bg-dark-bg">
        <div
          aria-label="Loading"
          className="h-10 w-10 animate-spin rounded-full border-4 border-light-border border-t-accent dark:border-dark-border dark:border-t-accent"
        />
      </div>
    )
  }

  if (isError) {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      <Navbar username={data.username} theme={data.theme} />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Feed />} />
        <Route path="/releases/:id" element={<ReleaseDetail />} />
        <Route path="/artists" element={<Artists />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

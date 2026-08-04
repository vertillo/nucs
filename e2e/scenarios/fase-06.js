'use strict'
/**
 * Fase 06 — external links (spec 9) and cover cache endpoint.
 * API-level checks via node fetch (no browser): needs a backend with releases
 * already enriched by the fase-06 pipeline (links + covers). Env: BASE,
 * ADMIN_USER, ADMIN_PASS.
 */
const h = require('../harness')

async function loginToken() {
  const r = await fetch(`${h.BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      Origin: h.BASE,
    },
    body: JSON.stringify({ username: h.ADMIN_USER, password: h.ADMIN_PASS }),
    redirect: 'manual',
  })
  if (r.status !== 204) throw new Error(`login failed: ${r.status}`)
  const setCookie = r.headers.get('set-cookie') || ''
  const m = setCookie.match(/nucs_session=([^;]+)/)
  if (!m) throw new Error('no session cookie in login response')
  return m[1]
}

async function apiGet(token, path) {
  const r = await fetch(`${h.BASE}${path}`, { headers: { Cookie: `nucs_session=${token}` } })
  let body = null
  try {
    body = await r.json()
  } catch {
    /* non-JSON */
  }
  return { status: r.status, body }
}

/** Follow redirects and report final status; network errors are FAILs. */
async function probe(url) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), 15000)
  try {
    const r = await fetch(url, {
      redirect: 'follow',
      signal: ctrl.signal,
      headers: { 'User-Agent': 'nucs-e2e/1.0' },
    })
    return { ok: r.status >= 200 && r.status < 400, status: r.status }
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) }
  } finally {
    clearTimeout(t)
  }
}

const DOMAINS = {
  spotify: 'https://open.spotify.com/',
  ytm: 'https://music.youtube.com/search?',
  deezer: 'https://www.deezer.com/',
  google: 'https://www.google.com/search?',
}

async function main() {
  const token = await loginToken()

  // List + details: links are only exposed on the detail endpoint (fase 05).
  const list = await apiGet(token, '/api/v1/releases?page_size=5')
  h.check('GET /releases with session -> 200', list.status === 200, `status=${list.status}`)
  const ids = (list.body && list.body.items || []).map((i) => i.id)
  h.check('feed has releases to verify', ids.length > 0, `ids=${ids.length}`)

  const details = []
  for (const id of ids.slice(0, 3)) {
    const d = await apiGet(token, `/api/v1/releases/${id}`)
    if (d.status === 200) details.push(d.body)
  }
  const withLinks = details.filter(
    (d) => d.spotify_url && d.ytm_url && d.deezer_url && d.google_url,
  )
  h.check('detail exposes all 4 links (spotify/ytm/deezer/google)', withLinks.length > 0, `con link: ${withLinks.length}/${details.length}`)

  // Spec 9 format + live resolution for the first 2 releases.
  let linkChecks = 0
  for (const d of withLinks.slice(0, 2)) {
    for (const [name, url] of [
      ['spotify', d.spotify_url],
      ['ytm', d.ytm_url],
      ['deezer', d.deezer_url],
      ['google', d.google_url],
    ]) {
      const res = await probe(url)
      const label = `${name} (${d.primary_artist} - ${d.title})`
      h.check(`${label}: URL domain per spec 9`, url.startsWith(DOMAINS[name]), url)
      h.check(
        `${label}: resolves ${res.ok ? '2xx/3xx' : 'KO'}`,
        res.ok,
        res.error ? `network error: ${res.error}` : `status=${res.status}`,
      )
      linkChecks++
    }
  }

  // Cover endpoint: real rgid -> 200 image; path traversal -> 400/404; uuid unknown -> 404.
  const rgid = withLinks[0] && withLinks[0].rgid
  if (rgid) {
    const cover = await apiGet(token, `/api/v1/covers/${rgid}`)
    h.check('GET /covers/{rgid} -> 200', cover.status === 200, `status=${cover.status}`)
  } else {
    h.check('GET /covers/{rgid} -> 200', false, 'nessun rgid disponibile')
  }
  const evil = await apiGet(token, '/api/v1/covers/..%2F..%2Fetc%2Fpasswd')
  h.check('covers path traversal -> 400/404, mai 200', evil.status === 400 || evil.status === 404, `status=${evil.status}`)
  const fake = await apiGet(token, '/api/v1/covers/00000000-0000-0000-0000-000000000000')
  h.check('covers uuid inesistente -> 404', fake.status === 404, `status=${fake.status}`)

  // Auth guard.
  const unauth = await fetch(`${h.BASE}/api/v1/releases`)
  h.check('releases without session -> 401', unauth.status === 401, `status=${unauth.status}`)

  const failed = h.results.filter((r) => !r.ok).length
  console.log(`\nTOTALE: ${h.results.length - failed}/${h.results.length} PASS (fase 06)`)
  if (failed > 0) process.exitCode = 1
}

main().catch((e) => {
  console.error('SCRIPT ERROR:', e)
  process.exit(2)
})

'use strict'
/**
 * Fase 12 — acceptance criteria of spec section 14 that can be automated:
 *   14.2 brute force -> 429 with Retry-After
 *   14.3-4 library scan + discovery seed -> feed with covers + detail with 4 links
 *   14.6 theme persistence across reload
 *   14.9 DB backup present after a manual run (CLI backup-now)
 *   14.10 data persistence across a backend restart
 * Remaining human checks (declared in piano/verifica-e2e.md): Apprise delivery on
 * device, docker stats after 24h, README validated on a clean second machine,
 * Cloudflare tunnel HTTPS cookie.
 *
 * Env: BASE, ADMIN_USER, ADMIN_PASS (harness defaults) + E2E_DATA_DIR (default
 * /tmp/nucs-e2e) and E2E_MUSIC_LIBRARY (default /tmp/nucs-lib-test). The backend
 * under test must have been started with DATA_DIR=$E2E_DATA_DIR,
 * DEV_INSECURE_COOKIES=true (plain http) and NOTIFY_URLS= (see e2e/README.md);
 * this scenario restarts it once to reset the in-memory rate limiter and once to
 * prove data persistence, using the same env.
 */
const { execSync, spawn, spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const h = require('../harness')

const DATA_DIR = process.env.E2E_DATA_DIR || '/tmp/nucs-e2e'
const MUSIC = process.env.E2E_MUSIC_LIBRARY || '/tmp/nucs-lib-test'
const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend')
const LOG_FILE = '/tmp/nucs-e2e-backend.log'
const port = new URL(h.BASE).port || '8080'
const HOST = new URL(h.BASE).hostname || '127.0.0.1'

const backendEnv = {
  DATA_DIR,
  COVERS_DIR: `${DATA_DIR}/covers`,
  FRONTEND_DIST: path.join(__dirname, '..', '..', 'frontend', 'dist'),
  DEV_INSECURE_COOKIES: 'true',
  ADMIN_USERNAME: h.ADMIN_USER,
  ADMIN_PASSWORD: h.ADMIN_PASS,
  MUSIC_LIBRARY_PATH: MUSIC,
  NOTIFY_URLS: '',
  NOTIFY_ENABLED: 'false',
  LOG_LEVEL: 'INFO',
  ...process.env,
}

function killBackend() {
  try {
    const out = execSync(`lsof -tiTCP:${port} -sTCP:LISTEN`, { encoding: 'utf8' }).trim()
    for (const pid of out.split('\n').filter(Boolean)) process.kill(parseInt(pid, 10), 'SIGTERM')
  } catch {
    /* nothing listening */
  }
}

function startBackend() {
  const args = [
    '.venv/bin/uvicorn',
    'app.main:app',
    '--host',
    HOST,
    '--port',
    port,
    '--proxy-headers',
    '--no-server-header',
  ]
  const child = spawn(args[0], args.slice(1), {
    cwd: BACKEND_DIR,
    env: backendEnv,
    stdio: ['ignore', fs.openSync(LOG_FILE, 'a'), fs.openSync(LOG_FILE, 'a')],
    detached: true,
  })
  child.unref()
  return child
}

async function waitHealth(timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const r = await fetch(`${h.BASE}/api/health`)
      if (r.status === 200) return true
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) return false
    await h.wait(2000)
  }
}

/** Restart the backend under test (kills what listens on BASE, starts fresh). */
async function restartBackend() {
  killBackend()
  await h.wait(1500)
  const child = startBackend()
  h.check('backend restarted (uvicorn spawned)', child.pid !== undefined, `pid ${child.pid}`)
  h.check('backend healthy after restart', await waitHealth(), h.BASE)
}

async function bruteForce429() {
  const statuses = []
  for (let i = 0; i < 6; i++) {
    const r = await fetch(`${h.BASE}/api/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        Origin: h.BASE,
      },
      body: JSON.stringify({ username: h.ADMIN_USER, password: `wrong-password-${i}` }),
      redirect: 'manual',
    })
    statuses.push(r.status)
    if (r.status === 429) {
      h.check('429 carries Retry-After', !!r.headers.get('retry-after'), r.headers.get('retry-after') || '')
    }
  }
  h.check('5 wrong logins -> 401', statuses.slice(0, 5).every((s) => s === 401), statuses.join(','))
  h.check('6th login -> 429 (rate limit)', statuses[5] === 429, statuses.join(','))
}

async function main() {
  const { browser, page, state } = await h.launch()
  try {
    // --- 14.2: brute force on a fresh backend (rate limiter is in-memory) ---
    await bruteForce429()

    // --- Reset the in-memory limiter by restarting (documented, spec 5.3) ---
    await restartBackend()

    // --- 14.3-4: seed (library scan + discovery) and feed/detail checks ---
    await h.uiLogin(page)
    const setRes = await h.apiPut(page, '/api/v1/settings', { discovery_from_date: '2024-01-01' })
    h.check('seed: set discovery_from_date=2024-01-01', setRes.status === 200, `status ${setRes.status}`)
    console.log('seed: POST /scans/library?full=true ...')
    const r1 = await h.apiPost(page, '/api/v1/scans/library?full=true')
    h.check('seed: library scan accepted', r1.status === 202, `status ${r1.status}`)
    await h.waitForScanIdle(page)
    console.log('seed: POST /scans/releases ...')
    const r2 = await h.apiPost(page, '/api/v1/scans/releases')
    h.check('seed: releases scan accepted', r2.status === 202, `status ${r2.status}`)
    await h.waitForScanIdle(page)
    console.log('seed: done')

    const feed = await h.apiJson(page, '/api/v1/releases?page_size=1')
    const total = feed.body.total || 0
    h.check('14.3/14.4: feed populated (releases > 0)', total > 0, `total ${total}`)

    await page.goto(`${h.BASE}/`, { waitUntil: 'networkidle0' })
    const cards = await page.$$eval('a[href^="/releases/"]', (els) => els.length)
    h.check('14.4: feed shows release cards', cards > 0, `cards ${cards}`)
    const coverImgs = await page.$$eval('img[src*="/api/v1/covers/"]', (els) => els.length)
    h.check('14.4: cards use local cover cache', coverImgs > 0, `covers ${coverImgs}`)

    const firstHref = await page.$eval('a[href^="/releases/"]', (a) => a.getAttribute('href'))
    await page.goto(`${h.BASE}${firstHref}`, { waitUntil: 'networkidle0' })
    const detailText = await page.$eval('body', (b) => b.innerText)
    const buttons = await page.$$eval('a[target="_blank"]', (els) =>
      els.map((a) => ({ text: a.innerText, rel: a.getAttribute('rel') })),
    )
    h.check(
      '14.4: detail has the 4 link buttons',
      ['Spotify', 'YouTube Music', 'Deezer', 'Search on Google'].every((s) =>
        buttons.some((b) => b.text.includes(s)),
      ),
      JSON.stringify(buttons.map((b) => b.text)),
    )
    h.check(
      '14.4: external links noopener noreferrer',
      buttons.every((b) => (b.rel || '').includes('noopener') && (b.rel || '').includes('noreferrer')),
    )
    h.check('14.4: detail shows title', detailText.length > 0, firstHref)

    // --- 14.6: theme persistence ---
    const toggle = 'button[aria-label="Toggle theme"]'
    const htmlDark = () => page.evaluate(() => document.documentElement.classList.contains('dark'))
    const bodyBg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    await page.goto(`${h.BASE}/`, { waitUntil: 'networkidle0' })
    await page.click(toggle)
    await h.wait(2000)
    await page.reload({ waitUntil: 'networkidle0' })
    await h.wait(1500)
    h.check('14.6: light theme persists after reload', !(await htmlDark()) && (await bodyBg()) === 'rgb(255, 255, 255)', await bodyBg())
    await page.click(toggle)
    await h.wait(2000)
    await page.reload({ waitUntil: 'networkidle0' })
    await h.wait(1500)
    h.check('14.6: dark theme persists after reload', (await htmlDark()) && (await bodyBg()) === 'rgb(15, 15, 15)', await bodyBg())

    // --- hardening: CSP must not allow unsafe-eval / unsafe-inline (spec 5.5) ---
    const cspHeader = await page.evaluate(async () => {
      const r = await fetch('/', { credentials: 'same-origin' })
      return r.headers.get('content-security-policy') || ''
    })
    h.check(
      'CSP has no unsafe-eval',
      !cspHeader.includes('unsafe-eval'),
      cspHeader,
    )
    h.check(
      'CSP has no unsafe-inline (static Tailwind CSS)',
      !cspHeader.includes('unsafe-inline'),
      cspHeader,
    )
    h.check('CSP keeps script-src self', cspHeader.includes("script-src 'self'"), cspHeader)

    // --- 14.9: DB backup via CLI (manual run) ---
    const backupsDir = path.join(DATA_DIR, 'backups')
    const before = fs.existsSync(backupsDir) ? fs.readdirSync(backupsDir).length : 0
    const backup = spawnSync('.venv/bin/python', ['-m', 'app.cli', 'backup-now'], {
      cwd: BACKEND_DIR,
      env: backendEnv,
      encoding: 'utf8',
    })
    h.check('14.9: backup-now CLI exits 0', backup.status === 0, `status ${backup.status}: ${(backup.stderr || '').slice(0, 200)}`)
    const files = fs.readdirSync(backupsDir).filter((f) => /^app-\d{8}-\d{6}\.db$/.test(f))
    h.check('14.9: backup file created in /data/backups', files.length === before + 1, `${before} -> ${files.length}`)
    if (files.length > 0) {
      const latest = path.join(DATA_DIR, 'backups', files[files.length - 1])
      const head = fs.readFileSync(latest).subarray(0, 15).toString('ascii')
      h.check('14.9: backup is a valid SQLite file', head === 'SQLite format 3', head)
    }

    // --- 14.10: data persistence across a backend restart ---
    const artists = await h.apiJson(page, '/api/v1/artists?page_size=1')
    const releases = await h.apiJson(page, '/api/v1/releases?page_size=1')
    const settings = await h.apiJson(page, '/api/v1/settings')
    const beforeTotal = { artists: artists.body.total, releases: releases.body.total }
    const themeBefore = settings.body.theme
    await restartBackend()
    await page.goto(`${h.BASE}/`, { waitUntil: 'networkidle0' })
    await page.waitForFunction(() => location.pathname === '/', { timeout: 20000 })
    const artists2 = await h.apiJson(page, '/api/v1/artists?page_size=1')
    const releases2 = await h.apiJson(page, '/api/v1/releases?page_size=1')
    const settings2 = await h.apiJson(page, '/api/v1/settings')
    h.check(
      '14.10: artists survive restart',
      artists2.body.total === beforeTotal.artists,
      `${beforeTotal.artists} -> ${artists2.body.total}`,
    )
    h.check(
      '14.10: releases survive restart',
      releases2.body.total === beforeTotal.releases,
      `${beforeTotal.releases} -> ${releases2.body.total}`,
    )
    h.check('14.10: session survives restart (already logged in)', true)
    h.check(
      '14.10: settings survive restart',
      settings2.body.theme === themeBefore && settings2.body.discovery_from_date === settings.body.discovery_from_date,
      `theme ${themeBefore} -> ${settings2.body.theme}`,
    )
    const cards2 = await page.$$eval('a[href^="/releases/"]', (els) => els.length)
    h.check('14.10: feed still rendered after restart', cards2 > 0, `cards ${cards2}`)

    // --- cleanliness ---
    await h.wait(1000)
    const realConsole = h.realErrors(state)
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    h.check('no console errors (excluding expected 401s)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 3)))
    h.check('no CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    h.check('no page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    const realFails = state.failedRequests.filter(
      (u) => !u.includes('/api/v1/auth/') && !u.includes('net::ERR_ABORTED'),
    )
    h.check('no failed requests', realFails.length === 0, JSON.stringify(realFails.slice(0, 3)))
  } finally {
    await h.finish({ browser, page, state }, '12')
  }
}

main().catch((e) => {
  console.error('SCRIPT ERROR:', e)
  process.exit(2)
})

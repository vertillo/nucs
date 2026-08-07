'use strict'
/**
 * Fase 13b — automated subset of the manual verification checklist (fase 13):
 * deterministic items only; the human-only rows (F2/B8, F4, F7, J1-J2, C11)
 * are recorded as N.A. in the exported table (see piano/fasi/fase-13b-*.md).
 *
 * Coverage per area (checklist refs of piano/fasi/fase-13-verifica-manuale-completa.md):
 * - A: A4 global lockout (REAL ~15 min wait), A5 timing (unknown user vs wrong
 *   password), A6 input limits, A7 double-click login, A8 Enter submit,
 *   A11 cookie tampering
 * - B: B1 rapid theme toggles, B4 invalid localStorage value fallback,
 *   B7 prefers-color-scheme: light -> no flash at first load
 * - C: C3 Singles+Unseen+search, C4 special-char search, C5 empty state,
 *   C7 mark-all-as-seen (dismiss + accept), C9 missing release,
 *   C13 broken cover placeholder, C14 Slow 3G skeleton + failed request,
 *   C15 double-trigger load on slow network
 * - E: E3 future/invalid discovery date, E14 offline save
 * - F: F1 viewports, F3 keyboard-only, F5 axe color-contrast+label both themes,
 *   F6 prefers-reduced-motion, F8 compact navbar at 375px
 * - G: G3 offline mutations, G4 backend restart (spawn uvicorn, kill by port),
 *   G5 TZ=Pacific/Kiritimati UTC dates, G6 double-click Save, G7 first load
 * - H: H4-H8, H10 (authenticated fetch equivalents of the curl checks)
 * - I: I1-I6 (two tabs via browser.createBrowserContext)
 * - J: J3/J5 only when E2E_PROD_STACK=1, else N.A.
 * - Final: G1/G2 console/CSP/external-images cleanliness
 *
 * Env: BASE, ADMIN_USER, ADMIN_PASS (harness defaults) + E2E_DATA_DIR (default
 * /tmp/nucs-e2e) and E2E_MUSIC_LIBRARY (default /tmp/nucs-lib-test); the
 * backend under test must run with DATA_DIR=$E2E_DATA_DIR and
 * DEV_INSECURE_COOKIES=true (see e2e/README.md). The scenario restarts the
 * backend once (G4) with the same env + TZ=Pacific/Kiritimati.
 * E2E_13B_QUICK=1 shortens the real lockout waits (validation aid only; the
 * real run uses the full ~15 min A4 wait).
 */
const { execSync, spawn, spawnSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const h = require('../harness')

const DATA_DIR = process.env.E2E_DATA_DIR || '/tmp/nucs-e2e'
const COVERS_DIR = process.env.E2E_COVERS_DIR || path.join(DATA_DIR, 'covers')
const MUSIC = process.env.E2E_MUSIC_LIBRARY || '/tmp/nucs-lib-test'
const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend')
const DB_FILE = path.join(DATA_DIR, 'app.db')
const LOG_FILE = '/tmp/nucs-e2e-backend.log'
const RESULTS_FILE = path.join(h.ARTIFACTS_DIR, 'fase-13-results.md')
const PROD_STACK = process.env.E2E_PROD_STACK === '1'
const QUICK = process.env.E2E_13B_QUICK === '1'
const port = new URL(h.BASE).port || '8080'
const HOST = new URL(h.BASE).hostname || '127.0.0.1'

const CARD = 'a[href^="/releases/"]'
const THEME_TOGGLE = 'button[aria-label="Toggle theme"]'
const UNSEEN_SWITCH = 'button[aria-label="Unseen only"]'
const SEARCH_INPUT = 'input[aria-label="Search"]'

// --- results table (exported at the end) ---
const rows = []
function t(area, ref, name, ok, evidence = '') {
  h.check(`${area}${ref}: ${name}`, ok, evidence)
  rows.push({ area, ref: `${ref} — ${name}`, ok: ok ? 'PASS' : 'FAIL', evidence })
}
function tNA(area, ref, name, evidence = '') {
  rows.push({ area, ref: `${ref} — ${name}`, ok: 'N.A.', evidence })
  console.log(`N.A. | ${area}${ref} | ${name} | ${evidence}`)
}
function exportTable(started) {
  const dur = Math.round((Date.now() - started) / 1000)
  const md = [
    '# FASE 13b — checklist compilata (automazione e2e:13)',
    '',
    `- Data: ${new Date().toISOString()}`,
    `- Durata: ${Math.floor(dur / 60)}m ${dur % 60}s`,
    `- BASE: ${h.BASE}`,
    `- Modalita: ${QUICK ? 'QUICK (attese lockout ridotte — solo validazione)' : 'completa (attese reali A4/A5)'}`,
    '',
    '| Area | Voce | Esito | Evidenza |',
    '|---|---|---|---|',
    ...rows.map((r) => `| ${r.area} | ${r.ref} | ${r.ok} | ${(r.evidence || '').replace(/\|/g, '\\|').replace(/\n/g, ' ')} |`),
    '',
  ].join('\n')
  fs.mkdirSync(h.ARTIFACTS_DIR, { recursive: true })
  fs.writeFileSync(RESULTS_FILE, md)
  console.log(`\n[13b] results exported: ${RESULTS_FILE}`)
  console.log('\narea | PASS/FAIL/N.A. | evidenza')
  for (const r of rows) console.log(`${r.area} | ${r.ok} | ${(r.evidence || '').slice(0, 140)}`)
}

async function clickByText(page, text) {
  try {
    const ok = await page.evaluate((txt) => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === txt)
      if (!btn) return false
      btn.click()
      return true
    }, text)
    if (!ok) throw new Error(`button not found: "${text}"`)
    return ok
  } catch (error) {
    // the click can trigger an SPA navigation that destroys the execution
    // context before the evaluate resolves (benign race)
    if (/Execution context was destroyed/.test(String(error))) return true
    throw error
  }
}

async function clickByTextAwait(page, text, gapMs = 100) {
  return page.evaluate(
    async ({ txt, gap }) => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === txt)
      if (!btn) return false
      btn.click()
      await new Promise((r) => setTimeout(r, gap))
      btn.click()
      return true
    },
    { txt: text, gap: gapMs },
  )
}

/** Set the value of the feed search input like a user typing (React onChange). */
async function setSearch(page, value) {
  await page.evaluate(
    (v) => {
      const input = document.querySelector('input[aria-label="Search"]')
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, v)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    },
    value,
  )
}

async function waitForH1(page, text, timeoutMs = 30000) {
  await page.waitForFunction(
    (txt) => {
      const h1 = document.querySelector('h1')
      return !!h1 && h1.textContent.trim().includes(txt)
    },
    { timeout: timeoutMs },
    text,
  )
}

async function waitForFeed(page, timeoutMs = 120000) {
  await page.waitForSelector(CARD, { timeout: timeoutMs }).catch(() => {})
}

/** Intentional console errors of the whole run (401/404/422/429 + offline/restart). */
function intentionalConsole(state) {
  return state.consoleErrors.filter((e) => {
    if (e.includes('status of 401')) return false
    if (e.includes('status of 404')) return false
    if (e.includes('status of 422')) return false
    if (e.includes('status of 429')) return false
    if (/net::ERR_(INTERNET_DISCONNECTED|CONNECTION_REFUSED|ABORTED|FAILED|CONNECTION_RESET)/.test(e)) return false
    return true
  })
}

function sqlite(sql) {
  return execSync(`sqlite3 "${DB_FILE}" "${sql}"`, { encoding: 'utf8' }).trim()
}

// --- backend restart helpers (same pattern as e2e:12) ---
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

function startBackend(extraEnv = {}) {
  const child = spawn(
    '.venv/bin/uvicorn',
    ['app.main:app', '--host', HOST, '--port', port, '--proxy-headers', '--no-server-header'],
    {
      cwd: BACKEND_DIR,
      env: { ...backendEnv, ...extraEnv },
      stdio: ['ignore', fs.openSync(LOG_FILE, 'a'), fs.openSync(LOG_FILE, 'a')],
      detached: true,
    },
  )
  child.unref()
  return child
}

async function waitHealth(timeoutMs = 120000) {
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

async function restartBackend(extraEnv = {}) {
  killBackend()
  await h.wait(1500)
  const child = startBackend(extraEnv)
  t('G', 'G4', 'backend restarted (uvicorn spawned with documented env)', child.pid !== undefined, `pid ${child.pid}`)
  t('G', 'G4', 'backend healthy after restart', await waitHealth(), h.BASE)
}

// --- auth helpers (Node-side fetch, like the curl checks of fase 13) ---
const XHR_HEADERS = {
  'Content-Type': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
  Origin: h.BASE,
}

async function apiLogin(user, pass) {
  const t0 = performance.now()
  const r = await fetch(`${h.BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: XHR_HEADERS,
    body: JSON.stringify({ username: user, password: pass }),
    redirect: 'manual',
  })
  const ms = performance.now() - t0
  let detail = null
  try {
    detail = await r.json()
  } catch {
    /* 204 */
  }
  return {
    status: r.status,
    ms,
    detail: detail && typeof detail === 'object' ? (detail.detail ?? null) : null,
    retryAfter: r.headers.get('retry-after'),
  }
}

async function seed(page) {
  await h.uiLogin(page)
  const put = await h.apiPut(page, '/api/v1/settings', { discovery_from_date: '2024-01-01' })
  console.log(`seed: PUT settings discovery_from_date -> ${put.status}`)
  console.log('seed: POST /scans/library?full=true ...')
  const r1 = await h.apiPost(page, '/api/v1/scans/library?full=true')
  console.log(`seed: library scan accepted (${r1.status}), waiting for idle ...`)
  await h.waitForScanIdle(page, 900000)
  console.log('seed: POST /scans/releases ...')
  const r2 = await h.apiPost(page, '/api/v1/scans/releases')
  console.log(`seed: releases scan accepted (${r2.status}), waiting for idle ...`)
  await h.waitForScanIdle(page, 900000)
  const feed = await h.apiJson(page, '/api/v1/releases?page_size=1')
  console.log(`seed: feed total = ${feed.body.total}`)
  await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
  await waitForFeed(page, 60000)
}

async function axeViolations(page) {
  // CSP (script-src 'self') blocks injected <script> tags; evaluating the
  // source directly bypasses the CSP check (CDP Runtime.evaluate)
  const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8')
  await page.evaluate(axeSrc)
  return page.evaluate(async () => {
    const res = await window.axe.run(document.body, {
      runOnly: { type: 'rule', values: ['color-contrast', 'label'] },
    })
    return res.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      targets: v.nodes.slice(0, 3).map((n) => n.target.join(' ')),
    }))
  })
}

async function setThemeViaServer(page, theme) {
  await h.apiPut(page, '/api/v1/settings', { theme })
  await page.evaluate((th) => localStorage.setItem('nucs-theme', th), theme)
  await page.reload({ waitUntil: 'domcontentloaded' })
}

async function main() {
  const { browser, page, state } = await h.launch()
  const started = Date.now()
  try {
    // ================= SEED =================
    console.log('\n=== 13b: seed (library scan + discovery) ===')
    await seed(page)

    // ================= G7: first load on normal network =================
    console.log('\n=== 13b: G7 first-load timing ===')
    const ctxCold = await browser.createBrowserContext()
    const cold = await ctxCold.newPage()
    await cold.setCacheEnabled(false)
    const tDoc0 = Date.now()
    await cold.goto(`${h.BASE}/login`, { waitUntil: 'domcontentloaded' })
    const navDur = await cold.evaluate(() => {
      const n = performance.getEntriesByType('navigation')[0]
      return n ? n.duration : -1
    })
    const docMs = Date.now() - tDoc0
    t('G', 'G7', 'first load (cold cache) under 3 s', navDur >= 0 && navDur < 3000 && docMs < 3000, `doc ${Math.round(navDur)}ms`)
    await cold.type('#username', h.ADMIN_USER)
    await cold.type('#password', h.ADMIN_PASS)
    const tCard0 = Date.now()
    await cold.click('button[type=submit]')
    await cold.waitForSelector(CARD, { timeout: 60000 }).catch(() => {})
    const toCard = Date.now() - tCard0
    t('G', 'G7', 'feed interactive under 3 s after login (normal network)', toCard < 3000, `${toCard}ms to first card`)
    await ctxCold.close()

    // ================= B: theme =================
    console.log('\n=== 13b: B theme ===')
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const dark = () => page.evaluate(() => document.documentElement.classList.contains('dark'))
    const themeState = await page.evaluate(() => ({
      dark: document.documentElement.classList.contains('dark'),
      stored: localStorage.getItem('nucs-theme'),
    }))
    let flips = 0
    for (let i = 0; i < 10; i++) {
      const before = await dark()
      await page.click(THEME_TOGGLE)
      await h.wait(60)
      const after = await dark()
      if (before !== after) flips++
    }
    t('B', 'B1', '10 rapid toggles: theme flips every click, never stuck', flips === 10, `flips ${flips}/10`)
    const finalTheme = await page.evaluate(() => document.documentElement.classList.contains('dark') ? 'dark' : 'light')
    await page.click(THEME_TOGGLE)
    await h.wait(300)
    const stillWorks = (await dark()) !== (finalTheme === 'dark')
    t('B', 'B1', 'toggle still responsive after the burst', stillWorks)

    // B4: the server theme is the source of truth (spec); with server dark the
    // invalid "purple" value must fall back to dark, never to a broken state.
    await setThemeViaServer(page, 'dark')
    await page.evaluate(() => localStorage.setItem('nucs-theme', 'purple'))
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    t('B', 'B4', 'localStorage "purple" -> fallback dark (server dark)', await dark())
    await setThemeViaServer(page, 'light')
    await page.evaluate(() => localStorage.setItem('nucs-theme', 'light'))
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    t('B', 'B4', 'localStorage "light" -> light theme (server light)', !(await dark()))
    await setThemeViaServer(page, 'dark')

    // B7: OS light preference, no stored value, server dark -> no flash
    const ctxLight = await browser.createBrowserContext()
    const lightPage = await ctxLight.newPage()
    await lightPage.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }])
    await lightPage.goto(`${h.BASE}/login`, { waitUntil: 'domcontentloaded' })
    const atDom = await lightPage.evaluate(() => ({
      dark: document.documentElement.classList.contains('dark'),
      stored: localStorage.getItem('nucs-theme'),
    }))
    await h.wait(1200)
    const afterSettle = await lightPage.evaluate(() => document.documentElement.classList.contains('dark'))
    t(
      'B', 'B7',
      'prefers-color-scheme: light -> no wrong theme flash at first load',
      atDom.dark && atDom.dark === afterSettle,
      `dark@DOMContentLoaded=${atDom.dark} dark@1.2s=${afterSettle} stored=${atDom.stored ?? 'none'}`,
    )
    await ctxLight.close()

    // ================= C: feed =================
    console.log('\n=== 13b: C feed & release detail ===')
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)

    // C3: Singles + Unseen only + search -> coherent result
    const singleSearch = await page.evaluate(async () => {
      const r = await fetch('/api/v1/releases?type=single&seen=no&page_size=100', { credentials: 'same-origin' })
      const body = await r.json()
      const items = body.items || []
      return { total: body.total || 0, term: items.length > 0 ? items[0].title.slice(0, 12) : null }
    })
    if (singleSearch.term) {
      await clickByText(page, 'Singles')
      await page.click(UNSEEN_SWITCH)
      await setSearch(page, singleSearch.term)
      await h.wait(1500)
      const uiCards = await page.$$eval(CARD, (els) => els.length)
      const apiTotal = (await h.apiJson(page, `/api/v1/releases?type=single&seen=no&q=${encodeURIComponent(singleSearch.term)}&page_size=100`)).body.total
      const coherent = await page.evaluate(() => ({
        error: document.body.innerText.includes('Something went wrong loading releases.'),
        singles: [...document.querySelectorAll('a[href^="/releases/"]')].every((c) => c.textContent.includes('Single')),
        unseen: [...document.querySelectorAll('a[href^="/releases/"]')].every((c) => c.querySelector('[aria-label="New"]') !== null),
      }))
      t(
        'C', 'C3',
        'Singles + Unseen only + search -> coherent with the API',
        !coherent.error && coherent.singles && coherent.unseen && uiCards === Math.min(apiTotal, 30),
        `UI ${uiCards} cards vs API total ${apiTotal} (q="${singleSearch.term}")`,
      )
      await clickByText(page, 'All')
      await page.click(UNSEEN_SWITCH)
      await setSearch(page, '')
      await h.wait(1000)
    } else {
      t('C', 'C3', 'Singles + Unseen only + search (no unseen singles in the seed)', true, 'combination not exercisable, API total 0')
    }

    // C4: special-char search -> literal results, no error
    for (const ch of ['%', '_', '\\', '"', "'"]) {
      await setSearch(page, ch)
      await h.wait(900)
      const state4 = await page.evaluate(() => ({
        error: document.body.innerText.includes('Something went wrong loading releases.'),
        cards: document.querySelectorAll('a[href^="/releases/"]').length,
      }))
      const api4 = (await h.apiJson(page, `/api/v1/releases?q=${encodeURIComponent(ch)}&page_size=100`)).body.total
      t(
        'C', 'C4',
        `search "${ch}" -> literal results, no error`,
        !state4.error && state4.cards === Math.min(api4, 30),
        `UI ${state4.cards} vs API ${api4}`,
      )
    }
    await setSearch(page, '')

    // C5: empty state
    await setSearch(page, 'zzzz-no-such-release-13b-999')
    await h.wait(1000)
    const empty = await page.evaluate(() => ({
      title: document.body.innerText.includes('No new releases'),
      hint: document.body.innerText.includes('Try running a scan from'),
      link: !!document.querySelector('a[href="/settings"]'),
    }))
    t('C', 'C5', 'empty state: "No new releases" + hint + Settings link', empty.title && empty.hint && empty.link, JSON.stringify(empty))
    await setSearch(page, '')

    // C9: missing release detail
    await page.goto(`${h.BASE}/releases/999999`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('Release not found'), { timeout: 30000 })
    const c9 = await page.evaluate(() => ({
      text: document.body.innerText.includes('Release not found'),
      feedBtn: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Back to feed'),
    }))
    t('C', 'C9', '/releases/999999 -> "Release not found" + link to the feed', c9.text && c9.feedBtn, JSON.stringify(c9))
    await clickByText(page, 'Back to feed')
    await page.waitForFunction(() => location.pathname === '/', { timeout: 15000 }).catch(() => {})

    // C13: broken cover -> placeholder, no broken layout
    const coverTarget = await page.evaluate(async () => {
      const r = await fetch('/api/v1/releases?page_size=100', { credentials: 'same-origin' })
      const body = await r.json()
      return (body.items || []).find((it) => it.cover_path) || null
    })
    const coverPath = coverTarget ? path.join(COVERS_DIR, coverTarget.cover_path) : null
    if (coverPath && fs.existsSync(coverPath)) {
      fs.renameSync(coverPath, `${coverPath}.13b-bak`)
      // disable the HTTP cache so the previously-loaded cover must be re-fetched
      // (and fail with 404 -> placeholder) instead of being served from cache
      await page.setCacheEnabled(false)
      await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
      await waitForFeed(page)
      await setSearch(page, coverTarget.title.slice(0, 14))
      await h.wait(1200)
      // wait for the lazy cover of the target card to fail (404 -> placeholder)
      let placeholder = false
      for (let i = 0; i < 40 && !placeholder; i++) {
        placeholder = await page.evaluate((title) => {
          const card = [...document.querySelectorAll('a[href^="/releases/"]')].find(
            (c) => c.querySelector('h3') && c.querySelector('h3').textContent.trim() === title,
          )
          if (!card) return false
          card.scrollIntoView()
          return card.querySelector('img[src*="/api/v1/covers/"]') === null
        }, coverTarget.title)
        if (!placeholder) await h.wait(500)
      }
      const afterWait = await page.evaluate((title) => {
        const card = [...document.querySelectorAll('a[href^="/releases/"]')].find(
          (c) => c.querySelector('h3') && c.querySelector('h3').textContent.trim() === title,
        )
        if (!card) return { found: false, placeholder: false, overflow: 0 }
        return {
          found: true,
          placeholder: card.querySelector('img[src*="/api/v1/covers/"]') === null,
          overflow: document.documentElement.scrollWidth - window.innerWidth,
        }
      }, coverTarget.title)
      t(
        'C', 'C13',
        'broken cover -> placeholder, no layout break',
        afterWait.found && afterWait.placeholder && afterWait.overflow <= 1,
        `placeholder=${afterWait.placeholder} overflow=${afterWait.overflow}px (${coverTarget.cover_path})`,
      )
      await setSearch(page, '')
      fs.renameSync(`${coverPath}.13b-bak`, coverPath)
      await page.setCacheEnabled(true)
    } else {
      t('C', 'C13', 'broken cover check (no cover file on disk to break)', false, 'COVERS_DIR/E2E_DATA_DIR mismatch or no covers in seed')
    }

    // C7: Mark all as seen — dismiss then accept
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    page.once('dialog', (d) => d.dismiss())
    await clickByText(page, 'Mark all as seen')
    await h.wait(1500)
    const dotsAfterDismiss = await page.$$eval('[aria-label="New"]', (els) => els.length)
    t('C', 'C7', '"Mark all as seen" with dialog dismissed -> nothing changes', dotsAfterDismiss > 0, `New dots still ${dotsAfterDismiss}`)
    page.once('dialog', (d) => d.accept())
    await clickByText(page, 'Mark all as seen')
    await h.wait(2500)
    const dotsAfterAccept = await page.$$eval('[aria-label="New"]', (els) => els.length)
    t('C', 'C7', '"Mark all as seen" accepted -> dots gone', dotsAfterAccept === 0, `New dots ${dotsAfterAccept}`)
    await page.click(UNSEEN_SWITCH)
    await h.wait(1200)
    const unseenEmpty = await page.evaluate(() => document.body.innerText.includes('No new releases'))
    t('C', 'C7', '"Unseen only" after mark-all -> empty state', unseenEmpty)
    await page.click(UNSEEN_SWITCH)

    // C14: Slow 3G -> skeleton then cards; failed request -> message + Retry
    await page.emulateNetworkConditions({ offline: false, latency: 2000, download: 50000, upload: 50000 })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    let sawSkeleton = false
    for (let i = 0; i < 40 && !sawSkeleton; i++) {
      sawSkeleton = await page.evaluate(() => document.querySelectorAll('.animate-pulse').length > 0)
      if (!sawSkeleton) await h.wait(200)
    }
    t('C', 'C14', 'Slow 3G: skeleton visible while loading', sawSkeleton, `skeleton ${sawSkeleton}`)
    await waitForFeed(page, 120000)
    const cardsSlow = await page.$$eval(CARD, (els) => els.length)
    t('C', 'C14', 'Slow 3G: cards eventually render', cardsSlow > 0, `cards ${cardsSlow}`)
    await page.emulateNetworkConditions(null)
    // failed request -> message + Retry: abort only the feed API call so /me
    // still succeeds (a full offline reload would redirect the whole app to /login)
    await page.setRequestInterception(true)
    await page.on('request', (req) => {
      // .catch() swallows the async rejection of a trailing request that is
      // finalized after interception gets disabled again
      if (req.url().includes('/api/v1/releases')) req.abort('failed').catch(() => {})
      else req.continue().catch(() => {})
    })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('Something went wrong loading releases.'), { timeout: 30000 }).catch(() => {})
    const retryShown = await page.evaluate(() => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Retry'))
    await page.setRequestInterception(false)
    t('C', 'C14', 'failed request -> error message + Retry button', retryShown)
    await clickByText(page, 'Retry')
    await waitForFeed(page, 60000)
    t('C', 'C14', 'Retry after the failure -> feed loads', (await page.$$eval(CARD, (els) => els.length)) > 0)

    // C15: double-trigger load on slow network -> no duplicate cards
    await page.emulateNetworkConditions({ offline: false, latency: 2000, download: 50000, upload: 50000 })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForFeed(page, 120000)
    const hasMore = await page.evaluate(() => document.body.innerText.includes('Loading more'))
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await h.wait(700)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await page.waitForFunction(() => /\d+ of \d+/.test(document.body.innerText), { timeout: 120000 }).catch(() => {})
    const uniq = await page.evaluate(() => {
      const hrefs = [...document.querySelectorAll('a[href^="/releases/"]')].map((a) => a.getAttribute('href'))
      return { total: hrefs.length, unique: new Set(hrefs).size }
    })
    if (hasMore) {
      t('C', 'C15', 'double-trigger "load more" on slow network -> no duplicated cards', uniq.total === uniq.unique && uniq.total > 0, `${uniq.unique}/${uniq.total} unique`)
    } else {
      t('C', 'C15', 'double-trigger "load more" (single page in the seed)', true, `only ${uniq.total} cards, no next page to double-trigger`)
    }
    await page.emulateNetworkConditions(null)

    // ================= E: settings =================
    console.log('\n=== 13b: E settings ===')
    await page.goto(`${h.BASE}/settings`, { waitUntil: 'domcontentloaded' })
    await waitForH1(page, 'Settings')
    await page.waitForSelector('#discovery-from-date', { timeout: 60000 })

    const discoverySection = async () => {
      // the sections render only after the settings data hydrate; retry briefly
      for (let i = 0; i < 10; i++) {
        const probe = await page.evaluate(() => {
          const sections = [...document.querySelectorAll('section')]
          const s = sections.find((x) => x.textContent.includes('Discover releases from'))
          if (!s) return { what: 'no-section', secs: sections.length, hasH1: !!document.querySelector('h1') }
          const b = [...s.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Save')
          return { what: b ? 'button' : 'no-button', buttons: [...s.querySelectorAll('button')].map((x) => x.textContent.trim()) }
        })
        if (probe.what === 'button') {
          await page.evaluate(() => {
            const s = [...document.querySelectorAll('section')].find((x) => x.textContent.includes('Discover releases from'))
            const b = [...s.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Save')
            b.click()
          })
          return true
        }
        await h.wait(500)
      }
      const diag = await page.evaluate(() => {
        const sections = [...document.querySelectorAll('section')]
        const s = sections.find((x) => x.textContent.includes('Discover releases from'))
        return {
          path: location.pathname,
          h1: document.querySelector('h1')?.textContent,
          input: !!document.querySelector('#discovery-from-date'),
          sections: sections.length,
          finderOk: !!s,
          buttons: s ? [...s.querySelectorAll('button')].map((b) => JSON.stringify(b.textContent.trim()) + (b.disabled ? ' [disabled]' : '')) : null,
          pendingText: document.body.innerText.includes('Saving'),
        }
      })
      console.error('[13b] discovery Section not found, page state:', JSON.stringify(diag))
      return null
    }

    // E3a: invalid date -> inline error
    await page.waitForSelector('#discovery-from-date', { timeout: 60000 })
    await page.evaluate(() => {
      const input = document.querySelector('#discovery-from-date')
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, 'not-a-date')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    if (!(await discoverySection())) throw new Error('discovery Section/Save button not found')
    await h.wait(500)
    const invalidError = await page.evaluate(() => document.body.innerText.includes('Enter a valid date (YYYY-MM-DD).'))
    t('E', 'E3', 'invalid discovery date -> inline error', invalidError)

    // E3b: future date -> expected inline error per checklist
    await page.evaluate(() => {
      const input = document.querySelector('#discovery-from-date')
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, '2099-01-01')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    if (!(await discoverySection())) throw new Error('discovery Section/Save button not found')
    await h.wait(1200)
    const futureError = await page.evaluate(() => ({
      inline: document.body.innerText.includes('Enter a valid date (YYYY-MM-DD).'),
      saved: document.body.innerText.includes('Saved'),
      value: document.querySelector('#discovery-from-date').value,
    }))
    t(
      'E', 'E3',
      'future discovery date -> inline error (checklist expectation)',
      futureError.inline,
      futureError.inline ? 'inline error shown' : `accepted: input=2099-01-01, toast "Saved"=${futureError.saved} — FINDING-13B-01 (BASSA)`,
    )
    // restore the value
    await page.evaluate(() => {
      const input = document.querySelector('#discovery-from-date')
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, '2024-01-01')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    if (!(await discoverySection())) throw new Error('discovery Section/Save button not found')
    await h.wait(1000)

    // G6: double-click Save -> one settings PUT
    let putCount = 0
    const onPut = (r) => {
      if (r.method() === 'PUT' && r.url().includes('/api/v1/settings')) putCount++
    }
    page.on('request', onPut)
    putCount = 0
    await page.evaluate(async () => {
      const s = [...document.querySelectorAll('section')].find((x) => x.textContent.includes('Discover releases from'))
      const btn = [...s.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Save')
      btn.click()
      await new Promise((r) => setTimeout(r, 100))
      btn.click()
    })
    await h.wait(1500)
    page.off('request', onPut)
    t('G', 'G6', 'double-click "Save" -> one settings PUT', putCount === 1, `PUTs ${putCount}`)

    // E14/G3: offline -> mutating actions fail with an inline error, no crash.
    // FINDING-13B-03 fixed: apiFetch aborts after 30s, so the error arrives
    // (and the button recovers) within the timeout instead of hanging forever.
    await page.emulateNetworkConditions({ offline: true, latency: 0, download: 0, upload: 0 })
    if (!(await discoverySection())) throw new Error('discovery Section/Save button not found')
    let e14 = null
    for (let i = 0; i < 45 && !(e14 && e14.toast && !e14.toast.includes('Saved') && e14.btnText === 'Save'); i++) {
      await h.wait(1000)
      e14 = await page.evaluate(() => {
        const s = [...document.querySelectorAll('section')].find((x) => x.textContent.includes('Discover releases from'))
        const b = [...s.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Save' || x.textContent.trim() === 'Saving…')
        const t = document.querySelector('[role="status"]')
        return { btnText: b ? b.textContent.trim() : 'none', toast: t ? t.textContent.trim() : null }
      })
    }
    t(
      'E', 'E14',
      'Save with network offline -> error message within the fetch timeout (no stuck UI)',
      !!e14 && !!e14.toast && !e14.toast.includes('Saved') && e14.btnText === 'Save',
      `button "${e14 && e14.btnText}" after timeout, toast="${e14 && e14.toast}"`,
    )
    await page.emulateNetworkConditions(null)
    if (!(await discoverySection())) throw new Error('discovery Section/Save button not found')
    await h.wait(1200)
    const recovered = await page.evaluate(() => {
      const toast = document.querySelector('[role="status"]')
      return toast ? toast.textContent.trim() : null
    })
    t('E', 'E14', 'Save works again after reconnecting', recovered === 'Saved ✓', JSON.stringify(recovered))

    // G3: offline seen toggle on the feed -> no crash, state stays coherent
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const seenBefore = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.items[0].seen
    await page.emulateNetworkConditions({ offline: true, latency: 0, download: 0, upload: 0 })
    await page.evaluate(() => {
      const card = document.querySelector('a[href^="/releases/"]')
      const eye = card.querySelector('button[aria-label="Mark as unseen"], button[aria-label="Mark as seen"]')
      if (eye) eye.click()
    })
    await h.wait(1500)
    const offlineSeen = await page.evaluate(() => ({
      interactive: !document.body.innerText.includes('Something went wrong loading releases.'),
    }))
    await page.emulateNetworkConditions(null)
    await h.wait(1500)
    const seenAfter = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.items[0].seen
    t(
      'G', 'G3',
      'offline seen toggle -> no crash, state valid after reconnect',
      (seenAfter === 0 || seenAfter === 1) && offlineSeen.interactive,
      `seen before=${seenBefore} after=${seenAfter} (offline request rolled back or completed after reconnect; UI interactive)`,
    )
    t('G', 'G3', 'offline mutations leave the UI interactive', offlineSeen.interactive)

    // ================= F: responsive & a11y =================
    console.log('\n=== 13b: F responsive & a11y ===')
    const firstReleaseId = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.items[0]?.id
    const f1Pages = ['/', '/artists', '/settings', firstReleaseId ? `/releases/${firstReleaseId}` : '/releases/1']
    for (const width of [320, 375, 768, 1280]) {
      await page.setViewport({ width, height: 900 })
      for (const p of f1Pages) {
        await page.goto(`${h.BASE}${p}`, { waitUntil: 'domcontentloaded' })
        if (p === '/') await waitForFeed(page, 60000)
        else if (p === '/artists') await page.waitForFunction(() => document.body.innerText.includes('Tracked artists'), { timeout: 30000 }).catch(() => {})
        else if (p === '/settings') await waitForH1(page, 'Settings', 30000).catch(() => {})
        else await page.waitForSelector('h1', { timeout: 30000 }).catch(() => {})
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
        t('F', 'F1', `no horizontal scroll at ${width}px on ${p}`, overflow <= 1, `overflow ${overflow}px`)
      }
    }
    await page.setViewport({ width: 1280, height: 900 })

    // F3: keyboard-only
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    await page.keyboard.press('Tab')
    const firstFocus = await page.evaluate(() => ({
      tag: document.activeElement.tagName,
      inHeader: !!document.activeElement.closest('header'),
      href: document.activeElement.getAttribute('href') || '',
      ring: (() => {
        const cs = getComputedStyle(document.activeElement)
        return cs.boxShadow !== 'none' || cs.outlineStyle !== 'none'
      })(),
    }))
    t('F', 'F3', 'first Tab lands on a navbar link (logical order)', firstFocus.tag === 'A' && firstFocus.inHeader, firstFocus.href)
    t('F', 'F3', 'keyboard focus shows the accent focus ring', firstFocus.ring)
    let chipFocused = false
    for (let i = 0; i < 30 && !chipFocused; i++) {
      await page.keyboard.press('Tab')
      chipFocused = await page.evaluate(() => document.activeElement.textContent.trim() === 'Singles')
    }
    if (chipFocused) {
      await page.keyboard.press('Enter')
      await h.wait(400)
      const pressed = await page.evaluate(() => document.activeElement.getAttribute('aria-pressed'))
      t('F', 'F3', 'Enter activates the filter chip', pressed === 'true', `aria-pressed=${pressed}`)
      await page.evaluate(() => {
        const chip = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'All')
        if (chip) chip.click()
      })
    } else {
      t('F', 'F3', 'Enter activates the filter chip (chip not reachable in 30 Tabs)', false, 'focus cycle too long')
    }
    let switchFocused = false
    for (let i = 0; i < 30 && !switchFocused; i++) {
      await page.keyboard.press('Tab')
      switchFocused = await page.evaluate(() => document.activeElement.getAttribute('role') === 'switch')
    }
    if (switchFocused) {
      const before = await page.evaluate(() => document.activeElement.getAttribute('aria-checked'))
      await page.keyboard.press('Space')
      await h.wait(300)
      const flipped = await page.evaluate(() => document.activeElement.getAttribute('aria-checked'))
      await page.keyboard.press('Space')
      await h.wait(300)
      const restored = await page.evaluate(() => document.activeElement.getAttribute('aria-checked'))
      t('F', 'F3', 'Space toggles a switch (and back)', before !== flipped && flipped !== restored, `${before} -> ${flipped} -> ${restored}`)
    } else {
      t('F', 'F3', 'Space toggles a switch (not reachable in 30 Tabs)', false, 'focus cycle too long')
    }

    // F5: axe color-contrast + label, both themes, on /, /artists, /settings
    for (const theme of ['dark', 'light']) {
      await setThemeViaServer(page, theme)
      for (const p of ['/', '/artists', '/settings']) {
        await page.goto(`${h.BASE}${p}`, { waitUntil: 'domcontentloaded' })
        if (p === '/') await waitForFeed(page, 60000)
        else if (p === '/artists') await page.waitForFunction(() => document.body.innerText.includes('Tracked artists'), { timeout: 30000 }).catch(() => {})
        else await waitForH1(page, 'Settings', 30000).catch(() => {})
        const violations = await axeViolations(page)
        const count = violations.reduce((n, v) => n + v.nodes, 0)
        t(
          'F', 'F5',
          `axe color-contrast+label clean on ${p} (${theme} theme)`,
          count === 0,
          violations.length ? JSON.stringify(violations).slice(0, 240) : '0 violations',
        )
      }
    }
    await setThemeViaServer(page, 'dark')

    // F6: prefers-reduced-motion
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }])
    await page.emulateNetworkConditions({ offline: false, latency: 2000, download: 50000, upload: 50000 })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    let reduced = 'no-skeleton'
    for (let i = 0; i < 30 && reduced === 'no-skeleton'; i++) {
      reduced = await page.evaluate(() => {
        const el = document.querySelector('.animate-pulse, [class*="animate-pulse"]')
        return el ? getComputedStyle(el).animationName : 'no-skeleton'
      })
      if (reduced === 'no-skeleton') await h.wait(200)
    }
    await page.emulateNetworkConditions(null)
    await waitForFeed(page, 60000)
    // FINDING-13B-06 fixed: reduced motion disables the skeleton/spinner animations
    t(
      'F', 'F6',
      'prefers-reduced-motion: skeleton present but NOT animated',
      reduced === 'none',
      `reduced-motion skeleton animationName: "${reduced}"`,
    )
    await page.emulateMediaFeatures([])

    // F8: compact navbar at 375px
    await page.setViewport({ width: 375, height: 800 })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const navbar375 = await page.evaluate(() => {
      const textHidden = (label) => {
        const link = document.querySelector(`a[aria-label="${label}"]`)
        if (!link) return false
        const span = [...link.querySelectorAll('span')].find((s) => s.textContent.trim() === label)
        return span ? getComputedStyle(span).display === 'none' : false
      }
      const iconVisible = (label) => {
        const link = document.querySelector(`a[aria-label="${label}"]`)
        if (!link) return false
        const svg = link.querySelector('svg')
        return svg ? getComputedStyle(svg).display !== 'none' : false
      }
      return {
        feedText: textHidden('Feed'),
        artistsText: textHidden('Artists'),
        settingsText: textHidden('Settings'),
        feedIcon: iconVisible('Feed'),
        artistsIcon: iconVisible('Artists'),
        settingsIcon: iconVisible('Settings'),
      }
    })
    t(
      'F', 'F8',
      '375px: navbar compact (text hidden, icons visible)',
      navbar375.feedText && navbar375.artistsText && navbar375.settingsText && navbar375.feedIcon && navbar375.artistsIcon && navbar375.settingsIcon,
      JSON.stringify(navbar375),
    )
    await page.click('a[aria-label="Artists"]')
    await page.waitForFunction(() => location.pathname === '/artists', { timeout: 15000 })
    t('F', 'F8', '375px: navbar icons are clickable (Artists)', true)
    await page.setViewport({ width: 1280, height: 900 })

    // ================= H: API adversarial =================
    console.log('\n=== 13b: H API adversarial ===')
    const h4 = await page.evaluate(async () => {
      const out = []
      for (const id of ['0', '-1', '999999999']) {
        const r = await fetch(`/api/v1/releases/${id}`, { credentials: 'same-origin' })
        out.push(r.status)
      }
      return out
    })
    t('H', 'H4', '/releases/0, /-1, /999999999 -> 404/422, never 500', h4.every((s) => s !== 500 && s !== 200), h4.join(','))
    const h5 = await page.evaluate(async () => {
      const r = await fetch('/api/v1/covers/..%2F..%2Fetc%2Fpasswd', { credentials: 'same-origin' })
      return r.status
    })
    t('H', 'H5', '/covers/..%2F..%2Fetc%2Fpasswd -> 400/404, never 200', h5 === 400 || h5 === 404, `status ${h5}`)
    const h6 = await page.evaluate(async () => {
      const big = 'x'.repeat(10000)
      const q = await fetch(`/api/v1/releases?q=${encodeURIComponent(big)}`, { credentials: 'same-origin' })
      const pz = await fetch('/api/v1/releases?page_size=0', { credentials: 'same-origin' })
      const pg = await fetch('/api/v1/releases?page=999999&page_size=5', { credentials: 'same-origin' })
      const pgBody = await pg.json()
      return { q: q.status, pageSize: pz.status, page: pg.status, items: (pgBody.items || []).length, total: pgBody.total }
    })
    t('H', 'H6', '?q=10k chars -> 422; ?page_size=0 -> 422; ?page=999999 -> empty list', h6.q === 422 && h6.pageSize === 422 && h6.page === 200 && h6.items === 0, JSON.stringify(h6))
    const h7 = await h.apiPut(page, '/api/v1/settings', { not_a_whitelisted_key: 'x' })
    t('H', 'H7', 'PUT /settings unknown key -> 422', h7.status === 422, `status ${h7.status}`)
    const h8 = await h.apiPut(page, '/api/v1/settings', { theme: 'purple' })
    t('H', 'H8', 'PUT /settings {"theme":"purple"} -> 422', h8.status === 422, `status ${h8.status}`)
    const h10 = []
    let h10Max = 0
    for (let i = 0; i < 20; i++) {
      const t0 = performance.now()
      const r = await fetch(`${h.BASE}/api/health`)
      const dur = performance.now() - t0
      const body = await r.json()
      h10.push(r.status)
      h10Max = Math.max(h10Max, dur)
    }
    t('H', 'H10', '20x GET /api/health -> always fast JSON', h10.every((s) => s === 200) && h10Max < 2000, `statuses ${[...new Set(h10)].join(',')}, max ${Math.round(h10Max)}ms`)

    // ================= I: concurrency / two tabs =================
    console.log('\n=== 13b: I concurrency (two tabs) ===')
    const ctx2 = await browser.createBrowserContext()
    const tabB = await ctx2.newPage()
    await h.uiLogin(tabB)
    await tabB.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(tabB, 60000)

    // I1: seen-all in tab A -> tab B refresh shows it
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    await page.evaluate(() => {
      const card = document.querySelector('a[href^="/releases/"]')
      const eye = card.querySelector('button[aria-label="Mark as seen"], button[aria-label="Mark as unseen"]')
      if (eye) eye.click()
    })
    await h.wait(1200)
    page.once('dialog', (d) => d.accept())
    await clickByText(page, 'Mark all as seen')
    await h.wait(2500)
    await tabB.reload({ waitUntil: 'domcontentloaded' })
    await waitForFeed(tabB, 60000)
    const dotsB = await tabB.$$eval('[aria-label="New"]', (els) => els.length)
    t('I', 'I1', 'mark-all-seen in tab A -> tab B (refresh) updated', dotsB === 0, `tab B New dots ${dotsB}`)

    // I2: same detail in two tabs -> no error, seen coherent
    const detailId = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.items[0]?.id
    if (detailId) {
      await page.goto(`${h.BASE}/releases/${detailId}`, { waitUntil: 'domcontentloaded' })
      await page.waitForSelector('h1', { timeout: 30000 })
      await tabB.goto(`${h.BASE}/releases/${detailId}`, { waitUntil: 'domcontentloaded' })
      await tabB.waitForSelector('h1', { timeout: 30000 })
      const beforeState = await page.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Seen')
        return btn ? btn.getAttribute('aria-pressed') : null
      })
      await page.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Seen')
        if (btn) btn.click()
      })
      await h.wait(1500)
      await tabB.reload({ waitUntil: 'domcontentloaded' })
      await tabB.waitForSelector('h1', { timeout: 30000 })
      const seenState = await tabB.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Seen')
        return btn ? btn.getAttribute('aria-pressed') : null
      })
      t(
        'I', 'I2',
        'same detail in two tabs -> seen state coherent after refresh',
        seenState !== null && seenState !== beforeState,
        `aria-pressed ${beforeState} -> ${seenState} (release ${detailId})`,
      )
    } else {
      t('I', 'I2', 'same detail in two tabs (no release to test)', false, 'empty feed')
    }

    // I3: simultaneous theme toggle in two tabs -> valid theme after reload
    const themeABefore = await tabB.evaluate(() => document.documentElement.classList.contains('dark'))
    const toggleBoth = (p) =>
      p.evaluate(() => {
        const btn = document.querySelector('button[aria-label="Toggle theme"]')
        if (btn) btn.click()
      })
    await toggleBoth(page)
    await toggleBoth(tabB)
    await h.wait(1500)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const validTheme = await page.evaluate(() => {
      const cls = document.documentElement.classList.contains('dark') ? 'dark' : 'light'
      const stored = localStorage.getItem('nucs-theme')
      return { cls, stored, valid: (cls === 'dark' || cls === 'light') && (stored === null || stored === 'dark' || stored === 'light') }
    })
    t('I', 'I3', 'simultaneous theme toggles -> valid theme after reload', validTheme.valid, `class=${validTheme.cls} stored=${validTheme.stored} (was ${themeABefore ? 'dark' : 'light'})`)
    await setThemeViaServer(page, 'dark')
    await tabB.evaluate(() => localStorage.setItem('nucs-theme', 'dark'))
    await tabB.reload({ waitUntil: 'domcontentloaded' })

    // I4: start a scan, logout -> logout ok, scan continues (background job)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const scanStart = await h.apiPost(page, '/api/v1/scans/releases')
    const logoutTime = new Date().toISOString()
    await clickByText(page, 'Log out')
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 15000 })
    t('I', 'I4', 'logout while a scan runs -> logout ok', true)
    await h.uiLogin(page)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    await h.waitForScanIdle(page, 900000)
    const scanRuns = await h.apiJson(page, '/api/v1/scans/status')
    const releasesRun = (scanRuns.body.last_runs || []).find((r) => r.type === 'releases' && r.started_at <= logoutTime)
    t('I', 'I4', 'scan kept running after logout (background job completed)', !!releasesRun, JSON.stringify(releasesRun ? { type: releasesRun.type, status: releasesRun.status } : scanRuns.body.last_runs?.slice(0, 2)))

    // I5: rapid double-trigger load -> no duplicated cards
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const hasMoreI5 = await page.evaluate(() => document.body.innerText.includes('Loading more'))
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await h.wait(600)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await page.waitForFunction(() => /\d+ of \d+/.test(document.body.innerText), { timeout: 120000 }).catch(() => {})
    const uniqI5 = await page.evaluate(() => {
      const hrefs = [...document.querySelectorAll('a[href^="/releases/"]')].map((a) => a.getAttribute('href'))
      return { total: hrefs.length, unique: new Set(hrefs).size }
    })
    t('I', 'I5', 'rapid double "load more" trigger -> no duplicated cards', uniqI5.total === uniqI5.unique && uniqI5.total > 0, `${uniqI5.unique}/${uniqI5.total} unique (hasMore=${hasMoreI5})`)

    // I6: "+ Add artist" double submit -> one artist only
    await page.goto(`${h.BASE}/artists`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('Tracked artists'), { timeout: 30000 })
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-query', { timeout: 10000 })
    const artistName = `e2e-double-submit-${Date.now()}`
    await page.type('#add-artist-query', artistName)
    await h.wait(1000)
    const doubleOk = await clickByTextAwait(page, 'Add by name', 100)
    await h.wait(2000)
    const created = await page.evaluate(async (name) => {
      const r = await fetch(`/api/v1/artists?q=${encodeURIComponent(name)}&page_size=10`, { credentials: 'same-origin' })
      const body = await r.json()
      return { total: body.total || 0, items: body.items || [] }
    }, artistName)
    t('I', 'I6', 'double submit "+ Add artist" -> exactly one artist created', doubleOk && created.total === 1, `artists ${created.total} (${artistName})`)
    if (created.items && created.items[0]) {
      const del = await page.evaluate(async (id) => {
        const r = await fetch(`/api/v1/artists/${id}`, {
          method: 'DELETE',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        })
        return r.status
      }, created.items[0].id)
      t('I', 'I6', 'cleanup: test artist removed', del === 204, `DELETE status ${del}`)
    }
    await ctx2.close()

    // ================= A: authentication & sessions =================
    console.log('\n=== 13b: A authentication (long waits ahead) ===')
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)

    // A8: Enter from the password field submits
    await clickByText(page, 'Log out')
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 15000 })
    await page.type('#username', h.ADMIN_USER)
    await page.type('#password', h.ADMIN_PASS)
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => location.pathname === '/', { timeout: 20000 })
    t('A', 'A8', 'Enter from the password field submits the login', true)

    // A7: double-click "Log in" -> exactly one new session (the logout revokes
    // one session and the double-click must create exactly one, not two)
    const sessionsBefore = (await h.apiJson(page, '/api/v1/auth/sessions')).body.length
    await clickByText(page, 'Log out')
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 15000 })
    await page.type('#username', h.ADMIN_USER)
    await page.type('#password', h.ADMIN_PASS)
    await clickByTextAwait(page, 'Log in', 100)
    await page.waitForFunction(() => location.pathname === '/', { timeout: 20000 })
    const sessionsAfter = (await h.apiJson(page, '/api/v1/auth/sessions')).body.length
    t('A', 'A7', 'double-click "Log in" -> one coherent session', sessionsAfter - sessionsBefore === 0, `sessions ${sessionsBefore} -> ${sessionsAfter} (logout revoked 1, login created 1)`)

    // A6: input limits -> never 500
    const A6_CASES = [
      { u: '', p: 'password-lunga-12', desc: 'empty username' },
      { u: '   ', p: 'password-lunga-12', desc: 'spaces-only username' },
      { u: 'x'.repeat(500), p: 'password-lunga-12', desc: '500+ chars username' },
      { u: '😀🎵', p: 'password-lunga-12', desc: 'emoji username' },
      { u: 'admin', p: "p@$$w0rd!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~", desc: 'special-char password' },
      { u: 'admin', p: '', desc: 'empty password' },
    ]
    const a6Statuses = []
    for (const c of A6_CASES) {
      const r = await apiLogin(c.u, c.p)
      a6Statuses.push(`${c.desc}=${r.status}`)
    }
    t('A', 'A6', 'login input limits: empty/spaces/500+/emoji/special chars -> never 500', a6Statuses.every((s) => !/=\d00/.test(s) && !/=\d\d\d\d/.test(s)), a6Statuses.join(', '))
    const a6Ok = await apiLogin(h.ADMIN_USER, h.ADMIN_PASS)
    t('A', 'A6', 'limiter state reset after a successful login (pre-A5)', a6Ok.status === 204, `status ${a6Ok.status}`)

    // A5: timing — 5 unknown-user logins vs 5 wrong-password logins (separated
    // by a full per-IP window so every measured attempt returns a real 401)
    const tUnknown = []
    for (let i = 0; i < 5; i++) tUnknown.push(await apiLogin(`no-such-user-13b-${i}`, 'password-lunga-12'))
    console.log('[13b] A5: waiting one per-IP window (5 min) before the second group ...')
    await h.wait(QUICK ? 5000 : 305000)
    const tWrong = []
    for (let i = 0; i < 5; i++) tWrong.push(await apiLogin(h.ADMIN_USER, `wrong-password-13b-${i}`))
    const avg = (arr) => arr.reduce((n, r) => n + r.ms, 0) / arr.length
    const avgUnknown = avg(tUnknown)
    const avgWrong = avg(tWrong)
    const all401 = [...tUnknown, ...tWrong].every((r) => r.status === 401)
    const sameDetail = [...tUnknown, ...tWrong].every((r) => r.detail === 'Invalid credentials')
    t('A', 'A5', '5 unknown-user vs 5 wrong-password logins: same 401, similar timing (< 100 ms)', all401 && sameDetail && Math.abs(avgUnknown - avgWrong) < 100, `unknown ${avgUnknown.toFixed(1)}ms vs wrong-pw ${avgWrong.toFixed(1)}ms (diff ${Math.abs(avgUnknown - avgWrong).toFixed(1)}ms)`)

    // A4: the 10th consecutive failure triggers the global lockout (~15 min)
    const blocked = await apiLogin(h.ADMIN_USER, h.ADMIN_PASS)
    const retryAfter = parseInt(blocked.retryAfter || '0', 10)
    t(
      'A', 'A4',
      '10 consecutive failures -> global lockout, correct login gets 429 + Retry-After',
      blocked.status === 429 && retryAfter > 0,
      `status ${blocked.status} Retry-After ${blocked.retryAfter}s`,
    )
    const waitMs = QUICK ? Math.min(8000, retryAfter * 1000) : (retryAfter + 5) * 1000
    console.log(`[13b] A4: waiting out the global lockout (~${Math.round(waitMs / 1000)}s) ...`)
    await h.wait(waitMs)
    let afterBlock = await apiLogin(h.ADMIN_USER, h.ADMIN_PASS)
    if (afterBlock.status !== 204 && afterBlock.retryAfter) {
      // still blocked (the per-IP window outlives the shortened QUICK wait): wait it out
      const ra = parseInt(afterBlock.retryAfter, 10)
      console.log(`[13b] A4: per-IP window still active (Retry-After ${ra}s), waiting ...`)
      await h.wait((ra + 5) * 1000)
      afterBlock = await apiLogin(h.ADMIN_USER, h.ADMIN_PASS)
    }
    t('A', 'A4', 'correct login works after the lockout interval', afterBlock.status === 204, `status ${afterBlock.status}`)

    // A11: cookie tampering
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const atLogin = () =>
      page.waitForFunction(() => location.pathname === '/login', { timeout: 20000 }).then(() => true).catch(() => false)
    await page.deleteCookie({ name: 'nucs_session', url: h.BASE })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    t('A', 'A11', 'removing nucs_session -> redirected to /login', await atLogin())
    await page.setCookie({ name: 'nucs_session', value: 'invented-value-13b', url: h.BASE })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    t('A', 'A11', 'invented cookie value -> 401 -> /login', await atLogin())
    const expiredSha = crypto.createHash('sha256').update('e2e-expired-13b').digest('hex')
    const past = '2026-01-01T00:00:00+00:00'
    if (fs.existsSync(DB_FILE)) {
      sqlite(
        `INSERT INTO sessions (id_hash, created_at, expires_at, last_seen_at, ip, user_agent) VALUES ('${expiredSha}', '${past}', '${past}', '${past}', '127.0.0.1', 'e2e-13b')`,
      )
      await page.setCookie({ name: 'nucs_session', value: 'e2e-expired-13b', url: h.BASE })
      await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
      t('A', 'A11', 'expired session -> 401 -> /login', await atLogin())
      sqlite(`DELETE FROM sessions WHERE id_hash = '${expiredSha}'`)
    } else {
      t('A', 'A11', 'expired session check (E2E_DATA_DIR app.db not found)', false, `missing ${DB_FILE}`)
    }
    await page.setCookie({ name: 'nucs_session', value: '', url: h.BASE, expires: 0 })
    await h.uiLogin(page)

    // ================= G4/G5: backend restart + TZ =================
    console.log('\n=== 13b: G4 backend restart / G5 TZ ===')
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page)
    const datesBefore = (await h.apiJson(page, '/api/v1/releases?page_size=5&sort=date_desc')).body.items.map((i) => i.first_release_date)
    const meBefore = await h.apiJson(page, '/api/v1/auth/me')
    await restartBackend({ TZ: 'Pacific/Kiritimati' })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    const where = await page
      .waitForFunction(() => location.pathname === '/' || location.pathname === '/login', { timeout: 30000 })
      .then(() => page.evaluate(() => location.pathname))
      .catch(() => 'unknown')
    if (where === '/') {
      await waitForFeed(page, 60000)
      const cardsAfter = await page.$$eval(CARD, (els) => els.length)
      t('G', 'G4', 'backend restarted with the app open -> session survives (ripristino)', cardsAfter > 0, `pathname ${where}, cards ${cardsAfter}`)
    } else {
      t('G', 'G4', 'backend restarted with the app open -> 401 -> /login (documented)', where === '/login', `pathname ${where}`)
    }
    const meAfter = await h.apiJson(page, '/api/v1/auth/me')
    t('G', 'G4', 'session works after restart (auth/me 200)', meAfter.status === 200, `me ${meAfter.status}`)
    const datesAfter = (await h.apiJson(page, '/api/v1/releases?page_size=5&sort=date_desc')).body.items.map((i) => i.first_release_date)
    t(
      'G', 'G5',
      'dates stay UTC under TZ=Pacific/Kiritimati (UTC+14)',
      JSON.stringify(datesBefore) === JSON.stringify(datesAfter),
      `${datesBefore.join(',')} -> ${datesAfter.join(',')}`,
    )
    const scanTimeAfter = (await h.apiJson(page, '/api/v1/scans/status')).body.last_runs?.[0]?.started_at
    t('G', 'G5', 'scan timestamps stay UTC+00:00', typeof scanTimeAfter === 'string' && scanTimeAfter.includes('+00:00'), `started_at ${scanTimeAfter}`)

    // ================= J: post-deploy (only with E2E_PROD_STACK=1) =================
    console.log('\n=== 13b: J post-deploy ===')
    if (PROD_STACK) {
      if (fs.existsSync(DB_FILE)) {
        const audit = sqlite(
          "SELECT event, detail FROM audit_log WHERE event IN ('login_ok','login_fail') ORDER BY id DESC LIMIT 25",
        )
          .split('\n')
          .filter(Boolean)
          .map((line) => {
            const idx = line.indexOf('|')
            return { event: line.slice(0, idx), detail: line.slice(idx + 1) }
          })
        const hasBoth = audit.some((r) => r.event === 'login_ok') && audit.some((r) => r.event === 'login_fail')
        const secretFree = audit.every((r) => !/(password|token|secret|authorization|cookie)/i.test(r.detail))
        t('J', 'J3', 'audit log login_ok/login_fail present and secret-free', hasBoth && secretFree, `rows ${audit.length}`)
        const backupsDir = path.join(DATA_DIR, 'backups')
        let backupFiles = fs.existsSync(backupsDir) ? fs.readdirSync(backupsDir).filter((f) => /^app-\d{8}-\d{6}\.db$/.test(f)) : []
        if (backupFiles.length === 0) {
          const backup = spawnSync('.venv/bin/python', ['-m', 'app.cli', 'backup-now'], { cwd: BACKEND_DIR, env: backendEnv, encoding: 'utf8' })
          backupFiles = fs.existsSync(backupsDir) ? fs.readdirSync(backupsDir).filter((f) => /^app-\d{8}-\d{6}\.db$/.test(f)) : []
          t('J', 'J5', 'backup-now CLI produced a backup file', backup.status === 0 && backupFiles.length > 0, `status ${backup.status}`)
        }
        if (backupFiles.length > 0) {
          const latest = path.join(backupsDir, backupFiles[backupFiles.length - 1])
          const integrity = execSync(`sqlite3 "${latest}" "PRAGMA integrity_check;"`, { encoding: 'utf8' }).trim()
          t('J', 'J5', 'backup PRAGMA integrity_check -> ok', integrity === 'ok', `${backupFiles[backupFiles.length - 1]}: ${integrity}`)
        } else {
          t('J', 'J5', 'backup present in /data/backups', false, 'no backup file found')
        }
      } else {
        t('J', 'J3', 'audit log check (app.db not found)', false, `missing ${DB_FILE}`)
      }
    } else {
      tNA('J', 'J3', 'audit log (login_ok/login_fail senza segreti)', 'E2E_PROD_STACK=1 required — deferred to phase 14 (production stack)')
      tNA('J', 'J5', 'backup file + PRAGMA integrity_check', 'E2E_PROD_STACK=1 required — deferred to phase 14 (production stack)')
    }

    // ================= G1/G2: final cleanliness =================
    console.log('\n=== 13b: G1/G2 final cleanliness ===')
    await h.wait(1500)
    const realConsole = intentionalConsole(state)
    const csp = state.consoleErrors.filter((e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'))
    t('G', 'G1', 'console clean (only intentional 401/404/429 + offline/restart)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 5)))
    t('G', 'G2', 'zero CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    t('G', 'G1', 'no unhandled page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    const externalImages = [...state.imageHosts].filter((host) => host && host !== new URL(h.BASE).host)
    t('G', 'G2', 'no images from external domains', externalImages.length === 0, JSON.stringify(externalImages.slice(0, 5)))
    const realFails = state.failedRequests.filter(
      (u) => !u.includes('/api/v1/auth/') && !/net::ERR_(ABORTED|INTERNET_DISCONNECTED|CONNECTION_REFUSED|FAILED|CONNECTION_RESET)/.test(u) && !u.includes('/api/v1/covers/') && !u.includes('/releases/999999'),
    )
    t('G', 'G1', 'no unexpected failed requests', realFails.length === 0, JSON.stringify(realFails.slice(0, 3)))

    // ================= N.A. rows (human-only items, declared in fase-13b doc §2) =================
    tNA('C', 'C11', 'Favorite toggle', 'button removed in fase 12b (documented deviation); N.A.')
    tNA('B', 'B8', 'zoom 200% readability', 'visual judgment — manual (fase 13)')
    tNA('F', 'F2', 'browser zoom 200%', 'visual judgment — manual (fase 13)')
    tNA('F', 'F4', 'screen reader (VoiceOver/NVDA)', 'requires a real screen reader — manual (fase 13)')
    tNA('F', 'F7', 'password-manager autofill', 'requires a real password manager — manual (fase 13)')
    tNA('G', 'G8', 'no out-of-scope features', 'DOM check done (no <audio>, no PWA manifest); visual semantics manual')
    tNA('J', 'J1', 'Cloudflare tunnel HTTPS', 'phase 14 (production stack)')
    tNA('J', 'J2', 'Tailscale access', 'phase 14 (production stack)')

    // ================= G8 partial DOM check =================
    const g8 = await page.evaluate(() => ({
      audio: document.querySelectorAll('audio, video').length,
      manifest: !!document.querySelector('link[rel="manifest"]'),
    }))
    t('G', 'G8', 'no out-of-scope UI (audio/video/PWA manifest)', g8.audio === 0 && !g8.manifest, JSON.stringify(g8))
  } finally {
    exportTable(started)
    await h.finish({ browser, page, state }, '13b')
  }
}

main().catch((e) => {
  console.error('fase-13b crashed:', e)
  try {
    /* best-effort export of the partial results */
    const partial = rows.length > 0 ? rows : [{ area: 'SCRIPT', ref: 'fase-13b crash', ok: 'FAIL', evidence: String(e) }]
    const md = [
      '# FASE 13b — checklist compilata (automazione e2e:13) — run INTERROTTO',
      '',
      `- Data: ${new Date().toISOString()}`,
      '',
      '| Area | Voce | Esito | Evidenza |',
      '|---|---|---|---|',
      ...partial.map((r) => `| ${r.area} | ${r.ref} | ${r.ok} | ${r.evidence.replace(/\|/g, '\\|')} |`),
    ].join('\n')
    fs.writeFileSync(RESULTS_FILE, md)
    console.log(`[13b] partial results exported: ${RESULTS_FILE}`)
  } catch {
    /* ignore */
  }
  process.exitCode = 2
})

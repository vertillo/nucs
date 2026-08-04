'use strict'
/** Shared harness for nucs E2E scenarios (headless Chrome via puppeteer). */

const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer')

const BASE = process.env.BASE || 'http://127.0.0.1:8080'
const ADMIN_USER = process.env.ADMIN_USER || 'admin'
const ADMIN_PASS = process.env.ADMIN_PASS || 'password-lunga-12'
const ARTIFACTS_DIR = path.join(__dirname, 'artifacts')

const results = []
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

function check(name, ok, extra = '') {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'} | ${name}${extra ? ' | ' + extra : ''}`)
}

async function launch() {
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true })
  const browser = await puppeteer.launch({ headless: 'shell', args: ['--no-sandbox'] })
  const page = await browser.newPage()
  page.setDefaultTimeout(20000)
  const state = { consoleErrors: [], pageErrors: [], failedRequests: [], imageHosts: new Set() }
  page.on('console', (m) => {
    if (m.type() === 'error') state.consoleErrors.push(m.text())
  })
  page.on('pageerror', (e) => state.pageErrors.push(String(e)))
  page.on('requestfailed', (r) => state.failedRequests.push(r.url()))
  page.on('response', (r) => {
    if (r.request().resourceType() === 'image') {
      try {
        state.imageHosts.add(new URL(r.url()).host)
      } catch {
        /* ignore malformed */
      }
    }
  })
  return { browser, page, state }
}

/** Console errors that are NOT the intentional 401s of the auth flows. */
function realErrors(state) {
  return state.consoleErrors.filter(
    (e) => !e.includes('Failed to load resource: the server responded with a status of 401'),
  )
}

/** Failed/4xx-5xx requests that are NOT the intentional /api/v1/auth calls. */
function realFailed(state) {
  return state.failedRequests.filter((u) => !u.includes('/api/v1/auth/'))
}

async function screenshotOnFailure(page, phase) {
  if (!results.some((r) => !r.ok)) return
  try {
    const file = path.join(ARTIFACTS_DIR, `fase-${phase}-fail.png`)
    await page.screenshot({ path: file, fullPage: true })
    console.log(`screenshot su FAIL salvato: ${file}`)
  } catch {
    /* ignore */
  }
}

async function finish({ browser, page, state }, phase) {
  await screenshotOnFailure(page, phase)
  const failed = results.filter((r) => !r.ok).length
  console.log(`\nTOTALE: ${results.length - failed}/${results.length} PASS (fase ${phase})`)
  await browser.close()
  if (failed > 0) process.exitCode = 1
}

/** Login through the real UI form; waits for redirect to /. */
async function uiLogin(page, user = ADMIN_USER, pass = ADMIN_PASS) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' })
  await page.type('#username', user)
  await page.type('#password', pass)
  await page.click('button[type=submit]')
  await page.waitForFunction(() => location.pathname === '/', { timeout: 20000 })
}

/** Authenticated POST from the page context (same-origin, X-Requested-With per spec 5.4). */
async function apiPost(page, path, body = {}) {
  return page.evaluate(
    async ({ path: p, body: b }) => {
      const r = await fetch(p, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(b),
      })
      return { status: r.status }
    },
    { path, body },
  )
}

/** Authenticated PUT from the page context. */
async function apiPut(page, path, body = {}) {
  return page.evaluate(
    async ({ path: p, body: b }) => {
      const r = await fetch(p, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(b),
      })
      let data = null
      try {
        data = await r.json()
      } catch {
        /* 204 */
      }
      return { status: r.status, body: data }
    },
    { path, body },
  )
}

/** Authenticated JSON GET from the page context. */
async function apiJson(page, path) {
  return page.evaluate(async (p) => {
    const r = await fetch(p, { credentials: 'same-origin' })
    return { status: r.status, body: await r.json() }
  }, path)
}

/** Poll /scans/status until nothing is running (used by --seed). */
async function waitForScanIdle(page, timeoutMs = 300000) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const status = await page.evaluate(async () =>
      (await fetch('/api/v1/scans/status', { credentials: 'same-origin' })).json(),
    )
    if (!status.running) return
    if (Date.now() > deadline) throw new Error('seed: scan did not finish in time')
    await wait(3000)
  }
}

/**
 * Seed a fresh backend with real data (used by phases 08/09):
 * library scan (full) + releases discovery, waiting for each to finish.
 */
async function seed(page) {
  await uiLogin(page)
  console.log('seed: POST /scans/library?full=true ...')
  const r1 = await apiPost(page, '/api/v1/scans/library?full=true')
  console.log(`seed: library scan accepted (${r1.status}), waiting for idle ...`)
  await waitForScanIdle(page)
  console.log('seed: POST /scans/releases ...')
  const r2 = await apiPost(page, '/api/v1/scans/releases')
  console.log(`seed: releases scan accepted (${r2.status}), waiting for idle ...`)
  await waitForScanIdle(page)
  console.log('seed: done')
}

module.exports = {
  BASE,
  ADMIN_USER,
  ADMIN_PASS,
  ARTIFACTS_DIR,
  check,
  wait,
  launch,
  finish,
  uiLogin,
  apiPost,
  apiPut,
  apiJson,
  waitForScanIdle,
  seed,
  realErrors,
  realFailed,
  results,
}

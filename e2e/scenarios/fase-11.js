'use strict'
/**
 * Fase 11 — container verification: login, theme, logout, security headers,
 * public health endpoint. Designed to run today on http://127.0.0.1:8066
 * (docker-compose.dev.yml) and in fase 14 on https://nucs.<tailnet>.ts.net
 * (BASE env var). The app must be the containerized one (FRONTEND_DIST=/app/static).
 */
const h = require('../harness')

const bodyBg = (page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor)
const htmlHasDark = (page) => page.evaluate(() => document.documentElement.classList.contains('dark'))

async function headersOf(page, url) {
  return page.evaluate(async (u) => {
    const r = await fetch(u, { credentials: 'same-origin' })
    return { status: r.status, headers: Object.fromEntries(r.headers.entries()) }
  }, url)
}

async function main() {
  const { browser, page, state } = await h.launch()
  const isHttps = h.BASE.startsWith('https://')
  try {
    // 1. Login page, dark by default
    await page.goto(`${h.BASE}/login`, { waitUntil: 'networkidle0' })
    await h.wait(300)
    h.check('login page shows nucs', (await page.$eval('body', (b) => b.innerText)).includes('nucs'))
    h.check('login page dark class by default', await htmlHasDark(page))
    h.check('login page dark bg #0F0F0F', (await bodyBg(page)) === 'rgb(15, 15, 15)')

    // 2. Wrong credentials -> inline error, no redirect
    await page.type('#username', h.ADMIN_USER)
    await page.type('#password', 'wrong-password-123')
    await page.click('button[type=submit]')
    await page.waitForFunction(
      () =>
        document.querySelector('[role=alert]') &&
        document.querySelector('[role=alert]').textContent.includes('Invalid credentials'),
      { timeout: 10000 },
    )
    h.check('wrong password shows "Invalid credentials" inline', true)
    h.check('wrong password does NOT redirect', page.url().includes('/login'))

    // 3. Correct login -> redirect / with full navbar
    await page.goto(`${h.BASE}/login`, { waitUntil: 'networkidle0' })
    await page.type('#username', h.ADMIN_USER)
    await page.type('#password', h.ADMIN_PASS)
    await page.click('button[type=submit]')
    await page.waitForFunction(() => location.pathname === '/', { timeout: 20000 })
    await page.waitForSelector('nav', { timeout: 10000 })
    const navText = await page.$eval('nav', (n) => n.innerText)
    h.check('login redirects to /', true)
    h.check(
      'navbar has Feed/Artists/Settings/Log out',
      ['Feed', 'Artists', 'Settings', 'Log out'].every((s) => navText.includes(s)),
      navText.replace(/\n/g, ' '),
    )
    h.check('navbar has theme toggle', (await page.$('button[aria-label="Toggle theme"]')) !== null)

    // 4. Theme toggle in BOTH directions
    const toggle = 'button[aria-label="Toggle theme"]'
    await page.click(toggle)
    await h.wait(1500)
    h.check('click sun -> light (no .dark class)', !(await htmlHasDark(page)))
    h.check('click sun -> light bg #FFFFFF', (await bodyBg(page)) === 'rgb(255, 255, 255)', await bodyBg(page))
    await page.click(toggle)
    await h.wait(1500)
    h.check('click again -> back to dark (.dark class)', await htmlHasDark(page))
    h.check('click again -> dark bg #0F0F0F', (await bodyBg(page)) === 'rgb(15, 15, 15)', await bodyBg(page))

    // 5. Theme persistence across reload (server sync via PUT /settings)
    await page.click(toggle)
    await h.wait(2000)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await h.wait(1500)
    h.check(
      'light theme persists after reload',
      !(await htmlHasDark(page)) && (await bodyBg(page)) === 'rgb(255, 255, 255)',
      await bodyBg(page),
    )
    await page.click(toggle)
    await h.wait(2000)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await h.wait(1500)
    h.check(
      'dark theme persists after reload',
      (await htmlHasDark(page)) && (await bodyBg(page)) === 'rgb(15, 15, 15)',
      await bodyBg(page),
    )

    // 6. Security headers on the app (spec 5.5), fetched same-origin
    const app = await headersOf(page, h.BASE + '/')
    h.check('GET / returns 200', app.status === 200, `status ${app.status}`)
    h.check('CSP header present', !!app.headers['content-security-policy'], app.headers['content-security-policy'])
    h.check('CSP strict (script-src self)', (app.headers['content-security-policy'] || '').includes("script-src 'self'"))
    h.check('X-Content-Type-Options nosniff', app.headers['x-content-type-options'] === 'nosniff')
    h.check('X-Frame-Options DENY', app.headers['x-frame-options'] === 'DENY')
    h.check('Referrer-Policy same-origin', app.headers['referrer-policy'] === 'same-origin')
    h.check(
      'Permissions-Policy present',
      !!app.headers['permissions-policy'],
      app.headers['permissions-policy'],
    )
    h.check('X-Robots-Tag noindex', app.headers['x-robots-tag'] === 'noindex')
    h.check('no "server" header (--no-server-header)', !('server' in app.headers), JSON.stringify(app.headers['server']))
    h.check('no "x-powered-by" header', !('x-powered-by' in app.headers))
    h.check(
      isHttps ? 'HSTS present behind HTTPS' : 'no HSTS on plain HTTP',
      isHttps ? (app.headers['strict-transport-security'] || '').includes('max-age=31536000')
        : !('strict-transport-security' in app.headers),
      app.headers['strict-transport-security'] || '(absent)',
    )

    // 7. Public health endpoint and auth boundary
    const health = await headersOf(page, h.BASE + '/api/health')
    h.check('GET /api/health public 200', health.status === 200, `status ${health.status}`)
    const me = await page.evaluate(async () => {
      const r = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
      return r.status
    })
    // still logged in at this point -> 200; then check the 401 boundary after logout
    h.check('GET /auth/me with session 200', me === 200, `status ${me}`)

    // 8. Logout -> /login; protected / without session -> redirect /login
    await page.evaluate(() => {
      ;[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Log out').click()
    })
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 10000 })
    h.check('logout returns to /login', true)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 20000 })
    h.check('protected / without session redirects to /login', true)
    const me401 = await page.evaluate(async () => {
      const r = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
      return r.status
    })
    h.check('GET /auth/me without session 401', me401 === 401, `status ${me401}`)

    // 9. Console / CSP / network cleanliness
    await h.wait(1000)
    const realConsole = h.realErrors(state)
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    h.check('no console errors (excluding expected 401s)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 3)))
    h.check('no CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    h.check('no page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    h.check('no failed requests', h.realFailed(state).length === 0, JSON.stringify(h.realFailed(state).slice(0, 3)))
  } finally {
    await h.finish({ browser, page, state }, '11')
  }
}

main().catch((e) => {
  console.error('SCRIPT ERROR:', e)
  process.exit(2)
})

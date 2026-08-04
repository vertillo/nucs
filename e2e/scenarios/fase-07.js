'use strict'
/**
 * Fase 07 — browser verification (login, theme, navbar, logout, redirects, CSP).
 * Run against a backend serving the built frontend (FRONTEND_DIST=../frontend/dist)
 * with DEV_INSECURE_COOKIES=true. Env: BASE, ADMIN_USER, ADMIN_PASS.
 */
const h = require('../harness')

const bodyBg = (page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor)
const htmlHasDark = (page) => page.evaluate(() => document.documentElement.classList.contains('dark'))

async function main() {
  const { browser, page, state } = await h.launch()
  try {
    // 1. Login page, dark by default (spec 11.1)
    await page.goto(`${h.BASE}/login`, { waitUntil: 'networkidle0' })
    await h.wait(300)
    h.check('login page shows 🎵 nucs', (await page.$eval('body', (b) => b.innerText)).includes('nucs'))
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
    const errColor = await page.$eval('[role=alert]', (e) => getComputedStyle(e).color)
    h.check('wrong password shows "Invalid credentials" inline', true)
    h.check('error color is danger #E5484D', errColor === 'rgb(229, 72, 77)', errColor)
    h.check('wrong password does NOT redirect', page.url().includes('/login'))

    // 3. Correct login -> redirect to / with full navbar
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

    // 4. Theme toggle works in BOTH directions (regression: toggle stuck on light)
    const toggle = 'button[aria-label="Toggle theme"]'
    await page.click(toggle)
    await h.wait(1200)
    h.check('click sun -> light (no .dark class)', !(await htmlHasDark(page)))
    h.check('click sun -> light bg #FFFFFF', (await bodyBg(page)) === 'rgb(255, 255, 255)', await bodyBg(page))
    await page.click(toggle)
    await h.wait(1200)
    h.check('click again -> back to dark (.dark class)', await htmlHasDark(page))
    h.check('click again -> dark bg #0F0F0F', (await bodyBg(page)) === 'rgb(15, 15, 15)', await bodyBg(page))

    // 5. Persistence: light survives reload (PUT /settings server sync)
    await page.click(toggle)
    await h.wait(2000)
    await page.reload({ waitUntil: 'networkidle0' })
    await h.wait(1500)
    h.check(
      'light theme persists after reload (server sync)',
      !(await htmlHasDark(page)) && (await bodyBg(page)) === 'rgb(255, 255, 255)',
      await bodyBg(page),
    )

    // 6. Persistence: dark survives reload
    await page.click(toggle)
    await h.wait(2000)
    await page.reload({ waitUntil: 'networkidle0' })
    await h.wait(1500)
    h.check(
      'dark theme persists after reload (server sync)',
      (await htmlHasDark(page)) && (await bodyBg(page)) === 'rgb(15, 15, 15)',
      await bodyBg(page),
    )

    // 7. Logout -> /login; protected / without session -> redirect /login
    await page.evaluate(() => {
      ;[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Log out').click()
    })
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 10000 })
    h.check('logout returns to /login', true)
    await page.goto(`${h.BASE}/`, { waitUntil: 'networkidle0' })
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 20000 })
    h.check('protected / without session redirects to /login', true)

    // 8. Console / CSP / network cleanliness
    await h.wait(1000)
    const realConsole = h.realErrors(state)
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    h.check('no console errors (excluding expected 401s)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 3)))
    h.check('no CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    h.check('no page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    h.check('no failed requests (favicon 404 fixed)', h.realFailed(state).length === 0, JSON.stringify(h.realFailed(state).slice(0, 3)))
  } finally {
    await h.finish({ browser, page, state }, '07')
  }
}

main().catch((e) => {
  console.error('SCRIPT ERROR:', e)
  process.exit(2)
})

'use strict'
/**
 * Fase 09 — artists management + settings pages (browser, spec 11.2.4/11.2.5).
 * Seeds a fresh backend via API (library scan + discovery), then verifies the
 * two pages end to end: filters, ignore toggle, add/retry artist, per-section
 * settings saves with persistence, manual scans with polling, notify-test
 * guard, Spotify secret write-only behavior, theme persistence, password
 * change + session revocation across contexts, mobile layout.
 * Env: BASE, ADMIN_USER, ADMIN_PASS. Backend must run with DEV_INSECURE_COOKIES=true,
 * FRONTEND_DIST=../frontend/dist and MUSIC_LIBRARY_PATH pointing at a real library.
 */
const h = require('../harness')

const NEW_ARTIST = 'Zzznonexistentartist123'
const NEW_PASSWORD = 'nuova-password-99'

async function clickByText(page, text) {
  const ok = await page.evaluate((t) => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t)
    if (!btn) return false
    btn.click()
    return true
  }, text)
  if (!ok) throw new Error(`button not found: "${text}"`)
  return ok
}

/** Click the first button with the given text inside the section whose h2 matches. */
async function clickButtonInSection(page, sectionTitle, buttonText) {
  const ok = await page.evaluate(
    ({ title, text }) => {
      const section = [...document.querySelectorAll('section')].find(
        (s) => s.querySelector('h2')?.textContent.trim() === title,
      )
      if (!section) return false
      const btn = [...section.querySelectorAll('button')].find((b) => b.textContent.trim() === text)
      if (!btn) return false
      btn.click()
      return true
    },
    { title: sectionTitle, text: buttonText },
  )
  if (!ok) throw new Error(`button "${buttonText}" in section "${sectionTitle}" not found`)
}

async function waitForToast(page, text, timeout = 10000) {
  await page.waitForFunction((t) => document.body.innerText.includes(t), { timeout }, text)
}

/** Set a React-controlled input value (text/date/password). */
async function setInput(page, selector, value) {
  const ok = await page.evaluate(
    ({ sel, v }) => {
      const el = document.querySelector(sel)
      if (!el) return false
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(el, v)
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
      return true
    },
    { sel: selector, v: value },
  )
  if (!ok) throw new Error(`input not found: ${selector}`)
  return ok
}

async function gotoArtists(page) {
  await page.goto(`${h.BASE}/artists`, { waitUntil: 'networkidle0' })
  await page.waitForSelector('table tbody tr', { timeout: 20000 })
}

async function gotoSettings(page) {
  await page.goto(`${h.BASE}/settings`, { waitUntil: 'networkidle0' })
  await page.waitForFunction(
    () => [...document.querySelectorAll('section h2')].some((el) => el.textContent.trim() === 'Discovery'),
    { timeout: 20000 },
  )
}

function artistRowText(page, name) {
  return page.evaluate((n) => {
    const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
    return row ? row.textContent : null
  }, name)
}

async function main() {
  const { browser, page, state } = await h.launch()
  const notFound = []
  page.on('response', (r) => {
    if (r.status() === 404) notFound.push(r.url())
  })
  try {
    await h.seed(page)

    // ============ 1. /artists ============
    await gotoArtists(page)
    const rowCount = await page.evaluate(() => document.querySelectorAll('table tbody tr').length)
    h.check('artists list populated', rowCount > 0, `rows=${rowCount}`)
    const firstRow = await page.evaluate(() => document.querySelector('table tbody tr').textContent)
    h.check(
      'source badge shown (Artist/Album artist/Featuring/Contributor/Manual)',
      /Artist|Album artist|Featuring|Contributor|Manual/.test(firstRow),
      firstRow.slice(0, 80),
    )

    // Search filters (debounce)
    await setInput(page, 'input[aria-label="Search artist"]', 'daft')
    await page.waitForFunction(
      () => {
        const rows = [...document.querySelectorAll('table tbody tr')]
        return rows.length > 0 && rows.every((r) => r.textContent.toLowerCase().includes('daft'))
      },
      { timeout: 15000 },
    )
    const searchTexts = await page.evaluate(() =>
      [...document.querySelectorAll('table tbody tr')].map((r) => r.textContent.toLowerCase()),
    )
    h.check('search "daft" filters the list (debounce)', searchTexts.length > 0, `rows=${searchTexts.length}`)
    await setInput(page, 'input[aria-label="Search artist"]', '')
    await page.waitForFunction(() => document.querySelectorAll('table tbody tr').length > 1, {
      timeout: 15000,
    })

    // Ignore toggle -> artist shows under the "Ignored" filter
    // (make the first artist start un-ignored so the test is idempotent)
    await page.evaluate(() => {
      const btn = document.querySelector('button[role="switch"][aria-label^="Ignore "]')
      if (btn && btn.getAttribute('aria-checked') === 'true') btn.click()
    })
    await h.wait(1200)
    const toggledName = await page.evaluate(() => {
      const btn = document.querySelector('button[role="switch"][aria-label^="Ignore "]')
      if (!btn) return null
      const name = btn.getAttribute('aria-label').replace('Ignore ', '')
      btn.click()
      return name
    })
    h.check('ignore switch present and clickable', !!toggledName, `artist=${toggledName}`)
    await h.wait(1200)
    await page.select('#artist-ignored-filter', 'yes')
    await page.waitForFunction(
      (n) => {
        const rows = [...document.querySelectorAll('table tbody tr')]
        return rows.length > 0 && rows.some((r) => r.textContent.includes(n))
      },
      { timeout: 15000 },
      toggledName,
    )
    const ignoredText = await page.evaluate(() => document.querySelector('table tbody').textContent)
    h.check('toggled artist appears under the "Ignored" filter', ignoredText.includes(toggledName))
    await page.select('#artist-ignored-filter', 'all')
    await page.waitForFunction(
      () => document.querySelectorAll('table tbody tr').length > 1,
      { timeout: 15000 },
    )

    // + Add artist (new name) -> appears in list; duplicate -> inline error
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-name')
    await page.type('#add-artist-name', NEW_ARTIST)
    await clickByText(page, 'Add')
    await page.waitForFunction((n) => document.body.innerText.includes(n), { timeout: 15000 }, NEW_ARTIST)
    h.check('added artist appears in the list', true)
    await h.wait(10000) // background MusicBrainz match
    const addedRow = await artistRowText(page, NEW_ARTIST)
    h.check('new artist is unmatched after background match (esito visibile)', addedRow && addedRow.includes('Unmatched'), 'matched!')

    // Retry on the unmatched artist -> inline feedback
    const retryOk = await page.evaluate((n) => {
      const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
      const btn = row && [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Retry')
      if (!btn) return false
      btn.click()
      return true
    }, NEW_ARTIST)
    h.check('Retry button present on unmatched artist', retryOk)
    await page.waitForFunction(
      (n) => {
        const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
        return row ? row.textContent.includes('No match found') : false
      },
      { timeout: 40000 },
      NEW_ARTIST,
    )
    h.check('Retry shows inline outcome ("No match found")', true)

    // Duplicate add -> inline error in the modal
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-name')
    await page.type('#add-artist-name', NEW_ARTIST)
    await clickByText(page, 'Add')
    await page.waitForFunction(() => document.body.innerText.includes('Artist already exists'), { timeout: 10000 })
    h.check('duplicate add shows inline error', true)
    await clickByText(page, 'Cancel')

    // ============ 2. /settings: Discovery ============
    await gotoSettings(page)
    await setInput(page, '#discovery-from-date', '2025-06-15')
    await clickButtonInSection(page, 'Discovery', 'Save')
    await waitForToast(page, 'Saved ✓')
    await page.reload({ waitUntil: 'networkidle0' })
    await page.waitForSelector('#discovery-from-date')
    const savedDate = await page.evaluate(() => document.querySelector('#discovery-from-date').value)
    h.check('discovery date persists after reload', savedDate === '2025-06-15', `value=${savedDate}`)

    // No release type selected -> inline error
    await page.evaluate(() => {
      const d = [...document.querySelectorAll('section')].find(
        (s) => s.querySelector('h2')?.textContent.trim() === 'Discovery',
      )
      d.querySelectorAll('input[type="checkbox"]').forEach((c) => {
        if (c.checked) c.click()
      })
    })
    await clickButtonInSection(page, 'Discovery', 'Save')
    await page.waitForFunction(() => document.body.innerText.includes('Select at least one release type.'), {
      timeout: 10000,
    })
    h.check('no release type selected -> inline validation error', true)
    await page.evaluate(() => {
      const d = [...document.querySelectorAll('section')].find(
        (s) => s.querySelector('h2')?.textContent.trim() === 'Discovery',
      )
      const album = [...d.querySelectorAll('label')].find((l) => l.textContent.trim() === 'Albums')
      album.querySelector('input').click()
    })

    // ============ 3. /settings: Scans ============
    const baselineRuns = await page.evaluate(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      const table = s?.querySelector('table')
      return table ? table.querySelectorAll('tbody tr').length : -1
    })
    h.check('recent scans table populated from seed', baselineRuns >= 2, `rows=${baselineRuns}`)

    await clickButtonInSection(page, 'Scans', 'Scan library now')
    await page.waitForFunction(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      const btn = [...s.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Scan library now')
      return btn ? btn.getAttribute('aria-disabled') === 'true' : false
    }, { timeout: 15000 })
    h.check('scan button disabled while running', true)
    await page.waitForFunction(() => !!document.querySelector('.animate-spin'), { timeout: 20000 })
    h.check('spinner shown while running', true)
    await page.waitForFunction(
      (n) => {
        const s = [...document.querySelectorAll('section')].find(
          (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
        )
        const table = s?.querySelector('table')
        return table ? table.querySelectorAll('tbody tr').length > n : false
      },
      { timeout: 90000 },
      baselineRuns,
    )
    const newestRun = await page.evaluate(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      return s.querySelector('table tbody tr').textContent
    })
    h.check(
      'recent scans updated with library run (ok + key stat)',
      /Library/.test(newestRun) && /ok/.test(newestRun) && /artist/.test(newestRun),
      newestRun,
    )
    // The scan_runs row is written before the post-scan MusicBrainz auto-match
    // finishes; wait for the library scan to FULLY complete (button re-enabled)
    // so the next section can start a fresh releases scan.
    await page.waitForFunction(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      const btn = [...s.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Scan library now')
      return btn ? btn.getAttribute('aria-disabled') !== 'true' : false
    }, { timeout: 60000 })

    // Start a releases scan via the real button, then a second real click while
    // the run is in progress -> "Scan already in progress" (client guard, same
    // message the server 409 returns; the server contract is checked below).
    await clickButtonInSection(page, 'Scans', 'Check for new releases now')
    await page.waitForFunction(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      const btn = [...s.querySelectorAll('button')].find(
        (b) => b.textContent.trim() === 'Check for new releases now',
      )
      return btn ? btn.getAttribute('aria-disabled') === 'true' : false
    }, { timeout: 15000 })
    h.check('releases scan button disabled while running', true)
    const s409 = await h.apiPost(page, '/api/v1/scans/releases')
    h.check('server answers 409 while a scan runs', s409.status === 409)
    await clickButtonInSection(page, 'Scans', 'Check for new releases now')
    await waitForToast(page, 'Scan already in progress', 15000)
    h.check('second scan click during run -> "Scan already in progress"', true)
    await h.waitForScanIdle(page, 600000)
    await page.waitForFunction(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      const row = s?.querySelector('table tbody tr')
      return row ? row.textContent.includes('Releases') : false
    }, { timeout: 30000 })
    const releasesRun = await page.evaluate(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Scans',
      )
      const row = s.querySelector('table tbody tr')
      return row ? row.textContent : ''
    })
    h.check(
      'recent scans updated with releases run (ok + key stat)',
      /Releases/.test(releasesRun) && /ok/.test(releasesRun) && /release/.test(releasesRun),
      releasesRun,
    )

    // ============ 4. Notifications: test without URLs -> clear error ============
    await clickButtonInSection(page, 'Notifications', 'Send test notification')
    await waitForToast(page, 'Add at least one Apprise URL first.')
    h.check('notify-test without URLs -> clear error message', true)

    // ============ 5. Integrations: secret write-only ============
    await setInput(page, '#spotify-client-id', 'fake-client-id-123')
    await setInput(page, '#spotify-client-secret', 'fake-secret-456')
    await clickButtonInSection(page, 'Integrations', 'Save')
    await waitForToast(page, 'Saved ✓')
    await page.reload({ waitUntil: 'networkidle0' })
    await page.waitForSelector('#spotify-client-secret')
    const integ = await page.evaluate(() => ({
      idVal: document.querySelector('#spotify-client-id').value,
      idPh: document.querySelector('#spotify-client-id').placeholder,
      secretVal: document.querySelector('#spotify-client-secret').value,
      secretPh: document.querySelector('#spotify-client-secret').placeholder,
    }))
    h.check(
      'spotify secret never shown after reload (placeholder only)',
      integ.idVal === '' && integ.secretVal === '' && integ.idPh === '••••••••' && integ.secretPh === '••••••••',
      JSON.stringify(integ),
    )
    const settingsBody = await h.apiJson(page, '/api/v1/settings')
    const serialized = JSON.stringify(settingsBody.body)
    h.check(
      'GET /settings does not contain the secret value',
      !serialized.includes('fake-secret-456') && !serialized.includes('fake-client-id-123'),
    )

    // ============ 6. Appearance: theme switch, immediate + persisted ============
    await page.evaluate(() => {
      document.querySelector('input[type="radio"][value="light"]').click()
    })
    await page.waitForFunction(() => !document.documentElement.classList.contains('dark'), { timeout: 10000 })
    h.check('appearance Light applies immediately', true)
    await page.reload({ waitUntil: 'networkidle0' })
    await page.waitForFunction(() => !document.documentElement.classList.contains('dark'), { timeout: 10000 })
    h.check('light theme persists after reload', true)
    await clickByText(page, 'Log out')
    await page.waitForFunction(() => location.pathname === '/login', { timeout: 10000 })
    await h.uiLogin(page)
    await page.waitForFunction(() => !document.documentElement.classList.contains('dark'), { timeout: 10000 })
    h.check('light theme persists after logout/login', true)
    await gotoSettings(page)
    await page.evaluate(() => {
      document.querySelector('input[type="radio"][value="dark"]').click()
    })
    await page.waitForFunction(() => document.documentElement.classList.contains('dark'), { timeout: 10000 })
    h.check('switching back to Dark applies immediately', true)

    // ============ 7. Security: password change + session revocation ============
    // New password too short -> inline error
    await setInput(page, '#pw-current', h.ADMIN_PASS)
    await setInput(page, '#pw-new', 'short')
    await setInput(page, '#pw-repeat', 'short')
    await clickButtonInSection(page, 'Security', 'Update password')
    await page.waitForFunction(() => document.body.innerText.includes('at least 12 characters'), {
      timeout: 10000,
    })
    h.check('password < 12 chars -> inline error', true)

    // Wrong current password -> server error
    await setInput(page, '#pw-current', 'wrong-current-pass')
    await setInput(page, '#pw-new', NEW_PASSWORD)
    await setInput(page, '#pw-repeat', NEW_PASSWORD)
    await clickButtonInSection(page, 'Security', 'Update password')
    await page.waitForFunction(() => document.body.innerText.includes('Current password is incorrect'), {
      timeout: 15000,
    })
    h.check('wrong current password -> server error shown', true)

    // Correct change -> success message
    await setInput(page, '#pw-current', h.ADMIN_PASS)
    await setInput(page, '#pw-new', NEW_PASSWORD)
    await setInput(page, '#pw-repeat', NEW_PASSWORD)
    await clickButtonInSection(page, 'Security', 'Update password')
    await page.waitForFunction(() => document.body.innerText.includes('Password updated'), { timeout: 15000 })
    h.check('correct password change -> "Password updated"', true)

    // Second session in a fresh incognito context
    const ctx = await browser.createBrowserContext()
    const page2 = await ctx.newPage()
    await page2.goto(`${h.BASE}/login`, { waitUntil: 'networkidle0' })
    await page2.type('#username', h.ADMIN_USER)
    await page2.type('#password', NEW_PASSWORD)
    await page2.click('button[type="submit"]')
    await page2.waitForFunction(() => location.pathname === '/', { timeout: 20000 })
    h.check('second session (incognito) logs in with new password', true)
    await page2.reload({ waitUntil: 'networkidle0' })
    await page2.waitForFunction(() => location.pathname === '/', { timeout: 15000 })
    h.check('second session stays authenticated after reload', true)

    // Main page: sessions list shows the current badge; revoke others
    const currentBadge = await page.evaluate(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'Security',
      )
      return s ? s.textContent.includes('Current') : false
    })
    h.check('active sessions list marks the current session', currentBadge)
    await clickButtonInSection(page, 'Security', 'Revoke other sessions')
    await waitForToast(page, 'Other sessions revoked')
    h.check('revoke other sessions succeeds', true)

    // The incognito session is now dead: reload -> redirected to login
    await page2.reload({ waitUntil: 'networkidle0' })
    await page2.waitForFunction(() => location.pathname === '/login', { timeout: 15000 })
    h.check('revoked session receives 401 (redirected to login)', true)
    await ctx.close()

    // ============ 8. About ============
    const about = await page.evaluate(() => {
      const s = [...document.querySelectorAll('section')].find(
        (sec) => sec.querySelector('h2')?.textContent.trim() === 'About',
      )
      return s ? s.textContent : ''
    })
    h.check(
      'About shows version, counts and library path placeholder',
      about.includes('1.0.0') && about.includes('Configured via environment variable'),
      about.replace(/\s+/g, ' ').slice(0, 140),
    )

    // ============ 9. Mobile 375px ============
    await page.setViewport({ width: 375, height: 667 })
    await page.goto(`${h.BASE}/artists`, { waitUntil: 'networkidle0' })
    await page.waitForFunction(() => document.querySelectorAll('ul li').length > 0, { timeout: 15000 })
    const hScrollArtists = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    h.check('mobile 375px /artists: no horizontal scroll', hScrollArtists)
    const cardVisible = await page.evaluate(() => {
      const table = getComputedStyle(document.querySelector('table'))
      const list = getComputedStyle(document.querySelector('ul'))
      return table.display === 'none' && list.display !== 'none'
    })
    h.check('mobile 375px /artists: card list replaces the table', cardVisible)
    await page.goto(`${h.BASE}/settings`, { waitUntil: 'networkidle0' })
    await page.waitForFunction(
      () => [...document.querySelectorAll('section h2')].some((el) => el.textContent.trim() === 'Discovery'),
      { timeout: 15000 },
    )
    const hScrollSettings = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    h.check('mobile 375px /settings: no horizontal scroll', hScrollSettings)

    // ============ 10. Console / CSP / network cleanliness ============
    await h.wait(1000)
    // The intentional 4xx console messages are the wrong-current-password
    // attempt (400) and the direct server 409 probe; every other 4xx/5xx would
    // be a real problem.
    const realConsole = h
      .realErrors(state)
      .filter(
        (e) => !e.includes('status of 400 (Bad Request)') && !e.includes('status of 409 (Conflict)'),
      )
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    h.check('no console errors (excluding expected 401s)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 3)))
    h.check('no CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    h.check('no page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    h.check('no 404 responses (no invented endpoints)', notFound.length === 0, JSON.stringify(notFound.slice(0, 5)))
  } finally {
    await h.finish({ browser, page, state }, '09')
  }
}

main().catch((e) => {
  console.error('SCRIPT ERROR:', e)
  process.exit(2)
})

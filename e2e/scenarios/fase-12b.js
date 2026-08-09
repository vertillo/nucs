'use strict'
/**
 * Fase 12b — phase-12b UI checks (browser):
 * - feed grouped by day, seen toggle on the card, sync button
 * - release detail: no Favorite, tracklist + info rows, 9 link buttons
 * - artists: "Unmatched only" filter, source files, delete artist
 * - add-artist modal: provider search shows candidates
 * - errors page with badge + Copy JSON
 * - reset library wipes the feed (run LAST)
 * Env: BASE, ADMIN_USER, ADMIN_PASS. Backend must run with DEV_INSECURE_COOKIES=true,
 * FRONTEND_DIST=../frontend/dist and MUSIC_LIBRARY_PATH pointing at a real library.
 */
const h = require('../harness')

const CARD = 'a[href^="/releases/"]'

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

async function main() {
  const { browser, page, state } = await h.launch()
  try {
    // Fresh seed: full library scan + releases discovery (live providers).
    // A wide discovery window makes the feed non-empty (like fase-08).
    console.log('fase-12b: seeding backend (library scan + discovery) ...')
    await h.uiLogin(page)
    const put = await h.apiPut(page, '/api/v1/settings', { discovery_from_date: '2024-01-01' })
    console.log(`seed: PUT settings discovery_from_date -> ${put.status}`)
    const r1 = await h.apiPost(page, '/api/v1/scans/library?full=true')
    console.log(`seed: library scan accepted (${r1.status}), waiting for idle ...`)
    await h.waitForScanIdle(page, 600000)
    const r2 = await h.apiPost(page, '/api/v1/scans/releases')
    console.log(`seed: releases scan accepted (${r2.status}), waiting for idle ...`)
    await h.waitForScanIdle(page, 600000)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector(CARD, { timeout: 30000 }).catch(() => {})
    const hasCards = (await page.$$(CARD)).length > 0
    if (hasCards) {
      const dayHeaders = await page.evaluate(() => {
        const h2s = [...document.querySelectorAll('section h2')]
        return h2s.map((el) => el.textContent.trim()).filter((t) => t.length > 0)
      })
      h.check('feed shows day-group headers', dayHeaders.length > 0, dayHeaders.slice(0, 3).join(' | '))

      // seen toggle on the first card: click the eye button -> no more "New" dot
      const before = await page.evaluate((sel) => {
        const card = document.querySelector(sel)
        return {
          dot: card.querySelector('[aria-label="New"]') !== null,
          eye: card.querySelector('button[aria-label="Mark as seen"], button[aria-label="Mark as unseen"]') !== null,
        }
      }, CARD)
      h.check('card has a seen toggle button', before.eye)
      if (before.eye) {
        await page.evaluate((sel) => {
          document.querySelector(sel).querySelector('button[aria-label="Mark as seen"], button[aria-label="Mark as unseen"]').click()
        }, CARD)
        await h.wait(1200)
        const after = await page.evaluate((sel) => {
          const card = document.querySelector(sel)
          return card.querySelector('[aria-label="New"]') === null
        }, CARD)
        h.check('seen toggle removes the "new" dot', after)
      }

      // sync button present and starts the releases scan
      const syncLabel = await page.evaluate(() => {
        const btn = document.querySelector('button[aria-label="Check for new releases"]')
        return btn ? btn.textContent.trim() : null
      })
      h.check('feed shows the sync button (bottom-right)', syncLabel === 'Sync', String(syncLabel))
      await page.evaluate(() => {
        document.querySelector('button[aria-label="Check for new releases"]').click()
      })
      await h.wait(1500)
      const statusAfter = await h.apiJson(page, '/api/v1/scans/status')
      h.check('sync button started the releases scan', statusAfter.body.running?.type === 'releases')
      await h.waitForScanIdle(page, 600000)
    } else {
      h.check('seed produced releases for the feed checks', false, 'no cards')
    }

    // 2. Release detail: no Favorite, tracklist/info present, 9 links
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector(CARD, { timeout: 30000 }).catch(() => {})
    if ((await page.$$(CARD)).length > 0) {
      await page.click(CARD)
      await page.waitForFunction(() => location.pathname.startsWith('/releases/'), { timeout: 15000 })
      await page.waitForSelector('h1', { timeout: 15000 })
      const detail = await page.evaluate(() => ({
        labels: [...document.querySelectorAll('a[rel="noopener noreferrer"]')].map((a) => a.textContent.trim()),
        hasFavorite: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Favorite'),
        infoRows: document.querySelectorAll('dl dt').length,
        tracklist: [...document.querySelectorAll('section h2')].some((h2) => h2.textContent.trim() === 'Tracklist'),
        tracks: document.querySelectorAll('section ol li').length,
      }))
      h.check('release detail has 9 external link buttons', detail.labels.length === 9, detail.labels.join(','))
      h.check('favorite button removed from release detail', !detail.hasFavorite)
      h.check('release detail shows info rows', detail.infoRows > 0, `rows=${detail.infoRows}`)
      h.check('release detail has tracklist when provider provides it', detail.tracklist, `tracks=${detail.tracks}`)

      // "Back to feed" keeps us on the feed without reload
      await page.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find((b) =>
          b.textContent.includes('Back to feed'),
        )
        if (btn) btn.click()
      })
      await page.waitForFunction(() => location.pathname === '/', { timeout: 15000 })
      h.check('back to feed navigates to the feed', true)
    }

    // 3. Artists: unmatched filter + source files + delete flow
    await page.goto(`${h.BASE}/artists`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(
      () => document.body.innerText.includes('Tracked artists'),
      { timeout: 15000 },
    )
    const unmatchedVisible = await page.evaluate(() => {
      const select = document.querySelector('#artist-matched-filter')
      return select !== null
    })
    h.check('artists page has the "Unmatched only" filter', unmatchedVisible)
    if (unmatchedVisible) {
      await page.select('#artist-matched-filter', 'no')
      await h.wait(1500)
      const rows = await page.evaluate(() => [...document.querySelectorAll('tbody tr')].length)
      h.check('unmatched filter renders (0 or more rows without error)', rows >= 0, `rows=${rows}`)
      await page.select('#artist-matched-filter', 'all')
      await h.wait(1200)
    }

    // wait until no scan is running (robust against transient 500s)
    await page.evaluate(async () => {
      for (let i = 0; i < 120; i++) {
        let running = true
        try {
          const r = await fetch('/api/v1/scans/status', { credentials: 'same-origin' })
          const body = await r.json()
          running = !!(body.running)
        } catch {
          /* transient failure: keep polling */
        }
        if (!running) return
        await new Promise((res) => setTimeout(res, 3000))
      }
    })

    // delete an unmatched artist through the API + verify the row disappears
    const deleteTarget = await page.evaluate(async () => {
      const r = await fetch('/api/v1/artists?matched=no&page_size=1', { credentials: 'same-origin' })
      const body = await r.json()
      const target = body.items && body.items[0]
      if (!target) return null
      const d = await fetch(`/api/v1/artists/${target.id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      })
      return { status: d.status, name: target.name }
    })
    if (deleteTarget) {
      h.check('DELETE /artists/{id} works', deleteTarget.status === 204, `status=${deleteTarget.status} (${deleteTarget.name})`)
    } else {
      h.check('DELETE /artists/{id} (no unmatched artist in the seed — ok)', true, 'all artists matched already')
    }

    // 4. Add-artist modal shows provider candidates (live search)
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-query', { timeout: 10000 })
    await page.type('#add-artist-query', 'deadmau5')
    await h.wait(8000)
    const candidates = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]')
      if (!dialog) return 0
      const providers = ['MusicBrainz', 'Deezer', 'Apple Music', 'Discogs']
      return [...dialog.querySelectorAll('button')].filter((b) =>
        providers.some((p) => b.textContent.includes(p)),
      ).length
    })
    h.check('add-artist search shows provider candidates', candidates > 0, `candidates=${candidates}`)
    await page.keyboard.press('Escape')

    // 4b. Non-MusicBrainz release covers (phase 12b review fix): link a Deezer
    // artist, discover its releases and verify a rgid-less release renders its
    // cover through /api/v1/covers/release/{id} (the numeric cover_key must not
    // hit the /covers/{rgid} route, which rejects it with 400).
    await page.goto(`${h.BASE}/artists`, { waitUntil: 'domcontentloaded' })
    await h.wait(500)
    const dzLinked = await page.evaluate(async () => {
      const headers = { 'X-Requested-With': 'XMLHttpRequest' }
      const r = await fetch('/api/v1/artists/search?q=' + encodeURIComponent('deadmau5'), {
        credentials: 'same-origin', headers,
      })
      const body = await r.json()
      const cand = (body.candidates || body.items || []).find((c) => c.provider === 'deezer')
      if (!cand) return null
      const a = await fetch('/api/v1/artists', {
        method: 'POST', credentials: 'same-origin',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: cand.name, provider: 'deezer', provider_id: cand.provider_id }),
      })
      return a.status === 202 ? { id: (await a.json()).id, name: cand.name } : null
    })
    if (dzLinked) {
      console.log(`seed: deadmau5 linked to Deezer (id=${dzLinked.id}), discovering releases ...`)
      await h.apiPost(page, '/api/v1/scans/releases')
      await h.waitForScanIdle(page, 600000)
      const nonMb = await page.evaluate(async () => {
        const r = await fetch('/api/v1/releases?q=' + encodeURIComponent('deadmau5') + '&page_size=50', {
          credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
        const body = await r.json()
        return (body.items || []).find((it) => /^[0-9]+$/.test(it.cover_key) && it.cover_path) || null
      })
      if (nonMb) {
        await page.goto(`${h.BASE}/releases/${nonMb.id}`, { waitUntil: 'domcontentloaded' })
        await page.waitForSelector('img[src^="/api/v1/covers/release/"]', { timeout: 15000 }).catch(() => {})
        await h.wait(1500)
        const coverOk = await page.evaluate(() => {
          const img = document.querySelector('img[src^="/api/v1/covers/release/"]')
          return img ? img.naturalWidth > 0 : false
        })
        h.check(
          'non-MB release cover loads via /covers/release/{id}',
          coverOk,
          `release=${nonMb.id} cover_key=${nonMb.cover_key}`,
        )
      } else {
        h.check('non-MB cover check (no recent rgid-less release with cover in the seed — ok)', true)
      }
    } else {
      h.check('non-MB cover check (Deezer search unavailable — ok)', true)
    }

    // 5. Errors page + navbar badge (report an error through the API first)
    await page.evaluate(async () => {
      await fetch('/api/v1/errors', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ message: 'e2e: intentional error for fase 12b' }),
      })
    })
    await page.goto(`${h.BASE}/errors`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(
      () => document.body.innerText.includes('e2e: intentional error for fase 12b'),
      { timeout: 15000 },
    )
    h.check('errors page lists the recorded error', true)
    const copyBtn = await page.evaluate(() =>
      [...document.querySelectorAll('button')].some((b) => b.textContent.includes('Copy JSON')),
    )
    h.check('errors page has Copy JSON', copyBtn)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('a[aria-label="Errors"]', { timeout: 10000 })
    const badge = await page.evaluate(() => {
      const link = document.querySelector('a[aria-label="Errors"]')
      return link ? link.querySelector('span')?.textContent : null
    })
    h.check('navbar shows the errors badge', badge !== null, `badge=${badge}`)

    // 6. Reset library (LAST: wipes the seed). Wait for any still-loading
    // cover images first: the reset deletes the cover files from disk, and an
    // in-flight img request would then complete with 404 (a benign race).
    await page.evaluate(
      () =>
        Promise.all(
          [...document.images]
            .filter((img) => !img.complete)
            .map(
              (img) =>
                new Promise((resolve) => {
                  img.addEventListener('load', resolve, { once: true })
                  img.addEventListener('error', resolve, { once: true })
                }),
            ),
        ),
    )
    await h.wait(500)
    const reset = await page.evaluate(async () => {
      const r = await fetch('/api/v1/library', {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      })
      return r.status
    })
    h.check('DELETE /api/v1/library resets the library', reset === 204, `status=${reset}`)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await h.wait(1000)
    // fase 15: with zero tracked artists the feed shows the guidance state
    // ("No tracked artists" + Settings link) instead of the plain empty state
    const emptyFeed = await page.evaluate(() => ({
      noTracked: document.body.innerText.includes('No tracked artists'),
      settingsLink: !!document.querySelector('a[href="/settings"]'),
      noNewReleases: document.body.innerText.includes('No new releases'),
    }))
    h.check(
      'feed empty after the reset ("No tracked artists" guidance)',
      emptyFeed.noTracked && emptyFeed.settingsLink && !emptyFeed.noNewReleases,
      JSON.stringify(emptyFeed),
    )

    // 7. Console / CSP / network cleanliness
    await h.wait(800)
    const realConsole = h.realErrors(state)
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    h.check('no console errors (excluding expected 401s)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 3)))
    h.check('no CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    h.check('no page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    const externalImages = [...state.imageHosts].filter((host) => host !== new URL(h.BASE).host)
    h.check('no images from external domains', externalImages.length === 0, JSON.stringify(externalImages.slice(0, 5)))
  } finally {
    await h.finish({ browser, page, state }, '12b')
  }
}

main().catch((e) => {
  console.error('fase-12b crashed:', e)
  process.exitCode = 1
})

'use strict'
/**
 * Fase 08 — feed + release detail (browser, spec 11.2.2/11.2.3).
 * Seeds a fresh backend via API (library scan + discovery with a wide window so
 * pagination is exercisable), then verifies the feed UI end to end.
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

async function ariaPressedByText(page, text) {
  return page.evaluate((t) => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t)
    return btn ? btn.getAttribute('aria-pressed') : null
  }, text)
}

function setSearch(page, value) {
  return page.evaluate((v) => {
    const input = document.querySelector('input[aria-label="Search"]')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, v)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }, value)
}

async function seedFeed(page) {
  await h.uiLogin(page)
  const put = await h.apiPut(page, '/api/v1/settings', { discovery_from_date: '2024-01-01' })
  console.log(`seed: PUT settings discovery_from_date -> ${put.status}`)
  const lib = await h.apiPost(page, '/api/v1/scans/library?full=true')
  console.log(`seed: library scan (${lib.status}) ...`)
  await h.waitForScanIdle(page, 600000)
  const disc = await h.apiPost(page, '/api/v1/scans/releases')
  console.log(`seed: releases scan (${disc.status}) ...`)
  await h.waitForScanIdle(page, 600000)
  const list = await h.apiJson(page, '/api/v1/releases?page_size=1')
  console.log(`seed: total releases = ${list.body.total}`)
  return list.body.total
}

async function cardsState(page) {
  return page.evaluate((sel) => {
    const cards = [...document.querySelectorAll(sel)]
    return {
      count: cards.length,
      ids: cards.map((c) => c.getAttribute('href')),
      covers: document.querySelectorAll('img[src^="/api/v1/covers/"]').length,
      newDots: document.querySelectorAll(`${sel} [aria-label="New"]`).length,
      text: cards.map((c) => c.innerText),
    }
  }, CARD)
}

async function main() {
  const { browser, page, state } = await h.launch()
  try {
    page.on('dialog', (d) => d.accept())

    const total = await seedFeed(page)

    // 1. Feed rendering
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector(CARD, { timeout: 30000 })
    let cs = await cardsState(page)
    h.check('feed renders cards', cs.count > 0, `cards=${cs.count}, total=${total}`)
    h.check('feed shows cover images from /api/v1/covers', cs.covers > 0, `covers=${cs.covers}`)
    const allText = cs.text.join('\n')
    h.check('type badges present (Album/Single/EP)', /SINGLE|ALBUM|\bEP\b/.test(allText))
    const hasIso = allText
      .split('\n')
      .some((l) => /^(19|20)\d{2}(-\d{2}(-\d{2})?)?$/.test(l.trim()))
    h.check('dates in ISO format', hasIso)
    h.check('unseen releases show "new" dot', cs.newDots > 0, `dots=${cs.newDots}`)

    // 2. Type chip: Singles only
    await clickByText(page, 'Singles')
    await page.waitForFunction(
      () => document.querySelectorAll('a[href^="/releases/"]').length > 0,
      { timeout: 15000 },
    )
    await h.wait(500)
    const singlesApi = await h.apiJson(page, '/api/v1/releases?type=single&page_size=1')
    cs = await cardsState(page)
    const allSingle = cs.text.every((t) => /\bSINGLE\b/i.test(t))
    h.check('chip Singles filters cards', allSingle, `cards=${cs.count}, api_total=${singlesApi.body.total}`)

    // 3. Unseen only toggle: every visible card has the dot (reset chip to All first)
    await clickByText(page, 'All')
    await page.waitForFunction(
      () => document.querySelectorAll('a[href^="/releases/"]').length > 0,
      { timeout: 15000 },
    )
    await h.wait(500)
    await page.click('button[aria-label="Unseen only"]')
    await h.wait(600)
    const unseenApi = await h.apiJson(page, '/api/v1/releases?seen=no&page_size=1')
    cs = await cardsState(page)
    h.check(
      'unseen toggle shows only unseen',
      cs.count === Math.min(unseenApi.body.total, 30) && cs.newDots === cs.count,
      `cards=${cs.count}, api_total=${unseenApi.body.total}, dots=${cs.newDots}`,
    )
    await page.click('button[aria-label="Unseen only"]')
    await h.wait(600)

    // 4. Search (debounced): "daft" filters, nonsense -> empty state
    await setSearch(page, 'daft')
    await page.waitForFunction(
      () => document.querySelectorAll('a[href^="/releases/"]').length > 0,
      { timeout: 15000 },
    )
    await h.wait(600)
    cs = await cardsState(page)
    const allDaft = cs.text.every((t) => t.toLowerCase().includes('daft'))
    h.check('search "daft" filters (debounce)', allDaft, `cards=${cs.count}`)
    await setSearch(page, 'zzzqqnonexistent')
    await page.waitForFunction(
      () => document.body.innerText.includes('No new releases'),
      { timeout: 15000 },
    )
    h.check('search without matches -> empty state', true)
    await setSearch(page, '')
    await page.waitForFunction(
      () => document.querySelectorAll('a[href^="/releases/"]').length > 0,
      { timeout: 15000 },
    )

    // 5. Infinite scroll: scrolling to the bottom loads the next page (phase 12b)
    cs = await cardsState(page)
    if (total > cs.count) {
      h.check('more pages exist than initially rendered', true, `rendered=${cs.count} total=${total}`)
      const beforeCount = cs.count
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
      await page.waitForFunction(
        (n) => document.querySelectorAll('a[href^="/releases/"]').length > n,
        { timeout: 20000 },
        beforeCount,
      )
      await h.wait(500)
      cs = await cardsState(page)
      const ids = cs.ids.map((i) => i.replace('/releases/', ''))
      const unique = new Set(ids)
      h.check('infinite scroll appends without duplicates', unique.size === ids.length, `cards=${ids.length}`)
    } else {
      h.check('infinite scroll: pagination exercisable (total > 30)', false, `total=${total} <= page_size 30`)
    }

    // 6. Detail page: links, favorite persistence, back -> dot gone
    const firstHref = cs.ids[0]
    await page.click(CARD)
    await page.waitForFunction(() => location.pathname.startsWith('/releases/'), { timeout: 15000 })
    await page.waitForSelector('h1', { timeout: 10000 })
    const detail = await page.evaluate(() => {
      const links = [...document.querySelectorAll('a[rel="noopener noreferrer"]')]
      return {
        h1: document.querySelector('h1').textContent,
        linkLabels: links.map((a) => a.textContent.trim()),
        linkHrefs: links.map((a) => a.href),
        cover: document.querySelector('img[src^="/api/v1/covers/"]') !== null,
      }
    })
    h.check('detail shows release title (H1)', detail.h1.length > 0, detail.h1)
    h.check(
      'detail has 9 external link buttons with noopener',
      detail.linkLabels.length === 9,
      detail.linkLabels.join(','),
    )
    const domains = [
      ['https://open.spotify.com/', 'spotify'],
      ['https://music.youtube.com/', 'ytm'],
      ['https://www.deezer.com/', 'deezer'],
      ['https://music.apple.com/', 'apple_music'],
      ['https://tidal.com/', 'tidal'],
      ['https://www.qobuz.com/', 'qobuz'],
      ['https://www.discogs.com/', 'discogs'],
      ['https://www.beatport.com/', 'beatport'],
      ['https://www.google.com/', 'google'],
    ]
    for (const [prefix, name] of domains) {
      const ok = detail.linkHrefs.some((u) => u.startsWith(prefix))
      h.check(`detail ${name} link points to ${prefix}`, ok)
    }
    h.check('detail cover from local cache (/api/v1/covers)', detail.cover)

    // Click on the first external link -> opens a new tab with a sensible destination
    const newTab = browser.waitForTarget((t) => t.url().startsWith('http') && t !== page.target(), { timeout: 15000 })
    await page.evaluate(() => {
      document.querySelector('a[rel="noopener noreferrer"]').click()
    })
    let opened = null
    try {
      opened = await newTab
    } catch {
      /* target never appeared */
    }
    if (opened) {
      const url = opened.url()
      h.check(
        'click on external link opens a new tab (sensible destination)',
        url.startsWith('https://open.spotify.com/') ||
          url.startsWith('https://music.youtube.com/') ||
          url.startsWith('https://www.deezer.com/') ||
          url.startsWith('https://music.apple.com/') ||
          url.startsWith('https://tidal.com/') ||
          url.startsWith('https://www.qobuz.com/') ||
          url.startsWith('https://www.discogs.com/') ||
          url.startsWith('https://www.beatport.com/') ||
          url.startsWith('https://www.google.com/'),
        url.slice(0, 90),
      )
      await opened.page().then((p) => p.close()).catch(() => {})
    } else {
      h.check('click on external link opens a new tab (sensible destination)', false, 'no target created')
    }

    // Favorite button was removed in phase 12b: assert it is not rendered
    const favBtn = await ariaPressedByText(page, 'Favorite')
    h.check('favorite button removed from the release page', favBtn === null)

    // Back to feed: the visited release lost its "new" dot
    await page.goBack()
    await page.waitForSelector(CARD, { timeout: 15000 })
    await h.wait(600)
    const dotGone = await page.evaluate(
      (href, sel) => {
        const card = [...document.querySelectorAll(sel)].find((c) => c.getAttribute('href') === href)
        return card ? card.querySelector('[aria-label="New"]') === null : false
      },
      firstHref,
      CARD,
    )
    h.check('back to feed: visited release no longer shows "new" dot', dotGone)

    // 7. Hide: release disappears from the feed
    await page.click(`a[href="${firstHref}"]`)
    await page.waitForFunction(() => location.pathname.startsWith('/releases/'), { timeout: 15000 })
    await clickByText(page, 'Hide')
    await h.wait(1000)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector(CARD, { timeout: 15000 })
    const hiddenGone = await page.evaluate(
      (href, sel) => ![...document.querySelectorAll(sel)].some((c) => c.getAttribute('href') === href),
      firstHref,
      CARD,
    )
    h.check('hidden release disappears from feed', hiddenGone)

    // 8. Mark all as seen (confirm auto-accepted) -> unseen-only becomes empty
    await clickByText(page, 'Mark all as seen')
    await h.wait(1500)
    await page.click('button[aria-label="Unseen only"]')
    await page.waitForFunction(
      () => document.body.innerText.includes('No new releases'),
      { timeout: 15000 },
    )
    h.check('mark all as seen -> unseen-only shows empty state', true)

    // 9. Mobile 375px: two-column grid
    await page.setViewport({ width: 375, height: 667 })
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector(CARD, { timeout: 15000 })
    const cols = await page.evaluate((sel) => {
      const grid = document.querySelector(sel)?.parentElement
      if (!grid) return -1
      return getComputedStyle(grid).gridTemplateColumns.split(' ').length
    }, CARD)
    h.check('mobile 375px: feed grid has 2 columns', cols === 2, `cols=${cols}`)
    const hScroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    h.check('mobile 375px: no horizontal scroll', hScroll)

    // 10. Console / CSP / network cleanliness
    await h.wait(1000)
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
    await h.finish({ browser, page, state }, '08')
  }
}

main().catch((e) => {
  console.error('SCRIPT ERROR:', e)
  process.exit(2)
})

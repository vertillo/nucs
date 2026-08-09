'use strict'
/**
 * Fase 15 — automated browser verification of the phase-15 use cases
 * (correzioni dal feedback manuale, b6dc720). Coverage:
 *
 * API contracts (deterministic):
 * - GET /artists?sort=name_asc|name_desc ordering + unmatched_total coherence
 * - POST /artists with url: Deezer locale URL -> 202 linked (name resolved),
 *   unsupported URL -> 422, url+provider conflict -> 422,
 *   SoundCloud URL without name -> 422 (no provider name resolution)
 * - GET /artists/lookup for mb (aliases) and discogs without token -> 422
 * - POST /artists/{id}/rematch on an ignored artist -> resolved_split
 * - POST /releases/purge-orphans -> {removed} + releases_purged audit event
 *
 * Artists UI:
 * - Match column 4 states: MB (score + musicbrainz.org link), provider
 *   (Deezer + "open" link), Unmatched (+Retry), Split (no Retry)
 * - artist name links to the provider page (target=_blank rel=noreferrer)
 * - "{N} unmatched" badge == API unmatched_total
 * - Name header sort toggle (aria-sort + API order)
 * - Add by URL (Deezer locale URL; fallback name+URL when the provider is
 *   down), unsupported URL inline error
 * - candidate details panel (Add modal: details + "Track this artist" + Back)
 * - Retry modal: "Search again by name" on an unmatchable name -> modal stays
 *   open and NO fake "Matched on MusicBrainz" toast; free-text search ->
 *   candidate details -> "Link artist" -> external_url persisted
 *   (the "already resolved via split" toast is API-only: the UI never shows
 *   Retry on Split rows — verified via the rematch response instead)
 *
 * Feed UI:
 * - filters live in the URL (?q=, ?type=, ?unseen=) and survive navigation /
 *   back / forward (fase 15 WI-9, review race: type change within the debounce
 *   window is not overwritten)
 * - "Remove releases without artists" (purge-orphans): confirm dialog, toast
 *   with the removed count, release list totals consistent, orphaned release
 *   404, audit event; releases of deleted artists stay until the purge
 * - post-reset guidance state "No tracked artists" + Settings link (WI-8)
 *
 * Final: console/CSP/page-errors/external-images cleanliness.
 * Live-provider dependent steps (Deezer name resolution, candidate search)
 * degrade to documented N.A. rows when the provider is unreachable.
 *
 * Env: BASE, ADMIN_USER, ADMIN_PASS (harness defaults) + E2E_DATA_DIR
 * (default /tmp/nucs-e2e) for the audit-log check. Backend must run with
 * DATA_DIR=$E2E_DATA_DIR and DEV_INSECURE_COOKIES=true (see e2e/README.md).
 */
const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')
const h = require('../harness')

const DATA_DIR = process.env.E2E_DATA_DIR || '/tmp/nucs-e2e'
const DB_FILE = path.join(DATA_DIR, 'app.db')
const RESULTS_FILE = path.join(h.ARTIFACTS_DIR, 'fase-15-results.md')

const CARD = 'a[href^="/releases/"]'
const THEME_TOGGLE = 'button[aria-label="Toggle theme"]'
const UNSEEN_SWITCH = 'button[aria-label="Unseen only"]'
const FEED_SEARCH = 'input[aria-label="Search"]'
const ARTIST_SEARCH = 'input[aria-label="Search artist"]'
const DEEZER_LOCALE_URL = 'https://www.deezer.com/it/artist/6253'
const DEEZER_ID = '6253'
// different Deezer artist for the UI add (the API-level add above already
// created 6253 on the same DB)
const DEEZER_UI_URL = 'https://www.deezer.com/it/artist/27'
const DEEZER_UI_ID = '27'
const UNSUPPORTED_URL = 'https://www.example.com/artist/42'
const SOUNDCLOUD_URL = 'https://soundcloud.com/nucs-e2e-user'
const NO_MATCH_NAME = `z-e2e-nomatch-${Date.now()}`
const SPLIT_NAME = `a-e2e-split-${Date.now()}`

// --- results table (exported at the end) ---
const rows = []
function t(area, ref, name, ok, evidence = '') {
  h.check(`${area}${ref}: ${name}`, ok, evidence)
  rows.push({ area, ref: `${ref} — ${name}`, ok: ok ? 'PASS' : 'FAIL', evidence })
}
function tSkip(area, ref, name, reason) {
  rows.push({ area, ref: `${ref} — ${name}`, ok: 'N.A.', evidence: reason })
  console.log(`N.A. | ${area}${ref} | ${name} | ${reason}`)
}
function exportTable(started) {
  const dur = Math.round((Date.now() - started) / 1000)
  const md = [
    '# FASE 15 — checklist compilata (automazione e2e:15)',
    '',
    `- Data: ${new Date().toISOString()}`,
    `- Durata: ${Math.floor(dur / 60)}m ${dur % 60}s`,
    `- BASE: ${h.BASE}`,
    '',
    '| Area | Voce | Esito | Evidenza |',
    '|---|---|---|---|',
    ...rows.map((r) => `| ${r.area} | ${r.ref} | ${r.ok} | ${(r.evidence || '').replace(/\|/g, '\\|').replace(/\n/g, ' ')} |`),
    '',
  ].join('\n')
  fs.mkdirSync(h.ARTIFACTS_DIR, { recursive: true })
  fs.writeFileSync(RESULTS_FILE, md)
  console.log(`\n[15] results exported: ${RESULTS_FILE}`)
  console.log('\narea | PASS/FAIL/N.A. | evidenza')
  for (const r of rows) console.log(`${r.area} | ${r.ok} | ${(r.evidence || '').slice(0, 140)}`)
}

function sqlite(sql) {
  return execSync(`sqlite3 "${DB_FILE}" "${sql}"`, { encoding: 'utf8' }).trim()
}

// --- page helpers ---
async function clickByText(page, text) {
  const ok = await page.evaluate((txt) => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === txt)
    if (!btn) return false
    btn.click()
    return true
  }, text)
  if (!ok) throw new Error(`button not found: "${text}"`)
  return ok
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

/** Set a React-controlled input value like a user typing. */
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

async function setFeedSearch(page, value) {
  await setInput(page, FEED_SEARCH, value)
}

/** Poll the toast (role=status, disappears after 4s) until the regex matches. */
async function waitForToast(page, re, timeout = 10000) {
  const deadline = Date.now() + timeout
  for (;;) {
    const t = await page.evaluate(() => {
      const el = document.querySelector('[role="status"]')
      return el ? el.textContent.trim() : null
    })
    if (t && re.test(t)) return t
    if (Date.now() > deadline) return null
    await h.wait(150)
  }
}

async function currentToast(page) {
  return page.evaluate(() => {
    const el = document.querySelector('[role="status"]')
    return el ? el.textContent.trim() : null
  })
}

/** Authenticated fetch from the page context (X-Requested-With per spec 5.4). */
async function api(page, method, apiPath, body) {
  return page.evaluate(
    async ({ m, p, b }) => {
      const r = await fetch(p, {
        method: m,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: b !== undefined ? JSON.stringify(b) : undefined,
      })
      let data = null
      try {
        data = await r.json()
      } catch {
        /* 204 */
      }
      return { status: r.status, body: data }
    },
    { m: method, p: apiPath, b: body },
  )
}

async function waitForFeed(page, timeoutMs = 120000) {
  await page.waitForSelector(CARD, { timeout: timeoutMs }).catch(() => {})
}

async function gotoArtists(page) {
  await page.goto(`${h.BASE}/artists`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => {
      const row = document.querySelector('table tbody tr')
      return row && row.textContent.trim().length > 3
    },
    { timeout: 30000 },
  )
}

function artistRow(page, name) {
  return page.evaluate((n) => {
    const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
    if (!row) return null
    const matchCell = row.querySelectorAll('td')[2]
    return {
      rowText: row.textContent,
      nameIsLink: !!row.querySelector('td a[target="_blank"]'),
      matchText: matchCell ? matchCell.textContent.trim() : '',
      matchLink: matchCell ? matchCell.querySelector('a') : null,
      nameHref: row.querySelector('td a[target="_blank"]') ? row.querySelector('td a[target="_blank"]').href : null,
      hasRetry: [...row.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Retry'),
    }
  }, name)
}

function sqlite3exists() {
  try {
    execSync('sqlite3 --version', { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

async function main() {
  const { browser, page, state } = await h.launch()
  const started = Date.now()
  try {
    await page.setViewport({ width: 1280, height: 900 })
    // ================= SEED =================
    console.log('\n=== 15: seed (library scan + discovery) ===')
    await h.uiLogin(page)
    const put = await h.apiPut(page, '/api/v1/settings', { discovery_from_date: '2024-01-01' })
    console.log(`seed: PUT settings discovery_from_date -> ${put.status}`)
    const r1 = await h.apiPost(page, '/api/v1/scans/library?full=true')
    console.log(`seed: library scan accepted (${r1.status}), waiting for idle ...`)
    await h.waitForScanIdle(page, 900000)
    const r2 = await h.apiPost(page, '/api/v1/scans/releases')
    console.log(`seed: releases scan accepted (${r2.status}), waiting for idle ...`)
    await h.waitForScanIdle(page, 900000)
    const feed = await h.apiJson(page, '/api/v1/releases?page_size=1')
    console.log(`seed: feed total = ${feed.body.total}`)
    if (!feed.body.total) console.warn('[15] WARNING: empty feed — some feed checks will be N.A.')

    // ================= API: fase-15 contracts =================
    console.log('\n=== 15: API contracts ===')

    // sort ordering + unmatched_total coherence
    const sortApi = await api(page, 'GET', '/api/v1/artists?sort=name_desc&page_size=50')
    const sortApiAsc = await api(page, 'GET', '/api/v1/artists?sort=name_asc&page_size=50')
    const namesDesc = (sortApi.body.items || []).map((a) => a.name)
    const namesAsc = (sortApiAsc.body.items || []).map((a) => a.name)
    const sortedDesc = namesDesc.every((n, i) => i === 0 || namesDesc[i - 1].localeCompare(n) >= 0)
    const sortedAsc = namesAsc.every((n, i) => i === 0 || namesAsc[i - 1].localeCompare(n) <= 0)
    t('API', '15-1', 'GET /artists?sort=name_desc -> descending order', sortApi.status === 200 && sortedDesc, namesDesc.slice(0, 4).join(' | '))
    t('API', '15-1', 'GET /artists?sort=name_asc -> ascending order', sortApiAsc.status === 200 && sortedAsc, namesAsc.slice(0, 4).join(' | '))

    const unmatchedApi = await api(page, 'GET', '/api/v1/artists?matched=no&page_size=100')
    const unmatchedItems = unmatchedApi.body.items || []
    const unmatchedPredicate = unmatchedItems.every((a) => a.mbid == null && a.provider === 'manual')
    const allApi = await api(page, 'GET', '/api/v1/artists?page_size=1')
    t(
      'API', '15-2',
      'matched=no -> only mbid-null manual artists (multi-provider semantics)',
      unmatchedApi.status === 200 && unmatchedPredicate,
      `items=${unmatchedItems.length} unmatched_total=${allApi.body.unmatched_total}`,
    )
    t(
      'API', '15-2',
      'unmatched_total == count under the matched=no filter',
      allApi.body.unmatched_total === unmatchedApi.body.total,
      `${allApi.body.unmatched_total} vs ${unmatchedApi.body.total}`,
    )

    // POST /artists with url (Deezer locale URL): created already linked
    const addDz = await api(page, 'POST', '/api/v1/artists', { url: DEEZER_LOCALE_URL })
    let dzArtistId = null
    let dzName = null
    if (addDz.status === 202 && addDz.body && addDz.body.id) {
      dzArtistId = addDz.body.id
      dzName = addDz.body.name
      const item = addDz.body
      t(
        'API', '15-3',
        'POST /artists {url: Deezer /it/artist/} -> 202, linked (provider/id/external_url, name resolved)',
        item.provider === 'deezer' && item.provider_id === DEEZER_ID && item.external_url === DEEZER_LOCALE_URL && !!item.name,
        JSON.stringify({ name: item.name, provider: item.provider, provider_id: item.provider_id }),
      )
    } else {
      tSkip(
        'API', '15-3',
        'POST /artists {url: Deezer /it/artist/} -> 202, linked',
        `provider unavailable: ${addDz.status} ${addDz.body && addDz.body.detail} (URL parsing covered by the deterministic 422 cases)`,
      )
    }

    // deterministic 422s of the url flow
    const badUrl = await api(page, 'POST', '/api/v1/artists', { url: UNSUPPORTED_URL })
    t('API', '15-4', 'POST /artists {url: example.com} -> 422 Unsupported URL', badUrl.status === 422 && /Unsupported URL/.test(badUrl.body?.detail || ''), `status ${badUrl.status} ${badUrl.body?.detail || ''}`)
    const conflict = await api(page, 'POST', '/api/v1/artists', {
      name: 'x', url: DEEZER_LOCALE_URL, provider: 'deezer', provider_id: '123',
    })
    t('API', '15-4', 'POST /artists {url + provider pair} -> 422 conflict', conflict.status === 422 && /not both/.test(conflict.body?.detail || ''), `status ${conflict.status} ${conflict.body?.detail || ''}`)
    const noNameSc = await api(page, 'POST', '/api/v1/artists', { url: SOUNDCLOUD_URL })
    t(
      'API', '15-4',
      'POST /artists {soundcloud url, no name} -> 422 "Provide an artist name" (no name resolution for soundcloud)',
      noNameSc.status === 422 && /Provide an artist name for this provider/.test(noNameSc.body?.detail || ''),
      `status ${noNameSc.status} ${noNameSc.body?.detail || ''}`,
    )

    // GET /artists/lookup: mb (aliases) + discogs without token -> 422
    const mbArtist = (await api(page, 'GET', '/api/v1/artists?page_size=100')).body.items.find((a) => a.mbid)
    if (mbArtist) {
      const lookupMb = await api(page, 'GET', `/api/v1/artists/lookup?provider=mb&provider_id=${mbArtist.mbid}`)
      if (lookupMb.status === 200 && lookupMb.body.name) {
        t(
          'API', '15-5',
          'GET /artists/lookup?provider=mb -> name + aliases array',
          !!lookupMb.body.name && Array.isArray(lookupMb.body.aliases),
          `name=${lookupMb.body.name} aliases=${(lookupMb.body.aliases || []).length} disambiguation=${lookupMb.body.disambiguation || ''}`,
        )
      } else {
        tSkip('API', '15-5', 'GET /artists/lookup?provider=mb -> name + aliases', `mb lookup unavailable: ${lookupMb.status} ${lookupMb.body?.detail || ''}`)
      }
    } else {
      tSkip('API', '15-5', 'GET /artists/lookup?provider=mb -> name + aliases', 'no mb-matched artist in the seed')
    }
    const lookupDiscogs = await api(page, 'GET', '/api/v1/artists/lookup?provider=discogs&provider_id=1')
    t('API', '15-5', 'GET /artists/lookup?provider=discogs (no token) -> 422', lookupDiscogs.status === 422, `status ${lookupDiscogs.status} ${lookupDiscogs.body?.detail || ''}`)

    // rematch on an ignored artist -> resolved_split, never re-searched (guard)
    const splitSetup = await api(page, 'POST', '/api/v1/artists', { name: SPLIT_NAME })
    await api(page, 'PATCH', `/api/v1/artists/${splitSetup.body.id}`, { ignored: 1 })
    const rematchIgnored = await api(page, 'POST', `/api/v1/artists/${splitSetup.body.id}/rematch`)
    t(
      'API', '15-6',
      'rematch on an ignored artist -> resolved_split, no mbid, no false matched',
      rematchIgnored.status === 200 && rematchIgnored.body.resolved_split === true && rematchIgnored.body.matched === false && rematchIgnored.body.mbid === null,
      JSON.stringify({ matched: rematchIgnored.body.matched, resolved_split: rematchIgnored.body.resolved_split }),
    )

    // ================= Artists UI =================
    console.log('\n=== 15: artists UI ===')
    await gotoArtists(page)

    // Match column: MB-matched seed artist (score + musicbrainz link + linked name)
    const mbRow = await page.evaluate(() => {
      const row = [...document.querySelectorAll('table tbody tr')].find(
        (r) => r.querySelectorAll('td')[2] && r.querySelector('td a[href^="https://musicbrainz.org/artist/"]'),
      )
      if (!row) return null
      const cell = row.querySelectorAll('td')[2]
      const link = cell.querySelector('a')
      return {
        name: row.querySelector('td').textContent.trim(),
        cellText: cell.textContent.trim(),
        linkHref: link.href,
        linkRel: link.rel,
        linkTarget: link.target,
        nameLinkHref: row.querySelector('td a[target="_blank"]') ? row.querySelector('td a[target="_blank"]').href : null,
      }
    })
    if (mbRow) {
      const mbUrl = mbRow.linkHref.startsWith('https://musicbrainz.org/artist/') ? new URL(mbRow.linkHref).pathname.split('/')[2] : null
      t(
        'ART', '15-7',
        'Match column: MB state (score + musicbrainz.org link, target=_blank, rel=noreferrer)',
        mbRow.cellText.includes('MusicBrainz') && mbRow.linkTarget === '_blank' && mbRow.linkRel.includes('noreferrer') && !!mbUrl && mbRow.nameLinkHref === mbRow.linkHref,
        JSON.stringify({ name: mbRow.name, href: mbRow.linkHref, rel: mbRow.linkRel }),
      )
    } else {
      t('ART', '15-7', 'Match column: MB state', false, 'no MB-matched row rendered in the seed')
    }

    // badge "{N} unmatched" == API unmatched_total (default filters, re-fetched
    // at badge-read time so the comparison is not stale)
    const badge = await page.evaluate(() => {
      const el = document.querySelector('span[title="Artists without a match"]')
      return el ? el.textContent.trim() : null
    })
    const badgeN = badge ? parseInt((badge.match(/(\d+) unmatched/) || [])[1] || '-1', 10) : -1
    const apiUnmatchedNow = (await api(page, 'GET', '/api/v1/artists?page_size=1')).body.unmatched_total
    t(
      'ART', '15-8',
      'badge "{N} unmatched" matches the API unmatched_total',
      badgeN >= 0 && badgeN === apiUnmatchedNow,
      `badge="${badge}" api=${apiUnmatchedNow}`,
    )

    // sort header toggle
    const sortBefore = await page.evaluate(() => {
      const btn = document.querySelector('thead button[aria-sort]')
      return btn ? { sort: btn.getAttribute('aria-sort'), text: btn.textContent.trim() } : null
    })
    await page.evaluate(() => {
      const btn = document.querySelector('thead button[aria-sort]')
      if (btn) btn.click()
    })
    await h.wait(1200)
    const sortAfter = await page.evaluate(() => {
      const btn = document.querySelector('thead button[aria-sort]')
      const first = document.querySelector('table tbody tr td')
      return { sort: btn ? btn.getAttribute('aria-sort') : null, first: first ? first.textContent.trim() : null }
    })
    const firstDescApi = (await api(page, 'GET', '/api/v1/artists?sort=name_desc&page_size=1')).body.items[0]?.name
    t(
      'ART', '15-9',
      'Name header click toggles the sort (aria-sort) and the list follows',
      sortBefore && sortBefore.sort === 'ascending' && sortAfter.sort === 'descending' && !!firstDescApi && !!sortAfter.first && sortAfter.first.startsWith(firstDescApi),
      `${sortBefore && sortBefore.sort} -> ${sortAfter.sort}, first="${sortAfter.first && sortAfter.first.slice(0, 30)}" vs API "${firstDescApi}"`,
    )
    await page.evaluate(() => {
      const btn = document.querySelector('thead button[aria-sort]')
      if (btn) btn.click()
    })
    await h.wait(1200)

    // Unmatched render (created artist) + Retry modal flows
    const nomatchSetup = await api(page, 'POST', '/api/v1/artists', { name: NO_MATCH_NAME })
    await setInput(page, ARTIST_SEARCH, NO_MATCH_NAME)
    await page.waitForFunction(
      (n) => [...document.querySelectorAll('table tbody tr')].some((r) => r.textContent.includes(n)),
      { timeout: 15000 },
      NO_MATCH_NAME,
    )
    await h.wait(800)
    const umRow = await artistRow(page, NO_MATCH_NAME)
    t(
      'ART', '15-10',
      'unmatched artist renders "Unmatched" + Retry, name NOT linked',
      umRow && umRow.matchText.includes('Unmatched') && umRow.hasRetry && umRow.nameIsLink === false,
      umRow ? JSON.stringify({ match: umRow.matchText, retry: umRow.hasRetry, nameLink: umRow.nameIsLink }) : 'row not found',
    )

    // Split render: ignored artist without mbid -> "Split", no Retry
    await setInput(page, ARTIST_SEARCH, SPLIT_NAME)
    await page.waitForFunction(
      (n) => [...document.querySelectorAll('table tbody tr')].some((r) => r.textContent.includes(n)),
      { timeout: 15000 },
      SPLIT_NAME,
    )
    await h.wait(800)
    const spRow = await artistRow(page, SPLIT_NAME)
    t(
      'ART', '15-11',
      'ignored artist renders "Split" without Retry',
      spRow && spRow.matchText.includes('Split') && !spRow.hasRetry && spRow.matchText.indexOf('Unmatched') === -1,
      spRow ? spRow.matchText : 'row not found',
    )

    // Retry modal: "Search again by name" on an unmatchable name
    await setInput(page, ARTIST_SEARCH, NO_MATCH_NAME)
    await page.waitForFunction(
      (n) => [...document.querySelectorAll('table tbody tr')].some((r) => r.textContent.includes(n)),
      { timeout: 15000 },
      NO_MATCH_NAME,
    )
    await page.evaluate((n) => {
      const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
      const btn = row && [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Retry')
      if (btn) btn.click()
    }, NO_MATCH_NAME)
    await page.waitForSelector('[role="dialog"][aria-label="Match artist"]', { timeout: 10000 })
    t('ART', '15-12', 'Retry opens the match dialog', true)
    await clickByText(page, 'Search again by name')
    // wait for the rematch to finish (button back from "Searching…")
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Search again by name'),
      { timeout: 30000 },
    )
    await h.wait(600)
    const afterRetry = await page.evaluate(() => ({
      dialogOpen: !!document.querySelector('[role="dialog"][aria-label="Match artist"]'),
      toast: (() => {
        const el = document.querySelector('[role="status"]')
        return el ? el.textContent.trim() : null
      })(),
      noCandidates: document.body.innerText.includes('No candidates yet'),
    }))
    t(
      'ART', '15-12',
      '"Search again by name" on an unmatchable name -> NO fake "Matched on MusicBrainz", modal stays open',
      afterRetry.dialogOpen && (!afterRetry.toast || !afterRetry.toast.includes('Matched on MusicBrainz')),
      JSON.stringify(afterRetry),
    )

    // Retry free-text search -> candidate details panel -> "Link artist"
    await setInput(page, '#retry-artist-search', 'deadmau5')
    const freeCandidates = await (async () => {
      for (let i = 0; i < 60; i++) {
        const n = await page.evaluate(() => {
          const dialog = document.querySelector('[role="dialog"][aria-label="Match artist"]')
          return dialog ? [...dialog.querySelectorAll('button')].filter((b) => b.textContent.includes('deadmau5')).length : 0
        })
        if (n > 0) return n
        await h.wait(500)
      }
      return 0
    })()
    if (freeCandidates > 0) {
      await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"][aria-label="Match artist"]')
        const btn = [...dialog.querySelectorAll('button')].find((b) => b.textContent.includes('deadmau5'))
        if (btn) btn.click()
      })
      await page.waitForFunction(
        () => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Link artist'),
        { timeout: 15000 },
      )
      await h.wait(1500)
      const panel = await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"][aria-label="Match artist"]')
        const text = dialog ? dialog.textContent : ''
        return {
          hasLinkBtn: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Link artist'),
          hasDetails: /Disambiguation:|Aliases:|Type:|Country:|Genre:|albums/.test(text) || text.includes('Details unavailable.'),
        }
      })
      t(
        'ART', '15-13',
        'free search -> candidate details panel with "Link artist"',
        panel.hasLinkBtn && panel.hasDetails,
        JSON.stringify(panel),
      )
      await clickByText(page, 'Link artist')
      const linkedToast = await waitForToast(page, /Artist matched/)
      await h.wait(800)
      const dialogGone = await page.evaluate(() => !document.querySelector('[role="dialog"][aria-label="Match artist"]'))
      // no GET /artists/{id} route: verify the linked state via the list search
      const linkedList = await api(page, 'GET', `/api/v1/artists?q=${encodeURIComponent(NO_MATCH_NAME)}&page_size=10`)
      const linked = (linkedList.body.items || [])[0]
      t(
        'ART', '15-13',
        '"Link artist" -> toast "Artist matched", dialog closes, external_url persisted',
        linkedToast !== null && dialogGone && linked && linked.provider !== 'manual' && !!linked.external_url,
        JSON.stringify({ toast: linkedToast, provider: linked && linked.provider, url: linked && linked.external_url }),
      )
    } else {
      tSkip('ART', '15-13', 'retry free-text search -> candidate -> link', 'no provider candidates for "deadmau5" (providers unreachable)')
    }
    await page.keyboard.press('Escape').catch(() => {})

    // "Unmatched only" filter: every row is Unmatched or Split (never a provider/MB row)
    await setInput(page, ARTIST_SEARCH, '')
    await h.wait(800)
    await page.select('#artist-matched-filter', 'no')
    await h.wait(1500)
    const unmatchedRows = await page.evaluate(() =>
      [...document.querySelectorAll('table tbody tr')].map((r) => {
        const cell = r.querySelectorAll('td')[2]
        return cell ? cell.textContent.trim() : ''
      }),
    )
    t(
      'ART', '15-14',
      '"Unmatched only" filter -> every row is Unmatched or Split',
      unmatchedRows.length > 0 && unmatchedRows.every((c) => c.includes('Unmatched') || c.includes('Split')),
      `rows=${unmatchedRows.length} ${unmatchedRows.slice(0, 3).join(' | ')}`,
    )
    await page.select('#artist-matched-filter', 'all')
    await h.wait(800)

    // Add modal: unsupported URL inline error
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-url', { timeout: 10000 })
    await setInput(page, '#add-artist-url', UNSUPPORTED_URL)
    await clickByText(page, 'Add artist')
    await page.waitForFunction(
      () => {
        const alert = document.querySelector('[role="alert"]')
        return alert && alert.textContent.includes('Unsupported URL')
      },
      { timeout: 10000 },
    )
    t('ART', '15-15', 'Add by URL: unsupported URL -> inline error, modal stays open', true)
    await clickByText(page, 'Cancel')
    await h.wait(400)

    // Add modal: candidate details panel (live search) -> Track this artist + Back
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-query', { timeout: 10000 })
    await page.type('#add-artist-query', 'deadmau5')
    const addCandidates = await (async () => {
      for (let i = 0; i < 60; i++) {
        const n = await page.evaluate(() => {
          const dialog = document.querySelector('[role="dialog"]')
          return dialog ? [...dialog.querySelectorAll('button')].filter((b) => b.textContent.includes('deadmau5')).length : 0
        })
        if (n > 0) return n
        await h.wait(500)
      }
      return 0
    })()
    if (addCandidates > 0) {
      await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"]')
        const btn = [...dialog.querySelectorAll('button')].find((b) => b.textContent.includes('deadmau5'))
        if (btn) btn.click()
      })
      await page.waitForFunction(
        () => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Track this artist'),
        { timeout: 15000 },
      )
      await h.wait(1500)
      const panelAdd = await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"]')
        const text = dialog ? dialog.textContent : ''
        return {
          trackBtn: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Track this artist'),
          details: /Disambiguation:|Aliases:|Type:|Country:|Genre:|albums/.test(text) || text.includes('Details unavailable.'),
          backBtn: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === '← Back'),
        }
      })
      t(
        'ART', '15-16',
        'Add modal: candidate click -> details panel (Track this artist + Back)',
        panelAdd.trackBtn && panelAdd.details && panelAdd.backBtn,
        JSON.stringify(panelAdd),
      )
      await page.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '← Back')
        if (btn) btn.click()
      })
      await h.wait(600)
      const backRestored = await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"]')
        return !!dialog && [...dialog.querySelectorAll('button')].some((b) => b.textContent.includes('deadmau5'))
      })
      t('ART', '15-16', 'Add modal: "← Back" restores the candidate list', backRestored)
    } else {
      tSkip('ART', '15-16', 'add-modal candidate details panel', 'no provider candidates for "deadmau5" (providers unreachable)')
    }
    await page.keyboard.press('Escape').catch(() => {})
    await h.wait(400)

    // Add by URL in the UI (Deezer locale URL, empty name): artist created linked.
    // If the provider is down (name resolution fails), fall back to name+URL so
    // the URL-parse+link UI path is still verified deterministically.
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-url', { timeout: 10000 })
    await setInput(page, '#add-artist-url', DEEZER_UI_URL)
    await clickByText(page, 'Add artist')
    let uiAddUrlOk = true
    const addedToast = await waitForToast(page, /Artist added/, 15000)
    if (addedToast === null) {
      const err = await page.evaluate(() => {
        const alert = document.querySelector('[role="alert"]')
        return alert ? alert.textContent.trim() : null
      })
      uiAddUrlOk = false
      console.log(`[15] add-by-URL resolution failed (${err}); retrying with name+URL ...`)
      await setInput(page, '#add-artist-url', DEEZER_UI_URL)
      await setInput(page, '#add-artist-query', `E2E Deezer URL Test ${Date.now()}`)
      await clickByText(page, 'Add artist')
      const fallbackToast = await waitForToast(page, /Artist added/, 15000)
      if (fallbackToast === null) throw new Error('add-by-URL (name+URL fallback) did not complete')
    }
    await h.wait(800)
    // the UI-added artist is the one linked to provider deezer with id 27
    const uiArtist = (await api(page, 'GET', '/api/v1/artists?page_size=100')).body.items.find(
      (a) => a.provider === 'deezer' && a.provider_id === DEEZER_UI_ID,
    )
    const addedName = uiArtist ? uiArtist.name : null
    if (addedName) {
      // fresh mount: reload the page so the table state is deterministic
      // (the add-modal/refetch transitions can transiently blank the rows)
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForFunction(() => {
        const row = document.querySelector('table tbody tr')
        return row && row.textContent.trim().length > 3
      }, { timeout: 30000 })
      await h.wait(800)
      // single self-contained probe: poll the table until the row appears and
      // return the match cell/name link data (same mechanism as the diag)
      const probe = await page.evaluate(async (n) => {
        const deadline = Date.now() + 15000
        for (;;) {
          const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
          if (row) {
            const matchCell = row.querySelectorAll('td')[2]
            const nameLink = row.querySelector('td a[target="_blank"]')
            return {
              found: true,
              rowText: row.textContent.trim().slice(0, 90),
              matchText: matchCell ? matchCell.textContent.trim() : '',
              matchHref: matchCell && matchCell.querySelector('a') ? matchCell.querySelector('a').href : null,
              nameHref: nameLink ? nameLink.href : null,
            }
          }
          if (Date.now() > deadline) break
          await new Promise((r) => setTimeout(r, 300))
        }
        return {
          found: false,
          rows: [...document.querySelectorAll('table tbody tr')].map((r) => r.textContent.trim().slice(0, 50)).slice(0, 6),
          inputValue: document.querySelector('input[aria-label="Search artist"]')?.value ?? null,
        }
      }, addedName)
      t(
        'ART', '15-17',
        'Add by URL (UI): artist created linked, Match column shows "Deezer" + open link, name linked',
        // external_url preserves the URL as given (locale prefix included), so
        // match only the host + the artist id path
        probe.found && probe.matchText.includes('Deezer') && probe.matchHref && probe.matchHref.includes('www.deezer.com/') && probe.matchHref.includes(`artist/${DEEZER_UI_ID}`) && probe.nameHref === probe.matchHref,
        JSON.stringify(probe),
      )
    } else {
      t('ART', '15-17', 'Add by URL (UI): artist created linked, Match column shows "Deezer"', false, 'ui-added artist not found via API')
    }
    if (!uiAddUrlOk) tSkip('API', '15-3b', 'add-by-URL name resolution (provider down) -> name+URL fallback used', 'provider unreachable; UI link path verified via name+URL')
    await setInput(page, ARTIST_SEARCH, '')
    await h.wait(600)

    // ================= Feed UI =================
    console.log('\n=== 15: feed UI (query params + purge + guidance state) ===')
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await waitForFeed(page, 60000)
    await clickByText(page, 'All')
    await page.click('button[aria-label="Unseen only"]').catch(() => {})
    if (
      await page.evaluate(() =>
        document.querySelector('button[aria-label="Unseen only"]')?.getAttribute('aria-checked') === 'true',
      )
    ) {
      await page.click('button[aria-label="Unseen only"]')
    }
    await setFeedSearch(page, '')
    await h.wait(800)
    const cleanUrl = await page.evaluate(() => window.location.search)
    console.log(`[15] feed clean-up url="${cleanUrl}"`)

    // filters land in the URL
    await setFeedSearch(page, 'avicii')
    await h.wait(900)
    const u1 = await page.evaluate(() => window.location.search)
    await clickByText(page, 'Singles')
    const u2 = await page.evaluate(() => window.location.search)
    await page.click(UNSEEN_SWITCH)
    const u3 = await page.evaluate(() => window.location.search)
    t(
      'FEED', '15-18',
      'filters persist in the URL (?q=, ?type=, ?unseen=)',
      u1.includes('q=avicii') && u2.includes('q=avicii') && u2.includes('type=single') && u3.includes('unseen=1'),
      JSON.stringify({ afterSearch: u1, afterType: u2, afterUnseen: u3 }),
    )

    // navigation to /artists and back preserves filters + input value
    await page.click('a[aria-label="Artists"]')
    await page.waitForFunction(() => location.pathname === '/artists', { timeout: 15000 })
    await page.goBack()
    await page.waitForFunction(() => location.pathname === '/', { timeout: 15000 })
    await h.wait(1000)
    const backState = await page.evaluate(() => ({
      search: window.location.search,
      input: document.querySelector('input[aria-label="Search"]') ? document.querySelector('input[aria-label="Search"]').value : null,
      unseen: (() => {
        const s = document.querySelector('button[aria-label="Unseen only"]')
        return s ? s.getAttribute('aria-checked') : null
      })(),
      singles: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Singles' && b.getAttribute('aria-pressed') === 'true'),
    }))
    t(
      'FEED', '15-19',
      'back from /artists -> filters and search input restored (URL params)',
      backState.search.includes('q=avicii') && backState.search.includes('type=single') && backState.search.includes('unseen=1') && backState.input === 'avicii' && backState.unseen === 'true' && backState.singles,
      JSON.stringify(backState),
    )
    // forward again keeps them too
    await page.goForward()
    await page.waitForFunction(() => location.pathname === '/artists', { timeout: 15000 })
    await page.goBack()
    await page.waitForFunction(() => location.pathname === '/', { timeout: 15000 })
    const fwdBack = await page.evaluate(() => window.location.search)
    t('FEED', '15-19', 'forward/back cycle keeps the URL filters', fwdBack.includes('q=avicii') && fwdBack.includes('type=single'), fwdBack)

    // race: filter change within the debounce window is not overwritten
    await clickByText(page, 'All')
    await page.click(UNSEEN_SWITCH)
    await setFeedSearch(page, '')
    await h.wait(800)
    await setFeedSearch(page, 'beyonce')
    await clickByText(page, 'EPs') // immediately (< 300 ms debounce)
    await h.wait(900)
    const raceUrl = await page.evaluate(() => window.location.search)
    t(
      'FEED', '15-20',
      'race: type change within the q debounce window -> both filters active',
      raceUrl.includes('q=beyonce') && raceUrl.includes('type=ep'),
      raceUrl,
    )
    await clickByText(page, 'All')
    await setFeedSearch(page, '')
    await h.wait(800)

    // purge-orphans: releases of a deleted artist stay until the purge
    const feedBefore = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.total
    const victims = (await api(page, 'GET', '/api/v1/artists?page_size=100')).body.items.filter((a) => a.releases_count > 0)
    let purgeOrphanId = null
    if (victims.length > 0 && feedBefore > 0) {
      const victim = victims[0]
      const vReleases = (await api(page, 'GET', `/api/v1/releases?q=${encodeURIComponent(victim.name)}&page_size=5`)).body.items || []
      purgeOrphanId = vReleases[0] ? vReleases[0].id : null
      const del = await api(page, 'DELETE', `/api/v1/artists/${victim.id}`)
      await h.wait(800)
      const feedAfterDelete = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.total
      t(
        'FEED', '15-21',
        'releases of a deleted artist stay in the feed until the purge',
        del.status === 204 && feedAfterDelete === feedBefore && purgeOrphanId !== null,
        `total ${feedBefore} -> ${feedAfterDelete} (orphan release ${purgeOrphanId})`,
      )
    } else {
      tSkip('FEED', '15-21', 'orphaned releases kept after artist deletion', `no artist with releases in the seed (total=${feedBefore})`)
    }

    // UI: "Remove releases without artists" with confirm -> toast + totals
    if (purgeOrphanId !== null) {
      await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
      await waitForFeed(page, 60000)
      page.once('dialog', (d) => d.accept())
      await clickByText(page, 'Remove releases without artists')
      const purgeToast = await waitForToast(page, /Removed \d+ releases? without artists/, 15000)
      const nRemoved = purgeToast ? parseInt((purgeToast.match(/Removed (\d+)/) || [])[1] || '0', 10) : 0
      const feedAfter = (await h.apiJson(page, '/api/v1/releases?page_size=1')).body.total
      const orphanAfter = await api(page, 'GET', `/api/v1/releases/${purgeOrphanId}`)
      t(
        'FEED', '15-22',
        'purge button (confirm) -> toast "Removed N releases without artists", N>=1, total consistent, orphan 404',
        purgeToast !== null && nRemoved >= 1 && feedAfter === feedBefore - nRemoved && orphanAfter.status === 404,
        `toast="${purgeToast}" before=${feedBefore} after=${feedAfter} orphan=${orphanAfter.status}`,
      )
      // idempotent second run via the API + audit event
      const purgeAgain = await api(page, 'POST', '/api/v1/releases/purge-orphans')
      t('FEED', '15-22', 'purge-orphans is idempotent (second run removes 0)', purgeAgain.status === 200 && purgeAgain.body.removed === 0, `removed=${purgeAgain.body.removed}`)
    } else {
      tSkip('FEED', '15-22', 'purge-orphans UI flow', 'no orphaned release created (no artist with releases)')
    }
    const auditRows = sqlite3exists() && fs.existsSync(DB_FILE) ? sqlite("SELECT count(*) FROM audit_log WHERE event='releases_purged'") : 'no-sqlite'
    t(
      'FEED', '15-22',
      'audit log has releases_purged events',
      auditRows !== 'no-sqlite' && parseInt(auditRows, 10) > 0,
      `rows=${auditRows}`,
    )

    // ================= No tracked artists guidance (WI-8) =================
    // wait for in-flight cover images so the reset does not 404 them mid-flight
    // (timeout-guarded: a stuck image request must not hang the whole run)
    await page.evaluate(
      () =>
        Promise.race([
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
          new Promise((resolve) => setTimeout(resolve, 5000)),
        ]),
    )
    await h.wait(500)
    const reset = await api(page, 'DELETE', '/api/v1/library')
    t('FEED', '15-23', 'library reset (DELETE /api/v1/library)', reset.status === 204, `status ${reset.status}`)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('No tracked artists'), { timeout: 20000 })
    const guidance = await page.evaluate(() => ({
      noTracked: document.body.innerText.includes('No tracked artists'),
      settingsLink: !!document.querySelector('a[href="/settings"]'),
      hint: document.body.innerText.includes('Run a library scan from'),
    }))
    t('FEED', '15-23', 'post-reset feed -> "No tracked artists" guidance + Settings link', guidance.noTracked && guidance.settingsLink && guidance.hint, JSON.stringify(guidance))

    // ================= Final cleanliness =================
    console.log('\n=== 15: console / CSP / network cleanliness ===')
    await h.wait(1200)
    const realConsole = state.consoleErrors.filter((e) => {
      if (e.includes('status of 401')) return false
      if (e.includes('status of 404')) return false
      if (e.includes('status of 422')) return false
      if (e.includes('status of 429')) return false
      if (/net::ERR_(INTERNET_DISCONNECTED|CONNECTION_REFUSED|ABORTED|FAILED|CONNECTION_RESET)/.test(e)) return false
      return true
    })
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    t('FIN', '15-24', 'console clean (only intentional 401/404/422/429)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 5)))
    t('FIN', '15-24', 'zero CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    t('FIN', '15-24', 'no unhandled page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    const externalImages = [...state.imageHosts].filter((host) => host && host !== new URL(h.BASE).host)
    t('FIN', '15-24', 'no images from external domains', externalImages.length === 0, JSON.stringify(externalImages.slice(0, 5)))
    const realFails = state.failedRequests.filter(
      (u) => !u.includes('/api/v1/auth/') && !/net::ERR_(ABORTED|INTERNET_DISCONNECTED|CONNECTION_REFUSED|FAILED|CONNECTION_RESET)/.test(u) && !u.includes('/api/v1/covers/'),
    )
    t('FIN', '15-24', 'no unexpected failed requests', realFails.length === 0, JSON.stringify(realFails.slice(0, 3)))
  } finally {
    exportTable(started)
    await h.finish({ browser, page, state }, '15')
  }
}

main().catch((e) => {
  console.error('fase-15 crashed:', e)
  try {
    const partial = rows.length > 0 ? rows : [{ area: 'SCRIPT', ref: 'fase-15 crash', ok: 'FAIL', evidence: String(e) }]
    const md = [
      '# FASE 15 — checklist compilata (automazione e2e:15) — run INTERROTTO',
      '',
      `- Data: ${new Date().toISOString()}`,
      '',
      '| Area | Voce | Esito | Evidenza |',
      '|---|---|---|---|',
      ...partial.map((r) => `| ${r.area} | ${r.ref} | ${r.ok} | ${r.evidence.replace(/\|/g, '\\|')} |`),
    ].join('\n')
    fs.writeFileSync(RESULTS_FILE, md)
    console.log(`[15] partial results exported: ${RESULTS_FILE}`)
  } catch {
    /* ignore */
  }
  process.exitCode = 2
})

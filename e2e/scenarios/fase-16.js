'use strict'
/**
 * Fase 16 — phase-9 deterministic remediation scenario (spec:1734-1759).
 *
 * Covers the 24 spec flows with a fully hermetic seed (no live providers for
 * the checks): artists are created via the API with stored identities
 * (provider-linked add = identity row, no network); releases and the
 * `today_override` settings KV seam are written directly to the SQLite DB
 * (the app has no release-creation API and discovery is provider-driven —
 * same "direct KV write" seam task 25 designed for exactly this).
 *
 * Flows (spec:1736-1759):
 *   1  navbar usable after long scroll
 *   2  artists page shows Status, not Source/Match columns
 *   3  identity manager adds provider B without losing A
 *   4  identity change (replace) without deleting the artist
 *   5  search candidate opens its provider page
 *   6  retry modal has no "Search again by name" button
 *   7  ambiguous artist stays Needs match
 *   8  sync starts
 *   9  reload while active
 *   10 same sync still active
 *   11 second sync refused (409)
 *   12 cancel works
 *   13 final run cancelled
 *   14 feed updates after completed sync without browser refresh
 *   15 progress leaves 100% determinate state when matching begins
 *   16 error badge equals unread
 *   17 read one
 *   18 mark all read
 *   19 errors remain visible in All
 *   20 markdown diagnostic report is copyable
 *   21 upcoming tab exists
 *   22 upcoming shows no seen controls
 *   23 release transitions to Released under mocked date (today_override)
 *   24 reset refused while scan active
 *
 * Only the seed's name-only artist POSTs and the flow-5 candidate search touch
 * the network (background MB match / live candidate search); every CHECK is
 * deterministic against the seeded state. Live-provider candidates degrade to
 * a documented FAIL with evidence (never a silent skip).
 *
 * Env: BASE, ADMIN_USER, ADMIN_PASS (harness defaults) + E2E_DATA_DIR
 * (default /tmp/nucs-e2e-f16) + E2E_MUSIC_LIBRARY (default /tmp/nucs-lib-f16).
 * Backend must run with DATA_DIR=$E2E_DATA_DIR, MUSIC_LIBRARY_PATH=$E2E_MUSIC_LIBRARY,
 * DEV_INSECURE_COOKIES=true, NOTIFY_URLS= (see e2e/README.md).
 */
const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')
const h = require('../harness')

const DATA_DIR = process.env.E2E_DATA_DIR || '/tmp/nucs-e2e-f16'
const LIB_DIR = process.env.E2E_MUSIC_LIBRARY || '/tmp/nucs-lib-f16'
const DB_FILE = path.join(DATA_DIR, 'app.db')
const RESULTS_FILE = path.join(h.ARTIFACTS_DIR, 'fase-16-results.md')

// --- seeded names / ids (deterministic) ---
const MAIN_ARTIST = 'E2E Linked Artist 16' // deezer identity '123456789'
const MAIN_ARTIST_DEZZER_ID = '123456789'
const MAIN_ARTIST_URL = 'https://www.deezer.com/artist/123456789'
const ITUNES_URL = 'https://itunes.apple.com/artist/55555555'
const REPLACED_DEZZER_ID = '123456790'
const AMBIGUOUS_NAME = 'E2E Ambiguous Artist 16'
const IGNORED_NAME = 'E2E Ignored Artist 16'
const FUT_REL_TITLE = 'E2E Future Album 16'
const FUT_REL_DATE = '2099-07-15'
const FUT_REL_PROV_ID = 'e2e-16-rel-fut'
const RELEASED_REL_TITLE = 'E2E Released Single 16'
const RELEASED_REL_DATE = '2020-01-01'
const RELEASED_REL_PROV_ID = 'e2e-16-rel-now'
const SYNC_REL_TITLE = 'E2E Synced EP 16'
const SYNC_REL_DATE = '2020-01-02'
const SYNC_REL_PROV_ID = 'e2e-16-rel-synced'
const ERR_ONE_MSG = 'e2e: fase-16 error one'
const ERR_TWO_MSG = 'e2e: fase-16 error two'

// 8 MB-linked + 2 deezer-linked artists make every releases scan last >= ~10s
// (MB client enforces a 1 req/s rate limit per artist fetch) — the window the
// sync lifecycle flows (8-13) need for reload/refuse/cancel.
const MB_SYNC_ARTISTS = Array.from({ length: 8 }, (_, i) => ({
  name: `E2E Sync Artist ${String(i + 1).padStart(2, '0')}`,
  provider: 'mb',
  provider_id: `e2e00000-0000-0000-0000-0000000000${String(i + 1).padStart(2, '0')}`,
}))
const DZ_SYNC_ARTISTS = [
  { name: 'E2E Sync Artist 09', provider: 'deezer', provider_id: '99000009' },
  { name: 'E2E Sync Artist 10', provider: 'deezer', provider_id: '99000010' },
]
// Pre-seeded library artists: the flow-15 library files carry these exact
// names, so the scan upserts existing rows (zero new pending artists) — the
// scanning phase stays short-but-observable and the matching phase only has
// the one ambiguous artist (~2s), keeping the run fast.
const LIB_ARTISTS = Array.from({ length: 32 }, (_, i) => ({
  name: `E2E Library Artist ${String(i + 1).padStart(2, '0')}`,
  provider: 'deezer',
  provider_id: `9901${String(i + 1).padStart(4, '0')}`,
}))

// --- results table (exported at the end, fase-15 convention) ---
const rows = []
function t(area, ref, name, ok, evidence = '') {
  h.check(`${area}${ref}: ${name}`, ok, evidence)
  rows.push({ area, ref: `${ref} — ${name}`, ok: ok ? 'PASS' : 'FAIL', evidence })
}
function exportTable(started) {
  const dur = Math.round((Date.now() - started) / 1000)
  const md = [
    '# FASE 16 — checklist compilata (automazione e2e:16)',
    '',
    `- Data: ${new Date().toISOString()}`,
    `- Durata: ${Math.floor(dur / 60)}m ${dur % 60}s`,
    `- BASE: ${h.BASE}`,
    `- E2E_DATA_DIR: ${DATA_DIR}`,
    `- E2E_MUSIC_LIBRARY: ${LIB_DIR}`,
    '',
    '| Area | Voce | Esito | Evidenza |',
    '|---|---|---|---|',
    ...rows.map((r) => `| ${r.area} | ${r.ref} | ${r.ok} | ${(r.evidence || '').replace(/\|/g, '\\|').replace(/\n/g, ' ')} |`),
    '',
  ].join('\n')
  fs.mkdirSync(h.ARTIFACTS_DIR, { recursive: true })
  fs.writeFileSync(RESULTS_FILE, md)
  console.log(`\n[16] results exported: ${RESULTS_FILE}`)
  console.log('\narea | PASS/FAIL/N.A. | evidenza')
  for (const r of rows) console.log(`${r.area} | ${r.ok} | ${(r.evidence || '').slice(0, 140)}`)
}

// --- helpers ---
function sqlite(sql) {
  return execSync(`sqlite3 -cmd ".timeout 8000" "${DB_FILE}" "${sql}"`, { encoding: 'utf8' }).trim()
}

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

/** Poll /scans/status from the page context; returns the status body when the
 * predicate matches, else null when the deadline expires. */
async function pollStatus(page, predicate, timeoutMs = 20000, intervalMs = 120) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const body = await page.evaluate(async () =>
      (await fetch('/api/v1/scans/status', { credentials: 'same-origin' })).json(),
    )
    if (predicate(body)) return body
    if (Date.now() > deadline) return null
    await h.wait(intervalMs)
  }
}

/** Collect (phase, total, done) samples while a predicate has NOT yet matched;
 * resolves {matched, samples} — used to observe phase transitions mid-scan. */
async function sampleScanStatus(page, predicate, timeoutMs = 90000, intervalMs = 60) {
  const deadline = Date.now() + timeoutMs
  const samples = []
  for (;;) {
    const body = await page.evaluate(async () =>
      (await fetch('/api/v1/scans/status', { credentials: 'same-origin' })).json(),
    )
    const run = body.running
    samples.push(
      run
        ? { phase: run.phase ?? null, total: run.progress?.total ?? null, done: run.progress?.done ?? null }
        : { phase: null, total: null, done: null },
    )
    if (predicate(body)) return { matched: true, samples }
    if (Date.now() > deadline) return { matched: false, samples }
    await h.wait(intervalMs)
  }
}

async function waitIdle(page, timeoutMs = 300000) {
  const body = await pollStatus(page, (s) => !s.running, timeoutMs, 2000)
  if (!body) throw new Error('scan did not finish in time')
  return body
}

async function gotoFeed(page) {
  await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.body.innerText.includes('New releases'), { timeout: 20000 })
}

async function gotoArtists(page) {
  await page.goto(`${h.BASE}/artists`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => {
    const row = document.querySelector('table tbody tr')
    return row && row.textContent.trim().length > 3
  }, { timeout: 30000 })
}

/** Filter the artists table to one name, open its Manage modal, wait for it. */
async function openManageModal(page, name) {
  await setInput(page, 'input[aria-label="Search artist"]', name)
  await page.waitForFunction(
    (n) => {
      const row = [...document.querySelectorAll('table tbody tr')].find((r) => r.textContent.includes(n))
      return row && row.querySelector(`button[aria-label="Manage ${n}"]`) !== null
    },
    { timeout: 15000 },
    name,
  )
  await page.evaluate((n) => {
    const btn = document.querySelector(`button[aria-label="Manage ${n}"]`)
    if (btn) btn.click()
  }, name)
  await page.waitForSelector(`[role="dialog"][aria-label="Manage ${name}"]`, { timeout: 10000 })
}

// --- seed ---
async function seed(page) {
  console.log('\n=== 16: hermetic seed ===')

  // 1) main artist, Linked via Deezer identity (no network: identity stored as-is)
  const main = await api(page, 'POST', '/api/v1/artists', {
    name: MAIN_ARTIST,
    provider: 'deezer',
    provider_id: MAIN_ARTIST_DEZZER_ID,
    external_url: MAIN_ARTIST_URL,
  })
  if (main.status !== 202 || !main.body.id) {
    throw new Error(`seed: main artist creation failed (${main.status}) ${JSON.stringify(main.body)}`)
  }
  const mainId = main.body.id

  // 2) sync-window artists (fake provider ids -> fast provider misses, no data)
  for (const a of [...MB_SYNC_ARTISTS, ...DZ_SYNC_ARTISTS, ...LIB_ARTISTS]) {
    const r = await api(page, 'POST', '/api/v1/artists', {
      name: a.name,
      provider: a.provider,
      provider_id: a.provider_id,
    })
    if (r.status !== 202) throw new Error(`seed: sync artist ${a.name} failed (${r.status})`)
  }

  // 3) Needs-match artist (nonsense name: the fire-and-forget background MB
  //    match can never link it) + an Ignored artist
  const amb = await api(page, 'POST', '/api/v1/artists', { name: AMBIGUOUS_NAME })
  if (amb.status !== 202 || !amb.body.id) throw new Error('seed: ambiguous artist failed')
  const ign = await api(page, 'POST', '/api/v1/artists', { name: IGNORED_NAME })
  if (ign.status !== 202 || !ign.body.id) throw new Error('seed: ignored artist failed')
  await api(page, 'PATCH', `/api/v1/artists/${ign.body.id}`, { ignored: 1 })

  // 4) releases (no creation API; written via the settings-KV-style direct DB
  //    seam — same mechanism the today_override flow uses)
  const ts = new Date().toISOString().replace('Z', '+00:00')
  const insert = (title, type, date, provId) =>
    sqlite(
      `INSERT INTO releases (rgid, provider, provider_id, title, primary_artist, type, secondary_types, first_release_date, discovered_at)
       VALUES (NULL, 'deezer', '${provId}', '${title}', '${MAIN_ARTIST}', '${type}', '', '${date}', '${ts}');
       INSERT INTO release_artists (release_id, artist_id, role)
       VALUES ((SELECT id FROM releases WHERE provider_id='${provId}'), ${mainId}, 'primary');
       INSERT INTO release_state (release_id, seen, hidden, favorite)
       VALUES ((SELECT id FROM releases WHERE provider_id='${provId}'), 0, 0, 0);
       SELECT id FROM releases WHERE provider_id='${provId}';`,
    )
  const futId = insert(FUT_REL_TITLE, 'album', FUT_REL_DATE, FUT_REL_PROV_ID)
  const relId = insert(RELEASED_REL_TITLE, 'single', RELEASED_REL_DATE, RELEASED_REL_PROV_ID)
  console.log(`seed: releases futId=${futId} releasedId=${relId}`)

  // wait for the background MB match of the nonsense names to settle
  await h.wait(4000)
  return { mainId, futId, relId, ambId: amb.body.id, ignId: ign.body.id }
}

async function main() {
  const { browser, page, state } = await h.launch()
  const started = Date.now()
  try {
    await page.setViewport({ width: 1280, height: 900 })
    // headless async clipboard needs the page focused AND the sanitized-write
    // permission granted on the BASE origin before the copy flows (probe-verified)
    await browser.defaultBrowserContext().overridePermissions(h.BASE, ['clipboard-read', 'clipboard-write', 'clipboard-sanitized-write'])

    await h.uiLogin(page)
    const seedInfo = await seed(page)
    const { mainId, futId, relId } = seedInfo
    let syncRelId = null

    // ================= 1. navbar usable after long scroll =================
    console.log('\n=== 16: 1-7 artists / navbar ===')
    await gotoArtists(page)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await h.wait(400)
    const navAfterScroll = await page.evaluate(() => {
      const sticky = document.querySelector('div.sticky.top-0')
      const rect = sticky ? sticky.getBoundingClientRect() : null
      return {
        stickyTop: rect ? Math.round(rect.top) : null,
        stickyVisible: rect ? rect.top < 50 && rect.bottom > 0 : false,
        navClickable: !!document.querySelector('a[aria-label="Feed"]'),
      }
    })
    t('ART', '1', 'navbar stays pinned at the top after a long scroll', navAfterScroll.stickyTop === 0 && navAfterScroll.stickyVisible, JSON.stringify(navAfterScroll))
    await page.click('a[aria-label="Feed"]')
    await page.waitForFunction(() => location.pathname === '/', { timeout: 15000 })
    t('ART', '1', 'navbar link clickable while scrolled (navigates to feed)', true)

    // ================= 2. Status, not Source/Match columns =================
    await gotoArtists(page)
    const headers = await page.evaluate(() =>
      [...document.querySelectorAll('table thead th')].map((th) => th.textContent.trim()),
    )
    t(
      'ART', '2',
      'artists table headers = [Name, Status, Releases, Actions], no Source/Match',
      headers.length === 4 && headers[1] === 'Status' && !headers.some((x) => /source|match/i.test(x)),
      JSON.stringify(headers),
    )
    const badgeTexts = await page.evaluate(() =>
      [...document.querySelectorAll('table tbody tr')].map(
        (r) => r.querySelector('td:nth-child(2)')?.textContent.trim() ?? '',
      ),
    )
    t(
      'ART', '2',
      'Status column renders the status pills (Linked / Needs match / Ignored)',
      badgeTexts.length > 0 && badgeTexts.every((b) => ['Linked', 'Needs match', 'Ignored'].includes(b)),
      badgeTexts.slice(0, 5).join(' | '),
    )

    // ================= 3. identity manager adds provider B =================
    await openManageModal(page, MAIN_ARTIST)
    const idsBefore = await page.evaluate((name) => {
      const dialog = document.querySelector(`[role="dialog"][aria-label="Manage ${name}"]`)
      return [...dialog.querySelectorAll('li')].map((li) => li.textContent)
    }, MAIN_ARTIST)
    t('ART', '3', 'identity manager opens with provider A (Deezer) listed', idsBefore.length === 1 && idsBefore[0].includes('Deezer'), JSON.stringify(idsBefore))

    await setInput(page, '#link-artist-url', ITUNES_URL)
    await clickByText(page, 'Link artist')
    await page.waitForFunction(
      (n) => {
        const dialog = document.querySelector(`[role="dialog"][aria-label="Manage ${n}"]`)
        return dialog && [...dialog.querySelectorAll('li')].length === 2
      },
      { timeout: 15000 },
      MAIN_ARTIST,
    )
    const idsAfter = await page.evaluate((name) => {
      const dialog = document.querySelector(`[role="dialog"][aria-label="Manage ${name}"]`)
      return [...dialog.querySelectorAll('li')].map((li) => li.textContent)
    }, MAIN_ARTIST)
    t(
      'ART', '3',
      'adding provider B (Apple Music) via the identity manager keeps provider A',
      idsAfter.length === 2 && idsAfter.some((x) => x.includes('Deezer')) && idsAfter.some((x) => x.includes('Apple Music')),
      JSON.stringify(idsAfter),
    )
    await page.keyboard.press('Escape').catch(() => {})
    await h.wait(400)

    // ================= 4. identity change without delete =================
    const before = await api(page, 'GET', `/api/v1/artists?q=${encodeURIComponent(MAIN_ARTIST)}&page_size=10`)
    const mainBefore = (before.body.items || []).find((a) => a.id === mainId)
    const replace = await api(page, 'PUT', `/api/v1/artists/${mainId}/identities/deezer`, { provider_id: REPLACED_DEZZER_ID })
    const after = await api(page, 'GET', `/api/v1/artists?q=${encodeURIComponent(MAIN_ARTIST)}&page_size=10`)
    const mainAfter = (after.body.items || []).find((a) => a.id === mainId)
    t(
      'ART', '4',
      'PUT /identities/{provider} replaces the identity without deleting the artist',
      mainAfter && mainAfter.id === mainId && mainAfter.status === 'Linked' && mainAfter.identities.length === 2 &&
        mainAfter.identities.some((i) => i.provider === 'deezer' && i.provider_id === REPLACED_DEZZER_ID) &&
        mainAfter.identities.some((i) => i.provider === 'itunes') && !!mainBefore,
      JSON.stringify({ before: mainBefore && mainBefore.identities, after: mainAfter && mainAfter.identities }),
    )

    // ================= 5. candidate opens provider page =================
    await clickByText(page, '+ Add artist')
    await page.waitForSelector('#add-artist-query', { timeout: 10000 })
    await page.type('#add-artist-query', 'deadmau5')
    let cand = await (async () => {
      for (let i = 0; i < 60; i++) {
        const c = await page.evaluate(() => {
          const dialog = document.querySelector('[role="dialog"][aria-label="Add artist"]')
          if (!dialog) return null
          const a = [...dialog.querySelectorAll('a')].find((x) => /^Open on /.test(x.textContent))
          return a
            ? { text: a.textContent.trim(), href: a.href, target: a.target, rel: a.rel }
            : null
        })
        if (c) return c
        await h.wait(500)
      }
      return null
    })()
    if (cand) {
      const urlOk = /^(https:\/\/musicbrainz\.org\/artist\/|https:\/\/www\.deezer\.com\/artist\/|https:\/\/music\.apple\.com\/artist\/|https:\/\/www\.discogs\.com\/artist\/)/.test(cand.href)
      t(
        'ART', '5',
        'search candidate row opens its provider page (target=_blank, rel=noreferrer)',
        urlOk && cand.target === '_blank' && cand.rel.includes('noreferrer') && /^Open on .+ ↗$/.test(cand.text),
        JSON.stringify(cand),
      )
    } else {
      t('ART', '5', 'search candidate row opens its provider page', false, 'no provider candidates rendered (live search unavailable)')
    }
    await page.keyboard.press('Escape').catch(() => {})
    await h.wait(400)

    // ================= 6. retry modal has no "Search again by name" =================
    await openManageModal(page, AMBIGUOUS_NAME)
    const retryModal = await page.evaluate((name) => {
      const dialog = document.querySelector(`[role="dialog"][aria-label="Manage ${name}"]`)
      const text = dialog ? dialog.textContent : ''
      return {
        hasSearchAgain: text.includes('Search again by name'),
        hasSearchAgainBtn: dialog ? [...dialog.querySelectorAll('button')].some((b) => b.textContent.includes('Search again by name')) : false,
        hasNoIdentitiesHint: text.includes('No external identities yet'),
      }
    }, AMBIGUOUS_NAME)
    t(
      'ART', '6',
      'retry/matching modal contains no "Search again by name" button',
      !retryModal.hasSearchAgain && !retryModal.hasSearchAgainBtn && retryModal.hasNoIdentitiesHint,
      JSON.stringify(retryModal),
    )
    await page.keyboard.press('Escape').catch(() => {})
    await h.wait(400)

    // ================= 7. ambiguous artist stays Needs match =================
    const ambNow = await api(page, 'GET', `/api/v1/artists?q=${encodeURIComponent(AMBIGUOUS_NAME)}&page_size=10`)
    const ambItem = (ambNow.body.items || []).find((a) => a.id === seedInfo.ambId)
    t(
      'ART', '7',
      'ambiguous artist still Needs match (no auto identity after the background match)',
      !!ambItem && ambItem.status === 'Needs match' && (ambItem.identities || []).length === 0,
      JSON.stringify({ status: ambItem && ambItem.status, identities: ambItem && ambItem.identities }),
    )

    // ================= 8-13. sync lifecycle =================
    console.log('\n=== 16: 8-13 sync lifecycle ===')
    await gotoFeed(page)
    const syncBtn = await page.evaluate(() => {
      const b = document.querySelector('button[aria-label="Check for new releases"]')
      return b ? { text: b.textContent.trim(), disabled: b.disabled } : null
    })
    t('SYNC', '8', 'sync button present on the feed', !!syncBtn && syncBtn.text === 'Sync', JSON.stringify(syncBtn))
    await page.click('button[aria-label="Check for new releases"]')
    const running1 = await pollStatus(page, (s) => s.running && s.running.type === 'releases', 15000, 150)
    t('SYNC', '8', 'clicking Sync starts the releases scan', !!running1, running1 ? `started_at=${running1.running.started_at}` : 'not running')

    // 9-10. reload while active -> same sync still active
    const startedAtBefore = running1.running.started_at
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('New releases'), { timeout: 20000 })
    const running2 = await pollStatus(page, (s) => s.running && s.running.type === 'releases', 15000, 150)
    t('SYNC', '9', 'reload while the sync is active keeps the app on the feed', running2 && running2.running.type === 'releases', running2 ? `started_at=${running2.running.started_at}` : 'not running')
    t('SYNC', '10', 'same sync still active after reload (unchanged started_at)', !!running2 && running2.running.started_at === startedAtBefore, `before=${startedAtBefore} after=${running2 && running2.running.started_at}`)

    // 11. second sync refused
    const second = await api(page, 'POST', '/api/v1/scans/releases')
    t('SYNC', '11', 'second sync request refused while running (409)', second.status === 409 && /already in progress/i.test(second.body?.detail || ''), `status=${second.status} ${second.body?.detail || ''}`)

    // 12. cancel works
    const cancel = await api(page, 'POST', '/api/v1/scans/releases/cancel')
    t('SYNC', '12', 'POST /scans/releases/cancel accepted (202, cancel_requested)', cancel.status === 202 && cancel.body?.cancel_requested === true, `status=${cancel.status} cancel_requested=${cancel.body && cancel.body.cancel_requested}`)

    // 13. final run cancelled
    const idle1 = await waitIdle(page)
    const lastRun1 = idle1.last_runs && idle1.last_runs[0]
    t(
      'SYNC', '13',
      'final releases run persisted as cancelled',
      lastRun1 && lastRun1.type === 'releases' && lastRun1.status === 'cancelled',
      JSON.stringify(lastRun1 && { type: lastRun1.type, status: lastRun1.status }),
    )

    // ================= 14. feed updates after sync, no refresh =================
    // The sync MUST be triggered through the UI Sync button: useStartScan
    // invalidates ['scan-status'], which is what teaches the browser that a
    // scan is running (the completion watcher's poll only activates once
    // scan-status returns running). An API-side POST alone never updates the
    // browser cache and the completion invalidation can never fire.
    console.log('\n=== 16: 14 feed invalidation ===')
    await gotoFeed(page)
    await page.waitForFunction(
      (t) => [...document.querySelectorAll('a[href^="/releases/"]')].some((a) => a.textContent.includes(t)),
      { timeout: 20000 },
      RELEASED_REL_TITLE,
    )
    await page.click('button[aria-label="Check for new releases"]')
    const runStarted = await pollStatus(page, (s) => s.running && s.running.type === 'releases', 15000, 150)
    if (!runStarted) throw new Error('flow 14: sync did not start')
    // insert the new release while the sync is running (invalidation refetch)
    const ts = new Date().toISOString().replace('Z', '+00:00')
    syncRelId = sqlite(
      `INSERT INTO releases (rgid, provider, provider_id, title, primary_artist, type, secondary_types, first_release_date, discovered_at)
       VALUES (NULL, 'deezer', '${SYNC_REL_PROV_ID}', '${SYNC_REL_TITLE}', '${MAIN_ARTIST}', 'ep', '', '${SYNC_REL_DATE}', '${ts}');
       INSERT INTO release_artists (release_id, artist_id, role)
       VALUES ((SELECT id FROM releases WHERE provider_id='${SYNC_REL_PROV_ID}'), ${mainId}, 'primary');
       INSERT INTO release_state (release_id, seen, hidden, favorite)
       VALUES ((SELECT id FROM releases WHERE provider_id='${SYNC_REL_PROV_ID}'), 0, 0, 0);
       SELECT id FROM releases WHERE provider_id='${SYNC_REL_PROV_ID}';`,
    )
    await waitIdle(page)
    const appeared = await (async () => {
      const deadline = Date.now() + 20000
      for (;;) {
        const found = await page.evaluate((id) => {
          const a = document.querySelector(`a[href="/releases/${id}"]`)
          return a ? { found: true, path: location.pathname } : { found: false, path: location.pathname }
        }, syncRelId)
        if (found.found) return found
        if (Date.now() > deadline) return found
        await h.wait(500)
      }
    })()
    t(
      'SYNC', '14',
      'feed shows the new release after the completed sync without a browser refresh',
      appeared.found && appeared.path === '/',
      JSON.stringify({ releaseId: syncRelId, ...appeared }),
    )

    // ================= 15. progress leaves 100% when matching begins =================
    console.log('\n=== 16: 15 progress phases (library scan) ===')
    const libStart = await api(page, 'POST', '/api/v1/scans/library?full=true')
    t('SYNC', '15', 'library scan accepted', libStart.status === 202, `status=${libStart.status}`)
    const obs = await sampleScanStatus(
      page,
      (s) => !s.running,
      180000,
      60,
    )
    const phases = obs.samples.map((s) => s.phase)
    const sawDeterminate = obs.samples.some((s) => s.phase === 'scanning' && s.total > 0 && s.done > 0)
    const sawMatchingIndeterminate = obs.samples.some(
      (s) => s.phase === 'matching artists' && s.total === 0 && s.done === 0,
    )
    const idxDeterminate = obs.samples.findIndex((s) => s.phase === 'scanning' && s.total > 0 && s.done > 0)
    const idxMatching = obs.samples.findIndex((s) => s.phase === 'matching artists' && s.total === 0)
    const ordered = idxDeterminate >= 0 && idxMatching >= 0 && idxDeterminate < idxMatching
    // The hard gate is sawMatchingIndeterminate: with the pre-task-37 Trap-5
    // bug the matching phase carried total>0 (inherited from scanning), so
    // `matching total==0` would be FALSE and this check would fail. The
    // "100%" moment (done == total) is instantaneous — the last done update is
    // immediately followed by the cleanup/matching reset — so sawDeterminate /
    // ordered are recorded as evidence and are N.A. when the tiny seeded
    // library completes scanning faster than the poll interval.
    t(
      'SYNC', '15',
      'progress leaves the 100% determinate state when matching begins (matching total == 0)',
      sawMatchingIndeterminate,
      `determinate(total=${idxDeterminate >= 0 ? obs.samples[idxDeterminate].total : '- N.A. (scan too fast to sample)'}) matching(total=0)=${sawMatchingIndeterminate} orderOk=${ordered} phases=${phases.filter((p) => p).slice(0, 8).join('>')}`,
    )

    // ================= 16-20. errors =================
    console.log('\n=== 16: 16-20 errors ===')
    const e1 = await api(page, 'POST', '/api/v1/errors', { message: ERR_ONE_MSG, context: 'fase-16 flow' })
    const e2 = await api(page, 'POST', '/api/v1/errors', { message: ERR_TWO_MSG })
    if (e1.status !== 201 || e2.status !== 201) throw new Error('seed: error rows failed')

    await gotoFeed(page)
    const badge1 = await (async () => {
      for (let i = 0; i < 40; i++) {
        const b = await page.evaluate(() => {
          const span = document.querySelector('a[aria-label="Errors"] span[class*="bg-danger"]')
          return span ? span.textContent : null
        })
        if (b !== null) return b
        await h.wait(250)
      }
      return null
    })()
    const unread1 = (await h.apiJson(page, '/api/v1/errors?page_size=1')).body.unread_total
    t('ERR', '16', 'navbar error badge equals the unread count', badge1 !== null && parseInt(badge1, 10) === unread1, `badge=${badge1} unread=${unread1}`)

    const readOne = await api(page, 'POST', `/api/v1/errors/${e1.body.id}/read`)
    const unread2 = (await h.apiJson(page, '/api/v1/errors?page_size=1')).body.unread_total
    t('ERR', '17', 'reading one error decrements the unread total', readOne.status === 200 && unread2 === unread1 - 1, `unread ${unread1} -> ${unread2}`)
    // badge reflects the decrement after the refetch on mount
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('New releases'), { timeout: 20000 })
    const badge2 = await (async () => {
      for (let i = 0; i < 40; i++) {
        const b = await page.evaluate(() => {
          const span = document.querySelector('a[aria-label="Errors"] span[class*="bg-danger"]')
          return span ? span.textContent : null
        })
        if (b !== null) return b
        await h.wait(250)
      }
      return null
    })()
    t('ERR', '17', 'navbar badge shows the decremented unread count', badge2 !== null && parseInt(badge2, 10) === unread2, `badge=${badge2} unread=${unread2}`)

    const readAll = await api(page, 'POST', '/api/v1/errors/read-all')
    const unread3 = (await h.apiJson(page, '/api/v1/errors?page_size=1')).body.unread_total
    t('ERR', '18', 'mark all read -> zero unread', readAll.status === 200 && unread3 === 0, `updated=${readAll.body && readAll.body.updated} unread=${unread3}`)

    // default tab is Unread; everything is read at this point, so switch to
    // the All tab BEFORE waiting for the seeded messages
    await page.goto(`${h.BASE}/errors`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('[role="tablist"][aria-label="Error filter"] [role="tab"]', { timeout: 15000 })
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('[role="tablist"][aria-label="Error filter"] [role="tab"]')].find((b) => b.textContent.startsWith('All ('))
      if (btn) btn.click()
    })
    await page.waitForFunction(
      (m1) => document.body.innerText.includes(m1),
      { timeout: 15000 },
      ERR_ONE_MSG,
    )
    const errorsVisible = await page.evaluate(([m1, m2]) => ({
      one: document.body.innerText.includes(m1),
      two: document.body.innerText.includes(m2),
      tabs: [...document.querySelectorAll('[role="tab"]')].map((b) => `${b.textContent.trim()}:${b.getAttribute('aria-selected')}`),
    }), [ERR_ONE_MSG, ERR_TWO_MSG])
    t(
      'ERR', '19',
      'read errors remain visible in the All tab (reading never deletes)',
      errorsVisible.one && errorsVisible.two && errorsVisible.tabs.some((x) => x.startsWith('All (') && x.endsWith(':true')),
      JSON.stringify(errorsVisible),
    )

    // 20. diagnostic report copyable (headless needs the page focused for the
    // async clipboard write permission, hence bringToFront before the click)
    await page.bringToFront()
    await clickByText(page, 'Copy diagnostic report')
    const copiedDiag = await (async () => {
      const deadline = Date.now() + 10000
      for (;;) {
        const ok = await page.evaluate(() =>
          [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Copied ✓'),
        )
        if (ok) return true
        if (Date.now() > deadline) return false
        await h.wait(200)
      }
    })()
    let clip = null
    let clipErr = null
    try {
      clip = await page.evaluate(() => navigator.clipboard.readText())
    } catch (err) {
      clipErr = String(err)
    }
    t(
      'ERR', '20',
      'markdown diagnostic report is copyable (Copied ✓ + clipboard has the report + seeded error)',
      copiedDiag && clip !== null && clip.includes('# NUCS Diagnostic Report') && clip.includes(ERR_ONE_MSG),
      clipErr ? `clipboard error: ${clipErr}` : `copied=${copiedDiag} reportLen=${clip ? clip.length : 0} hasMsg=${clip ? clip.includes(ERR_ONE_MSG) : false}`,
    )

    // ================= 21-23. upcoming / date transition =================
    console.log('\n=== 16: 21-23 upcoming tab + mocked-date transition ===')
    await gotoFeed(page)
    const tabs = await page.evaluate(() =>
      [...document.querySelectorAll('[role="tablist"][aria-label="Release view"] [role="tab"]')].map((b) => ({
        text: b.textContent.trim(),
        selected: b.getAttribute('aria-selected'),
      })),
    )
    t('UP', '21', 'Upcoming tab exists next to Released', tabs.length === 2 && tabs[0].text === 'Released' && tabs[1].text === 'Upcoming', JSON.stringify(tabs))
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('[role="tablist"][aria-label="Release view"] [role="tab"]')].find((b) => b.textContent.trim() === 'Upcoming')
      if (btn) btn.click()
    })
    await page.waitForFunction(
      (id) => !!document.querySelector(`a[href="/releases/${id}"]`),
      { timeout: 15000 },
      futId,
    )
    const upcomingCard = await page.evaluate((id) => {
      const card = document.querySelector(`a[href="/releases/${id}"]`)
      return {
        hasEye: !!card.querySelector('button[aria-label^="Mark as"]'),
        hasNewDot: !!card.querySelector('span[aria-label="New"]'),
      }
    }, futId)
    t('UP', '22', 'upcoming card shows no seen controls (no eye, no New dot)', !upcomingCard.hasEye && !upcomingCard.hasNewDot, JSON.stringify(upcomingCard))

    // 23. transition under mocked date via the today_override settings KV seam
    sqlite(`INSERT INTO settings (key, value) VALUES ('today_override', '2099-07-16')
            ON CONFLICT(key) DO UPDATE SET value='2099-07-16';`)
    await page.goto(`${h.BASE}/`, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(() => document.body.innerText.includes('New releases'), { timeout: 20000 })
    // wait for the future release's card (the releases query resolves after the
    // header renders) then assert the seen controls on it
    await page.waitForFunction(
      (id) => !!document.querySelector(`a[href="/releases/${id}"]`),
      { timeout: 15000 },
      futId,
    )
    const releasedCard = await page.evaluate(
      (id) => {
        const card = document.querySelector(`a[href="/releases/${id}"]`)
        if (!card) return null
        return {
          hasEye: !!card.querySelector('button[aria-label^="Mark as"]'),
          eyeLabel: (() => {
            const b = card.querySelector('button[aria-label^="Mark as"]')
            return b ? b.getAttribute('aria-label') : null
          })(),
          hasNewDot: !!card.querySelector('span[aria-label="New"]'),
        }
      },
      futId,
    )
    const upcomingApiAfter = (await h.apiJson(page, '/api/v1/releases?view=upcoming&page_size=50')).body.total
    t(
      'UP', '23',
      'under the mocked date the release appears in Released with seen controls',
      releasedCard !== null && releasedCard.hasEye && releasedCard.hasNewDot && releasedCard.eyeLabel === 'Mark as seen' && upcomingApiAfter === 0,
      JSON.stringify({ card: releasedCard, upcomingTotal: upcomingApiAfter }),
    )
    // restore the real date (delete the seam) so nothing later is date-shifted
    sqlite(`DELETE FROM settings WHERE key='today_override';`)
    t('UP', '23', 'today_override seam removed after the transition check', true, 'settings row deleted')

    // ================= 24. reset refused while scan active =================
    // A releases scan is used: it is long (many seeded artists) and has a
    // per-artist cancellation safe point, so the refuse + cancel sequence is
    // race-free (a short library scan could finish before the cancel lands).
    console.log('\n=== 16: 24 reset refused ===')
    const relStart = await api(page, 'POST', '/api/v1/scans/releases')
    t('RESET', '24', 'releases scan running for the reset test', relStart.status === 202, `status=${relStart.status}`)
    const runningReset = await pollStatus(page, (s) => s.running && s.running.type === 'releases', 15000, 100)
    const resetAttempt = runningReset ? await api(page, 'DELETE', '/api/v1/library') : { status: -1, body: null }
    t(
      'RESET', '24',
      'DELETE /library refused with 409 while the scan is active',
      !!runningReset && resetAttempt.status === 409,
      `running=${!!runningReset} status=${resetAttempt.status}`,
    )
    await api(page, 'POST', '/api/v1/scans/releases/cancel')
    const idleFinal = await waitIdle(page)
    const lastRel = idleFinal.last_runs && idleFinal.last_runs[0]
    t('RESET', '24', 'the reset-test releases scan is cancelled cleanly afterwards', !!lastRel && lastRel.type === 'releases' && lastRel.status === 'cancelled', JSON.stringify(lastRel && { type: lastRel.type, status: lastRel.status }))

    // ================= final cleanliness =================
    console.log('\n=== 16: console / CSP / network cleanliness ===')
    await gotoFeed(page)
    await h.wait(1200)
    const realConsole = state.consoleErrors.filter((e) => {
      if (e.includes('status of 401')) return false
      if (e.includes('status of 404')) return false
      if (e.includes('status of 422')) return false
      if (e.includes('status of 429')) return false
      // 409s are intentional: flows 11 (second sync refused) and 24 (reset
      // refused while a scan is active) assert exactly that status.
      if (e.includes('status of 409')) return false
      if (/net::ERR_(INTERNET_DISCONNECTED|CONNECTION_REFUSED|ABORTED|FAILED|CONNECTION_RESET|TIMED_OUT)/.test(e)) return false
      return true
    })
    const csp = state.consoleErrors.filter(
      (e) => e.includes('Content Security Policy') || e.includes('Refused to') || e.includes('violates'),
    )
    t('FIN', 'FIN', 'console clean (only intentional 401/404/422/429)', realConsole.length === 0, JSON.stringify(realConsole.slice(0, 5)))
    t('FIN', 'FIN', 'zero CSP violations', csp.length === 0, JSON.stringify(csp.slice(0, 3)))
    t('FIN', 'FIN', 'no unhandled page errors', state.pageErrors.length === 0, JSON.stringify(state.pageErrors.slice(0, 3)))
    const externalImages = [...state.imageHosts].filter((host) => host && host !== new URL(h.BASE).host)
    t('FIN', 'FIN', 'no images from external domains', externalImages.length === 0, JSON.stringify(externalImages.slice(0, 5)))
    const realFails = state.failedRequests.filter(
      (u) => !u.includes('/api/v1/auth/') && !/net::ERR_(ABORTED|INTERNET_DISCONNECTED|CONNECTION_REFUSED|FAILED|CONNECTION_RESET|TIMED_OUT)/.test(u) && !u.includes('/api/v1/covers/'),
    )
    t('FIN', 'FIN', 'no unexpected failed requests', realFails.length === 0, JSON.stringify(realFails.slice(0, 3)))
  } finally {
    exportTable(started)
    await h.finish({ browser, page, state }, '16')
  }
}

main().catch((e) => {
  console.error('fase-16 crashed:', e)
  try {
    const partial = rows.length > 0 ? rows : [{ area: 'SCRIPT', ref: 'fase-16 crash', ok: 'FAIL', evidence: String(e) }]
    const md = [
      '# FASE 16 — checklist compilata (automazione e2e:16) — run INTERROTTO',
      '',
      `- Data: ${new Date().toISOString()}`,
      '',
      '| Area | Voce | Esito | Evidenza |',
      '|---|---|---|---|',
      ...partial.map((r) => `| ${r.area} | ${r.ref} | ${r.ok} | ${r.evidence.replace(/\|/g, '\\|')} |`),
    ].join('\n')
    fs.writeFileSync(RESULTS_FILE, md)
    console.log(`[16] partial results exported: ${RESULTS_FILE}`)
  } catch {
    /* ignore */
  }
  process.exitCode = 2
})

# FASE 08 — UI: feed release + pagina dettaglio

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 07
- **Branch**: `git checkout -b fase-08-ui-release`

---

## 1. Obiettivo

La pagina principale dell'app: feed delle nuove uscite con filtri (§11.2.2) e pagina dettaglio
con i bottoni Spotify / YouTube Music / Deezer / Google (§11.2.3). Copertine dalla cache locale
(`/api/v1/covers/{rgid}`), placeholder se assente.

## 2. Prerequisiti

- Fase 07 mergiata. Backend con dati reali (release + cover dalle fasi 05-06) per il test manuale.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §11.2.2 (feed), §11.2.3 (dettaglio), §11.1 (palette), §11.3 (comportamenti),
  §10 (shape risposte /releases)
- piano/README.md §4
- piano/STATO.md
Branch: fase-08. Codice/commenti inglese, STRINGHE UI IN INGLESE. Solo Tailwind + SVG inline.
Se esistono mockup in piano/mockup/: usali come riferimento visivo vincolante.

OBIETTIVO
Feed release completo + pagina dettaglio con bottoni link esterni.

COMPITI
1. src/api/releases.ts: hook react-query: useReleases(filters,page), useRelease(id),
   useSetReleaseState, useSeenAll. Tipi TS allineati a §10 (ReleaseListItem, ReleaseDetail, Filters).
2. components/ReleaseCard.tsx: come §11.2.2: copertina quadrata (img src=/api/v1/covers/{rgid}
   loading="lazy"; onerror/assente → placeholder div surface2 con icona nota SVG), titolo 2 righe
   (line-clamp-2), riga artisti: matched_artists role primary/featured dei TUOI artisti in text accent
   (font-medium), gli altri in textDim (costruisci la stringa display: primary_artist + se ci sono
    matched featured → " (feat. {nomi})"), data in formato ISO 8601 (YYYY-MM-DD; date parziali così come sono),
   badge tipo (pill surface2: Album/Single/EP), pallino accent top-right se !seen ("new").
   Tutta la card è un Link a /releases/{id}. Hover: leggero scale/shadow. focus-visible ring-2 ring-accent.
3. pages/Feed.tsx (§11.2.2): H1 "New releases"; riga filtri: chip [All|Albums|Singles|EPs]
   (stato attivo accent), toggle "Unseen only" (switch con aria-label), input placeholder "Search…" (debounce 300ms),
   bottone textDim "Mark all as seen" (conferma window.confirm → POST seen-all → invalidate).
   Grid: grid-cols-2 sm:3 md:4 lg:5 xl:6 gap-4. Dati: GET /releases con filtri mappati
   (type CSV escluso 'All', seen=no se toggle, q). Paginazione: accumula pagine (keepPreviousData
   / infinite query semplice) + bottone "Load more" se page*page_size < total.
   Stati: loading → skeleton card (animate-pulse); errore → messaggio + bottone "Retry";
   vuoto → empty state: icona + "No new releases" + sottotesto "Try running a scan from Settings"
   + link /settings.
4. components/LinkButtons.tsx (§11.2.3): 4 bottoni pill: Spotify (bg accent, testo text-black per AA su #1DB954),
   YouTube Music (bg yt), Deezer (bg deezer), "Search on Google" (bg surface2 border border-border).
   Icona SVG semplice + label. href dai campi releases.*_url; target=_blank rel="noopener noreferrer".
   Bottoni disabilitati (opacity-50, no link) se il campo è null.
5. pages/ReleaseDetail.tsx (§11.2.3): fetch /releases/{id} (side-effect seen ok). Layout:
   link "← Back to feed"; grid md:grid-cols-[384px,1fr] gap-8; copertina grande rounded-xl
   (o placeholder); H1 titolo; riga meta: data completa + badge tipo + secondary_types se presenti;
   blocco "Your artists": matched_artists con ruolo tradotto (Main artist / Featuring / Contributor)
   in accent; riga LinkButtons; toggle Seen / Favorite (cuore SVG filled se attiva) /
   Hide (POST state ottimistico con invalidate). Se hidden → badge "Hidden" e bottone "Restore".
6. 404 release → pagina "Release not found" + link feed.
7. Accessibilità §11.3: focus ring ovunque, aria-label su toggle/icon-button, alt sensati sulle cover.
8. Typecheck pulito; build ok.

VINCOLI
- Solo endpoint esistenti (§10): se ti serve un dato mancante FERMATI e scrivilo in STATO.md (non modificare il backend salvo bug evidente: se proprio serve, segnala e chiedi).
- Date: sempre ISO 8601 (YYYY-MM-DD); first_release_date parziale mostrata così com'è ("2024", "2024-05").
- Niente infinite scroll complesso: bottone "Load more" (§11.2.2).
- Immagini SOLO da /api/v1/covers (CSP): mai hotlink esterni.

DELIVERABLE
Report + output build + aggiornamento piano/STATO.md (fase 08).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 08 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd frontend && npm ci && npx tsc --noEmit && npm run build` → exit 0.
2. Con backend avviato (dati reali fasi 05-06), nel browser:
   - / → grid di card con copertine reali (da /api/v1/covers), badge tipo, date in formato ISO.
   - Release non vista ha il pallino accent; click card → dettaglio; torna al feed → pallino sparito (seen).
   - Chip "Singles" → solo single; toggle "Unseen only" coerente; ricerca "que" filtra (debounce ok).
   - "Load more" carica la pagina successiva senza duplicati (conta card vs total).
   - "Mark all as seen" → conferma → feed "Unseen only" diventa empty state corretto.
   - Dettaglio: 4 bottoni presenti; click su ciascuno → nuova tab (noopener) verso destinazione sensata
     (Spotify/YTM/Deezer → release o ricerca coerente; Google → ricerca con artista+titolo).
   - Toggle Favorite → cuore pieno, persistito dopo reload; Hide → scompare dal feed (hidden default no).
   - Mobile (devtools 375px): grid 2 colonne, navbar compatta usabile.
   - Console: zero errori, zero warning CSP; Network: nessuna immagine caricata da domini esterni.
3. `grep -rn "http" frontend/src --include=*.tsx | grep -v "localhost" | grep -viE "spotify|deezer|youtube|google"` → nessun URL esterno inatteso.
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 08 di nucs.
1. Leggi piano/00-specifiche.md §11.2.2 §11.2.3 §11.3 §10 e piano/checklist-sicurezza.md (B5, F2).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: nessun hotlink esterno (F2), target=_blank sempre con rel="noopener noreferrer",
   date parziali gestite, duplicati in paginazione, race tra seen side-effect e cache react-query,
   accessibilità minima (focus, aria), nessun dato inventato oltre §10, stringhe UI in inglese.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Feed completo e filtri funzionanti nel browser su dati reali.
- [ ] Dettaglio con 4 bottoni verificati a mano.
- [ ] Zero errori console/CSP; nessuna immagine esterna.
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(frontend): releases feed and detail page with external links`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-09-ui-artisti-impostazioni`.
3. Apri `piano/fasi/fase-09-ui-artisti-impostazioni.md`.

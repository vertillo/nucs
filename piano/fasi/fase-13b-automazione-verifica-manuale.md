# FASE 13b — Automazione del sottoinsieme deterministico della verifica manuale (e2e:13)

- **Esecuzione**: **MODELLO** (lo scenario `e2e:13` esegue le voci deterministiche della checklist fase 13; il modello compila la tabella PASS/FAIL/N.A. in STATO.md)
- **Review**: modello **AVANZATO** (triage dei finding)
- **Dipende da**: fase 12b (mergiata) — complemento alla fase 13, che **non viene modificata**
- **Branch**: `git checkout -b fase-13b-automazione-verifica`

---

## 1. Obiettivo

La fase 13 è una checklist **umana** per design (timing reali, device, browser veri,
azioni adversarial). La 13b ne automatizza il **sottoinsieme deterministico** (~70 delle
99 voci) con un nuovo scenario browser `e2e:13`, che produce la **stessa "checklist
compilata"** (tabella `area | PASS/FAIL/N.A. | evidenza`) richiesta dal §4 della fase 13.

La 13b **non sostituisce** la 13: `piano/fasi/fase-13-verifica-manuale-completa.md` resta
invariato (nessuna voce rimossa, nessun esito pre-riempito). La tabella generata dallo
scenario viene incollata nella sezione FASE 13 di STATO.md come evidenza; l'operatore
esegue a mano **solo le voci residue** (vedi §2 "Confini") e fa il triage dei finding
secondo le regole della fase 13 (template FINDING-13-NN, severità, zero ALTA/MEDIA aperti).

## 2. Confini (cosa NON automatizza la 13b)

Voci della checklist fase 13 che restano **umane** (motivo):

| Voci | Motivo |
|---|---|
| **F4** (screen reader VoiceOver/NVDA) | richiede screen reader reale |
| **F7** (autofill password manager) | richiede un password manager/browser reale |
| **F2 / B8** (zoom 200%: giudizio visivo) | valutazione soggettiva di leggibilità/contrasto |
| **G8** (nessuna funzione fuori scope) | verifica semantica visiva (lo scenario fa solo un controllo DOM di base: niente `<audio>`, niente PWA manifest) |
| **J1-J2** (tunnel Cloudflare/Tailscale) | di competenza fase 14 (produzione) |
| **C11** (Favorite) | **N.A.** — pulsante rimosso in fase 12b (deviazione documentata in STATO.md) |

Inoltre: **J3** (audit log) e **J5** (backup integrity) sono eseguiti dallo scenario **solo
se l'ambiente docker è attivo** (variabile `E2E_PROD_STACK=1`), altrimenti marcati N.A.
con rinvio alla fase 14.

## 3. Prerequisiti

- Backend reale su DB di test (stesse env di e2e:12b: `DEV_INSECURE_COOKIES=true`,
  `NOTIFY_URLS=` vuoto, `ADMIN_USERNAME`/`ADMIN_PASSWORD`, `MUSIC_LIBRARY_PATH` reale).
- `axe-core` come nuova devDependency in `e2e/package.json` (solo tooling di test, come
  puppeteer; non tocca `frontend/package.json`).
- Node ≥ 20, puppeteer già installato (`npm ci` in `e2e/`).

## 4. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente:
- piano/fasi/fase-13-verifica-manuale-completa.md (checklist manuale, NON modificarla)
- piano/fasi/fase-12b-correzioni-utente.md (stile dello scenario e2e:12b)
- e2e/harness.js (launch, check, uiLogin, apiPost/apiPut/apiJson, waitForScanIdle, seed,
  state console/CSP/immagini, finish) e e2e/scenarios/fase-12b.js (stile dei check)
Branch: fase-13b-automazione-verifica. Codice/commenti inglese, docs in italiano.

OBIETTIVO
Nuovo scenario e2e/scenarios/fase-13.js + script "e2e:13" in e2e/package.json che
automatizza le voci deterministiche della checklist fase 13 (elenco per area sotto).
Il run termina con la tabella "area | PASS/FAIL/N.A. | evidenza" stampata a console e
salvata in e2e/artifacts/fase-13-results.md (checklist compilata da incollare in STATO.md).

INFRASTRUTTURA
- Riusa harness.js così com'è; dove servono due tab usa browser.createBrowserContext()
  (contesto incognito) con browser.newPage(); dove servono emulazioni usa CDP:
  page.emulateNetworkConditions (Slow 3G / offline), page.emulateMediaFeatures
  ([{name:'prefers-color-scheme',value:'light'}] e [{name:'prefers-reduced-motion',value:'reduce'}]),
  page.setCookie/deleteCookie (tampering cookie, A11), page.setViewport (4 larghezze).
- axe-core: importa axe-core (devDependency e2e) e lancia axe.run sul body di / e /artists
  e /settings nei due temi; filtra i soli risultati di tipo "color-contrast" + "label".
- Pattern riavvio backend (G4): come e2e:12 (spawn uvicorn con le stesse env, kill per
  porta di BASE) — lo scenario riavvia SOLO se richiesto da G4, alla fine.
- Seed: riusa la funzione h.seed / il seed di fase-12b (settings discovery_from_date
  2024-01-01, scans/library?full=true, scans/releases, waitForScanIdle).

COPERTURA PER AREA (riferimento: voci della checklist fase 13)
- A: A4 lockout globale con ATTESA REALE (~15 min: 10 fallimenti consecutivi →
  429+Retry-After; dopo l'intervallo il login corretto funziona); A5 timing curl
  (5 login utente inesistente vs 5 password errata, diff < 100 ms, stesso 401);
  A6 input limite (username vuoto/spazi/500+/emoji, password caratteri speciali → mai
  500); A7 doppio click "Log in" → una sessione coerente; A8 Enter dal campo password;
  A11 cookie tampering (rimuovi nucs_session → /login; valore inventato → 401 → /login;
  scadenza passata → /login).
- B: B1 toggle tema ×10 rapidi (mai bloccato); B4 localStorage "purple" → fallback dark;
  B7 prefers-color-scheme: light → nessun tema sbagliato al primo load (nessun flash:
  verifica il tema applicato subito dopo domcontentloaded).
- C: C3 combinazione Singles+Unseen only+ricerca; C4 ricerca caratteri speciali
  (% _ \ " ') → risultati letterali, nessun errore; C5 empty state "No new releases"
  + hint; C7 "Mark all as seen" con dialog Annulla → nulla cambia (page.on('dialog')
  risponde con dismiss), poi OK → pallini spariti; C9 /releases/999999 → "Release not
  found" + link al feed; C13 cover rotta (rinomina un file in covers/ via API sul DB di
  test → placeholder, nessun layout rotto); C14 Slow 3G → skeleton visibile poi card,
  richiesta fallita → messaggio + Retry; C15 doppio trigger "Load more" con rete lenta
  → nessuna card duplicata.
- E: E3 data futura/non valida in Discovery → errore inline; E14 Save con rete offline
  → messaggio di errore, nessuno stato UI corrotto.
- F: F1 viewport 320/375/768/1280 → nessuno scroll orizzontale su / , /artists, /settings,
  /release/{id}; F3 solo tastiera (Tab in ordine logico, focus ring accent, Enter/Space
  attivano bottoni e switch); F5 axe-core contrasto AA + label nei due temi su /, /artists,
  /settings; F6 prefers-reduced-motion (spinner/skeleton presenti ma non bloccanti);
  F8 375px: navbar compatta, link testuali nascosti, icone cliccabili.
- G: G3 modalità offline → azioni mutanti (seen, save settings) → errore inline, nessun
  crash; G4 riavvio backend con app aperta → comportamento documentato (401 → /login o
  ripristino); G5 backend con TZ diversa (es. Pacific/Kiritimati) → date API coerenti
  (UTC) e UI senza offset; G6 doppio click "Save" → una sola richiesta; G7 primo load
  su rete normale < ~3 s (performance.getEntriesByType('navigation')[0].duration).
- H (curl-equivalenti via fetch autenticato): H4 /releases/0, /-1, /999999999 → 404/422
  mai 500; H5 /covers/..%2F..%2Fetc%2Fpasswd → 400/404 mai 200; H6 ?q=<10k>, ?page_size=0
  → 422, ?page=999999 → lista vuota coerente; H7 PUT /settings chiave fuori whitelist →
  422; H8 PUT /settings {"theme":"purple"} → 422; H10 loop GET /api/health ×20 → sempre
  JSON veloce.
- I (due tab): I1 "Mark all as seen" in tab A → refresh tab B → aggiornato; I2 stesso
  dettaglio in due tab → nessun errore, seen coerente; I3 toggle tema simultaneo → al
  reload il tema è un valore valido; I4 avvia scan e fai logout → logout ok, scan
  prosegue (job background); I5 doppio click "Load more" → nessuna card duplicata;
  I6 "+ Add artist" doppio submit → un solo artista creato.
- J (solo se E2E_PROD_STACK=1): J3 audit log login_ok/login_fail senza segreti (leggi
  audit_log via sqlite su DATA_DIR); J5 backup file in /data/backups + sqlite3
  PRAGMA integrity_check → ok. Altrimenti N.A. documentato.
- G1/G2 finali: console pulita (solo 401 intenzionali), zero violazioni CSP, zero
  immagini da domini esterni (riuso state dell'harness).

VINCOLI
- NON modificare piano/fasi/fase-13-verifica-manuale-completa.md.
- NON modificare codice app (backend/ frontend/): la 13b è solo verifica; eventuali bug
  emersi diventano FINDING-13B-NN con fix in commit separati.
- I check con reti/flussi lenti usano timeout generosi (fino a 120 s) e non fanno
  assunzioni sulla velocità di MusicBrainz.
- Lo scenario termina con h.finish(...) e con l'export della tabella in
  e2e/artifacts/fase-13-results.md.

DELIVERABLE
- e2e/scenarios/fase-13.js + script "e2e:13" in e2e/package.json + axe-core devDep
- e2e/artifacts/fase-13-results.md generato dal run
- Sezione "FASE 13b" in piano/STATO.md con la tabella compilata + findings FINDING-13B-*
```

## 5. PROMPT DI VERIFICA (copia-incolla — il modello controlla il lavoro)

```text
Verifica la fase 13b di nucs.
1. Backend su DB test + `cd e2e && npm run e2e:13` → TUTTI i check PASS (le N.A. sono
   solo quelle dichiarate: F4/F7/F2/B8/G8-parziale/J1-J2/C11 e J3/J5 senza E2E_PROD_STACK).
2. `e2e/artifacts/fase-13-results.md` contiene la tabella area | PASS/FAIL/N.A. | evidenza
   con una riga per voce coperta.
3. Regressione: `npm run e2e:12b` e `npm run e2e:08` restano PASS (nessuna modifica agli
   scenari esistenti).
4. `npm audit` in e2e → 0 (axe-core incluso).
5. Tabella finale: controllo | PASS/FAIL | evidenza.
```

## 6. PROMPT DI REVIEW (copia-incolla — modello avanzato)

```text
Fai la review della fase 13b (triage dei finding della verifica automatizzata).
1. Per ogni FINDING-13B-*: severità corretta (regole fase 13 §3)? Bug vero o
   comportamento documentato (confronta con STATO.md)? Il fix proposto è minimo e
   coperto da test? Nessuno scope creep?
2. La copertura dichiarata corrisponde alle voci effettivamente eseguite dallo scenario?
   Le voci residue umane sono quelle del §2 della doc 13b (nessuna voce umana spacciata
   per automatica)?
3. Output: tabella findings (ALTA/MEDIA/BASSA | finding | problema | decisione) +
   VERDETTO: "FASE 13b CHIUSA" oppure "NON CHIUSA: <motivi>".
```

## 7. Criteri di completamento

- [ ] `e2e:13` verde (con N.A. solo dichiarate) + `e2e/artifacts/fase-13-results.md` generato.
- [ ] Nessuna modifica a `piano/fasi/fase-13-verifica-manuale-completa.md` e al codice app.
- [ ] Zero findings ALTA/MEDIA aperti senza decisione; i BASSA documentati.
- [ ] Eventuali fix in commit separati con test.
- [ ] STATO.md aggiornato (sezione FASE 13b con tabella + findings; la fase 13 resta
      "in corso": l'operatore esegue le voci residue con la tabella 13b come evidenza).
- [ ] Commit: `feat(e2e): phase 13b automated verification — e2e:13 scenario` (o
      `fix(...)` per i fix emersi).

## 8. Prossimo step

1. Fase 13: l'operatore esegue le sole voci residue (F4, F7, F2/B8, G8, J1-J2 e C11=N.A.)
   e fa triage dei finding con la tabella 13b già compilata.
2. Fase 14: produzione (boot container, tunnel Cloudflare/Tailscale, J1-J2/J3/J5 completi).
3. La 13b è riusabile: per ogni futura feature si ri-esegue lo scenario (o le sezioni
   impattate) prima del rilascio, esattamente come previsto dal §8 della fase 13.

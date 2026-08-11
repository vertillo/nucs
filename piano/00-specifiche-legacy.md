# LEGACY / HISTORICAL SPECIFICATION

This document describes an earlier NUCS specification (v1, written before phases
12b/13/15) and is **not authoritative** for current remediation or product behavior.

- Use **current code, migrations and tests** for the as-built implementation.
- Use **`docs/CURRENT_IMPLEMENTATION.md`** as the factual orientation map.
- Use **`docs/KNOWN_ISSUES.md`** and **`docs/REMEDIATION_RECONCILIATION.md`** for
  known defects and the gap between implementation and remediation requirements.
- Future authoritative product/remediation decisions will arrive as
  `NUCS_PRODUCT_DECISIONS.md` and `NUCS_REMEDIATION_SPEC.md` and will supersede
  this document where they explicitly define changed behavior.

The section-by-section disposition (STILL ACCURATE / IMPLEMENTATION DETAIL OUTDATED /
PRODUCT BEHAVIOR CHANGED LATER / NO LONGER APPLICABLE) of this document against the
current implementation is recorded in `docs/OMO_PREPARATION_REPORT.md`.

---

# SPECIFICHE TECNICHE — nucs (v1) [HISTORICAL CONTENT — see header above]

---

## 1. Visione e obiettivi

nucs è un'app web self-hosted, **single-user**, che:

1. Legge i tag della libreria musicale locale e ricava l'elenco degli artisti da monitorare:
   - artista traccia (`ARTIST`), album artist (`ALBUMARTIST`), artisti multipli,
   - **featuring** estratti da titoli e tag (es. "(feat. X)"),
   - **contributi** (performer/composer/remixer dove presenti).
2. Interroga periodicamente **MusicBrainz** (fonte primaria, gratuita, senza chiavi) per scoprire
   nuove release (album, singoli, EP) pubblicate da quegli artisti — **incluse release in cui
   compaiono solo come featuring**, anche di artisti mai ascoltati.
3. Mostra un **feed** delle nuove uscite (da una data configurabile) in una UI scura/chiara
   in stile app musicale (alla Spotify).
4. Ogni release ha una **pagina dettaglio** con bottoni verso Spotify, YouTube Music, Deezer,
   oppure ricerca Google come fallback.
5. È protetta da **login** (username+password), servita via **Docker Compose**, raggiungibile
   via **Cloudflare Tunnel** (HTTPS pubblico) e **Tailscale** (rete privata), senza porte aperte sul host.

### 1.1 Non-obiettivi (v1 — NON implementare, nemmeno parzialmente)

- Multi-utente / registrazione / ruoli.
- Riproduzione audio, integrazione con player, scrobbling, last.fm.
- App mobile nativa, PWA push notification.
- Download delle release, integrazione con *arr (Lidarr ecc.).
- Modifica dei tag dei file musicali (la libreria è montata **sola lettura**, sempre).

### 1.2 Arricchimenti rispetto alla richiesta originale (inclusi nella v1)

- Notifiche opzionali via **Apprise** (Telegram/ntfy/email/…) quando esce qualcosa.
- **Backup automatico** giornaliero del database (retention 7 giorni).
- Gestione artisti: ignora/riabilita, aggiunta manuale, retry abbinamento MusicBrainz.
- Stato per release: **vista / nascosta / preferita**; "segna tutte come viste".
- Audit log degli accessi e rate limiting anti brute-force sul login.
- Lista sessioni attive con revoca; cambio password che revoca le altre sessioni.
- Cache locale delle copertine (privacy, CSP stretta, funziona anche se l'hotlink muore).
- Healthcheck, log strutturati con rotazione, metriche di scan visibili in impostazioni.
- Header di sicurezza completi, container non-root, limiti di risorse, nessuna porta pubblicata.

---

## 2. Stack tecnologico (vincolante)

| Componente | Scelta | Motivo |
|---|---|---|
| Linguaggio backend | **Python 3.12** | Ecosistema tag/audio (mutagen), ottimo per modelli LLM |
| Framework API | **FastAPI** (ASGI, async) | Tipizzato, docs automatiche, leggero |
| Server | **Uvicorn** (1 worker) | 16 GB RAM ma inutile sprecare: workload basso |
| DB | **SQLite** (WAL mode) via **SQLAlchemy 2.0** (core+ORM) | Zero servizi extra, backup = copia file |
| Migrazioni | **Alembic** (autogenerate, eseguite all'avvio) | Evoluzione schema sicura |
| Scheduler | **APScheduler 3.x** (AsyncIOScheduler, jobstore in-memory) | Scan periodici dentro il processo app |
| Tag audio | **mutagen** | Standard de facto |
| HTTP client | **httpx** (async) + **tenacity** (retry) | MusicBrainz/Deezer/Spotify |
| Password hashing | **argon2-cffi** (argon2id) | Best practice OWASP |
| Notifiche | **Apprise** | Una dipendenza, decine di servizi |
| Frontend | **Vite + React 18 + TypeScript + TailwindCSS 3.4 + react-router-dom 6 + @tanstack/react-query 5** | SPA statica servita dal backend: zero server Node in produzione |
| Build frontend | Node 20 (solo in build Docker) | |
| Container | Docker multi-stage, `python:3.12-slim`, utente non-root, `tini` | |
| Orchestrazione | Docker Compose v2 | |

### 2.1 Regole dipendenze

- `backend/requirements.txt`: versioni **esatte** (`==`). Commentare accanto a ogni riga il motivo se non ovvio.
- `frontend/package.json` con versioni esatte + `package-lock.json` committato.
- Niente dipendenze "di moda" non elencate qui senza annotarlo in `STATO.md`.

---

## 3. Struttura del repository (vincolante)

```
/
├── piano/                      # questo piano (committato)
├── backend/
│   ├── requirements.txt
│   ├── requirements-dev.txt    # pytest, ruff, mypy(opz.), httpx(test)
│   ├── alembic.ini
│   ├── alembic/versions/
│   └── app/
│       ├── main.py             # create_app(), mount static, middleware
│       ├── config.py           # pydantic-settings, lettura env
│       ├── db.py               # engine, session, init, WAL pragma
│       ├── models.py           # tabelle SQLAlchemy
│       ├── schemas.py          # pydantic I/O
│       ├── security.py         # hashing, sessioni, rate limit, header
│       ├── deps.py             # dipendenze FastAPI (auth required ecc.)
│       ├── api/
│       │   ├── auth.py
│       │   ├── releases.py
│       │   ├── artists.py
│       │   ├── settings.py
│       │   └── scans.py
│       ├── services/
│       │   ├── library_scan.py # parsing tag
│       │   ├── mb_matching.py  # artista -> MBID
│       │   ├── discovery.py    # nuove release
│       │   ├── links.py        # link spotify/ytm/deezer/google
│       │   ├── covers.py       # cache copertine
│       │   ├── musicbrainz.py  # client con rate limit 1 req/s
│       │   ├── deezer.py
│       │   ├── spotify.py      # opzionale
│       │   ├── notify.py       # apprise
│       │   └── backup.py
│       ├── scheduler.py        # job periodici
│       └── cli.py              # create-admin, scan-once, ecc.
│   └── tests/
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/
│       ├── main.tsx
│       ├── App.tsx             # router
│       ├── api/client.ts       # fetch wrapper con gestione 401
│       ├── theme.ts            # toggle dark/light
│       ├── pages/ Login.tsx Feed.tsx ReleaseDetail.tsx Artists.tsx Settings.tsx
│       └── components/ ReleaseCard.tsx LinkButtons.tsx Navbar.tsx ...
├── docker/
│   └── Dockerfile              # multi-stage unico (fe build -> runtime)
├── deploy/
│   ├── cloudflared.md          # istruzioni tunnel (generate in fase 11)
│   └── tailscale/
│       └── serve.json
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .github/workflows/ci.yml    # lint + test (fase 00)
└── README.md                   # guida utente finale (fase 12)
```

---

## 4. Modello dati (SQLite)

Tutti i timestamp in **UTC ISO-8601** (`TEXT` o `DATETIME` con tz normalizzata). La UI converte in locale.

### Tabella `artists`
| colonna | tipo | note |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | nome come da tag (o input manuale) |
| normalized_name | TEXT UNIQUE | vedi §6.3 |
| mbid | TEXT NULL UNIQUE | MusicBrainz artist id |
| mb_match_score | INTEGER NULL | 0-100 |
| source | TEXT | `tag_artist` \| `tag_albumartist` \| `tag_feat` \| `tag_contrib` \| `manual` |
| ignored | INTEGER | 0/1, default 0 |
| created_at | TEXT | |

### Tabella `releases`
| colonna | tipo | note |
|---|---|---|
| id | INTEGER PK | |
| rgid | TEXT UNIQUE | MusicBrainz **release-group** id |
| title | TEXT | |
| primary_artist | TEXT | artist credit "display" |
| type | TEXT | `album` \| `single` \| `ep` \| `other` |
| secondary_types | TEXT | CSV, es. `Live,Compilation` (può essere vuota) |
| first_release_date | TEXT | `YYYY` / `YYYY-MM` / `YYYY-MM-DD` (formato MB) |
| cover_url | TEXT NULL | URL sorgente |
| cover_path | TEXT NULL | path locale cache (relativo a `COVERS_DIR`) |
| spotify_url / deezer_url / ytm_url / google_url | TEXT NULL | precomputati in fase 06 |
| discovered_at | TEXT | |

### Tabella `release_artists` (molti-a-molti)
| release_id | artist_id | role |
PK composta (release_id, artist_id). `role`: `primary` \| `featured` \| `contributor`.

### Tabella `release_state`
| release_id INTEGER PK FK | seen INTEGER 0/1 | hidden INTEGER 0/1 | favorite INTEGER 0/1 | seen_at TEXT NULL |

### Tabella `settings` (key-value)
| key TEXT PK | value TEXT |

Chiavi (default):
| key | default | note |
|---|---|---|
| `discovery_from_date` | oggi − 30 giorni (ISO date) | data da cui scoprire release |
| `scan_library_time` | `03:00` | orario giornaliero scan libreria |
| `scan_releases_time` | `04:00` | orario giornaliero discovery |
| `feat_scan_enabled` | `true` | scan featuring livello traccia (settimanale) |
| `feat_scan_weekday` | `sun` | giorno scan feat |
| `theme` | `dark` | `dark` \| `light` |
| `notify_enabled` | `false` | |
| `notify_urls` | `` | CSV di URL Apprise |
| `spotify_client_id` / `spotify_client_secret` | `` | mai restituiti in chiaro via API (vedi §8.4) |
| `release_types` | `album,single,ep` | tipi inclusi nel feed |

### Tabella `sessions`
| id_hash TEXT PK (sha256 del token) | created_at | expires_at | last_seen_at | ip | user_agent |

### Tabella `audit_log`
| id PK | ts | event TEXT (`login_ok`,`login_fail`,`logout`,`password_change`,`settings_change`,`scan_run`,…) | ip | detail TEXT (JSON, mai segreti) |

### Tabella `scan_runs`
| id PK | type (`library`,`releases`,`feat`) | started_at | finished_at | status (`ok`,`error`) | stats TEXT (JSON: contatori) |

Indici: `releases(first_release_date DESC)`, `release_artists(artist_id)`, `sessions(expires_at)`, `audit_log(ts)`.

---

## 5. Autenticazione e sicurezza (vincolante)

### 5.1 Utente e password
- **Un solo utente admin**. Username e password iniziali: variabili env `ADMIN_USERNAME` / `ADMIN_PASSWORD`
  lette **solo al primo avvio** (se il DB non ha utente) **oppure** create via CLI `python -m app.cli create-admin`.
  Se nessuna delle due è presente, l'app si rifiuta di avviarsi con messaggio chiaro nei log.
- Hash: **argon2id** (parametri default argon2-cffi: time=3, mem=64MB, par=4; se troppo pesante sul mini PC, mem=32MB accettabile — annotarlo).
- Policy password: min 12 caratteri. Al cambio password, verificare policy + conferma.
- La password iniziale da env deve poter essere cambiata dalla UI (pagina impostazioni); dopo il cambio,
  il valore env **non ha più alcun effetto** (la fonte è il DB). Documentarlo.

### 5.2 Sessioni
- Token opaco: `secrets.token_urlsafe(32)`, cookie `nucs_session`.
- Cookie: `HttpOnly`, `Secure` (disattivabile SOLO via env `DEV_INSECURE_COOKIES=true` per sviluppo locale),
  `SameSite=Lax`, `Path=/`, **nessun** `Domain`. Durata 7 giorni, rolling (rinnovo `expires_at` a ogni richiesta autenticata se mancano < 3 giorni).
- Nel DB si salva **solo sha256(token)**, mai il token.
- Tabella sessioni → sezione "Active sessions" in impostazioni (browser, IP, ultimo uso) + bottone "Revoke other sessions".
- Cambio password → revoca automatica di tutte le altre sessioni.
- Cleanup: job orario cancella sessioni scadute.

### 5.3 Protezione login (anti brute-force)
- Rate limit per IP: **5 tentativi / 5 minuti** su `POST /api/v1/auth/login` (finestra scorrevole in memoria;
  chiave = IP effettivo, vedi §5.6).
- Dopo 10 fallimenti consecutivi (qualsiasi IP) → blocco globale login 15 minuti (risposta 429 con `Retry-After`).
- Risposta generica identica per utente inesistente/password errata: `401 {"detail":"Invalid credentials"}`.
- Ritardo costante: verifica hash anche se lo username non esiste (hash dummy) per non leakare l'esistenza dell'utente.
- Ogni tentativo (ok/fail) → `audit_log`.

### 5.4 Protezione richieste mutanti (CSRF)
- Tutte le `POST/PUT/PATCH/DELETE` richiedono header `X-Requested-With: XMLHttpRequest`
  **e** header `Origin` (o `Referer`) che combacia con l'host della richiesta; altrimenti `403`.
- (Con SameSite=Lax + questo controllo l'app è protetta da CSRF classico.)

### 5.5 Header di sicurezza (middleware su TUTTE le risposte)
```
Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```
- HSTS (`max-age=31536000; includeSubDomains`) **solo** se la richiesta arriva in HTTPS (dietro CF/Tailscale lo è).
- Nessun header `Server`/`X-Powered-By` esposto.
- Le copertine esterne NON vengono caricate dal browser: passano dalla cache locale (`/api/v1/covers/...`)
  proprio per mantenere CSP stretta (`img-src 'self'`).
- `robots.txt` → `Disallow: /` + header `X-Robots-Tag: noindex` su tutte le pagine.

### 5.6 Proxy e IP reali
- L'app gira dietro cloudflared/tailscale → fidarsi di `X-Forwarded-For` **solo** dalla rete Docker interna
  (`TRUSTED_PROXY_CIDRS=172.16.0.0/12,10.0.0.0/8` env-configurabile). Uvicorn con `--proxy-headers`.
- Tutti gli endpoint (tranne `GET /api/health`, asset statici, login) richiedono sessione valida → `401`.

### 5.7 Errori e log
- Mai stack trace al client in produzione: handler globale → `500 {"detail":"Internal error"}` + log completo server-side.
- Log strutturati (JSON o key=value) su stdout, livello env `LOG_LEVEL` (default `INFO`).
- **Mai** loggare: password, token di sessione, secret Spotify, cookie. Redazione esplicita.
- Log di accesso HTTP disattivati per `/api/health` (rumore).

### 5.8 Segreti
- Tutto via env (file `.env` non committato, `.env.example` con placeholder).
- `docker-compose.yml` non contiene segreti inline, solo `${VAR}`.
- Endpoint settings: i campi segreti (Spotify secret) si scrivono ma **non si leggono**: GET restituisce `{"spotify_client_secret_set": true}`.

---

## 6. Scansione libreria e artisti

### 6.1 Formati supportati
`mp3` (ID3v2), `flac` (Vorbis comment), `m4a`/`mp4`/`aac`, `ogg`/`opus`, `wma` (best effort), `ape`? No: **mp3, flac, m4a/mp4, ogg/opus** soltanto. File illeggibili → contati e loggati (warning), mai bloccanti.

### 6.2 Tag letti
| Concetto | ID3v2 (mp3) | Vorbis (flac/ogg) | MP4 (m4a) |
|---|---|---|---|
| Artista traccia | TPE1 | ARTIST (+ ARTISTS se presente) | ©ART |
| Album artist | TPE2 | ALBUMARTIST | aART |
| Titolo | TIT2 | TITLE | ©nam |
| Featuring nel titolo | parsing testo | parsing testo | parsing testo |
| Contributi | TIPL/TMCL (performer, composer, remixer) | PERFORMER, COMPOSER, REMIXER | (best effort) |

### 6.3 Normalizzazione nome (funzione `normalize_name`, usata ovunque)
1. `unicodedata.normalize("NFKD", s)` → rimuovere caratteri combining (accenti).
2. `lower()`.
3. Rimuovere punteggiatura (`[^\w\s]` → spazio), underscore → spazio.
4. Collassare spazi multipli, trim.
Esempio: `"Beyoncé"` → `beyonce`, `"AC/DC"` → `ac dc`.

### 6.4 Split multi-artista e featuring — algoritmo (vincolante)
1. Preservare il nome completo come candidato.
2. Estrarre featuring dal **titolo**: regex su `(...)`/`[...]` contenenti `feat.|ft.|featuring|con` → cattura nomi interni; anche suffisso ` (feat. X & Y)` etc.
3. Splittare i campi artista su: `;`, ` feat. `, ` ft. `, ` featuring `, ` & ` (solo se spazi attorno), `, ` (solo se il risultato produce ≥2 nomi che matchano artisti noti o MB), ` vs `, ` with `, ` con `.
   **NON** splittare su `/` (AC/DC) né su ` & ` attaccato.
4. **Regola match-first**: prima di splittare, provare il match MusicBrainz del nome intero (fase 04);
   se score ≥ 90 → tenere il nome intero come singolo artista (salva "Earth, Wind & Fire").
5. Ogni nome risultante → `artists` con `source` appropriata (`tag_feat` per i featuring dal titolo,
   `tag_contrib` per performer/composer/remixer). Dedup su `normalized_name`.
6. I nomi con meno di 2 caratteri o banali ("various artists", "aa.vv.", "unknown") → ignorati (lista hardcoded).

### 6.5 Incrementale
- Scan basato su `mtime`: tabella `scan_files(path PK, mtime, size)` per rieseguire solo file nuovi/modificati.
- Bottone "Forza scan completo" in impostazioni (svuota `scan_files`).

---

## 7. MusicBrainz — uso e galateo (vincolante)

- Base URL: `https://musicbrainz.org/ws/2/`, formato JSON (`fmt=json`).
- **User-Agent obbligatorio**: `nucs/1.0 ( <email impostazioni> )` — chiave settings `mb_contact_email`,
  default placeholder da completare; se mancante, usare `nucs/1.0 ( selfhosted )`.
- **Rate limit globale**: max **1 richiesta/secondo** verso musicbrainz.org (token bucket in-process,
  condiviso da tutti i job). Retry con backoff esponenziale su 429/5xx (max 5 tentativi, tenacity).
- Cover Art Archive (`https://coverartarchive.org/`) stesso rate limit logico (condiviso ok).
- Le date MB possono essere parziali (`2024`, `2024-05`): confronto con `discovery_from_date` fatto
  trattando data parziale come **primo giorno possibile** (`2024` → `2024-01-01`) e come **ultimo**
  (`2024` → `2024-12-31`); una release "entra" se l'intervallo interseca `[discovery_from_date, oggi]`.

---

## 8. Discovery release

### 8.1 Livello 1 — release degli artisti + featuring a livello release (giornaliero)
Per ogni artista non ignored **con mbid**:
- Query Search release-group:
  `GET /ws/2/release-group/?query=arid:{mbid} AND firstreleasedate:[{from} TO *]&fmt=json&limit=100`
  dove `from` = `discovery_from_date` (ma vedi cursore sotto).
- Filtro client-side: `primary-type` ∈ {Album, Single, EP} (mappati a `album|single|ep`; altro → `other`
  e incluso solo se `release_types` lo prevede — default no). Escludere secondary-type `Live`? No:
  **includere tutto**, salvare `secondary_types` e filtrare in UI (default feed esclude `Compilation`? NO —
  default include tutto, filtro disponibile).
- La search con `arid` trova anche release-group dove l'artista è nell'artist credit **non primario**
  (tipico dei singoli "X feat. Y") → soddisfa il requisito featuring nel 90% dei casi.
- **Cursore per-artista** (`artists.last_release_check` TEXT): alle run successive alla prima, `from` =
  max(`discovery_from_date`, ultima `first_release_date` vista − 7 giorni) per ridurre i risultati.
- Ruolo: se l'artista monitorato è l'unico/primo nell'artist credit → `primary`, altrimenti `featured`.
  (Euristica semplice: `primary` se l'artist-credit-phrase inizia col nome dell'artista; altrimenti `featured`.)
- Upsert per `rgid`; più artisti monitorati sulla stessa release → più righe in `release_artists`.

### 8.2 Livello 2 — featuring a livello traccia (settimanale, opzionale `feat_scan_enabled`)
Per catturare album di terzi con un pezzo feat. (artista non nell'artist credit della release):
- `GET /ws/2/recording/?artist={mbid}&fmt=json&limit=100&offset=...` (browse, paginato).
- Per ogni recording non nota, `inc=releases` → raccogliere release; fetch release-group di ogni release;
  filtrare per data come sopra; registrare con role `featured`.
- Costo alto per artisti prolifici → per questo è settimanale e disattivabile. Paginazione **obbligatoria**
  con rispetto del rate limit; interrompibile (persiste offset per artista in caso di restart? No — semplice:
  se fallisce, riparte la settimana dopo; annotare in stats quante pagine lette).

### 8.3 Spotify opzionale (se credenziali presenti)
- Client credentials flow, token cache in memoria.
- Per ogni artista (match per nome → spotify id, cached): `GET /v1/artists/{id}/albums?include_groups=album,single,appears_on&limit=50`
  → merge con risultati MB (match per titolo normalizzato+data; se dubbio, tenere entrambi ma dedup per rgid/titolo+data).
- Arricchisce `spotify_url` diretto. Se assente → fase 06 genera URL di ricerca.

### 8.4 Pipeline dopo discovery
Per ogni release **nuova** inserita:
1. Cover: Cover Art Archive `release-group/{rgid}/front-250` (e `-500` per dettaglio); se 404 → Deezer search album → cover; se fallisce → placeholder. Download in `COVERS_DIR/{rgid}.jpg` (async, non blocca il job).
2. Link (vedi §9).
3. Se `notify_enabled` → notifica Apprise in inglese (1 notifica aggregata per run: "nucs: N new releases", non 1 per release).

### 8.5 Dedup e integrità
- Unicità per `rgid`. Release senza data → accettata solo se scoperta via arid con cursore (significa che è recente per costruzione) e marcata `first_release_date=""` e mostrata in coda al feed? **No**: release senza data vengono inserite ma escluse dal feed di default (filtro UI "senza data" disponibile in futuro — v1: escluse e loggate in stats).

---

## 9. Link esterni (vincolante — formato esatto)

Costruiti in fase 06 e salvati su `releases`:
- **Spotify**: se fase 8.3 ha trovato l'album → `https://open.spotify.com/album/{id}`; altrimenti
  `https://open.spotify.com/search/{urlencode(primary_artist + " " + title)}`
- **YouTube Music**: sempre `https://music.youtube.com/search?q={urlencode(primary_artist + " " + title)}`
- **Deezer**: prova risoluzione diretta via API gratuita `https://api.deezer.com/search/album?q=artist:"{a}" album:"{t}"&limit=1`
  → se hit con title match normalizzato → `https://www.deezer.com/album/{id}`; altrimenti `https://www.deezer.com/search/{q}`
- **Google fallback**: sempre presente: `https://www.google.com/search?q={urlencode(primary_artist + " " + title + " " + type)}`
- La pagina dettaglio mostra **tutti** i bottoni disponibili (Spotify, YTM, Deezer, Google): il "fallback Google"
  non sostituisce gli altri, è un'opzione aggiuntiva sempre visibile.

---

## 10. API REST (vincolante)

Base: `/api/v1`. Tutte le risposte JSON. Errori: `{"detail": "..."}` con status adeguato.
Paginazione: `?page=1&page_size=30` (max 100) → `{"items": [...], "total": n, "page": p, "page_size": s}`.

| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/auth/login` | no | body `{username, password}` → 204 + Set-Cookie; 401/429 come da §5.3 |
| POST | `/auth/logout` | sì | revoca sessione corrente → 204 |
| GET | `/auth/me` | sì | `{username, theme}` |
| POST | `/auth/password` | sì | `{current_password, new_password}` → 204; revoca altre sessioni |
| GET | `/auth/sessions` | sì | lista sessioni attive (ip, ua, last_seen, current flag) |
| POST | `/auth/sessions/revoke-others` | sì | 204 |
| GET | `/releases` | sì | filtri: `from`,`to`,`type` (CSV),`artist_id`,`seen` (`all\|yes\|no`, default `all`),`favorite`,`hidden` (default `no`),`q` (search titolo/artista), sort `date_desc` (default) / `date_asc` |
| GET | `/releases/{id}` | sì | dettaglio + `matched_artists: [{id,name,role}]` + link; **side-effect: seen=true** |
| POST | `/releases/{id}/state` | sì | `{seen?, hidden?, favorite?}` merge → stato aggiornato |
| POST | `/releases/seen-all` | sì | `{from?, to?}` → marca viste (solo non hidden) → `{updated: n}` |
| GET | `/artists` | sì | filtri `ignored`,`q`,`source`; include `releases_count` |
| POST | `/artists` | sì | `{name}` → aggiunta manuale + tentativo match MB |
| PATCH | `/artists/{id}` | sì | `{ignored?}` |
| POST | `/artists/{id}/rematch` | sì | ritenta match MB → risultato |
| GET | `/settings` | sì | tutte le chiavi NON segrete + flag `*_set` per le segrete |
| PUT | `/settings` | sì | aggiorna chiavi whitelisted (validazioni: date ISO, time HH:MM, url apprise) |
| POST | `/settings/notify-test` | sì | invia notifica Apprise di prova → `{"sent": true}` o errore dettagliato |
| POST | `/scans/{type}` | sì | `type` ∈ `library` \| `releases` \| `feat` → avvia job manuale (409 se già in corso) |
| GET | `/scans/status` | sì | ultimi 10 `scan_runs` + job in corso |
| GET | `/covers/{rgid}` | sì* | serve copertina dalla cache (*dietro auth; content-type image/*; cache-control 7gg) |
| GET | `/api/health` | no | `{"status":"ok","version":"1.0.0"}` — usato da Docker healthcheck |

Validazioni input con pydantic; `q` max 200 char; id interi positivi. 404 standard `{"detail":"Not found"}`.
Tutti i messaggi di errore visibili all'utente (campo `detail`) sono in **inglese**.

---

## 11. UI/UX (vincolante)

### 11.1 Tema e palette (token Tailwind, entrambi i temi via classe `.dark` su `<html>`)
```
accent:        #1DB954 (hover #1ED760, active #169C46)   /* verde "musicale" */
dark.bg:       #0F0F0F   dark.surface: #181818   dark.surface2: #242424   dark.border: #2C2C2C
dark.text:     #F5F5F5   dark.textDim: #A3A3A3
light.bg:      #FFFFFF   light.surface:#F6F6F6   light.surface2:#FFFFFF   light.border:#E4E4E4
light.text:    #131313   light.textDim:#5C5C5C
danger:        #E5484D   badgeNuova: accent
```
Font: stack di sistema (`-apple-system, Segoe UI, Roboto, Inter, sans-serif`). Angoli: card `rounded-2xl`,
copertine `rounded-xl`, bottoni `rounded-full`. Ombre morbide sulle card (solo dark: `shadow-black/40`).
Tema default `dark`; toggle in navbar (icona sole/luna) persistito in settings (via API) + `localStorage` per evitare flash.

### 11.2 Pagine
1. **/login**: centrata, logo "🎵 nucs", card con username/password, errore generico inline, bottone accent. Sfondo bg.
2. **/** (feed): navbar (logo, link Feed/Artists/Settings, toggle tema, logout). Sotto: titolo "New releases",
   riga filtri: chip tipo [All|Albums|Singles|EPs], toggle "Unseen only", input ricerca (placeholder "Search…"),
   bottone "Mark all as seen".
   Lista card (grid 2-6 colonne responsive; mobile 2): copertina quadrata, titolo (max 2 righe), artista/i
   (i tuoi artisti monitorati in **accent**, gli altri in textDim), data, badge tipo, pallino accent se non vista.
   Paginazione: bottone "Load more" in fondo. Empty state: illustrazione testuale + CTA "Run scan".
3. **/releases/:id**: layout a 2 colonne (mobile: stack): copertina grande (max 384px), titolo H1, artisti con ruoli
   ("Main artist", "Featuring your tracked artists: X, Y"), data completa, tipo + secondary types,
   riga bottoni: **Spotify / YouTube Music / Deezer / Search on Google** (bottoni pill con icona testuale,
   colori: Spotify accent, YTM rosso `#FF0000`, Deezer viola `#A238FF`, Google surface2 con bordo — aprono in `_blank` con `rel="noopener noreferrer"`),
   toggle "Seen / Favorite / Hide". Freccia "← Back to feed".
4. **/artists**: tabella/cards: nome, badge sorgente (Artist/Album artist/Featuring/Contributor/Manual), stato match MB
   (✅ + score / ⚠️ "Unmatched" + bottone "Retry"), n. release, toggle "Ignore". Ricerca (placeholder "Search artist…")
   + bottone "Add artist" (modale con input nome).
5. **/settings** (sezioni a card):
   - **Discovery**: data "Discover releases from" (input date), tipi inclusi (checkbox Albums/Singles/EPs), switch "Weekly featuring scan".
   - **Scans**: orari (input time), bottoni "Scan library now" / "Check for new releases now" con spinner,
     tabella "Recent scans" (tipo, data, esito, contatori).
   - **Notifications**: switch + textarea "Apprise URLs (one per line)" + bottone "Send test notification".
   - **Integrations**: Spotify client id/secret (secret mascherato, solo riscrittura), "MusicBrainz contact email".
   - **Appearance**: radio Dark/Light.
   - **Security**: cambio password (attuale + nuova×2), lista "Active sessions" + "Revoke other sessions".
   - **About**: versione app, artisti monitorati (n), release nel DB (n), path libreria (read-only).

### 11.3 Comportamenti
- Fetch centralizzato: su 401 → redirect `/login`. Loading skeleton sulle card. Errori API → toast inline semplice.
- Tutte le date mostrate in formato **ISO 8601** (`YYYY-MM-DD`; date parziali mostrate così come sono: `2024`, `2024-05`), calcolate nel timezone del browser.
- Accessibilità minima: contrasto AA su testo, focus visibile (`ring-2 ring-accent`), bottoni con `aria-label`.
- Responsive: breakpoint mobile < 640px gestito (grid 2 col, navbar compatta).
- Lingua UI: **inglese** (tutte le stringhe visibili, messaggi di errore, notifiche e email di sistema).

---

## 12. Docker e rete (vincolante)

### 12.1 Dockerfile unico multi-stage (`docker/Dockerfile`)
1. Stage `fe`: `node:20-alpine` → `npm ci` → `npm run build` → `/frontend/dist`.
2. Stage `runtime`: `python:3.12-slim` → install `requirements.txt` (no cache dir), copia `backend/`,
   copia `dist` da stage fe in `/app/static`, crea utente non-root `app` (uid 1000), `tini` come entrypoint,
   `HEALTHCHECK` su `http://127.0.0.1:8080/api/health`, CMD `uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers`.
3. `.dockerignore`: node_modules, .git, piano/ (il piano non serve nel container), data/.

### 12.2 docker-compose.yml (servizi)
- `app`: build `./docker`, **nessuna porta pubblicata** (solo `expose: 8080` sulla rete interna),
  volumi: `nucs-data:/data` (DB, covers, backup), `${MUSIC_LIBRARY_PATH}:/music:ro`,
  env_file `.env`, `restart: unless-stopped`, `mem_limit: 768m`, `cpus: 1.5`,
  `read_only: true` + `tmpfs: /tmp` (app scrive solo in `/data`).
- `cloudflared`: `cloudflare/cloudflared:latest` → comando `tunnel --no-autoupdate run --token ${CF_TUNNEL_TOKEN}`,
  `mem_limit: 128m`, dipende da `app`. Profilo `cloudflare`.
- `tailscale`: `tailscale/tailscale:latest`, volumi `ts-state:/var/lib/tailscale` + `/dev/net/tun`,
  `TS_SERVE_CONFIG=/config/serve.json` (proxy https→`http://app:8080`), `TS_HOSTNAME=nucs`,
  auth: `TS_AUTHKEY` opzionale altrimenti login interattivo documentato. `mem_limit: 256m`. Profilo `tailscale`.
- Rete: `nucs-net` (bridge interna). Volumi named: `nucs-data`, `ts-state`.
- L'host **non espone nulla**: si accede solo via tunnel CF (https pubblico) o tailnet.

### 12.3 Env (.env.example — vincolante)
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=                # solo primo avvio, poi cambiala dalla UI
MUSIC_LIBRARY_PATH=/srv/musica
TZ=Europe/Rome
LOG_LEVEL=INFO
DATA_DIR=/data
COVERS_DIR=/data/covers
DEV_INSECURE_COOKIES=false
CF_TUNNEL_TOKEN=
TS_AUTHKEY=
TRUSTED_PROXY_CIDRS=172.16.0.0/12,10.0.0.0/8
```

---

## 13. Test e qualità (vincolante)

- Backend: **pytest**. Copertura minima su `services/` e `security.py`: parsing tag (fixture con file sintetici
  generati con mutagen in tmp), normalize_name, split artisti (casi: AC/DC, Earth Wind & Fire, "A feat. B",
  "A & B", "A, B"), link builder, auth (login ok/ko, rate limit, sessione), API releases (filtri, paginazione, seen),
  settings PUT validazioni. Target: **≥ 70%** su `app/services` + `app/security.py` (misurato con pytest-cov).
- Lint: `ruff check` + `ruff format --check` (config in `pyproject.toml`). Frontend: `tsc --noEmit` + `eslint` (config base vite) — eslint opzionale se rallenta, `tsc` obbligatorio.
- CI (GitHub Actions o nessuna se repo locale — fase 00 decide, default: file presente ma opzionale).
- Test E2E manuale: checklist in fase 12.

---

## 14. Criteri di accettazione finali (Definition of Done del progetto)

1. `docker compose --profile cloudflare --profile tailscale up -d` su macchina pulita con `.env` compilato → app raggiungibile via URL Cloudflare e via `https://nucs.<tailnet>.ts.net`.
2. Senza login, ogni pagina/API (tranne health) → redirect/401. Login con brute force (6 tentativi) → 429.
3. Scan libreria su una cartella di test (≥ 100 file con featuring nei titoli) → artisti estratti inclusi feat. e album artist.
4. Dopo match MB + discovery con `discovery_from_date` = 60 giorni fa → feed popolato, card con copertina,
   apertura dettaglio → 4 bottoni link funzionanti.
5. Cambio `discovery_from_date` in impostazioni + scan manuale → il feed si aggiorna coerentemente.
6. Tema chiaro/scuro persistente al reload.
7. Container app < 300 MB RAM a riposo (verificato con `docker stats`).
8. `pip-audit` e `npm audit` senza vulnerabilità high/critical non giustificate (annotare eccezioni in STATO.md).
9. Backup DB presente in `/data/backups/` dopo 24h o run manuale.
10. README.md finale con: setup, variabili env, Cloudflare tunnel step-by-step, Tailscale, FAQ.

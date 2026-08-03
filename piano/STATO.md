# STATO DEL PROGETTO — diario di avanzamento

> Questo file viene aggiornato dal modello alla fine di ogni fase.
> Ogni prompt di fase inizia leggendo questo file + `piano/00-specifiche.md`.
> Formato: una sezione per fase completata, più recente in cima.

## Riepilogo rapido

- Fase corrente: **04** → aprire `piano/fasi/fase-04-matching-artisti.md`
- Fasi completate: 00, 01, 02, 03
- Branch attivo: `fase-04-matching-artisti` (fase-03 mergiata su main dopo review)
- Problemi aperti: warning deprecazione `httpx2` da `fastapi.testclient` (non bloccante); header `server: uvicorn` visibile in dev (fix in fase 11, vedi sotto)
- Idee emerse ma rimandate (v2): nessuna

---

## FASE 03 — Scansione libreria musicale ed estrazione artisti — 2026-08-03
- Branch: fase-03-scan-libreria
- Cosa è stato fatto:
  - `backend/requirements.txt`: aggiunto `mutagen==1.48.1` (commento inline: lettura tag audio, spec 6). Installato e verificato su Python 3.12.13.
  - `backend/app/models.py`: nuova tabella `ScanFile(path PK, mtime INTEGER (st_mtime_ns), size INTEGER)` (§6.5) + migration Alembic `f78ca2bec293_add_scan_files_table` (catena lineare da `9cb782c0d8f5`).
  - `backend/app/services/names.py`: `normalize_name` esattamente §6.3 (NFKD → strip combining → lower → `[^\w\s]`→spazio + `_`→spazio → collapse spazi); `extract_feat_from_title` (regex case-insensitive su gruppi `(...)`/`[...]` con keyword `feat.|ft.|featuring|con`, split interno su `,`/`&`/` e `; **solo parentesi**, il suffisso `" - feat. X"` senza parentesi NON è gestito — documentato nel docstring, per fase 04); `is_trivial_artist` (varianti lower/raw + normalizzate di "various artists", "aa.vv.", "unknown artist", "unknown", nomi < 2 char, §6.4.6).
  - `backend/app/services/library_scan.py`: `scan_library_sync(full=False)` — `os.walk(followlinks=False)` di `MUSIC_LIBRARY_PATH` (estensioni .mp3/.flac/.m4a/.mp4/.ogg/.opus case-insensitive); lettura tag con `mutagen.File(easy=False)` con mappatura §6.2 per ID3 (TPE1/TPE2/TIT2/TIPL/TMCL), Vorbis/FLAC/Ogg (ARTIST+ARTISTS/ALBUMARTIST/TITLE/PERFORMER/COMPOSER/REMIXER), MP4 (©ART/aART/©nam, `©wrt` best-effort come compositore); split SOLO su `;` (decisione operativa §6.4) + trim + dedup; feat dal titolo → `tag_feat`; upsert su `normalized_name` con regola source forte/debole (tag_artist/tag_albumartist sovrascrive tag_feat/tag_contrib, mai il contrario, mai il nome visualizzato); incrementale via `scan_files` (mtime_ns+size, `full=True` svuota scan_files); `scan_runs` con stats JSON {files_seen, files_parsed, files_skipped, files_error, artists_new, artists_total, duration_s} e status ok/error; audit event `scan_run` (nuovo `EVENT_SCAN_RUN` in `app/services/audit.py`). Errori di lettura → warning + contatore, mai eccezioni; eccezione fatale (es. libreria inesistente) → status error su scan_runs. **Nessuna write sulla libreria**: grep su open/write/unlink/mkdir in library_scan.py → zero risultati; verificato anche a runtime confrontando mtime.
  - `backend/app/api/scans.py` (protetto da `require_user`): `POST /api/v1/scans/library?full=` → 202, 409 `{"detail":"Scan already in progress"}` se già attivo; `GET /api/v1/scans/status` → `{running: null|{type,since}, last_runs: [ultimi 10 scan_runs con stats parsato]}`. Router registrato in `main.py`.
  - Lock asyncio globale per tipo di scan (dict `_locks`, esposto `start_library_scan`/`running_scans`/`reset_state`); worker sync eseguito in `asyncio.to_thread` (l'event loop non viene mai bloccato — mutagen è sync).
  - `backend/app/cli.py`: `python -m app.cli scan-library [--full]` → migrazioni + scan sync + stampa stats; libreria inesistente → errore su stderr + exit 2.
  - Test: `backend/tests/test_library_scan.py` (16 test) + fixture audio reali: `tests/fixtures/audio/s.{flac,ogg,opus,m4a,mp4,mp3}` (skeleton validi generati una volta con ffmpeg — silenzio 10ms; mutagen 1.48 non permette più di costruire file da costruttore vuoto, "FileType constructor requires a filename" — i test copiano lo skeleton in tmp_path, taggano con mutagen e salvano in place). FLAC minimale 42-byte via struct → NO (scartato: save in place ok ma ~1.2KB vs 8KB skeleton ffmpeg, alla fine usati gli skeleton ffmpeg per tutti). Nota: la build Homebrew di ffmpeg manca di libvorbis → il fixture `.ogg` contiene Opus (letto come `OggOpus`, stessa code path di OggVorbis via `OggFileType`).
  - `backend/tests/conftest.py`: `_reset_state()` ora chiama anche `library_scan.reset_state()` (locks/running per isolamento test).
- Decisione operativa §6.4 (registrata come richiesto dal prompt di fase): **split duro SOLO su `;`** (separatore sicuro dei tagger per valori multipli) + featuring dal titolo (parentesi/quadre). Gli split morbidi (` feat. `, ` & `, `, `, ` vs `, ` with `, ` con `) NON implementati: rimandati alla fase 04, da eseguire **dopo** il match-first MusicBrainz del nome intero (score ≥ 90 → nome intero come singolo artista, salva "Earth, Wind & Fire" e "AC/DC").
- Decisioni prese (e perché):
  - `scan_files.mtime` salvato come `st_mtime_ns` INTEGER (precisione sub-secondo; file riscritti nello stesso secondo vengono rilevati).
  - File corrotti/illeggibili NON vengono inseriti in `scan_files` → ritentati a ogni scan (files_error costante finché non si sistemano). Comportamento voluto (spec: contati e loggati, mai bloccanti).
  - Gli artisti non vengono mai cancellati dallo scan (spec non lo prevede): un artista non più presente in libreria resta in `artists` (test dedicato `test_scan_detects_changed_file` documenta il comportamento).
  - `POST /scans/library` restituisce **202** (accettato, scan in background) invece di 200.
  - `TIPL/TMCL.people` in mutagen 1.48 è una lista di coppie `[role, name]` (non lista piatta): scanner e test usano le coppie.
  - Feat regex: `\b` finale **solo** dopo `featuring`/`con`, NON dopo `feat.`/`ft.` (il punto è seguito da spazio → `\b` dopo il punto non matcherebbe mai, bug trovato in fase di test).
- Deviazioni dalle specifiche (approvate da chi): nessuna.
- Ambiguità riscontrate (interpretazione scelta):
  - Il prompt chiedeva test con "artist multiplo 'A; B'", ma §6.4.6 filtra i nomi < 2 char → nei test il multi-artista usa "AA; BB" e il filtro <2 char è verificato a parte.
  - `OggOpus` NON è sottoclasse di `OggVorbis` in mutagen 1.48 (fratelli, entrambi da `OggFileType`): lo scanner usa `OggFileType` per coprire ogg/opus.
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && .venv/bin/python -m pytest -q` → **81 passed** (erano 58 alla fine fase 02; +16 nuovi scan, +7 altri da fix fase 02)
  - `ruff check .` + `ruff format --check .` → OK; anche invocazione CI da root (`ruff check backend/ --config backend/pyproject.toml`) → OK
  - Coverage: TOTAL **95%** (target §13 ≥70%): `services/names.py` 100%, `services/library_scan.py` 89%, `api/scans.py` 100%, `security.py` 99%
  - Scan reale su libreria di prova (`/tmp/nucs-lib-test`: 7 file — FLAC con artist multiplo "Beyoncé; Jay-Z" + album artist + feat + PERFORMER; FLAC "Daft Punk" con "(feat. Pharrell Williams & Nile Rodgers)" + COMPOSER; MP3 "AC/DC" + remixer TIPL; M4A "Vasco Rossi (con Elisa)"; OGG con "Various Artists" (trivial) + feat; file corrotto): `scan-library --full` → files_seen=7 files_parsed=6 files_skipped=0 files_error=1 artists_new=13 artists_total=13; `SELECT source, COUNT(*)` → tag_artist 5, tag_albumartist 1, tag_feat 4, tag_contrib 3; campione verificato (beyonce, the carters, travis scott tag_feat, pianista nera tag_contrib, jay z); "Various Artists" assente (trivial filtrato); "Nile Rodgers" dedupato feat+composer → un solo row tag_contrib.
  - Rilancio `scan-library` SENZA `--full` → files_seen=7 files_parsed=0 files_skipped=6 files_error=1 artists_new=0 (il corrotto è ritentato, vedi decisioni)
  - Read-only libreria: `stat -f %m` su tutti i file prima/dopo due scan → **identici**; grep write-calls in library_scan.py → nessuno
  - Via API (uvicorn su porta 8099, login admin con cookie, DEV_INSECURE_COOKIES=true): POST `/api/v1/scans/library` con X-Requested-With+Origin → **202**; GET `/api/v1/scans/status` → `running: null` + last_runs (3 righe) con stats coerenti; status senza cookie → **401**
  - Concorrenza 409: coperto dal test automatico `test_api_scan_conflict_409` (worker monkeypatch-ato lento → secondo POST → 409 "Scan already in progress")
- Esito review: non ancora eseguita (fase economico; la review formale va incollata a un modello separato — i criteri di completamento della fase 03 la prevedono).
- Problemi noti / debito tecnico:
  - File corrotti ritentati a ogni scan (mai cache-ati): comportamento voluto, annotato sopra.
  - `server: uvicorn` esposto in dev (livello server, non middleware): aggiungere `--no-server-header` al CMD in fase 11.
  - Warning deprecazione Starlette TestClient/httpx2 (già noto da fase 01).
  - `backend/tests/fixtures/audio/*` sono binari generati con ffmpeg: se si rigenerano, assicurarsi che restino piccoli e validi (mutagen 1.48).
  - Il test API end-to-end usa polling (`_wait_until_idle`, 5s timeout): robusto ma leggermente lento.

---

## FASE 02 — Autenticazione, sessioni, rate limiting, header di sicurezza — 2026-08-03
- Branch: fase-02 (il prompt diceva "lavora sul branch corrente (fase-02)" ma il branch corrente era `main`: creato `fase-02` da `main` — interpretazione annotata)
- Cosa è stato fatto:
  - `backend/requirements.txt`: aggiunti `argon2-cffi==25.1.0` e `python-multipart==0.0.32` (commento inline: richiesto da FastAPI per endpoint form). Installate e verificate su Python 3.12.13.
  - `backend/app/security.py`: hash/verify argon2id (parametri default argon2-cffi: time=3, mem=64MiB ≥ floor 32MiB, par=4); `DUMMY_HASH` precalcolato a modulo per verifica a tempo costante su username inesistente; sessioni opache (`secrets.token_urlsafe(32)`, nel DB solo sha256 hex 64 char, `expires_at`=now+7gg, rolling renewal se <3gg); `revoke_session`/`revoke_other_sessions`/`cleanup_expired_sessions`/`list_active_sessions`; `LoginRateLimiter` in-memoria (finestra scorrevole 5 tentativi/5min per IP; 10 fallimenti consecutivi globali → blocco 15min con Retry-After; reset su successo); `parse_trusted_networks`/`resolve_client_ip` (X-Forwarded-For solo da proxy fidati, ultimo IP della lista); helpers `get_setting`/`set_setting`/`create_admin_user`.
  - `backend/app/services/audit.py`: `log_event(db, event, ip, detail)` con redazione difensiva delle chiavi sensibili (password/token/secret/cookie/authorization → `[redacted]`) prima del persist JSON; costanti evento (`login_ok`, `login_fail`, `logout`, `password_change`, `settings_change`).
  - `backend/app/deps.py`: `require_user` (cookie `nucs_session` → `verify_session`, 401 `{"detail":"Not authenticated"}`, aggiorna `last_seen_at`) esportata per i router futuri; `get_client_ip` (legge `request.state.client_ip` dal middleware).
  - `backend/app/api/auth.py` (prefix `/api/v1/auth`): POST `/login` (rate limit 429+Retry-After → dummy verify → 401 generico "Invalid credentials"; successo → audit `login_ok`, 204 + Set-Cookie HttpOnly/SameSite=Lax/Path=/Secure-salvo-DEV_INSECURE_COOKIES/Max-Age=604800, nessun Domain), POST `/logout` (revoca + cancella cookie + audit), GET `/me` (`{username, theme}` da settings), POST `/password` (verifica attuale → 400 "Current password is incorrect", policy ≥12 via pydantic, re-hash, revoca altre sessioni, audit `password_change`), GET `/sessions` (id=hash troncato 8 char, ip, user_agent, last_seen_at, current), POST `/sessions/revoke-others`.
  - `backend/app/main.py`: `SecurityHeadersMiddleware` (CSP §5.5, nosniff, DENY, Referrer-Policy, Permissions-Policy, X-Robots-Tag: noindex, HSTS solo se scheme=https, rimozione Server/X-Powered-By a livello app), `OriginCheckMiddleware` (POST/PUT/PATCH/DELETE richiedono X-Requested-With: XMLHttpRequest E Origin/Referer con netloc == Host → 403 `{"detail":"Forbidden"}`, nessuna eccezione), `ClientIPMiddleware` (risolve IP effettivo con `ipaddress` + TRUSTED_PROXY_CIDRS in `request.state.client_ip`); ordine: headers outermost. `ensure_admin_exists()` al boot (manca admin → da env con policy check + log "admin created from env", altrimenti `sys.exit(1)` con messaggio che indica il comando CLI); job asyncio orario di cleanup sessioni scadute nel lifespan; route `/robots.txt` ("User-agent: *\nDisallow: /"); auth router incluso.
  - `backend/app/cli.py`: `python -m app.cli create-admin <username> <password>` (argparse) con policy ≥12 (exit 2 + stderr), migrazioni applicate prima della creazione.
  - `backend/app/schemas.py`: `LoginRequest`, `PasswordChangeRequest` (pydantic, lunghezze max; `new_password` min 12).
  - Test: `tests/test_security.py` (24 unit test: hashing, dummy hash, sessioni CRUD/rolling/scadenza, rate limiter window/slide/reset/lockout/expiry, CIDR parsing, XFF trust, redazione audit) e `tests/test_auth.py` (26 test API con httpx AsyncClient + ASGITransport: login ok/ko identico messaggio, dummy-verify su utente ignoto, cookie flags ± DEV_INSECURE_COOKIES, 6° tentativo → 429 + Retry-After, reset contatori su successo, lockout globale, 401 senza cookie su tutti gli endpoint, 403 senza X-Requested-With/Origin/Referer o con Origin estraneo, Referer valido accettato, logout/revoca, cambio password che revoca altre sessioni, lista sessioni + revoke-others, header sicurezza, HSTS solo https, robots.txt, XFF fidato/non fidato, boot senza admin → SystemExit, boot con password corta → SystemExit, CLI create-admin).
- Versioni dipendenze introdotte: argon2-cffi 25.1.0, python-multipart 0.0.32 (esatte, `==`).
- Decisioni prese (e perché):
  - Cookie di test: fixture `make_client` usa base_url `https://testserver` perché httpx non rispedisce cookie `Secure` su http; test dedicato per `DEV_INSECURE_COOKIES=true`.
  - ASGITransport non esegue il lifespan FastAPI: le fixture eseguono esplicitamente `run_migrations()`/`seed_settings_if_empty()`/`ensure_admin_exists()` (documentato in conftest).
  - Contatore globale del rate limiter azzerato allo scattare del blocco (dopo i 15 min si riparte da zero): interpretazione semplice di "i contatori si resettano" estesa al lockout; commento nel codice.
  - `pyproject.toml`: `testpaths` da `backend/tests` a `tests` (il prompt di verifica di fase 02 esegue `python -m pytest -q` da `backend/`; con il valore precedente non trovava i test), aggiunto `asyncio_mode = "auto"` (pytest-asyncio), `extend-immutable-calls` per `fastapi.Depends` (B008), per-file-ignores S105/S106 su `tests/**` con doppia glob (`tests/**` e `backend/tests/**`) perché la CI invoca ruff da root.
  - `.coverage` aggiunto a `.gitignore` (artefatto pytest-cov).
- Deviazioni dalle specifiche (approvate da chi): nessuna.
- Ambiguità riscontrate (interpretazione scelta):
  - §5.5 "Nessun header Server esposto": il middleware ASGI rimuove header app-level, ma **uvicorn aggiunge `server: uvicorn` a livello protocollo**, fuori portata del middleware (verificato con curl: header presente). Fix = `--no-server-header` nel CMD uvicorn del Dockerfile → **rimandato alla fase 11** (annotato qui e nei problemi aperti).
  - "Lavora sul branch corrente (fase-02)": il branch corrente era `main`; creato `fase-02` (come da nome nel prompt, non `fase-02-auth` dell'header del file di fase).
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && .venv/bin/python -m pytest -q` → **58 passed** (4.0s)
  - `.venv/bin/ruff check .` + `ruff format --check .` → OK; anche invocazione CI da root (`ruff check backend/ --config backend/pyproject.toml`) → OK
  - Coverage: `app/security.py` **100%**, `app/services/audit.py` **100%**, TOTAL 98% (target §13 ≥70% superato)
  - Boot senza admin: `DATA_DIR=/tmp/nucs-d2a uvicorn ...` → processo esce (code 3) con msg "no admin user configured: set ADMIN_USERNAME and ADMIN_PASSWORD ... python -m app.cli create-admin <username> <password>"
  - Boot con env: log "admin created from env"; login sbagliato → 401 `{"detail":"Invalid credentials"}`; login giusto → 204 + `Set-Cookie: nucs_session=...; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure`; `/me` senza cookie → 401, con cookie → 200 `{"username":"admin","theme":"dark"}`; login senza X-Requested-With → 403; 6° tentativo → 429 `Retry-After: 300`; header sicurezza tutti presenti su `/api/health`; `/robots.txt` → `Disallow: /`
  - DB reale ispezionato: `sessions.id_hash` solo hex 64 char, token in chiaro assente (assert su token noto); audit_log con eventi `login_ok`/`login_fail` e detail `{"username":"admin"}` (nessun segreto)
  - CLI: `create-admin cliuser 'cli-password-lunga-1'` → creato (`$argon2id$` nel DB); password corta → exit 2 + stderr
  - Grep segreti: `grep -rniE "(logger\.(info|warning|error|exception|debug)|logging\.|print\()" backend/app --include="*.py" | grep -iE "password|token|secret|cookie"` → **nessun risultato** (il grep più ampio del prompt di verifica matcha solo un import e file .pyc binari: nessun log statement contiene segreti)
- Esito review (modello avanzato, 2026-08-03): 3 findings **MEDIA** + 6 BASSA, tutti risolti con fix minimi:
  - **MEDIA** — `POST /auth/password` senza rate limit né audit sui fallimenti → limiter dedicato (chiave `IP|id_sessione`, 5/5min, 429+Retry-After) + evento audit `password_fail` (`app/api/auth.py`).
  - **MEDIA** — HSTS mai emesso dietro cloudflared/tailscale (l'origin vede sempre scheme http) → HSTS emesso anche con `X-Forwarded-Proto: https`, ma **solo** da peer in `TRUSTED_PROXY_CIDRS` (`is_trusted_peer` in `app/security.py`, middleware in `app/main.py`).
  - **MEDIA** — `LoginRateLimiter`: crescita memoria illimitata → rimozione chiavi vuote dopo pruning + cap `max_tracked_ips` (default 100k) con eviction.
  - **BASSA** — origin check confrontava Host con porta non normalizzata → `_strip_default_port` (:80/:443 e IPv6 normalizzati, porte non-default restano significative).
  - **BASSA** — redazione audit non ricorsiva → `_sanitize_value` ricorsivo su dict/list (`app/services/audit.py`).
  - **BASSA** — tentativi 429 non auditati → evento `login_blocked` con debounce 60s/IP (niente flood del trail).
  - **BASSA** — password admin come argv CLI → argomento opzionale + `getpass` quando omesso (`app/cli.py`).
  - **BASSA** — digest/timestamp corrotti nel DB → 500: `verify_password` catch `Exception`, `verify_session` guarda `fromisoformat`.
  - **BASSA** — side-effect `seen=true` su `GET /releases/{id}` (spec §10): impatto minimo (SameSite=Lax), da valutare deroga spec in fase 05 (endpoint non ancora implementato in fase 02).
- Esito review: **fase 02 APPROVATA** (0 findings ALTA/MEDIA residui).
- Re-verifica dopo fix (tutti i comandi): `pytest` → **68 passed**; `ruff check` + `ruff format --check` OK da `backend/` e da root (invocazione CI); coverage TOTAL **97%** (security.py 99%, audit.py 100%); boot reale + curl: login 204+Set-Cookie (HttpOnly/Secure/SameSite=Lax), /me 401 senza cookie, 5 login errati → 401 e 6° → 429 Retry-After, cambio password rate-limitato (6° con password corretta → 429), HSTS via X-Forwarded-Proto solo da peer fidato, audit `login_ok/login_fail/login_blocked/password_fail` senza segreti, `sessions.id_hash` solo sha256 hex 64 char.
- Nuovi test per i fix (10): `test_auth.py` (password change rate limit, login_blocked auditato, HSTS XFP fidato/non fidato, origin con porta default/non-default), `test_security.py` (release empty IP slots, cap tracked IPs, timestamp corrotto, `verify_password` su input corrotti, sanitize ricorsivo). Fixture: reset di `password_change_limiter` e `_block_logged_at`.
- Problemi noti / debito tecnico:
  - `server: uvicorn` esposto in dev (livello server, non middleware): aggiungere `--no-server-header` al CMD in fase 11.
  - Warning deprecazione Starlette TestClient/httpx2 (già noto da fase 01).
  - Rate limiter in-memoria: contatori persi al restart (accettato, spec 5.3 "in memoria"; il blocco globale riparte da zero dopo restart).

---

## FASE 01 — Backend base: FastAPI, config, SQLite, migrazioni, health — 2026-08-03
- Branch: fase-01
- Cosa è stato fatto:
  - `backend/requirements.txt` con versioni pinnate (`==`): fastapi 0.141.1, uvicorn[standard] 0.52.1, sqlalchemy 2.0.51, alembic 1.18.5, pydantic 2.13.4, pydantic-settings 2.14.2 — verificate installabili e funzionanti su Python 3.12.13 (venv `backend/.venv`)
  - `backend/requirements-dev.txt`: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, pytest-cov 7.1.0, ruff 0.16.1
  - `backend/app/config.py`: `Settings` (pydantic-settings, legge env + `.env`) con ADMIN_USERNAME, ADMIN_PASSWORD (default vuota), DATA_DIR (default `./data`), COVERS_DIR (default `{DATA_DIR}/covers`), MUSIC_LIBRARY_PATH (default `./music`), TZ, LOG_LEVEL, DEV_INSECURE_COOKIES (bool, default False), TRUSTED_PROXY_CIDRS (str). Validatori che creano DATA_DIR e COVERS_DIR (mkdir parents=True, exist_ok=True). `get_settings()` con lru_cache.
  - `backend/app/db.py`: engine SQLite su `{DATA_DIR}/app.db`, PRAGMA journal_mode=WAL, foreign_keys=ON, busy_timeout=5000 via event listener `connect`; session factory e dependency FastAPI `get_db`.
  - `backend/app/models.py`: tutte le 9 tabelle di §4 (artists, releases, release_artists, release_state, settings, sessions, audit_log, scan_runs) con colonne/tipi/PK/UNIQUE/indici come da specifica (timestamps UTC ISO-8601 TEXT); `artists` include `last_release_check TEXT NULL` (cursore discovery §8.1). Indici: releases(first_release_date), release_artists(artist_id), sessions(expires_at), audit_log(ts).
  - Alembic: `backend/alembic.ini` + `backend/alembic/` (env.py puntato a `app.models.Base.metadata`, URL DB derivato da settings); prima migration autogenerate `9cb782c0d8f5_initial_schema` che crea l'intero schema. All'avvio (lifespan) `alembic upgrade head` programmatico via `alembic.command.upgrade`.
  - Seed settings (§4): se tabella `settings` vuota, inseriti i default; `discovery_from_date` = oggi − 30 giorni calcolato a runtime.
  - `backend/app/main.py`: `create_app()` con lifespan (dirs via config, migrazioni, seed, log avvio), `GET /api/health` → `{"status":"ok","version":"1.0.0"}`, logging key=value su stdout con livello da LOG_LEVEL, handler globale eccezioni → 500 `{"detail":"Internal error"}` + traceback completo lato server.
  - Test: `backend/tests/conftest.py` (fixture `app_env` con DATA_DIR in tmp_path + monkeypatch env + reset engine/session cached), `tests/test_health.py`, `tests/test_db.py` (WAL mode, foreign_keys ON, tutte le tabelle dopo migrazione, seed settings).
  - `backend/pyproject.toml`: aggiunta config isort `src=["app"]` + `known-first-party=["app"]` per ordinamento import consistente tra CI (root) e dev (backend/).
- Versioni dipendenze scelte (fase 01): elencate sopra; tutte installate e verificate con Python 3.12.13.
- Decisioni prese (e perché):
  - `pytest-asyncio` incluso in dev requirements (richiesto dal piano), anche se in fase 01 non ci sono test async.
  - Config `Settings` valida dati ma NON crea `MUSIC_LIBRARY_PATH` (fase 03) né applica `TZ` (usato in fasi successive).
  - `_set_pragmas` applicato via event listener `connect` (WAL/foreign_keys/busy_timeout a ogni nuova connessione).
  - In `alembic/env.py` **non** viene chiamato `logging.config.fileConfig()`: altrimenti il file di logging di alembic.ini resetta il root logger e rompe il formato key=value dell'app (bug trovato e corretto).
  - `dev_insecure_cookies` è dichiarata in config ma non usata (fase 02): presente per non rompere l'env da fase 00.
- Deviazioni dalle specifiche (approvate da chi):
  - **Prompt di fase 01 chiedeva** 500 `{"detail":"Errore interno"}`; le specifiche (§5.7 e §10) impongono messaggi d'errore per l'utente in inglese e mostrano `500 {"detail":"Internal error"}`. Applicato **`Internal error`** (le specifiche vincono, regola README §4.1). Annotata come ambiguità risolta.
  - Aggiunto `backend/alembic/README` e `script.py.mako` (generati da `alembic init`), coerenza con struttura §3.
- Esito verifica (comandi eseguiti e risultato):
  - `pytest tests/` (da `backend/`) → **6 passed** (health 200 + shape ×2, WAL, foreign_keys, tutte le tabelle, seed settings)
  - `ruff check backend/ --config backend/pyproject.toml` (invocazione CI da root) → **All checks passed!**
  - `ruff format --check backend/ --config backend/pyproject.toml` → OK (9 file formattati)
  - Boot reale: `uvicorn app.main:app --host 127.0.0.1 --port 8099` → `GET /api/health` → 200 `{"status":"ok","version":"1.0.0"}`; log key=value su stdout; migrazione + seed eseguiti; `data/app.db` (+ `-wal`/`-shm`) e `data/covers` creati.
- Esito review (findings risolti / accettati):
  - Non applicabile (nessuna review formale per fase 01 economico)
- Problemi noti / debito tecnico:
  - Warning deprecazione Starlette: "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead". Non bloccante; da valutare in fase 12 (il passaggio a `httpx2` dipende dal supporto fastapi/starlette).
  - `backend/app` è un namespace package (niente `__init__.py`): funziona, ma in fase 12 valutare se aggiungere gli `__init__.py`.
  - Access log HTTP non ancora filtrati per `/api/health` (richiede middleware, previsto in fase 02 per §5.7).
- Istruzioni avvio dev (fase 01):
  ```bash
  cd backend
  python3.12 -m venv .venv            # oppure riusare backend/.venv già creato
  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
  .venv/bin/uvicorn app.main:app --reload
  # health: http://127.0.0.1:8000/api/health
  # test:   .venv/bin/python -m pytest tests/ -v
  # lint:   ruff check . --config pyproject.toml
  ```
  Variabili in `.env` nella stessa dir da cui parte uvicorn (es. `backend/.env`); DATA_DIR default `./data`.

---

## FASE 00 — Scaffolding repo, convenzioni, CI minima — 2026-08-03
- Branch: main (non serve branch separato, scaffolding iniziale)
- Cosa è stato fatto:
  - Creata struttura directory completa come da §3: backend/app/{api,services}, backend/tests, backend/alembic/versions, frontend/src/{pages,components,api}, docker/, deploy/tailscale/, .github/workflows/
  - Directory vuote tracciate con .gitkeep
  - Creato .gitignore con pattern per Python, Node, env, data, OS
  - Creato .env.example copiando esattamente le variabili da §12.3
  - Creato backend/pyproject.toml con config ruff (py312, line-length 110, regole E/F/I/UP/B/S + ignore documentati) e pytest (testpaths=backend/tests)
  - Creati backend/requirements.txt e backend/requirements-dev.txt (vuoti con commento direzionale)
  - Creato .github/workflows/ci.yml: trigger push/PR su main, job lint con ruff check backend/
  - Creato README.md radice (titolo, scopo, stato, rimando a piano/)
  - Creato .dockerignore radice (.git, node_modules, data, piano, .env)
- Decisioni prese (e perché):
  - Ruff ignore rules: S101 (assert), S104 (bind all), S301 (pickle), S403/S404 (subprocess), S603/S607 (shell). Scelte per pragmatismo in fase iniziale; da rivalutare in hardening (fase 12)
  - CI esegue ruff config dal file backend/pyproject.toml per coerenza col setup locale
- Deviazioni dalle specifiche (approvate da chi):
  - Nessuna
- Versioni dipendenze introdotte:
  - ruff (nessuna versione pinnata in CI, install latest; sarà pinnata in requirements-dev.txt in fase 01)
- Esito verifica (comandi eseguiti e risultato):
  - `ruff check backend/ --config backend/pyproject.toml` → All checks passed! (exit 0)
  - Verifica newline finale su tutti i file creati → tutti OK
  - Verifica directory creata tramite `find` → struttura conforme a §3
- Esito review (findings risolti / accettati):
  - Non applicabile (fase 00, nessuna review formale)
- Problemi noti / debito tecnico:
  - Nessuno

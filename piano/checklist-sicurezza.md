# CHECKLIST SICUREZZA — compilata alla fase 12 (review finale v1.0.0)

> Istruzioni per il modello reviewer: valuta OGNI punto come ✅ / ❌ / ➖ (non applicabile alla fase).
> Ogni ❌ va riportato con: file, riga/frammento, gravità (ALTA/MEDIA/BASSA), fix proposto.
> Le gravità ALTA e MEDIA sono bloccanti: la fase non si chiude finché non sono risolte.
>
> **STATO AL RILASCIO v1.0.0 (fase 12, 2026-08-05):** tutti i punti ✅ o ➖ con evidenza
> `file:riga`. Nessun ❌ residuo. Verifiche dinamiche in `piano/verifica-e2e.md`.

## A. Autenticazione e sessioni
- [x] A1. Password hashate con argon2id (mai bcrypt<cost<12, mai MD5/SHA in chiaro, mai reversible).
  Evidenza: `backend/app/security.py:33` `PasswordHasher()` argon2id (t=3, m=64MiB, p=4); `hash_password`/`verify_password` (security.py:44-54); test `tests/test_security.py` (24).
- [x] A2. Token di sessione opaco ≥ 128 bit di entropia; nel DB solo hash del token.
  Evidenza: `security.py:89` `secrets.token_urlsafe(32)` (≈256 bit); `security.py:82-84` sha256 hex; DB `sessions.id_hash` (verificato fase 02: solo hex 64).
- [x] A3. Cookie: HttpOnly + Secure (salvo DEV_INSECURE_COOKIES) + SameSite=Lax; nessun Domain.
  Evidenza: `backend/app/api/auth.py:60-69` `set_cookie(..., httponly=True, secure=not dev_insecure_cookies, samesite="lax")`, nessun `domain=`. Verifica curl (fase 12): `Set-Cookie: nucs_session=...; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure`.
- [x] A4. Login: risposta identica per utente inesistente/password errata; tempo di risposta simile (hash dummy).
  Evidenza: `auth.py:84-91` stesso messaggio 401 `"Invalid credentials"`; dummy verify `DUMMY_HASH` (`security.py:37`); misura curl fase 12: esistente ~37 ms vs inesistente ~37 ms (post-warmup).
- [x] A5. Rate limit login: 5 tentativi/5 min/IP + blocco globale 15 min dopo 10 fallimenti.
  Evidenza: `security.py:154-234` `LoginRateLimiter` (5/300s/IP, 10 globali → 900s, Retry-After); `auth.py:75-82`; E2E: 5×401 → 6° 429 + Retry-After 300; curl 12 tentativi: 5×401 + 7×429.
- [x] A6. Logout e cambio password revocano correttamente le sessioni.
  Evidenza: `auth.py:106-116` (revoca corrente), `auth.py:154-158` (cambio password → `revoke_other_sessions`); `e2e:09` sessione incognito revocata → 401.
- [x] A7. Sessioni scadute non accettate; cleanup periodico presente.
  Evidenza: `security.py:105-124` `verify_session` (scadenza + delete); job orario `cleanup_sessions` (`scheduler.py`, fase 10); test.
- [x] A8. Nessun endpoint autenticato risponde senza sessione valida (401, non redirect per API).
  Evidenza: `deps.py` `require_user` → 401 `Not authenticated`; coperto da test API (`test_auth.py`) ed E2E.

## B. Input, output, injection
- [x] B1. Tutti gli input validati con pydantic (tipi, lunghezze max, formati data/time).
  Evidenza: `backend/app/schemas.py` (LoginRequest, PasswordChangeRequest, ReleaseStatePatch extra=forbid, SeenAllRequest); `api/settings.py` validazioni (date ISO, HH:MM, weekday, email, CSV types, caps lunghezza); `q` max 200 (releases/artists).
- [x] B2. Query DB solo via ORM/parametrizzate: nessuna concatenazione SQL.
  Evidenza: SQLAlchemy 2.0 core/ORM ovunque (models.py, api/*, services/*); uniche stringhe SQL = raw SQL parametrizzato di ALTER/pragma nei test; `release_in_range`/dates puro. Grep concatenazioni SQL → 0.
- [x] B3. Path della libreria e delle cover mai costruiti da input utente (path traversal: controllare `..`, symlink).
  Evidenza: `api/covers.py` `RGID_RE` strict `^[a-f0-9]{8}-...-{12}$` → 400 su non conforme; file serviti solo da `COVERS_DIR/{rgid}.jpg` validato; libreria montata `:ro` e mai scritta (fase 03). Test: `..%2F..%2Fetc%2Fpasswd` → 404.
- [x] B4. Output API non contiene: hash password, token, secret Spotify, path assoluti del server, stack trace.
  Evidenza: GET /settings esclude segreti (flag `*_set`, fase 06); sessioni restituiscono solo `id_hash[:8]`; handler 500 globale → `Internal error` (`main.py:327-330`); audit redatto. Test e verifiche live.
- [x] B5. React: nessun `dangerouslySetInnerHTML` su dati esterni; URL esterni sempre codificati (`quote`/`encodeURIComponent`).
  Evidenza: grep `dangerouslySetInnerHTML` → 0 in `frontend/src`; link esterni costruiti dal backend (`services/links.py` con `urllib.parse.quote`); `LinkButtons` usa solo URL dal server.
- [x] B6. Header di sicurezza presenti su tutte le risposte (CSP, nosniff, DENY, Referrer-Policy, Permissions-Policy).
  Evidenza: `main.py:83-107` `SecurityHeadersMiddleware` (tutte le risposte): CSP `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` (**fase 12: rimosso `'unsafe-inline'`**, verificato in browser senza violazioni), nosniff, DENY, Referrer-Policy same-origin, Permissions-Policy vuota, HSTS dietro HTTPS, niente `Server`/`X-Powered-By`.
- [x] B7. Controllo Origin/Referer + header `X-Requested-With` su tutte le mutazioni (POST/PUT/PATCH/DELETE).
  Evidenza: `main.py:133-147` `OriginCheckMiddleware` (403 senza X-Requested-With o Origin/Referer discordante); test `test_auth.py` (403 senza header / Origin estraneo).

## C. Segreti e configurazione
- [x] C1. Nessun segreto committato (controllare `git diff` e file nuovi): .env, token, password di esempio reali.
  Evidenza: `git ls-files | grep -iE "\.env$|secret|token"` → 0 file; `.env.example` placeholder; `e2e/` credenziali fixture documentate (mai usate in runtime); `.dockerignore` con `**/.env` (fix ALTA fase 11: nessun .env nei layer).
- [x] C2. `.env.example` contiene solo placeholder.
  Evidenza: `.env.example` (26 righe): valori vuoti o commenti; nessun token.
- [x] C3. GET /settings non restituisce valori di chiavi segrete (solo flag `*_set`).
  Evidenza: `api/settings.py` (fase 06): secret Spotify mai restituiti, flag `spotify_client_id_set`/`spotify_client_secret_set`; verificato live (GET senza `secret-x` nel body) e in `e2e:09`.
- [x] C4. Log privi di segreti/token/cookie (cercare `password`, `token`, `cookie`, `secret` nei log statement).
  Evidenza: `services/audit.py` redazione ricorsiva; `seed_settings_if_empty` logga solo i nomi chiave; grep sui log di 3 boot (fase 12): `password|secret|tgram|token|api_key` → 0 match; grep sui log statement di `backend/app` → nessun valore sensibile loggato.

## D. Rete e container
- [x] D1. Nessuna porta pubblicata sull'host per `app` (solo `expose` interno).
  Evidenza: `docker-compose.yml` `expose: 8080` senza `ports:`; `docker compose config | grep ports` → vuoto; unico `ports:` in `docker-compose.dev.yml` (127.0.0.1, vietato in produzione).
- [x] D2. Container app: utente non-root, filesystem read-only + tmpfs, volumi minimi, libreria montata `:ro`.
  Evidenza: `docker/Dockerfile` USER app (uid 1000, `--no-create-home`, HOME=/tmp); compose `read_only: true` + `tmpfs: /tmp`, volumi `nucs-data:/data` e `${MUSIC_LIBRARY_PATH}:/music:ro`, `cap_drop: ALL`, `security_opt no-new-privileges`. Verificato con `docker inspect` (fase 11).
- [x] D3. Limiti memoria/CPU presenti su tutti i servizi.
  Evidenza: compose: app `mem_limit: 768m, cpus: 1.5, pids_limit: 512`; cloudflared `mem_limit: 128m, pids_limit: 128`; tailscale `mem_limit: 256m, pids_limit: 512`.
- [x] D4. Immagini con tag/versione pinnata (niente `latest` salvo servizi infra senza alternativa — annotarlo).
  Evidenza: `node:20-alpine`, `python:3.12-slim` (Dockerfile), `cloudflare/cloudflared:2025.6.1`, `tailscale/tailscale:v1.84.0` (fase 11, verificate multi-arch); tini pinnato dalla suite Debian del base (annotato fase 11).
- [x] D5. `X-Forwarded-For` considerato solo da proxy fidati (CIDR rete Docker).
  Evidenza: `security.py:238-294` `parse_trusted_networks`/`resolve_client_ip` (solo peer in TRUSTED_PROXY_CIDRS, default `172.16.0.0/12,10.0.0.0/8`); `main.py:161-166` `ClientIPMiddleware`; HSTS solo con XFP https da peer fidato (`main.py:110-116`). Uvicorn `--proxy-headers`.
- [x] D6. Errori 5xx → messaggio generico al client, dettaglio solo nei log.
  Evidenza: `main.py:327-330` handler Exception → 500 `{"detail":"Internal error"}` + traceback server-side; test.

## E. Dipendenze e supply chain
- [x] E1. Versioni pinnate in requirements.txt / package.json; lockfile committati.
  Evidenza: `backend/requirements.txt` (`==` ovunque, commenti), `backend/requirements-dev.txt` (`==`); `frontend/package.json` esatte + `package-lock.json` committato; `e2e/package.json` + lock. Fase 12: aggiunto `httpx2==2.9.1` (dev).
- [x] E2. Nessuna dipendenza nuova non prevista dalle specifiche senza nota in STATO.md.
  Evidenza: stack §2 rispettato; `httpx2` (test-only, fase 12, annotato) e `@types/*` (dev types, annotato fase 07); puppeteer (tooling E2E separato, annotato).
- [x] E3. `pip-audit` / `npm audit` eseguiti nelle fasi previste; finding high/critical risolti o giustificati.
  Evidenza fase 12: `pip-audit -r backend/requirements.txt` → **0 findings**; `npm audit --omit=dev` → 2 **moderate** react-router 6.x non applicabili (SPA senza SSR, link interni hardcoded) e fix solo via major v7 → giustificate in STATO.md, pianificate v1.1; `npm audit` in e2e → 0. **Nessun high/critical residuo.**

## F. Privacy e superficie
- [x] F1. `X-Robots-Tag: noindex` + robots.txt disallow.
  Evidenza: `main.py:101` `X-Robots-Tag: noindex` su tutte le risposte; `main.py:299-301` `/robots.txt` → `Disallow: /`; `<meta name="robots" content="noindex">` in index.html.
- [x] F2. Copertine servite dalla cache locale (niente hotlink di terze parti nel browser) → CSP `img-src 'self'` rispettata.
  Evidenza: pipeline fase 06 scarica e salva in `COVERS_DIR/{rgid}.jpg`, servita da `/api/v1/covers/{rgid}` (auth + cache-control 7gg); `img-src 'self'` in CSP; E2E: `imageHosts` solo `127.0.0.1`, zero immagini esterne.
- [x] F3. Audit log di login_ok/login_fail/settings_change presente e senza dati sensibili.
  Evidenza: `services/audit.py` (eventi login_ok/login_fail/login_blocked/logout/password_change/password_fail/settings_change/scan_run); detail redatto ricorsivamente (mai password/token/secret); verificato live (fase 12): `{"username": "admin"}` senza dati sensibili.
- [x] F4. L'app non scrive MAI dentro la cartella musica.
  Evidenza: `services/library_scan.py` solo lettura (mutagen `open(...)` read); grep write/open-write → 0; verifica mtime invariato (fase 03); mount `:ro` in produzione.

---

## Esiti finali

- **Punti ✅: 26/26 applicabili** (A1-A8, B1-B7, C1-C4, D1-D6, E1-E3, F1-F4). **➖: 0. ❌: 0.**
- Verifiche dinamiche eseguite in fase 12: timing login (A4), brute-force reale (A5/B7),
  cookie Secure (A3), CSP in browser (B6), log puliti (C4), audit log (F3), E2E 33/33.
- Dettaglio completo: `piano/verifica-e2e.md` · `piano/STATO.md` (fase 12).

# FASE 11 — Docker finale, Compose multi-servizio, Tailscale (senza dominio)

- **Implementazione**: modello economico
- **Review**: **modello AVANZATO obbligatorio** (networking e sicurezza container)
- **Dipende da**: fase 10
- **Branch**: `git checkout -b fase-11-docker-rete`
- **Nota**: la verifica di PRODUZIONE (mini PC: HTTPS tailnet, scans reali, IP reali,
  Cloudflare) è nella **fase 14** — in questa fase si implementa tutto e si verifica
  il container su questa macchina di sviluppo (Mac con Docker).

---

## 1. Obiettivo

Immagine unica multi-stage (frontend+backend), **multi-arch** (arm64 + amd64, build
locale su ogni macchina — nessun registry), compose con 3 servizi (app, cloudflared,
tailscale) come da §12 con **nessuna porta esposta sull'host** e constraints di
sicurezza completi. HTTPS di partenza via **Tailscale** (`https://nucs.<tailnet>.ts.net`,
nessun dominio richiesto); il tunnel **Cloudflare** resta documentato e pronto ma
**differito** (richiede un dominio). Il container deve poter girare su più macchine
(Mac ARM, mini PC x86, altre future) con gli stessi constraints.

## 2. Prerequisiti

- Fase 10 mergiata; app completa e funzionante in dev.
- **Su questa macchina**: Docker (Desktop/OrbStack/colima) per la verifica locale.
- Account **Tailscale** (free, senza dominio) — servirà al momento della fase 14;
  i client vanno installati sui device da cui accedere all'app.
- Account **Cloudflare con dominio** (free): OPZIONALE e differito alla fase 14
  (il servizio cloudflared è già nel compose, basta il token + public hostname).
- Il mini PC NON è richiesto in questa fase.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §12 (Docker e rete, TUTTO vincolante), §12.3 (env), §5.6 (proxy)
- piano/README.md §4
- piano/STATO.md
Branch: fase-11. Codice/commenti inglese.

OBIETTIVO
Dockerfile multi-stage multi-arch + compose con constraints completi + docs deploy
(Tailscale attivo senza dominio; Cloudflare documentato e differito).

COMPITI
1. docker/Dockerfile ESATTAMENTE come §12.1 e multi-arch:
   - Stage fe: node:20-alpine, COPY frontend/package*.json → npm ci → COPY frontend/ → npm run build.
   - Stage runtime: python:3.12-slim → ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1;
     apt install tini (pinnato alla versione disponibile, --no-install-recommends, pulisci apt lists);
     COPY backend/requirements.txt → pip install; COPY backend/ → /app/backend;
     COPY --from=fe dist → /app/static; utente app (uid 1000) owner di /app e mkdir /data;
     USER app; ENV DATA_DIR=/data COVERS_DIR=/data/covers FRONTEND_DIST=/app/static;
     EXPOSE 8080; HEALTHCHECK --interval=30s --timeout=5s --start-period=15s
       CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health')" ;
     ENTRYPOINT ["/usr/bin/tini","--"]; CMD uvicorn come §12.1 (proxy-headers, host 0.0.0.0, port 8080,
     workers 1, working dir /app/backend).
   - Multi-arch: nessun pacchetto arch-specifico; ogni macchina fa `docker compose build`
     per la propria arch (arm64 su Mac, amd64 su mini PC). Nessun registry.
2. docker-compose.yml radice come §12.2 CON constraints completi:
   - servizi app / cloudflared / tailscale; rete nucs-net; volumi nucs-data e ts-state;
     profili cloudflare/tailscale; restart unless-stopped; healthcheck su app;
     NESSUNA porta pubblicata (solo expose 8080 su nucs-net).
   - app: mem_limit 768m, cpus 1.5, read_only: true, tmpfs /tmp, security_opt
     no-new-privileges, cap_drop: ALL, pids_limit (es. 512), env_file .env,
     volume nucs-data:/data, ${MUSIC_LIBRARY_PATH}:/music:ro.
   - cloudflared: mem_limit 128m, cap_drop ALL, no-new-privileges, pids_limit,
     command tunnel --no-autoupdate run --token ${CF_TUNNEL_TOKEN}.
   - tailscale: mem_limit 256m, cap_drop ALL + cap_add NET_ADMIN (unico extra),
     no-new-privileges, pids_limit, env TS_STATE_DIR=/var/lib/tailscale TS_HOSTNAME=nucs
     TS_SERVE_CONFIG=/config/serve.json TS_AUTHKEY=${TS_AUTHKEY:-} TS_USERSPACE=false;
     volumes ts-state + ./deploy/tailscale/serve.json:/config/serve.json:ro + /dev/net/tun.
3. docker-compose.dev.yml (NUOVO, SOLO sviluppo/verifica locale sul Mac):
   stesso servizio app (build condivisa) + ports "127.0.0.1:8080:8080".
   MAI incluso nel compose di produzione: documentare "usa il compose base in produzione".
4. deploy/tailscale/serve.json: proxy HTTPS 443 → http://app:8080
   (schema: {"TCP":{"443":{"HTTPS":true}},"Web":{"${TS_CERT_DOMAIN}:443":{"Handlers":{"/":{"Proxy":"http://app:8080"}}}}})
   — SE la sintassi esatta ti è incerta NON inventare: scrivi la versione migliore E segnala
   in STATO.md "serve.json da validare al primo avvio (fase 14)".
5. deploy/cloudflared.md: guida step-by-step (numerata, screenshot-less): dashboard Zero Trust →
   Networks → Tunnels → Add → Cloudflared → nome → copia TOKEN in .env (CF_TUNNEL_TOKEN) →
   Public Hostname: subdomain (es. musica), dominio tuo, service http://app:8080 → Save.
   Nota sicurezza: Cloudflare Access (allowlist email) come difesa in profondità OPZIONALE.
   Intestazione del file: "DA VERIFICARE IN FASE 14 — richiede un dominio gestito da Cloudflare".
6. deploy/tailscale.md (ATTIVO): due opzioni: (a) TS_AUTHKEY riutilizzabile da admin console → .env;
   (b) primo avvio senza authkey: docker compose exec tailscale tailscale up → URL di login.
   Poi: https://nucs.<tailnet>.ts.net raggiungibile dai device del tailnet.
7. .env.example: allinea con CF_TUNNEL_TOKEN=, TS_AUTHKEY=, TS_HOSTNAME=nucs,
   TS_STATE_DIR=/var/lib/tailscale + nota "senza dominio: usa solo --profile tailscale".
   docker-compose non contiene segreti.
8. Backend: verifica che §5.6 (trusted proxy) sia già pronto per X-Forwarded-For dietro
   tailscale serve e CF-Connecting-IP dietro cloudflared (fase 02 l'ha implementato: nessun
   cambio atteso, solo verifica in fase 14 con IP reali).
9. README.md radice: quick-start (build multi-arch locale, up con --profile tailscale,
   override dev per test locale, primo login, link a deploy/*.md). La guida completa in fase 12.
10. e2e/scenarios/fase-11.js (NUOVO, estende l'harness): login + tema + logout + security
    headers su URL https; oggi eseguibile su http://127.0.0.1:8080 (BASE param), in fase 14
    su https://nucs.<tailnet>.ts.net. Script e2e:11 in e2e/package.json.

VINCOLI
- Immagine finale < 400 MB (misura con docker images; se sfora, indaga e riduci).
- Build riproducibile: niente `latest` tranne cloudflared/tailscale (annota in STATO.md il perché;
  se riesci a pinnare digest/tag specifici, meglio).
- Nessuna porta pubblicata nel compose base: `docker compose config | grep -A2 ports` deve essere
  vuoto per app (la porta 127.0.0.1 esiste SOLO in docker-compose.dev.yml).

DELIVERABLE
Report + output build/up + aggiornamento piano/STATO.md (fase 11; la verifica produzione è fase 14).
```

## 4. PROMPT DI VERIFICA (copia-incolla) — Parte A: questa macchina

```text
Verifica la fase 11 di nucs SU QUESTA MACCHINA (Docker locale). Tabella PASS/FAIL con evidenza:
1. `docker compose build` → ok; `docker images | grep nucs` → taglia < 400MB (riporta).
2. `docker compose config` → NESSUNA sezione ports pubblicata (app solo expose 8080 su nucs-net);
   `docker compose config | grep -A2 ports` → vuoto.
3. `docker compose up -d` (senza profili, solo app) → container healthy
   (`docker compose ps`, `docker compose logs app --tail=50` senza errori).
4. Dall'host: `curl localhost:8080/api/health` → DEVE FALLIRE (connection refused) =
   nessuna porta esposta nel compose base. ✅ atteso.
5. `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` → app raggiungibile su
   http://127.0.0.1:8080 → login → feed; /api/health 200; healthcheck green.
6. Scan reali NEL CONTAINER con la libreria di test (MUSIC_LIBRARY_PATH=/tmp/nucs-lib-test):
   scan libreria → artisti; discovery → release nel feed con copertine.
7. Risorse: `docker stats --no-stream` → app < 300MB RAM a riposo (DoD §14.7), CPU ~0.
8. Persistenza: `docker compose down && docker compose up -d` → dati intatti (login, release).
9. `cd e2e && npm run e2e:11` con BASE=http://127.0.0.1:8080 → scenario login+theme+logout+headers verdi.
10. Nessun segreto nei file committati (grep CF_TUNNEL_TOKEN/TS_AUTHKEY in repo → solo .env.example).
Se FAIL: correggi e riesegui TUTTO.
```

> La verifica di PRODUZIONE (mini PC: HTTPS tailnet da più device, scans su libreria vera,
> IP reali nel login, Cloudflare quando ci sarà il dominio) è nella **fase 14**.

## 5. PROMPT DI REVIEW — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un reviewer senior DevOps/security. Revisiona la fase 11 di nucs.
1. Leggi piano/00-specifiche.md §12 §5.5 §5.6 e piano/checklist-sicurezza.md (sezione D TUTTA, C, F1).
2. Esamina: docker/Dockerfile, docker-compose.yml, docker-compose.dev.yml, deploy/, .env.example,
   `git diff main...HEAD`.
3. Caccia: porte esposte accidentalmente (incluso il dev override non documentato), segreti inline
   o nei layer (docker history), container root, filesystem scrivibile oltre il necessario,
   volumi con path host sensibili, :ro mancante sulla libreria, immagini non pinnate,
   healthcheck errato, proxy trust troppo permissivo (0.0.0.0/0), HSTS assente dietro HTTPS,
   serve.json tailscale con sintassi inventata (verifica contro doc ufficiale se puoi),
   cloudflared con autoupdate attivo, reti Docker troppo aperte, logging dei token tunnel,
   cap_drop/pids_limit/no-new-privileges effettivi.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA" + controlli eseguiti.
   Nota: i punti runtime non verificabili senza il mini PC restano marcati "differiti alla fase 14" in STATO.md.
```

Follow-up fix: stesso schema delle fasi precedenti (incolla findings → fix minimi → riverifica completa).

## 6. Criteri di completamento

- [ ] Build multi-arch ok, immagine < 400 MB.
- [ ] Compose base con ZERO porte pubblicate; constraints completi verificati (config + ps + stats).
- [ ] App in container funzionante su questa macchina (login, scans reali con libreria di test,
      feed con copertine, persistenza down/up, e2e:11 locale).
- [ ] Docs deploy/tailscale.md attiva e deploy/cloudflared.md pronta (differita), serve.json con flag.
- [ ] Review avanzata: zero ALTA/MEDIA aperti.
- [ ] STATO.md aggiornato; commit e push: `feat(deploy): multi-stage docker, compose with cloudflared and tailscale`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-12-hardening-qa` → apri `piano/fasi/fase-12-hardening-qa.md`.
3. Dopo la fase 13: **fase 14 — verifica di produzione** (mini PC): quando il mini PC sarà pronto,
   apri `piano/fasi/fase-14-verifica-produzione.md` per il deploy e la verifica completa dell'ambiente reale.

> Promemoria utente: crea l'account Tailscale (gratis) e installa i client sui device; per il
> mini PC servirà solo più avanti. Cloudflare (dominio) è opzionale e differito.

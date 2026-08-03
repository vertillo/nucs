# FASE 11 — Docker finale, Compose, Cloudflare Tunnel, Tailscale

- **Implementazione**: modello economico
- **Review**: **modello AVANZATO obbligatorio** (networking e sicurezza container)
- **Dipende da**: fase 10
- **Branch**: `git checkout -b fase-11-docker-rete`

---

## 1. Obiettivo

Immagine unica (multi-stage) con frontend+backend, compose con 3 servizi (app, cloudflared,
tailscale) come da §12, **nessuna porta esposta sull'host**. Documenti operativi per creare il
tunnel Cloudflare e attivare Tailscale.

## 2. Prerequisiti

- Fase 10 mergiata; app completa e funzionante in dev.
- Sul mini PC: Docker + compose plugin; `.env` compilato da `.env.example`.
- Account Cloudflare (dominio gestito) e Tailscale pronti.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §12 (Docker e rete, TUTTO vincolante), §12.3 (env), §5.6 (proxy)
- piano/README.md §4
- piano/STATO.md
Branch: fase-11. Codice/commenti inglese.

OBIETTIVO
Dockerfile multi-stage + compose + docs deploy.

COMPITI
1. docker/Dockerfile ESATTAMENTE come §12.1:
   - Stage fe: node:20-alpine, COPY frontend/package*.json → npm ci → COPY frontend/ → npm run build.
   - Stage runtime: python:3.12-slim → ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1;
     apt install tini (pinnato alla versione disponibile, usa --no-install-recommends, pulisci apt lists);
     COPY backend/requirements.txt → pip install; COPY backend/ → /app/backend;
     COPY --from=fe dist → /app/static; utente app (uid 1000) owner di /app e mkdir /data;
     USER app; ENV DATA_DIR=/data COVERS_DIR=/data/covers FRONTEND_DIST=/app/static;
     EXPOSE 8080; HEALTHCHECK --interval=30s --timeout=5s --start-period=15s
       CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health')" ;
     ENTRYPOINT ["/usr/bin/tini","--"]; CMD uvicorn come §12.1 (proxy-headers, host 0.0.0.0, port 8080,
     workers 1, working dir /app/backend).
   - Verifica che config.py legga FRONTEND_DIST (esiste già dalla fase 07: altrimenti adatta ORA).
2. docker-compose.yml radice come §12.2: servizi app / cloudflared / tailscale, rete nucs-net,
   volumi nucs-data e ts-state, profili cloudflare/tailscale, limiti risorse §12.2, read_only+tmpfs su app,
   security_opt no-new-privileges su tutti, restart unless-stopped. NESSUNA porta pubblicata.
   healthcheck su app. cloudflared: command tunnel --no-autoupdate run --token ${CF_TUNNEL_TOKEN}.
   tailscale: env TS_STATE_DIR=/var/lib/tailscale TS_HOSTNAME=nucs TS_SERVE_CONFIG=/config/serve.json
   TS_AUTHKEY=${TS_AUTHKEY:-} TS_USERSPACE=false; volumes ts-state + ./deploy/tailscale/serve.json:/config/serve.json:ro
   + /dev/net/tun; cap_add NET_ADMIN + SYS_MODULE? NO — solo NET_ADMIN.
3. deploy/tailscale/serve.json: proxy HTTPS 443 → http://app:8080 (schema:
   {"TCP":{"443":{"HTTPS":true}},"Web":{"${TS_CERT_DOMAIN}:443":{"Handlers":{"/":{"Proxy":"http://app:8080"}}}}}
   — usa variabile d'ambiente supportata da tailscale; SE la sintassi esatta ti è incerta NON inventare:
   scrivi la versione migliore E segnala in STATO.md "serve.json da validare al primo avvio (fase verifica)".)
4. deploy/cloudflared.md: guida step-by-step (numerata, screenshot-less): dashboard Zero Trust →
   Networks → Tunnels → Add → Cloudflared → nome → copia TOKEN in .env (CF_TUNNEL_TOKEN) →
   Public Hostname: subdomain (es. musica), domain tuo, service http://app:8080 → Save.
   Nota sicurezza: valutare Cloudflare Access (allowlist email) come difesa in profondità OPZIONALE
   (l'app ha già login proprio; documentare come attivarlo, non obbligatorio).
5. deploy/tailscale.md: due opzioni: (a) TS_AUTHKEY riutilizzabile da admin console → .env;
   (b) primo avvio senza authkey: docker compose exec tailscale tailscale up → URL di login.
   Poi: https://nucs.<tailnet>.ts.net raggiungibile dai device del tailnet.
6. Backend: verifica trusted proxy (§5.6) funzioni dietro entrambi (cloudflared imposta
   CF-Connecting-IP e X-Forwarded-For; tailscale serve imposta X-Forwarded-For): log dell'IP client
   su login_ok deve mostrare l'IP reale del visitatore (o quello del nodo tailscale), NON quello
   del container proxy. Se serve, mappa CF-Connecting-IP con priorità quando presente.
7. .env.example: allinea con eventuali nuove variabili (TS_*). docker-compose non contiene segreti.
8. README.md radice: sostituisci il placeholder con guida quick-start (build, .env, up con profili,
   primo login, link a deploy/*.md). La guida completa arriva in fase 12: qui bastano i passi essenziali
   VERIFICATI da te in questa fase.

VINCOLI
- Immagine finale < 400 MB (misura con docker images; se sfora, indaga e riduci).
- Build riproducibile: niente `latest` tranne cloudflared/tailscale (annota in STATO.md il perché;
  se riesci a pinnare digest/tag specifici, meglio).
- Nessuna porta pubblicata: `docker compose config | grep -A2 ports` deve essere vuoto per app.

DELIVERABLE
Report + output build/up + aggiornamento piano/STATO.md (fase 11).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 11 di nucs SUL MINI PC. Tabella PASS/FAIL con evidenza:
1. `docker compose build` → ok; `docker images | grep nucs` → taglia < 400MB (riporta).
2. `.env` compilato (ADMIN_*, MUSIC_LIBRARY_PATH reale, CF_TUNNEL_TOKEN, TS_AUTHKEY o pronto login interattivo):
   `docker compose --profile cloudflare --profile tailscale up -d` → tutti i container healthy
   (`docker compose ps`, `docker compose logs app --tail=50` senza errori).
3. `docker compose config` → NESSUNA sezione ports pubblicata; app solo expose 8080 su nucs-net.
4. Dall'host: `curl localhost:8080/api/health` → deve FALLIRE (connection refused) = nessuna porta esposta. ✅ atteso.
5. Cloudflare: https://<subdomain>.<dominio> → pagina login; login → feed; DevTools → HTTPS valido;
   header risposta contiene i security header; /api/health risponde.
6. Tailscale: da un device nel tailnet → https://nucs.<tailnet>.ts.net → login ok.
   (Se serve.json fallisce: leggi `docker compose logs tailscale`, correggi la sintassi con la doc
   ufficiale tailscale serve config, aggiorna serve.json e STATO.md, riprova.)
7. Scan reale: UI impostazioni → "Scansiona libreria ora" sulla libreria vera → artisti popolati;
   poi "Check for new releases now" → release nel feed con copertine.
8. Risorse: `docker stats --no-stream` → app < 300MB RAM a riposo (DoD §14.7), CPU ~0.
9. Login via tunnel: nei log app l'audit login_ok mostra IP reale o CF edge documentato (non 172.x del proxy
   se CF-Connecting-IP presente).
10. `docker compose down && up -d` → dati persistiti (login, release ancora presenti).
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un reviewer senior DevOps/security. Revisiona la fase 11 di nucs.
1. Leggi piano/00-specifiche.md §12 §5.5 §5.6 e piano/checklist-sicurezza.md (sezione D TUTTA, C, F1).
2. Esamina: docker/Dockerfile, docker-compose.yml, deploy/, .env.example, `git diff main...HEAD`.
3. Caccia: porte esposte accidentalmente, segreti inline o nei layer (docker history), container root,
   filesystem scrivibile oltre il necessario, volumi con path host sensibili, :ro mancante sulla libreria,
   immagini non pinnate, healthcheck errato, proxy trust troppo permissivo (0.0.0.0/0), HSTS assente dietro
   HTTPS, serve.json tailscale con sintassi inventata (verifica contro doc ufficiale se puoi),
   cloudflared con autoupdate attivo, reti Docker troppo aperte, logging dei token tunnel.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA" + controlli eseguiti.
```

Follow-up fix: stesso schema delle fasi precedenti (incolla findings → fix minimi → riverifica completa sul mini PC).

## 6. Criteri di completamento

- [ ] App raggiungibile via Cloudflare (HTTPS) e Tailscale, nessuna porta host esposta.
- [ ] Scan reale completo: feed popolato con copertine in produzione.
- [ ] `docker stats`: app < 300MB a riposo.
- [ ] Review avanzata: zero ALTA/MEDIA aperti.
- [ ] STATO.md aggiornato; commit e push: `feat(deploy): multi-stage docker, compose with cloudflared and tailscale`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-12-hardening-qa`.
3. Apri `piano/fasi/fase-12-hardening-qa.md`.

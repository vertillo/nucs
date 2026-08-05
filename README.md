# nucs

Self-hosted app to track new music releases from your favorite artists.
Monitors your local music library, discovers new releases via MusicBrainz,
and displays them in a dark/light UI inspired by music apps.

**Status: under construction** — la guida utente completa arriva in fase 12;
qui il quick-start per farlo girare con Docker.

Specifiche tecniche complete in `piano/00-specifiche.md` (vincolanti).

---

## Quick-start (Docker)

### 1. Prerequisiti

- **Docker** con Compose v2 (Engine ≥ 24, plugin ≥ 2.20).
- Il repo clonato su ogni macchina: l'immagine si **costruisce localmente** per
  l'architettura della macchina (arm64 su Mac, amd64 sul mini PC) — nessun registry.

### 2. Configurazione

```bash
cp .env.example .env
```

Poi compila `.env`:

| Variabile | Significato |
|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | credenziali del primo avvio (poi cambiale dalla UI) |
| `MUSIC_LIBRARY_PATH` | percorso della libreria musicale sull'host (montata sola lettura) |
| `TZ` / `LOG_LEVEL` | fuso orario / livello log |
| `TS_AUTHKEY` | (facoltativa) auth key Tailscale riutilizzabile — vedi `deploy/tailscale.md` |
| `CF_TUNNEL_TOKEN` | (differita) token del tunnel Cloudflare — vedi `deploy/cloudflared.md` |

### 3. Build

```bash
docker compose build
```

> Multi-arch: la build usa solo pacchetti indipendenti dall'architettura;
> ripeti `docker compose build` su ciascuna macchina (arm64 / amd64).

### 4. Avvio con Tailscale (consigliato, senza dominio)

```bash
docker compose --profile tailscale up -d
```

L'app diventa raggiungibile dai device del tuo tailnet su:

```
https://nucs.<il-tuo-tailnet>.ts.net
```

Passi dettagliati (auth key oppure login interattivo, troubleshooting):
**`deploy/tailscale.md`**.

### 5. Avvio con Cloudflare Tunnel (richiede un dominio — differito)

```bash
docker compose --profile cloudflare up -d
```

Guida step-by-step (dashboard Zero Trust, token, public hostname):
**`deploy/cloudflared.md`** — da verificare in fase 14.

### 6. Solo in produzione

Il compose base **non pubblica alcuna porta**: si accede esclusivamente via
tailnet o tunnel. Non aggiungere `ports:` al compose base.

### 7. Test locale sul Mac (dev override)

Per verificare su `http://127.0.0.1:8080` (E2E, scans, manuale):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Il file `docker-compose.dev.yml` è **solo sviluppo/verifica locale**: pubblica la
porta su `127.0.0.1`. In produzione usa sempre il compose base (senza override).

### 8. Primo login

Apri l'URL raggiunto al punto 4/5/7, accedi con `ADMIN_USERNAME` / `ADMIN_PASSWORD`
e subito dopo cambia la password da **Settings → Security**. Le env valgono solo al
primo avvio del DB (spec 5.1).

### 9. Comandi utili

```bash
docker compose ps                          # stato container (app healthy?)
docker compose logs -f app                 # log dell'app
docker compose down                        # stop (i volumi persistono)
```

## Deploy

- **Tailscale** (attivo): `deploy/tailscale.md`
- **Cloudflare Tunnel** (differito, richiede dominio): `deploy/cloudflared.md`

## Sviluppo e verifica

Backend in `backend/` (FastAPI + uvicorn), frontend in `frontend/` (Vite + React):
vedi `piano/STATO.md` e `piano/README.md` per il workflow a fasi e i comandi dev.
E2E automatico (puppeteer) in `e2e/` — `npm run e2e:11` incluso.

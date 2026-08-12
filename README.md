# nucs

## Cos'è

**nucs** è un'app web **self-hosted e single-user** che tiene traccia delle nuove
uscite musicali dei tuoi artisti preferiti:

1. **Legge i tag della tua libreria musicale** (MP3, FLAC, M4A, OGG/Opus) e
   ricava l'elenco degli artisti da monitorare — incluse le *featuring* estratte
   dai titoli (es. `Daft Punk — Get Lucky (feat. Pharrell Williams)`) e i
   contributi (performer/composer/remixer).
2. **Interroga MusicBrainz** (gratuito, senza chiavi) per scoprire album, singoli
   ed EP nuovi — anche release in cui i tuoi artisti compaiono solo come featuring.
3. **Mostra un feed** delle nuove uscite in una UI chiara/scura in stile app
   musicale, con pagina dettaglio e bottoni verso Spotify, YouTube Music, Deezer
   e ricerca Google.
4. È protetta da **login** e gira in **Docker Compose**, pubblicando la porta
   **8067** sull'host: l'accesso da remoto avviene tramite un tunnel o
   reverse-proxy esterno a tua scelta (Tailscale, Cloudflare Tunnel, …) puntato
   su `http://<host>:8067`.

Notifiche opzionali via **Apprise** (Telegram, ntfy, email, …), **backup
automatico giornaliero** del database, audit log e rate limiting sul login.

```
┌─────────────────────────────────────────────┐
│  🎵 nucs                                    │
│  ────────────────────────────────────────── │
│  New releases                  [🔍 Search…] │
│  [All] [Albums] [Singles] [EPs] [☑ Unseen] │
│                                             │
│  ┌──────────────┐  ┌──────────────┐        │
│  │  [cover]     │  │  [cover]     │        │
│  │  Album Title │  │  Single Title│        │
│  │  Artist Name │  │  Artist Name │        │
│  │  2026-08-01  │  │  2026-07-19  │        │
│  │  Album       │  │  Single      │        │
│  └──────────────┘  └──────────────┘        │
│        [ Load more ]                        │
└─────────────────────────────────────────────┘
```

**v1.0.0** — documentazione di riferimento: [`docs/README.md`](docs/README.md)
(implementazione corrente, problemi noti e stato della remediation). L'originaria
specifica tecnica v1 è conservata solo come riferimento storico in
`piano/00-specifiche-legacy.md` e **non è più vincolante**.

---

## Requisiti

- **Docker** con Compose v2 (Engine ≥ 24, plugin ≥ 2.20).
- **Git** (per clone e aggiornamenti).
- Una **libreria musicale locale** (montata sola lettura — l'app non scrive mai
  dentro la musica).
- Opzionale, solo se vuoi l'accesso da fuori rete locale: un tunnel o
  reverse-proxy esterno a tua scelta (Tailscale, Cloudflare Tunnel, …) puntato
  sulla porta 8067 pubblicata dall'app.

L'immagine si **costruisce localmente** per l'architettura della tua macchina
(arm64 su Mac, amd64 su PC/mini PC): nessun registry richiesto.

---

## Installazione passo-passo

### 1. Clona il repo e configurati

```bash
git clone <url-del-tuo-repo> nucs
cd nucs
cp .env.example .env
```

### 2. Compila il file `.env`

| Variabile | Obbligatoria | Significato |
|---|---|---|
| `ADMIN_USERNAME` | ✅ | username del primo avvio |
| `ADMIN_PASSWORD` | ✅ | password del primo avvio (min 12 caratteri). **Solo primo avvio**: poi la cambi dalla UI (Settings → Security) e l'env non ha più effetto |
| `MUSIC_LIBRARY_PATH` | ✅ | percorso della libreria musicale sull'host, es. `/srv/musica` (montata **sola lettura** dentro il container) |
| `TZ` | ❌ | fuso orario, default `Europe/Rome` |
| `LOG_LEVEL` | ❌ | livello log, default `INFO` |
| `NOTIFY_URLS` | ❌ | URL Apprise (uno per riga o CSV, provider misti, es. `tgram://<token>/<chat_id>`). Seed solo al primo avvio |
| `NOTIFY_ENABLED` | ❌ | `false` per avviare con notifiche disattivate (default: attive, ma senza URL non inviano nulla) |
| `DEV_INSECURE_COOKIES` | ❌ | `true` SOLO per sviluppo su http locale; in produzione lascia `false` |
| `TRUSTED_PROXY_CIDRS` | ❌ | rete/i dei proxy fidati per `X-Forwarded-For`; default `172.16.0.0/12,10.0.0.0/8` (rete Docker interna). Non allargare se non sai cosa fai |

### 3. Build e avvio

```bash
docker compose build
```

Poi avvia:

```bash
docker compose up -d
```

L'app è raggiungibile su **`http://<host>:8067`**. Il primo avvio applica le
migrazioni del database e crea l'utente admin dal `.env`. Se vuoi l'accesso da
fuori rete locale, punta un tunnel/reverse-proxy esterno a tua scelta
(Tailscale, Cloudflare Tunnel, …) su `http://<host>:8067`.

> Per una prova rapida su `http://127.0.0.1:8066` (sviluppo/verifica locale):
> `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
> — il file `docker-compose.dev.yml` è **solo sviluppo**, in produzione usa il
> compose base.

---

## Accesso da remoto (opzionale)

L'app pubblica la porta **8067** sull'host. Per accederci da fuori rete locale,
punta un tunnel o reverse-proxy esterno a tua scelta su `http://127.0.0.1:8067`
(o direttamente sull'host:8067):

- **Tailscale**: `tailscale serve` dalla macchina host verso
  `http://127.0.0.1:8067`.
- **Cloudflare Tunnel**: un tunnel `cloudflared` verso `http://127.0.0.1:8067`.
- Qualsiasi **reverse proxy** (Caddy, nginx, …) con la stessa destinazione.

I sidecar Tailscale/Cloudflare che prima vivevano **dentro** il compose sono
stati rimossi: il tunnel ora è esterno allo stack e gestito da te.

---

## Primo avvio e primo scan

1. Apri l'URL dell'app (`http://<host>:8067`, o l'URL del tuo tunnel esterno) e
   accedi con `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
2. Subito dopo vai su **Settings → Security** e **cambia la password** (le env
   valgono solo al primo avvio).
3. Vai su **Settings → Discovery**: controlla "Discover releases from" (default:
   ultimi 30 giorni) e attiva "Weekly featuring scan" se vuoi le featuring a
   livello traccia.
4. In **Settings → Scans** premi **"Scan library now"** (estrae gli artisti dalla
   tua musica e li abbina a MusicBrainz) e poi **"Check for new releases now"**.
5. Torna al feed: le nuove uscite appaiono con copertina, badge del tipo e
   pallino verde se non viste.

Da qui in poi gli scan girano da soli: libreria ogni giorno alle **03:00**,
nuove release alle **04:00**, featuring ogni domenica, backup alle **02:30**
(UTC del container).

---

## Uso quotidiano

- **Feed** (`/`): filtri per tipo (All/Albums/Singles/EPs), "Unseen only",
  ricerca, "Mark all as seen".
- **Dettaglio release**: copertina, artisti con ruolo, bottoni **Spotify /
  YouTube Music / Deezer / Google** (aprono in nuova scheda), toggle
  Seen/Favorite/Hide.
- **Artists** (`/artists`): stato abbinamento MusicBrainz (✅ score / ⚠️
  Unmatched + Retry), aggiunta manuale, toggle **Ignore** per escludere un
  artista (senza cancellarlo).
- **Settings** (`/settings`): discovery, orari scan, notifiche Apprise (con
  "Send test notification"), credenziali Spotify (opzionali), tema, cambio
  password, sessioni attive con revoca, About con versione e contatori.

---

## Backup e ripristino

- **Backup automatico**: ogni notte alle 02:30 viene creata una copia coerente
  del database in `nucs-data:/data/backups/app-YYYYMMDD-HHMMSS.db`
  (conservate **7 giorni**). Backup manuale: `docker compose exec app python -m app.cli backup-now`.
- **Ripristino**: ferma l'app, sostituisci il file di database nel volume
  `nucs-data` (`/data/app.db`) con una copia di backup, riavvia. Le migrazioni
  restano compatibili (il backup è dello stesso schema).

```bash
docker compose down
# copia /data/backups/app-<data>.db -> /data/app.db dentro il volume nucs-data
docker compose up -d
```

Le copertine sono già in `/data/covers` e vengono riusate.

---

## Aggiornamento

```bash
git pull
docker compose build
docker compose up -d
```

Le migrazioni del database partono da sole al primo avvio del nuovo container.
Controlla i log: `docker compose logs -f app`.

---

## Sicurezza

L'app applica di default:

- **Login** con password **argon2id**, sessioni opache HttpOnly+Secure+SameSite=Lax,
  risposta identica (tempo incluso) per utente inesistente/password errata.
- **Rate limiting anti brute-force**: 5 tentativi/5 min per IP; dopo 10
  fallimenti consecutivi blocco globale di 15 minuti; ogni tentativo è
  registrato nell'audit log.
- **Header di sicurezza** su tutte le risposte: CSP stretta (niente eval né
  inline style), nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy,
  HSTS dietro HTTPS, niente header `Server`.
- **CSRF**: le richieste mutanti richiedono `X-Requested-With` + Origin/Referer
  coerente.
- **Container**: utente non-root, filesystem read-only, limiti memoria/CPU,
  porta 8067 pubblicata, IP reali rispettando solo i proxy fidati.
- **Log senza segreti**: mai password/token/secret nei log.

**Raccomandazione (opzionale, difesa in profondità)**: se esponi nucs da
remoto, attiva un controllo di accesso sul tuo tunnel/reverse proxy (es.
allowlist email o di rete) davanti alla porta 8067.

---

## FAQ

**1. Una release nuova non appare nel feed. Perché?**
Il caso più comune: l'artista non è ancora abbinato a MusicBrainz (⚠️ "Unmatched"
nella pagina Artists) — l'app non può chiedere le uscite senza il MusicBrainz ID.
Vai su **Artists → Retry** per riprovare il match, oppure aggiungi l'artista
manualmente. Ricorda anche che la ricerca parte dalla data di
"Discover releases from": release più vecchie non vengono mostrate.

**2. Un artista è stato spezzato male (es. "Earth, Wind & Fire" diviso in due).**
Il matcher prima prova il nome intero (score ≥ 90 lo mantiene singolo) e solo
poi splitta. Se il risultato è sbagliato, la pagina **Artists** ti permette di
**Ignorare** l'artista spurio: resta nel database ma non viene più monitorato né
mostrato nel feed.

**3. Come ricevo le notifiche delle nuove uscite?**
Imposta uno o più URL Apprise in **Settings → Notifications** (es.
`tgram://<token>/<chat_id>` per Telegram) e premi "Send test notification". Se
attive, arriva una sola notifica aggregata per scan: "nucs: N new releases".
Le notifiche partono solo se `NOTIFY_URLS` è valorizzato.

**4. Come cambio la porta di accesso?**
La porta pubblicata sull'host è **8067** (mappatura `8067:8080` in
`docker-compose.yml`): cambiala lì e riavvia con `docker compose up -d`. Per
test locale c'è il dev override su `127.0.0.1:8066` (sezione Installazione,
punto 3). L'accesso da remoto passa dal tuo tunnel/reverse-proxy esterno
puntato sulla porta pubblicata.

**5. Ho dimenticato la password. Come la resetto?**
Da terminale, sul server:

```bash
docker compose exec app python -m app.cli create-admin <nuovo-utente> <nuova-password>
```

Il comando crea/sostituisce l'account admin (password min 12 caratteri) e le
vecchie sessioni restano valide solo se non le revochi: dopo il login, vai su
**Settings → Security → Revoke other sessions**.

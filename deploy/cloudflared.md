# Cloudflare Tunnel — accesso pubblico HTTPS via Cloudflare (differito)

> **DA VERIFICARE IN FASE 14 — richiede un dominio gestito da Cloudflare.**
> Il servizio `cloudflared` è già nel compose (profilo `cloudflare`); manca solo
> il token del tunnel e la configurazione del Public Hostname. Quando avrai un
> dominio su Cloudflare, segui questa guida e verifica in fase 14.

## Cosa ottieni

Un URL pubblico `https://musica.<iltuodominio>` che punta all'app via tunnel
Cloudflare (niente porta aperta sull'host, niente IP di origine esposto). L'utente
finale raggiunge l'app da qualsiasi rete; l'accesso è comunque protetto dal login
di nucs (username+password).

## Prerequisiti

- Account Cloudflare (gratuito) con **un dominio gestito da Cloudflare** (nameserver).
- (Solo per l'abilitazione di una volta) il client `cloudflared` installato
  localmente **oppure** la procedura guidata via dashboard (sotto).

## Passi

1. Accedi alla dashboard Zero Trust:
   https://one.dash.cloudflare.com → nel menu laterale: **Networks → Tunnels**.

2. Clicca **Add a tunnel** (o **Create a tunnel**).

3. Seleziona la tipologia **Cloudflared** e clicca **Next**.

4. Dai un **nome** al tunnel (es. `nucs` — serve solo a riconoscerlo in dashboard)
   e clicca **Save tunnel**.

5. Nella schermata di installazione, scegli il comando **docker** (non serve
   eseguirlo davvero: il token è ciò che ci serve). Copia il parametro `--token`
   (formato `eyJ...` o `eyJ...`) dal comando proposto:

   ```
   cloudflared tunnel --no-autoupdate run --token eyJ...
   ```

6. Apri il file `.env` alla radice del repo e imposta:

   ```
   CF_TUNNEL_TOKEN=eyJ...
   ```

   > Il token identifica il tunnel: trattalo come un segreto (non committarlo,
   > mai nel repo: esiste solo `.env.example` con il campo vuoto).

7. Nella dashboard, nella pagina del tunnel appena creato, vai su
   **Public Hostname** e clicca **Add a public hostname**.

8. Compila:
   - **Subdomain**: es. `musica`
   - **Domain**: il tuo dominio gestito da Cloudflare (es. `iltuodominio.it`)
   - **Service**: tipo `HTTP` + URL `app:8080`
   - Clicca **Save** (o **Save hostname**).

9. Avvia il profilo cloudflare:

   ```bash
   docker compose --profile cloudflare up -d
   ```

10. Verifica:

    ```bash
    docker compose ps                          # cloudflared running
    docker compose logs cloudflared            # "Registered tunnel connection"
    ```

11. Apri nel browser: `https://musica.<iltuodominio>` → login di nucs.

## Note di sicurezza

- **Nessuna porta pubblicata sull'host**: il tunnel parte da dentro la rete
  Docker (`nucs-net`) verso Cloudflare; l'app resta raggiungibile solo via
  tunnel o tailnet.
- **Cloudflare Access (OPZIONALE, difesa in profondità)**: puoi proteggere
  l'URL pubblico con una allowlist email dal tuo team — in Zero Trust →
  **Access → Applications** crea un'applicazione (Self-hosted, domain
  `musica.<iltuodominio>`) e una policy con `Emails` degli utenti autorizzati.
  Così, anche chi conoscesse l'URL, deve essere nella allowlist PRIMA di vedere
  la pagina di login di nucs.
- Il login di nucs (password admin, rate limiting anti brute-force, audit log)
  resta comunque la barriera principale: Cloudflare Access è solo un secondo
  strato, non un sostituto.

## Troubleshooting

| Sintomo | Cosa fare |
|---|---|
| `cloudflared` non parte | Controlla che `CF_TUNNEL_TOKEN` sia valorizzato nel `.env`; `docker compose logs cloudflared` per l'errore esatto |
| 502 Bad Gateway da Cloudflare | L'app deve essere healthy (`docker compose ps`): il tunnel non è il problema, controlla `docker compose logs app` |
| URL non risolve | Verifica che il dominio sia davvero gestito da Cloudflare (nameserver) e che il Public Hostname sia stato salvato |

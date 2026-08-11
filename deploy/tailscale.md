# Tailscale (attivo) — accesso privato all'app via tailnet, senza dominio

> **DA VERIFICARE IN FASE 14** — questa guida è implementata e pronta; la verifica
> con il mini PC reale e gli IP reali è nella fase 14.
> La sintassi di `serve.json` è stata verificata contro il sorgente ufficiale del
> container `tailscale/tailscale` (il placeholder `${TS_CERT_DOMAIN}` viene sostituito
> con il dominio certificato reale del nodo al primo avvio), ma il comportamento
> end-to-end va confermato sul mini PC: se `serve.json` fallisce, leggi
> `docker compose logs tailscale`, correggi e riprova (dettagli in fase 14).

## Cosa ottieni

Il container `tailscale` si unisce al tuo **tailnet** con hostname `nucs` e, via
**Tailscale Serve** (config `deploy/tailscale/serve.json`), pubblica l'app
(`http://app:8080`, rete interna `nucs-net`) su:

```
https://nucs.<il-tuo-tailnet>.ts.net
```

raggiungibile **solo dai device del tuo tailnet** (telefono, laptop, altro mini PC)
dove hai installato il client Tailscale e sei loggato con lo stesso account.
Nessuna porta viene esposta sull'host e nessun dominio è richiesto.

> Serve richiede **HTTPS abilitato per il tailnet** (attivo di default sui tailnet
> gratuiti; se serve, si abilita in una volta dal prompt di `tailscale serve`).

## Prerequisiti

- Account Tailscale (gratuito) e tailnet attivo: https://login.tailscale.com
- Il mini PC (o la macchina che ospita i container) raggiungibile da Docker.
- `/dev/net/tun` presente sul host Linux (`ls -l /dev/net/tun`; se manca,
  `sudo modprobe tun` o abilita il modulo TUN dal BIOS/VM).
- Client Tailscale installati sui device da cui vuoi accedere all'app.

> Nota macOS: Docker Desktop non espone `/dev/net/tun`, quindi il profilo
> `tailscale` non può partire sul Mac di sviluppo — è previsto per il mini PC
> (fase 14). Per test locali usa il compose dev (`127.0.0.1:8066`).

## Passi

### 1. Configura `.env`

Nel file `.env` alla radice del repo (copia di `.env.example`), assicurati che
`TS_HOSTNAME=nucs` e `TS_STATE_DIR=/var/lib/tailscale` siano presenti (già di
default) e scegli una delle due opzioni di accesso sotto.

### 2. Opzione (a) — auth key riutilizzabile (consigliata per il mini PC)

1. Vai su **Admin Console** → https://login.tailscale.com/admin/settings/keys
2. Clicca **Generate auth key...**
3. Seleziona **Reusable** (se vuoi che il container si riautentichi dopo un wipe
   del volume `ts-state`; se preferisci, usa la scadenza che preferisci).
4. Copia la chiave (formato `tskey-auth-...`) e mettila nel `.env`:

   ```
   TS_AUTHKEY=tskey-auth-xxxxxxxxxxxxxxxxxxxx
   ```

5. Avvia:

   ```bash
   docker compose --profile tailscale up -d
   ```

6. Verifica che il nodo `nucs` compaia in Admin Console → **Machines** e che il
   container risulti connesso:

   ```bash
   docker compose exec tailscale tailscale status
   ```

### 3. Opzione (b) — primo avvio senza auth key (login interattivo)

Utile al primo deploy quando vuoi approvare l'autenticazione dal browser:

1. Lascia `TS_AUTHKEY=` vuota nel `.env` e avvia il profilo:

   ```bash
   docker compose --profile tailscale up -d
   ```

2. Esegui il login interattivo:

   ```bash
   docker compose exec tailscale tailscale up
   ```

3. Il comando stampa un **URL di login** (es. `https://login.tailscale.com/a/...`):
   aprilo nel browser del device, autenticati con l'account del tailnet e approva
   il nodo. Dopo il login, l'URL di accesso al terminale si chiude da solo.

4. Verifica:

   ```bash
   docker compose exec tailscale tailscale status
   ```

### 4. Accesso all'app

1. Apri dal device nel tailnet:

   ```
   https://nucs.<il-tuo-tailnet>.ts.net
   ```

   (il nome tailnet esatto è visibile in Admin Console, o con
   `docker compose exec tailscale tailscale status` — campo DNS name del nodo).

2. Primo accesso: inserisci le credenziali `ADMIN_USERNAME` / `ADMIN_PASSWORD`
   del `.env` (valgono solo al primo avvio del DB; poi cambiale dalla UI →
   Settings → Security).

## Modificare la configurazione Serve

La config serve vive in `deploy/tailscale/serve.json` (montata in sola lettura
nel container). Dopo una modifica:

```bash
docker compose --profile tailscale restart tailscale
```

Il container ricarica la config al riavvio. Il valore del dominio
`${TS_CERT_DOMAIN}` viene sostituito automaticamente dal container con il
dominio certificato reale del nodo; non serve sostituirlo a mano.

## Troubleshooting

| Sintomo | Cosa fare |
|---|---|
| `https://nucs.<tailnet>.ts.net` non risponde | `docker compose logs tailscale`: se vedi errori serve/config, controlla che HTTPS sia abilitato nel tailnet e che il nodo sia autenticato; riprova con un altro device del tailnet |
| Container `tailscale` in crash-loop | Verifica `/dev/net/tun` sul host (Linux) e che `TS_USERSPACE=false` sia coerente (serve il TUN device) |
| Il nodo sparisce a ogni riavvio | Lo stato deve persistere nel volume `ts-state`: controlla che `TS_STATE_DIR=/var/lib/tailscale` sia impostato (di default sì) e che il volume non sia stato rimosso |
| Serve non si attiva | L'app deve essere healthy (`docker compose ps`); con `TS_SERVE_CONFIG` la config viene applicata quando il nodo ha il dominio certificato (dopo il primo login) |
| Auth key scaduta/ruotata | Rigenera la chiave in Admin Console, aggiorna `.env`, poi `docker compose --profile tailscale up -d --force-recreate tailscale` |

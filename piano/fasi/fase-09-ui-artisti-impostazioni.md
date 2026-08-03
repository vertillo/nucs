# FASE 09 — UI: pagina artisti + pagina impostazioni

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 08
- **Branch**: `git checkout -b fase-09-ui-artisti-impostazioni`

---

## 1. Obiettivo

Le ultime due pagine: gestione artisti (lista, ignora, aggiungi, rematch — §11.2.4) e impostazioni
complete (§11.2.5): data di scoperta, tipi di release, scansioni manuali con stato, notifiche,
integrazione Spotify, tema, cambio password, sessioni attive, info.

## 2. Prerequisiti

- Fase 08 mergiata. Endpoint `/artists/*`, `/settings`, `/scans/*`, `/auth/*` già funzionanti.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §11.2.4 (artisti), §11.2.5 (impostazioni, TUTTE le sezioni), §10 (shape API), §11.3
- piano/README.md §4
- piano/STATO.md
Branch: fase-09. Codice/commenti inglese, STRINGHE UI IN INGLESE. Solo Tailwind + SVG inline.
Se esistono mockup in piano/mockup/: usali come riferimento visivo vincolante.

OBIETTIVO
Pagine Artists e Settings complete.

COMPITI
1. src/api/artists.ts + settings.ts: hook react-query per GET/POST/PATCH artists, GET/PUT settings,
   POST scans, GET scans/status (polling 3s SOLO mentre running != null), POST auth/password,
   GET auth/sessions, POST auth/sessions/revoke-others, POST settings/notify-test.
2. pages/Artists.tsx (§11.2.4): H1 "Tracked artists"; toolbar: input placeholder "Search artist…" (debounce),
   select filtro [All|Active|Ignored], bottone accent "+ Add artist" → modale semplice
   (overlay + card: input nome, bottone "Add", chiudi; su 400 mostra messaggio).
   Tabella responsive (mobile → card list): Name | Source (badge: Artist/Album artist/Featuring/
   Contributor/Manual — mappa dai valori tag_*) | MB match (✅ + score verde se mbid, altrimenti ⚠️
   "Unmatched" + bottone text-sm "Retry" → POST rematch → toast inline esito) | Releases (n) |
   Toggle "Ignore" (switch; PATCH ottimistico). Paginazione "Load more" come feed.
3. pages/Settings.tsx (§11.2.5): layout a card impilate max-w-3xl, ogni card con H2 e descrizione
   textDim. Sezioni ESATTE:
   a. "Discovery": input type=date label "Discover releases from" (value da discovery_from_date); checkbox
      [Albums, Singles, EPs] → release_types CSV (almeno 1 obbligatorio); switch "Weekly featuring scan"
      (feat_scan_enabled). Bottone "Save" per sezione (PUT /settings) + feedback "Saved ✓".
   b. "Scans": due input type=time (scan_library_time, scan_releases_time); bottoni
      "Scan library now" / "Check for new releases now" (POST scans/*; disabilitati+spinner mentre
      running; 409 → messaggio "Scan already in progress"); tabella "Recent scans" (tipo, inizio, durata,
      esito ok/errore, stats chiave: artisti nuovi / release nuove) da scans/status.
   c. "Notifications": switch notify_enabled; textarea "Apprise URLs (one per line)" (notify_urls CSV↔righe);
      bottone "Send test notification" → POST notify-test → mostra esito/errore.
   d. "Integrations": input Spotify Client ID; input password Spotify Client Secret (placeholder
      "••••••••" se spotify_client_secret_set, svuotato alla submit se non modificato: invia solo se
      l'utente scrive); input email "MusicBrainz contact email".
   e. "Appearance": radio [Dark|Light] → applyTheme immediato + PUT settings theme.
   f. "Security": form cambio password (label "Current password", "New password", "Repeat new password";
      validazione client min 12 char e coincidenza; POST auth/password → 204 → messaggio "Password updated"
      e testo che segnala la revoca delle altre sessioni); sotto: "Active sessions" lista (browser da
      user_agent troncato a 40 char, IP, ultimo accesso in formato "YYYY-MM-DD HH:MM", badge "Current")
      + bottone danger "Revoke other sessions".
   g. "About": app version (da /api/health), tracked artists (count da /artists?ignored=no&page_size=1 → total),
      releases in DB (da /releases?page_size=1 → total), library path (da /settings se esposto:
      se non esposto dal backend, mostra "Configured via environment variable").
4. Validazioni client identiche a quelle server (date ISO, HH:MM, min 1 tipo): errori inline sotto il campo.
5. Toast/feedback: semplice componente inline (messaggio verde/rosso che scompare dopo 4s), niente librerie.
6. Typecheck pulito, build ok.

VINCOLI
- Solo endpoint §10 esistenti. Se un dato manca (es. library path in GET /settings) FERMATI e scrivilo
  in STATO.md; NON modificare il backend in questa fase salvo bug bloccante (segnalalo).
- Secret Spotify: mai mostrare il valore; invialo solo se l'utente lo riscrive.
- Accessibilità: label associate, focus ring, switch con role="switch" + aria-checked.

DELIVERABLE
Report + output build + aggiornamento piano/STATO.md (fase 09).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 09 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd frontend && npm ci && npx tsc --noEmit && npm run build` → exit 0.
2. Browser con backend avviato:
   - /artists: lista popolata; search filtra; toggle Ignore → artista passa a "Ignored" (select filtro);
     "Retry" su un unmatched → feedback; "+ Add artist" con nome nuovo → appare in lista
     (match in background: ricarica dopo 5s per vedere l'esito); aggiunta duplicata → errore inline.
   - /settings "Discovery": cambia data → Save → reload → data persistita; deseleziona tutti i tipi → errore inline.
   - "Scans": click "Scan library now" → bottone disabilitato + spinner; tabella "Recent scans"
     si aggiorna a fine run (polling); secondo click durante run → "Scan already in progress".
   - "Notifications": senza URL → test fallisce con messaggio chiaro; (se hai un URL Apprise reale: configura
     e verifica la ricezione).
   - "Integrations": scrivi secret finto → Save → reload → campo mostra placeholder, NON il valore
     (verifica anche in DevTools Network che GET /settings non lo contiene).
   - "Appearance": radio Light → tema cambia subito e persiste dopo logout/login.
   - "Security": cambio password con nuova <12 char → errore; con attuale errata → errore; corretto →
     messaggio "Password updated"; apri seconda sessione in altro browser/incognito, poi "Revoke other sessions" →
     l'altra sessione riceve 401 al refresh.
   - Mobile 375px: tutto usabile senza scroll orizzontale.
3. Console pulita; nessuna chiamata a endpoint inesistenti (404 in Network).
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 09 di nucs.
1. Leggi piano/00-specifiche.md §11.2.4 §11.2.5 §10 §5.8 e piano/checklist-sicurezza.md (B5, C3).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: secret mai visualizzato né reinviato non modificato (C3), validazioni client allineate
   al server, race conditions su toggle ottimistici, polling fermato quando non serve (memory leak),
   modale con focus management minimo, nessun endpoint inventato, stringhe UI in inglese.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Entrambe le pagine complete e verificate nel browser (incluse persistenze e revoca sessioni).
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(frontend): artists management and settings pages`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-10-scheduler-notifiche`.
3. Apri `piano/fasi/fase-10-scheduler-notifiche.md`.

> Se vuoi le **notifiche**, prepara ORA un URL Apprise (es. bot Telegram: `tgram://token/chat_id`,
> oppure ntfy: `ntfy://ntfy.sh/tuo-topic`). Servirà per la verifica della fase 10.

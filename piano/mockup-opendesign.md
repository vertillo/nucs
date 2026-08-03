# Mockup interattivo nucs — Brief per Open Design

> **Scopo**: generare con Open Design un prototipo UI interattivo e cliccabile di nucs,
> per validare flussi, schermate e feature **prima** di scrivere il frontend (fasi 07-09).
>
> **Come usarlo**:
> 1. Apri la cartella del progetto in Open Design (o nella CLI del tuo coding agent con le skill Open Design attive).
> 2. Incolla l'intero blocco "IL PROMPT" qui sotto come richiesta.
> 3. Itera a parole sul risultato ("la card è troppo alta", "sposta i filtri sotto il titolo"…).
> 4. Salva l'artifact finale in `piano/mockup/` (es. `piano/mockup/index.html` + asset).
> 5. Verifica il prototipo con la **checklist in fondo** a questo documento.
> 6. Se dalle iterazioni emergono cambiamenti UX che approvi → aggiorna PRIMA `piano/00-specifiche.md` §11
>    (è la fonte di verità), poi le fasi 07-09 useranno i mockup come riferimento visivo vincolante.

---

## IL PROMPT (copia-incolla integralmente)

```text
Crea un PROTOTIPO HTML INTERATTIVO e CLICCABILE per una web app chiamata "nucs".
Deliverable: un unico file index.html autocontenuto (CSS e JS inline, niente build step, niente
dipendenze esterne, niente chiamate di rete: tutti i dati sono mockati inline in JS).
Deve aprirsi in browser e permettere di navigare tra le schermate come se fosse l'app vera
(router simulato in JS, viste show/hide). Non è un'immagine: i controlli principali devono funzionare.

════════════════════════════════════════
1. COS'È NUCS
════════════════════════════════════════
nucs è un'app web self-hosted, single-user, che ti aiuta a non perdere le nuove uscite musicali
degli artisti che ami. Legge i tag della tua libreria musicale locale, ricava gli artisti da
monitorare (inclusi album artist, artisti in featuring e contributi tipo performer/composer),
interroga MusicBrainz e mostra un feed delle nuove release (album, singoli, EP) da una data
configurabile in poi — incluse le release in cui un tuo artista compare SOLO come featuring,
anche su dischi di artisti che non conosci. Ogni release ha una pagina dettaglio con bottoni
verso Spotify, YouTube Music, Deezer o ricerca Google. L'app è protetta da login.
Tono visivo: app musicale moderna alla Spotify — scura, densa di copertine, verde accento.

════════════════════════════════════════
2. DESIGN SYSTEM (rispettare ESATTAMENTE)
════════════════════════════════════════
Tema SCURO di default, con tema CHIARO attivabile da un toggle (cambio istantaneo via classe
sulla root, entrambi completi in ogni schermata).

Colori (usa CSS custom properties):
- accent: #1DB954 (hover #1ED760, active #169C46) — verde "musicale"
- danger: #E5484D
- Tema scuro: bg #0F0F0F, surface #181818, surface2 #242424, border #2C2C2C,
  text #F5F5F5, textDim #A3A3A3
- Tema chiaro: bg #FFFFFF, surface #F6F6F6, surface2 #FFFFFF, border #E4E4E4,
  text #131313, textDim #5C5C5C
- Bottoni brand: YouTube Music #FF0000 (testo bianco), Deezer #A238FF (testo bianco),
  Spotify = accent con testo NERO (contrasto AA), Google = surface2 con bordo border e testo text.

Tipografia: system stack (-apple-system, "Segoe UI", Roboto, Inter, sans-serif).
Titoli semibold; corpo 14-16px; metadati 12-13px in textDim.
Forme: card rounded-2xl (16px), copertine rounded-xl (12px), bottoni rounded-full (pill),
badge/pill rounded-full. Ombre morbide sulle card solo nel tema scuro (shadow nera 40%).
Focus visibile: anello 2px accent su tutti gli elementi interattivi.
Icone: SVG inline semplici (linea sottile), coerenti tra loro. Logo: wordmark "nucs" minuscolo
con emoji 🎵 accanto.

Regole globali UI:
- TUTTI i testi dell'interfaccia in INGLESE (vedi glossario §6 per le stringhe esatte).
- Date SEMPRE in formato ISO 8601: YYYY-MM-DD (es. 2026-07-25). Date parziali così come sono ("2026").
- Responsive: progetta a 1440px desktop E a 375px mobile (breakpoint <640px: grid release 2 colonne,
  navbar compatta con sole icone, tabelle che diventano card).
- Accessibilità: contrasto AA, aria-label su toggle e bottoni-icona, alt sulle copertine.
- Copertine: nel prototipo usa placeholder generati (div con gradiente scuro + iniziali o icona nota
  SVG, ognuno di colore diverso): NON caricare immagini esterne.

════════════════════════════════════════
3. SCHERMATE (tutte, con gli stati indicati)
════════════════════════════════════════

A) LOGIN (/login)
- Centrata su bg. Card surface con: emoji 🎵 + wordmark "nucs", sottotitolo textDim
  "Never miss a release from the artists you love", input "Username", input "Password",
  bottone pill accent full-width "Log in".
- STATO ERRORE riproducibile: cliccando "Log in" con campi vuoti o con un bottone demo
  "Simulate error", mostra sotto il form il messaggio danger "Invalid credentials".

B) FEED — "New releases" (/) — schermata principale
- Navbar top: a sinistra 🎵 nucs; al centro/sinistra link Feed / Artists / Settings (voce attiva
  in accent); a destra toggle tema (icona sole/luna, aria-label "Toggle theme") e bottone "Log out".
- Sotto: H1 "New releases". Riga filtri: chip pill [All | Albums | Singles | EPs] (attivo = bg accent,
  testo nero), switch "Unseen only", input search con placeholder "Search…" (filtra live),
  bottone textDim "Mark all as seen" (conferma con dialog, poi i pallini spariscono).
- Grid card 2-6 colonne (2 su mobile). Ogni card: copertina quadrata in alto, sotto: titolo
  (max 2 righe con ellissi), riga artisti (i TUOI artisti monitorati in accent medium, gli altri
  in textDim; se un tuo artista è in featuring mostra " (feat. Nome)"), data ISO, badge pill
  surface2 con tipo (Album/Single/EP), pallino accent in alto a destra sulla copertina se non vista.
- Click card → pagina dettaglio. In fondo bottone "Load more" (aggiunge altre card).
- STATI da rendere raggiungibili: loading (skeleton card animate-pulse, mostralo 1s al primo load),
  empty state (icona + "No new releases" + sottotesto "Try running a scan from Settings" + link)
  raggiungibile attivando "Unseen only" dopo "Mark all as seen".

C) DETTAGLIO RELEASE (/releases/:id)
- Link "← Back to feed". Layout 2 colonne (mobile: stacked): a sinistra copertina grande (max 384px,
  rounded-xl); a destra: H1 titolo, riga meta (data ISO completa + badge tipo + eventuali secondary
  types in textDim), blocco "Your artists": elenco degli artisti monitorati coinvolti con ruolo
  ("Main artist" / "Featuring" / "Contributor") in accent.
- Riga di 4 bottoni pill: Spotify / YouTube Music / Deezer / Search on Google (colori brand §2,
  aperti in nuova tab, qui href="#").
- Sotto: tre toggle: "Seen" (switch attivo di default dopo l'apertura — aprire il dettaglio segna
  la release come vista: tornando al feed il pallino è sparito), "Favorite" (cuore che si riempie),
  "Hide". Se Hide attivo: badge "Hidden" + bottone "Restore".

D) ARTISTI — "Tracked artists" (/artists)
- H1 "Tracked artists". Toolbar: search "Search artist…", select [All | Active | Ignored],
  bottone accent "+ Add artist" → MODALE (overlay scuro + card: input "Artist name", bottoni
  "Add" / "Cancel"; dopo Add la modale chiude e l'artista appare in lista con stato "matching…").
- Tabella (mobile: card list): Name | Source (badge: Artist / Album artist / Featuring /
  Contributor / Manual) | MB match (✅ verde + score es. "92" se abbinato; altrimenti ⚠️ "Unmatched"
  + bottone text-sm "Retry") | Releases (numero) | toggle "Ignore" (switch; gli ignorati vanno
  nel filtro Ignored e diventano textDim).
- In fondo "Load more".

E) IMPOSTAZIONI (/settings) — card impilate max-w-3xl, ognuna con H2 + descrizione textDim:
1. "Discovery": input date "Discover releases from" (valore 2026-06-01); checkbox [Albums Singles EPs]
   (almeno 1 obbligatorio: se li deselezioni tutti, errore inline "Select at least one release type");
   switch "Weekly featuring scan". Bottone "Save" → feedback verde "Saved ✓" (scompare dopo 3s).
2. "Scans": due input time (03:00 e 04:00); bottoni "Scan library now" e "Check for new releases now"
   (al click: spinner + disabilitato per 3s, poi la tabella si aggiorna; se clicchi mentre gira:
   messaggio "Scan already in progress"). Tabella "Recent scans": colonne Type / Started / Duration /
   Status (ok verde / error danger) / Results (es. "3 new releases").
3. "Notifications": switch off di default; textarea "Apprise URLs (one per line)"; bottone
   "Send test notification" → se switch off: errore inline "Notifications are disabled";
   se on senza URL: errore "Add at least one Apprise URL".
4. "Integrations": input "Spotify Client ID"; input password "Spotify Client Secret" con placeholder
   "••••••••"; input email "MusicBrainz contact email".
5. "Appearance": radio [Dark | Light] — cambia tema all'istante (stesso effetto del toggle in navbar).
6. "Security": form "Current password" / "New password" / "Repeat new password" con validazioni
   inline (nuova <12 char → "Password must be at least 12 characters"; ripetuta diversa →
   "Passwords do not match"; successo → "Password updated"). Sotto: "Active sessions": lista di 2-3
   sessioni finte (browser, IP, ultimo accesso "YYYY-MM-DD HH:MM", badge "Current" su quella corrente)
   + bottone danger "Revoke other sessions" (le altre sessioni spariscono).
7. "About": righe testo textDim: App version 1.0.0 · Tracked artists: 147 · Releases in DB: 312 ·
   Library path: configured via environment variable.

════════════════════════════════════════
4. FLUSSI DA RENDERE CLICCABILI
════════════════════════════════════════
1. /login → (Log in) → / feed
2. Feed: filtri chip + switch Unseen only + search live + Mark all as seen + Load more
3. Card → dettaglio → (Seen automatico) → Back to feed (pallino sparito)
4. Dettaglio: toggle Favorite/Hide/Restore; i 4 bottoni esterni aprono nuova tab (href="#")
5. Navbar → Artists: Ignore toggle, Retry su Unmatched, Add artist modale
6. Navbar → Settings: Save con feedback, scan con spinner, radio tema, validazioni password,
   Revoke other sessions
7. Toggle tema in navbar: switch istantaneo dark/light su OGNI schermata
8. Log out → /login
9. Tutto navigabile anche a 375px di larghezza

════════════════════════════════════════
5. DATI MOCK (usa ESATTAMENTE questi, in inglese)
════════════════════════════════════════
Artisti monitorati (estratto): Radiohead (Artist, ✅ 95), Fred again.. (Artist, ✅ 97),
Beyoncé (Artist, ✅ 98), Bonobo (Album artist, ✅ 91), Khruangbin (Artist, ✅ 90),
James Blake (Featuring, ✅ 88), Four Tet (Contributor, ✅ 86), Floating Points (Manual, ✅ 93),
"Earth, Wind & Fire" (Artist, ✅ 90), "AC/DC" (Artist, ✅ 94), "DJ Koze feat. Ada" (⚠️ Unmatched),
"Various Artists" (Ignored).

Release (campo: titolo — artista display — tuoi artisti coinvolti — tipo — data — stato):
1. "Inertia" — Fred again.. — Fred again.. (Main artist) — Album — 2026-07-31 — unseen, favorite
2. "True Magic" — salute — Fred again.. (Featuring) — Single — 2026-07-25 — unseen
3. "Playing Robots Into Heaven (Deluxe)" — James Blake — James Blake (Main artist) — Album — 2026-07-18 — seen
4. "A La Sala" — Khruangbin — Khruangbin (Main artist) — Album — 2026-07-11 — seen
5. "Midnight Harlem" — Khruangbin & Leon Bridges — Khruangbin (Main artist) — EP — 2026-07-04 — seen
6. "Cowboy Carter Act II" — Beyoncé — Beyoncé (Main artist) — Album — 2026-06-27 — seen
7. "Fragments (Remixes)" — Bonobo — Bonobo (Main artist) — EP — 2026-06-20 — seen, hidden
8. "Overtone" — Nicole Moudaber feat. James Blake — James Blake (Featuring) — Single — 2026-06-13 — unseen
9. "Crush" — Floating Points — Floating Points (Main artist) — Single — 2026-06-06 — seen
10. "Weird Little Birthday (Reissue)" — Happyness — nessuno (scoperta via Radiohead come Contributor) — Album — 2026 — seen
La release #10 ha data parziale "2026": mostrala così. La #7 mostra lo stato Hidden con badge.
Almeno 2 release (#3 e #9) senza copertina → placeholder con icona nota.

════════════════════════════════════════
6. GLOSSARIO STRINGHE (usare letteralmente)
════════════════════════════════════════
New releases · All / Albums / Singles / EPs · Unseen only · Search… · Mark all as seen ·
Load more · No new releases · Try running a scan from Settings · ← Back to feed · Your artists ·
Main artist / Featuring / Contributor · Seen · Favorite · Hide · Hidden · Restore ·
Spotify / YouTube Music / Deezer / Search on Google · Tracked artists · Search artist… ·
All / Active / Ignored · + Add artist · Artist name · Add / Cancel · Unmatched · Retry · Ignore ·
Releases · Discovery · Discover releases from · Weekly featuring scan · Save · Saved ✓ · Scans ·
Scan library now · Check for new releases now · Scan already in progress · Recent scans ·
Notifications · Apprise URLs (one per line) · Send test notification · Notifications are disabled ·
Add at least one Apprise URL · Integrations · Spotify Client ID · Spotify Client Secret ·
MusicBrainz contact email · Appearance · Dark / Light · Security · Current password ·
New password · Repeat new password · Password must be at least 12 characters ·
Passwords do not match · Password updated · Active sessions · Current · Revoke other sessions ·
About · Log in · Log out · Invalid credentials · Toggle theme · Select at least one release type

════════════════════════════════════════
7. NON INCLUDERE
════════════════════════════════════════
- Nessuna registrazione/signup, nessun multi-utente
- Nessun player audio, nessuna riproduzione
- Nessuna chiamata di rete reale: tutto mockato inline
- Niente librerie CSS/JS esterne: HTML+CSS+JS vanilla in un solo file
- Niente testi in italiano: UI 100% inglese

Prima di consegnare: verifica tu stesso che tutti i flussi §4 funzionino cliccando, che entrambi
i temi siano completi su OGNI schermata, che le date siano ISO e che non ci sia testo italiano.
```

---

## Checklist di verifica del prototipo (da fare tu, a mano)

- [ ] Tutti i 9 flussi della sezione 4 del prompt funzionano cliccando.
- [ ] Nessun testo in italiano da nessuna parte; date sempre `YYYY-MM-DD`.
- [ ] Tema scuro di default; toggle istantaneo; tema chiaro completo e leggibile (contrasto ok).
- [ ] Colori identici ai token §11.1 delle specifiche (prova con il contagocce del browser sull'accent: `#1DB954`).
- [ ] Mobile 375px: grid 2 colonne, navbar a icone, impostazioni usabili senza scroll orizzontale.
- [ ] Stati vuoto/loading/errore/hidden visibili e corretti.
- [ ] La release in solo-featuring (#2, #8) mostra "(feat. …)" e il ruolo "Featuring" nel dettaglio.
- [ ] I 4 bottoni esterni nel dettaglio hanno i colori brand giusti.

## Dopo l'approvazione

1. Salva l'artifact in `piano/mockup/`.
2. Se hai cambiato qualcosa rispetto a §11 delle specifiche (layout, label, flussi): aggiorna
   `piano/00-specifiche.md` §11 di conseguenza **prima** di iniziare la fase 07.
3. Nelle fasi 07-09 il prompt dice già al modello di usare `piano/mockup/` come riferimento visivo vincolante.

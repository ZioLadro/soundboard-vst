# Changelog

## v0.6.1 — 2026-11-02

### Correzioni
- **Niente più scatti e buchi occasionali** con la musica del player (YouTube e file) e con il microfono:
  microfono, cuffie e uscita verso il cavo virtuale vanno su schede con clock leggermente diversi, e il buffer
  tra loro prima o poi scartava un pezzo o restava vuoto. Ora la differenza di velocità viene compensata
  ricampionando in modo impercettibile (al massimo ±0,2%) e il buffer resta sempre allo stesso livello.
- Bot Discord: stessa compensazione tra il clock della scheda audio e quello del PC, così i brani lunghi non
  fanno scatti; conversione di frequenza continua quando il motore non è a 48 kHz (prima ogni frame di 20 ms
  veniva ricampionato da solo, con piccole giunture).
- Bot Discord: premere un pad mentre suona il player non taglia più un pezzo di musica (la risincronizzazione
  avviene solo dopo un momento di silenzio). Margine del bot portato da 30 a 40 ms.
- Meno contesa con il thread audio: gli aggiornamenti di avanzamento dei download di YouTube arrivano
  all'interfaccia al massimo 4 volte al secondo, e il thread audio ottiene prima il turno in Python.
- YouTube: i primi aggiornamenti di avanzamento di un download non vanno più persi.

## v0.6.0 — 2026-11-02

### Novità
- **Comandi slash del bot Discord**: `/suona` (con suggerimenti mentre scrivi, cerca in tutta la cartella),
  `/stop`, `/pulsantiera`, `/canale-pulsantiera`, `/entra` (nel canale di chi lo scrive), `/esci`, `/player`,
  `/riproduci` (link o ricerca YouTube), `/volume` e `/aiuto`.
- **Pulsantiera nei messaggi**: `/pulsantiera` pubblica i pad come pulsanti (20 per volta, con i colori dei pad,
  frecce per scorrere pagine e blocchi, «Stop suoni» e aggiorna). Può essere visibile solo a te.
- **Canale dedicato**: `/canale-pulsantiera qui` fa tenere al bot tutti i pad in quel canale, 25 per messaggio,
  più una riga con stop e comandi del player. I messaggi si aggiornano da soli quando cambi i pad.
- I pulsanti continuano a funzionare dopo un riavvio della soundboard, senza ripubblicare nulla.
- **Permessi** in Impostazioni → Bot Discord: chi può suonare e chi può controllare (solo io, un ruolo, chiunque
  nel server). Il proprietario può sempre tutto. Predefinito: suonano tutti, controlli solo il proprietario.
- Link d'invito aggiornato con i comandi e i permessi per scrivere nel canale dedicato: i bot già invitati vanno
  invitati di nuovo.

### Correzioni
- Le impostazioni del bot non cancellano più le chiavi che il dialogo non gestisce.

## v0.5.0 — 2026-11-02

### Novità
- **Controllo remoto da browser**: server web integrato e pagina per telefono con pad (tutte le pagine, colori,
  emoji, immagini), player (stato, avanzamento, comandi, volume, coda, aggiunta di link o ricerche YouTube),
  mixer (volumi e mute) e comandi del bot, più «ferma tutti i suoni».
- Accesso protetto da chiave (nel link al primo accesso, poi in un cookie), rigenerabile; QR code e link nella
  finestra 📱; scheda «Controllo remoto» nelle impostazioni con porta e istruzioni per l'accesso esterno
  (Tailscale consigliato, oppure port forwarding).
- Messaggi d'errore di YouTube più brevi e leggibili.

## v0.4.2 — 2026-11-02

### Correzioni
- YouTube: risolto «Server returned 403 Forbidden». L'audio non viene più letto da ffmpeg direttamente dai server
  di YouTube (che rifiutano queste richieste) ma scaricato da yt-dlp in una cache locale e poi riprodotto.
  Avanzamento del download mostrato nel player; il brano successivo della coda viene scaricato in anticipo;
  cache limitata a 1,5 GB.
- Il bot non smette più di suonare dopo aver premuto OK nelle impostazioni: il riavvio dell'audio ricreava il
  buffer da cui legge il bot. Ora il buffer resta lo stesso, e audio e MIDI si riavviano solo se le loro
  impostazioni sono cambiate.

## v0.4.1 — 2026-11-02

### Correzioni
- Latenza del bot ridotta da circa 1,5 s: il lettore di discord.py non viene più riavviato a ogni suono
  (resta aperto e va in pausa/riprende), all'inizio di ogni suono si scarta l'audio accumulato nel buffer,
  l'encoder Opus usa la modalità «lowdelay». Latenza interna misurata: ~20 ms (trasmissione continua) o ~40 ms.
- Nuova opzione «Bassa latenza: trasmissione continua» (attiva di default) nelle impostazioni del bot.
- I suoni dei pad vengono decodificati in anticipo: anche la prima pressione parte subito.
- Il menu del bot mostra l'ultima latenza interna misurata.

## v0.4.0 — 2026-11-02

### Novità
- **Player**: tab dedicata con coda di file, cartelle, playlist `.m3u`, video e playlist di YouTube e ricerca su
  YouTube; play/pausa, seek, precedente/successivo, ripeti, casuale; coda salvata alla chiusura.
- Canale **Player** nel mixer (con inserti), instradato a Discord (bot o cavo virtuale) e al monitor.
- **Mappa MIDI** dei controlli: volumi e mute dei canali, player, pad della pagina corrente, pagine e bot, con
  «Impara» e preset per **Nektar Impact LX25+**. I CC a valore 0 ora arrivano (servono ai fader).
- **Pitch shifter** a bassa latenza tra gli effetti integrati (quello di pedalboard ha ~1 s di latenza).
- Pad: **nome personalizzato** e **immagine** (ritagliata e velata per leggere il nome).
- Bot: pulsanti rapidi ⏻ / Entra / Esci, scorciatoie da tastiera configurabili e «Segui me» attivabile al volo.

### Correzioni
- Gli inserti gestiscono i plugin che restituiscono blocchi di lunghezza variabile (plugin con latenza).

### Build
- L'eseguibile include ffmpeg, Deno e yt-dlp con il componente EJS; il self-test li avvia per verificarli.

## v0.3.1 — 2026-11-02

### Correzioni
- Se lo stesso bot (stesso token) è usato da un'altra soundboard, il bot non viene più conteso tra le due:
  la seconda soundboard non lo sposta e mostra l'avviso «Bot già in uso» con la spiegazione.
- README: come usare la soundboard in più persone (un bot per ciascuno).

## v0.3.0 — 2026-11-02

### Novità
- Bot Discord integrato: entra nel canale vocale in cui sei, ti segue quando cambi canale ed esce con te,
  e riproduce i suoni premuti (canale Soundboard del mixer, con inserti e fader). Supporta la crittografia
  della voce DAVE (discord.py 2.7).
- Pulsante 🤖 nella barra in alto con stato del bot, entra/esci dal canale, avvio/arresto e invito nel server.
- Opzione per non mandare i suoni anche dal microfono virtuale quando il bot è in canale.
- Impostazioni divise in schede: Audio, MIDI, Bot Discord, Plugin VST3.
- Build: compilazione e verifica dell'eseguibile Windows a ogni push su `main`.

## v0.2.0 — 2026-11-02

### Novità
- Colore per ogni pad: 12 colori pronti o uno a scelta; il pad in riproduzione si illumina.
- Icona emoji per ogni suono, mostrata sul pad e nella libreria (selezione rapida o `Win + .`).
- Controller MIDI: scelta del controller nelle impostazioni, «Impara» per assegnare una nota o un CC
  (con canale) a ogni suono, velocity opzionale come volume. La nota assegnata è mostrata sul pad.
- L'eseguibile include python-rtmidi e il self-test della build verifica che il MIDI sia disponibile.

## v0.1.1 — 2026-11-02

### Correzioni
- Avviso «Possibile eco su Discord» all'avvio dell'audio se l'ingresso registra l'audio del PC
  (CABLE Output, Missaggio stereo), se il monitor è il cavo virtuale o se il cavo è il dispositivo
  di riproduzione predefinito di Windows.
- Al primo avvio non viene più scelto un ingresso loopback come microfono.
- Nelle impostazioni i dispositivi a rischio eco sono segnalati con ⚠.
- README: sezione su come eliminare l'eco.

## v0.1.0 — 2026-11-01

Prima versione.

### Soundboard
- Griglia di pad a pagine (fino a 12 × 12 per pagina, predefinita 6 × 8), pagine rinominabili e riordinabili.
- Libreria dei file con ricerca; drag & drop dalla libreria ai pad, tra pad e dall'esplora risorse.
- Cartella dei suoni predefinita `Musica\Suoni` o personalizzata, osservata per i file nuovi.
- Volume e scorciatoia per ogni suono, rinomina, spostamento nel cestino, «Sovrapponi» e «Stop tutto».
- Ricerca su MyInstants con anteprima solo in cuffia e aggiunta diretta ai pad.

### Audio
- Ingresso da microfono/scheda audio, uscita verso cavo virtuale (VB-Cable) per Discord e altri programmi, uscita monitor separata.
- Mixer a quattro canali (Microfono, Soundboard, Master → Discord, Monitor) con fader, mute e meter.
- Inserti per canale: plugin VST3 (interfaccia grafica o editor parametri) ed effetti integrati; stato salvato.
- Soundboard e Mixer in due tab separate.

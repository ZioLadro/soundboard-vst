# Changelog

## v1.0.0 — 2026-11-03

### Novità
- **ASIO** (Windows): nuovo driver «ASIO» in *Impostazioni → Audio* per schede audio professionali e Voicemeeter.
  Ingressi, uscita verso Discord e cuffie passano da un unico flusso full-duplex sullo stesso dispositivo, su
  coppie di canali a scelta (es. 1-2 verso Discord, 3-4 in cuffia). Si può disattivare (vale al riavvio).
- **Canali delle uscite**: «Uscita verso Discord» e «Monitor» hanno la scelta della coppia di canali, anche con
  WASAPI sulle schede con più uscite; Discord e cuffie possono stare sulla stessa scheda su canali diversi.
- **Ingressi multipli**: «＋ Ingresso» nel mixer aggiunge canali d'ingresso (secondo microfono, strumenti, linee),
  ognuno con dispositivo, canali, inserti, fader, *Anche al bot Discord* e ascolto in cuffia. Si **rinominano**
  (doppio clic sul titolo o **⋯**) e si tolgono; anche il Microfono si può rinominare.
- **Ingressi mono**: per ogni ingresso «Stereo 1-2, 3-4…» o «Mono 1, 2, 3…»; più ingressi mono sulla stessa scheda
  la aprono una volta sola.
- **Pan** su tutti i canali del mixer e su ogni suono (*Personalizza…*), anche nella pagina web.
- **SOLO** sui canali d'ingresso e sulle sorgenti (Soundboard, Sintesi vocale, Player), anche nella pagina web:
  con un canale in solo gli altri tacciono, anche verso Discord.
- **Icona del programma**: fumetto della chat vocale con una doppia croma, per l'eseguibile, la finestra e la barra
  delle applicazioni.
- Pagina web: ingresso, *Anche al bot* e ascolto in cuffia per ogni canale d'ingresso.

### Note
- Serve **sounddevice 0.5.1** o successivo (include PortAudio con ASIO).

## v0.9.1 — 2026-11-03

### Correzioni
- **Rotella del pitch bend** (es. Nektar Impact LX25+): prima veniva ignorata, ora si assegna con «Impara» ai
  parametri degli inserti e ai volumi della mappa MIDI. Usa tutti i 14 bit della rotella (movimenti più fini di un
  CC). Non si assegna ai pad né alle azioni a pulsante. La rotella di modulazione era già assegnabile (è il CC 1).

## v0.9.0 — 2026-11-03

### Novità
- **Categorie dei suoni**: campo «Categoria» in *Personalizza…* (con le categorie esistenti suggerite), anche per
  più suoni insieme dalla libreria. La libreria raggruppa i suoni per categoria; il menu sopra la ricerca mostra una
  categoria, i suoni senza categoria o quelli **con una certa emoji**. «Nuova pagina con…» mette una categoria su
  una pagina di pad. La ricerca (anche `/suona` su Discord) trova i suoni per categoria.
- **Suoni (o sintesi vocale) quando qualcuno si muta o si smuta** nel canale del bot: per persona o per tutti,
  oppure un annuncio a scelta; anche da `/mio-suono` (opzioni `muto` e `smuto`).
- **MIDI sui parametri degli inserti**: pulsante «MIDI» accanto a ogni parametro (effetti integrati e VST3): si
  assegna un potenziometro, un fader o una nota; le finestre dei parametri seguono i valori dal vivo.
- **Ingresso del microfono dal mixer**: scelta del dispositivo direttamente sul canale Microfono (anche dalla
  pagina web).
- **Microfono al bot Discord**: opzione «Anche al bot Discord» sul canale Microfono (anche dalla pagina web).
- **Scala in dB sui meter** del mixer, nel programma e nella pagina web.
- **Icone del player disegnate** invece delle emoji (trasporto, ripeti, casuale, brano in riproduzione, YouTube),
  nel programma e nella pagina web.

## v0.8.1 — 2026-11-03

### Novità
- **Avanzamento e meter sui pad**: mentre un suono suona, il pad mostra una barra di avanzamento in basso e un
  meter verticale a destra (verde → giallo → rosso, con caduta graduale). Anche nella pagina web.
- **Inserti dalla pagina web**: aggiungere effetti integrati o plugin VST3 (tra quelli trovati nelle cartelle),
  toglierli, spostarli, metterli in bypass e regolarne i parametri; il mixer del PC si aggiorna da solo.
- **Mixer della pagina web come quello del programma**: canali a colonne con inserti, fader verticale, meter L/R
  con picco, dB e MUTE, opzioni «Ascolta» del monitor; su telefono i canali scorrono di lato.

### Correzioni
- **Schermi 1920×1080 / 1920×1200 / 2K**: la finestra non poteva essere più stretta di ~1360 px (fino a 1560 con
  nomi dei dispositivi lunghi), più dello spazio disponibile con il ridimensionamento di Windows al 125–150%.
  Ora il minimo è ~820 × 520: percorso della cartella e dispositivi si accorciano con «…» (testo intero nel
  tooltip), il mixer scorre di lato se serve.
- Alla prima apertura la finestra prende una dimensione adatta allo schermo; una posizione salvata su uno schermo
  più grande viene riportata dentro quello attuale.
- Impostazioni: le sezioni (ormai otto) sono in un elenco a sinistra invece delle schede; le finestre delle
  impostazioni e di «Personalizza…» non superano mai lo schermo e scorrono se serve.
- Sugli schermi 2K al 100% il testo è un po' più grande; il testo dei pad cresce con la loro dimensione.

## v0.8.0 — 2026-11-03

### Novità
- **Nuovi suoni da YouTube e da link**: pulsante «Da YouTube o link…» nella tab Soundboard. Accetta un link di
  YouTube (o un testo da cercare), una pagina di MyInstants o un link a un file audio; si può tenere solo un pezzo
  (es. da 0:12 a 0:18). Il suono viene convertito in mp3 nella cartella e messo nel primo pad libero (massimo 10
  minuti).
- **Registro**: nuova tab con tutto quello che succede, con ora, tipo e **chi**: suoni premuti nella finestra, con
  il MIDI, dal telefono o dalla pulsantiera di Discord (con il nome di chi ha premuto), frasi della sintesi vocale,
  brani aggiunti alla playlist e da chi, comandi Discord, entrate e uscite dal canale vocale, permessi negati, nuovi
  suoni ed errori. Filtri per tipo, ricerca, e un file al giorno nella cartella dati (tenuto 14 giorni).
- **`/aggiungi-suono`** su Discord: carica un file (audio o video) oppure un link (YouTube, MyInstants, file audio,
  o una ricerca), con nome, inizio e fine facoltativi; il bot risponde con la pagina e il pad dove l'ha messo.
- **Permessi del bot più precisi** (nuova scheda Impostazioni → Permessi Discord): cinque gruppi di comandi
  (Suonare, Sintesi vocale, Musica, Controllo del bot, Gestione), ognuno aperto a tutti oppure a **ruoli e utenti
  scelti** da un elenco (ruoli dei server e persone già viste dal bot, o per ID); **utenti bloccati**; opzione
  «gli amministratori del server possono tutto». Le impostazioni delle versioni precedenti vengono convertite.
- **Suoni di entrata e uscita** (Impostazioni → Entrate e uscite): un suono quando una persona entra o esce dal
  canale vocale del bot, per persona o per tutti, con un tempo minimo tra due ripetizioni; in alternativa un
  annuncio con la sintesi vocale («{nome} è entrato»). Ognuno può scegliere i propri con **`/mio-suono`**.
- **Canale «Sintesi vocale» nel mixer**: le frasi (barra 💬, pad con frasi, `/parla`, annunci) hanno un canale
  tutto loro, con fader, mute, inserti ed effetti, separato dai suoni; nel monitor si può scegliere se sentirlo
  («Voce»). Anche nella mappa MIDI e in `/volume`.

## v0.7.2 — 2026-11-02

### Novità
- **Stato del bot su Discord**: mentre il player suona, il bot mostra «Ascolta *titolo del brano*» (anche per i
  video di YouTube); in pausa o fermo lo stato sparisce. Si disattiva in Impostazioni → Bot Discord. Discord non
  permette ai bot la «Rich Presence» completa (copertina, barra di avanzamento, pulsanti): un bot può mostrare
  solo una riga di testo, e cambiarla al massimo ogni 15 secondi circa.

## v0.7.1 — 2026-11-02

### Novità
- **Inizio, fine e dissolvenze per ogni pad**: in *Personalizza…* c'è la forma d'onda del suono; si trascinano le
  linee per scegliere da dove parte e dove finisce, e i quadratini in alto per la dissolvenza in entrata e in
  uscita (curva morbida). I tempi si possono anche scrivere in secondi; «▶ Ascolta» prova il risultato in cuffia.
  Vale anche per le frasi della sintesi vocale. Quando il taglio cade in mezzo al suono si applica da sola una
  micro-dissolvenza di 3 ms che evita il «clic». Il suono tagliato viene calcolato una volta e ricordato.

### Correzioni
- **Pulsantiera nel canale dedicato che smetteva di aggiornarsi**: se all'avvio del bot il primo aggiornamento
  falliva (rete non ancora pronta, errore temporaneo di Discord) l'aggiornamento automatico si fermava per sempre;
  una richiesta rimasta appesa (es. dopo lo standby del PC) poteva bloccarlo fino a 5 minuti, anche il pulsante ↻.
  Ora non si ferma mai: ogni aggiornamento ha un tempo massimo, dopo un errore riprova a intervalli crescenti e
  ripubblica tutto, e riparte da solo quando Discord si riconnette o premendo ↻.
- Il canale dedicato viene trovato anche se non è nella memoria del bot, e se è un thread archiviato lo riapre.
  Se il canale è stato eliminato, il bot lo dimentica e lo dice.
- Se una ripubblicazione si interrompe a metà, i messaggi già inviati vengono sostituiti e non restano doppioni.
- Il menu 🤖 mostra lo stato della pulsantiera («controllata alle…» o l'errore) e ha «Aggiorna ora la pulsantiera
  nel canale»; un errore viene mostrato una volta sola e c'è un messaggio quando torna a funzionare.

## v0.7.0 — 2026-11-02

### Novità
- **Sintesi vocale (text to speech)**: nella barra 💬 sotto i pad scrivi una frase e premi Invio: la soundboard la
  dice, sul canale Soundboard del mixer (quindi a Discord tramite cavo virtuale o bot, e in cuffia).
- **Frasi sui pad**: tasto destro su un pad vuoto → *Nuova frase…* (o «Salva su un pad» dalla barra). Le frasi si
  comportano come gli altri suoni: nome, colore, emoji, immagine, volume, scorciatoia, nota MIDI, spostamento tra
  pad e pagine, libreria, telefono, pulsantiera e `/suona` su Discord. Ogni frase può avere la sua voce.
- Due motori: **voci neurali Microsoft** (online, molto naturali, tante lingue; predefinita Diego, italiano) e
  **voci del sistema** (offline: SAPI su Windows, `say` su macOS, espeak-ng su Linux).
- Nuova scheda **Impostazioni → Sintesi vocale**: motore, voce predefinita, velocità, tono e prova in cuffia.
- Le frasi vengono create una volta sola e tenute in una cache (fino a 200 MB): la seconda volta partono subito,
  e quelle sui pad vengono preparate all'avvio.
- Discord: comando **`/parla testo:`** (stesso permesso di «Chi può suonare»).
- Telefono: campo «Scrivi una frase da far dire…» nella scheda Pad.

## v0.6.2 — 2026-11-02

### Correzioni
- **Il bot Discord era muto nella build 0.6.1**: si accendeva verde ma nessuno sentiva niente. La build aveva preso
  davey 0.2.0 (la libreria della crittografia vocale DAVE, uscita poco prima), che cambia il modo di passare alle
  nuove chiavi; discord.py 2.7.1 non lo supporta ancora, quindi l'audio partiva cifrato senza una chiave valida.
  davey è ora fissato alla 0.1.x.
- La build fallisce se include una combinazione di davey e discord.py incompatibile, e il bot mostra un avviso
  invece di restare muto senza spiegazioni.

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

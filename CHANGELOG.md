# Changelog

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

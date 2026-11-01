# Changelog

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

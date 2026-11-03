"""Impostazioni: dispositivi audio e cartelle dei plugin VST3."""

from __future__ import annotations

import sys

from PySide6.QtCore import QRegularExpression, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QSlider, QAbstractItemView, QHeaderView, QKeySequenceEdit, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .. import discord_bot, midi, midi_map, tts
from ..audio import devices
from ..config import Config, default_vst3_dirs
from ..discord_bot import normalize_greetings
from ..discord_commands import normalize_permissions
from .discord_settings import GreetingsEditor, PermissionsEditor
from .screen import SideTabs, fit_to_screen
from . import theme
from .phrase_dialog import VoiceCombo

NONE_LABEL = "— nessuno —"


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None, midi_bridge=None, preview_tts=None,
                 directory=None, sounds=None):
        """``directory()``: ruoli e utenti visti dal bot ({"roles": [...], "users": {id: nome}});
        ``sounds``: [(chiave, nome)] dei suoni da scegliere per entrate e uscite."""
        super().__init__(parent)
        self._bridge = midi_bridge
        self._preview_tts = preview_tts          # (testo, impostazioni) -> anteprima in cuffia
        self._learning_target: str | None = None
        self._map: dict[str, dict] = {k: dict(v) for k, v in config.data.get("midi_map", {}).items()}
        self.setWindowTitle("Impostazioni")
        self.setMinimumSize(560, 420)
        self.config = config
        a = config.data["audio"]

        # Audio -------------------------------------------------------------------
        self.host_api = QComboBox()
        self.input = QComboBox()
        self.virtual = QComboBox()
        self.monitor = QComboBox()
        self.virtual_ch = QComboBox()
        self.monitor_ch = QComboBox()
        for ch in (self.virtual_ch, self.monitor_ch):
            ch.setToolTip("Coppia di canali del dispositivo (per le schede con più uscite, es. ASIO)")
            ch.setMinimumContentsLength(6)
        self._outs: dict[str, devices.Device] = {}
        self._ch_choice = {self.virtual_ch: int(a.get("virtual_channel", 0) or 0),
                           self.monitor_ch: int(a.get("monitor_channel", 0) or 0)}
        for ch in (self.virtual_ch, self.monitor_ch):
            ch.activated.connect(lambda _i, c=ch: self._ch_choice.__setitem__(c, int(c.currentData() or 0)))
        self.virtual.currentIndexChanged.connect(
            lambda: self._fill_channels(self.virtual, self.virtual_ch, a.get("virtual_channel", 0)))
        self.monitor.currentIndexChanged.connect(
            lambda: self._fill_channels(self.monitor, self.monitor_ch, a.get("monitor_channel", 0)))
        self.asio = QCheckBox("Driver ASIO (schede audio professionali, Voicemeeter…): vale dal prossimo avvio")
        self.asio.setChecked(bool(a.get("asio", True)))
        self.asio.setToolTip("Aggiunge «ASIO» all'elenco dei driver. Se un driver ASIO dà problemi\n"
                             "all'avvio del programma, togli la spunta e riavvia.")
        self.asio_hint = QLabel(
            "<b>ASIO</b>: si usa un solo dispositivo per tutto. Scegli lo stesso dispositivo per Discord e "
            "cuffie con <b>coppie di canali diverse</b> (es. 1-2 verso Discord, 3-4 in cuffia); gli ingressi "
            "(anche mono, uno per canale) si scelgono nel mixer. La frequenza deve essere una di quelle "
            "supportate dal driver.")
        self.asio_hint.setWordWrap(True)
        self.asio_hint.setTextFormat(Qt.TextFormat.RichText)
        self.asio_hint.setStyleSheet(f"color: {theme.ACCENT};")
        self.asio_hint.setVisible(False)
        self.sample_rate = QComboBox()
        for sr in (44100, 48000, 96000):
            self.sample_rate.addItem(f"{sr} Hz", sr)
        self.sample_rate.setCurrentIndex(max(0, self.sample_rate.findData(a.get("sample_rate", 48000))))
        self.block = QComboBox()
        for b in (128, 256, 512, 1024, 2048):
            ms = b / 48000 * 1000
            self.block.addItem(f"{b} campioni (~{ms:.0f} ms)", b)
        self.block.setCurrentIndex(max(0, self.block.findData(a.get("block_size", 512))))

        refresh = QPushButton("Aggiorna elenco")
        refresh.clicked.connect(self._fill_devices)
        self.host_api.currentIndexChanged.connect(self._fill_devices)

        hint = QLabel(
            "Per mandare l'audio a Discord installa un cavo virtuale (es. <b>VB-Audio Virtual Cable</b>), "
            "scegli <b>CABLE Input</b> come «Uscita verso Discord» e in Discord imposta "
            "<b>CABLE Output</b> come dispositivo di input. Su Windows è consigliato WASAPI."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet(f"color: {theme.MUTED};")
        vb_btn = QPushButton("Scarica VB-Cable (gratuito)…")
        vb_btn.setToolTip("Apre la pagina ufficiale di VB-Audio nel browser")
        vb_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://vb-audio.com/Cable/")))

        audio_box = QGroupBox("Audio")
        form = QFormLayout(audio_box)
        api_row = QHBoxLayout()
        api_row.addWidget(self.host_api, 1)
        api_row.addWidget(refresh)
        form.addRow("Driver (host API)", api_row)
        form.addRow("Ingresso del Microfono", self.input)

        def with_channels(dev: QComboBox, ch: QComboBox) -> QHBoxLayout:
            row = QHBoxLayout()
            row.addWidget(dev, 1)
            row.addWidget(QLabel("canali"))
            row.addWidget(ch)
            return row

        form.addRow("Uscita verso Discord", with_channels(self.virtual, self.virtual_ch))
        form.addRow("Monitor (cuffie)", with_channels(self.monitor, self.monitor_ch))
        form.addRow("Frequenza", self.sample_rate)
        form.addRow("Buffer", self.block)
        form.addRow(self.asio_hint)
        form.addRow(hint)
        inputs_hint = QLabel("Altri ingressi (secondo microfono, strumenti, linee; mono o stereo) si aggiungono "
                             "nella tab <b>Mixer</b> con «＋ Ingresso».")
        inputs_hint.setWordWrap(True)
        inputs_hint.setTextFormat(Qt.TextFormat.RichText)
        inputs_hint.setStyleSheet(f"color: {theme.MUTED};")
        form.addRow(inputs_hint)
        if sys.platform == "win32":
            form.addRow(self.asio)
        vb_row = QHBoxLayout()
        vb_row.addWidget(vb_btn)
        vb_row.addStretch(1)
        form.addRow(vb_row)

        if not devices.audio_available():
            warn = QLabel("PortAudio non disponibile: impossibile elencare i dispositivi.")
            warn.setStyleSheet(f"color: {theme.DANGER};")
            form.addRow(warn)

        # MIDI ---------------------------------------------------------------------
        midi_box = QGroupBox("MIDI")
        mform = QFormLayout(midi_box)
        self.midi_port = QComboBox()
        midi_refresh = QPushButton("Aggiorna")
        midi_refresh.clicked.connect(self._fill_midi)
        mrow = QHBoxLayout()
        mrow.addWidget(self.midi_port, 1)
        mrow.addWidget(midi_refresh)
        mform.addRow("Controller", mrow)
        self.midi_velocity = QCheckBox("La forza con cui premi (velocity) regola il volume")
        self.midi_velocity.setChecked(bool(config.data["midi"].get("velocity", False)))
        mform.addRow(self.midi_velocity)
        midi_hint = QLabel("Assegna una nota a un suono: tasto destro sul pad → Personalizza… → Impara.")
        midi_hint.setWordWrap(True)
        midi_hint.setStyleSheet(f"color: {theme.MUTED};")
        mform.addRow(midi_hint)

        # Mappa MIDI dei controlli
        map_title = QLabel("MAPPA DEI CONTROLLI")
        map_title.setObjectName("sectionTitle")
        mform.addRow(map_title)
        self.preset = QComboBox()
        self.preset.addItem("Scegli un preset…", "")
        for name in midi_map.PRESETS:
            self.preset.addItem(name, name)
        apply_preset = QPushButton("Applica")
        apply_preset.setToolTip("Aggiunge le assegnazioni del preset (sostituisce quelle sugli stessi controlli)")
        apply_preset.clicked.connect(self._apply_preset)
        clear_map = QPushButton("Cancella tutto")
        clear_map.clicked.connect(self._clear_map)
        prow = QHBoxLayout()
        prow.addWidget(self.preset, 1)
        prow.addWidget(apply_preset)
        prow.addWidget(clear_map)
        mform.addRow("Preset", prow)
        self.map_table = QTableWidget(len(midi_map.TARGETS), 4)
        self.map_table.setHorizontalHeaderLabels(["Funzione", "Controllo MIDI", "", ""])
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.map_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.map_table.setMinimumHeight(260)
        hdr = self.map_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._learn_buttons: dict[str, QPushButton] = {}
        for row, t in enumerate(midi_map.TARGETS):
            name = QTableWidgetItem(f"{t.group} › {t.label}")
            name.setToolTip("Potenziometro o fader (CC)" if t.kind == "continuous" else "Pulsante, pad o nota")
            self.map_table.setItem(row, 0, name)
            self.map_table.setItem(row, 1, QTableWidgetItem(""))
            learn = QPushButton("Impara")
            learn.clicked.connect(lambda _=False, tid=t.id: self._toggle_map_learn(tid))
            clear = QPushButton("✕")
            clear.setToolTip("Togli l'assegnazione")
            clear.clicked.connect(lambda _=False, tid=t.id: self._set_map(tid, None))
            self.map_table.setCellWidget(row, 2, learn)
            self.map_table.setCellWidget(row, 3, clear)
            self._learn_buttons[t.id] = learn
        mform.addRow(self.map_table)
        self.map_hint = QLabel("Premi «Impara» e muovi il controllo o premi il tasto sul controller. "
                               "Le assegnazioni della mappa hanno la precedenza sulle note dei singoli suoni.")
        self.map_hint.setWordWrap(True)
        self.map_hint.setStyleSheet(f"color: {theme.MUTED};")
        mform.addRow(self.map_hint)
        self._refresh_map()
        if not midi.available():
            warn = QLabel(f"MIDI non disponibile (manca python-rtmidi): {midi.unavailable_reason()}")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {theme.DANGER};")
            mform.addRow(warn)
            self.midi_port.setEnabled(False)
            midi_refresh.setEnabled(False)

        # Bot Discord -------------------------------------------------------------------
        dc = config.data["discord"]
        bot_box = QGroupBox("Bot Discord")
        bform = QFormLayout(bot_box)
        self.bot_token = QLineEdit(dc.get("token", ""))
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.bot_token.setPlaceholderText("Token del bot dal portale sviluppatori")
        show = QPushButton("Mostra")
        show.setCheckable(True)
        show.toggled.connect(lambda on: self.bot_token.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        trow = QHBoxLayout()
        trow.addWidget(self.bot_token, 1)
        trow.addWidget(show)
        bform.addRow("Token", trow)
        self.bot_owner = QLineEdit(str(dc.get("owner_id", "")))
        self.bot_owner.setPlaceholderText("es. 123456789012345678")
        self.bot_owner.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,20}")))
        bform.addRow("Il tuo ID utente", self.bot_owner)
        self.bot_autostart = QCheckBox("Avvia il bot all'apertura della soundboard")
        self.bot_autostart.setChecked(bool(dc.get("autostart", False)))
        self.bot_follow = QCheckBox("Segui me: entra, cambia ed esci dai canali vocali insieme a me")
        self.bot_follow.setChecked(bool(dc.get("follow", True)))
        self.bot_exclusive = QCheckBox("Con il bot in canale, i suoni non passano dal microfono virtuale")
        self.bot_exclusive.setToolTip("Evita che il canale senta i suoni due volte (dal bot e dal tuo microfono)")
        self.bot_exclusive.setChecked(bool(dc.get("exclusive", True)))
        self.bot_continuous = QCheckBox("Bassa latenza: trasmissione continua")
        self.bot_continuous.setToolTip(
            "Il bot resta sempre in trasmissione (silenzio quando non suona niente): i suoni partono prima,\n"
            "ma su Discord il bot può risultare sempre «attivo». Senza, va in pausa dopo mezzo secondo di silenzio.")
        self.bot_continuous.setChecked(bool(dc.get("continuous", True)))
        self.bot_presence = QCheckBox("Mostra nello stato del bot cosa suona il player («Ascolta …»)")
        self.bot_presence.setToolTip("Mentre il player suona, il bot su Discord mostra il titolo del brano.\n"
                                     "Discord permette di cambiarlo al massimo ogni 15 secondi circa.")
        self.bot_presence.setChecked(bool(dc.get("presence", True)))
        sc = dc.get("shortcuts", {})
        self.bot_keys: dict[str, QKeySequenceEdit] = {}
        for name, label in (("toggle", "Avvia / ferma bot"), ("join", "Entra nel mio canale"),
                            ("leave", "Esci dal canale"), ("follow", "Segui me sì/no")):
            edit = QKeySequenceEdit(QKeySequence(sc.get(name, "")))
            self.bot_keys[name] = edit
            krow = QHBoxLayout()
            krow.addWidget(edit, 1)
            kclear = QPushButton("Cancella")
            kclear.clicked.connect(edit.clear)
            krow.addWidget(kclear)
            bform.addRow(f"Tasto: {label}", krow)
        for cb in (self.bot_autostart, self.bot_follow, self.bot_exclusive, self.bot_continuous, self.bot_presence):
            bform.addRow(cb)

        cm = dc.get("commands", {})
        self.cmd_enabled = QCheckBox("Comandi da Discord: /suona, /pulsantiera, /canale-pulsantiera, /player…")
        self.cmd_enabled.setChecked(bool(cm.get("enabled", True)))
        bform.addRow(self.cmd_enabled)
        cmd_hint = QLabel(
            "Scrivi <b>/pulsantiera</b> in un canale di testo per avere i pad come pulsanti, oppure "
            "<b>/canale-pulsantiera</b> in un canale dedicato: il bot ci tiene tutti i pad, aggiornati da soli. "
            "Chi può usare cosa si sceglie nella scheda <b>Permessi Discord</b>. Se il bot era già nel server "
            "prima della 0.6, invitalo di nuovo con il pulsante qui sotto per abilitare i comandi.")
        cmd_hint.setWordWrap(True)
        cmd_hint.setTextFormat(Qt.TextFormat.RichText)
        cmd_hint.setStyleSheet(f"color: {theme.MUTED};")
        bform.addRow(cmd_hint)
        portal = QPushButton("Crea il bot…")
        portal.setToolTip("Apre il portale sviluppatori di Discord")
        portal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.com/developers/applications")))
        invite = QPushButton("Invita il bot nel server…")
        invite.clicked.connect(self._invite_bot)
        brow = QHBoxLayout()
        brow.addWidget(portal)
        brow.addWidget(invite)
        brow.addStretch(1)
        bform.addRow(brow)
        bot_hint = QLabel(
            "1. Crea un'applicazione nel portale, sezione <b>Bot</b> → <b>Reset Token</b> e incollalo qui. "
            "2. Invita il bot nel tuo server. 3. In Discord attiva <i>Impostazioni → Avanzate → Modalità "
            "sviluppatore</i>, poi tasto destro sul tuo nome → <b>Copia ID utente</b>. "
            "Il token è salvato in chiaro nelle impostazioni del programma: non condividerlo.")
        bot_hint.setWordWrap(True)
        bot_hint.setTextFormat(Qt.TextFormat.RichText)
        bot_hint.setStyleSheet(f"color: {theme.MUTED};")
        bform.addRow(bot_hint)
        if not discord_bot.available():
            warn = QLabel(f"Bot non disponibile (manca discord.py): {discord_bot.unavailable_reason()}")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {theme.DANGER};")
            bform.addRow(warn)

        # VST3 ---------------------------------------------------------------------
        vst_box = QGroupBox("Cartelle plugin VST3")
        self.vst_dirs = QListWidget()
        self.vst_dirs.setObjectName("inserts")
        self.vst_dirs.addItems(config.vst3_dirs)
        self.vst_dirs.setMaximumHeight(110)
        add = QPushButton("Aggiungi…")
        add.clicked.connect(self._add_dir)
        rm = QPushButton("Rimuovi")
        rm.clicked.connect(lambda: self.vst_dirs.takeItem(self.vst_dirs.currentRow()))
        reset = QPushButton("Predefinite")
        reset.clicked.connect(self._reset_dirs)
        btns = QVBoxLayout()
        for b in (add, rm, reset):
            btns.addWidget(b)
        btns.addStretch(1)
        row = QHBoxLayout(vst_box)
        row.addWidget(self.vst_dirs, 1)
        row.addLayout(btns)

        # Controllo remoto ------------------------------------------------------------------
        rc = config.data["remote"]
        remote_box = QGroupBox("Controllo remoto")
        rform = QFormLayout(remote_box)
        self.remote_enabled = QCheckBox("Attiva il controllo da browser (telefono, tablet, altro PC)")
        self.remote_enabled.setChecked(bool(rc.get("enabled", False)))
        rform.addRow(self.remote_enabled)
        self.remote_port = QSpinBox()
        self.remote_port.setRange(1024, 65535)
        self.remote_port.setValue(int(rc.get("port", 8765)))
        rform.addRow("Porta", self.remote_port)
        self._remote_token = rc.get("token", "")
        self.remote_token_label = QLabel()
        self.remote_token_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        new_key = QPushButton("Nuova chiave")
        new_key.setToolTip("Genera una nuova chiave: i link vecchi smettono di funzionare")
        new_key.clicked.connect(self._new_remote_token)
        krow = QHBoxLayout()
        krow.addWidget(self.remote_token_label, 1)
        krow.addWidget(new_key)
        rform.addRow("Chiave di accesso", krow)
        remote_hint = QLabel(
            "Dopo aver salvato, il pulsante 📱 in alto mostra il link e il QR code da aprire sul telefono. "
            "La prima volta Windows può chiedere il permesso per la rete: consenti l'accesso sulle reti private.<br><br>"
            "<b>Dall'esterno di casa</b>: il modo consigliato è <b>Tailscale</b> (gratuito): installalo sul PC e sul "
            "telefono con lo stesso account e usa il link «Tailscale», che funziona da ovunque ed è cifrato, senza aprire "
            "porte sul router. In alternativa puoi inoltrare la porta sul router (port forwarding) e usare il tuo IP "
            "pubblico: funziona, ma il collegamento non è cifrato e la pagina è esposta su Internet, protetta solo dalla chiave.")
        remote_hint.setWordWrap(True)
        remote_hint.setTextFormat(Qt.TextFormat.RichText)
        remote_hint.setStyleSheet(f"color: {theme.MUTED};")
        rform.addRow(remote_hint)
        self._show_remote_token()

        # Sintesi vocale -------------------------------------------------------------------
        tc = config.data.get("tts", {})
        tts_box = QGroupBox("Sintesi vocale")
        tform = QFormLayout(tts_box)
        self.tts_engine = QComboBox()
        for value, label in tts.ENGINE_LABELS.items():
            self.tts_engine.addItem(label, value)
        self.tts_engine.setCurrentIndex(max(0, self.tts_engine.findData(tc.get("engine", tts.ENGINE_EDGE))))
        tform.addRow("Motore", self.tts_engine)
        self._tts_voices = {tts.ENGINE_EDGE: tc.get("edge_voice") or tts.DEFAULT_EDGE_VOICE,
                            tts.ENGINE_SYSTEM: tc.get("system_voice", "")}
        engine = self.tts_engine.currentData()
        self.tts_voice = VoiceCombo([engine], (engine, self._tts_voices[engine]),
                                    default_item="" if engine == tts.ENGINE_EDGE else "Voce predefinita del sistema")
        voice_refresh = QPushButton("Aggiorna")
        voice_refresh.setToolTip("Ricarica l'elenco delle voci")
        voice_refresh.clicked.connect(self.tts_voice.refresh)
        vrow = QHBoxLayout()
        vrow.addWidget(self.tts_voice, 1)
        vrow.addWidget(voice_refresh)
        tform.addRow("Voce predefinita", vrow)
        self.tts_engine.currentIndexChanged.connect(self._on_tts_engine)
        self.tts_rate, rate_row = self._tts_slider(-50, 100, int(tc.get("rate", 0)), "{:+d}%")
        tform.addRow("Velocità", rate_row)
        self.tts_pitch, pitch_row = self._tts_slider(-50, 50, int(tc.get("pitch", 0)), "{:+d} Hz")
        tform.addRow("Tono", pitch_row)
        self.tts_test = QLineEdit("Ciao! Questa è la voce della soundboard.")
        test_btn = QPushButton("▶  Ascolta in cuffia")
        test_btn.clicked.connect(self._test_tts)
        test_btn.setEnabled(preview_tts is not None)
        trow2 = QHBoxLayout()
        trow2.addWidget(self.tts_test, 1)
        trow2.addWidget(test_btn)
        tform.addRow("Prova", trow2)
        self.tts_status = QLabel()
        self.tts_status.setWordWrap(True)
        self.tts_status.setStyleSheet(f"color: {theme.DANGER};")
        tform.addRow(self.tts_status)
        tts_hint = QLabel(
            "Scrivi nella barra 💬 sotto i pad e premi Invio per far parlare la soundboard, oppure crea pad con "
            "frasi fisse (tasto destro su un pad vuoto → <b>Nuova frase…</b>): funzionano come gli altri suoni, "
            "con scorciatoie, note MIDI, telefono e Discord (<b>/parla</b>).<br><br>"
            "<b>Voci neurali Microsoft</b>: molto naturali, tante lingue; servono Internet e usano un servizio "
            "non ufficiale, che potrebbe cambiare. <b>Voci del sistema</b>: offline; su Windows sono quelle "
            "installate (es. «Microsoft Elsa» per l'italiano). Ogni frase viene creata una volta e poi tenuta in "
            "una cache, così la seconda volta parte subito.")
        tts_hint.setWordWrap(True)
        tts_hint.setTextFormat(Qt.TextFormat.RichText)
        tts_hint.setStyleSheet(f"color: {theme.MUTED};")
        tform.addRow(tts_hint)
        self._on_tts_engine()

        # Permessi Discord ed entrate/uscite --------------------------------------------------------
        directory = directory() if callable(directory) else (directory or {})
        directory = {"roles": list(directory.get("roles", [])),
                     "users": {**dc.get("known_users", {}), **directory.get("users", {})}}
        self.perm_editor = PermissionsEditor(normalize_permissions(dc.get("permissions"), dc.get("commands")),
                                             directory)
        perm_box = QGroupBox("Permessi Discord")
        QVBoxLayout(perm_box).addWidget(self.perm_editor)
        self.greet_editor = GreetingsEditor(normalize_greetings(dc.get("greetings")), directory, sounds or [])
        greet_box = QGroupBox("Entrate e uscite")
        QVBoxLayout(greet_box).addWidget(self.greet_editor)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        self.tabs = SideTabs()                         # 8 sezioni: elenco a sinistra invece delle schede
        for box, title in ((audio_box, "Audio"), (midi_box, "MIDI"), (bot_box, "Bot Discord"),
                           (vst_box, "Plugin VST3"), (remote_box, "Controllo remoto"),
                           (tts_box, "Sintesi vocale"), (perm_box, "Permessi Discord"),
                           (greet_box, "Entrate e uscite")):
            page = QWidget()
            pl = QVBoxLayout(page)
            box.setTitle("")
            pl.addWidget(box)
            pl.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(buttons)
        fit_to_screen(self, 940, 720)

        self._fill_host_apis()
        self._fill_midi()

    def _fill_midi(self) -> None:
        current = self.midi_port.currentData() if self.midi_port.count() else \
            self.config.data["midi"].get("input", "")
        self.midi_port.clear()
        self.midi_port.addItem(NONE_LABEL, "")
        ports = midi.MidiInput.ports()
        for name in ports:
            self.midi_port.addItem(name, name)
        if current and current not in ports:
            self.midi_port.addItem(f"{current} (non collegato)", current)
        self.midi_port.setCurrentIndex(max(0, self.midi_port.findData(current)))

    # Dispositivi ----------------------------------------------------------------
    def _fill_host_apis(self) -> None:
        apis = devices.host_apis()
        self.host_api.blockSignals(True)
        self.host_api.clear()
        self.host_api.addItems(apis)
        current = self.config.data["audio"].get("host_api") or devices.default_host_api()
        if current in apis:
            self.host_api.setCurrentText(current)
        self.host_api.blockSignals(False)
        self._fill_devices()

    def _fill_devices(self) -> None:
        api = self.host_api.currentText()
        a = self.config.data["audio"]
        ins = devices.inputs(api)
        outs = devices.outputs(api)

        def fill(combo: QComboBox, items, selected: str, mark_virtual=False, mark_loopback=False):
            prev = combo.currentData() if combo.count() else None
            combo.clear()
            combo.addItem(NONE_LABEL, "")
            for d in items:
                label = d.name
                if mark_virtual and d.looks_virtual:
                    label += "   ★ cavo virtuale"
                elif mark_loopback and d.looks_loopback:
                    label += "   ⚠ registra l'audio del PC (eco)"
                elif not mark_virtual and not mark_loopback and d.looks_virtual:
                    label += "   ⚠ cavo virtuale (eco)"
                combo.addItem(label, d.name)
            target = prev if prev else selected
            idx = combo.findData(target)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        asio = devices.is_asio(api)
        self._outs = {d.name: d for d in outs}
        fill(self.input, ins, a.get("input_device", ""), mark_loopback=not asio)
        fill(self.virtual, outs, a.get("virtual_output", ""), mark_virtual=not asio)
        fill(self.monitor, outs, a.get("monitor_output", ""))
        if not self.virtual.currentData() and not asio:
            guess = devices.guess_virtual_output(api)
            if guess:
                self.virtual.setCurrentIndex(self.virtual.findData(guess.name))
        self.asio_hint.setVisible(asio)
        self._fill_channels(self.virtual, self.virtual_ch, a.get("virtual_channel", 0))
        self._fill_channels(self.monitor, self.monitor_ch, a.get("monitor_channel", 0))

    def _fill_channels(self, dev_combo: QComboBox, ch_combo: QComboBox, saved: int = 0) -> None:
        """Coppie di canali del dispositivo scelto; resta la scelta fatta (o salvata) se c'è ancora."""
        dev = self._outs.get(dev_combo.currentData() or "")
        ch_combo.blockSignals(True)
        ch_combo.clear()
        pairs = devices.channel_pairs(dev.max_out) if dev else [(0, "1-2")]
        for first, label in pairs:
            ch_combo.addItem(label, first)
        ch_combo.setCurrentIndex(max(0, ch_combo.findData(self._ch_choice.get(ch_combo, 0))))
        ch_combo.blockSignals(False)
        ch_combo.setEnabled(dev is not None and len(pairs) > 1)

    # VST3 --------------------------------------------------------------------------
    def _add_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Cartella plugin VST3")
        if d:
            self.vst_dirs.addItem(d)

    def _reset_dirs(self) -> None:
        self.vst_dirs.clear()
        self.vst_dirs.addItems(default_vst3_dirs())

    def _invite_bot(self) -> None:
        app_id = discord_bot.application_id_from_token(self.bot_token.text())
        if app_id is None:
            QMessageBox.information(self, "Invita il bot", "Incolla prima il token del bot.")
            return
        QDesktopServices.openUrl(QUrl(discord_bot.invite_url(app_id)))

    # Mappa MIDI ---------------------------------------------------------------------------
    @property
    def learning(self) -> bool:
        return self._learning_target is not None

    def _refresh_map(self) -> None:
        for row, t in enumerate(midi_map.TARGETS):
            b = self._map.get(t.id)
            self.map_table.item(row, 1).setText(midi.binding_label(b) if b else "—")
            self._learn_buttons[t.id].setText("Annulla" if t.id == self._learning_target else "Impara")

    def _set_map(self, tid: str, binding: dict | None) -> None:
        midi_map.assign(self._map, tid, binding)
        self._refresh_map()

    def _apply_preset(self) -> None:
        name = self.preset.currentData()
        if not name:
            return
        for tid, binding in midi_map.PRESETS[name].items():
            midi_map.assign(self._map, tid, binding)
        self._refresh_map()
        self.map_hint.setText(f"Preset «{name}» applicato. I tasti di trasporto della tastiera vanno "
                              "assegnati con «Impara».")

    def _clear_map(self) -> None:
        self._map.clear()
        self._refresh_map()

    def _toggle_map_learn(self, tid: str) -> None:
        if self._bridge is None or not midi.available():
            QMessageBox.information(self, "MIDI", "MIDI non disponibile.")
            return
        if self._learning_target == tid:
            self._stop_map_learn()
            return
        if not self.config.data["midi"].get("input"):
            QMessageBox.information(self, "MIDI", "Scegli e salva prima un controller MIDI (poi riapri le impostazioni).")
            return
        self._stop_map_learn()
        self._learning_target = tid
        self._bridge.event.connect(self._on_map_midi)
        self._refresh_map()

    def _stop_map_learn(self) -> None:
        if self._learning_target is not None and self._bridge is not None:
            try:
                self._bridge.event.disconnect(self._on_map_midi)
            except (RuntimeError, TypeError):
                pass
        self._learning_target = None
        self._refresh_map()

    def _on_map_midi(self, ev) -> None:
        tid = self._learning_target
        target = midi_map.TARGETS_BY_ID.get(tid) if tid else None
        if target is None:
            return
        if target.kind == "continuous" and not ev.continuous:
            self.map_hint.setText("Per un volume serve un potenziometro, un fader o una rotella, non una nota.")
            return
        if target.kind == "button" and ev.kind == "pitch":
            return   # la rotella del pitch bend non è un pulsante
        if target.kind == "button" and ev.kind == "cc" and not ev.pressed:
            return   # rilascio del pulsante
        self._learning_target = None
        try:
            self._bridge.event.disconnect(self._on_map_midi)
        except (RuntimeError, TypeError):
            pass
        self._set_map(tid, ev.binding())

    def done(self, result: int) -> None:
        self._stop_map_learn()
        super().done(result)

    def _show_remote_token(self) -> None:
        t = self._remote_token
        self.remote_token_label.setText(f"{t[:4]}…{t[-4:]}" if t else "verrà creata al salvataggio")

    def _new_remote_token(self) -> None:
        from ..remote.server import new_token
        self._remote_token = new_token()
        self._show_remote_token()

    # Sintesi vocale ------------------------------------------------------------------------
    def _tts_slider(self, lo: int, hi: int, value: int, fmt: str):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(max(lo, min(hi, value)))
        label = QLabel(fmt.format(slider.value()))
        label.setMinimumWidth(56)
        slider.valueChanged.connect(lambda v: label.setText(fmt.format(v)))
        reset = QPushButton("0")
        reset.setFixedWidth(32)
        reset.setToolTip("Normale")
        reset.clicked.connect(lambda: slider.setValue(0))
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(label)
        row.addWidget(reset)
        return slider, row

    def _on_tts_engine(self) -> None:
        engine = self.tts_engine.currentData()
        old_engine, old_voice = self.tts_voice.selected()
        if old_engine:
            self._tts_voices[old_engine] = old_voice
        self.tts_voice.default_item = "" if engine == tts.ENGINE_EDGE else "Voce predefinita del sistema"
        self.tts_voice._selected = (engine, self._tts_voices.get(engine, ""))
        self.tts_voice.set_engines([engine])
        self.tts_pitch.setEnabled(engine == tts.ENGINE_EDGE)
        reason = tts.unavailable_reason(engine)
        self.tts_status.setText(f"Non disponibile: {reason}" if reason else "")

    def tts_values(self) -> dict:
        engine, voice = self.tts_voice.selected()
        engine = self.tts_engine.currentData()
        voices = dict(self._tts_voices)
        voices[engine] = voice
        return {"engine": engine, "edge_voice": voices.get(tts.ENGINE_EDGE) or tts.DEFAULT_EDGE_VOICE,
                "system_voice": voices.get(tts.ENGINE_SYSTEM, ""),
                "rate": self.tts_rate.value(), "pitch": self.tts_pitch.value()}

    def _test_tts(self) -> None:
        text = self.tts_test.text().strip()
        if text and self._preview_tts is not None:
            self._preview_tts(text, self.tts_values())

    def _save(self) -> None:
        a = self.config.data["audio"]
        a["host_api"] = self.host_api.currentText()
        a["input_device"] = self.input.currentData() or ""
        a["virtual_output"] = self.virtual.currentData() or ""
        a["monitor_output"] = self.monitor.currentData() or ""
        a["virtual_channel"] = int(self.virtual_ch.currentData() or 0)
        a["monitor_channel"] = int(self.monitor_ch.currentData() or 0)
        a["asio"] = self.asio.isChecked()
        a["sample_rate"] = int(self.sample_rate.currentData())
        a["block_size"] = int(self.block.currentData())
        # aggiorna senza sostituire: restano le chiavi che il dialogo non gestisce (es. canale dedicato)
        self.config.data["discord"].update({
            "token": self.bot_token.text().strip(),
            "owner_id": self.bot_owner.text().strip(),
            "autostart": self.bot_autostart.isChecked(),
            "follow": self.bot_follow.isChecked(),
            "exclusive": self.bot_exclusive.isChecked(),
            "continuous": self.bot_continuous.isChecked(),
            "presence": self.bot_presence.isChecked(),
            "shortcuts": {k: e.keySequence().toString() for k, e in self.bot_keys.items()},
            "commands": {"enabled": self.cmd_enabled.isChecked()},
            "permissions": self.perm_editor.values(),
            "greetings": self.greet_editor.values(),
        })
        self.config.data["midi_map"] = self._map
        self.config.data["tts"] = self.tts_values()
        self.config.data["remote"] = {"enabled": self.remote_enabled.isChecked(),
                                      "port": self.remote_port.value(), "token": self._remote_token}
        self.config.data["midi"] = {"input": self.midi_port.currentData() or "",
                                    "velocity": self.midi_velocity.isChecked()}
        dirs = [self.vst_dirs.item(i).text() for i in range(self.vst_dirs.count())]
        self.config.data["vst3_dirs"] = [] if dirs == default_vst3_dirs() else dirs
        self.accept()

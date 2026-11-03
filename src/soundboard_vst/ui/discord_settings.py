"""Impostazioni del bot più ricche: permessi per ruoli/utenti e suoni di entrata/uscita."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..discord_bot import GREETING_EVENTS, normalize_greetings
from ..discord_commands import GROUPS, normalize_permissions
from . import theme

ID_ROLE = Qt.ItemDataRole.UserRole + 1


def role_choices(directory: dict) -> list[tuple[str, str]]:
    return [(r["id"], f"@{r['name']}  ·  {r['guild']}") for r in directory.get("roles", [])]


def user_choices(directory: dict) -> list[tuple[str, str]]:
    users = directory.get("users", {})
    return sorted(((uid, f"{name}  ·  {uid}") for uid, name in users.items()), key=lambda x: x[1].lower())


def summary(ids: list[str], choices: list[tuple[str, str]], empty: str = "nessuno") -> str:
    if not ids:
        return empty
    labels = dict(choices)
    names = [labels.get(i, i).split("  ·  ")[0] for i in ids]
    text = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
    return text


class PickerDialog(QDialog):
    """Lista con caselle da spuntare; si possono aggiungere voci non in elenco (ID o nome)."""

    def __init__(self, title: str, choices: list[tuple[str, str]], selected: list[str], hint: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 420)
        self.list = QListWidget()
        known = {i for i, _ in choices}
        for value, label in choices + [(s, s) for s in selected if s not in known]:
            self._add(value, label, value in selected)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText(hint)
        self.custom.returnPressed.connect(self._add_custom)
        add = QPushButton("Aggiungi")
        add.clicked.connect(self._add_custom)
        row = QHBoxLayout()
        row.addWidget(self.custom, 1)
        row.addWidget(add)
        note = QLabel("Compaiono i ruoli dei server del bot e le persone che il bot ha già visto (nei canali vocali "
                      "o usando i comandi). Per gli altri scrivi l'ID (Discord → tasto destro → Copia ID).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)
        lay.addWidget(note)
        lay.addWidget(buttons)

    def _add(self, value: str, label: str, checked: bool) -> None:
        it = QListWidgetItem(label)
        it.setData(ID_ROLE, value)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.addItem(it)

    def _add_custom(self) -> None:
        value = self.custom.text().strip().lstrip("@").strip()
        if not value:
            return
        for i in range(self.list.count()):
            if self.list.item(i).data(ID_ROLE) == value:
                self.list.item(i).setCheckState(Qt.CheckState.Checked)
                break
        else:
            self._add(value, value, True)
        self.custom.clear()

    def values(self) -> list[str]:
        return [self.list.item(i).data(ID_ROLE) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class PermissionsEditor(QWidget):
    """Chi può usare ogni gruppo di comandi: chiunque, oppure ruoli e utenti scelti; più i bloccati."""

    def __init__(self, perms: dict, directory: dict, parent=None):
        super().__init__(parent)
        self.perms = normalize_permissions(perms)
        self.directory = directory
        self.roles = role_choices(directory)
        self.users = user_choices(directory)
        self.admins = QCheckBox("Gli amministratori del server possono usare tutti i comandi")
        self.admins.setChecked(self.perms["admins"])
        self.table = QTableWidget(len(GROUPS), 4)
        self.table.setHorizontalHeaderLabels(["Comandi", "Chiunque", "Ruoli", "Utenti"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self._everyone: dict[str, QCheckBox] = {}
        self._buttons: dict[tuple[str, str], QPushButton] = {}
        for row, (g, name, what) in enumerate(GROUPS):
            item = QTableWidgetItem(name)
            item.setToolTip(what)
            self.table.setItem(row, 0, item)
            cb = QCheckBox()
            cb.setChecked(self.perms["groups"][g]["everyone"])
            cb.setToolTip("Tutti i membri del server")
            cb.toggled.connect(lambda _=False, g=g: self._refresh(g))
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(8, 0, 0, 0)
            hl.addWidget(cb)
            self.table.setCellWidget(row, 1, holder)
            self._everyone[g] = cb
            for col, kind in ((2, "roles"), (3, "users")):
                b = QPushButton()
                b.clicked.connect(lambda _=False, g=g, kind=kind: self._pick(g, kind))
                self.table.setCellWidget(row, col, b)
                self._buttons[(g, kind)] = b
            self._refresh(g)
        self.table.setMinimumHeight(34 * len(GROUPS) + 34)
        self.blocked_btn = QPushButton()
        self.blocked_btn.clicked.connect(self._pick_blocked)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Utenti bloccati (non possono usare niente):"))
        brow.addWidget(self.blocked_btn, 1)
        self._refresh_blocked()
        hint = QLabel(
            "Tu (il tuo ID utente) puoi sempre usare tutto. Passa il mouse sul nome di un gruppo per vedere quali "
            "comandi comprende. In più, gli amministratori del server possono limitare i comandi da Discord: "
            "<i>Impostazioni server → Integrazioni → (il bot)</i>.")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet(f"color: {theme.MUTED};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.admins)
        lay.addWidget(self.table)
        lay.addLayout(brow)
        lay.addWidget(hint)

    def _refresh(self, g: str) -> None:
        everyone = self._everyone[g].isChecked()
        cfg = self.perms["groups"][g]
        for kind, choices in (("roles", self.roles), ("users", self.users)):
            b = self._buttons[(g, kind)]
            b.setText("tutti" if everyone else summary(cfg[kind], choices) + "  …")
            b.setEnabled(not everyone)

    def _pick(self, g: str, kind: str) -> None:
        name = dict((x[0], x[1]) for x in GROUPS)[g]
        if kind == "roles":
            dlg = PickerDialog(f"Ruoli — {name}", self.roles, self.perms["groups"][g]["roles"],
                               "ID o nome del ruolo", self)
        else:
            dlg = PickerDialog(f"Utenti — {name}", self.users, self.perms["groups"][g]["users"],
                               "ID dell'utente", self)
        if dlg.exec():
            self.perms["groups"][g][kind] = dlg.values()
            self._refresh(g)

    def _pick_blocked(self) -> None:
        dlg = PickerDialog("Utenti bloccati", self.users, self.perms["blocked"], "ID dell'utente", self)
        if dlg.exec():
            self.perms["blocked"] = dlg.values()
            self._refresh_blocked()

    def _refresh_blocked(self) -> None:
        self.blocked_btn.setText(summary(self.perms["blocked"], self.users) + "  …")

    def values(self) -> dict:
        out = normalize_permissions(self.perms)
        out["admins"] = self.admins.isChecked()
        for g, cb in self._everyone.items():
            out["groups"][g]["everyone"] = cb.isChecked()
        return out


class GreetingsEditor(QWidget):
    """Suoni quando qualcuno entra o esce dal canale vocale del bot."""

    DEFAULT_ROW = "*"

    def __init__(self, greetings: dict, directory: dict, sounds: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        g = normalize_greetings(greetings)
        self.sounds = sounds
        self.users = dict(directory.get("users", {}))
        self.enabled = QCheckBox("Suona quando qualcuno entra, esce, si muta o si smuta nel canale vocale del bot")
        self.enabled.setChecked(g["enabled"])
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 3600)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(g["cooldown"])
        self.cooldown.setToolTip("Se la stessa persona entra ed esce di continuo, suona al massimo una volta in questo tempo")
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Non ripetere per la stessa persona prima di"))
        crow.addWidget(self.cooldown)
        crow.addStretch(1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Persona", "Entra", "Esce", "Si muta", "Si smuta", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(34)
        hdr = self.table.horizontalHeader()
        for col in range(5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(200)
        self._add_row(self.DEFAULT_ROW, "Chiunque altro", *(g["default"][e] for e in GREETING_EVENTS))
        for uid, u in g["users"].items():
            self._add_row(uid, u.get("name") or self.users.get(uid, ""), *(u[e] for e in GREETING_EVENTS))
        add = QPushButton("Aggiungi persone…")
        add.clicked.connect(self._add_people)
        self.announce = QCheckBox("Se non c'è un suono, annuncia con la sintesi vocale")
        self.announce.setChecked(g["announce"]["enabled"])
        self.texts: dict[str, QLineEdit] = {}
        arow = QGridLayout()
        for i, (event, label) in enumerate(zip(GREETING_EVENTS, ("Entrata", "Uscita", "Muto", "Smuto"))):
            edit = QLineEdit(g["announce"][event])
            edit.setPlaceholderText("{nome} = nome della persona" if event in ("join", "leave")
                                    else "vuoto = nessun annuncio, es. «{nome} si è mutato»")
            self.texts[event] = edit
            arow.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            arow.addWidget(edit, i // 2, (i % 2) * 2 + 1)
        arow.setColumnStretch(1, 1)
        arow.setColumnStretch(3, 1)
        self.join_text, self.leave_text = self.texts["join"], self.texts["leave"]
        hint = QLabel("Ognuno può scegliere i propri suoni da Discord con <b>/mio-suono</b>. Funziona nel canale "
                      "vocale in cui si trova il bot. «Si muta» vale anche per chi silenzia le cuffie.")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet(f"color: {theme.MUTED};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.enabled)
        lay.addLayout(crow)
        lay.addWidget(self.table, 1)
        lay.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.announce)
        lay.addLayout(arow)
        lay.addWidget(hint)

    def _combo(self, key: str) -> QComboBox:
        c = QComboBox()
        c.addItem("— niente —", "")
        for k, label in self.sounds:
            c.addItem(label, k)
        idx = c.findData(key) if key else 0
        if key and idx < 0:
            c.addItem(f"(suono eliminato: {key})", key)
            idx = c.count() - 1
        c.setCurrentIndex(idx)
        return c

    def _add_row(self, uid: str, name: str, join: str, leave: str, mute: str = "", unmute: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        label = name if uid == self.DEFAULT_ROW else f"{name or 'Utente'}  ·  {uid}"
        item = QTableWidgetItem(label)
        item.setData(ID_ROLE, uid)
        item.setData(ID_ROLE + 1, name)
        if uid == self.DEFAULT_ROW:
            item.setToolTip("Chi non ha un suono suo")
            f = item.font()
            f.setItalic(True)
            item.setFont(f)
        self.table.setItem(row, 0, item)
        for col, key in enumerate((join, leave, mute, unmute), start=1):
            self.table.setCellWidget(row, col, self._combo(key))
        if uid != self.DEFAULT_ROW:
            rm = QPushButton("✕")
            rm.setToolTip("Togli")
            rm.clicked.connect(lambda _=False, it=item: self.table.removeRow(self.table.row(it)))
            self.table.setCellWidget(row, 5, rm)

    def _uids(self) -> set[str]:
        return {self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())}

    def _add_people(self) -> None:
        present = self._uids()
        choices = [(u, lbl) for u, lbl in user_choices({"users": self.users}) if u not in present]
        dlg = PickerDialog("Aggiungi persone", choices, [], "ID dell'utente", self)
        if dlg.exec():
            for uid in dlg.values():
                if uid not in self._uids():
                    self._add_row(uid, self.users.get(uid, ""), "", "", "", "")

    def values(self) -> dict:
        out = {"enabled": self.enabled.isChecked(), "cooldown": self.cooldown.value(), "users": {},
               "default": {e: "" for e in GREETING_EVENTS},
               "announce": {"enabled": self.announce.isChecked(),
                            **{e: self.texts[e].text().strip() for e in GREETING_EVENTS}}}
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            uid = item.data(ID_ROLE)
            keys = {e: self.table.cellWidget(r, c).currentData() or "" for c, e in enumerate(GREETING_EVENTS, start=1)}
            if uid == self.DEFAULT_ROW:
                out["default"] = keys
            else:
                out["users"][uid] = {"name": item.data(ID_ROLE + 1) or "", **keys}
        return normalize_greetings(out)

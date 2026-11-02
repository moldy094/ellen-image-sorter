# the little setup window
# lets you change the settings, start/stop the background service and see what
# its been doing lately. saving writes config.toml and the service picks it up on its own

import os
import json
import subprocess

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QPushButton, QCheckBox, QComboBox, QFileDialog, QListWidget, QMessageBox, QDialog,
)

from . import config, notify, lookup

SERVICE = "ellen-sorter.service"

GOONERY_CHOICES = [("off", "off, everything in the normal folders"),
                   ("lewd", "lewd stuff only"),
                   ("suggestive", "lewd + suggestive (bikinis etc)")]
DUPE_CHOICES = [("trash", "keep the best one, trash the rest"), ("keep", "keep both")]


def systemctl(*args):
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=20)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def find_horse():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(config.DATA_DIR, "horse.jpg"), os.path.join(here, "..", "horse.jpg")):
        if os.path.exists(p):
            return p
    return None


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = config.load()
        self.setWindowTitle("ellen image sorter")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)

        title = QLabel("<b style='font-size:16pt'>ellen image sorter</b><br><i>for those of culture</i>")
        layout.addWidget(title)

        # ---- folder ----
        box = QGroupBox("folder")
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.root = QLineEdit(self.cfg["library"]["root"])
        browse = QPushButton("browse")
        browse.clicked.connect(self.pick_folder)
        row.addWidget(self.root)
        row.addWidget(browse)
        form.addRow("drop folder", row)
        self.tag = QLineEdit(self.cfg["library"]["character_tag"])
        form.addRow("danbooru tag", self.tag)
        layout.addWidget(box)

        # ---- sorting ----
        box = QGroupBox("sorting")
        form = QFormLayout(box)
        self.goonery = QComboBox()
        for key, text in GOONERY_CHOICES:
            self.goonery.addItem(text, key)
        self.goonery.setCurrentIndex([k for k, _ in GOONERY_CHOICES].index(self.cfg["sorting"]["goonery"]))
        form.addRow("goonery folder", self.goonery)
        self.goonfilter = QCheckBox("keep the weird stuff out of goonery (sends it to _needs_review)")
        self.goonfilter.setChecked(self.cfg["sorting"]["goonery_filter"])
        form.addRow(self.goonfilter)
        self.ai = QCheckBox("put ai generated stuff in its own folder")
        self.ai.setChecked(self.cfg["sorting"]["separate_ai"])
        form.addRow(self.ai)
        self.upgrade = QCheckBox("grab the highest quality version if i can find one")
        self.upgrade.setChecked(self.cfg["sorting"]["upgrade_quality"])
        form.addRow(self.upgrade)
        self.dupes = QComboBox()
        for key, text in DUPE_CHOICES:
            self.dupes.addItem(text, key)
        self.dupes.setCurrentIndex([k for k, _ in DUPE_CHOICES].index(self.cfg["sorting"]["duplicates"]))
        form.addRow("duplicates", self.dupes)
        layout.addWidget(box)

        # ---- finding artists ----
        box = QGroupBox("finding artists")
        form = QFormLayout(box)
        self.saucenao = QLineEdit(self.cfg["sources"]["saucenao_key"])
        self.saucenao.setEchoMode(QLineEdit.Password)
        self.saucenao.setPlaceholderText("optional, finds way more artists")
        form.addRow("saucenao key", self.saucenao)
        self.ocr = QCheckBox("read signatures off the picture")
        self.ocr.setChecked(self.cfg["sources"]["ocr"])
        if not lookup.ocr_available():
            self.ocr.setText("read signatures off the picture (easyocr isnt installed)")
            self.ocr.setChecked(False)
            self.ocr.setEnabled(False)
        form.addRow(self.ocr)
        layout.addWidget(box)

        # ---- notifications ----
        box = QGroupBox("notifications")
        form = QFormLayout(box)
        self.desktop = QCheckBox("popup when something goes wrong")
        self.desktop.setChecked(self.cfg["notify"]["desktop"])
        form.addRow(self.desktop)
        self.success = QCheckBox("also popup every time something gets sorted")
        self.success.setChecked(self.cfg["notify"]["on_success"])
        form.addRow(self.success)
        self.webhook = QLineEdit(self.cfg["notify"]["webhook_url"])
        self.webhook.setPlaceholderText("discord webhook or ntfy url, optional")
        form.addRow("webhook", self.webhook)
        layout.addWidget(box)

        # ---- service ----
        box = QGroupBox("background service")
        v = QVBoxLayout(box)
        self.status = QLabel("checking...")
        v.addWidget(self.status)
        row = QHBoxLayout()
        for text, fn in (("start", self.start), ("stop", self.stop), ("restart", self.restart)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        self.autostart = QCheckBox("start on login")
        self.autostart.clicked.connect(self.toggle_autostart)
        row.addWidget(self.autostart)
        v.addLayout(row)
        layout.addWidget(box)

        # ---- recent stuff ----
        layout.addWidget(QLabel("recent activity"))
        self.recent = QListWidget()
        self.recent.setMinimumHeight(140)
        layout.addWidget(self.recent)

        # ---- bottom buttons ----
        row = QHBoxLayout()
        save = QPushButton("save")
        save.setDefault(True)
        save.clicked.connect(self.save)
        test = QPushButton("test notification")
        test.clicked.connect(self.test_notify)
        open_folder = QPushButton("open folder")
        open_folder.clicked.connect(lambda: subprocess.Popen(["xdg-open", self.root.text()]))
        logs = QPushButton("open log")
        logs.clicked.connect(lambda: subprocess.Popen(["xdg-open", config.LOG_FILE]))
        horse = QPushButton("horse")
        horse.clicked.connect(self.horse)
        for b in (save, test, open_folder, logs, horse):
            row.addWidget(b)
        layout.addLayout(row)

        self.last_lines = None
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "pick the folder you drop pictures into", self.root.text())
        if folder:
            self.root.setText(folder)

    def save(self):
        c = self.cfg
        c["library"]["root"] = self.root.text().strip()
        c["library"]["character_tag"] = self.tag.text().strip() or "ellen_joe"
        c["sorting"]["goonery"] = self.goonery.currentData()
        c["sorting"]["goonery_filter"] = self.goonfilter.isChecked()
        c["sorting"]["separate_ai"] = self.ai.isChecked()
        c["sorting"]["upgrade_quality"] = self.upgrade.isChecked()
        c["sorting"]["duplicates"] = self.dupes.currentData()
        c["sources"]["saucenao_key"] = self.saucenao.text().strip()
        c["sources"]["ocr"] = self.ocr.isChecked()
        c["notify"]["desktop"] = self.desktop.isChecked()
        c["notify"]["on_success"] = self.success.isChecked()
        c["notify"]["webhook_url"] = self.webhook.text().strip()
        if not os.path.isdir(c["library"]["root"]):
            QMessageBox.warning(self, "hmm", "that folder doesnt exist")
            return
        config.save(c)
        QMessageBox.information(self, "saved", "saved. the service picks it up on its own")

    def test_notify(self):
        c = config.load()
        c["notify"]["desktop"] = self.desktop.isChecked()
        c["notify"]["webhook_url"] = self.webhook.text().strip()
        notify.send(c, "ellen image sorter", "test notification, if you see this its working", error=True)

    def start(self):
        systemctl("start", SERVICE)
        self.refresh()

    def stop(self):
        systemctl("stop", SERVICE)
        self.refresh()

    def restart(self):
        systemctl("restart", SERVICE)
        self.refresh()

    def toggle_autostart(self):
        systemctl("enable" if self.autostart.isChecked() else "disable", SERVICE)
        self.refresh()

    def horse(self):
        path = find_horse()
        if not path:
            return
        d = QDialog(self)
        d.setWindowTitle("horse")
        v = QVBoxLayout(d)
        pic = QLabel()
        pic.setPixmap(QPixmap(path).scaled(480, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        v.addWidget(pic)
        d.exec()

    def refresh(self):
        code, out = systemctl("is-active", SERVICE)
        state = out.splitlines()[-1] if out else "unknown"
        colour = "green" if state == "active" else "red"
        self.status.setText(f"service is <b style='color:{colour}'>{state}</b>")
        code, out = systemctl("is-enabled", SERVICE)
        self.autostart.setChecked(code == 0)

        lines = []
        try:
            with open(config.ACTIVITY_FILE) as f:
                lines = f.readlines()[-40:]
        except FileNotFoundError:
            pass
        # only redo the list if something new happened, otherwise it keeps jumping back to the top
        if lines == self.last_lines:
            return
        self.last_lines = lines
        self.recent.clear()
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if "error" in e:
                text = f"{e['time']}  ⚠ {e['file']}: {e['error']}"
            elif "dest" in e:
                text = f"{e['time']}  {e['file']} -> {e['dest']}"
                if e.get("note"):
                    text += f"  ({e['note']})"
            else:
                text = f"{e['time']}  {e['file']}: {e.get('note', '')}"
            self.recent.addItem(text)


def main():
    app = QApplication([])
    app.setApplicationName("ellen image sorter")
    w = Window()
    w.show()
    app.exec()

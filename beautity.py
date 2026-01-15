import json
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QFileDialog,
    QLineEdit, QHBoxLayout, QVBoxLayout, QComboBox, QLabel, QMessageBox,
    QDialog, QDialogButtonBox, QPlainTextEdit, QTextEdit   # <-- ДОБАВИЛ QTextEdit
)


def xml_to_dict(x: str) -> dict:
    root = ET.fromstring(x)
    msg = root.find("message") or (root if root.tag == "message" else None)
    if msg is None:
        return {"_error": "No <message>"}

    out = {f"@{k}": msg.attrib[k] for k in ("id", "name", "date") if k in msg.attrib}

    for ch in msg:
        if ch.tag == "scalar":
            n = ch.attrib.get("name")
            out[n] = None if ch.attrib.get("nil") == "true" else (ch.text or "").strip()

    for lst in msg.findall("list"):
        lname = lst.attrib.get("name") or "list"
        arr = []
        for comp in lst.findall("complex"):
            row = {}
            for sc in comp.findall("scalar"):
                n = sc.attrib.get("name")
                row[n] = None if sc.attrib.get("nil") == "true" else (sc.text or "").strip()
            if row:
                arr.append(row)
        if arr:
            out[lname] = arr

    return out


def pretty(d: dict) -> str:
    def _one_line(v):
        return "None" if v is None else str(v)

    def _fmt_val(v, indent=""):
        if isinstance(v, dict):
            return "\n".join(f"{indent}{kk}: {_one_line(v[kk])}" for kk in sorted(v.keys(), key=str))

        if isinstance(v, list):
            if not v:
                return f"{indent}[]"
            if all(isinstance(x, dict) for x in v):
                lines = []
                for i, row in enumerate(v, 1):
                    lines.append(f"{indent}[{i}]")
                    lines.append(_fmt_val(row, indent + "  "))
                return "\n".join(lines)
            return "\n".join(f"{indent}- {_one_line(x)}" for x in v)

        return f"{indent}{_one_line(v)}"

    keys = sorted(d.keys(), key=lambda k: (0 if str(k).startswith("@") else 1, str(k)))
    out = []
    for k in keys:
        v = d[k]
        if isinstance(v, (dict, list)):
            out.append(f"{k}:")
            out.append(_fmt_val(v, "  "))
        else:
            out.append(f"{k}: {_one_line(v)}")
    return "\n".join(out)


def highlight_all(edit: QPlainTextEdit, q: str, color: QColor) -> int:
    if not q:
        edit.setExtraSelections([])
        return 0

    doc = edit.document()
    cur = QTextCursor(doc)

    fmt = QTextCharFormat()
    fmt.setBackground(color)
    fmt.setForeground(QColor(0, 0, 0))

    sels, n = [], 0
    flags = QTextDocument.FindFlags()  # без учета регистра

    while True:
        cur = doc.find(q, cur, flags)
        if cur.isNull():
            break
        s = QTextEdit.ExtraSelection()   # <-- ВОТ ЭТОТ ФИКС
        s.cursor = cur
        s.format = fmt
        sels.append(s)
        n += 1
        if n >= 5000:
            break

    edit.setExtraSelections(sels)
    return n


class PasteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вставить сообщение")
        self.resize(900, 550)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Вставь сюда JSON (Cmd+V) и нажми «Разобрать»…")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        buttons.button(QDialogButtonBox.Ok).setText("Разобрать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.text, 1)
        lay.addWidget(buttons)


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON + XML Beautity")
        self.resize(1300, 780)
        self.records = []

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self.render)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.textChanged.connect(self.apply_search)

        btn_load = QPushButton("Загрузить файл…")
        btn_load.clicked.connect(self.load)

        btn_paste = QPushButton("Вставить…")
        btn_paste.clicked.connect(self.paste)

        top = QHBoxLayout()
        top.addWidget(btn_load)
        top.addWidget(btn_paste)
        top.addSpacing(12)
        top.addWidget(QLabel("Запись:"))
        top.addWidget(self.combo, 2)
        top.addStretch()
        top.addWidget(self.search, 3)

        self.left = QPlainTextEdit()
        self.left.setReadOnly(True)

        self.right = QPlainTextEdit()
        self.right.setReadOnly(True)

        main = QHBoxLayout()
        main.addWidget(self.left, 1)
        main.addWidget(self.right, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(main)

        self.hl = QColor(255, 235, 120)

    def parse_and_show(self, raw: str):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Ожидался JSON-массив (список объектов)")

        self.left.setPlainText(raw)

        self.records = []
        self.combo.blockSignals(True)
        self.combo.clear()

        for i, item in enumerate(data, 1):
            d = item.get("digest", {}) or {}
            self.records.append({
                "digest": d,
                "msg": xml_to_dict(item.get("xml", "") or "")
            })
            self.combo.addItem(f"#{i}  {d.get('integrationId','—')}  {d.get('date','—')}")

        self.combo.blockSignals(False)
        self.combo.setCurrentIndex(0)
        self.render()

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбери файл", "", "JSON (*.json *.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            self.parse_and_show(raw)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def paste(self):
        while True:
            dlg = PasteDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return
            raw = dlg.text.toPlainText().strip()
            if not raw:
                return
            try:
                self.parse_and_show(raw)
                return
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def render(self):
        if not self.records:
            self.right.setPlainText("")
            return

        idx = self.combo.currentIndex()
        if idx < 0 or idx >= len(self.records):
            self.right.setPlainText("")
            return

        r = self.records[idx]
        text = "DIGEST:\n" + pretty(r["digest"]) + "\n\nMESSAGE:\n" + pretty(r["msg"])
        self.right.setPlainText(text)
        self.apply_search()

    def apply_search(self):
        q = (self.search.text() or "").strip()
        if not q:
            self.left.setExtraSelections([])
            self.right.setExtraSelections([])
            return
        highlight_all(self.left, q, self.hl)
        highlight_all(self.right, q, self.hl)


if __name__ == "__main__":
    app = QApplication([])
    w = App()
    w.show()
    app.exec()

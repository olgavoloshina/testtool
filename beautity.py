import json, xml.etree.ElementTree as ET
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QTextEdit, QFileDialog,
    QLineEdit, QHBoxLayout, QVBoxLayout, QComboBox, QLabel, QMessageBox
)

def xml_to_dict(x: str) -> dict:
    root = ET.fromstring(x)
    msg = root.find("message") or (root if root.tag == "message" else None)
    if msg is None: return {"_error": "No <message>"}
    out = {f"@{k}": msg.attrib[k] for k in ("id", "name", "date") if k in msg.attrib}
    for ch in msg:
        if ch.tag == "scalar":
            n = ch.attrib.get("name")
            out[n] = None if ch.attrib.get("nil") == "true" else (ch.text or "").strip()
    return out

def pretty(d: dict) -> str:
    keys = sorted(d.keys(), key=lambda k: (0 if str(k).startswith("@") else 1, str(k)))
    return "\n".join(f"{k}: {d[k]}" for k in keys)

def highlight_all(edit: QTextEdit, q: str, color: QColor) -> int:
    if not q:
        edit.setExtraSelections([])
        return 0

    doc = edit.document()
    cur = QTextCursor(doc)

    fmt = QTextCharFormat()
    fmt.setBackground(color)
    fmt.setForeground(QColor(0, 0, 0))  # чтобы точно было видно на темной теме

    sels, n = [], 0
    flags = QTextDocument.FindFlags()  # без CaseSensitive = поиск без учета регистра

    while True:
        cur = doc.find(q, cur, flags)
        if cur.isNull():
            break
        s = QTextEdit.ExtraSelection()
        s.cursor = cur
        s.format = fmt
        sels.append(s)
        n += 1
        if n >= 5000:  # защита от подвисаний на огромных raw
            break

    edit.setExtraSelections(sels)
    return n

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

        btn = QPushButton("Загрузить файл…")
        btn.clicked.connect(self.load)

        top = QHBoxLayout()
        top.addWidget(btn)
        top.addSpacing(12)
        top.addWidget(QLabel("Запись:"))
        top.addWidget(self.combo, 2)
        top.addStretch()
        top.addWidget(self.search, 3)

        self.left = QTextEdit();  self.left.setReadOnly(True)
        self.right = QTextEdit(); self.right.setReadOnly(True)

        main = QHBoxLayout()
        main.addWidget(self.left, 1)
        main.addWidget(self.right, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(main)

        self.hl = QColor(255, 235, 120)

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбери файл", "", "JSON (*.json *.txt)")
        if not path: return
        try:
            raw = open(path, encoding="utf-8").read()
            data = json.loads(raw)
            if not isinstance(data, list): raise ValueError("Ожидался JSON-массив")
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
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def render(self):
        if not self.records:
            self.right.setPlainText("")
            return
        r = self.records[self.combo.currentIndex()]
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
    w = App(); w.show()
    app.exec()

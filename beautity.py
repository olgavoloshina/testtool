import json
import re
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QTextDocument, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QFileDialog,
    QLineEdit, QHBoxLayout, QVBoxLayout, QComboBox, QLabel, QMessageBox,
    QPlainTextEdit, QTextEdit
)


# =========================
# XML → dict (для правого окна)
# =========================
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
            lines = []
            for i, row in enumerate(v, 1):
                lines.append(f"{indent}[{i}]")
                lines.append(_fmt_val(row, indent + "  "))
            return "\n".join(lines)
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


# =========================
# Подсветка
# =========================
def build_sel(edit: QPlainTextEdit, start: int, end: int, bg: QColor) -> QTextEdit.ExtraSelection:
    cur = edit.textCursor()
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.KeepAnchor)

    fmt = QTextCharFormat()
    fmt.setBackground(bg)
    fmt.setForeground(QColor(0, 0, 0))

    s = QTextEdit.ExtraSelection()
    s.cursor = cur
    s.format = fmt
    return s


def find_query_selections(edit: QPlainTextEdit, q: str, bg: QColor, limit: int = 5000) -> list:
    if not q:
        return []

    doc = edit.document()
    cur = QTextCursor(doc)

    fmt = QTextCharFormat()
    fmt.setBackground(bg)
    fmt.setForeground(QColor(0, 0, 0))

    sels, n = [], 0
    flags = QTextDocument.FindFlags()

    while True:
        cur = doc.find(q, cur, flags)
        if cur.isNull():
            break
        s = QTextEdit.ExtraSelection()
        s.cursor = cur
        s.format = fmt
        sels.append(s)
        n += 1
        if n >= limit:
            break

    return sels


# =========================
# App
# =========================
class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON + XML Beautity")
        self.resize(1300, 780)

        self.records = []
        self.parsed_dirty = False
        self._suppress_left_change = False

        self.left_static_sels: list = []

        # UI
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self.render)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.textChanged.connect(self.apply_search_dynamic)

        btn_load = QPushButton("Загрузить файл…")
        btn_load.clicked.connect(self.load)

        btn_refresh = QPushButton("Refresh (перепарсить слева)")
        btn_refresh.clicked.connect(self.refresh_from_left)

        btn_save = QPushButton("Save as…")
        btn_save.clicked.connect(self.save_left_as)

        top = QHBoxLayout()
        top.addWidget(btn_load)
        top.addWidget(btn_refresh)
        top.addWidget(btn_save)
        top.addSpacing(12)
        top.addWidget(QLabel("Запись:"))
        top.addWidget(self.combo, 2)
        top.addStretch()
        top.addWidget(self.search, 3)

        self.left = QPlainTextEdit()
        self.left.setReadOnly(False)

        self.right = QPlainTextEdit()
        self.right.setReadOnly(True)

        mono = QFont("Menlo")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setPointSize(11)
        self.left.setFont(mono)
        self.right.setFont(mono)

        main = QHBoxLayout()
        main.addWidget(self.left, 1)
        main.addWidget(self.right, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(main)

        # Colors
        self.hl_search = QColor(255, 235, 120)
        self.hl_key = QColor(190, 235, 255)
        self.hl_val = QColor(210, 245, 210)
        self.hl_dirty = QColor(255, 210, 210)

        # Regex (урезанный набор)
        self.re_json_key = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*:')
        self.re_json_boolnull = re.compile(r':\s*\b(true|false|null)\b')
        self.re_xml_name_attr = re.compile(r'name=\\"([^"\\]+)\\"')
        self.re_xml_nil_attr = re.compile(r'\bnil=\\"(true|false)\\"')
        self.re_xml_text_boolnull = re.compile(r'>\s*(true|false|null)\s*<')

        self.left.textChanged.connect(self.on_left_changed)

    # -------------------------
    # Handlers
    # -------------------------
    def on_left_changed(self):
        if self._suppress_left_change:
            return
        self.parsed_dirty = True
        self.update_right_header_only()
        self.apply_search_dynamic()

    def make_right_header(self) -> str:
        return "⚠ Parsed view outdated. Press Refresh." if self.parsed_dirty else "Parsed view — read only"

    def update_right_header_only(self):
        txt = self.right.toPlainText()
        if not txt:
            return
        lines = txt.splitlines()
        header = self.make_right_header()
        if lines and lines[0] != header:
            lines[0] = header
            self.right.setPlainText("\n".join(lines))

    def header_selection_for_right(self) -> list:
        if not self.parsed_dirty:
            return []
        txt = self.right.toPlainText()
        end = txt.find("\n")
        return [build_sel(self.right, 0, end if end != -1 else len(txt), self.hl_dirty)]

    # -------------------------
    # Highlighting
    # -------------------------
    def compute_left_static_syntax(self):
        text = self.left.toPlainText()
        sels = []
        cap = 4000

        def add(regex, group, color, limit):
            nonlocal sels
            for i, m in enumerate(regex.finditer(text)):
                if i >= limit or len(sels) >= cap:
                    break
                sels.append(build_sel(self.left, m.start(group), m.end(group), color))

        add(self.re_json_key, 1, self.hl_key, 1500)
        add(self.re_json_boolnull, 1, self.hl_val, 1500)
        add(self.re_xml_name_attr, 1, self.hl_key, 1500)

        for i, m in enumerate(self.re_xml_nil_attr.finditer(text)):
            if i >= 1200 or len(sels) >= cap:
                break
            seg = text[m.start(0):m.end(0)]
            rel = seg.find("nil")
            if rel != -1:
                sels.append(build_sel(self.left, m.start(0) + rel, m.start(0) + rel + 3, self.hl_key))
            sels.append(build_sel(self.left, m.start(1), m.end(1), self.hl_val))

        add(self.re_xml_text_boolnull, 1, self.hl_val, 1200)

        self.left_static_sels = sels[:cap]

    def apply_search_dynamic(self):
        q = self.search.text().strip()

        sels_left = list(self.left_static_sels)
        if q:
            sels_left += find_query_selections(self.left, q, self.hl_search)
        self.left.setExtraSelections(sels_left)

        sels_right = self.header_selection_for_right()
        if q:
            sels_right += find_query_selections(self.right, q, self.hl_search)
        self.right.setExtraSelections(sels_right)

    # -------------------------
    # Parsing / IO
    # -------------------------
    def parse_raw(self, raw: str, *, set_left: bool):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Ожидался JSON-массив")

        if set_left:
            self._suppress_left_change = True
            self.left.setPlainText(raw)
            self._suppress_left_change = False

        self.records.clear()
        self.combo.clear()

        for i, item in enumerate(data, 1):
            d = item.get("digest", {}) or {}
            self.records.append({
                "digest": d,
                "msg": xml_to_dict(item.get("xml", "") or "")
            })
            self.combo.addItem(f"#{i}  {d.get('integrationId','—')}  {d.get('date','—')}")

        self.parsed_dirty = False
        self.render()

        self.compute_left_static_syntax()
        self.apply_search_dynamic()

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбери файл", "", "JSON (*.json *.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.parse_raw(f.read(), set_left=True)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def refresh_from_left(self):
        raw = self.left.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "Пусто", "Слева пустой текст")
            return
        try:
            self.parse_raw(raw, set_left=False)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка парсинга", str(e))

    def save_left_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить как…", "edited.txt")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.left.toPlainText())

    def render(self):
        if not self.records:
            self.right.setPlainText("")
            return
        r = self.records[self.combo.currentIndex()]
        body = "DIGEST:\n" + pretty(r["digest"]) + "\n\nMESSAGE:\n" + pretty(r["msg"])
        self.right.setPlainText(self.make_right_header() + "\n\n" + body)


if __name__ == "__main__":
    app = QApplication([])
    w = App()
    w.show()
    app.exec()

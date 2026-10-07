import argparse
import os
import re
import sys
import zipfile
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import save_json, ensure_dir, fail, run_main

PAGE_LEN = 3000
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".svg"}
LIST_RE = re.compile(r"^(\d+[.)]|[-*\u2022])\s+\S")


class _H(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self._buf = []
        self._kind = None
        self._table = None
        self._row = None
        self._cell = None

    def _flush(self):
        t = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if t and self._kind:
            self.blocks.append((self._kind, t))
        self._buf = []
        self._kind = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._flush()
            self._table = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self._kind = "heading"
        elif tag == "li":
            self._flush()
            self._kind = "list_item"
        elif tag in ("p", "div", "section", "article", "br"):
            if self._kind and self._buf:
                self._flush()
            if self._kind is None:
                self._kind = "paragraph"

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._kind:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            t = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None:
                self._row.append(t)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._table is not None:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.blocks.append(("table", self._table))
            self._table = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "div"):
            self._flush()


def _lname(tag):
    return tag.rsplit("}", 1)[-1]


def detect_language(text):
    # ponytail: script-range heuristic only; full lang-id is out of scope
    deva = sum(1 for c in text if "\u0900" <= c <= "\u097F")
    beng = sum(1 for c in text if "\u0980" <= c <= "\u09FF")
    n = max(len(text), 1)
    if beng / n > 0.02:
        return "bn"
    if deva / n > 0.02:
        return "hi"
    if any(ord(c) > 127 for c in text):
        return "non-latin"
    return "en"


def heading_depth(line):
    s = line.strip()
    m = re.match(r"^(#{1,6})\s+\S", s)
    if m:
        return len(m.group(1))
    if re.match(r"^\d+(\.\d+)+\.?\s+\S", s) and len(s) < 120:
        return 2
    if re.match(r"^\d+\.?\s+[A-Z]", s) and len(s) < 100:
        return 1
    if len(s) < 80 and any(c.isalpha() for c in s):
        up = sum(1 for c in s if c.isupper())
        lo = sum(1 for c in s if c.islower())
        if up > lo:
            return 1
    if len(s) < 100 and s.endswith(":"):
        return 2
    return 0


def is_md_row(l):
    return l.strip().startswith("|") and "|" in l.strip()[1:]


def split_text(text):
    out = []
    for ch in re.split(r"\n\s*\n", text):
        lines = [l.strip() for l in ch.strip().splitlines() if l.strip()]
        if not lines:
            continue
        if len(lines) >= 2 and all(is_md_row(l) for l in lines):
            rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines]
            rows = [r for r in rows if not all(re.match(r"^:?-{2,}:?$", c) for c in r)]
            if rows:
                out.append(("table", rows))
                continue
        if len(lines) == 1:
            d = heading_depth(lines[0])
            out.append(("heading:%d" % d if d else "para", lines[0]))
            continue
        items = [l for l in lines if LIST_RE.match(l)]
        if items and len(items) == len(lines):
            out.extend(("list_item", l) for l in lines)
        else:
            d = heading_depth(lines[0])
            if d and len(lines) <= 2:
                out.append(("heading:%d" % d, lines[0]))
                out.append(("para", " ".join(lines[1:])))
            else:
                out.append(("para", " ".join(lines)))
    return out


def parse_docx(path):
    lims = []
    raw = []
    try:
        with zipfile.ZipFile(path) as z:
            try:
                xml = z.read("word/document.xml")
            except KeyError:
                return [], ["docx missing word/document.xml"]
            root = ET.fromstring(xml)
            body = None
            for el in root.iter():
                if _lname(el.tag) == "body":
                    body = el
                    break
            for ch in (body if body is not None else root):
                ln = _lname(ch.tag)
                if ln == "p":
                    style = ""
                    for d in ch.iter():
                        if _lname(d.tag) == "pStyle":
                            for k, v in d.attrib.items():
                                if _lname(k) == "val":
                                    style = v
                    t = "".join(t.text or "" for t in ch.iter() if _lname(t.tag) == "t").strip()
                    if t:
                        raw.append(("heading:1" if style.startswith("Heading") else "para", t))
                elif ln == "tbl":
                    rows = []
                    for tr in [c for c in ch if _lname(c.tag) == "tr"]:
                        cells = []
                        for tc in [c for c in tr if _lname(c.tag) in ("tc", "td", "th")]:
                            cells.append("".join(t.text or "" for t in tc.iter() if _lname(t.tag) == "t").strip())
                        rows.append(cells)
                    if rows:
                        raw.append(("table", rows))
    except zipfile.BadZipFile:
        return [], ["docx unreadable (not a zip)"]
    return raw, lims


def parse_pptx(path):
    lims = []
    raw = []
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
            if not names:
                return [], ["pptx has no slides"]
            for n in names:
                root = ET.fromstring(z.read(n))
                intbl = set()
                for el in root.iter():
                    if _lname(el.tag) == "tbl":
                        for t in el.iter():
                            if _lname(t.tag) == "t":
                                intbl.add(id(t))
                for el in root.iter():
                    if _lname(el.tag) == "p":
                        ts = [t for t in el.iter() if _lname(t.tag) == "t" and id(t) not in intbl]
                        t = "".join(x.text or "" for x in ts).strip()
                        if t:
                            raw.append(("para", t, True))
                for el in root.iter():
                    if _lname(el.tag) == "tbl":
                        rows = []
                        for tr in [c for c in el if _lname(c.tag) == "tr"]:
                            cells = []
                            for tc in tr.iter():
                                if _lname(tc.tag) in ("tc", "td", "th"):
                                    cells.append("".join(t.text or "" for t in tc.iter() if _lname(t.tag) == "t").strip())
                            if cells:
                                rows.append(cells)
                        if rows:
                            raw.append(("table", rows, True))
    except zipfile.BadZipFile:
        return [], ["pptx unreadable (not a zip)"]
    return raw, lims


def parse_xlsx(path):
    try:
        import openpyxl
    except ImportError:
        return [], ["openpyxl not installed; xlsx content skipped"]
    raw, lims = [], []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = [[("" if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(c.strip() for c in r)]
        if rows:
            raw.append(("table", rows, ws.title))
    if not raw:
        lims.append("xlsx has no non-empty sheets")
    return raw, lims


def parse_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], ["pypdf not installed; pdf content skipped"]
    raw, lims = [], []
    rd = PdfReader(path)
    for i, pg in enumerate(rd.pages):
        try:
            t = pg.extract_text() or ""
        except Exception:
            t = ""
        if not t.strip():
            lims.append("pdf page %d has no extractable text" % (i + 1))
            continue
        for kind, txt in split_text(t):
            raw.append((kind, txt, i + 1))
    return raw, lims


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", default="run")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.input):
        fail("input not found: %s" % a.input)
    ext = os.path.splitext(a.input)[1].lower()
    outdir = a.out if os.path.basename(os.path.normpath(a.out)) == a.run_id else os.path.join(a.out, a.run_id)
    ensure_dir(outdir)
    lims = []
    raw = []
    if ext in (".txt", ".md"):
        with open(a.input, encoding="utf-8", errors="replace") as f:
            raw = [(k, t) for k, t in split_text(f.read())]
    elif ext in (".html", ".htm"):
        with open(a.input, encoding="utf-8", errors="replace") as f:
            h = _H()
            h.feed(f.read())
        for b in h.blocks:
            if isinstance(b[1], list):
                raw.append(("table", b[1]))
            else:
                raw.append(b)
    elif ext == ".docx":
        raw, lims = parse_docx(a.input)
    elif ext == ".pptx":
        raw, lims = parse_pptx(a.input)
    elif ext == ".xlsx":
        raw, lims = parse_xlsx(a.input)
    elif ext == ".pdf":
        raw, lims = parse_pdf(a.input)
    elif ext in IMAGE_EXTS:
        lims.append("image input %s: no text extracted" % os.path.basename(a.input))
    else:
        fail("unsupported extension: %s" % ext)
    blocks = []
    stack = []
    chars = 0
    paged = ext in (".pdf", ".pptx")
    for i, item in enumerate(raw):
        if len(item) == 3:
            kind, payload, pg = item
        else:
            kind, payload = item
            pg = None
        if kind.startswith("heading"):
            try:
                d = int(kind.split(":")[1])
            except (IndexError, ValueError):
                d = 1
            d = max(d, 1)
            title = re.sub(r"^#{1,6}\s+", "", payload).strip() if isinstance(payload, str) else "table"
            stack = stack[:d - 1] + [title]
            text, table = (title, None) if isinstance(payload, str) else (None, payload)
            if table is not None:
                text = "\n".join(" | ".join(r) for r in table)
            sec = list(stack)
        elif kind == "table":
            table = payload if isinstance(payload, list) else []
            cap = payload if isinstance(payload, str) else ""
            text = "\n".join(" | ".join(r) for r in table)
            table = {"rows": table, "caption": cap or None}
            sec = list(stack)
        else:
            text, table = payload, None
            sec = list(stack)
        if pg is None:
            pg = chars // PAGE_LEN + 1
        if kind.startswith("heading"):
            k = "heading"
        elif kind == "list_item":
            k = "list_item"
        elif isinstance(table, dict):
            k = "table"
        else:
            k = "paragraph"
        blocks.append({"id": "B-%04d" % (i + 1), "kind": k, "page": pg, "section_path": sec, "text": text, "table": table, "language": detect_language(text or "")})
        chars += len(text or "")
    ntext = "\n\n".join(b["text"] or "" for b in blocks)
    off = 0
    for b in blocks:
        t = b["text"] or ""
        j = ntext.find(t, off)
        b["char_start"] = j if j >= 0 else off
        b["char_end"] = (j if j >= 0 else off) + len(t)
        off = b["char_end"]
    for b in blocks:
        if b["kind"] == "table" and b["table"] is None:
            b["table"] = {"rows": [], "caption": None}
        if b["table"] is None:
            b["table"] = None
    if not blocks:
        lims.append("no text blocks extracted")
    status = "ok" if blocks and not any("not installed" in l or "no text" in l or "image input" in l for l in lims) else ("unreliable" if lims else "ok")
    if not blocks:
        status = "unreliable"
    struct = {"blocks": blocks, "normalized_text": ntext, "extraction_status": status, "limitations": lims}
    save_json(os.path.join(outdir, "document_structure.json"), struct)
    with open(os.path.join(outdir, "normalized_source.txt"), "w", encoding="utf-8") as f:
        f.write(ntext)
    print("ingest: %d blocks, status=%s -> %s" % (len(blocks), status, outdir))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))

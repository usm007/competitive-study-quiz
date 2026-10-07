# Environment notes

Recorded for this skill (Windows authoring host).

- OS: Windows; Python 3.12.10.
- Available (installed for this skill): reportlab 5.0.1, pillow, openpyxl, pypdf 6.19.0, pymupdf 1.28.2 (optional: real glyph-box margin scan in check_pdf.py + page rendering for visual inspection; check degrades gracefully without it).
- Font: Nirmala.ttc (Devanagari + Bengali/Assamese) at `C:\Windows\Fonts\Nirmala.ttc` — used and embedded for PDF body text (verified in e2e: NirmalaUI-0 + NirmalaUI-Bold-1 embedded).
- NOT available: pdfplumber, python-docx, python-pptx, bs4, jsonschema, tesseract (confirmed absent via Get-Command).
- Consequences: DOCX/PPTX/HTML parsed with stdlib (zipfile/xml/html.parser); schemas validated with bundled mini-validator (now with patternProperties support); OCR without tesseract degrades to `extraction_status=unreliable` + STATUS LIMITED (tested).
- Font: Nirmala.ttc (Devanagari + Bengali/Assamese) at `C:\Windows\Fonts\Nirmala.ttc` — use for PDF Indic text.
- NOT available: pdfplumber, python-docx, python-pptx, bs4, jsonschema, tesseract (confirmed absent via Get-Command).
- Consequences: DOCX/PPTX/HTML parsed with stdlib (zipfile/xml/html.parser); schemas validated with bundled mini-validator (no `jsonschema` dep); OCR without tesseract degrades to `extraction_status=unreliable` + STATUS LIMITED.

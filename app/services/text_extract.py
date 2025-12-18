from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def normalize_text(text: str) -> str:
    text = _CONTROL_RE.sub("", text or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_pdf(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    parts: list[str] = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        parts.append(page.get_text("text"))
    return normalize_text("\n".join(parts))


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".txt":
        return normalize_text(file_path.read_text(encoding="utf-8", errors="replace"))
    if suffix == ".pdf":
        return extract_text_from_pdf(file_path)
    return normalize_text(file_path.read_text(encoding="utf-8", errors="replace"))


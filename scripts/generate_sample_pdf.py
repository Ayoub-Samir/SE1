from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


def main() -> None:
    out_dir = Path("samples")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "revizyon_talebi_ornek.pdf"

    doc = fitz.open()
    page = doc.new_page()
    text = (
        "YATIRIM PROGRAMI REVİZYON TALEBİ\n\n"
        "Proje Kodu: 2024-123456\n"
        "Talep Tutarı: 1.500.000 TL\n\n"
        "Gerekçe:\n"
        "Metro modernizasyon projesinde ihale sürecinde oluşan fiyat farkları ve\n"
        "ek güvenlik gereksinimleri nedeniyle ödenek revizyonuna ihtiyaç duyulmuştur.\n"
        "Revizyon, iş programını aksatmadan tamamlanabilmesi için kritiktir.\n"
    )
    page.insert_text((72, 72), text, fontsize=12)
    doc.save(pdf_path)
    print(f"OK: {pdf_path}")


if __name__ == "__main__":
    main()


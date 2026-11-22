"""OCR pages of a PDF with Tesseract, for documents whose text cannot be extracted (scanned
pages, or old Marathi fonts that extract as garbage, like MPKV's Krishidarshani).

Needs Tesseract (Windows: winget install UB-Mannheim.TesseractOCR) and the Marathi / Hindi
models from https://github.com/tesseract-ocr/tessdata_best in a tessdata folder (default
backend/data/tessdata, git-ignored), plus PyMuPDF (pip install pymupdf).

    python tools/ocr_pdf.py book.pdf out_dir 184 186            # pages 184-186 -> out_dir/p184.txt ...
    python tools/ocr_pdf.py book.pdf out_dir 1 20 --lang mar+eng

Pages already in out_dir are skipped, so a long run can be resumed. Check OCR text against
the PDF before adding it as a document (manage.py add-document), then approve it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("first", type=int)
    ap.add_argument("last", type=int)
    ap.add_argument("--lang", default="mar+eng")
    ap.add_argument("--dpi", type=int, default=250)
    ap.add_argument("--tessdata", type=Path, default=ROOT / "backend" / "data" / "tessdata")
    ap.add_argument("--tesseract", default=shutil.which("tesseract") or str(DEFAULT_TESSERACT))
    args = ap.parse_args()

    import fitz  # PyMuPDF

    args.out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(args.pdf))
    for pno in range(args.first, min(args.last, doc.page_count) + 1):
        txt = args.out / f"p{pno:03d}.txt"
        if txt.exists():
            continue
        png = args.out / f"p{pno:03d}.png"
        doc[pno - 1].get_pixmap(dpi=args.dpi).save(png)
        try:
            subprocess.run(
                [args.tesseract, str(png), str(txt.with_suffix("")), "--tessdata-dir", str(args.tessdata), "-l", args.lang, "--psm", "3"],
                check=True,
                capture_output=True,
            )
        finally:
            png.unlink(missing_ok=True)
        print(f"page {pno} -> {txt}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

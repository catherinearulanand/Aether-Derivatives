"""Render the synthetic Credit Support Annex to a native PDF.

    python scripts/build_csa_pdf.py

Produces ``fixtures/documents/csa_meridian_2026.pdf``, a **native** PDF with a real
text layer — the format a legal document actually arrives in. The Legal-Clause Agent
reads it through :func:`aether.agents.legal_clause.load_document`, which extracts the
text layer with ``pypdf`` and then follows exactly the same path as the markdown
source.

Scanned documents — an image with no text layer — remain out of scope, and the
methodology endpoint says so. Extracting those needs a vision model call, and a
hand-authored "OCR result" would be a fabrication rather than a capability.

Reuses the renderer from ``build_docs_pdf.py`` so there is one PDF pipeline, not two.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_docs_pdf import build_html, find_browser, render_pdf  # noqa: E402

SOURCE = ROOT / "fixtures" / "documents" / "csa_meridian_2026.md"
TARGET = ROOT / "fixtures" / "documents" / "csa_meridian_2026.pdf"


def main() -> int:
    if not SOURCE.exists():
        sys.exit(f"Source document not found: {SOURCE}")

    browser = find_browser()
    print(f"\n  Renderer: {browser.name}")

    work = ROOT / "fixtures" / "documents" / "_html"
    work.mkdir(exist_ok=True)
    try:
        title, html = build_html(SOURCE, "Simulated legal document — not a real agreement")
        html_path = work / "csa.html"
        html_path.write_text(html, encoding="utf-8")

        TARGET.unlink(missing_ok=True)
        render_pdf(browser, html_path, TARGET)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    size_kb = TARGET.stat().st_size / 1024
    print(f"  OK    {TARGET.relative_to(ROOT).as_posix()}  ({size_kb:.1f} KB)  {title}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(TARGET))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        print(f"  Text layer: {len(reader.pages)} pages, {len(text):,} characters extracted")
        marker = "Minimum Transfer Amount"
        print(f"  Sanity: {marker!r} present -> {marker in text}")
    except ImportError:
        print("  pypdf is not installed, so the text layer was not verified.")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

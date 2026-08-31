# renderers/pymupdf_fallback.py
"""PyMuPDF fallback renderer for non-macOS platforms."""

import fitz
from pathlib import Path


def render_pages(pdf_path: str, output_dir: str, dpi: int = 150,
                 pages: list[int] | None = None) -> dict[int, str]:
    """Render PDF pages using PyMuPDF.

    Args:
        pdf_path: Path to input PDF
        output_dir: Directory to write PNG files
        dpi: Resolution for rendering
        pages: 0-based page numbers to render. None = all pages.

    Returns:
        Dict mapping 0-based page_num to PNG file path.
    """
    doc = fitz.open(pdf_path)
    output_path = Path(output_dir)
    results = {}

    page_indices = pages if pages is not None else list(range(len(doc)))

    for page_num in page_indices:
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        png_path = output_path / f"page_{page_num + 1:03d}.png"
        pix.save(str(png_path))
        results[page_num] = str(png_path)

    doc.close()
    return results

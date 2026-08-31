# renderers/__init__.py
"""PDF page renderer — CoreGraphics on macOS, PyMuPDF fallback elsewhere."""

from .coregraphics import is_coregraphics_available


def render_pdf_pages(pdf_path: str, output_dir: str, dpi: int = 150,
                     pages: list[int] | None = None) -> dict[int, str]:
    """Render PDF pages to PNG files.

    Uses CoreGraphics (via pdf2png) on macOS for best CID font support.
    Falls back to PyMuPDF on other platforms.

    Args:
        pdf_path: Path to input PDF
        output_dir: Directory to write PNG files
        dpi: Resolution for rendering
        pages: 0-based page numbers to render. None = all pages.

    Returns:
        Dict mapping 0-based page_num to PNG file path.
    """
    if is_coregraphics_available():
        from .coregraphics import render_pages
    else:
        from .pymupdf_fallback import render_pages

    return render_pages(pdf_path, output_dir, dpi, pages)

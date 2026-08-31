# tests/test_renderer.py
import sys
import platform
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_test_pdf(path, num_pages=1):
    """Helper: create a simple test PDF with PyMuPDF."""
    import fitz
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((50, 100), f"Test page {i + 1}")
    doc.save(str(path))
    doc.close()


def test_render_pdf_pages_returns_dict_of_paths(tmp_path):
    """render_pdf_pages should return a dict mapping page_num to PNG path."""
    from renderers import render_pdf_pages

    pdf_path = tmp_path / "test.pdf"
    _make_test_pdf(pdf_path, 1)
    output_dir = tmp_path / "pages"
    output_dir.mkdir()

    result = render_pdf_pages(str(pdf_path), str(output_dir), dpi=72)

    assert isinstance(result, dict)
    assert len(result) == 1
    assert 0 in result  # 0-based page_num
    assert Path(result[0]).exists()
    assert Path(result[0]).suffix == ".png"


def test_render_pdf_pages_multi_page(tmp_path):
    """Multi-page PDF should return corresponding number of PNGs."""
    from renderers import render_pdf_pages

    pdf_path = tmp_path / "multi.pdf"
    _make_test_pdf(pdf_path, 3)
    output_dir = tmp_path / "pages"
    output_dir.mkdir()

    result = render_pdf_pages(str(pdf_path), str(output_dir), dpi=72)

    assert len(result) == 3
    for page_num in range(3):
        assert page_num in result
        assert Path(result[page_num]).exists()


def test_render_pdf_pages_with_page_filter(tmp_path):
    """When pages parameter is given, only those pages should be rendered."""
    from renderers import render_pdf_pages

    pdf_path = tmp_path / "multi.pdf"
    _make_test_pdf(pdf_path, 5)
    output_dir = tmp_path / "pages"
    output_dir.mkdir()

    # Only render pages 0 and 2 (0-based)
    result = render_pdf_pages(str(pdf_path), str(output_dir), dpi=72, pages=[0, 2])

    assert len(result) == 2
    assert 0 in result
    assert 2 in result
    assert 1 not in result


def test_fallback_to_pymupdf_when_cg_unavailable(tmp_path):
    """When CoreGraphics is unavailable, should fallback to PyMuPDF."""
    from renderers import render_pdf_pages

    pdf_path = tmp_path / "test.pdf"
    _make_test_pdf(pdf_path, 1)
    output_dir = tmp_path / "pages"
    output_dir.mkdir()

    with patch('renderers.coregraphics.is_coregraphics_available', return_value=False):
        result = render_pdf_pages(str(pdf_path), str(output_dir), dpi=72)

    assert len(result) == 1
    assert Path(result[0]).exists()


def test_is_coregraphics_available_on_macos():
    """macOS with pdf2png binary should return True."""
    from renderers.coregraphics import is_coregraphics_available

    if platform.system() == "Darwin":
        pdf2png_path = Path(__file__).parent.parent / "pdf2png"
        assert is_coregraphics_available() == pdf2png_path.exists()
    else:
        assert is_coregraphics_available() is False


def test_rendered_png_is_valid_image(tmp_path):
    """Rendered PNG should be a valid image with reasonable size."""
    from renderers import render_pdf_pages

    pdf_path = tmp_path / "letter.pdf"
    _make_test_pdf(pdf_path, 1)
    output_dir = tmp_path / "pages"
    output_dir.mkdir()

    result = render_pdf_pages(str(pdf_path), str(output_dir), dpi=150)
    png_path = Path(result[0])

    # Verify PNG magic bytes
    with open(png_path, "rb") as f:
        header = f.read(8)
    assert header[:4] == b'\x89PNG'
    assert png_path.stat().st_size > 1024

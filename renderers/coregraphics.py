# renderers/coregraphics.py
"""CoreGraphics PDF renderer via pdf2png CLI (macOS only)."""

import platform
import subprocess
from pathlib import Path

_PDF2PNG_PATH = Path(__file__).parent.parent / "pdf2png"


def is_coregraphics_available() -> bool:
    """Check if CoreGraphics rendering is available (macOS + pdf2png binary)."""
    return platform.system() == "Darwin" and _PDF2PNG_PATH.exists()


def render_pages(pdf_path: str, output_dir: str, dpi: int = 150,
                 pages: list[int] | None = None) -> dict[int, str]:
    """Render PDF pages using CoreGraphics.

    Args:
        pdf_path: Path to input PDF
        output_dir: Directory to write PNG files
        dpi: Resolution for rendering
        pages: 0-based page numbers to render. None = all pages.

    Returns:
        Dict mapping 0-based page_num to PNG file path.

    Raises:
        RuntimeError: If pdf2png fails
    """
    cmd = [str(_PDF2PNG_PATH), pdf_path, output_dir, str(dpi)]

    # pdf2png uses 1-based page numbers
    if pages is not None:
        page_str = ",".join(str(p + 1) for p in pages)
        cmd.append(page_str)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"pdf2png failed: {result.stderr}")

    output_path = Path(output_dir)
    rendered = {}
    for png_file in sorted(output_path.glob("page_*.png")):
        # page_001.png -> page_num 0
        page_num = int(png_file.stem.split("_")[1]) - 1
        rendered[page_num] = str(png_file)

    return rendered

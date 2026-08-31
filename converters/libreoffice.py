"""LibreOffice-based converters for doc2md."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def convert_via_libreoffice(input_path, output_dir, config, args):
    """Convert non-PDF files via LibreOffice to PDF, then process."""
    lo_path = config.get("libreoffice_path",
                         "/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if not os.path.exists(lo_path):
        print(f"Error: LibreOffice not found at {lo_path}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [lo_path, '--headless', '--convert-to', 'pdf',
               '--outdir', tmpdir, str(input_path)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            print(f"Error: LibreOffice conversion timed out for {input_path}", file=sys.stderr)
            return False

        # Find the converted PDF
        pdf_files = list(Path(tmpdir).glob("*.pdf"))
        if not pdf_files:
            print(f"Error: LibreOffice conversion failed for {input_path}", file=sys.stderr)
            return False

        # Lazy import to avoid circular dependency
        from converters.pdf import convert_pdf_to_md
        return convert_pdf_to_md(pdf_files[0], output_dir, config, args)


def convert_via_libreoffice_then_native(input_path, output_dir, config, args,
                                        target_fmt, native_converter):
    """Convert legacy format to modern format via LibreOffice, then use native parser.
    e.g. .doc -> .docx -> python-docx, .ppt -> .pptx -> python-pptx."""
    lo_path = config.get("libreoffice_path",
                         "/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if not os.path.exists(lo_path):
        print(f"Error: LibreOffice not found at {lo_path}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [lo_path, '--headless', '--convert-to', target_fmt,
               '--outdir', tmpdir, str(input_path)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            print(f"Error: LibreOffice conversion timed out for {input_path}", file=sys.stderr)
            return False

        converted = list(Path(tmpdir).glob(f"*.{target_fmt}"))
        if not converted:
            print(f"Error: LibreOffice conversion to .{target_fmt} failed for {input_path}",
                  file=sys.stderr)
            return False

        # Use native converter, but override source_file name to show original
        result = native_converter(converted[0], output_dir, config, args)

        # Rename output to use original filename (not the temp converted name)
        if result:
            orig_stem = Path(input_path).stem
            temp_stem = converted[0].stem
            if orig_stem != temp_stem:
                old_md = output_dir / f"{temp_stem}.md"
                new_md = output_dir / f"{orig_stem}.md"
                if old_md.exists():
                    old_md.rename(new_md)

            # Fix source_file in frontmatter to show original filename
            final_md = output_dir / f"{orig_stem}.md"
            if final_md.exists():
                content = final_md.read_text(encoding='utf-8')
                content = content.replace(
                    f'source_file: "{converted[0].name}"',
                    f'source_file: "{Path(input_path).name}"'
                )
                final_md.write_text(content, encoding='utf-8')

        return result

#!/usr/bin/python3
"""
doc2md - Universal Document to Markdown Converter
Converts PDF, DOC, DOCX, ODT, ODS, RTF, PPT, PPTX files to clean Markdown.

Usage:
    python doc2md.py input.pdf
    python doc2md.py input.docx -o /path/to/output/
    python doc2md.py /path/to/folder/ -o /path/to/output/
    python doc2md.py input.pdf --config my_config.json
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from utils import VERSION
from vlm_describer import DEFAULT_VLM_MODEL
from converters import SUPPORTED_FORMATS, CONVERTER_MAP
from profiles import load_profile, list_profiles


# ─── Default configuration ───────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "output_dir": "./output",
    "frontmatter": {
        "include": True,
        "fields": ["source_file", "title", "pages", "converted_date", "tool_version"]
    },
    "images": {
        "extract": True,
        "min_width": 100,
        "min_height": 100,
        "format": "png",
        "subfolder": "images"
    },
    "tables": {
        "extract": True,
        "fallback_to_image": True
    },
    "text": {
        "heading_detection": True,
        "remove_headers_footers": True,
        "remove_page_numbers": True,
        "body_font_size_tolerance": 0.5
    },
    "libreoffice_path": "/Applications/LibreOffice.app/Contents/MacOS/soffice"
}


def load_config(config_path=None):
    """Load configuration from JSON file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            # Deep merge
            for key, value in user_config.items():
                if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                    config[key].update(value)
                else:
                    config[key] = value
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config from {config_path}: {e}", file=sys.stderr)
    return config


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="doc2md — Universal Document to Markdown Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python doc2md.py paper.pdf
  python doc2md.py paper.pdf -o ./output/
  python doc2md.py /path/to/folder/ --ext .pdf .docx
  python doc2md.py slides.pdf --presentation
  python doc2md.py paper.pdf --render-pages --render-dpi 200
  python doc2md.py --inbox
  python doc2md.py --inbox --clean
  python doc2md.py --inbox --ext .pdf --no-images
"""
    )
    parser.add_argument('input', nargs='?', default=None, help='Input file or directory')
    parser.add_argument('--inbox', action='store_true',
                        help='Process all files in Inbox/, output to Output/')
    parser.add_argument('--clean', action='store_true',
                        help='Move successfully converted Inbox files to Inbox/_done/')
    parser.add_argument('-o', '--output', help='Output directory')
    parser.add_argument('--config', help='Path to config JSON file')
    parser.add_argument('--ext', nargs='+', help='Filter by extensions (e.g. .pdf .docx)')
    parser.add_argument('--no-images', action='store_true', help='Skip image extraction')
    parser.add_argument('--no-tables', action='store_true', help='Skip table extraction')
    parser.add_argument('--no-frontmatter', action='store_true', help='Skip YAML frontmatter')
    parser.add_argument('--presentation', action='store_true', help='Force presentation mode')
    parser.add_argument('--render-pages', action='store_true', help='Render each page as PNG')
    parser.add_argument('--render-dpi', type=int, default=150, help='DPI for page rendering (default: 150)')
    parser.add_argument('--vlm', action='store_true',
                        help='Use VLM to describe figures/schemes/tables')
    parser.add_argument('--vlm-model', default=DEFAULT_VLM_MODEL,
                        help=f'VLM model (default: {DEFAULT_VLM_MODEL})')
    parser.add_argument('--vlm-dpi', type=int, default=150,
                        help='DPI for VLM page rendering (default: 150)')
    parser.add_argument('--vlm-pages', metavar='RANGE',
                        help='VLM page range, e.g. 1-5,10,15-20 (default: all pages)')
    parser.add_argument('--split', action='store_true',
                        help='轉換完成後自動拆分 Markdown 成多個章節檔案（產出 _TOC.md）')
    parser.add_argument('--split-level', type=int, default=None, choices=[1, 2, 3],
                        help='--split 的拆分標題層級（1/2/3）。與 --split-pattern 互斥')
    parser.add_argument('--split-pattern', metavar='PATTERN',
                        help='--split 的 regex 或 shortcut（chinese/numbered/chapter）。與 --split-level 互斥')
    # Profile system (v0.10.0)
    available_profiles = list_profiles()
    parser.add_argument('--profile', default='journal',
                        choices=available_profiles if available_profiles else None,
                        metavar='PROFILE',
                        help=f'Conversion profile (default: journal). Available: {", ".join(available_profiles)}')
    parser.add_argument('--version', action='version', version=f'doc2md v{VERSION}')
    return parser.parse_args()


def get_output_path(input_path, output_dir=None):
    """Determine output directory for a given input file."""
    stem = Path(input_path).stem
    if output_dir:
        base = Path(output_dir)
    else:
        base = Path(input_path).parent
    out = base / stem
    out.mkdir(parents=True, exist_ok=True)
    return out


def _run_splitter(md_path: Path, level: int = None, pattern: str = None):
    """Import md_splitter and split the converted Markdown file.

    Looks for md_splitter.py alongside this file first, then one level up
    (supports both a self-contained checkout and a shared tools directory).
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent):
        if (candidate / "md_splitter.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            break
    try:
        import md_splitter
        md_splitter.split_and_export(input_path=md_path, level=level, pattern=pattern)
    except Exception as e:
        print(f"  Warning: split failed for {md_path.name}: {e}", file=sys.stderr)


def main():
    """Main entry point."""
    args = parse_args()

    # Load config
    config_path = args.config
    if not config_path:
        # Check for config.json next to script
        script_dir = Path(__file__).parent
        default_config = script_dir / "config.json"
        if default_config.exists():
            config_path = str(default_config)
    config = load_config(config_path)

    # Load profile (v0.10.0)
    profile_name = getattr(args, 'profile', 'journal') or 'journal'
    args.profile_data = load_profile(profile_name)

    # Override config with CLI flags
    if args.no_images:
        config.setdefault("images", {})["extract"] = False
    if args.no_tables:
        config.setdefault("tables", {})["extract"] = False
    if args.no_frontmatter:
        config.setdefault("frontmatter", {})["include"] = False

    # Collect files to process
    inbox_dir = None
    files_to_process = []

    if args.inbox:
        script_dir = Path(__file__).parent
        inbox_dir = (script_dir / "Inbox").resolve()
        output_base = (script_dir / "Output").resolve()
        inbox_dir.mkdir(exist_ok=True)
        output_base.mkdir(exist_ok=True)
        args.output = str(output_base)

        allowed_exts = set(args.ext) if args.ext else set(SUPPORTED_FORMATS.keys())
        for f in sorted(inbox_dir.iterdir()):
            if f.is_file() and not f.name.startswith('.') and f.suffix.lower() in allowed_exts:
                files_to_process.append(f)

        if not files_to_process:
            print("Inbox is empty — nothing to convert.", file=sys.stderr)
            sys.exit(0)

        print(f"Inbox: {len(files_to_process)} file(s) to process", file=sys.stderr)
    else:
        if not args.input:
            print("Error: input path is required (or use --inbox)", file=sys.stderr)
            sys.exit(1)

        input_path = Path(args.input).resolve()

        if not input_path.exists():
            print(f"Error: {input_path} does not exist", file=sys.stderr)
            sys.exit(1)

        if input_path.is_dir():
            allowed_exts = set(args.ext) if args.ext else set(SUPPORTED_FORMATS.keys())
            for f in sorted(input_path.rglob('*')):
                if f.is_file() and f.suffix.lower() in allowed_exts:
                    files_to_process.append(f)
            print(f"Found {len(files_to_process)} files to process", file=sys.stderr)
        else:
            files_to_process.append(input_path)

        if not files_to_process:
            print("No supported files found.", file=sys.stderr)
            sys.exit(1)

    # Process each file
    success_count = 0
    fail_count = 0

    for filepath in files_to_process:
        ext = filepath.suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            print(f"Skipping unsupported format: {filepath}", file=sys.stderr)
            continue

        output_dir = get_output_path(filepath, args.output)
        fmt_type = SUPPORTED_FORMATS[ext]

        try:
            converter = CONVERTER_MAP.get(fmt_type)
            if converter:
                result = converter(filepath, output_dir, config, args)
            else:
                result = False

            if result:
                success_count += 1
                if getattr(args, 'split', False):
                    md_file = output_dir / f"{filepath.stem}.md"
                    if md_file.exists():
                        _run_splitter(
                            md_file,
                            level=getattr(args, 'split_level', None),
                            pattern=getattr(args, 'split_pattern', None),
                        )
                    else:
                        print(f"  Warning: could not find {md_file.name} for splitting", file=sys.stderr)
                if args.inbox and args.clean and inbox_dir:
                    done_dir = inbox_dir / "_done"
                    done_dir.mkdir(exist_ok=True)
                    shutil.move(str(filepath), str(done_dir / filepath.name))
                    print(f"  Moved to _done/: {filepath.name}", file=sys.stderr)
            else:
                fail_count += 1
        except Exception as e:
            print(f"Error processing {filepath}: {e}", file=sys.stderr)
            fail_count += 1

    # Summary
    total = success_count + fail_count
    if total > 1:
        print(f"\nDone: {success_count}/{total} succeeded", file=sys.stderr)
    elif success_count == 1:
        print("Done.", file=sys.stderr)

    sys.exit(0 if fail_count == 0 else 1)


if __name__ == '__main__':
    main()

"""Plaintext/CSV/TSV to Markdown converter for doc2md."""

import sys
from datetime import datetime
from pathlib import Path

from utils import VERSION
from utils.tables import format_table_as_markdown


def convert_plaintext(input_path, output_dir, config, args):
    """Convert plaintext/CSV/TSV files directly to Markdown."""
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(input_path, 'r', encoding='latin-1') as f:
            content = f.read()

    ext = Path(input_path).suffix.lower()

    if ext in ('.csv', '.tsv'):
        delimiter = ',' if ext == '.csv' else '\t'
        lines = content.strip().split('\n')
        if lines:
            rows = [line.split(delimiter) for line in lines]
            md_table = format_table_as_markdown(rows)
            content = md_table

    # Frontmatter
    frontmatter = ""
    if not args.no_frontmatter and config.get("frontmatter", {}).get("include", True):
        fm_lines = ["---"]
        fm_lines.append(f"source_file: \"{Path(input_path).name}\"")
        fm_lines.append(f"converted_date: \"{datetime.now().strftime('%Y-%m-%d %H:%M')}\"")
        fm_lines.append(f"tool_version: \"{VERSION}\"")
        fm_lines.append("---")
        fm_lines.append("")
        frontmatter = '\n'.join(fm_lines)

    final_md = frontmatter + content
    if not final_md.endswith('\n'):
        final_md += '\n'

    md_filename = Path(input_path).stem + '.md'
    md_path = output_dir / md_filename
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(final_md)

    print(f"  Output: {md_path}", file=sys.stderr)
    return True

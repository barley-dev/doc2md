"""HTML to Markdown converter for doc2md."""

import re
import sys
from datetime import datetime
from pathlib import Path

from utils import VERSION


def convert_html_native(input_path, output_dir, config, args):
    """直接將 HTML 轉為 Markdown，保留語意結構。"""
    try:
        from markdownify import markdownify as md
    except ImportError:
        print("Error: markdownify is required. Install with: pip install markdownify", file=sys.stderr)
        return False

    try:
        # Try UTF-8 first, fallback to latin-1
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except UnicodeDecodeError:
            with open(input_path, 'r', encoding='latin-1') as f:
                html_content = f.read()
    except Exception as e:
        print(f"Error reading {input_path}: {e}", file=sys.stderr)
        return False

    print(f"Processing: {input_path}", file=sys.stderr)

    # Convert HTML to Markdown
    full_md = md(html_content, heading_style="ATX", strip=['script', 'style', 'meta', 'link'])

    # Clean up
    full_md = re.sub(r'\n{3,}', '\n\n', full_md)
    full_md = full_md.strip() + '\n'

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

    final_md = frontmatter + full_md

    md_filename = Path(input_path).stem + '.md'
    md_path = output_dir / md_filename
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(final_md)

    print(f"  Output: {md_path}", file=sys.stderr)
    return True

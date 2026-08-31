"""Table formatting utilities for doc2md."""

import sys
from datetime import datetime
from pathlib import Path

from utils import VERSION


def format_table_as_markdown(table_data):
    """Convert a 2D table array to Markdown table format.

    Handles journal PDFs where the column header spans multiple PDF rows due to
    subscripts / superscripts: all rows before the first row with a non-empty
    first cell are merged into a single header row.  Fully empty rows are
    dropped so they cannot produce spurious '| --- |\\n|  |' patterns.
    """
    if not table_data or not table_data[0]:
        return ""

    # Clean cells and drop fully empty rows
    cleaned = []
    for row in table_data:
        cleaned_row = [cell.strip().replace('\n', ' ') if cell else '' for cell in row]
        if any(cleaned_row):
            cleaned.append(cleaned_row)

    if not cleaned:
        return ""

    # Find the first row whose first cell is non-empty (= first data row).
    # All rows before it are header fragments to be merged.
    first_data_idx = 1  # default: first row is the header
    for i, row in enumerate(cleaned):
        if row[0] and row[0].strip():
            first_data_idx = i
            break

    ncols = len(cleaned[0])

    # Merge header fragment rows column-by-column
    merged_header = [''] * ncols
    for row in cleaned[:first_data_idx]:
        for j, cell in enumerate(row):
            if j < ncols and cell:
                merged_header[j] = (merged_header[j] + ' ' + cell).strip()

    lines = ['| ' + ' | '.join(merged_header) + ' |']
    lines.append('| ' + ' | '.join(['---'] * ncols) + ' |')

    for row in cleaned[first_data_idx:]:
        # Pad or trim to match header length
        while len(row) < ncols:
            row.append('')
        lines.append('| ' + ' | '.join(row[:ncols]) + ' |')

    return '\n'.join(lines)


def _format_cell_value(val):
    """Format a cell value to string for Markdown output."""
    if val is None or val == '':
        return ''
    elif isinstance(val, bool):
        return 'TRUE' if val else 'FALSE'
    elif isinstance(val, datetime):
        return val.strftime('%Y-%m-%d')
    elif isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    else:
        return str(val).replace('\n', ' ').replace('|', '\\|')


def _sheets_to_markdown(input_path, output_dir, config, args, sheets_data):
    """Shared logic: convert list of (sheet_name, all_rows) to Markdown file.
    Returns True on success."""
    md_parts = []
    sheets_output = 0

    for sheet_name, all_rows in sheets_data:
        # Strip trailing empty rows
        while all_rows and all(c == '' for c in all_rows[-1]):
            all_rows.pop()

        # Find first non-empty row as header
        header_idx = None
        for i, row in enumerate(all_rows):
            if any(c != '' for c in row):
                header_idx = i
                break

        if header_idx is None:
            print(f"  Sheet '{sheet_name}': empty, skipped", file=sys.stderr)
            continue

        data_rows = all_rows[header_idx:]
        if not data_rows:
            continue

        # Determine max columns and pad rows
        max_cols = max(len(r) for r in data_rows)
        for r in data_rows:
            while len(r) < max_cols:
                r.append('')

        # Build markdown table
        header = data_rows[0]
        table_lines = ['| ' + ' | '.join(header) + ' |']
        table_lines.append('| ' + ' | '.join(['---'] * max_cols) + ' |')
        for row in data_rows[1:]:
            table_lines.append('| ' + ' | '.join(row) + ' |')

        md_parts.append(f'## Sheet: {sheet_name}')
        md_parts.append('')
        md_parts.append('\n'.join(table_lines))
        md_parts.append('')

        sheets_output += 1
        print(f"  Sheet '{sheet_name}': {len(data_rows)-1} data rows, {max_cols} columns", file=sys.stderr)

    if sheets_output == 0:
        print(f"  Warning: no data found in {input_path}", file=sys.stderr)
        return False

    # Frontmatter
    frontmatter = ""
    if not args.no_frontmatter and config.get("frontmatter", {}).get("include", True):
        fm_lines = ["---"]
        fm_lines.append(f"source_file: \"{Path(input_path).name}\"")
        fm_lines.append(f"sheets: {sheets_output}")
        fm_lines.append(f"converted_date: \"{datetime.now().strftime('%Y-%m-%d %H:%M')}\"")
        fm_lines.append(f"tool_version: \"{VERSION}\"")
        fm_lines.append("---")
        fm_lines.append("")
        frontmatter = '\n'.join(fm_lines)

    final_md = frontmatter + '\n'.join(md_parts)
    if not final_md.endswith('\n'):
        final_md += '\n'

    md_filename = Path(input_path).stem + '.md'
    md_path = output_dir / md_filename
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(final_md)

    print(f"  Output: {md_path}", file=sys.stderr)
    return True

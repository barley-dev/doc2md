"""ODF (ODS/ODT) to Markdown converter for doc2md."""

import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from utils import VERSION
from utils.tables import _format_cell_value, _sheets_to_markdown


def convert_ods_native(input_path, output_dir, config, args):
    """直接讀取 .ods (OpenDocument Spreadsheet)，不依賴外部套件。"""
    ODF_NS = {
        'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
        'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
        'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    }

    try:
        with zipfile.ZipFile(str(input_path), 'r') as zf:
            content_xml = zf.read('content.xml')
    except Exception as e:
        print(f"Error opening {input_path}: {e}", file=sys.stderr)
        return False

    root = ET.fromstring(content_xml)
    body = root.find('.//office:body/office:spreadsheet', ODF_NS)
    if body is None:
        print(f"Error: no spreadsheet data in {input_path}", file=sys.stderr)
        return False

    tables = body.findall('table:table', ODF_NS)
    print(f"Processing: {input_path} ({len(tables)} sheets)", file=sys.stderr)

    sheets_data = []
    for table in tables:
        sheet_name = table.get(f'{{{ODF_NS["table"]}}}name', 'Sheet')

        all_rows = []
        for row_elem in table.findall('table:table-row', ODF_NS):
            # Handle table:number-rows-repeated (ODS optimization for empty rows)
            row_repeat = int(row_elem.get(f'{{{ODF_NS["table"]}}}number-rows-repeated', '1'))
            # Cap repeated empty rows to avoid memory issues
            if row_repeat > 100:
                row_repeat = 1

            cells = []
            for cell_elem in row_elem.findall('table:table-cell', ODF_NS):
                # Handle table:number-columns-repeated
                col_repeat = int(cell_elem.get(f'{{{ODF_NS["table"]}}}number-columns-repeated', '1'))
                if col_repeat > 100:
                    col_repeat = 1

                # Extract text content from all <text:p> children
                text_parts = []
                for p in cell_elem.findall('text:p', ODF_NS):
                    # Recursively get all text including child elements
                    text_parts.append(''.join(p.itertext()))
                cell_text = ' '.join(text_parts).strip().replace('|', '\\|')

                for _ in range(col_repeat):
                    cells.append(cell_text)

            row_data = [_format_cell_value(c) if c else '' for c in cells]

            for _ in range(row_repeat):
                all_rows.append(list(row_data))

        sheets_data.append((sheet_name, all_rows))

    return _sheets_to_markdown(input_path, output_dir, config, args, sheets_data)


def convert_odt_native(input_path, output_dir, config, args):
    """直接讀取 .odt (OpenDocument Text)，保留標題、段落、表格、列表。"""
    ODF_NS = {
        'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
        'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
        'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
        'style': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
        'fo': 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0',
    }

    try:
        with zipfile.ZipFile(str(input_path), 'r') as zf:
            content_xml = zf.read('content.xml')
    except Exception as e:
        print(f"Error opening {input_path}: {e}", file=sys.stderr)
        return False

    root = ET.fromstring(content_xml)
    body = root.find('.//office:body/office:text', ODF_NS)
    if body is None:
        print(f"Error: no text content in {input_path}", file=sys.stderr)
        return False

    print(f"Processing: {input_path}", file=sys.stderr)

    lines = []

    def _get_text(elem):
        """Recursively extract text from an element."""
        return ''.join(elem.itertext()).strip()

    for child in body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag

        if tag == 'h':
            # Heading: text:outline-level attribute
            level = int(child.get(f'{{{ODF_NS["text"]}}}outline-level', '2'))
            level = min(max(level, 1), 6)
            text = _get_text(child)
            if text:
                lines.append(f'{"#" * level} {text}')
                lines.append('')

        elif tag == 'p':
            text = _get_text(child)
            lines.append(text if text else '')
            if text:
                lines.append('')

        elif tag == 'list':
            # Process list items
            for item in child.findall('text:list-item', ODF_NS):
                for p in item.findall('text:p', ODF_NS):
                    text = _get_text(p)
                    if text:
                        lines.append(f'- {text}')
            lines.append('')

        elif tag == 'table':
            sheet_name = child.get(f'{{{ODF_NS["table"]}}}name', '')
            rows_data = []
            for row_elem in child.findall('table:table-row', ODF_NS):
                cells = []
                for cell_elem in row_elem.findall('table:table-cell', ODF_NS):
                    col_repeat = int(cell_elem.get(
                        f'{{{ODF_NS["table"]}}}number-columns-repeated', '1'))
                    if col_repeat > 100:
                        col_repeat = 1
                    cell_text = _get_text(cell_elem).replace('|', '\\|')
                    for _ in range(col_repeat):
                        cells.append(cell_text)
                rows_data.append(cells)

            # Strip trailing empty rows
            while rows_data and all(c == '' for c in rows_data[-1]):
                rows_data.pop()

            if rows_data and any(any(c for c in row) for row in rows_data):
                max_cols = max(len(r) for r in rows_data)
                for r in rows_data:
                    while len(r) < max_cols:
                        r.append('')

                header = rows_data[0]
                table_lines = ['| ' + ' | '.join(header) + ' |']
                table_lines.append('| ' + ' | '.join(['---'] * max_cols) + ' |')
                for row in rows_data[1:]:
                    table_lines.append('| ' + ' | '.join(row[:max_cols]) + ' |')
                lines.append('')
                lines.append('\n'.join(table_lines))
                lines.append('')

    full_md = '\n'.join(lines)
    full_md = re.sub(r'\n{3,}', '\n\n', full_md)
    if not full_md.endswith('\n'):
        full_md += '\n'

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

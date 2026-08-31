"""PDF to Markdown converter for doc2md."""

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from utils import VERSION
from utils.tables import format_table_as_markdown
from utils.text import filter_journal_noise, filter_noise, detect_language, post_process
from vlm_describer import DEFAULT_VLM_MODEL


def analyze_fonts(doc):
    """Analyze font usage across all pages to determine body text font size."""
    font_sizes = Counter()
    for page in doc:
        blocks = page.get_text("dict", flags=3)["blocks"]
        for block in blocks:
            if block["type"] != 0:  # text block
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    size = round(span["size"], 1)
                    text = span["text"].strip()
                    if text:
                        font_sizes[size] += len(text)
    if not font_sizes:
        return 10.0  # fallback
    # Body font = most common size by character count
    body_size = font_sizes.most_common(1)[0][0]
    return body_size


def detect_headings(blocks, body_size, tolerance=0.5, presentation_mode=False):
    """Detect heading levels based on font size relative to body text."""
    headings = {}  # (page, block_idx) -> heading level
    size_diff_threshold = 5.0 if presentation_mode else 1.5

    # Academic heading patterns
    heading_patterns = [
        re.compile(r'^(?:\d+\.)+\s'),           # "1. ", "1.1 ", "2.3.1 "
        re.compile(r'^(?:Abstract|Introduction|Conclusion|Discussion|Results|'
                   r'Experimental|Methods|References|Acknowledgment|Supporting\s+Information)',
                   re.IGNORECASE),
        re.compile(r'^(?:Scheme|Figure|Table)\s+\d+', re.IGNORECASE),
    ]

    for block in blocks:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = line["spans"]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text or len(text) <= 5:
                continue
            avg_size = sum(s["size"] * len(s["text"]) for s in spans if s["text"].strip()) / max(
                sum(len(s["text"]) for s in spans if s["text"].strip()), 1)
            avg_size = round(avg_size, 1)
            is_bold = any("Bold" in (s.get("font", "") or "") or
                         "bold" in (s.get("font", "") or "").lower()
                         for s in spans if s["text"].strip())

            size_diff = avg_size - body_size

            # Determine heading level
            level = 0
            if size_diff >= size_diff_threshold * 2:
                level = 1
            elif size_diff >= size_diff_threshold:
                level = 2
            elif size_diff >= tolerance and is_bold:
                level = 3
            elif is_bold and size_diff >= 0:
                # Check against academic patterns
                for pat in heading_patterns:
                    if pat.match(text):
                        level = 3
                        break

            if level > 0:
                bbox_key = (round(line["bbox"][0], 1), round(line["bbox"][1], 1))
                headings[bbox_key] = level

    return headings


def detect_headers_footers(doc):
    """Detect repeated headers and footers across pages by comparing text near top/bottom."""
    if len(doc) < 3:
        return set(), set()

    page_height = doc[0].rect.height
    header_zone = page_height * 0.08  # top 8%
    footer_zone = page_height * 0.92  # bottom 8%

    header_texts = []
    footer_texts = []

    for page in doc:
        blocks = page.get_text("dict", flags=3)["blocks"]
        h_texts = []
        f_texts = []
        for block in blocks:
            if block["type"] != 0:
                continue
            y0 = block["bbox"][1]
            y1 = block["bbox"][3]
            text = ""
            for line in block["lines"]:
                text += "".join(s["text"] for s in line["spans"])
            text = text.strip()
            if not text:
                continue
            if y0 < header_zone:
                h_texts.append(text)
            if y1 > footer_zone:
                f_texts.append(text)
        header_texts.append(h_texts)
        footer_texts.append(f_texts)

    # Find texts repeated on 50%+ of pages
    repeated_headers = set()
    repeated_footers = set()

    all_headers = Counter()
    all_footers = Counter()
    for texts in header_texts:
        for t in set(texts):
            all_headers[t] += 1
    for texts in footer_texts:
        for t in set(texts):
            all_footers[t] += 1

    threshold = len(doc) * 0.5
    for text, count in all_headers.items():
        if count >= threshold:
            repeated_headers.add(text)
    for text, count in all_footers.items():
        if count >= threshold:
            repeated_footers.add(text)

    return repeated_headers, repeated_footers


def _is_valid_table(data):
    """Return True if extracted table data looks like a real multi-column table."""
    if not data or len(data) < 2:
        return False
    if not data[0] or len(data[0]) < 2:
        return False
    content_rows = sum(1 for row in data if any(c and c.strip() for c in row))
    return content_rows >= 2


def _extract_tables_from_plumber_page(plumber_page):
    """Three-strategy table extraction for journal PDFs.

    Strategy 1 – Default pdfplumber (works for PDFs with explicit line objects).
    Strategy 2 – Rect-guided: uses filled rectangles as ruling lines to locate
                 table regions, then applies text+text strategy within a crop.
    Strategy 3 – Entry-anchored: detects the 'Entry' column header and builds
                 explicit column boundaries from the header-row word positions.
    """
    tables = []
    table_bboxes = []
    page_width = plumber_page.width
    page_height = plumber_page.height
    header_threshold = page_height * 0.15   # ignore tables in top 15%
    footer_threshold = page_height * 0.90   # ignore tables in bottom 10%

    # ── Strategy 1: default pdfplumber ──────────────────────────────────────
    try:
        found = plumber_page.find_tables()
        for t in found:
            data = t.extract()
            if not _is_valid_table(data):
                continue
            # Skip tables in the header zone (journal banners etc.)
            if t.bbox[1] < header_threshold:
                continue
            tables.append(data)
            table_bboxes.append(t.bbox)
        if tables:
            return tables, table_bboxes
    except Exception:
        pass

    # ── Strategy 2: rect-guided ──────────────────────────────────────────────
    # pdfplumber rects use 'top'/'bottom' for top-down coordinates.
    rects = plumber_page.rects
    ruling = sorted(
        [r for r in rects
         if (r['x1'] - r['x0']) >= 100
         and (r['bottom'] - r['top']) < 5
         and r['top'] > header_threshold
         and r['top'] < footer_threshold],
        key=lambda r: r['top']
    )

    if ruling:
        # Group horizontally-aligned rects (same table column)
        groups, current = [], [ruling[0]]
        for r in ruling[1:]:
            if (abs(r['x0'] - current[-1]['x0']) < 30
                    and abs(r['x1'] - current[-1]['x1']) < 30):
                current.append(r)
            else:
                groups.append(current)
                current = [r]
        groups.append(current)

        words = plumber_page.extract_words()
        text_text = {'vertical_strategy': 'text', 'horizontal_strategy': 'text'}

        for grp in groups:
            x0_g = min(r['x0'] for r in grp)
            x1_g = max(r['x1'] for r in grp)
            first_top = min(r['top'] for r in grp)
            last_bottom = max(r['bottom'] for r in grp)
            rect_width = x1_g - x0_g

            # Find standalone 'Table' caption above the rect group.
            # Wide rects (spanning multi-column layout) need page-wide search.
            if rect_width > page_width * 0.4:
                captions = [w for w in words
                            if w['text'] in ('Table', 'TABLE')
                            and w['top'] < first_top]
            else:
                captions = [w for w in words
                            if w['text'] in ('Table', 'TABLE')
                            and w['top'] < first_top
                            and w['x0'] >= x0_g - 30
                            and w['x0'] <= x1_g + 30]

            if not captions:
                continue

            cap_top = min(w['top'] for w in captions)
            cap_x0 = min(w['x0'] for w in captions if w['top'] == cap_top)

            # Limit crop to the column side where the caption lives.
            if rect_width > page_width * 0.4:
                if cap_x0 < page_width / 2:
                    crop_x0 = max(0, cap_x0 - 5)
                    crop_x1 = min(page_width / 2 + 10, x1_g + 5)
                else:
                    crop_x0 = max(0, x0_g - 5)
                    crop_x1 = min(page_width, x1_g + 5)
            else:
                crop_x0 = max(0, x0_g - 5)
                crop_x1 = min(page_width, x1_g + 5)

            try:
                crop = plumber_page.crop((
                    crop_x0,
                    max(0, cap_top - 5),
                    crop_x1,
                    min(page_height, last_bottom + 50),
                ))
                for t in crop.find_tables(table_settings=text_text):
                    data = t.extract()
                    if _is_valid_table(data):
                        tables.append(data)
                        table_bboxes.append(t.bbox)
            except Exception:
                pass

        if tables:
            return tables, table_bboxes

    # ── Strategy 3: Entry-anchored ───────────────────────────────────────────
    # Detects 'Entry' column header → infers column boundaries → explicit lines.
    words = plumber_page.extract_words()

    for ew in [w for w in words
               if w['text'].lower() == 'entry'
               and w['top'] > page_height * 0.10]:

        same_line = [w for w in words
                     if abs(w['top'] - ew['top']) < 5
                     and w['x0'] > ew['x0']]
        if len(same_line) < 2:
            continue

        # Respect 2-column layout: if Entry is in left column and right column
        # has body text on the same line, cap the crop at the midpoint.
        right_col_x = page_width / 2
        if ew['x0'] < right_col_x:
            right_body = [w for w in words
                          if w['x0'] > right_col_x + 20
                          and abs(w['top'] - ew['top']) < 30]
            col_x1 = right_col_x - 10 if right_body else page_width
        else:
            # Entry is already in the right column
            col_x1 = page_width

        header_words = sorted(
            [w for w in words
             if abs(w['top'] - ew['top']) < 5
             and w['x0'] >= ew['x0'] - 5
             and w['x0'] < col_x1],
            key=lambda w: w['x0']
        )
        if len(header_words) < 3:
            continue

        # Build explicit vertical line positions from column starts
        left_bound = header_words[0]['x0'] - 10
        right_bound = min(max(w['x1'] for w in header_words) + 10, col_x1)
        col_starts = [w['x0'] for w in header_words]

        verticals = [left_bound]
        for i in range(len(col_starts) - 1):
            mid = (col_starts[i + 1] + header_words[i]['x1']) / 2
            verticals.append(mid)
        verticals.append(right_bound)

        # Need a 'Table' caption above Entry
        cap_words = [w for w in words
                     if w['text'] in ('Table', 'TABLE')
                     and w['top'] < ew['top']
                     and w['x0'] >= left_bound - 20]
        if not cap_words:
            continue
        cap_top = min(w['top'] for w in cap_words)

        try:
            crop = plumber_page.crop((
                max(0, left_bound - 5),
                max(0, cap_top - 5),
                min(page_width, right_bound + 5),
                min(page_height, ew['top'] + 300),
            ))
            settings = {
                'explicit_vertical_lines': verticals,
                'horizontal_strategy': 'text',
                'intersection_x_tolerance': 20,
            }
            for t in crop.find_tables(table_settings=settings):
                data = t.extract()
                if _is_valid_table(data):
                    tables.append(data)
                    table_bboxes.append(t.bbox)
        except Exception:
            pass

    return tables, table_bboxes


def extract_tables(page, page_num, plumber_pdf=None):
    """Extract tables from a page using pdfplumber."""
    tables = []
    table_bboxes = []

    try:
        if plumber_pdf is not None:
            # Use pre-opened pdfplumber instance (performance path)
            if page_num < len(plumber_pdf.pages):
                plumber_page = plumber_pdf.pages[page_num]
                tables, table_bboxes = _extract_tables_from_plumber_page(plumber_page)
        else:
            # Fallback: open per-page (backward compatible)
            try:
                import pdfplumber
            except ImportError:
                return [], []
            pdf_path = page.parent.name
            with pdfplumber.open(pdf_path) as pdf:
                if page_num < len(pdf.pages):
                    plumber_page = pdf.pages[page_num]
                    tables, table_bboxes = _extract_tables_from_plumber_page(plumber_page)
    except Exception:
        pass

    return tables, table_bboxes


def extract_images(page, page_num, output_dir, config, min_width=100, min_height=100):
    """Extract images from a page and save them as PNG files."""
    images_info = []
    img_dir = output_dir / config.get("images", {}).get("subfolder", "images")
    img_dir.mkdir(parents=True, exist_ok=True)

    image_list = page.get_images(full=True)
    for img_idx, img_info in enumerate(image_list):
        xref = img_info[0]
        try:
            base_image = page.parent.extract_image(xref)
            if not base_image:
                continue

            img_width = base_image["width"]
            img_height = base_image["height"]

            # Filter small/fragment images
            if img_width < min_width or img_height < min_height:
                continue

            img_bytes = base_image["image"]
            img_ext = base_image["ext"]

            # Save as PNG, converting colorspace if needed
            img_filename = f"p{page_num + 1}_img{img_idx + 1}.png"
            try:
                try:
                    import pymupdf as fitz
                except ImportError:
                    import fitz
                pix = fitz.Pixmap(img_bytes)
                # CMYK (n>=4) must be converted to RGB; otherwise PNG saves as black
                if pix.colorspace and pix.colorspace.n >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                elif pix.alpha:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(str(img_dir / img_filename))
            except Exception:
                # Fallback: save raw bytes with original extension
                img_filename = f"p{page_num + 1}_img{img_idx + 1}.{img_ext}"
                with open(img_dir / img_filename, 'wb') as f:
                    f.write(img_bytes)

            # Find caption
            caption = find_caption(page, img_info)
            alt_text = caption if caption else f"Image p{page_num + 1}"

            images_info.append({
                "filename": img_filename,
                "alt_text": alt_text,
                "width": img_width,
                "height": img_height,
                "bbox": page.get_image_bbox(img_info),
            })

        except Exception:
            continue

    return images_info


def find_caption(page, img_info):
    """Find Figure/Scheme/Table caption near an image."""
    try:
        bbox = page.get_image_bbox(img_info)
        if not bbox:
            return None

        # Search area: below the image, within 50 points
        search_rect = (bbox[0], bbox[3], bbox[2], min(bbox[3] + 50, page.rect.height))

        blocks = page.get_text("dict", flags=3)["blocks"]
        caption_patterns = re.compile(
            r'^(?:Figure|Fig\.|Scheme|Table|Chart)\s*\d+',
            re.IGNORECASE
        )

        for block in blocks:
            if block["type"] != 0:
                continue
            by0 = block["bbox"][1]
            # Check if block overlaps search area
            if by0 >= search_rect[1] and by0 <= search_rect[3]:
                text = ""
                for line in block["lines"]:
                    text += "".join(s["text"] for s in line["spans"])
                text = text.strip()
                if caption_patterns.match(text):
                    return text[:200]  # cap length
    except Exception:
        pass
    return None


def process_page(page, page_num, doc, body_size, config, output_dir,
                 headings, repeated_headers, repeated_footers,
                 presentation_mode=False, plumber_pdf=None):
    """Process a single page: extract text with heading detection, tables, images."""
    lines = []
    blocks = page.get_text("dict", flags=3)["blocks"]

    # Extract tables and their bboxes to avoid duplicate text
    table_data_list = []
    table_bboxes = []
    if config.get("tables", {}).get("extract", True):
        table_data_list, table_bboxes = extract_tables(page, page_num, plumber_pdf)

    # Extract images
    images_info = []
    if config.get("images", {}).get("extract", True):
        min_w = config.get("images", {}).get("min_width", 100)
        min_h = config.get("images", {}).get("min_height", 100)
        if presentation_mode:
            min_w = max(min_w, 200)
            min_h = max(min_h, 200)
        images_info = extract_images(page, page_num, output_dir, config, min_w, min_h)

    # Page number patterns
    page_num_patterns = [
        re.compile(r'^\s*\d+\s*$'),                    # "1"
        re.compile(r'^\s*Page\s+\d+\s*$', re.IGNORECASE),  # "Page 1"
        re.compile(r'^\s*-\s*\d+\s*-\s*$'),            # "- 1 -"
        re.compile(r'^\s*第\s*\d+\s*頁\s*$'),           # "第 1 頁"
        re.compile(r'^\s*\d+\s*/\s*\d+\s*$'),          # "1 / 10"
    ]

    # Track which y-ranges are covered by tables
    def in_table_bbox(block_bbox):
        for tb in table_bboxes:
            # Check y-overlap
            if block_bbox[1] < tb[3] and block_bbox[3] > tb[1]:
                if block_bbox[0] < tb[2] and block_bbox[2] > tb[0]:
                    return True
        return False

    for block in blocks:
        if block["type"] != 0:
            continue

        # Skip blocks inside table regions
        if in_table_bbox(block["bbox"]):
            continue

        # Collect all lines in this block, merging non-heading lines into paragraphs
        block_parts = []  # list of (is_heading, level, text)
        for line in block["lines"]:
            spans = line["spans"]
            if not spans:
                continue

            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue

            # Skip repeated headers/footers
            if text in repeated_headers or text in repeated_footers:
                continue

            # Skip page numbers
            if config.get("text", {}).get("remove_page_numbers", True):
                is_page_num = False
                for pat in page_num_patterns:
                    if pat.match(text):
                        is_page_num = True
                        break
                if is_page_num:
                    continue

            # Check heading
            bbox_key = (round(line["bbox"][0], 1), round(line["bbox"][1], 1))
            level = headings.get(bbox_key, 0)
            block_parts.append((level > 0, level, text))

        # Merge block parts: headings are standalone, body lines join into paragraph
        paragraph_parts = []
        for is_heading, level, text in block_parts:
            if is_heading:
                # Flush accumulated paragraph
                if paragraph_parts:
                    lines.append(' '.join(paragraph_parts))
                    lines.append('')
                    paragraph_parts = []
                prefix = '#' * level + ' '
                lines.append(prefix + text)
                lines.append('')
            else:
                paragraph_parts.append(text)

        # Flush remaining paragraph
        if paragraph_parts:
            lines.append(' '.join(paragraph_parts))
            lines.append('')

    # Insert tables
    for table_data in table_data_list:
        md_table = format_table_as_markdown(table_data)
        if md_table:
            lines.append('')
            lines.append(md_table)
            lines.append('')

    # Insert image references
    img_subfolder = config.get("images", {}).get("subfolder", "images")
    for img in images_info:
        lines.append('')
        lines.append(f'![{img["alt_text"]}](./{img_subfolder}/{img["filename"]})')
        lines.append('')

    return lines


def generate_frontmatter(input_path, doc, config, detected_lang=None, encryption=None):
    """Generate YAML frontmatter."""
    if not config.get("frontmatter", {}).get("include", True):
        return ""

    fields = config.get("frontmatter", {}).get("fields", [])
    lines = ["---"]

    if "source_file" in fields:
        lines.append(f"source_file: \"{Path(input_path).name}\"")
    if "title" in fields:
        # Try to extract title from first page
        title = Path(input_path).stem.replace('_', ' ').replace('-', ' ')
        if doc and len(doc) > 0:
            first_page = doc[0]
            blocks = first_page.get_text("dict", flags=3)["blocks"]
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line_data in block["lines"]:
                    text = "".join(s["text"] for s in line_data["spans"]).strip()
                    if len(text) > 10:
                        title = text[:200]
                        break
                break
        lines.append(f"title: \"{title}\"")
    if "pages" in fields:
        lines.append(f"pages: {len(doc)}")
    if "converted_date" in fields:
        lines.append(f"converted_date: \"{datetime.now().strftime('%Y-%m-%d %H:%M')}\"")
    if "tool_version" in fields:
        lines.append(f"tool_version: \"{VERSION}\"")

    if detected_lang:
        lines.append(f"detected_language: \"{detected_lang}\"")
    if encryption:
        lines.append(f"encryption: \"{encryption}\"")

    lines.append("---")
    lines.append("")
    return '\n'.join(lines)


def render_pages(doc, output_dir, config, dpi=150):
    """Render each page as a PNG image for visual reference."""
    pages_dir = output_dir / config.get("images", {}).get("subfolder", "images") / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = page.get_pixmap(dpi=dpi)
        img_filename = f"page_{page_num + 1:03d}.png"
        mat.save(str(pages_dir / img_filename))

        img_subfolder = config.get("images", {}).get("subfolder", "images")
        lines.append(f'<details><summary>Page {page_num + 1}</summary>')
        lines.append('')
        lines.append(f'![Page {page_num + 1}]({img_subfolder}/pages/{img_filename})')
        lines.append('')
        lines.append('</details>')
        lines.append('')

    return '\n'.join(lines)


def normalize_ligatures(text: str) -> str:
    """Replace Unicode ligatures with ASCII equivalents (v0.9)."""
    ligature_map = {
        '\uFB00': 'ff',
        '\uFB01': 'fi',
        '\uFB02': 'fl',
        '\uFB03': 'ffi',
        '\uFB04': 'ffl',
    }
    for ligature, replacement in ligature_map.items():
        text = text.replace(ligature, replacement)
    return text


def fix_degree_symbol(text: str) -> str:
    """Fix RSC papers where °C appears as '1C' due to special font mapping (v0.9).

    Only matches when preceded by a number (temperature context) to avoid
    touching legitimate '1C' in chemical formulas.
    """
    # Pattern: digit, optional whitespace, then "1C" at word boundary
    text = re.sub(r'(\d)\s*1C\b', r'\1 °C', text)
    return text


def fix_drop_caps(text: str) -> str:
    """Fix ACS drop-cap first letters that PyMuPDF extracts as separate blocks (v0.9).

    Detects: single uppercase letter on its own line, blank line, then line
    starting with lowercase — and merges them.
    """
    text = re.sub(r'^([A-Z])\n\n([a-z])', r'\1\2', text, flags=re.MULTILINE)
    return text


def merge_consecutive_h1(text: str) -> str:
    """Merge consecutive H1 lines into a single H1 and demote author/section H1s (v0.9).

    Academic PDFs often have:
    1. Multi-line titles extracted as multiple '# ' lines → merge into one
    2. Author lines extracted as '# ' → demote to plain text
    3. Short journal/section names incorrectly classified as H1 → demote to '## '

    Strategy:
    - First H1 block (consecutive or blank-separated H1s) = title, merge into one
    - Subsequent H1s that look like author lines → plain text
    - Subsequent H1s that are short single-word journal names or common section
      headings → demote to H2
    """
    # Pattern: looks like an author line (names with superscripts, comma-separated)
    # Key signals: name+superscript (Khomane,a), trailing asterisk/dagger on name,
    # multiple comma-separated author names, or ends with affiliation superscript
    author_pattern = re.compile(
        r'(?:'
        r'et\s+al\.'                  # "et al."
        r'|[A-Za-z]+[a-z],[a-z]\b'   # superscript: "Khomane,a" or "Wang,a"
        r'|[A-Z][a-z]+\*\s*$'        # name ending with asterisk: "Lin*"
        r'|,\s*[a-z]\s*$'            # line ending with ", a" (affiliation superscript)
        r'|[A-Z][a-z]+-[A-Z][a-z]+\s+[A-Z][a-z]+,'  # "Tzu-Chun Yen," (hyphenated given name)
        r')'
    )

    # Section headings that should never be H1 (demote to H2)
    section_heading_pattern = re.compile(
        r'^(?:'
        r'Abstract|Introduction|Conclusion|Discussion|Results?|Experimental|'
        r'Methods?|References?|Acknowledgment|Supporting\s+Information|'
        r'Conflicts?\s+of\s+interest|Notes?\s+and\s+references?|'
        r'Author\s+contributions?|Funding|Keywords?|'
        r'ChemComm|JACS|Angew|OrgLett'  # journal name remnants
        r')$',
        re.IGNORECASE
    )

    lines = text.split('\n')
    result = []
    title_consumed = False
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith('# ') and not line.startswith('## '):
            content = line[2:]

            if not title_consumed:
                # This is the first H1 — treat as title, merge consecutive H1s
                title_parts = [content]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if next_line == '':
                        # Peek ahead: if next non-blank is H1, keep going
                        k = j + 1
                        while k < len(lines) and lines[k] == '':
                            k += 1
                        if k < len(lines) and lines[k].startswith('# ') and not lines[k].startswith('## '):
                            j = k  # jump to that H1
                            continue
                        else:
                            break
                    if next_line.startswith('# ') and not next_line.startswith('## '):
                        next_content = next_line[2:]
                        # Stop if this looks like an author line
                        if author_pattern.search(next_content):
                            break
                        # Stop if this is a section heading
                        if section_heading_pattern.match(next_content.strip()):
                            break
                        title_parts.append(next_content)
                        j += 1
                    else:
                        break
                result.append('# ' + ' '.join(title_parts))
                title_consumed = True
                i = j
            else:
                # Subsequent H1 — decide how to handle
                if author_pattern.search(content):
                    # Author line: demote to plain text
                    result.append(content)
                elif section_heading_pattern.match(content.strip()):
                    # Known section heading: demote to H2
                    result.append('## ' + content)
                else:
                    # Unknown subsequent H1: demote to H2 (safer default)
                    result.append('## ' + content)
                i += 1
        else:
            result.append(line)
            i += 1

    return '\n'.join(result)


def resolve_vlm_params(args):
    """Resolve VLM parameters with priority: CLI > profile > hardcoded default.

    Args:
        args: argparse Namespace (may have profile_data, vlm_model attrs).

    Returns:
        (model, prompt, max_tokens) tuple.
    """
    profile_data = getattr(args, 'profile_data', None)
    if profile_data is not None:
        vlm_cfg = profile_data.get('vlm', {})
        # CLI overrides profile when explicitly set (not argparse default)
        cli_model = getattr(args, 'vlm_model', DEFAULT_VLM_MODEL)
        if cli_model != DEFAULT_VLM_MODEL:
            model = cli_model
        else:
            model = vlm_cfg.get('model', DEFAULT_VLM_MODEL)
        prompt = vlm_cfg.get('prompt') or None
        max_tokens = vlm_cfg.get('max_tokens', None)
    else:
        model = getattr(args, 'vlm_model', DEFAULT_VLM_MODEL)
        prompt = None
        max_tokens = None
    return model, prompt, max_tokens


def convert_pdf_to_md(input_path, output_dir, config, args):
    """Main conversion: PDF -> Markdown."""
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            print("Error: pymupdf is required. Install with: pip install pymupdf", file=sys.stderr)
            return False

    try:
        doc = fitz.open(str(input_path))
    except Exception as e:
        print(f"Error opening {input_path}: {e}", file=sys.stderr)
        return False

    # --- 加密偵測 ---
    encryption_note = None
    if doc.is_encrypted:
        auth_result = doc.authenticate('')
        if auth_result > 0:
            encryption_note = "owner-password (bypassed)"
            print(f"  ℹ️  PDF has owner password (bypassed)", file=sys.stderr)
        else:
            print(f"  ❌ PDF requires open password, skipping: {input_path.name}", file=sys.stderr)
            doc.close()
            return False

    print(f"Processing: {input_path} ({len(doc)} pages)", file=sys.stderr)

    # Analyze fonts
    body_size = analyze_fonts(doc)
    print(f"  Body font size: {body_size}pt", file=sys.stderr)

    # Detect presentation mode
    presentation_mode = args.presentation or body_size >= 18.0
    if presentation_mode:
        print("  Presentation mode: ON", file=sys.stderr)

    # Detect language (v0.5.0: for tagging only, no encoding fix)
    detected_lang = detect_language(doc)
    if detected_lang != 'en':
        print(f"  Detected language: {detected_lang}", file=sys.stderr)

    # Detect headers/footers
    repeated_headers, repeated_footers = set(), set()
    if config.get("text", {}).get("remove_headers_footers", True):
        repeated_headers, repeated_footers = detect_headers_footers(doc)
        if repeated_headers or repeated_footers:
            print(f"  Found {len(repeated_headers)} repeated headers, {len(repeated_footers)} repeated footers",
                  file=sys.stderr)

    # Detect headings across all pages
    all_headings = {}
    tolerance = config.get("text", {}).get("body_font_size_tolerance", 0.5)
    for page in doc:
        blocks = page.get_text("dict", flags=3)["blocks"]
        page_headings = detect_headings(blocks, body_size, tolerance, presentation_mode)
        all_headings.update(page_headings)

    # Open pdfplumber once for all pages (performance: avoids re-opening per page)
    plumber_pdf = None
    if config.get("tables", {}).get("extract", True):
        try:
            import pdfplumber
            plumber_pdf = pdfplumber.open(str(input_path))
        except Exception:
            pass

    # Resolve VLM params early if needed (v0.10.1)
    use_vlm = getattr(args, 'vlm', False)
    vlm_descs = {}
    vlm_page_set = set()
    if use_vlm:
        try:
            from vlm_describer import describe_page as vlm_describe_page, parse_page_range
            vlm_dpi = getattr(args, 'vlm_dpi', 150)
            vlm_model, vlm_prompt, vlm_max_tokens = resolve_vlm_params(args)
            vlm_pages_spec = getattr(args, 'vlm_pages', None)
            vlm_page_set = parse_page_range(vlm_pages_spec, len(doc))
            print("  VLM: starting inline image description...", file=sys.stderr)
        except ImportError:
            print("  Warning: vlm_describer module not found, skipping VLM", file=sys.stderr)
            use_vlm = False
        except Exception as e:
            print(f"  Warning: VLM init failed: {e}", file=sys.stderr)
            use_vlm = False

    # v0.10.1: VLM implies render-pages (screenshots needed for inline reference)
    do_render = args.render_pages or use_vlm
    render_dpi = args.render_dpi if args.render_pages else (vlm_dpi if use_vlm else 150)

    # Prepare pages directory if rendering
    img_subfolder = config.get("images", {}).get("subfolder", "images")
    if do_render:
        pages_dir = output_dir / img_subfolder / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

    # Pre-render pages using CoreGraphics (macOS) or PyMuPDF fallback
    _render_tmpdir = None
    _vlm_tmpdir = None
    pre_rendered = {}
    pre_rendered_vlm = {}
    if do_render:
        import tempfile
        from renderers import render_pdf_pages

        render_page_list = list(range(len(doc)))  # all pages for render

        _render_tmpdir = tempfile.TemporaryDirectory(prefix="doc2md_render_")
        pre_rendered = render_pdf_pages(str(input_path), _render_tmpdir.name,
                                         dpi=render_dpi, pages=render_page_list)

        # VLM may need different DPI
        if use_vlm and render_dpi != vlm_dpi:
            vlm_page_list = list(vlm_page_set) if vlm_page_set else []
            _vlm_tmpdir = tempfile.TemporaryDirectory(prefix="doc2md_vlm_")
            pre_rendered_vlm = render_pdf_pages(str(input_path), _vlm_tmpdir.name,
                                                 dpi=vlm_dpi, pages=vlm_page_list)
        else:
            pre_rendered_vlm = pre_rendered if use_vlm else {}

    # Process each page (v0.10.1: inline VLM + page renders per page)
    total_pages = len(doc)
    all_lines = []
    vlm_count = 0
    for page_num in range(total_pages):
        page = doc[page_num]
        page_lines = process_page(
            page, page_num, doc, body_size, config, output_dir,
            all_headings, repeated_headers, repeated_footers,
            presentation_mode, plumber_pdf=plumber_pdf
        )
        all_lines.extend(page_lines)

        # Inline page render + VLM description (v0.10.1)
        if do_render:
            import shutil
            img_filename = f"page_{page_num + 1:03d}.png"
            if page_num in pre_rendered:
                shutil.copy2(pre_rendered[page_num], str(pages_dir / img_filename))
            else:
                pix = page.get_pixmap(dpi=render_dpi)
                pix.save(str(pages_dir / img_filename))

            all_lines.append('')
            all_lines.append(f'![Page {page_num + 1}]({img_subfolder}/pages/{img_filename})')
            all_lines.append('')

        if use_vlm and page_num in vlm_page_set:
            try:
                if page_num in pre_rendered_vlm:
                    png_bytes = Path(pre_rendered_vlm[page_num]).read_bytes()
                elif do_render and page_num in pre_rendered:
                    png_bytes = (pages_dir / f"page_{page_num + 1:03d}.png").read_bytes()
                else:
                    pix_vlm = page.get_pixmap(dpi=vlm_dpi)
                    png_bytes = pix_vlm.tobytes("png")
                print(f"  VLM: describing page {page_num + 1}/{total_pages}...", file=sys.stderr)
                desc = vlm_describe_page(png_bytes, model=vlm_model,
                                         prompt=vlm_prompt, max_tokens=vlm_max_tokens)
                if desc and "(text only)" not in desc:
                    all_lines.append(f'<!-- Page {page_num + 1} VLM descriptions -->')
                    all_lines.append(desc)
                    all_lines.append('')
                    vlm_count += 1
            except Exception as e:
                print(f"  Warning: VLM failed on page {page_num + 1}: {e}", file=sys.stderr)

        if page_num < total_pages - 1:
            all_lines.append('')  # page separator
        if total_pages > 50 and (page_num + 1) % 10 == 0:
            print(f"  📄 Processing page {page_num + 1}/{total_pages}...", file=sys.stderr)

    if vlm_count > 0:
        print(f"  VLM: described {vlm_count} pages with figures/schemes (inline)", file=sys.stderr)

    if plumber_pdf is not None:
        plumber_pdf.close()

    # Clean up pre-render temp directories
    if _render_tmpdir is not None:
        _render_tmpdir.cleanup()
    if _vlm_tmpdir is not None:
        _vlm_tmpdir.cleanup()

    full_md = '\n'.join(all_lines)

    # v0.9 fixes: applied before noise filter
    full_md = normalize_ligatures(full_md)
    full_md = fix_degree_symbol(full_md)
    full_md = fix_drop_caps(full_md)
    full_md = merge_consecutive_h1(full_md)

    # Layer 1: Filter noise (profile-aware, v0.10.0)
    profile_data = getattr(args, 'profile_data', None)
    if profile_data is not None:
        noise_cfg = profile_data.get('noise', {})
        compiled_patterns = noise_cfg.get('compiled_patterns', [])
        safety_threshold = noise_cfg.get('safety_threshold', 150)
        if compiled_patterns:
            full_md = filter_noise(full_md, compiled_patterns, safety_threshold)
    else:
        # Programmatic call without --profile: fallback to journal noise filter
        full_md = filter_journal_noise(full_md)

    # Post-process
    full_md = post_process(full_md)

    # Add AI_TODO for non-English documents (v0.5.0)
    if detected_lang != 'en':
        ai_todo = f"<!-- AI_TODO: non-English document ({detected_lang}), needs translation and encoding cleanup -->\n\n"
        full_md = ai_todo + full_md

    # Generate frontmatter
    frontmatter = generate_frontmatter(input_path, doc, config, detected_lang, encryption=encryption_note)

    # Combine (v0.10.1: VLM + renders are already inline, no separate sections)
    final_md = frontmatter + full_md

    # Write output
    md_filename = Path(input_path).stem + '.md'
    md_path = output_dir / md_filename
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(final_md)

    doc.close()
    print(f"  Output: {md_path}", file=sys.stderr)
    return True

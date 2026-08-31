#!/usr/bin/env python3
"""
md_splitter - Markdown 章節拆分工具 v0.3.0

將一個長 Markdown 檔案按照指定的標題層級或自訂 regex 拆分成多個小檔案，
並產出 _TOC.md 索引。

Usage:
    python3 md_splitter.py input.md                             # 預設按 # (H1) 拆分
    python3 md_splitter.py input.md --level 2                   # 按 ## (H2) 拆分
    python3 md_splitter.py input.md --level 3 --strict          # 嚴格模式
    python3 md_splitter.py input.md --pattern chinese           # 中文章節模式
    python3 md_splitter.py input.md --pattern '^Chapter\\s+\\d+' # 自訂 regex
    python3 md_splitter.py input.md --dry-run                   # 預覽，不寫檔
    python3 md_splitter.py input.md --toc-only                  # 只產出 _TOC.md
    python3 md_splitter.py input.md -o ./chapters/              # 指定輸出目錄
    python3 md_splitter.py input.md --keep-frontmatter          # 分檔保留 frontmatter
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

VERSION = "0.3.0"


# ─── --level 模式的白名單與雜訊判斷 ──────────────────────────────────────────

WHITELIST_PATTERNS = [
    re.compile(r'^[一二三四五六七八九十百千]+[、．]'),       # 中文章節：一、 二、 三、
    re.compile(r'^\d+\.[\d.]* '),                            # 編號章節：2.1  3.2.1
    re.compile(
        r'^(Abstract|Introduction|Conclusion|References'
        r'|附錄|摘要|目錄|圖目錄|表目錄|緒論|文獻回顧|結論|參考文獻)',
        re.IGNORECASE,
    ),
]

NOISE_SYMBOL_PAT = re.compile(r'[=±×]')


def is_structural_heading(title: str, strict: bool = False) -> bool:
    """判斷標題是否為結構性標題（應作為拆分點）。

    白名單永遠視為結構性標題。
    --strict 模式：非白名單一律排除。
    預設模式：含數學符號或純文字過短的 heading 排除。
    """
    for pat in WHITELIST_PATTERNS:
        if pat.search(title):
            return True

    if strict:
        return False

    # 含數學/統計符號 → 雜訊
    if NOISE_SYMBOL_PAT.search(title):
        return False

    # 純文字 < 5 字元 → 雜訊（去掉空白與標點後計算）
    pure = re.sub(r'[^\w\u4e00-\u9fff]', '', title)
    if len(pure) < 5:
        return False

    return True


# ─── --pattern 模式的 shortcut 展開 ──────────────────────────────────────────

PATTERN_SHORTCUTS = {
    "chinese": r'^[一二三四五六七八九十百]+、',
    "numbered": r'^\d+\.\s',
    "chapter":  r'^Chapter\s+\d+',
}


def resolve_pattern(p: str) -> str:
    """Shortcut 名稱展開為 regex。若不是已知 shortcut，原樣回傳（視為自訂 regex）。"""
    return PATTERN_SHORTCUTS.get(p, p)


# ─── 核心處理函式 ──────────────────────────────────────────────────────────────

def extract_frontmatter(lines):
    """Extract YAML frontmatter from the beginning of the file.

    Returns (frontmatter_lines, remaining_lines).
    frontmatter_lines includes the --- delimiters.
    If no frontmatter, returns ([], lines).
    """
    if not lines or lines[0].rstrip() != "---":
        return [], lines
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return lines[:i + 1], lines[i + 1:]
    return [], lines


def sanitize_filename(title: str) -> str:
    """Convert a heading title to a safe filename."""
    name = title.strip()
    name = re.sub(r'^#+\s*', '', name)
    name = re.sub(r'[*_`~]', '', name)
    # 移除 PDF TOC 的引點（連續 2 個以上的點）
    name = re.sub(r'\.{2,}', '', name)
    # 移除結尾的頁碼（空白 + 數字）
    name = re.sub(r'\s*\d+\s*$', '', name).strip()
    name = re.sub(r'[/\\:?<>"|]', '-', name)
    name = re.sub(r'\s+', '-', name)
    name = re.sub(r'-{2,}', '-', name)
    name = name.strip('-')
    if len(name) > 80:
        name = name[:80].rstrip('-')
    return name if name else 'untitled'


def split_markdown(lines, level: int, strict: bool = False):
    """Split lines by heading level (--level mode).

    Noisy headings are treated as regular content lines.
    Returns list of (title, content_lines) tuples.
    The first element may have title=None if there's content before the first heading.
    """
    target_pat = re.compile(r'^#{' + str(level) + r'}\s+(.+)$')

    sections = []
    current_title = None
    current_lines = []

    for line in lines:
        match = target_pat.match(line.rstrip())
        if match:
            title_text = match.group(1).strip()
            if is_structural_heading(title_text, strict=strict):
                if current_lines or current_title is not None:
                    sections.append((current_title, current_lines))
                current_title = title_text
                current_lines = [line]
            else:
                current_lines.append(line)
        else:
            current_lines.append(line)

    if current_lines or current_title is not None:
        sections.append((current_title, current_lines))

    return sections


def split_by_pattern(lines, pattern_str: str):
    """Split lines by matching any line against a regex (--pattern mode).

    Any line that matches pattern_str starts a new section.
    The full text of that line becomes the section title.
    Returns list of (title, content_lines) tuples.
    """
    pat = re.compile(pattern_str)

    sections = []
    current_title = None
    current_lines = []

    for line in lines:
        stripped = line.rstrip()
        if pat.search(stripped):
            if current_lines or current_title is not None:
                sections.append((current_title, current_lines))
            current_title = stripped
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines or current_title is not None:
        sections.append((current_title, current_lines))

    return sections


def _build_filenames(sections, use_prefix: bool) -> list:
    """Build filename list corresponding to each section."""
    filenames = []
    titled_idx = 0
    for title, _ in sections:
        if title is None:
            filenames.append("00-前言.md")
        else:
            titled_idx += 1
            safe = sanitize_filename(title)
            if use_prefix:
                filenames.append(f"{titled_idx:02d}-{safe}.md")
            else:
                filenames.append(f"{safe}.md")
    return filenames


def _estimate_tokens(content_lines) -> int:
    """Rough token estimate: character count / 1.5."""
    return int(len("".join(content_lines)) / 1.5)


def _build_toc(
    source_name: str,
    sections,
    filenames: list,
    split_date: str,
    level: int = None,
    pattern: str = None,
) -> str:
    """Build _TOC.md content string."""
    titled_count = sum(1 for s in sections if s[0] is not None)
    stem = Path(source_name).stem

    # YAML frontmatter
    lines_out = [
        "---",
        f'source_file: "{source_name}"',
    ]
    if pattern is not None:
        lines_out.append(f'split_pattern: "{pattern}"')
    else:
        lines_out.append(f"split_level: {level if level is not None else 1}")
    lines_out += [
        f'split_date: "{split_date}"',
        f"total_chapters: {titled_count}",
        "---",
        "",
        f"# {stem} — 目錄",
        "",
        "| # | 檔案 | 章節標題 | 行數 | 預估 tokens[a] |",
        "|---|------|---------|------|---------------|",
    ]

    row_idx = 0
    for (title, content), filename in zip(sections, filenames):
        if title is None:
            display_title = "前言"
            idx_str = "0"
        else:
            row_idx += 1
            display_title = title
            idx_str = str(row_idx)

        tokens_str = f"~{_estimate_tokens(content):,}"
        link = f"[{filename}](./{filename})"
        lines_out.append(f"| {idx_str} | {link} | {display_title} | {len(content)} | {tokens_str} |")

    lines_out += [
        "",
        "[a] tokens 預估以中文 1.5 字/token、英文 0.75 詞/token 粗估，僅供參考。",
        "",
    ]
    return "\n".join(lines_out)


# ─── 公開 API（供 doc2md import）────────────────────────────────────────────

def split_and_export(
    input_path,
    output_dir=None,
    level: int = None,
    pattern: str = None,
    keep_frontmatter: bool = False,
    strict: bool = False,
    toc_only: bool = False,
    use_prefix: bool = True,
) -> Path:
    """拆分 Markdown 並輸出章節檔案與 _TOC.md。

    Args:
        input_path: 輸入 .md 檔案路徑。
        output_dir: 輸出資料夾（預設：<stem>_chapters/，在輸入檔旁）。
        level: 拆分標題層級（1-3）。與 pattern 互斥，都未指定時預設 1。
        pattern: regex 或 shortcut 名稱（chinese/numbered/chapter）。與 level 互斥。
        keep_frontmatter: 每個分檔都保留原始 YAML frontmatter。
        strict: 只保留白名單標題作為拆分點（僅 level 模式有效）。
        toc_only: 只產出 _TOC.md，不寫章節檔案。
        use_prefix: 檔名加上序號前綴（預設 True）。

    Returns:
        輸出目錄的 Path 物件。
    """
    if level is not None and pattern is not None:
        raise ValueError("--level 和 --pattern 互斥，不能同時指定。")

    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"找不到檔案：{input_path}")

    text = input_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    frontmatter_lines, body_lines = extract_frontmatter(lines)

    if pattern is not None:
        resolved = resolve_pattern(pattern)
        try:
            re.compile(resolved)
        except re.error as e:
            raise ValueError(f"無效的 regex pattern '{resolved}'：{e}")
        sections = split_by_pattern(body_lines, resolved)
        label = f"pattern: {pattern}" + (f" ({resolved})" if resolved != pattern else "")
        toc_pattern = pattern
        toc_level = None
    else:
        eff_level = level if level is not None else 1
        sections = split_markdown(body_lines, eff_level, strict=strict)
        label = f"H{eff_level}" + ("（strict）" if strict else "")
        toc_pattern = None
        toc_level = eff_level

    if not sections:
        raise ValueError("找不到任何章節標題，無法拆分。")

    titled = [s for s in sections if s[0] is not None]
    preamble = [s for s in sections if s[0] is None]

    print(f"輸入：{input_path.name}", file=sys.stderr)
    print(f"拆分模式：{label}", file=sys.stderr)
    print(f"找到 {len(titled)} 個章節", file=sys.stderr)
    if preamble:
        print(f"  + 前言區塊（{len(preamble[0][1])} 行）", file=sys.stderr)

    # 決定輸出目錄
    if output_dir:
        out_dir = Path(output_dir).resolve()
    else:
        out_dir = input_path.parent / f"{input_path.stem}_chapters"
    out_dir.mkdir(parents=True, exist_ok=True)

    filenames = _build_filenames(sections, use_prefix)

    # 產出 _TOC.md
    split_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    toc_content = _build_toc(
        input_path.name, sections, filenames, split_date,
        level=toc_level, pattern=toc_pattern,
    )
    toc_path = out_dir / "_TOC.md"
    toc_path.write_text(toc_content, encoding="utf-8")
    print(f"  📋 _TOC.md 已產出", file=sys.stderr)

    if toc_only:
        print(f"\n完成（--toc-only）：_TOC.md 寫入 {out_dir}", file=sys.stderr)
        return out_dir

    # 寫入章節檔案
    written = 0
    for (title, content), filename in zip(sections, filenames):
        file_lines = []
        if keep_frontmatter and frontmatter_lines:
            file_lines.extend(frontmatter_lines)
            file_lines.append("\n")
        file_lines.extend(content)

        out_path = out_dir / filename
        out_path.write_text("".join(file_lines), encoding="utf-8")
        print(f"  ✅ {filename}（{len(content)} 行）", file=sys.stderr)
        written += 1

    print(f"\n完成：{written} 個檔案 + _TOC.md 寫入 {out_dir}", file=sys.stderr)
    return out_dir


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="將長 Markdown 檔案按章節標題拆分成多個檔案",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python3 md_splitter.py book.md                             # 按 H1 拆分
  python3 md_splitter.py book.md --level 2                   # 按 H2 拆分
  python3 md_splitter.py book.md --level 3 --strict          # 嚴格模式
  python3 md_splitter.py book.md --pattern chinese           # 中文章節（一、二、...）
  python3 md_splitter.py book.md --pattern numbered          # 編號章節（1. 2. ...）
  python3 md_splitter.py book.md --pattern '^Chapter\\s+\\d+' # 自訂 regex
  python3 md_splitter.py book.md --dry-run                   # 預覽，不寫檔
  python3 md_splitter.py book.md --toc-only                  # 只產出 _TOC.md
  python3 md_splitter.py book.md -o ./chapters/              # 指定輸出目錄

內建 pattern shortcuts：
  chinese   = ^[一二三四五六七八九十百]+、
  numbered  = ^\\d+\\.\\s
  chapter   = ^Chapter\\s+\\d+
        """,
    )
    parser.add_argument("input", help="輸入的 Markdown 檔案路徑")
    parser.add_argument(
        "--level",
        type=int,
        default=None,
        choices=[1, 2, 3],
        help="拆分的標題層級（1=H1, 2=H2, 3=H3）。與 --pattern 互斥，預設 1",
    )
    parser.add_argument(
        "--pattern",
        metavar="PATTERN",
        help="按 regex 拆分（支援 shortcut：chinese / numbered / chapter）。與 --level 互斥",
    )
    parser.add_argument("-o", "--output", help="輸出資料夾（預設：<輸入檔名>_chapters/）")
    parser.add_argument(
        "--keep-frontmatter",
        action="store_true",
        help="每個分檔都保留原始 YAML frontmatter",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="預覽拆分結果（顯示章節列表與行數），不寫入檔案",
    )
    parser.add_argument(
        "--toc-only",
        action="store_true",
        help="只產出 _TOC.md，不實際拆分章節檔案",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="嚴格模式：只保留白名單標題作為拆分點（僅 --level 模式有效）",
    )
    parser.add_argument(
        "--prefix-number",
        action="store_true",
        default=True,
        help="檔名加上序號前綴（預設開啟）",
    )
    parser.add_argument(
        "--no-prefix-number",
        action="store_true",
        help="檔名不加序號前綴",
    )
    parser.add_argument("--version", action="version", version=f"md_splitter v{VERSION}")
    return parser.parse_args()


def main():
    args = parse_args()
    use_prefix = not args.no_prefix_number

    # 互斥檢查
    if args.level is not None and args.pattern is not None:
        print("錯誤：--level 和 --pattern 互斥，不能同時指定。", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"錯誤：找不到檔案 {input_path}", file=sys.stderr)
        sys.exit(1)
    if input_path.suffix.lower() != ".md":
        print("警告：輸入檔案不是 .md 格式，繼續處理...", file=sys.stderr)

    # 計算實際使用的 level / pattern
    use_pattern = args.pattern
    use_level = args.level  # None 表示未明確指定

    # dry-run 模式：只列出章節，不寫任何檔案
    if args.dry_run:
        text = input_path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        _, body_lines = extract_frontmatter(lines)

        if use_pattern is not None:
            resolved = resolve_pattern(use_pattern)
            try:
                re.compile(resolved)
            except re.error as e:
                print(f"錯誤：無效的 regex pattern '{resolved}'：{e}", file=sys.stderr)
                sys.exit(1)
            sections = split_by_pattern(body_lines, resolved)
            label = f"pattern: {use_pattern}" + (f" ({resolved})" if resolved != use_pattern else "")
        else:
            eff_level = use_level if use_level is not None else 1
            sections = split_markdown(body_lines, eff_level, strict=args.strict)
            label = f"H{eff_level}" + ("（strict）" if args.strict else "")

        if not sections:
            print("找不到任何章節標題，無法拆分。", file=sys.stderr)
            sys.exit(1)

        titled = [s for s in sections if s[0] is not None]
        preamble = [s for s in sections if s[0] is None]

        print(f"輸入：{input_path.name}", file=sys.stderr)
        print(f"拆分模式：{label}", file=sys.stderr)
        print(f"找到 {len(titled)} 個章節", file=sys.stderr)
        if preamble:
            print(f"  + 前言區塊（{len(preamble[0][1])} 行）", file=sys.stderr)

        print(f"\n{'序號':>4}  {'行數':>5}  標題", file=sys.stderr)
        print(f"{'─' * 4}  {'─' * 5}  {'─' * 40}", file=sys.stderr)
        idx = 0
        for title, content in sections:
            if title is None:
                print(f"{'—':>4}  {len(content):>5}  （前言 / frontmatter 前內容）", file=sys.stderr)
            else:
                idx += 1
                print(f"{idx:>4}  {len(content):>5}  {title}", file=sys.stderr)
        print(f"\n總計 {sum(len(c) for _, c in sections)} 行", file=sys.stderr)
        print("（--dry-run 模式，未寫入檔案）", file=sys.stderr)
        return

    # 實際拆分
    try:
        split_and_export(
            input_path=input_path,
            output_dir=args.output,
            level=use_level,
            pattern=use_pattern,
            keep_frontmatter=args.keep_frontmatter,
            strict=args.strict,
            toc_only=args.toc_only,
            use_prefix=use_prefix,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

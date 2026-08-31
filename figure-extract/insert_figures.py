#!/usr/bin/env python3
"""
把裁切好的圖依錨點插回 Markdown。

設計原則：
  - 純確定性文字操作，不含 LLM
  - 預設 dry-run：先印出會插在哪，確認無誤才 --apply
  - 原檔備份為 .bak，不覆蓋既有備份
  - 錨點比對容錯：完全相符 → 正規化相符 → 模糊比對，找不到就跳過並回報

輸入：crop_figures.py 產出的 _crop_result.json

用法：
    python3 insert_figures.py _crop_result.json target.md            # dry-run 預覽
    python3 insert_figures.py _crop_result.json target.md --apply    # 實際寫入
    python3 insert_figures.py _crop_result.json target.md --apply --style obsidian
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path


def normalise(s: str) -> str:
    """正規化：去 Markdown 標記、空白、全形空格，供容錯比對。"""
    s = re.sub(r"^#+\s*", "", s.strip())
    s = s.replace("　", " ")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def find_anchor(lines: list, anchor: str) -> int:
    """回傳錨點所在行索引，找不到回 -1。三段容錯。"""
    if not anchor:
        return -1

    # 1. 完全相符
    for i, ln in enumerate(lines):
        if ln.strip() == anchor.strip():
            return i

    # 2. 正規化相符
    target = normalise(anchor)
    if target:
        for i, ln in enumerate(lines):
            if normalise(ln) == target:
                return i

    # 3. 模糊：正規化後互相包含（處理 OCR 雜訊造成的細微差異）
    if len(target) >= 6:
        for i, ln in enumerate(lines):
            n = normalise(ln)
            if n and (target in n or n in target):
                return i

    return -1


def build_ref(fig: dict, img_rel: str, style: str) -> str:
    cap = fig.get("caption", "").strip()
    if style == "obsidian":
        return f"![[{Path(img_rel).name}]]"
    alt = cap or fig.get("id", "figure")
    return f"![{alt}]({img_rel})"


def main():
    ap = argparse.ArgumentParser(description="把裁切好的圖依錨點插回 Markdown")
    ap.add_argument("crop_result", help="crop_figures.py 產出的 _crop_result.json")
    ap.add_argument("target_md", help="要插入的 Markdown 檔")
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設只預覽）")
    ap.add_argument("--style", choices=["markdown", "obsidian"], default="markdown",
                    help="圖片語法，obsidian 用 ![[]]")
    args = ap.parse_args()

    res = json.loads(Path(args.crop_result).expanduser().read_text(encoding="utf-8"))
    md_path = Path(args.target_md).expanduser()
    if not md_path.exists():
        sys.exit(f"找不到 Markdown：{md_path}")

    img_dir = Path(res["out_dir"])
    lines = md_path.read_text(encoding="utf-8").split("\n")

    # 由後往前插入，避免行號位移
    plan, missing = [], []
    for fig in res.get("cropped", []):
        idx = find_anchor(lines, fig.get("anchor_text", ""))
        if idx < 0:
            missing.append(fig)
            continue
        pos = fig.get("anchor_pos", "after")
        insert_at = idx + 1 if pos == "after" else idx
        plan.append((insert_at, fig, idx))

    plan.sort(key=lambda t: t[0], reverse=True)

    try:
        rel_base = os.path.relpath(img_dir, md_path.parent)
    except ValueError:
        rel_base = str(img_dir)

    print(f"\nMarkdown：{md_path}")
    print(f"圖片目錄：{img_dir}")
    print(f"可插入 {len(plan)} 張 | 錨點找不到 {len(missing)} 張")

    if plan:
        print(f"\n插入計畫（{'實際寫入' if args.apply else '預覽，未寫入'}）：")
        for insert_at, fig, idx in sorted(plan, key=lambda t: t[0]):
            print(f"  L{idx+1:<5} {fig['anchor_pos']:<6} {fig['file']:<20} ← {fig.get('caption','')[:40]}")

    if missing:
        print(f"\n⚠️  錨點找不到（未插入，需人工確認）：")
        for f in missing:
            print(f"  {f['file']:<20} anchor: {f.get('anchor_text','(空)')[:50]}")

    if not args.apply:
        print(f"\n這是預覽。確認無誤後加 --apply 實際寫入。")
        return

    if not plan:
        print("\n沒有可插入的項目，未修改檔案。")
        return

    # 備份（不覆蓋既有備份）
    bak = md_path.with_suffix(md_path.suffix + ".bak")
    n = 1
    while bak.exists():
        bak = md_path.with_suffix(md_path.suffix + f".bak{n}")
        n += 1
    shutil.copy2(md_path, bak)

    for insert_at, fig, _ in plan:
        img_rel = str(Path(rel_base) / fig["file"]) if rel_base != "." else fig["file"]
        ref = build_ref(fig, img_rel, args.style)
        lines.insert(insert_at, "")
        lines.insert(insert_at + 1, ref)
        lines.insert(insert_at + 2, "")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n✅ 已寫入 {len(plan)} 張圖")
    print(f"   備份：{bak}")
    if missing:
        print(f"   ⚠️ {len(missing)} 張因錨點找不到未插入")


if __name__ == "__main__":
    main()

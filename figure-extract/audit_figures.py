#!/usr/bin/env python3
"""
圖表擷取的校正稽核 — 自動抓可疑項 + 產出目視抽查清單。

【為何需要】2026-07-24 五篇實測，三個真 bug 中最危險的一個是「純文字表格只切到表頭」：
切出來有標題、有表頭，**看起來像成功了**，但資料列全沒了。
純靠「跑完沒報錯」會靜默通過。故稽核必須是獨立步驟，且必須有人目視環節。

稽核分三層：
  L1 幾何檢查（純算）—— 高度異常、範圍重疊、越界、錨點缺失
  L2 內容檢查（讀 PDF 文字層）—— 切出的範圍內有沒有涵蓋到該表的資料列與腳註
  L3 目視抽查清單 —— 挑出最該人工看的幾張，列出來給人（或 VLM）確認

用法：
    python3 audit_figures.py figure_map.json                    # L1+L2
    python3 audit_figures.py figure_map.json --crop-dir out/    # 加上檔案層檢查
    python3 audit_figures.py figure_map.json --json report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("需要 PyMuPDF：pip install pymupdf")


MIN_HEIGHT_PT = 40      # 低於此高度幾乎不可能是完整圖表
MAX_HEIGHT_RATIO = 0.95  # 超過此比例幾乎是整頁誤抓
ROW_RE = re.compile(r"(N\.?D\.?|trace|Trace|<\s*\d|\b\d{1,3}\s*%|^\d{1,2}[\s.)])", re.M)
FOOTNOTE_HINT = re.compile(r"(equiv|mmol|mol\s*%|Reaction conditions|isolated|determined|yield)", re.I)


def text_in_range(page, y0_ratio, y1_ratio):
    ph = page.rect.height
    y0, y1 = y0_ratio * ph, y1_ratio * ph
    out = []
    for b in page.get_text("blocks"):
        if b[4].strip() and b[1] >= y0 - 2 and b[3] <= y1 + 2:
            out.append(b[4].strip())
    return "\n".join(out)


def audit(map_path: Path, crop_dir: Path | None):
    data = json.loads(map_path.read_text(encoding="utf-8"))
    pdf = Path(data["source_pdf"]).expanduser()
    if not pdf.exists():
        sys.exit(f"找不到來源 PDF：{pdf}")
    doc = fitz.open(pdf)
    figs = data.get("figures", [])

    issues = []      # 必須處理
    warnings = []    # 建議確認
    visual = []      # 目視抽查清單

    by_page = {}
    for f in figs:
        by_page.setdefault(f["page"], []).append(f)

    for f in figs:
        fid, pno = f["id"], f["page"]
        y0, y1 = f["y_start"], f["y_end"]
        page = doc[pno - 1]
        ph = page.rect.height
        h_pt = (y1 - y0) * ph
        cont = f.get("continuation")

        # ---- L1 幾何檢查 ----
        if y1 <= y0:
            issues.append((fid, "y_end 未大於 y_start，裁切必然失敗"))
            continue
        if y0 < 0 or y1 > 1.001:
            issues.append((fid, f"座標越界 ({y0:.3f}-{y1:.3f})"))
        if h_pt < MIN_HEIGHT_PT and not cont:
            issues.append((fid, f"高度僅 {h_pt:.0f}pt 且無跨頁接續 — 極可能只切到標題"))
        if (y1 - y0) > MAX_HEIGHT_RATIO:
            warnings.append((fid, f"佔頁面 {(y1-y0)*100:.0f}%，可能誤抓整頁"))
        if not f.get("anchor_text"):
            warnings.append((fid, "無 Markdown 錨點 — 插入時會被跳過"))

        # 同頁範圍重疊
        for g in by_page.get(pno, []):
            if g["id"] >= fid:
                continue
            if not (f["y_end"] <= g["y_start"] or f["y_start"] >= g["y_end"]):
                warnings.append((fid, f"與 {g['id']} 範圍重疊"))

        # ---- L2 內容檢查 ----
        body = text_in_range(page, y0, y1)
        if cont:
            cpage = doc[int(cont["page"]) - 1]
            body += "\n" + text_in_range(cpage, cont["y_start"], cont["y_end"])

        caption = f.get("caption", "")
        is_table = caption.lower().lstrip().startswith(("table", "表"))

        # 表格本體可能是「圖片」而非文字層——此時文字檢查不適用，
        # 改判定範圍內是否涵蓋到夠大的圖片物件。
        # 實測：吳穎柔 Table 4-7、莊書錦 Table 5 皆為圖片型表格。
        img_cover = 0.0
        try:
            for im in page.get_image_info():
                bb = im.get("bbox")
                if not bb:
                    continue
                ov = min(bb[3], y1 * ph) - max(bb[1], y0 * ph)
                if ov > 0:
                    img_cover = max(img_cover, ov)
        except Exception:
            pass
        is_image_table = img_cover > max(60.0, h_pt * 0.35)

        if is_table and not is_image_table:
            rows = len(ROW_RE.findall(body))
            if rows == 0:
                issues.append((fid, "範圍內找不到任何資料列特徵 — 疑只切到表頭（最危險的靜默失敗）"))
            elif rows < 2:
                warnings.append((fid, f"僅偵測到 {rows} 條資料列，確認表格是否被截斷"))
            if not FOOTNOTE_HINT.search(body):
                warnings.append((fid, "範圍內無腳註特徵（reaction conditions / equiv 等），確認腳註是否被切掉"))
        elif is_table and is_image_table:
            # 圖片型表格無法用文字層驗證內容 → 一律列入必看目視清單
            f["_image_table"] = True
            if img_cover < h_pt * 0.5:
                warnings.append((fid, f"圖片僅覆蓋範圍的 {img_cover/h_pt*100:.0f}%，確認圖是否被切掉一半"))

        # 下緣是否緊貼下一個內容（可能切掉最後一列）
        nxt_top = None
        for b in sorted(page.get_text("blocks"), key=lambda b: b[1]):
            if b[4].strip() and b[1] > y1 * ph:
                nxt_top = b[1]
                break
        if nxt_top is not None and (nxt_top - y1 * ph) < 6:
            warnings.append((fid, "下緣緊貼下一段文字，可能切掉最後一列"))

        # ---- L3 目視抽查名單 ----
        # 挑選原則：有 issue 的必看；跨頁的必看；每個學生至少看最大與最小各一張
        # 圖片型表格無法程式驗證內容，必須目視
        need = bool(cont) or f.get("_image_table", False) or any(i[0] == fid for i in issues)
        visual.append({"id": fid, "page": pno, "h_pt": round(h_pt),
                       "cont": bool(cont), "must": need,
                       "img_table": f.get("_image_table", False),
                       "caption": caption[:50],
                       "file": f"{fid}.png"})

    doc.close()

    # 補上「最大/最小各一」的抽查建議
    if visual:
        srt = sorted(visual, key=lambda v: v["h_pt"])
        srt[0]["must"] = True
        srt[-1]["must"] = True

    # ---- 檔案層檢查 ----
    file_issues = []
    if crop_dir:
        for v in visual:
            p = crop_dir / v["file"]
            if not p.exists():
                file_issues.append((v["id"], "PNG 未產出"))
            elif p.stat().st_size < 4096:
                file_issues.append((v["id"], f"檔案僅 {p.stat().st_size}B，疑空白圖"))

    return {
        "source_pdf": str(pdf),
        "total": len(figs),
        "issues": issues,
        "warnings": warnings,
        "file_issues": file_issues,
        "visual": visual,
    }


def main():
    ap = argparse.ArgumentParser(description="圖表擷取的校正稽核")
    ap.add_argument("figure_map")
    ap.add_argument("--crop-dir", help="裁切輸出目錄（加做檔案層檢查）")
    ap.add_argument("--json", help="輸出 JSON 稽核報告")
    args = ap.parse_args()

    crop_dir = Path(args.crop_dir).expanduser() if args.crop_dir else None
    r = audit(Path(args.figure_map).expanduser(), crop_dir)

    print(f"\n稽核：{Path(r['source_pdf']).name}")
    print(f"圖表 {r['total']} 張 | ❌ 必處理 {len(r['issues'])} | ⚠️ 待確認 {len(r['warnings'])} | 檔案問題 {len(r['file_issues'])}")

    if r["issues"]:
        print(f"\n❌ 必須處理（會產出錯誤內容）：")
        for fid, msg in r["issues"]:
            print(f"   {fid:<22} {msg}")

    if r["warnings"]:
        print(f"\n⚠️  建議確認：")
        for fid, msg in r["warnings"]:
            print(f"   {fid:<22} {msg}")

    if r["file_issues"]:
        print(f"\n📁 檔案層：")
        for fid, msg in r["file_issues"]:
            print(f"   {fid:<22} {msg}")

    must = [v for v in r["visual"] if v["must"]]
    print(f"\n👁  目視抽查清單（{len(must)}/{len(r['visual'])} 張必看）：")
    for v in must:
        tag = ("跨頁" if v["cont"] else "") + ("圖表" if v.get("img_table") else "")
        print(f"   {v['file']:<26} {v['h_pt']:>4}pt {tag:<4} {v['caption']}")
    print(f"\n   檢查重點：標題在不在？資料列全不全？最後一列有沒有被切？腳註在不在？")

    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 報告：{args.json}")

    # 有必處理項目時回傳非零，方便流程中止
    sys.exit(1 if (r["issues"] or r["file_issues"]) else 0)


if __name__ == "__main__":
    main()

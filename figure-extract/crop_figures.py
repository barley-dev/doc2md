#!/usr/bin/env python3
"""
依座標檔從 PDF 裁切圖表為 PNG。

設計原則（2026-07-24 定）：
  - 只切上下邊界，左右吃滿頁寬 → 左右邊界判定最易出錯，直接跳過
  - 解析度以「模型看得清楚、人也看得清楚」為準，不追求高 DPI（省 context/token）
  - 純確定性運算，不含 LLM：座標一旦定了，裁切就是算術，可重跑可 diff

輸入：figure_map.json（由 mark_figures Agent 產出）
格式：
{
  "source_pdf": "/abs/path/to/thesis.pdf",
  "figures": [
    {
      "id": "table-01",
      "page": 26,              # 1-indexed，與 PDF 頁碼一致
      "y_start": 0.12,         # 0.0-1.0 相對頁高比例，或給絕對 pt（見 units）
      "y_end": 0.48,
      "caption": "Table 1 氰基化反應之鎳催化劑之篩選圖",
      "anchor_text": "### Table 1 氰基化反應之鎳催化劑之篩選圖",
      "anchor_pos": "after"    # after | before
    }
  ],
  "units": "ratio"             # ratio(預設) | pt
}

用法：
    python3 crop_figures.py figure_map.json -o out_dir/
    python3 crop_figures.py figure_map.json -o out_dir/ --dpi 150
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("需要 PyMuPDF：pip install pymupdf")


DEFAULT_DPI = 150   # 實測足夠讀清 Table 數值與 Scheme 結構式，檔案約 100-200KB
PAD_RATIO = 0.01    # 上下各留 1% 頁高的邊距，避免切到字


def crop(map_path: Path, out_dir: Path, dpi: int, pad: float) -> dict:
    data = json.loads(map_path.read_text(encoding="utf-8"))
    pdf_path = Path(data["source_pdf"]).expanduser()
    if not pdf_path.exists():
        sys.exit(f"找不到來源 PDF：{pdf_path}")

    units = data.get("units", "ratio")
    figures = data.get("figures", [])
    if not figures:
        sys.exit("figure_map.json 沒有 figures 條目")

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    done, failed = [], []

    for fig in figures:
        fid = fig.get("id") or f"fig-{len(done)+1:03d}"
        try:
            pno = int(fig["page"]) - 1          # 轉 0-indexed
            if not (0 <= pno < len(doc)):
                raise ValueError(f"頁碼 {fig['page']} 超出範圍(共{len(doc)}頁)")

            page = doc[pno]
            rect = page.rect
            ph = rect.height

            if units == "ratio":
                y0 = float(fig["y_start"]) * ph
                y1 = float(fig["y_end"]) * ph
            else:
                y0 = float(fig["y_start"])
                y1 = float(fig["y_end"])

            # 加邊距並夾回頁面範圍內
            padpt = pad * ph
            y0 = max(rect.y0, y0 - padpt)
            y1 = min(rect.y1, y1 + padpt)
            if y1 <= y0:
                raise ValueError(f"y_end({y1:.1f}) 未大於 y_start({y0:.1f})")

            # 左右吃滿頁寬（老師指定：不切左右）
            clip = fitz.Rect(rect.x0, y0, rect.x1, y1)
            pix = page.get_pixmap(matrix=matrix, clip=clip)

            out_file = out_dir / f"{fid}.png"

            # 跨頁圖表：標題在頁尾、本體在次頁 → 上下拼接成一張
            cont = fig.get("continuation")
            if cont:
                cpage = doc[int(cont["page"]) - 1]
                crect = cpage.rect
                cy0 = float(cont["y_start"]) * crect.height
                cy1 = min(crect.y1, float(cont["y_end"]) * crect.height + padpt)
                if cy1 > cy0:
                    cpix = cpage.get_pixmap(
                        matrix=matrix,
                        clip=fitz.Rect(crect.x0, cy0, crect.x1, cy1))
                    w = max(pix.width, cpix.width)
                    merged = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w,
                                                               pix.height + cpix.height))
                    merged.clear_with(255)
                    pix.set_origin(0, 0)
                    cpix.set_origin(0, pix.height)
                    merged.copy(pix, pix.irect)
                    merged.copy(cpix, cpix.irect)
                    pix = merged

            pix.save(out_file)

            done.append({
                "id": fid,
                "file": out_file.name,
                "page": fig["page"],
                "size": f"{pix.width}x{pix.height}",
                "kb": round(out_file.stat().st_size / 1024, 1),
                "caption": fig.get("caption", ""),
                "anchor_text": fig.get("anchor_text", ""),
                "anchor_pos": fig.get("anchor_pos", "after"),
            })
        except Exception as e:
            failed.append({"id": fid, "page": fig.get("page"), "error": str(e)})

    doc.close()

    # 產出裁切結果清單，供 insert_figures.py 使用
    result = {
        "source_pdf": str(pdf_path),
        "out_dir": str(out_dir),
        "dpi": dpi,
        "cropped": done,
        "failed": failed,
    }
    (out_dir / "_crop_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main():
    ap = argparse.ArgumentParser(description="依座標檔從 PDF 裁切圖表")
    ap.add_argument("figure_map", help="figure_map.json 路徑")
    ap.add_argument("-o", "--out", required=True, help="輸出目錄")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI,
                    help=f"解析度，預設 {DEFAULT_DPI}（夠模型與人閱讀，省 token）")
    ap.add_argument("--pad", type=float, default=PAD_RATIO,
                    help=f"上下邊距比例，預設 {PAD_RATIO}")
    args = ap.parse_args()

    res = crop(Path(args.figure_map).expanduser(),
               Path(args.out).expanduser(), args.dpi, args.pad)

    print(f"\n來源：{res['source_pdf']}")
    print(f"輸出：{res['out_dir']}  (DPI={res['dpi']})")
    print(f"成功 {len(res['cropped'])} 張 | 失敗 {len(res['failed'])} 張")

    if res["cropped"]:
        total_kb = sum(c["kb"] for c in res["cropped"])
        print(f"\n已裁切（總計 {total_kb:.0f} KB）：")
        for c in res["cropped"][:30]:
            print(f"  p{c['page']:<4} {c['file']:<20} {c['size']:<12} {c['kb']:>6.1f}KB  {c['caption'][:36]}")
        if len(res["cropped"]) > 30:
            print(f"  …另外 {len(res['cropped']) - 30} 張")

    if res["failed"]:
        print(f"\n❌ 失敗：")
        for f in res["failed"]:
            print(f"  {f['id']} (p{f['page']}): {f['error']}")

    print(f"\n裁切結果清單：{Path(res['out_dir']) / '_crop_result.json'}")


if __name__ == "__main__":
    main()

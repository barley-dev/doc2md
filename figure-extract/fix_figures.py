#!/usr/bin/env python3
"""
反饋修正 — 對 figure_map.json 的個別座標做微調，重跑裁切。

【為何需要】稽核或目視發現某張圖切得不對（下緣切到最後一列、上緣多含一段正文），
不必重跑整個 mark_figures（那會覆蓋所有手動調整），只針對那一張改座標。
座標是可版本控管的中間產物——這支讓「改一張、重切一張」變得直接。

支援的調整（對單一 figure id）：
  --top    +0.03 / -20pt    上邊界移動（正=往下縮，負=往上擴）
  --bottom +0.03 / +20pt    下邊界移動（正=往下擴，負=往上縮）
  --set    y0,y1            直接指定新的上下邊界（ratio 或 pt）
  --drop                    刪除這張（誤判時）
  --anchor "### Table X"    改插入錨點

單位：數字後接 pt 為絕對點數，否則為頁高比例（ratio）。

用法：
    # 下緣多留 30pt（切到最後一列時）
    python3 fix_figures.py map.json --id table-05_p30 --bottom +30pt

    # 上緣往上擴 5%（標題被切掉時）
    python3 fix_figures.py map.json --id figure-02_p39 --top -0.05

    # 直接指定範圍
    python3 fix_figures.py map.json --id table-01_p33 --set 0.10,0.72

    # 刪除誤判
    python3 fix_figures.py map.json --id scheme-99_p40 --drop

改完自動重跑裁切（除非 --no-crop）並跑稽核，讓修正立即可見。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("需要 PyMuPDF：pip install pymupdf")

HERE = Path(__file__).parent


def parse_delta(s: str, page_height: float) -> float:
    """把 '+30pt' / '-0.05' 轉成 ratio 位移量。"""
    s = s.strip()
    sign = 1
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:]
    if s.endswith("pt"):
        return sign * float(s[:-2]) / page_height
    return sign * float(s)


def parse_coord(s: str, page_height: float) -> float:
    s = s.strip()
    if s.endswith("pt"):
        return float(s[:-2]) / page_height
    return float(s)


def main():
    ap = argparse.ArgumentParser(description="反饋修正 figure_map 座標")
    ap.add_argument("figure_map")
    ap.add_argument("--id", required=True, help="要調整的 figure id")
    ap.add_argument("--top", help="上邊界位移，如 -0.05 或 +20pt")
    ap.add_argument("--bottom", help="下邊界位移，如 +30pt")
    ap.add_argument("--set", help="直接指定 y0,y1")
    ap.add_argument("--anchor", help="改插入錨點文字")
    ap.add_argument("--drop", action="store_true", help="刪除這張")
    ap.add_argument("--out", help="裁切輸出目錄（預設同 map 所在目錄）")
    ap.add_argument("--no-crop", action="store_true", help="只改 JSON 不重跑裁切")
    args = ap.parse_args()

    mp = Path(args.figure_map).expanduser()
    data = json.loads(mp.read_text(encoding="utf-8"))
    figs = data.get("figures", [])

    target = next((f for f in figs if f["id"] == args.id), None)
    if not target:
        ids = ", ".join(f["id"] for f in figs)
        sys.exit(f"找不到 id={args.id}\n可用 id：{ids}")

    if args.drop:
        data["figures"] = [f for f in figs if f["id"] != args.id]
        mp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 已刪除 {args.id}")
        return

    # 取該頁高度（座標為 ratio，位移換算需頁高）
    doc = fitz.open(Path(data["source_pdf"]).expanduser())
    ph = doc[target["page"] - 1].rect.height
    doc.close()

    old = (target["y_start"], target["y_end"])

    if args.set:
        a, b = args.set.split(",")
        target["y_start"] = round(parse_coord(a, ph), 4)
        target["y_end"] = round(parse_coord(b, ph), 4)
    else:
        if args.top:
            target["y_start"] = round(max(0.0, target["y_start"] + parse_delta(args.top, ph)), 4)
        if args.bottom:
            target["y_end"] = round(min(1.0, target["y_end"] + parse_delta(args.bottom, ph)), 4)

    if args.anchor:
        target["anchor_text"] = args.anchor

    if target["y_end"] <= target["y_start"]:
        sys.exit(f"調整後 y_end({target['y_end']}) 未大於 y_start({target['y_start']})，未寫入")

    target["_height_pt"] = round((target["y_end"] - target["y_start"]) * ph, 1)
    mp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ {args.id}: y {old[0]:.3f}-{old[1]:.3f} → {target['y_start']:.3f}-{target['y_end']:.3f}"
          f" ({target['_height_pt']}pt)")

    if not args.no_crop:
        out = Path(args.out).expanduser() if args.out else mp.parent
        print(f"\n重跑裁切 → {out}")
        subprocess.run([sys.executable, str(HERE / "crop_figures.py"),
                        str(mp), "-o", str(out)], check=False)
        print(f"\n請 Read {out}/{args.id}.png 確認修正結果。")


if __name__ == "__main__":
    main()

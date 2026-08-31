#!/usr/bin/env python3
"""
偵測 doc2md 擷取失敗的圖片（全黑／全白／低資訊量）。

用途：doc2md 從 PDF 抽圖時，遇到某些 PDF 內部結構（遮罩、CMYK、向量疊層）
會抽出整片黑或整片白的廢圖。人工逐張看很慢，這支用像素統計快速篩出來。

判定邏輯（三選一即判為壞圖）：
  1. 標準差過低      → 整片同色（全黑/全白/純色塊）
  2. 極暗且方差小    → 全黑圖的典型特徵
  3. 唯一色階數過少  → 資訊量不足（例如只有 2-3 個灰階值）

用法：
    python3 detect_blank_images.py <images_dir> [--json out.json]
    python3 detect_blank_images.py <images_dir> --recursive   # 掃子目錄

輸出：stdout 摘要 + 可選 JSON 報告
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("需要 Pillow：pip install Pillow")


# 判定門檻（依實測校準，寧可誤報也不漏報——漏報等於分析建在讀不到的數據上）
STD_THRESHOLD = 8.0        # 灰階標準差低於此 → 幾乎同色
DARK_MEAN_THRESHOLD = 25.0  # 平均亮度低於此 → 極暗
DARK_STD_THRESHOLD = 20.0   # 配合極暗使用
MIN_UNIQUE_LEVELS = 6       # 唯一灰階數少於此 → 資訊量不足


def analyse(path: Path) -> dict:
    """回傳單張圖的統計與判定結果。"""
    try:
        with Image.open(path) as im:
            gray = im.convert("L")
            # 縮圖加速：大圖降到 200px 寬統計即足夠，判定結果不受影響
            if gray.width > 200:
                ratio = 200 / gray.width
                gray = gray.resize((200, max(1, int(gray.height * ratio))))
            pixels = list(gray.getdata())
            w, h = gray.width, gray.height
    except Exception as e:
        return {"file": path.name, "path": str(path), "error": str(e), "verdict": "error"}

    n = len(pixels)
    mean = sum(pixels) / n
    var = sum((p - mean) ** 2 for p in pixels) / n
    std = var ** 0.5
    unique = len(set(pixels))

    reasons = []
    if std < STD_THRESHOLD:
        reasons.append(f"標準差過低({std:.1f})")
    if mean < DARK_MEAN_THRESHOLD and std < DARK_STD_THRESHOLD:
        reasons.append(f"極暗(mean={mean:.1f})")
    if unique < MIN_UNIQUE_LEVELS:
        reasons.append(f"色階僅{unique}種")

    if reasons:
        verdict = "bad"
    elif std < STD_THRESHOLD * 2:
        verdict = "suspect"   # 邊緣案例，建議人工看一眼
    else:
        verdict = "ok"

    return {
        "file": path.name,
        "path": str(path),
        "size": f"{w}x{h}",
        "mean": round(mean, 1),
        "std": round(std, 1),
        "unique_levels": unique,
        "verdict": verdict,
        "reasons": reasons,
    }


def main():
    ap = argparse.ArgumentParser(description="偵測 doc2md 擷取失敗的圖片")
    ap.add_argument("images_dir", help="圖片目錄")
    ap.add_argument("--json", help="輸出 JSON 報告路徑")
    ap.add_argument("--recursive", action="store_true", help="遞迴掃描子目錄")
    args = ap.parse_args()

    root = Path(args.images_dir).expanduser()
    if not root.is_dir():
        sys.exit(f"找不到目錄：{root}")

    pattern = "**/*" if args.recursive else "*"
    files = sorted(
        p for p in root.glob(pattern)
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not files:
        sys.exit(f"{root} 下沒有圖片")

    results = [analyse(p) for p in files]

    bad = [r for r in results if r["verdict"] == "bad"]
    suspect = [r for r in results if r["verdict"] == "suspect"]
    ok = [r for r in results if r["verdict"] == "ok"]
    err = [r for r in results if r["verdict"] == "error"]

    print(f"\n掃描：{root}")
    print(f"總計 {len(results)} 張 | 壞圖 {len(bad)} | 可疑 {len(suspect)} | 正常 {len(ok)} | 讀取失敗 {len(err)}")

    if bad:
        pct = len(bad) / len(results) * 100
        print(f"\n❌ 壞圖（{pct:.0f}%）：")
        for r in bad[:40]:
            print(f"  {r['file']:<28} {', '.join(r['reasons'])}")
        if len(bad) > 40:
            print(f"  …另外 {len(bad) - 40} 張")

    if suspect:
        print(f"\n⚠️  可疑（建議人工確認）：")
        for r in suspect[:15]:
            print(f"  {r['file']:<28} std={r['std']}")
        if len(suspect) > 15:
            print(f"  …另外 {len(suspect) - 15} 張")

    if err:
        print(f"\n讀取失敗：")
        for r in err:
            print(f"  {r['file']}: {r['error']}")

    if args.json:
        out = Path(args.json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "scanned_dir": str(root),
            "total": len(results),
            "bad_count": len(bad),
            "suspect_count": len(suspect),
            "ok_count": len(ok),
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 報告：{out}")

    # 壞圖比例過高時明確提示需重新擷取
    if bad and len(bad) / len(results) > 0.3:
        print(f"\n⚠️  壞圖比例超過 30%，此文件的圖片擷取應視為失敗，需從原 PDF 重切。")


if __name__ == "__main__":
    main()

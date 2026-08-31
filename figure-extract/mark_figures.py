#!/usr/bin/env python3
"""
從 PDF 自動偵測圖表邊界，產出 figure_map.json。

【為何用程式而非 VLM】（2026-07-24 實測結論）
原生 PDF（Word 匯出）的檔案結構本身就記著座標：
  - 標題文字（"Table 4 …"）的 bbox → PyMuPDF 直接讀得到
  - 圖片物件的 bbox → PDF 內部就有
  - 文字流中斷的大間隙 → 圖表所在位置
實測吳穎柔 p29：內文行距穩定 13.7pt，圖表處間隙 365.9pt（27 倍），
圖片 bbox y=131-435。三個訊號互相驗證，精確到 pt——VLM 目測反而更差。
VLM 只在「純掃描 PDF 無文字層」時才需要（本批論文皆非此類）。

偵測邏輯：
  1. 找標題行（Table/Scheme/Figure + 編號，或中文「表/圖」+編號）
  2. 從標題往下找內容範圍：圖片 bbox ∪ 大間隙區 ∪ 表格文字列
  3. 下邊界收在「下一個標題」或「正文段落重新開始」之前
  4. 含入腳註（如 "a 1 equiv: 0.5mmol"）

用法：
    python3 mark_figures.py <pdf> --pages 25-42 --md <target.md> -o figure_map.json
    python3 mark_figures.py <pdf> --pages 25-42 --md <target.md> -o out.json --report
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


# 圖表標題樣態。OCR 雜訊容忍：允許標題字之間有空白
CAPTION_RE = re.compile(
    r"^\s*(Table|Scheme|Figure|Fig\.?|Chart|Eq\.?|表|圖|式)\s*([0-9]{1,3})\s*[.、:：]?\s*(.*)",
    re.IGNORECASE,
)

# 正文段落特徵：夠長且不是標題
BODY_MIN_CHARS = 28
# 間隙超過行距幾倍算「圖表空白區」
GAP_FACTOR = 2.2
# 腳註特徵（表格下方的小字註解）
FOOTNOTE_RE = re.compile(r"^\s*[a-zA-Zᵃ-ᵒ]?\s*\d*\s*(equiv|eq\b|mmol|條件|reaction|isolated|yield|determined|GC|NMR)", re.IGNORECASE)


def is_table_row(text: str) -> bool:
    """判斷一個文字塊是否為表格資料列（而非正文段落）。

    為何需要：純文字表格（無向量框線）的資料列在 PDF 裡就是 text block，
    若當成正文會讓表格只切到表頭（實測方世文 Table 2）。

    表格列特徵：以 entry 編號開頭、含實驗數據記號（%、N.D.、trace、<5）、
    或短且不含中文句子結構。
    """
    t = text.strip()
    if not t:
        return False
    # entry 編號開頭（1 / 1) / 1. 後接內容）
    if re.match(r"^\d{1,2}[\s.)]", t) and len(t) < 110:
        return True
    # 含典型實驗結果記號
    if re.search(r"(N\.?D\.?|n\.?d\.?|trace|Trace|<\s*\d|\d\s*%)", t) and len(t) < 110:
        return True
    # 短片語且無中文句末標點（表格欄位內容，如 "Nickel Iodide"）
    if len(t) < 46 and not re.search(r"[，。；、]", t):
        return True
    return False


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def parse_pages(spec: str, npages: int):
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(p for p in out if 1 <= p <= npages)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"^#+\s*", "", s.strip())).lower()


def find_anchor(md_lines, caption: str):
    """在 Markdown 找對應標題行。回傳原文行，找不到回空字串。

    OCR 雜訊處理：用「型別+編號」當骨架比對（如 Table+4），
    因為標題描述文字常被 OCR 汙染，但型別與編號通常穩定。
    """
    m = CAPTION_RE.match(caption)
    if not m:
        return ""
    kind, num = m.group(1).lower(), m.group(2)

    # 型別的等價集合（中英對照 + OCR 常見替換）
    kind_alts = {
        "table": ["table", "表"], "表": ["table", "表"],
        "scheme": ["scheme", "式"], "式": ["scheme", "式"],
        "figure": ["figure", "fig", "圖"], "fig": ["figure", "fig", "圖"],
        "圖": ["figure", "fig", "圖"],
    }.get(kind, [kind])

    best = ""
    for ln in md_lines:
        n = norm(ln)
        if not n:
            continue
        for k in kind_alts:
            # 型別後緊接編號（容忍中間有全形/半形空白，已被 norm 去除）
            if re.search(rf"{re.escape(k)}{num}(?![0-9])", n):
                # 優先取 Markdown 標題行（以 # 開頭）
                if ln.strip().startswith("#"):
                    return ln
                if not best:
                    best = ln
    return best


def detect_page(page, md_lines, page_no):
    """偵測單頁的圖表，回傳 figure 清單。"""
    blocks = [b for b in page.get_text("blocks") if b[4].strip()]
    if not blocks:
        return []
    blocks.sort(key=lambda b: b[1])

    ph = page.rect.height
    heights = [b[3] - b[1] for b in blocks if (b[3] - b[1]) < 40]
    line_h = median(heights) or 13.0

    # 圖片物件 bbox
    img_boxes = []
    try:
        for im in page.get_image_info():
            bb = im.get("bbox")
            if bb and (bb[3] - bb[1]) > line_h:
                img_boxes.append((bb[1], bb[3]))
    except Exception:
        pass

    # 找標題行
    caps = []
    for i, b in enumerate(blocks):
        first = b[4].strip().split("\n")[0].strip()
        m = CAPTION_RE.match(first)
        if not m or len(first) >= 120:
            continue
        # 排除「以正文句子開頭且引用了圖表編號」的假標題。
        # 實測樣態：賴翌豪「Table 1 中比較不同配體對於反應的影響，於此得到…」
        #          方世文「Table 2 所示。當使用 NiBr2·diglyme 作為鎳前催化劑時，…」
        # 判準：編號後緊接中文虛詞（中/所/如/為/是/則/顯示/可知…）＝正文引用，非標題
        rest = (m.group(3) or "").strip()
        if re.match(r"^(中|所|如|為|是|則|與|和|及|的|之|顯示|可知|可以|說明|指出|列出|整理)", rest):
            continue
        # 標題通常不含句末標點（逗號/句號在中段即為敘述句）
        if re.search(r"[，。；]", rest[:24]):
            continue
        caps.append({"idx": i, "y0": b[1], "y1": b[3], "text": first})

    if not caps:
        return []

    # 找出「圖在標題上方」的排版：標題上方有大片空白（向量圖形，無 image bbox），
    # 且標題下方緊接正文段落。此類 caption 的圖在上、不可往下 gap-walk。
    # 實測方世文 p39 Figure 2：標題 y352，上方 y119-352 空白是機構圖，下方是 EPR 段落。
    def caption_above_figure(cap, ci):
        prev_bottom = 0.0
        for b in blocks:
            if b[3] <= cap["y0"] - 1:
                prev_bottom = max(prev_bottom, b[3])
        blank_above = cap["y0"] - prev_bottom
        # 標題正下方緊接的是正文（長句），非表格列/圖
        next_b = None
        for b in sorted(blocks, key=lambda b: b[1]):
            if b[1] > cap["y1"] + 1 and not re.fullmatch(r"\d{1,3}", b[4].strip()):
                next_b = b
                break
        below_is_body = (next_b is not None
                         and len(next_b[4].replace("\n", " ").strip()) >= BODY_MIN_CHARS
                         and not is_table_row(next_b[4].replace("\n", " ").strip()))
        return blank_above > line_h * 4 and prev_bottom > line_h and below_is_body

    figs = []
    for ci, cap in enumerate(caps):
        i = cap["idx"]
        y_start = cap["y0"]
        # 下一個標題的位置（作為硬上限）
        next_cap_y = caps[ci + 1]["y0"] if ci + 1 < len(caps) else ph

        # 圖在標題上方 → 上擴到空白起點、下緣止於標題，不往下 gap-walk
        if caption_above_figure(cap, ci):
            prev_bottom = 0.0
            for b in blocks:
                if b[3] <= cap["y0"] - 1:
                    prev_bottom = max(prev_bottom, b[3])
            floor = caps[ci - 1]["y1"] if ci > 0 else 0.0
            y_start = max(prev_bottom + 2, floor + 2)
            y_end = cap["y1"] + line_h * 0.5
            m = CAPTION_RE.match(cap["text"])
            kind = (m.group(1) or "fig").lower()
            kind = {"表": "table", "圖": "figure", "式": "scheme",
                    "fig": "figure", "fig.": "figure"}.get(kind, kind)
            figs.append({
                "id": f"{kind}-{int(m.group(2)):02d}_p{page_no}",
                "page": page_no,
                "y_start": round(y_start / ph, 4),
                "y_end": round(y_end / ph, 4),
                "caption": cap["text"],
                "anchor_text": find_anchor(md_lines, cap["text"]),
                "anchor_pos": "after",
                "_height_pt": round(y_end - y_start, 1),
                "_title_only": False,
            })
            continue

        # 從標題往下擴展
        y_end = cap["y1"]
        for b in blocks[i + 1:]:
            by0, by1, txt = b[1], b[3], b[4].strip()
            if by0 >= next_cap_y:
                break
            plain = txt.replace("\n", " ").strip()
            gap = by0 - y_end

            is_footnote = bool(FOOTNOTE_RE.match(plain)) and len(plain) < 120
            is_pagenum = bool(re.fullmatch(r"\d{1,3}", plain))
            is_row = is_table_row(plain)

            if is_pagenum:
                continue
            # 純文字表格：資料列本身是 text block（無向量框線），
            # 不可當成正文而中止。實測樣態：方世文 Table 2 六列資料全是 text block，
            # 誤判為正文會讓表格只切到表頭。
            is_body = (len(plain) >= BODY_MIN_CHARS
                       and gap < line_h * GAP_FACTOR
                       and not is_row)
            if is_body and not is_footnote:
                break  # 正文重新開始 → 圖表結束
            y_end = max(y_end, by1)

        # 併入與此區間重疊的圖片 bbox
        for iy0, iy1 in img_boxes:
            if iy0 < next_cap_y and iy1 > cap["y0"] - line_h * 2:
                y_start = min(y_start, iy0)
                y_end = max(y_end, iy1)

        # 表格本體常是「緊接標題下方的圖片物件」，中間無文字塊，
        # 上面的 gap-walk 走不到。這裡直接找標題下方最近的圖片並併入。
        # 實測樣態：吳穎柔 Table 6（標題 y497，圖 y183-365 在標題上方）
        #          與 Table 7（標題 y452，圖 y562-724 在標題下方）兩種都有。
        if (y_end - y_start) < line_h * 2.2:
            prev_cap_y1 = caps[ci - 1]["y1"] if ci > 0 else 0.0
            for iy0, iy1 in img_boxes:
                # 一張圖只屬於離它最近的標題。若某圖在下一個標題之後、或離下一個
                # 標題更近，就不是本圖的（實測方世文 p39：EPR 圖在 Figure 2 標題下方，
                # 但它是 Figure 3 的圖，不可被 Figure 2 認領）。
                img_mid = (iy0 + iy1) / 2
                closer_to_next = (next_cap_y < ph and
                                  abs(img_mid - next_cap_y) < abs(img_mid - cap["y0"]))
                if closer_to_next:
                    continue
                # 標題下方最近的圖（表格/圖形本體在標題下方）
                if 0 <= iy0 - cap["y1"] < line_h * 8 and iy0 < next_cap_y:
                    y_end = max(y_end, iy1)
                # 標題上方緊鄰的圖（標題在圖下方的排版，Figure 常見）。
                # 上緣不可越過前一個標題，否則會吃掉前一張圖。
                elif 0 <= cap["y0"] - iy1 < line_h * 10:
                    y_start = min(y_start, max(iy0, prev_cap_y1 + 1))

        # 標題與內容之間若有大間隙（圖在標題下方且無文字），延伸到間隙結束
        y_end = min(y_end, next_cap_y - 2, ph)
        if y_end <= y_start:
            continue

        m = CAPTION_RE.match(cap["text"])
        kind = (m.group(1) or "fig").lower()
        kind = {"表": "table", "圖": "figure", "式": "scheme", "fig": "figure",
                "fig.": "figure"}.get(kind, kind)
        fid = f"{kind}-{int(m.group(2)):02d}_p{page_no}"

        height = y_end - y_start
        # 標題在頁尾、內容續到下一頁：此頁只有標題（高度僅一行），
        # 標為 continues_next 讓呼叫端接續下一頁頂端。
        # 實測樣態：吳穎柔 Table 5/6、陳冠廷 Table 2 皆為此類。
        # 只有標題、頁面其餘皆空 → 表格必在後續頁（scope 表常橫跨數頁）。
        # 不限「標題在頁尾」：實測方世文 Table 9 標題在頁首 (0.093)，
        # 整頁再無其他內容，表格從次頁開始。
        # 標題後方（同頁）已無任何內容 → 表格必在後續頁。
        # 不能只看 len(blocks)：標題前方可能有整頁正文（實測方世文 Table 10，
        # 標題在 y0.319、其後整頁空白，但全頁有 8 個 block）。
        after_blocks = [b for b in blocks
                        if b[1] > cap["y1"] + 1
                        and not re.fullmatch(r"\d{1,3}", b[4].strip())]
        nothing_after = len(after_blocks) == 0
        near_bottom = (y_end / ph) > 0.82 or nothing_after
        title_only = height < line_h * 2.2

        figs.append({
            "id": fid,
            "page": page_no,
            "y_start": round(y_start / ph, 4),
            "y_end": round(y_end / ph, 4),
            "caption": cap["text"],
            "anchor_text": find_anchor(md_lines, cap["text"]),
            "anchor_pos": "after",
            "_height_pt": round(height, 1),
            "_title_only": bool(title_only and near_bottom),
        })
    return figs


def link_continuations(figs, doc):
    """把「頁尾只有標題」的圖表接續到下一頁頂端的內容區。

    為何需要：中文論文常把表格標題留在頁尾、表格本體排到次頁。
    若不處理，會切出只有一行標題的 13pt 廢圖（實測五篇皆有此樣態）。
    """
    by_page = {}
    for f in figs:
        by_page.setdefault(f["page"], []).append(f)

    for f in figs:
        if not f.get("_title_only"):
            continue
        nxt = f["page"] + 1
        if nxt > len(doc):
            continue
        page = doc[nxt - 1]
        ph = page.rect.height
        blocks = sorted([b for b in page.get_text("blocks") if b[4].strip()],
                        key=lambda b: b[1])
        if not blocks:
            continue

        # 次頁頂端到「第一個正文段落 / 第一個新標題」之前，即為續接的表格本體
        heights = [b[3] - b[1] for b in blocks if (b[3] - b[1]) < 40]
        line_h = median(heights) or 13.0
        y_end = blocks[0][3]
        for b in blocks:
            plain = b[4].replace("\n", " ").strip()
            if re.fullmatch(r"\d{1,3}", plain):
                continue
            if CAPTION_RE.match(plain) and b[1] > blocks[0][1] + line_h:
                break
            # 表格資料列不可視為正文而中止（同 detect_page 的理由）
            if (len(plain) >= BODY_MIN_CHARS
                    and not FOOTNOTE_RE.match(plain)
                    and not is_table_row(plain)):
                break
            y_end = max(y_end, b[3])
        # 次頁若為圖片型表格（無文字或極少），延伸到圖片下緣
        if not blocks or (y_end / ph) < 0.25:
            y_end = max(y_end, ph * 0.92)

        # 併入次頁的圖片 bbox
        try:
            for im in page.get_image_info():
                bb = im.get("bbox")
                if bb and bb[1] < y_end + line_h * 3:
                    y_end = max(y_end, bb[3])
        except Exception:
            pass

        f["continuation"] = {
            "page": nxt,
            "y_start": 0.0,
            "y_end": round(min(y_end / ph, 1.0), 4),
        }
        # 若次頁「幾乎整頁都是續接內容」，表格可能還跨更多頁（scope 表常見）。
        # 記錄總跨頁數供稽核提示，實際裁切僅接第一續頁（多頁拼接圖過大不利閱讀）。
        if (y_end / ph) > 0.85:
            span = 2
            for extra in range(nxt + 1, min(nxt + 4, len(doc) + 1)):
                ep = doc[extra - 1]
                eb = [b for b in ep.get_text("blocks") if b[4].strip()]
                # 續頁特徵：內容稀疏（表格為圖）或以資料列為主
                if len(eb) <= 2 or all(is_table_row(b[4].replace("\n", " ").strip())
                                       for b in eb[:6]):
                    span += 1
                else:
                    break
            if span > 2:
                f["continuation"]["spans_more"] = span
    return figs


def main():
    ap = argparse.ArgumentParser(description="從 PDF 自動偵測圖表邊界")
    ap.add_argument("pdf")
    ap.add_argument("--pages", required=True, help="頁範圍，如 25-42 或 25,27,30-33")
    ap.add_argument("--md", help="目標 Markdown（用於比對插入錨點）")
    ap.add_argument("-o", "--out", required=True, help="輸出 figure_map.json")
    ap.add_argument("--report", action="store_true", help="印出詳細偵測報告")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser()
    doc = fitz.open(pdf_path)
    pages = parse_pages(args.pages, len(doc))

    md_lines = []
    if args.md:
        p = Path(args.md).expanduser()
        if p.exists():
            md_lines = p.read_text(encoding="utf-8").split("\n")

    all_figs = []
    empty_pages = []
    for pno in pages:
        figs = detect_page(doc[pno - 1], md_lines, pno)
        if not figs:
            empty_pages.append(pno)
        all_figs.extend(figs)
    link_continuations(all_figs, doc)
    doc.close()

    out = {
        "source_pdf": str(pdf_path),
        "target_md": str(Path(args.md).expanduser()) if args.md else "",
        "units": "ratio",
        "scanned_pages": args.pages,
        "figures": all_figs,
    }
    op = Path(args.out).expanduser()
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    kinds = {}
    for f in all_figs:
        k = f["id"].split("-")[0]
        kinds[k] = kinds.get(k, 0) + 1
    no_anchor = [f for f in all_figs if not f["anchor_text"]]
    tiny = [f for f in all_figs if f["_height_pt"] < 40]

    print(f"\nPDF：{pdf_path.name}")
    print(f"掃描頁：{args.pages}（{len(pages)} 頁）")
    print(f"偵測到 {len(all_figs)} 張圖表 " + " ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print(f"無錨點 {len(no_anchor)} 張 | 過小(<40pt，疑誤判) {len(tiny)} 張 | 無圖表頁 {len(empty_pages)}")

    if args.report and all_figs:
        print(f"\n{'ID':<22}{'頁':>4}  {'y範圍':<16}{'高度':>7}  錨點  標題")
        for f in all_figs:
            a = "✓" if f["anchor_text"] else "✗"
            print(f"  {f['id']:<20}{f['page']:>4}  {f['y_start']:.3f}-{f['y_end']:.3f}  "
                  f"{f['_height_pt']:>6.0f}pt  {a}    {f['caption'][:38]}")

    if empty_pages:
        print(f"\n無圖表頁：{empty_pages}")
    if no_anchor:
        print(f"\n⚠️ 找不到 Markdown 錨點（插入時會跳過）：")
        for f in no_anchor[:10]:
            print(f"   {f['id']}  {f['caption'][:50]}")
    if tiny:
        print(f"\n⚠️ 高度過小，可能是誤判或圖被切掉：")
        for f in tiny[:10]:
            print(f"   {f['id']}  {f['_height_pt']}pt  {f['caption'][:44]}")

    print(f"\n輸出：{op}")


if __name__ == "__main__":
    main()

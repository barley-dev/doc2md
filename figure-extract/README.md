# figure-extract — 論文圖表重切工具鏈

從原 PDF 精準切出 Table / Scheme / Figure，插回 doc2md 產出的 Markdown。
**純 Python，無 LLM**：可重跑、可 diff、零 token 成本。

## 為何需要（實測診斷，2026-07-24）

doc2md 對某些 PDF 的圖片擷取會大規模失敗。實測五篇碩士論文
（「Markdown 內提及圖表次數」vs「實際抓到 PNG 數」）：

| 論文 | 頁數 | 文中提及 | 實際抓到 | 流失率 |
|---|---|---|---|---|
| A | 384 | 279 處 | 2 張 | **99%** |
| B | 274 | 204 處 | 4 張 | **98%** |
| C | 241 | 89 處 | 1 張 | **99%** |
| D | 108 | 82 處 | 54 張（8 張全黑）| 44% |
| E | 128 | 131 處 | 128 張 | 少數 |

**後果**：在此狀態下做的論文分析，是看不到任何數據表的。
實測案例中，重切後才發現「正文引用值與表中不符」「機構圖氧化態不守恆」等關鍵問題——
**只讀 Markdown 一個都抓不到。**

## 為何用程式而非 VLM

原生 PDF（Word 匯出）的檔案結構本身就記著座標：

- 標題文字 bbox → PyMuPDF 直接讀得到
- 圖片物件 bbox → PDF 內部就有
- 文字流中斷的大間隙 → 圖表所在

實測某頁：內文行距穩定 13.7pt，圖表處間隙 365.9pt（27 倍），圖片 bbox y=131–435。
三訊號互相驗證，**精確到 pt——VLM 目測反而更差**，且每頁進 context 燒 token。

VLM 只在「純掃描 PDF 無文字層」時才需要。

## 七支工具

```
detect_blank_images.py   偵測既有圖片是否全黑/全白（診斷用，可選）
        ↓
mark_figures.py          偵測圖表邊界 → figure_map.json  ← 人可在此攔截校正
        ↓
audit_figures.py         稽核座標，產出目視抽查清單       ← 必跑
        ↓
crop_figures.py          裁切為 PNG
        ↓
fix_figures.py           反饋修正：微調個別座標、重跑裁切  ← 稽核/目視發現問題時
        ↓
confirm_figures.py       確認 gate：目視清單可勾選，全確認才放行  ← 插入前必過
        ↓
insert_figures.py        依錨點插回 Markdown（預設 dry-run）
```

### 反饋修正（fix_figures.py）

稽核或目視發現某張切得不對，不必重跑整個 mark（會覆蓋手動調整），只改那一張：

```bash
python3 fix_figures.py map.json --id table-05_p30 --bottom +30pt   # 下緣多留 30pt
python3 fix_figures.py map.json --id figure-02_p39 --top -0.05     # 上緣往上擴 5%
python3 fix_figures.py map.json --id table-01_p33 --set 0.10,0.72  # 直接指定
python3 fix_figures.py map.json --id scheme-99_p40 --drop          # 刪除誤判
```

改完自動重跑裁切，Read 該 PNG 確認即可。

### 確認 gate（confirm_figures.py）

稽核抓得出「可疑」，抓不出「張冠李戴」。故插入前必須有一道確認閘門，
且確認結果落成檔案、可追溯：

```bash
python3 confirm_figures.py init map的crop_result.json    # 建 _confirm.json
python3 confirm_figures.py mark _confirm.json --id X --ok       # 逐張 Read PNG 後標記
python3 confirm_figures.py mark _confirm.json --id Y --bad "標題配錯圖"
python3 confirm_figures.py gate _confirm.json           # 有 bad 或 pending 則 exit 1
```

gate 通過（exit 0）才跑 insert_figures.py。bad 的先 fix_figures 修正、再標 --fixed。

**為何標記與裁切拆開**：裁切與插入是確定性算術，不該重複做。
座標存成 JSON 後可版本控管、可手改——某張切歪只需改 JSON 重跑裁切，不必重跑偵測。

## 使用

```bash
# 1. 偵測（--report 印詳細表）
python3 mark_figures.py thesis.pdf --pages 25-42 --md thesis.md -o map.json --report

# 2. 稽核（有 ❌ 必處理項目時回傳 exit 1）
python3 audit_figures.py map.json

# 3. 裁切
python3 crop_figures.py map.json -o figures/

# 4. 稽核（加檔案層檢查）
python3 audit_figures.py map.json --crop-dir figures/

# 5. 目視確認清單上的圖，確認無誤後插入
python3 insert_figures.py figures/_crop_result.json thesis.md          # dry-run
python3 insert_figures.py figures/_crop_result.json thesis.md --apply
```

## 切割規格

- **只切上下邊界，左右吃滿頁寬**——左右邊界判定最易出錯，跳過可大幅降低失敗率
- **150 DPI**——以「模型看得清楚、人也看得清楚」為準，不追求高解析度（省 context/token）。
  實測整頁 ≈ 195 KB，單表 30–170 KB，表格數值清晰可讀
- 自動含入腳註（reaction conditions 等），那常是判讀當量/產率基準的關鍵

## 已知排版樣態（實測五篇歸納，皆已處理）

| 樣態 | 症狀 | 處理 |
|---|---|---|
| **跨頁表格** | 標題在頁尾、本體在次頁 → 只切到一行標題 | `link_continuations()` + 裁切時上下拼接 |
| **標題下方圖片** | 表格本體是圖片物件、中間無文字 → gap-walk 走不到 | 找標題鄰近 image bbox 併入 |
| **純文字表格** | 資料列本身是 text block → 被當正文而中止，**只切到表頭** | `is_table_row()` 辨識資料列 |
| **正文假標題** | 「Table 1 中比較不同…」是敘述句被誤判成標題 | 編號後接中文虛詞則排除 |
| **圖片型表格** | 表格是整張圖，文字層無資料列 → 稽核誤報 | 改判 image bbox 覆蓋率，列入必看目視清單 |

⚠️ **最危險的是「純文字表格只切到表頭」**：切出來有標題有表頭，看起來像成功了，
但資料列全沒了。**純靠「跑完沒報錯」會靜默通過——這就是稽核步驟必須存在的理由。**

## 稽核三層

- **L1 幾何**：高度異常、範圍重疊、座標越界、錨點缺失
- **L2 內容**：讀 PDF 文字層，確認範圍內有資料列與腳註特徵；
  圖片型表格自動改用 image bbox 覆蓋率判定
- **L3 目視清單**：挑出最該人工看的（跨頁的、圖片型的、有 issue 的、最大與最小各一）

稽核**不保證正確，只保證「可疑的一定被列出來」**。
程式證明不了的（如圖片型表格的內容），一律列入必看，交給人或 VLM 確認。

## 限制

- 純掃描 PDF（無文字層）不適用——那種情況需要 VLM
- 標題格式需可辨識（`Table 1` / `表 1` / `Scheme 2` 等）；完全無編號的圖抓不到
- 錨點比對用「型別+編號」骨架，容忍 OCR 汙染的描述文字，
  但若 Markdown 連編號都錯就會失配（會在報告中列為「無錨點」）

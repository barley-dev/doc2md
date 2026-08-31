> **本文件位置：** ~/資料/Tools/doc2md/docs/textbook-upgrade-spec.md
> **建立日期：** 2026-04-12
> **版本基準：** doc2md v0.9.0
> **需求來源：** Bruice 教科書 PDF→Markdown 轉檔任務審查

# doc2md 教科書支援升級需求說明書

## 一、背景

doc2md v0.9.0 的 PDF 轉換管線針對學術期刊設計（噪音過濾、VLM prompt、標題偵測模式）。現需處理大學教科書（Bruice《Essential Organic Chemistry》3rd Ed.，21 章），發現以下落差：

| 現有能力 | 教科書需求 | 落差 |
|---------|-----------|------|
| 正文按 PDF 串流讀取 | 部分頁面雙欄排版 | 雙欄正文會錯位拼接 |
| VLM prompt 硬編碼（化學論文） | 教科書圖片類型更多元 | 無法自訂 prompt |
| `--render-pages` 和 `--vlm` 各自渲染 | 需同時整頁渲染 + VLM 描述 | 重複渲染浪費時間 |
| 28 條噪音 regex 全為期刊專用 | 教科書有出版社廣告、MasteringChemistry 等 | 教科書噪音無對應規則 |
| VLM 最大回應 1024 tokens | 教科書頁面內容密度高（習題頁多結構式） | 可能截斷描述 |
| VLM 僅支援 claude-haiku-4-5 | 可能需要 Gemini 或其他模型 | 後端不可替換 |

---

## 二、需求清單

### P0：必須實作（阻塞教科書轉檔）

#### R1. VLM Prompt 可自訂

**現狀：** `_VLM_PROMPT` 硬編碼在 `vlm_describer.py`，內容為化學論文語境（Scheme/Figure/Table），使用者無法更換。

**需求：**
- 支援 `--vlm-prompt <file>` 參數，載入外部 prompt 文字檔
- 未指定時使用現有預設 prompt（向後相容）
- prompt 檔案為純文字，不需特殊格式

**驗收標準：**
```bash
# 使用自訂 prompt
python3 doc2md.py ch5.pdf -o out/ --vlm --vlm-prompt textbook_prompt.txt

# 未指定時行為不變
python3 doc2md.py paper.pdf -o out/ --vlm
```

#### R2. VLM 最大回應 token 可調

**現狀：** `max_tokens=1024` 硬編碼在 `vlm_describer.py` 的 API 呼叫中。

**需求：**
- 支援 `--vlm-max-tokens <int>` 參數，預設維持 1024
- 教科書場景建議值：4096（習題頁面結構式多，描述需要更多空間）

**驗收標準：**
```bash
python3 doc2md.py ch5.pdf -o out/ --vlm --vlm-max-tokens 4096
```

---

### P1：建議實作（提升品質）

#### R3. 教科書噪音過濾規則

**現狀：** `utils/text.py` 的 `filter_journal_noise()` 有 28 條期刊 regex，教科書噪音無對應規則。

**需求：**
- 新增教科書噪音 regex 集合（與期刊集合並列，不取代）
- 透過 `--noise-profile` 參數切換：`journal`（預設）/ `textbook` / `none`
- 教科書噪音初始規則：

| 規則 | 樣式 | 說明 |
|------|------|------|
| TB#1 | `MasteringChemistry` | 出版社線上平台廣告 |
| TB#2 | `(?i)www\.\w+\.com/\w+` | 教科書內的出版社 URL |
| TB#3 | `(?i)ISBN[\s:-]*[\dX-]+` | ISBN 編號 |
| TB#4 | 頁碼行（僅含數字 + 章名的短行） | 教科書頁首頁尾 |

- 保留安全閥（超過 150 字元不過濾）

**驗收標準：**
```bash
# 教科書模式
python3 doc2md.py ch5.pdf -o out/ --noise-profile textbook

# 完全關閉噪音過濾
python3 doc2md.py ch5.pdf -o out/ --noise-profile none
```

#### R4. 整頁渲染與 VLM 共用渲染結果

**現狀：** `--render-pages` 和 `--vlm` 各自獨立呼叫 `page.get_pixmap()`，同時使用時每頁渲染兩次。

**需求：**
- 同時啟用 `--render-pages --vlm` 時，渲染一次，兩個功能共用 PNG
- 不影響只用其中一個旗標的行為

**驗收標準：**
- 同時啟用兩旗標時，log 顯示每頁只渲染一次
- 產出結果與分別使用時一致

#### R5. VLM 指定頁面範圍

**現狀：** `--vlm` 對所有頁面執行 VLM 描述，無法指定範圍。

**需求：**
- 支援 `--vlm-pages <range>` 參數，格式如 `1-5,10,15-20`
- 未指定時對所有頁面執行（向後相容）
- 用途：測試階段只跑幾頁驗證品質，不需跑全文

**驗收標準：**
```bash
# 只對第 7、12、25 頁做 VLM
python3 doc2md.py ch5.pdf -o out/ --vlm --vlm-pages 7,12,25
```

---

### P2：未來考慮（不阻塞當前任務）

#### R6. VLM 後端可替換

**現狀：** `vlm_describer.py` 直接呼叫 Anthropic API，模型固定為 `claude-haiku-4-5`。

**需求：**
- 支援 `--vlm-backend` 參數切換後端：`claude`（預設）/ `gemini` / `openai`
- 各後端需要的環境變數：`ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY`
- 參考：Microsoft markitdown 的 `--llm-client` 設計

**備註：** 待 VLM 比較測試（Claude vs Gemini）結果出來後再決定是否實作。若 Claude 品質足夠，此需求可降為 P3。

#### R7. 雙欄正文重組

**現狀：** 正文按 PDF 串流順序讀取，表格偵測有雙欄感知（Entry-anchored），但正文段落無雙欄重組。

**需求：**
- 偵測頁面是否為雙欄排版（基於文字 block 的 x 座標分布）
- 若為雙欄，先讀左欄再讀右欄

**備註：** 實作複雜度高，且教科書雙欄頁面比例待確認。建議先跑 Chapter 5 看實際影響程度再決定優先級。若雙欄頁面少或影響可忍受，可改為人工後處理。

---

## 三、架構升級：Profile 系統

### 問題

R1-R3 如果各自加 CLI 參數，程式碼會膨脹且每新增一種文件類型就要改源碼。根本問題是**領域知識（domain knowledge）和轉換邏輯（conversion logic）混在一起**。

| 目前硬編碼在程式中 | 本質 | 應該在哪 |
|-------------------|------|---------|
| `_VLM_PROMPT`（化學論文語境） | 領域知識 | profile |
| 28 條期刊 noise regex | 領域知識 | profile |
| 標題偵測的 academic 正則 | 領域知識 | profile |
| `max_tokens=1024` | 場景參數 | profile |
| PyMuPDF 圖片擷取邏輯 | 轉換邏輯 | 程式碼（不動） |
| 頁首頁尾重複率閾值 | 轉換邏輯 | 程式碼（不動） |

### 目標架構

```
doc2md/
├── doc2md.py              # 轉換引擎（不膨脹）
├── converters/            # 各格式轉換邏輯（不動）
├── utils/                 # 通用工具（不動）
├── profiles/              # ← 新增：領域知識外部化
│   ├── default.yaml       # 最小化預設（無噪音規則、通用 VLM prompt）
│   ├── journal.yaml       # 現有邏輯搬出來（期刊 noise regex、論文 VLM prompt）
│   └── textbook.yaml      # 教科書專用（教科書 noise、教科書 VLM prompt）
└── prompts/               # ← 新增：VLM prompt 模板
    ├── journal.txt        # 現有 _VLM_PROMPT 搬出來
    └── textbook.txt       # 教科書版 VLM prompt
```

### Profile 格式（概念）

```yaml
name: textbook
vlm:
  prompt_file: prompts/textbook.txt
  max_tokens: 4096
  model: claude-haiku-4-5
noise:
  rules:
    - pattern: "MasteringChemistry"
    - pattern: "(?i)ISBN[\\s:-]*[\\dX-]+"
    - pattern: "(?i)www\\.\\w+\\.com/\\w+"
  safety_threshold: 150
headings:
  patterns:
    - "^Chapter\\s+\\d+"
    - "^\\d+\\.\\d+\\s+"
```

### CLI 介面

```bash
# 使用教科書 profile
python3 doc2md.py ch5.pdf -o out/ --profile textbook

# 使用期刊 profile（等同現有行為）
python3 doc2md.py paper.pdf -o out/ --profile journal

# 未指定 → default profile
python3 doc2md.py file.pdf -o out/
```

### 好處

- R1（自訂 prompt）、R2（max tokens）、R3（噪音規則）自動解決——都是 profile 欄位
- 新增文件類型只加 .yaml + .txt，不改程式碼
- 使用者不需要懂 Python，改 yaml 就好

### 與 R1-R5 的關係

Profile 系統是 R1-R3 的**實作方式**，不是額外需求。R4（共用渲染）和 R5（指定頁面）仍是程式碼層級的改動，與 profile 無關。

---

## 四、qmd 輔助工作流（未來方向）

### 場景：處理未知類型的 PDF

第一次遇到新類型文件（如專利、技術手冊）時，不知道它有什麼噪音、該用什麼 profile。

### 工作流

```
未知 PDF
  → doc2md 粗轉（--profile default，不過濾噪音）
  → 產出的 Markdown 加入 qmd 索引
  → qmd 語義搜尋找異常段落（重複短句、URL 密集段、廣告語氣）
  → 人工確認哪些是噪音
  → 產出新 profile（.yaml + 噪音 regex）
  → 用新 profile 重跑轉換
```

### 定位

- qmd **不取代** regex——regex 處理已知噪音，快速且確定
- qmd **輔助發現**未知噪音——語義搜尋找出「看起來不像正文」的段落
- 產出的結果最終仍寫成 profile 中的 regex 規則，不在轉換過程中即時呼叫 qmd

### 實作時機

不在 v0.10-v0.11 範圍。待 profile 系統穩定、且有第二種文件類型需求時再考慮。目前 Bruice 教科書的噪音模式已知，不需要此工作流。

---

## 五、引擎可替換架構（Phase 2）

### 問題

doc2md 的 PDF 能力上限受制於引擎（PyMuPDF + pdfplumber）。Profile 系統解決「領域知識」的外部化，但雙欄排版、複雜表格、數學公式等問題的根源在引擎層。2025-2026 年 ML 驅動的 PDF 引擎已成熟，應該站在巨人肩上。

### 新一代 PDF 引擎調查

| 工具 | ★ 數 | 技術 | 雙欄 | 表格 | 公式 | License |
|------|------|------|------|------|------|---------|
| Docling（IBM） | 37k | DocLayNet + TableFormer | ✅ | ✅ 最強 | ✅ | **MIT** ✅ |
| Marker | 33k | Surya OCR + 版面模型 | ✅ | ✅ | ✅ | GPL-3.0 ⚠️ |
| MinerU | 26k | PaddleOCR + 自訓模型 | ✅ | ✅ | ✅ | AGPL-3.0 ⚠️ |
| Surya | 13k | 從頭訓練版面模型 | ✅ | ✅ | — | GPL-3.0 ⚠️ |
| DECIMER | — | 深度學習 image→SMILES | — | — | — | **MIT** ✅ |

化學結構式辨識：四大引擎均不支援，需搭配 DECIMER 獨立處理。

### License 風險分析

| License | 可否 import 整合 | 可否 CLI 呼叫 | doc2md 影響 |
|---------|-----------------|--------------|------------|
| MIT | ✅ | ✅ | 無限制 |
| GPL-3.0 | ⚠️ 整合後 doc2md 必須 GPL | ✅ subprocess 呼叫不傳染 | 只能外部呼叫 |
| AGPL-3.0 | ❌ 作為服務也要開源 | ✅ subprocess | 只能外部呼叫 |

**結論：只有 Docling（MIT）和 DECIMER（MIT）可以安全整合進 doc2md。** GPL 工具可作為外部 CLI 呼叫，但不能 import 模組。學習它們的設計思路、自己寫實作則完全沒有問題——GPL 保護原始碼，不保護演算法概念。

### 目標架構

```
doc2md（編排層）
  ├── engines/              ← Phase 2 新增
  │   ├── pymupdf.py        # 現有引擎（最快，簡單文件）
  │   ├── docling.py         # MIT，可直接 import（雙欄、高精度表格）
  │   └── marker_cli.py      # GPL，只能 subprocess 呼叫
  ├── profiles/             ← Phase 1
  ├── prompts/              ← Phase 1
  └── converters/           ← 現有（重構為接收引擎輸出）
```

```bash
# 使用 Docling 引擎（雙欄教科書）
python3 doc2md.py ch5.pdf -o out/ --engine docling --profile textbook

# 使用現有引擎（快速，簡單文件）
python3 doc2md.py paper.pdf -o out/ --engine pymupdf --profile journal

# 未指定 → pymupdf（向後相容）
python3 doc2md.py file.pdf -o out/
```

---

## 六、自研引擎模組（Phase 3，遠期）

### 為什麼最終要自研

- 外部引擎的能力上限不由我們控制
- 化學文件有特殊需求（結構式、反應式），通用引擎不會優先支援
- 自研可以針對化學文件微調 ML 模型——這是差異化優勢

### 可行路徑

| 方向 | 做法 | 來源 |
|------|------|------|
| 版面分析 | 學習 DocLayNet 架構，用化學文件資料集微調 | MIT，可學習 |
| 表格辨識 | 學習 TableFormer 設計思路，自己實作 | MIT，可學習 |
| 化學結構辨識 | 整合 DECIMER（MIT）或自訓模型 | MIT，可直接整合 |
| 雙欄重組 | 參考 Marker/MinerU 的閱讀順序演算法，自己寫 | 學概念不侵權 |

### 實作時機

Phase 2 引擎可替換架構穩定後，根據實際使用中的痛點決定優先順序。不預排版本號。

---

## 七、三階段路線圖

```
Phase 1（現在）           Phase 2                  Phase 3（遠期）
Profile 系統 + R5     →  引擎可替換架構        →  自研引擎模組
v0.10.0                  v0.11.0                  v1.0.0+
教科書能跑就好            Docling(MIT) 接入         學習 ML 版面分析
                         pymupdf 保持為預設        化學文件微調模型
                         R4 共用渲染               DECIMER 整合
```

### 各階段依賴

```
Phase 1: Profile 系統 ──→ VLM 比較測試 ──→ 教科書批量轉換
Phase 2: 引擎可替換 ──→ Docling 接入 ──→ R4 + R6
Phase 3: 待 Phase 2 穩定 + 有化學特化需求
qmd 輔助工作流：待 Profile 系統穩定後，獨立於 Phase 2/3
```

---

## 八、不在範圍內

- 不改動現有 config.json 結構（profile 系統獨立於 config.json）
- 不處理非 PDF 格式的升級（本文件聚焦 PDF 引擎）
- 不在轉換過程中即時呼叫 qmd（qmd 定位為離線輔助工具）
- 不整合 GPL/AGPL 工具的 Python 模組（只允許 subprocess 呼叫或學習概念自研）

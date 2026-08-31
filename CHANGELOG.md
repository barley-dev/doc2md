# doc2md Changelog

## v0.10.3 (2026-04-12)

### 改善
- 更新預設 VLM 模型：`gemini-2.5-flash` → `gemini-3-flash-preview`
- 驗證依據：CG 渲染 + 三模型比較（Chapter 5 前 5 頁）
  - 3.0 Flash Preview 是唯一能明確辨識 wedge/dash bond 及對應碳位置的模型
  - 幻覺程度最低，描述詳細度高且各頁一致
  - 2.5 Flash 立體資訊幾乎缺失；3.1 Lite 不均且有誤判（β-phellandrene 共軛誤稱）

### 修改檔案
- `vlm_describer.py` L27：`DEFAULT_VLM_MODEL = "gemini-3-flash-preview"`

---

## v0.10.2 (2026-04-12)

### 改善
- PDF 頁面渲染改用 macOS CoreGraphics（解決 Pearson CID 字型亂碼）
- 新增 `renderers/` 模組：CoreGraphics 優先，非 macOS 自動 fallback PyMuPDF
- VLM 輸入圖片同步受益（CG 渲染 → Gemini 辨識品質提升）
- `pdf2png` CLI 新增 page range 參數（只渲染指定頁面，效能優化）

## v0.10.1 — VLM Inline + 頁面截圖嵌入 (2026-04-12)

### VLM Inline 化
- **VLM 結果 inline**：每頁的 VLM 描述直接插在該頁文字之後，不再集中在文末 `## VLM Image Descriptions` 區塊
- **頁面截圖自動嵌入**：`--vlm` 自動啟用頁面渲染，每頁文字後插入 `![Page N](images/pages/page_NNN.png)`
- **設計意圖**：Obsidian 使用者看到圖文並排可對照 VLM 辨識結果；模型讀檔時只看到 VLM 文字描述（低 token 成本），圖片路徑僅為字串

### Textbook VLM Prompt 增強
- 增加 per-figure/per-problem 粒度要求：每個 Problem 的子題（a, b, c...）要分別描述
- 化學結構要求更詳細：IUPAC 名、環型、取代基、立體化學
- 表格要求盡量以 Markdown table 格式重現
- 優先準確度，不縮減描述長度

### 修改檔案
- `converters/pdf.py`：per-page 迴圈中 inline 插入 VLM 描述和頁面截圖，移除文末 VLM/Renders 集中區塊
- `prompts/textbook.txt`：增強 prompt 結構化與詳細度
- `utils/__init__.py`：VERSION → 0.10.1

### 行為變化
- `--vlm` 會自動渲染所有頁面（等同隱式 `--render-pages`），無需額外指定
- `--render-pages` 不加 `--vlm` 時仍正常運作（只渲染不呼叫 VLM）
- 向後相容：不使用 `--vlm` 的轉換行為完全不變

---

## v0.10.0 — Profile 系統 + Gemini VLM (2026-04-12)

### 架構升級
- **Profile 系統**：領域知識（VLM prompt、噪音 regex、標題模式）從程式碼分離至 YAML 設定檔，新增文件類型只需加 .yaml + .txt
- **`--profile` 參數**：切換轉檔 profile（預設 `journal`，向後相容 v0.9.0 行為）
- 三個內建 profile：`default`（無噪音過濾）、`journal`（學術期刊）、`textbook`（教科書，max_tokens=4096）

### Gemini VLM 後端
- **VLM 後端切換**：預設從 Claude Haiku 改為 Gemini 2.5 Flash（成本降 ~20 倍）
- **`DEFAULT_VLM_MODEL` 集中管理**：唯一定義在 `vlm_describer.py`，CLI/profile/converter 皆引用，換模型只改一處
- **雙後端支援**：`gemini-*` 開頭走 Google GenAI SDK，其他走 Anthropic SDK
- **`.env` API key 載入**：共用 `~/資料/.env`，透過 python-dotenv 自動載入
- **四模型比較定案**：2.0-flash / 2.5-flash-lite / 2.5-flash / 3.1-flash-lite，2.5-flash 在化學結構辨識品質最佳

### Textbook profile 實測修正
- **Pearson 頁眉 regex**：新增 `^\s*\d+\s+C\s*h\s*a\s*p\s*t\s*e\s*r` 匹配字母間有空格的 Chapter（偶數頁頁眉），成功過濾 23 行
- 教科書章末習題（Problem 32-46）VLM 辨識品質確認：化學結構、反應式、多部分題目均正確

### 新增檔案
- `profiles.py`：Profile 載入模組（YAML 解析、regex 編譯、prompt 載入）
- `profiles/default.yaml`、`profiles/journal.yaml`、`profiles/textbook.yaml`
- `prompts/default.txt`、`prompts/journal.txt`、`prompts/textbook.txt`

### 修改檔案
- `doc2md.py`：新增 `--profile`，`--vlm-model` default 引用 `DEFAULT_VLM_MODEL`
- `vlm_describer.py`：新增 `DEFAULT_VLM_MODEL` 常數、Gemini 後端（`_describe_page_gemini`）、`.env` 載入
- `utils/text.py`：新增通用 `filter_noise(text, compiled_patterns, safety_threshold)`，`filter_journal_noise` 改為 wrapper
- `converters/pdf.py`：noise filter 和 VLM 呼叫改為 profile-aware，VLM default 引用集中常數
- `profiles.py`：profile 無 model 欄位時不注入 hardcoded default，交由下游用 `DEFAULT_VLM_MODEL`
- `utils/__init__.py`：VERSION → 0.10.0
- `requirements.txt`：新增 PyYAML>=6.0、google-genai、python-dotenv

### 對應需求
- R1（VLM prompt 可自訂）→ profile + prompts/ 解決
- R2（VLM max_tokens 可調）→ profile vlm.max_tokens 解決
- R3（教科書噪音規則）→ textbook.yaml noise rules 解決
- R5（VLM 頁面範圍選擇）→ `--vlm-pages` 解決
- R4（VLM 後端可替換）→ 部分解決：Gemini/Claude 雙後端，`--vlm-model` 切換

### 架構修正（計畫審查後）
- **YAML canonical source**：移除 utils/text.py 的硬編碼 noise regex，profiles/journal.yaml 為唯一來源
- **noise filter 簡化**：消除死碼分支，邏輯改為有 patterns → 過濾，沒有 → 跳過
- **VLM 參數優先順序**：CLI `--vlm-model` 優先於 profile 設定（抽出 `resolve_vlm_params`）
- **移除 headings 死程式碼**：profile 不再包含未實作的 headings 欄位
- **fallback 統一**：未指定 profile 時 fallback 為 journal（等同 v0.9.0）
- **R5 `--vlm-pages`**：支援指定 VLM 描述的頁面範圍（如 `1-5,10,15-20`）

---

## v0.9.0 — 學術論文品質改良 (2026-03-30)

### 品質提升
- **雜訊過濾強化**：新增 14 條 regex 覆蓋 Wiley/ACS/RSC 期刊的頁首頁尾、引用行、ACCESS 標記等；MAX_NOISE_LINE_LENGTH 提升至 150
- **表格結構重建**：三策略架構（預設 → Rect-guided → Entry-anchored），修復期刊表格被攤平為純文字的問題
- **H1 標題合併**：連續 H1 合併為單一標題，作者行自動降級為純文字
- **合字正規化**：自動替換 ﬁ/ﬂ/ﬀ/ﬃ/ﬄ 為 ASCII（fi/fl/ff/ffi/ffl）
- **°C 編碼修復**：修復 RSC 論文中 °C 被轉為 1C 的字型映射問題
- **Drop-cap 修復**：修復 ACS 論文首字母放大拆開問題（P + hosphine → Phosphine）
- **空表格殘影移除**：過濾圖片佔位框產生的空 Markdown 表格

### 新增功能
- **`--vlm` VLM 圖片描述**：使用 Claude Vision API 自動描述論文中的 Scheme/Figure/Table，輸出為 HTML 註解
- **`--vlm-model`**：指定 VLM 使用的 Claude 模型（預設 claude-haiku-4-5）
- **`--vlm-dpi`**：VLM 頁面渲染解析度（預設 150）

### 新增檔案
- `vlm_describer.py`：VLM 圖片描述模組
- `tests/test_journal_quality.py`：22 個學術論文品質迴歸測試

### 修改檔案
- `converters/pdf.py`：表格三策略、標題合併、合字正規化、°C 修復、drop-cap 修復、VLM 整合
- `utils/text.py`：14 條新 noise regex、空表格移除邏輯
- `utils/tables.py`：智慧型標題合併、空行過濾
- `utils/__init__.py`：VERSION → 0.9.0
- `doc2md.py`：新增 --vlm/--vlm-model/--vlm-dpi 參數

### 品質測試結果（Pilot 3 篇）
| 出版社 | v0.8.2 | v0.9.0 | 改善項目 |
|--------|--------|--------|---------|
| Wiley ADSC | 3/5 | 4.5/5 | 雜訊清除、表格結構、標題合併、合字 |
| ACS OL | 2.5/5 | 4.5/5 | 雜訊清除、表格結構、drop-cap、空表格 |
| RSC CC | 3/5 | 4.5/5 | 雜訊清除、表格結構、°C 修復 |

---

## v0.8.2 + md_splitter v0.3.0 (2026-03-17)

### 新增功能（md_splitter v0.3.0）
- **`--pattern` 拆分模式**：允許用 regex 指定拆分點，解決 PDF 正文章節標題未被識別為 heading 的問題
- **內建 shortcut**：`chinese`（`^[一二三四五六七八九十百]+、`）、`numbered`（`^\d+\.\s`）、`chapter`（`^Chapter\s+\d+`）
- `--pattern` 與 `--level` 互斥，同時指定時報錯
- `--pattern` 模式下 `--dry-run`、`--toc-only` 同樣有效；`--strict` 在 pattern 模式下無效（無需過濾）
- `split_and_export()` 新增 `pattern` 參數

### 新增功能（doc2md v0.8.2）
- **`--split-pattern`**：轉換後用 regex 或 shortcut 拆分（對應 md_splitter `--pattern`）
- `--split-level` 與 `--split-pattern` 互斥

### 修改檔案
- `~/資料/Tools/md_splitter.py`：v0.2.0 → v0.3.0
- `doc2md.py`：新增 `--split-pattern`，更新 `_run_splitter()`
- `utils/__init__.py`：VERSION 更新為 0.8.2

---

## v0.8.1 + md_splitter v0.2.0 (2026-03-17)

### 新增功能（md_splitter v0.2.0）
- **_TOC.md 產出**：拆分後自動在輸出資料夾產出 `_TOC.md`，含 YAML frontmatter 與 Markdown 表格（序號、相對連結、標題、行數、預估 tokens）
- **智慧標題過濾**：拆分前掃描所有 heading，過濾含 `=`/`±`/`×` 的數值標記（如 `k1=0.0014`、`R=0.9936`），以及純文字 < 5 字元的短標題；白名單（中文章節、編號章節、學術關鍵詞）永遠保留
- **`--strict` 模式**：只保留白名單 heading 作為拆分點，過濾最積極
- **`--toc-only` 模式**：只產出 `_TOC.md`，不寫章節檔案，方便先預覽結構
- **`split_and_export()` 公開 API**：提取核心邏輯為可 import 的函式，供 doc2md 呼叫

### 新增功能（doc2md v0.8.1）
- **`--split` 旗標**：轉換完成後自動呼叫 md_splitter 拆分輸出的 Markdown
- **`--split-level`**：指定拆分的標題層級（1/2/3，預設 1）

### 修改檔案
- `~/資料/Tools/md_splitter.py`：v0.1.0 → v0.2.0
- `doc2md.py`：新增 `--split`/`--split-level` 旗標，新增 `_run_splitter()` helper

---

## v0.8.1 (2026-03-17)

### 新增功能
- **加密 PDF 偵測**：自動偵測 Owner Password 保護的 PDF，空密碼可繞過時繼續處理並在 frontmatter 加入 `encryption: "owner-password (bypassed)"`；Open Password 保護的 PDF 則跳過並輸出錯誤
- **pdfplumber 效能改善**：整份 PDF 只開啟一次 pdfplumber（原本每頁各開一次），177 頁 PDF 約減少 176 次 I/O
- **大型 PDF 進度顯示**：頁數 > 50 時，每處理 10 頁印一次進度到 stderr

### 修改檔案
- `converters/pdf.py`：`extract_tables()` 新增 `plumber_pdf` 參數、`process_page()` 新增 `plumber_pdf` 參數、`generate_frontmatter()` 新增 `encryption` 參數、`convert_pdf_to_md()` 加入加密偵測 + pdfplumber 單次開啟 + 進度顯示
- `utils/__init__.py`：VERSION 更新為 0.8.1

---

## v0.7.0 (2026-03-13)

### 新增功能
- **DOCX 圖片擷取**：自動從 .docx 提取嵌入圖片，存到 images/ 並插入 Markdown 引用
- **PPTX 圖片擷取**：自動從 .pptx 提取圖片 shape，含尺寸過濾
- **DOCX 圖表轉表格**：解析 chart XML，將圖表資料轉為 Markdown 表格
- **PPTX 圖表轉表格**：透過 python-pptx chart API 提取圖表資料
- **Fallback 安全網**：DOCX/PPTX 原生解析結果若內容過少（<100 有效字元），自動回退到 LibreOffice 路徑

### 輔助函式
- `_check_content_sufficient()` — 檢查輸出內容量
- `_extract_docx_images()` — DOCX 圖片提取與 rId 映射
- `_extract_chart_data()` — DOCX chart XML 解析

### 未變動
- PDF 路徑、Excel 路徑、config 結構均維持不變
- 無新增外部依賴

---

## v0.5.0 (2026-02-19)

- 基礎文字/表格/標題擷取
- Journal noise 過濾
- 多語言偵測
- LibreOffice fallback 路徑

# doc2md — 通用文件轉 Markdown 工具

將各種文件格式轉為乾淨的 Markdown，針對化學學術論文和教科書做了特別優化。

```bash
git clone https://github.com/barley-dev/doc2md.git
cd doc2md
pip install -r requirements.txt
python3 doc2md.py your-file.pdf
```

## 功能特色

- **15+ 格式支援**：PDF、Word、ODF、RTF、PowerPoint、Excel、CSV、HTML
- **雙引擎 PDF 解析**：PyMuPDF（文字/圖片） + pdfplumber（表格）
- **Profile 系統**（v0.10.0）：領域知識以 YAML 設定檔管理，切換 profile 即可適應不同文件類型
- **VLM 圖片描述**（v0.9.0+）：Gemini/Claude Vision 自動辨識圖表、結構式、習題
- **VLM Inline 模式**（v0.10.1）：VLM 描述與頁面截圖直接嵌入對應文字旁，方便 Obsidian 圖文對照
- **學術論文優化**：
  - 自動偵測標題層級（基於字型大小分析）
  - 移除期刊頁首/頁尾（Chem. Ber., J. Org. Chem. 等）
  - 移除 OA 浮水印（Wiley、ACS、RSC 下載戳記）
  - 語言偵測（德文/法文/英文），非英文文件加註 AI_TODO 標記
- **圖片擷取**：嵌入圖片 + 整頁渲染（保留化學結構式等向量圖形）
- **YAML frontmatter**：source_file、title、pages、語言標記等

## 內建 Profile

| Profile | 用途 | 噪音規則 | VLM max_tokens |
|---------|------|---------|---------------|
| `journal`（預設） | 學術期刊論文 | 28 條（Wiley/ACS/RSC） | 1024 |
| `textbook` | 大學教科書 | 4 條（Pearson 頁眉等） | 4096 |
| `default` | 通用，無噪音過濾 | 0 | 1024 |

## 支援格式

| 格式 | 副檔名 | 轉換方式 |
|------|--------|---------|
| PDF | `.pdf` | PyMuPDF + pdfplumber（直接解析） |
| Word | `.docx` | python-docx 原生解析（標題、表格、列表） |
| Word (舊版) | `.doc` | LibreOffice → .docx → python-docx 解析 |
| PowerPoint | `.pptx` | python-pptx 原生解析（投影片、表格、備忘稿） |
| PowerPoint (舊版) | `.ppt` | LibreOffice → .pptx → python-pptx 解析 |
| Excel | `.xlsx` | openpyxl 原生解析（多 Sheet、完整表格結構） |
| Excel (舊版) | `.xls` | xlrd 原生解析（多 Sheet、完整表格結構） |
| ODF 文件 | `.odt` | XML 原生解析（標題、表格、列表） |
| ODF 試算表 | `.ods` | XML 原生解析（多 Sheet、完整表格結構） |
| RTF | `.rtf` | LibreOffice → PDF → 解析 |
| HTML | `.html`, `.htm` | markdownify 原生解析（語意結構完整保留） |
| 純文字 | `.txt`, `.csv`, `.tsv` | 直接轉換（CSV/TSV → 表格） |

## 安裝

```bash
pip install -r requirements.txt
```

或直接指定套件：

```bash
pip install pymupdf pdfplumber openpyxl xlrd python-docx python-pptx markdownify PyYAML google-genai python-dotenv --break-system-packages
```

另外需要 [LibreOffice](https://www.libreoffice.org/)（處理非 PDF 格式）。
macOS 預設路徑：`/Applications/LibreOffice.app/Contents/MacOS/soffice`

### API 金鑰（僅 `--vlm` 需要）

不使用 `--vlm` 可完全跳過。設環境變數即可：

```bash
export GOOGLE_API_KEY=...      # Gemini
export ANTHROPIC_API_KEY=...   # Claude
```

也支援 `.env` 檔，依序查找：`$DOC2MD_ENV_FILE` → 當前目錄 `.env` → 專案目錄 `.env` → `~/.doc2md.env`。

### Claude Code Skill（選用）

讓 Claude Code 直接懂得怎麼用這個工具：

```bash
./install-skill.sh
```

之後在對話中說「把這篇 PDF 轉成 Markdown」即可觸發。

### pdf2png（選用，僅 macOS）

`renderers/coregraphics.py` 會用到 CoreGraphics 渲染（對 CID 字型支援較好）。
未編譯時自動退回 PyMuPDF，功能不受影響。要啟用：

```bash
swiftc -O pdf2png.swift -o pdf2png
```

## 使用方式

```bash
# 基本轉換
python3 doc2md.py paper.pdf
python3 doc2md.py report.docx -o ./output/

# 使用 Profile
python3 doc2md.py paper.pdf --profile journal       # 學術期刊（預設）
python3 doc2md.py textbook.pdf --profile textbook    # 教科書

# VLM 圖片描述（inline 模式，v0.10.1）
python3 doc2md.py textbook.pdf --profile textbook --vlm
python3 doc2md.py textbook.pdf --vlm --vlm-pages 1-5,10   # 只描述指定頁面
python3 doc2md.py paper.pdf --vlm --vlm-model gemini-2.5-flash

# 批量轉換
python3 doc2md.py /path/to/folder/
python3 doc2md.py /path/to/folder/ --ext .pdf .docx

# Inbox 工作流
python3 doc2md.py --inbox
python3 doc2md.py --inbox --clean

# 其他選項
python3 doc2md.py paper.pdf --no-images
python3 doc2md.py paper.pdf --no-tables
python3 doc2md.py paper.pdf --render-pages --render-dpi 200
python3 doc2md.py slides.pdf --presentation
python3 doc2md.py --version
```

### VLM 模式說明

`--vlm` 啟用後，每頁輸出結構為：

```
[PyMuPDF 提取的文字]

![Page N](images/pages/page_NNN.png)    ← 頁面截圖

<!-- VLM: [Label] — [Description] -->    ← VLM 辨識結果
```

- **Obsidian 使用者**：看到文字 + 截圖 + VLM 描述，可對照確認辨識正確性
- **模型讀檔時**：只看到文字和 VLM 描述（圖片路徑僅為字串），token 成本低

### Inbox 工作流

1. 將檔案丟進 `doc2md/Inbox/` 資料夾
2. 執行 `python3 doc2md.py --inbox`
3. 轉換結果在 `doc2md/Output/<檔名>/` 下

## 輸出結構

```
output/
├── Chapter_5/
│   ├── Chapter_5.md              ← 主文件（含 inline VLM 描述）
│   └── images/
│       ├── p3_img1.png           ← 嵌入圖片
│       ├── p5_img2.png
│       └── pages/                ← 頁面截圖（--vlm 或 --render-pages）
│           ├── page_001.png
│           └── ...
```

## 設定檔 (config.json)

放在 `doc2md.py` 同目錄下會自動載入，或用 `--config` 指定。

主要設定項：
- **images.extract**: 是否擷取嵌入圖片 (true/false)
- **images.min_width/min_height**: 最小圖片尺寸（過濾 icon 等小圖）
- **tables.extract**: 是否偵測表格
- **text.heading_detection**: 是否自動偵測標題層級
- **text.remove_headers_footers**: 是否移除頁首頁尾
- **libreoffice_path**: LibreOffice 執行檔路徑

## 已知限制

- **掃描式 PDF**：無文字層的 PDF 需先 OCR
- **數學公式**：PDF 中的方程式難以完美轉換
- **化學結構式**：向量圖形無法擷取為獨立圖片 → 使用 `--vlm` 或 `--render-pages` 保留
- **雙欄排版**：大部分可處理，極端案例可能需人工調整

## 資料夾結構

```
doc2md/
├── doc2md.py           ← 主程式入口
├── md_splitter.py      ← 章節拆分（--split 會呼叫）
├── config.json         ← 設定檔
├── profiles.py         ← Profile 載入模組
├── vlm_describer.py    ← VLM 圖片描述模組
├── pdf2png.swift       ← CoreGraphics 渲染器原始碼（選用，需自行編譯）
├── install-skill.sh    ← 安裝 Claude Code skill
├── profiles/           ← 領域知識 YAML（journal / textbook / default）
├── prompts/            ← VLM prompt 模板
├── converters/         ← 各格式轉換器
├── renderers/          ← 頁面渲染（CoreGraphics + PyMuPDF fallback）
├── utils/              ← 共用工具
├── tests/              ← 回歸測試（pytest）
├── skills/doc2md/      ← Claude Code skill
├── figure-extract/     ← 圖表重切工具鏈（圖片大量流失時的補救）
└── docs/               ← 補充文件
```

## 配套工具

| 工具 | 用途 |
|---|---|
| `md_splitter.py` | 長 Markdown 按標題層級或 regex 拆章，產出 `_TOC.md`。`doc2md.py --split` 會自動呼叫，也可獨立使用 |
| `figure-extract/` | doc2md 圖片擷取大規模失敗時的補救鏈（偵測壞圖 → 標座標 → 裁切 → 插回）。純程式無 LLM，可重跑可 diff。詳見 [`figure-extract/README.md`](figure-extract/README.md) |

## 測試

```bash
python3 -m pytest tests/ -q
```

## 授權

MIT — 見 [LICENSE](LICENSE)。

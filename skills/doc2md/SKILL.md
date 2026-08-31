---
name: doc2md
description: Convert documents (PDF, Word, PowerPoint, Excel, ODF, RTF, HTML) to clean Markdown using the doc2md tool. Use when the user wants to convert, extract, or turn a document into Markdown — including academic papers and textbooks — or asks to batch-convert a folder of documents. Triggers include "convert to markdown", "轉成 markdown", "轉檔", "把這篇 PDF 轉成", "batch convert", "doc2md".
---

# doc2md — Document to Markdown

Convert documents to clean Markdown. Optimised for academic papers and textbooks.

## Before running

Locate the tool. It lives wherever the user cloned this repository:

```bash
ls ~/tools/doc2md/doc2md.py 2>/dev/null || find ~ -name "doc2md.py" -maxdepth 4 2>/dev/null | head -3
```

Set `DOC2MD` to that path and use it throughout.

## Choosing a profile

Pick the profile from the document type. This matters more than any other flag — the wrong profile leaves journal headers and watermarks in the output.

| Document | Profile | Why |
|---|---|---|
| Journal article (Wiley / ACS / RSC …) | `journal` (default) | 28 noise rules strip running heads, OA download stamps |
| Textbook, lecture notes | `textbook` | Different heading structure, larger VLM budget |
| Anything else | `default` | No noise filtering — safest for unknown layouts |

```bash
python3 "$DOC2MD" paper.pdf                      # journal (default)
python3 "$DOC2MD" chapter.pdf --profile textbook
python3 "$DOC2MD" memo.docx --profile default
```

## Common tasks

**Single file**
```bash
python3 "$DOC2MD" input.pdf -o ./output/
```

**Batch a folder**
```bash
python3 "$DOC2MD" /path/to/folder/ --ext .pdf -o ./output/
```

**Large document — split into chapters**
```bash
python3 "$DOC2MD" book.pdf --profile textbook --split --split-level 2
```
Produces one file per chapter plus a `_TOC.md` index.

**Skip images** (much faster; use when only the text matters)
```bash
python3 "$DOC2MD" paper.pdf --no-images
```

**Describe figures with a vision model** (needs `GOOGLE_API_KEY` or `ANTHROPIC_API_KEY`)
```bash
python3 "$DOC2MD" paper.pdf --vlm
python3 "$DOC2MD" paper.pdf --vlm --vlm-pages 3-8   # limit cost to the pages that matter
```

## After converting — always check

Do not report success on the exit code alone. Open the output and verify:

1. **Headings** — are they real headings, or did body text get promoted?
2. **Tables** — did multi-column tables survive, or collapse into a single column?
3. **Figures** — count `![` references against what the PDF actually contains.

Figure loss is the most common failure and it is silent. On scanned or Word-exported PDFs, doc2md can miss the majority of figures while still exiting 0.

```bash
grep -c '!\[' output.md   # images actually embedded
```

If figures are largely missing, use the `figure-extract/` tool chain in the repository root — it re-cuts figures from the source PDF by coordinates and inserts them back. See `figure-extract/README.md`.

## Reporting back

State what was converted, where the output went, and what you verified — including anything that looked wrong. If figures were lost or tables collapsed, say so rather than presenting the conversion as clean.

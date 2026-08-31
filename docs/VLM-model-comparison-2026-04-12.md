# VLM 模型比較報告 — 2026-04-12

測試條件：CG 渲染（v0.10.2）+ Chapter 5 前 5 頁 + textbook profile + DPI 150

## 模型可用性

| 模型 | 狀態 |
|------|------|
| gemini-2.5-flash | 成功 |
| gemini-3-flash-preview | 成功 |
| gemini-3.1-flash-lite-preview | 成功 |

## 化學結構描述摘錄

### Page 2 — 萜類化合物（citronellol、limonene、β-phellandrene）

| 結構 | 2.5 Flash | 3.0 Flash Preview | 3.1 Lite Preview |
|------|-----------|-------------------|-----------------|
| citronellol | 八碳主鏈，無立體細節 | eight-carbon main chain, **wedge stereochemistry at C3**, trisubstituted double bond C6-C7 | "acyclic terpene alcohol with an alkene"（單行，無細節） |
| limonene | 六員環、C1 甲基、描述截斷 | **isopropenyl group at C4 with wedge stereochemistry** | "cyclic terpene with two alkenes"（未辨識立體） |
| β-phellandrene | 未單獨列出 | **exocyclic methylene, isopropyl at C4 with dash stereochemistry** | "cyclic terpene with two conjugated alkenes"（**誤**：非共軛） |
| bombykol | 基本正確，缺完整名 | (10E,12Z)-hexadeca-10,12-dien-1-ol，完整系統名 | (10E,12Z)-hexadeca-10,12-dien-1-ol（正確） |

### Page 3 — cis/trans-2-pentene

| | 2.5 Flash | 3.0 Flash Preview | 3.1 Lite Preview |
|---|---|---|---|
| 幾何異構描述 | E/Z 說明但無視覺細節 | 明確指出氫原子以**黃色高亮**標示，說明取代基相對位置 | 僅說 "same side / opposite sides"，無視覺細節 |
| 例題結構數量 | 3 個 | 5 組（更完整） | 14 個（最多，但每條簡短） |

### Page 5 — vinyl/allyl group

| | 2.5 Flash | 3.0 Flash Preview | 3.1 Lite Preview |
|---|---|---|---|
| 結構列出 | 4 個，格式正確 | LaTeX 格式，清晰完整 | 正確，**額外回答 Problem 2、3 答案及反應式**（超出描述範疇，準確度待驗證） |

## 綜合比較

| 評估面向 | 2.5 Flash | 3.0 Flash Preview | 3.1 Lite Preview |
|---------|-----------|-------------------|-----------------|
| wedge/dash bond 辨識 | 弱（幾乎不提） | **強**（明確標出 wedge/dash，指出哪個碳） | 弱（多數跳過立體描述） |
| 環狀結構辨識 | 普通（列出環但無立體） | **良**（exocyclic methylene、ring position） | 差（β-phellandrene 誤稱共軛） |
| IUPAC 命名正確性 | 普通（基本正確，缺完整名） | **良**（bombykol 完整系統名） | 良（bombykol 正確，習題答案基本正確） |
| 幻覺程度 | 低（描述保守） | **最低** | 中（β-phellandrene 誤判，習題答案需驗證） |
| 描述詳細度 | 中（常截斷） | **高且均勻** | 高但不均（page 5 超詳，page 2 最簡略） |
| 各頁一致性 | 中 | **高** | 低 |

## 結論

**最佳模型：gemini-3-flash-preview**

gemini-3-flash-preview 是唯一能明確辨識 wedge/dash bond 並指出對應碳位置的模型，這對有機化學立體化學內容最關鍵。幻覺程度最低，描述詳細且一致。

**決定：** `DEFAULT_VLM_MODEL` 已更新為 `gemini-3-flash-preview`（vlm_describer.py L27，v0.10.3）

## 原始輸出路徑（/tmp，非永久）

- `/tmp/vlm_compare_25flash/Chapter 5/Chapter 5.md`
- `/tmp/vlm_compare_30flash/Chapter 5/Chapter 5.md`
- `/tmp/vlm_compare_31lite/Chapter 5/Chapter 5.md`

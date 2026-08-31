#!/usr/bin/env python3
"""
最後確認 gate — 目視清單變成可勾選帳本，全部確認過才放行插入。

【為何需要】稽核抓得出「可疑」，抓不出「張冠李戴」（實測方世文 Figure 2 標題配到 EPR 圖，
稽核只報輕微「範圍重疊」，是目視才發現）。故插入前必須有一道人（或 VLM）確認的閘門，
且確認結果要落成檔案、可追溯——不能只存在某次對話的記憶裡。

流程：
  1. init  — 依 crop 結果產出確認清單 _confirm.json（每張 status=pending）
  2. 人或 VLM 逐張 Read PNG，用 mark 標 ok / bad / fixed
  3. gate  — 檢查是否全部非 pending 且無 bad；通過才允許插入

用法：
    python3 confirm_figures.py init  <crop_result.json>            # 建清單
    python3 confirm_figures.py mark  <_confirm.json> --id X --ok    # 標一張 OK
    python3 confirm_figures.py mark  <_confirm.json> --id X --bad "標題配錯圖"
    python3 confirm_figures.py gate  <_confirm.json>               # 放行檢查（exit 0/1）
    python3 confirm_figures.py show  <_confirm.json>               # 看目前狀態

gate 通過（exit 0）才跑 insert_figures.py。
"""

import argparse
import json
import sys
from pathlib import Path


def load(p):
    return json.loads(Path(p).expanduser().read_text(encoding="utf-8"))


def save(p, d):
    Path(p).expanduser().write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_init(args):
    crop = load(args.crop_result)
    items = []
    for c in crop.get("cropped", []):
        items.append({
            "id": c["id"],
            "file": c["file"],
            "page": c.get("page"),
            "caption": c.get("caption", ""),
            "status": "pending",     # pending | ok | bad | fixed
            "note": "",
        })
    out = {
        "source_pdf": crop.get("source_pdf", ""),
        "out_dir": crop.get("out_dir", ""),
        "crop_result": str(Path(args.crop_result).expanduser()),
        "items": items,
    }
    dest = Path(crop.get("out_dir", ".")) / "_confirm.json"
    save(dest, out)
    print(f"✅ 確認清單已建：{dest}")
    print(f"   共 {len(items)} 張待確認。逐張 Read PNG 後用 mark 標記。")
    print(f"\n   檢查重點：標題在不在？資料列全不全？最後一列有沒有被切？")
    print(f"   ★ 這張圖是不是它標題講的那張圖？（張冠李戴是稽核抓不到的）")


def cmd_mark(args):
    d = load(args.confirm)
    hit = None
    for it in d["items"]:
        if it["id"] == args.id:
            hit = it
            break
    if not hit:
        sys.exit(f"找不到 id={args.id}")
    if args.ok:
        hit["status"] = "ok"
        hit["note"] = args.note or ""
    elif args.bad is not None:
        hit["status"] = "bad"
        hit["note"] = args.bad
    elif args.fixed:
        hit["status"] = "fixed"
        hit["note"] = args.note or "已 fix_figures 修正並重新確認"
    save(args.confirm, d)
    print(f"✅ {args.id} → {hit['status']}" + (f"（{hit['note']}）" if hit['note'] else ""))


def cmd_show(args):
    d = load(args.confirm)
    order = {"bad": 0, "pending": 1, "fixed": 2, "ok": 3}
    icon = {"ok": "✅", "bad": "❌", "fixed": "🔧", "pending": "⬜"}
    print(f"\n確認清單：{d.get('out_dir','')}")
    for it in sorted(d["items"], key=lambda x: order.get(x["status"], 9)):
        note = f"  — {it['note']}" if it["note"] else ""
        print(f"  {icon.get(it['status'],'?')} {it['id']:<22} {it['caption'][:36]}{note}")
    counts = {}
    for it in d["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    print("\n  " + " | ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_gate(args):
    d = load(args.confirm)
    pending = [it for it in d["items"] if it["status"] == "pending"]
    bad = [it for it in d["items"] if it["status"] == "bad"]

    if bad:
        print(f"❌ 閘門未通過：{len(bad)} 張標為 bad，須先 fix_figures 修正並重新確認：")
        for it in bad:
            print(f"   {it['id']}  — {it['note']}")
        sys.exit(1)
    if pending:
        print(f"❌ 閘門未通過：{len(pending)} 張尚未確認：")
        for it in pending[:20]:
            print(f"   {it['id']}  {it['caption'][:40]}")
        sys.exit(1)

    ok = sum(1 for it in d["items"] if it["status"] == "ok")
    fixed = sum(1 for it in d["items"] if it["status"] == "fixed")
    print(f"✅ 閘門通過：{ok} ok + {fixed} fixed，全數確認，可插入。")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description="圖表插入前的確認 gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("crop_result"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("mark"); p.add_argument("confirm"); p.add_argument("--id", required=True)
    p.add_argument("--ok", action="store_true"); p.add_argument("--bad")
    p.add_argument("--fixed", action="store_true"); p.add_argument("--note")
    p.set_defaults(fn=cmd_mark)
    p = sub.add_parser("show"); p.add_argument("confirm"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("gate"); p.add_argument("confirm"); p.set_defaults(fn=cmd_gate)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

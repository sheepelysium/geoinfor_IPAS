"""題庫污染稽查: 找出疑似跨題黏連的文字與圖文錯位。"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MARK = re.compile(r"回答第?\s*\d+\s*[~～至\-–]\s*\d+\s*題")

for lvl in ["junior", "middle"]:
    qs = json.loads((ROOT / "data" / f"questions-{lvl}.json").read_text(encoding="utf-8"))
    for q in qs:
        probs = []
        for k, v in q["options"].items():
            if MARK.search(v):
                probs.append(f"選項{k}含題組標記")
            elif len(v) > 130 and re.search(r"資料集|請根據|情境|如下圖|欄位包含", v):
                probs.append(f"選項{k}疑似黏到情境段(len={len(v)})")
        if MARK.search(q["stem"]) and not q["context"]:
            probs.append("題幹含題組標記但無 context")
        if q["context"] and MARK.search(q["stem"]):
            probs.append("題幹含題組標記(context 已存在, 檢查重複)")
        if probs:
            print(q["id"], "|", "; ".join(probs))
            for k, v in q["options"].items():
                if any(k in p for p in probs):
                    print(f"   ({k}) ...{v[-120:]}")

if len(sys.argv) > 1:
    ids = sys.argv[1].split(",")
    allq = []
    for lvl in ["junior", "middle"]:
        allq += json.loads((ROOT / "data" / f"questions-{lvl}.json").read_text(encoding="utf-8"))
    for qid in ids:
        q = [x for x in allq if x["id"] == qid][0]
        print("=" * 12, qid, "ans=", q["answer"])
        if q["context"]:
            print(" CTX:", q["context"]["text"][:90].replace("\n", " / "), "figs:", q["context"]["figures"])
        print(" STEM:", q["stem"][:120])
        for k, v in q["options"].items():
            print(f"  ({k})", v[:80])
        print(" FIGS:", [(f["src"].split("/")[-1], f["position"]) for f in q["figures"]])

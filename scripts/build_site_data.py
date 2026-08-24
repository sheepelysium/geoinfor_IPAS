"""合併註解到題庫, 並輸出 site/data/*.js 供前端以 <script> 載入(避開 file:// CORS)。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANN_DIR = ROOT / "data" / "annotate" / "out"
SITE_DATA = ROOT / "site" / "data"
SITE_DATA.mkdir(parents=True, exist_ok=True)

annotations: dict[str, dict] = {}
for f in sorted(ANN_DIR.glob("*.json")):
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"WARN {f.name}: JSON 解析失敗 ({e}), 跳過")
        continue
    annotations.update(data)
    print(f"讀入 {f.name}: {len(data)} 題註解")

for lvl in ["junior", "middle"]:
    qs = json.loads((ROOT / "data" / f"questions-{lvl}.json").read_text(encoding="utf-8"))
    missing = []
    bad = []
    for q in qs:
        ann = annotations.get(q["id"])
        if ann is None:
            missing.append(q["id"])
            q["explanation"] = None
            continue
        opts = ann.get("options", {})
        if set(opts.keys()) < {"A", "B", "C", "D"} or not ann.get("approach"):
            bad.append(q["id"])
        q["explanation"] = {
            "approach": ann.get("approach", ""),
            "options": opts,
            **({"note": ann["note"]} if ann.get("note") else {}),
        }
    out = SITE_DATA / f"questions-{lvl}.js"
    payload = json.dumps(qs, ensure_ascii=False, separators=(",", ":"))
    out.write_text(
        f'window.QUESTION_BANK = window.QUESTION_BANK || {{}};\nwindow.QUESTION_BANK["{lvl}"] = {payload};\n',
        encoding="utf-8",
    )
    done = len(qs) - len(missing)
    print(f"{lvl}: {len(qs)} 題, 已附註解 {done}, 缺 {len(missing)}, 格式不完整 {len(bad)}")
    if bad:
        print("  格式不完整:", ", ".join(bad[:10]))

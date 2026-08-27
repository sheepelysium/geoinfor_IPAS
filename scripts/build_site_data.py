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

# 人工修正詳解(重跑註解 agent 也不會被蓋掉)
fix_file = ROOT / "data" / "explanation-fixes.json"
if fix_file.exists():
    for fix in json.loads(fix_file.read_text(encoding="utf-8")):
        ann = annotations.get(fix["id"])
        if ann is None:
            print(f"WARN 修正找不到題目 {fix['id']}")
            continue
        for key in fix.get("unset", []):
            ann.pop(key, None)
        for path, value in fix.get("set", {}).items():
            if path.startswith("options."):
                ann["options"][path.split(".", 1)[1]] = value
            else:
                ann[path] = value
        changed = fix.get("unset", []) + list(fix.get("set", {}))
        print(f"修正詳解 {fix['id']}: {changed}")

for lvl in ["junior", "middle"]:
    qs = json.loads((ROOT / "data" / f"questions-{lvl}.json").read_text(encoding="utf-8"))
    for q in qs:
        q["origin"] = "past"          # 歷屆公告試題

    # 併入學習指引範例題(官方解析 + AI 逐選項說明)
    guide_file = ROOT / "data" / f"guide-{lvl}.json"
    if guide_file.exists():
        guides = json.loads(guide_file.read_text(encoding="utf-8"))
        for g in guides:
            g["origin"] = "guide"     # 學習指引範例題
            official = g["explanation"]["approach"]
            errata = g["explanation"].get("errata")
            ann = annotations.get(g["id"]) or {}
            g["explanation"] = {
                "approach": official,
                "options": ann.get("options", {}),
                "source": "official",
                **({"note": ann["note"]} if ann.get("note") else {}),
                **({"errata": errata} if errata else {}),
            }
        qs += guides
        print(f"{lvl}: 併入學習指引題 {len(guides)} 題")

    missing = []
    bad = []
    for q in qs:
        if q.get("origin") == "guide":
            continue                  # 學習指引題的詳解已在上面組好
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
            **({"timeliness": ann["timeliness"]} if ann.get("timeliness") else {}),
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

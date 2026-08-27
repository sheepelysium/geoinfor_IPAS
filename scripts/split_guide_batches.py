"""把學習指引題切成註解批次檔(每份指引一批), 給註解 agent 補逐選項說明。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "annotate"
(OUT / "out").mkdir(parents=True, exist_ok=True)

for lvl in ["junior", "middle"]:
    qs = json.loads((DATA / f"guide-{lvl}.json").read_text(encoding="utf-8"))
    groups: dict[str, list] = {}
    for q in qs:
        groups.setdefault(f"guide_{lvl}_s{q['subject']}", []).append(q)
    for key, g in groups.items():
        slim = [
            {
                "id": q["id"],
                "subject_name": q["subject_name"],
                "stem": q["stem"],
                "options": q["options"],
                "answer": q["answer"],
                "official_explanation": q["explanation"]["approach"],
            }
            for q in g
        ]
        (OUT / f"{key}.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{key}: {len(g)} 題")

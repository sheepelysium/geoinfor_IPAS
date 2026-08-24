"""把題庫切成 12 個註解批次檔(每份考卷一批), 給註解 agent 使用。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "data" / "annotate"
out.mkdir(exist_ok=True)
(out / "out").mkdir(exist_ok=True)

for lvl in ["junior", "middle"]:
    qs = json.loads((ROOT / "data" / f"questions-{lvl}.json").read_text(encoding="utf-8"))
    groups: dict[str, list] = {}
    for q in qs:
        key = f"{lvl}_{q['session']}_s{q['subject']}"
        groups.setdefault(key, []).append(q)
    for key, g in groups.items():
        slim = [
            {k: q[k] for k in ("id", "subject_name", "context", "stem", "options", "answer", "figures")}
            for q in g
        ]
        (out / f"{key}.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
        print(key, len(g))

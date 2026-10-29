# /// script
# dependencies = ["pdfplumber"]
# ///
"""解析 iPAS 歷屆考題 PDF 成結構化 JSON 題庫。

版面結構(所有檔案一致):
- 答案欄: 單一字母 A-D(含全形), x0 < 100
- 題號欄: "N.", x0 100~117(題號必須連續遞增, 否則視為題幹內的編號清單)
- 題目內文: x0 >= 118, 題幹首行的 top 比題號 top 高約 5~6px
- 情境題: 「請依照以下情境回答第45~47題」之類的共用段落, 附掛到該範圍每題
- 圖表題: 行距出現大空隙且該區域有物件(圖/線條) → 裁切存 PNG, 並判斷位置
  (題幹後 / 某選項內 / 題末)
"""

import json
import re
import unicodedata
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
IMG_DIR = ROOT / "site" / "images"
OUT_DIR = ROOT / "data"

SUBJECT_NAMES = {
    ("junior", 1): "人工智慧基礎概論",
    ("junior", 2): "生成式AI應用與規劃",
    ("middle", 1): "人工智慧技術應用與規劃",
    ("middle", 2): "大數據處理分析與應用",
    ("middle", 3): "機器學習技術與應用",
}

ANS_X_MAX = 100
QNUM_X_MAX = 118
LINE_TOL = 4
GAP_THRESHOLD = 45
FW_MAP = str.maketrans("ＡＢＣＤ", "ABCD")

CONTEXT_RE = re.compile(r"回答(?:第|以|後續)?\s*(\d+)\s*[~～至\-–]\s*(\d+)\s*題")

HEADER_PATTERNS = [
    re.compile(r"能力鑑定【公告試題】"),
    re.compile(r"^第[一二三]科："),
    re.compile(r"^考試日期"),
    re.compile(r"^試題公告日期"),
    re.compile(r"^答\s*案?$"),
    re.compile(r"^案$"),
    re.compile(r"^題\s*目$"),
    re.compile(r"^題\s*目\s*答\s*案$"),
    re.compile(r"^答\s*案\s*題\s*目$"),
    re.compile(r"^第\s*\d+\s*頁"),
    re.compile(r"^《以下空白》$"),
    re.compile(r"^[一二三四五]、"),  # 節標題, 如「二、程式題」
]


def split_options(lines: list[str]) -> tuple[str, dict, dict]:
    """逐行切分題幹與選項。

    選項標記依 A→B→C→D 順序比對:
    - (A) 只在行首、或緊接句尾標點(？?。；;)後才算選項起點,
      避免題幹內的 (A) 引用(如「程式碼中(A)與(B)」)誤切
    - (B)(C)(D) 在進入選項區後可出現在行中(處理四選項擠一行的版面),
      但選項內文的 np.linalg.inv(A) 等舊字母不會誤觸(只找下一個預期字母)
    回傳 (stem, options, opt_start_line)。
    """
    stem_parts: list[str] = []
    opts: dict[str, list[str]] = {}
    opt_start_line: dict[str, int] = {}
    cur: str | None = None
    expected = 0

    def emit(text: str) -> None:
        if not text:
            return
        if cur is None:
            stem_parts.append(text)
        else:
            opts[cur].append(text)

    for li, raw in enumerate(lines):
        # 修正 PDF 抽取順序錯亂, 如 "(A「)月收入」" → "(A)「月收入」"
        line = re.sub(
            r"\(([A-DＡ-Ｄ])([^\w)])\)",
            lambda m: f"({m.group(1).translate(FW_MAP)}){m.group(2)}",
            raw,
        )
        pos = 0
        while expected < 4:
            marker = f"({'ABCD'[expected]})"
            idx = line.find(marker, pos)
            if idx == -1:
                break
            if expected == 0 and not (idx == 0 or line[idx - 1] in "？?。；;"):
                break
            emit(line[pos:idx].strip())
            cur = "ABCD"[expected]
            opts[cur] = []
            opt_start_line[cur] = li
            expected += 1
            pos = idx + len(marker)
        emit(line[pos:].strip())

    stem = join_lines(stem_parts).strip().rstrip("；;")
    options = {k: join_lines(v).strip().rstrip("；;").strip() for k, v in opts.items()}
    return stem, options, opt_start_line


def join_lines(parts: list[str]) -> str:
    """合併換行; 英數字跨行相接時補回空格, 避免 "Conditional"+"Random" 黏成一字"""
    out = ""
    for p in parts:
        if out and re.match(r"[A-Za-z0-9]", out[-1]) and re.match(r"[A-Za-z]", p):
            out += " "
        out += p
    return out


def is_cjk(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def join_words(words: list[dict]) -> str:
    parts = []
    for i, w in enumerate(words):
        t = w["text"]
        if i > 0 and parts and not (is_cjk(parts[-1][-1]) or is_cjk(t[0])):
            parts.append(" ")
        parts.append(t)
    return "".join(parts)


def region_has_ink(page, bbox, watermarks: set) -> bool:
    """檢查區域內是否有圖片/線條/矩形/曲線(排除空白、《以下空白》與浮水印)。"""
    x0, y0, x1, y1 = bbox
    try:
        crop_text = page.crop((x0, max(y0, 0), x1, min(y1, page.height))).extract_text() or ""
    except ValueError:
        crop_text = ""
    if "以下空白" in crop_text:
        return False
    for kind in ("images", "curves", "rects", "lines"):
        for obj in getattr(page, kind):
            ox0, oy0, ox1, oy1 = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
            key = (kind, round(ox0), round(oy0), round(ox1), round(oy1))
            if key in watermarks:
                continue
            ix = max(0, min(x1, ox1) - max(x0, ox0))
            iy = max(0, min(y1, oy1) - max(y0, oy0))
            if ix > 5 and iy > 5:
                return True
    return False


def find_watermarks(pdf) -> set:
    """同一 bbox 出現在 3 頁以上的物件視為浮水印/頁面裝飾。"""
    counts: dict[tuple, int] = {}
    for page in pdf.pages:
        for kind in ("images", "curves", "rects", "lines"):
            for obj in getattr(page, kind):
                key = (kind, round(obj["x0"]), round(obj["top"]), round(obj["x1"]), round(obj["bottom"]))
                counts[key] = counts.get(key, 0) + 1
    return {k for k, c in counts.items() if c >= 3}


def parse_file(pdf_path: Path, level: str, session: str, subject: int) -> list[dict]:
    prefix = f"{level}_{session}_s{subject}"
    questions: list[dict] = []
    contexts: list[dict] = []  # {"range": (a,b), "lines": [...], "figures": [...]}

    def new_question(n: int) -> dict:
        q = {"number": n, "lines": [], "line_meta": [], "figures": [], "answer": None, "kind": "q"}
        questions.append(q)
        return q

    with pdfplumber.open(pdf_path) as pdf:
        watermarks = find_watermarks(pdf)
        current: dict | None = None  # question 或 context dict
        for page_idx, page in enumerate(pdf.pages):
            page_start_owner = current
            page_ctxs: list[dict] = []
            words = page.extract_words()
            # 依 top 分行
            lines: list[dict] = []
            for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
                for ln in lines:
                    if abs(ln["top"] - w["top"]) <= LINE_TOL:
                        ln["words"].append(w)
                        if w["bottom"] > ln["bottom"]:
                            ln["bottom"] = w["bottom"]
                        break
                else:
                    lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
            lines.sort(key=lambda ln: ln["top"])

            # 逐行分類
            items = []
            for ln in lines:
                ln_words = sorted(ln["words"], key=lambda w: w["x0"])
                text_all = join_words(ln_words)
                if any(p.search(text_all) for p in HEADER_PATTERNS):
                    continue
                qnum = ans = None
                content = []
                for w in ln_words:
                    t = w["text"].strip()
                    if w["x0"] < ANS_X_MAX and re.fullmatch(r"[A-DＡ-Ｄ]", t):
                        ans = t.translate(FW_MAP)
                    elif w["x0"] < QNUM_X_MAX and re.fullmatch(r"\d{1,2}\.", t):
                        qnum = int(t[:-1])
                    else:
                        content.append(w)
                items.append(
                    {
                        "top": ln["top"],
                        "bottom": ln["bottom"],
                        "qnum": qnum,
                        "ans": ans,
                        "text": join_words(content) if content else "",
                    }
                )

            # 題號連續性檢查 → 真題號列表 (top 順序即編號順序)
            expected = (questions[-1]["number"] + 1) if questions else 1
            qrows = []
            for it in items:
                if it["qnum"] is not None and it["qnum"] == expected:
                    qrows.append(it)
                    expected += 1
                elif it["qnum"] is not None:
                    # 誤判的編號(題幹內清單), 還原成內文
                    it["text"] = f"{it['qnum']}. {it['text']}".strip()
                    it["qnum"] = None

            # 循序處理: lookahead 切換 owner
            ptr = 0
            prev = None  # (bottom, owner)
            for it in items:
                while ptr < len(qrows) and it["top"] >= qrows[ptr]["top"] - 10:
                    current = new_question(qrows[ptr]["qnum"])
                    ptr += 1
                    prev = None  # 跨題不做 gap 偵測(題末 gap 另外處理)
                if it["ans"]:
                    # 答案配對: 找 top 最接近的題號行
                    best = min(qrows, key=lambda q: abs(q["top"] - it["top"]), default=None)
                    if best is not None and abs(best["top"] - it["top"]) < 15:
                        for q in questions:
                            if q["number"] == best["qnum"] and q["answer"] is None:
                                q["answer"] = it["ans"]
                if not it["text"]:
                    continue
                m = CONTEXT_RE.search(it["text"])
                moved_prev_line = None
                if not m and prev is not None and prev[1] is not None and prev[1].get("lines"):
                    # 「請回答」與「第42~43題」被斷行拆開的情況: 併上一行尾端再試
                    merged = prev[1]["lines"][-1][-12:] + it["text"]
                    m2 = CONTEXT_RE.search(merged)
                    if m2 and "回答" in prev[1]["lines"][-1][-12:]:
                        m = m2
                        moved_prev_line = prev[1]["lines"].pop()
                if m:
                    current = {
                        "range": (int(m.group(1)), int(m.group(2))),
                        "lines": ([moved_prev_line] if moved_prev_line else []) + [it["text"]],
                        "line_meta": [(page_idx, it["top"])] * (2 if moved_prev_line else 1),
                        "figures": [],
                        "kind": "ctx",
                        "_start_top": it["top"],
                    }
                    contexts.append(current)
                    page_ctxs.append(current)
                    prev = (it["bottom"], current)
                    continue
                if current is None:
                    continue
                # gap 偵測(同 owner、同頁)
                if prev is not None and prev[1] is current and it["top"] - prev[0] > GAP_THRESHOLD:
                    bbox = (105, prev[0] + 2, page.width - 50, it["top"] - 2)
                    if region_has_ink(page, bbox, watermarks):
                        current["figures"].append(
                            {"page": page, "page_idx": page_idx, "bbox": bbox, "anchor": len(current["lines"])}
                        )
                current["lines"].append(it["text"])
                current["line_meta"].append((page_idx, it["top"]))
                prev = (it["bottom"], current)

            # 題末圖: 每個本頁題號行之前的空隙(上一 owner 的結尾)
            for qr in qrows:
                prior = [it for it in items if it["text"] and it["bottom"] < qr["top"] - 10]
                if not prior:
                    continue
                last = max(prior, key=lambda it: it["bottom"])
                if qr["top"] - last["bottom"] > GAP_THRESHOLD:
                    bbox = (105, last["bottom"] + 2, page.width - 50, qr["top"] - 4)
                    if region_has_ink(page, bbox, watermarks):
                        target = None
                        for q in questions:
                            if q["number"] == qr["qnum"] - 1:
                                target = q
                        for c in contexts:
                            if c["range"][0] == qr["qnum"]:
                                target = c  # 情境段與下一題間的圖 → 情境圖
                        if target is not None:
                            target["figures"].append(
                                {"page": page, "bbox": bbox, "anchor": len(target["lines"])}
                            )
            # 頁尾圖: 最後一行到頁尾的空隙
            if items:
                last = max((it for it in items if it["text"]), key=lambda it: it["bottom"], default=None)
                if last is not None and current is not None:
                    footer_top = page.height - 45
                    if footer_top - last["bottom"] > GAP_THRESHOLD:
                        bbox = (105, last["bottom"] + 2, page.width - 50, footer_top)
                        if region_has_ink(page, bbox, watermarks):
                            current["figures"].append(
                                {"page": page, "page_idx": page_idx, "bbox": bbox, "anchor": len(current["lines"])}
                            )

            # 補抓: 直接掃描本頁 raster 圖(gap 偵測會漏掉被文字標籤隔開的連續圖)
            def q_by_number(n):
                for q in questions:
                    if q["number"] == n:
                        return q
                return None

            for im in page.images:
                key = ("images", round(im["x0"]), round(im["top"]), round(im["x1"]), round(im["bottom"]))
                if key in watermarks:
                    continue
                if im["x1"] - im["x0"] < 25 or im["bottom"] - im["top"] < 25:
                    continue
                # 已被 gap 偵測的區域涵蓋就跳過
                covered = False
                for obj in questions + contexts:
                    for fig in obj["figures"]:
                        if fig["page"] is not page:
                            continue
                        fx0, fy0, fx1, fy1 = fig["bbox"]
                        ix = max(0, min(fx1, im["x1"]) - max(fx0, im["x0"]))
                        iy = max(0, min(fy1, im["bottom"]) - max(fy0, im["top"]))
                        if ix * iy > 0.5 * (im["x1"] - im["x0"]) * (im["bottom"] - im["top"]):
                            covered = True
                if covered:
                    continue
                # 歸屬: 本頁圖上緣以上最近的題號/情境起點, 否則頁首時的 owner
                owner = page_start_owner
                best_top = float("-inf")
                for qr in qrows:
                    if im["top"] >= qr["top"] - 10 and qr["top"] > best_top:
                        owner = q_by_number(qr["qnum"])
                        best_top = qr["top"]
                for c in page_ctxs:
                    if im["top"] >= c["_start_top"] - 10 and c["_start_top"] > best_top:
                        owner = c
                        best_top = c["_start_top"]
                if owner is None:
                    continue
                anchor = sum(
                    1
                    for (pi, t) in owner.get("line_meta", [])
                    if pi < page_idx or (pi == page_idx and t < im["top"])
                )
                owner["figures"].append(
                    {
                        "page": page,
                        "page_idx": page_idx,
                        "bbox": (im["x0"] - 3, im["top"] - 3, im["x1"] + 3, im["bottom"] + 3),
                        "anchor": anchor,
                    }
                )

        # ===== 組裝輸出 =====
        IMG_DIR.mkdir(parents=True, exist_ok=True)

        def save_figures(obj, qid: str) -> list[dict]:
            figs = []
            obj["figures"].sort(key=lambda f: (f.get("page_idx", 0), f["bbox"][1]))
            for i, fig in enumerate(obj["figures"]):
                page = fig["page"]
                x0, y0, x1, y1 = fig["bbox"]
                y0, y1 = max(y0, 0), min(y1, page.height)
                if y1 - y0 < 25:
                    continue
                img_name = f"{qid}_fig{i + 1}.png"
                page.crop((x0, y0, x1, y1)).to_image(resolution=150).save(IMG_DIR / img_name)
                figs.append({"src": f"images/{img_name}", "anchor": fig["anchor"]})
            return figs

        ctx_for: dict[int, dict] = {}
        for ci, c in enumerate(contexts):
            figs = save_figures(c, f"{prefix}_ctx{ci + 1}")
            entry = {"text": "\n".join(c["lines"]), "figures": [f["src"] for f in figs]}
            for n in range(c["range"][0], c["range"][1] + 1):
                ctx_for[n] = entry

        result = []
        for q in questions:
            qid = f"{prefix}_q{q['number']:02d}"
            figs = save_figures(q, qid)

            norm_lines = [
                re.sub(r"（([A-DＡ-Ｄ])）", lambda m: f"({m.group(1).translate(FW_MAP)})", t)
                for t in q["lines"]
            ]
            stem, options, opt_start_line = split_options(norm_lines)

            # 圖位置: anchor = 圖後面那一行的索引
            figures = []
            for f in figs:
                started = [k for k, li in opt_start_line.items() if li < f["anchor"]]
                if f["anchor"] >= len(q["lines"]) and len(started) == 4:
                    # 選項 D 本身是圖(無文字)時, 題末圖其實是 D 的圖
                    pos = "option:D" if not options.get("D", "").strip() else "end"
                elif started:
                    pos = f"option:{max(started)}"
                else:
                    pos = "stem"
                figures.append({"src": f["src"], "position": pos})

            result.append(
                {
                    "id": qid,
                    "level": level,
                    "session": session,
                    "subject": subject,
                    "subject_name": SUBJECT_NAMES[(level, subject)],
                    "number": q["number"],
                    "context": ctx_for.get(q["number"]),
                    "stem": stem.replace("\n", ""),
                    "options": options,
                    "answer": q["answer"],
                    "figures": figures,
                    "explanation": None,
                }
            )
        return result


def apply_patches(all_q: dict) -> None:
    patch_file = OUT_DIR / "patches.json"
    if not patch_file.exists():
        return
    patches = json.loads(patch_file.read_text(encoding="utf-8"))
    by_id = {q["id"]: q for qs in all_q.values() for q in qs}
    for p in patches:
        q = by_id.get(p["id"])
        if q is None:
            print(f"patch 找不到 {p['id']}")
            continue
        for path, value in p.get("set", {}).items():
            keys = path.split(".")
            obj = q
            for k in keys[:-1]:
                obj = obj[k]
            obj[keys[-1]] = value
        for path, value in p.get("prepend", {}).items():
            keys = path.split(".")
            obj = q
            for k in keys[:-1]:
                obj = obj[k]
            obj[keys[-1]] = value + obj[keys[-1]]
        print(f"patch 套用 {p['id']}: {list(p.get('set', {})) + list(p.get('prepend', {}))}")


def main() -> None:
    all_q = {"junior": [], "middle": []}
    issues = []
    for f in sorted(RAW_DIR.glob("*.pdf")):
        m = re.match(r"(junior|middle)_(\d+-\d+)_subj(\d)\.pdf", f.name)
        if not m:
            continue
        level, session, subject = m.group(1), m.group(2), int(m.group(3))
        qs = parse_file(f, level, session, subject)
        all_q[level].extend(qs)
        nums = [q["number"] for q in qs]
        if sorted(nums) != list(range(1, 51)):
            issues.append(f"{f.name}: 題號異常 count={len(nums)}")
        for q in qs:
            opt_figs = {fg["position"].split(":")[1] for fg in q["figures"] if fg["position"].startswith("option:")}
            if q["answer"] not in ("A", "B", "C", "D"):
                issues.append(f"{q['id']}: 缺答案 ({q['answer']})")
            if set(q["options"].keys()) != {"A", "B", "C", "D"}:
                issues.append(f"{q['id']}: 選項切分失敗 keys={sorted(q['options'].keys())}")
            else:
                for k, v in q["options"].items():
                    if not v and k not in opt_figs:
                        issues.append(f"{q['id']}: 選項{k}空白且無圖")
            if len(q["stem"]) < 8 and not q["figures"] and not q["context"]:
                issues.append(f"{q['id']}: 題幹過短 '{q['stem'][:30]}'")
        n_fig = sum(len(q["figures"]) for q in qs)
        n_ctx = len({id(q["context"]) for q in qs if q["context"]})
        print(f"{f.name}: {len(qs)} 題, 圖 {n_fig} 張, 情境 {n_ctx} 組")

    apply_patches(all_q)

    for level, qs in all_q.items():
        out = OUT_DIR / f"questions-{level}.json"
        out.write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"寫入 {out.name}: {len(qs)} 題")

    if issues:
        print(f"\n===== 異常 {len(issues)} 筆 =====")
        for i in issues:
            print(" ", i)
    else:
        print("\n全部通過驗證")


if __name__ == "__main__":
    main()

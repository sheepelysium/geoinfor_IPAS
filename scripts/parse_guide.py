# /// script
# dependencies = ["pdfplumber"]
# ///
"""解析 iPAS 學習指引 PDF 中的章末範例題(含官方答案與解析)。

版面:
- 題目區(章末): "N. 題幹" + "（A）…（D）" 全形括號, 無答案
- 解答區(緊接題目區): "N. Ans（X） 正解文字" + "解析：…" (可能含逐選項說明)
- 題號每章重置為 1, 以此切分章節區塊; 題目區與解答區依文件順序配對
"""

import json
import re
import unicodedata
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data"

GUIDES = {
    "guide_junior_subj1.pdf": ("junior", 1, "人工智慧基礎概論"),
    "guide_junior_subj2.pdf": ("junior", 2, "生成式AI應用與規劃"),
    "guide_middle_subj1.pdf": ("middle", 1, "人工智慧技術應用與規劃"),
    "guide_middle_subj2.pdf": ("middle", 2, "大數據處理分析與應用"),
    "guide_middle_subj3.pdf": ("middle", 3, "機器學習技術與應用"),
}

FW = str.maketrans("ＡＢＣＤ", "ABCD")
OPT_RE = re.compile(r"[（(]\s*([A-DＡ-Ｄ])\s*[)）]")
QNUM_RE = re.compile(r"^(\d{1,2})[.、]\s*(.*)$")
ANS_RE = re.compile(r"^(\d{1,2})[.、]\s*Ans\s*[（(]\s*([A-DＡ-Ｄ])\s*[)）]\s*(.*)$")
PAGE_FOOT_RE = re.compile(r"^\s*\d+-\d+\s*$")
# 頁首前常有 \uf0xx 私用區字元(Wingdings 裝飾符), 需一併容許
CHAP_HEAD_RE = re.compile(r"^[\s-]*第[一二三四五六七八九十]+章")
PUA_RE = re.compile(r"[-]")


def is_cjk(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def join_lines(parts: list[str]) -> str:
    """接合斷行:中文直接接, 英數之間補空格。"""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and not (is_cjk(out[-1]) or is_cjk(p[0])):
            out += " "
        out += p
    return out


CHAP_NUM_RE = re.compile(r"第([一二三四五六七八九十]+)章")
END_MARK_RE = re.compile(r"^(參考書目|參考文獻|附錄|索引|附件)")
# 書目/附錄可能與解析同一行(如「…確保風險管理的持續有效性。附件 本學習指引參考書目…」)
TAIL_CUT_RE = re.compile(r"附件\s*本學習指引參考書目.*$|本學習指引參考書目.*$")


def doc_lines(pdf) -> list[tuple[str, str]]:
    """回傳 (章節代號, 內文行);頁首章名與頁碼會被濾掉但用來標記章節。

    章節代號用於判斷「解析累積到哪裡該停」——章節一換就結束,
    否則章末最後一題的解析會一路吃進下一章的內文。
    """
    lines: list[tuple[str, str]] = []
    chap = "?"
    for page in pdf.pages:
        for ln in (page.extract_text() or "").split("\n"):
            s = ln.rstrip()
            if not s.strip():
                continue
            m = CHAP_HEAD_RE.match(s)
            if m:
                num = CHAP_NUM_RE.search(s)
                if num:
                    chap = num.group(1)
                continue
            if PAGE_FOOT_RE.match(s):
                continue
            s = PUA_RE.sub("", s).strip()   # 清掉內文中的裝飾符
            if not s:
                continue
            if END_MARK_RE.match(s):
                chap = "END"
            lines.append((chap, s))
    return lines


def parse_questions(lines: list[tuple[str, str]]) -> list[dict]:
    """抓出所有「N. 題幹 + （A）(B)(C)(D)」的題目, 依出現順序。"""
    items = []
    cur = None
    cur_chap = None
    for chap, raw in lines:
        s = raw.strip()
        if cur is not None and chap != cur_chap:
            if len(cur["opts"]) == 4:
                items.append(cur)
            cur = None
        if cur is None:
            cur_chap = chap
        if "Ans" in s and ANS_RE.match(s):
            # 進入解答區:先收下最後一題再停止
            if cur and len(cur["opts"]) == 4:
                items.append(cur)
            cur = None
            continue
        m = QNUM_RE.match(s)
        opt = OPT_RE.match(s)
        if m and not opt:
            if cur and len(cur["opts"]) == 4:
                items.append(cur)
            cur = {"n": int(m.group(1)), "stem": [m.group(2)], "opts": {}, "curopt": None}
            cur_chap = chap
            continue
        if cur is None:
            continue
        if opt:
            key = opt.group(1).translate(FW)
            cur["curopt"] = key
            cur["opts"][key] = [s[opt.end():].strip()]
        elif cur["curopt"]:
            cur["opts"][cur["curopt"]].append(s)
        else:
            cur["stem"].append(s)
    if cur and len(cur["opts"]) == 4:
        items.append(cur)

    out = []
    for it in items:
        if set(it["opts"]) != {"A", "B", "C", "D"}:
            continue
        out.append({
            "n": it["n"],
            "stem": join_lines(it["stem"]),
            "options": {k: join_lines(v) for k, v in it["opts"].items()},
        })
    return out


def parse_answers(lines: list[tuple[str, str]]) -> list[dict]:
    """抓出所有「N. Ans（X） 正解文字」+ 後續解析文字。

    章節一換就結束當前解析,避免章末最後一題吃進下一章內文。
    """
    items = []
    cur = None
    cur_chap = None
    for chap, raw in lines:
        s = raw.strip()
        if cur is not None and chap != cur_chap:
            items.append(cur)
            cur = None
        m = ANS_RE.match(s)
        if m:
            if cur:
                items.append(cur)
            cur = {"n": int(m.group(1)), "answer": m.group(2).translate(FW),
                   "answer_text": m.group(3).strip(), "expl": []}
            cur_chap = chap
            continue
        if cur is None:
            continue
        # 遇到新題目(非解答)就結束這一區
        if QNUM_RE.match(s) and not OPT_RE.match(s):
            items.append(cur)
            cur = None
            continue
        cur["expl"].append(s)
    if cur:
        items.append(cur)

    for it in items:
        text = join_lines(it["expl"])
        text = re.sub(r"^解析\s*[：:]\s*", "", text)
        text = TAIL_CUT_RE.sub("", text).strip()   # 切掉尾端誤黏的參考書目
        it["explanation"] = text
        del it["expl"]
    return items


def split_blocks(items: list[dict]) -> list[list[dict]]:
    """題號重置為 1 → 切成一個章節區塊。"""
    blocks, cur = [], []
    for it in items:
        if cur and it["n"] <= cur[-1]["n"]:
            blocks.append(cur)
            cur = []
        cur.append(it)
    if cur:
        blocks.append(cur)
    return blocks


def main() -> None:
    result = {"junior": [], "middle": []}
    issues = []

    for fname, (level, subject, subject_name) in GUIDES.items():
        path = RAW_DIR / fname
        with pdfplumber.open(path) as pdf:
            lines = doc_lines(pdf)

        qs = parse_questions(lines)
        ans = parse_answers(lines)
        qblocks, ablocks = split_blocks(qs), split_blocks(ans)

        if len(qblocks) != len(ablocks):
            issues.append(f"{fname}: 題目區 {len(qblocks)} 塊 vs 解答區 {len(ablocks)} 塊, 數量不符")

        paired = 0
        for bi, (qb, ab) in enumerate(zip(qblocks, ablocks), 1):
            amap = {a["n"]: a for a in ab}
            for q in qb:
                a = amap.get(q["n"])
                if a is None:
                    issues.append(f"{fname} 第{bi}區塊 第{q['n']}題: 找不到答案")
                    continue
                qid = f"guide_{level}_s{subject}_c{bi}_q{q['n']:02d}"
                result[level].append({
                    "id": qid,
                    "level": level,
                    "session": "學習指引",
                    "subject": subject,
                    "subject_name": subject_name,
                    "number": q["n"],
                    "context": None,
                    "stem": q["stem"],
                    "options": q["options"],
                    "answer": a["answer"],
                    "figures": [],
                    "explanation": {
                        "approach": a["explanation"],
                        "options": {},
                        "source": "official",
                    },
                })
                paired += 1
        print(f"{fname}: 題目 {len(qs)} / 解答 {len(ans)} / 配對成功 {paired} ({len(qblocks)} 個章節區塊)")

    # 套用官方勘誤表修正
    patch_file = OUT_DIR / "guide-patches.json"
    if patch_file.exists():
        by_id = {q["id"]: q for qs in result.values() for q in qs}
        for p in json.loads(patch_file.read_text(encoding="utf-8")):
            q = by_id.get(p["id"])
            if q is None:
                issues.append(f"勘誤找不到題目 {p['id']}")
                continue
            for path, value in p["set"].items():
                keys = path.split(".")
                obj = q
                for k in keys[:-1]:
                    obj = obj[k]
                obj[keys[-1]] = value
            print(f"套用勘誤 {p['id']}: {list(p['set'])}")

    # 驗證
    for level, qs in result.items():
        for q in qs:
            if q["answer"] not in "ABCD":
                issues.append(f"{q['id']}: 答案異常")
            if len(q["stem"]) < 6:
                issues.append(f"{q['id']}: 題幹過短")
            if any(not v for v in q["options"].values()):
                issues.append(f"{q['id']}: 有空選項")
            if len(q["explanation"]["approach"]) < 10:
                issues.append(f"{q['id']}: 解析過短")
        out = OUT_DIR / f"guide-{level}.json"
        out.write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"寫入 {out.name}: {len(qs)} 題")

    if issues:
        print(f"\n===== 異常 {len(issues)} 筆 =====")
        for i in issues[:40]:
            print(" ", i)
    else:
        print("\n全部通過驗證")


if __name__ == "__main__":
    main()

# /// script
# dependencies = ["httpx"]
# ///
"""下載 iPAS AI應用規劃師歷屆考題 PDF 到 data/raw/。"""

from pathlib import Path

import httpx

BASE = "https://www.ipas.org.tw/api/proxy/uploads/certification_resource/bf93f438f7be48d295c1b40a34d79f3d/"

# (存檔名, 原始檔名)
FILES = [
    ("junior_114-4_subj1.pdf", "114年第四梯次初級AI應用規劃師第一科人工智慧基礎概論(當次試題公告114_20251226000442.pdf"),
    ("junior_114-4_subj2.pdf", "114年第四梯次初級AI應用規劃師第二科生成式AI應用與規劃(當次試題公告114_20251226000507.pdf"),
    ("junior_115-1_subj1.pdf", "115年第一次初級AI應用規劃師_第一科_人工智慧基礎概論_公告試題_20260410164304.pdf"),
    ("junior_115-1_subj2.pdf", "115年第一次初級AI應用規劃師_第二科_生成式AI應用與規劃_公告試題_20260410164328.pdf"),
    ("junior_115-2_subj1.pdf", "115年第二次初級AI應用規劃師_第一科_人工智慧基礎概論_公告試題_20260604212644.pdf"),
    ("junior_115-2_subj2.pdf", "115年第二次初級AI應用規劃師_第二科_生成式AI應用與規劃_公告試題_20260604212719.pdf"),
    ("middle_114-2_subj1.pdf", "114年第二梯次中級AI應用規劃師第一科人工智慧技術應用與規劃(當次試題公告114_20251226000616.pdf"),
    ("middle_114-2_subj2.pdf", "114年第二梯次中級AI應用規劃師第二科大數據處理分析與應用(當次試題公告114_20251226000634.pdf"),
    ("middle_114-2_subj3.pdf", "114年第二梯次中級AI應用規劃師第三科機器學習技術與應用(當次試題公告114_20251226000650.pdf"),
    ("middle_115-1_subj1.pdf", "115年第一次中級AI應用規劃師_第一科_人工智慧技術應用與規劃_公告試題_20260615003359.pdf"),
    ("middle_115-1_subj2.pdf", "115年第一次中級AI應用規劃師_第二科_大數據處理分析與應用_公告試題_20260615003417.pdf"),
    ("middle_115-1_subj3.pdf", "115年第一次中級AI應用規劃師_第三科_機器學習技術與應用_公告試題_20260615003428.pdf"),
    # 學習指引(內含官方範例題)
    ("guide_junior_subj1.pdf", "AI應用規劃師(初級)-學習指引-科目1_人工智慧基礎概論1141203_20251222172144.pdf"),
    ("guide_junior_subj2.pdf", "AI應用規劃師(初級)-學習指引-科目2_生成式AI應用與規劃114123_20251222172159.pdf"),
    ("guide_middle_subj1.pdf", "AI應用規劃師(中級)-學習指引-科目1人工智慧技術應用規劃_20251222101833.pdf"),
    ("guide_middle_subj2.pdf", "AI應用規劃師(中級)-學習指引-科目2大數據處理分析與應用_20251222101850.pdf"),
    ("guide_middle_subj3.pdf", "AI應用規劃師(中級)-學習指引-科目3機器學習技術與應用_20251222101907.pdf"),
    # 勘誤表(可能修正學習指引內容)
    ("errata_junior.pdf", "AI應用規劃師(初級)學習指引勘誤表11404_20251222101819.pdf"),
    ("errata_middle.pdf", "AI應用規劃師(中級)_學習指引勘誤表_1150410_20260410150331.pdf"),
]


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for save_name, orig_name in FILES:
            dest = out_dir / save_name
            if dest.exists() and dest.stat().st_size > 0:
                print(f"skip {save_name} (exists, {dest.stat().st_size:,} bytes)")
                continue
            resp = client.get(BASE + orig_name)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if not resp.content.startswith(b"%PDF"):
                print(f"WARN {save_name}: not a PDF (content-type={content_type})")
                continue
            dest.write_bytes(resp.content)
            print(f"ok   {save_name} ({len(resp.content):,} bytes)")


if __name__ == "__main__":
    main()

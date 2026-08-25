# iPAS AI應用規劃師 題庫練習網站

經濟部 iPAS「AI應用規劃師」歷屆試題線上刷題工具。純靜態網站,雙擊 `site/index.html` 即可使用。

## 使用

直接開 [site/index.html](site/index.html):

- 初級 / 中級切換(題庫完全分離)
- 全科混合或單科,每回合隨機抽 20 題
- 選項順序隨機(正解不固定在同一字母)
- 作答後立即顯示 AI 詳解:解題思路 + 每個選項對錯原因
- 錯題回顧、各科累計正確率(存在瀏覽器 localStorage)

## 題庫

| 級別 | 梯次 | 科目 | 題數 |
|---|---|---|---|
| 初級 | 114-4、115-1、115-2 | 人工智慧基礎概論、生成式AI應用與規劃 | 300 |
| 中級 | 114-2、115-1 | 人工智慧技術應用與規劃、大數據處理分析與應用、機器學習技術與應用 | 300 |

來源:[iPAS 官方公告試題](https://ipd.nat.gov.tw/ipas/certification/AIAP/learning-resources)(含官方標準答案)。詳解由 AI(Claude Sonnet)生成,僅供學習參考。

## 部署(Cloudflare Workers 靜態資產)

設定在 [wrangler.jsonc](wrangler.jsonc),只發布 `site/` 目錄。

首次部署(會開瀏覽器登入 Cloudflare):

```
npx wrangler login
npx wrangler deploy
```

之後每次要更新網站,只要再跑一次 `npx wrangler deploy`。

- `site/_headers` 控制快取:題庫與程式碼不快取(改版立即生效),`images/` 長期快取
- 只有 `site/` 會被發布;`data/raw/` 的官方 PDF、`scripts/`、`data/annotate/` 都不會出現在網站上
- 驗證設定但不實際上傳:`npx wrangler deploy --dry-run`

## 資料管線(重建題庫時才需要)

```
uv run scripts/download_pdfs.py     # 下載官方 12 份試題 PDF → data/raw/
uv run scripts/parse_pdf.py         # 解析 PDF → data/questions-*.json + site/images/*.png
uv run scripts/split_batches.py     # 切註解批次檔 → data/annotate/*.json
# (由 AI agent 產出 data/annotate/out/*.json 註解)
uv run scripts/build_site_data.py   # 合併註解+人工修正 → site/data/questions-*.js
uv run scripts/audit.py             # 稽查題庫是否有跨題黏連污染
```

- `data/patches.json`:PDF 解析無法自動處理的**題目內容**人工修正(目前 14 筆,集中在中級的跨題組黏連)
- `data/explanation-fixes.json`:**詳解**人工修正(改寫錯誤說明、補答案疑義與時效註記、清除過期註記),於 `build_site_data.py` 套用在 AI 註解之上,重跑註解 agent 不會被覆蓋
- ⚠ `data/annotate/out/*.json` 是 **AI 原始輸出、未經修正**,可能含已被修正或已過期的內容;正確版本一律以 `build_site_data.py` 產出的 `site/data/questions-*.js` 為準,不要直接引用 `annotate/out`
- 新梯次試題公告後:把新 PDF 的 URL 加進 `download_pdfs.py` 的 `FILES`,重跑整條管線

### 詳解品質須知

詳解由 AI 產生,**官方答案一律為準**。網站上有兩種註記:

- **⚠ 答案疑義**(紅字):官方答案有討論空間、或選項界線模糊的題目,會說明其他選項為何也合理、以及應試時該怎麼判斷。仍依官方答案作答。
- **⏳ 時效提醒**(藍字):法規與 AI 產品功能等時間敏感題,標明「以考試當期版本為準」並指向官方查證管道。這類題目未逐題附來源連結,不宜當作最新事實引用。

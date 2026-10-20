# 新增梯次題庫的完整步驟(2026-10-20,補初級 115-3)

README 的「新梯次試題公告後」只寫了「把新 PDF 的 URL 加進 download_pdfs.py,重跑整條管線」,實際上還有兩處管線不會自動處理:

1. **`site/index.html` 有三處硬編題數**,管線不會更新,漏改會讓頁尾與 SEO meta 顯示舊數字:
   - `<meta name="description">` 的「600 題隨機抽考」
   - `<meta property="og:description">` 的「共 600 題」
   - 頁尾 `題庫來源:...(初級 N 梯次、中級 M 梯次,共 600 題)`
   README 本身也有三處(總題數、歷屆題數、級別表格的梯次與題數)。
2. **`split_batches.py` 會重生 `data/annotate/*.json`**,已 commit 的中級批次檔是 patches.json 套用前的舊版,重跑後會出現「非預期」的 diff。那是**修正**(跨題黏連已清掉),不是回歸,可以照收。

其餘腳本都用 glob 自動發現檔案,只有 `download_pdfs.py` 的 `FILES` 需要手動加。

**查新梯次的方法**:官方頁是 Next.js SSR,PDF 路徑直接在 HTML 裡,不用解 JS:
```
curl -s -L "https://www.ipas.org.tw/certification/AIAP/learning-resources" \
  | grep -o 'api/proxy/uploads/certification_resource/[^"'"'"'\]*\.pdf' | sort -u
```
BASE 加上檔名就是下載網址。注意 `ipd.nat.gov.tw` 與 `www.ipas.org.tw` 互為轉址,WebFetch 抓不到 href(按鈕沒有連結),要用 curl 抓原始 HTML。

**註解 agent 的輸出規格**(README 只說「由 AI agent 產出」,沒寫格式):
`data/annotate/out/<batch>.json` = `{ "<題目id>": { "approach": str, "options": {A,B,C,D}, "note"?: str, "timeliness"?: str } }`,UTF-8 無 BOM。
風格基準(取自既有初級批次):approach 60–200 字、每個選項說明 25–130 字;`note`=答案疑義(紅字)、`timeliness`=時效提醒(藍字),50 題裡各 0–3 題,不要濫用。

**瀏覽器驗證的坑**:app.js 的 `state` 包在 IIFE 內,外部取不到;要檢視特定題目只能改 `window.QUESTION_BANK` 再重開回合,而且**開始回合要求題庫 ≥20 題**(不足會跳 alert),所以要把目標題複製成 20 份。

## 部署(同日補充)

- **wrangler 的 OAuth token 會過期**,過期後 `npx wrangler deploy` 在非互動 shell 會直接要 `CLOUDFLARE_API_TOKEN` 而不自動 refresh。要在真正的終端機(TTY)跑才會走瀏覽器重新登入。
- **排除檔案用 `site/.assetsignore`**(格式同 `.gitignore`),放在 assets 目錄根部。`.assetsignore` 自己也不會被上傳。
- ⚠ `wrangler deploy --dry-run` 印的「Read N files」是**套用 .assetsignore 之前**的數量,加了排除規則數字不會變少,**不能用它驗證排除有沒有生效**。要實際部署後 curl 該路徑確認回 404。

## 詳解字母引用 vs 選項洗牌(2026-10-20 修正)

`startQuiz()` 會對每題的選項洗牌,但詳解是整段純文字輸出,裡面寫死的「(A)」是**原始卷面字母**,不會跟著重新對應,於是和畫面上的選項對不起來。逐選項說明不受影響(用原始 key 帶著走)。

修法:`remapLetters(text, q, order)` 在渲染時依該題洗牌結果改寫,套用在 approach / note / timeliness / errata / options 五處、兩個渲染路徑(`answer()` 與 `renderReview()`)。

⚠ **不能無條件改寫**,879 題裡掃出 19 處括號字母,其中 5 處是假陽性:
- `P(A)`、`P(B)`、`np.linalg.inv(A)`、`Support(A→B)` — 數學/程式寫法
- `程式碼中(A)與(B)` — 指附圖程式碼的填空標記,不是選項

判準(三條都要):
1. 全形`（A）`一律視為選項引用(官方學習指引都用全形)
2. 半形`(A)`只在**前一字不是英數字或底線**時才算(擋掉 `P(`、`inv(`)
3. **題幹若出現半形`([A-D])`**,代表那題的括號字母是程式碼填空標記,整題的半形引用都不動

不要用 lookbehind(Safari 16.4 以前不支援),改成把前一個字元一起捕捉再補回去。

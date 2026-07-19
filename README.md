# SplitMate

開源的台灣 LINE 群組分帳小工具：**在 LINE 記帳，在網頁看結算**。

> 定位：LINE 寫入 → Flask → 資料庫 → Web 讀取（同一套帳本）

---

## 你會得到什麼

- LINE 指令記帳（`#分帳`）、查結算（`#結算` / `#欠款`）、成員補綁 ID（`#合併`）
- 每個群組專屬網頁：最少轉帳結算、勾選多筆相抵、標記已付、刪除帳單（需 PIN）
- 本機 SQLite；部署建議 PostgreSQL（例如 Railway）

---

## 需要準備什麼

| 項目 | 說明 |
|------|------|
| Python 3.11+ | 本機開發 |
| LINE Developers 帳號 | 建立 Messaging API Channel |
| （可選）Railway 或任何能跑 Docker 的主機 | 公開 Webhook 網址 |
| （可選）PostgreSQL | 生產環境建議；本機可先用 SQLite |

---

## 1. Clone 與本機啟動

```bash
git clone https://github.com/yanoazi/SplitMate.git
cd SplitMate

cp .env.example .env
pip install -r requirements.txt
python app.py
```

瀏覽器開啟：

| 網址 | 用途 |
|------|------|
| http://localhost:7777/ | 首頁 |
| http://localhost:7777/demo | Demo 儀表板（PIN 預設 `1234`） |
| http://localhost:7777/health | 健康檢查 |

未填 LINE Token 時會以 **Web-only** 模式啟動（正常，可先玩 Demo）。

本機測試：

```bash
python -m pytest -q
```

### `.env` 重點

複製自 `.env.example`：

```env
PUBLIC_BASE_URL=http://localhost:7777
LINE_CHANNEL_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=
DEMO_MODE=1
DEMO_EDIT_PIN=1234
SECRET_KEY=請改成一串亂數
# DATABASE_URL=   # 不設則用 SQLite ./splitmate.db
```

**不要把 `.env` 提交到 Git。**

---

## 2. 設立 LINE 機器人

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立（或選用）Provider → 建立 **Messaging API** channel
3. 在 **Messaging API** 分頁：
   - 發行 **Channel access token**（long-lived）並複製
   - 在 **Basic settings** 複製 **Channel secret**
4. 貼進本機 `.env`（或之後貼進 Railway Variables）：
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `LINE_CHANNEL_SECRET`
5. 把 Bot 加入你的測試 LINE 群組（用 QR code / 加好友後邀請進群）

此時若只在本機跑、沒有公開網址，Webhook 還無法驗證——需先完成下一節部署。

---

## 3. 部署（以 Railway 為例）

其他平台只要能跑 Docker、提供 HTTPS、注入環境變數即可；以下以 Railway 說明。

### 3.1 推上 GitHub

把本 repo fork／推到你的 GitHub（若還沒有）。

### 3.2 建立 Railway 專案

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub** → 選 `SplitMate`
2. （建議）再 **New** → **Database** → **PostgreSQL**
3. 進入 **web** 服務 → **Variables**，設定：

| 變數 | 範例／說明 |
|------|------------|
| `DATABASE_URL` | 用 **Add Reference** 接到 Postgres（不要手打） |
| `PUBLIC_BASE_URL` | `https://你的網域.up.railway.app`（不要結尾 `/`） |
| `SECRET_KEY` | 長亂數 |
| `DEMO_MODE` | `1`（要公開 Demo 時） |
| `DEMO_EDIT_PIN` | 例如 `1234` |
| `LINE_CHANNEL_ACCESS_TOKEN` | 上一步取得 |
| `LINE_CHANNEL_SECRET` | 上一步取得 |

4. **Settings**：若曾自訂 Start Command，請清空，讓 `Dockerfile` 負責啟動（避免 `$PORT` 沒展開）
5. 等部署變 **Online** 後驗證：
   - `https://你的網域/health` → `"status":"ok"`
   - `https://你的網域/demo` → 儀表板可開

### 3.3 接上 LINE Webhook

1. LINE Developers → 你的 channel → **Messaging API**
2. Webhook URL：

```text
https://你的網域/splitmate/webhook
```

3. **Verify** 成功後，開啟 **Use webhook**
4. 建議關閉「自動回應訊息／問候訊息」（避免蓋過 Bot）
5. 在測試群打 `#幫助`；有回覆即表示通路正常

### 3.4 建議的第一次驗收

1. 付款人在群裡：`#分帳 300 午餐 @成員A @成員B`（用鍵盤 @ 點選）
2. 點 Bot 回覆的網頁連結，確認同一筆出現
3. 打 `#網頁` 取得 PIN，在網頁試標記已付／勾選結算

---

## 4. LINE 指令（精簡版）

完整說明以群組內 `#幫助` 為準。

| 指令 | 用途 |
|------|------|
| `#分帳 …` | **付款人**記一筆 |
| `#結算` | 全部未付 → 最少轉帳結果 |
| `#欠款` | 未付欠款摘要 |
| `#成員` | 🔗 已綁 ID／❓ 僅名字 |
| `#合併 舊名 @點選` | 把僅名字的舊帳綁到 LINE ID |
| `#網頁` | 專屬連結 + 編輯 PIN |
| `#幫助` | 指令一覽 |

標記已付、刪除帳單、勾選多筆相抵 → 在網頁操作（需 PIN）。

---

## 5. 專案結構（簡表）

```text
app.py                 # 入口（gunicorn "app:app"）
models.py              # SQLAlchemy 模型
splitmate/
  line/bot.py          # LINE Webhook 與指令
  services/            # 分攤、結算、成員合併等
  api/v1.py            # REST API
  web/routes.py        # 網頁路由
templates/ static/     # 前端
Dockerfile             # 容器部署
docker-compose.yml     # 本機 Postgres + Web（可選）
railway.toml           # Railway 設定
.env.example           # 環境變數範本
tests/                 # pytest
```

---

## 6. Docker 本機（可選）

若要本機也用 Postgres：

```bash
docker compose up --build
```

預設：http://localhost:7777 （見 `docker-compose.yml`）

---

## 授權

MIT — 歡迎 fork、改、自用。若你願意開 issue／PR 也很歡迎，但此專案以個人 side project 維護，不保證商業等級 SLA。

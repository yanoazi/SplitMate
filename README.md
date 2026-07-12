# SplitMate v0.1.0

在 **LINE 記帳**，在 **網頁看清楚誰欠誰**。

## 命名說明

| 名稱 | 意思 | 白話 |
|------|------|------|
| **SplitMate** | 產品名稱 | 整個專案叫這個 |
| **ExpenseGroup** | 程式裡的「記帳群組」資料表 | 一個 LINE 群對應一筆 |
| **GroupMember** | 群組成員 | 一個人（有名字，最好有 LINE ID） |
| **Bill** | 一筆支出 | 例如「火鍋 900」 |
| `sm_*` | 資料表前綴 | SplitMate 的縮寫 |

## 本機啟動

```bash
cp .env.example .env
pip install -r requirements.txt
python app.py
```

- 首頁：http://localhost:7777/
- Demo：http://localhost:7777/demo
- Health：http://localhost:7777/health

Demo 編輯 PIN 預設：`1234`

未設定 LINE Token 時為 Web-only 模式（正常）。

## 成員怎麼辨識？（LINE userId）

1. **付款人**：在群裡發指令時，LINE 會告訴我們他的 `userId`，自動綁定。
2. **被分帳的人**：請用手機鍵盤的 **「@」點選成員**（不要手動打字 `@小美`）。
   - 點選 → Webhook 會帶真實 `userId` → 資料庫寫入 `line_user_id`
   - 手動打字 → 通常只有名字字串，改名就可能對不到
3. 指令：
   - `#我的ID`：看自己的 userId
   - `#成員`：看誰已綁定（🔗）／誰只有名字（❓）

不一定要均分：分別計算與代墊本來就支援「每人不同金額」。

## LINE Webhook

部署後設為：

```text
https://你的網域/splitmate/webhook
```

## 環境變數

見 `.env.example`。本機預設 SQLite；生產環境建議 PostgreSQL（`DATABASE_URL`）。

部署到 Railway 時，請設定 `PUBLIC_BASE_URL`（你的公開網域，不要結尾斜線）、`SECRET_KEY`，並可選填入 LINE Token／Secret。

## API

| Method | Path |
|--------|------|
| GET | `/health` |
| GET | `/api/v1/demo` |
| GET | `/api/v1/groups/<token>/summary` |
| GET | `/api/v1/groups/<token>/bills` |
| GET | `/api/v1/groups/<token>/settlement` |
| GET | `/api/v1/groups/<token>/members` |
| POST | `/api/v1/groups/<token>/bills/<id>/settle` |

## 測試

```bash
python -m pytest -q
```

## License

MIT

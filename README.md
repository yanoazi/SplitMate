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
真實 LINE 群 PIN：在群裡打 `#網頁` 取得。

未設定 LINE Token 時為 Web-only 模式（正常）。

## LINE 指令

在群組打 `#幫助` 可看完整說明。

| 指令 | 用途 |
|------|------|
| `#分帳 300 午餐 @小美 @小王` | **由付款人**記一筆（均攤） |
| `#分帳 1000 聚餐 @小美 400 @小王 350` | 分別金額／代墊 |
| `#群組結算` | 全部未付帳正負相抵 |
| `#群組欠款` / `#群組帳單`（或 `#完整帳單`） | 摘要／列表 |
| `#結帳 B-1 @小美` | LINE 內標記已付（**僅該筆付款人**可執行） |
| `#支出詳情 B-1` | 單筆明細 |
| `#網頁` | 儀表板連結 **＋ 編輯 PIN** |
| `#成員` | 🔗已綁定／❓僅名字 |
| `#合併 小美 @點選本人` | 把 ❓僅名字 的舊帳轉到 LINE ID |
| `#選單` / `#建立帳單` | 快捷／範例 |

### 必須由付款人記帳

誰先墊錢，就由**付款人本人**在群裡打 `#分帳`。系統會把發言者當付款人並綁定其 LINE ID。

### `#合併` 怎麼用？

1. 當初記帳時若沒綁到 ID，`#成員` 會出現 `❓小美`
2. 小美進群後輸入：`#合併 小美` + 鍵盤 **@點選**小美  
3. 舊帳轉到她的 LINE ID，變成 `🔗`

「舊名字」必須與 `#成員` 裡 ❓ 的名字完全相同；@ 一定要用鍵盤點選。

### 網頁能做什麼

- 看全部未付淨欠款
- **勾選多筆帳單** → 計算相抵 →（可選）全部標記已付
- **刪除帳單**（需 PIN）
- 單人標記已付（需 PIN）

PIN 來源：`#網頁`（Demo 為 `1234`）。

## LINE Webhook

```text
https://你的網域/splitmate/webhook
```

## 環境變數

見 `.env.example`。本機預設 SQLite；生產環境建議 PostgreSQL（`DATABASE_URL`）。

## API

| Method | Path |
|--------|------|
| GET | `/health` |
| GET | `/api/v1/groups/<token>/summary` |
| GET | `/api/v1/groups/<token>/bills` |
| GET | `/api/v1/groups/<token>/settlement` |
| POST | `/api/v1/groups/<token>/settlement/batch` |
| POST | `/api/v1/groups/<token>/bills/<id>/settle` |
| POST | `/api/v1/groups/<token>/bills/settle-batch` |
| DELETE | `/api/v1/groups/<token>/bills/<id>` |

## 測試

```bash
python -m pytest -q
```

## License

MIT

# SplitMate v0.1.0

在 **LINE 記帳**，在 **網頁看清楚誰欠誰**。

## 本機啟動

```bash
cp .env.example .env
pip install -r requirements.txt
python app.py
```

- 首頁：http://localhost:7777/
- Demo：http://localhost:7777/demo（PIN：`1234`）
- Health：http://localhost:7777/health

## LINE 指令

群組打 `#幫助` 看完整說明。目前僅保留：

| 指令 | 用途 |
|------|------|
| `#分帳 …` | **付款人**記一筆 |
| `#結算` | 全部未付 → **最少轉帳**結果 |
| `#欠款` | 未付欠款摘要 |
| `#成員` | 🔗 已綁 ID／❓ 僅名字 |
| `#合併 舊名 @點選` | 補綁 LINE ID |
| `#網頁` | 專屬連結 + PIN |
| `#幫助` | 指令一覽 |

標記已付、刪除帳單、勾選多筆相抵 → 請在網頁操作（需 PIN）。

## 結算演算法

`#結算` 與網頁「最少轉帳結算」使用淨額貪婪配對，把交叉欠款壓成最少轉帳筆數。

## Webhook

```text
https://你的網域/splitmate/webhook
```

## 測試

```bash
python -m pytest -q
```

## License

MIT

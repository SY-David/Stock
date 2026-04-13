# tw_stock_assistant

這個工具現在只走線上官方資料，不再依賴本地假資料或 FinMind token。

目前版本做的事很單純：
- 固定追蹤你長期在看的股票
- 每天從候選池挑出 1 到 3 檔推薦
- 用價格、均線、量能加上 CPU 友善的 `Logistic Regression` 做輔助評分
- 額外整理 `超跌反彈觀察` 和 `超漲轉弱觀察` 兩個特殊榜單
- 新增夜間事件層，整理今晚到明早的新聞與風險
- 新增模擬帳戶，從 5 萬本金開始每天小額投入推薦股並結算
- 輸出 CLI 日報與 Streamlit GUI

## 安裝

```powershell
python -m pip install -r requirements.txt
```

## 設定

在專案根目錄建立 `.env`，內容可參考：

```env
WATCHLIST=0050,2344
DAILY_CANDIDATE_POOL=2330,2317,2454,2382,2308,3231,2603,2881
GENERATE_LLM_PROMPT=true
LOOKBACK_DAYS=480
ML_LOOKBACK_DAYS=960
ML_PREDICTION_HORIZON_DAYS=5
RECOMMENDATION_TOP_N=3
RECOMMENDATION_MIN_SCORE=65
HISTORY_LIMIT=30
PAPER_INITIAL_CASH=50000
PAPER_DAILY_BUDGET=5000
PAPER_MAX_NEW_BUYS_PER_DAY=2
PAPER_MAX_HOLD_DAYS=5
PAPER_ALLOW_FRACTIONAL=true
REQUEST_TIMEOUT=20
ALLOW_INSECURE_TWSE_SSL_FALLBACK=true
ENABLE_NIGHTLY_CONTEXT=true
NIGHTLY_REQUEST_TIMEOUT=12
NIGHTLY_NEWS_LIMIT=4
```

## CLI 用法

直接跑預設清單：

```powershell
python main.py
```

更新網站快照：

```powershell
python refresh_snapshot.py
```

臨時改固定追蹤：

```powershell
python main.py --watchlist 0050 2344
```

臨時改每日候選池：

```powershell
python main.py --candidate-pool 2330 2317 2454 2382
```

只輸出日報，不產生 LLM prompt：

```powershell
python main.py --no-prompt
```

輸出結果會在 `output/`：
- `daily_report_YYYY-MM-DD.md`
- `chatgpt_input_YYYY-MM-DD.txt`

## GUI 用法

```powershell
python -m streamlit run app.py
```

GUI 會顯示：
- 明日推薦
- 今晚到明早總覽
- 候選池前段班 / 偏弱股
- 超跌反彈觀察 / 超漲轉弱觀察
- 夜間消息偏多 / 夜間消息偏空
- 模擬帳戶與交易紀錄
- 歷史紀錄
- 固定追蹤明細
- 候選池明細
- 中學生版欄位說明
- 日報與 prompt 匯出

網站若找到 `data/site_snapshot.json`，會優先讀取快照；沒有快照時才會即時抓資料。
若排程更新失敗，會沿用上一版快照並在頁面上顯示 fallback 提示。
若雲端環境對 TWSE 歷史月資料出現 SSL 驗證不相容，程式會對該公開端點自動退回不驗證重試；可用 `ALLOW_INSECURE_TWSE_SSL_FALLBACK=false` 關掉。

## 模擬帳戶規則

目前預設規則：
- 本金 `50,000`
- 每天最多投入 `5,000`
- 最多買進 `2` 檔當日推薦
- 用隔天開盤價成交
- 持有滿 `5` 個交易日或轉紅燈時，下一個交易日開盤賣出
- 預設允許零股模擬

模擬帳戶是用 `data/history/site_snapshot_*.json` 加上目前的 `data/site_snapshot.json` 回放，不會真的下單。

## 分享給朋友看

如果你不想用 GitHub，最簡單的方式是：

1. 先啟動 Streamlit

```powershell
python -m streamlit run app.py
```

2. 再開第二個終端，啟動 Cloudflare Quick Tunnel

```powershell
cloudflared tunnel --url http://localhost:8501
```

它會給你一個 `https://xxxx.trycloudflare.com`，把那個網址丟給朋友即可。

注意：
- 你的電腦要開著
- `streamlit` 和 `cloudflared` 那兩個終端都不能關
- 這是臨時網址，重開 tunnel 會換

## 長期部署

如果你想讓網站長期活著，建議用 Linux 主機或 VPS 跑 Docker。

啟動網站：

```powershell
docker compose up -d web
```

手動更新一次網站快照：

```powershell
docker compose run --rm refresh
```

你可以把 [deploy/cron.example](/c:/Users/USER/Desktop/tw_stock_assistant/deploy/cron.example) 放進 Linux `crontab`，讓它在每個交易日 15:10 自動更新快照。

如果你有自己的網域，可以配 Caddy 反向代理，範例在 [deploy/Caddyfile.example](/c:/Users/USER/Desktop/tw_stock_assistant/deploy/Caddyfile.example)。

## GitHub 最簡單方案

如果你願意用 GitHub，最省事的做法是：

1. 把這個專案推到 GitHub repo
2. 到 Streamlit Community Cloud 建立 app，主檔選 `app.py`
3. 保持 repo 裡有 `data/site_snapshot.json`
4. 啟用 repo 內建的 GitHub Actions

這個 repo 已經附好排程工作流：
- [refresh_snapshot.yml](/c:/Users/USER/Desktop/tw_stock_assistant/.github/workflows/refresh_snapshot.yml)

它會在台北時間每個交易日約 `15:18` 自動更新 `data/site_snapshot.json`，並把變更 commit 回 GitHub。  
同時也會保存 `data/history/` 與 `data/update_status.json`，讓歷史紀錄與模擬帳戶可以持續往前滾。  
Streamlit Community Cloud 看到 repo 更新後，就會自動重新部署，網站內容也會跟著更新。

第一次上 GitHub 之前，你至少要確保：
- `data/site_snapshot.json` 已存在
- `data/cache/` 不要上傳
- `.env` 不要上傳

手動先更新一次快照：

```powershell
python refresh_snapshot.py --no-prompt
```

## 資料來源

目前主資料來源是：
- TWSE `STOCK_DAY_ALL`
- TWSE `STOCK_DAY`

所以這版最穩的是上市股票與 ETF。若之後你要大量支援上櫃股，可以再補 TPEX 歷史接口。

## 限制

- 目前推薦主要依賴價格、均線、量能與 ML 歷史特徵
- 法人、估值、月營收在這版沒有額外接入
- 夜間事件層目前以公開新聞標題規則判讀為主，不是完整 NLP
- ML 是 CPU 友善小模型，不是大型深度學習
- 這是研究輔助工具，不是交易保證
